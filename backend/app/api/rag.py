import dataclasses
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.rag import ingest, prune, search
from app.rag.pipeline import ProgressEvent

router = APIRouter(prefix="/rag", tags=["rag"])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"

NTFY_URL = "https://ntfy.sh"
NTFY_TOPIC = "louisding_9527"  # 用户手机 ntfy 已订阅的话题

MAX_JOBS = 100  # 内存任务表上限，超出后丢弃已完成的旧任务


@dataclass
class Job:
    """一次后台入库任务的状态。"""

    id: str
    status: str = "running"  # running | done | failed
    total_documents: int = 0
    current_index: int = 0
    current_file: str = ""
    phase: str = ""
    embedded: int = 0
    skipped: int = 0
    result: dict | None = None
    error: str | None = None


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


def _run_ingest_job(job: Job, path: str, reset: bool) -> None:
    def on_progress(event: ProgressEvent) -> None:
        job.total_documents = event.total
        job.current_index = event.index
        job.current_file = event.filename
        job.phase = event.phase
        job.embedded = event.embedded
        job.skipped = event.skipped

    try:
        result = ingest(path, reset=reset, progress=on_progress)
        job.status = "done"
        job.result = dataclasses.asdict(result)
    except ValueError as exc:
        job.status = "failed"
        job.error = str(exc)
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
    """异步入库：立即返回 job_id，用 GET /rag/ingest/status/{job_id} 轮询进度。"""
    job = _register_job()
    threading.Thread(
        target=_run_ingest_job, args=(job, request.path, request.reset), daemon=True
    ).start()
    return {"job_id": job.id, "status": job.status}


@router.get("/ingest/status/{job_id}")
def ingest_status(job_id: str):
    """查询入库任务进度；任务完成后 result 为最终统计。"""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已被清理")
    return dataclasses.asdict(job)


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
        return await run_in_threadpool(ingest, target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
