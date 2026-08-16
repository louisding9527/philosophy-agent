"""入库记录读写：每次 ingest 完成后写入任务概要 + 每文档明细，供审计与后续 agent 系统查询。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.database.db import connection


@dataclass
class DocumentRecord:
    """单个文档在本次入库中的结果。"""

    document_id: str
    filename: str
    title: str
    book: str | None
    path: str
    size: int | None
    mtime: float | None
    chunks: int
    embedded: int
    skipped: int
    status: str  # new | updated | unchanged | skipped
    warning: str | None = None


def create_task(
    task_id: str,
    kind: str,
    path: str,
    reset: bool,
    started_at: datetime,
    finished_at: datetime,
    result: dict[str, Any] | None,
    documents: list[DocumentRecord] | None = None,
    error: str | None = None,
) -> None:
    """单事务写入一条任务记录及其文档明细；result 为 IngestResult.asdict()。

    任务失败时 result 传 None，error 传失败原因；记录写入失败由调用方兜底，
    不影响入库结果本身。
    """
    task_id = str(UUID(task_id))  # 兼容无连字符的 hex 形式
    status = "failed" if error else "done"
    values = (
        task_id,
        kind,
        path,
        reset,
        status,
        started_at,
        finished_at,
        result.get("documents") if result else None,
        result.get("documents_new") if result else None,
        result.get("documents_updated") if result else None,
        result.get("documents_unchanged") if result else None,
        result.get("chunks") if result else None,
        result.get("embedded") if result else None,
        result.get("skipped") if result else None,
        error,
    )
    with connection() as conn:
        conn.execute(
            "INSERT INTO ingest_tasks (id, kind, path, reset, status, started_at, finished_at,"
            " documents, documents_new, documents_updated, documents_unchanged,"
            " chunks, embedded, skipped, error)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            values,
        )
        for doc in documents or []:
            conn.execute(
                "INSERT INTO ingest_documents (task_id, document_id, filename, title, book, path,"
                " size, mtime, chunks, embedded, skipped, status, warning)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    task_id,
                    doc.document_id,
                    doc.filename,
                    doc.title,
                    doc.book,
                    doc.path,
                    doc.size,
                    doc.mtime,
                    doc.chunks,
                    doc.embedded,
                    doc.skipped,
                    doc.status,
                    doc.warning,
                ),
            )
        conn.commit()


def list_tasks(limit: int = 20) -> list[dict]:
    """最近的任务列表（按开始时间倒序）。"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, kind, path, reset, status, started_at, finished_at,"
            " documents, documents_new, documents_updated, documents_unchanged,"
            " chunks, embedded, skipped, error"
            " FROM ingest_tasks ORDER BY started_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
    for row in rows:
        row["id"] = str(row["id"])
    return rows


def get_task(task_id: str) -> dict | None:
    """任务概要 + 该任务的文档明细；任务不存在返回 None。"""
    with connection() as conn:
        row = conn.execute(
            "SELECT id, kind, path, reset, status, started_at, finished_at,"
            " documents, documents_new, documents_updated, documents_unchanged,"
            " chunks, embedded, skipped, error"
            " FROM ingest_tasks WHERE id = %s",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        row["id"] = str(row["id"])
        docs = conn.execute(
            "SELECT document_id, filename, title, book, path, size, mtime,"
            " chunks, embedded, skipped, status, warning"
            " FROM ingest_documents WHERE task_id = %s ORDER BY filename",
            (task_id,),
        ).fetchall()
    row["documents"] = docs
    return row
