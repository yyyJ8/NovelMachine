"""
文档加载器 —— Markdown / TXT / PDF，输出统一的 Document 结构。

支持的格式:
  - .md / .markdown / .txt  →  纯文本（自动检测 UTF-8 / GBK / GB2312 编码）
  - .pdf                     →  pdfplumber → PyPDF2 双重回退

文本清洗:
  - 全角缩进 → 半角空格
  - 连续空行压缩
  - ■□ 保留（古典文本中标记缺字，有语义含义）

元数据提取:
  - 从文件名解析 书名/朝代/作者（格式: 书名-朝代-作者.txt）
  - 记录 mtime，支持增量摄入
  - 记录编码、清洗标记

使用方式:
    from novel_rag.ingestion.loader import load_file, load_directory
    docs = load_directory("_bible/xianxia/raw", sort=True)

Python ≥ 3.9
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Document:
    """统一的文档表示"""
    content: str
    metadata: dict = field(default_factory=dict)


# ── 公开 API ──

def load_file(filepath: str | Path) -> Document:
    """
    加载单个文件，自动识别格式、编码，清洗文本并提取元数据。

    支持: .md, .txt, .pdf
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"文件不存在: {filepath}")

    ext = filepath.suffix.lower()

    # ── 加载内容 + 编码 ──────────────────────
    if ext == ".pdf":
        content, detected_encoding = _load_pdf(filepath), "n/a"
    else:
        content, detected_encoding = _load_text_with_encoding(filepath)

    # ── 清洗 ────────────────────────────────
    cleaned, clean_flags = _clean_text(content)

    # ── 元数据 ──────────────────────────────
    meta = _build_metadata(filepath, ext, detected_encoding, clean_flags, len(cleaned))
    return Document(content=cleaned, metadata=meta)


def load_directory(
    dirpath: str | Path,
    recursive: bool = True,
    file_types: tuple[str, ...] = (".md", ".txt", ".pdf"),
    sort: bool = True,
) -> list[Document]:
    """
    遍历目录，加载所有匹配的文档文件。

    参数:
        dirpath: 根目录
        recursive: 是否递归子目录
        file_types: 要加载的文件扩展名
        sort: 是否按文件名排序（保证摄入顺序确定）
    """
    dirpath = Path(dirpath)
    if not dirpath.is_dir():
        raise NotADirectoryError(f"目录不存在: {dirpath}")

    # 收集文件路径
    filepaths: list[Path] = []
    if recursive:
        for root, _, files in os.walk(dirpath):
            for fname in files:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in file_types:
                    filepaths.append(fpath)
    else:
        for fpath in dirpath.iterdir():
            if fpath.is_file() and fpath.suffix.lower() in file_types:
                filepaths.append(fpath)

    # 确定性排序
    if sort:
        filepaths.sort(key=lambda p: str(p))

    documents: list[Document] = []
    for fpath in filepaths:
        try:
            doc = load_file(fpath)
            documents.append(doc)
        except Exception as e:
            print(f"[WARN] 跳过 {fpath.name}: {e}")

    return documents


# ── 编码检测 + 文本加载 ──

_ENCODINGS_TO_TRY = ("utf-8", "gbk", "gb2312", "gb18030", "big5", "latin-1")


def _load_text_with_encoding(filepath: Path) -> tuple[str, str]:
    """加载纯文本，返回 (content, encoding_used)"""
    for enc in _ENCODINGS_TO_TRY:
        try:
            content = filepath.read_text(encoding=enc)
            # 验证：如果解码成功但有大量替换字符 (U+FFFD)，不算成功
            if "�" in content:
                replacement_count = content.count("�")
                if replacement_count > len(content) * 0.01:  # >1% 替换
                    continue
            return content, enc
        except (UnicodeDecodeError, UnicodeError):
            continue

    # 最终回退：用 utf-8 + replace 错误处理
    content = filepath.read_text(encoding="utf-8", errors="replace")
    return content, "utf-8(replace)"


# ── 文本清洗 ──

def _clean_text(text: str) -> tuple[str, list[str]]:
    """
    清洗古典中文文本的常见问题。

    返回: (cleaned_text, flags)
    flags 记录执行了哪些清洗操作。
    """
    flags: list[str] = []

    # 1. 全角缩进 　 → 空字符串（中文排版缩进常见）
    if "　" in text:
        text = text.replace("　", "")
        flags.append("fullwidth_indent_removed")

    # 2. 连续 3+ 空行 → 最多保留 1 个空行
    if "\n\n\n" in text:
        text = re.sub(r"\n{3,}", "\n\n", text)
        flags.append("blank_lines_collapsed")

    # 3. 行首行尾空白去重
    #    保留单行内容，但去掉每行首尾多余空格（保留中间的）
    lines = text.split("\n")
    stripped_lines = [l.strip() for l in lines]
    if stripped_lines != lines:
        text = "\n".join(stripped_lines)
        flags.append("line_stripped")

    # 4. 检测 ■□ 缺字标记（不删除，但标记）
    if "■" in text or "□" in text:
        flags.append("has_missing_char_markers")

    return text, flags


# ── 元数据构建 ──

