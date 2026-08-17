# 入库时同步写 Neo4j 图存储

## Goal

RAG 入库（`/rag/ingest`）时，除了写 Qdrant 向量库和 postgres 入库记录外，把文档的「书 → 章节 → 片段」结构同步写入 Neo4j 图库，让 graph 层后续能基于图结构做查询与实体关系扩展。

## Background

- Neo4j 容器（docker compose 的 `neo4j:5-community`，bolt 7687）一直空跑，应用从未接线（`config.py` 只有空的 `neo4j_uri`）。
- Qdrant 是主检索存储；postgres 已接入库记录（best-effort）。Neo4j 是第三种存储，写入失败不得影响主入库流程。

## Requirements

- 新增 `backend/app/rag/neo4j_store.py`，提供图写入/清理接口（对应 Qdrant `VectorStore` 的职责，代码风格一致）。
- `pipeline.ingest` 在 Qdrant upsert 之后，把本次实际写入的片段同步成图；`reset=True` 时先清空图库；`pipeline.prune` 删除孤儿文档时同步删图。
- 写入幂等：重复入库不产生重复节点/关系（内容变化时覆盖属性）。
- 配置接线：`config.py` 增加 `neo4j_password`（user 固定 `neo4j`，与 docker compose `NEO4J_AUTH` 一致），`backend/.env` 补 `NEO4J_PASSWORD`，`requirements.txt` 增加 neo4j 驱动。
- 容错：Neo4j 未配置（`neo4j_uri` 为空）或连接/写入失败时，跳过图写入并打警告日志，不影响 ingest 主流程与结果统计。

## Acceptance Criteria

- [ ] `backend/app/rag/neo4j_store.py` 存在，提供 `upsert(chunks)`、`reset()`、`delete_documents(document_ids)`，与 `VectorStore` 同风格。
- [ ] 对真实语料（论语）走一遍 pipeline 相同路径（load → clean → chunk）后，Neo4j 中能看到 `Book` / `Chapter` / `Chunk` 节点及 `HAS_CHAPTER` / `HAS_CHUNK` 关系，节点数 > 0。
- [ ] 同一批片段重复 upsert，节点与关系数不增长（幂等）。
- [ ] `config.py` 有 `neo4j_password`；`backend/.env` 有 `NEO4J_PASSWORD`；`requirements.txt` 有 `neo4j`。
- [ ] `pipeline.ingest` / `prune` 中的图写入失败（如停掉 neo4j 容器）不抛异常，仅告警日志，ingest 结果正常返回。
- [ ] `pipeline.ingest` 中 `reset=True` 会先清空 Neo4j 全库。

## Notes

- 本任务不做实体/概念关系抽取（LLM 抽取是后续独立工作），只同步文档结构图。
- `NEO4J_PASSWORD` 取 docker compose 里已有的 `philosophy_dev_2026`。
