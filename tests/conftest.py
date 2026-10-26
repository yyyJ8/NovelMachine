"""
共享测试 fixture —— 隔离配置路径 + 提供 FakeEmbedder。

所有测试都不调用真实 API（embedding / LLM），用 FakeEmbedder 返回固定向量。
"""

from __future__ import annotations

import pytest

from novel_rag.config import config


class FakeEmbedder:
    """固定向量的假 Embedder，避免测试触发真实 API 调用"""

    def __init__(self, dim: int | None = None):
        self._dim = dim or config.embedding_dim

    def embed_texts(self, texts: list[str], batch_size: int | None = None, batch_delay: float | None = None) -> list[list[float]]:
        return [[0.1] * self._dim for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * self._dim


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """
    把 chroma/bm25/bible 目录重定向到临时目录，并还原配置到全局 config。
    （config 是模块级单例，测试后必须恢复，避免污染其他测试）
    """
    old = {
        "chroma": config.chroma_persist_dir,
        "bm25": config.bm25_index_dir,
        "bible": config.bible_dir,
    }
    config.chroma_persist_dir = tmp_path / "chroma_db"
    config.bm25_index_dir = tmp_path / "bm25_indexes"
    config.bible_dir = tmp_path / "bible"
    (config.bible_dir / "xianxia" / "raw" / "01-道藏核心").mkdir(parents=True)
    (config.bible_dir / "xianxia" / "raw" / "02-神话仙传").mkdir(parents=True)
    (config.bible_dir / "xianxia" / "raw" / "03-术数阵法").mkdir(parents=True)
    yield config
    config.chroma_persist_dir = old["chroma"]
    config.bm25_index_dir = old["bm25"]
    config.bible_dir = old["bible"]


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()
