# RAG 系统设计文档

> 网文写作多 Agent 系统的知识库检索增强生成（RAG）框架

---

## 目录

1. [什么是 RAG](#1-什么是-rag)
2. [整体架构](#2-整体架构)
3. [数据流](#3-数据流)
4. [核心模块详解](#4-核心模块详解)
   - [4.1 文档加载（Loader）](#41-文档加载loader)
   - [4.2 文本分块（Chunker）](#42-文本分块chunker)
   - [4.3 Embedding 向量化](#43-embedding-向量化)
   - [4.4 向量存储（ChromaDB）](#44-向量存储chromadb)
   - [4.5 BM25 关键词索引](#45-bm25-关键词索引)
   - [4.6 混合检索（Hybrid Search）](#46-混合检索hybrid-search)
   - [4.7 重排序（Reranker）](#47-重排序reranker)
   - [4.8 检索增强生成（Generator）](#48-检索增强生成generator)
5. [检索策略：为什么用双路召回](#5-检索策略为什么用双路召回)
6. [RRF 融合算法](#6-rrf-融合算法)
7. [知识库组织方式](#7-知识库组织方式)
8. [使用指南](#8-使用指南)
9. [调优建议](#9-调优建议)

---

## 1. 什么是 RAG

**RAG（Retrieval-Augmented Generation）** = 检索增强生成。

简单说：用户问一个问题 → 系统从知识库里搜出相关参考资料 → 把资料和问题一起丢给 LLM → LLM 基于资料生成准确回答。

- **没有 RAG**：用户 → LLM → 回答（LLM 凭记忆编，可能胡扯）
- **有了 RAG**：用户 → 检索知识库 → 找到相关资料 → LLM + 资料 → 有据可查的回答

### 为什么网文写作需要 RAG

- 你的小说有大量自创设定（角色、功法、地名、世界观），LLM 不知道这些
- 对话、情节、设定需要严格一致——"苍云宗的镇宗之宝是什么"不能每次回答不一样
- 写作时随时需要查阅自己积累的参考资料（经典典籍、神话、术语）

---

## 2. RAG 文件结构

```
novel_rag/                              # RAG 核心包
├── __init__.py
├── config.py                           # 配置中心 + Collection 注册表
├── pipeline.py                         # 端到端管线：IngestionPipeline + QueryPipeline
│
├── ingestion/                          # 摄入层
│   ├── loader.py                       #   文档加载（.md / .txt / .pdf）
│   ├── chunker.py                      #   文本分块（fixed / markdown / sentence）
│   └── embedder.py                     #   Embedding 客户端（SiliconFlow BAAI/bge-m3）
│
├── storage/                            # 存储层
│   ├── chroma_store.py                 #   ChromaDB 向量库封装
│   └── bm25_index.py                   #   BM25 关键词索引（jieba 分词）
│
├── retrieval/                          # 检索层
│   ├── hybrid_search.py                #   混合检索：语义 + BM25 → RRF 融合 ⭐
│   └── reranker.py                     #   LLM 重排序（可选）
│
├── generation/                         # 生成层
│   └── generator.py                    #   Prompt 组装 + LLM 生成回答

cli.py                                  # 命令行入口（ingest / query / info / clean）
.env                                    # API Key、模型名、路径配置
chroma_db/                              # ChromaDB 持久化数据（自动生成）
bm25_indexes/                           # BM25 索引持久化（自动生成）
```

### 模块分工

| 模块 | 职责 | 关键设计 |
|------|------|---------|
| **Config** | 全局配置、collection 注册表 | `.env` → Config 单例，`guess_collection()` 路由 |
| **Loader** | 加载 .md/.txt/.pdf | 6编码检测 → 4步清洗 → 书名/朝代/作者解析 → 14字段元数据 |
| **Chunker** | 长文本分块（默认 `classical`） | 4层切分：结构标记 → 段落 → 句子 → 递归兜底，min=50过滤 |
| **Embedder** | BGE-M3 向量化 | SiliconFlow API，32条/批，指数退避重试，timeout=60s |
| **ChromaStore** | 向量存储 + 语义搜索 | LangChain Chroma wrapper，跨 collection 合并检索 |
| **BM25Store** | 关键词索引 + BM25 搜索 | jieba分词 + rank_bm25，JSON持久化 |
| **HybridSearch** | 双路召回 + RRF 融合 | 语义 Top-15 + BM25 Top-15 → 1/(60+rank) 融合 → Top-5 |
| **Reranker** | LLM 重排序（可选） | 逐条 1-5 分评分，并行 5 线程 |
| **Generator** | 组装 prompt + 调用 LLM | 系统角色 + 编号参考资料 + 用户问题，流式输出 |
| **Pipeline** | 串联摄入/查询全流程 | `novel_rag/pipeline.py` |
| **CLI** | 命令行入口 | `cli.py` |

---

## 3. 数据流

### 3.1 摄入管线（Ingestion Pipeline）

摄入管线负责把原始文档变成可检索的索引，分为 5 个步骤：

**第 1 步：加载文档。** 遍历 `_bible/{genre}/raw/` 目录，按文件名排序后逐个加载。自动检测编码（UTF-8 → GBK → GB2312 → GB18030 → BIG5 → Latin-1），清洗全角缩进/空行/行首尾空白，从文件名解析书名/朝代/作者。每个文件输出一个 `Document` 对象，包含清洗后的 `content` 和完整的 `metadata`（14 个字段：title/dynasty/author/mtime/encoding/clean_flags 等）。

**第 2 步：文本分块。** 将每个 `Document` 按选定策略切成若干 `Chunk`。默认策略 `classical`（古典文本结构感知），在卷/篇/章/回和◎○节标记处优先断开，再逐层下钻到段落和句子。也支持 `markdown`、`fixed`、`sentence`。每个 `Chunk` 继承文档元数据（含 loader 提取的 title/dynasty/author）并附加自身位置信息（chunk_index、char_start、char_end）。低于 50 字的碎片被丢弃。

**第 3 步：按领域分组。** 根据文件路径判断每个 chunk 应该归入哪个 ChromaDB collection。当前映射：`01-道藏核心/`、`02-神话仙传/`、`04-儒释补充/` → `xianxia_classics`；`03-术数阵法/` → `xianxia_cultivation`。映射规则定义在 `config.py` 的 `guess_collection()` 函数中。

**第 4 步：双写入。** 这一步并行执行——(a) 将所有 chunk 通过 Embedder 转化为 1024 维向量，写入 ChromaDB 对应的 collection；(b) 将所有 chunk 用 jieba 分词后构建 BM25 倒排索引，存入内存。

**第 5 步：持久化。** ChromaDB 自动落盘，BM25 索引则单独存为 JSON 文件到 `bm25_indexes/{collection}.bm25`。下次启动时 `QueryPipeline` 会自动加载已有索引。

### 3.2 查询管线（Query Pipeline）

查询管线负责接收用户问题，检索相关资料，生成回答，分为 5 个步骤：

**第 1 步：Query Embedding。** 将用户输入的查询文本（如"金丹期如何突破"）通过 Embedder 转化为 1024 维向量。查询所用的 embedding 模型和摄入时一致（`BAAI/bge-m3`）。

**第 2a 步：语义检索。** 用查询向量在 ChromaDB 的目标 collection 中做余弦相似度搜索，返回 Top-15 最相似的 chunk。同时支持跨多个 collection 检索并合并结果。

**第 2b 步：BM25 关键词检索。** 用 jieba 对查询文本分词，在 BM25 索引的目标 collection 中计算词频相关性得分，同样返回 Top-15。这两路检索是并行执行的。

**第 3 步：RRF 融合。** 将两路检索结果用 Reciprocal Rank Fusion 算法合并。每个唯一 chunk 的最终得分 = `1/(60+语义排名) + 1/(60+BM25排名)`。在两路都命中的 chunk 获得更高的 RRF 分数，取 Top-5 返回。

**第 4 步：Reranker（可选）。** 如果启用重排序，将 RRF 融合后的 Top-15 逐条送给 LLM 做 1-5 分相关性评分，按新分数重新排列后取 Top-5。此步骤可纠正 RRF 纯数学融合可能产生的偏差。

**第 5 步：Generator 生成。** 将 Top-5 chunk 作为"参考资料"，和系统角色提示词、用户问题一起组装成完整 prompt，调用 LLM 生成流式回答，同时返回引用的来源清单。

---

## 4. 核心模块详解

### 4.1 文档加载（Loader）

**文件**：`novel_rag/ingestion/loader.py`

**支持格式**：`.md` / `.txt` / `.pdf`

---

#### 加载流程

```
文件 → 检测编码 → 读取内容 → 文本清洗 → 提取元数据 → Document
```

每条 `Document` 包含 `content`（清洗后的全文）和 `metadata`（见下方字段表）。

---

#### 编码检测

按顺序尝试 6 种编码，直到解码成功且替换字符 U+FFFD 不超过 1%：

```
utf-8 → gbk → gb2312 → gb18030 → big5 → latin-1
```

全部失败时回退到 `utf-8 + errors=replace`。

实测结论：当前 25 本资料 24 本 UTF-8，1 本（搜神记）GBK。`gb18030` 和 `big5` 是为未来扩展预留。

---

#### 文本清洗（`_clean_text`）

针对古典中文文本的常见问题，执行 4 步清洗：

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 全角缩进 `　` → 删除 | 文言文排版用全角空格缩进，对 embedding 无意义 |
| 2 | 连续 3+ 空行 → 压到 1 行 | 部分文本（列仙传 146 行空行）空行泛滥 |
| 3 | 行首尾 blank 去重 | 统一格式 |
| 4 | 检测 ■□ 缺字标记 | 不删除（古典文本缺字标记有语义含义），仅记录 flag |

每步执行后记录 `clean_flags`，方便追溯哪些文本经过哪些清洗。

**注意事项**：
- `　` 在古典文本中几乎只用于段落缩进，不是正文内容，全部删除安全
- ■□ 是编纂者标记原版缺字的位置，删除会丢失信息，保留用于 debug
- 没有做"删除版本说明/序言"——这类内容在 RAG 中可能是用户想查的（如"道藏本有几卷"）

---

#### 元数据提取（`parse_filename`）

文件名格式统一为 `书名-朝代-作者.txt`，loader 自动解析：

```
抱朴子内篇-晋-葛洪.txt  →  title=抱朴子内篇  dynasty=晋    author=葛洪
搜神记-晋-干宝.txt      →  title=搜神记      dynasty=晋    author=干宝
道德經.txt              →  title=道德經      dynasty=      author=
```

通过 25+ 个朝代关键词（先秦/春秋/战国/汉/晋/唐/宋/元/明/清...）的启发式匹配区分"朝代"和"作者"字段。

---

#### 完整元数据字段

| 字段 | 来源 | 示例 |
|------|------|------|
| `source_file` | 文件绝对路径 | `d:/novel/_bible/xianxia/raw/01-道藏核心/抱朴子内篇-晋-葛洪.txt` |
| `filename` | 文件名 | `抱朴子内篇-晋-葛洪.txt` |
| `stem` | 去扩展名 | `抱朴子内篇-晋-葛洪` |
| `suffix` | 扩展名 | `.txt` |
| `char_count` | 清洗后字数 | `103998` |
| `mtime` | 文件修改时间戳 | `1753800000.0` |
| `mtime_iso` | ISO 格式时间 | `2026-07-29T14:30:00` |
| `size_bytes` | 文件大小 | `312682` |
| `encoding` | 检测到的编码 | `utf-8` |
| `clean_flags` | 清洗标记 | `fullwidth_indent_removed,blank_lines_collapsed` |
| `title` | 从文件名解析 | `抱朴子内篇` |
| `dynasty` | 从文件名解析 | `晋` |
| `author` | 从文件名解析 | `葛洪` |

---

#### PDF 支持

双回退策略，按需安装：

```
pdfplumber（中文优）→ PyPDF2（轻量回退）→ 报错
```

- **pdfplumber**：中文提取质量好，支持表格和排版还原，推荐安装
- **PyPDF2**：轻量纯文本提取，中文效果一般，作为回退
- 两个都不在时给明确安装指引，不静默失败
- 扫描件 PDF 无文本时报错提示

当前项目有 0 个 PDF，此功能为未来扩展打基础。

---

#### 其他设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 文件排序 | `sort=True` 按路径排序 | 保证摄入顺序确定，chunk_id 可复现 |
| 目录遍历 | `os.walk()` 递归 | 支持子目录分类 |
| 异常处理 | 单文件失败不中断 | 25 本中 1 本坏了不应阻止其余 24 本 |
| mtime 记录 | 保留 | 为增量摄入做准备——只重处理修改过的文件 |
| `estimate_content_type()` | 提供但未接入管线 | 可用于未来根据文本类型自动调 chunk_size |

---

### 4.2 文本分块（Chunker）

**文件**：`novel_rag/ingestion/chunker.py`

**默认策略**：`classical`（古典文本结构感知）

---

#### 四种策略

| 策略 | 做法 | 适用场景 |
|------|------|---------|
| **`classical`** ⭐ | 在卷/篇/章/回、◎○节标记、编号标题处优先断开 | **文言文/古典文本（默认）** |
| `fixed` | 固定 512 字一段，重叠 64 字 | 无结构纯文本回退 |
| `markdown` | 先按 `#`/`##`/`###` 标题切 | .md 文件（修道真解） |
| `sentence` | 在句号/换行处断开 | 现代叙事文本 |

---

#### Classical 策略的四层切分

```
原文本
  │
  ├── 第1层：结构标记切分 ──────────────────
  │   识别: 卷/篇/章/回 + ◎○节标记 + 编号标题 + 分隔线
  │   效果: 抱朴子 20 篇 → 各自成段
  │         云笈七签 ◎节 → 各自成段
  │         道德经 81 章 → 各自成段
  │         山海经条目 → 各自成段
  │         西游记 100 回 → 各自成段
  │
  ├── 第2层：段落切分 ─────────────────────
  │   对超长的"篇"，按 \n\n 拆成段落
  │
  ├── 第3层：句子切分 ─────────────────────
  │   对超长的"段"，在 。！？；处断开
  │   文言文标点（。！？；）和白话文标点（.!?;）都支持
  │
  └── 第4层：递归拆分兜底 ────────────────
      单句仍超 512 字 → RecursiveCharacterTextSplitter 强制切断
```

**识别的结构标记**：

| 标记类型 | 正则示例 | 匹配内容 |
|---------|---------|---------|
| 卷/篇/章/回 | `卷一` `卷第五` `第一篇` `第三章` `第一百回` | 古典文本主要分界 |
| ◎○节标记 | `◎释《三十九章经》` `○口为章第三` | 道藏/佛经节标记 |
| 编号标题 | `一、` `（一）` `1.` `甲、` | 二级目录 |
| 分隔线 | `────` `===` `***` | 人工分隔 |

---

#### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `chunk_size` | 512 字 | 古典文本 512 字 ≈ 白话 1500 字，信息密度够 |
| `chunk_overlap` | 64 字 | 约 12.5% 重叠，保留跨块上下文 |
| `min_chunk_size` | 50 字 | 低于此值的碎片丢弃，不浪费 embedding |

**为什么是 512 字**：文言文信息密度约为白话的 3 倍。512 字文言文包含的信息量接近于 1500 字现代汉语。BGE-M3 支持 8192 token 输入，512 字约 700-1000 token，远在安全范围内。

**为什么 min_chunk_size=50**：旧版出现过 5 字的碎片（仅有标题）。这既没有检索价值，也浪费 embedding API 调用。

---

#### 实测数据（25 本资料，classical 策略）

| 文本 | 字数 | Chunks | 平均 | 碎块 |
|------|------|--------|------|:--:|
| 云笈七签 | 926k | 2887 | 343 | 0 |
| 西游记 | 715k | 2826 | 250 | 0 |
| 抱朴子内篇 | 104k | 366 | 290 | 0 |
| 山海经 | 40k | 289 | 78 | 0 |
| 道德经 | 7.7k | 77 | 95 | 0 |
| 金刚经 | 7k | 34 | 206 | 0 |

**关键验证**：所有文本碎块数 = 0。道德经 81 章和金刚经 32 分各自独立成块。

---

#### 注意事项

- **默认策略已从 `markdown` 改为 `classical`**：因为当前 25 本资料中仅 1 本（修道真解.md）有 markdown 标题，其余 24 本 .txt 全是古典格式
- **结构标记归入下一段**而非上一段：`卷一\n道德部` 切分后得到 `卷一\n道德部...` 而非 `...\n` + `卷一\n道德部...`，保证每个 chunk 的开头包含其章节标记，检索时能溯源
- **overlap 只发生在第 3 层（句子切分）后**：第 1、2 层切出来的自然段如果 ≤ 512 字则保持完整，不强行重叠

---

### 4.3 Embedding 向量化

**文件**：`novel_rag/ingestion/embedder.py`

---

#### 选型

| 选项 | 选择 | 原因 |
|------|------|------|
| 模型 | `BAAI/bge-m3` | 中文优化，多语言，1024 维，MTEB 中文榜首 |
| 调用方式 | SiliconFlow API（OpenAI 兼容） | 免部署，不占显存，国内访问快 |
| 客户端 | `openai.OpenAI` | 与 SiliconFlow 兼容 |

---

#### API 参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `timeout` | 60s | 单批调用超时，避免无限等待 |
| `max_retries` | 0（SDK 层） | 重试权交给 embedder 自己的指数退避逻辑 |
| `batch_size` | 32 条/批 | 平衡并发效率与单批失败影响面 |
| `max_retries`（自建） | 3 次 | 指数退避 1s → 2s → 4s |
| 输出维度 | 1024 | BGE-M3 固定输出 |

---

#### 重试逻辑

```
第 1 次失败 → 等 1s → 重试
第 2 次失败 → 等 2s → 重试
第 3 次失败 → 抛 RuntimeError
```

重试打印日志（`[Embedder] 重试 1/3，等待 1.0s: ...`），方便排查是偶发网络波动还是 API 挂了。

---

#### 注意事项

- **输入长度不审查**：BGE-M3 支持 8192 token，当前 chunk 上限 512 字（约 700-1000 token），远在安全范围内。但如果后续调整 chunk_size 超过 4000 字，需要加截断逻辑
- **排序保证**：`sorted(response.data, key=lambda x: x.index)` 确保输出向量顺序与输入文本顺序一致，即使 API 返回乱序
- **全局单例** `embedder = Embedder()`：模块加载时创建 OpenAI 客户端。`config.py` 在同一进程启动时已加载 `.env`，所以不会拿到空 API key
- **`embed_dim()` 不是 `embed_count()`**：之前命名有误导，已修正。返回 1024（维度），不是数量

---

#### 为什么不是本地模型

- BGE-M3 本地部署约需 2-4GB 显存，对开发机器不友好
- SiliconFlow API 价格低廉（约 ¥0.5/百万 token），25 本书摄入成本 < ¥1
- API 方案可随时切换模型（改 `.env` 中 `EMBEDDING_MODEL` 即可），无需重新部署

---

### 4.4 向量存储（ChromaDB）

**文件**：`novel_rag/storage/chroma_store.py`

---

#### 为什么选 ChromaDB

- 零配置本地运行，SQLite 持久化
- 支持 metadata 过滤
- LangChain 有官方 wrapper，与生态集成方便

---

#### 设计要点

**写入**：绕过 LangChain 的自动 embedding（我们已经在管线里算好了），直接写 `store._collection.add(embeddings=...)`。

**检索**：用 LangChain Chroma wrapper，返回余弦相似度分数。

**缓存**：`_stores` 字典缓存 LangChain Chroma 实例，避免每次 `search()` 都重新初始化。

**管理操作**：`list/delete/exists/count` 用原生 `chromadb.PersistentClient`，轻量且无副作用（原来 `collection_exists()` 用 `Chroma()` 检查，会**自动创建**不存在的 collection——已修复）。

---

#### 关键方法

```python
store = ChromaStore()

# 写入（embedding 已算好，直写底层）
store.add_chunks("xianxia_classics", texts, metas, embeddings)

# 单 collection 语义检索
results = store.search("xianxia_classics", query_vec, top_k=10)

# 跨 collection 检索 → 合并后返回 top_k 条
results = store.search_multi(
    ["xianxia_classics", "xianxia_cultivation"],
    query_vec,
    top_k=10
)

# 管理
store.list_collections()          # → ["xianxia_classics", ...]
store.collection_exists("foo")    # → True/False（无副作用）
store.delete_collection("foo")
store.stats()                     # → {"xianxia_classics": 366, ...}
```

**注意事项**：
- `search_multi` 返回 `top_k` 条而非 `top_k * n_collections` 条（原 bug 已修）
- 删 collection 后缓存自动失效（`_invalidate_cache`）
- 原生 chromadb client 懒加载单例，避免重复连接

---

### 4.5 BM25 关键词索引

**文件**：`novel_rag/storage/bm25_index.py`

---

#### 为什么需要 BM25

语义检索（BGE-M3）对专有名词效果不稳定："苍云宗"、"天渊剑" 这些词 embedding 模型没见过，语义向量可能不准。BM25 做纯字面匹配，精确命中关键词。

两路互补：语义检索擅长同义替换（"宗门守护神器"→"镇宗至宝"），BM25 擅长精确匹配（"天渊剑"绝对不会漏）。

---

#### 实现

| 组件 | 选型 | 说明 |
|------|------|------|
| 分词 | `jieba` | 中文分词，否则"金丹期修士"被切成单字，"金丹"查不到 |
| 算法 | `rank_bm25.BM25Okapi` | 标准 BM25 实现 |
| 持久化 | JSON（tokenized texts） | BM25Okapi 不可 pickle，存分词后文本重建 |

**为什么必须分词**：
```
不分词: 金丹期修士 → ['金','丹','期','修','士'] → 查"金丹"找不到
分词后: 金丹期修士 → ['金丹期','修士']         → 查"金丹"匹配到"金丹期"
```

---

#### 使用方式

```python
bm25 = BM25Store()

# 构建（摄入时）
bm25.build("xianxia_classics", chunks)
bm25.save("xianxia_classics")        # → bm25_indexes/xianxia_classics.bm25

# 加载（启动时）
bm25.load()                          # 自动扫描 bm25_indexes/ 下所有 .bm25

# 检索
results = bm25.search("xianxia_classics", "天渊剑 至宝", top_k=10)
```

---

### 4.6 混合检索（Hybrid Search）⭐核心

**文件**：`novel_rag/retrieval/hybrid_search.py`

---

#### 数据流

```
用户查询 "金丹如何炼制"
  │
  ├──→ embed_query → ChromaDB 语义检索 → Top-15（余弦相似度）
  │
  ├──→ jieba 分词 → BM25 关键词检索 → Top-15（词频相关性）
  │
  └──→ RRF 融合 → Top-5
       score = 1/(60 + rank_vec) + 1/(60 + rank_bm25)
```

#### RRF 融合

两路各有排名。同一个 chunk 在两路都排前面的，RRF 得分最高。

| chunk | 语义排名 | BM25排名 | RRF 得分 | 说明 |
|-------|:-----:|:------:|---------|------|
| 丹方内容 | #1 | - | 0.0164 | 仅语义命中 |
| 金丹关键词段落 | - | #1 | 0.0164 | BM25 补位 |
| 修炼理论 | #2 | - | 0.0161 | 仅语义命中 |

两路互补——语义找到意译内容，BM25 找到字面匹配，RRF 自然奖励双路都命中的结果。

---

#### Chunk 唯一标识（`_chunk_key`）

```python
# 用 col|source_file|chunk_index 组合（确定性，不依赖 hash）
key = f"{col}|{source}|{chunk_idx}"
```

同一个 chunk 在语义和 BM25 结果中出现时能正确去重合并。

**注意**：原来用 `hash(text)` 做一部分 key，但 Python 的 `hash()` 进程间随机化（PYTHONHASHSEED），已移除。

---

#### 响应时间参考

抱朴子内篇 366 chunks，单次混合检索耗时约 0.4s（embedding 0.2s + 双路检索 0.2s）。

---

### 4.7 重排序（Reranker）

**文件**：`novel_rag/retrieval/reranker.py`

**状态**：可选模块（默认不启用）

---

#### 工作原理

RRF 融合得到 Top-15 候选 → 逐条送 LLM 打 1-5 分 → 取最高分 Top-5。

#### 关键设计

| 设计 | 说明 |
|------|------|
| 模型可配置 | `Reranker(model="...")`，默认 `deepseek-ai/DeepSeek-V3` |
| `rerank_score` 独立字段 | 不覆盖 `rrf_score`（保留原始检索信息用于调试） |
| 并行评分 | 5 线程并行，15 条候选约 3-5s 完成 |
| 中文 prompt | prompt 用中文写，与数据语言一致 |

#### 使用方式

```python
reranker = Reranker()
reranked = reranker.rerank(query, results, top_k=5, verbose=True)
# 返回结果中 rerank_score 有值，rrf_score 保留
```

#### 适用场景

- 查询短且模糊（"金丹" → 可能返回大量相关但不够精准的结果）
- 需要精细排序后再生成

#### 不适用场景

- 快速响应（每次评分 = 1 次 LLM API 调用，15 条 = 15 次）
- 资料本身就很少的 collection

后续可替换为本地 cross-encoder（`bge-reranker-v2-m3`），省去 API 调用开销。

---

### 4.8 检索增强生成（Generator）

**文件**：`novel_rag/generation/generator.py`

---

#### Prompt 结构

```
## 系统角色
你是一位专业的网文写作助手，精通仙侠题材的设定与创作。
（规则: 基于资料回答 / 引用来源 / 诚实说明不足 / 标注创作建议）

## 参考资料
[1] (来源: 抱朴子内篇-晋-葛洪.txt / 抱朴子内篇)
以金液为威喜巨胜之方，取金液及水银一味合煮之，三十日出...

[2] (来源: 抱朴子内篇-晋-葛洪.txt / 抱朴子内篇)
抱朴子曰：余考览养性之书，鸠集久视之方，曾所披涉篇卷...

## 用户问题
金丹如何炼制？

请回答:
```

#### 关键设计

| 设计 | 说明 |
|------|------|
| 模型可配置 | `Generator(model="...")`，默认 `deepseek-ai/DeepSeek-V3` |
| 来源标注 | 每条参考资料带编号 + 文件名 + 书名，回答时可引用 |
| `stream` | 流式时不 print 到 stdout（原实现有——已修），在内存拼接后返回 |
| `sources` 字段 | 返回完整的来源信息（含 rrf_score / rerank_score）供 debug |
| `DEFAULT_SYSTEM_PROMPT` | 聚焦仙侠题材，可从外部覆盖 |

#### 使用方式

```python
gen = Generator()

# 非流式
result = gen.generate("金丹如何炼制", search_results)
print(result.answer)
for s in result.sources:
    print(f"  [{s['index']}] {s['title']} (rrf={s['rrf_score']:.4f})")

# 流式
result = gen.generate("金丹如何炼制", search_results, stream=True)
print(result.answer)  # 完整回答，不在生成过程中逐字打印
```

---

## 5. 检索策略：为什么用双路召回

### 纯语义检索的盲区

| 场景 | 问题 |
|------|------|
| 专有名词 | "苍云宗"、"天渊剑"——embedding 模型没见过，语义向量不准确 |
| 精确引用 | "第三章"、"公元1427年"——数字和章节号对语义模型区分力弱 |
| 自创术语 | "灵炁"、"虚界裂隙"——你自己起的词，模型完全没概念 |
| 缩写/别名 | "叶尘" vs "叶无尘"——语义相近但可能是两个不同角色 |

### BM25 怎么补位

BM25 是纯字面匹配，不关心语义：
- "苍云宗" → 精确匹配到所有出现"苍云宗"的段落
- "天渊剑" → 绝对不会漏掉任何提到"天渊剑"的地方
- 缺点：不会理解"宗门守护神器"指的就是天渊剑

### 两路互补 = 最优解

语义检索擅长处理同义替换，例如"宗门守护神器"能匹配到"镇宗至宝"；BM25 擅长精确匹配，例如"天渊剑"绝对不会漏掉任何提到这三个字的段落。两者结合后，"宗门守护神器"这个模糊查询就能精准定位到"天渊剑"所在的段落。

---

## 6. RRF 融合算法

### 公式

```
RRF_score(chunk) = Σ 1 / (k + rank_i)
```

其中：
- `k = 60`（平滑常数，避免排名靠前的 chunk 权重过大）
- `rank_i` 是该 chunk 在每路检索中的排名（1-indexed）
- 未出现在某一路的 chunk，该路贡献为 0

### 数值示例

```
chunk A 在语义检索排第1名，在 BM25 排第5名:
  RRF = 1/(60+1) + 1/(60+5) = 0.01639 + 0.01538 = 0.03177

chunk B 只在语义检索排第3名:
  RRF = 1/(60+3) + 0 = 0.01587

→ chunk A 分数几乎是 chunk B 的两倍，因为它被两路同时验证
```

### 为什么 k=60

- k 越大，排名差异的影响越小（所有 chunk 的分数趋同）
- k 越小，排名靠前的 chunk 权重过大（第一名碾压一切）
- 60 是论文验证过的最佳平衡点，一般不需要调

---

## 7. 知识库组织方式

### 目录结构

```
_bible/
├── xianxia/                       ← 题材：仙侠
│   ├── raw/                       ← 原始文本（只读，RAG 检索源）★ 题材级共享
│   │   ├── 01-道藏核心/           ← 《道德经》《庄子》...
│   │   ├── 02-神话仙传/           ← 《山海经》《神仙传》...
│   │   ├── 03-术数阵法/           ← 《周易》《奇门遁甲》...
│   │   └── 04-儒释补充/           ← 《金刚经》《论语》...
│   └── {book}/                    ← 书级根（如 duanze/，含 bible/、processed/ 等单书内容）
├── wuxia/                         ← 题材：武侠
├── historical/                    ← 题材：历史
├── scifi/                         ← 题材：科幻
├── common/                        ← 通用知识（写作技法）
└── research/                      ← 研究报告
```

### Collection 映射

每个题材下的知识领域 → 独立的 ChromaDB collection：

```
xianxia/
├── 01-道藏核心    → xianxia_classics       古典经文原文
├── 02-神话仙传    → xianxia_bestiary       异兽/精怪/灵物
├── 03-术数阵法    → xianxia_geography      仙山/洞府
│                   → xianxia_artifacts      法宝/神器
├── processed/     → xianxia_cultivation    修炼体系
│                   → xianxia_herbs          灵草/丹药
│                   → xianxia_characters     人物谱
│                   → xianxia_terminology    术语辞典
```

**好处**：
- 检索"金丹期"时限定在 `xianxia_cultivation`，不会被无关 collection 干扰
- 检索"御剑飞行"时跨 `xianxia_cultivation` + `xianxia_artifacts` 同时查
- 扩展新题材不影响已有 collection

---

## 8. 使用指南

### 安装

```bash
cd d:\novel
python -m venv venv
source venv/Scripts/activate   # Windows
pip install -r requirements.txt
```

### 配置 `.env`

```env
SILICONFLOW_API_KEY=your_key_here
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
CHROMA_PERSIST_DIR=./chroma_db
```

### 命令行

```bash
# ===== 摄入资料 =====
python cli.py ingest --genre xianxia              # 摄入仙侠资料
python cli.py ingest --genre xianxia --clear      # 清空重建
python cli.py ingest --all                        # 摄入全部题材
python cli.py ingest --genre xianxia --strategy sentence  # 换分块策略

# ===== 查询 =====
python cli.py query "金丹期如何突破"               # 检索 + 生成
python cli.py query "苍云宗" --search-only         # 只看检索结果
python cli.py query "天渊剑" --rerank              # 启用重排序
python cli.py query --interactive                  # 交互式查询模式

# ===== 管理 =====
python cli.py info                                 # 查看索引状态
python cli.py clean --collection xianxia_cultivation  # 清空指定 collection
python cli.py clean --all                          # 清空全部
```

### Python API

```python
from novel_rag.pipeline import IngestionPipeline, QueryPipeline

# ── 摄入 ──
ingest = IngestionPipeline()
result = ingest.run(genre="xianxia")
print(f"已摄入 {result['total_chunks']} 条 chunk")

# ── 查询 ──
query = QueryPipeline()

# 仅检索
results = query.search("金丹期", genre="xianxia", top_k=5)
for r in results:
    print(f"[{r.rrf_score:.4f}] {r.text[:80]}")

# 检索 + 生成
result = query.generate("金丹期怎么突破", genre="xianxia", stream=True)
print(result.answer)
for s in result.sources:
    print(f"  [{s['index']}] {s['source_file']}")
```

---

## 9. 调优建议

### 分块参数

```python
# novel_rag/config.py 或 .env 中调整

chunk_size = 512      # 减小 → 更精确但可能丢失上下文
chunk_overlap = 64    # 增大 → 减少信息断裂但索引变大
```

**经验法则**：
- 设定文档（术语、功法）→ `chunk_size=384`，小块更精准
- 叙事文本（章节、情节）→ `chunk_size=768`，大块保留上下文
- 混合内容 → `chunk_size=512`，默认值适用大多数场景

### 检索参数

```python
retrieval_top_k = 10   # 每路召回数 → 增大提高召回但增加噪音
fusion_top_k = 5       # 最终返回数 → 根据 LLM 上下文窗口定
rrf_k = 60             # RRF 平滑 → 一般不需要改
```

### 效果迭代路径

**第 1 步**：放资料 → 跑 `ingest` → 手工测试几个 query，看 Top-5 结果是否相关。

**第 2 步**：发现 bad case（如"苍云宗"搜不到相关结果）时排查原因——是分块问题（chunk 里没这段？）还是 embedding 问题（语义向量偏了？）还是分词问题（jieba 没切对人名？）。

**第 3 步**：针对性调优。分块问题调 `chunk_size` 或换 strategy；embedding 问题考虑调整 BM25 权重或更换模型；prompt 问题调整 generator 的 system prompt。

**第 4 步**：如果两路召回 + RRF + Reranker 还不够，考虑加元数据过滤（按章节、按题材先筛选范围），或加 Query Rewriting（检索前先用 LLM 改写查询），或加知识图谱补充（处理人物关系等结构化数据）。

### 监控指标

每次查询注意观察：

```
[HybridSearch] 语义检索: 15 条 (0.73s)
[HybridSearch] BM25 检索: 4 条 (1.11s)
[HybridSearch] RRF 融合后: 5 条 (1.11s)
```

- 语义检索为 0 → embedding API 可能挂了
- BM25 检索为 0 → 关键词一个没命中，检查分词或确认资料是否已摄入
- 融合后很多 chunk 只命中一路 → 两路结果差异大，可能是好事（互补），也可能暗示某一路有问题

---

## 附录：关键术语

| 术语 | 解释 |
|------|------|
| **RAG** | Retrieval-Augmented Generation，检索增强生成 |
| **Embedding** | 文本向量化，把文字变成一串数字表示语义 |
| **Chunk** | 文本片段，长文档切成小块做索引 |
| **ChromaDB** | 开源向量数据库，存 embedding + 做相似度搜索 |
| **BM25** | 经典关键词检索算法，基于词频计算相关性 |
| **RRF** | Reciprocal Rank Fusion，多路检索结果融合算法 |
| **Reranker** | 重排序器，对初步检索结果做精细二次排序 |
| **jieba** | 中文分词库，BM25 做中文检索的必需组件 |
| **Collection** | ChromaDB 的数据容器，类似关系数据库的"表" |

---

## 10. 系统细化记录

> 2026-07-29 ~ 2026-07-30，对 `novel_rag/` 全部模块进行逐文件审查和修复。

### 10.1 数据规模

| 层级 | 数量 | 大小 |
|------|------|------|
| 原始文本 | 25 本 | 10.8 MB |
| Chunks（classical 策略） | 10,418 | — |
| ChromaDB 向量库 | 2 collections | 182.7 MB |
| BM25 关键词索引 | 2 indexes | 37.7 MB |
| **索引总计** | — | **220.4 MB** |

```
Collection               Chunks
xianxia_classics         10,274   ← 22本（道藏核心+神话仙传+儒释补充）
xianxia_cultivation         144   ← 3本（周易+参同契+悟真篇）
```

### 10.2 摄入性能

| 指标 | 值 |
|------|-----|
| 总耗时 | ~408s（约 7 分钟） |
| Embedding API | SiliconFlow BAAI/bge-m3 |
| 批大小 | 32 条/批 |
| 重试次数 | 大量（见下方 429 问题） |
| ChromaDB 写入 | 分 3 批（5000/batch 上限） |

### 10.3 遇到的 13 个问题及解决

#### 问题 1：loader/`__init__.py` 含旧版完整副本 🔴

**现象**：`novel_rag/ingestion/__init__.py` 里藏了一份旧版 loader 的全部代码（`Document`、`load_file`、`load_directory`、`_load_text` 等），与 `loader.py` 形成重复定义。

**影响**：改了 `loader.py` 但 `__init__.py` 的旧代码不走新逻辑（无元数据提取、无文本清洗、无 PDF 双回退）。

**修复**：`__init__.py` 替换为轻量 re-export（仅 `from .loader import ...`）。

---

#### 问题 2：Loader 未提取文件名的结构化信息 🟡

**现象**：文件名为 `抱朴子内篇-晋-葛洪.txt`，但 metadata 只有原始 filename，不拆 title/dynasty/author。

**影响**：检索结果看不出来源书的朝代和作者，generator prompt 里 `title` 字段永远为空。

**修复**：新增 `parse_filename()` 函数，25+ 朝代关键词启发式匹配。

---

#### 问题 3：古典文本无清洗 🔴

**现象**：文本含全角缩进 `　`、大量空行（列仙传 146 行）、■□ 缺字标记，直接 embed 浪费向量空间。

**修复**：新增 `_clean_text()`：去全角缩进 → 压连续空行 → 去行首尾 blank → 检测 ■□。清洗标记记录到 `clean_flags`。

---

#### 问题 4：Default 分块策略 `markdown` 对文言文无效 🔴

**现象**：24/25 本为 .txt 文件，无 markdown 标题。`MarkdownHeaderTextSplitter` 切不动就退化 recursive split，等于 `fixed` 策略。结果是纯机械切分，无视 `卷/篇/◎/○` 等古典结构。

**修复**：新增 `classical` 策略——四层切分：结构标记（卷/篇/章/回/◎/○）→ 段落（\n\n）→ 句子（。！？）→ 递归兜底。默认策略改为 `classical`。加 `min_chunk_size=50` 过滤碎块。

---

#### 问题 5：Embedder 无超时 + 方法命名误导 🟡

**现象**：`OpenAI()` 客户端默认 timeout=600s，API 卡住时半天不报错。方法叫 `embed_count()` 但返回的是维度 1024。

**修复**：加 `timeout=60.0`，`max_retries=0`（重试权交给自己的指数退避）。改名 `embed_dim()`。

---

#### 问题 6：ChromaDB `collection_exists()` 有副作用 🔴

**现象**：`collection_exists()` 调用了 `Chroma()` 构造函数——LangChain Chroma wrapper 在 collection 不存在时会自动创建。检查存在性的行为本身会创建 collection。

**修复**：改用原生 `chromadb.PersistentClient.list_collections()` 检查，完全无副作用。

---

#### 问题 7：ChromaDB `search_multi()` 返回数量错误 🔴

**现象**：`search_multi` 返回 `top_k * n_collections` 条结果。跨 8 个 collection 检索时返回 80 条而不是 5 条。

**修复**：改为返回 `top_k` 条，而非 `top_k * n`。

---

#### 问题 8：ChromaDB 单批写入上限 5461 条 🔴

**现象**：10283 条 chunk 一次性 `add()` 报错 `ValueError: Batch size of 10283 is greater than max batch size of 5461`。

**修复**：`add_chunks()` 加分批逻辑，每批最多 5000 条。

---

#### 问题 9：HybridSearch `_chunk_key` 使用 `hash()` 🟡

**现象**：chunk key 用 `hash(text) % 10**8` 做去重标识。Python `hash()` 进程间随机化（PYTHONHASHSEED），跨进程无法复用。

**影响**：同进程内不影响，但冗余且脆弱。

**修复**：key 改为 `col|source_file|chunk_index`，完全确定性。

---

#### 问题 10：Reranker 覆盖 RRF 分数 + 英文 prompt 🟡

**现象**：`r.rrf_score = s` 直接用 LLM 评分覆盖 RRF 分数，原始检索排名信息丢失。评分 prompt 用英文写，数据全是中文。

**修复**：LLM 评分写入独立字段 `rerank_score`，`rrf_score` 保留。prompt 中文化。模型改为构造参数。

---

#### 问题 11：Generator 流式输出耦合 stdout 🔴

**现象**：`stream=True` 时 `print(content, end="", flush=True)` 直接写终端，生成器不该耦合 UI。

**修复**：流式块在内存拼接，统一返回 `GenerationResult.answer`。`sources` 增加 rrf_score/rerank_score/title 字段。

---

#### 问题 12：SiliconFlow 429 限流 🔴

**现象**：全量摄入 10418 条 chunk 时，SiliconFlow 免费 tier TPM（token per minute）限制触发大量 429 错误。embedder 的指数退避重试（1s→2s→4s）最终全部通过，但耗时从预估 30s 膨胀到 408s。

**解决**：当前重试逻辑扛住了。后续两个优化方向：(a) 升级付费 plan 消除限流；(b) 在 `embed_texts` 中加入速率控制（如每批之间 sleep 2s）。

---

#### 问题 13：GBK 终端编码 🟢

**现象**：Windows 终端 GBK 编码无法打印 emoji 和部分 Unicode，摄入日志乱码。

**修复**：全部 emoji 替换为 ASCII 标记（`📥`→`[INGEST]`，`⚠`→`[WARN]`，`✅`→`[DONE]`）。

---

### 10.4 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `novel_rag/ingestion/__init__.py` | 旧版代码副本 → 轻量 re-export |
| `novel_rag/ingestion/loader.py` | 完整重写：编码检测/文本清洗/元数据解析/PDF双回退/mtime |
| `novel_rag/ingestion/chunker.py` | 新增 `classical` 策略，四层切分，碎块过滤 |
| `novel_rag/ingestion/embedder.py` | 加 timeout，改名 `embed_dim`，删测试代码 |
| `novel_rag/storage/__init__.py` | 空文件 → re-export |
| `novel_rag/storage/chroma_store.py` | 修 `collection_exists` 副作用/`search_multi` bug/分批写入/加缓存 |
| `novel_rag/storage/bm25_index.py` | 删测试代码 |
| `novel_rag/retrieval/__init__.py` | 空文件 → re-export |
| `novel_rag/retrieval/hybrid_search.py` | `_chunk_key` 去 hash/删测试代码 |
| `novel_rag/retrieval/reranker.py` | `rerank_score` 独立字段/中文 prompt/model 参数化/删测试 |
| `novel_rag/generation/__init__.py` | 空文件 → re-export |
| `novel_rag/generation/generator.py` | stream 不 print/sources 增强/model 参数化/删测试 |
| `novel_rag/pipeline.py` | emoji→ASCII/默认策略 classical/删测试 |
| `novel_rag/config.py` | Collection 映射修正（02→classics, 03→cultivation）/删无用题材 |
| `cli.py` | 默认策略 classical/--all 精简 |
| `requirements.txt` | 加 `pdfplumber>=0.11.0` |
| `.env` | 不变 |
| `RAG_DESIGN.md` | 4.1~4.8 全部重写 + 新增 §10 细化记录 |


---

# 附录：实操使用指南

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
