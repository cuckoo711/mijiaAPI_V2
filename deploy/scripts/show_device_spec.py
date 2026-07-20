#!/usr/bin/env python3
"""查看设备规格工具

显示指定设备的完整规格信息，包括所有属性和操作的详细说明。
"""

import sys
from pathlib import Path

# 添加项目根目录到路径（本文件位于 deploy/scripts/）
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from mijiaAPI_V2 import create_api_client_from_file
from mijiaAPI_V2.repositories.property_translations import (
    get_property_translation,
    get_action_translation,
    get_access_translation,
)


def show_device_spec(api, device_name: str = None, device_model: str = None):
    """显示设备规格
    
    Args:
        api: API客户端
        device_name: 设备名称（可选）
        device_model: 设备型号（可选）
    """
    # 如果提供了设备名称，先查找设备
    if device_name:
        print(f"正在查找设备: {device_name}...")
        homes = api.get_homes()
        
        device = None
        for home in homes:
            devices = api.get_devices(home.id)
            for dev in devices:
                if dev.name == device_name:
                    device = dev
                    device_model = dev.model
                    break
            if device:
                break
        
        if not device:
            print(f"✗ 未找到设备: {device_name}")
            return
        
        print(f"✓ 找到设备: {device.name}")
        print(f"  型号: {device.model}")
        print(f"  DID: {device.did}")
        print()
    
    if not device_model:
        print("✗ 请提供设备名称或设备型号")
        return
    
    # 获取设备规格
    print(f"正在获取设备规格: {device_model}...")
    spec = api.get_device_spec(device_model)
    
    if not spec:
        print("✗ 未找到设备规格")
        return
    
    print(f"\n{'='*60}")
    print(f"设备规格: {spec.name}")
    print(f"型号: {spec.model}")
    print(f"{'='*60}\n")
    
    # 显示所有属性
    print(f"【属性列表】共 {len(spec.properties)} 个\n")
    for i, prop in enumerate(spec.properties, 1):
        # 获取中文翻译
        cn_name = get_property_translation(prop.name)
        access_cn = get_access_translation(prop.access.value)
        
        # 显示属性信息
        if cn_name != prop.name:
            print(f"{i}. {cn_name}")
            print(f"   英文名: {prop.name}")
        else:
            print(f"{i}. {prop.name}")
        
        print(f"   ID: siid={prop.siid}, piid={prop.piid}")
        print(f"   类型: {prop.type.value}")
        print(f"   权限: {access_cn}")
        
        if prop.value_range:
            if len(prop.value_range) == 2:
                print(f"   范围: {prop.value_range[0]} ~ {prop.value_range[1]}")
            elif len(prop.value_range) == 3:
                print(f"   范围: {prop.value_range[0]} ~ {prop.value_range[1]}, 步长: {prop.value_range[2]}")
        
        if prop.value_list:
            print(f"   可选值: {prop.value_list}")
        
        print()
    
    # 显示所有操作
    if spec.actions:
        print(f"\n【操作列表】共 {len(spec.actions)} 个\n")
        for i, action in enumerate(spec.actions, 1):
            # 获取中文翻译
            cn_name = get_action_translation(action.name)
            
            # 显示操作信息
            if cn_name != action.name:
                print(f"{i}. {cn_name}")
                print(f"   英文名: {action.name}")
            else:
                print(f"{i}. {action.name}")
            
            print(f"   ID: siid={action.siid}, aiid={action.aiid}")
            
            if action.parameters:
                print(f"   参数: {len(action.parameters)} 个")
            
            print()


def main():
    """主函数"""
    print("=== 米家设备规格查看工具 ===\n")
    
    # 加载API客户端
    try:
        api = create_api_client_from_file()
        print("✓ 已加载凭据\n")
    except Exception as e:
        print(f"✗ 加载凭据失败: {e}")
        return
    
    # 获取命令行参数
    if len(sys.argv) > 1:
        # 如果提供了参数，判断是设备名称还是型号
        arg = sys.argv[1]
        if arg.count('.') >= 2:  # 型号格式通常是 brand.type.model
            show_device_spec(api, device_model=arg)
        else:
            show_device_spec(api, device_name=arg)
    else:
        # 交互式选择设备
        print("获取设备列表...")
        homes = api.get_homes()
        
        if not homes:
            print("✗ 未找到任何家庭")
            return
        
        # 使用第一个家庭
        home = homes[0]
        print(f"✓ 使用家庭: {home.name}\n")
        
        devices = api.get_devices(home.id)
        
        if not devices:
            print("✗ 未找到任何设备")
            return
        
        print(f"找到 {len(devices)} 个设备:\n")
        for i, device in enumerate(devices, 1):
            status = "在线" if device.is_online() else "离线"
            print(f"{i}. {device.name} ({device.model}) - {status}")
        
        print()
        try:
            choice = int(input("请选择设备编号: "))
            if 1 <= choice <= len(devices):
                device = devices[choice - 1]
                print()
                show_device_spec(api, device_name=device.name)
            else:
                print("✗ 无效的设备编号")
        except (ValueError, KeyboardInterrupt):
            print("\n已取消")


if __name__ == "__main__":
    main()
