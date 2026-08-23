"""FFmpeg / ffprobe 封装。"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FileNotFoundError("未找到 ffmpeg，请先安装并加入 PATH")
    return path


def ffprobe_bin() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise FileNotFoundError("未找到 ffprobe，请先安装并加入 PATH")
    return path


async def run_async(cmd: list[str], timeout: float = 7200) -> tuple[bytes, bytes]:
    """执行命令，返回 (stdout, stderr)。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"命令超时（>{timeout}s）: {' '.join(cmd[:6])}")
    if proc.returncode != 0:
        tail = stderr.decode("utf-8", errors="ignore")[-800:]
        raise RuntimeError(f"FFmpeg 执行失败: {' '.join(cmd[:6])}...\n{tail}")
    return stdout, stderr


async def ffprobe_info(video_path: str | Path) -> dict[str, Any]:
    """读取视频信息：时长、分辨率、帧率、编码。"""
    cmd = [
        ffprobe_bin(), "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path),
    ]
    stdout, _ = await run_async(cmd, timeout=300)
    data = json.loads(stdout.decode("utf-8", errors="ignore"))
    fmt = data.get("format", {})
    try:
        duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    try:
        size = int(fmt.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    video_stream: dict[str, Any] = {}
    audio_stream: dict[str, Any] = {}
    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and not video_stream:
            video_stream = stream
        elif codec_type == "audio" and not audio_stream:
            audio_stream = stream

    # 部分 FLV 的 format.duration 可能缺失，用流时长兜底
    if duration <= 0:
        for stream in data.get("streams", []):
            try:
                stream_duration = float(stream.get("duration") or 0)
                duration = max(duration, stream_duration)
            except (TypeError, ValueError):
                continue

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    fps_text = video_stream.get("r_frame_rate") or video_stream.get("avg_frame_rate") or "0/1"
    try:
        parts = fps_text.split("/")
        if len(parts) == 2 and float(parts[1]) != 0:
            fps = float(parts[0]) / float(parts[1])
        elif len(parts) == 1:
            fps = float(parts[0])
        else:
            fps = 0.0
    except Exception:
        fps = 0.0
    return {
        "duration": duration,
        "size": size,
        "width": width,
        "height": height,
        "fps": fps,
        "video_codec": video_stream.get("codec_name", ""),
        "audio_codec": audio_stream.get("codec_name", ""),
    }


async def ffprobe_duration(path: str | Path) -> float:
    info = await ffprobe_info(path)
    return info.get("duration") or 0.0


async def convert_to_mp4(src: str | Path, dst: str | Path) -> str:
    """FLV 等转为浏览器可播放的 MP4（优先无损拷贝，失败则转码）。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return str(dst)
    cmd = [
        ffmpeg_bin(), "-y", "-i", str(src),
        "-c", "copy", "-movflags", "+faststart", str(dst),
    ]
    try:
        await run_async(cmd, timeout=7200)
    except RuntimeError:
        # 编码不支持 copy 时退回转码（H.264 + AAC）
        cmd = [
            ffmpeg_bin(), "-y", "-i", str(src),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst),
        ]
        await run_async(cmd, timeout=7200)
    return str(dst)


async def extract_audio_chunks(src: str | Path, out_dir: str | Path,
                               chunk_seconds: int = 1200,
                               concurrency: int = 2) -> list[str]:
    """按固定时长切出 mp3 音频块（手动 -ss/-t 方式，兼容性更好）。返回文件路径列表。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = await ffprobe_info(src)
    duration = float(info.get("duration") or 0)
    if duration <= 0:
        raise RuntimeError(f"无法读取音频时长: {src}")
    if not info.get("audio_codec"):
        # 视频本身没有音轨，跳过音频切分
        return []
    chunk_seconds = int(chunk_seconds)
    if chunk_seconds <= 0:
        chunk_seconds = 1200
    count = int(duration // chunk_seconds) + (1 if duration % chunk_seconds > 1 else 0)
    count = max(1, count)

    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def one(i: int) -> str:
        start = i * chunk_seconds
        out_path = out_dir / f"chunk_{i:04d}.mp3"
        if out_path.exists():
            return str(out_path)
        cmd = [
            ffmpeg_bin(), "-y",
            "-ss", str(start), "-i", str(src),
            "-t", str(chunk_seconds),
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "libmp3lame", "-q:a", "4",
            str(out_path),
        ]
        async with sem:
            await run_async(cmd, timeout=7200)
        return str(out_path)

    await asyncio.gather(*(one(i) for i in range(count)))
    return sorted(str(p) for p in out_dir.glob("chunk_*.mp3"))


async def extract_frames(video_path: str | Path, out_dir: str | Path,
                         interval: float = 15.0) -> list[tuple[float, str]]:
    """按固定间隔全局抽帧。返回 [(时间秒, 文件路径), ...]。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if interval <= 0:
        interval = 15.0
    pattern = out_dir / "frame_%06d.jpg"
    cmd = [
        ffmpeg_bin(), "-y", "-i", str(video_path),
        "-vf", f"fps=1/{interval}",
        "-q:v", "2",
        str(pattern),
    ]
    await run_async(cmd, timeout=7200)
    files = sorted(out_dir.glob("frame_*.jpg"))
    return [(round(i * interval, 2), str(fp)) for i, fp in enumerate(files)]


def format_ts(seconds: float) -> str:
    """秒数格式化为 HH:MM:SS。"""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
