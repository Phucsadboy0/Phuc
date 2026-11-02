"""AOTR Farm Assistant - bản MỘT FILE (tự sinh bởi tools/build_onefile.py).

Chạy trên Windows:  python AOTRFarm.py          (mở giao diện)
                    python AOTRFarm.py --check  (kiểm tra môi trường)
Cài thư viện:       pip install numpy opencv-python mss Pillow psutil

Đây là chương trình Python chạy NGOÀI Roblox (đọc màn hình + giả lập phím/chuột).
KHÔNG phải script Lua cho executor.
"""

from __future__ import annotations

# ======================================================================
# __init__.py
# ======================================================================
"""AOTR Farm Assistant - công cụ hỗ trợ farm cho Attack on Titan Revolution.

Nguyên tắc thiết kế:
    * Chỉ tương tác với game giống như người chơi: đọc pixel trên màn hình
      và gửi phím/chuột qua Windows SendInput.
    * KHÔNG inject, KHÔNG đọc/ghi bộ nhớ, KHÔNG sửa client Roblox,
      KHÔNG dùng API nội bộ của AOTR.
"""

__version__ = "1.0.0"
APP_NAME = "AOTR Farm Assistant"


# ======================================================================
# config.py
# ======================================================================
"""Quản lý cấu hình (đọc / ghi file JSON).

Toàn bộ thông số có thể chỉnh trong GUI tab "Cài đặt" hoặc sửa trực tiếp
file ``config/settings.json``. Nếu file chưa có, chương trình tự tạo từ giá
trị mặc định bên dưới.
"""


import json
import logging
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)

# Thư mục gốc của dự án (chứa config/, templates/, data/, logs/).
# Khi chạy bản .exe (PyInstaller), dùng thư mục chứa file .exe thay vì thư mục
# giải nén tạm -> cấu hình, template, log được giữ lại giữa các lần chạy.
if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).resolve().parent
else:
    ROOT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = ROOT_DIR / "config"
MACRO_DIR = CONFIG_DIR / "macros"
TEMPLATE_DIR = ROOT_DIR / "templates"
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


@dataclass
class TimingConfig:
    """Các mốc thời gian điều khiển vòng farm (đơn vị: giây trừ khi ghi chú)."""

    detection_interval: float = 0.5      # Chu kỳ quét màn hình; tăng lên để giảm CPU
    mission_timeout: float = 900.0       # Một lượt quá thời gian này -> coi là lỗi
    stuck_timeout: float = 180.0         # Không đổi trạng thái quá lâu -> coi là kẹt
    lobby_wait_timeout: float = 120.0    # Chờ tối đa ở sảnh trước khi báo lỗi
    delay_between_runs: float = 3.0      # Nghỉ giữa 2 lượt
    max_runs: int = 0                    # 0 = không giới hạn số lượt
    max_duration_minutes: float = 0.0    # 0 = không giới hạn thời gian
    stop_at_clock: str = ""              # "HH:MM" - dừng lúc mấy giờ, rỗng = tắt
    break_every_minutes: float = 0.0     # Cứ mỗi X phút farm ...
    break_length_minutes: float = 0.0    # ... thì nghỉ Y phút (0 = tắt)
    action_jitter: float = 0.1           # Dao động ngẫu nhiên (±10%) cho thời gian chờ


@dataclass
class DetectionConfig:
    """Thông số nhận diện hình ảnh."""

    match_threshold: float = 0.82        # Ngưỡng khớp template (0..1)
    reference_width: int = 1280          # Độ rộng cửa sổ lúc chụp template
    grayscale: bool = True               # So khớp ảnh xám -> nhanh hơn, ít RAM hơn
    # Tên các template (file PNG trong templates/) dùng để nhận diện trạng thái
    state_templates: Dict[str, str] = field(default_factory=lambda: {
        "slot_select": "slot_a_card",     # màn hình chọn slot nhân vật khi mới vào game
        "lobby": "lobby_play_button",
        "in_mission": "mission_hud",
        "reward": "reward_screen",
        "disconnected": "disconnected_dialog",
    })


@dataclass
class OcrConfig:
    """Đọc số liệu phần thưởng bằng OCR (tùy chọn, cần Tesseract)."""

    enabled: bool = False
    tesseract_path: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    # Vùng cần đọc, tọa độ tương đối theo cửa sổ: [x, y, w, h] trong khoảng 0..1
    regions: Dict[str, List[float]] = field(default_factory=lambda: {
        "exp": [0.40, 0.45, 0.20, 0.05],
        "gold": [0.40, 0.52, 0.20, 0.05],
    })
    # Nếu tắt OCR: cộng giá trị cố định này cho mỗi lượt thành công
    fallback_exp_per_run: int = 0
    fallback_gold_per_run: int = 0
    # Template icon vật phẩm (templates/items/*.png) để đếm item rơi
    detect_items: bool = False


@dataclass
class NotifyConfig:
    """Thông báo khi có lỗi / hoàn thành."""

    sound: bool = True
    desktop_toast: bool = True
    discord_webhook: str = ""            # Để trống nếu không dùng


