# AGENTS.md — Agent 协作说明（跨工具通用）

> 本文件遵循 [AGENTS.md 标准](https://agents.md)，供任何 AI 编码/写作工具（Claude Code、Cursor、Codex、DeepSeek Harness 等）在打开本项目时自动读取。工具专属配置：Claude/DSH 另见 [CLAUDE.md](CLAUDE.md)。

## 项目是什么

**NovelMachine** — 中文网文写作多 Agent 框架：多 Agent 编排（对话式）+ RAG 混合检索（ChromaDB 语义 + BM25 关键词 + RRF 融合）。

## 快速上手（3 步）

1. **安装**：运行 `setup.bat`（Windows）或 `bash setup.sh`（macOS/Linux），自动建 venv + 装依赖 + 生成 .env
2. **配置**：编辑 `.env`，填入 `SILICONFLOW_API_KEY`（SiliconFlow 密钥，用于 embedding）
3. **摄入资料**：`python cli.py ingest --genre xianxia`（资料放 `_bible/{题材}/raw/`）

## 常用命令

```bash
python cli.py ingest --genre xianxia        # 摄入资料（429 限流加 --batch-size 16 --batch-delay 1）
python rag_query.py "关键词" --search-only   # 查询（JSON 输出，Agent 用）
python rag_query.py "关键词"                 # 查询 + 生成回答
python cli.py info                          # 查看索引状态
```

## 目录约定

- `novel_rag/` — RAG 框架（ingestion/storage/retrieval/generation）
- `_agents/` — 8 个 Agent 岗位说明书（主编/写手/审稿/校验/读者/格式/设定/大纲）
- `_templates/` — 大纲/卷纲/章纲模板 + schema
- `_workflows/` — 校验脚本
- `config/genres.yaml` — 题材注册表（配置驱动，加题材无需改代码）
- `docs/RAG.md` — RAG 设计 + 使用指南

## 写作工作流（给 AI 的协作约定）

1. 写作循环由**主编 Agent**（`_agents/orchestrator.md`）在对话中调度，刻意不脚本化——每步可检查/打断/覆写
2. 书级内容按书名命名空间隔离：`_outline/{book}/`、`chapters/{book}/`、`_memory/{book}/`、`_reviews/{book}/`
3. 设定 YAML 在 `_outline/{book}/world/`；`_outline/{book}/novel_state.yaml` 是每章定稿后更新的状态快照
4. 查资料：`python rag_query.py "<关键词>" --search-only --top-k 5`（输出 JSON，直接可用）
5. 跑 Python 脚本用虚拟环境：Windows `venv/Scripts/python.exe`，macOS/Linux `venv/bin/python`

## 测试

```bash
pip install -r requirements.txt
pytest                          # 网络受限时: python tests/manual_smoke.py
```
