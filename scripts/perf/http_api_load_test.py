#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_CODES = ["600000", "000001", "600036", "600519", "000858"]
READ_TIMEOUT_SECONDS = 30
SCENARIOS = (
    "single-diagnosis",
    "kline",
    "market",
    "page-switch",
    "update-read",
)


@dataclass(frozen=True)
class RequestSpec:
    label: str
    method: str
    path: str
    body: dict[str, Any] | None = None


@dataclass
class Sample:
    label: str
    elapsed_ms: float
    ok: bool
    status: int | None
    error: str | None = None


class HttpClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = normalize_base_url(base_url)
        self.token = token

    def request(self, spec: RequestSpec) -> tuple[int, bytes]:
        url = f"{self.base_url}{spec.path}"
        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "stocktrade-http-api-load-test/1.0",
        }
        if spec.body is not None:
            data = json.dumps(spec.body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, data=data, method=spec.method, headers=headers)
        with urllib.request.urlopen(req, timeout=READ_TIMEOUT_SECONDS) as response:
            return response.status, response.read()


def normalize_base_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/api/v1"):
        return value[: -len("/api/v1")]
    return value


def parse_codes(raw: str | None) -> list[str]:
    codes = [item.strip().zfill(6) for item in (raw or "").split(",") if item.strip()]
    return codes or DEFAULT_CODES


def login(base_url: str, username: str, password: str) -> str:
    client = HttpClient(base_url)
    status, payload = client.request(
        RequestSpec(
            label="login",
            method="POST",
            path="/api/v1/auth/login",
            body={"username": username, "password": password},
        )
    )
    if status >= 400:
        raise RuntimeError(f"login failed with HTTP {status}")
    data = json.loads(payload.decode("utf-8"))
    token = data.get("access_token")
    if not token:
        raise RuntimeError("login response did not include access_token")
    return str(token)


def choose_code(codes: list[str]) -> str:
    return random.choice(codes)


def add_query(path: str, params: dict[str, Any]) -> str:
    return f"{path}?{urllib.parse.urlencode(params)}"


def scenario_single_diagnosis(codes: list[str]) -> RequestSpec:
    code = choose_code(codes)
    return RequestSpec(
        label="single-diagnosis",
        method="GET",
        path=add_query(
            f"/api/v1/analysis/diagnosis/{code}/history-status",
            {"days": 120, "page": 1, "page_size": 10},
        ),
    )


def scenario_kline(codes: list[str]) -> RequestSpec:
    return RequestSpec(
        label="kline",
        method="POST",
        path="/api/v1/stock/kline",
        body={
            "code": choose_code(codes),
            "days": 120,
            "include_weekly": True,
            "compact": True,
        },
    )


def scenario_market(_: list[str]) -> RequestSpec:
    return random.choice(
        [
            RequestSpec(
                label="market.tomorrow-candidates",
                method="GET",
                path=add_query("/api/v1/analysis/tomorrow-star/candidates", {"limit": 2000}),
            ),
            RequestSpec(
                label="market.tomorrow-results",
                method="GET",
                path="/api/v1/analysis/tomorrow-star/results",
            ),
            RequestSpec(
                label="market.current-hot-candidates",
                method="GET",
                path=add_query("/api/v1/analysis/current-hot/candidates", {"limit": 2000}),
            ),
            RequestSpec(
                label="market.current-hot-results",
                method="GET",
                path="/api/v1/analysis/current-hot/results",
            ),
        ]
    )


def scenario_page_switch(codes: list[str]) -> RequestSpec:
    code = choose_code(codes)
    return random.choice(
        [
            RequestSpec("page.freshness", "GET", "/api/v1/analysis/tomorrow-star/freshness"),
            RequestSpec("page.dates", "GET", "/api/v1/analysis/tomorrow-star/dates"),
            RequestSpec("page.watchlist", "GET", "/api/v1/watchlist/"),
            RequestSpec("page.current-hot-dates", "GET", "/api/v1/analysis/current-hot/dates"),
            scenario_kline([code]),
            scenario_single_diagnosis([code]),
            scenario_market(codes),
        ]
    )


def scenario_update_read(codes: list[str]) -> RequestSpec:
    code = choose_code(codes)
    return random.choice(
        [
            RequestSpec("update-read.running", "GET", "/api/v1/tasks/running"),
            RequestSpec("update-read.status", "GET", "/api/v1/tasks/status"),
            RequestSpec("update-read.freshness", "GET", "/api/v1/tasks/data-freshness"),
            RequestSpec("update-read.analysis-freshness", "GET", "/api/v1/analysis/tomorrow-star/freshness"),
            scenario_kline([code]),
            scenario_market(codes),
        ]
    )


SCENARIO_BUILDERS: dict[str, Callable[[list[str]], RequestSpec]] = {
    "single-diagnosis": scenario_single_diagnosis,
    "kline": scenario_kline,
    "market": scenario_market,
    "page-switch": scenario_page_switch,
    "update-read": scenario_update_read,
}


def run_worker(
    client: HttpClient,
    scenario_names: list[str],
    codes: list[str],
    stop_at: float,
    samples: list[Sample],
    lock: threading.Lock,
) -> None:
    local_samples: list[Sample] = []
    while time.perf_counter() < stop_at:
        scenario_name = random.choice(scenario_names)
        spec = SCENARIO_BUILDERS[scenario_name](codes)
        started = time.perf_counter()
        status: int | None = None
        error: str | None = None
        ok = False
        try:
            status, _ = client.request(spec)
            ok = 200 <= status < 400
        except urllib.error.HTTPError as exc:
            status = exc.code
            error = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 - load test should record all request failures.
            error = exc.__class__.__name__
        elapsed_ms = (time.perf_counter() - started) * 1000
        local_samples.append(Sample(spec.label, elapsed_ms, ok, status, error))

    with lock:
        samples.extend(local_samples)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * pct + 0.999999) - 1))
    return ordered[index]


