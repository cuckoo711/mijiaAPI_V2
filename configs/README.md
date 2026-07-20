# 配置文件说明

本目录是 **API Server 默认数据目录**（`MIJIA_SERVER_DATA_DIR=configs`），同时存放 SDK / Server 的 TOML 模板。

## 运行时文件（勿提交）

| 路径 | 说明 |
|------|------|
| `credential.json` | 米家凭据（AES-GCM 加密） |
| `.credential_key` | 本地生成的加密密钥（可用环境变量 `MIJIA_CREDENTIAL_SECRET` 覆盖） |
| `server/server.sqlite3` | 管理台 SQLite |
| `cache/` | SDK 磁盘缓存（L3） |
| `server.toml` | Server 配置（可由 CLI 生成） |

旧版 `.mijia/` 布局会在启动时幂等迁移到本目录；迁移完成后不应再保留有效 `.mijia` 数据。

## 模板文件（可提交）

- `server.toml.template` — API Server 配置模板  
  生成：`python -m server.cli write-config`
- `mijiaAPI.toml.template` — SDK 配置模板

复制模板：

```bash
# Server
python -m server.cli write-config
# 或
cp configs/server.toml.template configs/server.toml

# SDK（如需）
cp configs/mijiaAPI.toml.template configs/mijiaAPI.toml
```

## SDK 配置查找顺序

优先级从高到低：

1. `configs/mijiaAPI.toml`（推荐）
2. 项目根目录 `config.toml`
3. `~/.mijia/config.toml`（多项目共享的用户主目录配置）
4. SDK 内置默认值

> 注意：用户主目录的 `~/.mijia/` 是 **SDK 全局配置/凭据的可选位置**，与 Server 数据目录 `configs/` 不是同一概念。Server 部署请优先使用 `configs/`。

## 敏感信息

`*.toml`（除 `*.toml.template`）与凭据、数据库、缓存已在 `.gitignore` 中忽略，请勿提交密钥或生产库。

## 更多信息

- [配置说明](../docs/使用指南/03-配置说明.md)
- [API Server 开发启动](../docs/开发指南/05-API-Server-开发启动.md)
- 运维快照：`python -m server.cli status`
