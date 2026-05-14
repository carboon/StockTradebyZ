from pathlib import Path

from app.utils.system_resources import (
    SystemResources,
    detect_system_resources,
    read_proc_meminfo,
    recommend_process_workers,
)


def test_read_proc_meminfo_parses_kb_values(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       16384000 kB\n"
        "MemAvailable:    8192000 kB\n",
        encoding="utf-8",
    )

    result = read_proc_meminfo(meminfo)

    assert result["MemTotal"] == 16384000 * 1024
    assert result["MemAvailable"] == 8192000 * 1024


def test_detect_system_resources_uses_proc_meminfo(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:        4096000 kB\n"
        "MemAvailable:    2048000 kB\n",
        encoding="utf-8",
    )

    result = detect_system_resources(meminfo)

    assert result.cpu_count >= 1
    assert result.total_memory_mb == 4000
    assert result.available_memory_mb == 2000


def test_recommend_process_workers_respects_cpu_and_memory_limits() -> None:
    resources = SystemResources(
        cpu_count=8,
        total_memory_bytes=8 * 1024 * 1024 * 1024,
        available_memory_bytes=2 * 1024 * 1024 * 1024,
    )

    workers = recommend_process_workers(
        resources,
        max_workers=6,
        reserve_cpus=1,
        memory_per_worker_bytes=900 * 1024 * 1024,
    )

    assert workers == 2


def test_recommend_process_workers_never_returns_less_than_one() -> None:
    resources = SystemResources(
        cpu_count=1,
        total_memory_bytes=None,
        available_memory_bytes=None,
    )

    workers = recommend_process_workers(
        resources,
        max_workers=4,
        reserve_cpus=4,
        memory_per_worker_bytes=900 * 1024 * 1024,
    )

    assert workers == 1
