"""
重排序模块 —— 对混合检索结果做第二遍精细排序。

策略: 用 LLM 对 query + chunk 做相关性评分（1-5），取高分者。
后续可替换为专用 cross-encoder 模型（如 bge-reranker-v2-m3）。

使用方式:
    from novel_rag.retrieval.reranker import Reranker
    reranker = Reranker()
    reranked = reranker.rerank(query, results, top_k=5)
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from novel_rag.config import config
from novel_rag.retrieval.hybrid_search import HybridSearchResult


class Reranker:
    """
    重排序器。

    当前实现: LLM 逐条打分。
    每条 chunk 独立评分，可并行。

    注意: LLM 评分写入 rerank_score 字段，不覆盖 rrf_score（保留原始检索信息）。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        # 默认从配置读取（.env 可配 LLM_API_KEY / LLM_BASE_URL / RERANK_MODEL）
        self.api_key = api_key or config.effective_llm_api_key
        self.base_url = base_url or config.effective_llm_base_url
        self.model = model or config.rerank_model

    def rerank(
        self,
        query: str,
        results: list[HybridSearchResult],
        top_k: int = 5,
        parallel: bool = True,
        verbose: bool = False,
    ) -> list[HybridSearchResult]:
        """
        对混合检索结果重排序。

        参数:
            query: 原始查询
            results: 混合检索结果（通常取 top_k * 3 条送去重排）
            top_k: 重排后返回条数
            parallel: 是否并行评分（5 线程）
            verbose: 打印日志
        """
        if not results:
            return []

        candidates = results[: min(len(results), top_k * 3)]
        if verbose:
            print(f"[Reranker] 候选: {len(candidates)} 条, 目标: {top_k}")

        t0 = time.time()

        if parallel and len(candidates) > 1:
            scores = self._score_parallel(query, candidates)
        else:
            scores = [self._score_single(query, r) for r in candidates]

        # 写入 rerank_score（不覆盖 rrf_score）
        for r, s in zip(candidates, scores):
            r.rerank_score = s

        # 按 LLM 评分降序
        candidates.sort(key=lambda x: x.rerank_score or 0, reverse=True)

        if verbose:
            print(f"[Reranker] 重排完成 ({time.time()-t0:.2f}s)")

        return candidates[:top_k]

    # ── 评分逻辑 ──────────────────────────────

    def _score_single(self, query: str, result: HybridSearchResult) -> float:
        """让 LLM 给单条 chunk 打分（1-5）"""
        prompt = (
            f"评估以下文本片段与问题的相关性，只输出 1-5 的整数分数，不要解释。\n\n"
            f"问题: {query}\n\n"
            f"文本: {result.text[:300]}\n\n"
            f"相关性分数 (1=完全不相关, 5=高度相关):"
        )

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=5,
                temperature=0,
            )
            content = response.choices[0].message.content.strip()
            match = re.search(r'[1-5]', content)
            return float(match.group()) if match else 1.0
        except Exception as e:
            print(f"[Reranker] 评分失败: {e}")
            return 1.0

    def _score_parallel(self, query: str, results: list[HybridSearchResult]) -> list[float]:
        """并行评分（最多 5 线程）"""
        scores: list[float] = [1.0] * len(results)

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_idx = {
                executor.submit(self._score_single, query, r): i
                for i, r in enumerate(results)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    scores[idx] = future.result()
                except Exception as e:
                    print(f"[Reranker] 并行评分异常: {e}")

        return scores
