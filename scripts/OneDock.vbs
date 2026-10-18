' Starts OneDock on Windows with no console window: double-click this, or the
' OneDock shortcut that scripts\install.ps1 makes. The log goes to
' %LOCALAPPDATA%\OneDock\dock.log.
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scripts = fso.GetParentFolderName(WScript.ScriptFullName)
logs = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\OneDock"
If Not fso.FolderExists(logs) Then fso.CreateFolder(logs)
shell.Run "cmd /c powershell -NoProfile -ExecutionPolicy Bypass -File """ & scripts & "\start.ps1"" > """ & logs & "\dock.log"" 2>&1", 0, False
