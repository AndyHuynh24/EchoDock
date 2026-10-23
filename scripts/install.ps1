# One-time setup for Dock on Windows 10 or 11. Safe to run again.
#   git clone <repo>; cd OneDock
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# Then open Dock from the Start menu or the desktop shortcut.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
function Step($text) { Write-Host ""; Write-Host $text -ForegroundColor Cyan }

Step "1/5  Tools"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (runs Dock's Python code)..."
    powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "Installing cloudflared (gives the phone a secure address)..."
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
Write-Host "uv and cloudflared are ready."

Step "2/5  Dock's Python packages"
Push-Location server; uv sync -q; Pop-Location
Push-Location agent; uv sync -q; Pop-Location
Write-Host "Installed. (The bubble uses Microsoft Edge WebView2, which comes with Windows 10 and 11.)"

Step "3/5  Your private token"
if (-not (Test-Path .dock-token)) {
    $bytes = New-Object byte[] 16
    [Security.Cryptography.RNGCryptoServiceProvider]::new().GetBytes($bytes)
    (($bytes | ForEach-Object { $_.ToString("x2") }) -join "") | Set-Content -NoNewline -Encoding ascii .dock-token
}
Write-Host "Saved in .dock-token (keep it secret: it is the password for your phone link)."

Step "4/5  Amazon Bedrock (the AI)"
$awsOk = $false
if (Get-Command aws -ErrorAction SilentlyContinue) {
    aws sts get-caller-identity *> $null
    $awsOk = $LASTEXITCODE -eq 0
}
if ($awsOk) { Write-Host "AWS login found." }
else {
    Write-Host "No AWS login found yet. Install the AWS CLI (winget install Amazon.AWSCLI), run 'aws login',"
    Write-Host "and use region us-east-1. The setup page turns green when it works."
}

Step "5/5  OneDock in the Start menu"
$shell = New-Object -ComObject WScript.Shell
function Make-Shortcut($path) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = "wscript.exe"
    $link.Arguments = "`"$Root\scripts\OneDock.vbs`""
    $link.WorkingDirectory = $Root
    $link.Description = "OneDock: Alexa+ for your desk"
    $link.Save()
}
$programs = [Environment]::GetFolderPath("Programs")
Make-Shortcut "$programs\OneDock.lnk"
Make-Shortcut ([Environment]::GetFolderPath("Desktop") + "\OneDock.lnk")
Write-Host "Added OneDock to the Start menu and the desktop."
$answer = Read-Host "Start Dock automatically when you log in? [Y/n]"
if ($answer -notmatch "^[Nn]") {
    Make-Shortcut ([Environment]::GetFolderPath("Startup") + "\OneDock.lnk")
    Write-Host "Dock will start by itself when you log in. (Change it any time from the tray icon.)"
}
Write-Host "Opening Dock. Follow the welcome window; after that, Dock lives in the tray by the clock."
Start-Process wscript.exe -ArgumentList "`"$Root\scripts\OneDock.vbs`""
