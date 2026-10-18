"""UI Automation: Windows' way for helper apps (screen readers, and Dock) to
see the buttons, menus and text inside other apps, the same idea as the Mac's
Accessibility API. Through the `uiautomation` package.

UI Automation is COM, so each thread starts it once (ready()), and a control
found on one thread is only used on that thread.
"""

import threading
import time

import uiautomation as auto

auto.SetGlobalSearchTimeout(1)

# Tree scopes and properties of IUIAutomation (uiautomation has no names for scopes).
CHILDREN, DESCENDANTS = 2, 4
NAME, CONTROL_TYPE, RECT, ENABLED, OFFSCREEN, ACCELERATOR, AUTOMATION_ID, PASSWORD = (
    30005, 30003, 30001, 30010, 30022, 30006, 30011, 30019)

_local = threading.local()


def ready() -> None:
    if getattr(_local, "started", None) is None:
        _local.started = auto.UIAutomationInitializerInThread()


def window(hwnd: int):
    ready()
    return auto.ControlFromHandle(hwnd) if hwnd else None


def focused():
    ready()
    return auto.GetFocusedControl()


def rect(control) -> tuple[int, int, int, int] | None:
    try:
        r = control.BoundingRectangle
    except Exception:
        return None
    return (r.left, r.top, r.width(), r.height()) if r.width() > 0 and r.height() > 0 else None


def pattern(control, name: str):
    """A control pattern by name ("InvokePattern", "TextPattern"…), or None."""
    try:
        return control.GetPattern(getattr(auto.PatternId, name))
    except Exception:
        return None


def name_of(control) -> str:
    try:
        return " ".join(str(control.Name or "").split())
    except Exception:
        return ""


def press(control) -> bool:
    """Do what clicking the control would: invoke, toggle, select or expand it."""
    for name, act in (("InvokePattern", lambda p: p.Invoke(waitTime=0)),
                      ("TogglePattern", lambda p: p.Toggle(waitTime=0)),
                      ("SelectionItemPattern", lambda p: p.Select(waitTime=0)),
                      ("ExpandCollapsePattern", lambda p: p.Expand(waitTime=0)),
                      ("LegacyIAccessiblePattern", lambda p: p.DoDefaultAction(waitTime=0))):
        found = pattern(control, name)
        if found is not None:
            try:
                act(found)
                return True
            except Exception:
                continue
    return False


class Found:
    """One element from a quick search, with its properties read in the same call."""

    def __init__(self, element):
        self.element = element
        self.name = " ".join(str(element.CachedName or "").split())
        self.type = element.CachedControlType
        box = element.CachedBoundingRectangle
        self.rect = (box.left, box.top, box.right - box.left, box.bottom - box.top) if box.right > box.left and box.bottom > box.top else None
        self.enabled = bool(element.CachedIsEnabled)
        self.offscreen = bool(element.CachedIsOffscreen)
        self.accelerator = str(element.CachedAcceleratorKey or "")
        self.automation_id = str(element.CachedAutomationId or "")
        self.password = bool(element.CachedIsPassword)

    def control(self):
        return auto.Control.CreateControlFromElement(self.element)


def find_all(control, scope: int = DESCENDANTS, max_seconds: float = 3.0) -> list[Found]:
    """Every element under `control`, with their names, types and places read in
    one go (asking one property at a time takes about a millisecond each, and
    big windows have thousands of parts)."""
    ready()
    automation = auto._AutomationClient.instance().IUIAutomation
    cache = automation.CreateCacheRequest()
    for prop in (NAME, CONTROL_TYPE, RECT, ENABLED, OFFSCREEN, ACCELERATOR, AUTOMATION_ID, PASSWORD):
        cache.AddProperty(prop)
    started = time.time()
    try:
        elements = control.Element.FindAllBuildCache(scope, automation.ControlViewCondition, cache)
    except Exception as e:
        print(f"Couldn't list the window's parts: {e!r}")
        return []
    found = []
    for n in range(elements.Length if elements else 0):
        if time.time() - started > max_seconds:
            break
        try:
            found.append(Found(elements.GetElement(n)))
        except Exception:
            continue
    return found
