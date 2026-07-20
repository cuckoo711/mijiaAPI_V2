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
