"""FastAPI 入口。"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.export import router as export_router
from .api.report import router as report_router
from .api.tasks import router as tasks_router
from .config import PROJECT_ROOT, load_config
from .database import init_db

cfg = load_config()
Path(cfg.data.tasks_dir).mkdir(parents=True, exist_ok=True)
init_db(cfg.data.db_path)

if not shutil.which("ffmpeg"):
    print("[WARN] 未在 PATH 中找到 ffmpeg，视频处理与切片导出将无法使用")
if not shutil.which("ffprobe"):
    print("[WARN] 未在 PATH 中找到 ffprobe，视频信息读取与音频切分将无法使用")

app = FastAPI(title="直播切片分析工具", version="0.2.0")

app.include_router(tasks_router)
app.include_router(report_router)
app.include_router(export_router)

WEB_DIR = PROJECT_ROOT / "app" / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")
