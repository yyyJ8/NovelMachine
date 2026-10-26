"""
文本分割策略 —— 支持固定大小、Markdown 感知、句子感知、古典文本感知四种模式。

默认使用 classical 策略：
  1. 先按古典文本结构标记（卷/篇/章/◎/○）分大段
  2. 大段内部按段落 (\\n\\n) 分中段
  3. 中段内部按句标点 (。！？) 分小段
  4. 小段仍超长则递归拆分
  5. 过短的碎片（< min_chunk_size）过滤

每个 chunk 保留完整元数据链，方便溯源。

使用方式:
    from novel_rag.ingestion.chunker import chunk_documents, ChunkStrategy
    chunks = chunk_documents(docs, strategy=ChunkStrategy.CLASSICAL)
"""

from __future__ import annotations

import re
from enum import Enum
from dataclasses import dataclass, field
from langchain_text_splitters import RecursiveCharacterTextSplitter

from novel_rag.config import config
from novel_rag.ingestion.loader import Document


@dataclass
class Chunk:
    """一个文本片段 + 完整元数据"""
    text: str
    metadata: dict = field(default_factory=dict)


class ChunkStrategy(str, Enum):
    FIXED = "fixed"           # 固定大小 + 重叠（通用回退）
    MARKDOWN = "markdown"     # 按 #/##/### 标题切（.md 文件）
    SENTENCE = "sentence"     # 按句子边界切（叙事文本）
    CLASSICAL = "classical"   # 古典文本结构感知（文言文最优）


# ── 古典文本结构标记 ────────────────────────────
# 层级 1: 卷/篇/章/回 — e.g. 卷一、卷第五、卷之五、第一篇、第三章
_RE_VOLUME = re.compile(
    r"(?:^|\n)[　\s]*"
    r"(?:第[一二三四五六七八九十百千\d]+)?"
    r"[卷篇章节回]"
    r"(?:[　\s]*[第之])?"
    r"(?:[一二三四五六七八九十百千\d]+)?"
    r"[　\s]*[：:\n]?",
    re.MULTILINE,
)

# 层级 1: ◎ ○ ● 节标记 — e.g. ◎释《三十九章经》、 ○口为章第三
_RE_SECTION_MARKER = re.compile(
    r"(?:^|\n)[　\s]*[◎○●◇◆][　\s]*[^\n]{0,40}[：:\n]?",
    re.MULTILINE,
)

# 层级 2: 编号标题 — e.g. 一、 / 1. / （一） / 甲、
_RE_NUMBERED_HEADING = re.compile(
    r"(?:^|\n)[　\s]*"
    r"(?:[（(]?[一二三四五六七八九十\d]+[）).、]"
    r"|[（(][甲乙丙丁戊己庚辛壬癸][）)])"
    r"[　\s]*[^\n]{0,40}[：:\n]?",
    re.MULTILINE,
)

# 层级 2: 分隔线 — e.g. ──── / === / ***
_RE_RULE_LINE = re.compile(
    r"(?:^|\n)[　\s]*[-─=*]{3,}[　\s]*(?:\n|$)",
    re.MULTILINE,
)

# 综合结构切分模式（合并以上四种，任意命中即为分界）
_STRUCTURAL_BOUNDARY_PATTERN = re.compile(
    r"("
    + _RE_VOLUME.pattern + r"|"
    + _RE_SECTION_MARKER.pattern + r"|"
    + _RE_NUMBERED_HEADING.pattern + r"|"
    + _RE_RULE_LINE.pattern
    + r")",
    re.MULTILINE,
)


