# CLAUDE.md

> 在 AI 会话（Claude/DeepSeek 等）中使用本框架时的协作约定。

## 项目结构

- `novel_rag/` — RAG 检索框架（资料向量化 + 混合检索）
- `_agents/` — Agent 岗位说明书（主编/写手/审稿/校验/读者/格式/设定/大纲）
- `_templates/` — 大纲/卷纲/章纲模板
- `_workflows/verify_punct.py` — 标点校验脚本
- `docs/` — 使用文档
- `AGENTS.md` — 跨工具 Agent 协作说明（Claude Code/Cursor/Codex 通用）

## 快速上手（3 步）

1. 安装：运行 `setup.bat`（Windows）或 `bash setup.sh`（macOS/Linux），自动建 venv + 装依赖 + 生成 .env
2. 配置：编辑 `.env` 填入 `SILICONFLOW_API_KEY`
3. 摄入资料：`python cli.py ingest --genre xianxia`（资料放 `_bible/{题材}/raw/`）

## 写作工作流

用户提出写作需求时，按以下流程协作：

1. 阅读 `_agents/orchestrator.md`（主编岗位说明书），确认当前写作阶段
2. 按主编调度：需要查资料时用 `python rag_query.py "<关键词>" --search-only --top-k 5`
3. 写作前先读 `_outline/{book}/novel_state.yaml`（当前状态快照）+ 章纲模板（`_templates/chapter-beat-template.md`）
4. 写作循环由主编 Agent 在对话中调度，刻意不脚本化——每步可检查/打断/覆写

## 约定

- 所有书级内容按书名命名空间隔离：`_outline/{book}/`、`chapters/{book}/`、`_memory/{book}/`、`_reviews/{book}/`
- 设定 YAML 位于 `_outline/{book}/world/`；`_outline/{book}/novel_state.yaml` 是每章定稿后更新的状态快照
- 写作循环由主编 Agent（`_agents/orchestrator.md`）在对话中调度，刻意不脚本化
- 查询资料：`python rag_query.py "<关键词>" --search-only --top-k 5`
- 跑 Python 脚本时使用虚拟环境：`venv/Scripts/python.exe`（或对应平台的激活路径）
