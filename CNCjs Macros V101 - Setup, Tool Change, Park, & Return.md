# CNCjs Advanced Workflow: Workpiece Setup, Tool Change & Park Macro

---

## 📘 Macro System Overview (What Each Macro Does & How They Work)

This machine workflow uses **four coordinated macros**, each with a specific purpose. Together they create a safe, repeatable, and highly accurate tool-length and work-zero management system.

### **MACRO 1 — Touch Plate & Reference Tool**

**Purpose:** Establishes the foundation for the entire job.

- Probes Z, then X and Y, using the touch plate.  
- Sets accurate workpiece zero at the stock’s corner.  
- Moves to the tool-height sensor.  
- Measures the **reference tool**.  
- Saves the reference tool’s machine-coordinate Z as `TOOL_REFERENCE`.

**Why it matters:**  
All future tools are mathematically compared to the reference tool. This means you never have to re-probe the workpiece again during tool changes.

**Run:** Once at the start of each job.

---

### MACRO 2 — Tool Change

**Purpose:** Allows mid-job tool changes without ever touching the workpiece.

- Parks the spindle at the tool-height sensor.  
- Prompts operator to swap tools.  
- Probes the new tool.  
- Computes tool-length difference.  
- Applies corrected Z-offset using `G10 L20`.

**Why it matters:**  
This guarantees the new tool tip sits at the *exact same Z-zero* as the reference tool, even if tools differ in length.

**Run:** Every time a new tool is inserted.

---

### MACRO 3 — Park at Tool Sensor

**Purpose:** Provides a quick, safe movement to the tool sensor without modifying any offsets.

- Stops spindle.  
- Raises to a safe machine Z.  
- Moves directly to the tool sensor.  

**Why it matters:**  
Use this macro for cleaning, inspection, or prep before a tool change. Safe, simple, risk-free.

**Run:** Anytime the operator needs to move the tool safely away.

---

### MACRO 4 — Safe Return to Work Zero

**Purpose:** Returns the spindle to X0 Y0 safely.

- Raises to safe machine Z.  
- Travels to work zero in the active work coordinate system.  
- Does not modify offsets or Z-zero.

**Why it matters:**  
Convenient for inspecting the work area or preparing for the next job step.

**Run:** Anytime you want to return to work zero without disturbing offsets.

---

## 🚦 Operator Workflow Overview

This section explains **how the operator should use all four macros** during a typical job.

---

### 🔧 1. Before Starting Any Job

1. Clamp material securely.  
2. Install the **reference tool** (first tool of the job).  
3. Ensure the touch plate and clip are ready and accessible.  
4. Confirm the fixed tool-height sensor is unobstructed.  
5. Clear the machine bed and verify that the configured **SAFE_HEIGHT** is truly safe for your setup.

---

### ▶️ 2. Run MACRO 1 — Touch Plate & Reference Tool

**What this does:**

- Probes the stock with the touch plate to set Z, then X and Y.  
- Sets accurate workpiece zero at the corner.  
- Moves to the tool-height sensor.  
- Measures the reference tool and saves `TOOL_REFERENCE`.

**Operator actions:**

- When prompted, **attach the clip and place the touch plate** under the tool.  
- When prompted again, **remove the touch plate and clip**.  
- Do **not** change tools during this macro.  

Once Macro 1 completes, your work zero and reference tool height are fully established.

---

### ▶️ 3. Begin Cutting

- Load and run your G-code with the reference tool.  
- Cut normally until the job (or your program) calls for a tool change.

---

### ▶️ 4. When a Tool Change is Needed, Run MACRO 2 — Tool Change

**What this does:**

- Stops the spindle.  
- Raises to safe Z.  
- Moves to the tool-height sensor.  
- Prompts you to change the tool.  
- Measures the new tool.  
- Applies a corrected Z-offset so the new tool uses the same Z-zero as the reference tool.

**Operator actions:**

