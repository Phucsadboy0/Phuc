"""AOTR Farm Assistant - công cụ hỗ trợ farm cho Attack on Titan Revolution.

Nguyên tắc thiết kế:
    * Chỉ tương tác với game giống như người chơi: đọc pixel trên màn hình
      và gửi phím/chuột qua Windows SendInput.
    * KHÔNG inject, KHÔNG đọc/ghi bộ nhớ, KHÔNG sửa client Roblox,
      KHÔNG dùng API nội bộ của AOTR.
"""

__version__ = "1.0.0"
APP_NAME = "AOTR Farm Assistant"
