"""ASR 语音转写：自动分块，合并时间戳；SRT 字幕附属文件。"""
from __future__ import annotations

import re
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


# ---------------- SRT 字幕文件（附属产物，存视频根目录的日期文件夹） ----------------

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF"
    "\U0000FE00-\U0000FE0F\u200D\uFE0F\u2600-\u26FF\u2700-\u27BF]"
)


def clean_subtitle_text(text: str) -> str:
    """字幕文本清理：去表情、句号转逗号做句读、句尾不带句号（保留情感标点 ？！）。"""
    text = _EMOJI_RE.sub("", str(text or ""))
    # 中文句号 → 逗号；英文句号 → 逗号（但保留数字小数点，如 "3.5"）
    text = text.replace("。", "，")
    text = re.sub(r"(?<!\d)\.(?!\d)", "，", text)
    # 连续逗号压缩
    text = re.sub(r"[，,]{2,}", "，", text)
    # 句尾的逗号/句读符去掉
    text = re.sub(r"[，,]+$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def segments_to_srt(segments: list[dict]) -> str:
    """ASR 片段转标准 SRT 字幕文本（可插入视频；无表情，句读+情感标点，不用句号）。"""
    def ts(sec: float) -> str:
        ms = int(round(float(sec) * 1000))
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        s, milli = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"

    blocks = []
    idx = 0  # 块序号只对实际输出的条目递增，空文本不占号
    for seg in segments:
        text = clean_subtitle_text(seg.get("text") or "")
        if not text:
            continue
        idx += 1
        blocks.append(f"{idx}\n{ts(seg['start'])} --> {ts(seg['end'])}\n{text}\n")
    return "\n".join(blocks)


def save_srt(video_path: str | Path, segments: list[dict]) -> Path:
    """把 ASR 结果写成 SRT：在视频同目录创建「[创建日期]_视频名」文件夹存放，返回保存路径。"""
    from datetime import datetime

    video = Path(video_path)
    date_str = datetime.now().strftime("%Y-%m-%d")
    folder = video.parent / f"[{date_str}]_{video.stem}"
    folder.mkdir(parents=True, exist_ok=True)
    srt_path = folder / f"{video.stem}.srt"
    srt_path.write_text(segments_to_srt(segments), encoding="utf-8-sig")
    return srt_path
