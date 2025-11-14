# GRBL-Maintenance-Generator ![License](https://img.shields.io/badge/License-GPLv3-blue)

A lightweight, **web-based tool for woodworking CNC operators**. It generates **two safe, spindle-off G-code programs** for machine maintenance:

- **Greasing Routine:** Deep-cleaning “pecking” sequence to properly purge and apply grease.
- **Exercise Routine:** Simple warm-up movements to get your machine ready.

All settings are saved locally in your browser—no server or internet required.

------

## Features

- Fully **offline** – just open the HTML file in your browser.
- Automatically **saves your settings** for next time.
- Generates **ready-to-use G-code files** compatible with UGS, Candle, and similar CNC sender software.
- Open-source and licensed under **[GNU GPL v3.0](https://www.gnu.org/licenses/gpl-3.0.en.html)**.

------

## How to Use

### 1. Download the Tool

1. Go to the repository on GitHub.
2. Click on the `gcode_generator.html` file.
3. Click the **Raw** button.
4. Right-click and choose **Save As…** (or **Save Page As…**).
5. Save it as `gcode_generator.html` in a convenient location.

------

### 2. Open in Your Browser

- Double-click the saved file.
- Your default browser (Chrome, Firefox, Edge, etc.) will open the tool.
- No internet connection is required after downloading.

------

### 3. Generate G-Code

1. Enter your machine’s settings. These are saved automatically.
2. Click **Generate Greasing G-Code** for the maintenance routine, or **Generate Exercise G-Code** for a warm-up.
3. Click **Save as .gcode** to download the file.
4. Load it into your CNC sender software and run it safely with the spindle off.

------

### ⚠️ Safety Note

The generated G-code is **spindle-off** and designed **only for maintenance and warm-up routines**. Always verify your settings before running on your machine.
