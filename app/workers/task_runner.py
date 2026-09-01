"""后台任务主流程（推倒重建后，ADR-0006）：

ffprobe → 音频提取（+转封装供预览） → ASR 转写（缓存） → 自动打轴 → 保存。
"""
from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path

from ..config import load_config
from ..models import get_task, save_axles, update_task
from ..services import ffmpeg_utils as ff
from ..services.ai_client import AIClient
from ..services.asr import transcribe_chunks
from ..services.axle import build_axles

_background_tasks: set[asyncio.Task] = set()


def start_task(task_id: str) -> None:
    """在事件循环中启动后台任务。"""
    task = asyncio.create_task(run_task(task_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _task_dir(cfg, task_id: str) -> Path:
    return Path(cfg.data.tasks_dir) / task_id


async def run_task(task_id: str) -> None:
    cfg = load_config()
    task = get_task(task_id)
    if not task:
        return
    ai_client: AIClient | None = None
    try:
        video_path = Path(task["video_path"])
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        tdir = _task_dir(cfg, task_id)
        chunks_dir = tdir / "audio" / "chunks"
        converted_dir = tdir / "converted"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        converted_dir.mkdir(parents=True, exist_ok=True)

        # 1. 视频信息
        update_task(task_id, status="running", progress=5, message="读取视频信息…")
        info = await ff.ffprobe_info(video_path)
        duration = float(info["duration"] or 0)
        if duration <= 0:
            raise ValueError(f"无法读取视频时长: {video_path}")

        # 2. 音频提取 + 转封装（并行；FLV 等转 MP4 供浏览器预览与导出）
        update_task(task_id, progress=10, message="提取音频 / 准备预览视频…")
        if not info.get("audio_codec"):
            raise ValueError("视频无音轨，无法自动打轴（打轴依赖语音内容）")
        skip_convert = (
            video_path.suffix.lower() == ".mp4"
            and info["video_codec"] == "h264"
            and info["audio_codec"] in ("aac", "mp3", "")
        )
        audio_coro = ff.extract_audio_chunks(video_path, chunks_dir, int(cfg.asr.chunk_seconds))
        convert_coro = (asyncio.sleep(0) if skip_convert
                        else ff.convert_to_mp4(video_path, converted_dir / "video.mp4"))
        await asyncio.gather(audio_coro, convert_coro)

        # 3. ASR（asr.json 缓存复用，避免重复转写计费）
        ai_client = AIClient(cfg.ai)
        asr_path = tdir / "asr.json"
        asr_segments = None
        if asr_path.exists():
            try:
                asr_segments = json.loads(asr_path.read_text(encoding="utf-8"))
                update_task(task_id, progress=50, message=f"ASR 复用缓存，共 {len(asr_segments)} 句")
            except Exception:
                asr_segments = None
        if not asr_segments:
            update_task(task_id, progress=30, message="ASR 语音转写中…")
            asr_segments = await transcribe_chunks(ai_client, chunks_dir,
                                                   int(cfg.asr.chunk_seconds),
                                                   str(cfg.asr.language or ""))
            asr_path.write_text(
                json.dumps(asr_segments, ensure_ascii=False, indent=2), encoding="utf-8")
            update_task(task_id, progress=50, message=f"ASR 完成，共 {len(asr_segments)} 句")
        if not asr_segments:
            raise ValueError("ASR 转写结果为空，无法打轴")

        # 4. 自动打轴（唯一核心）
        update_task(task_id, progress=55, message="LLM 分析字幕、寻找内容点并打轴…")
        axles = await build_axles(ai_client, video_path, asr_segments, cfg.axle)
        full_axles = [
            {"task_id": task_id, "axle_index": i, **a}
            for i, a in enumerate(axles)
        ]
        save_axles(task_id, full_axles)
        update_task(task_id, progress=95, message=f"打轴完成，共 {len(full_axles)} 个切片轴")

        update_task(task_id, status="done", progress=100, message="打轴完成")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        update_task(task_id, status="failed", message=f"{type(exc).__name__}: {exc}")
    finally:
        if ai_client is not None:
            try:
                await ai_client.close()
            except Exception:
                pass
