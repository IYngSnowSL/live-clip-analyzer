"""视频导出预留模块。

后续可在此实现切片导出，例如：
    ffmpeg -y -ss {start} -i {video} -to {end-start} -c copy {out_path}

当前版本暂不实现视频导出，只保留接口。
"""
from __future__ import annotations

from pathlib import Path


def export_clip(video_path: str | Path, start: float, end: float,
                out_path: str | Path) -> str:
    """按起止时间裁剪视频片段，输出到 out_path。"""
    raise NotImplementedError("视频导出功能将在后续版本提供")


def export_candidates(video_path: str | Path, candidates: list[dict],
                      out_dir: str | Path) -> list[str]:
    """批量导出候选切片。"""
    raise NotImplementedError("视频导出功能将在后续版本提供")
