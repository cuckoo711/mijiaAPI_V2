# 示例代码

本目录包含米家API SDK的完整示例代码，从基础到高级，涵盖所有主要功能。

## 📚 示例列表

### 基础示例

1. **[01_authentication.py](01_authentication.py)** - 认证和凭据管理（首次使用必读）
   - 二维码登录
   - 从文件加载凭据
   - 保存和管理凭据
   - 检查凭据有效性
   - 刷新过期凭据

2. **[02_quick_start.py](02_quick_start.py)** - 快速开始
   - 加载凭据
   - 获取家庭和设备列表
   - 基本的设备控制

3. **[03_device_control.py](03_device_control.py)** - 设备控制
   - 获取设备属性
   - 设置设备属性
   - 批量操作
   - 调用设备动作

4. **[04_device_spec.py](04_device_spec.py)** - 设备规格查询
   - 获取设备规格
   - 查看属性和操作列表
   - 使用中文翻译
   - 根据规格控制设备

5. **[05_scene_control.py](05_scene_control.py)** - 智能控制
   - 获取智能列表
   - 执行智能
   - 按家庭筛选智能

### 高级示例

6. **[06_batch_operations.py](06_batch_operations.py)** - 批量操作
   - 批量获取属性
   - 批量设置属性
   - 性能优化
   - 最佳实践

7. **[07_error_handling.py](07_error_handling.py)** - 错误处理
   - 认证错误处理
   - 设备错误处理
   - 网络错误处理
   - 综合错误处理策略

8. **[08_custom_translations.py](08_custom_translations.py)** - 自定义翻译
   - 使用默认翻译
   - 添加自定义翻译
   - 从文件加载翻译
   - 动态添加翻译

9. **[09_configuration.py](09_configuration.py)** - 配置管理
   - 使用默认配置
   - 从TOML文件加载
   - 使用环境变量
   - 配置优先级

10. **[10_cache_management.py](10_cache_management.py)** - 缓存管理
    - 理解自动缓存机制
    - 手动刷新缓存
    - 清空缓存
    - 缓存最佳实践

11. **[11_complete_workflow.py](11_complete_workflow.py)** - 完整工作流
    - 智能家居自动化
    - 设备监控
    - 自动控制
    - 实际应用场景

12. **[12_random_user_agent.py](12_random_user_agent.py)** - 随机User-Agent生成
    - 自动生成随机移动端User-Agent
    - 提高账号安全性
    - 避免被识别为自动化工具
    - 模拟真实移动设备访问

## 🚀 快速开始

### 前提条件

1. 已安装项目依赖：
   ```bash
   uv sync
   ```

### 首次使用（登录）

首次使用需要先登录米家账号：

```bash
# 运行认证示例，按提示扫码登录
uv run python examples/01_authentication.py
```

登录成功后，凭据会自动保存到 `configs/credential.json`，后续使用无需重复登录。

> API Server 与 SDK 现已统一使用 `configs/` 作为默认数据目录；旧版项目根目录下的 `.mijia/` 会在 Server 启动时迁移并删除。

### 运行示例

```bash
# 运行任意示例
uv run python examples/02_quick_start.py
uv run python examples/03_device_control.py
# ... 其他示例
```

## 📖 学习路径

### 新手入门

1. 从 `01_authentication.py` 开始，完成首次登录
2. 运行 `02_quick_start.py`，了解基本用法
3. 学习 `03_device_control.py`，掌握设备控制

### 进阶学习

4. 查看 `04_device_spec.py`，理解设备规格
4. 学习 `05_scene_control.py`，掌握智能控制
6. 优化 `06_batch_operations.py`，提升性能

### 高级应用

7. 研究 `07_error_handling.py`，学习错误处理
8. 使用 `08_custom_translations.py`，自定义翻译
9. 配置 `09_configuration.py`，优化应用设置
10. 学习 `10_cache_management.py`，管理缓存
11. 参考 `11_complete_workflow.py`，构建完整应用

## 💡 使用提示

### 首次登录

首次使用时需要登录米家账号：

```bash
# 运行认证示例
uv run python examples/01_authentication.py
```

按照提示使用米家APP扫描二维码即可完成登录。登录成功后：
- 凭据默认保存到 `configs/credential.json`（加密落盘）
- 凭据有效期约7天
- 后续使用会自动加载凭据，无需重复登录

### 凭据管理

凭据文件位置：
- 默认：`configs/credential.json`
- 可通过配置文件或 `MIJIA_CREDENTIAL_PATH` 自定义

凭据过期后需要重新登录：
```bash
# 删除旧凭据
rm configs/credential.json

# 重新登录
uv run python examples/01_authentication.py
```

### 设备规格

使用设备前，建议先查看设备规格：

```bash
# 查看设备规格
python deploy/scripts/show_device_spec.py <device_model>

# 或交互式选择
python deploy/scripts/show_device_spec.py
```

### 错误处理

所有示例都包含基本的错误处理，实际应用中应该：

- 捕获具体的异常类型
- 提供清晰的错误信息
- 实现重试机制
- 记录错误日志

## 🔗 相关文档

- [快速开始](../docs/使用指南/01-快速开始.md)
- [高级用法](../docs/使用指南/02-高级用法.md)
- [API参考](../docs/API参考/01-API客户端.md)
- [异常处理](../docs/API参考/03-异常处理.md)
- [设备规格翻译](../docs/使用指南/05-设备规格翻译.md)

## 🤝 贡献示例

欢迎贡献新的示例！请确保：

1. 代码清晰易懂，包含详细注释
2. 遵循项目代码规范
3. 包含错误处理
4. 更新本 README 文件

## ⚠️ 注意事项

1. **安全性**：不要在示例代码中硬编码用户名、密码或凭据
2. **设备安全**：控制设备前请确认操作的安全性
3. **频率限制**：避免过于频繁的API调用
4. **测试环境**：建议先在测试设备上验证代码

## 📝 常见问题

### Q: 示例运行失败，提示凭据文件不存在？

A: 请先运行 `examples/01_authentication.py` 进行登录。

### Q: 如何重新登录？

A: 删除凭据文件后重新运行认证示例：
```bash
rm configs/credential.json
uv run python examples/01_authentication.py
```

### Q: 如何找到设备的 siid 和 piid？

A: 使用 `04_device_spec.py` 或 `deploy/scripts/show_device_spec.py` 查看设备规格。

### Q: 批量操作有数量限制吗？

A: 建议每批不超过50个请求，大量操作应分批处理。

### Q: 如何调试示例代码？

A: 可以设置日志级别为 DEBUG 查看详细信息：

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

更多信息请参考[项目文档](../docs/README.md)。
