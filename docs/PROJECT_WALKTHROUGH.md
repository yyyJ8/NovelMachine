# NovelMachine — 网文写作多 Agent 系统，从 0 到 1 全面讲解

> 一个 **对话式多 Agent 编排 + RAG 混合检索** 的中文网文写作框架。
>
> 自然想法 → 大纲/卷纲/章纲 → 写手起草 → 并行审稿 → 修改循环 → 定稿 → 状态更新，完整写作闭环。
> 本文对照源码逐模块讲解，既是一篇技术博客，也可作为面试讲解大纲。

---

## 总技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 编排 | **对话式多 Agent**（8 个岗位说明书） | 主编在 AI 会话中调度，刻意不脚本化——每步可检查/打断/覆写 |
| 语义检索 | ChromaDB + BGE-M3（1024 维） | 向量存储，嵌入走 SiliconFlow OpenAI 兼容 API |
| 关键词检索 | BM25 + jieba 分词 | 专有名词精确匹配，与语义路 RRF 融合 |
| 融合算法 | RRF（Reciprocal Rank Fusion） | `score = Σ 1/(k + rank)`，k=60，两路结果按排名融合 |
| 配置 | `config/genres.yaml` | 题材注册表配置驱动，接入新资料无需改代码 |
| 摄入 | 增量 + 限流自愈 | mtime+size 指纹增量；429 长退避重试（尊重 Retry-After） |
| 分块 | classical / markdown / sentence / fixed | 古典文本结构感知（卷/篇/章/◎○标记切分） |
| 生成 | OpenAI 兼容 Chat API | 按题材加载 system prompt（prompts/{genre}.txt） |
| 状态 | `novel_state.yaml` | 角色/伏笔/时间线结构化快照，跨会话不丢 |
| 安装 | setup.bat / setup.sh + AGENTS.md | 零代码一键安装；跨工具 Agent 配置 |

---

## 项目结构

```
NovelMachine/
├── novel_rag/                  # RAG 框架（核心代码）
│   ├── config.py               #   配置中心（.env → dataclass 单例）
│   ├── genre_registry.py       #   题材注册表（YAML 配置驱动）
│   ├── pipeline.py             #   端到端管线（摄入 + 查询）
│   ├── ingestion/              #   加载/分块/嵌入
│   │   ├── loader.py           #     MD/TXT/PDF + 编码检测 + 文件名解析
│   │   ├── chunker.py          #     4 种分块策略（classical 默认）
│   │   └── embedder.py         #     SiliconFlow 嵌入 + 429 自愈重试
│   ├── storage/                #   双路存储
│   │   ├── chroma_store.py     #     ChromaDB 向量库（md5 确定性 id）
│   │   └── bm25_index.py       #     BM25 关键词索引（jieba + JSON 持久化）
│   ├── retrieval/              #   检索层
│   │   ├── hybrid_search.py    #     双路召回 + RRF 融合 ⭐
│   │   └── reranker.py         #     LLM 逐条评分重排（可选，并行 5 线程）
│   ├── generation/             #   生成层
│   │   └── generator.py        #     Prompt 组装 + LLM 生成（带来源标注）
│   └── prompts/                #   按题材定制 system prompt
├── _agents/                    # 8 个 Agent 岗位说明书（对话式编排）
├── _templates/                 # 大纲/卷纲/章纲模板 + schema
├── _workflows/verify_punct.py  # 标点校验脚本
├── config/genres.yaml          # 题材注册表（可编辑）
├── tests/                      # smoke test（pytest + manual_smoke）
├── docs/                       # RAG.md（设计+使用）、本文
├── cli.py / rag_query.py       # 命令行入口（人用 rich 表格 / Agent 用 JSON）
├── setup.bat / setup.sh        # 一键安装（零代码用户）
├── AGENTS.md / CLAUDE.md       # Agent 协作配置（跨工具 + Claude/DSH）
└── AGENT_REVIEW.md             # Agent 演进记录（评审→优化→落地）
```

---

## 简介

