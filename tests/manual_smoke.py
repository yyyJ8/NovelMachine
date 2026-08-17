"""回归验证脚本（不依赖 pytest，网络受限环境可用）"""
import sys, tempfile, traceback
from pathlib import Path

# 项目根目录（tests/ 的上一级）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novel_rag.config import config, guess_collection, get_collections_for_genre
from novel_rag.ingestion.chunker import ChunkStrategy
from novel_rag.pipeline import IngestionPipeline, QueryPipeline
from novel_rag.storage.bm25_index import BM25Store

PASS = 0
FAIL = 0

def check(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  OK  {name}")
    except Exception as e:
        FAIL += 1
        print(f"  FAIL {name}: {e}")
        traceback.print_exc()

# ── 1. 归类规则 ──
def t_guess():
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
        ("_bible/xianxia/processed/杂项.md", "xianxia_terminology"),
        ("_bible/xianxia/raw/其他目录/无名.txt", "xianxia_classics"),
    ]
    for path, expected in cases:
        got = guess_collection(Path(path))
        assert got == expected, f"{path} -> {got} != {expected}"

def t_registry():
    cols = get_collections_for_genre("xianxia")
    assert "xianxia_classics" in cols and len(cols) >= 8
    assert get_collections_for_genre("wuxia") == []

# ── 2. 摄入 → 检索 端到端 ──
def make_fake_embedder():
    class Fake:
        def __init__(self):
            self.dim = config.embedding_dim
        def embed_texts(self, texts, batch_size=None, batch_delay=None):
            return [[0.1] * self.dim for _ in texts]
        def embed_query(self, text):
            return [0.1] * self.dim
    return Fake()

def t_ingest_search():
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp())
    old = (config.chroma_persist_dir, config.bm25_index_dir, config.bible_dir)
    try:
        config.chroma_persist_dir = tmp / "chroma_db"
        config.bm25_index_dir = tmp / "bm25_indexes"
        config.bible_dir = tmp / "bible"
        (config.bible_dir / "xianxia" / "raw" / "01-道藏核心").mkdir(parents=True)
        (config.bible_dir / "xianxia" / "raw" / "03-术数阵法").mkdir(parents=True)
        (config.bible_dir / "xianxia" / "raw" / "01-道藏核心" / "道德经-春秋-老子.txt").write_text(
            "道可道，非常道。名可名，非常名。无名天地之始，有名万物之母。"
            "故常无欲以观其妙，常有欲以观其徼。此两者同出而异名，同谓之玄。"
            "玄之又玄，众妙之门。天下皆知美之为美，斯恶已；皆知善之为善，斯不善已。"
            "故有无相生，难易相成，长短相形，高下相倾，音声相和，前后相随。",
            encoding="utf-8")
        (config.bible_dir / "xianxia" / "raw" / "03-术数阵法" / "周易-周-佚名.txt").write_text(
            "天行健，君子以自强不息。地势坤，君子以厚德载物。"
            "易有太极，是生两仪。两仪生四象，四象生八卦。"
            "八卦定吉凶，吉凶生大业。是故法象莫大乎天地，变通莫大乎四时。",
            encoding="utf-8")

        ingest = IngestionPipeline()
        ingest.embedder = make_fake_embedder()
        result = ingest.run(genre="xianxia", strategy=ChunkStrategy.CLASSICAL, verbose=False)
        assert result["total_chunks"] > 0, "total_chunks == 0"
        assert "xianxia_classics" in result["collections"]
        assert "xianxia_cultivation" in result["collections"]

        q = QueryPipeline()
        q.embedder = make_fake_embedder()
        q._searcher = None
        results = q.search("道可道", genre="xianxia", top_k=5)
        assert len(results) > 0, "search returned 0"
        assert all(r.text for r in results)

        # 增量摄入：第二次运行应跳过全部
        r2 = ingest.run(genre="xianxia", strategy=ChunkStrategy.CLASSICAL, verbose=False, incremental=True)
        assert r2["skipped"] >= 2, f"incremental skipped={r2['skipped']} (期望 >=2)"
        # 新增文件应被处理
        (config.bible_dir / "xianxia" / "raw" / "01-道藏核心" / "新增-现代-佚名.txt").write_text(
            "新增的测试资料内容，用于验证增量摄入。这一段文字是专门凑足最小分块长度的，"
            "确保它超过五十个字符的过滤阈值，从而能够被成功摄入到知识库的索引当中。",
            encoding="utf-8")
        r3 = ingest.run(genre="xianxia", strategy=ChunkStrategy.CLASSICAL, verbose=False, incremental=True)
        assert r3["skipped"] >= 2 and r3["total_chunks"] > 0, f"incremental add failed: {r3}"

        # BM25 持久化
        store = BM25Store()
        store.load()
        assert "xianxia_classics" in store.loaded_collections()
        bm25_hits = store.search("xianxia_classics", "道可道", top_k=3)
        assert len(bm25_hits) > 0  # 分数可为负（小语料下 BM25 idf 为负属正常）
    finally:
        config.chroma_persist_dir, config.bm25_index_dir, config.bible_dir = old
        shutil.rmtree(tmp, ignore_errors=True)

# ── 3. 未注册题材兜底 ──
def t_unregistered_fallback():
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp())
    old = (config.chroma_persist_dir, config.bm25_index_dir, config.bible_dir)
    try:
        config.chroma_persist_dir = tmp / "chroma_db"
        config.bm25_index_dir = tmp / "bm25_indexes"
        config.bible_dir = tmp / "bible"
        (config.bible_dir / "wuxia" / "raw").mkdir(parents=True)
        (config.bible_dir / "wuxia" / "raw" / "资料.txt").write_text(
            "江湖路远，快意恩仇。剑气纵横三万里，一剑光寒十九洲。"
            "这一篇武侠资料用于验证未注册题材的兜底逻辑，文字长度超过最小分块阈值，"
            "确保它能被正常摄入并落入题材兜底的通用集合当中。",
            encoding="utf-8")
        ingest = IngestionPipeline()
        ingest.embedder = make_fake_embedder()
        result = ingest.run(genre="wuxia", strategy=ChunkStrategy.FIXED, verbose=False)
        assert result["collections"].get("wuxia_general", 0) > 0, f"fallback failed: {result['collections']}"
    finally:
        config.chroma_persist_dir, config.bm25_index_dir, config.bible_dir = old
        shutil.rmtree(tmp, ignore_errors=True)

# ── 4. prompt 按题材加载 ──
def t_prompt_loading():
    from novel_rag.generation.generator import load_system_prompt
    x = load_system_prompt("xianxia")
    d = load_system_prompt("wuxia")  # 无 wuxia.txt → default.txt
    assert "仙侠" in x, "xianxia prompt should mention 仙侠"
    assert "仙侠" not in d, "default prompt should be generic"
    assert load_system_prompt() == d

print("=== 回归验证 ===")
check("guess_collection 规则与改造前一致", t_guess)
check("题材注册表", t_registry)
check("摄入→检索→增量→BM25 端到端", t_ingest_search)
check("未注册题材兜底 wuxia_general", t_unregistered_fallback)
check("prompt 按题材加载", t_prompt_loading)
print(f"\n结果: {PASS} 通过, {FAIL} 失败")
sys.exit(1 if FAIL else 0)
