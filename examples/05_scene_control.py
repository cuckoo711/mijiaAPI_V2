#!/usr/bin/env python3
"""示例05：场景控制

演示场景相关操作：
- 获取场景列表
- 交互式选择并执行场景
- 支持跳过场景执行
- 支持连续执行多个场景
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mijiaAPI_V2 import create_api_client_from_file


def main():
    """主函数"""
    print("=== 示例05：场景控制 ===\n")
    
    # 创建API客户端
    api = create_api_client_from_file()
    
    # 获取家庭列表
    homes = api.get_homes()
    if not homes:
        print("未找到任何家庭")
        return
    
    home = homes[0]
    print(f"当前家庭: {home.name}\n")
    
    # 1. 获取场景列表
    print("【获取场景列表】")
    scenes = api.get_scenes(home.id)
    
    if not scenes:
        print("该家庭没有场景")
        return
    
    print(f"找到 {len(scenes)} 个场景:\n")
    for i, scene in enumerate(scenes, 1):
        print(f"{i}. {scene.name}")
        print(f"   场景ID: {scene.scene_id}")
        print(f"   家庭ID: {scene.home_id}")
        if scene.icon:
            print(f"   图标: {scene.icon}")
        print()
    
    # 2. 执行场景
    print("【执行场景】")
    while True:
        try:
            choice = input(f"\n请选择要执行的场景 (1-{len(scenes)})，或输入 0 跳过: ").strip()
            
            if not choice:
                continue
            
            choice_num = int(choice)
            
            if choice_num == 0:
                print("跳过场景执行")
                break
            
            if 1 <= choice_num <= len(scenes):
                scene = scenes[choice_num - 1]
                print(f"\n执行场景: {scene.name}")
                
                try:
                    success = api.execute_scene(scene.scene_id, home.id)
                    if success:
                        print("✓ 场景执行成功")
                    else:
                        print("✗ 场景执行失败")
                except Exception as e:
                    print(f"✗ 场景执行失败: {e}")
                
                # 询问是否继续执行其他场景
                continue_choice = input("\n是否继续执行其他场景? (y/n): ").strip().lower()
                if continue_choice != 'y':
                    break
            else:
                print(f"无效的选择，请输入 0-{len(scenes)} 之间的数字")
        
        except ValueError:
            print("请输入有效的数字")
        except KeyboardInterrupt:
            print("\n\n操作已取消")
            break
    
    print("\n=== 示例完成 ===")
    print("\n提示：")
    print("- 场景需要在米家APP中预先创建")
    print("- 场景执行是异步的，可能需要几秒钟才能生效")
    print("- 可以通过米家APP查看场景执行结果")


if __name__ == "__main__":
    main()
