"""切片综合评分。"""
from __future__ import annotations


def score_scenes(scenes: list[dict], weights) -> list[dict]:
    """综合弹幕热度、弹幕情绪、内容有趣度、高光潜力，计算 0-10 分。"""
    w_heat = float(weights.danmaku_heat)
    w_emotion = float(weights.danmaku_emotion)
    w_fun = float(weights.fun)
    w_highlight = float(weights.highlight)

    # 全片无弹幕时，弹幕权重按比例转给有趣度与高光潜力，避免分数天花板过低
    # （否则最高只能拿到 fun+highlight 权重之和的分，永远达不到候选阈值）
    if scenes and sum(int(s.get("danmaku_count") or 0) for s in scenes) == 0:
        w_fun += w_heat / 2 + w_emotion / 2
        w_highlight += w_heat / 2 + w_emotion / 2
        w_heat = 0.0
        w_emotion = 0.0

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
