"""Focus mode: timer, desk presence, drift nudges, breaks and session reports.

Sessions are logged to .data/focus_log.json for the weekly report.
"""

import asyncio
import json
import re
import time
from datetime import date, datetime, timedelta

from dock_server import bedrock
from dock_server.hub import AgentError, AgentOffline, Hub
from dock_server.state import DATA_DIR, State

LOG_FILE = DATA_DIR / "focus_log.json"
TICK_SECONDS = 1
WINDOW_CHECK_SECONDS = 15
DRIFT_NUDGE_SECONDS = 120
WELCOME_BACK_AFTER_SECONDS = 60
PUSH_EVERY_SECONDS = 15

DISTRACTING = (
    "youtube", "netflix", "tiktok", "instagram", "facebook", "reddit", "twitter", "twitch", "hulu",
    "disney+", "prime video", "pinterest", "tumblr", "9gag", "discord", "steam", "roblox", "minecraft",
)
GOAL_FILLER = {"my", "the", "a", "an", "on", "for", "and", "to", "of", "work", "session", "focus", "some"}

RELEVANCE_SYSTEM = (
    "You decide whether what a student is looking at helps with their focus goal. "
    "Answer with only yes or no."
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in GOAL_FILLER}


def _minutes(seconds: float) -> int:
    return round(seconds / 60)


def _span(minutes: int) -> str:
    return f"{minutes} minute{'s' if minutes != 1 else ''}" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


