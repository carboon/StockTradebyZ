自行抓取数据的方式：
./deploy/scripts/start.sh update-latest


验证：
  TOKEN=$(
    curl -s http://127.0.0.1:8080/api/v1/auth/login \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"admin123"}' \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])'
  )

  curl -s http://127.0.0.1:8080/api/v1/analysis/tomorrow-star/freshness \
    -H "Authorization: Bearer $TOKEN"


  1. 确保 Docker 服务平时就是用你现有方式启动的，比如：

  ./start.sh

  或

  ./deploy/scripts/start.sh prod --build

  2. 把 systemd 文件安装到宿主机：

  sudo cp deploy/systemd/stocktrade-background-update.service /etc/systemd/system/
  sudo cp deploy/systemd/stocktrade-background-update.timer /etc/systemd/system/
  sudo systemctl daemon-reload

  3. 启用定时器：

  sudo systemctl enable --now stocktrade-background-update.timer

  4. 查看定时器是否生效：

  systemctl list-timers | grep stocktrade-background-update

  5. 如果你想立即手动跑一次：

  sudo systemctl start stocktrade-background-update.service

  6. 查看执行状态：

  sudo systemctl status stocktrade-background-update.service
  sudo systemctl status stocktrade-background-update.timer

  现在的定时规则

  当前 timer 默认是：

  - 工作日 18:30
  - 随机延迟最多 10 分钟
  - 如果机器当时关机，开机后会补跑一次

  对应内容是：

  OnCalendar=Mon..Fri *-*-* 18:30:00
  RandomizedDelaySec=10m
  Persistent=true

  资源限制还在不在

  还在。现在仍然是 systemd + cgroup 限制资源，限制作用在这个“更新任务进程”上。

  当前 service 里有：

  - CPUQuota=35%
  - MemoryMax=2G
  - Nice=10
  - IOSchedulingClass=idle
  - IOSchedulingPriority=7
  - TasksMax=128

  日志在哪里

  主业务日志：

  data/logs/async_latest_trade_day_update.log

  systemd 标准输出：

  data/logs/systemd-background-update.out.log

  systemd 标准错误：

  data/logs/systemd-background-update.err.log

  和之前相比，最大的变化

  不再需要你为 systemd 单独改宿主机数据库地址。
  因为它现在不是在宿主机直连数据库，而是进入 backend 容器执行，容器内部继续使用 postgres:5432 就可以。

  当前 service 实际含义

  现在这份 deploy/systemd/stocktrade-background-update.service 的关键执行行是：

  ExecStart=/Volumes/DATA/StockTradebyZ/deploy/scripts/run_background_update.sh

  也就是说，systemd 不再直接跑 Python，而是跑这个 Docker 包装脚本。
