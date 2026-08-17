<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

# 项目说明（Philosophy Agent）

AI 哲学思辨代理：FastAPI 后端 + 本地 RAG 知识库，语料为中外哲学经典（论语、道德经、康德、尼采等，位于 `backend/data/books`）。仓库注释、提交、界面文案均为中文，回复用户用中文。

## 目录结构

- `backend/app/` — FastAPI 应用。`api/` 路由（chat/rag/graph/health），`core/config.py` 环境配置，`rag/` 完整 RAG 管线（loader → chunker → embedding → vector_store → batch_to_md），planner/memory/tools/services 目前是空壳
- `backend/data/` — 语料库（books/sources/test_corpus，已被 .gitignore 忽略，不入库）
- `docker/` — docker-compose.yml：postgres / qdrant / neo4j 三个容器；Qdrant 是 RAG 检索库，postgres 存入库记录，neo4j 在入库时同步写「书 → 章节 → 片段」结构图（`rag/neo4j_store.py`，best-effort）
- `start-dev.ps1` — 一键启动：自动拉起 Docker Desktop → compose up → 等 postgres healthy → `uv run uvicorn app.main:app --reload`（8000 端口）
- `frontend/`、`prompts/`、`scripts/` — 空壳（.gitkeep）
- `TODO.md` — 项目待办（待办/已解决两节），后续跟进项追加在这里
- 根路由 `main.py` 内嵌 HTML 首页（RAG 测试面板，vanilla JS）

## 开发运行

- 一键启动：`powershell -ExecutionPolicy Bypass -File .\start-dev.ps1`（需要 uv；Docker Desktop 未运行会自动拉起）
- 单独起后端：在 `backend/` 下 `uv run uvicorn app.main:app --reload`
- **无测试/无 lint/无 typecheck 配置**（requirements.txt 裸依赖清单）
- Git Bash 里 docker 不在 PATH（Docker Desktop 按用户安装），用完整路径或 PowerShell；start-dev.ps1 已处理
- 代码库有 `.codegraph/` 索引，跨文件问题优先 `codegraph.cmd explore/impact`

## 配置（backend/.env，模板见 .env.example）

- LLM 走**中转站 relay，Anthropic Messages 协议**（LLM_PROVIDER=anthropic，LLM_BASE_URL 指向中转站，LLM_MODEL 默认 deepseek-v4-flash）；不是 OpenAI 直连
- EMBEDDING_MODEL=BAAI/bge-m3，EMBEDDING_DEVICE=auto|dml|cpu
- 中间件凭据在 `docker/.env`（POSTGRES_*/NEO4J_PASSWORD），改密码需与 backend/.env 同步

## RAG 关键行为

- 端点：`POST /rag/ingest`（异步 202 + job_id，阶段进度 + 执行日志，轮询 `/rag/ingest/status/{job_id}`）、`/rag/prune`、`/rag/search`、`/rag/upload`（FormData 上传）
- ingest 完成/失败通过 ntfy（话题 louisding_9527）推送到手机
- 文件指纹（size+mtime）快跳过 + 片段哈希兜底；文档清理需显式调 prune
- Qdrant upsert 分批 500 点/批（单请求 JSON 低于 32MB 上限），删文档按 id 前缀分片 1000
- Neo4j 图同步（`rag/neo4j_store.py`）：入库 upsert 后同批写入 `Book -HAS_CHAPTER-> Chapter -HAS_CHUNK-> Chunk`（无章节片段直挂 Book）；全部 MERGE 幂等；`reset=True` 清空图、prune 级联清理孤儿；未配置 `NEO4J_URI` 或写入失败仅告警，不影响 ingest 主流程
- loader 编码回退：utf-8 → gb18030 → markitdown；markitdown 返回字面量 "None" 视为失败
- 任务表未持久化，服务重启后任务丢失（当前靠幂等重跑兜底）

## 已知坑（改代码前必读）

- **AMD GPU 向量化（本机 RX 7700 XT）**：torch-directml（torch 2.4.1）+ `transformers<5`（requirements.txt 已锁）；DirectML 注册（rename_privateuse1_backend、inference_mode→no_grad）必须在 `import sentence_transformers` **之前**（embedding.py 顶层完成）；fp16 + batch 16 必须（fp32 长片段 OOM）；**fp16 下必须 `model_kwargs={"attn_implementation": "eager"}`**，默认 SDPA 会崩 `dml_util.h:52 Check failed`。改这些参数须在本机 GPU 实测
- 本机 GitHub/HuggingFace 直连被墙：走代理 127.0.0.1:7897，或 HF 用 hf-mirror.com；本地回环请求要走 NO_PROXY（Win 系统代理在注册表）
- git 提交后文件会变 CRLF：编辑前先 `sed -i 's/\r$//'` 去回车，否则 Edit 匹配失败
- 开发期 CORS 全放开（`allow_origins=["*"]`），联调后再收紧

## Trellis

本项目由 Trellis 管理：工作流见 `.trellis/workflow.md`，各层编码规范在 `.trellis/spec/`（写代码前先读对应层），任务在 `.trellis/tasks/`。**不要修改 AGENTS.md 的 TRELLIS 区块内部**（会被 `trellis update` 覆盖），项目说明追加在本区块之外。
