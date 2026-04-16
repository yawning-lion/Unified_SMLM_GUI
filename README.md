# Unified SMLM GUI

Integrated GUI for SMLM acquisition workflows with:

- embedded Micro-Manager control
- Teledyne / AOTF illumination control
- integrated Focus Lock runtime
- STORM 2D and whole-cell Z-scan workflows
- centralized JSON configuration

## Repository Layout

- `unified_smlm/`
  - main Python package
  - `assets/`: bundled minimum dependency assets used by the GUI
  - `runtime/`: generated runtime files, logs, and temporary XML outputs
- `run_unified_gui.bat`
  - main Windows launcher
- `run_unified_gui_hidden.vbs`
  - console-free launcher wrapper
- `install_desktop_unified_gui_launcher.ps1`
  - creates a shortcut for the current folder copy
- `launcher_local_config.cmd.example`
  - optional local override template
- `Unified_SMLM_GUI_使用说明_CN.md`
  - Chinese user guide
- `Unified_SMLM_GUI_User_Guide_EN.md`
  - English user guide
- `SMLM调节步骤整理.md`
  - workflow reference

## External Requirements

This repository bundles the minimum local assets needed by the current GUI, but it still depends on:

- a working Python environment with the required packages
- an installed Micro-Manager root
- NI-DAQ / serial / vendor drivers as required by the real hardware

The default configuration expects Micro-Manager at:

- `C:\Program Files\Micro-Manager-2.0`

If your Micro-Manager location differs, override it through:

1. `launcher_local_config.cmd`
2. or `run_unified_gui.bat --mm-root "C:\path\to\Micro-Manager-2.0"`

## Quick Start

### Option 1: Double-click the local shortcut

Run:

- `install_desktop_unified_gui_launcher.ps1`

This creates:

- a shortcut inside the current folder
- a desktop shortcut, unless `-SkipDesktopShortcut` is used

### Option 2: Launch directly

Run:

- `run_unified_gui.bat`

The launcher resolves paths relative to its own folder.

## Launcher Overrides

`run_unified_gui.bat` supports optional overrides:

```bat
run_unified_gui.bat ^
  --python "C:\path\to\python.exe" ^
  --mm-root "C:\Program Files\Micro-Manager-2.0" ^
  --mm-cfg "C:\path\to\GXD_sCMOS_XY_stage_250221.cfg" ^
  --save-root "D:\Research_RSC" ^
  --system-config "C:\path\to\system_config.json" ^
  --active-preset "Whole-Cell Z Scan"
```

For double-click use, create a local file named:

- `launcher_local_config.cmd`

based on:

- `launcher_local_config.cmd.example`

## Configuration

The main configuration file is:

- `unified_smlm/system_config.json`

This file defines:

- GUI startup defaults
- preset-specific defaults
- bundled asset paths
- hardware constants such as serial ports and AOTF frequencies

On the working microscope machine, this file may be ACL-protected so that only administrators can modify it.

## Runtime Files

The following are generated automatically and should not be treated as source files:

- `unified_smlm/runtime/teledyne/parameters.runtime.xml`
- `unified_smlm/runtime/focuslock/IX83_default.runtime.xml`

These are regenerated from `system_config.json` and the bundled base XML files.

## Exporting a Clean Package

To export a clean copy to the Desktop, run:

- `export_clean_unified_smlm_package.ps1`

By default this creates:

- `Desktop\Unified_SMLM_GUI_Clean`

The export:

- copies the required files
- excludes caches and generated runtime files
- recreates the runtime directory skeleton
- creates a local shortcut inside the exported folder

## Documentation

- Chinese guide: `Unified_SMLM_GUI_使用说明_CN.md`
- English guide: `Unified_SMLM_GUI_User_Guide_EN.md`

## Notes for GitHub Upload

Before publishing, review whether your organization allows distribution of:

- bundled DLLs
- bundled vendor executables
- bundled hardware XML files

If these binaries must not be published, keep the source tree structure but remove the restricted files from `unified_smlm/assets/` and document the expected local replacements in this README.
