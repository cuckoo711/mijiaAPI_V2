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

宿主回环连接在容器内表现为 Docker bridge 私网来源。Compose 默认的 `MIJIA_BOOTSTRAP_ALLOW_PRIVATE=1` 仅对尚无管理员的首页、静态资源、初始化状态和首次创建入口提供例外，其他 API 仍按网络策略拒绝。第一次通过私网创建管理员会在同一事务启用 `ALLOW_LAN_ACCESS`，使后续登录可用；不会启用 `ALLOW_PUBLIC_ACCESS`。如果实例已有管理员，该变量不改变访问策略。

```bash
docker compose -f deploy/docker-compose.yml run --rm mijia-server mijia-server init --admin admin --allow-lan
```

### 配置端口和安全选项

Compose 默认只监听本机。需要局域网访问时，在 **`deploy/` 目录**（compose 文件旁边）创建未提交的 `.env`：

> `.env` 必须和 compose 文件放在一起。Compose 查找 `.env` 的目录依次是
> `--project-directory`、第一个 `-f` 指定的 compose 文件所在目录、最后才是当前目录。
> 用 `-f deploy/docker-compose.yml` 启动时该目录就是 `deploy/`，
> 放在仓库根目录的 `.env` 不会被读取，`MIJIA_BIND_ADDRESS` 会静默回落到 `127.0.0.1`。

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

将绑定地址改为 `0.0.0.0` 后，建议关闭网络首次创建入口，先执行容器内 `init --admin admin --allow-lan` 明确创建管理员并启用局域网访问策略。

容器内 CLI 默认保留关闭局域网访问的策略。Docker 端口发布需要显式增加 `--allow-lan`；已有管理员但关闭了该策略时，也可执行 `docker compose -f deploy/docker-compose.yml run --rm mijia-server mijia-server init --allow-lan` 恢复宿主浏览器访问。该操作不会启用公网策略。

### 运行集成验证

```bash
python tests/docker/smoke.py --image mijia-server:latest --report docker-smoke-report.json
```

脚本使用已构建镜像创建隔离的随机名称容器、回环端口和数据/备份/恢复卷。它从宿主 HTTP 验证首次创建、管理员 Cookie 与 CSRF、API Key 创建/启停/轮换/撤销、restart 与 recreate 持久化，并将停机后的完整数据卷备份到新卷恢复。假米家凭据只用于核对加密文件和 `.credential_key` 配套恢复，不连接米家云或控制物理设备。

脚本输出不含密码、Cookie、API Key 或米家凭据的 JSON 报告，并只清理它创建的临时资源。CI 的 Docker job 会运行该脚本；镜像构建成功不会单独算作运行验证通过。

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

应将整个卷作为同一份备份恢复，尤其是 `credential.json` 与 `.credential_key`。若使用 `MIJIA_CREDENTIAL_SECRET`，还必须保留原来的部署密钥配置；卷备份不会包含外部环境变量。恢复后先确认管理员登录、Key 状态、账号身份和配置，再开放业务入口。

### 从旧卷名迁移（仅影响 v3.7.3 及更早已部署的实例）

早期 compose 文件没有显式声明 project name 和卷名，Compose 会用 project directory
的目录名作前缀，实际卷名是 **`deploy_mijia-data`**，而文档里一直写的是 `mijia-data`。
两个后果：

- 上面的备份命令会挂到一个**新建的空卷**上，备份出来的是空文件。
- 现在加了显式卷名 `mijia-data`，直接 `up -d` 会挂空卷，看起来像数据丢了
  （旧卷仍在，没有被删除）。

先确认自己是否有旧卷：

```bash
docker volume ls --filter name=mijia-data
```

只看到 `mijia-data` 说明是全新部署，无需处理。若看到 `deploy_mijia-data`，按以下步骤搬迁：

```bash
# 1. 停掉旧项目（此时项目名还是 deploy，需用 -p 指定）
docker compose -p deploy -f deploy/docker-compose.yml down

# 2. 建新卷并整卷复制数据
docker volume create mijia-data
docker run --rm -v deploy_mijia-data:/from -v mijia-data:/to \
  alpine sh -c "cd /from && cp -a . /to"

# 3. 用新配置启动并核对
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml logs -f mijia-server
```

确认管理台能正常登录、设备列表齐全之后，再删除旧卷：

```bash
docker volume rm deploy_mijia-data
```

> 第 3 步确认无误前不要执行 `docker volume rm`，删除卷不可恢复。

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

