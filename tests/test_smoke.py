"""
Smoke test —— 验证 RAG 管线最小闭环（不调用真实 API）。

覆盖:
  1. 题材注册表 / guess_collection 归类规则（配置驱动）
  2. 摄入 → 检索 端到端闭环
  3. 未注册题材的 {genre}_general 兜底
  4. BM25 索引持久化/恢复
"""

from __future__ import annotations

from pathlib import Path

from novel_rag.config import guess_collection, get_collections_for_genre
from novel_rag.ingestion.chunker import ChunkStrategy
from novel_rag.pipeline import IngestionPipeline, QueryPipeline
from novel_rag.storage.bm25_index import BM25Store

# ── 1. 归类规则 ───────────────────────────────


def test_guess_collection_rules():
    """guess_collection 的默认规则与改造前行为一致"""
    cases = [
        ("_bible/xianxia/raw/01-道藏核心/道德經.txt", "xianxia_classics"),
        ("_bible/xianxia/raw/02-神话仙传/搜神记-晋-干宝.txt", "xianxia_classics"),
        ("_bible/xianxia/raw/03-术数阵法/周易.txt", "xianxia_cultivation"),
        ("_bible/xianxia/raw/04-儒释补充/論語.txt", "xianxia_classics"),
        ("_bible/xianxia/processed/异兽录.md", "xianxia_bestiary"),
        ("_bible/xianxia/processed/法宝谱.md", "xianxia_artifacts"),
        ("_bible/xianxia/processed/灵草集.md", "xianxia_herbs"),
        ("_bible/xianxia/processed/人物谱.md", "xianxia_characters"),
        ("_bible/xianxia/processed/术语辞典.md", "xianxia_terminology"),
        ("_bible/xianxia/processed/地理志.md", "xianxia_geography"),
        ("_bible/xianxia/processed/杂项.md", "xianxia_terminology"),  # processed 兜底
        ("_bible/xianxia/raw/其他目录/无名.txt", "xianxia_classics"),  # 默认兜底
    ]
    for path, expected in cases:
        assert guess_collection(Path(path)) == expected, f"{path} -> {expected}"


def test_registry_collections():
    """注册表返回的 xianxia collection 列表与改造前一致"""
    cols = get_collections_for_genre("xianxia")
    assert "xianxia_classics" in cols
    assert "xianxia_cultivation" in cols
    assert len(cols) >= 8
    # 未注册题材 → 空列表（由 pipeline 兜底到 {genre}_general）
    assert get_collections_for_genre("wuxia") == []


# ── 2. 摄入 → 检索 端到端 ─────────────────────


def _write_sample_bible(bible_dir: Path):
    """写入两个样例典籍文件"""
    (bible_dir / "xianxia" / "raw" / "01-道藏核心" / "道德经-春秋-老子.txt").write_text(
        "道可道，非常道。名可名，非常名。无名天地之始，有名万物之母。\n"
        "故常无欲以观其妙，常有欲以观其徼。此两者同出而异名，同谓之玄。",
        encoding="utf-8",
    )
    (bible_dir / "xianxia" / "raw" / "03-术数阵法" / "周易-周-佚名.txt").write_text(
        "天行健，君子以自强不息。地势坤，君子以厚德载物。\n"
        "易有太极，是生两仪。两仪生四象，四象生八卦。八卦定吉凶，吉凶生大业。"
        "是故易有太极，太极生两仪，两仪生四象，四象生八卦。天地定位，山泽通气。",
        encoding="utf-8",
    )


def test_ingest_and_search(isolated_paths, fake_embedder):
    """摄入两个文件后，检索能返回结果"""
    _write_sample_bible(isolated_paths.bible_dir)

    ingest = IngestionPipeline()
    ingest.embedder = fake_embedder  # 替换真实 embedder
    result = ingest.run(
        genre="xianxia",
        strategy=ChunkStrategy.CLASSICAL,
        verbose=False,
    )
    assert result["total_chunks"] > 0
    # 两个文件按目录规则落入不同 collection
    assert "xianxia_classics" in result["collections"]
    assert "xianxia_cultivation" in result["collections"]

    # 查询管线（同样替换 embedder）
    query = QueryPipeline()
    query.embedder = fake_embedder
    query._searcher = None  # 强制重建 searcher（复用新 embedder）

    results = query.search("道可道非常道", genre="xianxia", top_k=5)
    assert len(results) > 0
    assert all(r.text for r in results)


def test_unregistered_genre_fallback(isolated_paths, fake_embedder):
    """未注册题材 → 全部落入 {genre}_general 兜底 collection"""
    (isolated_paths.bible_dir / "wuxia" / "raw").mkdir(parents=True)
    (isolated_paths.bible_dir / "wuxia" / "raw" / "某武侠资料.txt").write_text(
        "江湖路远，快意恩仇。剑气纵横三万里，一剑光寒十九洲。\n"
        "少年仗剑走天涯，快马加鞭未下鞍。行侠仗义平生志，不负男儿七尺躯。"
        "刀光剑影处，自有英雄泪。恩怨情仇里，方见赤子心。",
        encoding="utf-8",
    )

    ingest = IngestionPipeline()
    ingest.embedder = fake_embedder
    result = ingest.run(genre="wuxia", strategy=ChunkStrategy.FIXED, verbose=False)
    assert result["collections"].get("wuxia_general", 0) > 0


# ── 3. BM25 持久化 ────────────────────────────


def test_bm25_save_load(isolated_paths, fake_embedder):
    """BM25 索引可保存并恢复"""
    _write_sample_bible(isolated_paths.bible_dir)

    ingest = IngestionPipeline()
    ingest.embedder = fake_embedder
    ingest.run(genre="xianxia", strategy=ChunkStrategy.CLASSICAL, verbose=False)

    store = BM25Store()
    store.load()
    assert "xianxia_classics" in store.loaded_collections()

    results = store.search("xianxia_classics", "道可道", top_k=3)
    assert len(results) > 0  # 分数可为负（小语料下 BM25 idf 为负属正常）
