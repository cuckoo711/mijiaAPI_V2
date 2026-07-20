# 部署与打包

本目录集中存放运行时部署与可执行文件打包相关资产。

## Docker

在仓库根目录执行：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

- 构建上下文为仓库根目录；`.dockerignore` 因此保留在根目录（Docker 要求）。
- 入口脚本：[`docker-entrypoint.sh`](docker-entrypoint.sh)（`gosu` 修正数据卷属主后降权）。
- 首次建管理员：compose 已设置 `MIJIA_BOOTSTRAP_ALLOW_PRIVATE=1`。

可选初始化：

```bash
docker compose -f deploy/docker-compose.yml run --rm mijia-server mijia-server init --admin admin
```

## systemd

见 [`mijia-server.service`](mijia-server.service) 与 [`mijia-server.env.example`](mijia-server.env.example)。

## 打包（PyInstaller）

```bash
# 推荐
python deploy/packaging/build.py

# 或
./deploy/packaging/build.sh
# Windows: deploy\packaging\build.bat
```

图标资源在 [`assets/`](assets/)；Windows 旁路启动脚本：[`packaging/start-server.bat`](packaging/start-server.bat)（检测 `configs/server/server.sqlite3`）。
