#!/usr/bin/env python3
"""示例 11：完整工作流

演示一个完整的实际应用场景：
- 智能家居自动化脚本
- 包含认证、设备发现、状态监控、自动控制
- 展示最佳实践和错误处理
"""

import sys
import time
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mijiaAPI_V2 import create_api_client_from_file
from mijiaAPI_V2.domain.exceptions import (
    MijiaAPIException,
    DeviceOfflineError,
    DeviceError,
)


class SmartHomeAutomation:
    """智能家居自动化类"""
    
    def __init__(self):
        """初始化"""
        self.api = None
        self.homes = []
        self.devices = []
    
    def initialize(self) -> bool:
        """初始化API客户端"""
        print("【初始化】")
        try:
            self.api = create_api_client_from_file()
            print("✓ API客户端初始化成功")
            return True
        except FileNotFoundError:
            print("✗ 凭据文件不存在，请先登录")
            return False
        except Exception as e:
            print(f"✗ 初始化失败: {e}")
            return False
    
    def discover_devices(self) -> bool:
        """发现设备"""
        print("\n【设备发现】")
        try:
            # 获取家庭列表
            self.homes = self.api.get_homes()
            print(f"✓ 找到 {len(self.homes)} 个家庭")
            
            # 获取所有设备
            all_devices = []
            for home in self.homes:
                devices = self.api.get_devices(home.id)
                all_devices.extend(devices)
                print(f"  - {home.name}: {len(devices)} 个设备")
            
            self.devices = all_devices
            print(f"✓ 总共 {len(self.devices)} 个设备")
            return True
            
        except Exception as e:
            print(f"✗ 设备发现失败: {e}")
            return False
    
    def monitor_devices(self):
        """监控设备状态"""
        print("\n【设备监控】")
        
        online_count = 0
        offline_count = 0
        
        for device in self.devices:
            if device.is_online():
                online_count += 1
            else:
                offline_count += 1
        
        print(f"在线设备: {online_count}")
        print(f"离线设备: {offline_count}")
        
        # 显示离线设备
        if offline_count > 0:
            print("\n离线设备列表:")
            for device in self.devices:
                if not device.is_online():
                    print(f"  - {device.name} ({device.model})")
    
    def control_lights(self, turn_on: bool = True):
        """控制所有灯光"""
        action = "打开" if turn_on else "关闭"
        print(f"\n【{action}所有灯光】")
        
        # 查找所有灯光设备
        lights = [d for d in self.devices if "light" in d.model.lower()]
        
        if not lights:
            print("未找到灯光设备")
            return
        
        print(f"找到 {len(lights)} 个灯光设备")
        
        # 批量控制
        requests = []
        for light in lights:
            if light.is_online():
                requests.append({
                    "did": light.did,
                    "siid": 2,
                    "piid": 1,
                    "value": turn_on
                })
        
        if not requests:
            print("没有在线的灯光设备")
            return
        
        try:
            results = self.api.batch_set_properties(requests)
            success_count = sum(1 for r in results if r.get("code") == 0)
            print(f"✓ 成功控制 {success_count}/{len(requests)} 个灯光")
            
        except Exception as e:
            print(f"✗ 控制失败: {e}")
    
    def get_device_status(self, device_name: str):
        """获取指定设备的状态"""
        print(f"\n【获取设备状态】{device_name}")
        
        # 查找设备
        device = None
        for d in self.devices:
            if device_name in d.name:
                device = d
                break
        
        if not device:
            print(f"✗ 未找到设备: {device_name}")
            return
        
        print(f"设备: {device.name}")
        print(f"型号: {device.model}")
        print(f"状态: {'在线' if device.is_online() else '离线'}")
        
        if not device.is_online():
            return
        
        # 获取设备属性
        try:
            # 尝试获取常见属性
            requests = [
                {"did": device.did, "siid": 2, "piid": 1},  # 开关
                {"did": device.did, "siid": 2, "piid": 2},  # 亮度/其他
            ]
            
            results = self.api.batch_get_properties(requests)
            
            print("\n当前属性:")
            for i, result in enumerate(results):
                if result.get("code") == 0:
                    print(f"  属性{i+1}: {result.get('value')}")
                    
        except DeviceOfflineError:
            print("✗ 设备离线")
        except DeviceError as e:
            print(f"✗ 获取属性失败: {e.message}")
    
    def execute_scene(self, scene_name: str):
        """执行智能"""
        print(f"\n【执行智能】{scene_name}")
        
        # 获取智能列表
        try:
            if not self.homes:
                print("✗ 没有可用的家庭")
                return
            
            home = self.homes[0]
            scenes = self.api.get_scenes(home.id)
            
            # 查找智能
            scene = None
            for s in scenes:
                if scene_name in s.name:
                    scene = s
                    break
            
            if not scene:
                print(f"✗ 未找到智能: {scene_name}")
                print(f"可用智能: {[s.name for s in scenes]}")
                return
            
            # 执行智能（home_id 必填）
            success = self.api.execute_scene(scene.scene_id, home.id)
            if success:
                print(f"✓ 智能 '{scene.name}' 执行成功")
            else:
                print(f"✗ 智能执行失败")
                
        except Exception as e:
            print(f"✗ 执行智能失败: {e}")
    
    def run(self):
        """运行自动化流程"""
        print("=" * 60)
        print("智能家居自动化脚本")
        print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        # 1. 初始化
        if not self.initialize():
            return
        
        # 2. 发现设备
        if not self.discover_devices():
            return
        
        # 3. 监控设备状态
        self.monitor_devices()
        
        # 4. 控制灯光（示例）
        # self.control_lights(turn_on=True)
        
        # 5. 获取特定设备状态（示例）
        # self.get_device_status("台灯")
        
        # 6. 执行智能（示例）
        # self.execute_scene("回家模式")
        
        print("\n" + "=" * 60)
        print("自动化流程完成")
        print("=" * 60)


def main():
    """主函数"""
    automation = SmartHomeAutomation()
    automation.run()


if __name__ == "__main__":
    main()
