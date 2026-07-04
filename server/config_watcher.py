"""配置文件监控模块

监控配置文件变化，当文件被修改时自动重新加载。
"""

import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional


class ConfigWatcher:
    """配置文件监控器
    
    监控指定的配置文件，当文件被修改时触发回调函数。
    
    Args:
        file_path: 要监控的文件路径
        callback: 文件变化时的回调函数
        interval: 检查间隔（秒），默认5秒
    """
    
    def __init__(
        self,
        file_path: Path,
        callback: Callable[[Path], Any],
        interval: int = 5
    ):
        self.file_path = file_path
        self.callback = callback
        self.interval = interval
        self._running = False
        self._last_mtime: Optional[float] = None
        self._thread: Optional[threading.Thread] = None
        
    def start(self) -> None:
        """启动监控"""
        if self._running:
            return
            
        self._running = True
        
        # 记录初始修改时间
        if self.file_path.exists():
            self._last_mtime = self.file_path.stat().st_mtime
        else:
            self._last_mtime = 0
            
        # 启动监控线程
        self._thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name=f"config-watcher-{self.file_path.name}"
        )
        self._thread.start()
        
    def stop(self) -> None:
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
            
    def check_now(self) -> bool:
        """立即检查一次文件变化
        
        Returns:
            True if file was changed, False otherwise
        """
        if not self.file_path.exists():
            return False
            
        current_mtime = self.file_path.stat().st_mtime
        if self._last_mtime is None or current_mtime > self._last_mtime:
            self._last_mtime = current_mtime
            self.callback(self.file_path)
            return True
        return False
        
    def _watch_loop(self) -> None:
        """监控循环"""
        while self._running:
            time.sleep(self.interval)
            try:
                if self.file_path.exists():
                    current_mtime = self.file_path.stat().st_mtime
                    if self._last_mtime is None or current_mtime > self._last_mtime:
                        # 文件已修改
                        self._last_mtime = current_mtime
                        try:
                            self.callback(self.file_path)
                        except Exception as e:
                            # 回调函数出错不影响监控
                            print(f"Config watcher callback error: {e}")
            except Exception as e:
                # 监控过程出错，继续运行
                print(f"Config watcher error: {e}")


class MultiConfigWatcher:
    """多配置文件监控器
    
    同时监控多个配置文件。
    """
    
    def __init__(self):
        self._watchers: dict[str, ConfigWatcher] = {}
        
    def add_watcher(
        self,
        name: str,
        file_path: Path,
        callback: Callable[[Path], Any],
        interval: int = 5
    ) -> None:
        """添加监控
        
        Args:
            name: 监控名称
            file_path: 要监控的文件路径
            callback: 文件变化时的回调函数
            interval: 检查间隔（秒）
        """
        if name in self._watchers:
            # 停止旧的监控
            self._watchers[name].stop()
            
        watcher = ConfigWatcher(file_path, callback, interval)
        self._watchers[name] = watcher
        
    def start_all(self) -> None:
        """启动所有监控"""
        for watcher in self._watchers.values():
            watcher.start()
            
    def stop_all(self) -> None:
        """停止所有监控"""
        for watcher in self._watchers.values():
            watcher.stop()
            
    def remove_watcher(self, name: str) -> None:
        """移除监控"""
        if name in self._watchers:
            self._watchers[name].stop()
            del self._watchers[name]
