"""场景切分：优先使用 PySceneDetect（如已安装），否则退回 FFmpeg scene 滤镜。"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from .ffmpeg_utils import ffmpeg_bin, run_async


async def detect_scenes(video_path: str | Path, duration: float,
                        threshold: float = 0.35) -> list[float]:
    """返回场景切换时间点列表（不含 0 和 duration）。"""
    if duration <= 0:
        return []
    boundaries = await _try_scenedetect(video_path, duration, threshold)
    if boundaries:
        return boundaries
    return await _ffmpeg_scene_boundaries(video_path, duration, threshold)


async def _try_scenedetect(video_path: str | Path, duration: float,
                           threshold: float) -> list[float]:
    try:
        import scenedetect  # noqa: F401
    except ImportError:
        return []

    def _run() -> list[float]:
        from scenedetect import ContentDetector, detect
        scenes = detect(str(video_path), ContentDetector(threshold=threshold), show_progress=False)
        times: list[float] = []
        for scene in scenes:
            t = float(scene[0].get_seconds())
            if 0.5 < t < duration - 0.5:
                times.append(round(t, 2))
        return times

    try:
        return await asyncio.to_thread(_run)
    except Exception:
        return []


async def _ffmpeg_scene_boundaries(video_path: str | Path, duration: float,
                                   threshold: float) -> list[float]:
    cmd = [
        ffmpeg_bin(), "-hide_banner", "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "-",
    ]
    try:
        _, stderr = await run_async(cmd, timeout=7200)
    except RuntimeError as exc:
        # 场景滤镜不可用时退化为固定时长切分，不让整个任务失败
        print(f"[scene_detect] ffmpeg 场景检测失败，将退化为固定时长切分: {exc}")
        return []
    text = stderr.decode("utf-8", errors="ignore")
    times: list[float] = []
    for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", text):
        t = float(match.group(1))
        if 0.5 < t < duration - 0.5:
            times.append(round(t, 2))
    times = sorted(set(times))
    return times


def refine_scenes(boundaries: list[float], duration: float,
                  min_seconds: float = 8.0, max_seconds: float = 30.0) -> list[tuple[float, float]]:
    """根据切换点生成时间段：过长自动切分，过短并入相邻段。"""
    points = sorted(set([0.0] + [b for b in boundaries if 0 < b < duration] + [duration]))
    raw: list[tuple[float, float]] = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        if b - a <= 1e-6:
            continue
        while b - a > max_seconds + 1e-6:
            raw.append((a, a + max_seconds))
            a += max_seconds
        if b - a > 1e-6:
            raw.append((a, b))

    # 合并过短片段
    merged: list[tuple[float, float]] = []
    i = 0
    n = len(raw)
    while i < n:
        a, b = raw[i]
        if b - a < min_seconds:
            if merged:
                pa, pb = merged[-1]
                if abs(pa - a) < 1e-6 or abs(pb - a) < 1e-6:
                    merged[-1] = (pa, b)
                    i += 1
                    continue
            if i + 1 < n:
                # 合并到下一段
                raw[i + 1] = (a, raw[i + 1][1])
                i += 1
                continue
        merged.append((a, b))
        i += 1

    # 再次切分因合并而明显超长的段。阈值取 max+min，避免切出过短尾段
    final: list[tuple[float, float]] = []
    for a, b in merged:
        if b - a <= 1e-6:
            continue
        while b - a > max_seconds + min_seconds + 1e-6:
            final.append((a, a + max_seconds))
            a += max_seconds
        if b - a > 1e-6:
            final.append((a, b))
    return final
