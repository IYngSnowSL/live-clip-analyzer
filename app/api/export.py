"""视频切片导出接口。"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import models
from ..config import load_config
from ..services.exporter import export_clips

router = APIRouter(prefix="/api/tasks", tags=["export"])


class ClipSpec(BaseModel):
    start: float
    end: float
    title: str = ""


class ExportPayload(BaseModel):
    candidate_ids: list[int] | None = None
    clips: list[ClipSpec] | None = None
    accurate: bool | None = None


def _task_dir(task_id: str) -> Path:
    cfg = load_config()
    return Path(cfg.data.tasks_dir) / task_id


def _get_task_or_404(task_id: str) -> dict:
    task = models.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


def _candidate_to_clip(c: dict) -> dict:
    start = c.get("review_start") if c.get("review_start") is not None else c.get("start")
    end = c.get("review_end") if c.get("review_end") is not None else c.get("end")
    title = c.get("review_title") or c.get("title_zh") or c.get("title_en") or ""
    return {"start": float(start), "end": float(end), "title": str(title)}


@router.post("/{task_id}/export")
async def export_task_clips(task_id: str, payload: ExportPayload):
    task = _get_task_or_404(task_id)
    cfg = load_config()
    tdir = _task_dir(task_id)

    source = tdir / "converted" / "video.mp4"
    if not source.exists():
        source = Path(task["video_path"])
    if not source.exists():
        raise HTTPException(404, "找不到可用于导出的视频文件")

    # 组装待导出切片
    clips: list[dict] = []
    if payload.candidate_ids is not None:
        ids = set(payload.candidate_ids)
        candidates = models.get_candidates(task_id)
        clips = [_candidate_to_clip(c) for c in candidates if c.get("id") in ids]
        if not clips:
            raise HTTPException(404, "未找到指定的候选切片")
    elif payload.clips is not None:
        clips = [{"start": c.start, "end": c.end, "title": c.title} for c in payload.clips]
    else:
        clips = [_candidate_to_clip(c) for c in models.get_candidates(task_id)]

    if not clips:
        raise HTTPException(400, "当前没有可导出的切片")

    # 检查时间范围
    for c in clips:
        if c["start"] < 0 or c["end"] <= c["start"]:
            raise HTTPException(400, f"切片时间无效: {c}")

    accurate = payload.accurate if payload.accurate is not None else bool(cfg.export.accurate)
    out_dir = tdir / "exports"
    results = await export_clips(
        source, clips, out_dir,
        accurate=accurate,
        concurrency=int(cfg.export.concurrency),
    )
    return {"task_id": task_id, "export_dir": str(out_dir), "files": results}


@router.get("/{task_id}/exports")
async def list_exports(task_id: str):
    _get_task_or_404(task_id)
    base = _task_dir(task_id) / "exports"
    if not base.exists():
        return []
    pattern = re.compile(r"clip_\d+_(\d+)s_(\d+)s\.mp4$")
    files = []
    for p in sorted(base.glob("*.mp4")):
        m = pattern.match(p.name)
        files.append({
            "filename": p.name,
            "start": int(m.group(1)) if m else 0,
            "end": int(m.group(2)) if m else 0,
            "title": "",
            "status": "ok",
            "size": p.stat().st_size,
        })
    return files


@router.get("/{task_id}/exports/{filename}")
async def get_export_file(task_id: str, filename: str):
    _get_task_or_404(task_id)
    base = (_task_dir(task_id) / "exports").resolve()
    path = (base / filename).resolve()
    if path.parent != base or not path.exists():
        raise HTTPException(404, "导出文件不存在")
    return FileResponse(path, media_type="video/mp4", filename=path.name)
