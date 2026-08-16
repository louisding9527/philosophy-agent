"""PostgreSQL 连接与入库记录表初始化。

记录写入低频（任务完成时一次 + 查询），直接按需建连，不上连接池；
psycopg 为同步驱动，与应用的 threading 线程模型一致。
"""

import os

# Windows 系统代理（注册表）会拦截 localhost 请求
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

from contextlib import contextmanager

from psycopg import connect
from psycopg.rows import dict_row

from app.core.config import settings

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ingest_tasks (
        id UUID PRIMARY KEY,
        kind TEXT NOT NULL,               -- directory | file | upload
        path TEXT NOT NULL,
        reset BOOLEAN NOT NULL DEFAULT FALSE,
        status TEXT NOT NULL,             -- done | failed
        started_at TIMESTAMPTZ NOT NULL,
        finished_at TIMESTAMPTZ,
        documents INT,
        documents_new INT,
        documents_updated INT,
        documents_unchanged INT,
        chunks INT,
        embedded INT,
        skipped INT,
        error TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingest_documents (
        task_id UUID NOT NULL REFERENCES ingest_tasks(id) ON DELETE CASCADE,
        document_id TEXT NOT NULL,        -- uuid5 稳定文档 id
        filename TEXT NOT NULL,
        title TEXT NOT NULL,
        book TEXT,
        path TEXT NOT NULL,
        size BIGINT,
        mtime DOUBLE PRECISION,
        chunks INT NOT NULL,
        embedded INT NOT NULL,
        skipped INT NOT NULL,
        status TEXT NOT NULL,             -- new | updated | unchanged | skipped
        warning TEXT,                     -- 清洗校验警告（不洁净原因等）
        PRIMARY KEY (task_id, document_id)
    )
    """,
]


def enabled() -> bool:
    """记录功能是否可用（DATABASE_URL 已配置）。"""
    return bool(settings.database_url)


def _normalize_url(url: str) -> str:
    """兼容旧示例里的 postgresql+asyncpg 协议后缀（psycopg 用纯 postgresql://）。"""
    return url.replace("postgresql+asyncpg://", "postgresql://")


@contextmanager
def connection():
    """数据库连接上下文；调用方负责事务（commit/rollback），退出时关闭连接。"""
    conn = connect(_normalize_url(settings.database_url), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """创建记录表（幂等，启动时调用）。连接失败抛异常，由调用方降级处理。"""
    with connection() as conn:
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()
