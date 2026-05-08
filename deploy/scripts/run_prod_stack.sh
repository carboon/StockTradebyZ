#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_DIR="$PROJECT_ROOT/deploy"
DOCKER_CONFIG_DIR="$PROJECT_ROOT/.docker"

log() {
    echo "[stocktrade-prod] $1"
}

resolve_docker_compose() {
    if docker compose version >/dev/null 2>&1; then
        DOCKER_COMPOSE=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        DOCKER_COMPOSE=(docker-compose)
    else
        echo "未找到 docker compose / docker-compose" >&2
        exit 1
    fi
}

run_compose() {
    "${DOCKER_COMPOSE[@]}" -f docker-compose.yml --profile postgres --profile prod "$@"
}

main() {
    local action="${1:-up}"

    if ! command -v docker >/dev/null 2>&1; then
        echo "未找到 Docker，请先安装 Docker" >&2
        exit 1
    fi

    if [ ! -f "$DEPLOY_DIR/.env" ]; then
        echo "未找到 $DEPLOY_DIR/.env，请先准备生产环境配置" >&2
        exit 1
    fi

    mkdir -p "$DOCKER_CONFIG_DIR"
    export DOCKER_CONFIG="$DOCKER_CONFIG_DIR"

    resolve_docker_compose
    cd "$DEPLOY_DIR"

    case "$action" in
        up)
            log "启动生产服务栈..."
            run_compose up -d --build postgres redis backend nginx
            ;;
        stop)
            log "停止生产服务栈..."
            run_compose stop postgres redis backend nginx
            ;;
        restart)
            log "重启生产服务栈..."
            run_compose up -d --build postgres redis backend nginx
            ;;
        ps)
            run_compose ps
            ;;
        *)
            echo "用法: $0 [up|stop|restart|ps]" >&2
            exit 2
            ;;
    esac
}

main "$@"