def chunk_document(
    doc: Document,
    strategy: ChunkStrategy = ChunkStrategy.CLASSICAL,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    min_chunk_size: int = 50,
) -> list[Chunk]:
    """
    将单个 Document 切分成若干 Chunk。

    参数:
        doc: 文档对象
        strategy: 分块策略（默认 classical）
        chunk_size: 最大块大小（None = 用 config.chunk_size）
        chunk_overlap: 块间重叠（None = 用 config.chunk_overlap）
        min_chunk_size: 最小块大小，低于此值的碎片被丢弃
    """
    chunk_size = chunk_size or config.chunk_size
    chunk_overlap = chunk_overlap or config.chunk_overlap

    if strategy == ChunkStrategy.CLASSICAL:
        texts = _chunk_classical(doc.content, chunk_size, chunk_overlap, min_chunk_size)
    elif strategy == ChunkStrategy.MARKDOWN:
        texts = _chunk_markdown(doc.content, chunk_size, chunk_overlap)
    elif strategy == ChunkStrategy.SENTENCE:
        texts = _chunk_sentence(doc.content, chunk_size, chunk_overlap)
    else:
        texts = _chunk_fixed(doc.content, chunk_size, chunk_overlap)

    # 过滤碎块
    if min_chunk_size > 0:
        texts = [t for t in texts if len(t.strip()) >= min_chunk_size]

    # 构建 Chunk 对象，带完整溯源
    chunks: list[Chunk] = []
    char_cursor = 0

    for i, text in enumerate(texts):
        start = doc.content.find(text, char_cursor) if char_cursor < len(doc.content) else char_cursor
        if start == -1:
            start = char_cursor
        end = start + len(text)

        chunk_meta = {
            **doc.metadata,
            "chunk_index": i,
            "chunk_count": len(texts),
            "char_start": start,
            "char_end": end,
            "chunk_strategy": strategy.value,
        }
        chunks.append(Chunk(text=text.strip(), metadata=chunk_meta))
        char_cursor = end

    return chunks


def chunk_documents(
    docs: list[Document],
    strategy: ChunkStrategy = ChunkStrategy.CLASSICAL,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    min_chunk_size: int = 50,
) -> list[Chunk]:
    """批量切分多个文档"""
    all_chunks: list[Chunk] = []
    for doc in docs:
        all_chunks.extend(chunk_document(doc, strategy, chunk_size, chunk_overlap, min_chunk_size))
    return all_chunks


# ═══════════════════════════════════════════════════
# CLASSICAL 策略 —— 古典文本结构感知
# ═══════════════════════════════════════════════════

def _chunk_classical(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    min_chunk_size: int,
) -> list[str]:
    """
    古典文本专用切分。

    层级:
      1. 在结构标记处切成"篇"
      2. 篇太长 → 按 \\n\\n 切成"段"
      3. 段太长 → 按句标点切成"句组"
      4. 句组仍超长 → recursive split 兜底
    """
    # ── 第 1 层：结构标记切分 ─────────────────
    sections = _split_by_structural_boundaries(text)

    result: list[str] = []

    for section in sections:
        if not section.strip():
            continue

        if len(section) <= chunk_size:
            result.append(section)
            continue

        # ── 第 2 层：段落切分 ─────────────────
        paragraphs = _split_paragraphs(section)

        for para in paragraphs:
            if not para.strip():
                continue

            if len(para) <= chunk_size:
                if len(para.strip()) >= min_chunk_size:
                    result.append(para)
                continue

            # ── 第 3 层：句子切分 ──────────────
            sentences = _split_sentences_classical(para)

            current = ""
            for sent in sentences:
                if not sent.strip():
                    continue

                if len(current) + len(sent) <= chunk_size:
                    current += sent
                else:
                    if current.strip() and len(current.strip()) >= min_chunk_size:
                        result.append(current)
                    # 单句超长 → 递归兜底
                    if len(sent) > chunk_size:
                        subs = _chunk_fixed(sent, chunk_size, chunk_overlap)
                        result.extend(s for s in subs if len(s.strip()) >= min_chunk_size)
                        current = ""
                    else:
                        # 新块开始，带 overlap
                        if chunk_overlap > 0 and result:
                            prev = result[-1]
                            overlap_text = prev[-chunk_overlap:] if len(prev) > chunk_overlap else prev
                            current = overlap_text + sent
                        else:
                            current = sent

            if current.strip() and len(current.strip()) >= min_chunk_size:
                result.append(current)

    return result


