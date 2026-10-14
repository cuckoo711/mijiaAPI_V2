#!/usr/bin/env python3
"""示例07：错误处理

演示如何正确处理各种异常：
- 认证错误
- 设备错误
- 网络错误
- 参数验证错误
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mijiaAPI_V2 import create_api_client_from_file
from mijiaAPI_V2.domain.exceptions import (
    MijiaAPIException,
    AuthenticationError,
    TokenExpiredError,
    DeviceError,
    DeviceOfflineError,
    DeviceNotFoundError,
    NetworkError,
    TimeoutError,
    ValidationError,
)


def example_authentication_error():
    """示例：处理认证错误"""
    print("=== 示例1：认证错误处理 ===\n")
    
    try:
        # 尝试从不存在的文件加载凭据
        api = create_api_client_from_file(credential_path=Path("nonexistent.json"))
        homes = api.get_homes()
        
    except FileNotFoundError:
        print("✗ 凭据文件不存在")
        print("  解决方案：请先登录并保存凭据")
        
    except TokenExpiredError:
        print("✗ Token已过期")
        print("  解决方案：重新登录获取新的Token")
        
    except AuthenticationError as e:
        print(f"✗ 认证失败: {e.message}")
        print("  解决方案：检查凭据是否正确")
    
    print()


def example_device_error():
    """示例：处理设备错误"""
    print("=== 示例2：设备错误处理 ===\n")
    
    try:
        api = create_api_client_from_file()
        
        # 尝试控制不存在的设备
        api.control_device("invalid_device_id", siid=2, piid=1, value=True)
        
    except DeviceNotFoundError:
        print("✗ 设备不存在")
        print("  解决方案：检查设备ID是否正确")
        
    except DeviceOfflineError:
        print("✗ 设备离线")
        print("  解决方案：确保设备在线后重试")
        
    except DeviceError as e:
        print(f"✗ 设备错误: {e.message}")
        print(f"  错误码: {e.code}")
        print("  解决方案：检查设备状态和参数")
    
    except FileNotFoundError:
        print("✗ 凭据文件不存在（跳过此示例）")
    
    print()


def example_network_error():
    """示例：处理网络错误"""
    print("=== 示例3：网络错误处理 ===\n")
    
    try:
        api = create_api_client_from_file()
        
        # 模拟网络请求
        homes = api.get_homes()
        print(f"✓ 请求成功，找到 {len(homes)} 个家庭")
        
    except TimeoutError:
        print("✗ 请求超时")
        print("  解决方案：检查网络连接，稍后重试")
        
    except NetworkError as e:
        print(f"✗ 网络错误: {e.message}")
        print("  解决方案：检查网络连接")
    
    except FileNotFoundError:
        print("✗ 凭据文件不存在（跳过此示例）")
    
    print()


def example_validation_error():
    """示例：处理参数验证错误"""
    print("=== 示例4：参数验证错误处理 ===\n")
    
    try:
        api = create_api_client_from_file()
        homes = api.get_homes()
        
        if homes:
            home = homes[0]
            devices = api.get_devices(home.id)
            
            if devices:
                device = devices[0]
                
                # 尝试设置无效的属性值
                api.control_device(device.did, siid=2, piid=1, value="invalid")
                
    except ValidationError as e:
        print(f"✗ 参数验证失败: {e.message}")
        print("  解决方案：检查参数类型和值范围")
    
    except FileNotFoundError:
        print("✗ 凭据文件不存在（跳过此示例）")
    
    except Exception as e:
        print(f"其他错误: {e}")
    
    print()


def example_comprehensive_error_handling():
    """示例：综合错误处理"""
    print("=== 示例5：综合错误处理 ===\n")
    
    try:
        # 创建API客户端
        api = create_api_client_from_file()
        
        # 获取家庭列表
        homes = api.get_homes()
        if not homes:
            print("未找到任何家庭")
            return
        
        home = homes[0]
        devices = api.get_devices(home.id)
        
        # 遍历设备并尝试控制
        for device in devices:
            try:
                if device.is_online():
                    # 批量读取属性（请求项：did + siid + piid）
                    properties = api.get_device_properties([
                        {"did": device.did, "siid": 2, "piid": 1},
                    ])
                    print(f"✓ {device.name}: 获取属性成功 {properties}")
                else:
                    print(f"⊘ {device.name}: 设备离线")
                    
            except DeviceOfflineError:
                print(f"✗ {device.name}: 设备离线")
                continue
                
            except DeviceError as e:
                print(f"✗ {device.name}: {e.message}")
                continue
        
    except TokenExpiredError:
        print("✗ Token已过期，请重新登录")
        
    except AuthenticationError as e:
        print(f"✗ 认证失败: {e.message}")
        
    except NetworkError as e:
        print(f"✗ 网络错误: {e.message}")
        
    except MijiaAPIException as e:
        print(f"✗ API错误: {e.message}")
        if e.code:
            print(f"  错误码: {e.code}")
    
    except FileNotFoundError:
        print("✗ 凭据文件不存在")
    
    print()


def main():
    """主函数"""
    print("=" * 60)
    print("示例07：错误处理")
    print("=" * 60)
    print()
    
    example_authentication_error()
    example_device_error()
    example_network_error()
    example_validation_error()
    example_comprehensive_error_handling()
    
    print("=" * 60)
    print("错误处理最佳实践：")
    print("1. 捕获具体的异常类型，而不是通用的 Exception")
    print("2. 为用户提供清晰的错误信息和解决方案")
    print("3. 对于临时性错误（如网络超时），实现重试机制")
    print("4. 记录异常信息，便于问题排查")
    print("5. 优雅降级，避免整个程序崩溃")
    print("=" * 60)
    print("\n参考文档：docs/API参考/03-异常处理.md")


if __name__ == "__main__":
    main()
