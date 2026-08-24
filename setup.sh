#!/usr/bin/env bash
# NovelMachine 一键安装（macOS / Linux）
# 自动完成: Python 虚拟环境 + 依赖安装 + .env 模板生成
set -euo pipefail

echo "============================================================"
echo "  NovelMachine - 一键安装 (macOS/Linux)"
echo "============================================================"

# ── 0. 检查 Python ──────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[错误] 未找到 python3，请先安装 Python 3.10+"
    exit 1
fi
echo "[1/4] 检测到 $(python3 --version)"

# ── 1. 创建虚拟环境 ─────────────────────────────────────
if [ -d "venv" ]; then
    echo "[2/4] venv 已存在，跳过创建"
else
    echo "[2/4] 创建虚拟环境 venv/ ..."
    python3 -m venv venv
fi

# ── 2. 安装依赖 ─────────────────────────────────────────
echo "[3/4] 安装依赖（首次约需 1-3 分钟）..."
# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r requirements.txt

# ── 3. 生成 .env ────────────────────────────────────────
if [ -f ".env" ]; then
    echo "[4/4] .env 已存在，跳过生成"
else
    echo "[4/4] 生成 .env 模板（请编辑填入你的 API Key）..."
    cp .env.example .env
fi

echo ""
echo "============================================================"
echo "  安装完成！"
echo ""
echo "  下一步："
echo "    1. 编辑 .env，填入 SILICONFLOW_API_KEY"
echo "    2. 把资料放进 _bible/{题材}/raw/"
echo "    3. 运行: python cli.py ingest --genre xianxia"
echo "    4. 查询: python rag_query.py \"关键词\" --search-only"
echo "============================================================"
