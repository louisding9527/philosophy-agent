from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.health import router as health_router
from app.api.chat import router as chat_router
from app.api.rag import router as rag_router
from app.api.graph import router as graph_router

app = FastAPI(
    title="Philosophy Agent",
    description="AI 哲学思辨代理",
    version="0.1.0",
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
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460);
                color: #fff;
            }
            .container {
                text-align: center;
                padding: 3rem;
            }
            h1 { font-size: 3rem; margin-bottom: 0.5rem; }
            p { font-size: 1.2rem; opacity: 0.8; }
            a {
                display: inline-block;
                margin-top: 2rem;
                padding: 0.8rem 2rem;
                background: #e94560;
                color: #fff;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
            }
            a:hover { background: #c73e54; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🧠 Philosophy Agent</h1>
            <p>AI 哲学思辨代理 — 探索思想的边界</p>
            <a href="/docs">查看 API 文档</a>
        </div>
    </body>
    </html>
    """


app.include_router(health_router)
app.include_router(chat_router)
app.include_router(rag_router)
app.include_router(graph_router)
