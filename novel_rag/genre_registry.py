"""
题材注册表 —— 从 YAML 配置加载题材 → collection 的映射规则。

取代原先硬编码在 config.py 里的 GENRE_COLLECTIONS / GENRE_PATHS / guess_collection。
设计目标：
  1. 默认配置 = 改造前的行为（xianxia 映射逐字保留），对现有管线零影响
  2. 别人接入自己的资料：在 _bible/ 下建目录 + 在 config/genres.yaml 里加一段即可，
     未注册的题材自动落入 {genre}_general 兜底 collection
  3. 配置文件首次运行时自动生成（带默认 xianxia 映射），用户可编辑

使用方式:
    from novel_rag.genre_registry import genre_registry
    genre_registry.get_collections("xianxia")   # -> ["xianxia_classics", ...]
    genre_registry.guess_collection(Path(".../01-道藏核心/xxx.txt"), "xianxia")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# 项目根目录（novel_rag 的上一级）；不 import config 以避免循环依赖
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── 默认配置（改造前行为的逐字快照）──────────────────

DEFAULT_GENRES_YAML = """\
# 题材注册表 —— 定义每个题材的目录、collection 及归类规则
#
# 结构说明:
#   path:                        _bible/ 下的子目录名（摄入时扫描这个目录）
#   default_collection:          未匹配任何规则时落入的 collection
#   processed_default_collection: processed/ 子目录内未匹配 file_keywords 时落入的 collection
#   collections:                 归类规则列表
#     dir_keywords:              路径包含任一关键词 → 该 collection（目录级，优先）
#     file_keywords:             路径含 "processed" 且文件名包含任一关键词 → 该 collection
#
# 接入自己的资料:
#   1. 在 _bible/ 下建题材目录（如 _bible/wuxia/），放入 raw 资料
#   2. 在本文件追加同名题材配置（可只写 path + default_collection，规则后续再细化）
#   3. 运行: python cli.py ingest --genre wuxia
#   未注册的题材也能摄入，全部资料落入 {genre}_general 兜底 collection。
genres:
  xianxia:
    path: xianxia
    default_collection: xianxia_classics
    processed_default_collection: xianxia_terminology
    collections:
      - name: xianxia_classics
        dir_keywords: ["01-道藏核心", "02-神话仙传", "04-儒释补充", "narrative"]
      - name: xianxia_cultivation
        dir_keywords: ["03-术数阵法"]
        file_keywords: ["修炼"]
      - name: xianxia_bestiary
        file_keywords: ["异兽"]
      - name: xianxia_artifacts
        file_keywords: ["法宝"]
      - name: xianxia_herbs
        file_keywords: ["灵草"]
      - name: xianxia_characters
        file_keywords: ["人物"]
      - name: xianxia_geography
        file_keywords: ["地理"]
      - name: xianxia_terminology
        file_keywords: ["术语"]
"""


# ── 数据结构 ─────────────────────────────────────

@dataclass
class CollectionRule:
    """一条归类规则：关键词命中 → 落入指定 collection"""

    name: str
    dir_keywords: list[str] = field(default_factory=list)
    file_keywords: list[str] = field(default_factory=list)


@dataclass
class GenreConfig:
    """一个题材的完整配置"""

    key: str
    path: str
    default_collection: str = ""
    processed_default_collection: str = ""
    collections: list[CollectionRule] = field(default_factory=list)

    @property
    def collection_names(self) -> list[str]:
        return [c.name for c in self.collections]


# ── 注册表 ───────────────────────────────────────

class GenreRegistry:
    """从 config/genres.yaml 加载题材注册表"""

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path or (PROJECT_ROOT / "config" / "genres.yaml"))
        self._genres: dict[str, GenreConfig] = {}
        self._ensure_default()
        self.reload()

    # ── 加载 ────────────────────────────────────

    def _ensure_default(self):
        """配置文件不存在时，用内置默认（= 改造前行为）生成"""
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(DEFAULT_GENRES_YAML, encoding="utf-8")
            print(f"[GenreRegistry] 已生成默认配置: {self.config_path}")

    def reload(self):
        """（重新）加载配置文件"""
        self._genres = {}
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"[GenreRegistry] 配置加载失败 ({self.config_path}): {e}，使用空注册表")
            data = {}

        for key, cfg in (data.get("genres") or {}).items():
            if not isinstance(cfg, dict):
                continue
            collections = []
            for col in cfg.get("collections") or []:
                if not isinstance(col, dict):
                    continue
                collections.append(
                    CollectionRule(
                        name=col.get("name", ""),
                        dir_keywords=list(col.get("dir_keywords") or []),
                        file_keywords=list(col.get("file_keywords") or []),
                    )
                )
            self._genres[key] = GenreConfig(
                key=key,
                path=cfg.get("path", key),
                default_collection=cfg.get("default_collection", ""),
                processed_default_collection=cfg.get("processed_default_collection", ""),
                collections=collections,
            )

    # ── 查询 ────────────────────────────────────

    def get(self, genre: str) -> GenreConfig | None:
        return self._genres.get(genre)

    def genre_keys(self) -> list[str]:
        return list(self._genres.keys())

    def get_collections(self, genre: str) -> list[str]:
        """题材 → 该题材下所有 collection 名（兼容旧 API 语义）"""
        cfg = self._genres.get(genre)
        return cfg.collection_names if cfg else []

    def get_path(self, genre: str) -> str | None:
        """题材 → _bible 下的子目录名"""
        cfg = self._genres.get(genre)
        return cfg.path if cfg else None

    def guess_collection(self, source_path: str | Path, genre: str | None = None) -> str | None:
        """
        根据文件路径猜测它应该属于哪个 collection。

        规则（与改造前行为一致）:
          1. 路径包含任一 collection 的 dir_keywords → 该 collection
          2. 路径含 "processed" → 用 file_keywords 匹配文件名 → 未匹配则 processed_default_collection
          3. 仍未匹配 → default_collection
        """
        path_str = str(source_path).replace("\\", "/")
        cfg = self._genres.get(genre) if genre else None

        # 显式指定了题材但未注册：直接返回 None，由调用方兜底（如 {genre}_general）
        if genre and cfg is None:
            return None

        # 遍历所有题材的规则（兼容 genre=None 的调用）
        candidates: list[GenreConfig] = [cfg] if cfg else list(self._genres.values())

        # 1. 目录级关键词（优先）
        for gc in candidates:
            for col in gc.collections:
                if any(k in path_str for k in col.dir_keywords):
                    return col.name

        # 2. processed 子目录：文件级关键词
        if "processed" in path_str:
            for gc in candidates:
                for col in gc.collections:
                    if any(k in path_str for k in col.file_keywords):
                        return col.name
            if cfg:
                return cfg.processed_default_collection or cfg.default_collection or None
            # 未指定 genre：取第一个配置了 processed 默认值的题材
            for gc in candidates:
                if gc.processed_default_collection:
                    return gc.processed_default_collection

        # 3. 兼容旧行为：narrative 目录
        if "narrative" in path_str:
            return "xianxia_classics"

        # 4. 兜底
        if cfg:
            return cfg.default_collection or None
        xianxia = self._genres.get("xianxia")
        if xianxia:
            return xianxia.default_collection or None
        return None


# 全局单例
genre_registry = GenreRegistry()
