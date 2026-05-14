#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = ROOT / "deploy"
COMPOSE_FILE = DEPLOY_DIR / "docker-compose.yml"
BACKEND_DISABLE_PREWARM_FILE = ROOT / "data" / ".disable_startup_prewarm"
DOCKER_CONFIG_DIR = ROOT / ".docker"
MAINTENANCE_SERVICE = "backend-maintenance"
# 已移除低资源限制，提升性能
LOW_RESOURCE_ENV_DEFAULTS = {
    "PYTHONUNBUFFERED": "1",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "停服维护总控：停止对外服务，构建并启动最小服务，执行最近120交易日补数/校验，"
            "校验通过后再拉起完整服务。只读预热由后端服务启动后自行完成。"
        )
    )
    parser.add_argument("--window-size", type=int, default=120, help="最近多少个交易日，默认 120")
    parser.add_argument("--warmup-trade-days", type=int, default=140, help="回补 warmup 天数，默认 140")
    parser.add_argument("--reviewer", default="quant", help="复核器，默认 quant")
    parser.add_argument("--end-date", default="", help="指定重建截止交易日 YYYY-MM-DD；默认自动解析有效最新交易日")
    parser.add_argument("--skip-build", action="store_true", help="跳过镜像构建")
    parser.add_argument("--no-cache", action="store_true", help="构建时不使用缓存")
    parser.add_argument("--keep-services-on-failure", action="store_true", help="失败时保留最小服务现场，不自动停止")
    parser.add_argument("--allow-prewarm-on-start", action="store_true", help="允许完整服务启动后立刻执行只读预热")
    parser.add_argument("--nice-level", type=int, default=0, help="容器内长任务 nice 值，默认 0（无限制）")
    parser.add_argument("--cpu-quota", default="4.0", help="补数容器 CPU 配额，默认 4.0")
    parser.add_argument("--memory", default="8g", help="补数容器内存上限，默认 8g")
    parser.add_argument("--memory-swap", default="10g", help="补数容器内存+swap 上限，默认 10g")
    parser.add_argument("--rebuild-args", default="", help="附加传递给 rebuild_recent_120_data.py 的参数")
    parser.add_argument("--health-timeout", type=int, default=180, help="等待 backend health 的秒数，默认 180")
    parser.add_argument("--skip-validation", action="store_true", help="跳过完整性校验步骤（步骤5/6），提升速度")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不实际执行")
    return parser.parse_args()


def log(message: str) -> None:
    print(message, flush=True)


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def resolve_compose_cmd() -> list[str]:
    if subprocess.run(["docker", "compose", "version"], capture_output=True, text=True).returncode == 0:
        return ["docker", "compose"]
    if subprocess.run(["docker-compose", "version"], capture_output=True, text=True).returncode == 0:
        return ["docker-compose"]
    raise RuntimeError("未找到 docker compose / docker-compose")


def compose_cmd(compose: list[str], *extra: str) -> list[str]:
    return [
        *compose,
        "-f",
        str(COMPOSE_FILE),
        "--profile",
        "postgres",
        "--profile",
        "prod",
        *extra,
    ]


def compose_run_backend_cmd(
    compose: list[str],
    backend_args: list[str],
    *,
    low_resource: bool = True,
) -> list[str]:
    cmd = compose_cmd(compose, "run", "--rm")
    if low_resource:
        for key, value in LOW_RESOURCE_ENV_DEFAULTS.items():
            cmd.extend(["-e", f"{key}={value}"])
    cmd.append(MAINTENANCE_SERVICE if low_resource else "backend")
    cmd.extend(backend_args)
    return cmd


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    log(f"$ {shell_join(cmd)}")
    if capture:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            capture_output=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
    else:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
        )
    if check and result.returncode != 0:
        raise RuntimeError(f"命令失败({result.returncode}): {shell_join(cmd)}")
    return result


def write_prewarm_flag(disabled: bool) -> None:
    if disabled:
        BACKEND_DISABLE_PREWARM_FILE.parent.mkdir(parents=True, exist_ok=True)
        BACKEND_DISABLE_PREWARM_FILE.write_text("maintenance\n", encoding="utf-8")
    else:
        BACKEND_DISABLE_PREWARM_FILE.unlink(missing_ok=True)


