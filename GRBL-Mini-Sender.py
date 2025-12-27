import json
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import time
import serial
from serial.tools import list_ports
from pathlib import Path
import collections

APP_NAME = "GRBL Mini Sender"

THEME = {
    "bg": "#1e1e1e",
    "card": "#242424",
    "card_edge": "#2c2c2c",
    "field": "#1a1a1a",
    "text": "#f7f6ff",
    "muted": "#b8b8b8",
    "accent": "#3B82F6",
    "accent_dark": "#2563EB",
    "btn_bg": "#2a2a2a",
    "btn_hover": "#343434",
    "btn_primary": "#16a249",
    "btn_primary_hover": "#139040",
    "btn_warn": "#e3940f",
    "btn_warn_hover": "#cb820d",
    "danger": "#e9590c",
    "danger_dark": "#cc4f0a",
    "stop": "#c94d0a",
    "stop_dark": "#b44509",
    "ok": "#16a249",
    "jog_x": "#e9590c",
    "jog_x_hover": "#cc4f0a",
    "jog_y": "#16a249",
    "jog_y_hover": "#139040",
    "jog_z": "#3B82F6",
    "jog_z_hover": "#2563EB",
    "jog_fg": "#f7f6ff"
}

def ui_font_label(size: int, weight: str = "normal") -> tuple[str, int] | tuple[str, int, str]:
    family = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
    return (family, int(size), weight) if weight != "normal" else (family, int(size))


def ui_font_mono(size: int) -> tuple[str, int]:
    family = "Consolas" if os.name == "nt" else "DejaVu Sans Mono"
    return (family, int(size))


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def app_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA", str(Path.home()))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_config_path() -> Path:
    return user_data_dir() / "config.json"


def user_macros_dir() -> Path:
    d = user_data_dir() / "macros"
    d.mkdir(parents=True, exist_ok=True)
    return d


CONFIG_PATH = user_config_path()
DEFAULT_GRBL_RX_BUFFER_BYTES = 128
# Sync-mode / ack wait timeouts
DEFAULT_SYNC_TIMEOUT_S = 2.0
HOMING_SYNC_TIMEOUT_S = 60.0
SYSTEM_SYNC_TIMEOUT_S = 10.0  # other $-commands

# GRBL realtime bytes
CTRL_X = b"\x18"
RT_STATUS = b"?"
RT_HOLD = b"!"
RT_RESUME = b"~"
RT_JOG_CANCEL = b"\x85"  # GRBL 1.1 Jog Cancel
RT_FEED_RESET = b"\x90"
RT_FEED_PLUS_10 = b"\x91"
RT_FEED_MINUS_10 = b"\x92"
RT_FEED_PLUS_1 = b"\x93"
RT_FEED_MINUS_1 = b"\x94"
RT_SPINDLE_RESET = b"\x99"
RT_SPINDLE_PLUS_10 = b"\x9A"
RT_SPINDLE_MINUS_10 = b"\x9B"
RT_SPINDLE_PLUS_1 = b"\x9C"
RT_SPINDLE_MINUS_1 = b"\x9D"


def clean_gcode_line(line: str) -> str:
    s = line.strip()
    if not s:
        return ""

    # Strip ( ... ) comments
    out = []
    in_paren = 0
    for ch in s:
        if ch == "(":
            in_paren += 1
        elif ch == ")":
            in_paren = max(0, in_paren - 1)
        elif in_paren == 0:
            out.append(ch)
    s = "".join(out).strip()

    # Strip ; comments
    if ";" in s:
        s = s.split(";", 1)[0].strip()

    if not s:
        return ""

    # Normalize for older GRBL variants: uppercase and remove all whitespace.
    s = "".join(s.split()).upper()
    return s


def sanitize_file_to_current_job(src_path: str, dest_path: str) -> int:
    count = 0
    with open(src_path, "r", encoding="utf-8", errors="replace") as fin, \
         open(dest_path, "w", encoding="utf-8", newline="\n") as fout:
        for raw in fin:
            line = clean_gcode_line(raw)
            if not line:
                continue
            fout.write(line + "\n")
            count += 1
    return count


def seed_user_macros_if_missing():
    dst_dir = user_macros_dir()
    src_dir = app_dir() / "macros"

    for i in range(1, 9):
        dst = dst_dir / f"macro-{i}.txt"
        if dst.exists():
            continue

        src = src_dir / f"macro-{i}.txt"
        try:
            if src.exists():
                dst.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            else:
                dst.write_text(
                    f"Macro {i}\n"
                    f"; Put your G-code below. First line is the button name.\n",
                    encoding="utf-8"
                )
        except Exception:
            try:
                dst.write_text(f"Macro {i}\n", encoding="utf-8")
            except Exception:
                pass


def load_macro_with_name(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        raise FileNotFoundError(str(path))

    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not raw_lines:
        return ("(empty macro)", [])

    name = raw_lines[0].strip() or path.stem

    cmds: list[str] = []
    for raw in raw_lines[1:]:
        line = clean_gcode_line(raw)
        if line:
            cmds.append(line)

    return (name, cmds)


def parse_state_from_status(status_line: str) -> str | None:
    if not status_line.startswith("<") or "|" not in status_line:
        return None
    try:
        return status_line[1:].split("|", 1)[0]
    except Exception:
        return None


def parse_field(status_line: str, key: str) -> str | None:
    needle = "|" + key
    if needle not in status_line:
        return None
    try:
        seg = status_line.split(needle, 1)[1]
        return seg.split("|", 1)[0]
    except Exception:
        return None


def parse_vec3(csv3: str | None) -> tuple[float, float, float] | None:
    if not csv3:
        return None
    try:
        parts = csv3.split(",")
        if len(parts) < 3:
            return None
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except Exception:
        return None


def compute_wpos(mpos: tuple[float, float, float] | None,
                 wco: tuple[float, float, float] | None) -> tuple[float, float, float] | None:
    if mpos is None or wco is None:
        return None
    return (mpos[0] - wco[0], mpos[1] - wco[1], mpos[2] - wco[2])


def parse_feed_from_status(status_line: str) -> str | None:
    fs = parse_field(status_line, "FS:")
    if not fs:
        return None
    try:
        return fs.split(",", 1)[0]
    except Exception:
        return None


def parse_bf_from_status(status_line: str) -> tuple[int, int] | None:
    bf = parse_field(status_line, "Bf:")
    if not bf:
        return None
    try:
        a, b = bf.split(",", 1)
        return (int(a), int(b))
    except Exception:
        return None


def parse_pins_from_status(status_line: str) -> set[str]:
    pn = parse_field(status_line, "Pn:")
    if not pn:
        return set()
    return set(pn.strip())


def parse_accessories_from_status(status_line: str) -> set[str]:
    a = parse_field(status_line, "A:")
    if not a:
        return set()
    return set(a.strip())


def list_serial_ports_detailed() -> list[tuple[str, str]]:
    items = []
    for p in list_ports.comports():
        desc = p.description or "Serial Port"
        vidpid = ""
        if p.vid is not None and p.pid is not None:
            vidpid = f" (VID:PID {p.vid:04X}:{p.pid:04X})"
        display = f"{p.device} - {desc}{vidpid}"
        items.append((display, p.device))
    return items


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


class ScrollableRoot(ttk.Frame):
    """
    Optional wrapper to make the whole window scrollable.
    Applies at launch; changing requires restart (to keep state/simple/reliable).
    """
    def __init__(self, parent, bg: str | None = None):
        super().__init__(parent)

        if bg is None:
            bg = THEME["bg"]
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bg)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)
        self._mousewheel_bound = False

    def _bind_mousewheel(self, _):
        if not self._mousewheel_bound:
            self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self._mousewheel_bound = True

    def _unbind_mousewheel(self, _):
        if self._mousewheel_bound:
            self.canvas.unbind_all("<MouseWheel>")
            self._mousewheel_bound = False

    def _on_inner_configure(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.inner_id, width=event.width)

    def _on_mousewheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass


class Tooltip:
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self._tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _show(self, _):
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(self._tip, text=self.text, bg=THEME["card"], fg=THEME["text"],
                       padx=8, pady=4, relief="solid", borderwidth=1, justify="left")
        lbl.pack()

    def _hide(self, _):
        if self._tip:
            self._tip.destroy()
            self._tip = None


