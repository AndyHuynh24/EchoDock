"""On-screen pointer on Windows: a topmost, click-through, color-keyed window drawn
with Pillow. Hidden on user input or after SHOW_SECONDS. Thread-safe.
"""

import ctypes
import math
import queue
import threading
import time

import win32api
import win32con
import win32gui
from PIL import Image, ImageDraw, ImageFont, ImageWin

from dock_agent.win import winapi

SHOW_SECONDS = 6
IGNORE_FIRST_SECONDS = 0.5
MOVE_PIXELS = 25
MARGIN = 360
KEY = (255, 0, 255)  # transparent color key
ORANGE, WHITE = (255, 149, 0), (255, 255, 255)
WM_WORK = win32con.WM_APP + 1
TIMER_WATCH, TIMER_END = 1, 2

_jobs: queue.Queue = queue.Queue()
_hwnd = 0
_image = None
_shown = {"at": 0.0, "cursor": (0, 0), "on_hide": None, "count": 0}
_started = threading.Event()
user32 = ctypes.windll.user32
user32.SetTimer.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_void_p]
user32.KillTimer.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
user32.InvalidateRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]


def start() -> None:
    threading.Thread(target=_run, daemon=True, name="pointer").start()
    _started.wait(5)


def show(rect: tuple[float, float, float, float], label: str, on_hide=None) -> None:
    """Point at `rect` (x, y, width, height in screen pixels)."""
    _jobs.put(("show", rect, label, on_hide))
    if _hwnd:
        win32gui.PostMessage(_hwnd, WM_WORK, 0, 0)


def hide() -> None:
    _jobs.put(("hide",))
    if _hwnd:
        win32gui.PostMessage(_hwnd, WM_WORK, 0, 0)


def _font(size: int):
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _thick_line(draw, start, end, color, width) -> None:
    draw.line([start, end], fill=color, width=width)
    for x, y in (start, end):
        draw.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=color)


def _draw(rect, label) -> tuple[Image.Image, tuple[int, int]]:
    """The image and its top-left position on screen."""
    scale = winapi.scale()
    x, y, w, h = rect
    font = _font(round(20 * scale))
    label_width = font.getbbox(label)[2] if label else 0
    room = max(round(MARGIN * scale), round(200 * scale + label_width + 60 * scale))
    screen = winapi.screen_of((x + w / 2, y + h / 2))["full"]
    flipped = x + w + room > screen[0] + screen[2]
    left = x - room if flipped else x - round(40 * scale)
    top = y - round(40 * scale)
    width, height = w + room + round(40 * scale), h + round(260 * scale)
    image = Image.new("RGB", (int(width), int(height)), KEY)
    draw = ImageDraw.Draw(image)
    tx, ty = x - left, y - top

    pad = round(4 * scale)
    draw.rounded_rectangle([tx - pad, ty - pad, tx + w + pad, ty + h + pad], radius=round(6 * scale),
                           outline=ORANGE, width=round(4 * scale))
    side = -1 if flipped else 1
    if y - screen[1] < 40 * scale:
        head = (tx + w / 2, ty + h + 8 * scale)
        tail = (head[0] + side * 90 * scale, head[1] + 130 * scale)
    else:
        head = (tx + w + 10 * scale, ty + h / 2) if side == 1 else (tx - 10 * scale, ty + h / 2)
        tail = (head[0] + side * 150 * scale, head[1] + 70 * scale)
    angle = math.atan2(head[1] - tail[1], head[0] - tail[0])
    for color, line in ((WHITE, round(11 * scale)), (ORANGE, round(6 * scale))):
        _thick_line(draw, tail, head, color, line)
        for wing_side in (-1, 1):
            wing = angle + math.pi - wing_side * 0.5
            _thick_line(draw, head, (head[0] + 22 * scale * math.cos(wing), head[1] + 22 * scale * math.sin(wing)), color, line)

    if label:
        box = font.getbbox(label)
        text_w, text_h = box[2] - box[0], box[3] - box[1]
        start = tail[0] - 12 * scale if side == 1 else tail[0] - text_w - 12 * scale
        draw.rounded_rectangle([start, tail[1], start + text_w + 24 * scale, tail[1] + text_h + 18 * scale],
                               radius=round(10 * scale), fill=ORANGE)
        draw.text((start + 12 * scale, tail[1] + 9 * scale - box[1]), label, font=font, fill=WHITE)
    return image, (int(left), int(top))


def _do_show(rect, label, on_hide) -> None:
    global _image
    _do_hide()
    image, (left, top) = _draw(rect, label)
    _image = image
    _shown.update(at=time.time(), cursor=win32api.GetCursorPos(), on_hide=on_hide, count=_shown["count"] + 1)
    win32gui.SetWindowPos(_hwnd, win32con.HWND_TOPMOST, left, top, image.width, image.height,
                          win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)
    user32.InvalidateRect(_hwnd, None, True)
    user32.SetTimer(_hwnd, TIMER_WATCH, 50, None)
    user32.SetTimer(_hwnd, TIMER_END, SHOW_SECONDS * 1000, None)


def _do_hide() -> None:
    global _image
    user32.KillTimer(_hwnd, TIMER_WATCH)
    win32gui.ShowWindow(_hwnd, win32con.SW_HIDE)
    _image = None


def _watch_user() -> None:
    """Hide on click, key press or mouse move."""
    if _image is None or time.time() - _shown["at"] < IGNORE_FIRST_SECONDS:
        return
    x, y = win32api.GetCursorPos()
    moved = math.hypot(x - _shown["cursor"][0], y - _shown["cursor"][1]) > MOVE_PIXELS * winapi.scale()
    if moved or winapi.any_key_down():
        _do_hide()


def _wndproc(hwnd, message, wparam, lparam):
    if message == WM_WORK:
        while not _jobs.empty():
            job = _jobs.get_nowait()
            try:
                if job[0] == "show":
                    _do_show(*job[1:])
                else:
                    _do_hide()
            except Exception as e:
                print(f"Pointer failed: {e!r}")
        return 0
    if message == win32con.WM_TIMER:
        if wparam == TIMER_WATCH:
            _watch_user()
        elif wparam == TIMER_END:
            user32.KillTimer(hwnd, TIMER_END)
            on_hide = _shown["on_hide"]
            _do_hide()
            if on_hide:
                threading.Thread(target=on_hide, daemon=True).start()
        return 0
    if message == win32con.WM_PAINT:
        hdc, paint = win32gui.BeginPaint(hwnd)
        if _image is not None:
            ImageWin.Dib(_image).expose(hdc)
        win32gui.EndPaint(hwnd, paint)
        return 0
    return win32gui.DefWindowProc(hwnd, message, wparam, lparam)


def _run() -> None:
    global _hwnd
    window_class = win32gui.WNDCLASS()
    window_class.lpfnWndProc = _wndproc
    window_class.lpszClassName = "OneDockPointer"
    window_class.hInstance = win32api.GetModuleHandle(None)
    window_class.hbrBackground = win32gui.CreateSolidBrush(win32api.RGB(*KEY))
    win32gui.RegisterClass(window_class)
    style = (win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST
             | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE)
    _hwnd = win32gui.CreateWindowEx(style, "OneDockPointer", "Dock pointer", win32con.WS_POPUP,
                                    0, 0, 1, 1, 0, 0, window_class.hInstance, None)
    win32gui.SetLayeredWindowAttributes(_hwnd, win32api.RGB(*KEY), 0, win32con.LWA_COLORKEY)
    _started.set()
    win32gui.PumpMessages()
