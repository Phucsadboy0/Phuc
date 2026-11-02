"""Theo dõi CPU / RAM của chính chương trình (và của Roblox nếu tìm thấy)."""

from __future__ import annotations

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
