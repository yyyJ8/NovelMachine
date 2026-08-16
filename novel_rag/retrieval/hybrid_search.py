"""
混合检索核心 —— 两路召回（语义 + BM25）+ RRF 融合。

算法:
  1. 用户 query → embed_query → 语义检索 Top-K
  2. 用户 query → jieba 分词 → BM25 检索 Top-K
  3. RRF 融合: score(d) = Σ 1/(k + rank_i(d))
  4. 按 RRF score 降序返回 Top-K

使用方式:
    from novel_rag.retrieval.hybrid_search import HybridSearcher
    searcher = HybridSearcher()
    results = searcher.search("金丹期如何突破", genre="xianxia", top_k=5)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from novel_rag.config import config, get_collections_for_genre, get_all_collections
from novel_rag.ingestion.embedder import Embedder
from novel_rag.storage.chroma_store import ChromaStore
from novel_rag.storage.bm25_index import BM25Store


@dataclass
class HybridSearchResult:
    """混合检索结果"""
    text: str
    metadata: dict = field(default_factory=dict)
    rrf_score: float = 0.0
    vector_score: float | None = None
    bm25_score: float | None = None
    vector_rank: int | None = None
    bm25_rank: int | None = None
    rerank_score: float | None = None       # LLM 重排序分数（独立字段，不覆盖 rrf）
    collection: str = ""
    chunk_id: str = ""


class HybridSearcher:
    """混合检索引擎：语义 + BM25 → RRF 融合"""

    def __init__(
        self,
        chroma_store: ChromaStore | None = None,
        bm25_store: BM25Store | None = None,
        embedder: Embedder | None = None,
    ):
        self.chroma = chroma_store or ChromaStore()
        self.bm25 = bm25_store or BM25Store()
        self.embedder = embedder or Embedder()

    # ── 主检索方法 ────────────────────────────

    def search(
        self,
        query: str,
        collections: list[str] | None = None,
        genre: str | None = None,
        top_k: int | None = None,
        per_source_k: int | None = None,
        verbose: bool = False,
    ) -> list[HybridSearchResult]:
        """
        执行混合检索。

        参数:
            query: 用户查询
            collections: 要检索的 collection 列表（优先于 genre）
            genre: 题材名，自动展开为对应 collections
            top_k: 最终返回结果数（默认 config.fusion_top_k = 5）
            per_source_k: 每路召回的候选数（默认 top_k * 3）
            verbose: 打印详细日志
        """
        top_k = top_k or config.fusion_top_k
        per_source_k = per_source_k or (top_k * 3)

        # 确定目标 collections
        if collections:
            target_cols = collections
        elif genre:
            target_cols = get_collections_for_genre(genre)
        else:
            target_cols = get_all_collections()

        if not target_cols:
            print(f"[HybridSearch] 未找到匹配的 collection")
            return []

        if verbose:
            print(f"[HybridSearch] 查询: {query}")
            print(f"[HybridSearch] 目标 collections: {target_cols}")

        t0 = time.time()

        # ── 第1路：语义检索 ──────────────────
        query_vec = self.embedder.embed_query(query)
        semantic_results = self.chroma.search_multi(target_cols, query_vec, top_k=per_source_k)
        if verbose:
            print(f"[HybridSearch] 语义检索: {len(semantic_results)} 条 ({time.time()-t0:.2f}s)")

        # ── 第2路：BM25 检索 ──────────────────
        bm25_results = self.bm25.search_multi(target_cols, query, top_k=per_source_k)
        if verbose:
            print(f"[HybridSearch] BM25 检索: {len(bm25_results)} 条 ({time.time()-t0:.2f}s)")

        # ── RRF 融合 ──────────────────────────
        fused = self._rrf_fuse(semantic_results, bm25_results, top_k)
        if verbose:
            print(f"[HybridSearch] RRF 融合后: {len(fused)} 条 ({time.time()-t0:.2f}s)")

        return fused

    # ── RRF 融合算法 ──────────────────────────

    def _rrf_fuse(
        self,
        semantic_results: list[dict],
        bm25_results: list[dict],
        top_k: int,
    ) -> list[HybridSearchResult]:
        """
        Reciprocal Rank Fusion。

        对每个唯一 chunk:
            RRF_score = 1/(k + rank_vec) + 1/(k + rank_bm25)
        其中 k=60，未出现在某路的 chunk 该路贡献为 0。
        """
        k = config.rrf_k
        chunk_map: dict[str, HybridSearchResult] = {}

        # 处理语义检索结果
        for rank, result in enumerate(semantic_results, start=1):
            key = _chunk_key(result)
            if key not in chunk_map:
                chunk_map[key] = HybridSearchResult(
                    text=result["text"],
                    metadata=result.get("metadata", {}),
                    collection=result.get("collection", ""),
                )
            chunk_map[key].vector_score = result.get("score")
            chunk_map[key].vector_rank = rank
            chunk_map[key].rrf_score += 1.0 / (k + rank)

        # 处理 BM25 结果
        for rank, result in enumerate(bm25_results, start=1):
            key = _chunk_key(result)
            if key not in chunk_map:
                chunk_map[key] = HybridSearchResult(
                    text=result["text"],
                    metadata=result.get("metadata", {}),
                    collection=result.get("collection", ""),
                )
            chunk_map[key].bm25_score = result.get("score")
            chunk_map[key].bm25_rank = rank
            chunk_map[key].rrf_score += 1.0 / (k + rank)

        # 按 RRF 分数降序排列
        sorted_results = sorted(
            chunk_map.values(),
            key=lambda x: x.rrf_score,
            reverse=True,
        )

        return sorted_results[:top_k]


def _chunk_key(result: dict) -> str:
    """
    生成 chunk 唯一标识。

    用 source_file + chunk_index 组合（同一个 chunk 在语义和 BM25 中出现时
    能正确去重合并），不依赖 hash()（Python 进程间随机化）。
    """
    meta = result.get("metadata", {})
    col = result.get("collection", "")
    source = meta.get("source_file", "")
    chunk_idx = meta.get("chunk_index", "")
    return f"{col}|{source}|{chunk_idx}"
