# CNCjs Advanced Workflow: Workpiece Setup, Tool Change & Park Macro

------

## 📘 Macro System Overview (What Each Macro Does & How They Work)

This machine workflow uses **four coordinated macros**, each with a specific purpose. Together they create a safe, repeatable, and highly accurate tool-length and work-zero management system.

### **MACRO 1 — Touch Plate & Reference Tool**

**Purpose:** Establishes the foundation for the entire job.

- Probes Z, then X and Y using the touch plate.
- Sets accurate workpiece zero at the stock’s corner.
- Moves to the tool-height sensor.
- Measures the **reference tool**.
- Saves the reference tool’s machine-coordinate Z as `TOOL_REFERENCE`.

**Run:** Once at the start of each job.

------

### **MACRO 2 — Tool Change**

**Purpose:** Allows mid-job tool changes without re-probing the workpiece.

- Parks the spindle at the tool-height sensor.
- Prompts operator to swap tools.
- Probes the new tool.
- Computes tool-length difference.
- Applies corrected Z-offset using `G10 L20`.

**Run:** Every time a new tool is inserted.

------

### **MACRO 3 — Park at Tool Sensor**

**Purpose:** Moves safely to the tool sensor without changing offsets.

Use for cleaning, inspection, and manual preparation before tool changes.

------

### **MACRO 4 — Safe Return to Work Zero**

**Purpose:** Safely returns the spindle to X0 Y0 without modifying offsets.

------

## 🚦 Operator Workflow Overview

This section explains **how the operator should use all four macros** during a typical job.

------

### 🔧 1. Before Starting Any Job

1. Clamp material securely.
2. Install the **reference tool**.
3. Ensure the touch plate and clip are ready.
4. Verify the fixed tool-height sensor is unobstructed.
5. Confirm the configured **SAFE_HEIGHT** is truly safe for your setup.

------

### ▶️ 2. Run MACRO 1 — Touch Plate & Reference Tool

- Probes the stock with the touch plate to set Z, X, and Y.
- Moves to the tool-height sensor and measures the reference tool.
- Stores the reference tool’s machine Z as `TOOL_REFERENCE`.

Do **not** change tools during this macro.

------

### ▶️ 3. Begin Cutting

Use the reference tool normally and run your G-code until a tool change is required.

------

### ▶️ 4. When a Tool Change is Needed, Run MACRO 2 — Tool Change

- Moves to the sensor, stops spindle.
- Prompts you to change the tool.
- Measures the new tool length.
- Applies the correct Z-offset.

------

### ▶️ 5. Using MACRO 3 — Park at Tool Sensor

Use **anytime** to safely move away from the workpiece without altering offsets.

------

### ▶️ 6. Using MACRO 4 — Safe Return to Work Zero

Moves the spindle safely to X0 Y0 in work coordinates without changing Z-zero.

------

### ▶️ 7. **Using MACRO 1r — Reference Tool Recovery (ONLY When Needed)**

**Purpose:**
 MACRO 1r is a *special-use recovery macro* used **only when TOOL_REFERENCE has been lost** and must be rebuilt **without re-probing the workpiece**.

This macro re-measures the **current tool** on the fixed tool sensor and regenerates a valid `TOOL_REFERENCE`.

------

#### ⚠️ **CRITICAL WARNINGS**

- **Never use MACRO 1r during normal machining workflow.**
- Only use *when TOOL_REFERENCE no longer exists or was reset*.
- The **current tool must be the same reference tool** used when running MACRO 1 originally.
- Using MACRO 1r with any other tool will generate an incorrect tool height and cause Z-depth errors.

------

#### ✔️ When to Use MACRO 1r

Use this macro **only** when:

- You lost TOOL_REFERENCE (power cycle, CNCjs restart, memory loss, etc.).
- The tool currently in the spindle **is the reference tool**.
- You want to continue a multi-tool workflow without re-probing the workpiece.

------

#### ❌ When *NOT* to Use MACRO 1r

Do **NOT** use this macro:

- During a normal job workflow
- If TOOL_REFERENCE already exists
- After tool changes
- If the current tool is *not* the reference tool
- To probe the touch plate (it does not do that)

------

#### ✔️ After Running MACRO 1r

- TOOL_REFERENCE is restored
- You may resume using MACRO 2 for tool changes
- Your workpiece zero is untouched and still correct





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
%global.state.PLATE_THICKNESS = 12.05 ; Increasing drives bit closer to work piece
%global.state.Z_FAST_PROBE_DISTANCE = 50
%global.state.X_PLATE_OFFSET = -13.175
%global.state.Y_PLATE_OFFSET = -13.175

; Tool-Height settings
%global.state.SAFE_HEIGHT = -5
%global.state.PROBE_X_LOCATION = -1.5
%global.state.PROBE_Y_LOCATION = -1224
%global.state.PROBE_Z_LOCATION = -5
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
%global.state.PROBE_DISTANCE = 100
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
; MACRO 3: Park at Tool Sensor
; VERSION: 1.01
; ============================================================================

M5 (Ensuring spindle is stopped.)

G21
G90

; Raise to safe machine Z
G53 G0 Z-5

; Go to tool height sensor
G53 G0 X-1.5 Y-1224
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
G53 G0 Z-5

; Go to work zero
G0 X0 Y0
```

------

# 🔧 **MACRO 1R — Reference Tool Recovery**

```gcode
; ==============================================================================
; MACRO 1r: Reference Tool Recovery (Sensor Only)
; VERSION: 1.02 (GRBL-safe)
; DESCRIPTION:
;   Re-establish TOOL_REFERENCE using the current tool at the fixed sensor.
;   Only runs if TOOL_REFERENCE does NOT already exist.
;   Prevents accidental overwriting of a valid tool reference.
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
%global.state.PROBE_Z_LOCATION = -10
%global.state.PROBE_DISTANCE = 100
%global.state.PROBE_RAPID_FEEDRATE = 200

%wait

M0 (This will SET TOOL_REFERENCE using the CURRENT tool.)

; ==============================================================================
; Save Modal State & Position
; ==============================================================================
%X0 = posx
%Y0 = posy
%Z0 = posz

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
