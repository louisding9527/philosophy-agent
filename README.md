# Philosophy Agent

AI 哲学思辨代理。基于 FastAPI 后端 + 本地 RAG 知识库，语料为中外哲学经典（论语、道德经、康德、尼采等），通过向量检索实现哲学文献的语义搜索与智能问答。

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI + uvicorn |
| 向量数据库 | Qdrant（语义检索） |
| 关系数据库 | PostgreSQL 16（入库记录） |
| 图数据库 | Neo4j 5 Community（文档结构图） |
| 向量化模型 | BAAI/bge-m3（sentence-transformers） |
| LLM | 通过中转站调用，Anthropic Messages 协议 |
| 容器化 | Docker Compose（中间件） |

## 环境要求

- **Python** 3.11+
- **uv**（Python 包管理器）：[安装文档](https://docs.astral.sh/uv)
- **Docker Desktop**：运行 PostgreSQL / Qdrant / Neo4j 中间件
- **Git**
- **操作系统**：Windows（当前开发环境）

## 快速开始（一键启动）

```powershell
# 1. 克隆仓库
git clone <repo-url>
cd philosophy-agent

# 2. 配置环境变量
Copy-Item backend\.env.example backend\.env
# 编辑 backend\.env，填入 LLM_API_KEY 等真实值

# 3. 一键启动（自动拉起 Docker Desktop + 启动中间件 + 启动后端）
.\start-dev.ps1
```

如果 PowerShell 策略阻止执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

启动后访问 http://127.0.0.1:8000 使用 Web 面板。

## 手动部署（分步）

### 第一步：启动中间件容器

```bash
cd docker
docker compose up -d
```

三个容器启动后：

| 容器 | 端口 | 用途 |
|------|------|------|
| philosophy-postgres | 5432 | 入库记录表 |
| philosophy-qdrant | 6333（REST）/ 6334（gRPC） | 向量检索 |
| philosophy-neo4j | 7474（浏览器）/ 7687（Bolt） | 文档结构图 |

验证容器健康：

```bash
# PostgreSQL
docker inspect --format '{{.State.Health.Status}}' philosophy-postgres

# Neo4j（等待 7687 端口可连接）
```

### 第二步：配置环境变量

复制模板并编辑：

```bash
cp backend/.env.example backend/.env
```

#### docker/.env（中间件密码）

已在 `docker/.env` 中预设，默认值：

```
POSTGRES_USER=philosophy
POSTGRES_PASSWORD=philosophy_dev_2026
POSTGRES_DB=philosophy
NEO4J_PASSWORD=philosophy_dev_2026
```

> **注意**：修改密码后需同步更新 `backend/.env` 中对应的连接字符串。

#### backend/.env（后端配置）

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `LLM_API_KEY` | LLM 中转站 API Key | `sk-xxx` |
| `LLM_BASE_URL` | 中转站地址 | `https://opencode.ai/zen/go/v1` |
| `LLM_PROVIDER` | 协议类型 | `anthropic`（默认）或 `openai` |
| `LLM_MODEL` | 模型名称 | `deepseek-v4-flash`（默认） |
| `EMBEDDING_MODEL` | 向量化模型 | `BAAI/bge-m3`（默认） |
| `EMBEDDING_DEVICE` | 向量化设备 | `auto`（自动检测 GPU）/ `dml` / `cpu` |
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://philosophy:密码@127.0.0.1:5432/philosophy` |
| `QDRANT_URL` | Qdrant 地址 | `http://localhost:6333` |
| `NEO4J_URI` | Neo4j Bolt 地址 | `bolt://localhost:7687` |
| `NEO4J_PASSWORD` | Neo4j 密码 | 与 `docker/.env` 一致 |

> **关键**：`DATABASE_URL` 必须用 `127.0.0.1`，不能用 `localhost`。本机 `localhost` 会解析到 IPv6 `::1`，导致连接挂起。

### 第三步：安装后端依赖

```bash
cd backend
uv sync
```

这会根据 `requirements.txt` 创建 `.venv` 并安装所有依赖。

### 第四步：启动后端

```bash
cd backend
uv run uvicorn app.main:app --reload
```

后端启动后监听 http://127.0.0.1:8000。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health/` | 健康检查 |
| POST | `/rag/search` | 语义搜索 |
| POST | `/rag/ingest` | 异步入库（返回 job_id） |
| GET | `/rag/ingest/status/{job_id}` | 查询入库进度 |
| GET | `/rag/records` | 入库任务记录列表 |
| GET | `/rag/records/{task_id}` | 单条任务详情 |
| POST | `/rag/prune` | 清理孤立片段 |
| POST | `/rag/upload` | 上传文件并入库 |

## 已知坑与排障

### AMD GPU 向量化（RX 7700 XT）

本机使用 `torch-directml` 加速向量化，有以下约束：

- `transformers` 必须 `<5`（requirements.txt 已锁定）
- 必须使用 `fp16` + batch 16（fp32 长片段会 OOM）
- `fp16` 下必须设置 `attn_implementation="eager"`，默认 SDPA 会崩溃报错 `dml_util.h:52 Check failed`

如果遇到向量化崩溃，检查 `embedding.py` 中的 `model_kwargs` 配置。

### GFW 代理（GitHub / HuggingFace 被墙）

- 代理地址：`127.0.0.1:7897`（需在系统代理中配置）
- HuggingFace 模型下载可使用镜像：`https://hf-mirror.com`
- Python 进程内需设置 `NO_PROXY=localhost,127.0.0.1` 避免本地请求走代理

### CRLF 换行符

Git 提交后文件可能变为 CRLF。编辑前先转换：

```bash
sed -i 's/\r$//' <file>
```

否则代码编辑器的字符串匹配可能失败。

### Docker 相关

- Docker Desktop 按用户安装时，Git Bash 中 `docker` 命令可能不在 PATH，使用 PowerShell 或完整路径
- 容器数据持久化在 Docker named volumes（`postgres_data`、`qdrant_data`、`neo4j_data`），删除容器不影响数据
- 重置数据：`docker compose down -v`（会删除所有存储数据）

## 项目结构

```
philosophy-agent/
├── backend/
│   ├── app/
│   │   ├── api/          # 路由（rag/health/chat/graph）
│   │   ├── core/         # 配置（config.py）
│   │   ├── rag/          # RAG 管线（loader/chunker/embedding/vector_store）
│   │   └── main.py       # FastAPI 入口（含内嵌 Web 面板）
│   ├── data/             # 语料库（.gitignore 忽略）
│   ├── requirements.txt  # Python 依赖
│   └── .env.example      # 环境变量模板
├── docker/
│   ├── docker-compose.yml
│   └── .env              # 中间件密码
├── frontend/             # 前端（待开发）
├── start-dev.ps1         # 一键启动脚本
└── TODO.md               # 项目待办
```

## 停止服务

```bash
# 停止后端：Ctrl+C

# 停止中间件容器（数据保留）
cd docker
docker compose down

# 彻底清理（删除所有数据）
docker compose down -v
```