一个"AI 会话驱动"的网文写作框架：**8 个专职 Agent（写手/审稿/校验/读者/格式/设定/大纲）由主编在对话中调度**，写作时通过 RAG 框架检索自己积累的典籍资料（《道藏》《山海经》《周易》等 30+ 部），保证设定一致、有据可依。

核心设计思路（项目特色）：

1. **对话式编排，刻意不脚本化**：写作需要每步人工判断（节奏、爽点、方向），脚本化 workflow 不可打断、问题不可见；对话式每步可检查/覆写——这是产品决策，不是技术妥协。
2. **双路 RAG，RRF 融合**：纯语义抓不住专有名词（"苍云宗""金丹"），纯关键词抓不住同义表达（"修炼""修行""证道"）；两路按排名融合，各取所长。
3. **题材注册表，配置驱动**：加新题材（武侠/历史/科幻）= 在 YAML 加一段，不改代码；未注册题材自动落入 `{genre}_general` 兜底。
4. **增量摄入 + 限流自愈**：mtime+size 指纹只重摄变化文件（1 万条全量重摄太慢费钱）；429 限流长退避自动续跑，尊重 Retry-After。
5. **古典文本专业处理**：编码自动检测（UTF-8/GBK/GB2312/Big5）、古文清洗（全角缩进/空行压缩）、结构感知分块（卷/篇/章/◎○标记）、文件名解析（书名-朝代-作者）。
6. **人机分离的输出设计**：`cli.py` 给人看（rich 表格），`rag_query.py` 给 Agent 看（JSON）——Agent 在写作循环里直接消费结构化检索结果。

---

## 摄入管线（IngestionPipeline）

`novel_rag/pipeline.py` 的 `IngestionPipeline.run()` 是五步流水线：

```
_bible/{genre}/raw/ → load_directory() → chunk_documents() → embed_texts() → ChromaDB + BM25
```

### 第 1 步：加载（loader.py）

**编码检测**（`_load_text_with_encoding`）：依次尝试 `utf-8 → gbk → gb2312 → gb18030 → big5 → latin-1`。关键细节：解码成功但出现大量 `�` 替换字符（>1% 内容）**不算成功**，继续尝试下一种——防止"乱码但解码不报错"的假成功：

```python
for enc in _ENCODINGS_TO_TRY:
    try:
        content = filepath.read_text(encoding=enc)
        if "�" in content:
            if content.count("�") > len(content) * 0.01:  # >1% 替换字符
                continue                                  # 视为解码失败
        return content, enc
    except (UnicodeDecodeError, UnicodeError):
        continue
```

**文件名 → 结构化元数据**（`parse_filename`）：从 `抱朴子内篇-晋-葛洪.txt` 解析出 `title="抱朴子内篇"`、`dynasty="晋"`、`author="葛洪"`，用朝代关键词表做启发式判断（支持 `书名-朝代-作者` 和 `书名-作者-朝代` 两种格式）。这些元数据会一路带到检索结果里，让 Agent 查资料时能看到"这段话出自《抱朴子》（晋·葛洪）"。

**文本清洗**（`_clean_text`）：全角缩进去除、连续 3+ 空行压缩、行首行尾空白清理；**`■□` 缺字标记保留不删**（古典文本中表示原书缺字，有语义含义）。

**PDF 双重回退**：`pdfplumber`（中文更优）→ 失败回退 `PyPDF2` → 都失败则明确报错"可能是扫描件"。

### 第 2 步：分块（chunker.py）

四种策略，默认 `classical`（古典文本专用）：

```
层级 1：结构标记切分（卷/篇/章/回、◎○●节标记、编号标题、分隔线）
层级 2：段落切分（\n\n）
层级 3：句子切分（。！？；）
层级 4：递归兜底（仍超长 → fixed 策略）
```

核心是 `_STRUCTURAL_BOUNDARY_PATTERN`——合并四种正则的复合模式，任意命中即为分界：