def resolve_effective_end_date(compose: list[str], requested_end_date: str) -> str:
    if requested_end_date.strip():
        return requested_end_date.strip()

    script = (
        "from app.services.tushare_service import TushareService; "
        "value = TushareService().get_effective_latest_trade_date(prefer_realtime=True); "
        "print(value or '')"
    )
    result = run(
        compose_run_backend_cmd(
            compose,
            ["python", "-c", script],
        ),
        cwd=ROOT,
        capture=True,
    )
    resolved = (result.stdout or "").strip().splitlines()
    if not resolved:
        raise RuntimeError("无法解析有效最新交易日")
    value = resolved[-1].strip()
    if not value:
        raise RuntimeError("有效最新交易日为空")
    return value


def build_images(compose: list[str], *, no_cache: bool) -> None:
    for service in ("backend", "nginx"):
        cmd = compose_cmd(compose, "build")
        if no_cache:
            cmd.append("--no-cache")
        cmd.append(service)
        run(cmd, cwd=ROOT)


def stop_services(compose: list[str]) -> None:
    run(compose_cmd(compose, "stop", "nginx", "backend", "redis", "postgres"), cwd=ROOT)


def start_minimal_services(compose: list[str]) -> None:
    run(compose_cmd(compose, "up", "-d", "postgres", "redis"), cwd=ROOT)


def run_recent_120_rebuild(
    compose: list[str],
    *,
    window_size: int,
    warmup_trade_days: int,
    reviewer: str,
    end_date: str,
    extra_args: str,
    nice_level: int,
) -> None:
    rebuild_parts = [
        "python",
        "backend/scripts/rebuild_recent_120_data.py",
        "--yes",
        "--window-size",
        str(window_size),
        "--warmup-trade-days",
        str(warmup_trade_days),
        "--reviewer",
        reviewer,
        "--end-date",
        end_date,
    ]
    if extra_args.strip():
        rebuild_parts.extend(shlex.split(extra_args))
    rebuild_cmd = shell_join(rebuild_parts)
    # 直接执行，无 nice/ionice 限制，提升性能
    shell_cmd = f"exec {rebuild_cmd}"

    run(
        compose_run_backend_cmd(
            compose,
            ["sh", "-lc", shell_cmd],
        ),
        cwd=ROOT,
    )


def run_backend_python(compose: list[str], python_code: str) -> dict[str, Any]:
    result = run(
        compose_run_backend_cmd(
            compose,
            ["python", "-c", python_code],
        ),
        cwd=ROOT,
        capture=True,
    )
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("后端检查未输出结果")
    return json.loads(lines[-1])


def verify_recent_120_integrity(compose: list[str], window_size: int) -> dict[str, Any]:
    code = (
        "import json; "
        "from app.database import SessionLocal; "
        "from app.api.tasks import _build_recent_120_integrity_report; "
        f"db = SessionLocal(); "
        "result = _build_recent_120_integrity_report(db, window_size="
        + str(window_size)
        + "); "
        "db.close(); "
        "print(json.dumps(result, ensure_ascii=False))"
    )
    return run_backend_python(compose, code)


def verify_trade_date_revalidation(compose: list[str], trade_date: str) -> dict[str, Any]:
    code = (
        "import json; "
        "from datetime import date as date_class; "
        "from app.database import SessionLocal; "
        "from app.api.tasks import _build_trade_date_revalidation_report; "
        f"target = date_class.fromisoformat('{trade_date}'); "
        "db = SessionLocal(); "
        "result = _build_trade_date_revalidation_report(db, target); "
        "db.close(); "
        "print(json.dumps(result, ensure_ascii=False))"
    )
    return run_backend_python(compose, code)


def start_full_services(compose: list[str]) -> None:
    run(compose_cmd(compose, "up", "-d", "postgres", "redis", "backend", "nginx"), cwd=ROOT)


def wait_backend_healthy(compose: list[str], timeout_seconds: int) -> None:
    deadline = time.time() + max(10, timeout_seconds)
    while time.time() < deadline:
        result = run(
            compose_cmd(compose, "ps", "--format", "json", "backend"),
            cwd=ROOT,
            check=False,
            capture=True,
        )
        payload = (result.stdout or "").strip()
        if payload:
            try:
                rows = json.loads(payload)
                if isinstance(rows, dict):
                    rows = [rows]
            except json.JSONDecodeError:
                rows = []
            if rows:
                health = str(rows[0].get("Health") or "")
                state = str(rows[0].get("State") or "")
                if health.lower() == "healthy" or ("running" in state.lower() and "healthy" in state.lower()):
                    return
        time.sleep(5)
    raise RuntimeError(f"backend 在 {timeout_seconds}s 内未达到 healthy 状态")


