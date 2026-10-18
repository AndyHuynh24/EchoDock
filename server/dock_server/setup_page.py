"""The setup page on the Mac (http://localhost:8000/setup): live checks for
each step and a QR code to pair the phone.

These routes only answer requests made on the Mac itself, never through the
tunnel, because the phone link they show contains the secret token.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

import qrcode
import qrcode.image.svg
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from dock_server import bedrock, google_account, tunnel, webapp
from dock_server.hub import AgentError, AgentOffline, Hub

BEDROCK_CHECK_SECONDS = 120
# Made by scripts/install.sh (Mac) or scripts/install.ps1 and the tray menu (Windows).
LOGIN_ITEM = (Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/OneDock.lnk"
              if sys.platform == "win32" else Path.home() / "Library/LaunchAgents/com.onedock.dock.plist")


def _on_this_mac(request: Request) -> bool:
    host = request.headers.get("host", "").split(":")[0]
    return host in ("localhost", "127.0.0.1") and "cf-connecting-ip" not in request.headers


def routes(hub: Hub, token: str, static_dir, calendar=None, downloads=None, mail=None, briefing=None) -> list[Route]:
    bedrock_check = {"at": 0.0, "ok": False, "error": ""}

    async def check_bedrock() -> dict:
        if time.time() - bedrock_check["at"] > BEDROCK_CHECK_SECONDS:
            try:
                await asyncio.to_thread(bedrock.ask, "Say OK", "Reply with OK.", 5)
                bedrock_check.update(ok=True, error="")
            except Exception as e:
                bedrock_check.update(ok=False, error=str(e)[:200])
            bedrock_check["at"] = time.time()
        return bedrock_check

    async def page(request: Request):
        if not _on_this_mac(request):
            return JSONResponse({"error": "Open the setup page on the Mac itself."}, status_code=403)
        return FileResponse(static_dir / "setup.html")

    async def status(request: Request):
        if not _on_this_mac(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        allowed = {}
        if hub.agent is not None:
            try:
                allowed = await hub.ask_agent("permissions")
            except (AgentOffline, AgentError):
                pass
        accessibility = allowed.get("accessibility")
        url = tunnel.public_url()
        # The installed app's fixed address if it's ready (the token goes after "#",
        # so it never reaches the web host); else the tunnel's own address.
        if url and webapp.app_url():
            phone_url = f"{webapp.app_url()}#token={token}"
        else:
            phone_url = f"{url}/?token={token}" if url else ""
        qr = qrcode.make(phone_url, image_factory=qrcode.image.svg.SvgPathImage).to_string(encoding="unicode") if phone_url else ""
        check = await check_bedrock()
        return JSONResponse({
            "agent": hub.agent is not None,
            "platform": hub.platform, "talk_key": hub.talk_key,
            "accessibility": accessibility,
            "bedrock": check["ok"], "bedrock_error": check["error"], "model": bedrock.MODEL_ID,
            "phone_url": phone_url, "qr_svg": qr, "tunnel_problem": tunnel.problem(),
            "phones": hub.real_phones(),
            "microphone": allowed.get("microphone"), "screen": allowed.get("screen"),
            "talked": hub.talked,
            "start_at_login": LOGIN_ITEM.exists(),
            "fixed_address": bool(webapp.app_url()), "webapp_problem": webapp.problem(),
            "calendar": calendar.connected if calendar else "",
            "folder_suggestions": bool(downloads and downloads.automatic),
            "google_ready": google_account.ready(), "google_problem": google_state["problem"],
            "google_busy": google_state["busy"], "google_address": google_account.address(),
            "mail": mail.connected if mail else "", "let_through": ", ".join(mail.let_through) if mail else "",
            "briefing": bool(briefing and briefing.on),
        })

    async def open_accessibility(request: Request):
        if not _on_this_mac(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        try:
            await hub.ask_agent("open_accessibility_settings")
        except (AgentOffline, AgentError) as e:
            return JSONResponse({"ok": False, "error": str(e) or "The desktop agent isn't running."})
        return JSONResponse({"ok": True})

    async def agent_job(request: Request, action: str):
        if not _on_this_mac(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        try:
            await hub.ask_agent(action)
        except (AgentOffline, AgentError) as e:
            return JSONResponse({"ok": False, "error": str(e) or "The desktop agent isn't running."})
        return JSONResponse({"ok": True})

    async def ask_speech(request: Request):
        return await agent_job(request, "ask_speech_permission")

    async def ask_screen(request: Request):
        return await agent_job(request, "ask_screen_permission")

    google_state = {"busy": False, "problem": ""}

    async def sign_in_google(request: Request):
        """Open Google's sign-in page in the browser (Calendar and Gmail in one); the status shows when it's done."""
        if not _on_this_mac(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        if not google_account.ready():
            return JSONResponse({"ok": False, "error": "Google sign-in isn't set up for this copy of Dock yet."})
        if not google_state["busy"]:
            google_state.update(busy=True, problem="")

            async def wait_for_user():
                try:
                    await asyncio.to_thread(google_account.sign_in)
                    calendar.ensure_watch()
                    mail.ensure_watch()
                except Exception as e:
                    google_state["problem"] = f"Google sign-in didn't finish: {str(e)[:120]}"
                finally:
                    google_state["busy"] = False

            asyncio.get_running_loop().create_task(wait_for_user())
        return JSONResponse({"ok": True})

    async def sign_out_google(request: Request):
        if not _on_this_mac(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        google_account.sign_out()
        return JSONResponse({"ok": True})

    async def set_folder_suggestions(request: Request):
        if not _on_this_mac(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        await downloads.set_automatic(bool((await request.json()).get("on")))
        return JSONResponse({"ok": True})

    async def set_start_at_login(request: Request):
        if not _on_this_mac(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        try:
            await hub.ask_agent("start_at_login", on=bool((await request.json()).get("on")))
        except (AgentOffline, AgentError) as e:
            return JSONResponse({"ok": False, "error": str(e) or "Dock isn't running."})
        return JSONResponse({"ok": True})

    async def save_mail(request: Request):
        """Email settings: who may reach you during focus, and the morning briefing."""
        if not _on_this_mac(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        body = await request.json()
        if "let_through" in body:
            return JSONResponse({"ok": True, "let_through": mail.set_let_through(str(body["let_through"]))})
        if "briefing" in body:
            briefing.set_on(bool(body["briefing"]))
        return JSONResponse({"ok": True})

    async def show_window(request: Request):
        return await agent_job(request, "show_welcome")

    return [
        Route("/setup/speech", ask_speech, methods=["POST"]),
        Route("/setup/screen", ask_screen, methods=["POST"]),
        Route("/setup/google", sign_in_google, methods=["POST"]),
        Route("/setup/google-off", sign_out_google, methods=["POST"]),
        Route("/setup/folder-suggestions", set_folder_suggestions, methods=["POST"]),
        Route("/setup/login", set_start_at_login, methods=["POST"]),
        Route("/setup/mail", save_mail, methods=["POST"]),
        Route("/setup/show-window", show_window, methods=["POST"]),
        Route("/setup", page),
        Route("/setup/status", status),
        Route("/setup/accessibility", open_accessibility, methods=["POST"]),
    ]
