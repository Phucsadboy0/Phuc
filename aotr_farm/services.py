"""Khởi tạo và nối các thành phần (composition root).

GUI chỉ làm việc với đối tượng ``Services`` -> dễ thay thế từng phần khi test.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import APP_NAME
from .config import DATA_DIR, MACRO_DIR, TEMPLATE_DIR, AppConfig
from .engine import FarmEngine
from .macro import MacroLibrary
from .notifier import Notifier
from .ocr import RewardReader
from .platform.input import InputController
from .platform.window import GameWindow
from .stats import SessionStats
from .vision import TemplateMatcher, Vision


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
