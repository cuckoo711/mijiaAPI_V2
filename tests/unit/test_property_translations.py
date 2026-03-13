"""属性翻译测试"""

import json
import tempfile
from pathlib import Path

import pytest

from mijiaAPI_V2.repositories.property_translations import (
    TranslationManager,
    get_action_translation,
    get_access_translation,
    get_property_translation,
    get_type_translation,
)


@pytest.fixture
def temp_translation_file() -> Path:
    """创建临时翻译文件"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        translations = {
            "properties": {
                "Temperature": "温度",
                "Humidity": "湿度",
            },
            "actions": {
                "TurnOn": "打开",
                "TurnOff": "关闭",
            },
            "types": {
                "bool": "布尔值",
                "int": "整数",
            },
            "access": {
                "read": "只读",
                "write": "可写",
            },
        }
        json.dump(translations, f, ensure_ascii=False)
        temp_path = Path(f.name)

    yield temp_path

    # 清理
    if temp_path.exists():
        temp_path.unlink()


def test_translation_manager_init_default() -> None:
    """测试默认初始化翻译管理器"""
    manager = TranslationManager()

    # 验证管理器已创建
    assert manager is not None
    assert hasattr(manager, "_translations")


def test_translation_manager_with_custom_dict() -> None:
    """测试使用自定义字典初始化"""
    custom_translations = {
        "properties": {
            "CustomProp": "自定义属性",
        },
        "actions": {
            "CustomAction": "自定义操作",
        },
    }

    manager = TranslationManager(custom_translations=custom_translations)

    # 验证自定义翻译
    assert manager.get_property_translation("CustomProp") == "自定义属性"
    assert manager.get_action_translation("CustomAction") == "自定义操作"


def test_translation_manager_with_custom_file(temp_translation_file: Path) -> None:
    """测试使用自定义文件初始化"""
    manager = TranslationManager(custom_file=temp_translation_file)

    # 验证文件中的翻译
    assert manager.get_property_translation("Temperature") == "温度"
    assert manager.get_property_translation("Humidity") == "湿度"
    assert manager.get_action_translation("TurnOn") == "打开"
    assert manager.get_action_translation("TurnOff") == "关闭"
    assert manager.get_type_translation("bool") == "布尔值"
    assert manager.get_access_translation("read") == "只读"


def test_translation_manager_merge_priority() -> None:
    """测试翻译合并优先级"""
    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        translations = {
            "properties": {
                "TestProp": "文件翻译",
            },
        }
        json.dump(translations, f, ensure_ascii=False)
        temp_path = Path(f.name)

    try:
        # 自定义字典应该覆盖文件翻译
        custom_translations = {
            "properties": {
                "TestProp": "字典翻译",
            },
        }

        manager = TranslationManager(
            custom_translations=custom_translations,
            custom_file=temp_path,
        )

        # 验证优先级：自定义字典 > 外部文件
        assert manager.get_property_translation("TestProp") == "字典翻译"
    finally:
        temp_path.unlink()


def test_get_property_translation_fallback() -> None:
    """测试属性翻译回退"""
    manager = TranslationManager()

    # 不存在的翻译应返回原英文名
    result = manager.get_property_translation("NonExistentProperty")
    assert result == "NonExistentProperty"


def test_get_action_translation_fallback() -> None:
    """测试操作翻译回退"""
    manager = TranslationManager()

    # 不存在的翻译应返回原英文名
    result = manager.get_action_translation("NonExistentAction")
    assert result == "NonExistentAction"


def test_get_type_translation_fallback() -> None:
    """测试类型翻译回退"""
    manager = TranslationManager()

    # 不存在的翻译应返回原类型名
    result = manager.get_type_translation("unknown_type")
    assert result == "unknown_type"


def test_get_access_translation_fallback() -> None:
    """测试访问权限翻译回退"""
    manager = TranslationManager()

    # 不存在的翻译应返回原权限名
    result = manager.get_access_translation("unknown_access")
    assert result == "unknown_access"


def test_add_property_translation() -> None:
    """测试添加属性翻译"""
    manager = TranslationManager()

    # 添加新翻译
    manager.add_property_translation("NewProperty", "新属性")

    # 验证翻译已添加
    assert manager.get_property_translation("NewProperty") == "新属性"


def test_add_action_translation() -> None:
    """测试添加操作翻译"""
    manager = TranslationManager()

    # 添加新翻译
    manager.add_action_translation("NewAction", "新操作")

    # 验证翻译已添加
    assert manager.get_action_translation("NewAction") == "新操作"


def test_export_to_file() -> None:
    """测试导出翻译到文件"""
    manager = TranslationManager()

    # 添加一些翻译
    manager.add_property_translation("ExportProp", "导出属性")
    manager.add_action_translation("ExportAction", "导出操作")

    # 导出到临时文件
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        export_path = Path(f.name)

    try:
        manager.export_to_file(export_path)

        # 验证文件存在
        assert export_path.exists()

        # 读取并验证内容
        with open(export_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "properties" in data
        assert "ExportProp" in data["properties"]
        assert data["properties"]["ExportProp"] == "导出属性"
    finally:
        if export_path.exists():
            export_path.unlink()


def test_load_nonexistent_file() -> None:
    """测试加载不存在的文件"""
    with pytest.raises(FileNotFoundError):
        TranslationManager(custom_file=Path("/nonexistent/path/file.json"))


def test_global_functions() -> None:
    """测试全局便捷函数"""
    # 这些函数使用默认管理器
    # 测试它们不会抛出异常
    result = get_property_translation("TestProperty")
    assert isinstance(result, str)

    result = get_action_translation("TestAction")
    assert isinstance(result, str)

    result = get_type_translation("test_type")
    assert isinstance(result, str)

    result = get_access_translation("test_access")
    assert isinstance(result, str)


def test_merge_translations() -> None:
    """测试合并翻译"""
    manager = TranslationManager()

    # 初始翻译
    initial_translations = {
        "properties": {
            "Prop1": "属性1",
        },
    }
    manager._merge_translations(initial_translations)

    # 合并新翻译
    new_translations = {
        "properties": {
            "Prop2": "属性2",
        },
        "actions": {
            "Action1": "操作1",
        },
    }
    manager._merge_translations(new_translations)

    # 验证两个翻译都存在
    assert manager.get_property_translation("Prop1") == "属性1"
    assert manager.get_property_translation("Prop2") == "属性2"
    assert manager.get_action_translation("Action1") == "操作1"
