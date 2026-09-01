"""后台任务主流程。"""
from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path

from ..config import load_config
from ..models import get_task, save_candidates, save_scenes, update_task
from ..services import danmaku as dm
from ..services import ffmpeg_utils as ff
from ..services import scene_detect as sd
from ..services.ai_client import AIClient
from ..services.asr import transcribe_chunks
from ..services.candidates import generate_long_candidates, generate_sentence_candidates
from ..services.report import build_export_json, build_reports
from ..services.scorer import score_scenes
from ..services.timeline import analyze_scenes
from ..services.vision import describe_scenes

_background_tasks: set[asyncio.Task] = set()


def start_task(task_id: str) -> None:
    """在事件循环中启动后台任务。"""
    task = asyncio.create_task(run_task(task_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _task_dir(cfg, task_id: str) -> Path:
    return Path(cfg.data.tasks_dir) / task_id


def _map_frames_to_scenes(frame_items: list[tuple[float, str]],
                          scenes: list[dict]) -> dict[int, list[str]]:
    """把全局抽帧结果按时间分派到场景。"""
    mapping: dict[int, list[str]] = {int(sc["scene_index"]): [] for sc in scenes}
    if not frame_items or not scenes:
        return mapping
    idx = 0
    for t, fp in frame_items:
        # 推进到包含 t 的场景
        while idx < len(scenes) - 1 and t >= float(scenes[idx]["end"]):
            idx += 1
        sc = scenes[idx]
        if float(sc["start"]) <= t < float(sc["end"]):
            mapping[int(sc["scene_index"])].append(fp)
    return mapping


async def run_task(task_id: str) -> None:
    cfg = load_config()
    task = get_task(task_id)
    if not task:
        return
    ai_client: AIClient | None = None
    try:
        video_path = Path(task["video_path"])
        danmaku_path = Path(task["danmaku_path"]) if task.get("danmaku_path") else None
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        if danmaku_path and not danmaku_path.exists():
            raise FileNotFoundError(f"弹幕文件不存在: {danmaku_path}")

        tdir = _task_dir(cfg, task_id)
        converted_dir = tdir / "converted"
        chunks_dir = tdir / "audio" / "chunks"
        frames_dir = tdir / "frames"
        converted_dir.mkdir(parents=True, exist_ok=True)
        chunks_dir.mkdir(parents=True, exist_ok=True)
        frames_dir.mkdir(parents=True, exist_ok=True)

        # 1. 视频信息
        update_task(task_id, status="running", progress=5, message="读取视频信息…")
        info = await ff.ffprobe_info(video_path)
        duration = float(info["duration"] or 0)
        if duration <= 0:
            raise ValueError(f"无法读取视频时长: {video_path}")

        # 2. 并行：转封装 + 音频切块 + 场景检测；同时解析弹幕
        update_task(task_id, progress=10, message="转封装 / 音频切分 / 场景检测中…")
        # 源文件已是浏览器可播的 MP4（H.264 + AAC/MP3/无音轨）时跳过转封装
        skip_convert = (
            video_path.suffix.lower() == ".mp4"
            and info["video_codec"] == "h264"
            and info["audio_codec"] in ("aac", "mp3", "")
        )
        if skip_convert:
            convert_coro = asyncio.sleep(0)
        else:
            convert_coro = ff.convert_to_mp4(video_path, converted_dir / "video.mp4")
        audio_coro = ff.extract_audio_chunks(video_path, chunks_dir, int(cfg.asr.chunk_seconds))
        scene_coro = sd.detect_scenes(video_path, duration, float(cfg.scene.threshold))

        convert_task = asyncio.create_task(convert_coro)
        audio_task = asyncio.create_task(audio_coro)
        scene_task = asyncio.create_task(scene_coro)
        danmaku_list = await asyncio.to_thread(
            dm.parse_danmaku_xml, danmaku_path, float(task.get("offset_seconds") or 0)
        ) if danmaku_path else []
        update_task(task_id, progress=18, message=f"弹幕解析完成，共 {len(danmaku_list)} 条")

        try:
            await asyncio.gather(convert_task, audio_task, scene_task)
        except Exception:
            for t in (convert_task, audio_task, scene_task):
                t.cancel()
            raise
        boundaries = scene_task.result()

        # 3. 场景切分与保存
        scenes_raw = sd.refine_scenes(boundaries, duration,
                                      float(cfg.scene.min_scene_seconds),
                                      float(cfg.scene.max_scene_seconds))
        scenes: list[dict] = []
        for i, (a, b) in enumerate(scenes_raw):
            scenes.append({
                "task_id": task_id,
                "scene_index": i,
                "start": round(a, 2),
                "end": round(b, 2),
                "title_zh": "",
                "title_en": "",
                "summary_zh": "",
                "summary_en": "",
                "visual_summary": "",
                "asr_text": "",
                "danmaku_count": 0,
                "danmaku_heat": 0,
                "danmaku_emotion": 0,
                "danmaku_keywords": [],
                "fun_score": 0,
                "highlight_score": 0,
                "final_score": 0,
                "rank": "low",
                "quote": "",
                "quote_start": None,
                "quote_end": None,
                "quote_reason_zh": "",
                "quote_reason_en": "",
            })
        save_scenes(task_id, scenes)
        update_task(task_id, progress=35, message=f"场景切分完成，共 {len(scenes)} 段")

        # 4. 弹幕统计
        stats = dm.build_danmaku_stats(danmaku_list, scenes)
        for sc in scenes:
            st = stats.get(int(sc["scene_index"]), {})
            sc["danmaku_count"] = int(st.get("count") or 0)
            sc["danmaku_heat"] = float(st.get("heat") or 0)
            sc["danmaku_emotion"] = float(st.get("emotion") or 0)
            sc["danmaku_keywords"] = list(st.get("keywords") or [])
        save_scenes(task_id, scenes)
        update_task(task_id, progress=40, message="弹幕统计完成")

        # 5. 抽帧（使用转封装后的 MP4 便于快速定位）
        update_task(task_id, progress=42, message="全局抽帧中…")
        video_for_frames = converted_dir / "video.mp4"
        if not video_for_frames.exists():
            video_for_frames = video_path
        frame_items = await ff.extract_frames(video_for_frames, frames_dir,
                                              float(cfg.vision.frame_interval))
        frames_by_scene = _map_frames_to_scenes(frame_items, scenes)
        update_task(task_id, progress=50, message=f"抽帧完成，共 {len(frame_items)} 帧")

        # 6. ASR
        ai_client = AIClient(cfg.ai)
        if info.get("audio_codec"):
            update_task(task_id, progress=52, message="ASR 语音转写中…")
            asr_segments = await transcribe_chunks(ai_client, chunks_dir,
                                                   int(cfg.asr.chunk_seconds),
                                                   str(cfg.asr.language or ""))
            (tdir / "asr.json").write_text(
                json.dumps(asr_segments, ensure_ascii=False, indent=2), encoding="utf-8")
            update_task(task_id, progress=60, message=f"ASR 完成，共 {len(asr_segments)} 句")
        else:
            asr_segments = []
            update_task(task_id, progress=60, message="视频无音轨，跳过 ASR")

        # 7. 画面理解
        update_task(task_id, progress=62, message="画面理解（视觉模型）中…")
        await describe_scenes(ai_client, scenes, frames_by_scene,
                              int(cfg.vision.max_frames_per_scene))
        update_task(task_id, progress=72, message="画面理解完成")

        # 8. 逐段 LLM 分析
        update_task(task_id, progress=75, message="生成详细时间轴分析…")
        scenes = await analyze_scenes(ai_client, scenes, asr_segments,
                                      int(cfg.ai.concurrency))
        update_task(task_id, progress=85, message="时间轴分析完成")

        # 9. 评分 + 候选
        scenes = score_scenes(scenes, cfg.scoring.weights)
        save_scenes(task_id, scenes)
        long_candidates = generate_long_candidates(scenes, cfg.scoring)
        sentence_candidates = generate_sentence_candidates(scenes, cfg.scoring)
        all_candidates = long_candidates + sentence_candidates
        save_candidates(task_id, all_candidates)
        update_task(task_id, progress=93,
                    message=f"候选生成完成：长切片 {len(long_candidates)} 条，单句素材 {len(sentence_candidates)} 条")

        # 10. 报告
        task = get_task(task_id) or task
        try:
            languages = json.loads(task.get("output_languages") or '["zh","en"]')
            if not isinstance(languages, list) or not languages:
                languages = ["zh", "en"]
        except (TypeError, ValueError):
            languages = ["zh", "en"]
        await asyncio.to_thread(build_reports, task, scenes, all_candidates, tdir, languages)
        export_path = tdir / "export.json"
        export_path.write_text(
            json.dumps(build_export_json(task, scenes, all_candidates), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        update_task(task_id, status="done", progress=100, message="分析完成")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        update_task(task_id, status="failed", message=f"{type(exc).__name__}: {exc}")
    finally:
        if ai_client is not None:
            try:
                await ai_client.close()
            except Exception:
                pass