class DroPanel(ttk.Frame):
    def __init__(self, parent, title: str):
        super().__init__(parent, style="CardBody.TFrame")
        self.var_x = tk.StringVar(value="-")
        self.var_y = tk.StringVar(value="-")
        self.var_z = tk.StringVar(value="-")

        font_label = ui_font_label(9)
        mono_family = "Courier New" if os.name == "nt" else "DejaVu Sans Mono"
        font_value = (mono_family, 20, "bold")

        ttk.Label(self, text=title, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", padx=10, pady=(8, 0))

        grid = ttk.Frame(self, style="CardBody.TFrame")
        grid.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 10))
        self.grid_columnconfigure(0, weight=1)

        ttk.Label(grid, text="X", font=font_label, style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Label(grid, textvariable=self.var_x, font=font_value, style="Card.TLabel").grid(row=0, column=1, sticky="w")

        ttk.Label(grid, text="Y", font=font_label, style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
        ttk.Label(grid, textvariable=self.var_y, font=font_value, style="Card.TLabel").grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(grid, text="Z", font=font_label, style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
        ttk.Label(grid, textvariable=self.var_z, font=font_value, style="Card.TLabel").grid(row=2, column=1, sticky="w", pady=(8, 0))

    def set_xyz(self, v: tuple[float, float, float] | None):
        if v is None:
            self.var_x.set("-"); self.var_y.set("-"); self.var_z.set("-")
        else:
            self.var_x.set(f"{v[0]:.3f}")
            self.var_y.set(f"{v[1]:.3f}")
            self.var_z.set(f"{v[2]:.3f}")


class LedIndicator(ttk.Frame):
    def __init__(self, parent, label: str, size: int = 10, bg: str | None = None):
        super().__init__(parent)
        if bg is None:
            bg = THEME["card"]
        self.canvas = tk.Canvas(self, width=size, height=size, highlightthickness=0, bg=bg, bd=0)
        self.canvas.grid(row=0, column=0, padx=(0, 8), pady=2, sticky="w")
        self._oval = self.canvas.create_oval(1, 1, size - 1, size - 1, outline="#3a444f", fill=THEME["field"])
        self.lbl = ttk.Label(self, text=label, style="Card.TLabel")
        self.lbl.grid(row=0, column=1, sticky="w")

    def set_on(self, on: bool):
        if on:
            self.canvas.itemconfigure(self._oval, fill=THEME["ok"], outline="#16a34a")
        else:
            self.canvas.itemconfigure(self._oval, fill=THEME["field"], outline="#3a444f")


class IndicatorColumn(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="CardBody.TFrame")
        wrap = ttk.Frame(self, style="CardBody.TFrame")
        wrap.pack(fill="x")

        ttk.Label(wrap, text="Inputs", font=ui_font_label(9, "bold"), style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.led_x = LedIndicator(wrap, "X Limit", bg=THEME["card"])
        self.led_y = LedIndicator(wrap, "Y Limit", bg=THEME["card"])
        self.led_z = LedIndicator(wrap, "Z Limit", bg=THEME["card"])
        self.led_p = LedIndicator(wrap, "Probe", bg=THEME["card"])
        self.led_d = LedIndicator(wrap, "Door", bg=THEME["card"])
        self.led_h = LedIndicator(wrap, "Hold", bg=THEME["card"])
        self.led_r = LedIndicator(wrap, "Reset", bg=THEME["card"])
        self.led_s = LedIndicator(wrap, "Cycle Start", bg=THEME["card"])

        leds_inputs = [self.led_x, self.led_y, self.led_z, self.led_p, self.led_d, self.led_h, self.led_r, self.led_s]
        for i, w in enumerate(leds_inputs, start=1):
            w.grid(row=i, column=0, sticky="w")

        ttk.Separator(wrap, orient="horizontal").grid(row=9, column=0, sticky="ew", pady=10)

        ttk.Label(wrap, text="Accessories", font=ui_font_label(9, "bold"), style="Card.TLabel").grid(row=10, column=0, sticky="w", pady=(0, 6))

        self.led_as = LedIndicator(wrap, "Spindle", bg=THEME["card"])
        self.led_af = LedIndicator(wrap, "Flood", bg=THEME["card"])
        self.led_am = LedIndicator(wrap, "Mist", bg=THEME["card"])

        self.led_as.grid(row=11, column=0, sticky="w")
        self.led_af.grid(row=12, column=0, sticky="w")
        self.led_am.grid(row=13, column=0, sticky="w")

        self.set_all_off()

    def set_all_off(self):
        for led in (self.led_x, self.led_y, self.led_z, self.led_p, self.led_d, self.led_h, self.led_r, self.led_s,
                    self.led_as, self.led_af, self.led_am):
            led.set_on(False)

    def update_from_status(self, status_line: str):
        pins = parse_pins_from_status(status_line)
        acc = parse_accessories_from_status(status_line)

        self.led_x.set_on("X" in pins)
        self.led_y.set_on("Y" in pins)
        self.led_z.set_on("Z" in pins)
        self.led_p.set_on("P" in pins)
        self.led_d.set_on("D" in pins)
        self.led_h.set_on("H" in pins)
        self.led_r.set_on("R" in pins)
        self.led_s.set_on("S" in pins)

        self.led_as.set_on("S" in acc)
        self.led_af.set_on("F" in acc)
        self.led_am.set_on("M" in acc)


class GCodeView(ttk.Frame):
    def __init__(self, parent, default_height_lines: int = 8,
                 sent_color: str = "#243249", ack_color: str = "#1f4d3a",
                 show_sent: bool = True):
        super().__init__(parent)
        self.text = tk.Text(
            self,
            wrap="none",
            height=max(4, int(default_height_lines)),
            font=ui_font_mono(11),
            background=THEME["field"],
            foreground=THEME["text"],
            insertbackground=THEME["text"],
            selectbackground="#2f3747",
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=0
        )
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)

        self.text.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.text.tag_configure("lineno", foreground=THEME["muted"])
        self.text.tag_configure("current", background=ack_color, foreground="#eafff3")
        self.text.tag_configure("sent", background=sent_color, foreground=THEME["text"])
        self._line_count = 0
        self._show_line_numbers = True
        self._show_sent = bool(show_sent)

        # Read-only
        self.text.bind("<Key>", lambda e: "break")

    def set_height_lines(self, n: int):
        n = max(4, int(n))
        self.text.configure(height=n)

    def load_lines(self, lines: list[str]):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self._line_count = len(lines)

        for idx, raw in enumerate(lines, start=1):
            prefix = f"{idx:5d}  " if self._show_line_numbers else ""
            self.text.insert("end", prefix, ("lineno",))
            self.text.insert("end", raw + "\n")

        self.text.config(state="disabled")
        self.highlight_line(0)
        self.text.see("1.0")

    def highlight_line(self, line_no_1based: int):
        self.highlight_lines(0, line_no_1based)

    def highlight_lines(self, sent_line_1based: int, ack_line_1based: int):
        self.text.config(state="normal")
        self.text.tag_remove("current", "1.0", "end")
        self.text.tag_remove("sent", "1.0", "end")

        if self._show_sent and 1 <= sent_line_1based <= self._line_count:
            ln = sent_line_1based
            start = f"{ln}.0"
            end = f"{ln}.end"
            self.text.tag_add("sent", start, end)

        if 1 <= ack_line_1based <= self._line_count:
            ln = ack_line_1based
            start = f"{ln}.0"
            end = f"{ln}.end"
            self.text.tag_add("current", start, end)
            self.text.see(start)
        elif self._show_sent and 1 <= sent_line_1based <= self._line_count:
            self.text.see(f"{sent_line_1based}.0")

        self.text.config(state="disabled")

    def set_highlight_colors(self, sent_color: str, ack_color: str):
        self.text.tag_configure("sent", background=sent_color)
        self.text.tag_configure("current", background=ack_color)

    def set_show_sent(self, show_sent: bool):
        self._show_sent = bool(show_sent)


class GrblWorker(threading.Thread):
    def __init__(self, port: str, baud: int, rx_buffer_total: int, use_bf_autosize: bool,
                 use_planner_throttle: bool, planner_free_min: int,
                 cancel_unlock: bool,
                 sync_timeout_s: float,
                 homing_sync_timeout_s: float,
                 system_sync_timeout_s: float,
                 tx_queue: queue.Queue, ui_queue: queue.Queue):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.tx_queue = tx_queue
        self.ui_queue = ui_queue

        self.ser = None
        self.running = True

        self.job_path: Path | None = None
        self.job_total = 0
        self.job_sent = 0
        self.job_ok = 0
        self.job_active = False

        self.job_paused = False
        self.pause_mode = "paused"

        self.stream_mode = "sync"  # "sync" or "buffered"

        self._inflight_bytes = 0
        self._pending_lengths = collections.deque()

        self._buffer_total = max(32, min(int(rx_buffer_total), 4096))
        self._use_bf_autosize = bool(use_bf_autosize)
        self._use_planner_throttle = bool(use_planner_throttle)
        self._planner_free_min = clamp(int(planner_free_min), 1, 4)
        self._cancel_unlock = bool(cancel_unlock)
        self._sync_timeout_s = float(sync_timeout_s)
        self._homing_sync_timeout_s = float(homing_sync_timeout_s)
        self._system_sync_timeout_s = float(system_sync_timeout_s)

        self._last_planner_free = None
        self._last_rx_free = None
        self._bf_seen = False
        self._bf_warned = False

        self._rx_buf = ""
        self._last_state = None

        self._job_fh = None

    def _push_job_line(self):
        self.ui_queue.put(("job_line", self.job_sent, self.job_ok, self.job_total))

    def open(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=0.0, write_timeout=1.0)
        time.sleep(2.0)
        self.ser.write(b"\r\n")
        self.ser.flush()

        self.ui_queue.put(("log", f"Connected: {self.port} @ {self.baud}"))
        self.ui_queue.put(("port_info", f"{self.port} @ {self.baud}"))
        self.ui_queue.put(("job_state", "idle"))
        self.ui_queue.put(("active_stream_mode", "-"))
        self._handshake()

    def _handshake(self):
        try:
            self.ser.write(b"$I\n")
            self.ser.flush()
        except Exception as e:
            self.ui_queue.put(("error", f"Handshake write failed: {e}"))
            self.ui_queue.put(("grbl_id", "(handshake failed)"))
            return

        info_lines = []
        t0 = time.time()
        while time.time() - t0 < 1.25:
            for line in self._pop_lines_from_rx():
                info_lines.append(line)
            time.sleep(0.01)

        if info_lines:
            for ln in info_lines:
                self.ui_queue.put(("log", f"[id] {ln}"))

        banner = None
        for ln in info_lines:
            if "grbl" in ln.lower():
                banner = ln
                break

        self.ui_queue.put(("grbl_id", banner if banner else "(no GRBL banner detected)"))

    def close(self):
        self._close_job_file()
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def _open_job_file(self, path: Path):
        self._close_job_file()
        self._job_fh = open(path, "r", encoding="utf-8", errors="replace")

    def _close_job_file(self):
        try:
            if self._job_fh:
                self._job_fh.close()
        except Exception:
            pass
        self._job_fh = None

    def send_line(self, line: str):
        self.ser.write((line + "\n").encode("ascii", errors="ignore"))
        self.ser.flush()

    def send_realtime(self, b: bytes):
        self.ser.write(b)
        self.ser.flush()

    def _read_available(self) -> str:
        try:
            data = self.ser.read(4096)
        except serial.SerialException as e:
            self.running = False
            self.ui_queue.put(("error", f"Serial read failed: {e}"))
            self.ui_queue.put(("log", "Emergency disconnect: serial read failed."))
            return ""
        except Exception:
            return ""
        if not data:
            return ""
        return data.decode(errors="replace")

    def _pop_lines_from_rx(self) -> list[str]:
        self._rx_buf += self._read_available()
        if "\n" not in self._rx_buf and "\r" not in self._rx_buf:
            return []
        buf = self._rx_buf.replace("\r", "\n")
        parts = buf.split("\n")
        self._rx_buf = parts[-1]
        return [p.strip() for p in parts[:-1] if p.strip() != ""]

    def _update_bf_tuning(self, status_line: str):
        bf = parse_bf_from_status(status_line)
        if not bf:
            return
        planner_free, rx_free = bf
        self._bf_seen = True
        self._last_planner_free = planner_free
        self._last_rx_free = rx_free

        if self._use_bf_autosize and rx_free is not None:
            if rx_free > self._buffer_total:
                self._buffer_total = rx_free
                self.ui_queue.put(("log", f"[info] Learned larger RX buffer total via Bf: {self._buffer_total}"))

    def _planner_can_send(self) -> bool:
        if not self._use_planner_throttle:
            return True
        if not self._bf_seen:
            if not self._bf_warned:
                self._bf_warned = True
                self.ui_queue.put(("log", "[info] Planner throttle disabled (no Bf: in status)."))
            return True
        if self._last_planner_free is None:
            return True
        return self._last_planner_free > self._planner_free_min

    def _process_incoming_lines(self):
        ok_count = 0
        fatal = None

        for line in self._pop_lines_from_rx():
            if line.startswith("<") and line.endswith(">"):
                self.ui_queue.put(("status", line))
                self._last_state = parse_state_from_status(line) or self._last_state
                self.ui_queue.put(("machine_state", self._last_state or "-"))
                self._update_bf_tuning(line)
                continue

            low = line.lower()
            if line == "ok":
                ok_count += 1
                if self._pending_lengths:
                    ln = self._pending_lengths.popleft()
                    self._inflight_bytes = max(0, self._inflight_bytes - ln)
                continue

            if low.startswith("error:") or low.startswith("alarm:"):
                if self._pending_lengths:
                    ln = self._pending_lengths.popleft()
                    self._inflight_bytes = max(0, self._inflight_bytes - ln)
                fatal = line
                self.ui_queue.put(("log", f"[grbl] {line}"))
                continue

            self.ui_queue.put(("log", f"[grbl] {line}"))

        return ok_count, fatal

    def _sync_timeout_for_line(self, line: str) -> float:
        s = (line or "").strip().upper()
        if not s:
            return self._sync_timeout_s
        if s.startswith("$H"):
            return self._homing_sync_timeout_s
        if s.startswith("$"):
            return self._system_sync_timeout_s
        return self._sync_timeout_s

    def _read_sync_response(self, timeout_s: float = DEFAULT_SYNC_TIMEOUT_S):
        deadline = time.monotonic() + float(timeout_s)

        while self.running:
            for line in self._pop_lines_from_rx():
                if line.startswith("<") and line.endswith(">"):
                    self.ui_queue.put(("status", line))
                    self._last_state = parse_state_from_status(line) or self._last_state
                    self.ui_queue.put(("machine_state", self._last_state or "-"))
                    self._update_bf_tuning(line)
                    continue

                low = line.lower()
                if line == "ok":
                    return ("ok", "ok")
                if low.startswith("error:") or low.startswith("alarm:"):
                    return ("fatal", line)

                self.ui_queue.put(("log", f"[grbl] {line}"))

            if time.monotonic() >= deadline:
                return ("timeout", f"No response from controller (waiting for ok) after {timeout_s:.1f}s.")

            time.sleep(0.005)

        return ("stopped", "stopped")

    def start_job_from_file(self, job_path: Path, total_lines: int, stream_mode: str):
        self.job_path = job_path
        self.job_total = total_lines
        self.job_sent = 0
        self.job_ok = 0
        self.job_active = True
        self.job_paused = False
        self.pause_mode = "paused"
        self.stream_mode = stream_mode if stream_mode in ("sync", "buffered") else "sync"

        self._inflight_bytes = 0
        self._pending_lengths.clear()

        self._open_job_file(job_path)
        self.ui_queue.put(("job_state", "running"))
        self.ui_queue.put(("progress", 0, self.job_total))
        self.ui_queue.put(("active_stream_mode", self.stream_mode))
        self._push_job_line()
        self.ui_queue.put(("log", f"Job started ({self.stream_mode}): {job_path.name} ({self.job_total} lines)"))

    def finish_job(self, msg: str):
        self.job_active = False
        self.job_paused = False
        self.job_path = None
        self.job_total = 0
        self.job_sent = 0
        self.job_ok = 0
        self._close_job_file()
        self._inflight_bytes = 0
        self._pending_lengths.clear()
        self.ui_queue.put(("job_state", "idle"))
        self.ui_queue.put(("active_stream_mode", "-"))
        self._push_job_line()
        self.ui_queue.put(("log", msg))

    def cancel_job_local(self):
        self.job_active = False
        self.job_paused = False
        self.job_path = None
        self.job_total = 0
        self.job_sent = 0
        self.job_ok = 0
        self._close_job_file()
        self._inflight_bytes = 0
        self._pending_lengths.clear()
        self.ui_queue.put(("progress", 0, 0))
        self.ui_queue.put(("job_state", "idle"))
        self.ui_queue.put(("active_stream_mode", "-"))
        self._push_job_line()

    def run_lines_blocking(self, lines: list[str]):
        for line in lines:
            self.send_line(line)
            st, resp = self._read_sync_response(timeout_s=self._sync_timeout_for_line(line))
            if st != "ok":
                self.ui_queue.put(("error", f"Macro stopped ({st}): {resp}"))
                break

    def _stream_step_sync(self):
        raw = self._job_fh.readline()
        if raw == "":
            self.finish_job("Job complete")
            return

        line = raw.strip()
        if not line:
            return

        self.send_line(line)
        self.job_sent += 1
        self._push_job_line()
        st, resp = self._read_sync_response(timeout_s=self._sync_timeout_for_line(line))
        if st == "ok":
            self.job_ok += 1
            self.ui_queue.put(("progress", self.job_ok, self.job_total))
            self._push_job_line()
            if self.job_total > 0 and self.job_ok >= self.job_total:
                self.finish_job("Job complete")
        else:
            self.finish_job(f"Job stopped: {resp}")

    def _stream_step_buffered(self):
        while self.running and self.job_active and not self.job_paused:
            if not self._planner_can_send():
                break
            if self._inflight_bytes >= (self._buffer_total - 2):
                break

            pos = self._job_fh.tell()
            raw = self._job_fh.readline()
            if raw == "":
                if self._inflight_bytes == 0 and not self._pending_lengths:
                    self.finish_job("Job complete")
                break

            line = raw.strip()
            if not line:
                continue

            payload = (line + "\n").encode("ascii", errors="ignore")
            ln = len(payload)

            if ln > self._buffer_total:
                self.ui_queue.put(("log", f"[warn] Line exceeds RX buffer ({ln} > {self._buffer_total}); waiting for buffer to drain."))
                if self._inflight_bytes > 0 or self._pending_lengths:
                    self._job_fh.seek(pos)
                    break

                self.send_line(line)
                self.job_sent += 1
                self._push_job_line()
                st, resp = self._read_sync_response(timeout_s=self._sync_timeout_for_line(line))
                if st == "ok":
                    self.job_ok += 1
                    self.ui_queue.put(("progress", self.job_ok, self.job_total))
                    self._push_job_line()
                else:
                    self.finish_job(f"Job stopped: {resp}")
                break

            if self._inflight_bytes + ln > self._buffer_total:
                self._job_fh.seek(pos)
                break

            try:
                self.ser.write(payload)
                self.ser.flush()
            except Exception as e:
                self.finish_job(f"Serial write failed: {e}")
                return

            self._inflight_bytes += ln
            self._pending_lengths.append(ln)
            self.job_sent += 1
            self._push_job_line()

    def run(self):
        try:
            self.open()
        except Exception as e:
            self.ui_queue.put(("error", f"Failed to open serial: {e}"))
            self.ui_queue.put(("job_state", "disconnected"))
            self.ui_queue.put(("active_stream_mode", "-"))
            self.ui_queue.put(("machine_state", "-"))
            self.ui_queue.put(("grbl_id", "(not connected)"))
            return

        last_status_poll = 0.0

        while self.running:
            try:
                timeout = 0.002 if self.job_active else 0.02
                msg = self.tx_queue.get(timeout=timeout)
            except queue.Empty:
                msg = None

            if msg:
                kind = msg[0]

                if kind == "shutdown":
                    self.running = False

                elif kind == "realtime":
                    self.send_realtime(msg[1])

                elif kind == "line":
                    line = msg[1]
                    self.send_line(line)
                    st, resp = self._read_sync_response(timeout_s=self._sync_timeout_for_line(line))
                    if st != "ok":
                        self.ui_queue.put(("error", f"Command {st}: {resp}"))

                elif kind == "start_job_file":
                    path, total, mode = msg[1], msg[2], msg[3]
                    try:
                        self.start_job_from_file(Path(path), int(total), str(mode))
                    except Exception as e:
                        self.ui_queue.put(("error", f"Failed to start job: {e}"))
                        self.cancel_job_local()

                elif kind == "pause_local":
                    self.job_paused = True
                    self.pause_mode = "paused"
                    self.ui_queue.put(("job_state", "paused"))

                elif kind == "hold_local":
                    self.job_paused = True
                    self.pause_mode = "hold"
                    self.ui_queue.put(("job_state", "hold"))

                elif kind == "resume_local":
                    self.job_paused = False
                    self.ui_queue.put(("job_state", "running"))

                elif kind == "soft_reset":
                    self.send_realtime(CTRL_X)
                    self.cancel_job_local()
                    self.ui_queue.put(("log", "Soft reset sent (Ctrl-X)."))

                elif kind == "cancel_job":
                    try:
                        self.send_realtime(CTRL_X)
                        time.sleep(0.08)
                    except Exception:
                        pass

                    if self._cancel_unlock:
                        try:
                            self.send_line("$X")
                            _ = self._read_sync_response(timeout_s=self._sync_timeout_for_line("$X"))
                        except Exception:
                            pass

                    self.cancel_job_local()
                    self.ui_queue.put(("log", "Cancel: Ctrl-X sent; job cleared." + (" ($X sent)" if self._cancel_unlock else "")))

                elif kind == "run_lines_blocking":
                    self.run_lines_blocking(msg[1])

            if self.job_active and not self.job_paused and self._job_fh:
                if self.stream_mode == "buffered":
                    self._stream_step_buffered()
                else:
                    self._stream_step_sync()

            now = time.time()
            if now - last_status_poll > 0.25:
                last_status_poll = now
                try:
                    self.send_realtime(RT_STATUS)
                except Exception:
                    pass

            ok_count, fatal = self._process_incoming_lines()
            if self.job_active and self.stream_mode == "buffered":
                if fatal:
                    try:
                        self.send_realtime(RT_HOLD)
                    except Exception:
                        pass
                    self.finish_job(f"Job stopped: {fatal}")
                elif ok_count:
                    self.job_ok += ok_count
                    self.ui_queue.put(("progress", self.job_ok, self.job_total))
                    self._push_job_line()

        self.close()
        self.ui_queue.put(("job_state", "disconnected"))
        self.ui_queue.put(("active_stream_mode", "-"))
        self.ui_queue.put(("machine_state", "-"))
        self.ui_queue.put(("port_info", "-"))
        self.ui_queue.put(("grbl_id", "-"))
        self._push_job_line()
        self.ui_queue.put(("log", "Disconnected"))


class SettingsWindow(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app)
        self.app = app
        self.title("Settings")
        self.resizable(False, False)
        settings_bg = THEME["bg"]
        self.configure(background=settings_bg)

        self.transient(app)
        self.grab_set()

        try:
            x = app.winfo_rootx() + 80
            y = app.winfo_rooty() + 80
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

        style = ttk.Style(self)
        style.configure("Settings.TFrame", background=settings_bg)

        outer = ttk.Frame(self, style="Settings.TFrame")
        outer.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)

        self.port_map = {}
        self._refresh_ports()

        self.port_display_var = tk.StringVar(value=self._guess_port_display_from_config())
        self.baud_var = tk.IntVar(value=int(self.app._cfg.get("baud", 115200)))

        self.stream_mode_var = tk.StringVar(value=self.app._cfg.get("stream_mode", "sync"))
        if self.stream_mode_var.get() not in ("sync", "buffered"):
            self.stream_mode_var.set("sync")
        self.planner_free_min_var = tk.IntVar(value=int(self.app._cfg.get("planner_free_min", 2)))

        self.jog_feed_x = tk.DoubleVar(value=float(self.app._cfg.get("jog_feed_x", 50.0)))
        self.jog_feed_y = tk.DoubleVar(value=float(self.app._cfg.get("jog_feed_y", 50.0)))
        self.jog_feed_z = tk.DoubleVar(value=float(self.app._cfg.get("jog_feed_z", 30.0)))
        self.step_presets_xy_var = tk.StringVar(value=", ".join(str(x) for x in self.app.step_presets_xy))
        self.step_presets_z_var = tk.StringVar(value=", ".join(str(x) for x in self.app.step_presets_z))

        self.cancel_unlock_var = tk.BooleanVar(value=bool(self.app._cfg.get("cancel_unlock", False)))

        self.gcode_height_var = tk.IntVar(value=int(self.app._cfg.get("gcode_height_lines", self.app.gcode_height_lines)))
        self.console_height_var = tk.IntVar(value=int(self.app._cfg.get("console_height_lines", self.app.console_height_lines)))

        self.scrollable_main_var = tk.BooleanVar(value=bool(self.app._cfg.get("scrollable_main", False)))
        self.sent_line_color_var = tk.StringVar(value=str(self.app._cfg.get("sent_line_color", self.app.sent_line_color)))
        self.acked_line_color_var = tk.StringVar(value=str(self.app._cfg.get("acked_line_color", self.app.acked_line_color)))
        self.show_sent_highlight_var = tk.BooleanVar(value=bool(self.app._cfg.get("show_sent_highlight", True)))

        conn = ttk.LabelFrame(outer, text="Connection")
        conn.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        conn.grid_columnconfigure(1, weight=1)

        ttk.Label(conn, text="Port").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        self.port_combo = ttk.Combobox(conn, state="readonly", textvariable=self.port_display_var, values=list(self.port_map.keys()))
        self.port_combo.grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 6))

        ttk.Button(conn, text="Refresh", command=self._refresh_ports_ui).grid(row=0, column=2, padx=10, pady=(10, 6))

        ttk.Label(conn, text="Baud").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))
        baud_entry = ttk.Entry(conn, textvariable=self.baud_var, width=12)
        baud_entry.grid(row=1, column=1, sticky="w", padx=10, pady=(0, 10))

        stream = ttk.LabelFrame(outer, text="Streaming")
        stream.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(10, 0))

        row = ttk.Frame(stream)
        row.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        ttk.Label(row, text="Default G-code send method").grid(row=0, column=0, sticky="w")
        stream_mode_combo = ttk.Combobox(row, state="readonly", textvariable=self.stream_mode_var, values=["sync", "buffered"], width=14)
        stream_mode_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(row, text="(sync = safest, buffered = faster)").grid(row=0, column=2, sticky="w", padx=(10, 0))

        row2 = ttk.Frame(stream)
        row2.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        ttk.Label(row2, text="Planner min free blocks (buffered)").grid(row=0, column=0, sticky="w")
        planner_min_entry = ttk.Entry(row2, textvariable=self.planner_free_min_var, width=6)
        planner_min_entry.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(row2, text="(1-4)").grid(row=0, column=2, sticky="w", padx=(10, 0))

        self.rx_buffer_bytes_var = tk.IntVar(value=int(self.app._cfg.get("rx_buffer_bytes", DEFAULT_GRBL_RX_BUFFER_BYTES)))
        self.use_bf_autosize_var = tk.BooleanVar(value=bool(self.app._cfg.get("use_bf_autosize", True)))
        self.use_planner_throttle_var = tk.BooleanVar(value=bool(self.app._cfg.get("use_planner_throttle", True)))
        self.sync_timeout_var = tk.DoubleVar(value=float(self.app._cfg.get("sync_timeout_s", DEFAULT_SYNC_TIMEOUT_S)))
        self.homing_sync_timeout_var = tk.DoubleVar(value=float(self.app._cfg.get("homing_sync_timeout_s", HOMING_SYNC_TIMEOUT_S)))
        self.system_sync_timeout_var = tk.DoubleVar(value=float(self.app._cfg.get("system_sync_timeout_s", SYSTEM_SYNC_TIMEOUT_S)))

        row3 = ttk.Frame(stream)
        row3.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        ttk.Label(row3, text="RX buffer total bytes").grid(row=0, column=0, sticky="w")
        rx_buffer_entry = ttk.Entry(row3, textvariable=self.rx_buffer_bytes_var, width=8)
        rx_buffer_entry.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(row3, text="(32-4096)").grid(row=0, column=2, sticky="w", padx=(10, 0))

        row4 = ttk.Frame(stream)
        row4.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        use_bf_chk = ttk.Checkbutton(row4, text="Auto-size RX buffer using Bf:",
                                     variable=self.use_bf_autosize_var)
        use_bf_chk.grid(row=0, column=0, sticky="w")
        use_throttle_chk = ttk.Checkbutton(row4, text="Planner throttle (buffered)",
                                           variable=self.use_planner_throttle_var)
        use_throttle_chk.grid(row=1, column=0, sticky="w", pady=(6, 0))

        row5 = ttk.Frame(stream)
        row5.grid(row=4, column=0, sticky="ew", padx=10, pady=(0, 10))
        ttk.Label(row5, text="Sync timeout (s)").grid(row=0, column=0, sticky="w")
        sync_timeout_entry = ttk.Entry(row5, textvariable=self.sync_timeout_var, width=8)
        sync_timeout_entry.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(row5, text="Homing timeout (s)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        homing_timeout_entry = ttk.Entry(row5, textvariable=self.homing_sync_timeout_var, width=8)
        homing_timeout_entry.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(6, 0))
        ttk.Label(row5, text="System $ timeout (s)").grid(row=2, column=0, sticky="w", pady=(6, 0))
        system_timeout_entry = ttk.Entry(row5, textvariable=self.system_sync_timeout_var, width=8)
        system_timeout_entry.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(6, 0))

        ttk.Label(stream, text="Note: Streaming/RX changes require reconnect.", foreground="#9ca3af")\
            .grid(row=5, column=0, sticky="w", padx=10, pady=(0, 10))

        Tooltip(stream_mode_combo, "sync: wait for ok after each line (safest).\\nbuffered: queue multiple lines for speed.")
        Tooltip(planner_min_entry, "Minimum free planner blocks required before sending more (1-4).")
        Tooltip(rx_buffer_entry, "Total RX buffer bytes to assume for buffered streaming.")
        Tooltip(use_bf_chk, "Use status Bf: to auto-detect a larger RX buffer.")
        Tooltip(use_throttle_chk, "Throttle buffered sending based on planner free blocks.")
        Tooltip(sync_timeout_entry, "Max wait for ok in sync mode (seconds).")
        Tooltip(homing_timeout_entry, "Max wait for ok after $H (seconds).")
        Tooltip(system_timeout_entry, "Max wait for ok after other $ commands (seconds).")

        job = ttk.LabelFrame(outer, text="Job Safety")
        job.grid(row=2, column=0, sticky="ew", padx=(0, 8), pady=(10, 0))
        cancel_unlock_chk = ttk.Checkbutton(job, text="After Cancel (Ctrl-X), also send $X to unlock (optional)",
                                            variable=self.cancel_unlock_var)
        cancel_unlock_chk.grid(row=0, column=0, sticky="w", padx=10, pady=10)

        jog = ttk.LabelFrame(outer, text="Jog Defaults")
        jog.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(jog, text="Default feed X").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        jog_feed_x_entry = ttk.Entry(jog, textvariable=self.jog_feed_x, width=10)
        jog_feed_x_entry.grid(row=0, column=1, sticky="w", padx=10, pady=(10, 6))

        ttk.Label(jog, text="Default feed Y").grid(row=1, column=0, sticky="w", padx=10, pady=6)
        jog_feed_y_entry = ttk.Entry(jog, textvariable=self.jog_feed_y, width=10)
        jog_feed_y_entry.grid(row=1, column=1, sticky="w", padx=10, pady=6)

        ttk.Label(jog, text="Default feed Z").grid(row=2, column=0, sticky="w", padx=10, pady=(6, 10))
        jog_feed_z_entry = ttk.Entry(jog, textvariable=self.jog_feed_z, width=10)
        jog_feed_z_entry.grid(row=2, column=1, sticky="w", padx=10, pady=(6, 10))

        ttk.Label(jog, text="Step presets X/Y").grid(row=3, column=0, sticky="w", padx=10, pady=(0, 6))
        step_presets_xy_entry = ttk.Entry(jog, textvariable=self.step_presets_xy_var, width=38)
        step_presets_xy_entry.grid(row=3, column=1, sticky="w", padx=10, pady=(0, 6))

        ttk.Label(jog, text="Step presets Z").grid(row=4, column=0, sticky="w", padx=10, pady=(0, 10))
        step_presets_z_entry = ttk.Entry(jog, textvariable=self.step_presets_z_var, width=38)
        step_presets_z_entry.grid(row=4, column=1, sticky="w", padx=10, pady=(0, 10))

        ui = ttk.LabelFrame(outer, text="UI Layout")
        ui.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
        ttk.Label(ui, text="G-code window height (lines)").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        gcode_height_entry = ttk.Entry(ui, textvariable=self.gcode_height_var, width=10)
        gcode_height_entry.grid(row=0, column=1, sticky="w", padx=10, pady=(10, 6))

        ttk.Label(ui, text="Console window height (lines)").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 6))
        console_height_entry = ttk.Entry(ui, textvariable=self.console_height_var, width=10)
        console_height_entry.grid(row=1, column=1, sticky="w", padx=10, pady=(0, 6))

        ttk.Label(ui, text="Sent line color (hex)").grid(row=2, column=0, sticky="w", padx=10, pady=(0, 6))
        sent_color_entry = ttk.Entry(ui, textvariable=self.sent_line_color_var, width=12)
        sent_color_entry.grid(row=2, column=1, sticky="w", padx=10, pady=(0, 6))

        ttk.Label(ui, text="Acked line color (hex)").grid(row=3, column=0, sticky="w", padx=10, pady=(0, 6))
        ack_color_entry = ttk.Entry(ui, textvariable=self.acked_line_color_var, width=12)
        ack_color_entry.grid(row=3, column=1, sticky="w", padx=10, pady=(0, 6))

        show_sent_chk = ttk.Checkbutton(ui, text="Show sent line highlight",
                                        variable=self.show_sent_highlight_var)
        show_sent_chk.grid(row=4, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 6))

        scrollable_chk = ttk.Checkbutton(ui, text="Scrollable main window (applies after restart)",
                                         variable=self.scrollable_main_var)
        scrollable_chk.grid(row=5, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))

        macros = ttk.LabelFrame(outer, text="Macros")
        macros.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
        ttk.Label(macros, text=f"Macro folder: {self.app.macros_dir}").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        ttk.Button(macros, text="Reload macro names", command=self.app.refresh_macro_labels).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))

        btns = ttk.Frame(outer)
        btns.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text="Save", command=self._save).grid(row=0, column=1)

    def _refresh_ports(self):
        items = list_serial_ports_detailed()
        self.port_map = {display: device for (display, device) in items}

    def _refresh_ports_ui(self):
        self._refresh_ports()
        self.port_combo["values"] = list(self.port_map.keys())
        if self.port_combo["values"]:
            if self.port_display_var.get() not in self.port_combo["values"]:
                self.port_display_var.set(self.port_combo["values"][0])

    def _guess_port_display_from_config(self) -> str:
        saved_dev = self.app._cfg.get("port_device", "")
        if not saved_dev:
            return ""
        for disp, dev in self.port_map.items():
            if dev == saved_dev:
                return disp
        return ""

    def _save(self):
        port_display = self.port_display_var.get().strip()
        port_device = self.port_map.get(port_display, "")

        try:
            baud = int(self.baud_var.get())
        except Exception:
            messagebox.showerror("Invalid baud", "Baud must be an integer.")
            return

        sm = self.stream_mode_var.get().strip()
        if sm not in ("sync", "buffered"):
            sm = "sync"

        try:
            planner_min = int(self.planner_free_min_var.get())
        except Exception:
            messagebox.showerror("Invalid planner buffer", "Planner min free blocks must be an integer.")
            return
        if planner_min < 1 or planner_min > 4:
            messagebox.showerror("Invalid planner buffer", "Planner min free blocks must be between 1 and 4.")
            return

        try:
            rx_bytes = int(self.rx_buffer_bytes_var.get())
        except Exception:
            messagebox.showerror("Invalid RX buffer", "RX buffer bytes must be an integer.")
            return
        if rx_bytes < 32 or rx_bytes > 4096:
            messagebox.showerror("Invalid RX buffer", "RX buffer bytes must be between 32 and 4096.")
            return

        def parse_timeout(raw: float, label: str) -> float | None:
            try:
                v = float(raw)
            except Exception:
                messagebox.showerror("Invalid timeout", f"{label} must be a number.")
                return None
            if v <= 0:
                messagebox.showerror("Invalid timeout", f"{label} must be greater than 0.")
                return None
            return v

        sync_timeout_s = parse_timeout(self.sync_timeout_var.get(), "Sync timeout")
        homing_timeout_s = parse_timeout(self.homing_sync_timeout_var.get(), "Homing timeout")
        system_timeout_s = parse_timeout(self.system_sync_timeout_var.get(), "System timeout")
        if sync_timeout_s is None or homing_timeout_s is None or system_timeout_s is None:
            return

        try:
            jx = float(self.jog_feed_x.get())
            jy = float(self.jog_feed_y.get())
            jz = float(self.jog_feed_z.get())
        except Exception:
            messagebox.showerror("Invalid jog feed", "Jog feeds must be numeric.")
            return

        def parse_presets(raw: str) -> list[str] | None:
            tokens = [t for t in raw.replace(",", " ").split() if t]
            presets: list[str] = []
            for t in tokens:
                try:
                    if float(t) <= 0:
                        raise ValueError()
                    presets.append(t)
                except Exception:
                    return None
            return presets if presets else None

        presets_xy = parse_presets(self.step_presets_xy_var.get())
        presets_z = parse_presets(self.step_presets_z_var.get())
        if presets_xy is None or presets_z is None:
            messagebox.showerror("Invalid step presets", "Step presets must be positive numbers separated by commas or spaces.")
            return

        try:
            gh = int(self.gcode_height_var.get())
            ch = int(self.console_height_var.get())
        except Exception:
            messagebox.showerror("Invalid UI height", "Heights must be integers.")
            return

        if gh < 4 or gh > 60:
            messagebox.showerror("Invalid G-code height", "G-code height must be between 4 and 60 lines.")
            return
        if ch < 4 or ch > 60:
            messagebox.showerror("Invalid Console height", "Console height must be between 4 and 60 lines.")
            return

        def normalize_color(raw: str) -> str | None:
            s = (raw or "").strip()
            if len(s) != 7 or not s.startswith("#"):
                return None
            hexpart = s[1:]
            for ch in hexpart:
                if ch not in "0123456789abcdefABCDEF":
                    return None
            return s.lower()

        sent_color = normalize_color(self.sent_line_color_var.get())
        ack_color = normalize_color(self.acked_line_color_var.get())
        if not sent_color or not ack_color:
            messagebox.showerror("Invalid highlight color", "Use hex colors like #243249.")
            return

        old_scroll = bool(self.app._cfg.get("scrollable_main", False))
        new_scroll = bool(self.scrollable_main_var.get())

        self.app._cfg["port_device"] = port_device
        self.app._cfg["baud"] = baud
        self.app._cfg["stream_mode"] = sm
        self.app._cfg["planner_free_min"] = planner_min
        self.app._cfg["rx_buffer_bytes"] = rx_bytes
        self.app._cfg["use_bf_autosize"] = bool(self.use_bf_autosize_var.get())
        self.app._cfg["use_planner_throttle"] = bool(self.use_planner_throttle_var.get())
        self.app._cfg["sync_timeout_s"] = sync_timeout_s
        self.app._cfg["homing_sync_timeout_s"] = homing_timeout_s
        self.app._cfg["system_sync_timeout_s"] = system_timeout_s
        self.app._cfg["jog_feed_x"] = jx
        self.app._cfg["jog_feed_y"] = jy
        self.app._cfg["jog_feed_z"] = jz
        self.app._cfg["step_presets_xy"] = presets_xy
        self.app._cfg["step_presets_z"] = presets_z
        self.app._cfg["cancel_unlock"] = bool(self.cancel_unlock_var.get())
        self.app._cfg["gcode_height_lines"] = gh
        self.app._cfg["console_height_lines"] = ch
        self.app._cfg["scrollable_main"] = new_scroll
        self.app._cfg["sent_line_color"] = sent_color
        self.app._cfg["acked_line_color"] = ack_color
        self.app._cfg["show_sent_highlight"] = bool(self.show_sent_highlight_var.get())

        save_config(self.app._cfg)
        self.app._log("[info] Settings saved.")

        self.app.set_sync_timeouts(sync_timeout_s, homing_timeout_s, system_timeout_s)
        self.app.jog_feed_x.set(jx)
        self.app.jog_feed_y.set(jy)
        self.app.jog_feed_z.set(jz)
        self.app.set_step_presets_xy(presets_xy)
        self.app.set_step_presets_z(presets_z)
        self.app._set_stream_mode_ui(sm)

        self.app.set_gcode_height_lines(gh)
        self.app.set_console_height_lines(ch)
        self.app.set_gcode_highlight_colors(sent_color, ack_color)
        self.app.set_show_sent_highlight(bool(self.show_sent_highlight_var.get()))

        if self.app.worker:
            self.app._log("[info] Connection settings changed. Disconnect/reconnect to apply port/baud changes.")

        if old_scroll != new_scroll:
            self.app._log("[info] Scrollable main window changed. Restart required to apply.")
            messagebox.showinfo("Restart required", "Scrollable main window setting will apply after restarting the app.")

        self.destroy()


