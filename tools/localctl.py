#!/usr/bin/env python3
from __future__ import annotations

import argparse
import locale
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE_FILE = ROOT / ".env.example"
FRONTEND_ENV_FILE = ROOT / "frontend" / ".env.local"
RUN_DIR = ROOT / "data" / "run"
LOG_DIR = ROOT / "data" / "logs"
BACKEND_PID_FILE = RUN_DIR / "backend.pid"
FRONTEND_PID_FILE = RUN_DIR / "frontend.pid"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173
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


def log(message: str) -> None:
    print(message)


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


def merged_runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(load_env_file(ENV_FILE))
    return env


def ensure_env_file() -> None:
    if not ENV_FILE.exists():
        shutil.copyfile(ENV_EXAMPLE_FILE, ENV_FILE)
        log("已从 .env.example 复制 .env，请至少填入 TUSHARE_TOKEN。")


def ensure_data_dirs() -> None:
    for directory in DATA_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


def venv_python() -> Path:
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def resolve_command(candidates: list[str]) -> str | None:
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def require_command(candidates: list[str], description: str) -> str:
    command = resolve_command(candidates)
    if command:
        return command
    if os.name == "nt":
        help_text = (
            "请先手动安装以下依赖并重试：\n"
            "  Python 3.11+\n"
            "  Node.js 18+\n"
            "  npm\n"
            "建议使用 winget：\n"
            "  winget install Python.Python.3.12\n"
            "  winget install OpenJS.NodeJS.LTS"
        )
    else:
        help_text = f"请先安装 {description} 后重试。"
    fail(f"缺少 {description}: {candidates[0]}\n{help_text}")
    return ""


def check_python_version(python_bin: str) -> None:
    result = subprocess.run(
        [python_bin, "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"],
        cwd=str(ROOT),
        check=False,
    )
    if result.returncode != 0:
        fail(f"当前 Python 版本过低：{python_bin}，需要 Python 3.11 或更高版本")


