"""Wall-clock and peak-memory measurement."""

from __future__ import annotations

import platform
import sys
import time
import tracemalloc
from dataclasses import dataclass
from typing import Any


def _peak_rss_bytes() -> tuple[int | None, str]:
    # Returns the source alongside the number: the report prints it so an
    # OS-level peak RSS is never confused with a tracemalloc Python-only one.
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            # Signatures must be declared: without them ctypes truncates the
            # 64-bit pseudo-handle and the call silently returns 0.
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.GetCurrentProcess.argtypes = []
            kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
            kernel32.K32GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(_Counters),
                wintypes.DWORD,
            ]

            counters = _Counters()
            counters.cb = ctypes.sizeof(_Counters)
            if kernel32.K32GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            ):
                return int(counters.PeakWorkingSetSize), "windows_peak_working_set"
        except Exception:  # noqa: BLE001 - measurement must never fail a run
            pass
    else:
        try:
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Linux reports kilobytes, macOS reports bytes.
            scale = 1024 if sys.platform.startswith("linux") else 1
            return int(peak) * scale, "getrusage_ru_maxrss"
        except Exception:  # noqa: BLE001
            pass

    if tracemalloc.is_tracing():
        return int(tracemalloc.get_traced_memory()[1]), "tracemalloc_python_only"
    return None, "unavailable"


@dataclass
class RunMetrics:
    started_at: float
    stages: dict[str, float]

    @classmethod
    def start(cls) -> "RunMetrics":
        return cls(started_at=time.perf_counter(), stages={})

    def stage(self, name: str) -> "_StageTimer":
        return _StageTimer(self, name)

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started_at

    def summary(self) -> dict[str, Any]:
        peak, source = _peak_rss_bytes()
        return {
            "wall_clock_seconds": round(self.elapsed_seconds, 3),
            "stage_seconds": {k: round(v, 3) for k, v in self.stages.items()},
            "peak_memory_bytes": peak,
            "peak_memory_mib": round(peak / (1024 * 1024), 1) if peak else None,
            "peak_memory_source": source,
            "machine": {
                "platform": platform.platform(),
                "processor": platform.processor() or platform.machine(),
                "python_version": platform.python_version(),
                "python_implementation": platform.python_implementation(),
            },
        }


class _StageTimer:
    __slots__ = ("_metrics", "_name", "_started")

    def __init__(self, metrics: RunMetrics, name: str) -> None:
        self._metrics = metrics
        self._name = name
        self._started = 0.0

    def __enter__(self) -> "_StageTimer":
        self._started = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        elapsed = time.perf_counter() - self._started
        self._metrics.stages[self._name] = self._metrics.stages.get(self._name, 0.0) + elapsed
