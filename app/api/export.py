"""视频切片导出接口。"""
from __future__ import annotations

import json
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
    _save_exports_meta(out_dir, results)
    return {"task_id": task_id, "export_dir": str(out_dir), "files": results}


def _exports_meta_path(out_dir: Path) -> Path:
    return out_dir / "exports_meta.json"


def _save_exports_meta(out_dir: Path, results: list[dict]) -> None:
    """把导出结果（含 title）持久化，刷新页面后仍可显示标题。"""
    meta_path = _exports_meta_path(out_dir)
    meta: dict[str, dict] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    for r in results:
        if not r.get("filename"):
            continue
        meta[r["filename"]] = {
            "title": r.get("title") or "",
            "start": r.get("start") or 0,
            "end": r.get("end") or 0,
            "status": r.get("status") or "",
            "error": r.get("error") or "",
        }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/{task_id}/exports")
async def list_exports(task_id: str):
    _get_task_or_404(task_id)
    base = _task_dir(task_id) / "exports"
    if not base.exists():
        return []
    meta: dict[str, dict] = {}
    meta_path = _exports_meta_path(base)
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    pattern = re.compile(r"clip_\d+_(\d+)s_(\d+)s(?:_\d+)?\.mp4$")
    files = []
    for p in sorted(base.glob("*.mp4")):
        m = pattern.match(p.name)
        info = meta.get(p.name, {})
        files.append({
            "filename": p.name,
            "start": int(m.group(1)) if m else (info.get("start") or 0),
            "end": int(m.group(2)) if m else (info.get("end") or 0),
            "title": info.get("title") or "",
            "status": info.get("status") or "ok",
            "error": info.get("error") or "",
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
