#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import locale
import os
import socket
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
if _THIS_FILE.parent.name == "utils" and _THIS_FILE.parent.parent.name == "scripts":
    ROOT = _THIS_FILE.parent.parent.parent
else:
    ROOT = _THIS_FILE.parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE_FILE = ROOT / ".env.example"
FRONTEND_ENV_FILE = ROOT / "frontend" / ".env.local"
RUN_DIR = ROOT / "data" / "run"
LOG_DIR = ROOT / "data" / "logs"
BACKEND_PID_FILE = RUN_DIR / "backend.pid"
FRONTEND_PID_FILE = RUN_DIR / "frontend.pid"
FRONTEND_DIST_DIR = ROOT / "frontend" / "dist"
INSTALL_STATE_FILE = RUN_DIR / "install-state.json"
ROOT_REQUIREMENTS_FILE = ROOT / "requirements.txt"
BACKEND_REQUIREMENTS_FILE = ROOT / "backend" / "requirements.txt"
FRONTEND_LOCK_FILE = ROOT / "frontend" / "package-lock.json"
SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
LAUNCHD_USER_DIR = Path.home() / "Library" / "LaunchAgents"
BACKEND_SERVICE_NAME = "stocktrader-backend.service"
FRONTEND_SERVICE_NAME = "stocktrader-frontend.service"
BACKEND_PLIST_NAME = "com.stocktrader.backend.plist"
FRONTEND_PLIST_NAME = "com.stocktrader.frontend.plist"
DOCKER_CONTAINER_NAMES = [
    "stocktrade-backend",
    "stocktrade-frontend-dev",
    "stocktrade-nginx",
    "stocktrade-postgres",
]
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173
MIN_BOOTSTRAP_PYTHON = (3, 10)
MIN_RUNTIME_PYTHON = (3, 11)
MIN_NODE_MAJOR = 18
COMMON_SEARCH_DIRS = [
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/home/linuxbrew/.linuxbrew/bin"),
    Path("/usr/bin"),
    Path("/usr/sbin"),
]
PIP_INDEX_CANDIDATES = [
    os.environ.get("PIP_INDEX_URL", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.org/simple",
]
NPM_REGISTRY_CANDIDATES = [
    os.environ.get("NPM_REGISTRY", "https://registry.npmmirror.com"),
    "https://registry.npmmirror.com",
    "https://registry.npmjs.org",
]
DATA_DIRS = [
    ROOT / "data" / "db",
    ROOT / "data" / "raw",
    ROOT / "data" / "candidates",
    ROOT / "data" / "review",
    ROOT / "data" / "kline",
    ROOT / "data" / "logs",
    ROOT / "data" / "run",
]
DB_CONFIG_PATH = ROOT / "data" / "db" / "stocktrade.db"


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str, exit_code: int = 1) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_db_configs(path: Path = DB_CONFIG_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        conn = sqlite3.connect(path)
        try:
            rows = conn.execute("SELECT key, value FROM configs").fetchall()
        finally:
            conn.close()
    except Exception:
        return {}
    return {
        str(key).strip().lower(): str(value)
        for key, value in rows
        if key is not None
    }


def get_runtime_setting(
    env_values: dict[str, str],
    env_key: str,
    *,
    db_key: str | None = None,
    default: str = "",
) -> str:
    value = env_values.get(env_key, "").strip()
    if value and value != "your_tushare_token_here":
        return value
    db_values = load_db_configs()
    fallback_key = (db_key or env_key.lower()).lower()
    db_value = db_values.get(fallback_key, "").strip()
    if db_value:
        return db_value
    return default


def ensure_env_file() -> None:
    if not ENV_FILE.exists():
        shutil.copyfile(ENV_EXAMPLE_FILE, ENV_FILE)
        log("已从 .env.example 复制 .env，请至少填入 TUSHARE_TOKEN。")


def ensure_data_dirs() -> None:
    for directory in DATA_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


def file_sha256(path: Path) -> str:
    if not path.exists():
        return ""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def frontend_env_content(env_values: dict[str, str]) -> str:
    api_base_url = env_values.get("VITE_API_BASE_URL", "").strip() or "/api"
    return f"VITE_API_BASE_URL={api_base_url}\n"


def frontend_env_needs_update(env_values: dict[str, str]) -> bool:
    expected = frontend_env_content(env_values)
    if not FRONTEND_ENV_FILE.exists():
        return True
    try:
        current = FRONTEND_ENV_FILE.read_text(encoding="utf-8")
    except Exception:
        return True
    return current != expected


def load_install_state() -> dict[str, object]:
    if not INSTALL_STATE_FILE.exists():
        return {}
    try:
        parsed = json.loads(INSTALL_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def save_install_state(state: dict[str, object]) -> None:
    ensure_data_dirs()
    INSTALL_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def dependency_snapshot() -> dict[str, dict[str, str]]:
    return {
        "backend": {
            "python": ".".join(str(part) for part in sys.version_info[:3]),
            "requirements.txt": file_sha256(ROOT_REQUIREMENTS_FILE),
            "backend/requirements.txt": file_sha256(BACKEND_REQUIREMENTS_FILE),
        },
        "frontend": {
            "package-lock.json": file_sha256(FRONTEND_LOCK_FILE),
        },
    }


def backend_install_required(
    install_state: dict[str, object],
    snapshot: dict[str, dict[str, str]],
    *,
    force: bool = False,
) -> bool:
    if force or not venv_python().exists():
        return True
    return install_state.get("backend") != snapshot["backend"]


def frontend_install_required(
    install_state: dict[str, object],
    snapshot: dict[str, dict[str, str]],
    *,
    force: bool = False,
) -> bool:
    if force or not (ROOT / "frontend" / "node_modules").exists():
        return True
    return install_state.get("frontend") != snapshot["frontend"]


def has_persisted_data() -> bool:
    if DB_CONFIG_PATH.exists():
        return True

    for directory in [
        ROOT / "data" / "raw",
        ROOT / "data" / "candidates",
        ROOT / "data" / "review",
        ROOT / "data" / "kline",
    ]:
        if not directory.exists():
            continue
        for child in directory.iterdir():
            if child.name.startswith("."):
                continue
            return True
    return False


def install_plan_snapshot(force_install: bool = False) -> dict[str, object]:
    env_values = load_env_file(ENV_FILE) if ENV_FILE.exists() else {}
    snapshot = dependency_snapshot()
    install_state = load_install_state()
    backend_needed = backend_install_required(install_state, snapshot, force=force_install)
    frontend_needed = frontend_install_required(install_state, snapshot, force=force_install)
    frontend_build_needed = (
        env_values.get("FORCE_FRONTEND_BUILD", "0") == "1"
        or frontend_needed
        or not FRONTEND_DIST_DIR.exists()
        or frontend_env_needs_update(env_values)
    )
    token = get_runtime_setting(env_values, "TUSHARE_TOKEN", db_key="tushare_token")
    auto_init_needed = bool(token) and not has_persisted_data()
    return {
        "env_values": env_values,
        "snapshot": snapshot,
        "install_state": install_state,
        "backend_needed": backend_needed,
        "frontend_needed": frontend_needed,
        "frontend_build_needed": frontend_build_needed,
        "auto_init_needed": auto_init_needed,
        "token_configured": bool(token),
    }


class PhasePrinter:
    def __init__(self, phases: list[tuple[str, int]]) -> None:
        self.phases = phases
        self.index = 0

    def begin_next(self) -> None:
        if self.index >= len(self.phases):
            return
        remaining_seconds = sum(seconds for _, seconds in self.phases[self.index :])
        title, _ = self.phases[self.index]
        self.index += 1
        log(f"[{self.index}/{len(self.phases)}] {title} | 预计剩余 {format_duration(remaining_seconds)}")


def venv_python() -> Path:
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def resolve_command(candidates: list[str]) -> str | None:
    search_dirs = list(COMMON_SEARCH_DIRS)
    if os.name == "nt":
        for env_key in ["ProgramFiles", "ProgramFiles(x86)"]:
            base_dir = os.environ.get(env_key, "")
            if base_dir:
                search_dirs.append(Path(base_dir) / "nodejs")
    for candidate in candidates:
        candidate_path = Path(candidate)
        if candidate_path.is_file() and os.access(candidate_path, os.X_OK):
            return str(candidate_path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if candidate_path.name == candidate and candidate_path.parent == Path("."):
            for search_dir in search_dirs:
                search_path = search_dir / candidate
                if search_path.is_file() and os.access(search_path, os.X_OK):
                    return str(search_path)
    return None


def system_dependency_help() -> str:
    if os.name == "nt":
        return (
            "系统会自动尝试通过 winget 安装 Python 3.12 和 Node.js LTS。\n"
            "如果系统策略阻止安装，请以管理员身份重新运行当前脚本。"
        )

    if sys.platform == "darwin":
        return "系统会自动尝试通过 Homebrew 安装 Python 3.11 和 Node.js。"

    if resolve_command(["apt-get"]):
        return "系统会自动尝试通过 apt-get 安装 Python、Node.js、npm、lsof。"
    if resolve_command(["dnf"]):
        return "系统会自动尝试通过 dnf 安装 Python、Node.js、npm、lsof。"
    if resolve_command(["yum"]):
        return "系统会自动尝试通过 yum 安装 Python、Node.js、npm、lsof。"
    return "请先安装 Python 3.11+、Node.js 18+、npm、lsof、curl 后重试。"


def require_command(candidates: list[str], description: str) -> str:
    command = resolve_command(candidates)
    if command:
        return command
    help_text = system_dependency_help()
    fail(f"缺少 {description}: {candidates[0]}\n{help_text}")
    return ""


def version_tuple_text(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def parse_semver_prefix(raw: str) -> tuple[int, ...] | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned[0] in {"v", "V"}:
        cleaned = cleaned[1:]
    parts = cleaned.split(".")
    values: list[int] = []
    for part in parts:
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        values.append(int(digits))
    return tuple(values) if values else None


def command_version_output(cmd: list[str], code: str) -> str | None:
    try:
        result = subprocess.run(
            [*cmd, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def python_command_version(cmd: list[str]) -> tuple[int, ...] | None:
    output = command_version_output(cmd, "import sys; print('.'.join(str(x) for x in sys.version_info[:3]))")
    if not output:
        return None
    return parse_semver_prefix(output)


def python_command_candidates() -> list[list[str]]:
    candidates: list[list[str]] = []

    venv_py = str(venv_python())
    if Path(venv_py).exists():
        candidates.append([venv_py])

    if sys.executable:
        candidates.append([sys.executable])

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        for path in [
            Path(local_app_data) / "Programs" / "Python" / "Python312" / "python.exe",
            Path(local_app_data) / "Programs" / "Python" / "Python311" / "python.exe",
            Path(local_app_data) / "Programs" / "Python" / "Python310" / "python.exe",
            Path(program_files) / "Python312" / "python.exe",
            Path(program_files) / "Python311" / "python.exe",
            Path(program_files) / "Python310" / "python.exe",
        ]:
            if path.is_file():
                candidates.append([str(path)])
        py_launcher = resolve_command(["py"])
        if py_launcher:
            for selector in ["-3.12", "-3.11", "-3.10"]:
                candidates.append([py_launcher, selector])

    for candidate in ["python3.12", "python3.11", "python3.10", "python3", "python"]:
        resolved = resolve_command([candidate])
        if resolved:
            candidates.append([resolved])

    unique: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def find_python_command(min_version: tuple[int, int]) -> tuple[list[str], tuple[int, ...]] | None:
    for candidate in python_command_candidates():
        version = python_command_version(candidate)
        if version is None:
            continue
        if version[:2] >= min_version:
            return candidate, version
    return None


def check_python_version(python_bin: str, min_version: tuple[int, int] = MIN_RUNTIME_PYTHON) -> None:
    result = subprocess.run(
        [python_bin, "-c", f"import sys; raise SystemExit(0 if sys.version_info >= {min_version} else 1)"],
        cwd=str(ROOT),
        check=False,
    )
    if result.returncode != 0:
        fail(f"当前 Python 版本过低：{python_bin}，需要 Python {version_tuple_text(min_version)} 或更高版本")


def node_version(node_bin: str) -> tuple[int, ...] | None:
    try:
        result = subprocess.run(
            [node_bin, "--version"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return parse_semver_prefix(result.stdout.strip())


def python_has_venv(python_cmd: list[str]) -> bool:
    try:
        result = subprocess.run(
            [*python_cmd, "-m", "venv", "--help"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def python_has_pip(python_cmd: list[str]) -> bool:
    try:
        result = subprocess.run(
            [*python_cmd, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def run_command(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(cmd, cwd=str(cwd or ROOT), env=env, check=False)
    if result.returncode != 0:
        fail(f"命令执行失败（退出码 {result.returncode}）：{' '.join(cmd)}", result.returncode)


def detect_system_package_manager() -> str | None:
    if os.name == "nt":
        return "winget" if resolve_command(["winget"]) else None
    if sys.platform == "darwin":
        return "brew"
    if resolve_command(["apt-get"]):
        return "apt-get"
    if resolve_command(["dnf"]):
        return "dnf"
    if resolve_command(["yum"]):
        return "yum"
    if resolve_command(["brew"]) or (resolve_command(["bash", "/bin/bash"]) and resolve_command(["curl", "/usr/bin/curl"])):
        return "brew"
    return None


def run_package_manager_command(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    actual_cmd = list(cmd)
    if os.name != "nt" and Path(cmd[0]).name != "brew":
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            sudo_bin = resolve_command(["sudo"])
            if not sudo_bin:
                fail("需要 sudo 权限来安装系统依赖，但系统未检测到 sudo。")
            actual_cmd = [sudo_bin, *cmd]
    run_command(actual_cmd, env=env)


def build_package_manager_command(cmd: list[str]) -> list[str]:
    if os.name == "nt" or Path(cmd[0]).name == "brew":
        return list(cmd)
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        sudo_bin = resolve_command(["sudo"])
        if not sudo_bin:
            fail("需要 sudo 权限来安装系统依赖，但系统未检测到 sudo。")
        return [sudo_bin, *cmd]
    return list(cmd)


def ensure_homebrew() -> str:
    brew_bin = resolve_command(["brew"])
    if brew_bin:
        return brew_bin

    installer = resolve_command(["bash", "/bin/bash"])
    if not installer:
        fail("未检测到 bash，无法自动安装 Homebrew。")

    curl_bin = resolve_command(["curl", "/usr/bin/curl"])
    if not curl_bin:
        fail("未检测到 curl，无法自动安装 Homebrew。")

    log("未检测到 Homebrew，开始自动安装...")
    env = os.environ.copy()
    env["NONINTERACTIVE"] = "1"
    run_command(
        [
            installer,
            "-c",
            f"$({curl_bin} -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)",
        ],
        env=env,
    )
    brew_bin = resolve_command(["brew"]) or resolve_command(
        [
            "/opt/homebrew/bin/brew",
            "/usr/local/bin/brew",
            "/home/linuxbrew/.linuxbrew/bin/brew",
        ]
    )
    if not brew_bin:
        fail("Homebrew 安装完成后仍未检测到 brew。")
    return brew_bin


def ensure_winget() -> str:
    winget_bin = resolve_command(["winget"])
    if winget_bin:
        return winget_bin
    fail("未检测到 winget，请先通过 start-local.ps1 自动修复 WinGet 后重试。")
    return ""


def collect_system_dependency_issues() -> list[str]:
    issues: list[str] = []

    runtime_python = find_python_command(MIN_RUNTIME_PYTHON)
    if runtime_python is None:
        issues.append(f"Python {version_tuple_text(MIN_RUNTIME_PYTHON)}+")
    else:
        python_cmd, _ = runtime_python
        if not python_has_venv(python_cmd):
            issues.append("Python venv")
        if not python_has_pip(python_cmd):
            issues.append("Python pip")

    node_bin = resolve_command(["node", "node.exe"])
    if not node_bin:
        issues.append(f"Node.js {MIN_NODE_MAJOR}+")
    else:
        version = node_version(node_bin)
        if version is None or version[0] < MIN_NODE_MAJOR:
            issues.append(f"Node.js {MIN_NODE_MAJOR}+")

    if not resolve_command(["npm.cmd", "npm"]):
        issues.append("npm")

    if os.name != "nt" and not resolve_command(["lsof"]):
        issues.append("lsof")

    return issues


def install_system_dependencies(manager: str, issues: list[str]) -> None:
    log(f"检测到系统依赖缺失或版本不足: {', '.join(issues)}")
    log(f"开始自动安装系统依赖，包管理器: {manager}")

    if manager == "brew":
        brew_bin = ensure_homebrew()
        run_package_manager_command([brew_bin, "install", "python@3.11", "node"])
        return

    if manager == "apt-get":
        apt_bin = require_command(["apt-get"], "apt-get")
        run_package_manager_command([apt_bin, "update"])
        attempts = [
            [apt_bin, "install", "-y", "python3.12", "python3.12-venv", "python3-pip", "nodejs", "npm", "lsof"],
            [apt_bin, "install", "-y", "python3.11", "python3.11-venv", "python3-pip", "nodejs", "npm", "lsof"],
            [apt_bin, "install", "-y", "python3", "python3-venv", "python3-pip", "nodejs", "npm", "lsof"],
        ]
        for idx, attempt in enumerate(attempts, start=1):
            result = subprocess.run(
                build_package_manager_command(attempt),
                cwd=str(ROOT),
                check=False,
            )
            if result.returncode == 0:
                return
            log(f"  apt 安装尝试 {idx}/{len(attempts)} 失败，切换下一组包名")
        fail("apt-get 已执行，但仍无法安装满足要求的 Python/Node.js 依赖。")

    if manager == "dnf":
        dnf_bin = require_command(["dnf"], "dnf")
        run_package_manager_command([dnf_bin, "install", "-y", "python3", "python3-pip", "python3-virtualenv", "nodejs", "npm", "lsof"])
        return

    if manager == "yum":
        yum_bin = require_command(["yum"], "yum")
        run_package_manager_command([yum_bin, "install", "-y", "python3", "python3-pip", "nodejs", "npm", "lsof"])
        return

    if manager == "winget":
        winget_bin = ensure_winget()
        base_args = [
            winget_bin,
            "install",
            "--exact",
            "--source",
            "winget",
            "--accept-source-agreements",
            "--accept-package-agreements",
            "--scope",
            "machine",
            "--silent",
        ]
        run_package_manager_command([*base_args, "--id", "Python.Python.3.12"])
        run_package_manager_command([*base_args, "--id", "OpenJS.NodeJS.LTS"])
        return

    fail(f"当前系统未识别到可自动执行的包管理器。{system_dependency_help()}")


def relaunch_with_runtime_python() -> None:
    runtime_python = find_python_command(MIN_RUNTIME_PYTHON)
    if runtime_python is None:
        fail(f"自动安装后仍未检测到 Python {version_tuple_text(MIN_RUNTIME_PYTHON)}+。")
    python_cmd, version = runtime_python
    log(f"切换到 Python {version_tuple_text(version[:3])} 继续执行...")
    result = subprocess.run([*python_cmd, str(Path(__file__)), *sys.argv[1:]], cwd=str(ROOT), env=os.environ.copy(), check=False)
    raise SystemExit(result.returncode)


def ensure_system_dependencies() -> None:
    issues = collect_system_dependency_issues()
    if not issues:
        return

    manager = detect_system_package_manager()
    if manager is None and sys.platform == "darwin":
        manager = "brew"
    if manager is None:
        fail(f"系统依赖缺失：{', '.join(issues)}\n{system_dependency_help()}")

    install_system_dependencies(manager, issues)

    remaining = collect_system_dependency_issues()
    if remaining:
        fail(f"系统依赖自动安装后仍不满足要求：{', '.join(remaining)}")

def install_with_pip_fallback(python_bin: str, args: list[str]) -> str:
    indexes = dedupe_preserve_order(PIP_INDEX_CANDIDATES)
    for idx, index in enumerate(indexes, start=1):
        log(f"  pip 镜像 {idx}/{len(indexes)}: {index}")
        result = subprocess.run(
            [python_bin, "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off", *args, "-i", index],
            cwd=str(ROOT),
            check=False,
        )
        if result.returncode == 0:
            return index
    fail("pip 依赖安装失败，已尝试所有镜像源")
    return ""


def install_with_npm_fallback(npm_bin: str) -> str:
    registries = dedupe_preserve_order(NPM_REGISTRY_CANDIDATES)
    install_command = "ci" if FRONTEND_LOCK_FILE.exists() else "install"
    for idx, registry in enumerate(registries, start=1):
        log(f"  npm 镜像 {idx}/{len(registries)}: {registry}")
        result = subprocess.run(
            [npm_bin, install_command, "--registry", registry, "--no-fund", "--no-audit", "--loglevel=error"],
            cwd=str(ROOT / "frontend"),
            check=False,
        )
        if result.returncode == 0:
            return registry
    fail("npm 依赖安装失败，已尝试所有镜像源")
    return ""


def write_frontend_env(env_values: dict[str, str] | None = None) -> str:
    env_values = env_values or load_env_file(ENV_FILE)
    api_base_url = env_values.get("VITE_API_BASE_URL", "").strip() or "/api"
    FRONTEND_ENV_FILE.write_text(frontend_env_content(env_values), encoding="utf-8")
    return api_base_url


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in result.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def read_pid(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def stop_pid(pid: int, label: str) -> None:
    if not process_exists(pid):
        return

    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and process_exists(pid):
            fail(f"无法停止 {label} (PID={pid})：{result.stderr.strip() or result.stdout.strip()}")
    else:
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 5
        while time.time() < deadline and process_exists(pid):
            time.sleep(0.2)
        if process_exists(pid):
            os.kill(pid, signal.SIGKILL)


def pid_listening_on_port(port: int) -> list[int]:
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        pids: set[int] = set()
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() != "TCP":
                continue
            local_addr = parts[1]
            state = parts[3].upper()
            pid_str = parts[4]
            if not local_addr.endswith(f":{port}") or state != "LISTENING":
                continue
            try:
                pids.add(int(pid_str))
            except ValueError:
                continue
        return sorted(pids)

    lsof_bin = resolve_command(["lsof"])
    if not lsof_bin:
        return []
    result = subprocess.run(
        [lsof_bin, "-tiTCP:%s" % port, "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        return []
    pids = []
    for item in result.stdout.splitlines():
        try:
            pids.append(int(item.strip()))
        except ValueError:
            continue
    return sorted(set(pids))


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError, ValueError, socket.timeout, Exception):
        return False


def process_command(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["wmic", "process", "where", f"processid={pid}", "get", "commandline", "/value"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return ""
            for line in result.stdout.splitlines():
                if line.startswith("CommandLine="):
                    return line.split("=", 1)[1].strip()
            return ""

        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception:
        return ""


def docker_compose_available() -> bool:
    docker_bin = resolve_command(["docker"])
    if not docker_bin:
        return False
    result = subprocess.run(
        [docker_bin, "compose", "version"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    return result.returncode == 0


def stocktrade_docker_services_running() -> list[str]:
    docker_bin = resolve_command(["docker"])
    if not docker_bin:
        return []
    result = subprocess.run(
        [docker_bin, "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    if result.returncode != 0:
        return []
    running = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return [name for name in DOCKER_CONTAINER_NAMES if name in running]


def stop_stocktrade_docker_services(*, reason: str | None = None) -> bool:
    services = stocktrade_docker_services_running()
    if not services:
        return False

    if reason:
        log(reason)
    log(f"检测到运行中的 Docker 服务: {', '.join(services)}，正在停止以避免端口/模式冲突...")

    docker_bin = require_command(["docker"], "docker")
    result = subprocess.run(
        [docker_bin, "rm", "-f", *services],
        cwd=str(ROOT),
        check=False,
    )
    if result.returncode != 0:
        fail("检测到本项目 Docker 服务正在运行，但自动停止失败。请手动执行 deploy/scripts/stop.sh down")
    return True


def ensure_runtime_prerequisites() -> tuple[str, str]:
    ensure_env_file()
    ensure_data_dirs()
    ensure_system_dependencies()

    if sys.version_info[:2] < MIN_RUNTIME_PYTHON:
        relaunch_with_runtime_python()

    python_bin = sys.executable
    check_python_version(python_bin, MIN_RUNTIME_PYTHON)
    require_command(["node", "node.exe"], "Node.js")
    npm_bin = require_command(["npm.cmd", "npm"], "npm")
    return python_bin, npm_bin


def log_runtime_state(env_values: dict[str, str]) -> None:
    backend_port = int(env_values.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT)))
    token = get_runtime_setting(env_values, "TUSHARE_TOKEN", db_key="tushare_token")

    if token:
        log("TUSHARE_TOKEN: 已配置")
    else:
        log("TUSHARE_TOKEN: 未配置，首次初始化需在页面内完成")

    docker_services = stocktrade_docker_services_running()
    if docker_services:
        log(f"Docker 模式: 运行中 ({', '.join(docker_services)})")
    else:
        log("Docker 模式: 未运行")

    if is_port_open(backend_port):
        log(f"端口 {backend_port}: 已被占用，启动时将复用现有实例")
    else:
        log(f"端口 {backend_port}: 可用")

    log(f"访问地址: http://127.0.0.1:{backend_port}")


def apply_install_plan(
    plan: dict[str, object],
    *,
    python_bin: str,
    npm_bin: str,
) -> dict[str, str]:
    env_values = plan["env_values"]
    if not isinstance(env_values, dict):
        fail("安装计划异常：env_values 缺失")

    pip_index = ""
    npm_registry = ""

    if not (ROOT / ".venv").exists():
        log("创建 .venv ...")
        run_command([python_bin, "-m", "venv", str(ROOT / ".venv")])

    venv_py = str(venv_python())
    backend_needed = bool(plan.get("backend_needed"))
    frontend_needed = bool(plan.get("frontend_needed"))
    previous_state = plan.get("install_state")
    previous_pip_index = ""
    previous_npm_registry = ""
    if isinstance(previous_state, dict):
        previous_pip_index = str(previous_state.get("pip_index") or "")
        previous_npm_registry = str(previous_state.get("npm_registry") or "")

    if backend_needed:
        log("安装 Python 依赖...")
        pip_index = install_with_pip_fallback(venv_py, ["--upgrade", "pip"])
        pip_index = install_with_pip_fallback(venv_py, ["-r", str(ROOT_REQUIREMENTS_FILE)])
        pip_index = install_with_pip_fallback(venv_py, ["-r", str(BACKEND_REQUIREMENTS_FILE)])
    else:
        pip_index = previous_pip_index
        log("Python 依赖无变更，跳过")

    if frontend_needed:
        log("安装前端依赖...")
        npm_registry = install_with_npm_fallback(npm_bin)
    else:
        npm_registry = previous_npm_registry
        log("前端依赖无变更，跳过")

    write_frontend_env(env_values)

    snapshot = plan.get("snapshot")
    if not isinstance(snapshot, dict):
        fail("安装计划异常：snapshot 缺失")

    save_install_state(
        {
            "backend": snapshot.get("backend", {}),
            "frontend": snapshot.get("frontend", {}),
            "pip_index": pip_index,
            "npm_registry": npm_registry,
            "updated_at": int(time.time()),
        }
    )
    return {"pip_index": pip_index, "npm_registry": npm_registry}


def maybe_build_frontend(npm_bin: str, env_values: dict[str, str], *, force: bool = False) -> None:
    write_frontend_env(env_values)
    if not force and FRONTEND_DIST_DIR.exists():
        log("前端资源已存在，跳过构建")
        return
    log("构建前端生产资源...")
    run_command([npm_bin, "run", "build"], cwd=ROOT / "frontend")


def submit_init_task(env_values: dict[str, str]) -> tuple[str, int]:
    reviewer = get_runtime_setting(env_values, "DEFAULT_REVIEWER", db_key="default_reviewer", default="quant")
    base_url = backend_base_url(env_values)
    response = api_request(
        "POST",
        f"{base_url}/api/v1/tasks/start",
        {
            "reviewer": reviewer,
            "skip_fetch": False,
            "start_from": 1,
        },
    )
    task = response.get("task")
    if not isinstance(task, dict) or "id" not in task:
        fail(f"初始化任务启动失败，返回内容异常: {response}")
    return base_url, int(task["id"])


def preflight() -> None:
    ensure_runtime_prerequisites()
    env_values = load_env_file(ENV_FILE)
    log_runtime_state(env_values)
    log("预检完成")


def install(force: bool = False) -> None:
    python_bin, npm_bin = ensure_runtime_prerequisites()
    plan = install_plan_snapshot(force_install=force)
    env_values = plan["env_values"]
    if not isinstance(env_values, dict):
        fail("安装计划异常：env_values 缺失")

    if not plan["backend_needed"] and not plan["frontend_needed"]:
        api_base_url = write_frontend_env(env_values)
        log("依赖已就绪，跳过安装。")
        log(f"前端 API 地址: {api_base_url}")
        return

    mirrors = apply_install_plan(plan, python_bin=python_bin, npm_bin=npm_bin)
    api_base_url = write_frontend_env(env_values)
    log("安装完成")
    log(f"pip 镜像: {mirrors['pip_index'] or '-'}")
    log(f"npm 镜像: {mirrors['npm_registry'] or '-'}")
    log(f"前端 API 地址: {api_base_url}")


def build_backend_env(env_values: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(env_values)
    path_items = [str(ROOT), str(ROOT / "backend")]
    existing = env.get("PYTHONPATH", "")
    if existing:
        path_items.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(path_items)
    return env


def start_process(cmd: list[str], pid_file: Path, log_file: Path, cwd: Path, env: dict[str, str]) -> int:
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        with log_file.open("ab") as stream:
            process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
    else:
        with log_file.open("ab") as stream:
            process = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
    pid_file.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def wait_backend_ready(port: int) -> None:
    url = f"http://127.0.0.1:{port}/docs"
    for _ in range(15):
        if http_ok(url):
            log(f"后端健康检查通过: {url}")
            return
        time.sleep(1)
    log(f"警告: 后端在 15s 内未返回健康响应，前端仍会继续启动: {url}")


def backend_base_url(env_values: dict[str, str]) -> str:
    backend_port = int(env_values.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT)))
    return f"http://127.0.0.1:{backend_port}"


def api_request(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    request_headers = {"Content-Type": "application/json"}
    request_data = None
    if payload is not None:
        request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, method=method.upper(), data=request_data, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw or str(exc)
        fail(f"API 请求失败: {url} | {detail}", exc.code)
    except urllib.error.URLError as exc:
        fail(f"API 请求失败: {url} | {exc}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        fail(f"API 返回了无法解析的响应: {url} | {raw[:200]}")
    if not isinstance(parsed, dict):
        fail(f"API 返回了非对象响应: {url}")
    return parsed


def format_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    minutes, remain = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}小时{minutes}分"
    if minutes > 0:
        return f"{minutes}分{remain}秒"
    return f"{remain}秒"


def wait_for_task_completion(base_url: str, task_id: int) -> None:
    last_snapshot = None
    while True:
        task = api_request("GET", f"{base_url}/api/v1/tasks/{task_id}")
        meta = task.get("progress_meta_json") or {}
        stage = meta.get("stage_label") or task.get("task_stage") or "-"
        if meta.get("current") is not None and meta.get("total") is not None:
            progress_text = f"{meta.get('current')}/{meta.get('total')}"
        elif meta.get("stage_index") is not None and meta.get("stage_total") is not None:
            progress_text = f"阶段 {meta.get('stage_index')}/{meta.get('stage_total')}"
        else:
            progress_text = f"{task.get('progress', 0)}%"
        parts = [f"[{task.get('status')}] {stage}", progress_text]
        if meta.get("eta_seconds") is not None:
            parts.append(f"预计剩余 {format_duration(int(meta['eta_seconds']))}")
        if meta.get("current_code"):
            parts.append(f"当前 {meta['current_code']}")
        if meta.get("failed_count"):
            parts.append(f"失败 {meta['failed_count']}")
        snapshot = " | ".join(parts)
        if snapshot != last_snapshot:
            log(snapshot)
            last_snapshot = snapshot

        status = str(task.get("status") or "")
        if status == "completed":
            return
        if status in {"failed", "cancelled"}:
            error_message = task.get("error_message") or meta.get("message") or "初始化未完成"
            fail(str(error_message))
        time.sleep(2)


def start(skip_preflight: bool = False, skip_init_data: bool = False, force_install: bool = False) -> None:
    plan = install_plan_snapshot(force_install=force_install)
    frontend_build_needed = bool(plan["frontend_build_needed"])
    auto_init_needed = bool(plan["auto_init_needed"])
    phases: list[tuple[str, int]] = [
        ("检查运行环境", 20),
        ("准备本地配置", 5),
    ]
    if not (ROOT / ".venv").exists():
        phases.append(("创建 Python 虚拟环境", 20))
    if plan["backend_needed"] or plan["frontend_needed"]:
        phases.append(("安装项目依赖", 330))
    if frontend_build_needed:
        phases.append(("构建前端资源", 90))
    if not skip_preflight:
        phases.append(("启动前检查", 10))
    phases.append(("启动后端服务", 15))
    phases.append(("等待服务就绪", 15))
    if not skip_init_data and auto_init_needed:
        phases.append(("首次初始化数据", 900))

    progress = PhasePrinter(phases)

    progress.begin_next()
    python_bin, npm_bin = ensure_runtime_prerequisites()

    stop_stocktrade_docker_services(reason="本地模式启动前先清理本项目 Docker 实例")

    progress.begin_next()
    env_values = load_env_file(ENV_FILE)
    write_frontend_env(env_values)

    if not (ROOT / ".venv").exists():
        progress.begin_next()
        log("创建 .venv ...")
        run_command([python_bin, "-m", "venv", str(ROOT / ".venv")])

    plan = install_plan_snapshot(force_install=force_install)
    if plan["backend_needed"] or plan["frontend_needed"]:
        progress.begin_next()
        mirrors = apply_install_plan(plan, python_bin=python_bin, npm_bin=npm_bin)
        log(f"依赖安装完成 | pip: {mirrors['pip_index'] or '-'} | npm: {mirrors['npm_registry'] or '-'}")

    if frontend_build_needed:
        progress.begin_next()
        maybe_build_frontend(npm_bin, env_values, force=True)

    if not skip_preflight:
        progress.begin_next()
        log_runtime_state(env_values)

    backend_pid = read_pid(BACKEND_PID_FILE)
    backend_port = int(env_values.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT)))
    backend_host = env_values.get("BACKEND_HOST", "0.0.0.0")

    progress.begin_next()
    if backend_pid and process_exists(backend_pid):
        log(f"后端已在运行，PID={backend_pid}")
    else:
        existing_pids = pid_listening_on_port(backend_port)
        if existing_pids:
            pid_text = ",".join(str(pid) for pid in existing_pids)
            first_pid = existing_pids[0]
            command = process_command(first_pid)
            command_lower = command.lower()
            is_local_backend = (
                "uvicorn" in command_lower
                and str(ROOT) in command
            )
            if is_local_backend and http_ok(f"http://127.0.0.1:{backend_port}/health"):
                if BACKEND_PID_FILE.exists():
                    BACKEND_PID_FILE.unlink(missing_ok=True)
                BACKEND_PID_FILE.write_text(str(first_pid), encoding="utf-8")
                log(f"检测到后端端口 {backend_port} 已由本项目实例监听，沿用运行中实例，PID={pid_text}")
            else:
                fail(
                    f"端口 {backend_port} 已被其他进程占用，无法启动本地后端。"
                    f" PID={pid_text} CMD={command or '-'}。"
                    " 如果这是 Docker 版服务，请先执行 deploy/scripts/stop.sh down，"
                    " 或改用 deploy/scripts/start.sh dev/prod。"
                )
        else:
            env = build_backend_env(env_values)
            pid = start_process(
                [str(venv_python()), "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", backend_host, "--port", str(backend_port)],
                BACKEND_PID_FILE,
                LOG_DIR / "backend.log",
                ROOT,
                env,
            )
            log(f"后端已启动，PID={pid}，日志: {LOG_DIR / 'backend.log'}")

    progress.begin_next()
    wait_backend_ready(backend_port)

    frontend_pid = read_pid(FRONTEND_PID_FILE)
    if frontend_pid and process_exists(frontend_pid):
        stop_pid(frontend_pid, "前端(旧 dev server)")
        FRONTEND_PID_FILE.unlink(missing_ok=True)
        log(f"已停止旧的前端 dev server，PID={frontend_pid}")

    log("")
    log("服务已启动：")
    log(f"- 后端: http://127.0.0.1:{backend_port}")
    log(f"- 应用首页: http://127.0.0.1:{backend_port}")
    log(f"- API 文档: http://127.0.0.1:{backend_port}/docs")
    if not get_runtime_setting(env_values, "TUSHARE_TOKEN", db_key="tushare_token"):
        log("提示: 先在页面配置 TUSHARE_TOKEN，再从“运维管理”发起首次初始化")
        return

    if skip_init_data or not auto_init_needed:
        return

    progress.begin_next()
    base_url, task_id = submit_init_task(env_values)
    log(f"初始化任务已提交，任务号 #{task_id}")
    log(f"图形进度: http://127.0.0.1:{backend_port}/update")
    wait_for_task_completion(base_url, task_id)
    log("首次初始化已完成。")


def stop() -> None:
    stop_stocktrade_docker_services(reason="停止本地服务前先清理本项目 Docker 实例")
    for pid_file, label, default_port in [
        (BACKEND_PID_FILE, "后端", DEFAULT_BACKEND_PORT),
        (FRONTEND_PID_FILE, "旧前端 dev server", DEFAULT_FRONTEND_PORT),
    ]:
        pid = read_pid(pid_file)
        if pid and process_exists(pid):
            stop_pid(pid, label)
            log(f"{label} 已停止 (PID={pid})")
        else:
            env_values = load_env_file(ENV_FILE)
            port = int(env_values.get("BACKEND_PORT", str(default_port))) if label == "后端" else int(
                env_values.get("FRONTEND_PORT", str(default_port))
            )
            fallback_pids = pid_listening_on_port(port)
            if fallback_pids:
                for fallback_pid in fallback_pids:
                    stop_pid(fallback_pid, f"{label}:{port}")
                    log(f"{label} 已停止 (PID={fallback_pid})")
            else:
                log(f"{label} 未运行")
        if pid_file.exists():
            pid_file.unlink(missing_ok=True)


def status() -> None:
    env_values = load_env_file(ENV_FILE)
    backend_port = int(env_values.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT)))
    docker_services = stocktrade_docker_services_running()

    if docker_services:
        log(f"Docker 服务: 运行中 ({', '.join(docker_services)})")
    else:
        log("Docker 服务: 未运行")

    backend_pid = read_pid(BACKEND_PID_FILE)
    if backend_pid and process_exists(backend_pid):
        log(f"后端: 运行中 (PID={backend_pid})")
    else:
        fallback_pids = pid_listening_on_port(backend_port)
        if fallback_pids:
            BACKEND_PID_FILE.write_text(str(fallback_pids[0]), encoding="utf-8")
            log(f"后端: 运行中 (PID={','.join(str(pid) for pid in fallback_pids)})")
        else:
            log("后端: 未运行")

    frontend_pid = read_pid(FRONTEND_PID_FILE)
    if frontend_pid and process_exists(frontend_pid):
        log(f"旧前端 dev server: 运行中 (PID={frontend_pid})")

    log(f"后端 HTTP: {'正常' if http_ok(f'http://127.0.0.1:{backend_port}/health') else '不可达'} (http://127.0.0.1:{backend_port}/health)")
    log(f"应用 HTTP: {'正常' if http_ok(f'http://127.0.0.1:{backend_port}') else '不可达'} (http://127.0.0.1:{backend_port})")


def init_data() -> None:
    ensure_runtime_prerequisites()
    env_values = load_env_file(ENV_FILE)
    token = get_runtime_setting(env_values, "TUSHARE_TOKEN", db_key="tushare_token")
    if not token:
        fail("请先在 .env 或页面配置中提供有效的 TUSHARE_TOKEN")

    start(skip_preflight=True, skip_init_data=True)
    base_url, task_id = submit_init_task(env_values)
    log(f"初始化任务已提交，任务号 #{task_id}")
    log(f"打开 http://127.0.0.1:{env_values.get('BACKEND_PORT', str(DEFAULT_BACKEND_PORT))}/update 可查看图形界面进度")
    wait_for_task_completion(base_url, task_id)
    log("首次初始化已完成。")


def remove_path(target: Path) -> None:
    if not target.exists():
        return
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=False)
    else:
        target.unlink()
    log(f"已删除: {target}")


def cleanup_user_services() -> None:
    if sys.platform == "linux":
        if resolve_command(["systemctl"]):
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", BACKEND_SERVICE_NAME, FRONTEND_SERVICE_NAME],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        remove_path(SYSTEMD_USER_DIR / BACKEND_SERVICE_NAME)
        remove_path(SYSTEMD_USER_DIR / FRONTEND_SERVICE_NAME)
        return

    if sys.platform == "darwin":
        if resolve_command(["launchctl"]):
            subprocess.run(
                ["launchctl", "unload", str(LAUNCHD_USER_DIR / BACKEND_PLIST_NAME)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["launchctl", "unload", str(LAUNCHD_USER_DIR / FRONTEND_PLIST_NAME)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        remove_path(LAUNCHD_USER_DIR / BACKEND_PLIST_NAME)
        remove_path(LAUNCHD_USER_DIR / FRONTEND_PLIST_NAME)


def uninstall() -> None:
    log("开始卸载本地内容")
    log("- 停止本地服务")
    log("- 清理本目录生成的配置、依赖、构建产物和数据")

    stop()
    cleanup_user_services()

    for target in [
        ROOT / ".env",
        ROOT / ".venv",
        ROOT / ".pytest_cache",
        ROOT / "frontend" / ".env.local",
        ROOT / "frontend" / "node_modules",
        ROOT / "frontend" / "dist",
        ROOT / "frontend" / "coverage",
        ROOT / ".coverage",
        ROOT / "htmlcov",
        ROOT / "data",
        ROOT / "deploy",
    ]:
        remove_path(target)

    for cache_dir in ROOT.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=False)
            log(f"已删除: {cache_dir}")

    log("卸载完成")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StockTrader 本地部署控制器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--force", action="store_true")
    subparsers.add_parser("preflight")
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--skip-preflight", action="store_true")
    start_parser.add_argument("--skip-init-data", action="store_true")
    start_parser.add_argument("--force-install", action="store_true")
    subparsers.add_parser("stop")
    subparsers.add_parser("status")
    subparsers.add_parser("init-data")
    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--skip-init-data", action="store_true")
    bootstrap_parser.add_argument("--force-install", action="store_true")
    subparsers.add_parser("uninstall")
    return parser


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    if args.command == "install":
        install(force=args.force)
    elif args.command == "preflight":
        preflight()
    elif args.command == "start":
        start(
            skip_preflight=args.skip_preflight,
            skip_init_data=args.skip_init_data,
            force_install=args.force_install,
        )
    elif args.command == "stop":
        stop()
    elif args.command == "status":
        status()
    elif args.command == "init-data":
        init_data()
    elif args.command == "bootstrap":
        start(skip_init_data=args.skip_init_data, force_install=args.force_install)
    elif args.command == "uninstall":
        uninstall()
    else:
        parser.error(f"未知命令: {args.command}")


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")
    main()
