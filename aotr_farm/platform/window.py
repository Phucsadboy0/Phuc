"""Tìm và quản lý cửa sổ Roblox bằng user32 (FindWindow, GetClientRect...).

Chỉ đọc vị trí/kích thước cửa sổ và đưa nó lên foreground. Không đọc bộ nhớ
hay can thiệp vào tiến trình game.
"""

from __future__ import annotations

import ctypes
import logging
import time
from dataclasses import dataclass
from typing import Optional

from . import IS_WINDOWS

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rect:
    """Vùng client của cửa sổ, tọa độ màn hình (pixel)."""

    left: int
    top: int
    width: int
    height: int

    def to_abs(self, rx: float, ry: float) -> tuple[int, int]:
        """Đổi tọa độ tương đối (0..1) trong cửa sổ -> tọa độ màn hình."""
        return int(self.left + rx * self.width), int(self.top + ry * self.height)

    def sub(self, rx: float, ry: float, rw: float, rh: float) -> "Rect":
        """Lấy vùng con theo tọa độ tương đối."""
        return Rect(
            int(self.left + rx * self.width),
            int(self.top + ry * self.height),
            max(1, int(rw * self.width)),
            max(1, int(rh * self.height)),
        )


if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    # Bật DPI awareness để tọa độ chụp màn hình khớp tọa độ chuột
    # (nếu không, màn hình scale 125%/150% sẽ bị lệch).
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except (OSError, AttributeError):
        try:
            user32.SetProcessDPIAware()
        except AttributeError:
            pass

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class GameWindow:
    """Bao gói cửa sổ game. Tự tìm lại cửa sổ nếu Roblox bị đóng/mở lại."""

    def __init__(self, title: str = "Roblox") -> None:
        self.title = title
        self.hwnd: Optional[int] = None

    # ------------------------------------------------------------------ #
    def find(self) -> bool:
        """Tìm cửa sổ có tiêu đề đúng bằng ``title`` (hoặc chứa ``title``)."""
        if not IS_WINDOWS:
            return False
        hwnd = user32.FindWindowW(None, self.title)
        if not hwnd:
            hwnd = self._find_partial()
        self.hwnd = hwnd or None
        return self.hwnd is not None

    def _find_partial(self) -> int:
        found = []
        needle = self.title.lower()

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if needle in buf.value.lower():
                    found.append(hwnd)
                    return False  # dừng duyệt
            return True

        user32.EnumWindows(EnumWindowsProc(callback), 0)
        return found[0] if found else 0

    def is_valid(self) -> bool:
        return bool(IS_WINDOWS and self.hwnd and user32.IsWindow(self.hwnd))

    def ensure(self) -> bool:
        """Đảm bảo đang giữ handle hợp lệ (tìm lại nếu cần)."""
        return self.is_valid() or self.find()

    def is_minimized(self) -> bool:
        return bool(self.is_valid() and user32.IsIconic(self.hwnd))

    def is_foreground(self) -> bool:
        return bool(self.is_valid() and user32.GetForegroundWindow() == self.hwnd)

    def focus(self) -> bool:
        """Đưa cửa sổ lên trước để phím/chuột đi vào đúng game."""
        if not self.ensure():
            return False
        if self.is_foreground():
            return True
        SW_RESTORE = 9
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_RESTORE)
        # Mẹo phổ biến: nhấn/nhả ALT để Windows cho phép SetForegroundWindow
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(self.hwnd)
        time.sleep(0.15)
        return self.is_foreground()

    def client_rect(self) -> Optional[Rect]:
        """Vùng client (không gồm viền/tiêu đề) theo tọa độ màn hình."""
        if not self.ensure():
            return None
        rect = wintypes.RECT()
        if not user32.GetClientRect(self.hwnd, ctypes.byref(rect)):
            return None
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        return Rect(pt.x, pt.y, w, h)
