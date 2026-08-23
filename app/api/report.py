"""报告 / 场景 / 候选 / 复核 / 文件接口。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .. import models
from ..config import load_config

router = APIRouter(prefix="/api/tasks", tags=["report"])


def _task_dir(task_id: str) -> Path:
    cfg = load_config()
    return Path(cfg.data.tasks_dir) / task_id


def _get_task_or_404(task_id: str) -> dict:
    task = models.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/{task_id}/scenes")
async def get_scenes(task_id: str):
    _get_task_or_404(task_id)
    return models.get_scenes(task_id)


@router.get("/{task_id}/candidates")
async def get_candidates(task_id: str):
    _get_task_or_404(task_id)
    return models.get_candidates(task_id)


class ReviewPayload(BaseModel):
    start: float | None = None
    end: float | None = None
    title: str | None = None
    score: float | None = None
    rank: str | None = None


@router.put("/{task_id}/candidates/{candidate_id}/review")
async def review_candidate(task_id: str, candidate_id: int, payload: ReviewPayload):
    _get_task_or_404(task_id)
    fields = {}
    if payload.start is not None:
        fields["review_start"] = payload.start
    if payload.end is not None:
        fields["review_end"] = payload.end
    if payload.title is not None:
        fields["review_title"] = payload.title
    if payload.score is not None:
        fields["review_score"] = payload.score
    if payload.rank is not None:
        fields["review_rank"] = payload.rank
    if not fields:
        return {"ok": True}
    models.update_candidate_review(task_id, candidate_id, **fields)
    return {"ok": True}


@router.get("/{task_id}/report")
async def get_report(task_id: str, lang: str = "zh", download: bool = False):
    _get_task_or_404(task_id)
    if lang not in ("zh", "en"):
        raise HTTPException(400, "lang 仅支持 zh / en")
    path = _task_dir(task_id) / f"report_{lang}.md"
    if not path.exists():
        raise HTTPException(404, "报告尚未生成")
    if download:
        return FileResponse(path, media_type="text/markdown", filename=path.name)
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")


@router.get("/{task_id}/export.json")
async def export_json(task_id: str):
    _get_task_or_404(task_id)
    path = _task_dir(task_id) / "export.json"
    if not path.exists():
        raise HTTPException(404, "导出文件尚未生成")
    return FileResponse(path, media_type="application/json", filename="export.json")


@router.get("/{task_id}/video")
async def get_video(task_id: str):
    _get_task_or_404(task_id)
    path = _task_dir(task_id) / "converted" / "video.mp4"
    if not path.exists():
        raise HTTPException(404, "转封装视频不存在")
    return FileResponse(path, media_type="video/mp4")


@router.get("/{task_id}/frames/{filename}")
async def get_frame(task_id: str, filename: str):
    _get_task_or_404(task_id)
    path = _task_dir(task_id) / "frames" / filename
    if not path.exists():
        raise HTTPException(404, "帧图片不存在")
    return FileResponse(path, media_type="image/jpeg")
