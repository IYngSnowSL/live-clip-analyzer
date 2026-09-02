"""打轴结果接口：列表 / 复核 / CSV 导出 / 视频预览。"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .. import models
from ..config import load_config

router = APIRouter(prefix="/api/tasks", tags=["axles"])


def _task_dir(task_id: str) -> Path:
    cfg = load_config()
    return Path(cfg.data.tasks_dir) / task_id


def _get_task_or_404(task_id: str) -> dict:
    task = models.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/{task_id}/axles")
async def get_axles(task_id: str):
    _get_task_or_404(task_id)
    return models.get_axles(task_id)


class ReviewPayload(BaseModel):
    start: float | None = None
    end: float | None = None
    title: str | None = None


class ReaxlePayload(BaseModel):
    target_min_seconds: float | None = None
    target_max_seconds: float | None = None
    fine_mode: bool = False


@router.post("/{task_id}/reaxle")
async def reaxle_task(task_id: str, payload: ReaxlePayload):
    """任务完成后重新打轴：复用 ASR 结果（不重复计费），可改目标时长，可选精细分窗。"""
    task = _get_task_or_404(task_id)
    if task.get("status") in ("running", "pending"):
        raise HTTPException(400, "任务正在运行中，请等待完成后再重新打轴")
    from ..workers.task_runner import start_reaxle
    start_reaxle(task_id, payload.model_dump())
    return {"ok": True}


@router.put("/{task_id}/axles/{axle_id}/review")
async def review_axle(task_id: str, axle_id: int, payload: ReviewPayload):
    _get_task_or_404(task_id)
    fields = {}
    if payload.start is not None:
        fields["review_start"] = payload.start
    if payload.end is not None:
        fields["review_end"] = payload.end
    if payload.title is not None:
        fields["review_title"] = payload.title
    if not fields:
        return {"ok": True}
    models.update_axle_review(task_id, axle_id, **fields)
    return {"ok": True}


@router.get("/{task_id}/subtitle")
async def get_subtitle(task_id: str):
    """返回 SRT 字幕文件内容与路径（供 WebUI 字幕页展示/下载）。"""
    task = _get_task_or_404(task_id)
    srt_path = task.get("srt_path")
    if not srt_path:
        raise HTTPException(404, "该任务尚未生成字幕文件（需完成 ASR 转写）")
    path = Path(srt_path)
    if not path.exists():
        raise HTTPException(404, f"字幕文件不存在: {srt_path}")
    content = path.read_text(encoding="utf-8-sig")
    return {"path": str(path), "content": content}


@router.get("/{task_id}/axles.csv")
async def export_axles_csv(task_id: str):
    """导出轴清单 CSV（BOM 让 Excel 正确识别 UTF-8），可直接对照剪辑软件打轴。"""
    _get_task_or_404(task_id)
    axles = models.get_axles(task_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["序号", "开始(秒)", "结束(秒)", "时长(秒)", "标题", "推荐理由", "评分"])
    for i, a in enumerate(axles, 1):
        start = a.get("review_start") if a.get("review_start") is not None else a.get("start")
        end = a.get("review_end") if a.get("review_end") is not None else a.get("end")
        writer.writerow([
            i, start, end, round(float(end) - float(start), 1),
            a.get("review_title") or a.get("title") or "",
            a.get("reason") or "",
            a.get("score") or 0,
        ])
    data = "\ufeff" + buf.getvalue()
    return Response(
        content=data.encode("utf-8"), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=axles_{task_id}.csv"},
    )


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
        # 源文件本身是可播 MP4 时未做转封装，直接回退到源文件
        task = models.get_task(task_id)
        src = Path(task["video_path"]) if task and task.get("video_path") else None
        if src and src.exists() and src.suffix.lower() == ".mp4":
            path = src
    if not path.exists():
        raise HTTPException(404, "视频不可用")
    return _range_response(path, request, "video/mp4")
