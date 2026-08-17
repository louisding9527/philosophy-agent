# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

<!--
Document your project's database conventions here.

Questions to answer:
- What ORM/query library do you use?
- How are migrations managed?
- What are the naming conventions for tables/columns?
- How do you handle transactions?
-->

(To be filled by the team)

---

## Query Patterns

<!-- How should queries be written? Batch operations? -->

(To be filled by the team)

---

## Migrations

<!-- How to create and run migrations -->

(To be filled by the team)

---

## Naming Conventions

<!-- Table names, column names, index names -->

(To be filled by the team)

---

## Common Mistakes

<!-- Database-related mistakes your team has made -->

(To be filled by the team)

---

## Neo4j（图库，2026-08-17 接线）

- 入库时把「书 → 章节 → 片段」结构同步成图：`(:Book)-[:HAS_CHAPTER]->(:Chapter {book,title})-[:HAS_CHUNK]->(:Chunk {id,...})`；chapter 为空的片段跳过 Chapter 节点直挂 Book。
- 写入全用 MERGE 幂等（Chunk 按稳定 uuid5 id、Chapter 按 (book,title)），重复入库只覆盖属性不新增节点。
- best-effort：未配置 `NEO4J_URI` 或连接/写入失败仅 `logger.warning`，不影响 ingest 主流程（与 postgres 入库记录同原则）。
- 凭据：`NEO4J_URI` + `NEO4J_PASSWORD`（user 固定 neo4j，对应 docker-compose 的 `NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}`），两者需同步。
- 驱动 `neo4j>=5.0`（现装 6.2.0，`GraphDatabase.driver` API 兼容）；写入批次 500 与 Qdrant 一致。
