"""场景时间轴分析：逐段调用 LLM，生成中英双语标题、概述、评分和单句素材。"""
from __future__ import annotations

import asyncio
import re

from .ai_client import AIError
from .ffmpeg_utils import format_ts


def gather_asr_for_scene(asr_segments: list[dict], start: float, end: float,
                         limit: int = 2400) -> str:
    lines: list[str] = []
    for seg in asr_segments:
        s = float(seg["start"])
        e = float(seg["end"])
        if e <= start or s >= end:
            continue
        lines.append(f"[{format_ts(max(s, start))}] {seg['text']}")
    text = "\n".join(lines)
    return text[:limit]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def find_quote_time(asr_segments: list[dict], quote: str,
                    start: float, end: float) -> tuple[float, float]:
    """在场景语音中定位单句素材的时间戳。"""
    q = _normalize_text(quote)
    if not q:
        return start, end
    for seg in asr_segments:
        s = float(seg["start"])
        e = float(seg["end"])
        if e <= start or s >= end:
            continue
        text = _normalize_text(seg.get("text") or "")
        if q in text or (len(text) > 0 and text in q):
            return s, e
    return start, end


def _build_prompt(scene: dict, asr_text: str) -> str:
    keywords = scene.get("danmaku_keywords") or []
    keywords_text = "、".join(str(k) for k in keywords[:8]) if keywords else "（无）"
    return f"""你是专业直播切片策划助手。请分析下面这段直播片段，并严格只输出一个 JSON 对象（不要输出代码块、不要输出任何解释文字）。

时间段：{format_ts(scene['start'])} - {format_ts(scene['end'])}

【画面描述】
{scene.get('visual_summary') or '（无）'}

【语音转写】
{asr_text or '（无）'}

【弹幕统计】
数量：{scene.get('danmaku_count', 0)}；热度：{(scene.get('danmaku_heat') or 0):.2f}；情绪强度：{(scene.get('danmaku_emotion') or 0):.2f}；高频弹幕：{keywords_text}

请输出 JSON，字段如下：
{{
  "title_zh": "中文小标题，15字以内",
  "title_en": "English short title, within 10 words",
  "summary_zh": "中文内容概述：这段时间在做什么，1-3句话",
  "summary_en": "English summary: what is happening, 1-3 sentences",
  "fun_score": 0到10的有趣程度评分（数字）,
  "highlight_score": 0到10的高光/名场面/二创潜力评分（数字）,
  "quote": "从语音转写中选出一句最适合做切片二创的原话（5-50字，必须原样引用），没有就输出空字符串",
  "quote_reason_zh": "这句为什么适合二创，中文一句话；没有则空字符串",
  "quote_reason_en": "English reason, one sentence, or empty string"
}}"""


async def analyze_scenes(client, scenes: list[dict], asr_segments: list[dict],
                         concurrency: int = 4) -> list[dict]:
    """逐段调用 LLM，把标题/概述/评分/单句素材写回 scenes。

    单个场景调用失败时使用空数据继续，只有全部失败才终止任务。
    """
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    failures = 0

    async def one(scene: dict) -> dict:
        nonlocal failures
        asr_text = gather_asr_for_scene(asr_segments, scene["start"], scene["end"])
        prompt = _build_prompt(scene, asr_text)
        messages = [
            {"role": "system", "content": "你是专业的直播切片分析助手，只输出 JSON 对象。"},
            {"role": "user", "content": prompt},
        ]
        async with sem:
            try:
                data = await client.chat_json(messages, model=client.llm_model,
                                              temperature=0.3, max_tokens=1600)
            except AIError as exc:
                failures += 1
                print(f"[timeline] scene {scene['scene_index']} LLM 失败: {exc}")
                data = {}

        scene["title_zh"] = str(data.get("title_zh") or "").strip()
        scene["title_en"] = str(data.get("title_en") or "").strip()
        scene["summary_zh"] = str(data.get("summary_zh") or "").strip()
        scene["summary_en"] = str(data.get("summary_en") or "").strip()
        scene["asr_text"] = asr_text

        try:
            scene["fun_score"] = max(0.0, min(10.0, float(data.get("fun_score") or 0)))
        except (TypeError, ValueError):
            scene["fun_score"] = 0.0
        try:
            scene["highlight_score"] = max(0.0, min(10.0, float(data.get("highlight_score") or 0)))
        except (TypeError, ValueError):
            scene["highlight_score"] = 0.0

        # rank 由 score_scenes 根据 final_score 统一计算，LLM 不再输出 rank
        quote = str(data.get("quote") or "").strip()
        scene["quote"] = quote
        scene["quote_reason_zh"] = str(data.get("quote_reason_zh") or "").strip()
        scene["quote_reason_en"] = str(data.get("quote_reason_en") or "").strip()
        if quote:
            qs, qe = find_quote_time(asr_segments, quote, scene["start"], scene["end"])
            scene["quote_start"] = round(qs, 2)
            scene["quote_end"] = round(qe, 2)
        else:
            scene["quote_start"] = None
            scene["quote_end"] = None
        return scene

    result = await asyncio.gather(*(one(s) for s in scenes))
    if scenes and failures >= len(scenes):
        raise AIError("所有场景的时间轴分析调用均失败，请检查 LLM 模型配置")
    return result
