"""Neo4j 图存储：入库时把「书 → 章节 → 片段」结构同步成图。

与 Qdrant 向量库同构：按稳定 id 幂等写入、按文档清理；图写入失败只记警告，
不影响入库主流程（best-effort，与 postgres 入库记录同一原则）。
"""

import logging
from functools import lru_cache
from typing import Iterable

from neo4j import GraphDatabase

from app.core.config import settings
from app.rag.chunker import Chunk

logger = logging.getLogger(__name__)

WRITE_BATCH = 500  # 与 Qdrant 写入批次一致，单事务行数可控

# 有章节的片段：Book -HAS_CHAPTER-> Chapter -HAS_CHUNK-> Chunk；
# 无章节（chapter 为空）的片段跳过 Chapter 节点，直接挂 Book，避免空标题节点。
_UPSERT_CYPHER = """
UNWIND $rows AS row
MERGE (b:Book {title: row.book})
FOREACH (_ IN CASE WHEN row.chapter <> '' THEN [1] ELSE [] END |
    MERGE (c:Chapter {book: row.book, title: row.chapter})
    MERGE (b)-[:HAS_CHAPTER]->(c)
    MERGE (k:Chunk {id: row.id})
    SET k.document_id = row.document_id, k.index = row.index, k.text = row.text,
        k.text_hash = row.hash, k.chapter = row.chapter, k.book = row.book
    MERGE (c)-[:HAS_CHUNK]->(k)
)
FOREACH (_ IN CASE WHEN row.chapter = '' THEN [1] ELSE [] END |
    MERGE (k:Chunk {id: row.id})
    SET k.document_id = row.document_id, k.index = row.index, k.text = row.text,
        k.text_hash = row.hash, k.chapter = row.chapter, k.book = row.book
    MERGE (b)-[:HAS_CHUNK]->(k)
)
"""

_DELETE_CHUNKS_CYPHER = "MATCH (k:Chunk) WHERE k.document_id IN $ids DETACH DELETE k"
# 级联清理不再被任何片段引用的章节与书
_PRUNE_CHAPTERS_CYPHER = (
    "MATCH (c:Chapter) WHERE NOT EXISTS((c)-[:HAS_CHUNK]->(:Chunk)) DETACH DELETE c"
)
_PRUNE_BOOKS_CYPHER = (
    "MATCH (b:Book) WHERE NOT EXISTS((b)-[:HAS_CHAPTER]->(:Chapter))"
    " AND NOT EXISTS((b)-[:HAS_CHUNK]->(:Chunk)) DETACH DELETE b"
)


class Neo4jStore:
    """Neo4j 图写入；未配置 NEO4J_URI 时 enabled=False，所有操作静默跳过。"""

    def __init__(self, uri: str | None = None, password: str | None = None):
        self.uri = uri or settings.neo4j_uri
        self.password = password if password is not None else settings.neo4j_password
        self.enabled = bool(self.uri)
        self._driver = None
        if self.enabled:
            # user 固定 neo4j，与 docker-compose 的 NEO4J_AUTH: neo4j/${NEO4J_PASSWORD} 对应
            self._driver = GraphDatabase.driver(
                self.uri, auth=("neo4j", self.password), connection_timeout=5
            )

    def _run(self, cypher: str, **params) -> None:
        """执行一条 Cypher；连接/执行失败仅记警告，不向调用方抛错。"""
        if not self.enabled or self._driver is None:
            return
        try:
            with self._driver.session() as session:
                session.run(cypher, **params)
        except Exception as exc:  # noqa: BLE001 - best-effort 写入，不拖垮主流程
            logger.warning("Neo4j 写入失败: %s", exc)

    def upsert(self, chunks: Iterable[Chunk]) -> int:
        """把片段批量 upsert 成图（MERGE 幂等，重复写入只覆盖属性），返回行数。"""
        rows = [
            {
                "id": chunk.id,
                "document_id": chunk.document_id,
                "index": chunk.index,
                "text": chunk.text,
                "hash": chunk.text_hash,
                "book": str(chunk.metadata.get("book") or ""),
                "chapter": str(chunk.metadata.get("chapter") or ""),
            }
            for chunk in chunks
        ]
        if not rows:
            return 0
        for start in range(0, len(rows), WRITE_BATCH):
            self._run(_UPSERT_CYPHER, rows=rows[start : start + WRITE_BATCH])
        return len(rows)

    def reset(self) -> None:
        """清空图库，对应 ingest reset=True 的全量重建。"""
        self._run("MATCH (n) DETACH DELETE n")

    def delete_documents(self, document_ids: Iterable[str]) -> int:
        """按 document_id 删除片段节点，并级联清理不再有片段的章节与书，返回文档数。"""
        ids = list(document_ids)
        if not ids:
            return 0
        self._run(_DELETE_CHUNKS_CYPHER, ids=ids)
        self._run(_PRUNE_CHAPTERS_CYPHER)
        self._run(_PRUNE_BOOKS_CYPHER)
        return len(ids)


@lru_cache
def get_graph_store() -> Neo4jStore:
    """进程内复用一个客户端实例。"""
    return Neo4jStore()
