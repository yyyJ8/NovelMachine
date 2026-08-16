"""
摄入层 —— 文档加载 → 文本分块 → Embedding 向量化。

使用方式:
    from novel_rag.ingestion.loader import load_file, load_directory, Document
    from novel_rag.ingestion.chunker import chunk_documents, Chunk, ChunkStrategy
    from novel_rag.ingestion.embedder import Embedder
"""

from novel_rag.ingestion.loader import Document, load_file, load_directory
from novel_rag.ingestion.chunker import Chunk, ChunkStrategy, chunk_documents
from novel_rag.ingestion.embedder import Embedder

__all__ = [
    "Document", "load_file", "load_directory",
    "Chunk", "ChunkStrategy", "chunk_documents",
    "Embedder",
]