class App(tk.Tk):
    DEFAULT_STEP_PRESETS_XY = ["0.1", "0.25", "0.5", "1.0", "5.0", "10", "25", "50", "100", "200", "400"]
    DEFAULT_STEP_PRESETS_Z = ["0.1", "0.25", "0.5", "1.0", "5.0", "10", "25", "50"]
    LEGACY_STEP_PRESETS = ["0.25", "0.5", "1.0", "5.0", "10", "25", "50", "100"]
    DEFAULT_SENT_LINE_COLOR = "#243249"
    DEFAULT_ACK_LINE_COLOR = "#1f4d3a"

    def __init__(self):
        super().__init__()

        seed_user_macros_if_missing()

        self.title("GRBL Mini Sender")
        self.geometry("1920x1080")

        self.tx_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self.worker: GrblWorker | None = None

        self.current_job_path = user_data_dir() / "current-job.gcode"
        self.current_job_total_lines = 0
        self.current_job_lines: list[str] = []

        self.ui_mode = "disconnected"
        self.last_grbl_state = "-"

        self.macros_dir = user_macros_dir()
        self._cfg = load_config()

        self.jog_feed_x = tk.DoubleVar(value=float(self._cfg.get("jog_feed_x", 50.0)))
        self.jog_feed_y = tk.DoubleVar(value=float(self._cfg.get("jog_feed_y", 50.0)))
        self.jog_feed_z = tk.DoubleVar(value=float(self._cfg.get("jog_feed_z", 30.0)))
        self.enable_jog_var = tk.BooleanVar(value=bool(self._cfg.get("enable_jog", False)))
        self.hold_to_jog_var = tk.BooleanVar(value=bool(self._cfg.get("hold_to_jog", False)))

        legacy = self._cfg.get("step_presets")
        if "step_presets_xy" not in self._cfg and isinstance(legacy, list) and legacy:
            self.step_presets_xy = legacy
        else:
            self.step_presets_xy = self._cfg.get("step_presets_xy", list(self.DEFAULT_STEP_PRESETS_XY))
        self.step_presets_z = self._cfg.get("step_presets_z", list(self.DEFAULT_STEP_PRESETS_Z))
        if not isinstance(self.step_presets_xy, list) or not self.step_presets_xy:
            self.step_presets_xy = list(self.DEFAULT_STEP_PRESETS_XY)
        if not isinstance(self.step_presets_z, list) or not self.step_presets_z:
            self.step_presets_z = list(self.DEFAULT_STEP_PRESETS_Z)
        if self.step_presets_xy == self.LEGACY_STEP_PRESETS:
            self.step_presets_xy = list(self.DEFAULT_STEP_PRESETS_XY)

        self.gcode_height_lines = int(self._cfg.get("gcode_height_lines", 8))
        self.console_height_lines = int(self._cfg.get("console_height_lines", 8))
        self.sent_line_color = str(self._cfg.get("sent_line_color", self.DEFAULT_SENT_LINE_COLOR))
        self.acked_line_color = str(self._cfg.get("acked_line_color", self.DEFAULT_ACK_LINE_COLOR))
        self.show_sent_highlight = bool(self._cfg.get("show_sent_highlight", True))
        self.sync_timeout_s = float(self._cfg.get("sync_timeout_s", DEFAULT_SYNC_TIMEOUT_S))
        self.homing_sync_timeout_s = float(self._cfg.get("homing_sync_timeout_s", HOMING_SYNC_TIMEOUT_S))
        self.system_sync_timeout_s = float(self._cfg.get("system_sync_timeout_s", SYSTEM_SYNC_TIMEOUT_S))

        self._line_px_gcode = 18
        self.feed_override_current = 100
        self.spindle_override_current = 100
        self.feed_override_var = tk.IntVar(value=100)
        self.spindle_override_var = tk.IntVar(value=100)
        self.feed_override_label_var = tk.StringVar(value="100%")
        self.spindle_override_label_var = tk.StringVar(value="100%")
        self.status_banner_var = tk.StringVar(value="Disconnected")
        self.job_line_var = tk.StringVar(value="Line: -")
        self.machine_state_var = tk.StringVar(value="STATE: -")
        self.feed_var = tk.StringVar(value="FEED: -")
        self.raw_status_var = tk.StringVar(value="")
        self.big_state_var = tk.StringVar(value="IDLE")
        self._override_updating = False
        self._last_mpos: tuple[float, float, float] | None = None
        self._last_wco: tuple[float, float, float] | None = None

        self._build_styles()
        self._build_ui()

        self._apply_config()
        self.refresh_macro_labels()

        self.after(50, self._poll_ui_queue)
        self._apply_mode("disconnected")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=THEME["bg"])
        style.configure("TLabel", background=THEME["card"], foreground=THEME["text"])
        style.configure("Topbar.TFrame", background=THEME["card"])
        style.configure("Topbar.TLabel", background=THEME["card"], foreground=THEME["muted"])
        style.configure("TLabelframe", background=THEME["card"], foreground=THEME["text"])
        style.configure("TLabelframe.Label", background=THEME["card"], foreground=THEME["text"],
                        font=ui_font_label(9, "bold"))

        style.configure("CardBody.TFrame", background=THEME["card"])
        style.configure("Card.TLabel", background=THEME["card"], foreground=THEME["text"])
        style.configure("CardMuted.TLabel", background=THEME["card"], foreground=THEME["muted"])
        style.configure("CardTitle.TLabel", background=THEME["card"], foreground=THEME["text"],
                        font=ui_font_label(10, "bold"))
        style.configure("TCheckbutton", background=THEME["card"], foreground=THEME["text"])

        style.configure("TButton", padding=(14, 10), background=THEME["btn_bg"], foreground=THEME["text"])
        style.map("TButton",
                  background=[("active", THEME["btn_hover"]), ("!active", THEME["btn_bg"])],
                  foreground=[("active", THEME["text"]), ("!active", THEME["text"])])
        style.configure("Preset.TButton", padding=(4, 2))
        style.configure("PresetActive.TButton", padding=(4, 2), background=THEME["accent_dark"], foreground="#eef2ff")
        style.map("PresetActive.TButton",
                  background=[("active", THEME["accent_dark"]), ("!active", THEME["accent_dark"])],
                  foreground=[("active", "#eef2ff"), ("!active", "#eef2ff")])
        style.configure("Start.TButton", padding=(14, 10), background=THEME["btn_primary"], foreground="#eff6ff")
        style.map("Start.TButton",
                  background=[("active", THEME["btn_primary_hover"]), ("!active", THEME["btn_primary"])],
                  foreground=[("active", "#eff6ff"), ("!active", "#eff6ff")])
        style.configure("Hold.TButton", padding=(14, 10), background=THEME["btn_warn"], foreground="#fff7ed")
        style.map("Hold.TButton",
                  background=[("active", THEME["btn_warn_hover"]), ("!active", THEME["btn_warn"])],
                  foreground=[("active", "#fff7ed"), ("!active", "#fff7ed")])
        style.configure("Stop.TButton", padding=(14, 10), background=THEME["stop"], foreground="#fff1f2")
        style.map("Stop.TButton",
                  background=[("active", THEME["stop_dark"]), ("!active", THEME["stop"])],
                  foreground=[("active", "#fff1f2"), ("!active", "#fff1f2")])
        style.configure("Danger.TButton", padding=(12, 10), background=THEME["stop"], foreground="#fff1f2")
        style.map("Danger.TButton",
                  background=[("active", THEME["stop_dark"]), ("!active", THEME["stop"])],
                  foreground=[("active", "#fff1f2"), ("!active", "#fff1f2")])
        style.configure("JogX.TButton", padding=(8, 6), background=THEME["jog_x"], foreground=THEME["jog_fg"])
        style.map("JogX.TButton",
                  background=[("active", THEME["jog_x_hover"]), ("!active", THEME["jog_x"])],
                  foreground=[("active", THEME["jog_fg"]), ("!active", THEME["jog_fg"])])
        style.configure("JogY.TButton", padding=(8, 6), background=THEME["jog_y"], foreground=THEME["jog_fg"])
        style.map("JogY.TButton",
                  background=[("active", THEME["jog_y_hover"]), ("!active", THEME["jog_y"])],
                  foreground=[("active", THEME["jog_fg"]), ("!active", THEME["jog_fg"])])
        style.configure("JogZ.TButton", padding=(8, 6), background=THEME["jog_z"], foreground=THEME["jog_fg"])
        style.map("JogZ.TButton",
                  background=[("active", THEME["jog_z_hover"]), ("!active", THEME["jog_z"])],
                  foreground=[("active", THEME["jog_fg"]), ("!active", THEME["jog_fg"])])
        style.configure("BigState.TLabel", font=ui_font_label(18, "bold"), foreground=THEME["accent"])
        style.configure("TProgressbar", troughcolor=THEME["bg"], background=THEME["accent"],
                        lightcolor=THEME["accent"], darkcolor=THEME["accent"], bordercolor=THEME["card_edge"])

    def _make_card(self, parent, title: str, padx: int = 12, pady: int = 10) -> tuple[tk.Frame, ttk.Frame]:
        outer = tk.Frame(parent, bg=THEME["card_edge"])
        inner = tk.Frame(outer, bg=THEME["card"])
        inner.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)

        title_lbl = tk.Label(inner, text=title, bg=THEME["card"], fg=THEME["text"],
                             font=ui_font_label(10, "bold"))
        title_lbl.grid(row=0, column=0, sticky="w", padx=padx, pady=(pady, 0))

        body = ttk.Frame(inner, style="CardBody.TFrame")
        body.grid(row=1, column=0, sticky="nsew", padx=padx, pady=(6, pady))
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_rowconfigure(1, weight=1)

        return outer, body

    @staticmethod
    def _ellipsis(s: str, max_len: int = 60) -> str:
        s = (s or "").strip()
        if len(s) <= max_len:
            return s
        if max_len <= 3:
            return s[:max_len]
        return s[: max_len - 3] + "..."

    def _apply_config(self):
        geom = self._cfg.get("geometry")
        if isinstance(geom, str) and "x" in geom:
            try:
                self.geometry(geom)
            except Exception:
                pass

        self._set_stream_mode_ui(self._cfg.get("stream_mode", "sync"))
        self._last_upload_dir = self._cfg.get("last_upload_dir", "") if isinstance(self._cfg.get("last_upload_dir", ""), str) else ""

        self.jog_feed_x.set(float(self._cfg.get("jog_feed_x", self.jog_feed_x.get())))
        self.jog_feed_y.set(float(self._cfg.get("jog_feed_y", self.jog_feed_y.get())))
        self.jog_feed_z.set(float(self._cfg.get("jog_feed_z", self.jog_feed_z.get())))
        self.enable_jog_var.set(bool(self._cfg.get("enable_jog", self.enable_jog_var.get())))
        self.hold_to_jog_var.set(bool(self._cfg.get("hold_to_jog", self.hold_to_jog_var.get())))
        self._configure_jog_button_behavior()

        step_presets_xy = self._cfg.get("step_presets_xy", self.step_presets_xy)
        if isinstance(step_presets_xy, list) and step_presets_xy:
            self.step_presets_xy = step_presets_xy
        step_presets_z = self._cfg.get("step_presets_z", self.step_presets_z)
        if isinstance(step_presets_z, list) and step_presets_z:
            self.step_presets_z = step_presets_z

        self.gcode_height_lines = int(self._cfg.get("gcode_height_lines", self.gcode_height_lines))
        self.console_height_lines = int(self._cfg.get("console_height_lines", self.console_height_lines))
        self.sent_line_color = str(self._cfg.get("sent_line_color", self.sent_line_color))
        self.acked_line_color = str(self._cfg.get("acked_line_color", self.acked_line_color))
        self.show_sent_highlight = bool(self._cfg.get("show_sent_highlight", self.show_sent_highlight))
        self.sync_timeout_s = float(self._cfg.get("sync_timeout_s", self.sync_timeout_s))
        self.homing_sync_timeout_s = float(self._cfg.get("homing_sync_timeout_s", self.homing_sync_timeout_s))
        self.system_sync_timeout_s = float(self._cfg.get("system_sync_timeout_s", self.system_sync_timeout_s))
        self._apply_heights_live()
        self.set_gcode_highlight_colors(self.sent_line_color, self.acked_line_color)
        self.set_show_sent_highlight(self.show_sent_highlight)

    def _write_config(self):
        cfg = dict(self._cfg)
        cfg["geometry"] = self.geometry()
        cfg["jog_feed_x"] = float(self.jog_feed_x.get())
        cfg["jog_feed_y"] = float(self.jog_feed_y.get())
        cfg["jog_feed_z"] = float(self.jog_feed_z.get())
        cfg["enable_jog"] = bool(self.enable_jog_var.get())
        cfg["hold_to_jog"] = bool(self.hold_to_jog_var.get())
        cfg["step_presets_xy"] = list(self.step_presets_xy)
        cfg["step_presets_z"] = list(self.step_presets_z)
        cfg["gcode_height_lines"] = int(self.gcode_height_lines)
        cfg["console_height_lines"] = int(self.console_height_lines)
        cfg["sent_line_color"] = str(self.sent_line_color)
        cfg["acked_line_color"] = str(self.acked_line_color)
        cfg["show_sent_highlight"] = bool(self.show_sent_highlight)
        cfg["sync_timeout_s"] = float(self.sync_timeout_s)
        cfg["homing_sync_timeout_s"] = float(self.homing_sync_timeout_s)
        cfg["system_sync_timeout_s"] = float(self.system_sync_timeout_s)
        save_config(cfg)
        self._cfg = cfg

    def set_gcode_height_lines(self, n: int):
        self.gcode_height_lines = max(4, int(n))
        self._apply_heights_live()
        self._write_config()

    def set_console_height_lines(self, n: int):
        self.console_height_lines = max(4, int(n))
        self._apply_heights_live()
        self._write_config()

    def set_gcode_highlight_colors(self, sent_color: str, ack_color: str):
        self.sent_line_color = sent_color
        self.acked_line_color = ack_color
        try:
            self.gcode_view.set_highlight_colors(sent_color, ack_color)
        except Exception:
            pass
        self._write_config()

    def set_show_sent_highlight(self, show_sent: bool):
        self.show_sent_highlight = bool(show_sent)
        try:
            self.gcode_view.set_show_sent(self.show_sent_highlight)
        except Exception:
            pass
        self._write_config()

    def set_sync_timeouts(self, sync_timeout_s: float, homing_sync_timeout_s: float, system_sync_timeout_s: float):
        self.sync_timeout_s = float(sync_timeout_s)
        self.homing_sync_timeout_s = float(homing_sync_timeout_s)
        self.system_sync_timeout_s = float(system_sync_timeout_s)
        if self.worker:
            try:
                self.worker._sync_timeout_s = self.sync_timeout_s
                self.worker._homing_sync_timeout_s = self.homing_sync_timeout_s
                self.worker._system_sync_timeout_s = self.system_sync_timeout_s
            except Exception:
                pass
        self._write_config()

    def set_step_presets_xy(self, presets: list[str]):
        cleaned = [str(p).strip() for p in presets if str(p).strip()]
        if not cleaned:
            cleaned = list(self.DEFAULT_STEP_PRESETS_XY)
        self.step_presets_xy = cleaned
        try:
            self._build_step_preset_buttons()
        except Exception:
            pass
        self._write_config()

    def set_step_presets_z(self, presets: list[str]):
        cleaned = [str(p).strip() for p in presets if str(p).strip()]
        if not cleaned:
            cleaned = list(self.DEFAULT_STEP_PRESETS_Z)
        self.step_presets_z = cleaned
        try:
            self._build_step_preset_buttons()
        except Exception:
            pass
        self._write_config()

    def _set_active_step_preset(self, value: float, target_var: tk.DoubleVar, buttons: list[ttk.Button]):
        target_var.set(float(value))
        for btn in buttons:
            try:
                btn_val = float(btn._step_value)  # type: ignore[attr-defined]
            except Exception:
                btn_val = None
            style = "PresetActive.TButton" if btn_val == float(value) else "Preset.TButton"
            btn.config(style=style)
        self._write_config()

    def _build_step_preset_buttons(self):
        if not hasattr(self, "step_preset_row_xy") or not hasattr(self, "step_preset_row_z"):
            return

        for child in self.step_preset_row_xy.winfo_children():
            child.destroy()
        for child in self.step_preset_row_z.winfo_children():
            child.destroy()

        self.step_preset_buttons_xy = []
        for i, raw in enumerate(self.step_presets_xy):
            try:
                val = float(raw)
            except Exception:
                continue
            btn = ttk.Button(
                self.step_preset_row_xy,
                text=str(raw),
                style="Preset.TButton",
                width=4,
                command=lambda v=val: self._set_active_step_preset(v, self.jog_step_xy, self.step_preset_buttons_xy)
            )
            btn._step_value = val  # type: ignore[attr-defined]
            btn.grid(row=0, column=i, padx=(0, 6), pady=2, sticky="w")
            self.step_preset_buttons_xy.append(btn)

        self.step_preset_buttons_z = []
        for i, raw in enumerate(self.step_presets_z):
            try:
                val = float(raw)
            except Exception:
                continue
            btn = ttk.Button(
                self.step_preset_row_z,
                text=str(raw),
                style="Preset.TButton",
                width=4,
                command=lambda v=val: self._set_active_step_preset(v, self.jog_step_z, self.step_preset_buttons_z)
            )
            btn._step_value = val  # type: ignore[attr-defined]
            btn.grid(row=0, column=i, padx=(0, 6), pady=2, sticky="w")
            self.step_preset_buttons_z.append(btn)

        if self.step_preset_buttons_xy:
            xy_vals = [float(b._step_value) for b in self.step_preset_buttons_xy]  # type: ignore[attr-defined]
            first_xy = float(self.step_preset_buttons_xy[0]._step_value)  # type: ignore[attr-defined]
            current_xy = float(self.jog_step_xy.get())
            self._set_active_step_preset(current_xy if current_xy in xy_vals else first_xy,
                                         self.jog_step_xy, self.step_preset_buttons_xy)
        if self.step_preset_buttons_z:
            z_vals = [float(b._step_value) for b in self.step_preset_buttons_z]  # type: ignore[attr-defined]
            first_z = float(self.step_preset_buttons_z[0]._step_value)  # type: ignore[attr-defined]
            current_z = float(self.jog_step_z.get())
            self._set_active_step_preset(current_z if current_z in z_vals else first_z,
                                         self.jog_step_z, self.step_preset_buttons_z)

    def send_realtime(self, b: bytes):
        if not self.worker:
            return
        self.tx_queue.put(("realtime", b))

    def emergency_stop(self):
        self.cancel_job()
        self._log("[rt] Emergency Stop (Ctrl-X).")

    def _set_status_banner(self, text: str, level: str):
        colors = {
            "ok": ("#1f3c35", "#bff3e5"),
            "warn": ("#1f3340", "#bfe7f6"),
            "error": ("#3a1b25", "#f5c3d0"),
            "info": (THEME["card"], THEME["text"])
        }
        bg, fg = colors.get(level, colors["info"])
        self.status_banner_var.set(text)
        try:
            self.status_banner.configure(bg=bg, fg=fg)
        except Exception:
            pass

    def _update_status_banner(self, status_line: str):
        state = parse_state_from_status(status_line) if status_line else None
        pins = parse_pins_from_status(status_line) if status_line else set()

        if state and state.upper().startswith("ALARM"):
            self._set_status_banner("ALARM: Clear issue, then Unlock ($X) and Home ($H).", "error")
            return
        if "D" in pins:
            self._set_status_banner("DOOR: Close door, then Unlock ($X).", "warn")
            return
        if any(p in pins for p in ("X", "Y", "Z")):
            self._set_status_banner("LIMIT: Clear switch, then Unlock ($X).", "warn")
            return
        if state in ("Run", "Jog", "Cycle"):
            self._set_status_banner("RUNNING", "ok")
            return
        if state == "Hold":
            self._set_status_banner("HOLD: Press Resume.", "warn")
            return
        if state == "Idle":
            self._set_status_banner("READY", "ok")
            return
        if state:
            self._set_status_banner(f"STATE: {state}", "info")

    def _send_override_steps(self, target: int, current: int, min_val: int, max_val: int,
                             plus10: bytes, minus10: bytes, plus1: bytes, minus1: bytes) -> int:
        target = clamp(int(target), min_val, max_val)
        diff = target - current
        if diff == 0:
            return current
        step10 = 10 if diff > 0 else -10
        step1 = 1 if diff > 0 else -1
        while abs(diff) >= 10:
            self.send_realtime(plus10 if diff > 0 else minus10)
            diff -= step10
            current += step10
        while diff != 0:
            self.send_realtime(plus1 if diff > 0 else minus1)
            diff -= step1
            current += step1
        return current

    def _commit_feed_override(self):
        target = int(self.feed_override_var.get())
        self.feed_override_current = self._send_override_steps(
            target, self.feed_override_current, 10, 200,
            RT_FEED_PLUS_10, RT_FEED_MINUS_10, RT_FEED_PLUS_1, RT_FEED_MINUS_1
        )
        self.feed_override_var.set(self.feed_override_current)
        self.feed_override_label_var.set(f"{self.feed_override_current}%")

    def _commit_spindle_override(self):
        target = int(self.spindle_override_var.get())
        self.spindle_override_current = self._send_override_steps(
            target, self.spindle_override_current, 50, 200,
            RT_SPINDLE_PLUS_10, RT_SPINDLE_MINUS_10, RT_SPINDLE_PLUS_1, RT_SPINDLE_MINUS_1
        )
        self.spindle_override_var.set(self.spindle_override_current)
        self.spindle_override_label_var.set(f"{self.spindle_override_current}%")

    def _feed_override_slider_changed(self, value: str):
        if self._override_updating:
            return
        self.feed_override_var.set(int(float(value)))
        self.feed_override_label_var.set(f"{self.feed_override_var.get()}%")

    def _spindle_override_slider_changed(self, value: str):
        if self._override_updating:
            return
        self.spindle_override_var.set(int(float(value)))
        self.spindle_override_label_var.set(f"{self.spindle_override_var.get()}%")

    def _reset_feed_override(self):
        self.send_realtime(RT_FEED_RESET)
        self.feed_override_current = 100
        self._override_updating = True
        self.feed_override_var.set(100)
        self.feed_override_label_var.set("100%")
        self.feed_override_scale.set(100)
        self._override_updating = False

    def _reset_spindle_override(self):
        self.send_realtime(RT_SPINDLE_RESET)
        self.spindle_override_current = 100
        self._override_updating = True
        self.spindle_override_var.set(100)
        self.spindle_override_label_var.set("100%")
        self.spindle_override_scale.set(100)
        self._override_updating = False

    def _jog_cmd(self, axis: str, direction: int) -> str:
        step = (self.jog_step_xy.get() if axis in ("X", "Y") else self.jog_step_z.get()) * direction
        unit_g = "G20" if self.units_var.get().lower() == "inch" else "G21"
        feed = float(self.jog_feed_x.get()) if axis == "X" else (
            float(self.jog_feed_y.get()) if axis == "Y" else float(self.jog_feed_z.get())
        )
        return f"$J={unit_g} G91 {axis}{step} F{feed}"

    def _configure_jog_button_behavior(self):
        if not hasattr(self, "_jog_button_map"):
            return
        hold = bool(self.hold_to_jog_var.get())
        for btn, (axis, direction) in self._jog_button_map.items():
            btn.unbind("<ButtonPress-1>")
            btn.unbind("<ButtonRelease-1>")
            if hold:
                btn.configure(command=lambda: None)
                btn.bind("<ButtonPress-1>", lambda e, a=axis, d=direction: self.send_line(self._jog_cmd(a, d)))
                btn.bind("<ButtonRelease-1>", lambda e: self.jog_cancel())
            else:
                btn.configure(command=lambda a=axis, d=direction: self.send_line(self._jog_cmd(a, d)))

    def _on_jog_safety_changed(self):
        self._configure_jog_button_behavior()
        self._apply_mode(self.ui_mode)
        self._write_config()

    def _apply_heights_live(self):
        try:
            self.gcode_view.set_height_lines(self.gcode_height_lines)
        except Exception:
            pass
        try:
            self.console.configure(height=self.console_height_lines)
        except Exception:
            pass
        self.after(10, self._apply_pane_split_from_settings)

    def _apply_pane_split_from_settings(self):
        if not hasattr(self, "left_pane"):
            return

        g_px = int(self.gcode_height_lines * self._line_px_gcode)

        self.left_pane.update_idletasks()
        total = self.left_pane.winfo_height()
        if total < 200:
            self.after(50, self._apply_pane_split_from_settings)
            return

        sash = clamp(g_px, 120, total - 180)
        try:
            self.left_pane.sashpos(0, sash)
        except Exception:
            pass

    def on_close(self):
        self._write_config()
        if self.worker:
            try:
                self.worker.running = False
            except Exception:
                pass
            self.tx_queue.put(("shutdown",))
        self.destroy()

    def _set_stream_mode_ui(self, mode: str):
        self.default_stream_mode = "buffered" if mode == "buffered" else "sync"

    def get_stream_mode_value(self) -> str:
        return getattr(self, "default_stream_mode", "sync")

    def _build_ui(self):
        self.configure(background=THEME["bg"])

        scrollable = bool(self._cfg.get("scrollable_main", False))
        if scrollable:
            wrapper = ScrollableRoot(self, bg=THEME["bg"])
            wrapper.grid(row=0, column=0, sticky="nsew")
            self.grid_rowconfigure(0, weight=1)
            self.grid_columnconfigure(0, weight=1)
            host = wrapper.inner
            self._scroll_wrapper = wrapper
        else:
            host = self
            self._scroll_wrapper = None
            self.grid_rowconfigure(0, weight=1)
            self.grid_columnconfigure(0, weight=1)

        root = ttk.Frame(host)
        root.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        host.grid_rowconfigure(0, weight=1)
        host.grid_columnconfigure(0, weight=1)

        root.grid_columnconfigure(0, weight=2)
        root.grid_columnconfigure(1, weight=3)
        root.grid_rowconfigure(1, weight=1)

        # ---------------- Topbar ----------------
        topbar = ttk.Frame(root, style="Topbar.TFrame")
        topbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        topbar.grid_columnconfigure(99, weight=1)

        self.btn_estop = ttk.Button(topbar, text="E-STOP (Ctrl-X)", style="Danger.TButton", command=self.emergency_stop)
        self.btn_soft_reset = ttk.Button(topbar, text="Soft Reset", style="Stop.TButton", command=self.soft_reset)
        self.btn_start  = ttk.Button(topbar, text="Start",  style="Start.TButton", command=self.start_job)
        self.btn_hold   = ttk.Button(topbar, text="Hold",   style="Hold.TButton", command=self.stop_gentle)
        self.btn_pause  = ttk.Button(topbar, text="Pause",  style="Hold.TButton", command=self.pause_job)
        self.btn_resume = ttk.Button(topbar, text="Resume", style="Start.TButton", command=self.resume_job)
        self.btn_cancel = ttk.Button(topbar, text="Cancel", style="Stop.TButton", command=self.cancel_job)

        self.btn_estop.grid(row=0, column=0, padx=(0, 8))
        self.btn_soft_reset.grid(row=0, column=1, padx=(0, 12))
        ttk.Separator(topbar, orient="vertical").grid(row=0, column=2, sticky="ns", padx=(0, 12))
        self.btn_start.grid(row=0, column=3, padx=(0, 8))
        self.btn_pause.grid(row=0, column=4, padx=(0, 8))
        self.btn_resume.grid(row=0, column=5, padx=(0, 8))
        self.btn_hold.grid(row=0, column=6, padx=(0, 8))
        self.btn_cancel.grid(row=0, column=7, padx=(0, 12))
        ttk.Separator(topbar, orient="vertical").grid(row=0, column=8, sticky="ns", padx=(0, 12))

        self.btn_connect = ttk.Button(topbar, text="Connect", command=self.connect)
        self.btn_connect.grid(row=0, column=9, padx=(0, 8))
        self.btn_disconnect = ttk.Button(topbar, text="Disconnect", command=self.disconnect)
        self.btn_disconnect.grid(row=0, column=10, padx=(0, 12))

        self.btn_settings = ttk.Button(topbar, text="Settings", command=self.open_settings)
        self.btn_settings.grid(row=0, column=11, padx=(0, 12))

        self.btn_upload = ttk.Button(topbar, text="NC File Load", command=self.load_file)
        self.btn_upload.grid(row=0, column=12, padx=(0, 16))

        self.device_info_var = tk.StringVar(value="Device: -")
        ttk.Label(topbar, textvariable=self.device_info_var, style="Topbar.TLabel").grid(row=0, column=13, sticky="w", padx=(0, 12))

        self.grbl_id_var = tk.StringVar(value="GRBL: -")
        ttk.Label(topbar, textvariable=self.grbl_id_var, style="Topbar.TLabel").grid(row=0, column=14, sticky="w", padx=(0, 12))

        self.job_label_var = tk.StringVar(value="No job loaded")
        ttk.Label(topbar, textvariable=self.job_label_var, style="Topbar.TLabel").grid(row=0, column=99, sticky="e")

        sidebar = ttk.Frame(root)
        sidebar.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(0, weight=0)
        sidebar.grid_rowconfigure(1, weight=0)
        sidebar.grid_rowconfigure(2, weight=0)
        sidebar.grid_rowconfigure(3, weight=1)

        main = ttk.Frame(root)
        main.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=0)  # job header
        main.grid_rowconfigure(1, weight=1)  # gcode+console pane

        # ---------------- Job panel above G-code ----------------
        job_header = ttk.Frame(main)
        job_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        job_header.grid_columnconfigure(0, weight=1)

        job_card, job_body = self._make_card(job_header, "Job")
        job_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        job_body.grid_columnconfigure(0, weight=1)
        job_body.grid_columnconfigure(1, weight=0)

        self.active_mode_var = tk.StringVar(value="Active: -")
        ttk.Label(job_body, textvariable=self.active_mode_var, anchor="center", style="Card.TLabel")\
            .grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 6))
        self.progress = ttk.Progressbar(job_body, mode="determinate")
        self.progress.grid(row=1, column=0, sticky="ew", padx=0, pady=(0, 0))
        ttk.Label(job_body, textvariable=self.job_line_var, width=14, anchor="e", style="CardMuted.TLabel")\
            .grid(row=1, column=1, sticky="e", padx=(8, 0), pady=(0, 0))

        overrides_card, overrides_body = self._make_card(job_header, "Overrides")
        overrides_card.grid(row=1, column=0, sticky="ew")
        overrides_body.grid_columnconfigure(1, weight=1)

        ttk.Label(overrides_body, text="Feed", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.feed_override_scale = ttk.Scale(overrides_body, from_=10, to=200, orient="horizontal",
                                             command=self._feed_override_slider_changed)
        self.feed_override_scale.grid(row=0, column=1, sticky="ew", padx=8, pady=(0, 4))
        self.feed_override_scale.bind("<ButtonRelease-1>", lambda e: self._commit_feed_override())
        ttk.Label(overrides_body, textvariable=self.feed_override_label_var, width=5, style="CardMuted.TLabel")\
            .grid(row=0, column=2, sticky="e", padx=(0, 6), pady=(0, 4))
        self.btn_feed_reset = ttk.Button(overrides_body, text="Reset", command=self._reset_feed_override)
        self.btn_feed_reset.grid(row=0, column=3, padx=(0, 0), pady=(0, 4))

        ttk.Label(overrides_body, text="Spindle", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 0))
        self.spindle_override_scale = ttk.Scale(overrides_body, from_=50, to=200, orient="horizontal",
                                                command=self._spindle_override_slider_changed)
        self.spindle_override_scale.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 0))
        self.spindle_override_scale.bind("<ButtonRelease-1>", lambda e: self._commit_spindle_override())
        ttk.Label(overrides_body, textvariable=self.spindle_override_label_var, width=5, style="CardMuted.TLabel")\
            .grid(row=1, column=2, sticky="e", padx=(0, 6), pady=(0, 0))
        self.btn_spindle_reset = ttk.Button(overrides_body, text="Reset", command=self._reset_spindle_override)
        self.btn_spindle_reset.grid(row=1, column=3, padx=(0, 0), pady=(0, 0))

        # --- Main area: vertical split (G-code / Console) ---
        self.left_pane = ttk.PanedWindow(main, orient="vertical")
        self.left_pane.grid(row=1, column=0, sticky="nsew")

        gcode_card, gcode_body = self._make_card(self.left_pane, "G-code")
        gcode_body.grid_rowconfigure(0, weight=1)
        gcode_body.grid_columnconfigure(0, weight=1)
        self.gcode_view = GCodeView(
            gcode_body,
            default_height_lines=self.gcode_height_lines,
            sent_color=self.sent_line_color,
            ack_color=self.acked_line_color,
            show_sent=self.show_sent_highlight
        )
        self.gcode_view.grid(row=0, column=0, sticky="nsew")

        console_card, console_body = self._make_card(self.left_pane, "Console")
        console_body.grid_columnconfigure(0, weight=1)
        console_body.grid_columnconfigure(1, weight=0)
        console_body.grid_rowconfigure(0, weight=1)

        self.console = tk.Text(
            console_body,
            height=max(4, int(self.console_height_lines)),
            font=ui_font_mono(10),
            background=THEME["field"],
            foreground=THEME["text"],
            insertbackground=THEME["text"],
            relief="flat",
            borderwidth=0
        )
        self.console.config(state="disabled")
        self.console.bind("<Key>", lambda e: "break")
        self.console_vsb = ttk.Scrollbar(console_body, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=self.console_vsb.set)
        self.console.grid(row=0, column=0, sticky="nsew")
        self.console_vsb.grid(row=0, column=1, sticky="ns", padx=(8, 0))

        cmd_row = ttk.Frame(console_body, style="CardBody.TFrame")
        cmd_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        cmd_row.grid_columnconfigure(1, weight=1)

        ttk.Label(cmd_row, text="Command", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.cmd_var = tk.StringVar()
        self.cmd_entry = ttk.Entry(cmd_row, textvariable=self.cmd_var)
        self.cmd_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.cmd_entry.bind("<Return>", lambda e: self.send_console_command())
        self.btn_send_cmd = ttk.Button(cmd_row, text="Send", command=self.send_console_command)
        self.btn_send_cmd.grid(row=0, column=2, padx=(0, 6))
        self.btn_clear_console = ttk.Button(cmd_row, text="Clear", command=self.clear_console)
        self.btn_clear_console.grid(row=0, column=3)

        self.left_pane.add(gcode_card, weight=1)
        self.left_pane.add(console_card, weight=1)
        self.after(80, self._apply_pane_split_from_settings)

        # ---------------- Sidebar: Status + DRO + Overrides + Jog ----------------
        status_card, status_body = self._make_card(sidebar, "Status")
        status_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        status_body.grid_columnconfigure(0, weight=1)
        self.status_banner = tk.Label(status_body, textvariable=self.status_banner_var,
                                      bg=THEME["card"], fg=THEME["text"], padx=10, pady=10, anchor="w")
        self.status_banner.grid(row=0, column=0, sticky="ew")

        dro_card, dro_body = self._make_card(sidebar, "Position")
        dro_card.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        dro_row = ttk.Frame(dro_body, style="CardBody.TFrame")
        dro_row.grid(row=0, column=0, sticky="ew")
        dro_row.grid_columnconfigure(0, weight=1)
        dro_row.grid_columnconfigure(1, weight=1)

        self.dro_machine = DroPanel(dro_row, "Machine (MPos)")
        self.dro_machine.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.dro_work = DroPanel(dro_row, "Work (WPos)")
        self.dro_work.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        jog_btn_width = 28

        wpos_row = ttk.Frame(dro_row, style="CardBody.TFrame")
        wpos_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        for c in range(6):
            wpos_row.grid_columnconfigure(c, weight=1, uniform="wpos")

        self.btn_home_all = ttk.Button(wpos_row, text="Home All ($H)", style="Start.TButton", command=self.home_all)
        self.btn_unlock = ttk.Button(wpos_row, text="Unlock ($X)", style="Start.TButton", command=self.unlock)
        self.btn_reset_wpos = ttk.Button(wpos_row, text="Clear WPOS", style="Hold.TButton", command=self.clear_wpos)
        self.btn_set_wpos_x = ttk.Button(wpos_row, text="Set X", style="Hold.TButton", command=lambda: self.set_wpos_axis("X"))
        self.btn_set_wpos_y = ttk.Button(wpos_row, text="Set Y", style="Hold.TButton", command=lambda: self.set_wpos_axis("Y"))
        self.btn_set_wpos_z = ttk.Button(wpos_row, text="Set Z", style="Hold.TButton", command=lambda: self.set_wpos_axis("Z"))

        self.btn_home_all.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_unlock.grid(row=0, column=1, sticky="ew", padx=6)
        self.btn_reset_wpos.grid(row=0, column=2, sticky="ew", padx=6)
        self.btn_set_wpos_x.grid(row=0, column=3, sticky="ew", padx=6)
        self.btn_set_wpos_y.grid(row=0, column=4, sticky="ew", padx=6)
        self.btn_set_wpos_z.grid(row=0, column=5, sticky="ew", padx=(6, 0))

        self.feed_override_scale.set(self.feed_override_current)
        self.spindle_override_scale.set(self.spindle_override_current)

        # Sidebar body: Indicators + Jog
        body = ttk.Frame(sidebar)
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)

        indicators_card, indicators_body = self._make_card(body, "Indicators")
        indicators_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.indicators = IndicatorColumn(indicators_body)
        self.indicators.grid(row=0, column=0, sticky="nsew")

        # Jog window
        jog_card, jog_body = self._make_card(body, "Jog")
        jog_card.grid(row=0, column=1, sticky="nw")
        jog_body.grid_columnconfigure(0, weight=1)

        cfg = ttk.Frame(jog_body, style="CardBody.TFrame")
        cfg.grid(row=0, column=0, sticky="w")

        ttk.Label(cfg, text="Units", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.units_var = tk.StringVar(value="inch")
        self.units_combo = ttk.Combobox(cfg, textvariable=self.units_var, state="readonly", width=8, values=["inch", "mm"])
        self.units_combo.grid(row=0, column=1, padx=(6, 14))
        self.units_combo.bind("<<ComboboxSelected>>", lambda e: self._write_config())
        ttk.Checkbutton(cfg, text="Enable Jog", variable=self.enable_jog_var,
                        command=self._on_jog_safety_changed).grid(row=0, column=2, padx=(0, 6))

        self.jog_step_xy = tk.DoubleVar(value=0.1)
        self.jog_step_z = tk.DoubleVar(value=0.1)

        self.step_preset_row_xy = ttk.Frame(jog_body, style="CardBody.TFrame")
        self.step_preset_row_xy.grid(row=1, column=0, sticky="w", pady=(6, 8))
        self._build_step_preset_buttons()

        pad = ttk.Frame(jog_body, style="CardBody.TFrame")
        pad.grid(row=2, column=0, pady=(0, 8))

        self.btn_jog_yp = ttk.Button(pad, text="Y+", width=8, style="JogY.TButton")
        self.btn_jog_xm = ttk.Button(pad, text="X-", width=8, style="JogX.TButton")
        self.btn_jog_xp = ttk.Button(pad, text="X+", width=8, style="JogX.TButton")
        self.btn_jog_ym = ttk.Button(pad, text="Y-", width=8, style="JogY.TButton")

        self.btn_jog_yp.grid(row=0, column=1, padx=6, pady=6)
        self.btn_jog_xm.grid(row=1, column=0, padx=6, pady=6)
        ttk.Label(pad, text="XYZ", style="Card.TLabel").grid(row=1, column=1, padx=6, pady=6)
        self.btn_jog_xp.grid(row=1, column=2, padx=6, pady=6)
        self.btn_jog_ym.grid(row=2, column=1, padx=6, pady=6)
        self.btn_jog_cancel = ttk.Button(pad, text="Jog Cancel", style="Hold.TButton", command=self.jog_cancel)
        self.btn_jog_cancel.grid(row=0, column=3, rowspan=3, sticky="ns", padx=(12, 0), pady=6)

        self.step_preset_row_z = ttk.Frame(jog_body, style="CardBody.TFrame")
        self.step_preset_row_z.grid(row=3, column=0, pady=(0, 6))
        self._build_step_preset_buttons()

        zrow = ttk.Frame(jog_body, style="CardBody.TFrame")
        zrow.grid(row=4, column=0, pady=(0, 8))
        zrow.grid_columnconfigure(0, weight=0)
        zrow.grid_columnconfigure(1, weight=0)

        self.btn_jog_zm = ttk.Button(zrow, text="Z-", style="JogZ.TButton")
        self.btn_jog_zp = ttk.Button(zrow, text="Z+", style="JogZ.TButton")
        self.btn_jog_zm.grid(row=0, column=0, padx=(0, 6))
        self.btn_jog_zp.grid(row=0, column=1, padx=(6, 0))

        mgrid = ttk.Frame(jog_body, style="CardBody.TFrame")
        mgrid.grid(row=6, column=0, pady=(0, 10))
        for c in range(2):
            mgrid.grid_columnconfigure(c, weight=0, uniform="jogcols")

        self.macro_buttons: list[ttk.Button] = []
        for i in range(8):
            n = i + 1
            btn = ttk.Button(mgrid, text=f"Macro {n}", width=jog_btn_width, command=lambda k=n: self.run_macro_file(k))
            col = i % 2
            padx = (0, 6) if col == 0 else (6, 0)
            btn.grid(row=i // 2, column=col, sticky="ew", padx=padx, pady=6)
            self.macro_buttons.append(btn)

        self._jog_button_map = {
            self.btn_jog_yp: ("Y", +1),
            self.btn_jog_xm: ("X", -1),
            self.btn_jog_xp: ("X", +1),
            self.btn_jog_ym: ("Y", -1),
            self.btn_jog_zm: ("Z", -1),
            self.btn_jog_zp: ("Z", +1)
        }
        self._configure_jog_button_behavior()

    def open_settings(self):
        SettingsWindow(self)

    def _sync_presets_for_units(self):
        pass

    def refresh_macro_labels(self):
        for idx in range(1, 9):
            path = self.macros_dir / f"macro-{idx}.txt"
            btn = self.macro_buttons[idx - 1]
            try:
                name, lines = load_macro_with_name(path)
                if lines:
                    btn.config(text=self._ellipsis(name, 22))
                    btn._has_macro = True  # type: ignore
                else:
                    btn.config(text=f"(empty {idx})")
                    btn._has_macro = False  # type: ignore
            except Exception:
                btn.config(text=f"(missing {idx})")
                btn._has_macro = False  # type: ignore

        self._log(f"[info] Macro names loaded from: {self.macros_dir}")
        self._apply_mode(self.ui_mode)

    def _state_flags(self):
        st = (self.last_grbl_state or "-").strip()
        upper = st.upper()
        is_alarm = upper.startswith("ALARM")
        is_door = st == "Door"
        is_idle = st == "Idle"
        is_run = st in ("Run", "Jog", "Cycle")
        return {"state": st, "is_alarm": is_alarm, "is_door": is_door, "is_run": is_run, "is_idle": is_idle}

    def _apply_mode(self, mode: str):
        self.ui_mode = mode
        flags = self._state_flags()

        def set_state(widget, enabled: bool):
            widget.config(state=("normal" if enabled else "disabled"))

        connected = (mode != "disconnected")
        idle = (mode == "idle")
        running = (mode == "running")
        paused = (mode == "paused")
        hold = (mode == "hold")

        set_state(self.btn_connect, not connected)
        set_state(self.btn_disconnect, connected)
        set_state(self.btn_settings, True)

        set_state(self.btn_upload, connected and idle and flags["is_idle"])

        set_state(self.btn_start, connected and idle and flags["is_idle"] and self.current_job_total_lines > 0)
        set_state(self.btn_pause, connected and running)
        set_state(self.btn_hold, connected and running)
        set_state(self.btn_resume, connected and (paused or hold))
        set_state(self.btn_cancel, connected and (running or paused or hold))

        can_jog = connected and idle and flags["is_idle"] and bool(self.enable_jog_var.get())
        for b in (self.btn_jog_xm, self.btn_jog_xp, self.btn_jog_ym, self.btn_jog_yp, self.btn_jog_zm, self.btn_jog_zp):
            set_state(b, can_jog)
        set_state(self.btn_jog_cancel, connected)

        set_state(self.btn_home_all, connected and idle and (flags["is_idle"] or flags["is_alarm"]))
        can_unlock = connected and (flags["is_alarm"] or flags["is_door"])
        set_state(self.btn_unlock, can_unlock)
        for b in (self.btn_reset_wpos, self.btn_set_wpos_x, self.btn_set_wpos_y, self.btn_set_wpos_z):
            set_state(b, connected and idle and flags["is_idle"])

        can_macro = connected and idle and flags["is_idle"]
        for b in self.macro_buttons:
            has = getattr(b, "_has_macro", False)
            set_state(b, can_macro and bool(has))

        set_state(self.cmd_entry, connected and idle)
        set_state(self.btn_send_cmd, connected and idle)
        set_state(self.btn_clear_console, True)

        if not connected:
            self.active_mode_var.set("Active: -")
            self.device_info_var.set("Device: -")
            self.grbl_id_var.set("GRBL: -")
            self.big_state_var.set("DISCONNECTED")
            self.indicators.set_all_off()
            self._set_status_banner("Disconnected", "info")
            self.job_line_var.set("Line: -")

        if hasattr(self, "feed_override_scale"):
            set_state(self.feed_override_scale, connected)
            set_state(self.spindle_override_scale, connected)
            set_state(self.btn_feed_reset, connected)
            set_state(self.btn_spindle_reset, connected)

    def connect(self):
        if self.worker:
            return

        port = self._cfg.get("port_device", "")
        if not port:
            messagebox.showerror("No port configured", "Open Settings and select a serial port.")
            return

        baud = int(self._cfg.get("baud", 115200))
        rx_total = int(self._cfg.get("rx_buffer_bytes", DEFAULT_GRBL_RX_BUFFER_BYTES))
        use_bf = bool(self._cfg.get("use_bf_autosize", True))
        use_planner_throttle = bool(self._cfg.get("use_planner_throttle", True))
        planner_free_min = int(self._cfg.get("planner_free_min", 2))
        cancel_unlock = bool(self._cfg.get("cancel_unlock", False))

        self.worker = GrblWorker(
            port=port,
            baud=baud,
            rx_buffer_total=rx_total,
            use_bf_autosize=use_bf,
            use_planner_throttle=use_planner_throttle,
            planner_free_min=planner_free_min,
            cancel_unlock=cancel_unlock,
            sync_timeout_s=self.sync_timeout_s,
            homing_sync_timeout_s=self.homing_sync_timeout_s,
            system_sync_timeout_s=self.system_sync_timeout_s,
            tx_queue=self.tx_queue,
            ui_queue=self.ui_queue
        )
        self.worker.start()
        self._log(f"Connecting to {port} @ {baud} ... (RX total={rx_total}, Bf autosize={use_bf})")
        self._apply_mode("idle")
        self._write_config()

    def disconnect(self):
        if not self.worker:
            return
        if not messagebox.askyesno("Confirm disconnect", "Disconnect from GRBL now?"):
            return
        if getattr(self, "_disconnecting", False):
            return
        self._disconnecting = True
        try:
            self.worker.running = False
        except Exception:
            pass
        self.tx_queue.put(("shutdown",))
        self._log("Disconnect requested.")
        self._poll_disconnect_complete()

    def _poll_disconnect_complete(self):
        if self.worker and self.worker.is_alive():
            self.after(100, self._poll_disconnect_complete)
            return
        self.worker = None
        self._disconnecting = False
        self.last_grbl_state = "-"
        self.device_info_var.set("Device: -")
        self.grbl_id_var.set("GRBL: -")
        self.gcode_view.highlight_line(0)
        self.indicators.set_all_off()
        self._apply_mode("disconnected")

    def load_file(self):
        if self.ui_mode != "idle":
            return

        initdir = getattr(self, "_last_upload_dir", "")
        path = filedialog.askopenfilename(
            initialdir=initdir if initdir else None,
            filetypes=[("G-code", "*.nc *.gcode *.tap *.txt"), ("All", "*.*")]
        )
        if not path:
            return

        try:
            total = sanitize_file_to_current_job(path, str(self.current_job_path))
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return

        self._last_upload_dir = str(Path(path).parent)
        self._cfg["last_upload_dir"] = self._last_upload_dir
        self.current_job_total_lines = total
        self.job_label_var.set(f"Loaded: current-job.gcode ({total} lines)")
        self._log(f"Saved sanitized job to: {self.current_job_path}")
        self.progress["value"] = 0
        self.progress["maximum"] = max(1, total)
        self._apply_mode("idle")
        self._write_config()

        try:
            self.current_job_lines = self.current_job_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            self.current_job_lines = []
        self.gcode_view.load_lines(self.current_job_lines)

    def start_job(self):
        if not self.worker:
            messagebox.showerror("Not connected", "Connect to GRBL first.")
            return
        if self.current_job_total_lines <= 0 or not self.current_job_path.exists():
            messagebox.showerror("No job", "Load a G-code file first.")
            return
        if (self.last_grbl_state or "") != "Idle":
            messagebox.showerror("Not idle", f"GRBL is not Idle (state={self.last_grbl_state}).")
            return

        mode = self.get_stream_mode_value()
        self.tx_queue.put(("start_job_file", str(self.current_job_path), int(self.current_job_total_lines), mode))
        self._apply_mode("running")

    def pause_job(self):
        if self.worker and self.ui_mode == "running":
            self.tx_queue.put(("realtime", RT_HOLD))
            self.tx_queue.put(("pause_local",))
            self._apply_mode("paused")

    def stop_gentle(self):
        if self.worker and self.ui_mode == "running":
            self.tx_queue.put(("realtime", RT_HOLD))
            self.tx_queue.put(("hold_local",))
            self._apply_mode("hold")

    def resume_job(self):
        if self.worker and self.ui_mode in ("paused", "hold"):
            self.tx_queue.put(("realtime", RT_RESUME))
            self.tx_queue.put(("resume_local",))
            self._apply_mode("running")

    def soft_reset(self):
        if self.worker:
            if not messagebox.askyesno("Confirm soft reset", "Send Ctrl-X (soft reset) now?"):
                return
            self.active_mode_var.set("Active: -")
            self.progress["value"] = 0
            self.gcode_view.highlight_line(0)
            self.tx_queue.put(("soft_reset",))
            self._apply_mode("idle")

    def cancel_job(self):
        if self.worker:
            if not messagebox.askyesno("Confirm cancel", "Cancel the current job?"):
                return
            self.tx_queue.put(("cancel_job",))
            self.gcode_view.highlight_line(0)
            self._apply_mode("idle")

    def home_all(self):
        if not self.worker:
            return
        if not messagebox.askyesno("Confirm homing", "Home all axes ($H)?"):
            return
        self.send_line("$H")

    def unlock(self):
        self.send_line("$X")

    def reset_wpos_to_mpos(self):
        if not self.worker:
            return
        if not messagebox.askyesno("Confirm WPOS update", "Set WPOS to current MPOS for all axes?"):
            return
        if not self._last_mpos:
            messagebox.showerror("Position unknown", "No MPos data yet; wait for status and try again.")
            return
        x, y, z = self._last_mpos
        self.send_line(f"G10 L2 P0 X{x:.3f} Y{y:.3f} Z{z:.3f}")
        self._log("[info] Set WCO to current MPos (WPos -> 0,0,0).")

    def clear_wpos(self):
        if not self.worker:
            return
        if not messagebox.askyesno("Confirm WPOS clear", "Set WPOS to 0 for all axes?"):
            return
        self.send_line("G10 L2 P0 X0 Y0 Z0")
        self._log("[info] WPOS cleared (G10 L2 P0 X0 Y0 Z0).")

    def set_wpos_axis(self, axis: str):
        axis = axis.upper()
        if axis not in ("X", "Y", "Z"):
            return
        if not messagebox.askyesno("Confirm WPOS update", f"Set WPOS {axis}=0?"):
            return
        self.send_line(f"G10 L20 P0 {axis}0")

    def jog_cancel(self):
        if self.worker:
            self.tx_queue.put(("realtime", RT_JOG_CANCEL))
            self._log("[rt] Jog Cancel")

    def clear_console(self):
        self.console.config(state="normal")
        self.console.delete("1.0", "end")
        self.console.config(state="disabled")

    def run_macro_file(self, macro_index: int):
        if not self.worker:
            messagebox.showerror("Not connected", "Connect to GRBL first.")
            return
        if self.ui_mode != "idle":
            return

        macro_path = self.macros_dir / f"macro-{macro_index}.txt"
        try:
            name, lines = load_macro_with_name(macro_path)
        except Exception as e:
            messagebox.showerror("Macro file missing/invalid", f"{macro_path}\n\n{e}")
            return

        if not lines:
            messagebox.showwarning("Empty macro", f"Macro file has no commands:\n{macro_path}")
            return

        self._log(f"Running macro {macro_index}: {name}  ({macro_path})")
        self.tx_queue.put(("run_lines_blocking", lines))

    def send_console_command(self):
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return
        self.cmd_var.set("")
        self._log(f"> {cmd}")

        low = cmd.lower()
        if low == ":status":
            self.tx_queue.put(("realtime", RT_STATUS))
            return
        if low == ":hold":
            self.tx_queue.put(("realtime", RT_HOLD))
            return
        if low == ":resume":
            self.tx_queue.put(("realtime", RT_RESUME))
            return
        if low == ":reset":
            self.tx_queue.put(("soft_reset",))
            return
        if low == ":jcancel":
            self.tx_queue.put(("realtime", RT_JOG_CANCEL))
            return

        self.send_line(cmd)

    def send_line(self, line: str):
        if not self.worker:
            return
        self.tx_queue.put(("line", line))

    def _set_state_style(self, st: str | None):
        if st and st.upper().startswith("ALARM"):
            self.machine_state_var.set(f"STATE: {st}  ALARM")
            self.big_state_var.set("ALARM")
        else:
            self.machine_state_var.set(f"STATE: {st if st else '-'}")
            self.big_state_var.set(st.upper() if st else "IDLE")

    def _poll_ui_queue(self):
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                kind = msg[0]

                if kind == "log":
                    self._log(msg[1])
                elif kind == "error":
                    self._log("[ERROR] " + msg[1])
                elif kind == "job_state":
                    self._apply_mode(msg[1])
                elif kind == "progress":
                    done, total = msg[1], msg[2]
                    self.progress["maximum"] = max(1, total)
                    self.progress["value"] = min(done, total if total else done)
                elif kind == "job_line":
                    sent = msg[1]
                    ack = msg[2] if len(msg) > 2 else 0
                    total = msg[3] if len(msg) > 3 else 0
                    self.gcode_view.highlight_lines(int(sent) if sent else 0, int(ack) if ack else 0)
                    if total:
                        self.job_line_var.set(f"Sent: {sent}/{total}  Ack: {ack}/{total}")
                    else:
                        self.job_line_var.set("Line: -")
                elif kind == "active_stream_mode":
                    mode = msg[1]
                    label = "-" if mode == "-" else ("sync (safe)" if mode == "sync" else "buffered (fast)")
                    self.active_mode_var.set(f"Active: {label}")
                elif kind == "port_info":
                    v = msg[1]
                    self.device_info_var.set(f"Device: {v}" if v and v != "-" else "Device: -")
                elif kind == "grbl_id":
                    v = msg[1] if msg[1] else "-"
                    self.grbl_id_var.set(f"GRBL: {self._ellipsis(v, 60) if v != '-' else '-'}")
                elif kind == "machine_state":
                    self.last_grbl_state = msg[1] if msg[1] else "-"
                    if self.ui_mode != "disconnected":
                        self._apply_mode(self.ui_mode)
                elif kind == "status":
                    status_line = msg[1]
                    self.raw_status_var.set(status_line)
                    self.indicators.update_from_status(status_line)
                    self._update_status_banner(status_line)

                    st = parse_state_from_status(status_line)
                    self._set_state_style(st)
                    self.last_grbl_state = st or self.last_grbl_state
                    if self.ui_mode != "disconnected":
                        self._apply_mode(self.ui_mode)

                    feed = parse_feed_from_status(status_line)
                    self.feed_var.set(f"FEED: {feed if feed is not None else '-'}")

                    mpos = parse_vec3(parse_field(status_line, "MPos:"))
                    wpos = parse_vec3(parse_field(status_line, "WPos:"))
                    wco  = parse_vec3(parse_field(status_line, "WCO:"))
                    if mpos is not None:
                        self._last_mpos = mpos
                    if wco is not None:
                        self._last_wco = wco
                    if wpos is None:
                        wpos = compute_wpos(mpos, wco)

                    self.dro_machine.set_xyz(mpos)
                    self.dro_work.set_xyz(wpos)

        except queue.Empty:
            pass

        self.after(50, self._poll_ui_queue)

    def _log(self, text: str):
        self.console.config(state="normal")
        self.console.insert("end", text + "\n")
        self.console.see("end")
        max_lines = 2000
        try:
            line_count = int(self.console.index("end-1c").split(".", 1)[0])
        except Exception:
            self.console.config(state="disabled")
            return
        if line_count > max_lines:
            self.console.delete("1.0", f"{line_count - max_lines + 1}.0")
        self.console.config(state="disabled")


if __name__ == "__main__":
    App().mainloop()
