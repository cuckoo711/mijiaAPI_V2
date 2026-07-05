"""CacheManager单元测试"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from mijiaAPI_V2.infrastructure.cache_manager import CacheManager


class TestCacheManager:
    """CacheManager测试类"""

    @pytest.fixture
    def temp_cache_dir(self) -> Path:
        """创建临时缓存目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def cache_manager(self, temp_cache_dir: Path) -> CacheManager:
        """创建CacheManager实例（无Redis）"""
        return CacheManager(cache_dir=temp_cache_dir)

    @pytest.fixture
    def mock_redis_client(self) -> Mock:
        """创建Mock Redis客户端"""
        redis_mock = MagicMock()
        redis_mock.get.return_value = None
        redis_mock.set.return_value = True
        redis_mock.delete.return_value = True
        redis_mock.delete_pattern.return_value = 0
        redis_mock.get_info.return_value = {"status": "可用"}
        return redis_mock

    @pytest.fixture
    def cache_manager_with_redis(
        self, temp_cache_dir: Path, mock_redis_client: Mock
    ) -> CacheManager:
        """创建带Redis的CacheManager实例"""
        return CacheManager(cache_dir=temp_cache_dir, redis_client=mock_redis_client)

    def test_init_creates_cache_directory(self, temp_cache_dir: Path) -> None:
        """测试初始化时创建缓存目录"""
        cache_dir = temp_cache_dir / "test_cache"
        CacheManager(cache_dir=cache_dir)
        assert cache_dir.exists()
        assert cache_dir.is_dir()

    def test_set_and_get_memory_cache(self, cache_manager: CacheManager) -> None:
        """测试内存缓存的设置和获取"""
        cache_manager.set("test_key", "test_value", ttl=300)
        result = cache_manager.get("test_key")
        assert result == "test_value"

    def test_get_nonexistent_key_returns_none(self, cache_manager: CacheManager) -> None:
        """测试获取不存在的键返回None"""
        result = cache_manager.get("nonexistent_key")
        assert result is None

    def test_namespace_isolation(self, cache_manager: CacheManager) -> None:
        """测试命名空间隔离"""
        cache_manager.set("key1", "value1", namespace="user1")
        cache_manager.set("key1", "value2", namespace="user2")

        result1 = cache_manager.get("key1", namespace="user1")
        result2 = cache_manager.get("key1", namespace="user2")

        assert result1 == "value1"
        assert result2 == "value2"

    def test_set_memory_cache_ttl_selection(self, cache_manager: CacheManager) -> None:
        """测试根据TTL选择不同的内存缓存"""
        # 短TTL应该使用state_cache
        cache_manager.set("short_ttl", "value1", ttl=30)
        assert "default:short_ttl" in cache_manager._state_cache

        # 长TTL应该使用device_cache
        cache_manager.set("long_ttl", "value2", ttl=300)
        assert "default:long_ttl" in cache_manager._device_cache

    def test_invalidate_single_key(self, cache_manager: CacheManager) -> None:
        """测试失效单个缓存键"""
        cache_manager.set("test_key", "test_value")
        assert cache_manager.get("test_key") == "test_value"

        cache_manager.invalidate("test_key")
        assert cache_manager.get("test_key") is None

    def test_invalidate_pattern(self, cache_manager: CacheManager) -> None:
        """测试模式匹配失效"""
        cache_manager.set("device:123:status", "online")
        cache_manager.set("device:123:name", "Light")
        cache_manager.set("device:456:status", "offline")

        cache_manager.invalidate_pattern("device:123")

        assert cache_manager.get("device:123:status") is None
        assert cache_manager.get("device:123:name") is None
        assert cache_manager.get("device:456:status") == "offline"

    def test_file_cache_persistence(self, cache_manager: CacheManager) -> None:
        """测试文件缓存持久化"""
        # 长TTL会触发文件缓存
        cache_manager.set("persistent_key", {"data": "value"}, ttl=600)

        # 创建新的CacheManager实例，应该能从文件加载
        new_manager = CacheManager(cache_dir=cache_manager._cache_dir)
        result = new_manager.get("persistent_key")

        assert result == {"data": "value"}

    def test_get_stats(self, cache_manager: CacheManager) -> None:
        """测试缓存统计"""
        # 执行一些缓存操作
        cache_manager.set("key1", "value1")
        cache_manager.get("key1")  # L1 hit
        cache_manager.get("key2")  # miss

        stats = cache_manager.get_stats()

        assert stats["l1_hits"] == 1
        assert stats["misses"] == 1
        assert stats["redis_enabled"] is False
        assert "hit_rate" in stats

    def test_redis_integration(self, cache_manager_with_redis: CacheManager) -> None:
        """测试Redis集成"""
        manager = cache_manager_with_redis
        redis_client = manager._redis_client

        # 设置缓存应该调用Redis
        manager.set("test_key", "test_value", ttl=300)
        redis_client.set.assert_called_once()

        # 清空L1缓存，模拟从Redis读取
        manager._device_cache.clear()
        manager._state_cache.clear()

        # 模拟Redis返回数据
        redis_client.get.return_value = "test_value"
        result = manager.get("test_key")

        # 应该调用了Redis的get方法
        redis_client.get.assert_called()
        assert result == "test_value"

    def test_redis_failure_graceful_degradation(
        self, cache_manager_with_redis: CacheManager
    ) -> None:
        """测试Redis失败时的优雅降级"""
        manager = cache_manager_with_redis
        redis_client = manager._redis_client

        # 模拟Redis写入失败
        redis_client.set.side_effect = Exception("Redis连接失败")

        # 应该不抛出异常，继续使用内存缓存
        manager.set("test_key", "test_value")
        result = manager.get("test_key")
        assert result == "test_value"

    def test_redis_read_failure_fallback(self, cache_manager_with_redis: CacheManager) -> None:
        """测试Redis读取失败时回退到文件缓存"""
        manager = cache_manager_with_redis
        redis_client = manager._redis_client

        # 先设置一个长TTL的缓存（会写入文件）
        redis_client.set.side_effect = None
        manager.set("test_key", "test_value", ttl=600)

        # 清空内存缓存
        manager._device_cache.clear()
        manager._state_cache.clear()

        # 模拟Redis读取失败
        redis_client.get.side_effect = Exception("Redis读取失败")

        # 应该从文件缓存读取
        result = manager.get("test_key")
        assert result == "test_value"

    def test_cache_stats_with_redis(self, cache_manager_with_redis: CacheManager) -> None:
        """测试带Redis的缓存统计"""
        manager = cache_manager_with_redis
        stats = manager.get_stats()

        assert stats["redis_enabled"] is True
        assert "redis_info" in stats

    def test_hash_key_consistency(self, cache_manager: CacheManager) -> None:
        """测试键哈希的一致性"""
        key = "test:key:123"
        hash1 = cache_manager._hash_key(key)
        hash2 = cache_manager._hash_key(key)
        assert hash1 == hash2

    def test_complex_data_types(self, cache_manager: CacheManager) -> None:
        """测试复杂数据类型的缓存"""
        complex_data = {
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
            "string": "test",
            "number": 42,
            "boolean": True,
            "null": None,
        }

        cache_manager.set("complex_key", complex_data, ttl=600)
        result = cache_manager.get("complex_key")

        assert result == complex_data

    def test_l1_l2_l3_cache_hierarchy(
        self, cache_manager_with_redis: CacheManager, temp_cache_dir: Path
    ) -> None:
        """测试三层缓存层次结构"""
        manager = cache_manager_with_redis
        redis_client = manager._redis_client

        # 设置缓存（写入所有层）
        manager.set("hierarchy_key", "test_value", ttl=600)

        # 清空L1缓存
        manager._device_cache.clear()
        manager._state_cache.clear()

        # 模拟L2 Redis返回数据
        redis_client.get.return_value = "test_value"

        # 应该从L2获取并回填L1
        result = manager.get("hierarchy_key")
        assert result == "test_value"
        assert manager._stats["l2_hits"] == 1

        # 再次获取应该从L1命中
        result = manager.get("hierarchy_key")
        assert result == "test_value"
        assert manager._stats["l1_hits"] == 1

    def test_invalidate_with_redis(self, cache_manager_with_redis: CacheManager) -> None:
        """测试带Redis的缓存失效"""
        manager = cache_manager_with_redis
        redis_client = manager._redis_client

        manager.set("test_key", "test_value")
        manager.invalidate("test_key")

        # 应该调用Redis删除
        redis_client.delete.assert_called()

    def test_invalidate_pattern_with_redis(self, cache_manager_with_redis: CacheManager) -> None:
        """测试带Redis的模式失效"""
        manager = cache_manager_with_redis
        redis_client = manager._redis_client

        manager.invalidate_pattern("device:*")

        # 应该调用Redis批量删除
        redis_client.delete_pattern.assert_called_with("device:*")

    def test_file_cache_expires_and_is_removed(
        self, cache_manager: CacheManager, temp_cache_dir: Path
    ) -> None:
        """TTL 过期后文件缓存返回 None 且文件被清理"""
        manager = cache_manager
        # 直接调用底层方法写入一个 TTL=1s 的文件缓存
        manager._save_to_file("default:expiring", "payload", ttl=1)
        cache_file = temp_cache_dir / manager._hash_key("default:expiring")
        assert cache_file.exists()

        # 手动把 expires_at 改到过去，模拟过期
        import json
        import time as _time

        with open(cache_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["expires_at"] = _time.time() - 10
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        assert manager._load_from_file("default:expiring") is None
        assert not cache_file.exists()

    def test_file_cache_reads_legacy_format(
        self, cache_manager: CacheManager, temp_cache_dir: Path
    ) -> None:
        """旧格式（顶层即数据）的缓存文件仍能被正确读取"""
        import json

        manager = cache_manager
        legacy_path = temp_cache_dir / manager._hash_key("default:legacy")
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump({"foo": "bar"}, f)

        assert manager._load_from_file("default:legacy") == {"foo": "bar"}
