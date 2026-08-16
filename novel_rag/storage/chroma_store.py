"""
ChromaDB 向量库封装 —— 每个知识领域一个 collection。

设计:
  - 存：直接写底层 collection，绕过 LangChain 的自动 embedding（我们已经算好了）
  - 查：用 LangChain Chroma wrapper，方便与 hybrid_search 集成
  - 管理：list/delete/count 用原生 chromadb client，轻量且无副作用

使用方式:
    from novel_rag.storage.chroma_store import ChromaStore
    store = ChromaStore()
    store.add_chunks("xianxia_classics", texts, metas, embeddings)
    results = store.search("xianxia_classics", query_vec, top_k=10)
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from langchain_chroma import Chroma

from novel_rag.config import config
from novel_rag.ingestion.embedder import Embedder


class ChromaStore:
    """ChromaDB 向量存储"""

    def __init__(self, persist_dir: str | Path | None = None):
        self.persist_dir = str(persist_dir or config.chroma_persist_dir)
        os.makedirs(self.persist_dir, exist_ok=True)
        self._embedder = Embedder()
        self._raw_client = None
        # LangChain Chroma 实例缓存: collection_name → Chroma
        self._stores: dict[str, Chroma] = {}

    # ── 原生 chromadb client（懒加载，单例）──

    @property
    def _client(self):
        """原生 chromadb PersistentClient，用于轻量管理操作"""
        if self._raw_client is None:
            import chromadb
            self._raw_client = chromadb.PersistentClient(path=self.persist_dir)
        return self._raw_client

    # ── LangChain Chroma 实例（懒加载，缓存）──

    def _get_store(self, collection_name: str) -> Chroma:
        """获取或创建 LangChain Chroma wrapper（带缓存）"""
        if collection_name not in self._stores:
            self._stores[collection_name] = Chroma(
                collection_name=collection_name,
                embedding_function=_LangChainEmbeddingAdapter(self._embedder),
                persist_directory=self.persist_dir,
            )
        return self._stores[collection_name]

    def _invalidate_cache(self, collection_name: str | None = None):
        """清除缓存（删 collection 后调用）"""
        if collection_name:
            self._stores.pop(collection_name, None)
        else:
            self._stores.clear()

    # ── Collection 管理 ───────────────────────

    def collection_exists(self, name: str) -> bool:
        """检查 collection 是否存在（无副作用，不创建）"""
        existing = [c.name for c in self._client.list_collections()]
        return name in existing

    def list_collections(self) -> list[str]:
        """列出所有 collection"""
        return [c.name for c in self._client.list_collections()]

    def delete_collection(self, name: str):
        """删除 collection"""
        try:
            self._client.delete_collection(name)
            self._invalidate_cache(name)
            print(f"[ChromaStore] 已删除 collection: {name}")
        except Exception as e:
            print(f"[ChromaStore] 删除失败 ({name}): {e}")

    # ── 数据写入 ──────────────────────────────

    def add_chunks(
        self,
        collection_name: str,
        texts: list[str],
        metadatas: list[dict],
        embeddings: list[list[float]] | None = None,
    ):
        """
        批量写入 chunk 到指定 collection。

        如果提供了 embeddings，直接写底层 collection（跳过 LangChain 的自动 embedding，
        因为我们已经在管线里算好了）。
        """
        # 确定性 id：基于 collection + 文本内容 md5。
        # 之前用 hash(text)（进程内随机），重复摄入会产生不同 id，导致脏数据。
        ids = [
            f"{collection_name}_{i}_{hashlib.md5(text.encode('utf-8')).hexdigest()[:16]}"
            for i, text in enumerate(texts)
        ]

        # ChromaDB 单批写入上限约 5461 条，超限时分批写入
        MAX_BATCH = 5000

        if embeddings:
            store = self._get_store(collection_name)
            for i in range(0, len(texts), MAX_BATCH):
                store._collection.add(
                    ids=ids[i : i + MAX_BATCH],
                    embeddings=embeddings[i : i + MAX_BATCH],
                    documents=texts[i : i + MAX_BATCH],
                    metadatas=metadatas[i : i + MAX_BATCH],
                )
        else:
            # 走 LangChain 自动 embedding（一般不用）
            store = self._get_store(collection_name)
            for i in range(0, len(texts), MAX_BATCH):
                store.add_texts(
                    texts=texts[i : i + MAX_BATCH],
                    metadatas=metadatas[i : i + MAX_BATCH] if metadatas else None,
                    ids=ids[i : i + MAX_BATCH],
                )

    # ── 检索 ──────────────────────────────────

    def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[dict]:
        """
        在指定 collection 中做语义检索（余弦相似度）。

        返回: [{"text": ..., "metadata": ..., "score": ..., "collection": ...}, ...]
        """
        store = self._get_store(collection_name)
        results = store._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        output: list[dict] = []
        if results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                # ChromaDB 返回的是余弦距离，转换为相似度分数
                distance = results["distances"][0][i] if results["distances"] else 0.0
                output.append({
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "score": 1.0 - distance,
                    "collection": collection_name,
                })
        return output

    def search_multi(
        self,
        collection_names: list[str],
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[dict]:
        """
        跨多个 collection 检索，合并结果按相似度降序排列。

        返回 top_k 条，而非 top_k * n_collections 条。
        """
        all_results: list[dict] = []
        for name in collection_names:
            try:
                results = self.search(name, query_embedding, top_k=top_k)
                all_results.extend(results)
            except Exception as e:
                print(f"[ChromaStore] 检索 {name} 失败: {e}")

        # 按相似度降序，取 top_k 条
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results[:top_k]

    # ── 统计 ──────────────────────────────────

    def count(self, collection_name: str) -> int:
        """返回 collection 中的 chunk 数量"""
        try:
            store = self._get_store(collection_name)
            return store._collection.count()
        except Exception:
            return 0

    def stats(self) -> dict:
        """返回所有 collection 的统计信息"""
        return {col: self.count(col) for col in self.list_collections()}


# ── LangChain Embedding 适配器 ──

class _LangChainEmbeddingAdapter:
    """
    将我们的 Embedder 包装成 LangChain 兼容的 Embeddings 接口。
    供 LangChain Chroma wrapper 构造函数使用。
    """

    def __init__(self, embedder: Embedder):
        self._embedder = embedder

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embedder.embed_query(text)
