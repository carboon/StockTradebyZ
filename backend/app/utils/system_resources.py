from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class SystemResources:
    cpu_count: int
    total_memory_bytes: int | None
    available_memory_bytes: int | None

    @property
    def total_memory_mb(self) -> int | None:
        if self.total_memory_bytes is None:
            return None
        return int(self.total_memory_bytes // (1024 * 1024))

    @property
    def available_memory_mb(self) -> int | None:
        if self.available_memory_bytes is None:
            return None
        return int(self.available_memory_bytes // (1024 * 1024))


def read_proc_meminfo(meminfo_path: str | Path = "/proc/meminfo") -> dict[str, int]:
    path = Path(meminfo_path)
    if not path.exists():
        return {}

    result: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            parts = raw_value.strip().split()
            if not parts:
                continue
            value = int(parts[0])
            unit = parts[1].lower() if len(parts) > 1 else ""
            if unit == "kb":
                value *= 1024
            result[key.strip()] = value
    except Exception:
        return {}
    return result


def _read_total_memory_from_sysconf() -> int | None:
    try:
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, ValueError):
        return None
    if page_count <= 0 or page_size <= 0:
        return None
    return page_count * page_size


def detect_system_resources(meminfo_path: str | Path = "/proc/meminfo") -> SystemResources:
    cpu_count = max(1, int(os.cpu_count() or 1))
    meminfo = read_proc_meminfo(meminfo_path)

    total_memory_bytes = meminfo.get("MemTotal") or _read_total_memory_from_sysconf()
    available_memory_bytes = meminfo.get("MemAvailable") or total_memory_bytes

    return SystemResources(
        cpu_count=cpu_count,
        total_memory_bytes=total_memory_bytes,
        available_memory_bytes=available_memory_bytes,
    )


def recommend_process_workers(
    resources: SystemResources,
    *,
    max_workers: int | None = None,
    reserve_cpus: int = 1,
    memory_per_worker_bytes: int = 900 * 1024 * 1024,
    min_workers: int = 1,
) -> int:
    lower_bound = max(1, int(min_workers))
    cpu_count = max(1, int(resources.cpu_count or 1))
    cpu_budget = max(lower_bound, cpu_count - max(0, int(reserve_cpus)))

    worker_cap = cpu_budget
    if max_workers is not None and int(max_workers) > 0:
        worker_cap = min(worker_cap, int(max_workers))

    if memory_per_worker_bytes <= 0:
        return max(lower_bound, worker_cap)

    available_memory = resources.available_memory_bytes or resources.total_memory_bytes
    if available_memory is None or available_memory <= 0:
        return max(lower_bound, worker_cap)

    memory_budget = max(lower_bound, int(available_memory // int(memory_per_worker_bytes)))
    return max(lower_bound, min(worker_cap, memory_budget))
