"""FastAPI 入口。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.report import router as report_router
from .api.tasks import router as tasks_router
from .config import PROJECT_ROOT, load_config
from .database import init_db

cfg = load_config()
Path(cfg.data.tasks_dir).mkdir(parents=True, exist_ok=True)
init_db(cfg.data.db_path)

app = FastAPI(title="直播切片分析工具", version="0.1.0")

app.include_router(tasks_router)
app.include_router(report_router)

WEB_DIR = PROJECT_ROOT / "app" / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")
