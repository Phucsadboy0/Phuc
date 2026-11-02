"""Điểm khởi chạy.

    python -m aotr_farm            # mở giao diện
    python -m aotr_farm --check    # kiểm tra thư viện, Tesseract, cửa sổ Roblox
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys

from . import APP_NAME, __version__
from .config import ensure_dirs, load_config
from .logging_setup import setup_logging

log = logging.getLogger("aotr_farm")


def check_environment() -> int:
    """In báo cáo môi trường; trả về số vấn đề bắt buộc phải sửa."""
    problems = 0
    print(f"{APP_NAME} v{__version__} - kiểm tra môi trường\n")
    print(f"Python      : {sys.version.split()[0]}  ({'OK' if sys.version_info >= (3, 9) else 'CẦN >= 3.9'})")
    print(f"Hệ điều hành: {sys.platform}  ({'OK' if sys.platform == 'win32' else 'Chỉ hỗ trợ đầy đủ trên Windows'})")
    for mod, required in (("numpy", True), ("cv2", True), ("mss", True), ("PIL", True),
                          ("psutil", False), ("pytesseract", False), ("plyer", False)):
        try:
            importlib.import_module(mod)
            print(f"  [OK]   {mod}")
        except ImportError:
            print(f"  [{'THIẾU' if required else 'tùy chọn'}] {mod}")
            problems += int(required)

    cfg = load_config()
    from .ocr import RewardReader
    if cfg.ocr.enabled:
        print(f"Tesseract   : {'OK' if RewardReader(cfg.ocr).available else 'KHÔNG tìm thấy'}")

    from .platform.window import GameWindow
    win = GameWindow(cfg.window_title)
    rect = win.client_rect()
    print(f"Cửa sổ game : {f'{rect.width}x{rect.height}' if rect else 'chưa mở / không tìm thấy'}")
    print("\nKết quả:", "SẴN SÀNG" if problems == 0 else f"{problems} vấn đề cần sửa (pip install -r requirements.txt)")
    return problems


def _utf8_console() -> None:
    """Console Windows thường dùng cp1252/cp437 -> in tiếng Việt sẽ lỗi.
    Chuyển sang UTF-8; ký tự không hiển thị được thì thay bằng '?' thay vì crash."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main(argv=None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(prog="aotr_farm", description=APP_NAME)
    parser.add_argument("--check", action="store_true", help="kiểm tra môi trường rồi thoát")
    args = parser.parse_args(argv)

    ensure_dirs()
    if args.check:
        return 1 if check_environment() else 0

    cfg = load_config()
    setup_logging(cfg.log_level)

    from .gui.app import FarmApp
    from .services import build_services

    try:
        app = FarmApp(build_services(cfg))
    except Exception:
        log.exception("Không khởi tạo được giao diện")
        return 1
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
