"""Hộp thoại chọn vùng: hiển thị ảnh chụp cửa sổ game, người dùng kéo chuột
để khoanh vùng. Trả về tọa độ tương đối (0..1) so với ảnh gốc.

Dùng cho:
    * Chụp template (nút Play, Retry, màn hình thưởng...).
    * Chọn vùng OCR đọc EXP / vàng.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageTk


class RegionPicker(tk.Toplevel):
    def __init__(self, master: tk.Misc, frame_bgr: np.ndarray, title: str = "Chọn vùng") -> None:
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.result: Optional[Tuple[float, float, float, float]] = None

        h, w = frame_bgr.shape[:2]
        # Thu nhỏ ảnh để vừa màn hình (tối đa 90%)
        max_w = int(self.winfo_screenwidth() * 0.9)
        max_h = int(self.winfo_screenheight() * 0.8)
        self.scale = min(1.0, max_w / w, max_h / h)
        disp = Image.fromarray(frame_bgr[:, :, ::-1])  # BGR -> RGB
        if self.scale < 1.0:
            disp = disp.resize((int(w * self.scale), int(h * self.scale)), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(disp)
        self.img_w, self.img_h = disp.size

        ttk.Label(self, text="Kéo chuột để khoanh vùng, rồi bấm 'Xác nhận' (Enter). Esc để hủy.").pack(
            anchor="w", padx=8, pady=4)
        self.canvas = tk.Canvas(self, width=self.img_w, height=self.img_h, cursor="cross",
                                highlightthickness=0)
        self.canvas.pack(padx=8)
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        self._rect_id: Optional[int] = None
        self._start: Optional[Tuple[int, int]] = None
        self._sel: Optional[Tuple[int, int, int, int]] = None

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=6)
        self.info = ttk.Label(bar, text="Chưa chọn vùng")
        self.info.pack(side="left")
        ttk.Button(bar, text="Hủy", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Xác nhận", command=self._confirm).pack(side="right", padx=6)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag)
        self.bind("<Return>", lambda _e: self._confirm())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.focus_force()

    def _clamp(self, x: int, y: int) -> Tuple[int, int]:
        return max(0, min(self.img_w, x)), max(0, min(self.img_h, y))

    def _on_press(self, e) -> None:
        self._start = self._clamp(e.x, e.y)
        if self._rect_id:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(*self._start, *self._start,
                                                     outline="#00ff66", width=2)

    def _on_drag(self, e) -> None:
        if not self._start or not self._rect_id:
            return
        x, y = self._clamp(e.x, e.y)
        x0, y0 = self._start
        self.canvas.coords(self._rect_id, x0, y0, x, y)
        self._sel = (min(x0, x), min(y0, y), abs(x - x0), abs(y - y0))
        sw, sh = int(self._sel[2] / self.scale), int(self._sel[3] / self.scale)
        self.info.config(text=f"Vùng chọn: {sw} x {sh} px")

    def _confirm(self) -> None:
        if not self._sel or self._sel[2] < 4 or self._sel[3] < 4:
            self.info.config(text="Vùng quá nhỏ - hãy kéo lại")
            return
        x, y, w, h = self._sel
        self.result = (x / self.img_w, y / self.img_h, w / self.img_w, h / self.img_h)
        self.destroy()


def pick_region(master: tk.Misc, frame_bgr: np.ndarray, title: str = "Chọn vùng"):
    """Mở hộp thoại và chờ tới khi người dùng đóng. Trả về (rx, ry, rw, rh) hoặc None."""
    dlg = RegionPicker(master, frame_bgr, title)
    master.wait_window(dlg)
    return dlg.result


def crop_relative(frame: np.ndarray, region) -> np.ndarray:
    h, w = frame.shape[:2]
    rx, ry, rw, rh = region
    x0, y0 = int(rx * w), int(ry * h)
    return frame[y0:y0 + max(1, int(rh * h)), x0:x0 + max(1, int(rw * w))].copy()
