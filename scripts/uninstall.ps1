# Removes OneDock's shortcuts on Windows. Data in ~\.dock and server\.data is kept.
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1

foreach ($folder in "Programs", "Desktop", "Startup") {
    $link = [Environment]::GetFolderPath($folder) + "\OneDock.lnk"
    if (Test-Path $link) { Remove-Item $link; Write-Host "Removed $link" }
}
Write-Host "Done. To stop Dock if it's running: right-click its tray icon › Quit Dock."
