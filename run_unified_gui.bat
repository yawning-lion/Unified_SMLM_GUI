@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if exist "%~dp0launcher_local_config.cmd" (
    call "%~dp0launcher_local_config.cmd"
)

set "FORWARD_ARGS="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--python" (
    set "UNIFIED_SMLM_PYTHON=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--mm-root" (
    set "SMLM_MM_ROOT=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--mm-cfg" (
    set "SMLM_MM_CFG=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--save-root" (
    set "SMLM_SAVE_ROOT=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--system-config" (
    set "SMLM_SYSTEM_CONFIG=%~2"
    shift
    shift
    goto parse_args
)
if /I "%~1"=="--active-preset" (
    set "SMLM_ACTIVE_PRESET=%~2"
    shift
    shift
    goto parse_args
)
set FORWARD_ARGS=!FORWARD_ARGS! "%~1"
shift
goto parse_args

:args_done
set "PYTHON_EXE="

if defined UNIFIED_SMLM_PYTHON (
    set "PYTHON_EXE=%UNIFIED_SMLM_PYTHON%"
)

if not defined PYTHON_EXE if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
)

if not defined PYTHON_EXE if exist "%USERPROFILE%\anaconda3\envs\gui_smlm_unified\python.exe" (
    set "PYTHON_EXE=%USERPROFILE%\anaconda3\envs\gui_smlm_unified\python.exe"
)

if defined PYTHON_EXE (
    "%PYTHON_EXE%" -m unified_smlm !FORWARD_ARGS!
    exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 -m unified_smlm !FORWARD_ARGS!
    exit /b %ERRORLEVEL%
)

echo Could not find a Python interpreter for Unified SMLM GUI.
echo.
echo Supported options:
echo   1. Create launcher_local_config.cmd next to this script and set:
echo        set "UNIFIED_SMLM_PYTHON=C:\path\to\python.exe"
echo   2. Or run:
echo        run_unified_gui.bat --python "C:\path\to\python.exe"
exit /b 1
