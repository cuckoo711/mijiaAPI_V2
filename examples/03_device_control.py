#!/usr/bin/env python3
"""示例03：设备控制

演示设备控制的各种方法：
- 获取设备属性
- 设置设备属性
- 批量操作
- 调用设备动作
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mijiaAPI_V2 import create_api_client_from_file
from mijiaAPI_V2.domain.exceptions import DeviceError, MijiaAPIException


def main():
    """主函数"""
    print("=== 示例03：设备控制 ===\n")
    
    # 创建API客户端
    api = create_api_client_from_file()
    
    # 获取设备列表
    homes = api.get_homes()
    if not homes:
        print("未找到任何家庭")
        return
    
    home = homes[0]
    devices = api.get_devices(home.id)
    
    # 查找灯光设备作为示例
    lamp = None
    for device in devices:
        if device.is_online() and "light" in device.model.lower():
            lamp = device
            break
    
    if not lamp:
        print("未找到在线的灯光设备")
        print("提示：示例需要至少一个在线的灯光设备")
        return
    
    print(f"使用设备: {lamp.name} ({lamp.model})\n")
    
    # 先获取设备规格，确定正确的 siid/piid
    spec = api.get_device_spec(lamp.model)
    if not spec or not spec.properties:
        print("无法获取设备规格，示例无法继续")
        return
    
    # 查找开关、模式和亮度属性
    power_prop = None
    mode_prop = None
    brightness_prop = None
    
    for prop in spec.properties:
        name_lower = prop.name.lower()
        # 查找开关属性（优先选择可写的）
        if not power_prop or (prop.is_writable() and not power_prop.is_writable()):
            if any(keyword in name_lower for keyword in ["switch", "power", "on", "开关"]):
                power_prop = prop
        # 查找模式属性
        if not mode_prop and prop.is_writable():
            if "mode" in name_lower or "模式" in prop.name:
                mode_prop = prop
        # 查找亮度属性
        if not brightness_prop and prop.is_writable():
            if any(keyword in name_lower for keyword in ["brightness", "亮度", "level"]):
                brightness_prop = prop
    
    if not power_prop:
        print("未找到开关属性，示例无法继续")
        return
    
    print(f"找到属性: 开关 (siid={power_prop.siid}, piid={power_prop.piid})")
    if mode_prop:
        print(f"找到属性: 模式 (siid={mode_prop.siid}, piid={mode_prop.piid})")
        if mode_prop.value_list:
            print(f"  可选模式: {mode_prop.value_list}")
    if brightness_prop:
        print(f"找到属性: 亮度 (siid={brightness_prop.siid}, piid={brightness_prop.piid})")
    print()
    
    # 1. 批量获取属性
    print("【方法1】批量获取属性")
    try:
        requests = [
            {"did": lamp.did, "siid": power_prop.siid, "piid": power_prop.piid},
        ]
        if brightness_prop:
            requests.append({"did": lamp.did, "siid": brightness_prop.siid, "piid": brightness_prop.piid})
        
        results = api.get_device_properties(requests)
        
        for i, result in enumerate(results):
            if result.get("code") == 0:
                print(f"  属性{i+1} (siid={requests[i]['siid']}, piid={requests[i]['piid']}): {result.get('value')}")
            else:
                print(f"  属性{i+1}: 获取失败 (code={result.get('code')})")
    except (DeviceError, MijiaAPIException) as e:
        print(f"  批量获取失败: {e}")
    print()
    
    # 2. 设置单个属性
    print("【方法2】设置单个属性")
    try:
        # 设置开关状态为开
        success = api.control_device(lamp.did, siid=power_prop.siid, piid=power_prop.piid, value=True)
        if success:
            print("  ✓ 设备已打开")
        else:
            print("  ✗ 设置失败")
    except (DeviceError, MijiaAPIException) as e:
        print(f"  设置失败: {e}")
    print()
    
    # 3. 设置模式属性（如果有）
    print("【方法3】设置模式属性")
    if mode_prop and mode_prop.is_writable() and mode_prop.value_list:
        try:
            # 获取当前模式
            requests = [{"did": lamp.did, "siid": mode_prop.siid, "piid": mode_prop.piid}]
            results = api.get_device_properties(requests)
            current_mode = results[0].get("value") if results else None
            
            if current_mode is not None:
                print(f"  当前模式: {current_mode}")
                
                # 切换到下一个模式
                mode_list = mode_prop.value_list
                current_index = mode_list.index(current_mode) if current_mode in mode_list else 0
                next_mode = mode_list[(current_index + 1) % len(mode_list)]
                
                success = api.control_device(lamp.did, siid=mode_prop.siid, piid=mode_prop.piid, value=next_mode)
                if success:
                    print(f"  ✓ 已切换到模式 {next_mode}")
                    # 切换回原模式
                    api.control_device(lamp.did, siid=mode_prop.siid, piid=mode_prop.piid, value=current_mode)
                    print(f"  ✓ 已恢复到模式 {current_mode}")
                else:
                    print(f"  ✗ 模式切换失败")
            else:
                print("  ✗ 无法获取当前模式")
        except (DeviceError, MijiaAPIException) as e:
            print(f"  设置失败: {e}")
    elif brightness_prop and brightness_prop.is_writable():
        # 如果有亮度属性，使用批量设置
        try:
            requests = [
                {"device_id": lamp.did, "siid": power_prop.siid, "piid": power_prop.piid, "value": True},
                {"device_id": lamp.did, "siid": brightness_prop.siid, "piid": brightness_prop.piid, "value": 80},
            ]
            results = api.batch_control_devices(requests)
            
            for i, result in enumerate(results):
                if result.get("code") == 0:
                    print(f"  ✓ 属性{i+1}设置成功")
                else:
                    print(f"  ✗ 属性{i+1}设置失败 (code={result.get('code')})")
        except (DeviceError, MijiaAPIException) as e:
            print(f"  批量设置失败: {e}")
    else:
        print("  跳过：未找到可控制的模式或亮度属性")
    print()
    
    # 4. 调用设备动作
    print("【方法4】调用设备动作")
    if spec.actions:
        # 查找一个不需要参数的简单动作
        simple_action = None
        for action in spec.actions:
            # 优先选择亮度相关的动作
            if "bright" in action.name.lower() or "亮度" in action.name:
                if not action.parameters:  # 不需要参数
                    simple_action = action
                    break
        
        # 如果没找到亮度动作，找其他不需要参数的动作
        if not simple_action:
            for action in spec.actions:
                if not action.parameters:
                    simple_action = action
                    break
        
        if simple_action:
            try:
                print(f"  尝试调用动作: {simple_action.name} (siid={simple_action.siid}, aiid={simple_action.aiid})")
                result = api.call_device_action(lamp.did, siid=simple_action.siid, aiid=simple_action.aiid, params={})
                if result.get("code") == 0:
                    print(f"  ✓ 动作执行成功")
                else:
                    print(f"  ✗ 动作执行失败 (code={result.get('code')})")
            except (DeviceError, MijiaAPIException) as e:
                print(f"  ✗ 动作执行失败: {e}")
        else:
            print("  跳过：所有动作都需要参数")
            print(f"  提示：设备有 {len(spec.actions)} 个动作，可使用 'python deploy/scripts/show_device_spec.py' 查看详情")
    else:
        print("  跳过：设备没有可用的动作")
    print()
    
    # 5. 查看设备规格摘要
    print("【方法5】查看设备规格摘要")
    print(f"  设备型号: {spec.model}")
    print(f"  设备名称: {spec.name}")
    print(f"  属性数量: {len(spec.properties)}")
    print(f"  操作数量: {len(spec.actions)}")
    
    # 显示可写属性
    writable_props = [p for p in spec.properties if p.is_writable()]
    if writable_props:
        print(f"\n  可写属性 ({len(writable_props)} 个):")
        for prop in writable_props[:5]:  # 只显示前5个
            print(f"    - {prop.name} (siid={prop.siid}, piid={prop.piid})")
        if len(writable_props) > 5:
            print(f"    ... 还有 {len(writable_props) - 5} 个")
    print()
    
    print("=== 示例完成 ===")
    print("\n提示：")
    print("- siid 和 piid 需要根据设备规格确定")
    print("- 使用 'python deploy/scripts/show_device_spec.py' 查看完整设备规格")
    print("- 参考文档：docs/使用指南/05-设备规格翻译.md")


if __name__ == "__main__":
    main()
