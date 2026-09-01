"""报告 / 场景 / 候选 / 复核 / 文件接口。"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
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


@router.get("/{task_id}/topics")
async def get_topics(task_id: str):
    _get_task_or_404(task_id)
    return models.get_topics(task_id)


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


def _range_response(path: Path, request: Request, media_type: str) -> Response:
    """支持 HTTP Range 的文件响应，便于浏览器视频跳转播放。"""
    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})

    match = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
    if not match:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})

    start_s, end_s = match.groups()
    if start_s == "" and end_s:
        # 后缀范围：bytes=-500 表示最后 500 字节
        suffix = int(end_s)
        start = max(0, file_size - suffix)
        end = file_size - 1
    else:
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
    end = min(end, file_size - 1)

    if start > end or start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    chunk_size = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(chunk_size)
    return Response(
        content=data,
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
        },
    )


@router.get("/{task_id}/video")
async def get_video(task_id: str, request: Request):
    _get_task_or_404(task_id)
    path = _task_dir(task_id) / "converted" / "video.mp4"
    if not path.exists():
        # 源文件本身是 MP4 时未做转封装，直接回退到源文件
        task = models.get_task(task_id)
        src = Path(task["video_path"]) if task and task.get("video_path") else None
        if src and src.exists() and src.suffix.lower() == ".mp4":
            path = src
    if not path.exists():
        raise HTTPException(404, "转封装视频不存在")
    return _range_response(path, request, "video/mp4")


@router.get("/{task_id}/frames/{filename}")
async def get_frame(task_id: str, filename: str):
    _get_task_or_404(task_id)
    base = (_task_dir(task_id) / "frames").resolve()
    path = (base / filename).resolve()
    if path.parent != base or not path.exists():
        raise HTTPException(404, "帧图片不存在")
    return FileResponse(path, media_type="image/jpeg")
