# 部署与打包

本目录集中存放 Docker、systemd、可执行文件打包和运维脚本。

## Docker Compose

### 快速启动

在仓库根目录执行：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

默认发布到 `127.0.0.1:8123`，启动后访问 `http://127.0.0.1:8123`。镜像会在本地构建，运行数据保存在命名卷 `mijia-data`，包括：

- `/data/server/server.sqlite3`：管理台数据库
- `/data/credential.json`：米家凭据
- `/data/.credential_key`：凭据加密密钥（未设置 `MIJIA_CREDENTIAL_SECRET` 时自动生成）
- `/data/cache/`：SDK 磁盘缓存

`deploy/Dockerfile` 内置健康检查，容器状态可用以下命令查看：

```bash
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f mijia-server
```

### 首次创建管理员

默认回环绑定下可以直接打开管理台完成首次创建。也可以使用容器内 CLI：

```bash
docker compose -f deploy/docker-compose.yml run --rm mijia-server mijia-server init --admin admin
```

### 配置端口和安全选项

Compose 默认只监听本机。需要局域网访问时，在仓库根目录创建未提交的 `.env`：

```dotenv
MIJIA_BIND_ADDRESS=0.0.0.0
MIJIA_HOST_PORT=8123
MIJIA_BOOTSTRAP_ALLOW_PRIVATE=0
MIJIA_SERVER_LOG_LEVEL=INFO
# 可选；不设置时使用持久化的 /data/.credential_key
# MIJIA_CREDENTIAL_SECRET=replace-with-a-long-random-secret
```

然后重新创建服务：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

将绑定地址改为 `0.0.0.0` 后，不建议再允许通过网络首次建管理员；先执行容器内 `init --admin`，再按需在管理台开启局域网访问策略。

### 停止、更新和备份

```bash
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml up -d --build
```

停止容器不会删除 `mijia-data`。备份前建议先停止服务，然后将 `<本机备份目录>` 替换为实际目录：

```bash
docker run --rm -v mijia-data:/data -v <本机备份目录>:/backup alpine tar czf /backup/mijia-data.tar.gz -C /data .
```

恢复时先停止服务，再解压到卷中：

```bash
docker run --rm -v mijia-data:/data -v <本机备份目录>:/backup alpine tar xzf /backup/mijia-data.tar.gz -C /data
```

- 构建上下文是仓库根目录，根目录 `.dockerignore` 会排除测试、文档、前端依赖和打包产物。
- 入口脚本是 [`docker-entrypoint.sh`](docker-entrypoint.sh)，启动时修正数据卷属主并降权到 `mijia` 用户。

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

## 运维脚本

见 [`scripts/`](scripts/)：`clean`、`extract_release_notes`、`show_device_spec`。

