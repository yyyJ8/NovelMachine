# 题材素材（_bible）

RAG 的唯一输入目录。**资料自备**——本仓库不含任何典籍原文，只留这个占位说明。

## 约定

```
_bible/
└── {题材}/                   # 题材名，对应 config/genres.yaml 的 key（如 xianxia）
    ├── raw/                  # 原始资料（摄入时递归扫描）
    │   ├── 01-xxx/           #   子目录名可命中 dir_keywords，决定落入哪个 collection
    │   └── 02-yyy/
    └── processed/            # 加工后的精炼资料（按文件名命中 file_keywords）
```

## 放什么

- 只放 `.md` / `.txt` / `.pdf`，其他格式请先转换
- 想自定义归类：编辑 `config/genres.yaml`；不配置也能跑，全部落入 `{题材}_general`
- 摄入会**递归扫描整个 `{题材}/` 目录**，模板 YAML 之类的非资料文件不要放在里面

## 摄入

```bash
python cli.py ingest --genre xianxia
python cli.py ingest --genre xianxia --incremental                    # 只处理新增/变更
python cli.py ingest --genre xianxia --batch-size 16 --batch-delay 1   # 429 限流时
```

## 放在仓库外（推荐）

资料体积大、且属于个人财产，建议用 `.env` 指到仓库外：

```env
BIBLE_DIR=D:/corpus/_bible
CHROMA_PERSIST_DIR=D:/corpus/index/chroma_db
BM25_INDEX_DIR=D:/corpus/index/bm25_indexes
```

`.gitignore` 默认忽略 `_bible/*/`，所以放在仓库内也不会被误提交。
