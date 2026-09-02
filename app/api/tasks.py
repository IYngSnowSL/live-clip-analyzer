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


class BatchCreate(BaseModel):
    video_paths: list[str]
    danmaku_path: Optional[str] = None
    offset_seconds: float = 0.0


@router.post("/batch")
async def create_tasks_batch(payload: BatchCreate):
    """批量创建任务：一次传入多个视频路径，并行分析。"""
    if not payload.video_paths:
        raise HTTPException(400, "请至少提供一个视频路径")
    if len(payload.video_paths) > 20:
        raise HTTPException(400, "单次批量最多 20 个视频")
    tasks = []
    for vp in payload.video_paths:
        video_path = Path(vp)
        if not video_path.exists():
            raise HTTPException(400, f"视频文件不存在: {vp}")
        task = models.create_task(
            video_path=str(video_path.resolve()),
            danmaku_path=str(Path(payload.danmaku_path).resolve()) if payload.danmaku_path else None,
            offset_seconds=payload.offset_seconds,
        )
        start_task(task["id"])
        tasks.append(task)
    return tasks


@router.post("")
async def create_task(payload: TaskCreate):
    video_path = Path(payload.video_path)
    if not video_path.exists():
        raise HTTPException(400, f"视频文件不存在: {payload.video_path}")
    if payload.danmaku_path and not Path(payload.danmaku_path).exists():
        raise HTTPException(400, f"弹幕文件不存在: {payload.danmaku_path}")

    task = models.create_task(
        video_path=str(video_path.resolve()),
        danmaku_path=str(Path(payload.danmaku_path).resolve()) if payload.danmaku_path else None,
        offset_seconds=payload.offset_seconds,
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
async def delete_task(task_id: str, force: bool = False):
    task = models.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.get("status") in ("running", "pending") and not force:
        raise HTTPException(400, "任务正在运行，无法删除（可加 ?force=true 强制删除）")
    cfg = load_config()
    task_dir = Path(cfg.data.tasks_dir) / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)
    models.delete_task(task_id)
    return {"ok": True}
