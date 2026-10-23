"""Actions the server may run on Windows (same names and replies as the Mac agent).
Anything not in ACTIONS is refused.
"""

import os
import time

from dock_agent import documents, files, tidy
from dock_agent.win import apps, arrange, bubble, menus, onscreen, overlay, reading, recap, savepanel, tray, winapi, workspaces
from dock_agent.workspaces_common import WorkspaceError


class ActionError(Exception):
    """An error message meant for the user."""


def open_folder(name: str, close: bool = True) -> dict:
    try:
        return files.open_folder(name, close)
    except files.SearchError as e:
        raise ActionError(str(e))


def find_files(name: str = "", kind: str = "", folder: str = "", days: int = 0) -> dict:
    try:
        return files.find_files(name=name, kind=kind, folder=folder, days=days)
    except files.SearchError as e:
        raise ActionError(str(e))


def open_path(path: str, show_in_finder: bool = False) -> dict:
    try:
        return files.open_path(path, show_in_finder)
    except files.SearchError as e:
        raise ActionError(str(e))


def arrange_windows(layout: list[dict], screen: str = "this", hide_others: bool = False) -> dict:
    try:
        return arrange.arrange(layout, screen, hide_others)
    except arrange.ArrangeError as e:
        raise ActionError(str(e))


def open_url(url: str) -> dict:
    """Open an https link in the default browser."""
    if not url.startswith("https://"):
        raise ActionError("I only open https links.")
    os.startfile(url)
    return {}


def folder_names() -> dict:
    return {"names": files.spoken_folder_names()}


def find_folder(name: str) -> dict:
    matches = [p for p in files.find_folders(name) if files._norm(p.name) == files._norm(name)]
    return {"folder": matches[0].name, "where": files.where(matches[0])} if matches else {}


def open_app(name: str, exact: bool = False) -> dict:
    try:
        return apps.open_app(name, exact)
    except apps.AppNotFound as e:
        raise ActionError(str(e))


def save_workspace(name: str) -> dict:
    try:
        return workspaces.save(name)
    except WorkspaceError as e:
        raise ActionError(str(e))


def open_workspace(name: str) -> dict:
    try:
        return workspaces.open_workspace(name)
    except WorkspaceError as e:
        raise ActionError(str(e))


def list_workspaces() -> dict:
    return {"names": workspaces.list_all()}


def open_app_names() -> dict:
    return {"names": apps.open_app_names()}


def bring_app_forward(name: str) -> dict:
    try:
        return apps.bring_app_forward(name)
    except apps.AppNotFound as e:
        raise ActionError(str(e))


def downloads_overview() -> dict:
    return tidy.overview()


def move_files(moves: list[dict]) -> dict:
    return tidy.move(moves)


def undo_moves() -> dict:
    try:
        return tidy.undo()
    except tidy.TidyError as e:
        raise ActionError(str(e))


def point_at_save_folder(label: str) -> dict:
    return savepanel.point(label)


def save_in_folder(folder: str, new_folder: bool = False) -> dict:
    try:
        return savepanel.save_in(folder, new_folder)
    except (savepanel.SavePanelError, tidy.TidyError) as e:
        raise ActionError(str(e))


def read_text(path: str = "") -> dict:
    if not path:
        _bring_forward(menus.front_app()[1])
    try:
        return reading.read_text(path)
    except reading.ReadError as e:
        raise ActionError(str(e))


def day_recap(day: str = "today") -> dict:
    return recap.day_recap(day)


def permissions() -> dict:
    """Only the microphone has a permission on Windows."""
    from dock_agent import speech
    return {"accessibility": True, **speech.permissions(), "screen": True}


def open_accessibility_settings() -> dict:
    return {}


def ask_speech_permission() -> dict:
    from dock_agent import speech
    speech.ask_permission()
    return {}


def ask_screen_permission() -> dict:
    return {}


def window_controls() -> dict:
    return onscreen.window_controls()


def highlight_control(number: int, label: str) -> dict:
    try:
        overlay.show(onscreen.control_rect(number), label)
    except LookupError as e:
        raise ActionError(str(e))
    return {}


def _same_app(pid: int) -> None:
    name, front_pid = menus.front_app()
    if front_pid != pid:
        raise ActionError(f"{name} is in front now. Switch back to the app I was helping with and try again.")


def _bring_forward(pid: int) -> None:
    """Give the keyboard back to the user's app (close the chat box first)."""
    if bubble.has_keyboard():
        bubble.compose(False)
    hwnd = winapi.window_of(pid)
    if hwnd and winapi.foreground() != hwnd:
        if not winapi.bring_forward(hwnd):
            print(f"Couldn't give the keyboard back to {winapi.title(hwnd)}")
    time.sleep(0.15)


def press_control(pid: int, number: int) -> dict:
    overlay.hide()
    _same_app(pid)
    _bring_forward(pid)
    try:
        onscreen.press_control(number)
    except LookupError as e:
        raise ActionError(str(e))
    return {}


def window_screenshot() -> dict:
    try:
        return onscreen.window_screenshot()
    except (onscreen.NotAllowed, LookupError) as e:
        raise ActionError(str(e))


