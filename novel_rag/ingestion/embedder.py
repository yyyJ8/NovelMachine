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
from openai import OpenAI, RateLimitError

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

    def embed_texts(
        self,
        texts: list[str],
        batch_size: int | None = None,
        batch_delay: float | None = None,
    ) -> list[list[float]]:
        """
        批量 embedding（自动分批 + 重试）。

        参数:
            batch_size: 每批条数（默认 config.embedding_batch_size；调小可降低单批 token 量）
            batch_delay: 批间等待秒数（默认 config.embedding_batch_delay；限流时调大降速）
        """
        if not texts:
            return []

        batch_size = batch_size or config.embedding_batch_size
        if batch_delay is None:
            batch_delay = config.embedding_batch_delay

        all_vectors: list[list[float]] = []
        total = len(texts)

        for i in range(0, total, batch_size):
            batch = texts[i : i + batch_size]
            if i > 0 and batch_delay > 0:
                time.sleep(batch_delay)
            vectors = self._embed_batch_with_retry(batch)
            all_vectors.extend(vectors)
            done = min(i + batch_size, total)
            if total > batch_size:  # 多批时才打印进度
                print(f"[Embedder] 已嵌入 {done}/{total} 条")

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
        """
        单批 embedding，含重试逻辑。

        普通错误: 指数退避重试 config.max_retries 次。
        429 限流: 尊重 Retry-After 头，指数退避（上限 config.rate_limit_max_wait）
                  重试 config.rate_limit_max_retries 次，等 TPM 窗口恢复后自动继续。
        """
        last_error = None
        is_rate_limited = False

        # ── 第一段：普通错误重试（遇到 429 立即转入限流循环）──
        for attempt in range(config.max_retries):
            try:
                return self._create_embeddings(texts)
            except Exception as e:
                if _is_rate_limit(e):
                    last_error, is_rate_limited = e, True
                    break
                last_error = e
                if attempt < config.max_retries - 1:
                    wait = config.retry_delay * (2 ** attempt)
                    print(f"[Embedder] 重试 {attempt + 1}/{config.max_retries}，等待 {wait:.1f}s: {type(e).__name__}: {e}")
                    time.sleep(wait)

        # ── 第二段：429 限流重试（等 TPM 窗口恢复）──
        if is_rate_limited:
            for attempt in range(config.rate_limit_max_retries):
                try:
                    return self._create_embeddings(texts)
                except Exception as e:
                    if not _is_rate_limit(e):
                        last_error = e
                        break
                    last_error = e
                    wait = _retry_after(e)
                    if wait is None:
                        wait = config.retry_delay * (2 ** attempt)
                    wait = min(max(wait, 1.0), config.rate_limit_max_wait)
                    print(
                        f"[Embedder] 429 限流，等待 {wait:.1f}s 重试 "
                        f"({attempt + 1}/{config.rate_limit_max_retries})..."
                    )
                    time.sleep(wait)

        raise RuntimeError(
            f"Embedding 失败（重试后仍失败）: {last_error}\n"
            f"若为 429 限流，建议: 调小批大小（--embed-batch-size 16 / 8）或"
            f"加大批间延时（--batch-delay 1~3）后重试"
        )

    def _create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """单次 API 调用 + 按输入顺序排列"""
        response = self._client.embeddings.create(
            model=self.model,
            input=texts,
        )
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [d.embedding for d in sorted_data]

    def embed_dim(self) -> int:
        """返回向量维度"""
        return config.embedding_dim


# ── 429 辅助 ────────────────────────────────────

def _is_rate_limit(e: Exception) -> bool:
    """判断异常是否为 429 限流"""
    if isinstance(e, RateLimitError):
        return True
    status = getattr(e, "status_code", None)
    if status is None:
        status = getattr(getattr(e, "response", None), "status_code", None)
    return status == 429


def _retry_after(e: Exception) -> float | None:
    """从异常响应头读取 Retry-After（秒）；无则返回 None"""
    try:
        headers = getattr(getattr(e, "response", None), "headers", None) or getattr(e, "headers", None)
        if headers:
            ra = headers.get("retry-after")
            if ra is not None:
                return float(ra)
    except (TypeError, ValueError, AttributeError):
        pass
    return None


# ── 全局单例 ──────────────────────────────────
embedder = Embedder()
