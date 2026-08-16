"""文本分块：先按行识别章节标记并跟踪当前章节，段落按 \n\n 切分，超长段落定长滑动窗口。"""

import re
from dataclasses import dataclass, field
from hashlib import md5
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.rag.loader import Document

# markdown 标题（康德/尼采 md 书的 `## 导言` 等）；标签需剥掉尾部链接噪音
_MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_TRAILING_LINK = re.compile(r"\[\[[^\]]*\]\]\([^)]*\)\s*$")
# txt 独立章节标记行：道德经译文「第一章」、论语「学而第一」
_TXT_CHAPTER = re.compile(
    r"^(?:第[一二三四五六七八九十百千\d]+[篇章节卷回]|[\u4e00-\u9fa5·]{1,15}第[一二三四五六七八九十百千\d]+)$"
)
# txt 行首编号：道德经帛书原文「01.道可道也…」（编号与正文同行）。
# 点后必须紧跟非空白非数字，排除「2. 德性讲坛」这类带空格的标题行
_TXT_NUMBERED = re.compile(r"^(\d{1,3})\.(?=[^\s\d])")


def _match_marker(line: str) -> tuple[str | None, str | None]:
    """识别章节标记行，返回 (章节标签, 保留的正文行)。

    无标记返回 (None, 原行)；独立标记行（标题/章节名）返回 (标签, None)，
    正文行整个剔除；「编号+正文同行」返回 (标签, 剥掉编号后的正文)。
    """
    m = _MD_HEADING.match(line)
    if m:
        label = _TRAILING_LINK.sub("", m.group(1)).strip()
        return label or None, None
    if _TXT_CHAPTER.match(line):
        return line, None
    m = _TXT_NUMBERED.match(line)
    if m:
        return f"第{int(m.group(1)):02d}章", line[m.end() :].strip()
    return None, line


def _split_sections(text: str) -> list[tuple[str, str]]:
    """按行扫描，输出 [(章节, 段落), ...]；空行分隔段落，标记行更新当前章节。"""
    sections: list[tuple[str, str]] = []
    current_chapter = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if buffer:
            sections.append((current_chapter, "\n".join(buffer)))
            buffer = []

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        chapter, keep = _match_marker(stripped)
        if chapter is not None:
            flush()
            current_chapter = chapter
            if keep:
                buffer.append(keep)
            continue
        buffer.append(stripped)
    flush()
    return sections


@dataclass
class Chunk:
    """一个可入库检索的文本片段。"""

    id: str
    document_id: str
    index: int
    text: str
    metadata: dict = field(default_factory=dict)
    text_hash: str = field(default="", init=False)

    def __post_init__(self):
        # 内容哈希用于增量入库时判断片段是否变化
        self.text_hash = md5(self.text.encode("utf-8")).hexdigest()


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """按字符窗口切分文本；overlap 必须小于 chunk_size。"""
    if overlap >= chunk_size:
        raise ValueError("overlap 必须小于 chunk_size")
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    pieces: list[str] = []
    for paragraph in (p.strip() for p in normalized.split("\n\n") if p.strip()):
        if len(paragraph) <= chunk_size:
            pieces.append(paragraph)
            continue
        start = 0
        while start < len(paragraph):
            pieces.append(paragraph[start : start + chunk_size])
            start += chunk_size - overlap
    return pieces


def chunk_document(
    document: Document, chunk_size: int = 800, overlap: int = 100
) -> list[Chunk]:
    """把单个文档切成 Chunk 列表；id 由文档 id 加序号稳定生成，metadata 含章节。"""
    chunks = []
    for section_chapter, section_text in _split_sections(document.text):
        for text in chunk_text(section_text, chunk_size, overlap):
            chunk_id = str(uuid5(NAMESPACE_URL, f"{document.id}:{len(chunks)}"))
            chunks.append(
                Chunk(
                    id=chunk_id,
                    document_id=document.id,
                    index=len(chunks),
                    text=text,
                    metadata={
                        **document.metadata,
                        "source": document.source,
                        "chapter": section_chapter,
                    },
                )
            )
    return chunks


def chunk_documents(
    documents: list[Document], chunk_size: int = 800, overlap: int = 100
) -> list[Chunk]:
    """批量切分文档。"""
    chunks = []
    for document in documents:
        chunks.extend(chunk_document(document, chunk_size, overlap))
    return chunks


def probe_chapters(path: str | Path, max_preview: int = 10) -> None:
    """章节提取核对：打印每个文档的章节数与章节清单开头，供人工核对正则。

    用法: uv run python -c "from app.rag.chunker import probe_chapters; probe_chapters('data/books')"
    """
    from app.rag.cleaner import clean_text
    from app.rag.loader import load_file, load_directory

    target = Path(path)
    files = [target] if target.is_file() else load_directory(target)
    for doc in files:
        if doc is None:
            continue
        cleaned = clean_text(doc.text)
        sections = _split_sections(cleaned.text)
        seen: list[str] = []
        for chapter, _text in sections:
            if chapter and chapter not in seen:
                seen.append(chapter)
        preview = "、".join(seen[:max_preview])
        suffix = "…" if len(seen) > max_preview else ""
        print(
            f"{doc.metadata.get('filename', doc.source)}: 章节 {len(seen)} 个"
            f"{'（无章节！）' if not seen else ''} 清洗移除 {cleaned.removed_lines} 行"
            + (f" 警告 {cleaned.warnings}" if cleaned.warnings else "")
        )
        if seen:
            print(f"  前 {min(max_preview, len(seen))} 个: {preview}{suffix}")