def screen_region(rect: list[float]) -> dict:
    return onscreen.screen_region(rect)


def highlight_spot(rect: list[float], label: str) -> dict:
    overlay.show(tuple(rect), label)
    return {}


def click_spot(pid: int, x: float, y: float) -> dict:
    overlay.hide()
    _same_app(pid)
    _bring_forward(pid)
    onscreen.click(x, y)
    return {}


def chat_box(open: bool) -> dict:
    bubble.compose(bool(open))
    return {}


def start_at_login(on: bool) -> dict:
    tray.apply_start_at_login(bool(on))
    return {}


def show_welcome() -> dict:
    bubble.show_welcome()
    return {}


def front_app() -> dict:
    name, pid = menus.front_app()
    return {"app": name, "pid": pid}


def front_window() -> dict:
    name, pid = menus.front_app()
    title, document = menus.front_window(pid)
    return {"app": name, "pid": pid, "title": title, "document": document}


def files_changed_since(timestamp: float) -> dict:
    return {"files": recap.files_changed_since(timestamp)}


def app_menus() -> dict:
    name, pid = menus.front_app()
    return {"app": name, "pid": pid, "items": menus.read_menus(pid)}


def selection_size() -> dict:
    """Length of the selection (via UI Automation, nothing copied)."""
    name, _ = menus.front_app()
    return {"app": name, "chars": len(reading.selected_by_uia().strip())}


def selected_text() -> dict:
    _, pid = menus.front_app()
    _bring_forward(pid)
    try:
        return reading.selection()
    except reading.ReadError as e:
        raise ActionError(str(e))


def replace_selected_text(pid: int, text: str) -> dict:
    _same_app(pid)
    _bring_forward(pid)
    return {"how": reading.replace_selection(pid, text)}


def insert_below_selection(pid: int, text: str) -> dict:
    _same_app(pid)
    _bring_forward(pid)
    return {"how": reading.insert_after_selection(pid, text)}


def save_panel_text() -> dict:
    """Start of the document in the open Save dialog."""
    _, pid = menus.front_app()
    return {"text": reading.window_text(pid)}


def file_start(path: str) -> dict:
    try:
        return {"text": reading.file_text(path)[:reading.WINDOW_TEXT_CHARS]}
    except reading.ReadError:
        return {"text": ""}


def menu_item_enabled(pid: int, path: list[str]) -> dict:
    try:
        return {"enabled": menus.item_enabled(pid, path)}
    except Exception:
        return {"enabled": None}


def highlight_menu(pid: int, path: list[str], label: str) -> dict:
    try:
        rect = menus.show(pid, path)
    except LookupError:
        raise ActionError(f"I couldn't find {path[-1]} in the menus anymore.")
    if rect is None:
        raise ActionError("I couldn't see that menu on the screen.")
    overlay.show(rect, label, on_hide=lambda: menus.close(pid, path))
    return {}


def press_menu(pid: int, path: list[str]) -> dict:
    overlay.hide()
    _same_app(pid)
    _bring_forward(pid)
    try:
        menus.press(pid, path)
    except menus.MenuItemDisabled:
        raise ActionError(f"{path[-1]} is greyed out right now, so you may need to select something first.")
    except LookupError:
        raise ActionError(f"I couldn't find {path[-1]} in the menus anymore.")
    return {}


ACTIONS = {
    "open_folder": open_folder,
    "find_files": find_files,
    "open_path": open_path,
    "open_app": open_app,
    "find_folder": find_folder,
    "folder_names": folder_names,
    "arrange_windows": arrange_windows,
    "open_url": open_url,
    "save_workspace": save_workspace,
    "open_workspace": open_workspace,
    "list_workspaces": list_workspaces,
    "open_app_names": open_app_names,
    "bring_app_forward": bring_app_forward,
    "downloads_overview": downloads_overview,
    "list_documents": documents.list_documents,
    "document_texts": documents.document_texts,
    "move_files": move_files,
    "undo_moves": undo_moves,
    "point_at_save_folder": point_at_save_folder,
    "save_in_folder": save_in_folder,
    "read_text": read_text,
    "day_recap": day_recap,
    "permissions": permissions,
    "open_accessibility_settings": open_accessibility_settings,
    "ask_speech_permission": ask_speech_permission,
    "ask_screen_permission": ask_screen_permission,
    "window_controls": window_controls,
    "highlight_control": highlight_control,
    "press_control": press_control,
    "window_screenshot": window_screenshot,
    "screen_region": screen_region,
    "highlight_spot": highlight_spot,
    "click_spot": click_spot,
    "show_welcome": show_welcome,
    "start_at_login": start_at_login,
    "chat_box": chat_box,
    "front_app": front_app,
    "front_window": front_window,
    "files_changed_since": files_changed_since,
    "app_menus": app_menus,
    "menu_item_enabled": menu_item_enabled,
    "save_panel_text": save_panel_text,
    "selected_text": selected_text,
    "selection_size": selection_size,
    "replace_selected_text": replace_selected_text,
    "insert_below_selection": insert_below_selection,
    "file_start": file_start,
    "highlight_menu": highlight_menu,
    "press_menu": press_menu,
}
