"""The talk key on Windows: press Alt+Space once anywhere to talk to Dock (like
tapping the face on the phone; ⌥ Space on the Mac; PowerToys Run uses the same
keys). Press it again to send right away.

A low-level keyboard hook sees the keys before the app in front does and
swallows Space, so it doesn't type a space or open the window menu. Letting
go of Alt alone would select the app's menu bar, so Dock "masks" it with an
unused key (the same trick AutoHotkey uses). No permission is needed.

The hook has its own thread and message loop; on_tap runs on a helper
thread, because Windows drops hooks that take too long to answer.
"""

import ctypes
import queue
import threading
from ctypes import wintypes

KEY_NAME = "Alt+Space"

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
VK_SPACE, VK_CONTROL, VK_LWIN, VK_RWIN = 0x20, 0x11, 0x5B, 0x5C
ALT_KEYS = {0x12, 0xA4, 0xA5}
LLKHF_INJECTED, LLKHF_ALTDOWN = 0x10, 0x20
MASK_KEY = 0xE8  # a key code no keyboard has
KEYEVENTF_KEYUP = 0x2

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

_state = {"down": False}  # Space is down as part of the talk key (its repeats and key-up are swallowed too)
_jobs: queue.Queue = queue.Queue()
_proc = None  # kept so it isn't garbage-collected while Windows calls it


def _down(key: int) -> bool:
    return bool(user32.GetAsyncKeyState(key) & 0x8000)


def _mask_alt() -> None:
    user32.keybd_event(MASK_KEY, 0, 0, 0)
    user32.keybd_event(MASK_KEY, 0, KEYEVENTF_KEYUP, 0)


def _hook(code, wparam, lparam):
    if code == 0:
        info = KBDLLHOOKSTRUCT.from_address(lparam)
        if not info.flags & LLKHF_INJECTED:
            down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            if info.vkCode == VK_SPACE:
                if down:
                    if _state["down"]:
                        return 1  # the key repeating while held
                    if info.flags & LLKHF_ALTDOWN and not (_down(VK_CONTROL) or _down(VK_LWIN) or _down(VK_RWIN)):
                        _state["down"] = True
                        _jobs.put("tap")
                        return 1
                elif _state["down"]:
                    _state["down"] = False
                    return 1
    return user32.CallNextHookEx(None, code, wparam, lparam)


def start(on_tap) -> bool:
    """Call on_tap() each time the keys are pressed."""
    ready = threading.Event()
    result = {"ok": False}

    def run_hook():
        global _proc
        _proc = HOOKPROC(_hook)  # (kept in the module, so it isn't garbage-collected)
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _proc, kernel32.GetModuleHandleW(None), 0)
        result["ok"] = bool(hook)
        ready.set()
        if not hook:
            return
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def run_jobs():
        while True:
            _jobs.get()
            try:
                _mask_alt()
                on_tap()
            except Exception as e:
                print(f"Talk key action failed: {e!r}")

    threading.Thread(target=run_hook, daemon=True, name="talk key").start()
    threading.Thread(target=run_jobs, daemon=True, name="talk key jobs").start()
    ready.wait(3)
    return result["ok"]