@dataclass
class AppConfig:
    """Cấu hình tổng của ứng dụng."""

    window_title: str = "Roblox"
    focus_window: bool = True            # Tự đưa cửa sổ Roblox lên trước khi gửi phím
    macro_start: str = "start_mission"   # Macro chạy ở sảnh để vào nhiệm vụ
    macro_mission: str = "mission_loop"  # Macro lặp trong lúc làm nhiệm vụ
    macro_reward: str = "after_reward"   # Macro ở màn hình thưởng (Retry/Continue)
    macro_recover: str = "recover"       # Macro khôi phục khi bị kẹt
    macro_select_slot: str = "select_slot"  # Macro chọn slot nhân vật (Slot A)
    max_consecutive_errors: int = 3      # Lỗi liên tiếp quá số này -> dừng hẳn
    hotkey_toggle: str = "F6"            # Start / Stop
    hotkey_pause: str = "F7"             # Pause / Resume
    hotkey_emergency: str = "F8"         # Dừng khẩn cấp
    log_level: str = "INFO"
    timing: TimingConfig = field(default_factory=TimingConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    # ------------------------------------------------------------------ #
    # Chuyển đổi dict <-> dataclass
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        """Tạo config từ dict, bỏ qua khóa lạ và giữ mặc định cho khóa thiếu."""
        return _build(cls, data)


def _build(klass, data: Dict[str, Any]):
    """Dựng dataclass đệ quy, chịu lỗi (khóa thiếu/thừa/sai kiểu)."""
    if not isinstance(data, dict):
        return klass()
    kwargs = {}
    defaults = klass()
    for f in fields(klass):
        if f.name not in data:
            continue
        value = data[f.name]
        default_value = getattr(defaults, f.name)
        if hasattr(default_value, "__dataclass_fields__"):
            kwargs[f.name] = _build(type(default_value), value)
        elif isinstance(default_value, dict) and isinstance(value, dict):
            # Gộp với mặc định -> file cấu hình cũ vẫn nhận được khóa mới
            kwargs[f.name] = {**default_value, **value}
        elif isinstance(default_value, bool):
            kwargs[f.name] = bool(value)
        elif isinstance(default_value, (int, float)) and not isinstance(value, (int, float)):
            try:
                kwargs[f.name] = type(default_value)(value)
            except (TypeError, ValueError):
                log.warning("Giá trị cấu hình không hợp lệ cho %s: %r", f.name, value)
        else:
            kwargs[f.name] = value
    return klass(**kwargs)


def load_config(path: Path = SETTINGS_FILE) -> AppConfig:
    """Đọc cấu hình; nếu chưa có hoặc hỏng thì dùng mặc định và ghi lại."""
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                return AppConfig.from_dict(json.load(fh))
        except (OSError, json.JSONDecodeError) as exc:
            log.error("Không đọc được %s (%s) - dùng cấu hình mặc định", path, exc)
    cfg = AppConfig()
    save_config(cfg, path)
    return cfg


def save_config(cfg: AppConfig, path: Path = SETTINGS_FILE) -> None:
    """Ghi cấu hình ra JSON (ghi file tạm rồi đổi tên để tránh hỏng file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(cfg.to_dict(), fh, indent=2, ensure_ascii=False)
    tmp.replace(path)


def ensure_dirs() -> None:
    """Tạo các thư mục làm việc nếu chưa tồn tại."""
    for d in (CONFIG_DIR, MACRO_DIR, TEMPLATE_DIR, TEMPLATE_DIR / "items", DATA_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


# Macro mẫu - tự ghi ra config/macros/ nếu chưa có
DEFAULT_MACROS = {'after_reward': {'name': 'after_reward',
                  'description': 'Ở màn hình thưởng: bấm Retry nếu có, nếu không thì bấm Continue / về sảnh.',
                  'steps': [{'action': 'if_image',
                             'template': 'retry_button',
                             'then': [{'action': 'click_image', 'template': 'retry_button', 'timeout': 5}],
                             'else': [{'action': 'click_image',
                                       'template': 'continue_button',
                                       'timeout': 10,
                                       'optional': True}]},
                            {'action': 'wait', 'seconds': 2.0}]},
 'mission_loop': {'name': 'mission_loop',
                  'description': 'Một chu kỳ hành động trong nhiệm vụ. Engine lặp lại macro này cho tới khi '
                                 'thấy màn hình thưởng. CHỈNH LẠI phím theo cài đặt điều khiển của bạn.',
                  'steps': [{'action': 'key_down', 'key': 'w'},
                            {'action': 'press', 'key': 'space', 'times': 2, 'interval': 0.25},
                            {'action': 'wait', 'seconds': 1.2},
                            {'action': 'key_up', 'key': 'w'},
                            {'action': 'mouse_move_rel', 'dx': 250, 'dy': 0, 'steps': 12, 'duration': 0.3},
                            {'action': 'click', 'button': 'left', 'times': 3, 'interval': 0.35},
                            {'action': 'wait', 'seconds': 0.5}]},
 'recover': {'name': 'recover',
             'description': 'Chạy khi có lỗi/kẹt: nhả phím, đóng hộp thoại, thử kết nối lại.',
             'steps': [{'action': 'release_all'},
                       {'action': 'wait', 'seconds': 1.0},
                       {'action': 'click_image',
                        'template': 'reconnect_button',
                        'timeout': 3,
                        'optional': True},
                       {'action': 'click_image', 'template': 'close_button', 'timeout': 3, 'optional': True},
                       {'action': 'click_image',
                        'template': 'continue_button',
                        'timeout': 3,
                        'optional': True},
                       {'action': 'wait', 'seconds': 2.0}]},
 'select_slot': {'name': 'select_slot',
                 'description': "Màn hình chọn nhân vật khi mới vào game: bấm SELECT ở Slot A, rồi bấm 'Join "
                                "Community' nếu popup 'Join AoTR' hiện ra. Template 'slot_a_card' là ảnh "
                                'chụp CẢ thẻ Slot A (từ chữ SLOT A tới nút SELECT); anchor_y 0.92 = vị trí '
                                "nút SELECT gần đáy thẻ. Template 'join_community_button' là ảnh chụp nút "
                                "xanh 'Join Community'.",
                 'steps': [{'action': 'log', 'message': 'Chọn Slot A...'},
                           {'action': 'click_image',
                            'template': 'slot_a_card',
                            'anchor_x': 0.5,
                            'anchor_y': 0.92,
                            'timeout': 10},
                           {'action': 'wait', 'seconds': 1.5},
                           {'action': 'if_image',
                            'template': 'join_community_button',
                            'then': [{'action': 'log', 'message': 'Bấm Join Community'},
                                     {'action': 'click_image',
                                      'template': 'join_community_button',
                                      'timeout': 5},
                                     {'action': 'wait', 'seconds': 1.5}]},
                           {'action': 'click_image',
                            'template': 'join_community_button',
                            'timeout': 4,
                            'optional': True},
                           {'action': 'wait_image_gone',
                            'template': 'slot_a_card',
                            'timeout': 30,
                            'optional': True},
                           {'action': 'wait', 'seconds': 3.0}]},
 'start_mission': {'name': 'start_mission',
                   'description': 'Menu chính -> PLAY -> ô LOBBY -> chờ tải -> trong lobby bấm ô PLAY lớn. '
                                  "Template: 'lobby_play_button' = chữ PLAY trên menu chính KÈM một phần chữ "
                                  'CUSTOMIZATION bên dưới (để không nhầm với ô PLAY trong lobby), anchor_y '
                                  "0.3 = bấm vào phần chữ PLAY ở trên; 'lobby_card' = ô LOBBY; "
                                  "'mission_play_button' = ô PLAY lớn trong lobby (khung viền cam, dòng N/A "
                                  "phía trên). 'missions_card' = thẻ MISSIONS (chụp tiêu đề MISSIONS kèm "
                                  'phần trên của hình).',
                   'steps': [{'action': 'log', 'message': 'Menu chính: bấm PLAY'},
                             {'action': 'click_image',
                              'template': 'lobby_play_button',
                              'anchor_y': 0.3,
                              'timeout': 15},
                             {'action': 'wait', 'seconds': 1.5},
                             {'action': 'log', 'message': 'Chọn LOBBY'},
                             {'action': 'click_image', 'template': 'lobby_card', 'timeout': 15},
                             {'action': 'wait', 'seconds': 2.0},
                             {'action': 'wait_image_gone',
                              'template': 'lobby_card',
                              'timeout': 60,
                              'optional': True},
                             {'action': 'log', 'message': 'Trong lobby: bấm PLAY'},
                             {'action': 'click_image', 'template': 'mission_play_button', 'timeout': 60},
                             {'action': 'wait', 'seconds': 2.0},
                             {'action': 'log', 'message': 'Chọn MISSIONS'},
                             {'action': 'click_image', 'template': 'missions_card', 'timeout': 20},
                             {'action': 'wait', 'seconds': 1.5}]}}


def write_default_macros() -> None:
    MACRO_DIR.mkdir(parents=True, exist_ok=True)
    for _name, _data in DEFAULT_MACROS.items():
        _p = MACRO_DIR / f'{_name}.json'
        if not _p.exists():
            _p.write_text(json.dumps(_data, ensure_ascii=False, indent=2), encoding='utf-8')


# ======================================================================
# logging_setup.py
# ======================================================================
"""Cấu hình logging: ghi file xoay vòng + đẩy log sang GUI qua hàng đợi.

* File log: ``logs/farm.log`` (tối đa 2 MB x 5 file -> không phình ổ đĩa).
* GUI đọc log từ ``log_queue`` theo chu kỳ, không khóa luồng farm.
"""


import logging
import queue
import sys
from logging.handlers import QueueHandler, RotatingFileHandler
from pathlib import Path


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


# ======================================================================
# stats.py
# ======================================================================
"""Thống kê phần thưởng và thời gian farm.

* ``RunRecord``    : kết quả của một lượt (EXP, vàng, vật phẩm, thời gian).
* ``SessionStats`` : cộng dồn cả phiên, tính tốc độ/giờ, xuất CSV & JSON.

Lớp này an toàn đa luồng (luồng farm ghi, luồng GUI đọc).
"""


import csv
import json
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class RunRecord:
    index: int
    started_at: float
    ended_at: float = 0.0
    success: bool = False
    exp: int = 0
    gold: int = 0
    items: Dict[str, int] = field(default_factory=dict)
    note: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, (self.ended_at or time.time()) - self.started_at)

    def to_row(self) -> Dict[str, object]:
        return {
            "index": self.index,
            "started_at": datetime.fromtimestamp(self.started_at).isoformat(timespec="seconds"),
            "duration_s": round(self.duration, 1),
            "success": self.success,
            "exp": self.exp,
            "gold": self.gold,
            "items": ";".join(f"{k}x{v}" for k, v in sorted(self.items.items())),
            "note": self.note,
        }


class SessionStats:
    """Thống kê của một phiên farm (từ lúc bấm Start tới lúc Stop)."""

    # Chỉ giữ N lượt gần nhất trong RAM; toàn bộ lịch sử vẫn ghi ra CSV
    MAX_RECORDS_IN_MEMORY = 500

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self.data_dir = data_dir
        self.reset()

    # ------------------------------------------------------------------ #
    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self.session_start: float = 0.0
            self.session_end: float = 0.0
            self.paused_total: float = 0.0     # Tổng thời gian tạm dừng
            self._pause_started: float = 0.0
            self.records: List[RunRecord] = []
            self.total_runs = 0
            self.success_runs = 0
            self.failed_runs = 0
            self.total_exp = 0
            self.total_gold = 0
            self.items: Counter = Counter()
            self.errors = 0
            self.current: Optional[RunRecord] = None

    def start_session(self) -> None:
        self.reset()
        self.session_start = time.time()

    def end_session(self) -> None:
        if self._pause_started:
            self.resume()
        self.session_end = time.time()

    def pause(self) -> None:
        if not self._pause_started:
            self._pause_started = time.time()

    def resume(self) -> None:
        if self._pause_started:
            self.paused_total += time.time() - self._pause_started
            self._pause_started = 0.0

    # ------------------------------------------------------------------ #
    def begin_run(self) -> RunRecord:
        with self._lock:
            self.current = RunRecord(index=self.total_runs + 1, started_at=time.time())
            return self.current

    def finish_run(self, success: bool, exp: int = 0, gold: int = 0,
                   items: Optional[Dict[str, int]] = None, note: str = "") -> Optional[RunRecord]:
        """Kết thúc lượt hiện tại và cộng dồn phần thưởng."""
        with self._lock:
            rec = self.current
            if rec is None:
                return None
            rec.ended_at = time.time()
            rec.success = success
            rec.exp = max(0, int(exp))
            rec.gold = max(0, int(gold))
            rec.items = dict(items or {})
            rec.note = note
            self.total_runs += 1
            if success:
                self.success_runs += 1
                self.total_exp += rec.exp
                self.total_gold += rec.gold
                self.items.update(rec.items)
            else:
                self.failed_runs += 1
            self.records.append(rec)
            if len(self.records) > self.MAX_RECORDS_IN_MEMORY:
                del self.records[: len(self.records) - self.MAX_RECORDS_IN_MEMORY]
            self.current = None
        self._append_csv(rec)
        return rec

    def add_error(self) -> None:
        with self._lock:
            self.errors += 1

    # ------------------------------------------------------------------ #
    # Số liệu dẫn xuất
    # ------------------------------------------------------------------ #
    @property
    def elapsed(self) -> float:
        """Thời gian farm thực tế (đã trừ thời gian pause)."""
        if not self.session_start:
            return 0.0
        end = self.session_end or time.time()
        paused = self.paused_total
        if self._pause_started:
            paused += time.time() - self._pause_started
        return max(0.0, end - self.session_start - paused)

    def per_hour(self, value: float) -> float:
        hours = self.elapsed / 3600.0
        return value / hours if hours > 1e-6 else 0.0

    def avg_run_time(self) -> float:
        with self._lock:
            done = [r.duration for r in self.records if r.success]
        return sum(done) / len(done) if done else 0.0

    def snapshot(self) -> Dict[str, object]:
        """Bản tóm tắt để GUI hiển thị / lưu JSON."""
        with self._lock:
            items = dict(self.items)
            total, ok, fail = self.total_runs, self.success_runs, self.failed_runs
            exp, gold, errors = self.total_exp, self.total_gold, self.errors
            current_dur = self.current.duration if self.current else 0.0
        return {
            "elapsed": self.elapsed,
            "total_runs": total,
            "success_runs": ok,
            "failed_runs": fail,
            "success_rate": (ok / total * 100.0) if total else 0.0,
            "total_exp": exp,
            "total_gold": gold,
            "exp_per_hour": self.per_hour(exp),
            "gold_per_hour": self.per_hour(gold),
            "runs_per_hour": self.per_hour(ok),
            "avg_run_time": self.avg_run_time(),
            "current_run_time": current_dur,
            "items": items,
            "errors": errors,
        }

    # ------------------------------------------------------------------ #
    # Lưu trữ
    # ------------------------------------------------------------------ #
    def _append_csv(self, rec: RunRecord) -> None:
        if not self.data_dir:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "run_history.csv"
        row = rec.to_row()
        new_file = not path.exists()
        try:
            with path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
                if new_file:
                    writer.writeheader()
                writer.writerow(row)
        except OSError:
            pass  # Không để lỗi ghi file làm dừng farm

    def save_summary(self) -> Optional[Path]:
        """Ghi tóm tắt phiên ra data/session_YYYYmmdd_HHMMSS.json."""
        if not self.data_dir or not self.session_start:
            return None
        self.data_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromtimestamp(self.session_start).strftime("%Y%m%d_%H%M%S")
        path = self.data_dir / f"session_{stamp}.json"
        data = self.snapshot()
        with self._lock:
            data["runs"] = [asdict(r) for r in self.records]
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        return path


def fmt_duration(seconds: float) -> str:
    """12345 -> '03:25:45'."""
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ======================================================================
# platform/__init__.py
# ======================================================================
"""Lớp nền tảng: cửa sổ và thiết bị nhập (Windows).

Các module ở đây chỉ dùng API công khai của Windows (user32) thông qua
``ctypes`` -> không cần pywin32 và không chạm vào tiến trình Roblox.
"""

import sys

IS_WINDOWS = sys.platform == "win32"


# ======================================================================
# platform/window.py
# ======================================================================
"""Tìm và quản lý cửa sổ Roblox bằng user32 (FindWindow, GetClientRect...).

Chỉ đọc vị trí/kích thước cửa sổ và đưa nó lên foreground. Không đọc bộ nhớ
hay can thiệp vào tiến trình game.
"""


import ctypes
import logging
import time
from dataclasses import dataclass
from typing import Optional


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Rect:
    """Vùng client của cửa sổ, tọa độ màn hình (pixel)."""

    left: int
    top: int
    width: int
    height: int

    def to_abs(self, rx: float, ry: float) -> tuple[int, int]:
        """Đổi tọa độ tương đối (0..1) trong cửa sổ -> tọa độ màn hình."""
        return int(self.left + rx * self.width), int(self.top + ry * self.height)

    def sub(self, rx: float, ry: float, rw: float, rh: float) -> "Rect":
        """Lấy vùng con theo tọa độ tương đối."""
        return Rect(
            int(self.left + rx * self.width),
            int(self.top + ry * self.height),
            max(1, int(rw * self.width)),
            max(1, int(rh * self.height)),
        )


if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    # Bật DPI awareness để tọa độ chụp màn hình khớp tọa độ chuột
    # (nếu không, màn hình scale 125%/150% sẽ bị lệch).
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except (OSError, AttributeError):
        try:
            user32.SetProcessDPIAware()
        except AttributeError:
            pass

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class GameWindow:
    """Bao gói cửa sổ game. Tự tìm lại cửa sổ nếu Roblox bị đóng/mở lại."""

    def __init__(self, title: str = "Roblox") -> None:
        self.title = title
        self.hwnd: Optional[int] = None

    # ------------------------------------------------------------------ #
    def find(self) -> bool:
        """Tìm cửa sổ có tiêu đề đúng bằng ``title`` (hoặc chứa ``title``)."""
        if not IS_WINDOWS:
            return False
        hwnd = user32.FindWindowW(None, self.title)
        if not hwnd:
            hwnd = self._find_partial()
        self.hwnd = hwnd or None
        return self.hwnd is not None

    def _find_partial(self) -> int:
        found = []
        needle = self.title.lower()

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if needle in buf.value.lower():
                    found.append(hwnd)
                    return False  # dừng duyệt
            return True

        user32.EnumWindows(EnumWindowsProc(callback), 0)
        return found[0] if found else 0

    def is_valid(self) -> bool:
        return bool(IS_WINDOWS and self.hwnd and user32.IsWindow(self.hwnd))

    def ensure(self) -> bool:
        """Đảm bảo đang giữ handle hợp lệ (tìm lại nếu cần)."""
        return self.is_valid() or self.find()

    def is_minimized(self) -> bool:
        return bool(self.is_valid() and user32.IsIconic(self.hwnd))

    def is_foreground(self) -> bool:
        return bool(self.is_valid() and user32.GetForegroundWindow() == self.hwnd)

    def focus(self) -> bool:
        """Đưa cửa sổ lên trước để phím/chuột đi vào đúng game."""
        if not self.ensure():
            return False
        if self.is_foreground():
            return True
        SW_RESTORE = 9
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_RESTORE)
        # Mẹo phổ biến: nhấn/nhả ALT để Windows cho phép SetForegroundWindow
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(self.hwnd)
        time.sleep(0.15)
        return self.is_foreground()

    def client_rect(self) -> Optional[Rect]:
        """Vùng client (không gồm viền/tiêu đề) theo tọa độ màn hình."""
        if not self.ensure():
            return None
        rect = wintypes.RECT()
        if not user32.GetClientRect(self.hwnd, ctypes.byref(rect)):
            return None
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        return Rect(pt.x, pt.y, w, h)


# ======================================================================
# platform/input.py
# ======================================================================
"""Giả lập bàn phím/chuột qua Windows ``SendInput`` (scan code).

Roblox đọc phím theo scan code (DirectInput/raw input) nên các thư viện chỉ gửi
virtual-key (như pyautogui) thường không hoạt động khi xoay camera hoặc di
chuyển. Module này gửi scan code giống bàn phím thật.

Mọi phím đang giữ được ghi nhận để ``release_all()`` nhả hết khi Pause/Stop,
tránh trường hợp nhân vật bị "kẹt" giữ phím W.
"""


import ctypes
import logging
import threading
import time
from typing import Set


log = logging.getLogger(__name__)

# Bảng scan code (Set 1). Phím có cờ extended đánh dấu bằng 0xE0xx.
SCAN_CODES = {
    "esc": 0x01, "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B, "-": 0x0C, "=": 0x0D,
    "backspace": 0x0E, "tab": 0x0F, "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13,
    "t": 0x14, "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "[": 0x1A, "]": 0x1B, "enter": 0x1C, "ctrl": 0x1D, "a": 0x1E, "s": 0x1F,
    "d": 0x20, "f": 0x21, "g": 0x22, "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    ";": 0x27, "'": 0x28, "`": 0x29, "shift": 0x2A, "\\": 0x2B, "z": 0x2C,
    "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30, "n": 0x31, "m": 0x32, ",": 0x33,
    ".": 0x34, "/": 0x35, "rshift": 0x36, "alt": 0x38, "space": 0x39,
    "capslock": 0x3A, "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F,
    "f6": 0x40, "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44, "f11": 0x57,
    "f12": 0x58,
    "up": 0xE048, "down": 0xE050, "left": 0xE04B, "right": 0xE04D,
    "insert": 0xE052, "delete": 0xE053, "home": 0xE047, "end": 0xE04F,
    "pageup": 0xE049, "pagedown": 0xE051, "rctrl": 0xE01D, "ralt": 0xE038,
}

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x8
    MOUSEEVENTF_MOVE = 0x0001
    MOUSE_FLAGS = {
        "left": (0x0002, 0x0004),
        "right": (0x0008, 0x0010),
        "middle": (0x0020, 0x0040),
    }
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    def _send(*inputs: "INPUT") -> None:
        arr = (INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


class InputController:
    """Gửi phím/chuột. Thread-safe; ghi nhớ phím/chuột đang giữ."""

    def __init__(self) -> None:
        self._held_keys: Set[str] = set()
        self._held_buttons: Set[str] = set()
        self._lock = threading.Lock()
        if not IS_WINDOWS:
            log.warning("Không phải Windows - InputController chạy ở chế độ giả lập (không gửi phím).")

    # ------------------------------ Bàn phím --------------------------- #
    @staticmethod
    def _scan(key: str) -> int:
        key = key.lower()
        if key not in SCAN_CODES:
            raise ValueError(f"Phím không hỗ trợ: {key!r}")
        return SCAN_CODES[key]

    def _key_event(self, key: str, up: bool) -> None:
        code = self._scan(key)
        if not IS_WINDOWS:
            return
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
        if code > 0xFF:
            flags |= KEYEVENTF_EXTENDEDKEY
            code &= 0xFF
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ki = KEYBDINPUT(0, code, flags, 0, 0)
        _send(inp)

    def key_down(self, key: str) -> None:
        with self._lock:
            self._key_event(key, up=False)
            self._held_keys.add(key.lower())

    def key_up(self, key: str) -> None:
        with self._lock:
            self._key_event(key, up=True)
            self._held_keys.discard(key.lower())

    def press(self, key: str, duration: float = 0.05) -> None:
        self.key_down(key)
        time.sleep(duration)
        self.key_up(key)

    # ------------------------------ Chuột ------------------------------ #
    def move_to(self, x: int, y: int) -> None:
        if IS_WINDOWS:
            user32.SetCursorPos(int(x), int(y))

    def move_rel(self, dx: int, dy: int) -> None:
        """Di chuyển tương đối - dùng để xoay camera trong Roblox."""
        if not IS_WINDOWS:
            return
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, 0)
        _send(inp)

    def mouse_down(self, button: str = "left") -> None:
        with self._lock:
            if IS_WINDOWS:
                inp = INPUT(type=INPUT_MOUSE)
                inp.mi = MOUSEINPUT(0, 0, 0, MOUSE_FLAGS[button][0], 0, 0)
                _send(inp)
            self._held_buttons.add(button)

    def mouse_up(self, button: str = "left") -> None:
        with self._lock:
            if IS_WINDOWS:
                inp = INPUT(type=INPUT_MOUSE)
                inp.mi = MOUSEINPUT(0, 0, 0, MOUSE_FLAGS[button][1], 0, 0)
                _send(inp)
            self._held_buttons.discard(button)

    def click(self, x: int | None = None, y: int | None = None,
              button: str = "left", hold: float = 0.05) -> None:
        if x is not None and y is not None:
            self.move_to(x, y)
            # Roblox cần một chuyển động nhỏ để "nhận" vị trí chuột mới
            self.move_rel(1, 0)
            self.move_rel(-1, 0)
            time.sleep(0.03)
        self.mouse_down(button)
        time.sleep(hold)
        self.mouse_up(button)

    def scroll(self, amount: int) -> None:
        if not IS_WINDOWS:
            return
        MOUSEEVENTF_WHEEL = 0x0800
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(0, 0, ctypes.c_ulong(int(amount) * 120).value, MOUSEEVENTF_WHEEL, 0, 0)
        _send(inp)

    # ------------------------------ An toàn ---------------------------- #
    def release_all(self) -> None:
        """Nhả mọi phím/chuột đang giữ. Gọi khi Pause, Stop hoặc gặp lỗi."""
        for key in list(self._held_keys):
            try:
                self.key_up(key)
            except Exception:  # pragma: no cover - chỉ phòng hờ
                pass
        for btn in list(self._held_buttons):
            try:
                self.mouse_up(btn)
            except Exception:  # pragma: no cover
                pass

    @property
    def held(self) -> Set[str]:
        return set(self._held_keys) | {f"mouse:{b}" for b in self._held_buttons}


# ======================================================================
# platform/hotkeys.py
# ======================================================================
"""Phím tắt toàn cục (hoạt động cả khi cửa sổ Roblox đang được focus).

Dùng ``RegisterHotKey`` của Windows: không cần quyền Administrator và không
cài keyboard hook (nhẹ hơn thư viện ``keyboard``).
"""


import ctypes
import logging
import threading
from typing import Callable, Dict


log = logging.getLogger(__name__)

WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_NOREPEAT = 0x4000


def vk_from_name(name: str) -> int:
    """'F6' -> 0x75, 'P' -> 0x50."""
    name = name.strip().upper()
    if name.startswith("F") and name[1:].isdigit():
        n = int(name[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    if len(name) == 1 and name.isalnum():
        return ord(name)
    raise ValueError(f"Phím tắt không hỗ trợ: {name}")


class HotkeyManager:
    def __init__(self) -> None:
        self._bindings: Dict[int, tuple[int, Callable[[], None]]] = {}
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()

    def start(self, mapping: Dict[str, Callable[[], None]]) -> None:
        if not IS_WINDOWS:
            log.info("Phím tắt toàn cục chỉ hỗ trợ trên Windows.")
            return
        self.stop()
        self._ready.clear()
        self._thread = threading.Thread(target=self._loop, args=(mapping,), daemon=True, name="hotkeys")
        self._thread.start()
        self._ready.wait(2.0)

    def _loop(self, mapping: Dict[str, Callable[[], None]]) -> None:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        self._thread_id = kernel32.GetCurrentThreadId()
        hk_id = 1
        for key, cb in mapping.items():
            try:
                vk = vk_from_name(key)
            except ValueError as exc:
                log.warning("%s", exc)
                continue
            if user32.RegisterHotKey(None, hk_id, MOD_NOREPEAT, vk):
                self._bindings[hk_id] = (vk, cb)
                log.info("Đã đăng ký phím tắt %s", key)
            else:
                log.warning("Không đăng ký được %s (đang bị chương trình khác dùng?)", key)
            hk_id += 1
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in self._bindings:
                try:
                    self._bindings[msg.wParam][1]()
                except Exception:
                    log.exception("Lỗi khi xử lý phím tắt")
        for hid in list(self._bindings):
            user32.UnregisterHotKey(None, hid)
        self._bindings.clear()

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._thread_id:
            ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(1.0)
        self._thread = None


# ======================================================================
# vision.py
# ======================================================================
"""Nhận diện hình ảnh trên màn hình (chỉ đọc pixel, không đọc bộ nhớ game).

Tối ưu CPU/RAM:
    * Chỉ chụp vùng client của cửa sổ Roblox (hoặc một vùng con), không chụp
      toàn màn hình.
    * So khớp trên ảnh xám (1 kênh thay vì 3) khi ``grayscale=True``.
    * Template được đọc một lần, scale theo độ rộng cửa sổ hiện tại rồi cache.
    * Mỗi luồng giữ một đối tượng ``mss`` riêng (mss không thread-safe) và tái
      sử dụng, tránh tạo/hủy liên tục.
"""


import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np


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


# ======================================================================
# ocr.py
# ======================================================================
"""Đọc số EXP / vàng trên màn hình thưởng bằng Tesseract OCR (tùy chọn).

Nếu không cài Tesseract, chương trình vẫn chạy bình thường và dùng giá trị
``fallback_*_per_run`` trong cấu hình.
"""


import logging
import re
from typing import Dict, Optional

import numpy as np


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


# ======================================================================
# macro.py
# ======================================================================
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


import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


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


# ======================================================================
# notifier.py
# ======================================================================
"""Thông báo lỗi / sự kiện: âm thanh, thông báo Windows, Discord webhook.

Tất cả đều chạy ở luồng nền và nuốt lỗi -> việc gửi thông báo thất bại không
bao giờ làm dừng quá trình farm.
"""


import json
import logging
import sys
import threading
import time
import urllib.request
from typing import Callable, List, Optional


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


# ======================================================================
# resources.py
# ======================================================================
"""Theo dõi CPU / RAM của chính chương trình (và của Roblox nếu tìm thấy)."""


from typing import Dict, Optional

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None


class ResourceMonitor:
    def __init__(self) -> None:
        self._proc = psutil.Process() if psutil else None
        self._roblox: Optional["psutil.Process"] = None
        if self._proc:
            self._proc.cpu_percent(None)  # lần gọi đầu luôn trả 0 -> "mồi" trước

    def _find_roblox(self):
        if not psutil:
            return None
        if self._roblox is not None and self._roblox.is_running():
            return self._roblox
        self._roblox = None
        for p in psutil.process_iter(["name"]):
            if (p.info.get("name") or "").lower() == "robloxplayerbeta.exe":
                self._roblox = p
                p.cpu_percent(None)
                break
        return self._roblox

    def sample(self) -> Dict[str, float]:
        """Trả về % CPU (chia theo số nhân) và RAM (MB)."""
        if not self._proc:
            return {}
        cores = psutil.cpu_count() or 1
        out = {
            "cpu": self._proc.cpu_percent(None) / cores,
            "ram_mb": self._proc.memory_info().rss / 1024 / 1024,
        }
        try:
            rb = self._find_roblox()
            if rb:
                out["roblox_cpu"] = rb.cpu_percent(None) / cores
                out["roblox_ram_mb"] = rb.memory_info().rss / 1024 / 1024
        except Exception:  # NoSuchProcess / AccessDenied
            self._roblox = None
        return out


# ======================================================================
# engine.py
# ======================================================================
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


import enum
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional


log = logging.getLogger(__name__)


class State(str, enum.Enum):
    IDLE = "Chờ lệnh"
    STARTING = "Khởi động"
    SELECT_SLOT = "Chọn slot"
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
            if state == "slot_select":
                raise FarmError("Bị đưa về màn hình chọn slot giữa nhiệm vụ")
            if state is not None:
                self._last_known_state_at = now
            elif now - self._last_known_state_at > self.cfg.timing.stuck_timeout:
                raise FarmError(f"Kẹt: không nhận diện được màn hình trong "
                                f"{self.cfg.timing.stuck_timeout:.0f}s")
            if now > mission_deadline:
                raise FarmError(f"Nhiệm vụ quá {self.cfg.timing.mission_timeout:.0f}s")

    def _enter_mission(self) -> None:
        """(Chọn slot nếu cần) -> ở sảnh chờ nút Play -> chạy macro vào nhiệm vụ."""
        self._set_state(State.LOBBY)
        state = self._detect_state()
        if state == "slot_select":
            self._select_slot()
            state = self._detect_state()
        if self._state_template("lobby"):
            deadline = time.monotonic() + self.cfg.timing.lobby_wait_timeout
            while state != "lobby":
                if state == "in_mission":
                    return
                if state == "slot_select":
                    self._select_slot()
                if time.monotonic() > deadline:
                    raise FarmError("Không thấy màn hình sảnh")
                self.sleep(self.cfg.timing.detection_interval)
                state = self._detect_state()
        if self.macros.exists(self.cfg.macro_start):
            self.run_macro(self.cfg.macro_start)
        # Chờ vào trận (nếu có template HUD nhiệm vụ)
        if self._state_template("in_mission"):
            deadline = time.monotonic() + self.cfg.timing.lobby_wait_timeout
            while self._detect_state() != "in_mission":
                if time.monotonic() > deadline:
                    raise FarmError("Không vào được nhiệm vụ (hết thời gian chờ tải)")
                self.sleep(self.cfg.timing.detection_interval)

    def _select_slot(self) -> None:
        """Màn hình chọn nhân vật: bấm SELECT ở Slot A (macro ``select_slot``)."""
        self._set_state(State.SELECT_SLOT)
        if not self.macros.exists(self.cfg.macro_select_slot):
            raise FarmError(f"Đang ở màn hình chọn slot nhưng thiếu macro '{self.cfg.macro_select_slot}'")
        log.info("Chọn slot nhân vật")
        self.run_macro(self.cfg.macro_select_slot)
        self._set_state(State.LOBBY)

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


# ======================================================================
# services.py
# ======================================================================
"""Khởi tạo và nối các thành phần (composition root).

GUI chỉ làm việc với đối tượng ``Services`` -> dễ thay thế từng phần khi test.
"""


from dataclasses import dataclass



@dataclass
class Services:
    cfg: AppConfig
    window: GameWindow
    input: InputController
    vision: Vision
    macros: MacroLibrary
    reader: RewardReader
    notifier: Notifier
    stats: SessionStats
    engine: FarmEngine

    def rebuild_engine(self) -> None:
        """Áp dụng cấu hình mới (chỉ gọi khi engine KHÔNG chạy)."""
        old_handler = self.engine.on_event
        self.window.title = self.cfg.window_title
        m = self.vision.matcher
        m.threshold = self.cfg.detection.match_threshold
        m.reference_width = self.cfg.detection.reference_width
        if m.grayscale != self.cfg.detection.grayscale:
            m.grayscale = self.cfg.detection.grayscale
        m.clear_cache()
        self.notifier.cfg = self.cfg.notify
        self.reader = RewardReader(self.cfg.ocr)
        self.engine = FarmEngine(self.cfg, self.window, self.vision, self.input, self.macros,
                                 self.reader, self.notifier, self.stats)
        self.engine.on_event = old_handler


def build_services(cfg: AppConfig) -> Services:
    window = GameWindow(cfg.window_title)
    input_ctl = InputController()
    matcher = TemplateMatcher(TEMPLATE_DIR, cfg.detection.match_threshold,
                              cfg.detection.reference_width, cfg.detection.grayscale)
    vision = Vision(matcher)
    macros = MacroLibrary(MACRO_DIR)
    reader = RewardReader(cfg.ocr)
    notifier = Notifier(cfg.notify, APP_NAME)
    stats = SessionStats(DATA_DIR)
    engine = FarmEngine(cfg, window, vision, input_ctl, macros, reader, notifier, stats)
    return Services(cfg, window, input_ctl, vision, macros, reader, notifier, stats, engine)


# ======================================================================
# gui/region_picker.py
# ======================================================================
"""Hộp thoại chọn vùng: hiển thị ảnh chụp cửa sổ game, người dùng kéo chuột
để khoanh vùng. Trả về tọa độ tương đối (0..1) so với ảnh gốc.

Dùng cho:
    * Chụp template (nút Play, Retry, màn hình thưởng...).
    * Chọn vùng OCR đọc EXP / vàng.
"""


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


# ======================================================================
# gui/app.py
# ======================================================================
"""Cửa sổ chính của AOTR Farm Assistant.

Nguyên tắc luồng:
    * tkinter KHÔNG thread-safe -> engine, phím tắt, notifier chỉ đẩy sự kiện
      vào ``self.ui_queue``; GUI rút hàng đợi bằng ``after()`` mỗi 200 ms.
    * Bảng số liệu cập nhật mỗi 1 s (đủ mượt, rất ít CPU).
"""


import logging
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from dataclasses import fields
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Dict, List, Tuple


log = logging.getLogger(__name__)

STATE_COLORS = {
    State.IDLE: "#7f8c8d", State.STARTING: "#2980b9", State.SELECT_SLOT: "#2980b9",
    State.LOBBY: "#2980b9",
    State.IN_MISSION: "#27ae60", State.REWARD: "#8e44ad", State.RECOVERING: "#e67e22",
    State.BREAK: "#16a085", State.PAUSED: "#f39c12", State.STOPPING: "#7f8c8d",
    State.STOPPED: "#7f8c8d", State.ERROR: "#c0392b",
}
MAX_LOG_LINES = 1000

# Nhãn tiếng Việt cho các trường cấu hình (tab Cài đặt)
LABELS: Dict[str, str] = {
    "window_title": "Tiêu đề cửa sổ game",
    "focus_window": "Tự focus cửa sổ Roblox",
    "macro_start": "Macro vào nhiệm vụ",
    "macro_mission": "Macro trong nhiệm vụ",
    "macro_reward": "Macro màn hình thưởng",
    "macro_recover": "Macro khôi phục",
    "macro_select_slot": "Macro chọn slot (Slot A)",
    "max_consecutive_errors": "Số lỗi liên tiếp tối đa",
    "hotkey_toggle": "Phím Start/Stop",
    "hotkey_pause": "Phím Pause/Resume",
    "hotkey_emergency": "Phím dừng khẩn cấp",
    "log_level": "Mức log (DEBUG/INFO/WARNING)",
    "detection_interval": "Chu kỳ quét màn hình (s)",
    "mission_timeout": "Thời gian tối đa 1 lượt (s)",
    "stuck_timeout": "Báo kẹt sau (s)",
    "lobby_wait_timeout": "Chờ sảnh/tải tối đa (s)",
    "delay_between_runs": "Nghỉ giữa các lượt (s)",
    "max_runs": "Số lượt tối đa (0 = vô hạn)",
    "max_duration_minutes": "Thời gian chạy tối đa (phút, 0 = vô hạn)",
    "stop_at_clock": "Dừng lúc (HH:MM, trống = tắt)",
    "break_every_minutes": "Nghỉ giải lao sau mỗi (phút)",
    "break_length_minutes": "Thời gian nghỉ (phút)",
    "action_jitter": "Dao động ngẫu nhiên (0..0.5)",
    "match_threshold": "Ngưỡng khớp ảnh (0..1)",
    "reference_width": "Độ rộng cửa sổ khi chụp template",
    "grayscale": "So khớp ảnh xám (nhanh hơn)",
    "enabled": "Bật OCR (cần Tesseract)",
    "tesseract_path": "Đường dẫn tesseract.exe",
    "fallback_exp_per_run": "EXP mặc định/lượt (khi tắt OCR)",
    "fallback_gold_per_run": "Vàng mặc định/lượt (khi tắt OCR)",
    "detect_items": "Đếm icon vật phẩm (templates/items)",
    "sound": "Phát âm thanh",
    "desktop_toast": "Thông báo Windows",
    "discord_webhook": "Discord webhook URL",
}
SECTION_TITLES = {"": "Chung", "timing": "Thời gian chạy", "detection": "Nhận diện",
                  "ocr": "Phần thưởng / OCR", "notify": "Thông báo"}


def open_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


class FarmApp:
    def __init__(self, services: Services) -> None:
        self.s = services
        self.ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.monitor = ResourceMonitor()
        self.hotkeys = HotkeyManager()

        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{__version__}")
        self.root.geometry("860x620")
        self.root.minsize(760, 540)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._style()

        self._wire_events()
        self._build()
        self._register_hotkeys()
        self.root.after(200, self._poll_queues)
        self.root.after(1000, self._refresh_stats)

    # ================================================================== #
    # Khởi tạo
    # ================================================================== #
    def _style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=8)
        style.configure("Value.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("State.TLabel", font=("Segoe UI", 16, "bold"))

    def _wire_events(self) -> None:
        # Callback chạy trên luồng khác -> chỉ đẩy vào hàng đợi
        self.s.engine.on_event = lambda kind, data: self.ui_queue.put((kind, data))
        self.s.notifier.listeners.append(
            lambda level, title, msg: self.ui_queue.put(("notify", (level, title, msg))))

    def _register_hotkeys(self) -> None:
        c = self.s.cfg
        self.hotkeys.start({
            c.hotkey_toggle: lambda: self.ui_queue.put(("hotkey", "toggle")),
            c.hotkey_pause: lambda: self.ui_queue.put(("hotkey", "pause")),
            c.hotkey_emergency: lambda: self.ui_queue.put(("hotkey", "emergency")),
        })

    def _build(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self.tab_control = ttk.Frame(nb, padding=10)
        self.tab_stats = ttk.Frame(nb, padding=10)
        self.tab_log = ttk.Frame(nb, padding=10)
        self.tab_settings = ttk.Frame(nb, padding=10)
        self.tab_tools = ttk.Frame(nb, padding=10)
        nb.add(self.tab_control, text="  Điều khiển  ")
        nb.add(self.tab_stats, text="  Thống kê  ")
        nb.add(self.tab_log, text="  Nhật ký  ")
        nb.add(self.tab_settings, text="  Cài đặt  ")
        nb.add(self.tab_tools, text="  Công cụ  ")
        self._build_control()
        self._build_stats()
        self._build_log()
        self._build_settings()
        self._build_tools()

        bar = ttk.Frame(self.root, padding=(8, 4))
        bar.pack(fill="x")
        self.res_label = ttk.Label(bar, text="CPU: -  RAM: -")
        self.res_label.pack(side="left")
        c = self.s.cfg
        ttk.Label(bar, text=f"{c.hotkey_toggle}: Start/Stop   {c.hotkey_pause}: Pause/Resume   "
                            f"{c.hotkey_emergency}: Dừng khẩn cấp").pack(side="right")

    # ------------------------------------------------------------------ #
    # Tab Điều khiển
    # ------------------------------------------------------------------ #
    def _build_control(self) -> None:
        f = self.tab_control
        top = ttk.Frame(f)
        top.pack(fill="x")
        self.state_label = ttk.Label(top, text=State.IDLE.value, style="State.TLabel",
                                     foreground=STATE_COLORS[State.IDLE])
        self.state_label.pack(side="left")
        self.window_label = ttk.Label(top, text="")
        self.window_label.pack(side="right")

        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=12)
        self.btn_start = ttk.Button(btns, text="▶  Start", style="Big.TButton", command=self.toggle_start)
        self.btn_start.pack(side="left", expand=True, fill="x", padx=4)
        self.btn_pause = ttk.Button(btns, text="⏸  Pause", style="Big.TButton",
                                    command=self.toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", expand=True, fill="x", padx=4)

        grid = ttk.LabelFrame(f, text="Phiên hiện tại", padding=10)
        grid.pack(fill="x")
        self.values: Dict[str, ttk.Label] = {}
        items = [
            ("elapsed", "Thời gian farm"), ("time_left", "Còn lại"),
            ("current_run_time", "Lượt hiện tại"), ("avg_run_time", "TB mỗi lượt"),
            ("runs", "Lượt (thành công/lỗi)"), ("runs_per_hour", "Lượt / giờ"),
            ("total_exp", "Tổng EXP"), ("exp_per_hour", "EXP / giờ"),
            ("total_gold", "Tổng vàng"), ("gold_per_hour", "Vàng / giờ"),
            ("errors", "Số lỗi"), ("success_rate", "Tỉ lệ thành công"),
        ]
        for i, (key, label) in enumerate(items):
            r, c = divmod(i, 2)
            ttk.Label(grid, text=label + ":").grid(row=r, column=c * 2, sticky="w", padx=(0, 8), pady=3)
            v = ttk.Label(grid, text="-", style="Value.TLabel")
            v.grid(row=r, column=c * 2 + 1, sticky="w", padx=(0, 40), pady=3)
            self.values[key] = v

        quick = ttk.LabelFrame(f, text="Thời gian chạy nhanh (áp dụng cho lần Start tiếp theo)", padding=10)
        quick.pack(fill="x", pady=10)
        t = self.s.cfg.timing
        self.q_runs = tk.StringVar(value=str(t.max_runs))
        self.q_minutes = tk.StringVar(value=f"{t.max_duration_minutes:g}")
        self.q_clock = tk.StringVar(value=t.stop_at_clock)
        for i, (label, var) in enumerate([("Số lượt tối đa (0=∞)", self.q_runs),
                                          ("Số phút tối đa (0=∞)", self.q_minutes),
                                          ("Dừng lúc (HH:MM)", self.q_clock)]):
            ttk.Label(quick, text=label).grid(row=0, column=i * 2, sticky="w", padx=(0, 4))
            ttk.Entry(quick, textvariable=var, width=8).grid(row=0, column=i * 2 + 1, padx=(0, 16))

        self.last_msg = ttk.Label(f, text="", foreground="#c0392b", wraplength=780)
        self.last_msg.pack(fill="x", pady=4)

    def _apply_quick_settings(self) -> bool:
        t = self.s.cfg.timing
        try:
            t.max_runs = int(self.q_runs.get() or 0)
            t.max_duration_minutes = float(self.q_minutes.get() or 0)
        except ValueError:
            messagebox.showerror(APP_NAME, "Số lượt / số phút phải là số.")
            return False
        clock = self.q_clock.get().strip()
        if clock:
            try:
                hh, mm = (int(x) for x in clock.split(":"))
                assert 0 <= hh < 24 and 0 <= mm < 60
            except (ValueError, AssertionError):
                messagebox.showerror(APP_NAME, "Giờ dừng phải có dạng HH:MM, ví dụ 23:30")
                return False
        t.stop_at_clock = clock
        save_config(self.s.cfg)
        return True

    # ------------------------------------------------------------------ #
    # Tab Thống kê
    # ------------------------------------------------------------------ #
    def _build_stats(self) -> None:
        f = self.tab_stats
        cols = ("index", "time", "duration", "result", "exp", "gold", "items")
        heads = ("#", "Bắt đầu", "Thời gian", "Kết quả", "EXP", "Vàng", "Vật phẩm / ghi chú")
        widths = (40, 80, 80, 80, 80, 80, 300)
        tv_frame = ttk.Frame(f)
        tv_frame.pack(fill="both", expand=True)
        self.runs_tree = ttk.Treeview(tv_frame, columns=cols, show="headings", height=12)
        for c, h, w in zip(cols, heads, widths):
            self.runs_tree.heading(c, text=h)
            self.runs_tree.column(c, width=w, anchor="w" if c == "items" else "center")
        sb = ttk.Scrollbar(tv_frame, orient="vertical", command=self.runs_tree.yview)
        self.runs_tree.configure(yscrollcommand=sb.set)
        self.runs_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.runs_tree.tag_configure("fail", foreground="#c0392b")

        bottom = ttk.Frame(f)
        bottom.pack(fill="x", pady=(8, 0))
        items_box = ttk.LabelFrame(bottom, text="Vật phẩm thu được", padding=6)
        items_box.pack(side="left", fill="both", expand=True)
        self.items_tree = ttk.Treeview(items_box, columns=("name", "count"), show="headings", height=5)
        self.items_tree.heading("name", text="Vật phẩm")
        self.items_tree.heading("count", text="Số lượng")
        self.items_tree.column("count", width=80, anchor="center")
        self.items_tree.pack(fill="both", expand=True)

        actions = ttk.Frame(bottom, padding=(10, 0))
        actions.pack(side="right", fill="y")
        ttk.Button(actions, text="Mở thư mục dữ liệu (CSV/JSON)",
                   command=lambda: open_path(DATA_DIR)).pack(fill="x", pady=2)
        ttk.Button(actions, text="Lưu tóm tắt phiên ngay", command=self._save_summary).pack(fill="x", pady=2)

    def _save_summary(self) -> None:
        path = self.s.stats.save_summary()
        messagebox.showinfo(APP_NAME, f"Đã lưu: {path}" if path else "Chưa có phiên nào.")

    def _add_run_row(self, rec) -> None:
        detail = ", ".join(f"{k} x{v}" for k, v in rec.items.items()) or rec.note
        self.runs_tree.insert("", 0, values=(
            rec.index, time.strftime("%H:%M:%S", time.localtime(rec.started_at)),
            fmt_duration(rec.duration), "Thành công" if rec.success else "Lỗi",
            f"{rec.exp:,}", f"{rec.gold:,}", detail), tags=() if rec.success else ("fail",))
        children = self.runs_tree.get_children()
        for iid in children[300:]:      # giới hạn số dòng hiển thị -> tiết kiệm RAM
            self.runs_tree.delete(iid)

    # ------------------------------------------------------------------ #
    # Tab Nhật ký
    # ------------------------------------------------------------------ #
    def _build_log(self) -> None:
        f = self.tab_log
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Hiển thị từ mức:").pack(side="left")
        self.log_filter = tk.StringVar(value="INFO")
        cb = ttk.Combobox(bar, textvariable=self.log_filter, width=10, state="readonly",
                          values=["DEBUG", "INFO", "WARNING", "ERROR"])
        cb.pack(side="left", padx=6)
        ttk.Button(bar, text="Xóa màn hình", command=lambda: self.log_text.delete("1.0", "end")).pack(side="left")
        ttk.Button(bar, text="Mở thư mục log", command=lambda: open_path(LOG_DIR)).pack(side="right")
        self.log_text = scrolledtext.ScrolledText(f, height=20, font=("Consolas", 9), wrap="word")
        self.log_text.pack(fill="both", expand=True)
        for level, color in (("DEBUG", "#7f8c8d"), ("INFO", "#000000"),
                             ("WARNING", "#d35400"), ("ERROR", "#c0392b"), ("CRITICAL", "#c0392b")):
            self.log_text.tag_configure(level, foreground=color)
        self._log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    def _append_log(self, record: logging.LogRecord) -> None:
        if record.levelno < getattr(logging, self.log_filter.get(), logging.INFO):
            return
        at_bottom = self.log_text.yview()[1] > 0.98
        self.log_text.insert("end", self._log_fmt.format(record) + "\n", record.levelname)
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > MAX_LOG_LINES:
            self.log_text.delete("1.0", f"{lines - MAX_LOG_LINES}.0")
        if at_bottom:
            self.log_text.see("end")

    # ------------------------------------------------------------------ #
    # Tab Cài đặt (tự sinh form từ dataclass cấu hình)
    # ------------------------------------------------------------------ #
    def _build_settings(self) -> None:
        f = self.tab_settings
        canvas = tk.Canvas(f, highlightthickness=0)
        sb = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
        bar = ttk.Frame(f)
        bar.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bar, text="Lưu cài đặt", command=self._save_settings).pack(side="right")
        ttk.Label(bar, text="Một số thay đổi (phím tắt) cần khởi động lại chương trình.").pack(side="left")
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.setting_vars: List[Tuple[Any, str, tk.Variable]] = []
        row = 0

        def add_section(obj, prefix: str) -> None:
            nonlocal row
            ttk.Label(inner, text=SECTION_TITLES.get(prefix, prefix), font=("Segoe UI", 10, "bold")).grid(
                row=row, column=0, sticky="w", pady=(10, 2))
            row += 1
            for fld in fields(obj):
                value = getattr(obj, fld.name)
                if hasattr(value, "__dataclass_fields__") or isinstance(value, dict):
                    continue  # mục con xử lý riêng; dict chỉnh trong tab Công cụ / file JSON
                label = LABELS.get(fld.name, fld.name)
                ttk.Label(inner, text=label).grid(row=row, column=0, sticky="w", padx=(12, 8), pady=2)
                if isinstance(value, bool):
                    var: tk.Variable = tk.BooleanVar(value=value)
                    ttk.Checkbutton(inner, variable=var).grid(row=row, column=1, sticky="w")
                elif fld.name.startswith("macro_"):
                    var = tk.StringVar(value=str(value))
                    ttk.Combobox(inner, textvariable=var, values=self.s.macros.names(), width=36).grid(
                        row=row, column=1, sticky="w")
                else:
                    var = tk.StringVar(value=str(value))
                    ttk.Entry(inner, textvariable=var, width=40).grid(row=row, column=1, sticky="w")
                self.setting_vars.append((obj, fld.name, var))
                row += 1

        cfg = self.s.cfg
        add_section(cfg, "")
        for name in ("timing", "detection", "ocr", "notify"):
            add_section(getattr(cfg, name), name)

    def _save_settings(self) -> None:
        if self.s.engine.running:
            messagebox.showwarning(APP_NAME, "Hãy Stop trước khi đổi cài đặt.")
            return
        errors = []
        for obj, name, var in self.setting_vars:
            old = getattr(obj, name)
            raw = var.get()
            try:
                if isinstance(old, bool):
                    new = bool(raw)
                elif isinstance(old, int):
                    new = int(float(raw))
                elif isinstance(old, float):
                    new = float(raw)
                else:
                    new = str(raw).strip()
                setattr(obj, name, new)
            except ValueError:
                errors.append(LABELS.get(name, name))
        if errors:
            messagebox.showerror(APP_NAME, "Giá trị không hợp lệ:\n- " + "\n- ".join(errors))
            return
        save_config(self.s.cfg)
        set_level(self.s.cfg.log_level)
        self.s.rebuild_engine()
        self._sync_quick_fields()
        log.info("Đã lưu cài đặt")
        messagebox.showinfo(APP_NAME, "Đã lưu cài đặt.")

    def _sync_quick_fields(self) -> None:
        t = self.s.cfg.timing
        self.q_runs.set(str(t.max_runs))
        self.q_minutes.set(f"{t.max_duration_minutes:g}")
        self.q_clock.set(t.stop_at_clock)

    # ------------------------------------------------------------------ #
    # Tab Công cụ
    # ------------------------------------------------------------------ #
    def _build_tools(self) -> None:
        f = self.tab_tools
        tpl = ttk.LabelFrame(f, text="1. Chụp template nhận diện (nút / màn hình)", padding=8)
        tpl.pack(fill="x")
        ttk.Label(tpl, text="Tên template:").grid(row=0, column=0, sticky="w")
        names = sorted(set(self.s.cfg.detection.state_templates.values()) |
                       {"slot_a_card", "join_community_button", "lobby_card", "mission_play_button", "missions_card",
                        "retry_button", "continue_button", "reconnect_button", "close_button"})
        self.tpl_name = tk.StringVar(value=names[0])
        ttk.Combobox(tpl, textvariable=self.tpl_name, values=names, width=28).grid(row=0, column=1, padx=6)
        ttk.Button(tpl, text="Chụp & khoanh vùng", command=self._capture_template).grid(row=0, column=2)
        ttk.Button(tpl, text="Mở thư mục templates",
                   command=lambda: open_path(TEMPLATE_DIR)).grid(row=0, column=3, padx=6)
        ttk.Label(tpl, text="Gợi ý: để 'items/<tên>' để lưu icon vật phẩm. Luôn chụp ở cùng kích thước cửa sổ.",
                  foreground="#555").grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        ocr = ttk.LabelFrame(f, text="2. Vùng OCR đọc phần thưởng", padding=8)
        ocr.pack(fill="x", pady=8)
        self.ocr_name = tk.StringVar(value="exp")
        ttk.Combobox(ocr, textvariable=self.ocr_name, values=["exp", "gold"], width=10).pack(side="left")
        ttk.Button(ocr, text="Khoanh vùng OCR", command=self._pick_ocr_region).pack(side="left", padx=6)
        ttk.Button(ocr, text="Thử đọc OCR", command=self._test_ocr).pack(side="left")

        test = ttk.LabelFrame(f, text="3. Kiểm tra", padding=8)
        test.pack(fill="x")
        ttk.Button(test, text="Tìm cửa sổ Roblox", command=self._test_window).pack(side="left")
        ttk.Button(test, text="Thử nhận diện trạng thái", command=self._test_detect).pack(side="left", padx=6)
        ttk.Button(test, text="Thử thông báo", command=lambda: send_test(self.s.notifier)).pack(side="left")
        ttk.Button(test, text="Mở thư mục macro", command=lambda: open_path(MACRO_DIR)).pack(side="left", padx=6)

        self.tools_out = scrolledtext.ScrolledText(f, height=12, font=("Consolas", 9))
        self.tools_out.pack(fill="both", expand=True, pady=(8, 0))
        self._tools_print(self._template_status())

    def _tools_print(self, text: str) -> None:
        self.tools_out.insert("end", text + "\n")
        self.tools_out.see("end")

    def _template_status(self) -> str:
        lines = ["Trạng thái template nhận diện:"]
        for key, name in self.s.cfg.detection.state_templates.items():
            ok = self.s.vision.matcher.exists(name)
            lines.append(f"  [{'OK' if ok else '--'}] {key:<13} -> templates/{name}.png")
        lines.append("Macro có sẵn: " + ", ".join(self.s.macros.names()))
        return "\n".join(lines)

    def _grab_game(self):
        if self.s.engine.running and not self.s.engine.paused:
            messagebox.showwarning(APP_NAME, "Hãy Pause hoặc Stop trước khi dùng công cụ.")
            return None, None
        rect = self.s.window.client_rect()
        if rect is None:
            messagebox.showerror(APP_NAME, f"Không tìm thấy cửa sổ '{self.s.cfg.window_title}'.")
            return None, None
        try:
            return self.s.vision.grab(rect), rect
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Không chụp được màn hình: {exc}")
            return None, None

    def _capture_template(self) -> None:
        name = self.tpl_name.get().strip().replace("\\", "/")
        if not name:
            return
        self.root.iconify()        # thu nhỏ để không che game khi chụp
        self.root.after(400, lambda: self._capture_template_step2(name))

    def _capture_template_step2(self, name: str) -> None:
        frame, rect = self._grab_game()
        self.root.deiconify()
        if frame is None:
            return
        region = pick_region(self.root, frame, f"Khoanh vùng cho template '{name}'")
        if not region:
            return
        pass
        path = TEMPLATE_DIR / f"{name}.png"
        save_png(crop_relative(frame, region), path)
        det = self.s.cfg.detection
        if det.reference_width != rect.width:
            det.reference_width = rect.width
            save_config(self.s.cfg)
            self._tools_print(f"Đã đặt độ rộng tham chiếu = {rect.width}px (kích thước cửa sổ hiện tại).")
        self.s.vision.matcher.clear_cache()
        self._tools_print(f"Đã lưu template: {path}")
        self._tools_print(self._template_status())

    def _pick_ocr_region(self) -> None:
        self.root.iconify()
        self.root.after(400, self._pick_ocr_step2)

    def _pick_ocr_step2(self) -> None:
        frame, _rect = self._grab_game()
        self.root.deiconify()
        if frame is None:
            return
        key = self.ocr_name.get().strip() or "exp"
        region = pick_region(self.root, frame, f"Khoanh vùng số {key.upper()} trên màn hình thưởng")
        if region:
            self.s.cfg.ocr.regions[key] = [round(v, 4) for v in region]
            save_config(self.s.cfg)
            self._tools_print(f"Vùng OCR '{key}' = {self.s.cfg.ocr.regions[key]}")

    def _test_ocr(self) -> None:
        frame, rect = self._grab_game()
        if frame is None:
            return
        pass
        reader = RewardReader(self.s.cfg.ocr)
        if not reader.available:
            self._tools_print("OCR chưa sẵn sàng: bật OCR trong Cài đặt và cài Tesseract (xem README).")
            return
        self._tools_print(f"Kết quả OCR: {reader.read_rewards(frame, rect)}")

    def _test_window(self) -> None:
        rect = self.s.window.client_rect()
        if rect:
            self._tools_print(f"Tìm thấy cửa sổ: vị trí ({rect.left},{rect.top}), kích thước {rect.width}x{rect.height}")
        else:
            self._tools_print(f"KHÔNG tìm thấy cửa sổ có tiêu đề '{self.s.cfg.window_title}'.")

    def _test_detect(self) -> None:
        frame, rect = self._grab_game()
        if frame is None:
            return
        m = self.s.vision.matcher
        prepared = m.prepare(frame)
        self._tools_print("Điểm khớp (ngưỡng hiện tại = %.2f):" % m.threshold)
        for key, name in self.s.cfg.detection.state_templates.items():
            if not m.exists(name):
                self._tools_print(f"  {key:<13} : chưa có template")
                continue
            hit = m.find(prepared, name, rect, threshold=0.0)
            score = hit.score if hit else 0.0
            self._tools_print(f"  {key:<13} : {score:.3f} {'<- KHỚP' if score >= m.threshold else ''}")

    # ================================================================== #
    # Điều khiển
    # ================================================================== #
    def toggle_start(self) -> None:
        if self.s.engine.running:
            self.s.engine.stop()
            return
        if not self._apply_quick_settings():
            return
        self.runs_tree.delete(*self.runs_tree.get_children())
        self.last_msg.config(text="")
        self.s.engine.start()
        self.btn_start.config(text="■  Stop")
        self.btn_pause.config(state="normal", text="⏸  Pause")

    def toggle_pause(self) -> None:
        e = self.s.engine
        if not e.running:
            return
        if e.paused:
            e.resume()
            self.btn_pause.config(text="⏸  Pause")
        else:
            e.pause()
            self.btn_pause.config(text="▶  Resume")

    def emergency_stop(self) -> None:
        self.s.input.release_all()
        if self.s.engine.running:
            self.s.engine.stop("Dừng khẩn cấp")
        log.warning("DỪNG KHẨN CẤP")

    # ================================================================== #
    # Vòng cập nhật GUI
    # ================================================================== #
    def _poll_queues(self) -> None:
        # Log: tối đa 200 bản ghi mỗi lần để GUI không bị khựng
        for _ in range(200):
            try:
                self._append_log(log_queue.get_nowait())
            except queue.Empty:
                break
        while True:
            try:
                kind, data = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(kind, data)
        self.root.after(200, self._poll_queues)

    def _handle_event(self, kind: str, data: Any) -> None:
        if kind == "state":
            st: State = data["state"]
            self.state_label.config(text=st.value, foreground=STATE_COLORS.get(st, "#000"))
        elif kind == "run_finished":
            self._add_run_row(data["record"])
        elif kind == "error":
            self.last_msg.config(text=f"⚠ {data['message']}")
        elif kind == "session_stopped":
            self.btn_start.config(text="▶  Start")
            self.btn_pause.config(state="disabled", text="⏸  Pause")
            self.last_msg.config(text=f"Kết thúc: {data['reason']}")
            self._refresh_stats(reschedule=False)
        elif kind == "notify":
            level, title, msg = data
            if level == ERROR:
                self.last_msg.config(text=f"⚠ {title}: {msg}")
        elif kind == "hotkey":
            {"toggle": self.toggle_start, "pause": self.toggle_pause,
             "emergency": self.emergency_stop}[data]()

    def _refresh_stats(self, reschedule: bool = True) -> None:
        snap = self.s.stats.snapshot()
        v = self.values
        v["elapsed"].config(text=fmt_duration(snap["elapsed"]))
        left = self.s.engine.time_left() if self.s.engine.running else None
        v["time_left"].config(text=fmt_duration(left) if left is not None else "∞")
        v["current_run_time"].config(text=fmt_duration(snap["current_run_time"]))
        v["avg_run_time"].config(text=fmt_duration(snap["avg_run_time"]))
        v["runs"].config(text=f"{snap['success_runs']} / {snap['failed_runs']}")
        v["runs_per_hour"].config(text=f"{snap['runs_per_hour']:.1f}")
        v["total_exp"].config(text=f"{snap['total_exp']:,}")
        v["exp_per_hour"].config(text=f"{snap['exp_per_hour']:,.0f}")
        v["total_gold"].config(text=f"{snap['total_gold']:,}")
        v["gold_per_hour"].config(text=f"{snap['gold_per_hour']:,.0f}")
        v["errors"].config(text=str(snap["errors"]))
        v["success_rate"].config(text=f"{snap['success_rate']:.0f}%")

        # Bảng vật phẩm
        self.items_tree.delete(*self.items_tree.get_children())
        for name, count in sorted(snap["items"].items(), key=lambda kv: -kv[1]):
            self.items_tree.insert("", "end", values=(name, count))

        # Tài nguyên
        res = self.monitor.sample()
        if res:
            txt = f"Tool: CPU {res['cpu']:.1f}%  RAM {res['ram_mb']:.0f} MB"
            if "roblox_cpu" in res:
                txt += f"   |   Roblox: CPU {res['roblox_cpu']:.0f}%  RAM {res['roblox_ram_mb']:.0f} MB"
            self.res_label.config(text=txt)
        found = self.s.window.is_valid() or self.s.window.find()
        self.window_label.config(text="Roblox: đã kết nối" if found else "Roblox: chưa thấy cửa sổ",
                                 foreground="#27ae60" if found else "#c0392b")
        if reschedule:
            self.root.after(1000, self._refresh_stats)

    def _on_close(self) -> None:
        if self.s.engine.running:
            if not messagebox.askyesno(APP_NAME, "Đang farm. Dừng và thoát?"):
                return
            self.s.engine.stop("Thoát chương trình")
            self.s.engine.join(5)
        self.s.input.release_all()
        self.hotkeys.stop()
        self.root.destroy()

    def run(self) -> None:
        log.info("%s v%s sẵn sàng", APP_NAME, __version__)
        self.root.mainloop()


# ======================================================================
# __main__.py
# ======================================================================
"""Điểm khởi chạy.

    python -m aotr_farm            # mở giao diện
    python -m aotr_farm --check    # kiểm tra thư viện, Tesseract, cửa sổ Roblox
"""


import argparse
import importlib
import logging
import sys


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
    pass
    if cfg.ocr.enabled:
        print(f"Tesseract   : {'OK' if RewardReader(cfg.ocr).available else 'KHÔNG tìm thấy'}")

    pass
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
    write_default_macros()
    if args.check:
        return 1 if check_environment() else 0

    cfg = load_config()
    setup_logging(cfg.log_level)

    pass
    pass

    try:
        app = FarmApp(build_services(cfg))
    except Exception:
        log.exception("Không khởi tạo được giao diện")
        return 1
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
