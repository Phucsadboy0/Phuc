"""Thống kê phần thưởng và thời gian farm.

* ``RunRecord``    : kết quả của một lượt (EXP, vàng, vật phẩm, thời gian).
* ``SessionStats`` : cộng dồn cả phiên, tính tốc độ/giờ, xuất CSV & JSON.

Lớp này an toàn đa luồng (luồng farm ghi, luồng GUI đọc).
"""

from __future__ import annotations

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
