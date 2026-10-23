# Windows setup (quick)

For Windows 10 or 11. It takes about 10 minutes, most of it downloads.

## 1. Install the tools
Open **PowerShell** and run:
```powershell
winget install Git.Git
winget install Amazon.AWSCLI
```
Close PowerShell and open it again, so it finds `git` and `aws`.

## 2. Get Dock
```powershell
cd $HOME\Documents
git clone https://github.com/AndyHuynh24/EchoDock.git
cd EchoDock
```
*(Optional, for Google Calendar and Gmail:)* copy `server\google_oauth_client.json` from the Mac into the same folder on the PC. It isn't on GitHub because it holds a secret.

## 3. Log in to AWS (the AI)
```powershell
aws login
```
Sign in in the browser, and use region **us-east-1** when it asks.

## 4. Install Dock
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```
It installs everything else (uv, cloudflared, Dock's Python packages) and adds **OneDock** to the Start menu and the desktop. Answer **Y** if you want Dock to start when you log in.

## 5. First run
- Dock opens by itself. Follow the welcome window, and its steps turn green.
- If the microphone step stays red: **Settings › Privacy & security › Microphone**, then turn on **Let desktop apps access your microphone**.
- After that, Dock lives in the **tray by the clock** (a small face). Press **Alt+Space** once and say "open my downloads".

## Test it
Work through [test-checklist-windows.md](test-checklist-windows.md) (16 quick checks).

## If something goes wrong
| Problem | Fix |
|---|---|
| `install.ps1` "cannot be loaded" | Run it exactly as in step 4 (with `-ExecutionPolicy Bypass`) |
| `winget` not found | Install **App Installer** from the Microsoft Store |
| "My AI login has expired" | Run `aws login` again |
| Anything else | Open `%LOCALAPPDATA%\OneDock\dock.log`, or run `scripts\start.ps1` in PowerShell to watch the log live, and send the lines around the error |

**Update later:** `git pull` in the OneDock folder, then quit Dock from the tray and open it again.
**Remove:** `powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1`.
