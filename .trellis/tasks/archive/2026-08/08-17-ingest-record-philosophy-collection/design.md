# 入库记录表与哲学 Collection 改造 — 技术设计

## 架构与边界

```
backend/app/
  database/db.py        # 连接管理 + init_db（psycopg 同步驱动）
  database/records.py   # 入库记录写/查（ingest_tasks + ingest_documents 两表）
  rag/chunker.py        # 章节提取（md 标题 + txt 章节标记启发式），chunk.metadata["chapter"]
  rag/pipeline.py       # book 清洗、per-doc 统计收集（DocumentRecord）
  rag/vector_store.py   # 默认集合 philosophy_chunks → philosophy
  api/rag.py            # 任务完成后写记录；GET /rag/records、GET /rag/records/{task_id}
  main.py               # lifespan 启动时 init_db；首页加"入库记录"卡片
```

边界：记录写入是**尽力而为**的审计层——Qdrant 仍是片段数据的唯一事实源，记录写失败只记日志、不阻断入库成功。

## 存储层（PostgreSQL，psycopg 同步驱动）

- 新依赖 `psycopg[binary]>=3.1`（应用是同步代码 + threading 线程模型，用同步驱动贴合现状；不用 SQLAlchemy，贴合项目"裸依赖"风格——表结构稳定，将来 agent 系统要 ORM 可直接加，无需改表）
- `settings.database_url` 已存在；代码统一规范化：`postgresql+asyncpg://` → `postgresql://`（兼容 .env.example 里的旧示例）。DATABASE_URL 为空 → 记录功能禁用，启动时打一次 warning
- 两表结构：

```sql
CREATE TABLE IF NOT EXISTS ingest_tasks (
  id UUID PRIMARY KEY,
  kind TEXT NOT NULL,              -- directory | file | upload
  path TEXT NOT NULL,
  reset BOOLEAN NOT NULL DEFAULT FALSE,
  status TEXT NOT NULL,            -- done | failed
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  documents INT, documents_new INT, documents_updated INT, documents_unchanged INT,
  chunks INT, embedded INT, skipped INT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS ingest_documents (
  task_id UUID NOT NULL REFERENCES ingest_tasks(id) ON DELETE CASCADE,
  document_id TEXT NOT NULL,       -- uuid5 稳定文档 id
  filename TEXT NOT NULL,
  title TEXT NOT NULL,
  book TEXT,
  path TEXT NOT NULL,
  size BIGINT, mtime DOUBLE PRECISION,
  chunks INT NOT NULL, embedded INT NOT NULL, skipped INT NOT NULL,
  status TEXT NOT NULL,            -- new | updated | unchanged
  PRIMARY KEY (task_id, document_id)
);
```

- 数据流：`run_ingest_job` 拿到 IngestResult 后，单事务写入 task + documents；失败任务也落一条 `status='failed'` + error（调试与 agent 审计都有用）

## Qdrant 集合：philosophy

- `VectorStore` 默认集合改名 `philosophy`；payload 新增 `book`（清洗后书名）与 `chapter`（提取值或空串），保留 source/filename/size/mtime/title 原字段
- 迁移：改名 + chapter 字段无法原地回填 → **reset 全量重入库**（语料仅 4 本书，分钟级）。旧 `philosophy_chunks` 集合在验证前不删除，作为回滚点；验证通过后手动删（`DELETE /collections/philosophy_chunks`）

## 文本校验与清洗（新模块 backend/app/rag/cleaner.py）

数据流：`load_file`（解码/转换）→ `clean_text`（校验+清洗）→ `chunk_document`（分块+章节）。

