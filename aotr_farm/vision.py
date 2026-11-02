"""Nhận diện hình ảnh trên màn hình (chỉ đọc pixel, không đọc bộ nhớ game).

Tối ưu CPU/RAM:
    * Chỉ chụp vùng client của cửa sổ Roblox (hoặc một vùng con), không chụp
      toàn màn hình.
    * So khớp trên ảnh xám (1 kênh thay vì 3) khi ``grayscale=True``.
    * Template được đọc một lần, scale theo độ rộng cửa sổ hiện tại rồi cache.
    * Mỗi luồng giữ một đối tượng ``mss`` riêng (mss không thread-safe) và tái
      sử dụng, tránh tạo/hủy liên tục.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from .config import TEMPLATE_DIR
from .platform.window import Rect

log = logging.getLogger(__name__)

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - báo lỗi rõ ràng khi chạy thật
    cv2 = None

try:
    import mss  # type: ignore
except ImportError:  # pragma: no cover
    mss = None


@dataclass
class Match:
    name: str
    score: float
    x: int          # tâm vùng khớp, tọa độ màn hình
    y: int
    w: int
    h: int


class ScreenCapture:
    """Chụp một vùng màn hình -> mảng numpy BGR (uint8)."""

    def __init__(self) -> None:
        self._local = threading.local()

    def _sct(self):
        if mss is None:
            raise RuntimeError("Thiếu thư viện 'mss'. Chạy: pip install -r requirements.txt")
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = mss.mss()
            self._local.sct = sct
        return sct

    def grab(self, rect: Rect) -> np.ndarray:
        shot = self._sct().grab(
            {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}
        )
        # BGRA -> BGR (bỏ kênh alpha, ascontiguousarray để OpenCV xử lý nhanh)
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])

    def close(self) -> None:
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            sct.close()
            self._local.sct = None


class TemplateMatcher:
    """Tìm template PNG trong ảnh chụp."""

    def __init__(self, template_dir: Path = TEMPLATE_DIR, threshold: float = 0.82,
                 reference_width: int = 1280, grayscale: bool = True) -> None:
        self.template_dir = template_dir
        self.threshold = threshold
        self.reference_width = reference_width
        self.grayscale = grayscale
        self._raw: Dict[str, Optional[np.ndarray]] = {}
        self._scaled: Dict[Tuple[str, int], np.ndarray] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def path_of(self, name: str) -> Path:
        p = Path(name)
        if p.suffix.lower() != ".png":
            p = p.with_suffix(".png")
        return p if p.is_absolute() else self.template_dir / p

    def exists(self, name: str) -> bool:
        return self.path_of(name).exists()

    def clear_cache(self) -> None:
        """Gọi sau khi chụp lại template mới."""
        with self._lock:
            self._raw.clear()
            self._scaled.clear()

    def _load(self, name: str) -> Optional[np.ndarray]:
        if name in self._raw:
            return self._raw[name]
        path = self.path_of(name)
        img = None
        if path.exists() and cv2 is not None:
            # imdecode thay cho imread để hỗ trợ đường dẫn có dấu tiếng Việt
            data = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is not None and self.grayscale:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if img is None:
            log.debug("Không có template: %s", path)
        self._raw[name] = img
        return img

    def _get(self, name: str, window_width: int) -> Optional[np.ndarray]:
        key = (name, window_width)
        with self._lock:
            if key in self._scaled:
                return self._scaled[key]
            raw = self._load(name)
            if raw is None:
                return None
            scale = window_width / float(self.reference_width or window_width)
            if abs(scale - 1.0) > 0.02:
                h, w = raw.shape[:2]
                size = (max(4, int(w * scale)), max(4, int(h * scale)))
                tpl = cv2.resize(raw, size, interpolation=cv2.INTER_AREA)
            else:
                tpl = raw
            self._scaled[key] = tpl
            return tpl

    # ------------------------------------------------------------------ #
    def prepare(self, frame: np.ndarray) -> np.ndarray:
        """Đổi khung hình sang dạng dùng để so khớp (xám nếu bật)."""
        if self.grayscale and frame.ndim == 3:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return frame

    def find(self, prepared: np.ndarray, name: str, origin: Rect,
             window_width: Optional[int] = None,
             threshold: Optional[float] = None) -> Optional[Match]:
        """Tìm ``name`` trong ``prepared`` (đã qua ``prepare``).

        ``origin`` là vùng màn hình tương ứng với ảnh, dùng để quy đổi về
        tọa độ màn hình (cho thao tác click).
        """
        if cv2 is None:
            raise RuntimeError("Thiếu thư viện 'opencv-python'.")
        tpl = self._get(name, window_width or origin.width)
        if tpl is None:
            return None
        th, tw = tpl.shape[:2]
        if th > prepared.shape[0] or tw > prepared.shape[1]:
            return None
        result = cv2.matchTemplate(prepared, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < (threshold if threshold is not None else self.threshold):
            return None
        return Match(name, float(max_val),
                     origin.left + max_loc[0] + tw // 2,
                     origin.top + max_loc[1] + th // 2, tw, th)

    def count(self, prepared: np.ndarray, name: str, window_width: int,
              threshold: Optional[float] = None, max_hits: int = 50) -> int:
        """Đếm số lần template xuất hiện (dùng để đếm icon vật phẩm)."""
        tpl = self._get(name, window_width)
        if tpl is None or cv2 is None:
            return 0
        th, tw = tpl.shape[:2]
        if th > prepared.shape[0] or tw > prepared.shape[1]:
            return 0
        result = cv2.matchTemplate(prepared, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= (threshold or self.threshold))
        # Gộp các điểm khớp sát nhau (non-maximum suppression đơn giản)
        hits: list[tuple[int, int]] = []
        for x, y in sorted(zip(xs.tolist(), ys.tolist()), key=lambda p: -result[p[1], p[0]]):
            if all(abs(x - hx) > tw // 2 or abs(y - hy) > th // 2 for hx, hy in hits):
                hits.append((x, y))
                if len(hits) >= max_hits:
                    break
        return len(hits)


class Vision:
    """Kết hợp chụp màn hình + so khớp. Đây là đối tượng engine sử dụng."""

    def __init__(self, matcher: TemplateMatcher, capture: Optional[ScreenCapture] = None) -> None:
        self.matcher = matcher
        self.capture = capture or ScreenCapture()

    def grab(self, rect: Rect) -> np.ndarray:
        return self.capture.grab(rect)

    def find(self, rect: Rect, name: str, threshold: Optional[float] = None) -> Optional[Match]:
        frame = self.matcher.prepare(self.grab(rect))
        return self.matcher.find(frame, name, rect, threshold=threshold)

    def find_any(self, rect: Rect, names: Dict[str, str]) -> Optional[Tuple[str, Match]]:
        """Chụp MỘT lần rồi thử nhiều template -> trả về (khóa, match) tốt nhất."""
        frame = self.matcher.prepare(self.grab(rect))
        best: Optional[Tuple[str, Match]] = None
        for key, tpl_name in names.items():
            m = self.matcher.find(frame, tpl_name, rect)
            if m and (best is None or m.score > best[1].score):
                best = (key, m)
        return best

    def count_items(self, rect: Rect, item_dir: Path) -> Dict[str, int]:
        """Đếm mọi icon trong ``templates/items`` xuất hiện trên màn hình thưởng."""
        result: Dict[str, int] = {}
        if not item_dir.exists():
            return result
        frame = self.matcher.prepare(self.grab(rect))
        for png in sorted(item_dir.glob("*.png")):
            n = self.matcher.count(frame, str(png), rect.width)
            if n:
                result[png.stem] = n
        return result


def save_png(image: np.ndarray, path: Path) -> None:
    """Lưu ảnh BGR ra PNG (hỗ trợ đường dẫn Unicode)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise IOError(f"Không mã hóa được ảnh {path}")
    buf.tofile(str(path))