def run_command(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(cmd, cwd=str(cwd or ROOT), env=env, check=False)
    if result.returncode != 0:
        fail(f"命令执行失败（退出码 {result.returncode}）：{' '.join(cmd)}", result.returncode)


def install_with_pip_fallback(python_bin: str, args: list[str]) -> str:
    for index in PIP_INDEX_CANDIDATES:
        log(f"尝试 pip 源: {index}")
        result = subprocess.run(
            [python_bin, "-m", "pip", "install", *args, "-i", index],
            cwd=str(ROOT),
            check=False,
        )
        if result.returncode == 0:
            return index
    fail("pip 依赖安装失败，已尝试所有镜像源")
    return ""


def install_with_npm_fallback(npm_bin: str) -> str:
    for registry in NPM_REGISTRY_CANDIDATES:
        log(f"尝试 npm 源: {registry}")
        result = subprocess.run(
            [npm_bin, "install", "--registry", registry],
            cwd=str(ROOT / "frontend"),
            check=False,
        )
        if result.returncode == 0:
            return registry
    fail("npm 依赖安装失败，已尝试所有镜像源")
    return ""


def write_frontend_env(env_values: dict[str, str] | None = None, actual_backend_port: int = None) -> str:
    env_values = env_values or load_env_file(ENV_FILE)
    # 如果提供了实际使用的后端端口，则使用它；否则使用配置中的端口
    backend_port = str(actual_backend_port) if actual_backend_port is not None else env_values.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT))
    backend_host = env_values.get("BACKEND_HOST", "127.0.0.1")
    api_base_url = env_values.get("VITE_API_BASE_URL", "").strip()

    if not api_base_url:
        normalized_host = "127.0.0.1" if backend_host == "0.0.0.0" else backend_host
        api_base_url = f"http://{normalized_host}:{backend_port}/api"

    FRONTEND_ENV_FILE.write_text(f"VITE_API_BASE_URL={api_base_url}\n", encoding="utf-8")
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
    """检查端口是否被占用（尝试绑定）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('0.0.0.0', port))
            return False  # 可以绑定，说明端口未被占用
    except OSError:
        return True  # 无法绑定，说明端口已被占用


def find_available_port(start_port: int, max_attempts: int = 100) -> int:
    """查找可用的端口，从start_port开始尝试"""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return port
        except OSError:
            continue
    fail(f"无法找到可用端口（已尝试 {max_attempts} 个端口）")
    return start_port


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def preflight() -> None:
    python_bin = sys.executable
    check_python_version(python_bin)
    require_command(["node", "node.exe"], "Node.js")
    require_command(["npm.cmd", "npm"], "npm")
    ensure_env_file()
    ensure_data_dirs()

    env_values = load_env_file(ENV_FILE)
    backend_port = int(env_values.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT)))
    frontend_port = int(env_values.get("FRONTEND_PORT", str(DEFAULT_FRONTEND_PORT)))

    if env_values.get("TUSHARE_TOKEN", "") in {"", "your_tushare_token_here"}:
        log("[WARN] TUSHARE_TOKEN 未配置，系统可启动，但首次进入后需要在页面中完成配置")
    else:
        log("[OK] TUSHARE_TOKEN 已配置")

    if is_port_open(backend_port):
        log(f"[WARN] 后端端口 {backend_port} 已被占用")
    else:
        log(f"[OK] 后端端口 {backend_port} 可用")

    if is_port_open(frontend_port):
        log(f"[WARN] 前端端口 {frontend_port} 已被占用")
    else:
        log(f"[OK] 前端端口 {frontend_port} 可用")

    log("[OK] 预检完成")


def install() -> None:
    python_bin = sys.executable
    check_python_version(python_bin)
    require_command(["node", "node.exe"], "Node.js")
    npm_bin = require_command(["npm.cmd", "npm"], "npm")
    ensure_env_file()
    ensure_data_dirs()

    venv_dir = ROOT / ".venv"
    if not venv_dir.exists():
        log("创建虚拟环境...")
        run_command([python_bin, "-m", "venv", str(venv_dir)])

    venv_py = str(venv_python())
    pip_index = install_with_pip_fallback(venv_py, ["--upgrade", "pip"])
    log("安装后端依赖...")
    pip_index = install_with_pip_fallback(venv_py, ["-r", "requirements.txt"])
    pip_index = install_with_pip_fallback(venv_py, ["-r", "backend/requirements.txt"])

    log("安装前端依赖...")
    npm_registry = install_with_npm_fallback(npm_bin)

    api_base_url = write_frontend_env()
    log("")
    log("安装完成。")
    log(f"- pip: {pip_index}")
    log(f"- npm: {npm_registry}")
    log(f"- 前端 API 地址: {api_base_url}")
    log("")
    log("Windows 下一步：")
    log(r"1. 一键启动：.\bootstrap-local.bat")
    log(r"2. 或分步执行：.\init-data.bat / .\start-local.bat / .\status-local.bat")


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


def start(skip_preflight: bool = False) -> None:
    if not (ROOT / ".venv").exists():
        fail(r"未检测到 .venv，请先执行 .\install-local.bat")
    if not ENV_FILE.exists():
        fail(r"未检测到 .env，请先执行 .\install-local.bat 并配置 TUSHARE_TOKEN")

    if not skip_preflight:
        preflight()

    ensure_data_dirs()
    env_values = load_env_file(ENV_FILE)
    backend_port = int(env_values.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT)))
    frontend_port = int(env_values.get("FRONTEND_PORT", str(DEFAULT_FRONTEND_PORT)))
    backend_host = env_values.get("BACKEND_HOST", "0.0.0.0")
    frontend_host = env_values.get("FRONTEND_HOST", "0.0.0.0")
    
    # 检查并自动分配可用端口
    original_backend_port = backend_port
    original_frontend_port = frontend_port
    
    if is_port_open(backend_port):
        log(f"[WARN] 后端端口 {backend_port} 已被占用，正在查找可用端口...")
        backend_port = find_available_port(backend_port + 1)
        log(f"[OK] 后端使用新端口: {backend_port}")
    
    if is_port_open(frontend_port):
        log(f"[WARN] 前端端口 {frontend_port} 已被占用，正在查找可用端口...")
        frontend_port = find_available_port(frontend_port + 1)
        log(f"[OK] 前端使用新端口: {frontend_port}")
    
    # 如果端口发生变化，更新.env文件
    if backend_port != original_backend_port or frontend_port != original_frontend_port:
        env_content = ENV_FILE.read_text(encoding="utf-8")
        if backend_port != original_backend_port:
            env_content = env_content.replace(
                f"BACKEND_PORT={original_backend_port}",
                f"BACKEND_PORT={backend_port}"
            )
        if frontend_port != original_frontend_port:
            env_content = env_content.replace(
                f"FRONTEND_PORT={original_frontend_port}",
                f"FRONTEND_PORT={frontend_port}"
            )
        ENV_FILE.write_text(env_content, encoding="utf-8")
        log(f"[INFO] 已更新 .env 文件中的端口配置")
    
    write_frontend_env(env_values, actual_backend_port=backend_port)

    backend_pid = read_pid(BACKEND_PID_FILE)
    if backend_pid and process_exists(backend_pid):
        log(f"后端已在运行，PID={backend_pid}")
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

    wait_backend_ready(backend_port)

    frontend_pid = read_pid(FRONTEND_PID_FILE)
    if frontend_pid and process_exists(frontend_pid):
        log(f"前端已在运行，PID={frontend_pid}")
    else:
        npm_bin = require_command(["npm.cmd", "npm"], "npm")
        env = merged_runtime_env()
        pid = start_process(
            [npm_bin, "run", "dev", "--", "--host", frontend_host, "--port", str(frontend_port)],
            FRONTEND_PID_FILE,
            LOG_DIR / "frontend.log",
            ROOT / "frontend",
            env,
        )
        log(f"前端已启动，PID={pid}，日志: {LOG_DIR / 'frontend.log'}")

    log("")
    log("服务已启动：")
    log(f"- 前端: http://127.0.0.1:{frontend_port}")
    log(f"- 后端: http://127.0.0.1:{backend_port}")
    log(f"- API 文档: http://127.0.0.1:{backend_port}/docs")


def stop() -> None:
    for pid_file, label, default_port in [
        (BACKEND_PID_FILE, "后端", DEFAULT_BACKEND_PORT),
        (FRONTEND_PID_FILE, "前端", DEFAULT_FRONTEND_PORT),
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
            pid_file.unlink()


def status() -> None:
    env_values = load_env_file(ENV_FILE)
    backend_port = int(env_values.get("BACKEND_PORT", str(DEFAULT_BACKEND_PORT)))
    frontend_port = int(env_values.get("FRONTEND_PORT", str(DEFAULT_FRONTEND_PORT)))

    for pid_file, label in [
        (BACKEND_PID_FILE, "后端"),
        (FRONTEND_PID_FILE, "前端"),
    ]:
        pid = read_pid(pid_file)
        if pid and process_exists(pid):
            log(f"{label}: 运行中 (PID={pid})")
        else:
            log(f"{label}: 未运行")

    log(f"后端 HTTP: {'正常' if http_ok(f'http://127.0.0.1:{backend_port}/health') else '不可达'} (http://127.0.0.1:{backend_port}/health)")
    log(f"前端 HTTP: {'正常' if http_ok(f'http://127.0.0.1:{frontend_port}') else '不可达'} (http://127.0.0.1:{frontend_port})")


def init_data() -> None:
    if not (ROOT / ".venv").exists():
        fail(r"未检测到 .venv，请先执行 .\install-local.bat")
    if not ENV_FILE.exists():
        fail(r"未检测到 .env，请先执行 .\install-local.bat 并配置 TUSHARE_TOKEN")

    env_values = load_env_file(ENV_FILE)
    token = env_values.get("TUSHARE_TOKEN", "")
    if token in {"", "your_tushare_token_here"}:
        fail("请先在 .env 中配置有效的 TUSHARE_TOKEN")

    env = build_backend_env(env_values)
    reviewer = env_values.get("DEFAULT_REVIEWER", "quant")
    run_command([str(venv_python()), "run_all.py", "--reviewer", reviewer, "--start-from", "1"], env=env)


def uninstall() -> None:
    log("开始卸载本地部署内容：")
    log("- 停止前后端本地进程")
    log("- 删除数据库、配置文件、本地数据目录")
    log("- 删除虚拟环境、前端依赖与构建产物")

    stop()

    for target in [
        ROOT / ".env",
        ROOT / ".venv",
        ROOT / ".pytest_cache",
        ROOT / "frontend" / ".env.local",
        ROOT / "frontend" / "node_modules",
        ROOT / "frontend" / "dist",
        ROOT / "data",
        ROOT / "deploy",
    ]:
        if target.exists():
            try:
                if target.is_dir():
                    # Windows下删除大目录可能需要重试
                    _remove_directory_with_retry(target)
                else:
                    target.unlink()
                log(f"已删除: {target}")
            except Exception as e:
                log(f"[WARN] 删除 {target} 失败: {e}")
                log(f"       请手动删除: {target}")

    log("")
    log("卸载完成。")


def _remove_directory_with_retry(dir_path: Path, max_retries: int = 3) -> None:
    """在Windows下安全删除目录，带重试机制"""
    import time
    
    for attempt in range(max_retries):
        try:
            # Windows下使用cmd的rmdir命令可能更可靠
            if os.name == 'nt':
                import subprocess
                result = subprocess.run(
                    ['cmd', '/c', 'rmdir', '/s', '/q', str(dir_path)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    return
                else:
                    raise OSError(f"rmdir failed: {result.stderr}")
            else:
                shutil.rmtree(dir_path, ignore_errors=False)
            return
        except (PermissionError, OSError) as e:
            if attempt < max_retries - 1:
                log(f"[WARN] 删除 {dir_path} 第{attempt + 1}次尝试失败，等待后重试...")
                time.sleep(2)
            else:
                raise


def bootstrap(skip_init_data: bool = False) -> None:
    install()
    env_values = load_env_file(ENV_FILE)
    token = env_values.get("TUSHARE_TOKEN", "")
    if token in {"", "your_tushare_token_here"}:
        log("")
        log("安装已完成，当前未配置有效的 TUSHARE_TOKEN。")
        log("系统将先启动前后端，请在浏览器进入配置页完成 Token 配置后再执行数据初始化。")
        start(skip_preflight=True)
        return

    preflight()
    if not skip_init_data:
        log("执行首次数据初始化...")
        init_data()
    start(skip_preflight=True)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StockTrader 本地部署控制器")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("install")
    subparsers.add_parser("preflight")
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--skip-preflight", action="store_true")
    subparsers.add_parser("stop")
    subparsers.add_parser("status")
    subparsers.add_parser("init-data")
    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--skip-init-data", action="store_true")
    subparsers.add_parser("uninstall")
    return parser


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    if args.command == "install":
        install()
    elif args.command == "preflight":
        preflight()
    elif args.command == "start":
        start(skip_preflight=args.skip_preflight)
    elif args.command == "stop":
        stop()
    elif args.command == "status":
        status()
    elif args.command == "init-data":
        init_data()
    elif args.command == "bootstrap":
        bootstrap(skip_init_data=args.skip_init_data)
    elif args.command == "uninstall":
        uninstall()
    else:
        parser.error(f"未知命令: {args.command}")


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")
    main()
