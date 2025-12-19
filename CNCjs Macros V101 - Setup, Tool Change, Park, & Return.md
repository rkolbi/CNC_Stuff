# CNCjs Advanced Workflow: Workpiece Setup, Tool Change & Park Macros

------

## 📘 Macro System Overview

This workflow uses **six coordinated CNCjs macros**, each with a specific purpose. Together, they provide a safe, repeatable method for establishing work zero, maintaining accurate Z across tool changes, and recovering `TOOL_REFERENCE` when needed.

### Coordinate model (important)

- **Assumes the machine is homed** and machine coordinates are valid before any `G53` move.
- **Work zero (job setup):** These macros establish work coordinates using `G92` *(a temporary coordinate shift applied in the currently active WCS, e.g., G54)*.
  - **Important:** `G92` is temporary (it is not stored like `G54` values).
  - **Note:** If CNCjs/GRBL resets or restarts (or you power-cycle), you will lose the `G92` shift (and likely `TOOL_REFERENCE`). Re-run the appropriate setup macro (or use **MACRO 1R** if the reference tool is installed).
- **Fixed sensor travel:** `G53` moves are used **only** to travel to the fixed tool sensor in **machine coordinates**.
- **Tool-change Z preservation:** During tool changes, the macros preserve Z consistency by applying the stored `TOOL_REFERENCE` using `G10 L20` (without re-probing the workpiece).
- **SAFE_HEIGHT meaning:** **SAFE_HEIGHT is a machine-Z height** used with `G53` and must clear clamps/fixtures everywhere on the table.

### Reference tool (definition)

