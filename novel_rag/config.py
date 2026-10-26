"""
配置中心 —— 从 .env 加载所有配置，管理 collection 注册表。

使用方式:
    from novel_rag.config import config
    print(config.embedding_model)
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# 项目根目录（novel_rag 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 加载 .env
load_dotenv(PROJECT_ROOT / ".env")


def _path(env: str, default: str) -> Path:
    """读取路径配置：绝对路径原样使用，相对路径相对项目根目录。"""
    p = Path(os.getenv(env) or default)
    return p if p.is_absolute() else PROJECT_ROOT / p


@dataclass
class Config:
    """RAG 系统全局配置"""

    # ── API ──────────────────────────────────
    api_key: str = os.getenv("SILICONFLOW_API_KEY", "")
    base_url: str = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

    # ── 路径 ─────────────────────────────────
    project_root: Path = PROJECT_ROOT
    # 题材素材（RAG 输入），跨书共享
    bible_dir: Path = field(default_factory=lambda: _path("BIBLE_DIR", "_bible"))
    # 索引产物（可重建）
    chroma_persist_dir: Path = field(default_factory=lambda: _path("CHROMA_PERSIST_DIR", "chroma_db"))
    bm25_index_dir: Path = field(default_factory=lambda: _path("BM25_INDEX_DIR", "bm25_indexes"))

    # ── 当前活跃书：一本书 = 一个自包含目录 ──
    # BOOK_DIR 未配置时回落到 <仓库>/novels/<CURRENT_BOOK>/
    current_book: str = os.getenv("CURRENT_BOOK", "mybook")
    book_dir: Path = field(
        default_factory=lambda: _path("BOOK_DIR", f"novels/{os.getenv('CURRENT_BOOK', 'mybook')}")
    )

    # ── 分块参数 ─────────────────────────────
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "512"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "64"))

    # ── 检索参数 ─────────────────────────────
    retrieval_top_k: int = 10          # 每路召回数
    fusion_top_k: int = 5              # RRF 融合后返回数
    rrf_k: int = 60                    # RRF 平滑常数

    # ── LLM 生成/重排（默认回落 SiliconFlow，可整体换成其他 OpenAI 兼容服务）──
    llm_api_key: str = os.getenv("LLM_API_KEY", "")          # 为空则回落 api_key
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")        # 为空则回落 base_url
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V3")
    rerank_model: str = os.getenv("RERANK_MODEL", "deepseek-ai/DeepSeek-V3")

    # ── API 参数 ─────────────────────────────
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_delay: float = float(os.getenv("RETRY_DELAY", "1.0"))
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    embedding_batch_delay: float = float(os.getenv("EMBEDDING_BATCH_DELAY", "0"))  # 批间 sleep 秒（限流降速）

    # ── 429 限流专用重试（等 TPM 窗口恢复）────────
    rate_limit_max_retries: int = int(os.getenv("RATE_LIMIT_MAX_RETRIES", "10"))
    rate_limit_max_wait: float = float(os.getenv("RATE_LIMIT_MAX_WAIT", "60"))  # 单次最大等待秒

    # ── Embedding 维度（bge-m3 输出 1024 维；换模型时同步改 .env）──
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "1024"))

    @property
    def effective_llm_api_key(self) -> str:
        """LLM 专用 key，未配置时回落 embedding 用的 api_key"""
        return self.llm_api_key or self.api_key

    @property
    def effective_llm_base_url(self) -> str:
        """LLM 专用 base_url，未配置时回落 embedding 用的 base_url"""
        return self.llm_base_url or self.base_url

    # ── 书目录内的约定子目录 ─────────────────
    @property
    def book_world_dir(self) -> Path:
        """三大设定 + 角色/势力/物品等 YAML"""
        return self.book_dir / "world"

    @property
    def book_outline_dir(self) -> Path:
        """总大纲"""
        return self.book_dir / "outline"

    @property
    def book_volumes_dir(self) -> Path:
        """卷纲"""
        return self.book_dir / "volumes"

    @property
    def book_beats_dir(self) -> Path:
        """章级节拍设计"""
        return self.book_dir / "beats"

    @property
    def book_chapters_dir(self) -> Path:
        """正文"""
        return self.book_dir / "chapters"

    @property
    def book_reviews_dir(self) -> Path:
        """审稿报告"""
        return self.book_dir / "reviews"

    @property
    def book_memory_dir(self) -> Path:
        """会话日志 / 作者方向 / 连续性"""
        return self.book_dir / "memory"

    @property
    def book_state_file(self) -> Path:
        """状态快照"""
        return self.book_dir / "novel_state.yaml"


# 全局单例
config = Config()


# ── Collection 注册表（题材/领域 → ChromaDB collection） ──
# 已迁移到 config/genres.yaml（见 novel_rag/genre_registry.py）。
# 以下函数保持旧签名与旧行为，内部从注册表读取。
from novel_rag.genre_registry import genre_registry  # noqa: E402

def get_collections_for_genre(genre: str) -> list[str]:
    """获取指定题材下的所有 collection 名"""
    return genre_registry.get_collections(genre)


def get_all_collections() -> list[str]:
    """获取所有已注册的 collection 名"""
    result: list[str] = []
    for genre in genre_registry.genre_keys():
        result.extend(genre_registry.get_collections(genre))
    return result


# 题材 → _bible 下的子目录（兼容旧 import；值来自注册表）
GENRE_PATHS: dict[str, str] = {
    g: (genre_registry.get_path(g) or g) for g in genre_registry.genre_keys()
}


def guess_collection(source_path: Path, genre: str | None = None) -> str | None:
    """
    根据文件路径猜测它应该属于哪个 collection。
    规则由 config/genres.yaml 定义（默认值 = 改造前行为）。
    例如: _bible/xianxia/raw/02-神话仙传/xxx.md → xianxia_classics
    """
    return genre_registry.guess_collection(source_path, genre)
