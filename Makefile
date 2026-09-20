.PHONY: help clean clean-all test test-cov format lint type-check install dev

# 代码质量与测试的参数统一在 pyproject.toml 里配置
# （[tool.flake8] / [tool.mypy] / [tool.pytest.ini_options]），
# 这里不再重复传递，避免命令行参数覆盖配置导致两套标准。

help:
	@echo "可用命令："
	@echo "  make clean        - 清理缓存和临时文件"
	@echo "  make clean-all    - 清理所有生成文件（含覆盖率报告与构建产物）"
	@echo "  make test         - 运行测试"
	@echo "  make test-cov     - 运行测试并生成覆盖率报告"
	@echo "  make format       - 格式化代码（black + isort）"
	@echo "  make lint         - 代码质量检查（flake8）"
	@echo "  make type-check   - 类型检查（mypy）"
	@echo "  make install      - 安装依赖"
	@echo "  make dev          - 安装开发依赖"

clean:
	@uv run python deploy/scripts/clean.py

clean-all:
	@uv run python deploy/scripts/clean.py --all

# pyproject 的 addopts 默认开启覆盖率统计，所以快速测试显式关掉。
test:
	@echo "运行测试..."
	@uv run pytest tests/ --no-cov

test-cov:
	@echo "运行测试并生成覆盖率报告..."
	@uv run pytest tests/
	@echo "✓ 覆盖率报告已生成到 htmlcov/ 目录"

format:
	@echo "格式化代码..."
	@uv run black mijiaAPI_V2/ server/ tests/ examples/ deploy/scripts/
	@uv run isort mijiaAPI_V2/ server/ tests/ examples/ deploy/scripts/
	@echo "✓ 代码格式化完成"

lint:
	@echo "代码质量检查..."
	@uv run flake8 mijiaAPI_V2/ server/
	@echo "✓ flake8 检查通过"

type-check:
	@echo "类型检查..."
	@uv run mypy mijiaAPI_V2/ server/
	@echo "✓ 类型检查通过"

install:
	@echo "安装依赖..."
	@uv sync
	@echo "✓ 依赖安装完成"

dev: install
	@echo "开发环境已准备就绪"
