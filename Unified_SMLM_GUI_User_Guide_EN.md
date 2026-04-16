# Unified SMLM GUI User Guide

## 1. Purpose of This Document

This guide is based on:

- The lab workflow summary: [SMLM调节步骤整理.md](./SMLM调节步骤整理.md)
- The current integrated project: `unified_smlm`

This document describes how the current unified GUI actually works. It is not a guide for the old workflow where Micro-Manager, TeledyneCam, and Focus Lock were launched as separate user windows.

The current GUI integrates:

- Micro-Manager camera and acquisition control
- 642/647 laser and AOTF control
- Focus lock runtime and whole-cell Z scan
- Image preview, event logging, and save path planning
- Centralized default-parameter management and bundled dependency assets

The recommended launch entry point is still the desktop shortcut:

- `Unified SMLM GUI.lnk`

## 2. What the Current GUI Can Do

The unified GUI currently covers these tasks:

- Load `GXD_sCMOS_XY_stage_250221.cfg`
- Show and refresh embedded Micro-Manager status
- Start and stop Live, Snap, and Acquire
- Automatically load and apply the ROI preset file
- Configure exposure, trigger mode, saving format, and frame counts
- Control 642/647 laser output, AOTF output, and modulation mode
- Initialize the hidden focus lock runtime without opening the legacy focus lock user window
- Perform Lock / Unlock, Jump, and whole-cell Z scan configuration inside the current GUI
- Show absolute stage coordinates
- Use the event log to display preset guidance, round plans, save paths, and runtime state

## 3. Launch Methods

### 3.1 Recommended Method

Double-click the desktop shortcut:

- `Unified SMLM GUI.lnk`

It launches the GUI through this chain:

- `run_unified_gui_hidden.vbs`
- `run_unified_gui.bat`
- `python -m unified_smlm`

### 3.2 Backup Methods

If the desktop shortcut is temporarily unavailable, run:

- `run_unified_gui.bat`

If you want a console-free launch, run:

- `run_unified_gui_hidden.vbs`

### 3.3 If the Project Folder Is Moved

If the entire project directory is moved, the desktop shortcut will break. In that case, rerun:

- `install_desktop_unified_gui_launcher.ps1`

This recreates the desktop shortcut.

## 4. Configuration Files, Bundled Assets, and Permissions

### 4.1 Central Configuration File

The GUI defaults, preset defaults, and major hardware constants are now centralized in:

- [system_config.json](./unified_smlm/system_config.json)

This file controls:

- GUI default acquisition parameters
- Illumination defaults
- Focus lock defaults
- Bleach defaults
- Preset-specific one-click parameter sets
- Teledyne hardware constants such as serial ports, AOTF frequencies, and DAQ channels
- Paths to bundled dependency files

After editing this file, restart the GUI for the changes to take effect.

### 4.2 Administrator Permission Requirement

`system_config.json` is currently protected so that:

- `Administrators` can write
- `SYSTEM` can write
- normal `Users` are read-only

In practice, changing startup defaults requires administrator privileges.

### 4.3 Runtime Files You Should Not Edit Directly

At runtime, the GUI automatically generates:

- `unified_smlm\runtime\teledyne\parameters.runtime.xml`
- `unified_smlm\runtime\focuslock\IX83_default.runtime.xml`

These files are derived from `system_config.json` and bundled assets. Do not treat them as the source of truth. If you want to change defaults, edit:

- `unified_smlm\system_config.json`

### 4.4 Bundled Local Dependency Assets

The minimum self-contained dependency set is now bundled under:

- `unified_smlm\assets`

This includes:

- `assets\micromanager\GXD_sCMOS_XY_stage_250221.cfg`
- `assets\roi\0512-0512.roi`
- `assets\teledyne\parameters.base.xml`
- `assets\teledyne\aotf_analog_calib.csv`
- `assets\teledyne\AotfLibrary.dll`
- `assets\teledyne\thorlabs_tsi_camera_sdk.dll`
- `assets\bin\PriorScientificSDK.dll`
- `assets\bin\uc480_64.dll`
- `assets\bin\uc480_tools_64.dll`

