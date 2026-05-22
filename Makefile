.PHONY: help clean clean-all test test-cov format lint type-check install dev

help:
	@echo "可用命令："
	@echo "  make clean        - 清理缓存和临时文件"
	@echo "  make clean-all    - 清理所有生成文件（包括覆盖率报告）"
	@echo "  make test         - 运行测试"
	@echo "  make test-cov     - 运行测试并生成覆盖率报告"
	@echo "  make format       - 格式化代码（black + isort）"
	@echo "  make lint         - 代码质量检查（flake8 + pylint）"
	@echo "  make type-check   - 类型检查（mypy）"
	@echo "  make install      - 安装依赖"
	@echo "  make dev          - 安装开发依赖"

clean:
	@echo "清理缓存和临时文件..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name "*.pyd" -delete 2>/dev/null || true
	@rm -rf .mypy_cache/ .pytest_cache/ 2>/dev/null || true
	@find . -type f -name "*.tmp" -delete 2>/dev/null || true
	@find . -type f -name "*.log" -delete 2>/dev/null || true
	@find . -type f -name ".DS_Store" -delete 2>/dev/null || true
	@echo "✓ 清理完成"

clean-all: clean
	@echo "清理所有生成文件..."
	@rm -rf .coverage .coverage.* htmlcov/ 2>/dev/null || true
	@rm -rf dist/ build/ *.egg-info/ *.egg 2>/dev/null || true
	@echo "✓ 清理完成"

test:
	@echo "运行测试..."
	@uv run pytest tests/ -v

test-cov:
	@echo "运行测试并生成覆盖率报告..."
	@uv run pytest tests/ -v --cov=mijiaAPI_V2 --cov-report=html --cov-report=term
	@echo "✓ 覆盖率报告已生成到 htmlcov/ 目录"

format:
	@echo "格式化代码..."
	@uv run black mijiaAPI_V2/ server/ tests/ examples/ scripts/
	@uv run isort mijiaAPI_V2/ server/ tests/ examples/ scripts/
	@echo "✓ 代码格式化完成"

lint:
	@echo "代码质量检查..."
	@uv run flake8 mijiaAPI_V2/ server/ --max-line-length=120 --extend-ignore=E203,W503
	@echo "✓ flake8 检查通过"

type-check:
	@echo "类型检查..."
	@uv run mypy mijiaAPI_V2/ server/ --ignore-missing-imports
	@echo "✓ 类型检查通过"

install:
	@echo "安装依赖..."
	@uv sync
	@echo "✓ 依赖安装完成"

dev: install
	@echo "开发环境已准备就绪"
