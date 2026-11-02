"""Cửa sổ chính của AOTR Farm Assistant.

Nguyên tắc luồng:
    * tkinter KHÔNG thread-safe -> engine, phím tắt, notifier chỉ đẩy sự kiện
      vào ``self.ui_queue``; GUI rút hàng đợi bằng ``after()`` mỗi 200 ms.
    * Bảng số liệu cập nhật mỗi 1 s (đủ mượt, rất ít CPU).
"""

from __future__ import annotations

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

from .. import APP_NAME, __version__
from ..config import DATA_DIR, LOG_DIR, MACRO_DIR, TEMPLATE_DIR, save_config
from ..engine import State
from ..logging_setup import log_queue, set_level
from ..notifier import ERROR, send_test
from ..platform.hotkeys import HotkeyManager
from ..resources import ResourceMonitor
from ..services import Services
from ..stats import fmt_duration
from .region_picker import crop_relative, pick_region

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
                       {"slot_a_card", "join_community_button", "lobby_card", "mission_play_button", "missions_card", "forest_map", "create_button", "start_button",
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
        from ..vision import save_png
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
        from ..ocr import RewardReader
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
