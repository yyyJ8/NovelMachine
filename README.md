# NovelMachine — 网文写作多 Agent 系统

用多个 AI Agent 协作写小说：RAG 资料检索为骨，Agent 为笔。

## 这是什么

一套面向中文网文写作的多 Agent 工作流 + RAG 检索框架：

- **RAG 检索**（`novel_rag/`）：把你自己提供的资料（典籍/设定/语料）向量化，ChromaDB（语义）+ BM25（关键词）双路混合检索，RRF 融合，可选 LLM 重排。题材注册表配置驱动，接入新资料无需改代码。
- **多 Agent 写作管线**（`_agents/`）：8 个专职 Agent —— 主编（调度）、写手、审稿、跨章校验、读者盲读、格式检查、设定研究员、大纲师。主编在 AI 会话中逐步调度，每章经过「写作 → 并行审稿 → 修改（≤3 轮）→ 定稿 → 状态更新」闭环。
- **三层规划体系**（`_templates/`）：大纲（人定）→ 卷纲（人机协商）→ 章纲（机定 + 评判体系）。
- **状态持久化**：`novel_state.yaml` 存故事内部状态（角色/伏笔/时间线），写作记忆按书隔离。

## 快速开始（约 30 分钟）

```bash
# 1. 装环境
python -m venv venv
venv/Scripts/activate          # Windows；macOS/Linux: source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env           # 填 API Key（详见 .env.example 注释）

# 2. 放资料：把自己要检索的资料放进 _bible/{题材}/raw/
#    （可选）在 config/genres.yaml 里加归类规则；不配置也能跑，资料落入 {题材}_general

# 3. 摄入
python cli.py ingest --genre {题材}

# 4. 查询（Agent 用 --search-only 输出 JSON）
python rag_query.py "关键词" --search-only --top-k 5

# 5. 写作：把 _agents/ + _templates/ 放进你的 AI 会话项目
#    （Claude/DeepSeek 等），让主编 Agent 调度写作循环
```

详细用法见 [docs/RAG_USAGE.md](docs/RAG_USAGE.md)，检索系统设计见 [RAG_DESIGN.md](RAG_DESIGN.md)。

## 目录结构

```
novel_rag/          RAG 框架（摄入/存储/检索/生成）
_agents/            Agent 岗位说明书（主编/写手/审稿/校验/读者/格式/设定/大纲）
_templates/         大纲/卷纲/章纲模板
_workflows/         校验脚本（verify_punct.py）
docs/               使用文档
config/genres.yaml  题材注册表（配置驱动，可编辑）
cli.py / rag_query.py   命令行入口
```

## 设计哲学

- **人机协作**：系统是作者的放大器，不是替代品。大纲人定、卷纲人机协商、章纲机定，任何 Agent 输出人类都可覆写。
- **状态显式化**：不依赖 LLM 记忆，关键状态全部落在结构化文件中，跨会话不丢。
- **对话式编排**：写作循环刻意不脚本化——主编在对话中逐步调度，每步可检查、可打断、可覆写，问题在何处发生一目了然。

## 测试

```bash
pip install -e ".[dev]"
pytest                 # 或网络受限时: python tests/manual_smoke.py
```

## License

[MIT](LICENSE)
