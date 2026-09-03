"""任务相关接口。"""
from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import models
from ..config import load_config
from ..workers.task_runner import cancel_task, start_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    video_path: str
    danmaku_path: Optional[str] = None
    offset_seconds: float = 0.0


class BatchCreate(BaseModel):
    video_paths: list[str]
    danmaku_path: Optional[str] = None
    offset_seconds: float = 0.0


def _auto_danmaku(video_path: Path) -> str | None:
    """自动查找视频同目录的同名弹幕 XML（如 live.flv → live.xml）。"""
    sibling = video_path.with_suffix(".xml")
    return str(sibling) if sibling.exists() else None


def _check_offset(offset: float) -> float:
    """弹幕时间偏移校验：必须是非负有限数值。"""
    try:
        offset = float(offset)
    except (TypeError, ValueError):
        raise HTTPException(400, "offset_seconds 必须是数值")
    if not math.isfinite(offset) or offset < 0:
        raise HTTPException(400, "offset_seconds 必须是非负有限数值")
    return offset


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
        danmaku = payload.danmaku_path or _auto_danmaku(video_path)
        offset = _check_offset(payload.offset_seconds)
        task = models.create_task(
            video_path=str(video_path.resolve()),
            danmaku_path=str(Path(danmaku).resolve()) if danmaku else None,
            offset_seconds=offset,
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

    # 未填弹幕时自动查找同目录同名 .xml；显式传入的弹幕优先
    danmaku = payload.danmaku_path
    auto_danmaku = None
    if not danmaku:
        auto_danmaku = _auto_danmaku(video_path)
        danmaku = auto_danmaku

    offset = _check_offset(payload.offset_seconds)
    task = models.create_task(
        video_path=str(video_path.resolve()),
        danmaku_path=str(Path(danmaku).resolve()) if danmaku else None,
        offset_seconds=offset,
    )
    if auto_danmaku:
        task["_auto_danmaku"] = True  # 仅供前端提示，不落库
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
    # 先取消在飞的后台协程（强制删除时任务可能还在转写/打轴），
    # 避免删除后 ffmpeg 继续跑、LLM/ASR 继续计费、目录被重建
    cancel_task(task_id)
    cfg = load_config()
    task_dir = Path(cfg.data.tasks_dir) / task_id
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)
    models.delete_task(task_id)
    return {"ok": True}
