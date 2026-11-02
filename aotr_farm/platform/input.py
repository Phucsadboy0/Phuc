"""Giả lập bàn phím/chuột qua Windows ``SendInput`` (scan code).

Roblox đọc phím theo scan code (DirectInput/raw input) nên các thư viện chỉ gửi
virtual-key (như pyautogui) thường không hoạt động khi xoay camera hoặc di
chuyển. Module này gửi scan code giống bàn phím thật.

Mọi phím đang giữ được ghi nhận để ``release_all()`` nhả hết khi Pause/Stop,
tránh trường hợp nhân vật bị "kẹt" giữ phím W.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import Set

from . import IS_WINDOWS

log = logging.getLogger(__name__)

# Bảng scan code (Set 1). Phím có cờ extended đánh dấu bằng 0xE0xx.
SCAN_CODES = {
    "esc": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B, "-": 0x0C, "=": 0x0D,
    "backspace": 0x0E, "tab": 0x0F, "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13,
    "t": 0x14, "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "[": 0x1A, "]": 0x1B, "enter": 0x1C, "ctrl": 0x1D, "a": 0x1E, "s": 0x1F,
    "d": 0x20, "f": 0x21, "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    ";": 0x27, "'": 0x28, "`": 0x29, "shift": 0x2A, "\\": 0x2B, "z": 0x2C,
    "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30, "n": 0x31, "m": 0x32, ",": 0x33,
    ".": 0x34, "/": 0x35, "rshift": 0x36, "alt": 0x38, "space": 0x39,
    "capslock": 0x3A, "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F,
    "f6": 0x40, "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44, "f11": 0x57,
    "f12": 0x58,
    "up": 0xE048, "down": 0xE050, "left": 0xE04B, "right": 0xE04D,
    "insert": 0xE052, "delete": 0xE053, "home": 0xE047, "end": 0xE04F,
    "pageup": 0xE049, "pagedown": 0xE051, "rctrl": 0xE01D, "ralt": 0xE038,
}

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x8
    MOUSEEVENTF_MOVE = 0x0001
    MOUSE_FLAGS = {
        "left": (0x0002, 0x0004),
        "right": (0x0008, 0x0010),
        "middle": (0x0020, 0x0040),
    }
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    def _send(*inputs: "INPUT") -> None:
        arr = (INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


class InputController:
    """Gửi phím/chuột. Thread-safe; ghi nhớ phím/chuột đang giữ."""

    def __init__(self) -> None:
        self._held_keys: Set[str] = set()
        self._held_buttons: Set[str] = set()
        self._lock = threading.Lock()
        if not IS_WINDOWS:
            log.warning("Không phải Windows - InputController chạy ở chế độ giả lập (không gửi phím).")

    # ------------------------------ Bàn phím --------------------------- #
    @staticmethod
    def _scan(key: str) -> int:
        key = key.lower()
        if key not in SCAN_CODES:
            raise ValueError(f"Phím không hỗ trợ: {key!r}")
        return SCAN_CODES[key]

    def _key_event(self, key: str, up: bool) -> None:
        code = self._scan(key)
        if not IS_WINDOWS:
            return
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
        if code > 0xFF:
            flags |= KEYEVENTF_EXTENDEDKEY
            code &= 0xFF
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(0, code, flags, 0, 0)
        _send(inp)

    def key_down(self, key: str) -> None:
        with self._lock:
            self._key_event(key, up=False)
            self._held_keys.add(key.lower())

    def key_up(self, key: str) -> None:
        with self._lock:
            self._key_event(key, up=True)
            self._held_keys.discard(key.lower())

    def press(self, key: str, duration: float = 0.05) -> None:
        self.key_down(key)
        time.sleep(duration)
        self.key_up(key)

    # ------------------------------ Chuột ------------------------------ #
    def move_to(self, x: int, y: int) -> None:
        if IS_WINDOWS:
            user32.SetCursorPos(int(x), int(y))

    def move_rel(self, dx: int, dy: int) -> None:
        """Di chuyển tương đối - dùng để xoay camera trong Roblox."""
        if not IS_WINDOWS:
            return
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, 0)
        _send(inp)

    def mouse_down(self, button: str = "left") -> None:
        with self._lock:
            if IS_WINDOWS:
                inp = INPUT(type=INPUT_MOUSE)
                inp.mi = MOUSEINPUT(0, 0, 0, MOUSE_FLAGS[button][0], 0, 0)
                _send(inp)
            self._held_buttons.add(button)

    def mouse_up(self, button: str = "left") -> None:
        with self._lock:
            if IS_WINDOWS:
                inp = INPUT(type=INPUT_MOUSE)
                inp.mi = MOUSEINPUT(0, 0, 0, MOUSE_FLAGS[button][1], 0, 0)
                _send(inp)
            self._held_buttons.discard(button)

    def click(self, x: int | None = None, y: int | None = None,
              button: str = "left", hold: float = 0.05) -> None:
        if x is not None and y is not None:
            self.move_to(x, y)
            # Roblox cần một chuyển động nhỏ để "nhận" vị trí chuột mới
            self.move_rel(1, 0)
            self.move_rel(-1, 0)
            time.sleep(0.03)
        self.mouse_down(button)
        time.sleep(hold)
        self.mouse_up(button)

    def scroll(self, amount: int) -> None:
        if not IS_WINDOWS:
            return
        MOUSEEVENTF_WHEEL = 0x0800
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(0, 0, ctypes.c_ulong(int(amount) * 120).value, MOUSEEVENTF_WHEEL, 0, 0)
        _send(inp)

    # ------------------------------ An toàn ---------------------------- #
    def release_all(self) -> None:
        """Nhả mọi phím/chuột đang giữ. Gọi khi Pause, Stop hoặc gặp lỗi."""
        for key in list(self._held_keys):
            try:
                self.key_up(key)
            except Exception:  # pragma: no cover - chỉ phòng hờ
                pass
        for btn in list(self._held_buttons):
            try:
                self.mouse_up(btn)
            except Exception:  # pragma: no cover
                pass

    @property
    def held(self) -> Set[str]:
        return set(self._held_keys) | {f"mouse:{b}" for b in self._held_buttons}
