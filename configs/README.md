# 配置文件说明

本目录包含米家API SDK的配置文件。

## 文件说明

- `*.toml.template` - 配置模板文件，提交到版本控制
- `*.toml` - 实际使用的配置文件，已在 `.gitignore` 中忽略

## 配置文件查找顺序

SDK会按以下顺序查找配置文件（优先级从高到低）：

1. `configs/mijiaAPI.toml` - 项目根目录的configs目录（推荐）
2. `config.toml` - 项目根目录
3. `~/.mijia/config.toml` - 用户主目录
4. SDK自带的默认配置 - 最低优先级

## 首次使用

复制模板文件创建实际配置：

```bash
cp configs/default.toml.template configs/mijiaAPI.toml
```

然后根据需要修改 `mijiaAPI.toml` 中的配置项。

## 不同使用场景

### 项目级配置（推荐）
使用 `configs/mijiaAPI.toml`，适合将配置保存在项目目录中：
```bash
cp configs/default.toml.template configs/mijiaAPI.toml
```

### 项目根目录配置
使用 `config.toml`，适合简单项目：
```bash
cp configs/default.toml.template config.toml
```

### 全局配置
使用 `~/.mijia/config.toml`，适合多个项目共享配置：
```bash
mkdir -p ~/.mijia
cp configs/default.toml.template ~/.mijia/config.toml
```

## 配置文件不会被提交

为了保护敏感信息，所有 `*.toml` 文件（除了 `*.toml.template`）都已在 `.gitignore` 中忽略，不会被提交到版本控制。

你可以放心地在配置文件中添加：
- Redis 密码
- 自定义的超时时间
- 日志路径
- 其他个性化配置

## 更多信息

详细的配置说明请参考：[配置说明文档](../docs/使用指南/03-配置说明.md)
