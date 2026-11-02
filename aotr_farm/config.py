"""Quản lý cấu hình (đọc / ghi file JSON).

Toàn bộ thông số có thể chỉnh trong GUI tab "Cài đặt" hoặc sửa trực tiếp
file ``config/settings.json``. Nếu file chưa có, chương trình tự tạo từ giá
trị mặc định bên dưới.
"""

from __future__ import annotations

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
    ROOT_DIR = Path(__file__).resolve().parent.parent
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
