# 配置文件说明

本目录是 **默认数据目录**（`MIJIA_SERVER_DATA_DIR=configs`），同时存放 SDK / Server 的 TOML 模板。

## 运行时文件（勿提交）

| 路径 | 说明 |
|------|------|
| `credential.json` | 米家凭据（AES-GCM 加密） |
| `.credential_key` | 本地加密密钥（二进制；可用 `MIJIA_CREDENTIAL_SECRET` 覆盖）。备份时须与 `credential.json` 成对复制，勿当文本编辑 |
| `server/server.sqlite3` | 管理台 SQLite |
| `cache/` | SDK 磁盘缓存（L3） |
| `server.toml` | Server 配置（可由 CLI 生成） |

旧版项目根目录下的 `.mijia/` 会在 Server 启动时迁移到本目录，**迁移后自动删除**（含 `.mijia_backup*`），不保留备份。

## 模板文件（可提交）

- `server.toml.template` — API Server 配置模板  
  生成：`python -m server.cli write-config`
- `mijiaAPI.toml.template` — SDK 配置模板

```bash
python -m server.cli write-config
cp configs/mijiaAPI.toml.template configs/mijiaAPI.toml   # 如需自定义 SDK
```

## SDK 配置查找顺序

1. `configs/mijiaAPI.toml`（推荐）
2. 项目根目录 `config.toml`
3. `~/.mijia/config.toml`（可选：多项目共享的用户级配置）
4. SDK 内置默认值

默认凭据路径：`configs/credential.json`；默认缓存：`configs/cache`。

## 敏感信息

`*.toml`（除 `*.toml.template`）与凭据、数据库、缓存已在 `.gitignore` 中忽略。

## 更多信息

- [配置说明](../docs/使用指南/03-配置说明.md)
- [API Server 开发启动](../docs/开发指南/05-API-Server-开发启动.md)
- `python -m server.cli status`