```python
_STRUCTURAL_BOUNDARY_PATTERN = re.compile(
    r"(" + _RE_VOLUME.pattern + r"|" + _RE_SECTION_MARKER.pattern
    + r"|" + _RE_NUMBERED_HEADING.pattern + r"|" + _RE_RULE_LINE.pattern + r")",
    re.MULTILINE,
)
```

`min_chunk_size=50` 过滤碎块，每个 chunk 保留完整元数据链（`chunk_index`/`char_start`/`char_end`），支撑检索结果精确溯源。

### 第 3 步：嵌入（embedder.py）

**分层重试设计**（`_embed_batch_with_retry`）是工程亮点：

```python
# 第一段：普通错误重试（指数退避 2^attempt）
for attempt in range(config.max_retries):
    try:
        return self._create_embeddings(texts)
    except Exception as e:
        if _is_rate_limit(e):          # 遇到 429 立即转入限流循环
            last_error, is_rate_limited = e, True
            break
        ...

# 第二段：429 限流专用重试（等 TPM 窗口恢复）
if is_rate_limited:
    for attempt in range(config.rate_limit_max_retries):   # 默认 10 次
        wait = _retry_after(e) or config.retry_delay * (2 ** attempt)
        wait = min(max(wait, 1.0), config.rate_limit_max_wait)  # 尊重 Retry-After
        time.sleep(wait)
```

- **普通错误**：3 次指数退避
- **429 限流**：**10 次长退避**，优先尊重服务端 `Retry-After` 头，单次最长等 60s——1 万条 chunk 遇到 TPM 限流也能最终啃完，只是慢
- `max_retries=0` 交给 SDK 层，重试完全自己控制
- **维度校验**：API 返回维度 ≠ `.env` 的 `EMBEDDING_DIM` 时告警（换模型后维度变，需同步改配置并重建索引）

**批量 + 进度**：默认每批 32 条，批间可配置 sleep（`--batch-delay`），限流时调小批大小降速。

### 第 4/5 步：双路写入（chroma_store.py + bm25_index.py）

见下节「存储层」。

**增量摄入**（pipeline 的 manifest 机制）：

```python
def _file_signature(metadata: dict) -> list:
    """文件指纹：mtime + size"""
    return [round(float(metadata.get("mtime", 0)), 3), int(metadata.get("size_bytes", 0))]
```

`ingest_manifest.json` 存 `{相对路径: [mtime, size]}`。增量模式只处理指纹变化的文件，未变的跳过（`skipped` 计数）。**全量摄入也写 manifest**，为后续增量做准备。

---

## 存储层：双路索引

### ChromaStore（chroma_store.py）

设计要点：**存走原生 chromadb 底层，查走 LangChain wrapper，管理走原生 client**——三套接口各取所需。

**确定性 ID**（踩坑修复）：

```python
ids = [
    f"{collection_name}_{i}_{hashlib.md5(text.encode('utf-8')).hexdigest()[:16]}"
    for i, text in enumerate(texts)
]
```

之前用 `hash(text)`——Python 的 `hash()` 是**进程内随机化**的（PYTHONHASHSEED），重复摄入会生成不同 id → 脏数据。改用 md5 后，同文本永远同 id，重复摄入可正确去重。

**批量写入上限**：ChromaDB 单批约 5461 条上限，代码里 `MAX_BATCH = 5000` 分批写入，避免大批量摄入时写入失败。

**查询返回余弦距离 → 转相似度**：`score = 1.0 - distance`。

### BM25Store（bm25_index.py）

- **jieba 分词** + `rank_bm25` 的 `BM25Okapi`
- **每个 collection 独立索引**，与 ChromaDB 的 collection 一一对应
- **持久化用 JSON 而非 pickle**（踩坑修复）：`BM25Okapi` 本身不可 pickle，改存 `tokenized corpus + texts + metas`，加载时重建模型
- **不过滤负分**：小语料/高词频词在 rank_bm25 下 idf 可能为负，但相对大小仍有排序意义，过滤会误杀有效结果
- `search_multi` 跨 collection 检索并合并排序，**与语义路的候选数保持一致**（保证 RRF 融合时两路对称）

