# StockTrader 生产部署指南

本指南使用 Cloudflare Tunnel + Docker Compose 部署到腾讯云服务器，无需单独开放公网 80/443 给应用容器。

## 前置条件

- 腾讯云服务器，推荐 Ubuntu 22.04
- 域名已接入 Cloudflare
- Cloudflare 账号
- 服务器已安装 `docker`、`docker compose`、`sqlite3`

## 1. 服务器准备

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
sudo apt update
sudo apt install -y sqlite3

sudo curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared
```

## 2. 拉取代码并配置环境变量

```bash
git clone <你的仓库地址> /opt/stocktrade
cd /opt/stocktrade

cp .env.example .env
mkdir -p data/db data/backups data/logs
```

`.env` 至少需要设置这些值：

```dotenv
TUSHARE_TOKEN=你的_tushare_token
SECRET_KEY=生产环境强随机字符串
ADMIN_DEFAULT_PASSWORD=生产环境管理员密码
ENVIRONMENT=production
BACKEND_CORS_ORIGINS=https://你的域名
```

## 3. 启动生产服务

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
curl http://127.0.0.1/health
```

预期结果：

- `backend` 和 `nginx` 容器都为 `Up`
- `curl http://127.0.0.1/health` 返回 JSON，包含 `status` 和 `database`

## 4. 配置 Cloudflare Tunnel

```bash
cloudflared tunnel login
cloudflared tunnel create stocktrade
cloudflared tunnel route dns stocktrade 你的域名
```

创建 `~/.cloudflared/config.yml`：

```yaml
tunnel: <Tunnel-ID>
credentials-file: /root/.cloudflared/<Tunnel-ID>.json

ingress:
  - hostname: 你的域名
    service: http://localhost:80
  - service: http_status:404
```

安装并启动服务：

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl restart cloudflared
curl https://你的域名/health
```

## 5. 配置数据库备份

```bash
chmod +x tools/backup.sh tools/restore.sh
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/stocktrade/tools/backup.sh >> /opt/stocktrade/data/logs/backup.log 2>&1") | crontab -
```

备份脚本会：

- 使用 `sqlite3 .backup` 做一致性备份
- 输出到 `data/backups/`
- 默认保留最近 7 份

## 运维命令

查看服务状态：

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f
```

更新应用：

```bash
cd /opt/stocktrade
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

恢复数据库：

```bash
ls -la data/backups/
./tools/restore.sh data/backups/stocktrade_20260430_020000.db
```

迁移 CSV 数据到数据库：

```bash
docker compose -f docker-compose.prod.yml exec backend python tools/migrate_csv_to_db.py
```

## 架构

```text
用户
  -> Cloudflare CDN
  -> Cloudflare Tunnel
  -> 服务器 localhost:80
  -> Nginx 容器
     -> 前端静态文件
     -> /api/* -> FastAPI 容器
     -> /ws/* -> FastAPI WebSocket
     -> /health -> FastAPI 健康检查
     -> /data/* -> FastAPI 静态数据目录
```
