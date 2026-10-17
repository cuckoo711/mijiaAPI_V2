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

正式发布与 Android 测试预发布完成 GitHub Release 后，会自动从该 Release 同步标题、完整说明、预发行状态和原附件到 Gitee，并核对下载 SHA-256。补同步既有版本时无需重新构建：

1. 在 Gitee 的“设置 → 私人令牌 → 生成新令牌”创建具有 `projects` 权限的令牌。
2. 在 GitHub 仓库 `Settings → Secrets and variables → Actions → New repository secret` 中保存为 `GITEE_TOKEN`。令牌值仅填入 Secret，不放进源码、命令参数或报告。
3. 进入 GitHub Actions 的 **Sync existing releases to Gitee**，选择 `main`，点击 **Run workflow**。`tag` 填某个已发布标签，或填 `all` 补齐全部正式版和预发行版；首次可勾选 `dry_run` 只检查清单。
4. 查看任务结果与 `gitee-release-sync-*` 报告。只有附件实际从 Gitee 下载后哈希一致，才记为该版同步通过。

已同步附件再次运行会核对后跳过；同名附件哈希不同、额外附件或标签 SHA 不符时停止，保留现有远端内容。先解决具体差异再重跑，不能把 Git 标签存在当作发行版附件已同步。

本机已有 `gh` 登录和 `GITEE_TOKEN` 环境变量时，也可执行：

```bash
python deploy/scripts/sync_gitee_releases.py --all --dry-run --report gitee-plan.json
python deploy/scripts/sync_gitee_releases.py --tag v3.9.1 --report gitee-sync.json
python deploy/scripts/sync_gitee_releases.py --all --report gitee-sync.json
```

`--dry-run` 不需要 Gitee 写入令牌；实际同步前必须先将源仓库的 `main` 与标签推到 Gitee，并确保标签指向相同对象。手动工作流会先完成这一步。`--all` 仅读取 GitHub 已发布的 Release，排除草稿；只有标签但没有 Release 的版本不会被另行创建。旧版附件可能较大，首次补齐需要下载、上传并下载校验；逐版报告会保留已完成进度，重跑可复用已校验的远端内容。

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
