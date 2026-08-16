"""RAG 流水线：文档增量同步入库、显式清理与语义检索。

用法：
    from app.rag import ingest, prune, search

    ingest(Path("data/books"))                # 整目录入库（增量：跳过未变、覆盖变化）
    ingest(Path("data/books/kant.txt"))       # 单个文件
    prune(Path("data/books"))                 # 清理目录中已删除文档的旧片段
    ingest(Path("data/books"), reset=True)    # 清空集合全量重建
    hits = search("什么是先验综合判断", top_k=5)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import NAMESPACE_URL, uuid5
import re

from app.rag.chunker import chunk_document
from app.rag.embedding import get_embedder
from app.rag.loader import load_directory, load_file
from app.rag.vector_store import SearchHit, get_store

EMBED_BATCH = 64  # 每批向量化的片段数，用于细粒度进度展示


@dataclass
class IngestResult:
    """一次入库的结果统计。"""

    documents: int  # 成功处理的文档数（三类之和）
    chunks: int  # 生成的片段总数
    embedded: int  # 新写入或内容变化的片段数
    skipped: int  # 内容未变、跳过向量化的片段数
    documents_new: int  # 新入库的文档数
    documents_updated: int  # 内容变化的文档数
    documents_unchanged: int  # 未变化的文档数（含文件指纹匹配的快跳过）


@dataclass
class ProgressEvent:
    """入库过程中的进度事件（按文档分阶段触发，用于前端阶段展示与执行日志）。"""

    index: int  # 当前文档序号（0 起）
    total: int  # 文档总数
    filename: str  # 当前文档名
    stage: str  # title | convert | chunk | embed | upsert | skip | done
    embedded: int  # 累计写入片段数
    skipped: int  # 累计跳过片段数
    message: str = ""  # 阶段细节，如 "向量化 128/356 片段"


def _clean_title(filename: str) -> str:
    """从文件名提取展示用书名：去扩展名，压缩多余分隔符。"""
    return re.sub(r"[\s_\-—]+", " ", Path(filename).stem).strip()


def _load_documents(path: str | Path) -> list:
    target = Path(path)
    if target.is_file():
        documents = [load_file(target)]
    else:
        documents = load_directory(target)
    return [doc for doc in documents if doc is not None]


def ingest(
    path: str | Path,
    *,
    reset: bool = False,
    progress: Callable[[ProgressEvent], None] | None = None,
) -> IngestResult:
    """把单个文件或目录下的文档同步进 Qdrant，返回统计。

    自动分辨新旧文档：
    - 文件指纹（大小 + 修改时间）与库中一致 -> 整个文档快跳过，不解析、不向量化
    - 片段内容未变 -> 跳过，不重新向量化
    - 片段内容变化 -> 覆盖写入
    已删除文档的清理请显式调用 prune；reset=True 时清空集合后全量重建。
    progress 回调每处理完一个文档触发一次，可用于任务进度展示。
    """
    target = Path(path)
    if target.is_file():
        files = [target]
    else:
        files = sorted(p for p in target.rglob("*") if p.is_file())
    if not files:
        raise ValueError(f"没有找到可解析的文档: {path}")

    embedder = get_embedder()
    store = get_store()
    if reset:
        store.reset_collection(embedder.dim)
    else:
        store.ensure_collection(embedder.dim)

    total_chunks = embedded_total = skipped_total = 0
    new_docs = updated_docs = unchanged_docs = 0
    for index, file in enumerate(files):
        fpath = file.resolve()
        document_id = str(uuid5(NAMESPACE_URL, str(fpath)))
        try:
            stamp = {"size": fpath.stat().st_size, "mtime": fpath.stat().st_mtime}
        except OSError:
            continue
        filename = fpath.name

        def emit(stage: str, message: str = "") -> None:
            if progress:
                progress(
                    ProgressEvent(
                        index=index, total=len(files), filename=filename,
                        embedded=embedded_total, skipped=skipped_total,
                        stage=stage, message=message,
                    )
                )

        # 文件指纹匹配 -> 整文档快跳过，连解析都省了
        if not reset and store.document_stamp(document_id) == stamp:
            unchanged_docs += 1
            emit("skip")
            continue

        emit("title")
        title = _clean_title(filename)
        emit("convert")
        doc = load_file(fpath)
        if doc is None:
            continue
        doc.metadata["title"] = title
        doc_chunks = chunk_document(doc)
        emit("chunk")
        existing = store.existing_hashes([chunk.id for chunk in doc_chunks])
        to_embed = [
            chunk for chunk in doc_chunks if existing.get(chunk.id) != chunk.text_hash
        ]
        if to_embed:
            vectors: list[list[float]] = []
            for start in range(0, len(to_embed), EMBED_BATCH):
                batch = to_embed[start : start + EMBED_BATCH]
                vectors.extend(embedder.embed([chunk.text for chunk in batch]))
                done = min(start + EMBED_BATCH, len(to_embed))
                emit("embed", message=f"向量化 {done}/{len(to_embed)} 片段")
            emit("upsert")
            store.upsert(to_embed, vectors)
        total_chunks += len(doc_chunks)
        embedded_total += len(to_embed)
        skipped_total += len(doc_chunks) - len(to_embed)
        known = sum(1 for chunk in doc_chunks if chunk.id in existing)
        if known == 0:
            new_docs += 1
        elif to_embed:
            updated_docs += 1
        else:
            unchanged_docs += 1
        emit("done")

    documents = new_docs + updated_docs + unchanged_docs
    if documents == 0:
        raise ValueError(f"没有找到可解析的文档: {path}")
    return IngestResult(
        documents=documents,
        chunks=total_chunks,
        embedded=embedded_total,
        skipped=skipped_total,
        documents_new=new_docs,
        documents_updated=updated_docs,
        documents_unchanged=unchanged_docs,
    )


def prune(path: str | Path) -> int:
    """清理集合中已不在目录或文件里的文档，返回清理的文档数。

    只读语料目录本身，不触发向量化；集合不存在时直接返回 0。
    """
    store = get_store()
    if not store.exists():
        return 0
    documents = _load_documents(path)
    if not documents:
        raise ValueError(f"没有找到可解析的文档: {path}")
    current_ids = {doc.id for doc in documents}
    orphan_ids = sorted(store.document_ids() - current_ids)
    if orphan_ids:
        store.delete_documents(orphan_ids)
    return len(orphan_ids)


def search(
    query: str, top_k: int = 5, score_threshold: float | None = None
) -> list[SearchHit]:
    """把查询向量化后在库中检索最相关的片段，按得分从高到低返回。"""
    embedder = get_embedder()
    store = get_store()
    store.ensure_collection(embedder.dim)
    [vector] = embedder.embed([query])
    return store.search(vector, top_k=top_k, score_threshold=score_threshold)
