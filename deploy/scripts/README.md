# 项目脚本说明

## 1. 清理脚本

在仓库根目录运行：

```bash
uv run python deploy/scripts/clean.py --dry-run   # 预览
make clean                                     # 缓存与临时文件
make clean-all                                 # 另删根目录构建产物和覆盖率报告
```

无 Make 时直接运行 `uv run python deploy/scripts/clean.py`，加 `--all` 对应 `make clean-all`。`bash deploy/scripts/clean.sh` 是同一脚本的包装，参数原样透传。

| 范围 | 删除内容 |
|------|------|
| 默认 | `__pycache__/`、`*.pyc`、`*.pyo`、`*.pyd`、`.mypy_cache/`、`.pytest_cache/`、`*.tmp`、`*.log`、`.DS_Store`、`Thumbs.db` |
| 加 `--all` | 根目录 `dist/`、`build/`、`htmlcov/`、`*.egg-info/`、`*.egg`、`.coverage`、`.coverage.*` |
| 加 `--include-web-dist` | `web/dist/`，删除后需重新构建管理台 |

脚本跳过 `.git`、`.venv`、`node_modules` 和 IDE 配置目录。清理前用 `--dry-run` 检查清单，需保留的日志、报告和构建包应先备份。

## 2. 设备规格查看工具

```bash
uv run python deploy/scripts/show_device_spec.py                         # 交互选择
uv run python deploy/scripts/show_device_spec.py "设备名称"
uv run python deploy/scripts/show_device_spec.py "yeelink.light.lamp4"    # 设备型号
```

## 3. Gitee Release 镜像

在 GitHub 仓库 Secret 配置具备 `projects` 权限的 `GITEE_TOKEN` 后，**Sync latest releases to Gitee**（`.github/workflows/sync-gitee-releases.yml`）自动同步发行说明和附件。可用 `GITEE_OWNER` / `GITEE_REPO` 覆盖默认目标 `cuckoo711/mijiaAPI`。

触发条件：

- 正式版或 Android 构建工作流成功完成，包含使用 `GITHUB_TOKEN` 发布的 Release。
- 在 GitHub 发布发行版或修改发行说明。
- 每天北京时间 **03:37** 核对补偿；实际启动时间由 GitHub 调度决定。

每次选择最多两个已发布、非草稿版本，按版本号的数字大小排序：

| 类别 | 标签与标记 | 选择规则 |
| --- | --- | --- |
| 正式版 | `vX.Y.Z`，`prerelease=false` | 最高正式版本号 |
| Android 测试版 | `vX.Y.Z-android-test.N`，`prerelease=true` | 最高版本号及测试序号，`test.10` 大于 `test.9` |

普通 beta/RC、草稿及未发布标签不参与选择；缺少某一类时只处理现有类别。排队期间被新版本取代的任务会跳过，已同步的历史发行版保留。

`build.yml` 与 `android.yml` 发布 GitHub Release；镜像工作流只运行受信 `main` 代码，拒绝 PR、fork、失败上游及普通分支的完成事件。它补齐所选发行标签，`main` 与完整标签镜像由 `mirror-gitee.yml` 负责。

### 附件校验与故障处理

- 同步标题、完整发行说明、预发行标记及全部原附件，包括程序、APK、校验清单和检查报告。
- 上传前核对 GitHub 文件大小与 SHA-256，上传后从 Gitee 下载复核；已有正确附件直接复用。无附件的发行版会报错，等待附件补齐。
- 每个版本最多尝试 3 次，间隔 30 秒，每次重读远端清单；不同版本独立处理，定时任务继续补偿失败版本。同步入口串行运行。
- 同名附件哈希冲突、额外附件或标签 SHA 不符时中止并保留现场，不自动覆盖。
- CI 使用 curl，单文件传输超时为两小时；报告名为 `gitee-release-sync-<源发行版ID>-<运行ID>-<尝试次数>`。

排障时可手动运行 **Sync latest releases to Gitee**，`dry_run=true` 只检查清单，仍只选择上述最新两类。

### 单版本同步脚本

本机需已登录 `gh`；实际写入还需环境变量 `GITEE_TOKEN`。

```bash
python deploy/scripts/sync_gitee_releases.py --tag v3.9.1 --latest-only --dry-run --report gitee-plan.json
python deploy/scripts/sync_gitee_releases.py --tag v3.9.1 --latest-only --report gitee-sync.json
```

`--dry-run` 不需要 Gitee 写入令牌。实际同步前，Gitee 对应标签的对象和提交 SHA 均须与 GitHub 一致；自动工作流会先同步所选标签。脚本保留原附件，不自动重发失败的 multipart POST。

### 直接发布本地产物

```bash
export GITEE_TOKEN=...   # 私人令牌，需 projects 权限

uv run python deploy/scripts/publish_gitee_release.py \
  --tag v3.9.1 \
  --notes-file release-notes.md \
  --owner cuckoo711 \
  --repo mijiaAPI \
  dist/mijia-server-* dist/SHA256SUMS
```

此工具从环境变量读取令牌，按 Gitee 已有标签的提交 SHA 创建或复用 Release，不创建或移动标签；**重跑会删除并重传同名附件**。`--prerelease` 用于测试版。

## 相关文档

- [开发环境](../../docs/开发指南/01-开发环境.md)：依赖与 Makefile 命令。
- [部署与打包](../README.md)：部署、备份和发布。
- [示例代码](../../examples/README.md)：SDK 调用。
