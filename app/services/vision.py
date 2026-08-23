"""画面内容理解：每个时间段选代表帧，调用视觉模型输出简短画面描述。"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path

VISION_PROMPT = (
    "以下是同一段直播录像中按时间顺序截取的几帧画面。"
    "请用简洁的中文描述这段画面里正在发生什么（人物、动作、场景、屏幕上的关键文字等），"
    "80字以内，只输出描述文本。"
)


def image_to_data_url(path: str | Path) -> str:
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


async def describe_scenes(client, scenes: list[dict],
                          frames_by_scene: dict[int, list[str]],
                          max_frames_per_scene: int = 2) -> list[dict]:
    """为每个场景生成 visual_summary 字段。"""
    sem = asyncio.Semaphore(max(1, int(client.concurrency)))

    async def one(scene: dict) -> dict:
        files = list(frames_by_scene.get(scene["scene_index"], []))[:max_frames_per_scene]
        content: list[dict] = [{"type": "text", "text": VISION_PROMPT}]
        for fp in files:
            if Path(fp).exists():
                url = await asyncio.to_thread(image_to_data_url, fp)
                content.append({"type": "image_url", "image_url": {"url": url}})
        if len(content) == 1:
            scene["visual_summary"] = ""
            return scene
        messages = [{"role": "user", "content": content}]
        async with sem:
            text = await client.chat(messages, model=client.vision_model,
                                     json_mode=False, max_tokens=500)
        scene["visual_summary"] = (text or "").strip()
        return scene

    return await asyncio.gather(*(one(s) for s in scenes))
