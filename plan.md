# 配置系统优化方案 (v3.0)

## 版本信息

- **版本号**：3.0.0
- **变更类型**：Breaking Change（目录结构变更）

## 需求分析

1. **自动创建配置文件**：服务器启动时，如果配置文件不存在，自动从模板创建默认配置文件
2. **配置热更新**：监控配置文件变化，当文件被修改时自动重新加载
3. **统一数据目录**：将 .mijia 文件夹移到 configs 目录下，统一管理
4. **自动迁移**：支持从 v2.x 版本自动迁移配置文件和数据

## 实现方案

### 1. 目录结构调整

**新结构 (v3.0)**
```
configs/
├── mijiaAPI.toml          # SDK配置文件（自动创建）
├── mijiaAPI.toml.template # SDK配置文件模板
├── server.toml            # 服务器配置文件（自动创建）
├── server.toml.template   # 服务器配置文件模板
├── credential.json        # 凭据文件（从 .mijia 迁移）
├── server/                # 服务器数据目录（从 .mijia/server 迁移）
│   └── server.sqlite3
├── cache/                 # 缓存目录（从 .mijia/cache 迁移）
└── README.md
```

**旧结构 (v2.x)**
```
.mijia/
├── credential.json
├── server/
│   └── server.sqlite3
└── cache/
```

### 2. 自动迁移逻辑

服务器启动时检测旧版本数据并自动迁移：
1. 检查 `.mijia` 目录是否存在
2. 如果存在，将文件迁移到 `configs` 目录
3. 迁移完成后，保留旧目录作为备份（可手动删除）

### 3. 版本管理

在配置文件中添加版本号字段：
```toml
[system]
version = "3.0.0"
migrated_from = "2.1.0"  # 迁移来源版本
```

## 代码修改清单

| 文件 | 修改内容 |
|------|----------|
| `pyproject.toml` | 版本号更新到 3.0.0 |
| `server/config.py` | 添加配置文件路径、热更新支持、迁移逻辑 |
| `server/config_watcher.py` | 新建：配置文件监控模块 |
| `server/app.py` | 添加配置初始化、热更新、迁移逻辑 |
| `server/mijia_runtime.py` | 支持配置热更新 |
| `server/cli.py` | 添加迁移命令支持 |
| `configs/server.toml.template` | 新建：服务器配置文件模板 |

## 迁移流程

```python
def migrate_v2_to_v3():
    """从 v2.x 迁移到 v3.0"""
    old_dir = Path(".mijia")
    new_dir = Path("configs")
    
    if old_dir.exists():
        # 迁移凭据文件
        if (old_dir / "credential.json").exists():
            shutil.move(old_dir / "credential.json", new_dir / "credential.json")
        
        # 迁移服务器数据
        if (old_dir / "server").exists():
            shutil.move(old_dir / "server", new_dir / "server")
        
        # 迁移缓存
        if (old_dir / "cache").exists():
            shutil.move(old_dir / "cache", new_dir / "cache")
        
        # 保留旧目录作为备份
        old_dir.rename(old_dir / ".backup")
```

## 注意事项

1. **配置热更新时需要考虑线程安全**
2. **某些配置修改可能需要重启服务才能生效**
3. **需要保持向后兼容，自动迁移旧版本数据**
4. **迁移过程需要记录日志，便于排查问题**
