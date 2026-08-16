"""文档加载器：从文件或目录读取原始文本，统一为 Document 结构。

.txt/.md 直接读取；其他格式（pdf/docx/pptx/xlsx/html 等）先经
markitdown 转换为 Markdown 文本再入库。转换失败或编码不识别返回 None，跳过该文件。
"""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


@dataclass
class Document:
    """一份原始文档。id 由文件绝对路径稳定生成，重复加载不会产生新 id。"""

    id: str
    source: str  # 绝对路径
    text: str
    metadata: dict = field(default_factory=dict)


DIRECT_SUFFIXES = {".txt", ".md"}

_markitdown = None


def _convert_to_markdown(path: Path) -> str | None:
    """用 markitdown 把任意受支持格式转成 Markdown 文本；失败返回 None。"""
    global _markitdown
    if _markitdown is None:
        try:
            from markitdown import MarkItDown
        except ImportError:
            return None
        _markitdown = MarkItDown()
    try:
        return _markitdown.convert(str(path)).text_content
    except Exception:
        return None


def load_file(path: Path) -> Document | None:
    """读取单个文件；扩展名不受支持、编码不识别或转换失败时返回 None。"""
    path = path.resolve()
    if path.suffix.lower() in DIRECT_SUFFIXES:
        text = None
        for encoding in ("utf-8", "gb18030"):
            try:
                text = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = _convert_to_markdown(path)  # 仍失败（如 UTF-16）走 markitdown
        # markitdown 对部分 txt 会返回字面量 "None"，视为转换失败
        if not text or text.strip() == "None":
            return None
    else:
        text = _convert_to_markdown(path)
        if not text:
            return None
    st = path.stat()
    return Document(
        id=str(uuid5(NAMESPACE_URL, str(path))),
        source=str(path),
        text=text,
        metadata={"filename": path.name, "size": st.st_size, "mtime": st.st_mtime},
    )


def load_directory(directory: Path) -> list[Document]:
    """递归加载目录下所有受支持的文本文件。"""
    documents = []
    for path in sorted(Path(directory).rglob("*")):
        if path.is_file():
            doc = load_file(path)
            if doc is not None:
                documents.append(doc)
    return documents
