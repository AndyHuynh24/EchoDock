# Removes OneDock's shortcuts on Windows (Start menu, desktop, start at login).
# Your workspaces, notes and activity (in ~\.dock and server\.data) are kept;
# delete those folders to remove them too.
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1

foreach ($folder in "Programs", "Desktop", "Startup") {
    $link = [Environment]::GetFolderPath($folder) + "\OneDock.lnk"
    if (Test-Path $link) { Remove-Item $link; Write-Host "Removed $link" }
}
Write-Host "Done. To stop Dock if it's running: right-click its tray icon › Quit Dock."
