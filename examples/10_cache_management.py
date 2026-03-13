#!/usr/bin/env python3
"""示例 10：缓存管理

演示如何使用和管理缓存：
- 理解自动缓存机制
- 手动刷新缓存
- 清空缓存
- 查看缓存统计
- 缓存最佳实践
"""

import sys
import time
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mijiaAPI_V2 import create_api_client_from_file


def example_auto_cache():
    """示例：自动缓存机制"""
    print("=== 方式1：自动缓存机制 ===\n")
    
    api = create_api_client_from_file()
    homes = api.get_homes()
    
    if not homes:
        print("未找到任何家庭")
        return
    
    home = homes[0]
    
    print("第一次获取设备列表（从API）:")
    start_time = time.time()
    devices1 = api.get_devices(home.id)
    elapsed1 = time.time() - start_time
    print(f"  ✓ 获取 {len(devices1)} 个设备")
    print(f"  耗时: {elapsed1:.10f}秒")
    print()
    
    print("第二次获取设备列表（从缓存）:")
    start_time = time.time()
    devices2 = api.get_devices(home.id)
    elapsed2 = time.time() - start_time
    print(f"  ✓ 获取 {len(devices2)} 个设备")
    print(f"  耗时: {elapsed2:.10f}秒")
    print()
    
    if elapsed1 > 0:
        speedup = elapsed1 / elapsed2 if elapsed2 > 0 else float('inf')
        print(f"✓ 缓存加速: {speedup:.5f}倍")
    print()


def example_refresh_cache():
    """示例：刷新缓存"""
    print("=== 方式2：刷新缓存 ===\n")
    
    api = create_api_client_from_file()
    homes = api.get_homes()
    
    if not homes:
        print("未找到任何家庭")
        return
    
    home = homes[0]
    
    # 第一次获取（会被缓存）
    print("第一次获取设备列表:")
    devices1 = api.get_devices(home.id)
    print(f"  ✓ 获取 {len(devices1)} 个设备")
    print()
    
    # 刷新特定家庭的缓存
    print("刷新特定家庭的缓存:")
    api.refresh_cache(home_id=home.id)
    print("  ✓ 缓存已刷新")
    print()
    
    # 再次获取（会从API重新获取）
    print("刷新后再次获取:")
    devices2 = api.get_devices(home.id)
    print(f"  ✓ 获取 {len(devices2)} 个设备")
    print()


def example_clear_cache():
    """示例：清空缓存"""
    print("=== 方式3：清空缓存 ===\n")
    
    api = create_api_client_from_file()
    homes = api.get_homes()
    
    if not homes:
        print("未找到任何家庭")
        return
    
    # 获取一些数据（会被缓存）
    print("获取数据（会被缓存）:")
    for home in homes[:2]:
        devices = api.get_devices(home.id)
        print(f"  - {home.name}: {len(devices)} 个设备")
    print()
    
    # 清空当前用户的所有缓存
    print("清空当前用户的所有缓存:")
    api.refresh_cache()  # 不传 home_id 则清空所有
    print("  ✓ 所有缓存已清空")
    print()
    
    # 清空所有用户的缓存（谨慎使用）
    print("清空所有用户的缓存（谨慎使用）:")
    api.clear_all_cache()
    print("  ✓ 全局缓存已清空")
    print()


def example_cache_behavior():
    """示例：缓存行为"""
    print("=== 方式4：缓存行为 ===\n")
    
    api = create_api_client_from_file()
    homes = api.get_homes()
    
    if not homes:
        print("未找到任何家庭")
        return
    
    home = homes[0]
    devices = api.get_devices(home.id)
    
    if not devices:
        print("未找到任何设备")
        return
    
    device = devices[0]
    
    print("缓存的数据类型:")
    print("  1. 家庭列表 - TTL: 300秒（5分钟）")
    print("  2. 设备列表 - TTL: 300秒（5分钟）")
    print("  3. 设备属性 - TTL: 30秒（状态变化快）")
    print("  4. 设备规格 - TTL: 3600秒（1小时）")
    print()
    
    print("缓存失效场景:")
    print("  1. 控制设备后，该设备的缓存会自动失效")
    print("  2. 批量操作后，相关设备的缓存会自动失效")
    print("  3. 手动调用 refresh_cache() 刷新")
    print("  4. 缓存过期（超过TTL）")
    print()
    
    # 演示控制设备后缓存失效
    print("演示：控制设备后缓存自动失效")
    print(f"  设备: {device.name}")
    
    # 注意：这里只是演示，实际控制可能失败
    # try:
    #     api.control_device(device.did, siid=2, piid=1, value=True)
    #     print("  ✓ 设备控制成功，相关缓存已自动失效")
    # except Exception as e:
    #     print(f"  ✗ 控制失败: {e}")
    
    print("  （为避免实际控制设备，此处省略执行）")
    print()


