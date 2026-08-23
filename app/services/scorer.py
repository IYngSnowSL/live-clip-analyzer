"""切片综合评分。"""
from __future__ import annotations


def score_scenes(scenes: list[dict], weights) -> list[dict]:
    """综合弹幕热度、弹幕情绪、内容有趣度、高光潜力，计算 0-10 分。"""
    w_heat = float(weights.danmaku_heat)
    w_emotion = float(weights.danmaku_emotion)
    w_fun = float(weights.fun)
    w_highlight = float(weights.highlight)
    total_weight = w_heat + w_emotion + w_fun + w_highlight
    if total_weight <= 0:
        total_weight = 1.0

    for sc in scenes:
        heat = float(sc.get("danmaku_heat") or 0)
        emotion = float(sc.get("danmaku_emotion") or 0)
        fun = float(sc.get("fun_score") or 0) / 10.0
        highlight = float(sc.get("highlight_score") or 0) / 10.0

        final = (
            w_heat * heat
            + w_emotion * emotion
            + w_fun * fun
            + w_highlight * highlight
        ) / total_weight * 10.0

        sc["final_score"] = round(final, 2)
        if final >= 7.5:
            sc["rank"] = "high"
        elif final >= 5.0:
            sc["rank"] = "medium"
        else:
            sc["rank"] = "low"
    return scenes
