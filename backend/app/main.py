import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.api.health import router as health_router
from app.api.chat import router as chat_router
from app.api.rag import router as rag_router
from app.api.graph import router as graph_router
from app.database.db import enabled as db_enabled
from app.database.db import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化入库记录表；未配置 DATABASE_URL 则记录功能降级禁用。"""
    if db_enabled():
        try:
            init_db()
            logger.info("入库记录表就绪（PostgreSQL）")
        except Exception as exc:
            logger.warning("入库记录表初始化失败，记录功能禁用：%s", exc)
    else:
        logger.warning("DATABASE_URL 未配置，入库记录功能禁用")
    yield


app = FastAPI(
    title="Philosophy Agent",
    description="AI 哲学思辨代理",
    version="0.1.0",
    lifespan=lifespan,
)

# 开发阶段放开跨域，前端联调后再收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Philosophy Agent</title>
        <style>
            body {
                font-family: system-ui, -apple-system, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460);
                color: #fff;
            }
            .container {
                text-align: center;
                padding: 3rem 1rem 1rem;
            }
            h1 { font-size: 2.6rem; margin-bottom: 0.5rem; }
            p { font-size: 1.1rem; opacity: 0.8; }
            a {
                display: inline-block;
                margin-top: 1.5rem;
                padding: 0.7rem 2rem;
                background: #e94560;
                color: #fff;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
            }
            a:hover { background: #c73e54; }
            .panel { width: min(760px, 92vw); padding: 0 1rem 3rem; }
            .panel h2 {
                text-align: center;
                color: #ffd166;
                margin: 1.5rem 0 1rem;
                font-size: 1.4rem;
            }
            .card {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
                padding: 1.1rem 1.2rem;
                margin-bottom: 1rem;
            }
            .card h3 { margin: 0 0 0.7rem; font-size: 1rem; color: #8ecae6; }
            input[type="text"], input[type="file"] {
                width: 100%;
                box-sizing: border-box;
                padding: 0.55rem 0.7rem;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 6px;
                background: rgba(0, 0, 0, 0.25);
                color: #fff;
                font-size: 0.9rem;
            }
            button {
                padding: 0.5rem 1.2rem;
                background: #e94560;
                color: #fff;
                border: none;
                border-radius: 6px;
                font-weight: 600;
                cursor: pointer;
            }
            button:hover { background: #c73e54; }
            .row { display: flex; gap: 0.6rem; align-items: center; }
            .row input[type="text"] { flex: 1; margin-bottom: 0; }
            .muted { color: #9aa5b1; font-size: 0.85rem; margin: 0.5rem 0; }
            .bar {
                height: 8px;
                background: rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                overflow: hidden;
                margin: 0.4rem 0;
            }
            .bar-fill {
                height: 100%;
                width: 0;
                background: linear-gradient(90deg, #e94560, #ffd166);
                transition: width 0.3s;
            }
            pre {
                background: rgba(0, 0, 0, 0.35);
                border-radius: 6px;
                padding: 0.6rem;
                font-size: 0.8rem;
                overflow-x: auto;
                margin: 0.5rem 0 0;
                white-space: pre-wrap;
                word-break: break-all;
            }
            .hit {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 8px;
                padding: 0.6rem 0.8rem;
                margin-bottom: 0.5rem;
            }
            .hit-head { font-size: 0.8rem; margin-bottom: 0.3rem; }
            .score { color: #ffd166; font-weight: 600; margin-right: 0.6rem; }
            .file { color: #8ecae6; }
            .hit-text { font-size: 0.85rem; line-height: 1.5; color: #e6e6ef; }
            .log {
                background: rgba(0, 0, 0, 0.35);
                border-radius: 6px;
                padding: 0.6rem;
                font-size: 0.78rem;
                font-family: ui-monospace, Consolas, monospace;
                line-height: 1.6;
                max-height: 220px;
                overflow-y: auto;
                margin-top: 0.5rem;
                color: #c9d1d9;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🧠 Philosophy Agent</h1>
            <p>AI 哲学思辨代理 — 探索思想的边界</p>
            <a href="/docs">查看 API 文档</a>
        </div>

        <div class="panel">
            <h2>📚 RAG 知识库</h2>

            <div class="card">
                <h3>📥 入库（目录或文件，增量同步）</h3>
                <div class="row">
                    <input type="text" id="ingest-path" placeholder="语料路径，如 D:/agents/zhexue/philosophy-agent/backend/data/books">
                    <button onclick="startIngest()">开始入库</button>
                </div>
                <label class="muted" style="display:flex;align-items:center;gap:0.4rem;margin-top:0.4rem;">
                    <input type="checkbox" id="ingest-reset" style="width:auto;"> 清空集合后全量重建
                </label>
                <div class="muted" id="ingest-progress"></div>
                <div class="bar"><div class="bar-fill" id="ingest-bar"></div></div>
                <div class="log" id="ingest-log"></div>
                <pre id="ingest-result"></pre>
            </div>

            <div class="card">
                <h3>📤 上传文件入库</h3>
                <div class="row">
                    <input type="file" id="upload-file" style="margin-bottom:0;">
                    <button onclick="uploadFile()">上传入库</button>
                </div>
                <pre id="upload-result"></pre>
            </div>

            <div class="card">
                <h3>🔍 语义检索</h3>
                <div class="row">
                    <input type="text" id="search-query" placeholder="输入问题，如：什么是先验综合判断">
                    <input type="number" id="search-topk" value="5" min="1" max="20" style="width:70px;margin-bottom:0;">
                    <button onclick="doSearch()">检索</button>
                </div>
                <div id="search-result"></div>
            </div>

            <div class="card">
                <h3>🧹 清理已删除文档</h3>
                <div class="row">
                    <input type="text" id="prune-path" placeholder="语料目录路径（与入库一致）">
                    <button onclick="doPrune()">清理</button>
                </div>
                <pre id="prune-result"></pre>
            </div>

            <div class="card">
                <h3>📋 入库记录</h3>
                <button onclick="loadRecords()">刷新记录</button>
                <div id="records-result"></div>
            </div>
        </div>

        <script>
            function esc(s) {
                return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
            }
            async function api(url, options) {
                try {
                    const r = await fetch(url, options);
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) return { detail: data.detail || ("HTTP " + r.status) };
                    return data;
                } catch (e) {
                    return { detail: "网络错误: " + e.message };
                }
            }
            function show(id, text) { document.getElementById(id).textContent = text; }

            async function startIngest() {
                const path = document.getElementById("ingest-path").value.trim();
                if (!path) { alert("请填写语料路径"); return; }
                show("ingest-result", "");
                show("ingest-progress", "启动中…");
                document.getElementById("ingest-bar").style.width = "0";
                document.getElementById("ingest-log").innerHTML = "";
                let lastLogLen = 0;
                const stageNames = {
                    title: "书名优化", convert: "格式转换", clean: "文本清洗", chunk: "分块",
                    embed: "向量化", upsert: "写入向量库",
                    skip: "指纹匹配，跳过", done: "完成"
                };
                const res = await api("/rag/ingest", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path: path, reset: document.getElementById("ingest-reset").checked })
                });
                if (res.detail) { show("ingest-progress", ""); show("ingest-result", res.detail); return; }
                const timer = setInterval(async () => {
                    const s = await api("/rag/ingest/status/" + res.job_id);
                    if (s.detail) { clearInterval(timer); show("ingest-progress", ""); show("ingest-result", s.detail); return; }
                    const total = s.total_documents || 1;
                    const pct = s.status === "running" ? Math.round((s.current_index + 1) / total * 100) : 100;
                    document.getElementById("ingest-bar").style.width = pct + "%";
                    const stageLabel = stageNames[s.stage] || s.stage || "";
                    if (s.status === "running") {
                        show("ingest-progress", "处理中 " + (s.current_file || "…") + "（" + (s.current_index + 1) + "/" + total + " 文档）" + (stageLabel ? " · " + stageLabel : ""));
                    } else {
                        clearInterval(timer);
                        show("ingest-progress", "");
                        show("ingest-result", JSON.stringify(s.status === "done" ? s.result : { status: s.status, error: s.error }, null, 2));
                    }
                    if (s.log && s.log.length > lastLogLen) {
                        const logEl = document.getElementById("ingest-log");
                        logEl.insertAdjacentHTML("beforeend", s.log.slice(lastLogLen).map(l => "<div>" + esc(l) + "</div>").join(""));
                        lastLogLen = s.log.length;
                        logEl.scrollTop = logEl.scrollHeight;
                    }
                }, 1500);
            }

            async function uploadFile() {
                const f = document.getElementById("upload-file").files[0];
                if (!f) { alert("请选择文件"); return; }
                show("upload-result", "上传处理中…（大文件需数秒）");
                const fd = new FormData();
                fd.append("file", f);
                const res = await api("/rag/upload", { method: "POST", body: fd });
                show("upload-result", JSON.stringify(res, null, 2));
            }

            async function doSearch() {
                const q = document.getElementById("search-query").value.trim();
                if (!q) { alert("请输入问题"); return; }
                const top_k = parseInt(document.getElementById("search-topk").value) || 5;
                const hits = await api("/rag/search", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ query: q, top_k: top_k })
                });
                const el = document.getElementById("search-result");
                if (!Array.isArray(hits)) { el.innerHTML = "<pre>" + esc(JSON.stringify(hits)) + "</pre>"; return; }
                if (hits.length === 0) { el.innerHTML = '<p class="muted">无结果</p>'; return; }
                el.innerHTML = hits.map(h =>
                    '<div class="hit"><div class="hit-head"><span class="score">' + h.score.toFixed(4) +
                    '</span><span class="file">' + esc(h.title || h.filename || "") + '</span></div>' +
                    '<div class="hit-text">' + esc(h.text.length > 150 ? h.text.slice(0, 150) + "…" : h.text) + '</div></div>'
                ).join("");
            }

            async function doPrune() {
                const path = document.getElementById("prune-path").value.trim();
                if (!path) { alert("请填写语料目录路径"); return; }
                show("prune-result", "");
                const res = await api("/rag/prune", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path: path })
                });
                show("prune-result", JSON.stringify(res, null, 2));
            }

            async function loadRecords() {
                const el = document.getElementById("records-result");
                el.innerHTML = '<p class="muted">加载中…</p>';
                const data = await api("/rag/records?limit=20");
                if (data.detail) { el.innerHTML = "<pre>" + esc(JSON.stringify(data)) + "</pre>"; return; }
                if (!Array.isArray(data) || data.length === 0) { el.innerHTML = '<p class="muted">暂无记录</p>'; return; }
                const rows = data.map(t => {
                    const started = String(t.started_at || "").replace("T", " ").slice(0, 19);
                    const stat = t.documents != null ? t.documents + " 文档 / " + t.chunks + " 片段" : "—";
                    return '<tr style="border-top:1px solid rgba(255,255,255,0.08);cursor:pointer;" onclick="loadRecordDetail(\'' + t.id + '\')">' +
                        '<td style="padding:4px;white-space:nowrap;">' + started + '</td>' +
                        '<td style="padding:4px;">' + t.kind + '</td>' +
                        '<td style="padding:4px;word-break:break-all;">' + esc(t.path) + '</td>' +
                        '<td style="padding:4px;">' + (t.status === "done" ? "✅ 完成" : "❌ 失败") + '</td>' +
                        '<td style="padding:4px;">' + stat + '</td></tr>';
                }).join("");
                el.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:0.8rem;">' +
                    '<tr><th style="text-align:left;padding:4px;">时间</th><th style="text-align:left;padding:4px;">类型</th>' +
                    '<th style="text-align:left;padding:4px;">路径</th><th style="text-align:left;padding:4px;">状态</th>' +
                    '<th style="text-align:left;padding:4px;">文档/片段</th></tr>' + rows +
                    '</table><div id="record-detail"></div>';
            }

            async function loadRecordDetail(taskId) {
                const el = document.getElementById("record-detail");
                el.innerHTML = '<p class="muted">加载中…</p>';
                const data = await api("/rag/records/" + taskId);
                if (data.detail) { el.innerHTML = "<pre>" + esc(JSON.stringify(data)) + "</pre>"; return; }
                const docs = (data.documents || []).map(d =>
                    '<div class="hit"><div class="hit-head"><span class="file">' + esc(d.filename) + '</span>' +
                    '<span class="muted"> · ' + esc(d.book || "") + '</span>' +
                    '<span class="muted"> · 片段 ' + d.chunks + '（嵌入 ' + d.embedded + '）</span>' +
                    '<span class="muted"> · ' + d.status + '</span></div>' +
                    (d.warning ? '<div class="hit-text" style="color:#ffd166;">⚠ ' + esc(d.warning) + '</div>' : '') +
                    '</div>'
                ).join("") || '<p class="muted">无文档明细</p>';
                el.innerHTML = docs;
            }
        </script>
    </body>
    </html>
    """


app.include_router(health_router)
app.include_router(chat_router)
app.include_router(rag_router)
app.include_router(graph_router)
