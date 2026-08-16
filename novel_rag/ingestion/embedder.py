"""
Embedding 客户端 —— 封装 SiliconFlow 的 OpenAI 兼容 API。

模型: BAAI/bge-m3（1024 维）
API: POST /v1/embeddings

使用方式:
    from novel_rag.ingestion.embedder import Embedder
    embedder = Embedder()
    vec = embedder.embed_query("金丹期修士渡劫")
    vecs = embedder.embed_texts(["文本1", "文本2"])
"""

from __future__ import annotations

import time
from openai import OpenAI

from novel_rag.config import config


class Embedder:
    """SiliconFlow Embedding 客户端"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or config.api_key
        self.base_url = base_url or config.base_url
        self.model = model or config.embedding_model

        # 使用 OpenAI 兼容客户端
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=60.0,
            max_retries=0,  # 我们自己控制重试
        )

    def embed_query(self, text: str) -> list[float]:
        """单条查询 embedding"""
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量 embedding（自动处理分批 + 重试）"""
        if not texts:
            return []

        all_vectors: list[list[float]] = []
        batch_size = config.embedding_batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            vectors = self._embed_batch_with_retry(batch)
            all_vectors.extend(vectors)

        # 维度校验：API 返回维度与 .env 的 EMBEDDING_DIM 不一致时告警
        # （换 embedding 模型后维度会变，需同步改 .env，否则 ChromaDB 写入会出错）
        expected = config.embedding_dim
        actual = len(all_vectors[0]) if all_vectors else expected
        if actual != expected:
            print(
                f"[Embedder] 警告: 实际向量维度 {actual} != 配置 EMBEDDING_DIM {expected}，"
                f"请在 .env 中设置 EMBEDDING_DIM={actual}（换模型后索引需重建）"
            )

        return all_vectors

    def _embed_batch_with_retry(self, texts: list[str]) -> list[list[float]]:
        """单批 embedding，含重试逻辑"""
        last_error = None

        for attempt in range(config.max_retries):
            try:
                response = self._client.embeddings.create(
                    model=self.model,
                    input=texts,
                )
                # 按输入顺序排列
                sorted_data = sorted(response.data, key=lambda x: x.index)
                return [d.embedding for d in sorted_data]

            except Exception as e:
                last_error = e
                if attempt < config.max_retries - 1:
                    wait = config.retry_delay * (2 ** attempt)
                    print(f"[Embedder] 重试 {attempt + 1}/{config.max_retries}，等待 {wait:.1f}s: {e}")
                    time.sleep(wait)

        raise RuntimeError(f"Embedding 失败（重试{config.max_retries}次后仍失败）: {last_error}")

    def embed_dim(self) -> int:
        """返回向量维度"""
        return config.embedding_dim


# ── 全局单例 ──────────────────────────────────
embedder = Embedder()
