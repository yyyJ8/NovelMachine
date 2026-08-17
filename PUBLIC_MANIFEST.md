# 公开清单（PUBLIC MANIFEST）

> 本文件定义私有工作区 → 公开仓库（NovelMachine）的导出边界。
> 私有仓库（NOVEL）是工作区，包含小说正文、审稿、写作记忆，**永不公开**。
> 公开仓库（NovelMachine）只含工具框架，供分享/开源。
> 导出由 `export_public.ps1` 执行（复制 + 生成公开版文件 + commit + push）。

## ✅ 公开（复制进公开仓库）

| 路径 | 说明 |
|------|------|
| `novel_rag/` | RAG 框架（配置注册表/摄入/存储/检索/生成） |
| `_agents/` | 8 个 Agent 岗位说明书 |
| `_templates/` | 大纲/卷纲/章纲模板 + schema |
| `_workflows/verify_punct.py` | 标点校验脚本 |
| `cli.py` / `rag_query.py` | CLI 入口 |
| `requirements.txt` / `pyproject.toml` | 依赖与打包 |
| `.env.example` | 环境配置示例（不含真实 key） |
| `config/genres.yaml` | 题材注册表（默认配置） |
| `docs/RAG_USAGE.md` | RAG 使用指南 |
| `RAG_DESIGN.md` | RAG 技术设计文档（已确认无敏感信息） |
| `AGENT_REVIEW.md` | Agent 评审方法论（通用，无书专属内容） |
| `LICENSE` | 公开版模板（`_public_templates/LICENSE`，MIT） |
| `README.md` | 公开版模板（`_public_templates/README.md`，陌生人视角） |
| `CLAUDE.md` | 公开版模板（`_public_templates/CLAUDE.md`，去个人化约定） |
| `.gitignore` | 公开版模板（`_public_templates/.gitignore`，UTF-8） |

> 四个公开版文件是**独立 UTF-8 模板**，由 `export_public.ps1` 复制进公开仓库；
> 修改公开版文案时直接编辑 `_public_templates/` 下的文件，不要动私有版。

## ❌ 私有（永不导出）

| 路径 | 原因 |
|------|------|
| `chapters/` `_reviews/` `_outline/` `_memory/` | 小说正文/审稿/大纲/写作记忆 |
| `_bible/` | 典籍资料（符合"资料自备"定位） |
| `.env` | 真实 API Key |
| `venv/` `chroma_db/` `bm25_indexes/` | 环境与索引产物 |
| `INTERVIEW_GUIDE.md` | 个人求职指南 |
| `DESIGN.md` | 含《断则》创作设计（分卷规划/设定表） |
| `src/` `mvp_chapter.py` `run_mvp.bat` `test_context.py` `_check_punct.py` | 早期遗留 MVP，已被 novel_rag 取代 |

## 🔧 导出时自动处理

| 处理 | 说明 |
|------|------|
| 复制 `_public_templates/` 四件套 | LICENSE / README.md / CLAUDE.md / .gitignore |
| `_templates/schema/events.yaml` | "林尘"示例 → "主角"（去书专属） |

## ⚠️ 双仓库纪律

1. 公开仓库必须独立 `git init`/clone，**禁止**复制私有仓库 `.git`（提交历史会泄露内容）
2. 日常只更新私有仓库；想发布时跑 `export_public.ps1`
3. 不要给私有仓库添加公开 remote（防手滑 push 小说）
