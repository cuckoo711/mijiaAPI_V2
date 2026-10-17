# 示例代码

运行前先执行 `uv sync`，再按下方步骤扫码登录。

## 示例列表

**基础**

1. [01_authentication.py](01_authentication.py) - 认证与凭据
2. [02_quick_start.py](02_quick_start.py) - 快速开始
3. [03_device_control.py](03_device_control.py) - 设备控制与批量操作
4. [04_device_spec.py](04_device_spec.py) - 设备规格查询与中文翻译
5. [05_scene_control.py](05_scene_control.py) - 场景执行

**进阶**

6. [06_batch_operations.py](06_batch_operations.py) - 批量读写与性能
7. [07_error_handling.py](07_error_handling.py) - 错误处理
8. [08_custom_translations.py](08_custom_translations.py) - 自定义翻译
9. [09_configuration.py](09_configuration.py) - 配置管理
10. [10_cache_management.py](10_cache_management.py) - 缓存管理
11. [11_complete_workflow.py](11_complete_workflow.py) - 完整工作流
12. [12_random_user_agent.py](12_random_user_agent.py) - 随机 User-Agent

## 快速开始

```bash
# 1. 首次登录（扫码），凭据保存到 configs/credential.json
uv run python examples/01_authentication.py

# 2. 运行其它示例
uv run python examples/02_quick_start.py
```

默认数据目录为 `configs/`。凭据过期后可尝试 `refresh_credential()`，失败时重新扫码登录。

查看设备规格（siid / piid）：

```bash
python deploy/scripts/show_device_spec.py <device_model>
```

调试时可将日志级别设为 `DEBUG`。不要硬编码账号或凭据；控制设备前确认操作安全。

## 相关文档

- [快速开始](../docs/使用指南/01-快速开始.md)
- [API 参考](../docs/API参考/01-API客户端.md)
- [异常处理](../docs/API参考/03-异常处理.md)
- [文档索引](../docs/README.md)
