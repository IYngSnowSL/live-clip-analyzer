"""ASR 语音转写：自动分块，合并时间戳。"""
from __future__ import annotations

from pathlib import Path

from .ai_client import AIError
from .ffmpeg_utils import ffprobe_duration


async def transcribe_chunks(client, chunks_dir: str | Path, chunk_seconds: int,
                            language: str = "") -> list[dict]:
    """转写音频块目录，返回 [{start, end, text}, ...]（时间为相对原视频的秒数）。"""
    chunks_dir = Path(chunks_dir)
    files = sorted(chunks_dir.glob("chunk_*.mp3"))
    if not files:
        # 兼容单独音频文件
        files = sorted(chunks_dir.glob("*.mp3"))
    if not files:
        raise FileNotFoundError(f"未找到音频块: {chunks_dir}")

    all_segments: list[dict] = []
    offset = 0.0
    for fp in files:
        duration = await ffprobe_duration(fp)
        if duration <= 0:
            duration = float(chunk_seconds)
        segments = await _transcribe_one(client, fp, duration, language)
        for seg in segments:
            all_segments.append({
                "start": round(offset + float(seg["start"]), 2),
                "end": round(offset + float(seg["end"]), 2),
                "text": (seg.get("text") or "").strip(),
            })
        offset += duration
    return all_segments


async def _transcribe_one(client, file_path: Path, duration: float, language: str) -> list[dict]:
    result = None
    for fmt in ("verbose_json", "json", None):
        try:
            result = await client.transcribe_audio(file_path, language=language,
                                                   response_format=fmt)
            break
        except AIError as exc:
            if fmt is not None and exc.status_code in (400, 404, 422):
                continue
            raise

    if not isinstance(result, dict):
        return []

    segments = result.get("segments")
    if segments:
        out: list[dict] = []
        for seg in segments:
            start = float(seg.get("start") or 0)
            end = float(seg.get("end") or 0)
            text = (seg.get("text") or "").strip()
            if text:
                out.append({"start": start, "end": end, "text": text})
        return out

    text = (result.get("text") or "").strip()
    if text:
        return [{"start": 0.0, "end": duration, "text": text}]
    return []
