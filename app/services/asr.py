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
    failures = 0
    for fp in files:
        duration = float(chunk_seconds)
        try:
            probed = await ffprobe_duration(fp)
            if probed > 0:
                duration = probed
            segments = await _transcribe_one(client, fp, duration, language)
        except Exception as exc:  # noqa: BLE001
            # 单个音频块失败不中断整场 ASR；时间偏移仍然前进
            failures += 1
            print(f"[asr] {fp.name} 转写失败: {exc}")
            offset += duration
            continue
        for seg in segments:
            all_segments.append({
                "start": round(offset + float(seg["start"]), 2),
                "end": round(offset + float(seg["end"]), 2),
                "text": (seg.get("text") or "").strip(),
            })
        offset += duration

    if files and failures >= len(files):
        raise AIError("所有音频块的 ASR 转写均失败，请检查 asr_model 配置或 API Key")
    return all_segments


async def _transcribe_one(client, file_path: Path, duration: float, language: str) -> list[dict]:
    result = None
    for fmt in ("verbose_json", "json", None):
        try:
            result = await client.transcribe(file_path, language=language,
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


# ---------------- SRT 字幕文件（附属产物，存视频根目录） ----------------

def segments_to_srt(segments: list[dict]) -> str:
    """ASR 片段转标准 SRT 字幕文本。"""
    def ts(sec: float) -> str:
        ms = int(round(float(sec) * 1000))
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        s, milli = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"

    blocks = []
    for i, seg in enumerate(segments, 1):
        text = str(seg.get("text") or "").strip().replace("\n", " ")
        if not text:
            continue
        blocks.append(f"{i}\n{ts(seg['start'])} --> {ts(seg['end'])}\n{text}\n")
    return "\n".join(blocks)


def save_srt(video_path: str | Path, segments: list[dict]) -> Path:
    """把 ASR 结果写成与视频同目录同名的 .srt 文件，返回保存路径。"""
    srt_path = Path(video_path).with_suffix(".srt")
    srt_path.write_text(segments_to_srt(segments), encoding="utf-8-sig")
    return srt_path