- `CleanResult{text, removed_lines, warnings, valid}`；pipeline 对每个文档在 load 之后、分块之前调用
- 无损清洗（不改文意，古籍语料敏感）：
  - 规范化：去 BOM；`\r\n`/`\r` → `\n`；去 null 字节与控制字符（保留 `\n`/`\t`）；去零宽字符（U+200B-200D、U+FEFF）
  - 噪音行剔除：纯链接行 `^\s*\[[^\]]*\]\([^)]*\)\s*$`、纯图片行 `^\s*!\[[^\]]*\]\([^)]*\)\s*$`、文件头 markitdown 元信息块（`^\*\*[^*]+:\*\*` 起始段）——epub 转换残留，实测尼采 93/4736、康德 43/1730 chunk
- 校验门禁（不洁净即跳过，不阻断批次）：
  - 清洗后空 / 少于 20 字 → `valid=False`，记录 status='skipped' + 原因
  - 乱码疑似（U+FFFD 占比 > 0.1%，或 CJK 占比 < 20%）→ 打 warning 不阻断（解码层已有 loader 的 utf-8→gb18030 兜底）
- 可观测：新增 ingest 阶段 `clean`（STAGE_LABELS 加「文本清洗」）；每文档日志「清洗: 移除 N 行噪音, 警告: …」；警告写入 `ingest_documents.warning`（表加列，status 增 'skipped'）
- 明确不做：全半角归一、标点归一、繁简转换（哲学古籍语义敏感，属破坏性清洗，留待 agent 阶段按需做）
- 链接/图片行过滤从 chunker 上移到 cleaner（源头清洗单一职责）；chunker 只管分块 + 章节跟踪

## 章节提取（chunker.py）

- 预扫描文档行，识别章节标记，后续段落归入当前 chapter。模式**先验后定**：实现时对全部 4 本语料跑提取、打印每本书的章节清单人工核对后再定稿（实测风格见下）
  - markdown 标题：`^#{1,6}\s+(.+)$`（康德/尼采 md 书的 `## 导言`、`### 一 纯粹知识与经验的知识之区别`）
  - txt 独立标记行：`^\s*(?:第[一二三四五六七八九十百千\d]+[篇章节卷回]|[\u4e00-\u9fa5·]{1,15}第[一二三四五六七八九十百千\d]+)\s*$`（道德经译文「第一章」、论语「学而第一」）
  - txt 行首编号：`^\s*\d{1,3}\.`（道德经帛书原文「01.道可道也…」，标签「第01章」；帛书版前言「2.部分帛书版补全文字…」会误匹配，接受——审计信号可见，正文不丢）
- 剔除规则（防误判丢内容，实测关键）：仅「整行独立」的标记行不进 chunk 文本；「编号+正文同行」只剥编号前缀，正文必须保留
- 无章节可提取的文档 chapter 为空串；ingest 日志按文档报「提取章节数 N」，N=0 的文档一眼可见（审计信号，发现漏网格式及时补模式）
- 已知取舍：道德经一个文件含帛书原文 + 译文精简版两本书，「第X章」标签重复出现；文档拆分是独立任务，本次不做
- 副作用：chunk 文本与哈希全部变化 → 本轮必然全量重入库（与集合改名一致）

## book 清洗（pipeline.py）

- `_clean_title` 基础上剥离尾部括号片段（论语文件名带 `(z-library.sk, 1lib.sk, z-lib.sk)`）→ book；title 字段保留原清洗结果不动

## API 与前端

- `GET /rag/records?limit=20` → 最近任务列表（含全部统计字段）
- `GET /rag/records/{task_id}` → 任务概要 + 该任务的 per-doc 明细
- 首页加"入库记录"卡片：拉最近任务列表渲染，点击展开 per-doc 明细（vanilla JS，风格同现有面板）
- `/rag/search` 响应增加 book/chapter 字段

## 权衡与回滚

- 裸 psycopg vs ORM：选前者；表结构即契约，将来无痛升级
- 尽力而为写入：记录失败不失败入库；日志可见
- 章节启发式对异形格式不完美 → 空串兜底，不阻断入库
- 回滚：新集合验证前不删旧集合；代码回退即回旧行为
