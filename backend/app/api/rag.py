import dataclasses
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.database import records as records_db
from app.database.db import enabled as db_enabled
from app.rag import ingest, prune, search
from app.rag.pipeline import ProgressEvent

router = APIRouter(prefix="/rag", tags=["rag"])
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"

NTFY_URL = "https://ntfy.sh"
NTFY_TOPIC = "louisding_9527"  # 用户手机 ntfy 已订阅的话题

MAX_JOBS = 100  # 内存任务表上限，超出后丢弃已完成的旧任务
MAX_LOG_LINES = 300  # 每个任务的执行日志行数上限

STAGE_LABELS = {
    "title": "书名优化",
    "convert": "格式转换",
    "clean": "文本清洗",
    "chunk": "分块",
    "embed": "向量化",
    "upsert": "写入向量库",
    "skip": "指纹匹配，跳过",
    "done": "完成",
}


@dataclass
class Job:
    """一次后台入库任务的状态。"""

    id: str
    status: str = "running"  # running | done | failed
    stage: str = ""  # 当前处理阶段
    total_documents: int = 0
    current_index: int = 0
    current_file: str = ""
    embedded: int = 0
    skipped: int = 0
    log: list[str] = field(default_factory=list)  # 执行日志（带时间戳）
    result: dict | None = None
    error: str | None = None
    kind: str = "directory"  # directory | file | upload（记录表用）
    path: str = ""
    reset: bool = False
    started_at: datetime | None = None


def _log_line(message: str) -> str:
    return f"[{datetime.now():%H:%M:%S}] {message}"


def _append_log(job: Job, message: str) -> None:
    job.log.append(_log_line(message))
    if len(job.log) > MAX_LOG_LINES:
        del job.log[: len(job.log) - MAX_LOG_LINES]


def _notify(job: Job) -> None:
    """入库任务完成或失败时推送手机通知；通知失败不影响任务本身。"""
    if job.status == "done":
        r = job.result
        title = "📚 入库完成"
        message = (
            f"文档 {r['documents']} 个：新增 {r['documents_new']}、"
            f"更新 {r['documents_updated']}、未变 {r['documents_unchanged']}；"
            f"片段 {r['chunks']}（嵌入 {r['embedded']}、跳过 {r['skipped']}）"
        )
    else:
        title = "❌ 入库失败"
        message = job.error or "未知错误"
    try:
        httpx.post(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            json={"title": title, "message": message},
            timeout=10,
        )
    except Exception:
        pass  # 通知只是附加功能，失败不阻塞任务


_jobs: dict[str, Job] = {}


def _write_records(
    task_id: str,
    kind: str,
    path: str,
    reset: bool,
    started_at: datetime,
    result=None,
    error: str | None = None,
) -> None:
    """尽力而为写入入库记录（任务概要 + 文档明细）；失败只记日志，不影响任务。"""
    try:
        records_db.create_task(
            task_id=task_id,
            kind=kind,
            path=path,
            reset=reset,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            result=dataclasses.asdict(result) if result else None,
            documents=result.documents_detail if result else None,
            error=error,
        )
    except Exception as exc:
        logger.warning("入库记录写入失败（id=%s）：%s", task_id, exc)


def _run_ingest_job(job: Job, path: str, reset: bool, kind: str) -> None:
    job.kind = kind
    job.path = path
    job.reset = reset
    job.started_at = datetime.now(timezone.utc)

    def on_progress(event: ProgressEvent) -> None:
        job.total_documents = event.total
        job.current_index = event.index
        job.current_file = event.filename
        job.stage = event.stage
        job.embedded = event.embedded
        job.skipped = event.skipped
        label = STAGE_LABELS.get(event.stage, event.stage)
        detail = f"（{event.message}）" if event.message else ""
        _append_log(job, f"[{event.index + 1}/{event.total}] {event.filename}: {label}{detail}")

    _append_log(job, "任务开始" + ("（清空集合重建）" if reset else "（增量同步）"))
    try:
        result = ingest(path, reset=reset, progress=on_progress)
        job.status = "done"
        job.result = dataclasses.asdict(result)
        r = job.result
        _append_log(
            job,
            f"入库完成：文档 {r['documents']}（新增 {r['documents_new']}、"
            f"更新 {r['documents_updated']}、未变 {r['documents_unchanged']}），"
            f"片段 {r['chunks']}（嵌入 {r['embedded']}、跳过 {r['skipped']}）",
        )
        _write_records(job.id, job.kind, job.path, job.reset, job.started_at, result=result)
    except Exception as exc:  # 任何异常都标记失败，避免任务永远停在 running
        job.status = "failed"
        job.error = str(exc)
        _append_log(job, f"入库失败：{exc}")
        _write_records(
            job.id, job.kind, job.path, job.reset, job.started_at, error=str(exc)
        )
    _notify(job)


