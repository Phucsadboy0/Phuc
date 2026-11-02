"""Trình chạy macro khai báo bằng JSON.

Mỗi macro là file ``config/macros/<tên>.json``::

    {
      "name": "mission_loop",
      "description": "Đánh titan gần nhất",
      "steps": [
        {"action": "key_down", "key": "w"},
        {"action": "wait", "seconds": 1.5},
        {"action": "key_up", "key": "w"},
        {"action": "press", "key": "space", "times": 2, "interval": 0.2},
        {"action": "click", "x": 0.5, "y": 0.5, "button": "left"}
      ]
    }

Danh sách action được hỗ trợ: xem ``STEP_SCHEMA`` bên dưới hoặc README.

Mọi thao tác chờ đều đi qua ``ctx.sleep`` -> có thể Pause/Stop ngay lập tức,
kể cả giữa một bước "wait" dài.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from .config import MACRO_DIR

log = logging.getLogger(__name__)


class MacroError(Exception):
    """Lỗi khi nạp hoặc chạy macro (template không thấy, cú pháp sai...)."""


class StopRequested(Exception):
    """Ném ra khi người dùng bấm Stop -> thoát khỏi mọi vòng lặp lồng nhau."""


class MacroContext(Protocol):
    """Những gì macro cần từ engine (giúp test dễ bằng đối tượng giả)."""

    input: Any

    def sleep(self, seconds: float) -> None: ...
    def checkpoint(self) -> None: ...
    def to_abs(self, rx: float, ry: float) -> tuple[int, int]: ...
    def find_template(self, name: str, threshold: Optional[float] = None): ...
    def run_macro(self, name: str) -> None: ...


# Tham số bắt buộc (và kiểu) cho từng action -> dùng để kiểm tra khi nạp file
STEP_SCHEMA: Dict[str, Dict[str, type]] = {
    "press": {"key": str},               # tùy chọn: times, interval, hold
    "key_down": {"key": str},
    "key_up": {"key": str},
    "hold": {"key": str, "seconds": (int, float)},
    "wait": {"seconds": (int, float)},   # tùy chọn: jitter
    "click": {},                         # tùy chọn: x, y (0..1), button, times, interval
    "mouse_down": {},                    # tùy chọn: button
    "mouse_up": {},
    "mouse_move_rel": {"dx": int, "dy": int},  # tùy chọn: steps, duration
    "scroll": {"amount": int},
    "click_image": {"template": str},    # tùy chọn: timeout, threshold, optional, offset_x/y, anchor_x/y
    "wait_image": {"template": str},     # tùy chọn: timeout, threshold, optional
    "wait_image_gone": {"template": str},
    "if_image": {"template": str},       # then: [...], else: [...]
    "repeat": {"times": int, "steps": list},
    "call": {"macro": str},
    "release_all": {},
    "log": {"message": str},
}


def validate_steps(steps: List[Dict[str, Any]], where: str = "steps") -> None:
    if not isinstance(steps, list):
        raise MacroError(f"{where}: phải là danh sách")
    for i, step in enumerate(steps):
        loc = f"{where}[{i}]"
        if not isinstance(step, dict) or "action" not in step:
            raise MacroError(f"{loc}: thiếu trường 'action'")
        action = step["action"]
        if action not in STEP_SCHEMA:
            raise MacroError(f"{loc}: action không hợp lệ '{action}'")
        for key, typ in STEP_SCHEMA[action].items():
            if key not in step:
                raise MacroError(f"{loc} ({action}): thiếu tham số '{key}'")
            if not isinstance(step[key], typ):
                raise MacroError(f"{loc} ({action}): '{key}' sai kiểu")
        for key in ("x", "y", "anchor_x", "anchor_y"):
            if key in step and not 0.0 <= float(step[key]) <= 1.0:
                raise MacroError(f"{loc}: '{key}' phải nằm trong 0..1 (tọa độ tương đối)")
        if action == "repeat":
            validate_steps(step["steps"], f"{loc}.steps")
        if action == "if_image":
            validate_steps(step.get("then", []), f"{loc}.then")
            validate_steps(step.get("else", []), f"{loc}.else")


class Macro:
    def __init__(self, name: str, steps: List[Dict[str, Any]], description: str = "") -> None:
        validate_steps(steps)
        self.name = name
        self.steps = steps
        self.description = description

    @classmethod
    def load(cls, path: Path) -> "Macro":
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise MacroError(f"{path.name}: JSON lỗi dòng {exc.lineno}: {exc.msg}") from exc
        return cls(data.get("name", path.stem), data.get("steps", []), data.get("description", ""))


class MacroLibrary:
    """Nạp macro từ thư mục, tự nạp lại khi file thay đổi (sửa macro khi đang chạy)."""

    def __init__(self, macro_dir: Path = MACRO_DIR) -> None:
        self.macro_dir = macro_dir
        self._cache: Dict[str, tuple[float, Macro]] = {}

    def names(self) -> List[str]:
        return sorted(p.stem for p in self.macro_dir.glob("*.json"))

    def exists(self, name: str) -> bool:
        return (self.macro_dir / f"{name}.json").exists()

    def get(self, name: str) -> Macro:
        path = self.macro_dir / f"{name}.json"
        if not path.exists():
            raise MacroError(f"Không tìm thấy macro '{name}' ({path})")
        mtime = path.stat().st_mtime
        cached = self._cache.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        macro = Macro.load(path)
        self._cache[name] = (mtime, macro)
        log.debug("Đã nạp macro %s (%d bước)", name, len(macro.steps))
        return macro


class MacroRunner:
    """Thực thi từng bước của macro trên một ``MacroContext``."""

    MAX_CALL_DEPTH = 8

    def __init__(self, ctx: MacroContext, jitter: float = 0.1) -> None:
        self.ctx = ctx
        self.jitter = jitter
        self._depth = 0

    # ------------------------------------------------------------------ #
    def _jit(self, seconds: float, jitter: Optional[float] = None) -> float:
        """Thêm dao động ngẫu nhiên nhỏ để thao tác tự nhiên hơn."""
        j = self.jitter if jitter is None else jitter
        if j <= 0:
            return seconds
        return max(0.0, seconds * random.uniform(1 - j, 1 + j))

    def run(self, macro: Macro) -> None:
        self._depth += 1
        try:
            if self._depth > self.MAX_CALL_DEPTH:
                raise MacroError("Macro gọi lồng nhau quá sâu (có vòng lặp 'call'?)")
            self.run_steps(macro.steps)
        finally:
            self._depth -= 1

    def run_steps(self, steps: List[Dict[str, Any]]) -> None:
        for step in steps:
            self.ctx.checkpoint()   # Pause/Stop giữa các bước
            handler = getattr(self, f"_do_{step['action']}")
            handler(step)

    # ------------------------------ Bàn phím --------------------------- #
    def _do_press(self, s):
        times = int(s.get("times", 1))
        for i in range(times):
            self.ctx.input.press(s["key"], float(s.get("hold", 0.05)))
            if i < times - 1:
                self.ctx.sleep(self._jit(float(s.get("interval", 0.1))))

    def _do_key_down(self, s):
        self.ctx.input.key_down(s["key"])

    def _do_key_up(self, s):
        self.ctx.input.key_up(s["key"])

    def _do_hold(self, s):
        self.ctx.input.key_down(s["key"])
        try:
            self.ctx.sleep(self._jit(float(s["seconds"])))
        finally:
            self.ctx.input.key_up(s["key"])

    def _do_wait(self, s):
        self.ctx.sleep(self._jit(float(s["seconds"]), s.get("jitter")))

    # ------------------------------ Chuột ------------------------------ #
    def _do_click(self, s):
        x = y = None
        if "x" in s and "y" in s:
            x, y = self.ctx.to_abs(float(s["x"]), float(s["y"]))
        times = int(s.get("times", 1))
        for i in range(times):
            self.ctx.input.click(x, y, s.get("button", "left"))
            if i < times - 1:
                self.ctx.sleep(self._jit(float(s.get("interval", 0.1))))

    def _do_mouse_down(self, s):
        self.ctx.input.mouse_down(s.get("button", "left"))

    def _do_mouse_up(self, s):
        self.ctx.input.mouse_up(s.get("button", "left"))

    def _do_mouse_move_rel(self, s):
        """Xoay camera mượt: chia nhỏ chuyển động thành nhiều bước."""
        steps = max(1, int(s.get("steps", 10)))
        duration = float(s.get("duration", 0.2))
        dx, dy = int(s["dx"]), int(s["dy"])
        sent_x = sent_y = 0
        for i in range(1, steps + 1):
            tx, ty = dx * i // steps, dy * i // steps
            self.ctx.input.move_rel(tx - sent_x, ty - sent_y)
            sent_x, sent_y = tx, ty
            self.ctx.sleep(duration / steps)

    def _do_scroll(self, s):
        self.ctx.input.scroll(int(s["amount"]))

    # ------------------------------ Hình ảnh --------------------------- #
    def _wait_for(self, s, want_present: bool):
        timeout = float(s.get("timeout", 10.0))
        poll = float(s.get("poll", 0.5))
        deadline = time.monotonic() + timeout
        while True:
            match = self.ctx.find_template(s["template"], s.get("threshold"))
            if bool(match) == want_present:
                return match
            if time.monotonic() >= deadline:
                if s.get("optional", False):
                    log.debug("Bỏ qua (optional): %s '%s'", s["action"], s["template"])
                    return None
                verb = "xuất hiện" if want_present else "biến mất"
                raise MacroError(f"Hết {timeout:.0f}s chờ '{s['template']}' {verb}")
            self.ctx.sleep(poll)

    def _do_wait_image(self, s):
        self._wait_for(s, True)

    def _do_wait_image_gone(self, s):
        self._wait_for(s, False)

    def _do_click_image(self, s):
        match = self._wait_for(s, True)
        if match is None:
            return
        # anchor_x/anchor_y (0..1): click vào vị trí tương đối BÊN TRONG ảnh mẫu,
        # ví dụ anchor_y=0.92 = gần đáy ảnh (nút SELECT dưới thẻ Slot A).
        # Mặc định (0.5, 0.5) = tâm ảnh.
        x = match.x + int((float(s.get("anchor_x", 0.5)) - 0.5) * match.w)
        y = match.y + int((float(s.get("anchor_y", 0.5)) - 0.5) * match.h)
        x += int(s.get("offset_x", 0))
        y += int(s.get("offset_y", 0))
        self.ctx.input.click(x, y, s.get("button", "left"))

    def _do_if_image(self, s):
        branch = "then" if self.ctx.find_template(s["template"], s.get("threshold")) else "else"
        self.run_steps(s.get(branch, []))

    # ------------------------------ Điều khiển ------------------------- #
    def _do_repeat(self, s):
        for _ in range(int(s["times"])):
            self.run_steps(s["steps"])

    def _do_call(self, s):
        self.ctx.run_macro(s["macro"])

    def _do_release_all(self, _s):
        self.ctx.input.release_all()

    def _do_log(self, s):
        log.info("[macro] %s", s["message"])
