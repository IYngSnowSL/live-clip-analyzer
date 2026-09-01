"""字幕语义切分：从 ASR 转写字幕中切出话题段（层次化第一级）。

流程（纯 Python 预筛 + LLM 命名）：
1. 分窗（window_seconds，重叠 overlap_seconds）
2. 预筛：相邻窗字符 2-gram 关键词集合的 Jaccard 相似度，低于阈值视为话题切换点
3. 构建话题段：在切换点切分，过短段并入相邻
4. LLM 为每个话题段生成标题 / 摘要 / 关键词（走 AI 门面 analyze_document）
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter

from .ai_client import AIError
from .subtitle import chunk_by_window


def extract_keywords(text: str, top_k: int = 20) -> set[str]:
    """提取文本关键词（字符 2-gram，过滤标点/空白）。零依赖的轻量近似。"""
    text = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]+", "", text or "")
    if len(text) < 2:
        return set()
    counter: Counter = Counter()
    for i in range(len(text) - 1):
        gram = text[i:i + 2]
        if not gram[0].isdigit() and not gram[1].isdigit():
            counter[gram] += 1
    return {g for g, _ in counter.most_common(top_k)}


def jaccard(a: set, b: set) -> float:
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def preselect_boundaries(chunks: list[dict], threshold: float = 0.35) -> list[int]:
    """预筛：返回"应在此处切分"的 chunk 索引列表（i 表示在 chunk[i] 与 chunk[i+1] 之间切）。"""
    sigs = [extract_keywords(c["text"]) for c in chunks]
    candidates: list[int] = []
    for i in range(len(sigs) - 1):
        if jaccard(sigs[i], sigs[i + 1]) < threshold:
            candidates.append(i)
    return candidates


def build_topics(chunks: list[dict], boundary_indices: list[int],
                 min_topic_seconds: float = 120.0) -> list[dict]:
    """根据候选切换点把分窗合并成话题段，返回 [{start, end, text}]（无重叠）。"""
    if not chunks:
        return []
    boundary_set = set(boundary_indices)
    cut_points: dict[int, float] = {}
    for i in boundary_set:
        if 0 <= i < len(chunks) - 1:
            # 切换点取相邻两窗重叠区的中点，保证话题段无重叠
            cut_points[i] = (chunks[i]["end"] + chunks[i + 1]["start"]) / 2

    topics: list[dict] = []
    seg_start = chunks[0]["start"]
    seg_text: list[str] = []
    for i in range(len(chunks)):
        seg_text.append(chunks[i]["text"])
        if i in cut_points:
            seg_end = cut_points[i]
            if seg_end - seg_start >= min_topic_seconds:
                topics.append({
                    "start": round(seg_start, 2),
                    "end": round(seg_end, 2),
                    "text": " ".join(seg_text),
                })
                seg_start = seg_end
                seg_text = []
    seg_end = chunks[-1]["end"]
    if seg_start < seg_end:
        topics.append({
            "start": round(seg_start, 2),
            "end": round(seg_end, 2),
            "text": " ".join(seg_text),
        })
    return topics


async def segment_topics(client, asr_segments: list[dict], seg_cfg) -> list[dict]:
    """字幕语义切分主入口：分窗 + 预筛 + 建话题段。

    返回话题段列表 [{start, end, text}]（尚未命名，未加 task_id / topic_index）。
    """
    if not asr_segments:
        return []
    chunks = chunk_by_window(
        asr_segments,
        int(getattr(seg_cfg, "window_seconds", 600)),
        int(getattr(seg_cfg, "overlap_seconds", 60)),
    )
    if not chunks:
        return []
    if len(chunks) == 1:
        topics = [{"start": chunks[0]["start"], "end": chunks[0]["end"], "text": chunks[0]["text"]}]
    else:
        boundaries = preselect_boundaries(chunks, float(getattr(seg_cfg, "threshold", 0.35)))
        topics = build_topics(chunks, boundaries, float(getattr(seg_cfg, "min_topic_seconds", 120)))
    max_topics = max(1, int(getattr(seg_cfg, "max_topics", 50)))
    return topics[:max_topics]


ANALYZE_TOPIC_PROMPT = (
    "请为下面这段直播字幕内容生成一个简短的话题总结。"
    "严格只输出一个 JSON 对象（不要代码块、不要解释），字段如下：\n"
    '{\n  "title_zh": "中文话题标题，15字以内",\n'
    '  "title_en": "English topic title, within 8 words",\n'
    '  "summary_zh": "中文概述：这段主要在聊什么，1-2句话",\n'
    '  "summary_en": "English summary, 1-2 sentences",\n'
    '  "keywords": ["关键词1", "关键词2", "关键词3"]\n}'
)


async def analyze_topics(client, topics: list[dict], concurrency: int = 4) -> list[dict]:
    """用 LLM 为每个话题段生成标题 / 摘要 / 关键词。单个失败不中断，全部失败才报错。"""
    sem = asyncio.Semaphore(max(1, int(concurrency)))
    failures = 0

    async def one(t: dict) -> dict:
        nonlocal failures
        text = (t.get("text") or "")[:4000]
        try:
            async with sem:
                data = await client.analyze_document(
                    text, ANALYZE_TOPIC_PROMPT, json_mode=True, max_tokens=800
                )
        except AIError as exc:
            failures += 1
            print(f"[segmentation] 话题段分析失败: {exc}")
            data = {}
        t["title_zh"] = str(data.get("title_zh") or "").strip()
        t["title_en"] = str(data.get("title_en") or "").strip()
        t["summary_zh"] = str(data.get("summary_zh") or "").strip()
        t["summary_en"] = str(data.get("summary_en") or "").strip()
        t["keywords"] = list(data.get("keywords") or [])
        t["score"] = 0.0
        return t

    result = await asyncio.gather(*(one(t) for t in topics))
    if topics and failures >= len(topics):
        raise AIError("所有话题段的 LLM 分析均失败，请检查 LLM 模型配置")
    return result
