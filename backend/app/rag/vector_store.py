"""Qdrant 向量存储：集合管理、批量写入与相似度检索。"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.rag.chunker import Chunk

RESERVED_PAYLOAD_KEYS = {"text", "document_id", "index", "hash"}


@dataclass
class SearchHit:
    """一次检索命中的片段及其相似度得分。"""

    chunk: Chunk
    score: float


class VectorStore:
    def __init__(self, url: str | None = None, collection: str | None = None):
        self.client = QdrantClient(url=url or settings.qdrant_url)
        self.collection = collection or "philosophy_chunks"

    def ensure_collection(self, vector_size: int) -> None:
        """集合不存在则创建；已存在但向量维度不符时报错。"""
        if self.client.collection_exists(self.collection):
            existing = self.client.get_collection(self.collection)
            if existing.config.params.vectors.size != vector_size:
                raise ValueError(
                    f"集合 {self.collection} 向量维度为 {existing.config.params.vectors.size}，"
                    f"与模型维度 {vector_size} 不一致"
                )
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    def exists(self) -> bool:
        return self.client.collection_exists(self.collection)

    def reset_collection(self, vector_size: int) -> None:
        """删除并重建集合，用于全量重新入库。"""
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    def upsert(self, chunks: Iterable[Chunk], vectors: Iterable[list[float]]) -> int:
        """批量写入 chunk 与对应向量；同 id 重复写入视为覆盖，返回写入条数。"""
        points = []
        for chunk, vector in zip(chunks, vectors):
            points.append(
                PointStruct(
                    id=chunk.id,
                    vector=vector,
                    payload={
                        "text": chunk.text,
                        "document_id": chunk.document_id,
                        "index": chunk.index,
                        "hash": chunk.text_hash,
                        **chunk.metadata,
                    },
                )
            )
        self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    def existing_hashes(self, ids: list[str]) -> dict[str, str]:
        """批量查询已入库片段的文本哈希；未入库的 id 不出现。"""
        hashes: dict[str, str] = {}
        for start in range(0, len(ids), 1000):
            batch = ids[start : start + 1000]
            for record in self.client.retrieve(
                collection_name=self.collection,
                ids=batch,
                with_payload=["hash"],
                with_vectors=False,
            ):
                if record.payload and record.payload.get("hash"):
                    hashes[str(record.id)] = record.payload["hash"]
        return hashes

    def document_ids(self) -> set[str]:
        """扫描集合，返回所有已入库的 document_id。"""
        ids: set[str] = set()
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                limit=1000,
                offset=offset,
                with_payload=["document_id"],
                with_vectors=False,
            )
            for point in points:
                if point.payload and point.payload.get("document_id"):
                    ids.add(point.payload["document_id"])
            if offset is None:
                break
        return ids

    def document_stamp(self, document_id: str) -> dict | None:
        """返回该文档上次入库时记录的文件指纹 (size, mtime)；从未入库返回 None。"""
        points, _ = self.client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
            limit=1,
            with_payload=["size", "mtime"],
            with_vectors=False,
        )
        if not points or not points[0].payload:
            return None
        return {"size": points[0].payload.get("size"), "mtime": points[0].payload.get("mtime")}

    def delete_documents(self, document_ids: list[str]) -> int:
        """按 document_id 删除其全部片段，返回请求删除的文档数。"""
        if not document_ids:
            return 0
        self.client.delete(
            collection_name=self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchAny(any=document_ids))]
            ),
        )
        return len(document_ids)

    def search(
        self,
        vector: list[float],
        top_k: int = 5,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        """按余弦相似度检索最相关的片段。"""
        result = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )
        hits = []
        for point in result.points:
            payload = point.payload or {}
            metadata = {k: v for k, v in payload.items() if k not in RESERVED_PAYLOAD_KEYS}
            chunk = Chunk(
                id=point.id,
                document_id=payload["document_id"],
                index=payload["index"],
                text=payload["text"],
                metadata=metadata,
            )
            hits.append(SearchHit(chunk=chunk, score=point.score))
        return hits


@lru_cache
def get_store() -> VectorStore:
    """进程内复用一个客户端实例。"""
    return VectorStore()
