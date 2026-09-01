"""FastAPI 入口。"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.export import router as export_router
from .api.files import router as files_router
from .api.report import router as report_router
from .api.tasks import router as tasks_router
from .config import PROJECT_ROOT, load_config
from .database import init_db
from .models import mark_interrupted_tasks

cfg = load_config()
Path(cfg.data.tasks_dir).mkdir(parents=True, exist_ok=True)
init_db(cfg.data.db_path)
interrupted = mark_interrupted_tasks()
if interrupted:
    print(f"[INFO] 已将 {interrupted} 个因服务重启而中断的任务标记为 failed")

if not shutil.which("ffmpeg"):
    print("[WARN] 未在 PATH 中找到 ffmpeg，视频处理与切片导出将无法使用")
if not shutil.which("ffprobe"):
    print("[WARN] 未在 PATH 中找到 ffprobe，视频信息读取与音频切分将无法使用")

app = FastAPI(title="直播切片分析工具", version=__version__)

app.include_router(tasks_router)
app.include_router(report_router)
app.include_router(export_router)
app.include_router(files_router)

WEB_DIR = PROJECT_ROOT / "app" / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")
