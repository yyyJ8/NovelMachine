"""
端到端管线 —— 将加载→分块→嵌入→存储→检索→生成串联起来。

摄入管线:  raw/ → load → chunk → embed → ChromaDB + BM25
查询管线:  query → embed → hybrid search → (rerank) → generate

使用方式:
    from novel_rag.pipeline import IngestionPipeline, QueryPipeline

    # 摄入
    ingest = IngestionPipeline()
    ingest.run(genre="xianxia")

    # 查询
    query_pipe = QueryPipeline()
    results = query_pipe.search("金丹期", genre="xianxia")
    answer = query_pipe.generate("金丹期怎么突破", genre="xianxia")
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from novel_rag.config import config, GENRE_PATHS, get_collections_for_genre, guess_collection
from novel_rag.ingestion.loader import load_directory, Document
from novel_rag.ingestion.chunker import chunk_documents, ChunkStrategy, Chunk
from novel_rag.ingestion.embedder import Embedder
from novel_rag.storage.chroma_store import ChromaStore
from novel_rag.storage.bm25_index import BM25Store
from novel_rag.retrieval.hybrid_search import HybridSearcher, HybridSearchResult
from novel_rag.retrieval.reranker import Reranker
from novel_rag.generation.generator import Generator, GenerationResult, load_system_prompt


# ── 摄入管线 ──

class IngestionPipeline:
    """
    端到端摄入管线。

    流程:
      _bible/{genre}/raw/ → load_directory() → chunk_documents()
      → embed_texts() → ChromaDB + BM25
    """

    def __init__(self):
        self.chroma = ChromaStore()
        self.bm25 = BM25Store()
        self.embedder = Embedder()

    def run(
        self,
        genre: str | None = None,
        target_dir: str | Path | None = None,
        strategy: ChunkStrategy = ChunkStrategy.CLASSICAL,
        clear_existing: bool = False,
        verbose: bool = True,
        strict: bool = False,
        incremental: bool = False,
        batch_size: int | None = None,
        batch_delay: float | None = None,
    ) -> dict:
        """
        执行完整摄入。

        参数:
            genre: 题材名（如 "xianxia"），自动扫描 _bible/{genre}/
            target_dir: 或直接指定要扫描的目录
            strategy: 分块策略
            clear_existing: 是否先清空已有 collection
            verbose: 打印进度
            strict: 失败即抛异常（默认收集 warnings 继续，不静默）
            incremental: 增量摄入——只处理新增/变更文件（依据 mtime+size 指纹）
            batch_size: 每批 embedding 条数（默认 config.embedding_batch_size）
            batch_delay: 批间等待秒数（默认 config.embedding_batch_delay；429 限流时降速）
        返回:
            {"collections": {...}, "total_chunks": int, "elapsed": float,
             "warnings": [str, ...], "skipped": int}  # 增量模式跳过未变文件数
        """
        t0 = time.time()

        # 确定扫描目录
        if target_dir:
            scan_dir = Path(target_dir)
            genre = genre or "custom"
        elif genre:
            genre_subdir = GENRE_PATHS.get(genre, genre)
            scan_dir = config.bible_dir / genre_subdir
        else:
            raise ValueError("必须指定 genre 或 target_dir")

        if verbose:
            print(f"\n{'='*60}")
            print(f"[INGEST] 摄入管线启动")
            print(f"   题材: {genre}")
            print(f"   目录: {scan_dir}")
            print(f"   策略: {strategy.value}")
            print(f"{'='*60}")

        # ── 第1步：加载文档 ──────────────────
        if verbose:
            print("\n[1/5] 加载文档...")
        documents = load_directory(scan_dir, recursive=True)
        if verbose:
            print(f"   找到 {len(documents)} 个文档")
            for doc in documents[:5]:
                print(f"     - {doc.metadata.get('filename', '?')} ({doc.metadata.get('char_count', 0)}字)")

        # 增量模式：按 mtime+size 指纹过滤掉未变文件
        skipped = 0
        unchanged_rels: set[str] = set()
        if incremental and not clear_existing:
            manifest = self._load_manifest()
            kept: list[Document] = []
            for doc in documents:
                rel = _relative_path(doc.metadata.get("source_file", ""), scan_dir)
                sig = _file_signature(doc.metadata)
                if rel in manifest and manifest[rel] == sig:
                    skipped += 1
                    unchanged_rels.add(rel)
                    continue
                kept.append(doc)
            if verbose and skipped:
                print(f"   增量模式: 跳过 {skipped} 个未变化文件")
            documents = kept

        if not documents:
            msg = "未发现需要摄入的文档（增量模式下已全部跳过）"
            print(f"   [WARN] {msg}")
            return {"collections": {}, "total_chunks": 0, "elapsed": time.time() - t0, "warnings": [msg], "skipped": skipped}

        # ── 第2步：分块 ──────────────────────
        if verbose:
            print(f"\n[2/5] 文本分块 (策略: {strategy.value}, size={config.chunk_size}, overlap={config.chunk_overlap})...")
        chunks = chunk_documents(documents, strategy=strategy)
        if verbose:
            print(f"   生成 {len(chunks)} 个 chunk")

        # ── 第3步：按 collection 分组 ──────────
        if verbose:
            print(f"\n[3/5] 按 collection 分组...")
        grouped = self._group_by_collection(chunks, genre)
        for col_name, col_chunks in grouped.items():
            if verbose:
                print(f"   {col_name}: {len(col_chunks)} chunks")

        # ── 第4步：嵌入 + 存储 ────────────────
        if verbose:
            print(f"\n[4/5] 生成 embedding 并写入 ChromaDB + BM25...")

        stats: dict[str, int] = {}
        total_stored = 0
        warnings: list[str] = []

        for col_name, col_chunks in grouped.items():
            if clear_existing:
                self.chroma.delete_collection(col_name)

            texts = [c.text for c in col_chunks]
            metas = [c.metadata for c in col_chunks]

            if verbose:
                print(f"   {col_name}: embedding {len(texts)} 条...")

            try:
                vecs = self.embedder.embed_texts(
                    texts,
                    batch_size=batch_size,
                    batch_delay=batch_delay,
                )
            except Exception as e:
                msg = f"{col_name} embedding 失败: {e}"
                if strict:
                    raise RuntimeError(msg) from e
                print(f"   [WARN]{msg}")
                warnings.append(msg)
                continue

            # 写入 ChromaDB
            try:
                self.chroma.add_chunks(col_name, texts, metas, vecs)
            except Exception as e:
                msg = f"{col_name} ChromaDB 写入失败: {e}"
                if strict:
                    raise RuntimeError(msg) from e
                print(f"   [WARN]{msg}")
                warnings.append(msg)

            # 构建 BM25 索引
            try:
                self.bm25.build(col_name, col_chunks)
            except Exception as e:
                msg = f"{col_name} BM25 构建失败: {e}"
                if strict:
                    raise RuntimeError(msg) from e
                print(f"   [WARN]{msg}")
                warnings.append(msg)

            stats[col_name] = len(texts)
            total_stored += len(texts)

        # ── 第5步：持久化 BM25 ────────────────
        if verbose:
            print(f"\n[5/5] 持久化 BM25 索引...")
        for col_name in grouped:
            try:
                self.bm25.save(col_name)
            except Exception as e:
                print(f"   [WARN]{col_name} BM25 保存失败: {e}")

        elapsed = time.time() - t0
        if verbose:
            print(f"\n{'='*60}")
            print(f"[DONE] 摄入完成! {total_stored} 条 chunk -> {len(grouped)} 个 collection")
            print(f"   耗时: {elapsed:.1f}s")
            if warnings:
                print(f"   ⚠ 以下 {len(warnings)} 项失败（已跳过）:")
                for w in warnings:
                    print(f"     - {w}")
            print(f"{'='*60}")

        # 更新 manifest 指纹（全量摄入也写，为后续增量做准备；--clear 时跳过）
        if not clear_existing:
            self._update_manifest(scan_dir, documents, unchanged_rels)

        return {
            "collections": stats,
            "total_chunks": total_stored,
            "elapsed": elapsed,
            "warnings": warnings,
            "skipped": skipped,
        }

    # ── 增量摄入 manifest ────────────────────

    def _manifest_path(self) -> Path:
        return config.bm25_index_dir / "ingest_manifest.json"

    def _load_manifest(self) -> dict:
        """读取文件指纹 manifest：{相对路径: [mtime, size]}"""
        try:
            return json.loads(self._manifest_path().read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_manifest(self, manifest: dict):
        self._manifest_path().parent.mkdir(parents=True, exist_ok=True)
        self._manifest_path().write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def _update_manifest(self, scan_dir: Path, processed: list[Document], unchanged_rels: set[str]):
        """合并 manifest：保留未变文件的旧指纹 + 写入本次处理文件的新指纹"""
        old = self._load_manifest()
        merged: dict = {}
        for rel in unchanged_rels:
            if rel in old:
                merged[rel] = old[rel]
        for doc in processed:
            rel = _relative_path(doc.metadata.get("source_file", ""), scan_dir)
            merged[rel] = _file_signature(doc.metadata)
        self._save_manifest(merged)

    def _group_by_collection(self, chunks: list[Chunk], genre: str) -> dict[str, list[Chunk]]:
        """将 chunks 按所属 collection 分组"""
        grouped: dict[str, list[Chunk]] = {}

        for chunk in chunks:
            source = chunk.metadata.get("source_file", "")
            # 优先按题材归类；未注册题材的 guess 返回 None → 走兜底
            col = guess_collection(Path(source), genre)

            # 尝试从 genre 映射取默认 collection
            if not col:
                genre_cols = get_collections_for_genre(genre)
                col = genre_cols[0] if genre_cols else f"{genre}_general"

            if col not in grouped:
                grouped[col] = []
            grouped[col].append(chunk)

        return grouped


# ── 查询管线 ──

class QueryPipeline:
    """
    端到端查询管线。

    流程:
      query → embed → hybrid search → (optional rerank) → (optional generate)
    """

    def __init__(self):
        # 先尝试加载已有 BM25 索引
        self.chroma = ChromaStore()
        self.bm25 = BM25Store()
        self.bm25.load()  # 加载所有已保存的索引

        self.embedder = Embedder()
        self._searcher: HybridSearcher | None = None
        self._reranker: Reranker | None = None
        self._generator: Generator | None = None

    @property
    def searcher(self) -> HybridSearcher:
        if self._searcher is None:
            self._searcher = HybridSearcher(
                chroma_store=self.chroma,
                bm25_store=self.bm25,
                embedder=self.embedder,
            )
        return self._searcher

    @property
    def reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = Reranker()
        return self._reranker

    @property
    def generator(self) -> Generator:
        if self._generator is None:
            self._generator = Generator()
        return self._generator

    def search(
        self,
        query: str,
        genre: str | None = None,
        collections: list[str] | None = None,
        top_k: int = 10,
        use_reranker: bool = False,
        verbose: bool = False,
    ) -> list[HybridSearchResult]:
        """
        混合检索。

        返回: 按 RRF 分数排序的检索结果列表
        """
        results = self.searcher.search(
            query=query,
            genre=genre,
            collections=collections,
            top_k=top_k if not use_reranker else top_k * 3,
            verbose=verbose,
        )

        if use_reranker and results:
            results = self.reranker.rerank(query, results, top_k=top_k, verbose=verbose)

        return results

    def generate(
        self,
        query: str,
        genre: str | None = None,
        collections: list[str] | None = None,
        top_k: int = 5,
        use_reranker: bool = False,
        system_prompt: str | None = None,
        stream: bool = True,
        verbose: bool = False,
    ) -> GenerationResult:
        """
        检索 + 生成：先检索相关资料，再喂给 LLM 生成回答。
        """
        # 检索
        results = self.search(
            query=query,
            genre=genre,
            collections=collections,
            top_k=top_k,
            use_reranker=use_reranker,
            verbose=verbose,
        )

        if not results:
            return GenerationResult(
                answer="当前知识库中未找到相关信息。",
                sources=[],
            )

        # 未显式指定 prompt 时，按题材加载（prompts/{genre}.txt → default.txt → 内置默认）
        if not system_prompt:
            system_prompt = load_system_prompt(genre)

        # 生成
        return self.generator.generate(
            query=query,
            search_results=results,
            system_prompt=system_prompt,
            max_chunks=top_k,
            stream=stream,
        )

    def info(self) -> dict:
        """返回当前索引状态"""
        chroma_stats = self.chroma.stats()
        bm25_cols = self.bm25.loaded_collections()
        return {
            "chroma_collections": chroma_stats,
            "bm25_loaded": bm25_cols,
            "total_chunks": sum(chroma_stats.values()),
        }


# ── 增量摄入辅助 ───────────────────────────────

def _relative_path(source_file: str, scan_dir: Path) -> str:
    """把绝对路径转成相对 scan_dir 的路径（用于 manifest key）"""
    try:
        p = Path(source_file)
        return p.relative_to(scan_dir).as_posix()
    except (ValueError, OSError):
        # 扫描目录外或异常路径：退回文件名
        return Path(source_file).name


def _file_signature(metadata: dict) -> list:
    """文件指纹：mtime + size（用于判断文件是否变化）"""
    return [round(float(metadata.get("mtime", 0)), 3), int(metadata.get("size_bytes", 0))]


