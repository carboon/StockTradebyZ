#!/bin/bash
# 采集本地生产发布过程的资源开销快照

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BENCH_ROOT="$PROJECT_ROOT/data/logs/release-bench"
STAMP="${1:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="$BENCH_ROOT/$STAMP"
OS_TYPE="$(uname -s)"

mkdir -p "$OUT_DIR"

collect_host_snapshot() {
    echo "timestamp=$(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "os_type=$OS_TYPE"
    echo "[uptime]"
    uptime || true
    echo

    case "$OS_TYPE" in
        Linux)
            echo "[memory]"
            free -h || true
            echo
            echo "[cpu]"
            lscpu || true
            echo
            echo "[top]"
            top -bn1 | head -n 20 || true
            ;;
        Darwin)
            echo "[memory]"
            vm_stat || true
            echo
            echo "[cpu]"
            sysctl -n machdep.cpu.brand_string 2>/dev/null || true
            sysctl -n hw.ncpu 2>/dev/null || true
            echo
            echo "[top]"
            top -l 1 -n 0 | head -n 20 || true
            ;;
        *)
            echo "[memory]"
            echo "unsupported host snapshot OS: $OS_TYPE"
            echo
            echo "[cpu]"
            uname -a || true
            ;;
    esac
}

{
    collect_host_snapshot
} > "$OUT_DIR/host_snapshot.txt"

{
    echo "timestamp=$(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "[docker ps]"
    docker ps -a || true
    echo
    echo "[docker images]"
    docker images || true
    echo
    echo "[docker volume ls]"
    docker volume ls || true
    echo
    echo "[docker stats]"
    docker stats --no-stream || true
} > "$OUT_DIR/docker_snapshot.txt"

{
    echo "timestamp=$(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "[project data]"
    du -sh "$PROJECT_ROOT/data" || true
    echo
    echo "[project data detail]"
    du -sh "$PROJECT_ROOT/data"/* 2>/dev/null || true
} > "$OUT_DIR/disk_usage.txt"

echo "$OUT_DIR"