def summarize_samples(samples: list[Sample], duration_seconds: float) -> dict[str, Any]:
    labels = sorted({sample.label for sample in samples})
    by_label = {label: [sample for sample in samples if sample.label == label] for label in labels}

    def summarize_group(group: list[Sample]) -> dict[str, Any]:
        latencies = [sample.elapsed_ms for sample in group]
        errors = [sample for sample in group if not sample.ok]
        status_counts: dict[str, int] = {}
        for sample in group:
            key = str(sample.status) if sample.status is not None else sample.error or "unknown"
            status_counts[key] = status_counts.get(key, 0) + 1
        return {
            "requests": len(group),
            "rps": round(len(group) / duration_seconds, 2) if duration_seconds > 0 else 0,
            "errors": len(errors),
            "error_rate": round(len(errors) / len(group), 4) if group else 0,
            "avg_ms": round(statistics.mean(latencies), 2) if latencies else 0,
            "p50_ms": round(percentile(latencies, 0.50), 2),
            "p95_ms": round(percentile(latencies, 0.95), 2),
            "p99_ms": round(percentile(latencies, 0.99), 2),
            "min_ms": round(min(latencies), 2) if latencies else 0,
            "max_ms": round(max(latencies), 2) if latencies else 0,
            "status_counts": status_counts,
        }

    return {
        "overall": summarize_group(samples),
        "by_endpoint": {label: summarize_group(group) for label, group in by_label.items()},
    }


def print_human_summary(result: dict[str, Any]) -> None:
    config = result["config"]
    overall = result["summary"]["overall"]
    print("StockTrade HTTP API load test")
    print(
        f"base_url={config['base_url']} scenarios={','.join(config['scenarios'])} "
        f"concurrency={config['concurrency']} duration={config['duration_seconds']}s"
    )
    print(
        "overall "
        f"requests={overall['requests']} rps={overall['rps']} "
        f"avg={overall['avg_ms']}ms p50={overall['p50_ms']}ms "
        f"p95={overall['p95_ms']}ms p99={overall['p99_ms']}ms "
        f"error_rate={overall['error_rate'] * 100:.2f}%"
    )
    print()
    print("endpoint                              req     rps     avg     p50     p95     p99    err%")
    for label, item in result["summary"]["by_endpoint"].items():
        print(
            f"{label[:35]:35} "
            f"{item['requests']:5d} "
            f"{item['rps']:7.2f} "
            f"{item['avg_ms']:7.2f} "
            f"{item['p50_ms']:7.2f} "
            f"{item['p95_ms']:7.2f} "
            f"{item['p99_ms']:7.2f} "
            f"{item['error_rate'] * 100:7.2f}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run production-shaped read-only HTTP load tests against a running StockTrade service.",
    )
    parser.add_argument("--base-url", default=os.environ.get("STOCKTRADE_PERF_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--username", default=os.environ.get("STOCKTRADE_PERF_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("STOCKTRADE_PERF_PASSWORD"))
    parser.add_argument("--token", default=os.environ.get("STOCKTRADE_PERF_TOKEN"))
    parser.add_argument("--codes", default=os.environ.get("STOCKTRADE_PERF_CODES", ",".join(DEFAULT_CODES)))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("STOCKTRADE_PERF_CONCURRENCY", "8")))
    parser.add_argument("--duration", type=int, default=int(os.environ.get("STOCKTRADE_PERF_DURATION", "60")))
    parser.add_argument(
        "--scenario",
        action="append",
        choices=(*SCENARIOS, "all"),
        default=None,
        help="Scenario to run. Repeat for multiple scenarios. Default: all.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to also write the JSON result.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.duration < 1:
        raise SystemExit("--duration must be >= 1")

    scenario_names = list(SCENARIOS) if not args.scenario or "all" in args.scenario else args.scenario
    codes = parse_codes(args.codes)

    token = args.token
    if not token:
        if not args.username or not args.password:
            raise SystemExit("provide --token or both --username and --password, or matching STOCKTRADE_PERF_* env vars")
        token = login(args.base_url, args.username, args.password)

    client = HttpClient(args.base_url, token)
    samples: list[Sample] = []
    lock = threading.Lock()
    started_at = time.time()
    perf_started = time.perf_counter()
    stop_at = perf_started + args.duration

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(run_worker, client, scenario_names, codes, stop_at, samples, lock)
            for _ in range(args.concurrency)
        ]
        for future in futures:
            future.result()

    actual_duration = time.perf_counter() - perf_started
    result = {
        "config": {
            "base_url": normalize_base_url(args.base_url),
            "scenarios": scenario_names,
            "codes": codes,
            "concurrency": args.concurrency,
            "duration_seconds": args.duration,
            "actual_duration_seconds": round(actual_duration, 3),
            "authenticated": bool(token),
        },
        "started_at_unix": round(started_at, 3),
        "summary": summarize_samples(samples, actual_duration),
    }

    print_human_summary(result)
    print()
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 0 if result["summary"]["overall"]["error_rate"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