def print_json_block(title: str, payload: dict[str, Any]) -> None:
    log(f"{title}:")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def explain_validation_failure(title: str, payload: dict[str, Any]) -> None:
    issues = payload.get("issues") or []
    if isinstance(issues, list) and issues:
        log(f"{title} failed details:")
        for issue in issues:
            log(f"- {issue}")
    message = str(payload.get("message") or "").strip()
    if message:
        log(f"{title} message: {message}")


def main() -> int:
    args = parse_args()
    # os.environ.setdefault("DOCKER_CONFIG", str(DOCKER_CONFIG_DIR))  # 使用系统默认 Docker 配置
    os.environ["MAINTENANCE_BACKEND_CPUS"] = args.cpu_quota
    os.environ["MAINTENANCE_BACKEND_MEMORY"] = args.memory
    os.environ["MAINTENANCE_BACKEND_MEMORY_SWAP"] = args.memory_swap

    compose = resolve_compose_cmd()
    planned_end_date = args.end_date.strip() or "<auto>"

    if args.dry_run:
        log("维护计划:")
        log(f"- window_size={args.window_size}")
        log(f"- warmup_trade_days={args.warmup_trade_days}")
        log(f"- reviewer={args.reviewer}")
        log(f"- end_date={planned_end_date}")
        log(f"- skip_build={args.skip_build}")
        log(f"- no_cache={args.no_cache}")
        log(f"- allow_prewarm_on_start={args.allow_prewarm_on_start}")
        log(f"- skip_validation={args.skip_validation}")
        log(f"- cpu_quota={args.cpu_quota}")
        log(f"- memory={args.memory}")
        log(f"- memory_swap={args.memory_swap}")
        log(f"- nice_level={args.nice_level} (0=无限制)")
        log("- 已优化：去除线程限制、nice/ionice 限制、提升资源配额")
        log("- 只读预热由服务启动后自行完成，不由维护脚本主动补算")
        return 0

    write_prewarm_flag(disabled=not args.allow_prewarm_on_start)
    minimal_services_started = False
    try:
        log("步骤 1/7: 停止对外服务与相关容器")
        stop_services(compose)

        if not args.skip_build:
            log("步骤 2/7: 构建 backend/nginx 镜像")
            build_images(compose, no_cache=args.no_cache)
        else:
            log("步骤 2/7: 跳过镜像构建")

        log("步骤 3/7: 启动最小必要服务 postgres/redis")
        start_minimal_services(compose)
        minimal_services_started = True

        effective_end_date = resolve_effective_end_date(compose, args.end_date)
        log(f"步骤 4/7: 执行最近120交易日补数重建，effective_end_date={effective_end_date}")
        run_recent_120_rebuild(
            compose,
            window_size=args.window_size,
            warmup_trade_days=args.warmup_trade_days,
            reviewer=args.reviewer,
            end_date=effective_end_date,
            extra_args=args.rebuild_args,
            nice_level=args.nice_level,
        )

        if args.skip_validation:
            log("步骤 5/7: 跳过完整性校验（--skip-validation）")
            log("步骤 6/7: 跳过重验证校验（--skip-validation）")
        else:
            log("步骤 5/7: 校验最近120交易日完整性")
            integrity = verify_recent_120_integrity(compose, args.window_size)
            print_json_block("recent_120_integrity", integrity)
            if not integrity.get("success"):
                explain_validation_failure("recent_120_integrity", integrity)
                raise RuntimeError(str(integrity.get("message") or "最近120交易日完整性校验失败"))

            log(f"步骤 6/7: 校验最新有效交易日 {effective_end_date} 的本地重验证")
            revalidation = verify_trade_date_revalidation(compose, effective_end_date)
            print_json_block("trade_date_revalidation", revalidation)
            if not revalidation.get("success"):
                explain_validation_failure("trade_date_revalidation", revalidation)
                raise RuntimeError(str(revalidation.get("message") or f"{effective_end_date} 本地重验证失败"))

        log("步骤 7/7: 拉起完整服务栈")
        start_full_services(compose)
        wait_backend_healthy(compose, args.health_timeout)
        log("维护完成。只读预热由后端服务启动后自行执行。")
        return 0
    except Exception as exc:
        log(f"维护失败: {exc}")
        if minimal_services_started and not args.keep_services_on_failure:
            log("失败后自动停止最小服务现场")
            try:
                stop_services(compose)
            except Exception as stop_exc:
                log(f"停止服务时再次失败: {stop_exc}")
        return 1
    finally:
        if not args.allow_prewarm_on_start:
            write_prewarm_flag(disabled=False)


if __name__ == "__main__":
    raise SystemExit(main())
