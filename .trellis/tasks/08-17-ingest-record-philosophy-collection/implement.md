# 入库记录表与哲学 Collection 改造 — 实施清单

## 实施顺序

1. `backend/requirements.txt` 加 `psycopg[binary]>=3.1`；`backend/.env.example` 的 DATABASE_URL 示例改 `postgresql://`（同步驱动）并注明需与 docker/.env 密码一致
2. `backend/app/database/db.py`：连接上下文管理器（URL 规范化去掉 `+asyncpg`）、`init_db()`（CREATE TABLE IF NOT EXISTS 两表；ingest_documents 含 warning 列、status 支持 skipped）
3. `backend/app/database/records.py`：`create_task` / `add_documents` / `list_tasks(limit)` / `get_task(task_id)`（单事务写 task+documents；连接失败抛异常由调用方兜底）
4. `backend/app/main.py`：FastAPI lifespan 启动时 `init_db()`，DATABASE_URL 为空则跳过并 warning
5. `backend/app/rag/cleaner.py`（新）：`clean_text` 无损清洗（BOM/换行/控制/零宽字符、链接/图片/元信息噪音行）+ 校验门禁（空/过短 → valid=False；乱码疑似 → warning），返回 CleanResult
6. `backend/app/rag/chunker.py`：章节提取函数 + `chunk_document` 按章节跟踪；先跑 probe 打印 4 本书的章节清单**人工核对后**再定稿正则（独立标记行剔除、编号行只剥前缀保正文）；`metadata["chapter"]`；不再负责链接行过滤
7. `backend/app/rag/pipeline.py`：load 后调 cleaner（新增 clean 阶段）；不洁净文档跳过并记录原因；book 清洗（去尾部括号片段）写入 `metadata["book"]`；收集 per-doc 统计（DocumentRecord 含 warning）
8. `backend/app/rag/vector_store.py`：默认集合 `philosophy_chunks` → `philosophy`
9. `backend/app/api/rag.py`：任务完成后单事务写记录（失败任务也落库）；STAGE_LABELS 加 clean「文本清洗」；`GET /rag/records`、`GET /rag/records/{task_id}`；search 响应加 book/chapter
10. 首页：stageNames 加 clean；加"入库记录"卡片（最近任务列表 + 点击展开明细）
11. TODO.md：勾选/关联"任务表持久化"待办条目

## 验证命令

```bash
# 章节提取 probe：先打印 4 本书章节清单人工核对（定稿正则前必做）
uv run python -c "from app.rag.chunker import probe_chapters; probe_chapters('D:/agents/zhexue/philosophy-agent/backend/data/books')"
# 后端起来后（start-dev.ps1 或 uv run uvicorn）
# 1. 小语料入库验证记录与 chapter
curl -X POST localhost:8000/rag/ingest -H 'Content-Type: application/json' \
  -d '{"path":"D:/agents/zhexue/philosophy-agent/backend/data/test_corpus"}'
curl localhost:8000/rag/records
curl localhost:8000/rag/records/<task_id>
# 2. 查表（Git Bash 下 docker 用完整路径或 PowerShell）
docker exec philosophy-postgres psql -U philosophy -d philosophy \
  -c "SELECT status,documents,chunks FROM ingest_tasks ORDER BY started_at DESC LIMIT 5"
docker exec philosophy-postgres psql -U philosophy -d philosophy \
  -c "SELECT filename,book,chunks FROM ingest_documents LIMIT 10"
# 3. 检索带 book/chapter
curl -X POST localhost:8000/rag/search -H 'Content-Type: application/json' \
  -d '{"query":"什么是先验综合判断","top_k":3}'
# 4. 全量重入库（新集合 philosophy）
curl -X POST localhost:8000/rag/ingest -H 'Content-Type: application/json' \
  -d '{"path":"D:/agents/zhexue/philosophy-agent/backend/data/books","reset":true}'
# 5. 重启后端，records 仍在（持久化验证）
# 6. 验证通过后删旧集合：curl -X DELETE localhost:6333/collections/philosophy_chunks
```

## 风险文件 / 回滚点

- `cleaner.py`：清洗规则若误伤正文（如把正文行当噪音剔除）会丢内容——剔除仅限整行独立且完全匹配链接/图片模式的行；probe 验证 4 本书清洗前后字符数差
- `chunker.py`：章节跟踪改变全部 chunk 文本与哈希 → 必须全量重入库；回滚 = 还原代码（旧集合未删前不受影响）
- `vector_store.py`：集合名切换；旧 `philosophy_chunks` 保留到验证通过
- `api/rag.py`：记录写入失败不得阻断入库（try/except + 日志）

## 前置条件（用户侧）

- `backend/.env` 填 `DATABASE_URL=postgresql://philosophy:<docker/.env 密码>@localhost:5432/philosophy`（用户按自己习惯自行填写）