1. Wait for the machine to park at the sensor and stop the spindle.  
2. Change the tool and **tighten the collet securely**.  
3. Press *Continue* when ready.  
4. Allow all probing moves to complete.  

After this, resume your program. Z-depth for the new tool will be correct.

---

### ▶️ 5. Using MACRO 3 — Park at Tool Sensor

Use **MACRO 3** when you want to:

- Move the spindle safely away from the workpiece.  
- Inspect or clean the tool.  
- Prepare for a manual tool change (before running Macro 2).  

**Important:**

- This macro does *not* change any offsets.  
- It simply stops the spindle and moves to a safe, known location at the tool sensor.

You can safely run it **any time** the machine is idle or paused.

---

### ▶️ 6. Using MACRO 4 — Safe Return to Work Zero

Use **MACRO 4** when you want to:

- Return the spindle to **X0 Y0** in work coordinates.  
- Make sure the move back to zero is done from a safe machine Z.  
- Inspect the part at the origin after cuts.  

**What it does:**

- Stops the spindle.  
- Raises to a safe machine Z height.  
- Moves to the workpiece origin X0 Y0.  
- Does *not* change work offsets or Z-zero.

Run this whenever you want a **safe, predictable return to origin**.

---





---

# 🔧 **MACRO 1 — Touch Plate & Reference Tool**

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
%global.state.PLATE_THICKNESS = 12.3
%global.state.Z_FAST_PROBE_DISTANCE = 50
%global.state.X_PLATE_OFFSET = -13.175
%global.state.Y_PLATE_OFFSET = -13.175

; Tool-Height settings
%global.state.SAFE_HEIGHT = -10
%global.state.PROBE_X_LOCATION = -1.5
%global.state.PROBE_Y_LOCATION = -1224
%global.state.PROBE_Z_LOCATION = -10
%global.state.PROBE_DISTANCE = 100
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
G38.2 Z-15 F60                      ; Probe Z down slowly for accuracy
G90                                 ; Absolute positioning
G92 Z[global.state.PLATE_THICKNESS] ; Reset Z coordinate to plate thickness
G0 Z16                              ; Rapid move up to safe Z

; ==============================================================================
; Probe X (Touch Plate)
; ==============================================================================
G0 X-70 F800                        ; Rapid move to X approach position
G0 Z4                               ; Rapid move down to probing height
G38.2 X0 F200                       ; Probe X towards plate
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
G38.2 Y0 F200                       ; Probe Y towards plate
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

G38.2 Z-5 F40                       ; Slow probe Z for accuracy
G4 P.25                             ; Dwell (pause) for 0.25 seconds
G38.4 Z10 F20                       ; Probe Z away (verify switch release)
G4 P.25                             ; Dwell
G38.2 Z-2 F10                       ; Very slow probe Z for final accuracy
G4 P.25                             ; Dwell
G38.4 Z10 F5                        ; Very slow probe Z away
G4 P.25                             ; Dwell

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

; Refine Probe
G38.2 Z-5 F40                       ; Slow probe Z for accuracy
G4 P.25                             ; Dwell (pause) for 0.25 seconds
G38.4 Z10 F20                       ; Probe Z away (verify switch release)
G4 P.25                             ; Dwell
G38.2 Z-2 F10                       ; Very slow probe Z for final accuracy
G4 P.25                             ; Dwell
G38.4 Z10 F5                        ; Very slow probe Z away
G4 P.25                             ; Dwell
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
; MACRO 3: Park at Tool Sensor
; VERSION: 1.01
; ============================================================================

M5 (Ensuring spindle is stopped.)

G21
G90

G53 G0 Z-10
G53 G0 X-1.5 Y-1224
G53 G0 Z-10
```

------

# 🔧 **MACRO 4 — Return to Work**

```gcode
; ============================================================================
; MACRO 4: Return to Work
; VERSION: 1.01
; ============================================================================

M5 (Ensuring spindle is stopped.)
G21
G90

; Raise to safe machine Z
G53 G0 Z-10

; Go to work zero
G0 X0 Y0
```