def example_cache_best_practices():
    """示例：缓存最佳实践"""
    print("=== 方式5：缓存最佳实践 ===\n")
    
    print("最佳实践：")
    print()
    
    print("1. 信任自动缓存")
    print("   - SDK 会自动缓存常用数据")
    print("   - 控制设备后会自动失效相关缓存")
    print("   - 大多数情况下无需手动管理")
    print()
    
    print("2. 何时手动刷新缓存")
    print("   - 设备列表在其他地方被修改（添加/删除设备）")
    print("   - 设备状态被其他应用改变")
    print("   - 需要确保获取最新数据")
    print()
    
    print("3. 性能优化")
    print("   - 批量操作优于单个操作（减少缓存失效）")
    print("   - 避免频繁刷新缓存")
    print("   - 合理设置缓存TTL（通过配置文件）")
    print()
    
    print("4. 调试技巧")
    print("   - 遇到数据不一致时，先尝试刷新缓存")
    print("   - 使用 clear_all_cache() 清空所有缓存")
    print("   - 检查缓存配置（configs/mijiaAPI.toml）")
    print()
    
    print("5. 配置缓存TTL")
    print("   在 configs/mijiaAPI.toml 中配置:")
    print("   ```toml")
    print("   [cache]")
    print("   device_list_ttl = 300      # 设备列表缓存5分钟")
    print("   device_property_ttl = 30   # 设备属性缓存30秒")
    print("   device_spec_ttl = 3600     # 设备规格缓存1小时")
    print("   ```")
    print()


def example_cache_scenarios():
    """示例：实际应用场景"""
    print("=== 方式6：实际应用场景 ===\n")
    
    print("场景1：定时监控脚本")
    print("```python")
    print("# 每次运行前刷新缓存，确保数据最新")
    print("api = create_api_client_from_file()")
    print("api.refresh_cache()")
    print("devices = api.get_devices(home_id)")
    print("# 监控设备状态...")
    print("```")
    print()
    
    print("场景2：交互式应用")
    print("```python")
    print("# 首次加载时获取数据（会被缓存）")
    print("devices = api.get_devices(home_id)")
    print()
    print("# 用户点击刷新按钮时")
    print("api.refresh_cache(home_id=home_id)")
    print("devices = api.get_devices(home_id)")
    print("```")
    print()
    
    print("场景3：批量处理")
    print("```python")
    print("# 批量操作前清空缓存")
    print("api.refresh_cache()")
    print()
    print("# 批量控制设备")
    print("for device in devices:")
    print("    api.control_device(device.did, ...)")
    print()
    print("# 操作完成后刷新缓存")
    print("api.refresh_cache()")
    print("```")
    print()
    
    print("场景4：多用户环境")
    print("```python")
    print("# 用户切换时清空缓存")
    print("api.clear_all_cache()")
    print()
    print("# 使用新凭据")
    print("api.update_credential(new_credential)")
    print("```")
    print()


def main():
    """主函数"""
    print("=" * 60)
    print("示例 10：缓存管理")
    print("=" * 60)
    print()
    
    example_auto_cache()
    example_refresh_cache()
    example_clear_cache()
    example_cache_behavior()
    example_cache_best_practices()
    example_cache_scenarios()
    
    print("=" * 60)
    print("缓存管理总结：")
    print("1. SDK 自动缓存常用数据，提升性能")
    print("2. 控制设备后会自动失效相关缓存")
    print("3. 使用 refresh_cache() 手动刷新")
    print("4. 使用 clear_all_cache() 清空所有缓存")
    print("5. 通过配置文件调整缓存TTL")
    print("=" * 60)


if __name__ == "__main__":
    main()
