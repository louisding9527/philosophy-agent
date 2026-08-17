# 设计：入库时同步写 Neo4j 图存储

## 图结构

```
(:Book {title}) -[:HAS_CHAPTER]-> (:Chapter {book, title}) -[:HAS_CHUNK]-> (:Chunk {id, ...})
```

- `Book.title` = `doc.metadata["book"]`（pipeline 已清洗，如《论语》原文、纯粹理性批判）。
- `Chapter` 节点以 `(book, title)` 唯一；章节标签来自 chunker 的 `metadata["chapter"]`（空章节统一为空字符串，不单独建节点——空章节片段直接挂 Book）。
- `Chunk` 节点以稳定 id（`uuid5`，与 Qdrant 同源）唯一，属性：`document_id`、`index`、`text`、`text_hash`、`chapter`、`book`。
- 空章节（`chapter == ""`）的片段：跳过 Chapter 节点，直接 `(:Book)-[:HAS_CHUNK]->(:Chunk)`，避免无意义空标题节点。

## 幂等策略

全部用 `MERGE`：节点按唯一键 merge + `SET` 覆盖属性，关系 merge。重复入库只更新属性，不新增节点。同一书内不同文档共用 Book/Chapter 节点。

## 写入批量

`UNWIND $rows` 单条 Cypher 批量写入，与 Qdrant 一致按 500 一批，避免单事务过大。每次 upsert 开一个事务（auto-commit）。

## 清理

- `reset()`：`MATCH (n) DETACH DELETE n` 全清（对应 ingest reset=True 全量重建）。
- `delete_documents(ids)`：按 `document_id` 删 `Chunk`，随后级联清理不再有片段的 `Chapter`、不再有章节的 `Book`（`WHERE NOT EXISTS(...)`）。

## 容错

- `Neo4jStore` 构造时若 `neo4j_uri` 为空 → `enabled=False`，所有方法直接跳过。
- pipeline 调用时 try/except，任何 Neo4j 异常打 `logger.warning`（含一句话原因），吞掉继续；与 postgres 记录同样的 best-effort 定位。
- driver 惰性连接，方法内首次使用时 `verify_connectivity` 失败即抛错被吞。

## 配置

- `config.py`：`neo4j_password: str = ""`（user 固定 `neo4j`，对应 docker compose `NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}`）。
- `backend/.env`：`NEO4J_PASSWORD=philosophy_dev_2026`（与 `docker/.env` 同步）。
- `requirements.txt`：`neo4j>=5.0`。

## 改动文件

| 文件 | 改动 |
|---|---|
| `backend/app/rag/neo4j_store.py` | 新增，Neo4jStore 类 |
| `backend/app/rag/pipeline.py` | ingest/prune/reset 集成图写入（best-effort） |
| `backend/app/core/config.py` | 加 `neo4j_password` |
| `backend/.env` | 加 `NEO4J_PASSWORD` |
| `backend/requirements.txt` | 加 `neo4j>=5.0` |

明确不做：实体/概念关系抽取（LLM）、graph API 路由、Qdrant/postgres 逻辑改动。
