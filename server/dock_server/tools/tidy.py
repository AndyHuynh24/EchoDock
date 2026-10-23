"""Downloads tidy-up: suggest folders, ask about unclear files, move only after the user agrees.

Moves can be undone and are logged in .data/moves.json to learn the user's habits.
"""

import asyncio
import json
import re
import time

from pydantic import BaseModel

from dock_server import bedrock
from dock_server.hub import AgentError, AgentOffline, Hub
from dock_server.savings import Savings
from dock_server.state import DATA_DIR, State
from dock_server.tools.computer import run_on_computer

PLAN_SYSTEM = (
    "You help a student tidy their Mac's Downloads folder. For each downloaded file, "
    "decide which of their existing folders it belongs in, using what the file says (its "
    "start, when Dock could read it), the file name, the website it came from, where the "
    "user put similar files before, and the folder names. What the file says matters most: "
    "a PDF called \"document (3).pdf\" that starts with \"STAT 525 Homework 4\" goes with "
    "STAT 525. Only suggest a move when you are sure; never force one. If no folder really fits, "
    "or you'd be guessing, leave the file out (it stays in Downloads, which is fine). A folder "
    "must really fit the file, not just be the closest one: resumes and cover letters don't go in a school folder (use a "
    "Career folder, new if needed), and when only the name hints at a project, the words must "
    "match (an \"echocase\" model isn't a keyboard case). Watch numbers: HW4 files don't belong in an HW2 folder; use the course folder "
    "or suggest a new HW4 folder next to HW2 instead. If a new folder inside an existing "
    "one would clearly help (for example Documents/Career for resumes), you may suggest it "
    "with new_folder true. Ask a short question only when "
    "one answer would sort several unsure files (group them); otherwise just leave them out. Dock never deletes files, so never "
    "ask about deleting or discarding; unsure files can simply stay in Downloads. Leave "
    "installers alone.\n"
    "Reply with only JSON in this shape:\n"
    '{"moves": [{"file": "exact file name", "to": "folder path from the list", '
    '"new_folder": false, "why": "few words"}], "questions": ["short question"]}\n'
    'For a new folder, "to" is its full new path (like "Documents/Career", inside a folder from the '
    'list) and "new_folder" is true. "why" only says why the file goes there.'
)


MOVES_FILE = DATA_DIR / "moves.json"
MOVES_KEPT = 200


def past_moves(count: int = 30) -> list[dict]:
    """Recent moves, newest last."""
    return json.loads(MOVES_FILE.read_text())[-count:] if MOVES_FILE.exists() else []


def remember_moves(moved: list[dict]) -> None:
    history = past_moves(MOVES_KEPT) + [{"file": m["file"], "to": m["to"]} for m in moved]
    DATA_DIR.mkdir(exist_ok=True)
    MOVES_FILE.write_text(json.dumps(history[-MOVES_KEPT:], indent=1))


class Move(BaseModel):
    file: str
    to: str
    new_folder: bool = False


DELETE_WORDS = re.compile(r"\b(delet\w*|discard\w*|trash\w*|remov\w*|get rid of|throw\w* (?:away|out)|bin)\b", re.IGNORECASE)


def _parse_plan(answer: str, files: set[str], folders: set[str]) -> tuple[list[dict], list[str]]:
    match = re.search(r"\{.*\}", answer, re.DOTALL)
    try:
        plan = json.loads(match.group()) if match else {}
    except json.JSONDecodeError:
        plan = {}
    moves = []
    for move in plan.get("moves", []):
        file, to = str(move.get("file", "")), str(move.get("to", "")).strip("/")
        new_folder = bool(move.get("new_folder"))
        if new_folder and to in folders:
            continue
        if file in files and (to in folders or (new_folder and to.rsplit("/", 1)[0] in folders)):
            moves.append({"file": file, "to": to, "new_folder": new_folder and to not in folders, "why": str(move.get("why", ""))})
    # Dock never deletes files.
    questions = [str(q) for q in plan.get("questions", []) if not DELETE_WORDS.search(str(q))]
    return moves, questions[:3]


