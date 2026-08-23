"""视频切片导出模块。

使用 FFmpeg 按起止时间裁剪：
- 快速模式（默认）：-c copy 无损流复制，速度快；起点对齐到关键帧，
  可能比指定时间略早。
- 精切模式：重新编码，起点更准确，但速度慢、体积可能变化。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .ffmpeg_utils import ffmpeg_bin, run_async


def build_clip_filename(index: int, start: float, end: float) -> str:
    """统一使用 ASCII 文件名，避免中文/特殊字符导致的下载与编码问题。"""
    return f"clip_{index:03d}_{int(start)}s_{int(end)}s.mp4"


async def export_clip(video_path: str | Path, start: float, end: float,
                      out_path: str | Path, accurate: bool = False) -> str:
    """导出单个切片，返回输出文件路径。"""
    start = float(start)
    end = float(end)
    duration = max(0.1, end - start)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if accurate:
        cmd = [
            ffmpeg_bin(), "-y",
            "-ss", str(start), "-i", str(video_path),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        await run_async(cmd, timeout=7200)
        return str(out_path)

    cmd_copy = [
        ffmpeg_bin(), "-y",
        "-ss", str(start), "-i", str(video_path),
        "-t", str(duration),
        "-c", "copy", "-movflags", "+faststart",
        str(out_path),
    ]
    try:
        await run_async(cmd_copy, timeout=7200)
    except RuntimeError:
        # 源编码无法直接 copy 时，退回重编码
        cmd = [
            ffmpeg_bin(), "-y",
            "-ss", str(start), "-i", str(video_path),
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        await run_async(cmd, timeout=7200)
    return str(out_path)


async def export_clips(video_path: str | Path, clips: list[dict[str, Any]],
                       out_dir: str | Path, accurate: bool = False,
                       concurrency: int = 1) -> list[dict[str, Any]]:
    """批量导出切片。

    clips 中每项需要 start / end，可带 title。
    单个切片失败不会影响其他切片，返回每项的结果与错误信息。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(index: int, clip: dict[str, Any]) -> dict[str, Any]:
        start = float(clip["start"])
        end = float(clip["end"])
        title = str(clip.get("title") or "")
        base = {
            "index": index + 1,
            "start": round(start, 2),
            "end": round(end, 2),
            "title": title,
        }
        if end <= start + 0.05:
            return {**base, "status": "failed", "error": "结束时间必须大于开始时间"}

        filename = build_clip_filename(index + 1, start, end)
        out_path = out_dir / filename
        try:
            async with sem:
                await export_clip(video_path, start, end, out_path, accurate=accurate)
        except Exception as exc:  # noqa: BLE001
            return {**base, "filename": filename, "status": "failed", "error": str(exc)}
        return {
            **base,
            "filename": filename,
            "path": str(out_path),
            "status": "ok",
            "error": "",
        }

    results = await asyncio.gather(*(one(i, c) for i, c in enumerate(clips)))
    return list(results)


def export_clip_sync(video_path: str | Path, start: float, end: float,
                     out_path: str | Path, accurate: bool = False) -> str:
    """同步版本，便于在非异步环境或脚本中直接调用。"""
    return asyncio.run(export_clip(video_path, start, end, out_path, accurate=accurate))

