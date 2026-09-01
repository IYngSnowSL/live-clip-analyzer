"""字幕整理：把 ASR 转写片段整理成带时间戳的文档文本，并按时间窗分块。"""
from __future__ import annotations

from .ffmpeg_utils import format_ts


def build_subtitle_document(asr_segments: list[dict]) -> str:
    """把 [{start, end, text}] 整理成带时间戳的文档文本，供 LLM 分析。"""
    lines = []
    for seg in asr_segments:
        text = (seg.get("text") or "").strip()
        if text:
            lines.append(f"[{format_ts(seg['start'])}] {text}")
    return "\n".join(lines)


def chunk_by_window(asr_segments: list[dict], window_seconds: int = 600,
                    overlap_seconds: int = 60) -> list[dict]:
    """按时间窗把字幕分块，返回 [{start, end, text}]。

    用于语义切分的预筛与分窗处理。窗口滑动步长 = window - overlap。
    """
    if not asr_segments:
        return []
    total_start = float(asr_segments[0]["start"])
    total_end = float(asr_segments[-1]["end"])
    if window_seconds <= 0:
        window_seconds = 600
    if overlap_seconds >= window_seconds:
        overlap_seconds = 0

    chunks: list[dict] = []
    cursor = total_start
    while cursor < total_end:
        win_end = cursor + window_seconds
        segs = [
            s for s in asr_segments
            if float(s["start"]) < win_end and float(s["end"]) >= cursor
        ]
        if segs:
            text = " ".join((s.get("text") or "").strip() for s in segs).strip()
            if text:
                chunks.append({"start": round(cursor, 2), "end": round(win_end, 2), "text": text})
        cursor += window_seconds - overlap_seconds
    return chunks