---

## 检索层：混合检索 + RRF 融合（项目核心 ⭐）

`hybrid_search.py` 的 `HybridSearcher.search()` 四步：

```python
# 第1路：语义检索（query → embedding → ChromaDB top-K）
query_vec = self.embedder.embed_query(query)
semantic_results = self.chroma.search_multi(target_cols, query_vec, top_k=per_source_k)

# 第2路：BM25 检索（query → jieba 分词 → 关键词 top-K）
bm25_results = self.bm25.search_multi(target_cols, query, top_k=per_source_k)

# 第3步：RRF 融合
fused = self._rrf_fuse(semantic_results, bm25_results, top_k)
```

**RRF 融合算法**（`_rrf_fuse`）：

```python
k = config.rrf_k   # 60
# 对每个唯一 chunk：
#   RRF_score = 1/(k + rank_vec) + 1/(k + rank_bm25)
# 未出现在某路的 chunk 该路贡献为 0
```

- **只看排名不看分数**：语义相似度和 BM25 分数尺度完全不同（一个是余弦、一个是 idf 加权），无法直接相加；RRF 把两路都折算成排名分，天然可比
- **k=60 平滑**：避免排名靠前的结果分数差距过大
- **按唯一 chunk 去重合并**：`_chunk_key` 用 `collection|source_file|chunk_index`（不用 `hash()`，理由同 md5 id），两路命中的同一 chunk 分数累加，两路都命中的结果天然排前——**这正是双路互补的体现**

**结果结构**（`HybridSearchResult`）：保留 `vector_score`/`bm25_score`/`vector_rank`/`bm25_rank`/`rrf_score`/`rerank_score`——每一路的信息都不丢，可审计、可调试。

### 重排（reranker.py，可选）

LLM 对 `query + chunk` 逐条打 1-5 分，5 线程并行，按分数重排。**评分写入独立字段 `rerank_score`，不覆盖 `rrf_score`**——保留原始检索信息，重排只是第二遍精细排序。设计上预留了替换为专用 cross-encoder（bge-reranker-v2-m3）的扩展点。

---

## 生成层（generator.py）

**Prompt 三段式**：系统角色 + 参考资料（带来源编号）+ 用户问题。

```python
## 系统角色
{system_prompt}
## 参考资料
[1] (来源: {source_file} / {title})
{chunk_text}
## 用户问题
{query}
```

**按题材加载 system prompt**（`load_system_prompt`）：`prompts/{genre}.txt → prompts/default.txt → 内置默认`。接入新题材时在 prompts/ 放同名 .txt 即可定制生成风格（如 xianxia.txt 强调"仙侠术语准确、境界体系一致"）。

**诚实规则**（写进默认 prompt）：资料有答案就引用并标注来源；资料不足就明说"未找到"；创作延伸需标注"创作建议"——**防止 LLM 编造典籍内容**。

---

## 配置驱动：题材注册表（genre_registry.py）

**为什么从硬编码改 YAML**：原来题材/collection 映射硬编码在 config.py 里，别人接入自己的资料要改代码。现在：

```yaml
genres:
  xianxia:
    path: xianxia
    default_collection: xianxia_classics
    processed_default_collection: xianxia_terminology
    collections:
      - name: xianxia_classics
        dir_keywords: ["01-道藏核心", "02-神话仙传", "04-儒释补充", "narrative"]
      - name: xianxia_cultivation
        dir_keywords: ["03-术数阵法"]
        file_keywords: ["修炼"]
```

**三个设计细节**：

1. **默认配置 = 改造前行为的逐字快照**（`DEFAULT_GENRES_YAML` 内置字符串）：首次运行自动生成配置文件，现有管线零影响——迁移不破坏任何东西。
2. **兜底机制**：未注册题材 → `{genre}_general` 兜底 collection；目录级关键词优先，processed 子目录走文件级关键词，最后落 default。
3. **避免循环依赖**：genre_registry 不 import config（用 `Path(__file__).parent.parent` 定位项目根），config 单方面依赖 registry，并提供兼容旧签名的 `get_collections_for_genre`/`guess_collection`。

