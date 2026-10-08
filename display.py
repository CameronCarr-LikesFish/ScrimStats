"""
Sharp on every monitor.

Windows can scale each monitor differently (for example 100% on one, 150% on
another). By default the window library declares one scale for the whole
program, so on a monitor with a different scale Windows stretches the
window's picture, which is what makes it blurry.

per_monitor_dpi() tells Windows the app handles each monitor's scale
itself, so pages are drawn at the monitor's real resolution. Windows then
leaves the window's size in pixels alone when it moves to another monitor,
so follow_monitor_scale() resizes it to match: the same size on every
screen, kept inside that screen.
"""

import ctypes
import threading
import time
from ctypes import wintypes

PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
SWP_NOZORDER, SWP_NOACTIVATE = 0x0004, 0x0010
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def per_monitor_dpi():
    """Call before the window library starts (it only sets the
    whole-program kind, which Windows then ignores)."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)
    except Exception:
        pass                      # older Windows: stays as it was


def _work_area(user32, hwnd):
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
    return info.rcWork


def follow_monitor_scale(hwnd, poll_s=0.3):
    """Keep the window the same size on screen when it moves between monitors
    with different scaling. Runs in the background until the window closes."""
    user32 = ctypes.windll.user32
    user32.GetDpiForWindow.restype = ctypes.c_uint
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]

    def watch():
        last = user32.GetDpiForWindow(hwnd)
        # The size people want, in 100%-scale pixels. A screen too small for it
        # only shrinks the window while it's there; back on a bigger screen it
        # returns to this size. Resizing by hand changes it.
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        wanted = [(rect.right - rect.left) * 96 / last, (rect.bottom - rect.top) * 96 / last]
        placed = (rect.right - rect.left, rect.bottom - rect.top)
        while user32.IsWindow(hwnd):
            time.sleep(poll_s)
            dpi = user32.GetDpiForWindow(hwnd)
            if not dpi or not last:
                continue
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            size = (rect.right - rect.left, rect.bottom - rect.top)
            if user32.IsZoomed(hwnd) or user32.IsIconic(hwnd):
                last = dpi                       # maximised / minimised: Windows sizes it
                continue
            if dpi == last:
                if abs(size[0] - placed[0]) > 2 or abs(size[1] - placed[1]) > 2:
                    wanted = [size[0] * 96 / dpi, size[1] * 96 / dpi]     # resized by hand
                    placed = size
                continue
            work = _work_area(user32, hwnd)
            # Never bigger than the screen it's on, and fully on it.
            width = min(round(wanted[0] * dpi / 96), work.right - work.left - 20)
            height = min(round(wanted[1] * dpi / 96), work.bottom - work.top - 20)
            x = max(work.left, min(rect.left, work.right - width))
            y = max(work.top, min(rect.top, work.bottom - height))
            user32.SetWindowPos(hwnd, None, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE)
            placed, last = (width, height), dpi
    threading.Thread(target=watch, daemon=True, name="monitor-scale").start()


def fit_on_screen(hwnd):
    """If the window is bigger than its screen (a small or highly scaled
    monitor), shrink it to fit."""
    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    work = _work_area(user32, hwnd)
    width = min(rect.right - rect.left, work.right - work.left - 20)
    height = min(rect.bottom - rect.top, work.bottom - work.top - 20)
    if (width, height) != (rect.right - rect.left, rect.bottom - rect.top):
        x = work.left + (work.right - work.left - width) // 2
        y = work.top + (work.bottom - work.top - height) // 2
        user32.SetWindowPos(hwnd, None, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE)
