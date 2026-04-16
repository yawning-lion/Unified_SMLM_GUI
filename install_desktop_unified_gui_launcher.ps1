param(
    [string]$ShortcutName = "Unified SMLM GUI",
    [switch]$SkipDesktopShortcut,
    [switch]$SkipLocalShortcut
)

$ErrorActionPreference = "Stop"

$packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetScript = Join-Path $packageRoot "run_unified_gui_hidden.vbs"

if (-not (Test-Path -LiteralPath $targetScript)) {
    throw "Launcher script not found: $targetScript"
}

$wsh = New-Object -ComObject WScript.Shell

function New-LauncherShortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $shortcut = $wsh.CreateShortcut($Path)
    $shortcut.TargetPath = "$env:SystemRoot\System32\wscript.exe"
    $shortcut.Arguments = '"' + $targetScript + '"'
    $shortcut.WorkingDirectory = $packageRoot
    $shortcut.WindowStyle = 1
    $shortcut.Description = "Launch Unified SMLM GUI from $packageRoot"
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
    $shortcut.Save()
    Write-Host "Created shortcut:" $Path
}

if (-not $SkipLocalShortcut) {
    $localShortcutPath = Join-Path $packageRoot ($ShortcutName + ".lnk")
    New-LauncherShortcut -Path $localShortcutPath
}

if (-not $SkipDesktopShortcut) {
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $desktopShortcutPath = Join-Path $desktopPath ($ShortcutName + ".lnk")
    New-LauncherShortcut -Path $desktopShortcutPath
}