The main external dependencies that still remain are:

- The installed Micro-Manager root itself
- NI-DAQ, serial drivers, and the real hardware devices

## 5. Hardware Preparation Before Launch

It is still recommended to follow the original hardware power-on SOP. The suggested order is:

1. Power on the ODT camera, then the SMLM camera.
2. Power on the focus-lock laser.
3. Power on the AOTF outlet or power strip.
4. Power on the main laser and wait until it is ready.
5. Power on the vibration motor.

If your lab has a newer hardware SOP, follow that SOP.

## 6. Main GUI Layout

### 6.1 Left Panel: Preset / Acquisition / Illumination

The left side is mainly for deciding what to acquire and how to save it:

- `Preset Modes`
- `Acquisition`
- `Illumination (642 / AOTF)`

### 6.2 Center Panel: Preview and Event Log

The center area is mainly for:

- Live preview
- Snap / Live / Acquire
- Event Log

### 6.3 Right Panel: Micro-Manager / Focus Lock / Z Planner

The right side is mainly for:

- `Embedded Micro-Manager`
- `Focus Lock and Z Scan`
- `Advanced Focus Lock Parameters`
- `Z Scan Planner`

## 7. Recommended Startup Sequence for Each Session

Use this order for a normal session:

1. Launch the unified GUI.
2. Check that the config path is correct in `Embedded Micro-Manager`.
3. Click `Load Config`.
4. Confirm that the config loads and stage coordinates begin updating.
5. Confirm that the ROI has been applied automatically. If needed, use `ROI Preset` + `Apply ROI`.
6. Click `Initialize` in `Focus Lock and Z Scan`.
7. Find focus first, then decide whether to manually lock.
8. Choose the appropriate preset.
9. When you are ready to turn on illumination, configure the `Illumination` panel and click `Apply To Hardware`.
10. Use `Acquire` to start the acquisition.

## 8. Important Differences Between the Current GUI and the Old Workflow

### 8.1 You No Longer Need Three Separate User Windows

The old workflow required separately opening:

- `TeledyneCam`
- `Micro-Manager`
- `focuslock_83.py`

The current GUI integrates the core functionality into a single window. In normal use, you do not need to open the old interfaces separately.

### 8.2 The Legacy Focus Lock Window Stays Hidden

The current GUI uses the integrated focus lock runtime. The original `IX83 Focus Lock` window is no longer the user-facing interface.

### 8.3 Search / Focus Is Effectively Merged into ROI Preview

The current GUI does not keep a separate full-field Search / Focus preview mode. `ROI Preview` is now the main preview and focusing entry point.

### 8.4 Presets No Longer Auto-Lock Focus

Switching presets no longer forces the focus lock into the locked state.

You must:

1. `Initialize`
2. Find focus manually
3. Click `Lock` manually

Only after that are you allowed to enter:

- `STORM 2D`
- `Whole-Cell Z Scan`

If focus has not been manually locked, the GUI will block the preset switch and show a warning.

## 9. Recommended Usage of Each Preset

### 9.1 ROI Preview

Purpose:

- Find focus
- Check whether the ROI is correct
- Check brightness and signal stability

Current default characteristics:

- Trigger: `Internal`
- Saving Format: `Image Stack File`
- Illumination modulation: `Independent mode`
- This is the only recommended preview preset in the current GUI

Recommended workflow:

1. `Load Config`
2. Confirm that the ROI is loaded
3. `Start Live`
4. Find the sample and focus plane
5. If you plan to run STORM or whole-cell next, manually click `Lock`

### 9.2 Widefield Test

Purpose:

- Quickly verify brightness, focus, and save path using a short stack

Current default characteristics:

- `Widefield Frames` defaults to `10`
- `Image Stack File`
- `Internal` trigger

Recommended use:

- Run once before a real single-molecule acquisition

