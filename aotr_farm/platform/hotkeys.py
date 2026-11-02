"""Phím tắt toàn cục (hoạt động cả khi cửa sổ Roblox đang được focus).

Dùng ``RegisterHotKey`` của Windows: không cần quyền Administrator và không
cài keyboard hook (nhẹ hơn thư viện ``keyboard``).
"""

from __future__ import annotations

import ctypes
import logging
import threading
from typing import Callable, Dict

from . import IS_WINDOWS

log = logging.getLogger(__name__)

WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_NOREPEAT = 0x4000


def vk_from_name(name: str) -> int:
    """'F6' -> 0x75, 'P' -> 0x50."""
    name = name.strip().upper()
    if name.startswith("F") and name[1:].isdigit():
        n = int(name[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    if len(name) == 1 and name.isalnum():
        return ord(name)
    raise ValueError(f"Phím tắt không hỗ trợ: {name}")


class HotkeyManager:
    def __init__(self) -> None:
        self._bindings: Dict[int, tuple[int, Callable[[], None]]] = {}
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()

    def start(self, mapping: Dict[str, Callable[[], None]]) -> None:
        if not IS_WINDOWS:
            log.info("Phím tắt toàn cục chỉ hỗ trợ trên Windows.")
            return
        self.stop()
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, args=(mapping,), daemon=True, name="hotkeys")
        self._thread.start()
        self._ready.wait(2.0)

    def _loop(self, mapping: Dict[str, Callable[[], None]]) -> None:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        self._thread_id = kernel32.GetCurrentThreadId()
        hk_id = 1
        for key, cb in mapping.items():
            try:
                vk = vk_from_name(key)
            except ValueError as exc:
                log.warning("%s", exc)
                continue
            if user32.RegisterHotKey(None, hk_id, MOD_NOREPEAT, vk):
                self._bindings[hk_id] = (vk, cb)
                log.info("Đã đăng ký phím tắt %s", key)
            else:
                log.warning("Không đăng ký được %s (đang bị chương trình khác dùng?)", key)
            hk_id += 1
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in self._bindings:
                try:
                    self._bindings[msg.wParam][1]()
                except Exception:
                    log.exception("Lỗi khi xử lý phím tắt")
        for hid in list(self._bindings):
            user32.UnregisterHotKey(None, hid)
        self._bindings.clear()

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._thread_id:
            ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(1.0)
        self._thread = None