class FocusMode:
    def __init__(self, hub: Hub, state: State):
        self.hub = hub
        self.state = state
        self.session: dict | None = None
        self.relevance_cache: dict[str, bool] = {}
        self._task: asyncio.Task | None = None

    # ---- phone display ----

    def _view(self) -> dict:
        s = self.session
        if not s:
            return {"kind": "focus", "state": "idle"}
        remaining = max(0, s["planned"] - s["focused"]) if s["planned"] else None
        return {
            "kind": "focus", "state": s["state"], "goal": s["goal"], "planned": s["planned"],
            "focused": round(s["focused"]), "remaining": round(remaining) if remaining is not None else None,
            "away": round(s["away"]), "drift": round(s["drift"]), "drifting": s["drift_run"] >= DRIFT_NUDGE_SECONDS,
            "break_left": round(max(0, s["break_until"] - time.time())) if s["state"] == "break" else None,
        }

    async def push(self) -> None:
        view = self._view()
        await self.hub.push_phone(view.pop("kind"), **view)

    async def phone_connected(self, ws) -> None:
        await ws.send_text(json.dumps(self._view()))

    async def say(self, text: str) -> None:
        await self.hub.push_phone("say", text=text)

    # ---- start / pause / resume / end ----

    async def start(self, goal: str = "", minutes: int = 0) -> str:
        if self.session and self.session["state"] in ("running", "away", "paused"):
            return f"A session for {self.session['goal']} is already running. Say end session first."
        goal = goal.strip() or "deep work"
        now = time.time()
        self.session = {
            "goal": goal, "goal_words": _words(goal), "planned": max(0, minutes) * 60,
            "started": now, "state": "running", "last_tick": now, "last_check": 0.0, "last_push": now,
            "focused": 0.0, "away": 0.0, "paused": 0.0, "drift": 0.0, "drift_run": 0.0, "nudged": False,
            "away_since": None, "away_count": 0, "app_seconds": {}, "goal_apps": set(),
            "last_on_task": {}, "questions_at_start": len(self.state.questions), "break_until": 0.0, "report": None,
        }
        try:
            front = await self.hub.ask_agent("front_window")
            self.session["goal_apps"].add(front["app"])
        except (AgentOffline, AgentError):
            pass
        self._ensure_clock()
        await self.push()
        length = f"for {_span(minutes)}" if minutes else "until you end it"
        return f"Started your {goal} session {length}."

    def _ensure_clock(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def pause(self) -> str:
        s = self.session
        if not s or s["state"] not in ("running", "away"):
            return "There's no running session to pause."
        self._tick()
        s["state"] = "paused"
        await self.push()
        return "Paused. Say resume when you're ready."

    async def resume(self) -> str:
        s = self.session
        if not s or s["state"] != "paused":
            return "There's no paused session."
        self._tick()
        s["state"] = "running"
        await self.push()
        return f"Resumed your {s['goal']} session."

    async def end(self, completed: bool | None = None) -> str:
        s = self.session
        if s and s["state"] == "break":
            s["state"] = "done"
            await self.push()
            return "Break's over. Nice work today."
        if not s or s["state"] == "done":
            if s and completed is not None:
                return await self.mark_finished(completed)
            return "There's no focus session running."
        self._tick()
        report = await self._finish(completed)
        return self._report_text(report)

    async def mark_finished(self, completed: bool) -> str:
        """Answer to "did you finish your goal?"."""
        log = self._load_log()
        if log:
            log[-1]["completed"] = completed
            self._save_log(log)
        if self.session and self.session.get("report"):
            self.session["report"]["completed"] = completed
        return "Nice work, goal done!" if completed else "No problem. You can pick it up next session."

    async def _finish(self, completed: bool | None) -> dict:
        s = self.session
        s["state"] = "done"
        try:
            files = (await self.hub.ask_agent("files_changed_since", timeout=10, timestamp=s["started"]))["files"]
        except (AgentOffline, AgentError):
            files = []
        apps = sorted(s["app_seconds"].items(), key=lambda kv: -kv[1])[:5]
        focused = max(1.0, s["focused"])
        report = {
            "goal": s["goal"], "date": date.today().isoformat(), "start": datetime.fromtimestamp(s["started"]).isoformat(timespec="minutes"),
            "planned_min": _minutes(s["planned"]), "focused_min": _minutes(s["focused"]), "away_min": _minutes(s["away"]),
            "away_count": s["away_count"], "drift_min": _minutes(s["drift"]),
            "on_task_pct": max(0, round(100 * (focused - s["drift"]) / focused)),
            "apps": [{"app": a, "minutes": _minutes(sec)} for a, sec in apps],
            "files": [f["name"] for f in files[:8]], "questions": len(self.state.questions) - s["questions_at_start"],
            "completed": completed,
        }
        s["report"] = report
        log = self._load_log()
        log.append(report)
        self._save_log(log)
        await self.push()
        await self.hub.push_phone("focus_report", **report, cards=self.flashcards())
        return report

    def _report_text(self, r: dict) -> str:
        text = f"Session done: {_span(r['focused_min'])} on {r['goal']}"
        if r["away_min"]:
            text += f", {_span(r['away_min'])} away"
        if r["drift_min"]:
            text += f", {_span(r['drift_min'])} drifting"
        text += f". You were on task {r['on_task_pct']}% of the time"
        if r["files"]:
            text += f" and changed {len(r['files'])} file{'s' if len(r['files']) != 1 else ''}"
        return text + ". Did you finish your goal?"

    # ---- breaks ----

    async def start_break(self, minutes: int = 0) -> str:
        s = self.session
        if not s:
            return "Start a focus session first."
        minutes = minutes or max(5, min(15, round(_minutes(s["planned"] or s["focused"]) / 5)))
        s["state"] = "break"
        s["break_until"] = time.time() + minutes * 60
        s["last_tick"] = time.time()
        self._ensure_clock()
        await self.push()
        await self.hub.push_phone("flashcards", cards=self.flashcards())
        return f"Enjoy a {minutes} minute break. I put some shortcut flashcards on your phone."

    def flashcards(self) -> list[dict]:
        """Shortcuts asked about, or the pad's shortcuts if none."""
        cards = list(self.state.shortcuts_seen.values())
        if not cards and self.state.pad:
            cards = [{"app": self.state.pad["app"], "name": b["title"], "shortcut": b["shortcut"]}
                     for b in self.state.pad.get("buttons", []) if b.get("shortcut")]
        return cards[:12]

    # ---- presence ----

    async def presence(self, present: bool) -> None:
        s = self.session
        if not s or s["state"] not in ("running", "away"):
            return
        self._tick()
        if not present and s["state"] == "running":
            s["state"], s["away_since"] = "away", time.time()
            s["away_count"] += 1
            await self.push()
        elif present and s["state"] == "away":
            gone = time.time() - (s["away_since"] or time.time())
            s["state"], s["away_since"] = "running", None
            await self.push()
            if gone >= WELCOME_BACK_AFTER_SECONDS:
                await self._welcome_back()

    async def _welcome_back(self) -> None:
        last = self.session["last_on_task"]
        where = last.get("document", "").rsplit("/", 1)[-1] or last.get("app", "")
        await self.say(f"Welcome back! You were working in {where}." if where else "Welcome back!")
        try:
            if last.get("document"):
                await self.hub.ask_agent("open_path", path=last["document"])
            elif last.get("app"):
                await self.hub.ask_agent("open_app", name=last["app"])
        except (AgentOffline, AgentError):
            pass

    async def skip_to_end(self, seconds: int = 3) -> bool:
        """Test remote: end the running session in a few seconds."""
        s = self.session
        if not s or s["state"] not in ("running", "away", "paused"):
            return False
        self._tick()
        if not s["planned"]:
            s["planned"] = s["focused"] + seconds
        s["focused"] = max(s["focused"], s["planned"] - seconds)
        print(f"Remote: focus timer skipped to the last {seconds} s")
        await self.push()
        return True

    # ---- the clock ----

    def _tick(self) -> None:
        s = self.session
        now = time.time()
        passed, s["last_tick"] = now - s["last_tick"], now
        bucket = {"running": "focused", "away": "away", "paused": "paused"}.get(s["state"])
        if bucket:
            s[bucket] += passed

    async def _run(self) -> None:
        while self.session and self.session["state"] in ("running", "away", "paused", "break"):
            await asyncio.sleep(TICK_SECONDS)
            s = self.session
            if not s:
                break
            self._tick()
            now = time.time()
            try:
                if s["state"] == "running" and now - s["last_check"] >= WINDOW_CHECK_SECONDS:
                    s["last_check"] = now
                    await self._check_window()
                if s["state"] == "running" and s["planned"] and s["focused"] >= s["planned"]:
                    report = await self._finish(None)
                    await self.say(f"Time's up! You focused {_span(report['focused_min'])} on {report['goal']}. "
                                   "Take a break, and check out your shortcut flashcards.")
                    continue
                if s["state"] == "break" and now >= s["break_until"]:
                    s["state"] = "done"
                    await self.push()
                    await self.say("Break's over. Ready for another round?")
                    continue
                if now - s["last_push"] >= PUSH_EVERY_SECONDS:
                    s["last_push"] = now
                    await self.push()
            except Exception as e:
                print(f"Focus loop: {e!r}")

    # ---- drift ----

    async def _check_window(self) -> None:
        s = self.session
        try:
            window = await self.hub.ask_agent("front_window")
        except (AgentOffline, AgentError):
            return
        app, title, document = window["app"], window["title"], window["document"]
        s["app_seconds"][app] = s["app_seconds"].get(app, 0) + WINDOW_CHECK_SECONDS
        verdict = await self._classify(app, title, document)
        if verdict == "on":
            s["last_on_task"] = {"app": app, "document": document, "title": title}
        if verdict == "off":
            s["drift"] += WINDOW_CHECK_SECONDS
            s["drift_run"] += WINDOW_CHECK_SECONDS
            if s["drift_run"] >= DRIFT_NUDGE_SECONDS and not s["nudged"]:
                s["nudged"] = True
                await self.push()
                await self.hub.push_phone("nudge", text=f"Back to {s['goal']}?", detail=f"You've been on {title or app} for a couple of minutes.")
        elif s["drift_run"]:
            was_drifting = s["drift_run"] >= DRIFT_NUDGE_SECONDS
            s["drift_run"], s["nudged"] = 0.0, False
            if was_drifting:
                await self.push()

    async def _classify(self, app: str, title: str, document: str) -> str:
        """"on", "off" or "neutral" relative to the goal."""
        s = self.session
        text = f"{app} {title} {document}"
        if s["goal_words"] & _words(text):
            return "on"
        distracting = any(d in text.lower() for d in DISTRACTING)
        if not distracting:
            return "on" if app in s["goal_apps"] else "neutral"
        key = f"{s['goal']}|{app}|{title}"
        if key not in self.relevance_cache:
            # Recent apps and files give the model context for the goal.
            last = s["last_on_task"]
            working_in = ", ".join(sorted(a for a in s["goal_apps"] if a != app))
            if last.get("document"):
                working_in += f" (file: {last['document'].rsplit('/', 1)[-1]})"
            prompt = (f"Focus goal: {s['goal']}\nThey have been working in: {working_in or 'unknown'}\n"
                      f"Now they are looking at: {app} — {title}\nIs this probably helping with the goal?")
            try:
                answer = await asyncio.to_thread(bedrock.ask, prompt, RELEVANCE_SYSTEM, 5, purpose="on-task check")
            except Exception:
                answer = "no"
            verdict = re.match(r"\W*(yes|no)", answer, re.IGNORECASE)
            self.relevance_cache[key] = bool(verdict) and verdict.group(1).lower() == "yes"
        return "on" if self.relevance_cache[key] else "off"

    # ---- status and reports ----

    def status(self) -> str:
        s = self.session
        if not s or s["state"] == "done":
            return "No focus session is running right now."
        self._tick()
        if s["state"] == "break":
            return f"You're on a break, {_span(max(1, _minutes(s['break_until'] - time.time())))} left."
        text = f"You've focused {_span(_minutes(s['focused']))} on {s['goal']}"
        if s["planned"]:
            text += f", {_span(max(0, _minutes(s['planned'] - s['focused'])))} to go"
        if s["state"] == "paused":
            text += ". It's paused right now"
        elif s["state"] == "away":
            text += ". The timer is paused while you're away"
        return text + "."

    def _load_log(self) -> list[dict]:
        return json.loads(LOG_FILE.read_text()) if LOG_FILE.exists() else []

    def _save_log(self, log: list[dict]) -> None:
        DATA_DIR.mkdir(exist_ok=True)
        LOG_FILE.write_text(json.dumps(log, indent=2))

    async def week_report(self) -> str:
        """Last 7 days: minutes per day, goals finished, focus quality."""
        today = date.today()
        days = [today - timedelta(days=n) for n in range(6, -1, -1)]
        log = [r for r in self._load_log() if r["date"] >= days[0].isoformat()]
        per_day = [{"day": d.strftime("%a"), "minutes": sum(r["focused_min"] for r in log if r["date"] == d.isoformat())} for d in days]
        total = sum(d["minutes"] for d in per_day)
        finished = sum(1 for r in log if r.get("completed"))
        on_task = round(sum(r["on_task_pct"] * r["focused_min"] for r in log) / total) if total else 0
        goals: dict[str, int] = {}
        for r in log:
            goals[r["goal"]] = goals.get(r["goal"], 0) + r["focused_min"]
        top = sorted(goals.items(), key=lambda kv: -kv[1])[:3]
        await self.hub.push_phone("week_report", days=per_day, total=total, sessions=len(log), finished=finished,
                                  on_task=on_task, goals=[{"goal": g, "minutes": m} for g, m in top])
        if not log:
            return "No focus sessions in the last 7 days yet."
        best = max(per_day, key=lambda d: d["minutes"])
        text = (f"This week you focused {_span(total)} over {len(log)} session{'s' if len(log) != 1 else ''}, "
                f"finished {finished} goal{'s' if finished != 1 else ''}, and stayed on task {on_task}% of the time. ")
        text += f"Your best day was {best['day']}"
        if top:
            text += f", and most of your time went to {top[0][0]}"
        return text + "."

    # ---- phone buttons ----

    async def from_phone(self, message: dict) -> None:
        kind = message.get("kind")
        if kind == "start_focus":
            text = await self.start(str(message.get("goal", "")), int(message.get("minutes") or 0))
            if not text.startswith("Started"):
                await self.hub.push_phone("card", title="Focus mode", detail=text)
        elif kind == "pause_focus":
            await self.pause()
        elif kind == "resume_focus":
            await self.resume()
        elif kind == "end_focus":
            await self.end()
        elif kind == "presence":
            await self.presence(bool(message.get("present")))
        elif kind == "focus_finished":
            await self.mark_finished(bool(message.get("completed")))
        elif kind == "start_break":
            await self.start_break()
        elif kind == "week_report":
            await self.week_report()
