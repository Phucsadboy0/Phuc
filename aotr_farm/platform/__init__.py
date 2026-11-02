"""Lớp nền tảng: cửa sổ và thiết bị nhập (Windows).

Các module ở đây chỉ dùng API công khai của Windows (user32) thông qua
``ctypes`` -> không cần pywin32 và không chạm vào tiến trình Roblox.
"""

import sys

IS_WINDOWS = sys.platform == "win32"
