# CLAUDE.md

> 在 AI 会话（Claude/DeepSeek 等）中使用本框架时的协作约定。

## 项目结构

- `novel_rag/` — RAG 检索框架（资料向量化 + 混合检索）
- `_agents/` — Agent 岗位说明书（主编/写手/审稿/校验/读者/格式/设定/大纲）
- `_templates/` — 大纲/卷纲/章纲模板
- `_workflows/verify_punct.py` — 标点校验脚本
- `docs/` — 使用文档

## 约定

- 所有书级内容按书名命名空间隔离：`_outline/{book}/`、`chapters/{book}/`、`_memory/{book}/`、`_reviews/{book}/`
- 设定 YAML 位于 `_outline/{book}/world/`；`_outline/{book}/novel_state.yaml` 是每章定稿后更新的状态快照
- 写作循环由主编 Agent（`_agents/orchestrator.md`）在对话中调度，刻意不脚本化
- 查询资料：`python rag_query.py "<关键词>" --search-only --top-k 5`
- 跑 Python 脚本时使用虚拟环境：`venv/Scripts/python.exe`（或对应平台的激活路径）
