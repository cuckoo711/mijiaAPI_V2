#!/usr/bin/env python3
"""示例02：快速开始

演示最基本的使用方法：
- 从文件加载凭据
- 获取家庭列表
- 获取设备列表
- 控制设备
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mijiaAPI_V2 import create_api_client_from_file


def main():
    """主函数"""
    print("=== 示例02：快速开始 ===\n")
    
    # 1. 创建API客户端（从文件加载凭据）
    print("【步骤1】加载凭据")
    api = create_api_client_from_file()
    print("✓ 凭据加载成功\n")
    
    # 2. 获取家庭列表
    print("【步骤2】获取家庭列表")
    homes = api.get_homes()
    print(f"✓ 找到 {len(homes)} 个家庭")
    for home in homes:
        print(f"  - {home.name} (ID: {home.id})")
    print()
    
    # 3. 获取第一个家庭的设备列表
    if homes:
        home = homes[0]
        print(f"【步骤3】获取家庭 '{home.name}' 的设备")
        devices = api.get_devices(home.id)
        print(f"✓ 找到 {len(devices)} 个设备")
        
        # 显示前5个设备
        for device in devices[:5]:
            status = "在线" if device.is_online() else "离线"
            print(f"  - {device.name} ({device.model}) - {status}")
        
        if len(devices) > 5:
            print(f"  ... 还有 {len(devices) - 5} 个设备")
        print()
        
        # 4. 控制第一个在线设备（如果是灯光设备）
        print("【步骤4】控制设备")
        lamp = None
        for device in devices:
            if device.is_online() and "light" in device.model.lower():
                lamp = device
                break
        
        if lamp:
            print(f"找到灯光设备: {lamp.name}")
            
            # 获取设备规格以了解属性结构
            spec = api.get_device_spec(lamp.model)
            if spec:
                print(f"设备型号: {spec.model}")
                print(f"设备名称: {spec.name}")
                # 显示前3个属性
                if spec.properties:
                    print("可用属性:")
                    for prop in spec.properties[:3]:
                        print(f"  - {prop.name} (siid={prop.siid}, piid={prop.piid})")
            
            # 注意：控制设备需要知道正确的 siid 和 piid
            # 可以使用 deploy/scripts/show_device_spec.py 查看设备规格
            print("\n提示：使用 'python deploy/scripts/show_device_spec.py' 查看设备规格后再控制设备")
        else:
            print("未找到可控制的灯光设备")
    
    print("\n=== 示例完成 ===")


if __name__ == "__main__":
    main()