The **reference tool** is the tool you treat as the baseline for the job (often Tool #1). It is measured once at the fixed sensor to establish `TOOL_REFERENCE`.

### Operator rules (do not skip)

✅ **Do not run MACRO 2 unless `TOOL_REFERENCE` already exists** (created by **MACRO 1** or **MACRO 1Z**, or recovered by **MACRO 1R**).
✅ **Do not run both MACRO 1 and MACRO 1Z for the same job.** Choose the one that matches your setup.

------

### **MACRO 1 — XYZ Touch Plate & Reference Tool (Standard Setup)**

**Purpose:** Establishes job zero and creates the reference-tool baseline.

- Probes **Z, then X and Y** using the touch plate.
- Sets **workpiece X0/Y0/Z0** at the chosen corner/edge.
- Moves to the fixed tool-height sensor.
- Measures the installed **reference tool**.
- Stores the sensor contact point as machine Z: `TOOL_REFERENCE`.

**Run:** Once at the start of each job (when X/Y probing is possible).

------

### **MACRO 1Z — Z-Only Touch Plate & Reference Tool (Manual XY Setup)**

**Purpose:** Establishes Z zero and the same reference-tool baseline when X/Y probing isn’t practical.

- Operator manually sets **X=0 / Y=0** in the **currently active WCS**.
- Probes **ONLY Z** using the touch plate.
- Moves to the fixed tool-height sensor.
- Measures the installed **reference tool**.
- Stores the sensor contact point as machine Z: `TOOL_REFERENCE`.

**Run:** Once at the start of each job **only** when X/Y probing is not possible (round/irregular stock, inaccessible edges).

**Behavior note:**
MACRO 1Z returns to the **location where the macro was started** (typically your **flat Z-probing spot**), which may be different from the project’s XY origin **where you set X0/Y0**.

------

### **When to Use MACRO 1 vs MACRO 1Z**

- Use **MACRO 1** when the material has reliable, **probeable** X/Y edges (square/rectangular stock, known corner).
- Use **MACRO 1Z** when X/Y probing isn’t possible (round stock, irregular/live-edge material, or obstructed edges) and you will set X/Y manually.

------

### **MACRO 2 — Tool Change (Preserve Work Z Using TOOL_REFERENCE)**

**Purpose:** Enables tool swaps **without re-probing the workpiece**, while keeping the original work Z-zero correct.

- Moves to the fixed tool-height sensor and stops the spindle.
- Prompts the operator to change the tool.
- Probes the **new tool** on the fixed sensor.
- Preserves the correct Z relationship by setting the active WCS Z to the stored `TOOL_REFERENCE` using `G10 L20`.

**Run:** Every time a new tool is inserted during the job.
**Prerequisite:** `TOOL_REFERENCE` must already exist from **MACRO 1** or **MACRO 1Z** (or be restored using **MACRO 1R**).

------

### **MACRO 3 — Park at Tool Sensor**

**Purpose:** Safely moves to the tool sensor without changing offsets.

Use this for cleaning, inspection, or staging before a manual tool swap.

------

### **MACRO 4 — Safe Return to Work Zero**

**Purpose:** Raises to **SAFE_HEIGHT** in machine coordinates, then returns to **X0 Y0** in work coordinates **without changing offsets**.

------

### **MACRO 1R — Reference Tool Recovery (Sensor Only, Recovery Use)**

**Purpose:** Restores `TOOL_REFERENCE` **without re-probing the workpiece**.

- Runs only if `TOOL_REFERENCE` does not already exist.
- Measures the **current tool** on the fixed sensor and stores it as `TOOL_REFERENCE`.

⚠️ Use only when the tool currently installed is the original **reference tool** from **MACRO 1 / MACRO 1Z**.

------



## 🚦 Operator Workflow Overview

This section describes how to use the macros during a typical job.

------

### 🔧 1) Before Starting Any Job

1. Clamp material securely.
2. Install the **reference tool** (your baseline tool for the job).
3. Ensure the touch plate and clip are ready.
4. Verify the fixed tool-height sensor is clean and unobstructed.
5. Confirm **SAFE_HEIGHT** is truly safe for your machine, clamps, and fixtures.
6. Confirm the machine is **homed** so `G53` moves are safe and accurate.

------

### ▶️ 2) Choose Your Setup Macro (MACRO 1 *or* MACRO 1Z)

#### ✅ If your material has probeable X/Y edges (square/rectangular stock, known corner)

Run **MACRO 1 — XYZ Touch Plate & Reference Tool**:

- Probes Z, X, and Y with the touch plate
- Sets X0/Y0/Z0 automatically
- Measures the reference tool on the fixed sensor and stores `TOOL_REFERENCE`

#### ✅ If your material cannot be probed in X/Y (round stock, irregular/live-edge, inaccessible edges)

Run **MACRO 1Z — Z-Only Touch Plate & Reference Tool**:

Operator steps first:

- Jog to your project’s intended XY zero and **set X=0 / Y=0 manually** in the **currently active WCS**.
- Jog to a safe flat area for Z probing.

Then run **MACRO 1Z**:

- Probes **ONLY Z** with the touch plate
- Measures the reference tool on the fixed sensor and stores `TOOL_REFERENCE`

⚠️ **Do not run both MACRO 1 and MACRO 1Z for the same job.**

------

### ▶️ 3) Begin Cutting

- Start your job normally using the reference tool.
- Run your G-code until a tool change is required.

------

### ▶️ 4) Tool Changes During the Job

When the job calls for a new tool, run **MACRO 2 — Tool Change**:

- The macro moves to the fixed sensor and stops the spindle
- You swap the tool
- The macro probes the new tool on the sensor
- The macro preserves the original work Z-zero using `G10 L20` and `TOOL_REFERENCE`

Repeat **MACRO 2** for every tool change.

------

### ▶️ 5) Optional: Parking and Returning

Use these any time during setup or between operations:

- **MACRO 3 — Park at Tool Sensor**
  Moves to the sensor area for inspection/cleaning/staging without changing offsets.
- **MACRO 4 — Safe Return to Work Zero**
  Raises to **SAFE_HEIGHT**, then returns to **X0 Y0** in work coordinates without modifying offsets.

------

### ▶️ 6) Recovery Only (If TOOL_REFERENCE Is Lost)

If CNCjs restarts, power cycles, or `TOOL_REFERENCE` is missing:

Run **MACRO 1R — Reference Tool Recovery** **only if**:

- `TOOL_REFERENCE` does not exist, **and**
- The tool currently installed **is the original reference tool**

**MACRO 1R:**

- Re-measures the current tool on the fixed sensor
- Restores `TOOL_REFERENCE`
- Does **not** alter workpiece zero

⚠️ Never run **MACRO 1R** with a non-reference tool installed.





---

# 🔧 **MACRO 1 — XYZ-Touch Plate & Reference Tool**

```gcode
; ==============================================================================
; MACRO: Touch Plate and Tool Height Reference
; VERSION: 1.01
; DESCRIPTION: Probes XYZ on Touch plate, then measures tool height on fixed sensor.
; Tool Height Reference based on neilferreri's work authored on Jul 14, 2019
; https://github.com/cncjs/CNCjs-Macros/tree/master/Initial%20%26%20New%20Tool
; ==============================================================================

; ==============================================================================
; USER CONFIGURATION
; ==============================================================================
;XYZ Probe Plate settings
%global.state.PLATE_THICKNESS = 11.95 ; Increasing drives bit closer to work piece
%global.state.Z_FAST_PROBE_DISTANCE = 50
%global.state.X_PLATE_OFFSET = -13.175
%global.state.Y_PLATE_OFFSET = -13.175

; Tool-Height settings
%global.state.SAFE_HEIGHT = -5
%global.state.PROBE_X_LOCATION = -1.5
%global.state.PROBE_Y_LOCATION = -1224
%global.state.PROBE_Z_LOCATION = -5
%global.state.PROBE_DISTANCE = 150
%global.state.PROBE_RAPID_FEEDRATE = 200

%wait
; ==============================================================================

M0 (Ensure Touch Plate is in place and Clip is attached to bit before proceeding.)

; ==============================================================================
; Initialize & Set Temporary Zero
; ==============================================================================
G90                                 ; Absolute positioning
G21                                 ; Metric
G92 X0 Y0                           ; Set current position as temporary XY zero

; ==============================================================================
; Probe Z (Touch Plate)
; ==============================================================================
; Fast probe
G91                                 ; Relative positioning
G38.2 Z-[global.state.Z_FAST_PROBE_DISTANCE] F150 ; Probe Z down towards plate
G90                                 ; Absolute positioning
G92 Z[global.state.PLATE_THICKNESS] ; Set Z coordinate to plate thickness
G1 Z14                              ; Linear move up to Z14
; Slow probe
G91                                 ; Relative positioning
G38.2 Z-15 F40                      ; Probe Z down slowly for accuracy
G0 Z2                               ; Rapid retract Z by 2mm
G4 P.25                             ; Dwell
G38.2 Z-3 F20                       ; second accuracy pass
G90                                 ; Absolute positioning
G92 Z[global.state.PLATE_THICKNESS] ; Reset Z coordinate to plate thickness
G0 Z16                              ; Rapid move up to safe Z

; ==============================================================================
; Probe X (Touch Plate)
; ==============================================================================
G0 X-70 F800                        ; Rapid move to X approach position
G0 Z4                               ; Rapid move down to probing height
G38.2 X0 F170                       ; Probe X towards plate
G92 X[global.state.X_PLATE_OFFSET]  ; Set X coordinate (compensating for plate width)
G1 X-14                             ; Linear move back from plate

G38.2 X0 F60                        ; Probe X slowly for accuracy
G92 X[global.state.X_PLATE_OFFSET]  ; Reset X coordinate
G0 X-15                             ; Rapid move back to clear plate

; ==============================================================================
; Probe Y (Touch Plate)
; ==============================================================================
G0 Z16                              ; Rapid move up to safe Z
G0 X30 Y-70 F800                    ; Rapid move to Y approach position
G0 Z4                               ; Rapid move down to probing height
G38.2 Y0 F170                       ; Probe Y towards plate
G92 Y[global.state.Y_PLATE_OFFSET]  ; Set Y coordinate (compensating for plate width)
G1 Y-14                             ; Linear move back from plate

G38.2 Y0 F60                        ; Probe Y slowly for accuracy
G92 Y[global.state.Y_PLATE_OFFSET]  ; Reset Y coordinate

; ==============================================================================
; Return to Work Zero
; ==============================================================================
G0 Y-15                             ; Rapid move back to clear plate
G0 Z20                              ; Rapid move Z up to safe height
G0 X0 Y0                            ; Rapid move to X0 Y0 work zero

M0 (Stow Touch Plate and Clip. Tool height will be checked next.)
%wait

; ==============================================================================
; Save State & Position
; ==============================================================================
%X0 = posx, Y0 = posy, Z0 = posz

%WCS = modal.wcs
%PLANE = modal.plane
%UNITS = modal.units
%DISTANCE = modal.distance
%FEEDRATE = modal.feedrate
%SPINDLE = modal.spindle
%COOLANT = modal.coolant

; ==============================================================================
; Move to Fixed Sensor (Machine Coordinates)
; ==============================================================================
G21                                 ; Metric
M5                                  ; Stop spindle
G90                                 ; Absolute positioning

G53 G0 Z[global.state.SAFE_HEIGHT]  ; Move Z to safe height in Machine Coordinates
G53 X[global.state.PROBE_X_LOCATION] Y[global.state.PROBE_Y_LOCATION] ; Move XY to sensor in Machine Coordinates
%wait

G53 Z[global.state.PROBE_Z_LOCATION]; Move Z down to approach height in Machine Coordinates

; ==============================================================================
; Measure Tool Reference
; ==============================================================================
G91                                 ; Relative positioning
G38.2 Z-[global.state.PROBE_DISTANCE] F[global.state.PROBE_RAPID_FEEDRATE] ; Fast probe Z towards sensor
G0 Z2                               ; Rapid retract Z by 2mm
G4 P.25                             ; Dwell
G38.2 Z-5 F40                       ; Slow probe Z for accuracy
G4 P.25                             ; Dwell (pause) for 0.25 seconds
G38.4 Z10 F20                       ; Probe Z away (verify switch release)
G4 P.25                             ; Dwell
G38.2 Z-2 F5                        ; Very slow probe Z for final accuracy
G4 P.25                             ; Dwell
G38.4 Z10 F5                        ; Very slow probe Z away
G90                                 ; Absolute positioning
%global.state.TOOL_REFERENCE = posz ; Store current Z machine position
%wait
(TOOL_REFERENCE = [global.state.TOOL_REFERENCE])

; ==============================================================================
; Cleanup & Restore
; ==============================================================================
G91                                 ; Relative positioning
G0 Z5                               ; Rapid retract Z by 5mm
G90                                 ; Absolute positioning
G53 Z[global.state.SAFE_HEIGHT]     ; Rapid move Z to safe height in Machine Coordinates
%wait

G0 X0 Y0                            ; Rapid move to X0 Y0 work zero

; Restore Modal State
[WCS] [PLANE] [UNITS] [DISTANCE] [FEEDRATE] [SPINDLE] [COOLANT]
````
------

# 🔧 **MACRO 1Z — Z-Touch Plate & Reference Tool**

```gcode
; =============================================================================
; MACRO: Z-ONLY Touch Plate and Tool Height Reference / VERSION: 1.01Z
; DESCRIPTION: Operator manually sets X/Y. Macro probes ONLY Z on touch plate,
;              then measures tool height on fixed sensor.
; Tool Height Reference based on neilferreri's work authored on Jul 14, 2019
; https://github.com/cncjs/CNCjs-Macros/tree/master/Initial%20%26%20New%20Tool
; ==============================================================================

; ==============================================================================
; USER CONFIGURATION
; ==============================================================================
; Z Probe Plate settings
%global.state.PLATE_THICKNESS = 11.95             ; Increasing drives bit closer to work piece
%global.state.Z_FAST_PROBE_DISTANCE = 50

; Tool-Height settings (Machine Coordinates / G53)
%global.state.SAFE_HEIGHT = -5                    ; Machine Z safe height (G53)
%global.state.PROBE_X_LOCATION = -1.5             ; Machine X location of fixed sensor (G53)
%global.state.PROBE_Y_LOCATION = -1224            ; Machine Y location of fixed sensor (G53)
%global.state.PROBE_Z_LOCATION = -5               ; Machine Z approach height above sensor (G53)
%global.state.PROBE_DISTANCE = 150                ; Max probe travel toward sensor
%global.state.PROBE_RAPID_FEEDRATE = 200

%wait
; ==============================================================================

M0 (Jog to your project's XY zero and set X=0 / Y=0 manually. Then jog to a flat area for Z probing, place the touch plate under the bit, attach the clip, and proceed.)

; ==============================================================================
; Initialize
; ==============================================================================
G90                                 ; Absolute positioning
G21                                 ; Metric

; Save current work position (so we can return to the start XY)
%X0 = posx, Y0 = posy

; ==============================================================================
; Probe Z ONLY (Touch Plate)
; ==============================================================================
; Fast probe
G91                                 ; Relative positioning
G38.2 Z-[global.state.Z_FAST_PROBE_DISTANCE] F150 ; Probe Z down towards plate
G90                                 ; Absolute positioning
G92 Z[global.state.PLATE_THICKNESS] ; Set Z coordinate to plate thickness
G1 Z14                              ; Linear move up to Z14

; Slow probe for accuracy
G91                                 ; Relative positioning
G38.2 Z-15 F40                      ; Probe Z down slowly for accuracy
G0 Z2                               ; Rapid retract Z by 2mm
G4 P.25                             ; Dwell
G38.2 Z-3 F20                       ; Second accuracy pass
G90                                 ; Absolute positioning
G92 Z[global.state.PLATE_THICKNESS] ; Reset Z coordinate to plate thickness
G0 Z16                              ; Rapid move up to safe Z

; ==============================================================================
; Retract and Stow
; ==============================================================================
G0 Z20                              ; Rapid move Z up to safe height

M0 (Stow touch plate and clip. Tool height will be checked next.)
%wait

; ==============================================================================
; Save Modal State
; ==============================================================================
%WCS = modal.wcs
%PLANE = modal.plane
%UNITS = modal.units
%DISTANCE = modal.distance
%FEEDRATE = modal.feedrate
%SPINDLE = modal.spindle
%COOLANT = modal.coolant

; ==============================================================================
; Move to Fixed Sensor (Machine Coordinates)
; ==============================================================================
G21                                 ; Metric
M5                                  ; Stop spindle
G90                                 ; Absolute positioning

G53 G0 Z[global.state.SAFE_HEIGHT]  ; Move Z to safe height in Machine Coordinates
G53 X[global.state.PROBE_X_LOCATION] Y[global.state.PROBE_Y_LOCATION] ; Move XY to sensor in Machine Coordinates
%wait

G53 Z[global.state.PROBE_Z_LOCATION]; Move Z down to approach height in Machine Coordinates

; ==============================================================================
; Measure Tool Reference
; ==============================================================================
G91                                 ; Relative positioning
G38.2 Z-[global.state.PROBE_DISTANCE] F[global.state.PROBE_RAPID_FEEDRATE] ; Fast probe Z towards sensor
G0 Z2                               ; Rapid retract Z by 2mm
G4 P.25                             ; Dwell
G38.2 Z-5 F40                       ; Slow probe Z for accuracy
G4 P.25                             ; Dwell
G38.4 Z10 F20                       ; Probe Z away (verify switch release)
G4 P.25                             ; Dwell
G38.2 Z-2 F5                        ; Very slow probe Z for final accuracy
G4 P.25                             ; Dwell
G38.4 Z10 F5                        ; Very slow probe Z away
G90                                 ; Absolute positioning

%global.state.TOOL_REFERENCE = posz  ; Store current Z machine position
%wait
(TOOL_REFERENCE = [global.state.TOOL_REFERENCE])

; ==============================================================================
; Cleanup & Return (Keep Z High, Return to Start XY)
; ==============================================================================
G91                                 ; Relative positioning
G0 Z5                               ; Rapid retract Z by 5mm
G90                                 ; Absolute positioning
G53 Z[global.state.SAFE_HEIGHT]     ; Rapid move Z to safe height in Machine Coordinates
%wait

G0 X[X0] Y[Y0]                      ; Return to the XY position where macro was started (work coordinates)

; ==============================================================================
; Restore Modal State
; ==============================================================================
[WCS] [PLANE] [UNITS] [DISTANCE] [FEEDRATE] [SPINDLE] [COOLANT]
````
------

# 🔧 **MACRO 2 — Tool Change**

```gcode
; ==============================================================================
; MACRO: Tool Change Routine
; VERSION: 1.01
; DESCRIPTION: Moves to sensor, allows tool swap, measures new length, updates Offset.
; WARNING: Run "Touch Plate and Tool Height" macro BEFORE this one.
; Tool Height Reference based on neilferreri's work authored on Jul 14, 2019
; https://github.com/cncjs/CNCjs-Macros/tree/master/Initial%20%26%20New%20Tool
; ==============================================================================

; ==============================================================================
; USER CONFIGURATION
; ==============================================================================
; Tool-Height settings
%global.state.SAFE_HEIGHT = -5
%global.state.PROBE_X_LOCATION = -1.5
%global.state.PROBE_Y_LOCATION = -1224
%global.state.PROBE_Z_LOCATION = -5
%global.state.PROBE_DISTANCE = 150
%global.state.PROBE_RAPID_FEEDRATE = 200

%wait

; ==============================================================================
; Save State & Position
; ==============================================================================
%X0 = posx, Y0 = posy, Z0 = posz    ; Backup work position

; Capture Modal State
%WCS = modal.wcs
%PLANE = modal.plane
%UNITS = modal.units
%DISTANCE = modal.distance
%FEEDRATE = modal.feedrate
%SPINDLE = modal.spindle
%COOLANT = modal.coolant

; ==============================================================================
; Move to Tool Change Position (Machine Coordinates)
; ==============================================================================
G21                                 ; Metric
M5                                  ; Stop spindle
G90                                 ; Absolute positioning

G53 G0 Z[global.state.SAFE_HEIGHT]  ; Move Z to safe height in Machine Coordinates
G53 X[global.state.PROBE_X_LOCATION] Y[global.state.PROBE_Y_LOCATION] ; Move XY to sensor in Machine Coordinates
%wait

; ==============================================================================
; Manual Tool Swap
; ==============================================================================
M0 (Change Tool Now, press continue when done.)

; ==============================================================================
; Probe New Tool Length
; ==============================================================================
G53 Z[global.state.PROBE_Z_LOCATION]; Move Z down to approach height in Machine Coordinates
G91                                 ; Relative positioning
G38.2 Z-[global.state.PROBE_DISTANCE] F[global.state.PROBE_RAPID_FEEDRATE] ; Fast probe Z towards sensor
G0 Z2                               ; Rapid retract Z by 2mm
G4 P.25                             ; Dwell
G38.2 Z-5 F40                       ; Slow probe Z for accuracy
G4 P.25                             ; Dwell (pause) for 0.25 seconds
G38.4 Z10 F20                       ; Probe Z away (verify switch release)
G4 P.25                             ; Dwell
G38.2 Z-2 F5                        ; Very slow probe Z for final accuracy
G4 P.25                             ; Dwell
G38.4 Z10 F5                        ; Very slow probe Z away
G90                                 ; Absolute positioning
%wait

; ==============================================================================
; Apply Z-Offset
; ==============================================================================
; Updates Z zero based on the difference between the Reference tool and New tool.
G10 L20 Z[global.state.TOOL_REFERENCE] ; Set Work Coordinate Z to match Reference
%wait

; ==============================================================================
; Retract & Restore
; ==============================================================================
G91                                 ; Relative positioning
G0 Z5                               ; Rapid retract Z by 5mm
G90                                 ; Absolute positioning
G53 Z[global.state.SAFE_HEIGHT]     ; Rapid move Z to safe height in Machine Coordinates
%wait

G0 X0 Y0                            ; Rapid move to X0 Y0 work zero

; Restore Modal State
[WCS] [PLANE] [UNITS] [DISTANCE] [FEEDRATE] [SPINDLE] [COOLANT]
```

------

# 🔧 **MACRO 3 — Park at Tool Sensor**

```gcode
; ============================================================================
; MACRO 3: Park at Tool Sensor / VERSION: 1.01
; ============================================================================

; ==============================================================================
; USER CONFIGURATION
; ==============================================================================
%global.state.SAFE_HEIGHT = -5
%global.state.PROBE_X_LOCATION = -1.5
%global.state.PROBE_Y_LOCATION = -1224


M5 (Ensuring spindle is stopped.)

G21
G90

; Raise to safe machine Z
G53 G0 Z[global.state.SAFE_HEIGHT]  ; Move Z to safe height in Machine Coordinates

; Go to tool height sensor
G53 G0 X[global.state.PROBE_X_LOCATION] Y[global.state.PROBE_Y_LOCATION] ; Move XY to sensor in Machine Coordinates
```

------

# 🔧 **MACRO 4 — Return to Work**

```gcode
; ============================================================================
; MACRO 4: Return to Work / VERSION: 1.01
; ============================================================================

; ==============================================================================
; USER CONFIGURATION
; ==============================================================================
%global.state.SAFE_HEIGHT = -5            ; Tool-Height setting


M5 (Ensuring spindle is stopped.)
G21
G90

; Raise to safe machine Z
G53 G0 Z[global.state.SAFE_HEIGHT]  ; Move Z to safe height in Machine Coordinates

; Go to work zero
G0 X0 Y0
```

------

# 🔧 **MACRO 1R — Reference Tool Recovery**

```gcode
; ==============================================================================
; MACRO 1r: Reference Tool Recovery (Sensor Only) / VERSION: 1.02 (GRBL-safe)
; DESCRIPTION:
;   Re-establish TOOL_REFERENCE using the current tool at the fixed sensor.
;   Only runs if TOOL_REFERENCE does NOT already exist.
;   For GRBL 1.1 — NO modal probe checks included.
; ==============================================================================

; ==============================================================================
; SAFETY CHECK - Abort if TOOL_REFERENCE already exists
; ==============================================================================
%if global.state.TOOL_REFERENCE != null
    (ERROR: TOOL_REFERENCE already exists!)
    (Current TOOL_REFERENCE = [global.state.TOOL_REFERENCE])
    (To overwrite it, CLEAR it manually first:)
    (Use: %global.state.TOOL_REFERENCE = null)
    M0 (TOOL REFERENCE ALREADY EXISTS - Abort Macro.)
    %return
%endif

; ==============================================================================
; USER CONFIGURATION (matches Macro 1 settings)
; ==============================================================================
%global.state.SAFE_HEIGHT = -5
%global.state.PROBE_X_LOCATION = -1.5
%global.state.PROBE_Y_LOCATION = -1224
%global.state.PROBE_Z_LOCATION = -5
%global.state.PROBE_DISTANCE = 100
%global.state.PROBE_RAPID_FEEDRATE = 200


%wait

M0 (This will SET TOOL_REFERENCE using the CURRENT tool.)

; ==============================================================================
; Save State & Position
; ==============================================================================
%X0 = posx, Y0 = posy, Z0 = posz

; Capture Modal State
%WCS = modal.wcs
%PLANE = modal.plane
%UNITS = modal.units
%DISTANCE = modal.distance
%FEEDRATE = modal.feedrate
%SPINDLE = modal.spindle
%COOLANT = modal.coolant

; ==============================================================================
; Move to Fixed Tool Sensor (Machine Coordinates)
; ==============================================================================
G21                     ; Metric
M5                      ; Spindle stop
G90                     ; Absolute positioning

G53 G0 Z[global.state.SAFE_HEIGHT]  ; Raise to safe machine Z
G53 G0 X[global.state.PROBE_X_LOCATION] Y[global.state.PROBE_Y_LOCATION]
%wait

G53 G0 Z[global.state.PROBE_Z_LOCATION]
%wait

; ==============================================================================
; Probe Tool on Fixed Sensor (GRBL-valid sequence)
; ==============================================================================
G91                                   ; Relative

G38.2 Z-[global.state.PROBE_DISTANCE] F[global.state.PROBE_RAPID_FEEDRATE] ; Fast probe
G0 Z2                                 ; Retract 2mm

G38.2 Z-5 F40                         ; First slow accuracy pass
G4 P0.25
G38.4 Z10 F20                         ; Verify switch opens
G4 P0.25
G38.2 Z-2 F10                         ; Very slow precision pass
G4 P0.25
G38.4 Z10 F5                          ; Final open check
G4 P0.25

G90                                   ; Back to absolute

; ==============================================================================
; Store TOOL_REFERENCE
; ==============================================================================
%global.state.TOOL_REFERENCE = posz
(NEW TOOL_REFERENCE = [global.state.TOOL_REFERENCE])
%wait

; ==============================================================================
; Cleanup & Stay at Sensor
; ==============================================================================
G91
G0 Z5
G90

G53 G0 Z[global.state.SAFE_HEIGHT]
%wait

M0 (Reference Tool Recovery Complete — Machine parked at sensor.)

; Restore Modal State
[WCS] [PLANE] [UNITS] [DISTANCE] [FEEDRATE] [SPINDLE] [COOLANT]
````
