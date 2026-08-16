"""
BM25 关键词索引 —— 每个 collection 维护独立的 BM25 索引。

使用 jieba 分词（中文友好），支持持久化/恢复。
与 ChromaDB 的语义检索互补，对专有名词/精确匹配有更好的召回。

使用方式:
    from novel_rag.storage.bm25_index import BM25Store
    bm25 = BM25Store()
    bm25.build("xianxia_bestiary", chunks)
    results = bm25.search("xianxia_bestiary", "苍云宗", top_k=10)
"""

from __future__ import annotations

import json
import pickle
import os
from pathlib import Path
from collections import defaultdict

import jieba
from rank_bm25 import BM25Okapi

from novel_rag.config import config
from novel_rag.ingestion.chunker import Chunk


class BM25Store:
    """BM25 关键词索引管理器"""

    def __init__(self, index_dir: str | Path | None = None):
        self.index_dir = Path(index_dir or config.bm25_index_dir)
        os.makedirs(self.index_dir, exist_ok=True)

        # 内存中的索引
        # collection_name → {"model": BM25Okapi, "texts": list[str], "metas": list[dict]}
        self._indexes: dict[str, dict] = {}

    # ── 构建索引 ──────────────────────────────

    def build(self, collection_name: str, chunks: list[Chunk]):
        """
        为指定 collection 构建 BM25 索引。
        会覆盖旧索引。
        """
        if not chunks:
            print(f"[BM25] {collection_name}: 无数据，跳过")
            return

        texts = [c.text for c in chunks]
        metas = [c.metadata for c in chunks]
        tokenized = [self._tokenize(t) for t in texts]

        model = BM25Okapi(tokenized)

        self._indexes[collection_name] = {
            "model": model,
            "texts": texts,
            "metas": metas,
            "tokenized": tokenized,
        }

        print(f"[BM25] {collection_name}: 已索引 {len(texts)} 条 chunk")

    def build_from_texts(self, collection_name: str, texts: list[str], metadatas: list[dict] | None = None):
        """从纯文本列表构建索引"""
        chunks = [
            Chunk(text=text, metadata=metadatas[i] if metadatas else {})
            for i, text in enumerate(texts)
        ]
        self.build(collection_name, chunks)

    # ── 检索 ──────────────────────────────────

    def search(
        self,
        collection_name: str,
        query: str,
        top_k: int = 10,
    ) -> list[dict]:
        """
        在指定 collection 中做 BM25 关键词检索。
        返回: [{"text": ..., "metadata": ..., "score": ...}, ...]
        """
        if collection_name not in self._indexes:
            return []

        idx = self._indexes[collection_name]
        model: BM25Okapi = idx["model"]
        texts: list[str] = idx["texts"]
        metas: list[dict] = idx["metas"]

        tokenized_query = self._tokenize(query)
        scores = model.get_scores(tokenized_query)

        # 取 top_k（不过滤负分：小语料/高词频词在 rank_bm25 下 idf 可能为负，
        # 相对大小仍有排序意义；过滤会误杀有效结果）
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)
        top = indexed[:top_k]

        results: list[dict] = []
        for idx, score in top:
            results.append({
                "text": texts[idx],
                "metadata": metas[idx] if idx < len(metas) else {},
                "score": float(score),
                "collection": collection_name,
            })
        return results

    def search_multi(
        self,
        collection_names: list[str],
        query: str,
        top_k: int = 10,
    ) -> list[dict]:
        """跨多个 collection 检索，合并排序。

        返回 top_k 条（与 ChromaStore.search_multi 的语义路对称），
        保证 RRF 融合时两路候选数量一致。
        """
        all_results: list[dict] = []
        for name in collection_names:
            results = self.search(name, query, top_k=top_k)
            all_results.extend(results)

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results[:top_k]

    # ── 持久化 ────────────────────────────────

    def save(self, collection_name: str | None = None):
        """
        保存索引到磁盘。
        如果指定 collection_name 则只保存那一个；否则保存全部。
        """
        names = [collection_name] if collection_name else list(self._indexes.keys())
        for name in names:
            if name not in self._indexes:
                continue
            idx = self._indexes[name]
            save_path = self.index_dir / f"{name}.bm25"
            # 保存 tokenized corpus + 元数据（BM25Okapi 本身不可 pickle，存 tokenized 重建）
            data = {
                "texts": idx["texts"],
                "metas": idx["metas"],
                "tokenized": idx["tokenized"],
            }
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"[BM25] 已保存: {save_path}")

    def load(self, collection_name: str | None = None):
        """
        从磁盘加载索引。
        如果指定 collection_name 则只加载那一个；否则加载全部。
        """
        if collection_name:
            names = [collection_name]
        else:
            # 扫描 index_dir 下的所有 .bm25 文件
            names = [
                p.stem
                for p in self.index_dir.glob("*.bm25")
            ]

        for name in names:
            load_path = self.index_dir / f"{name}.bm25"
            if not load_path.exists():
                continue
            with open(load_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            model = BM25Okapi(data["tokenized"])
            self._indexes[name] = {
                "model": model,
                "texts": data["texts"],
                "metas": data["metas"],
                "tokenized": data["tokenized"],
            }
            print(f"[BM25] 已加载: {load_path} ({len(data['texts'])} 条)")

    def loaded_collections(self) -> list[str]:
        """返回当前已加载的 collection 名称"""
        return list(self._indexes.keys())

    # ── 内部 ──────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """jieba 分词，过滤空白"""
        return [w.strip() for w in jieba.cut(text) if w.strip()]