### 9.3 STORM 2D

Purpose:

- Standard 2D single-molecule acquisition

Entry requirements:

- Focus lock runtime is initialized
- Focus is currently manually locked

Current default characteristics:

- Trigger: `Internal`
- Saving Format: `Separate Image Files`
- Modulation: `one-chan FSK mode`

Recommended workflow:

1. Find the correct focus plane in `ROI Preview`
2. Click `Lock` manually
3. Switch to `STORM 2D`
4. Check the 642 and AOTF parameters
5. Confirm modulation mode is `one-chan FSK mode`
6. Click `Apply To Hardware`
7. Click `Acquire`

### 9.4 Whole-Cell Z Scan

Purpose:

- Perform whole-cell Z-scan acquisition through the focus-lock DAQ path

Entry requirements:

- Focus lock runtime is initialized
- Focus is currently manually locked

Current default characteristics:

- Trigger: `External`
- Saving Format: `Separate Image Files`
- Modulation: `one-chan FSK mode`
- Default Z range is `-4.5 um` to `+4.5 um`
- The current preset default is `Depth Count = 16`
- Default `Frames / Depth / Round = 100`

Recommended workflow:

1. `Load Config`
2. `Initialize` the focus lock
3. Find focus
4. Click `Lock` manually
5. Switch to `Whole-Cell Z Scan`
6. Set `Z Start` / `Z End` / `Depth Count` or `Z Step`
7. Check `Frames / Depth / Round`
8. Confirm illumination is in `one-chan FSK mode`
9. Click `Apply To Hardware`
10. Click `Acquire`

Do not structure a real acquisition like this:

- First click `Run Z Scan`
- Then click `Acquire`

For real coordinated acquisition, the recommended workflow is:

- Click `Acquire` directly

That is because the current whole-cell acquisition logic is:

1. Arm the camera in external-trigger mode
2. Let the integrated focus lock DAQ path generate the Z motion and trigger pulses

## 10. How to Interpret Focus Lock Parameters

### 10.1 Lock / Unlock

- `Lock`: enter closed-loop focus stabilization
- `Unlock`: leave closed-loop stabilization

Before switching to ODT or leaving the single-molecule workflow, it is still recommended to unlock first.

### 10.2 Jump Offset

`Jump Offset` is the actual movement per click of `Jump +` or `Jump -`.

The current default is:

- `10 um`

### 10.3 Z Start / Z End

In `Whole-Cell Z Scan`, `Z Start` and `Z End` are not absolute stage coordinates.

They mean:

- Relative offsets from the stage position at the moment the scan starts

If you start from a locked state, that reference is usually the current locked plane.

So the defaults:

- `Z Start = -4.5 um`
- `Z End = +4.5 um`

mean:

- Scan symmetrically around the current focus plane, from 4.5 um below to 4.5 um above

### 10.4 Frames / Depth / Round vs STORM Total Frames

This is the most important parameter relationship to understand in whole-cell mode.

In whole-cell mode:

- `STORM Total Frames` means the final target frame count for each depth
- `Frames / Depth / Round` means how many frames are acquired per depth in each scan round

Example:

- `STORM Total Frames = 200`
- `Frames / Depth / Round = 100`

Then the system will automatically plan:

- `2 rounds`

If `Depth Count = 16`, the total number of images is:

- `16 depths x 200 frames/depth = 3200 images`

If you keep:

- `STORM Total Frames = 20000`
- `Frames / Depth / Round = 100`

that means:

- The target is `20000` frames per depth
- The system will plan `200 rounds`

So before a whole-cell run, always verify:

- `STORM Total Frames`
- `Frames / Depth / Round`
- `Depth Count`

## 11. Save Paths and Naming Rules

### 11.1 Overall Rule

The current implementation no longer uses `trial`.

Each time the GUI is launched, the application generates a fixed session timestamp prefix. That timestamp stays constant until the GUI is closed.

The session folder naming rule is:

- `[optional prefix]_[launch timestamp]_[optional sample]`

