# 项目脚本说明

本目录包含项目维护和开发的实用脚本。

## 可用脚本

### 1. 清理脚本

用于清理项目中的缓存文件、构建产物和临时文件。

#### 使用方式

**方式一：使用 Makefile（推荐）**

```bash
# 清理缓存和临时文件
make clean

# 清理所有生成文件（包括覆盖率报告）
make clean-all

# 查看所有可用命令
make help
```

**方式二：使用 Shell 脚本**

```bash
# 运行清理脚本
./deploy/scripts/clean.sh

# 或者
bash deploy/scripts/clean.sh
```

**方式三：使用 Python 脚本**

```bash
# 运行清理脚本
uv run python deploy/scripts/clean.py

# 或者
python deploy/scripts/clean.py
```

#### 清理内容

清理脚本会删除以下内容：

1. **Python 缓存文件**
   - `__pycache__/` 目录
   - `*.pyc`, `*.pyo`, `*.pyd` 文件

2. **测试覆盖率文件**
   - `.coverage` 文件
   - `htmlcov/` 目录

3. **构建产物**
   - `dist/` 目录
   - `build/` 目录
   - `*.egg-info/` 目录

4. **工具缓存**
   - `.mypy_cache/` 目录
   - `.pytest_cache/` 目录

5. **临时文件**
   - `*.tmp` 文件
   - `*.log` 文件
   - `.DS_Store` 文件（macOS）
   - `Thumbs.db` 文件（Windows）

#### 可选清理

如果需要清理以下内容，请编辑脚本并取消相应注释：

- **IDE 配置**: `.idea/`, `.vscode/`
- **旧版本代码**: `mijiaAPI/`

### 2. 设备规格查看工具

查看米家设备的完整规格信息，包括所有属性和操作的详细说明。

```bash
# 交互式选择设备
uv run python deploy/scripts/show_device_spec.py

# 通过设备名称查看
uv run python deploy/scripts/show_device_spec.py "设备名称"

# 通过设备型号查看
uv run python deploy/scripts/show_device_spec.py "yeelink.light.lamp4"
```

### 3. Gitee Release 镜像

仓库 Secret `GITEE_TOKEN` 配置完成后，后续发版自动同步，无需手动双推、补传附件或在本机保存令牌。统一入口是 **Sync latest releases to Gitee**（`.github/workflows/sync-gitee-releases.yml`）：

- 正式构建与 Android 构建工作流成功完成时自动触发，覆盖 CI 使用 `GITHUB_TOKEN` 发布 Release 的情况。
- 在 GitHub 手工发布发行版或修改发行说明时自动触发。
- 每天北京时间 **03:37** 自动核对和补偿漏事件、暂时网络故障及稍后上传的附件；定时任务实际启动时间由 GitHub 调度决定。

每次从 GitHub 重新选择最多两个已发布、非草稿版本，按版本号的数字大小排序：

| 类别 | 标签与标记 | 选择规则 |
| --- | --- | --- |
| 正式版 | `vX.Y.Z`，`prerelease=false` | 最高正式版本号 |
| Android 测试版 | `vX.Y.Z-android-test.N`，`prerelease=true` | 最高版本号及测试序号，`test.10` 大于 `test.9` |

补发旧版本、普通 beta/RC、草稿和未发布标签不会替代上述选择。某一类尚未发布时只处理现有类别。每次只处理最新两类，已同步的历史发行版保留。

`build.yml` 与 `android.yml` 负责发布 GitHub Release，统一镜像工作流负责 Gitee，避免多个上传入口争用同一个版本。镜像只执行受信 `main` 的代码，拒绝来自 PR、fork、失败上游和普通分支的完成事件；只补齐所选发行标签，`main` 与完整标签镜像仍由 `mirror-gitee.yml` 负责。

同步标题、完整发行说明、预发行标记及全部原附件，包含可执行文件、APK、校验清单和验收报告。每个附件上传前核对 GitHub 大小与 SHA-256，上传后从 Gitee 下载复核；已有正确附件直接核对后复用。附件尚未上传到 GitHub 时会明确失败并稍后重试，不创建空的完整镜像。任务排队期间若版本已被更新版本取代，会跳过旧任务。

每个版本失败后最多自动尝试 3 次，间隔 30 秒；每次重新读取远端清单，补齐缺失附件。每天的核对还会继续补偿未完成版本。不同版本独立执行，一版失败不取消另一版。跨工作流串行同一同步入口，避免重复上传；同名附件哈希不同、额外附件或标签 SHA 不符会保留现场并报错，需按具体错误排查。

GitHub 托管运行器到 Gitee 的跨境上传可能较慢，CI 使用 curl，并为单文件预留最长两小时传输时间。只在实际下载校验通过后计为同步成功，结果保存为 `gitee-release-sync-<源发行版ID>-<运行ID>-<尝试次数>` 报告。

仅在排障时，可手动运行 **Sync latest releases to Gitee**；它仍只选择最新两类，唯一输入 `dry_run` 为 true 时只检查清单。正常发版由上述事件自动完成。

维护脚本的单版本检查示例（本机已有 `gh` 登录及 `GITEE_TOKEN` 环境变量）：

```bash
python deploy/scripts/sync_gitee_releases.py --tag v3.9.1 --latest-only --dry-run --report gitee-plan.json
python deploy/scripts/sync_gitee_releases.py --tag v3.9.1 --latest-only --report gitee-sync.json
```

`--dry-run` 不需要 Gitee 写入令牌。实际同步前，Gitee 必须已有对应标签，且标签对象与提交 SHA 均和 GitHub 一致；自动工作流会先完成所选标签同步。创建和更新都保留原附件，不自动重发失败的 multipart POST。

需要直接发布本地产物时，原有工具仍可使用：

```bash
export GITEE_TOKEN=...   # Gitee 私人令牌，需 projects 权限

uv run python deploy/scripts/publish_gitee_release.py \
  --tag v3.9.1 \
  --notes-file release-notes.md \
  --owner cuckoo711 \
  --repo mijiaAPI \
  dist/mijia-server-* dist/SHA256SUMS
```

要点：

- 环境变量 `GITEE_TOKEN` 必填，不会从命令行读取令牌。
- 默认仓库 `cuckoo711/mijiaAPI`（与 GitHub 的 `cuckoo711/mijiaAPI_V2` 名称不同）。
- 发布前须先同步对应标签；工具按 Gitee 已有标签的提交 SHA 创建 Release，不自动创建或移动标签。
- 可重跑：已存在的 Release 会复用；同名附件先删后传，避免重复。
- `--prerelease` 用于 Android 测试包等预发布。
- GitHub Actions 需在仓库 Secret 配置 `GITEE_TOKEN`；可用 `GITEE_OWNER` / `GITEE_REPO` 覆盖目标仓库。

## 其他 Makefile 命令

```bash
# 运行测试
make test

# 运行测试并生成覆盖率报告
make test-cov

# 格式化代码
make format

# 代码质量检查
make lint

# 类型检查
make type-check

# 安装依赖
make install

# 准备开发环境
make dev
```

## 注意事项

- 清理操作不可逆，请确保重要文件已备份
- 清理后需要重新运行测试以生成覆盖率报告
- IDE 配置文件默认不会被清理，如需清理请手动修改脚本

## 相关文档

- [示例代码](../../examples/README.md) - 完整的API使用示例
- [开发指南](../../docs/开发指南/01-开发环境.md) - 开发环境配置
- [使用指南](../../docs/使用指南/01-快速开始.md) - 快速开始指南
