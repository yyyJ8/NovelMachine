# RAG 使用指南 —— 接入你自己的资料

本项目的 RAG 部分是一个**框架**：仓库里不含任何典籍内容，你需要提供自己的资料进行向量化。

## 一、安装

```bash
# 推荐使用虚拟环境
python -m venv venv
venv/Scripts/activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -e .
```

然后复制 `.env.example` 为 `.env` 并填写 API Key：

```bash
cp .env.example .env
```

> 需要生成回答/重排时，可另配 `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`（OpenAI 兼容接口）；
> 只做检索（`--search-only`）则只需 embedding 的 `SILICONFLOW_API_KEY`。

## 二、目录结构约定

资料放在 `_bible/{题材}/raw/` 下：

```
_bible/
└── xianxia/            ← 题材目录（名字自定：wuxia / scifi / fantasy ...）
    └── raw/
        ├── 01-道藏核心/道德經.txt
        ├── 02-神话仙传/山海經.txt
        └── ...
```

支持 `.md` / `.txt` / `.pdf`，自动检测 UTF-8 / GBK 编码。文件名建议格式 `书名-朝代-作者.txt`（会解析进元数据，非强制）。

## 三、配置题材规则（可选）

`config/genres.yaml` 定义每个题材的归类规则（哪些目录/关键词 → 哪个 collection）。

**最小可用**：不配置也行。摄入未注册题材时，所有资料自动落入 `{题材}_general` 兜底 collection。

**精细归类**（推荐，检索质量更好）：追加题材配置：

```yaml
genres:
  wuxia:
    path: wuxia                      # _bible/ 下的目录名
    default_collection: wuxia_general
    processed_default_collection: wuxia_terminology
    collections:
      - name: wuxia_classics         # 目录含 "经典" 的资料 → 此 collection
        dir_keywords: ["经典"]
      - name: wuxia_terminology      # processed/ 下文件名含 "术语" → 此 collection
        file_keywords: ["术语"]
```

**生成 prompt 定制**（可选）：在 `novel_rag/prompts/` 下放 `{题材}.txt`，生成回答时会用它做系统提示词，未配置则用 `default.txt`。

## 四、摄入

```bash
# 摄入单个题材
python cli.py ingest --genre xianxia

# 摄入全部题材（自动扫描 _bible/ 下所有目录）
python cli.py ingest --all

# 摄入前清空该题材旧索引（改分块策略/换模型后必须 --clear 重建）
python cli.py ingest --genre xianxia --clear

# 分块策略：classical（古文，默认）/ fixed / markdown / sentence
python cli.py ingest --genre xianxia --strategy sentence

# 任一环节失败立即报错（默认是收集 warnings 继续）
python cli.py ingest --genre xianxia --strict

# 增量摄入：只处理新增/变更文件（依据 mtime+size 指纹，大幅省时间）
python cli.py ingest --genre xianxia --incremental

# 429 限流时降速：调小批大小 + 加大批间延时
python cli.py ingest --genre xianxia --clear --batch-size 16 --batch-delay 1
```

查看索引状态：`python cli.py info`

## 五、查询

```bash
# 检索 + 生成回答
python rag_query.py "金丹期如何突破"

# 只检索（Agent 用，输出 JSON）
python rag_query.py "金丹期如何突破" --search-only

# 限定题材 / 调整返回条数
python rag_query.py "天劫" --genre xianxia --top-k 10

# 交互式查询（CLI）
python cli.py query --interactive

# 启用 LLM 重排（更准但更慢更贵）
python rag_query.py "阵法" --search-only --top-k 10 --rerank 2>NUL
```

## 六、常见问题

| 问题 | 处理 |
|------|------|
| 摄入时报 **429 限流** | 分两层应对：① **自动**——embedder 对 429 做长退避重试（默认最多 10 次、单次最长等 60s，尊重 `Retry-After` 头），限流窗口恢复后自动继续，1 万条最终能全部啃完（只是慢）；② **手动降速**——`--batch-size 16/8`（减单批 token 量）+ `--batch-delay 1~3`（批间 sleep），或在 `.env` 设 `EMBEDDING_BATCH_SIZE` / `EMBEDDING_BATCH_DELAY` / `RATE_LIMIT_MAX_RETRIES` / `RATE_LIMIT_MAX_WAIT` |
| 摄入后查询无结果 | 检查 `python cli.py info` 的 collection 是否为空；确认资料在 `_bible/{题材}/raw/` 下 |
| 换 embedding 模型报维度错 | `.env` 里同步改 `EMBEDDING_DIM`，并 `--clear` 重建索引 |
| 重复摄入产生脏数据 | 用 `--clear` 全量重建；日常新增资料用 `--incremental` 增量摄入 |
| 删除资料后索引未清理 | 目前增量摄入不做删除同步；删除文件后建议 `--clear` 重建一次 |
| 检索结果都落进一个 collection | 在 `config/genres.yaml` 里细化 `dir_keywords` 规则 |
| 不想用生成回答 | 一直用 `--search-only`，只花 embedding 的钱 |

## 七、给开发者的说明

- 架构：`ingestion`（加载/分块/嵌入）→ `storage`（ChromaDB 向量 + BM25 关键词双路）→ `retrieval`（RRF 融合 + 可选重排）→ `generation`
- 双路检索为何必要：语义检索抓同义表达，BM25 抓专有名词精确匹配，RRF 融合两者
- 测试：`pip install -e ".[dev]" && pytest`