def _register_job() -> Job:
    job = Job(id=uuid.uuid4().hex)
    _jobs[job.id] = job
    if len(_jobs) > MAX_JOBS:
        for old_id in [
            jid for jid, j in _jobs.items() if j.status != "running"
        ][: len(_jobs) - MAX_JOBS]:
            del _jobs[old_id]
    return job


class IngestRequest(BaseModel):
    path: str
    reset: bool = False


class PruneRequest(BaseModel):
    path: str


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    score_threshold: float | None = None


@router.post("/ingest", status_code=202)
def ingest_documents(request: IngestRequest):
    """异步入库：立即返回 job_id，用 GET /rag/ingest/status/{job_id} 轮询阶段进度与执行日志。"""
    job = _register_job()
    kind = "file" if Path(request.path).is_file() else "directory"
    threading.Thread(
        target=_run_ingest_job, args=(job, request.path, request.reset, kind), daemon=True
    ).start()
    return {"job_id": job.id, "status": job.status}


@router.get("/ingest/status/{job_id}")
def ingest_status(job_id: str):
    """查询入库任务进度；log 为带时间戳的执行日志，任务完成后 result 为最终统计。"""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已被清理")
    return dataclasses.asdict(job)


@router.get("/records")
def list_records(limit: int = 20):
    """最近入库任务列表（按开始时间倒序，来自 PostgreSQL 记录表）。"""
    if not db_enabled():
        raise HTTPException(status_code=503, detail="入库记录功能未启用（未配置 DATABASE_URL）")
    return records_db.list_tasks(limit=max(1, min(limit, 100)))


@router.get("/records/{task_id}")
def get_record(task_id: str):
    """任务概要 + 该任务的文档明细。"""
    if not db_enabled():
        raise HTTPException(status_code=503, detail="入库记录功能未启用（未配置 DATABASE_URL）")
    task = records_db.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return task


@router.post("/prune")
def prune_documents(request: PruneRequest):
    """清理指定目录中已不存在文档的旧片段，返回清理的文档数。"""
    try:
        deleted = prune(request.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"deleted_documents": deleted}


@router.post("/search")
def search_chunks(request: SearchRequest):
    """语义检索，返回相关片段及得分。"""
    hits = search(
        request.query, top_k=request.top_k, score_threshold=request.score_threshold
    )
    return [
        {
            "score": hit.score,
            "text": hit.chunk.text,
            "document_id": hit.chunk.document_id,
            "index": hit.chunk.index,
            "source": hit.chunk.metadata.get("source"),
            "filename": hit.chunk.metadata.get("filename"),
            "title": hit.chunk.metadata.get("title"),
            "book": hit.chunk.metadata.get("book"),
            "chapter": hit.chunk.metadata.get("chapter"),
        }
        for hit in hits
    ]


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """上传单个文本文件入库，保存到 data/uploads/ 后增量 ingest。"""
    filename = Path(file.filename or "upload.txt").name  # 仅取文件名，防路径穿越
    target = UPLOAD_DIR / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(await file.read())
    try:
        result = await run_in_threadpool(ingest, target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _write_records(
        uuid.uuid4().hex, "upload", str(target), False,
        datetime.now(timezone.utc), result=result,
    )
    return result
