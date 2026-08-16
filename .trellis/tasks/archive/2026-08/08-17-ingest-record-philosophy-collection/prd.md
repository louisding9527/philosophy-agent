# 入库记录表与哲学 Collection 改造

## Goal

每次入库成功后把文档级统计持久化到 PostgreSQL（记录表），为后续 agent 系统打基础；Qdrant 集合改为 `philosophy`，片段结构统一为 `{text, vector, metadata:{book, chapter}}`。

## Background（已核实）

- 当前集合 `philosophy_chunks`，payload = {text, document_id, index, hash, source, filename, size, mtime, title}（`backend/app/rag/vector_store.py:82`）；`/rag/search` 返回 source/filename/title（`backend/app/api/rag.py:188`）
- 入库统计 IngestResult：documents/chunks/embedded/skipped/documents_new/updated/unchanged（`backend/app/rag/pipeline.py:28`）；目前只存在内存 Job（`backend/app/api/rag.py:37`），重启即丢
- Postgres 容器已在 compose 中运行（`docker/docker-compose.yml`），应用未接线（无 DB 驱动、DATABASE_URL 空）；应用是同步代码 + threading 模型 → 用同步驱动 psycopg
- 语料：md 书（康德/尼采）有规整 `#` 章节标题，文件为干净 UTF-8（早前疑有乱码，字节级验证为终端显示假象，实际无）；epub 转换残留目录链接行，纯链接/图片行 chunk 约占 2%（尼采 93/4736、康德 43/1730）；论语 txt「学而第一」式标记；道德经帛书版 txt 双书结构（原文 `NN.` 行首编号 + 译文「第X章」独立行）
- 分块器按段落 + 定长窗口切分（`backend/app/rag/chunker.py:26`），无章节感知

## Requirements

- R1（记录表）每次 ingest（目录/单文件/上传）后单事务写入：任务概要（kind/path/reset/status/时间/新增/更新/未变/chunks/embedded/skipped/error）+ 每文档明细（document_id/filename/title/book/path/size/mtime/chunks/embedded/skipped/status/warning）；失败任务也落库；清洗校验不过的文档落 status='skipped' + warning 原因
- R2（持久化）记录存 PostgreSQL 两表 `ingest_tasks` / `ingest_documents`（见 design.md）；DATABASE_URL 为空时记录功能禁用但不影响入库
- R3（集合结构）默认集合改名 `philosophy`；payload 增 book（清洗后书名）与 chapter（章节提取值，无则空串），保留原字段
- R4（章节提取）chunker 按 md 标题 / txt 章节标记启发式跟踪章节；模式对全部 4 本语料实测并打印章节清单核对后定稿；仅整行独立的标记行不进 chunk 文本，「编号+正文同行」只剥编号保正文（防误判丢内容）；ingest 日志按文档报提取章节数（审计信号）
- R7（源头校验清洗）新模块 cleaner.py，在 load 之后、分块之前：无损清洗（BOM、换行归一、控制/零宽字符、链接/图片/元信息噪音行剔除）+ 校验门禁（清洗后空/过短 → 跳过并记录原因；乱码疑似 → warning 不阻断）；结果进 ingest 日志（新增 clean 阶段）与记录表 warning 字段
- R5（查询）`GET /rag/records`（任务列表）、`GET /rag/records/{task_id}`（含文档明细）；`/rag/search` 响应加 book/chapter；首页加"入库记录"卡片
- R6（迁移）reset 全量重入库（语料 4 本书，分钟级）；旧 `philosophy_chunks` 验证通过前不删

## Acceptance Criteria

- [ ] 入库后 `GET /rag/records` 与数据库表可查到任务与文档记录（含分块数等统计），重启后端后仍在
- [ ] 失败入库任务在 records 中标记 failed 并带 error
- [ ] 新集合 `philosophy` 内片段 payload 含 book、chapter；search 结果返回这两字段
- [ ] 论语/道德经 txt 与康德/尼采 md 入库后 chapter 有实际章节值（提取不到时为空串）
- [ ] 记录写入失败不阻断入库（日志可见）
- [ ] 入库前文本校验清洗生效：BOM/换行/控制/零宽字符规范化、链接/图片/元信息噪音行剔除，每文档日志报清洗结果
- [ ] 校验不洁文档（空/过短/乱码疑似）跳过并记录原因，records 中可见，不阻断批次

## Out of Scope

- 进行中任务（running）的完整持久化与恢复（见 TODO.md 待办，另行处理）
- 分块器按句边界升级（TODO.md 待办）
- 破坏性清洗：全半角归一、标点归一、繁简转换（古籍语义敏感，agent 阶段按需做）
- agent 系统本体（本任务只打数据层基础）

## Key Decisions

- 记录表存 PostgreSQL（用户已选）；裸 psycopg 不用 ORM，贴合项目风格且表结构即契约
- 集合名 philosophy（用户原话要求）；改名 + chapter 字段无法回填 → reset 重入库
- chapter 提取：md 标题 + txt 启发式，覆盖现有全部语料格式，空串兜底
- 源头校验清洗：保守无损清洗 + 校验门禁（不洁净跳过不阻断），保证进库文本干净
- 记录写入尽力而为：失败只记日志，不阻断入库（Qdrant 是片段数据唯一事实源）

## Risks / Deferred

- 章节启发式对未知格式可能提取不准 → 缓解：模式对全部语料实测核对后定稿；误判不丢正文（仅整行独立标记行剔除）；ingest 日志报提取章节数作审计信号；空串兜底
- 道德经文件含两本书（帛书原文 + 译文），章节标签重复 → 本次不拆文档，接受（文档拆分另行任务）
- 重入库期间服务可用性无保障（dev 阶段可接受）
- 用户需在 backend/.env 填 DATABASE_URL（docker/.env 密码一致）
