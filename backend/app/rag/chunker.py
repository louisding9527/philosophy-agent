"""文本分块：先按段落切分，超长段落再用定长滑动窗口，支持重叠。"""

from dataclasses import dataclass, field
from hashlib import md5
from uuid import NAMESPACE_URL, uuid5

from app.rag.loader import Document


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
    """把单个文档切成 Chunk 列表；id 由文档 id 加序号稳定生成。"""
    chunks = []
    for index, text in enumerate(chunk_text(document.text, chunk_size, overlap)):
        chunk_id = str(uuid5(NAMESPACE_URL, f"{document.id}:{index}"))
        chunks.append(
            Chunk(
                id=chunk_id,
                document_id=document.id,
                index=index,
                text=text,
                metadata={**document.metadata, "source": document.source},
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
