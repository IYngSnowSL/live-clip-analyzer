"""画面内容理解：每个时间段选代表帧，调用视觉模型输出简短画面描述。"""
from __future__ import annotations

import asyncio
from pathlib import Path

from .ai_client import AIError

VISION_PROMPT = (
    "以下是同一段直播录像中按时间顺序截取的几帧画面。"
    "请用简洁的中文描述这段画面里正在发生什么（人物、动作、场景、屏幕上的关键文字等），"
    "80字以内，只输出描述文本。"
)


async def describe_scenes(client, scenes: list[dict],
                          frames_by_scene: dict[int, list[str]],
                          max_frames_per_scene: int = 2) -> list[dict]:
    """为每个场景生成 visual_summary 字段。单个场景失败不会中断全片分析。

    画面解析统一走 AI 门面的 describe_images 能力接口。
    """
    sem = asyncio.Semaphore(max(1, int(client.concurrency)))
    failures = 0

    async def one(scene: dict) -> dict:
        nonlocal failures
        files = [
            fp for fp in list(frames_by_scene.get(scene["scene_index"], []))[:max_frames_per_scene]
            if Path(fp).exists()
        ]
        if not files:
            scene["visual_summary"] = ""
            return scene
        async with sem:
            try:
                text = await client.describe_images(files, VISION_PROMPT)
            except AIError as exc:
                failures += 1
                print(f"[vision] scene {scene['scene_index']} 失败: {exc}")
                scene["visual_summary"] = ""
                return scene
        scene["visual_summary"] = (text or "").strip()
        return scene

    result = await asyncio.gather(*(one(s) for s in scenes))
    if scenes and failures >= len(scenes):
        raise AIError("所有场景的画面理解调用均失败，请检查视觉模型配置")
    return result
