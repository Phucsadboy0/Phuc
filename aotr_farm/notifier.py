"""Thông báo lỗi / sự kiện: âm thanh, thông báo Windows, Discord webhook.

Tất cả đều chạy ở luồng nền và nuốt lỗi -> việc gửi thông báo thất bại không
bao giờ làm dừng quá trình farm.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import urllib.request
from typing import Callable, List, Optional

from .config import NotifyConfig

log = logging.getLogger(__name__)

INFO, WARNING, ERROR = "info", "warning", "error"


class Notifier:
    # Chống spam: cùng một nội dung chỉ gửi lại sau N giây
    DEDUP_SECONDS = 60.0

    def __init__(self, cfg: NotifyConfig, app_name: str = "AOTR Farm") -> None:
        self.cfg = cfg
        self.app_name = app_name
        self._last_sent: dict[str, float] = {}
        # GUI đăng ký để hiện thông báo trong cửa sổ
        self.listeners: List[Callable[[str, str, str], None]] = []

    def notify(self, level: str, title: str, message: str) -> None:
        key = f"{level}|{title}|{message}"
        now = time.monotonic()
        if now - self._last_sent.get(key, -1e9) < self.DEDUP_SECONDS:
            return
        self._last_sent[key] = now

        log_fn = {ERROR: log.error, WARNING: log.warning}.get(level, log.info)
        log_fn("%s: %s", title, message)
        for cb in list(self.listeners):
            try:
                cb(level, title, message)
            except Exception:
                pass
        threading.Thread(target=self._dispatch, args=(level, title, message),
                         daemon=True, name="notify").start()

    # ------------------------------------------------------------------ #
    def _dispatch(self, level: str, title: str, message: str) -> None:
        if self.cfg.sound:
            self._beep(level)
        if self.cfg.desktop_toast and level != INFO:
            self._toast(title, message)
        if self.cfg.discord_webhook:
            self._discord(level, title, message)

    @staticmethod
    def _beep(level: str) -> None:
        if sys.platform != "win32":
            return
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONHAND if level == ERROR else winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def _toast(self, title: str, message: str) -> None:
        """Thông báo góc màn hình. Dùng 'plyer' nếu có (tùy chọn)."""
        try:
            from plyer import notification  # type: ignore
            notification.notify(title=f"{self.app_name} - {title}", message=message[:250],
                                app_name=self.app_name, timeout=8)
        except Exception:
            pass  # Không có plyer -> chỉ dùng âm thanh + thông báo trong GUI

    def _discord(self, level: str, title: str, message: str) -> None:
        color = {ERROR: 0xE74C3C, WARNING: 0xF1C40F}.get(level, 0x2ECC71)
        payload = {"embeds": [{"title": f"{self.app_name}: {title}",
                               "description": message[:1800], "color": color}]}
        req = urllib.request.Request(
            self.cfg.discord_webhook, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "AOTR-Farm-Assistant"},
        )
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as exc:
            log.debug("Gửi Discord thất bại: %s", exc)


def send_test(notifier: Notifier, extra: Optional[str] = None) -> None:
    notifier._last_sent.clear()
    notifier.notify(WARNING, "Thử thông báo", extra or "Nếu bạn thấy thông báo này, cấu hình đã đúng.")
