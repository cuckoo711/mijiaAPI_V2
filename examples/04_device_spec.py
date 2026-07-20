#!/usr/bin/env python3
"""示例04：设备规格查询

演示如何查询和使用设备规格：
- 获取设备规格
- 查看设备属性列表
- 查看设备操作列表
- 使用中文翻译
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mijiaAPI_V2 import create_api_client_from_file
from mijiaAPI_V2.repositories.property_translations import (
    get_property_translation,
    get_action_translation,
    get_access_translation,
)


def main():
    """主函数"""
    print("=== 示例04：设备规格查询 ===\n")
    
    # 创建API客户端
    api = create_api_client_from_file()
    
    # 获取设备列表
    homes = api.get_homes()
    if not homes:
        print("未找到任何家庭")
        return
    
    home = homes[0]
    devices = api.get_devices(home.id)
    
    # 选择第一个设备
    if not devices:
        print("未找到任何设备")
        return
    
    device = devices[0]
    print(f"设备: {device.name}")
    print(f"型号: {device.model}")
    print(f"状态: {'在线' if device.is_online() else '离线'}\n")
    
    # 获取设备规格
    print("【获取设备规格】")
    spec = api.get_device_spec(device.model)
    
    if not spec:
        print("✗ 未找到设备规格")
        return
    
    print(f"✓ 设备名称: {spec.name}")
    print(f"✓ 属性数量: {len(spec.properties)}")
    print(f"✓ 操作数量: {len(spec.actions)}\n")
    
    # 显示属性列表
    print("【属性列表】")
    print(f"共 {len(spec.properties)} 个属性:\n")
    
    for i, prop in enumerate(spec.properties[:10], 1):  # 只显示前10个
        # 获取中文翻译
        cn_name = get_property_translation(prop.name)
        access_cn = get_access_translation(prop.access.value)
        
        # 显示属性信息
        if cn_name != prop.name:
            print(f"{i}. {cn_name} ({prop.name})")
        else:
            print(f"{i}. {prop.name}")
        
        print(f"   ID: siid={prop.siid}, piid={prop.piid}")
        print(f"   类型: {prop.type.value}, 权限: {access_cn}")
        
        if prop.value_range:
            print(f"   范围: {prop.value_range}")
        if prop.value_list:
            print(f"   可选值: {prop.value_list}")
        print()
    
    if len(spec.properties) > 10:
        print(f"... 还有 {len(spec.properties) - 10} 个属性\n")
    
    # 显示操作列表
    print("【操作列表】")
    print(f"共 {len(spec.actions)} 个操作:\n")
    
    for i, action in enumerate(spec.actions[:10], 1):  # 只显示前10个
        # 获取中文翻译
        cn_name = get_action_translation(action.name)
        
        # 显示操作信息
        if cn_name != action.name:
            print(f"{i}. {cn_name} ({action.name})")
        else:
            print(f"{i}. {action.name}")
        
        print(f"   ID: siid={action.siid}, aiid={action.aiid}")
        if action.parameters:
            print(f"   参数: {len(action.parameters)} 个")
        print()
    
    if len(spec.actions) > 10:
        print(f"... 还有 {len(spec.actions) - 10} 个操作\n")
    
    # 使用规格信息控制设备
    print("【使用规格信息】")
    print("根据规格信息，可以这样控制设备:\n")
    
    # 查找开关属性
    switch_prop = None
    for prop in spec.properties:
        if prop.name == "Switch Status" or "switch" in prop.name.lower():
            switch_prop = prop
            break
    
    if switch_prop:
        print(f"开关属性: {switch_prop.name}")
        print(f"  siid={switch_prop.siid}, piid={switch_prop.piid}")
        print(f"  类型: {switch_prop.type.value}")
        print(f"  权限: {switch_prop.access.value}")
        print()
        print("控制示例:")
        print(f"  api.set_device_property(")
        print(f"      device_id='{device.did}',")
        print(f"      siid={switch_prop.siid},")
        print(f"      piid={switch_prop.piid},")
        print(f"      value=True  # 打开设备")
        print(f"  )")
    
    print("\n=== 示例完成 ===")
    print("\n提示：")
    print("- 使用 deploy/scripts/show_device_spec.py 可以查看完整的设备规格")
    print("- 参考文档：docs/使用指南/05-设备规格翻译.md")


if __name__ == "__main__":
    main()