async def move(hub: Hub, state: State, savings: Savings, moves: list[dict]) -> dict:
    result = await hub.ask_agent("move_files", timeout=20, moves=moves)
    moved = result["moved"]
    remember_moves(moved)
    if moved:
        state.last_move_at = time.time()
    moved_names = {m["file"] for m in moved}
    state.tidy_plan[:] = [m for m in state.tidy_plan if m["file"] not in moved_names]
    for name in moved_names & set(state.new_downloads):
        del state.new_downloads[name]
        await hub.push_phone("download_done", file=name)
    await savings.add("file_moved", len(moved))
    if moved:
        detail = ", ".join(f"{m['file']} → {m['to']}" for m in moved[:4]) + (" …" if len(moved) > 4 else "")
        await hub.push_phone("card", title=f"Moved {len(moved)} file{'s' if len(moved) != 1 else ''}", detail=detail)
    return result


def _moved_text(result: dict) -> str:
    moved, problems = result["moved"], result["problems"]
    text = f"Moved {len(moved)} file{'s' if len(moved) != 1 else ''}." if moved else "I didn't move anything."
    if problems:
        text += " Problems: " + "; ".join(p.rstrip(".") for p in problems[:3]) + "."
    if moved:
        text += " Say undo if you want them back."
    return text


async def move_from_phone(hub: Hub, state: State, savings: Savings, message: dict) -> None:
    """The user ticked suggestions on the phone and tapped Move."""
    picked = [state.tidy_plan[n] for n in message.get("items", []) if isinstance(n, int) and 0 <= n < len(state.tidy_plan)]
    if not picked:
        return
    try:
        result = await move(hub, state, savings, picked)
    except (AgentOffline, AgentError) as e:
        await hub.push_phone("card", title="Couldn't move the files", detail=str(e) or "The computer isn't connected.")
        return
    if result["problems"]:
        await hub.push_phone("card", title="Some files weren't moved", detail="; ".join(result["problems"][:3]))


async def plan(hub: Hub, state: State) -> str:
    """Suggest a folder for each file in Downloads. Moves nothing."""
    overview = await run_on_computer(hub, "downloads_overview", timeout=20)
    if not overview["files"]:
        return "Your Downloads folder is already empty."
    files = "\n".join(
        f"- {f['name']} (changed {f['changed']}, {f['size_kb']} KB" + (f", from {f['from']}" if f["from"] else "") + ")"
        + (f"\n  says: {f['says']}" if f.get("says") else "")
        for f in overview["files"]
    )
    past = "\n".join(f"- {m['file']} → {m['to']}" for m in past_moves()) or "(none yet)"
    prompt = (f"Downloaded files:\n{files}\n\nWhere the user put earlier files:\n{past}"
              "\n\nThe user's folders:\n" + "\n".join(overview["folders"]))
    answer = await asyncio.to_thread(bedrock.ask, prompt, PLAN_SYSTEM, 1500, bedrock.SMART_MODEL_ID, purpose="tidy plan")
    moves, questions = _parse_plan(answer, {f["name"] for f in overview["files"]}, set(overview["folders"]))
    state.tidy_plan[:] = moves
    state.tidy_plan_at = time.time()
    await hub.push_phone("plan", moves=moves, questions=questions)

    if not moves and not questions:
        return "I looked through your Downloads but I'm not sure where any of the files belong."
    count = len(moves)
    text = f"I have {count} suggestion{'s' if count != 1 else ''} for your Downloads"
    if questions:
        text += f", and {'a question' if len(questions) == 1 else f'{len(questions)} questions'} on the card"
    return text + ". Check the list, then tap Move selected or say yes."


async def undo(hub: Hub) -> str:
    """Undo the most recent moves."""
    result = await run_on_computer(hub, "undo_moves")
    restored = result["restored"]
    # Don't learn from undone moves.
    history = past_moves(MOVES_KEPT)
    for name in restored:
        for n in range(len(history) - 1, -1, -1):
            if history[n]["file"] == name:
                del history[n]
                break
    if MOVES_FILE.exists():
        MOVES_FILE.write_text(json.dumps(history, indent=1))
    await hub.push_phone("card", title=f"Put back {len(restored)} files", detail=", ".join(restored[:4]))
    return f"Done, I put {len(restored)} file{'s' if len(restored) != 1 else ''} back in Downloads."
