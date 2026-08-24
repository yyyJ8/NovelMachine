@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title NovelMachine Setup

echo ============================================================
echo   NovelMachine - 一键安装（Windows）
echo   自动完成: Python 虚拟环境 + 依赖安装 + .env 模板生成
echo ============================================================
echo.

REM ── 0. 检查 Python ──────────────────────────────────────
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+（https://www.python.org/downloads/）
    echo        安装时请勾选 "Add Python to PATH"。
    pause
    exit /b 1
)

for /f "delims=" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [1/4] 检测到 %PYVER%

REM ── 1. 创建虚拟环境 ─────────────────────────────────────
if exist venv (
    echo [2/4] venv 已存在，跳过创建
) else (
    echo [2/4] 创建虚拟环境 venv/ ...
    python -m venv venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败
        pause
        exit /b 1
    )
)

REM ── 2. 安装依赖 ─────────────────────────────────────────
echo [3/4] 安装依赖（首次约需 1-3 分钟）...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>nul
pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试
    pause
    exit /b 1
)

REM ── 3. 生成 .env ────────────────────────────────────────
if exist .env (
    echo [4/4] .env 已存在，跳过生成
) else (
    echo [4/4] 生成 .env 模板（请编辑填入你的 API Key）...
    copy .env.example .env >nul
)

echo.
echo ============================================================
echo   安装完成！
echo.
echo   下一步：
echo     1. 编辑 .env，填入 SILICONFLOW_API_KEY
echo     2. 把资料放进 _bible/{题材}/raw/
echo     3. 运行: python cli.py ingest --genre xianxia
echo     4. 查询: python rag_query.py "关键词" --search-only
echo ============================================================
pause
