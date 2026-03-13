#!/usr/bin/env python3
"""示例 9：配置管理

演示如何使用配置文件管理SDK行为：
- 加载配置文件
- 配置凭据存储路径
- 配置网络参数
- 配置缓存策略
- 使用环境变量覆盖配置
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from mijiaAPI_V2.core.config import ConfigManager
from mijiaAPI_V2.factory import create_auth_service, create_config_manager


def example_load_config():
    """示例：加载配置文件"""
    print("=== 方式1：加载配置文件 ===\n")
    
    # 加载配置文件（SDK会按优先级自动查找）
    # 1. configs/mijiaAPI.toml（推荐）
    # 2. config.toml
    # 3. ~/.mijia/config.toml
    # 4. SDK自带的默认配置
    config = create_config_manager(config_path=Path("configs/mijiaAPI.toml"))
    
    print("配置加载成功")
    print(f"  API基础URL: {config.get('API_BASE_URL')}")
    print(f"  默认超时: {config.get('NETWORK_DEFAULT_TIMEOUT')} 秒")
    print(f"  最大重试次数: {config.get('NETWORK_MAX_RETRIES')}")
    print(f"  设备列表缓存TTL: {config.get('CACHE_DEVICE_LIST_TTL')} 秒")
    print(f"  凭据存储路径: {config.get('CREDENTIAL_PATH')}")
    print()
    
    print("配置文件查找顺序（优先级从高到低）：")
    print("  1. configs/mijiaAPI.toml - 项目configs目录（推荐）")
    print("  2. config.toml - 项目根目录")
    print("  3. ~/.mijia/config.toml - 用户主目录")
    print("  4. SDK自带的默认配置 - 最低优先级")
    print()


def example_credential_path_config():
    """示例：配置凭据存储路径"""
    print("=== 方式2：配置凭据存储路径 ===\n")
    
    # 创建认证服务（会自动从配置读取凭据路径）
    auth_service = create_auth_service(config_path=Path("configs/mijiaAPI.toml"))
    
    # 查看凭据存储路径
    store = auth_service._store
    credential_path = store._default_path
    
    print(f"凭据存储路径: {credential_path}")
    print(f"  是否为绝对路径: {credential_path.is_absolute()}")
    print(f"  父目录: {credential_path.parent}")
    print(f"  父目录是否存在: {credential_path.parent.exists()}")
    print()
    
    # 演示不同的路径配置方式
    print("支持的路径格式：")
    print("  1. 相对路径: .mijia/credential.json")
    print("     -> 相对于项目根目录")
    print("  2. 用户目录: ~/.mijia/credential.json")
    print("     -> 展开为用户主目录")
    print("  3. 绝对路径: /tmp/credential.json")
    print("     -> 直接使用绝对路径")
    print()
    
    print("配置文件示例：")
    print("  [security]")
    print("  credential_path = '.mijia/credential.json'  # 项目级")
    print("  # 或")
    print("  credential_path = '~/.mijia/credential.json'  # 全局级")
    print()


def example_custom_config():
    """示例：使用自定义配置"""
    print("=== 方式3：使用自定义配置 ===\n")
    
    # 创建配置管理器
    config = ConfigManager()
    
    # 运行时修改配置
    config.set("NETWORK_DEFAULT_TIMEOUT", 60)
    config.set("CACHE_DEVICE_LIST_TTL", 600)
    config.set("LOG_LEVEL", "DEBUG")
    
    print("自定义配置已设置：")
    print(f"  超时时间: {config.get('NETWORK_DEFAULT_TIMEOUT')} 秒")
    print(f"  缓存TTL: {config.get('CACHE_DEVICE_LIST_TTL')} 秒")
    print(f"  日志级别: {config.get('LOG_LEVEL')}")
    print()


def example_environment_variables():
    """示例：使用环境变量"""
    print("=== 方式4：使用环境变量 ===\n")
    
    print("环境变量格式: MIJIA_<配置键名>")
    print()
    print("示例：")
    print("  export MIJIA_NETWORK_DEFAULT_TIMEOUT=60")
    print("  export MIJIA_CACHE_DEVICE_LIST_TTL=600")
    print("  export MIJIA_LOG_LEVEL=DEBUG")
    print("  export MIJIA_CREDENTIAL_PATH=~/.mijia/credential.json")
    print()
    print("环境变量优先级最高，会覆盖配置文件中的设置")
    print()


def example_config_priority():
    """示例：配置优先级"""
    print("=== 方式5：配置优先级 ===\n")
    
    print("配置加载优先级（从低到高）：")
    print("  1. 默认配置（最低优先级）")
    print("     -> 代码中定义的默认值")
    print("  2. 配置文件")
    print("     -> TOML文件中的配置")
    print("  3. 环境变量（最高优先级）")
    print("     -> MIJIA_* 环境变量")
    print()
    print("示例：")
    print("  默认: NETWORK_DEFAULT_TIMEOUT = 30")
    print("  配置文件: default_timeout = 45")
    print("  环境变量: MIJIA_NETWORK_DEFAULT_TIMEOUT = 60")
    print("  最终值: 60（环境变量优先）")
    print()


def example_credential_migration():
    """示例：凭据迁移"""
    print("=== 方式6：凭据迁移 ===\n")
    
    print("如果需要迁移凭据到新路径：")
    print()
    print("```python")
    print("from mijiaAPI_V2.infrastructure.credential_store import FileCredentialStore")
    print("from pathlib import Path")
    print()
    print("# 从旧路径加载")
    print("old_store = FileCredentialStore(")
    print("    default_path=Path('~/.mijia/credential.json')")
    print(")")
    print("credential = old_store.load()")
    print()
    print("# 保存到新路径")
    print("new_store = FileCredentialStore(")
    print("    default_path=Path('.mijia/credential.json')")
    print(")")
    print("new_store.save(credential)")
    print("```")
    print()


def example_multi_environment():
    """示例：多环境配置"""
    print("=== 方式7：多环境配置 ===\n")
    
    print("为不同环境创建不同的配置文件：")
    print()
    print("开发环境 (configs/development.toml):")
    print("  [security]")
    print("  credential_path = '.mijia/dev_credential.json'")
    print()
    print("生产环境 (configs/production.toml):")
    print("  [security]")
    print("  credential_path = '/var/lib/mijia/credential.json'")
    print()
    print("使用方式：")
    print("```python")
    print("import os")
    print("env = os.getenv('ENV', 'development')")
    print("config_path = Path(f'configs/{env}.toml')")
    print("auth_service = create_auth_service(config_path=config_path)")
    print("```")
    print()


def main():
    """主函数"""
    print("=" * 60)
    print("示例 9：配置管理")
    print("=" * 60)
    print()
    
    example_load_config()
    example_credential_path_config()
    example_custom_config()
    example_environment_variables()
    example_config_priority()
    example_credential_migration()
    example_multi_environment()
    
    print("=" * 60)
    print("配置最佳实践：")
    print("1. 使用配置文件管理不同环境的配置")
    print("2. 敏感信息使用环境变量")
    print("3. 凭据路径根据使用场景选择：")
    print("   - 项目级：使用相对路径")
    print("   - 全局级：使用用户目录")
    print("   - 服务器：使用绝对路径")
    print("4. 不要将凭据文件提交到版本控制")
    print("=" * 60)


if __name__ == "__main__":
    main()
