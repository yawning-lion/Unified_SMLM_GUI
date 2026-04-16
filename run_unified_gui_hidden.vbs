Option Explicit

Dim shell
Dim fso
Dim scriptDir
Dim launcher

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = fso.BuildPath(scriptDir, "run_unified_gui.bat")

If Not fso.FileExists(launcher) Then
    MsgBox "Launcher not found: " & launcher, vbCritical, "Unified SMLM GUI"
    WScript.Quit 1
End If

shell.Run """" & launcher & """", 0, False
