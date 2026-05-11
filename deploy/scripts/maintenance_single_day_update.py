#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from maintenance_rebuild_and_restart import (
    DOCKER_CONFIG_DIR,
    ROOT,
    build_images,
    compose_run_backend_cmd,
    explain_validation_failure,
    log,
    print_json_block,
    resolve_compose_cmd,
    run,
    shell_join,
    start_full_services,
    start_minimal_services,
    stop_services,
    verify_trade_date_revalidation,
    wait_backend_healthy,
    write_prewarm_flag,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "停服离线单日更新：停止对外服务，启动最小依赖，"
            "只补齐指定交易日数据并重建当日派生结果，校验通过后恢复完整服务。"
        )
    )
    parser.add_argument("--target-date", required=True, help="目标交易日 YYYY-MM-DD")
    parser.add_argument("--window-size", type=int, default=120, help="明日之星窗口大小，默认 120")
    parser.add_argument("--reviewer", default="quant", help="复核器，默认 quant")
    parser.add_argument("--skip-build", action="store_true", help="跳过镜像构建")
    parser.add_argument("--no-cache", action="store_true", help="构建时不使用缓存")
    parser.add_argument("--keep-services-on-failure", action="store_true", help="失败时保留最小服务现场，不自动停止")
    parser.add_argument("--allow-prewarm-on-start", action="store_true", help="允许完整服务启动后立刻执行只读预热")
    parser.add_argument("--nice-level", type=int, default=10, help="容器内长任务 nice 值，默认 10")
    parser.add_argument("--cpu-quota", default="0.75", help="补数容器 CPU 配额，默认 0.75")
    parser.add_argument("--memory", default="1400m", help="补数容器内存上限，默认 1400m")
    parser.add_argument("--memory-swap", default="1600m", help="补数容器内存+swap 上限，默认 1600m")
    parser.add_argument("--health-timeout", type=int, default=180, help="等待 backend health 的秒数，默认 180")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不实际执行")
    return parser.parse_args()


def run_single_trade_date_update(
    compose: list[str],
    *,
    target_date: str,
    window_size: int,
    reviewer: str,
    nice_level: int,
) -> None:
    update_parts = [
        "python",
        "backend/scripts/run_background_latest_trade_day_update.py",
        "--target-date",
        target_date,
        "--window-size",
        str(window_size),
        "--reviewer",
        reviewer,
        "--force",
    ]
    update_cmd = shell_join(update_parts)
    shell_cmd = (
        f"if command -v ionice >/dev/null 2>&1; "
        f"then exec ionice -c3 nice -n {nice_level} {update_cmd}; "
        f"else exec nice -n {nice_level} {update_cmd}; fi"
    )
    run(
        compose_run_backend_cmd(
            compose,
            ["sh", "-lc", shell_cmd],
        ),
        cwd=ROOT,
    )


def main() -> int:
    args = parse_args()
    os.environ.setdefault("DOCKER_CONFIG", str(DOCKER_CONFIG_DIR))
    os.environ["MAINTENANCE_BACKEND_CPUS"] = args.cpu_quota
    os.environ["MAINTENANCE_BACKEND_MEMORY"] = args.memory
    os.environ["MAINTENANCE_BACKEND_MEMORY_SWAP"] = args.memory_swap

    compose = resolve_compose_cmd()

    if args.dry_run:
        log("离线单日更新计划:")
        log(f"- target_date={args.target_date}")
        log(f"- window_size={args.window_size}")
        log(f"- reviewer={args.reviewer}")
        log(f"- skip_build={args.skip_build}")
        log(f"- no_cache={args.no_cache}")
        log(f"- allow_prewarm_on_start={args.allow_prewarm_on_start}")
        log(f"- cpu_quota={args.cpu_quota}")
        log(f"- memory={args.memory}")
        log(f"- memory_swap={args.memory_swap}")
        log("- 执行方式：停服后仅更新目标交易日，并强制补齐当日数据")
        return 0

    write_prewarm_flag(disabled=not args.allow_prewarm_on_start)
    minimal_services_started = False
    try:
        log("步骤 1/6: 停止对外服务与相关容器")
        stop_services(compose)

        if not args.skip_build:
            log("步骤 2/6: 构建 backend/nginx 镜像")
            build_images(compose, no_cache=args.no_cache)
        else:
            log("步骤 2/6: 跳过镜像构建")

        log("步骤 3/6: 启动最小必要服务 postgres/redis")
        start_minimal_services(compose)
        minimal_services_started = True

        log(f"步骤 4/6: 执行离线单日更新 target_date={args.target_date}")
        run_single_trade_date_update(
            compose,
            target_date=args.target_date,
            window_size=args.window_size,
            reviewer=args.reviewer,
            nice_level=args.nice_level,
        )

        log(f"步骤 5/6: 校验目标交易日 {args.target_date} 的本地重验证")
        revalidation = verify_trade_date_revalidation(compose, args.target_date)
        print_json_block("trade_date_revalidation", revalidation)
        if not revalidation.get("success"):
            explain_validation_failure("trade_date_revalidation", revalidation)
            raise RuntimeError(str(revalidation.get("message") or f"{args.target_date} 本地重验证失败"))

        log("步骤 6/6: 拉起完整服务栈")
        start_full_services(compose)
        wait_backend_healthy(compose, args.health_timeout)
        log("离线单日更新完成。只读预热由后端服务启动后自行执行。")
        return 0
    except Exception as exc:
        log(f"离线单日更新失败: {exc}")
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
