"""任务相关接口。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import models
from ..config import load_config
from ..workers.task_runner import start_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    video_path: str
    danmaku_path: Optional[str] = None
    offset_seconds: float = 0.0
    output_languages: Optional[list[str]] = None


@router.post("")
async def create_task(payload: TaskCreate):
    video_path = Path(payload.video_path)
    if not video_path.exists():
        raise HTTPException(400, f"视频文件不存在: {payload.video_path}")
    if payload.danmaku_path and not Path(payload.danmaku_path).exists():
        raise HTTPException(400, f"弹幕文件不存在: {payload.danmaku_path}")

    langs = payload.output_languages or ["zh", "en"]
    langs = [x.strip() for x in langs if x.strip() in ("zh", "en")]
    if not langs:
        langs = ["zh", "en"]

    task = models.create_task(
        video_path=str(video_path.resolve()),
        danmaku_path=str(Path(payload.danmaku_path).resolve()) if payload.danmaku_path else None,
        offset_seconds=payload.offset_seconds,
        output_languages=langs,
    )
    start_task(task["id"])
    return task


@router.get("")
async def list_tasks():
    return models.list_tasks()


@router.get("/{task_id}")
async def get_task_detail(task_id: str):
    task = models.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    task = models.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.get("status") in ("running", "pending"):
        raise HTTPException(400, "任务正在运行，无法删除")
    cfg = load_config()
    task_dir = Path(cfg.data.tasks_dir) / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)
    models.delete_task(task_id)
    return {"ok": True}
