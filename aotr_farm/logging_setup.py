"""Cấu hình logging: ghi file xoay vòng + đẩy log sang GUI qua hàng đợi.

* File log: ``logs/farm.log`` (tối đa 2 MB x 5 file -> không phình ổ đĩa).
* GUI đọc log từ ``log_queue`` theo chu kỳ, không khóa luồng farm.
"""

from __future__ import annotations

import logging
import queue
import sys
from logging.handlers import QueueHandler, RotatingFileHandler
from pathlib import Path

from .config import LOG_DIR

# Hàng đợi giới hạn kích thước: nếu GUI bị treo, log cũ bị bỏ thay vì tốn RAM
log_queue: "queue.Queue[logging.LogRecord]" = queue.Queue(maxsize=2000)

LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"


class DroppingQueueHandler(QueueHandler):
    """QueueHandler không bao giờ chặn: hàng đợi đầy thì bỏ bản ghi cũ nhất."""

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(record)
            except (queue.Empty, queue.Full):
                pass


def setup_logging(level: str = "INFO", log_dir: Path = LOG_DIR) -> None:
    """Khởi tạo logger gốc. Gọi một lần khi chương trình khởi động."""
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Xóa handler cũ (tránh log trùng nếu gọi lại)
    for h in list(root.handlers):
        root.removeHandler(h)

    file_handler = RotatingFileHandler(
        log_dir / "farm.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, "%Y-%m-%d %H:%M:%S"))
    root.addHandler(file_handler)

    gui_handler = DroppingQueueHandler(log_queue)
    root.addHandler(gui_handler)

    # Bản .exe không có cửa sổ console (sys.stderr = None) -> bỏ qua
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        root.addHandler(console)


def set_level(level: str) -> None:
    logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))