def _build_metadata(
    filepath: Path,
    ext: str,
    encoding: str,
    clean_flags: list[str],
    char_count: int,
) -> dict:
    """构建完整的文档元数据"""

    # 文件级
    stat = filepath.stat()
    meta = {
        "source_file": str(filepath),
        "filename": filepath.name,
        "stem": filepath.stem,
        "suffix": ext,
        "char_count": char_count,
        "mtime": stat.st_mtime,
        "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
        "size_bytes": stat.st_size,
        "encoding": encoding,
        "clean_flags": ",".join(clean_flags) if clean_flags else "none",
    }

    # 从文件名解析结构化信息
    file_meta = parse_filename(filepath.stem)
    meta.update(file_meta)

    return meta


def parse_filename(stem: str) -> dict:
    """
    从文件名解析 书名/朝代/作者。

    支持的格式:
      - 书名-朝代-作者   → 抱朴子内篇-晋-葛洪
      - 书名-作者-朝代   → (不常见，但尝试兼容)
      - 书名             → 道德經
      - 书名-作者         → 莊子-莊周

    返回: {"title": ..., "dynasty": ..., "author": ...}
    """
    parts = [p.strip() for p in stem.split("-") if p.strip()]

    result = {"title": "", "dynasty": "", "author": ""}

    if not parts:
        return result

    # ── 1. 确定书名 ──────────────────────
    # 第一个部分始终是书名
    result["title"] = parts[0]

    if len(parts) == 1:
        return result

    # ── 2. 确定朝代和作者（启发式）─────────
    # 常见的朝代/年代关键词
    DYNASTY_KEYWORDS = {
        "先秦", "春秋", "战国", "秦", "汉", "西汉", "东汉",
        "三国", "魏", "蜀", "吴", "晋", "西晋", "东晋",
        "南北朝", "北魏", "南朝", "北朝", "宋", "齐", "梁", "陈",
        "隋", "唐", "五代", "宋", "北宋", "南宋",
        "辽", "金", "元", "明", "清", "民国", "现代"
    }

    candidate_author = parts[-1]  # 默认最后一个字段是作者

    # 如果倒数第二个字段像朝代，确认它
    if len(parts) >= 3:
        middle = parts[-2]
        if middle in DYNASTY_KEYWORDS or any(d in middle for d in DYNASTY_KEYWORDS):
            result["dynasty"] = middle
            result["author"] = parts[-1]
        elif parts[-1] in DYNASTY_KEYWORDS or any(d in parts[-1] for d in DYNASTY_KEYWORDS):
            # 格式: 书名-作者-朝代
            result["dynasty"] = parts[-1]
            result["author"] = parts[-2]
        else:
            # 无法判断，最后一个当作作者
            result["author"] = candidate_author

    elif len(parts) == 2:
        # 两个字段：可能是 书名-作者 或 书名-朝代
        if parts[1] in DYNASTY_KEYWORDS or any(d in parts[1] for d in DYNASTY_KEYWORDS):
            result["dynasty"] = parts[1]
        else:
            result["author"] = parts[1]

    return result


# ── PDF 加载 ──

def _load_pdf(filepath: Path) -> str:
    """
    从 PDF 提取文本。

    策略: pdfplumber（中文更优）→ PyPDF2（轻量回退）→ 报错
    """

    # 策略 1: pdfplumber（推荐）
    try:
        import pdfplumber
        pages: list[str] = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    # pdfplumber 默认保留排版空格，适度清理
                    text = re.sub(r" {2,}", " ", text)  # 压缩多空格
                    pages.append(text)
        if pages:
            return "\n\n".join(pages)
    except ImportError:
        pass  # 回退到 PyPDF2
    except Exception as e:
        print(f"[PDF] pdfplumber 提取失败 ({e})，回退到 PyPDF2...")

    # 策略 2: PyPDF2（回退）
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(filepath))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        if pages:
            return "\n\n".join(pages)
    except ImportError:
        raise ImportError(
            "PDF 加载需要 pdfplumber 或 PyPDF2。\n"
            "  推荐: pip install pdfplumber    (中文支持更好)\n"
            "  回退: pip install PyPDF2"
        )
    except Exception as e:
        raise RuntimeError(f"PDF 提取完全失败: {e}")

    raise RuntimeError(f"PDF 无可提取文本（可能是扫描件/图片PDF）: {filepath.name}")


# ── 辅助 ──

def estimate_content_type(text: str) -> str:
    """
    启发式判断文本类型。

    返回: "classical_chinese" | "modern_chinese" | "mixed" | "unknown"
    """
    if not text.strip():
        return "unknown"

    sample = text[:1000]

    # 文言文特征：单字词多、"之乎者也"频率高
    classical_markers = set("之乎者也矣焉哉曰吾汝其乃")
    classical_count = sum(1 for c in sample if c in classical_markers)

    # 现代汉语特征：多字词、"的了吗呢"频率高
    modern_markers = set("的了吗呢吧们着过到在")
    modern_count = sum(1 for c in sample if c in modern_markers)

    if classical_count > modern_count * 2:
        return "classical_chinese"
    elif modern_count > classical_count * 2:
        return "modern_chinese"
    elif classical_count > 0 or modern_count > 0:
        return "mixed"
    return "unknown"
