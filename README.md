# NovelMachine — 网文写作多 Agent 系统

基于 **多 Agent 编排 + RAG 混合检索** 的中文网文写作框架。

> 自然想法 → 大纲/卷纲/章纲 → 写手起草 → 并行审稿 → 修改循环 → 定稿 → 状态更新，完整写作闭环。

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)](https://www.python.org/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5+-blue)](https://www.trychroma.com/)
[![BM25](https://img.shields.io/badge/BM25-%E5%85%B3%E9%94%AE%E8%AF%8D%E6%A3%80%E7%B4%A2-orange)](https://github.com/dorianbrown/rank_bm25)
[![RAG](https://img.shields.io/badge/RAG-%E6%B7%B7%E5%90%88%E6%A3%80%E7%B4%A2-green)](docs/RAG.md)
[![OpenAI Compatible](https://img.shields.io/badge/API-OpenAI_Compatible-000000?logo=openai)](https://platform.openai.com/docs/api-reference)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 快速开始

```bash
# 1. 环境
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -e ".[dev]"

# 2. 配置：把 .env.example 复制成 .env，填入 SILICONFLOW_API_KEY（embedding 用）

# 3. 检索：资料放进 _bible/{题材}/raw/ → 摄入 → 查询
python cli.py ingest --genre xianxia
python rag_query.py "关键词" --search-only --top-k 5

# 4. 写作：复制书目录脚手架，把 .env 的 BOOK_DIR 指过去，
#    然后在 AI 会话里用 _agents/orchestrator.md 启动主编
cp -r _templates/book-scaffold ~/novels/mybook
```

> 429 限流时加 `--batch-size 16 --batch-delay 1`。
> 题材归类改 `config/genres.yaml`，不配也能跑（资料落入 `{题材}_general`）。

---

## 架构

```
你的 AI 会话（Claude / DeepSeek）
     │  读 _agents/ 说明书 + 组装上下文
     ▼
主编 Agent（对话式编排 · 刻意不脚本化）
     │
     ├── 写作循环 ──────────────────────────┐
     │   Writer → Reviewer + FormatChecker  │
     │   → 修改循环（≤3 轮）→ 定稿          │
     │   → 更新 novel_state.yaml            │
     └── 周期触发：Inspector / BetaReader / WorldBuilder
     │
     ▼ 检索资料
RAG 框架（novel_rag/）
     ├── ChromaDB（语义向量）──┐
     ├── BM25（jieba 关键词）──┼─ RRF 融合 → 结果
     └── config/genres.yaml ──┘（题材注册表）
```

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 编排 | AI 会话 + 主编 Agent | 主编在对话中调度 8 个专职 Agent，每步可检查/打断/覆写 |
| 语义检索 | ChromaDB + BGE-M3 | 向量检索，嵌入走 SiliconFlow OpenAI 兼容 API |
| 关键词检索 | BM25 + jieba 分词 | 专有名词精确匹配，与语义路 RRF 融合 |
| 配置 | `config/genres.yaml` | 题材注册表配置驱动，接入新资料无需改代码 |
| 状态 | `novel_state.yaml` | 角色/伏笔/时间线结构化快照，跨会话不丢 |
| 摄入 | 增量 + 限流自愈 | mtime 指纹增量；429 长退避重试（尊重 Retry-After） |
| 打包 | `pyproject.toml` | `pip install -e`，自带 `rag-query` / `novel-cli` 命令 |

---

## Agent 团队（8 个）

| 代号 | Agent | 职责 | 触发时机 |
|------|-------|------|---------|
| 主编 | Orchestrator | 调度团队、组装上下文、决策修改轮次、更新状态 | 全程 |
| A | Writer 写手 | 起草章节正文 | 每章 |
| B | Reviewer 审稿 | 四维审稿（爽点/文笔/水文/节奏） | 每章，与 E 并行 |
| E | FormatChecker 格式 | 标点/格式规则检查 | 每章，与 B 并行 |
| C | Inspector 校验 | 跨章数据一致性（3/5/10 章分层 + 卷末） | 周期 |
| D | BetaReader 读者 | 纯读者视角盲读（不看设定/大纲） | 开篇/高潮/卷末 |
| WB | WorldBuilder 设定 | 典籍检索 + 设定建造/矛盾修复 | 开书时 + Writer 标缺时 |
| OL | Outliner 大纲师 | 大纲/卷纲人机交互规划 | 开书时 + 每卷开始前 |

### 单章写作闭环

```
章纲（7 项评判自检）→ Writer 起草
  → Reviewer + FormatChecker 并行审稿
  → 通过 → 定稿 → 微型检查 → 更新 novel_state.yaml
  → 不通过 → 修改循环（≤3 轮）→ 仍不过 → 标记「需人工介入」
```

---

## 项目结构

本仓库**只含框架**，不含任何书稿：

```
├── novel_rag/                  # RAG 框架
│   ├── genre_registry.py       #   题材注册表（config/genres.yaml 驱动）
│   ├── ingestion/              #   加载/分块/嵌入（429 自愈重试）
│   ├── storage/                #   ChromaDB + BM25 双路存储
│   ├── retrieval/              #   混合检索（RRF 融合）+ LLM 重排
│   ├── generation/             #   生成（prompts/ 按题材定制）
│   └── prompts/                #   xianxia.txt / default.txt
├── _agents/                    # 8 个 Agent 岗位说明书 + NOTES.md（调校记录）
├── _templates/                 # 模板与 schema
│   ├── book-scaffold/          #   书目录脚手架（新开一本书从这里复制）
│   ├── schema/                 #   设定 YAML schema（权威）
│   ├── genres/xianxia/         #   题材专属字段速查
│   └── references/             #   起名热词表等写作参考
├── _workflows/                 # 章节体检（verify_punct.py）
├── _bible/                     # 题材素材占位（放自己的资料，不入库）
├── tests/                      # smoke test（pytest + manual_smoke.py）
├── docs/                       # RAG.md（设计 + 使用指南）
├── config/genres.yaml          # 题材注册表（可编辑）
├── cli.py / rag_query.py       # 命令行入口
└── DESIGN.md / _agents/REVIEW.md  # 系统设计与 Agent 评审记录
```

### 书目录（不在本仓库里）

一本书 = 一个自包含目录，路径由 `.env` 的 `BOOK_DIR` 指定，可以放在任何位置：

```
{BOOK_DIR}/
├── book.yaml           # 书名/题材/状态/当前卷（自描述）
├── novel_state.yaml    # 角色/伏笔/时间线结构化快照
├── world/              # 三大设定 + 角色/势力/物品 YAML
├── outline/            # 总大纲
├── volumes/            # 卷纲
├── beats/              # 章级节拍设计
├── chapters/           # 正文
├── reviews/            # 审稿报告
└── memory/             # 会话日志 / 作者方向 / 连续性
```

`BOOK_DIR` 未配置时回落到 `<仓库>/novels/<CURRENT_BOOK>/`，新克隆开箱即用。
Agent 说明书里的 `{book_dir}` 就是这个目录。

---

## 关键决策记录

| 决策 | 选什么 | 为什么不选另一个 |
|------|--------|------------------|
| **写作循环编排** | 对话式（主编在 AI 会话中调度） | 脚本化 workflow 不可打断、问题不可见；对话式每步可检查可覆写 |
| **状态管理** | `novel_state.yaml` 结构化快照 | 依赖 LLM 记忆会跨会话丢失；RAG 查前文只能精确检索，不能做状态感知 |
| **RAG 双路** | ChromaDB + BM25 RRF 融合 | 纯语义抓不住专有名词，纯关键词抓不住同义表达 |
| **题材接入** | `config/genres.yaml` 配置驱动 | 硬编码题材表，别人加资料要改代码 |
| **内容边界** | 仓库只含框架，资料与书稿用户自备 | 典籍版权不清；书稿是个人创作；框架才能通用，谁都能接入自己的资料 |
| **增量摄入** | mtime+size 指纹 | 全量重摄 1 万条 chunk 太慢、费 token |
| **429 限流** | 长退避重试 + 批间延时 | 重试 3 次退避 4s 扛不住 TPM 限流窗口 |

---

## 测试

```bash
pip install -e ".[dev]"
pytest                          # 网络受限时: python tests/manual_smoke.py
```

覆盖：题材归类规则、摄入→检索端到端、增量摄入、未注册题材兜底、prompt 按题材加载。

---

## License

[MIT](LICENSE)
