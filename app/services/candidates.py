"""切片候选生成：长切片候选 + 单句二创素材候选。"""
from __future__ import annotations

from typing import Any


def generate_long_candidates(scenes: list[dict], scoring_cfg) -> list[dict[str, Any]]:
    """合并高分场景，生成长切片候选。"""
    min_score = float(scoring_cfg.long_candidate_min_score)
    min_duration = float(scoring_cfg.long_candidate_min_minutes) * 60.0
    max_duration = float(scoring_cfg.long_candidate_max_minutes) * 60.0
    merge_gap = float(scoring_cfg.merge_gap_seconds)
    max_count = int(scoring_cfg.max_long_candidates)

    high = [s for s in scenes if float(s.get("final_score") or 0) >= min_score]
    if not high:
        return []

    groups: list[list[dict]] = []
    for sc in high:
        if not groups:
            groups.append([sc])
            continue
        last = groups[-1][-1]
        gap = float(sc["start"]) - float(last["end"])
        if gap <= merge_gap:
            groups[-1].append(sc)
        else:
            groups.append([sc])

    candidates: list[dict[str, Any]] = []
    for group in groups:
        group_start = float(group[0]["start"])
        group_end = float(group[-1]["end"])
        total_duration = group_end - group_start
        if total_duration < min_duration:
            continue

        # 过长则按最大时长切块
        chunk_start = group_start
        while chunk_start < group_end - 0.5:
            chunk_end = min(chunk_start + max_duration, group_end)
            if chunk_end - chunk_start < min_duration:
                break
            cand = _build_long_candidate(group, chunk_start, chunk_end)
            if cand:
                candidates.append(cand)
            chunk_start = chunk_end

    candidates.sort(key=lambda c: float(c.get("score") or 0), reverse=True)
    return candidates[:max_count]


def _build_long_candidate(group: list[dict], start: float, end: float) -> dict[str, Any] | None:
    chunk_scenes = [s for s in group if float(s["start"]) < end and float(s["end"]) > start]
    if not chunk_scenes:
        return None
    best = max(chunk_scenes, key=lambda s: float(s.get("final_score") or 0))
    score = float(best.get("final_score") or 0)
    rank = "high" if score >= 7.5 else "medium" if score >= 5.0 else "low"
    keywords: list[str] = []
    for s in chunk_scenes:
        for kw in (s.get("danmaku_keywords") or []):
            if kw not in keywords:
                keywords.append(kw)
            if len(keywords) >= 10:
                break
        if len(keywords) >= 10:
            break

    return {
        "type": "long",
        "start": round(start, 2),
        "end": round(end, 2),
        "title_zh": best.get("title_zh") or f"高光片段 {int(start)}s-{int(end)}s",
        "title_en": best.get("title_en") or f"Highlight {int(start)}s-{int(end)}s",
        "score": round(score, 2),
        "reason_zh": best.get("summary_zh") or "",
        "reason_en": best.get("summary_en") or "",
        "keywords": keywords,
    }


def generate_sentence_candidates(scenes: list[dict], scoring_cfg) -> list[dict[str, Any]]:
    """从 LLM 提取的 quote 中生成单句二创素材候选。"""
    min_score = float(scoring_cfg.sentence_candidate_min_score)
    max_count = int(scoring_cfg.max_sentence_candidates)

    candidates: list[dict[str, Any]] = []
    for sc in scenes:
        quote = (sc.get("quote") or "").strip()
        if not quote:
            continue
        score = float(sc.get("final_score") or 0)
        if score < min_score:
            continue
        quote_start = sc.get("quote_start")
        quote_end = sc.get("quote_end")
        candidates.append({
            "type": "sentence",
            "start": round(float(quote_start if quote_start is not None else sc["start"]), 2),
            "end": round(float(quote_end if quote_end is not None else sc["end"]), 2),
            "title_zh": quote,
            "title_en": quote,
            "score": round(score, 2),
            "reason_zh": sc.get("quote_reason_zh") or "该句具有二创潜力",
            "reason_en": sc.get("quote_reason_en") or "Potential meme/quote material",
            "keywords": [],
        })

    candidates.sort(key=lambda c: float(c.get("score") or 0), reverse=True)
    return candidates[:max_count]
