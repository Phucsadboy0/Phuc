"""Đọc số EXP / vàng trên màn hình thưởng bằng Tesseract OCR (tùy chọn).

Nếu không cài Tesseract, chương trình vẫn chạy bình thường và dùng giá trị
``fallback_*_per_run`` trong cấu hình.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Optional

import numpy as np

from .config import OcrConfig
from .platform.window import Rect

log = logging.getLogger(__name__)

try:
    import pytesseract  # type: ignore
except ImportError:
    pytesseract = None

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover
    cv2 = None

_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def parse_number(text: str) -> Optional[int]:
    """Lấy số lớn nhất trong chuỗi OCR.

    Hỗ trợ dạng "+1,250 EXP", "Gold: 3.400", "12.5K", "1.2M".
    """
    if not text:
        return None
    text = text.lower()
    best: Optional[int] = None
    for m in re.finditer(r"(\d[\d,.\s]*)([kmb])?", text):
        raw, suffix = m.group(1).strip(), m.group(2)
        raw = raw.replace(" ", "")
        if suffix:
            # "12.5k" -> 12500 : dấu '.' / ',' là thập phân
            try:
                value = int(float(raw.replace(",", ".")) * _SUFFIX[suffix])
            except ValueError:
                continue
        else:
            # "1,250" hoặc "1.250" -> dấu phân cách hàng nghìn
            digits = re.sub(r"[^\d]", "", raw)
            if not digits:
                continue
            value = int(digits)
        if best is None or value > best:
            best = value
    return best


class RewardReader:
    """Đọc các vùng OCR được cấu hình trong ``OcrConfig.regions``."""

    def __init__(self, cfg: OcrConfig) -> None:
        self.cfg = cfg
        self.available = False
        if cfg.enabled:
            if pytesseract is None:
                log.warning("OCR bật nhưng chưa cài 'pytesseract' -> dùng giá trị mặc định.")
            else:
                if cfg.tesseract_path:
                    pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_path
                try:
                    pytesseract.get_tesseract_version()
                    self.available = True
                except Exception as exc:  # TesseractNotFoundError, OSError...
                    log.warning("Không tìm thấy Tesseract (%s) -> dùng giá trị mặc định.", exc)

    @staticmethod
    def _preprocess(img: np.ndarray) -> np.ndarray:
        """Tăng độ tương phản: xám -> phóng to 2x -> nhị phân Otsu."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Chữ sáng trên nền tối -> đảo màu cho Tesseract (thích chữ đen nền trắng)
        if bw.mean() < 127:
            bw = 255 - bw
        return bw

    def read_text(self, img: np.ndarray) -> str:
        if not self.available:
            return ""
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,.+KMBkmb"
        return pytesseract.image_to_string(self._preprocess(img), config=cfg)

    def read_rewards(self, frame: np.ndarray, window: Rect) -> Dict[str, int]:
        """``frame`` là ảnh chụp toàn bộ client của cửa sổ game."""
        out: Dict[str, int] = {}
        if not self.available:
            if self.cfg.fallback_exp_per_run:
                out["exp"] = self.cfg.fallback_exp_per_run
            if self.cfg.fallback_gold_per_run:
                out["gold"] = self.cfg.fallback_gold_per_run
            return out
        h, w = frame.shape[:2]
        for name, (rx, ry, rw, rh) in self.cfg.regions.items():
            x0, y0 = int(rx * w), int(ry * h)
            x1, y1 = min(w, x0 + max(1, int(rw * w))), min(h, y0 + max(1, int(rh * h)))
            crop = frame[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            try:
                text = self.read_text(crop)
            except Exception as exc:
                log.warning("OCR lỗi ở vùng %s: %s", name, exc)
                continue
            value = parse_number(text)
            log.debug("OCR %s: %r -> %s", name, text, value)
            if value is not None:
                out[name] = value
        return out