**归类规则优先级**：`dir_keywords（目录级）→ processed + file_keywords（文件级）→ processed_default → default`。

---

## 命令行：人机分离的双入口

### cli.py — 给人用（rich 美化）

```bash
python cli.py ingest --genre xianxia        # 摄入
python cli.py ingest --all                  # 全部题材
python cli.py ingest --incremental          # 增量
python cli.py query "金丹期" --interactive  # 交互式查询
python cli.py info                          # 索引状态
python cli.py clean --all                   # 清空
```

`_discover_genres()` 取**配置文件注册的题材 ∪ _bible/ 下实际存在的目录**（并集）——新目录不用注册也能被发现。

### rag_query.py — 给 Agent 用（JSON 输出）

```bash
python rag_query.py "金丹期如何突破" --search-only --top-k 5
# → JSON 数组：[{"text", "score", "source", "title", "dynasty", "author", "collection"}]
```

**这是 Agent 工作流的关键设计**：`_agents/*.md` 里写的就是这条命令（`--search-only` 输出纯 JSON），Agent（AI 会话）直接消费结构化检索结果，不需要解析 rich 表格。

---

## 编排层：对话式多 Agent（项目灵魂）

> ⚠️ 诚实说明：这个项目的编排层**刻意不是代码**——8 个 Agent 是 `_agents/*.md` 岗位说明书，由主编在 AI 会话（Claude/DeepSeek/DSH）中调度。这是产品决策：写作需要每步人工判断，脚本化 workflow 不可打断、问题不可见。

**团队构成**（`_agents/orchestrator.md` 主编调度 7 个专职 Agent）：

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

**单章写作闭环**：

```
章纲（7 项评判自检）→ Writer 起草
  → Reviewer + FormatChecker 并行审稿
  → 通过 → 定稿 → 微型检查 → 更新 novel_state.yaml
  → 不通过 → 修改循环（≤3 轮）→ 仍不过 → 标记「需人工介入」
```

**分书命名空间**：`_outline/{book}/`、`chapters/{book}/`、`_memory/{book}/`、`_reviews/{book}/`——多本书并存互不干扰，当前活跃书由 `.env` 的 `CURRENT_BOOK` 指定。

**状态快照**：`novel_state.yaml` 存角色状态/活跃伏笔/时间线——**不依赖 LLM 记忆**（跨会话丢失），RAG 查前文只能精确检索、不能做状态感知，所以状态单独结构化持久化。

**演进记录**：`AGENT_REVIEW.md` 记录每个 Agent 的评审 → 优化方向 → 落地状态——这是"项目在持续迭代"的证据。

---

## 关键设计决策（面试必问）与答案

**Q1：为什么编排用对话式，不用 LangGraph/CrewAI 脚本化？**
A：写作不是确定性流程——节奏、爽点、方向都需要每步人工判断。脚本化 workflow 不可打断、问题不可见；对话式主编每步可检查/打断/覆写，适合创作场景。**这是产品决策**：把"确定性流程"（RAG 摄入/检索）脚本化，把"需要判断的流程"（写作编排）留给对话。

**Q2：为什么双路检索 + RRF，不用单一向量检索？**
A：网文写作查询两类需求：① 专有名词精确匹配（"苍云宗""金丹"）——向量检索抓不住；② 同义表达语义匹配（"修炼/修行/证道"）——BM25 抓不住。RRF 按排名融合：两路都命中的结果天然排前，各取所长。且 RRF 只看排名不看分数，规避了两路分数尺度不可比的问题。

**Q3：增量摄入怎么保证不漏？**
A：manifest 存 `{相对路径: [mtime, size]}` 指纹。增量模式对比指纹，只处理新增/变更文件；**全量摄入也写 manifest**，为后续增量做准备。指纹用 mtime+size 双字段，避免只靠 mtime 精度不足或只靠 size 撞车。