Where:

- `Save Prefix` may be empty
- `Sample Name` may be empty

### 11.2 Examples

Suppose:

- `Save Root = D:\Research_RSC`
- GUI launch timestamp = `20260416_021734`
- `Save Prefix = test`
- `Sample Name = HeLa`

Then the session folder becomes:

- `D:\Research_RSC\test_20260416_021734_HeLa`

If both prefix and sample name are empty, it may simply be:

- `D:\Research_RSC\20260416_021734`

### 11.3 Subdirectories by Mode

Different presets write to different subdirectories:

- `ROI Preview` -> `roi_preview`
- `Widefield Test` -> `widefield`
- `STORM 2D` -> `sr_smlm`
- `Whole-Cell Z Scan` -> `whole_cell_z`

### 11.4 File Prefixes

Default file prefixes by mode:

- `roi`
- `wf`
- `sr`
- `zscan`

Examples:

- `wf_20260416_153000.tif`
- `sr_20260416_153000`
- `zscan_20260416_153000`

## 12. Actual Behavior of the Two Saving Formats

### 12.1 Separate Image Files

The current implementation writes single-frame TIFF files directly in a streaming way.

The primary output is a directory such as:

- `...\sr_smlm\sr_20260416_153000\`

That directory contains many single-frame TIFF files.

This path does not keep an extra `_mda` dataset directory.

Recommended for:

- `STORM 2D`
- `Whole-Cell Z Scan`

### 12.2 Image Stack File

The current implementation still uses an MDA-based path internally to produce a stack output.

The primary output is:

- One `.tif`

By default, some `Image Stack File` workflows may still keep an `_mda` dataset directory.

The exception is:

- `Widefield Test` currently does not keep `_mda` in the final save directory

Recommended for:

- `ROI Preview`
- Small validation acquisitions

## 13. What You Will See in the Event Log

The Event Log currently reports:

- Preset usage guidance
- Current parameter summaries
- Planned save paths
- MDA or streaming TIFF output information
- Whole-cell round plans
- Total frame and image counts
- Acquisition completion or interruption
- Illumination apply and safe shutdown messages

For whole-cell runs, the log explicitly shows:

- Number of rounds
- `frames/depth` per round
- `frames/depth total`
- `depths x frames/depth = total images`

## 14. Absolute Stage Position Display

The GUI now displays absolute stage coordinates in real time:

- XY stage absolute position
- Focus stage absolute Z position

You can see this in:

- The `Stage` field inside `Embedded Micro-Manager`

When focus lock is active, the Z value is preferentially updated from the focus lock runtime.

## 15. How to Use the Illumination Panel

The current Illumination panel exposes:

- 642/647 laser enable
- Laser power
- AOTF enable
- AOTF value
- Modulation mode

Common modes:

- `Independent mode`
  - For finding the sample, focusing, and widefield checks
- `one-chan FSK mode`
  - For STORM and whole-cell, where camera timing gates the AOTF

Recommended workflow:

1. Edit the parameters
2. Click `Apply To Hardware`
3. Check the Event Log for the apply result

## 16. Safe Shutdown and Closing the GUI

### 16.1 The Illumination Safe Shutdown Button

Clicking `Safe Shutdown` performs the current software-side illumination shutdown path:

1. Ramp the 647 laser target back to the safe shutdown setpoint
2. Disable AOTF outputs
3. Drive NI-DAQ outputs low
4. Reset the AOTF DDS state
5. Turn the laser output off

### 16.2 Closing the Entire GUI

If you close the GUI directly:

- The application also attempts an automatic illumination safe shutdown

If the GUI is closed during an external-trigger whole-cell acquisition, the current shutdown order is:

1. Stop the acquisition wait state
2. Request the focus lock to stop DAQ-driven scanning
3. Perform safe shutdown on the laser and AOTF path
4. Release Micro-Manager, focus lock, and Teledyne runtime resources

## 17. Recommended Software Shutdown Sequence

Recommended order:

1. If focus is locked, `Unlock` first
2. If an acquisition is running, click `Stop Acquisition`
3. If needed, click `Safe Shutdown`
4. Close the GUI

## 18. Recommended Hardware Power-Off Sequence

It is still recommended to follow the original workflow order:

1. Turn off the vibration motor
2. Turn off the main laser
3. Turn off the focus-lock laser
4. Turn off the AOTF power
5. Turn off the cameras last

## 19. Troubleshooting

### 19.1 The Desktop Shortcut Does Not Launch the GUI

Check:

- Whether the project directory has been moved
- Whether `run_unified_gui_hidden.vbs` is still present in the project root

If the project location changed, rerun:

- `install_desktop_unified_gui_launcher.ps1`

### 19.2 Load Config Fails Because a COM Port or Device Is Busy

This usually means:

- An old GUI instance has not fully exited
- Another program is still holding the camera, stage, or serial port

Close:

- Any other program that may still connect to Micro-Manager
- Any old focus lock runtime
- Any old TeledyneCam instance

Then try again.

### 19.3 Why Can I Not Switch to STORM 2D or Whole-Cell Z Scan

This is by design, not a bug.

You must first:

1. Initialize the focus lock runtime
2. Find focus
3. Click `Lock` manually

Only after that can you enter those presets.

### 19.4 The Whole-Cell Round Count Looks Wrong

Check these first:

- `STORM Total Frames`
- `Frames / Depth / Round`
- `Depth Count`

Remember:

- In whole-cell mode, `STORM Total Frames` means the target total frame count per depth

### 19.5 There Is No Light or the Brightness Is Wrong

Check in this order:

1. Whether the laser hardware is actually powered on
2. Whether the AOTF hardware is actually powered on
3. Whether `642 Laser` is enabled
4. Whether `AOTF 642` is enabled
5. Whether you clicked `Apply To Hardware`
6. Whether the modulation mode is correct
7. Whether the experiment requires `one-chan FSK mode`
8. Whether the Event Log reports a runtime apply failure

### 19.6 Saving Fails Because the Directory Already Exists

`Separate Image Files` mode requires the target output directory to not already contain files.

If you manually reuse the same path, you may get a conflict. The easiest fixes are:

- Change `Save Prefix`
- Change `Sample Name`
- Or close and reopen the GUI so the session timestamp changes

### 19.7 I Changed Parameters in the GUI but the Startup Defaults Did Not Change

That is expected. Most GUI edits are session-level changes only.

If you want to change the defaults used at the next startup, edit this file with administrator privileges:

- `unified_smlm\system_config.json`

Then restart the GUI.

## 20. Recommended Mapping from the Original Workflow to the Current GUI

If you compress the old multi-software workflow into the current unified GUI, the practical sequence is:

1. Launch the unified GUI from the desktop shortcut
2. `Load Config`
3. Use `ROI Preview` to find focus
4. Click `Lock` manually
5. Switch to `Widefield Test`, `STORM 2D`, or `Whole-Cell Z Scan` as needed
6. Apply the corresponding illumination settings in the `Illumination` panel
7. Click `Acquire`
8. Watch the Event Log and save path preview
9. `Unlock` when finished, then close the GUI

## 21. Related Files

The key files behind the current behavior include:

- `SMLM调节步骤整理.md`
- `run_unified_gui.bat`
- `run_unified_gui_hidden.vbs`
- `install_desktop_unified_gui_launcher.ps1`
- `unified_smlm\system_config.json`
- `unified_smlm\config_store.py`
- `unified_smlm\main_window.py`
- `unified_smlm\presets.py`
- `unified_smlm\mm_backend.py`
- `unified_smlm\focuslock_integration.py`
- `unified_smlm\teledyne_integration.py`
- `unified_smlm\save_paths.py`
- `unified_smlm\assets\`
- `unified_smlm\runtime\`

If the GUI behavior changes again in the future, update this file together with the Chinese guide.
