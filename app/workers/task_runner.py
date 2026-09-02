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
from ..services.asr import save_srt, transcribe_chunks
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

        # 3.5 字幕附属文件：与视频同目录同名的 .srt（时间戳 + 文本）
        try:
            srt_path = save_srt(video_path, asr_segments)
            update_task(task_id, srt_path=str(srt_path))
        except Exception as exc:  # noqa: BLE001
            print(f"[srt] 字幕文件保存失败（不影响打轴）: {exc}")

        # 4. 自动打轴（唯一核心）
        update_task(task_id, progress=55, message="LLM 分析字幕、寻找内容点并打轴…")
        axles = await build_axles(ai_client, video_path, asr_segments, cfg.axle)
        full_axles = [
            {"task_id": task_id, "axle_index": i, **a}
            for i, a in enumerate(axles)
        ]

        # 4.5 弹幕高峰标注（任务关联了弹幕时）
        if task.get("danmaku_path"):
            try:
                from ..services.danmaku import build_density, find_peaks, parse_danmaku
                dms = await asyncio.to_thread(
                    parse_danmaku, task["danmaku_path"],
                    float(task.get("offset_seconds") or 0))
                density = build_density(dms)
                for a in full_axles:
                    a["danmaku_peaks"] = find_peaks(density, a["start"], a["end"])
                if dms:
                    update_task(task_id, progress=80,
                                message=f"弹幕解析完成（{len(dms)} 条），已标注各轴弹幕高峰")
            except Exception as exc:  # noqa: BLE001
                print(f"[danmaku] 弹幕高峰计算失败（不影响打轴）: {exc}")

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


# ---------------- 重新打轴（复用 ASR，不重复计费） ----------------

def start_reaxle(task_id: str, overrides: dict | None = None) -> None:
    """在事件循环中启动重新打轴任务。"""
    task = asyncio.create_task(run_reaxle(task_id, overrides))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def run_reaxle(task_id: str, overrides: dict | None = None) -> None:
    """复用 asr.json 缓存重新打轴；可覆盖目标时长，可选精细分窗模式。"""
    from types import SimpleNamespace

    cfg = load_config()
    task = get_task(task_id)
    if not task:
        return
    ai_client: AIClient | None = None
    try:
        tdir = _task_dir(cfg, task_id)
        asr_path = tdir / "asr.json"
        if not asr_path.exists():
            raise FileNotFoundError("该任务没有 ASR 缓存（asr.json），无法重新打轴")
        asr_segments = json.loads(asr_path.read_text(encoding="utf-8"))
        if not asr_segments:
            raise ValueError("ASR 缓存为空，无法重新打轴")
        video_path = Path(task["video_path"])
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
        axle_kwargs = dict(cfg.axle)
        axle_kwargs.update(overrides)
        fine_mode = bool(overrides.pop("fine_mode", False))
        if fine_mode:
            # 精细模式：分窗减半，找更多内容点，切得更细
            axle_kwargs["window_seconds"] = max(120, int(axle_kwargs.get("window_seconds", 600)) // 2)
            axle_kwargs["overlap_seconds"] = max(30, int(axle_kwargs.get("overlap_seconds", 60)) // 2)
        axle_cfg = SimpleNamespace(**axle_kwargs)

        update_task(task_id, status="running", progress=60,
                    message="重新打轴中（复用 ASR 结果，不重复计费）…")
        ai_client = AIClient(cfg.ai)
        axles = await build_axles(ai_client, video_path, asr_segments, axle_cfg)
        full_axles = [
            {"task_id": task_id, "axle_index": i, **a}
            for i, a in enumerate(axles)
        ]
        save_axles(task_id, full_axles)
        update_task(task_id, status="done", progress=100,
                    message=f"重新打轴完成，共 {len(full_axles)} 个切片轴")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        update_task(task_id, status="failed", message=f"重新打轴失败: {type(exc).__name__}: {exc}")
    finally:
        if ai_client is not None:
            try:
                await ai_client.close()
            except Exception:
                pass