def _split_by_structural_boundaries(text: str) -> list[str]:
    """
    在古典文本的结构标记处切分。

    识别: 卷/篇/章/回标记、◎○节标记、编号标题、分隔线
    """
    matches = list(_STRUCTURAL_BOUNDARY_PATTERN.finditer(text))

    if not matches:
        return [text]

    sections: list[str] = []
    last_end = 0

    for m in matches:
        # 保留分界标记之前的内容
        before = text[last_end : m.start()]
        if before.strip():
            sections.append(before)

        last_end = m.start()  # 分界标记归入下一段

    # 最后一段
    remaining = text[last_end:]
    if remaining.strip():
        sections.append(remaining)

    return sections if sections else [text]


def _split_paragraphs(text: str) -> list[str]:
    """按双换行 (paragraph break) 切分"""
    # 先按 \n\n 拆
    raw = re.split(r"\n\s*\n", text)
    return [p for p in raw if p.strip()]


def _split_sentences_classical(text: str) -> list[str]:
    """
    古典文本句子切分。

    文言文标点: 。！？；：、
    白话文标点: .!?;
    都支持。
    """
    # 在句末标点后切分（保留标点在句尾）
    pattern = re.compile(
        r"([^。！？\.!\?\n；;]+[。！？\.!\?\n；;]?)"
    )
    matches = pattern.findall(text)
    if not matches:
        return [text]
    return [m for m in matches if m.strip()]


# ═══════════════════════════════════════════════════
# 其他三种策略（保留，供特殊场景使用）
# ═══════════════════════════════════════════════════

def _chunk_fixed(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """固定大小切分，中文友好分隔符优先"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", ".", "!", "?", ";", ",", " ", ""],
        length_function=len,
    )
    return splitter.split_text(text)


def _chunk_markdown(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Markdown 感知切分：先按 #/##/### 标题切，太长的段落再细切。

    对没有 markdown 标题的文本自动降级为 fixed。
    """
    # 快速检测：文本是否包含 markdown 标题
    if not re.search(r"^#{1,4}\s", text, re.MULTILINE):
        # 没有 markdown 标题，直接走 fixed
        return _chunk_fixed(text, chunk_size, chunk_overlap)

    try:
        from langchain_text_splitters import MarkdownHeaderTextSplitter
        splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[
                ("#", "h1"),
                ("##", "h2"),
                ("###", "h3"),
                ("####", "h4"),
            ],
            strip_headers=False,
        )
        md_splits = splitter.split_text(text)
        sections = [s.page_content for s in md_splits]
    except Exception:
        sections = [text]

    # 对每个段落，超出 chunk_size 的再细切
    result: list[str] = []
    fine_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
        length_function=len,
    )

    for section in sections:
        if len(section) <= chunk_size:
            if section.strip():
                result.append(section.strip())
        else:
            subs = fine_splitter.split_text(section)
            result.extend(s.strip() for s in subs if s.strip())

    return result


def _chunk_sentence(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """句子感知切分：优先在标点处断开"""
    sentences = _split_sentences_classical(text)

    chunks: list[str] = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) <= chunk_size:
            current += sent
        else:
            if current.strip():
                chunks.append(current.strip())
            if len(sent) > chunk_size:
                sub = _chunk_fixed(sent, chunk_size, chunk_overlap)
                chunks.extend(sub)
                current = ""
            else:
                if chunk_overlap > 0 and chunks:
                    prev = chunks[-1]
                    overlap_text = prev[-chunk_overlap:] if len(prev) > chunk_overlap else prev
                    current = overlap_text + sent
                else:
                    current = sent

    if current.strip():
        chunks.append(current.strip())

    return chunks
