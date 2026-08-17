# 增加部署说明文档

## Goal

为 philosophy-agent 项目编写完整的部署文档，让新人能按步骤稳定部署。文档写入 `README.md`（当前为空）。

## Background

- 项目：AI 哲学思辨代理，FastAPI 后端 + RAG 知识库
- 语料：中外哲学经典（backend/data/books，已被 .gitignore 忽略）
- 中间件：PostgreSQL 16 + Qdrant + Neo4j 5（Docker Compose）
- 后端运行方式：本地 `uv run uvicorn`，非容器化
- 前端：当前为空壳（frontend/ 下只有 .gitkeep），首页内嵌在 main.py 的 HTML 中
- 无 pyproject.toml、无 Makefile、无 CI/CD
- README.md 当前为空

## Confirmed Facts

- `start-dev.ps1` 一键启动脚本：自动拉 Docker Desktop → compose up → 等 postgres healthy → 启 uvicorn
- `docker/.env` 存中间件密码，`backend/.env` 存 LLM/API 配置，两者密码需同步
- requirements.txt 有 16 个依赖，含 torch-directml（AMD GPU 特殊配置）
- 已知坑：AMD GPU DirectML、GFW 代理、CRLF、DATABASE_URL 必须用 127.0.0.1
- 本机 Windows 环境（Git Bash + PowerShell）

## Scope

### In Scope
- 项目简介与功能说明
- 环境要求（Python、uv、Docker Desktop、Git）
- 中间件启动（Docker Compose）
- 后端依赖安装与配置（.env 配置说明）
- 启动方式（一键脚本 + 手动启动）
- API 端点说明
- 已知坑与排障指南
- 语料准备（data/books 目录说明）

### Out of Scope
- 生产环境部署（当前纯开发用途）
- 前端独立部署（尚无前端）
- CI/CD 配置
- 代码架构深度文档

## Requirements

- R1: 文档语言为中文
- R2: 覆盖从零开始的完整步骤
- R3: 包含所有依赖和配置说明
- R4: 包含已知坑和排障指南
- R5: 写入 README.md

## Acceptance Criteria

- AC1: 新人能按 README 步骤从零部署成功
- AC2: 所有 .env 配置项都有说明
- AC3: Docker 中间件和后端启动步骤分离清晰
- AC4: 已知坑（AMD GPU、GFW、127.0.0.1）有明确提示

## Decisions

- 前端目录和语料目录不写入部署文档（当前为空壳/gitignore，不影响后端部署）
