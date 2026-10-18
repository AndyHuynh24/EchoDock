# Starts Dock on Windows: the server (which also opens the secure phone
# address) and the desktop agent. Quit Dock from its tray icon (or close
# this window) to stop both. Setup page: http://localhost:8000/setup
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
# (OneDock.vbs runs this without a window; the log is in %LOCALAPPDATA%\OneDock\dock.log.)

$ErrorActionPreference = "Continue"  # (uv prints progress on stderr; that is not an error)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"

# Already running (e.g. OneDock opened again)? Just show its window.
try {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://localhost:8000/style.css | Out-Null
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Method Post http://localhost:8000/setup/show-window | Out-Null } catch {}
    Write-Host "Dock is already running."
    exit 0
} catch {}

if (-not (Test-Path .dock-token)) {
    $bytes = New-Object byte[] 16
    [Security.Cryptography.RNGCryptoServiceProvider]::new().GetBytes($bytes)
    (($bytes | ForEach-Object { $_.ToString("x2") }) -join "") | Set-Content -NoNewline -Encoding ascii .dock-token
}
$env:DOCK_TOKEN = (Get-Content .dock-token -Raw).Trim()
$env:DOCK_LAUNCHER_PID = "$PID"  # (Quit in the tray stops this window and everything it started)
$env:PYTHONUTF8 = "1"            # (names like "Scientific ⌘2" and saved files are UTF-8, as on the Mac)

# "uv sync" installs anything missing; then Python runs directly.
Push-Location server; uv sync -q; Pop-Location
Push-Location agent; uv sync -q; Pop-Location

$server = Start-Process -PassThru -NoNewWindow -WorkingDirectory "$Root\server" `
    -FilePath "$Root\server\.venv\Scripts\python.exe" -ArgumentList "-u", "-m", "dock_server.main"
Start-Sleep -Seconds 3
$agent = Start-Process -PassThru -NoNewWindow -WorkingDirectory "$Root\agent" `
    -FilePath "$Root\agent\.venv\Scripts\python.exe" -ArgumentList "-u", "-m", "dock_agent.win.main"

Write-Host "Dock is running. Setup page: http://localhost:8000/setup"
try {
    Wait-Process -Id $server.Id, $agent.Id
} finally {
    taskkill /PID $server.Id /T /F 2>$null | Out-Null
    taskkill /PID $agent.Id /T /F 2>$null | Out-Null
}