**Q4：429 限流怎么处理？1 万条能摄入完吗？**
A：分两层：① 自动——embedder 对 429 长退避重试（默认 10 次、单次最长 60s，**尊重 Retry-After 头**），窗口恢复后自动继续；② 手动——`--batch-size 16/8` 减单批 token + `--batch-delay 1~3` 批间降速。1 万条最终能全部摄入，只是慢。

**Q5：换 embedding 模型会怎样？**
A：三个防线：① 运行时维度校验（API 返回维度 ≠ `EMBEDDING_DIM` 即告警）；② 需要 `--clear` 重建索引（新旧向量不能混存）；③ `.env` 的 `EMBEDDING_DIM` 是显式配置，换模型必须同步改。

**Q6：为什么存走底层、查走 LangChain wrapper？**
A：存——我们已在管线里算好 embedding，直接写底层 collection 跳过 LangChain 的自动 embedding（省一次重复计算）；查——LangChain Chroma wrapper 的接口与 hybrid_search 集成更顺；管理（list/delete/count）——原生 chromadb client 轻量无副作用。三套接口各取所需。

**Q7：Agent 怎么用 RAG？**
A：`rag_query.py --search-only` 输出纯 JSON，Agent 在写作循环里直接消费——查设定、查典籍、查术语，结果带来源（书名/朝代/作者），写手引用有据可依。**人用 cli.py（rich 表格），Agent 用 rag_query.py（JSON）**——同一套检索，两种输出。

---

## 踩坑/修复汇总（面试加分素材）

| 坑 | 现象 | 根因 | 修复 |
|----|------|------|------|
| ChromaDB 重复摄入脏数据 | 同文本产生不同 id | `hash()` 进程内随机化 | 改用 `md5(text)` 确定性 id |
| BM25 无法持久化 | pickle 报错 | `BM25Okapi` 不可 pickle | 存 tokenized corpus + 重建 |
| 大批量写入失败 | ChromaDB 报 batch 超限 | 单批约 5461 条上限 | `MAX_BATCH = 5000` 分批 |
| 编码误判乱码 | 解码成功但全文乱码 | 部分编码"假成功" | 替换字符 >1% 视为失败继续尝试 |
| 测试 fixture 缺目录 | 摄入测试 FileNotFound | conftest 只建了部分题材子目录 | 补齐全部子目录 |
| 测试样例低于阈值 | chunk 为 0 断言失败 | 样例 47 字 < min_chunk_size=50 | 加长样例文本 |
| 换模型维度不匹配 | ChromaDB 写入报错 | 维度变了配置没变 | 运行时校验 + 告警 |

---

## 工程化

- **零代码安装**：`setup.bat`（Windows 双击）/ `setup.sh`——自动建 venv + 装依赖 + 生成 .env 模板；README 提供"复制这段话给 AI"引导，AI 自动完成配置。
- **Agent 配置标准化**：`AGENTS.md`（跨工具：Claude Code/Cursor/Codex/DSH）+ `CLAUDE.md`（Claude/DSH 专属，含写作工作流引导）。
- **测试**：`pytest`（5 个 smoke test：归类规则、摄入→检索端到端、未注册题材兜底、BM25 持久化），FakeEmbedder 固定向量，不触发真实 API。
- **文档**：`docs/RAG.md`（设计 + 使用指南）+ 本文（代码级讲解）+ `AGENT_REVIEW.md`（演进记录）。

---

## 一句话总结

这个项目值钱的地方不在"用了 ChromaDB/BM25"这些名词，而在**三个能讲透的设计决策**：① **对话式编排**（把需要判断的流程留给 AI 会话，把确定性流程脚本化）；② **双路 RRF 融合**（排名融合规避分数尺度问题，专有名词与同义表达兼得）；③ **配置驱动 + 自愈工程**（题材接入零代码、增量摄入省钱、429 自愈抗限流）。配合完整的写作闭环和持续迭代的演进记录，它是一个能经得起深挖、且真正解决"AI 写网文设定不一致"痛点的项目。
