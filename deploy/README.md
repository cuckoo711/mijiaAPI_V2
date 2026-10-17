# 部署与打包

本目录集中存放 Docker、systemd、可执行文件打包和运维脚本。

源码可从 GitHub 或 Gitee 镜像克隆（国内推荐 Gitee，目录名为 `mijiaAPI`）：

```bash
git clone https://github.com/cuckoo711/mijiaAPI_V2.git
# 或 https://gitee.com/cuckoo711/mijiaAPI.git
```

二进制与 APK 见 [GitHub Release](https://github.com/cuckoo711/mijiaAPI_V2/releases) / [Gitee Release](https://gitee.com/cuckoo711/mijiaAPI/releases)。

使用边界见[免责声明](../DISCLAIMER.md)。

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
- `/data/audit-pending/`：审计补写队列及异常记录；整卷备份时一并保留

Docker 内置 `/healthz` 存活检查，依赖就绪另查 `/readyz`。查看容器状态和日志：

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

Compose 默认只监听本机。需要局域网访问时，创建未提交的 `deploy/.env`，并在启动命令中用 `--env-file` 指定：

```dotenv
MIJIA_BIND_ADDRESS=0.0.0.0
MIJIA_HOST_PORT=8123
MIJIA_BOOTSTRAP_ALLOW_PRIVATE=0
MIJIA_SERVER_LOG_LEVEL=INFO
# 可选；不设置时使用持久化的 /data/.credential_key
# MIJIA_CREDENTIAL_SECRET=replace-with-a-long-random-secret
```

在仓库根目录重新创建服务：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
```

将绑定地址改为 `0.0.0.0` 后，建议关闭网络首次创建入口，先执行容器内 `init --admin admin --allow-lan` 明确创建管理员并启用局域网访问策略。

容器内 CLI 默认保留关闭局域网访问的策略。Docker 端口发布需要显式增加 `--allow-lan`；已有管理员但关闭了该策略时，也可执行 `docker compose -f deploy/docker-compose.yml run --rm mijia-server mijia-server init --allow-lan` 恢复宿主浏览器访问。该操作不会启用公网策略。

### 运行集成验证

```bash
python tests/docker/smoke.py --image mijia-server:latest --report docker-smoke-report.json
```

脚本创建隔离容器、回环端口和临时卷，从宿主 HTTP 检查首次创建、Cookie 与 CSRF、API Key 生命周期、重启持久化及整卷备份恢复。使用虚构米家凭据检查加密文件和 `.credential_key` 配套恢复，不连接米家云。输出脱敏 JSON 报告，只清理本次创建的资源；CI 的 Docker job 运行同一脚本。

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

旧配置的默认卷名为 `deploy_mijia-data`，新配置显式使用 `mijia-data`。未迁移就启动或执行新卷的备份命令，会挂载新建的空卷；原数据仍在旧卷。

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

需要 Python、uv、Node.js 和 npm。在仓库根目录执行：

```bash
uv sync
uv pip install pyinstaller pillow
uv run python deploy/packaging/build.py
```

脚本构建前端并生成当前平台的单文件程序，输出到 `dist/`。也可分步执行：

```bash
cd web && npm ci && npm run build && cd ..
uv run pyinstaller --clean --noconfirm deploy/packaging/mijia-server.spec
```

图标资源在 [`assets/`](assets/)；Windows 旁路启动脚本：[`packaging/start-server.bat`](packaging/start-server.bat)（检测 `configs/server/server.sqlite3`）。

## 自动发布

推送 `vX.Y.Z` 标签到 GitHub 后，[正式版工作流](../.github/workflows/build.yml) 构建桌面程序和 Android 测试 APK，完成各平台运行检查后创建 GitHub Release，附带程序、`SHA256SUMS` 和检查报告。标签版本须与 `pyproject.toml` 一致。

`vX.Y.Z-android-test.N` 标签单独发布 Android 测试版，详见 [Android 发布说明](../android/README.md#github-自动构建与发布)。最新正式版和最新 Android 测试版的说明与全部附件自动同步至 Gitee；触发规则、令牌配置和排障见 [Gitee Release 镜像](scripts/README.md#3-gitee-release-镜像)。`main` 和 `v*` 标签由 [仓库镜像工作流](../.github/workflows/mirror-gitee.yml) 同步。

## 运维脚本

见 [`scripts/`](scripts/)：`clean`、`extract_release_notes`、`publish_gitee_release`、`show_device_spec`。

## 依赖就绪与审计恢复

从允许的来源分别检查存活与依赖就绪（两者仍受全站网络 ACL 约束）：

```bash
curl -i http://127.0.0.1:8123/healthz
curl -i http://127.0.0.1:8123/readyz
```

`/healthz` 正常返回 200、`{"status":"ok","version":"..."}`。`/readyz` 检查 SQLite 回滚写入、前端 `web_dist_dir/index.html` 和审计状态；全部通过返回 200、`status=ready`，否则返回 503、`status=degraded`，`checks.sqlite/frontend/audit` 指出对应依赖。若读取存储配置即失败，返回标准 503 `STORAGE_UNAVAILABLE` 错误对象。这些检查不探测米家授权、真实设备在线或动作效果。

控制响应的 `X-Operation-ID` 对应一次操作的审计事件；`X-Audit-Delivery` 为 `stored`（已写 SQLite）、`queued`（已存文件队列）、`unavailable`（两处都未能保存）。审计失败不会把已经返回的控制结果改成失败，也不能通过重新执行设备操作来补日志。回执可从管理员 `GET /api/admin/operations/{operation_id}` 查询；API Key 可从 `GET /api/v1/operations/{operation_id}` 查询自己发起的操作，须使用仍有效的同一个 Key。回执缺失不证明控制没有执行。

审计文件队列在 `<data_dir>/audit-pending/`（Docker 为 `/data/audit-pending/`）；数据库不可写但队列保存成功时，事件仍可恢复。启动时尝试补写，运行中约每 10 秒自动尝试，每轮默认最多成功补写 100 条。管理员可在「日志与审计」点「补写审计」，或使用带 Cookie 与 `X-CSRF-Token` 的 `POST /api/admin/audit/replay`。补写仅写审计数据库，保持事件 ID 并去重，绝不重新执行属性、动作或场景。

`GET /api/admin/audit/health` 返回三个整数计数；补写响应另含 `delivered`：

| 字段 | 运维含义与处理 |
|------|----------------|
| `pending` | 可待补写的 `.json` 文件数量；修复存储后可等待自动补写或显式补写 |
| `invalid` | 异常/隔离 `.invalid` 记录数量；队列检查失败也报告异常，需检查日志与队列文件 |
| `unavailable` | **本进程未能保存的事件历史计数**；这些完全未保存事件不能补写，须排查日志、权限、磁盘和 SQLite/队列存储 |

`unavailable` 不表示当前目录必然不可访问，不阻止已有 `pending` 的补写，也不会随成功补写清零。即使存储已恢复，`/readyz` 仍会因该历史计数返回 503。应先保留并核对操作 ID、响应头、日志和队列证据，处理存储故障与异常记录；确认排查完成后再重启服务重置进程计数，例如：

```bash
docker compose -f deploy/docker-compose.yml restart mijia-server
```

重启不会恢复丢失的审计事件；重启后再次检查 `/readyz` 与管理员审计健康接口。

控制出现 `409 EXECUTION_UNKNOWN`（`retry_safe=false`）或客户端丢失写入响应时，不得自动重试。先查询最新属性、查操作回执并核对实际设备/场景效果，再明确决定新的请求。审计自动补写只重试记录保存，不重试设备操作；读取请求和确认尚未发送控制的连接失败仍可按 SDK 策略重试。

管理员手动操作接口与参数见 [API Server 开发启动](../docs/开发指南/05-API-Server-开发启动.md#管理员手动控制与操作回执)。

