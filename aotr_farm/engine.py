"""FarmEngine - máy trạng thái điều phối vòng farm.

Luồng một lượt farm::

    ┌────────┐ start macro ┌────────────┐ reward thấy ┌────────┐ after_reward
    │ LOBBY  │────────────►│ IN_MISSION │────────────►│ REWARD │───────────┐
    └────────┘             └────────────┘             └────────┘           │
        ▲      (mission_loop lặp lại tới khi thấy màn hình thưởng)        │
        └──────────────────────────────────────────────────────────────────┘

Phát hiện lỗi:
    * Không tìm thấy cửa sổ Roblox / cửa sổ bị thu nhỏ.
    * Thấy hộp thoại mất kết nối (template ``disconnected``).
    * Một lượt vượt ``mission_timeout``.
    * Không nhận diện được trạng thái nào trong ``stuck_timeout`` giây (kẹt).
    * Macro lỗi (không thấy nút cần bấm...).
    Mỗi lỗi -> thông báo + chạy macro ``recover``; lỗi liên tiếp vượt
    ``max_consecutive_errors`` -> dừng hẳn.

Engine chạy ở luồng riêng; GUI chỉ gọi start/stop/pause/resume và nhận sự
kiện qua ``on_event`` (callback được gọi từ luồng engine, GUI phải tự đẩy vào
hàng đợi của mình).
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .config import TEMPLATE_DIR, AppConfig
from .macro import MacroError, MacroLibrary, MacroRunner, StopRequested
from .notifier import ERROR, INFO, WARNING, Notifier
from .stats import SessionStats

log = logging.getLogger(__name__)


class State(str, enum.Enum):
    IDLE = "Chờ lệnh"
    STARTING = "Khởi động"
    LOBBY = "Ở sảnh"
    IN_MISSION = "Đang làm nhiệm vụ"
    REWARD = "Nhận thưởng"
    RECOVERING = "Đang khôi phục"
    BREAK = "Nghỉ giải lao"
    PAUSED = "Tạm dừng"
    STOPPING = "Đang dừng"
    STOPPED = "Đã dừng"
    ERROR = "Lỗi"


class FarmError(Exception):
    """Lỗi có thể khôi phục trong một lượt farm."""


class FatalError(Exception):
    """Lỗi không thể tiếp tục (ví dụ thiếu macro bắt buộc)."""


class FarmEngine:
    # Chờ hiệu ứng số đếm trên màn hình thưởng chạy xong trước khi OCR (giây)
    REWARD_SETTLE_DELAY = 0.8

    def __init__(self, cfg: AppConfig, window, vision, input_ctl, macros: MacroLibrary,
                 reward_reader, notifier: Notifier, stats: SessionStats,
                 template_dir: Path = TEMPLATE_DIR) -> None:
        self.cfg = cfg
        self.window = window
        self.vision = vision
        self.input = input_ctl
        self.macros = macros
        self.reward_reader = reward_reader
        self.notifier = notifier
        self.stats = stats
        self.template_dir = template_dir

        self.on_event: Callable[[str, Dict[str, Any]], None] = lambda kind, data: None
        self.state = State.IDLE
        self.stop_reason = ""

        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume.set()                     # set = đang chạy, clear = đang pause
        self._thread: Optional[threading.Thread] = None
        self._runner = MacroRunner(self, jitter=cfg.timing.action_jitter)
        self._last_state_change = time.monotonic()
        self._last_known_state_at = time.monotonic()
        self._state_before_pause = State.IN_MISSION
        self._held_before_pause: set[str] = set()
        self._stop_at: Optional[datetime] = None
        self._farm_since_break = 0.0
        self._warned_missing: set[str] = set()

    # ================================================================== #
    # API cho GUI
    # ================================================================== #
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def start(self) -> bool:
        if self.running:
            return False
        self._stop.clear()
        self._resume.set()
        self.stop_reason = ""
        self._thread = threading.Thread(target=self._main, name="farm-engine", daemon=True)
        self._thread.start()
        return True

    def stop(self, reason: str = "Người dùng dừng") -> None:
        if not self.running:
            return
        self.stop_reason = self.stop_reason or reason
        self._stop.set()
        self._resume.set()          # đánh thức nếu đang pause
        self._set_state(State.STOPPING)

    def pause(self) -> None:
        if self.running and not self.paused:
            self._state_before_pause = self.state
            self._resume.clear()
            self.stats.pause()
            self._held_before_pause = {k for k in self.input.held if not k.startswith("mouse:")}
            self.input.release_all()   # nhả phím ngay để nhân vật không chạy lung tung
            self._set_state(State.PAUSED)
            log.info("Tạm dừng")

    def resume(self) -> None:
        if self.running and self.paused:
            self.stats.resume()
            self._resume.set()
            log.info("Tiếp tục")

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # ================================================================== #
    # MacroContext (macro gọi ngược vào engine)
    # ================================================================== #
    def checkpoint(self) -> None:
        """Điểm kiểm tra: dừng nếu Stop, chờ nếu Pause."""
        if self._stop.is_set():
            raise StopRequested()
        if not self._resume.is_set():
            # Nhả lại phím ngay trên luồng engine (phòng trường hợp engine vừa
            # nhấn phím đúng lúc GUI bấm Pause)
            held = {k for k in self.input.held if not k.startswith("mouse:")}
            self._held_before_pause = self._held_before_pause | held
            self.input.release_all()
            self._resume.wait()
            if self._stop.is_set():
                raise StopRequested()
            # Giữ lại phím đang nhấn trước khi pause (ví dụ đang giữ W)
            for key in self._held_before_pause:
                self.input.key_down(key)
            self._held_before_pause = set()
            if self.cfg.focus_window:
                self.window.focus()
            self._set_state(self._state_before_pause)

    def sleep(self, seconds: float) -> None:
        """Ngủ có thể ngắt; thời gian pause không tính vào ``seconds``."""
        remaining = max(0.0, seconds)
        while remaining > 0:
            self.checkpoint()
            step = min(0.1, remaining)
            t0 = time.monotonic()
            if self._stop.wait(step):
                raise StopRequested()
            if self._resume.is_set():
                remaining -= time.monotonic() - t0
        self.checkpoint()

    def to_abs(self, rx: float, ry: float) -> tuple[int, int]:
        rect = self._require_window()
        return rect.to_abs(rx, ry)

    def find_template(self, name: str, threshold: Optional[float] = None):
        rect = self._require_window()
        if not self._template_exists(name):
            return None
        return self.vision.find(rect, name, threshold)

    def run_macro(self, name: str) -> None:
        self._runner.run(self.macros.get(name))

    # ================================================================== #
    # Vòng lặp chính
    # ================================================================== #
    def _main(self) -> None:
        self.stats.start_session()
        self._set_state(State.STARTING)
        self._compute_stop_at()
        self._farm_since_break = 0.0
        consecutive_errors = 0
        self._emit("session_started", {})
        log.info("Bắt đầu farm")
        try:
            self._preflight()
            while not self._stop.is_set():
                if self._limit_reached():
                    break
                self._maybe_take_break()
                cycle_start = self.stats.elapsed
                try:
                    self._one_run()
                    consecutive_errors = 0
                except FarmError as exc:
                    consecutive_errors += 1
                    self._handle_error(str(exc), consecutive_errors)
                    if consecutive_errors >= self.cfg.max_consecutive_errors:
                        self.stop_reason = f"Quá {consecutive_errors} lỗi liên tiếp: {exc}"
                        self.notifier.notify(ERROR, "Dừng farm", self.stop_reason)
                        break
                    self._recover()
                except MacroError as exc:
                    consecutive_errors += 1
                    self._handle_error(f"Macro: {exc}", consecutive_errors)
                    if consecutive_errors >= self.cfg.max_consecutive_errors:
                        self.stop_reason = f"Macro lỗi liên tiếp: {exc}"
                        self.notifier.notify(ERROR, "Dừng farm", self.stop_reason)
                        break
                    self._recover()
                self._farm_since_break += self.stats.elapsed - cycle_start
        except StopRequested:
            pass
        except FatalError as exc:
            self.stop_reason = str(exc)
            self.notifier.notify(ERROR, "Không thể chạy", str(exc))
            self._set_state(State.ERROR)
        except Exception as exc:  # lỗi bất ngờ: ghi đầy đủ traceback
            log.exception("Lỗi không mong muốn")
            self.stop_reason = f"Lỗi không mong muốn: {exc}"
            self.notifier.notify(ERROR, "Lỗi chương trình", self.stop_reason)
            self._set_state(State.ERROR)
        finally:
            self.input.release_all()
            if self.stats.current is not None:
                self.stats.finish_run(False, note="Bị dừng giữa chừng")
            self.stats.end_session()
            path = self.stats.save_summary()
            reason = self.stop_reason or "Hoàn tất"
            log.info("Kết thúc farm: %s%s", reason, f" (đã lưu {path.name})" if path else "")
            if self.state != State.ERROR:
                self._set_state(State.STOPPED)
            self._emit("session_stopped", {"reason": reason})
            if reason != "Người dùng dừng":
                self.notifier.notify(INFO, "Kết thúc farm", reason)

    def _preflight(self) -> None:
        """Kiểm tra trước khi chạy: cửa sổ game, macro bắt buộc, template."""
        if not self.window.ensure():
            raise FatalError(f"Không tìm thấy cửa sổ '{self.cfg.window_title}'. Hãy mở Roblox và vào AOTR.")
        if not self.macros.exists(self.cfg.macro_mission):
            raise FatalError(f"Thiếu macro bắt buộc '{self.cfg.macro_mission}' trong config/macros/")
        try:
            self.macros.get(self.cfg.macro_mission)
        except MacroError as exc:
            raise FatalError(str(exc)) from exc
        if not self._state_template("reward"):
            log.warning("Chưa có template màn hình thưởng -> chạy chế độ HẸN GIỜ: "
                        "mỗi lần chạy macro '%s' được tính là 1 lượt.", self.cfg.macro_mission)
        if self.cfg.focus_window and not self.window.focus():
            log.warning("Không đưa được cửa sổ Roblox lên trước - phím có thể không vào game.")

    # ------------------------------------------------------------------ #
    def _one_run(self) -> None:
        state = self._detect_state()
        if state == "disconnected":
            raise FarmError("Phát hiện hộp thoại mất kết nối")
        if state == "reward":
            # Bắt đầu đúng lúc đang ở màn hình thưởng (ví dụ resume sau lỗi)
            self.stats.begin_run()
            self._handle_reward()
            return
        if state != "in_mission":
            self._enter_mission()

        self.stats.begin_run()
        self._set_state(State.IN_MISSION)
        self._emit("run_started", {"index": self.stats.current.index})
        mission_deadline = time.monotonic() + self.cfg.timing.mission_timeout
        timed_mode = not self._state_template("reward")
        self._last_known_state_at = time.monotonic()

        while True:
            self._check_window()
            self.run_macro(self.cfg.macro_mission)
            if timed_mode:
                self._handle_reward()
                return
            state = self._detect_state()
            now = time.monotonic()
            if state == "reward":
                self._handle_reward()
                return
            if state == "disconnected":
                raise FarmError("Mất kết nối giữa nhiệm vụ")
            if state is not None:
                self._last_known_state_at = now
            elif now - self._last_known_state_at > self.cfg.timing.stuck_timeout:
                raise FarmError(f"Kẹt: không nhận diện được màn hình trong "
                                f"{self.cfg.timing.stuck_timeout:.0f}s")
            if now > mission_deadline:
                raise FarmError(f"Nhiệm vụ quá {self.cfg.timing.mission_timeout:.0f}s")

    def _enter_mission(self) -> None:
        """Ở sảnh: chờ nút Play rồi chạy macro vào nhiệm vụ."""
        self._set_state(State.LOBBY)
        if self._state_template("lobby"):
            deadline = time.monotonic() + self.cfg.timing.lobby_wait_timeout
            while (state := self._detect_state()) != "lobby":
                if state == "in_mission":
                    return
                if time.monotonic() > deadline:
                    raise FarmError("Không thấy màn hình sảnh")
                self.sleep(self.cfg.timing.detection_interval)
        if self.macros.exists(self.cfg.macro_start):
            self.run_macro(self.cfg.macro_start)
        # Chờ vào trận (nếu có template HUD nhiệm vụ)
        if self._state_template("in_mission"):
            deadline = time.monotonic() + self.cfg.timing.lobby_wait_timeout
            while self._detect_state() != "in_mission":
                if time.monotonic() > deadline:
                    raise FarmError("Không vào được nhiệm vụ (hết thời gian chờ tải)")
                self.sleep(self.cfg.timing.detection_interval)

    def _handle_reward(self) -> None:
        self._set_state(State.REWARD)
        self.sleep(self.REWARD_SETTLE_DELAY)
        rewards: Dict[str, int] = {}
        items: Dict[str, int] = {}
        rect = self._require_window()
        try:
            frame = self.vision.grab(rect)
            rewards = self.reward_reader.read_rewards(frame, rect)
            if self.cfg.ocr.detect_items:
                items = self.vision.count_items(rect, self.template_dir / "items")
        except Exception as exc:
            log.warning("Không đọc được phần thưởng: %s", exc)
        rec = self.stats.finish_run(True, exp=rewards.get("exp", 0), gold=rewards.get("gold", 0),
                                    items=items)
        if rec:
            log.info("Lượt #%d xong sau %.0fs: +%d EXP, +%d vàng%s", rec.index, rec.duration,
                     rec.exp, rec.gold, f", vật phẩm {rec.items}" if rec.items else "")
            self._emit("run_finished", {"record": rec})
        if self.macros.exists(self.cfg.macro_reward):
            self.run_macro(self.cfg.macro_reward)
        self.sleep(self.cfg.timing.delay_between_runs)

    # ------------------------------------------------------------------ #
    # Lỗi & khôi phục
    # ------------------------------------------------------------------ #
    def _handle_error(self, message: str, count: int) -> None:
        self.input.release_all()
        self.stats.add_error()
        if self.stats.current is not None:
            self.stats.finish_run(False, note=message)
        self._set_state(State.ERROR)
        self.notifier.notify(WARNING, f"Lỗi ({count}/{self.cfg.max_consecutive_errors})", message)
        self._emit("error", {"message": message, "count": count})

    def _recover(self) -> None:
        self._set_state(State.RECOVERING)
        self.sleep(2.0)
        if not self.window.ensure():
            # Roblox có thể bị crash: chờ người dùng mở lại tối đa lobby_wait_timeout
            deadline = time.monotonic() + self.cfg.timing.lobby_wait_timeout
            while not self.window.ensure():
                if time.monotonic() > deadline:
                    return
                self.sleep(2.0)
        if self.cfg.focus_window:
            self.window.focus()
        if self.macros.exists(self.cfg.macro_recover):
            try:
                self.run_macro(self.cfg.macro_recover)
            except MacroError as exc:
                log.warning("Macro khôi phục lỗi: %s", exc)
        self._last_known_state_at = time.monotonic()

    def _require_window(self):
        rect = self.window.client_rect()
        if rect is None:
            raise FarmError("Mất cửa sổ Roblox (đã đóng hoặc crash?)")
        return rect

    def _check_window(self) -> None:
        self._require_window()
        if self.window.is_minimized():
            raise FarmError("Cửa sổ Roblox đang bị thu nhỏ")
        if self.cfg.focus_window and not self.window.is_foreground():
            if not self.window.focus():
                raise FarmError("Cửa sổ khác đang che Roblox - không thể gửi phím")

    # ------------------------------------------------------------------ #
    # Nhận diện trạng thái
    # ------------------------------------------------------------------ #
    def _template_exists(self, name: str) -> bool:
        ok = self.vision.matcher.exists(name)
        if not ok and name not in self._warned_missing:
            self._warned_missing.add(name)
            log.warning("Chưa có template '%s.png' trong templates/ - bỏ qua nhận diện này.", name)
        return ok

    def _state_template(self, key: str) -> Optional[str]:
        name = self.cfg.detection.state_templates.get(key)
        return name if name and self.vision.matcher.exists(name) else None

    def _detect_state(self) -> Optional[str]:
        """Trả về 'lobby' / 'in_mission' / 'reward' / 'disconnected' hoặc None."""
        rect = self._require_window()
        names = {k: v for k, v in self.cfg.detection.state_templates.items()
                 if v and self._template_exists(v)}
        if not names:
            return None
        found = self.vision.find_any(rect, names)
        return found[0] if found else None

    # ------------------------------------------------------------------ #
    # Giới hạn thời gian / số lượt / nghỉ giải lao
    # ------------------------------------------------------------------ #
    def _compute_stop_at(self) -> None:
        self._stop_at = None
        txt = self.cfg.timing.stop_at_clock.strip()
        if not txt:
            return
        try:
            hh, mm = (int(x) for x in txt.split(":"))
            now = datetime.now()
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            self._stop_at = target
            log.info("Sẽ tự dừng lúc %s", target.strftime("%H:%M %d/%m"))
        except ValueError:
            log.warning("Giờ dừng không hợp lệ: %r (định dạng HH:MM)", txt)

    def _limit_reached(self) -> bool:
        t = self.cfg.timing
        if t.max_runs and self.stats.success_runs >= t.max_runs:
            self.stop_reason = f"Đã đủ {t.max_runs} lượt"
        elif t.max_duration_minutes and self.stats.elapsed >= t.max_duration_minutes * 60:
            self.stop_reason = f"Đã chạy đủ {t.max_duration_minutes:g} phút"
        elif self._stop_at and datetime.now() >= self._stop_at:
            self.stop_reason = f"Đến giờ dừng {self.cfg.timing.stop_at_clock}"
        else:
            return False
        return True

    def time_left(self) -> Optional[float]:
        """Số giây còn lại theo giới hạn gần nhất (cho GUI hiển thị)."""
        options = []
        t = self.cfg.timing
        if t.max_duration_minutes:
            options.append(t.max_duration_minutes * 60 - self.stats.elapsed)
        if self._stop_at:
            options.append((self._stop_at - datetime.now()).total_seconds())
        return max(0.0, min(options)) if options else None

    def _maybe_take_break(self) -> None:
        t = self.cfg.timing
        if not (t.break_every_minutes and t.break_length_minutes):
            return
        if self._farm_since_break < t.break_every_minutes * 60:
            return
        self.input.release_all()
        self._set_state(State.BREAK)
        self.notifier.notify(INFO, "Nghỉ giải lao", f"Nghỉ {t.break_length_minutes:g} phút")
        self.stats.pause()          # thời gian nghỉ không tính vào thời gian farm
        try:
            self.sleep(t.break_length_minutes * 60)
        finally:
            self.stats.resume()
        self._farm_since_break = 0.0

    # ------------------------------------------------------------------ #
    def _set_state(self, state: State) -> None:
        if state != self.state:
            self.state = state
            self._last_state_change = time.monotonic()
            self._emit("state", {"state": state})

    def _emit(self, kind: str, data: Dict[str, Any]) -> None:
        try:
            self.on_event(kind, data)
        except Exception:
            log.exception("Lỗi trong on_event")
