"""自动打轴：唯一核心功能。

从 ASR 字幕中自动找出可切片的"轴"（内容单元），为切片二创提供
精确起止时间与内容说明（标题 / 理由 / 评分）。

流程（ADR-0006）：
1. LLM 分窗分析字幕 → 找出内容点并初步打轴
2. 合并相邻内容点 + 长度约束（目标 1~3 分钟，硬上限 10 分钟）
3. ffmpeg silencedetect 静音点精修每个轴的起止（边界干净，不留杂音）
"""
from __future__ import annotations

import asyncio
import re

from .ai_client import AIError
from .ffmpeg_utils import ffmpeg_bin, format_ts, run_async

# ---------------- LLM 找内容点 ----------------

FIND_POINTS_PROMPT = """你是专业的直播切片策划师。下面是一段直播录播的带时间戳字幕（每行格式 [HH:MM:SS] 内容）。

请找出所有值得切成二创切片的内容点（名场面、趣点、高光、爆点、话题、情绪拉满时刻），
为每个内容点"打轴"：给出精确的起止时间（必须取自字幕行的时间戳，边界切在完整句子处，不截断半句话）。

严格只输出一个 JSON 对象（不要代码块、不要解释文字），格式：
{"points": [
  {"start": "HH:MM:SS", "end": "HH:MM:SS", "title": "切片标题（15字内）", "reason": "为什么值得切", "score": 8}
]}

要求：
- start / end 必须使用字幕中出现过的时间戳（HH:MM:SS）
- 每个内容点目标 1~3 分钟；内容自然更长时最多 10 分钟
- score 为 0~10 的整数，10 分 = 顶级名场面；低于 5 分的不要输出
- reason 必须详细具体，包含"素材用途"分析：说明为什么值得切（起因、看点、情绪点、
  适合做什么类型的二创），并引用该片段内 2~4 条**原话素材**——原话逐字取自字幕行、
  用引号括起、附时间戳（HH:MM:SS），方便视频创作者判断每句素材的用途（开场/标题/结尾/笑点），
  例如：
  "01:23:45 主播惊呼'这波操作太秀了'，全场情绪引爆，适合做高能操作集锦；
   01:24:30 金句'再给我一次机会我还能翻'，可做标题或结尾；
   01:25:10 '兄弟们看好了'，适合开场。整段为逆风翻盘局，情绪起伏完整"
- 宁可多给候选，不要漏掉精彩内容"""


def _ts_to_seconds(ts: str) -> float:
    """HH:MM:SS / MM:SS 转秒。非法输入返回 0。"""
    parts = str(ts or "").strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except (TypeError, ValueError):
        pass
    return 0.0


def _window_text(asr_segments: list[dict], start: float, end: float) -> str:
    """把 [start, end) 时间窗内的字幕整理成带时间戳文本。"""
    lines = []
    for seg in asr_segments:
        s = float(seg["start"])
        e = float(seg["end"])
        if e <= start or s >= end:
            continue
        lines.append(f"[{format_ts(s)}] {(seg.get('text') or '').strip()}")
    return "\n".join(lines)


async def find_points(client, asr_segments: list[dict], axle_cfg) -> list[dict]:
    """分窗调 LLM 找内容点，返回 [{start, end, title, reason, score}]。"""
    window = max(60, int(getattr(axle_cfg, "window_seconds", 600)))
    overlap = int(getattr(axle_cfg, "overlap_seconds", 60))
    total_start = float(asr_segments[0]["start"])
    total_end = float(asr_segments[-1]["end"])
    step = max(window // 5, window - overlap)
    sem = asyncio.Semaphore(max(1, int(client.concurrency)))
    failures = 0

    async def one(win_start: float) -> list[dict]:
        nonlocal failures
        win_end = min(win_start + window, total_end)
        text = _window_text(asr_segments, win_start, win_end)
        if not text.strip():
            return []
        try:
            async with sem:
                data = await client.analyze_document(
                    text, FIND_POINTS_PROMPT, json_mode=True, max_tokens=4000
                )
        except AIError as exc:
            failures += 1
            print(f"[axle] 分窗找内容点失败 (窗口起点 {format_ts(win_start)}): {exc}")
            return []
        points = []
        for p in data.get("points") or []:
            start = _ts_to_seconds(p.get("start"))
            end = _ts_to_seconds(p.get("end"))
            if end <= start or start < 0:
                continue
            points.append({
                "start": round(start, 2),
                "end": round(end, 2),
                "title": str(p.get("title") or "").strip(),
                "reason": str(p.get("reason") or "").strip(),
                "score": float(p.get("score") or 0),
            })
        return points

    windows = []
    cursor = total_start
    while cursor < total_end:
        windows.append(cursor)
        cursor += step
    results = await asyncio.gather(*(one(w) for w in windows))
    points = [p for sub in results for p in sub]
    if windows and failures >= len(windows):
        raise AIError("所有分窗的内容点分析均失败，请检查 LLM 配置")

    # 去重：起点接近的点保留分数高的
    points.sort(key=lambda p: (p["start"], -(p["score"] or 0)))
    deduped: list[dict] = []
    for p in points:
        if deduped and abs(p["start"] - deduped[-1]["start"]) < 5:
            if (p["score"] or 0) > (deduped[-1]["score"] or 0):
                deduped[-1] = p
            continue
        deduped.append(p)
    return deduped


# ---------------- 合并 + 长度约束 ----------------

def merge_points(points: list[dict], axle_cfg) -> list[dict]:
    """合并相邻内容点，应用长度约束（目标 1~3 分钟，硬上限 10 分钟）。"""
    target_min = float(getattr(axle_cfg, "target_min_seconds", 60))
    target_max = float(getattr(axle_cfg, "target_max_seconds", 180))
    hard_max = max(target_max, float(getattr(axle_cfg, "hard_max_seconds", 600)))
    merge_gap = float(getattr(axle_cfg, "merge_gap_seconds", 30))

    if not points:
        return []
    points = sorted(points, key=lambda p: p["start"])

    merged: list[dict] = []
    for p in points:
        if merged and p["start"] - merged[-1]["end"] <= merge_gap:
            merged[-1]["end"] = max(merged[-1]["end"], p["end"])
            if (p["score"] or 0) > (merged[-1]["score"] or 0):
                merged[-1].update(
                    score=p["score"], title=p["title"], reason=p["reason"])
            continue
        merged.append(dict(p))

    axles: list[dict] = []
    for p in merged:
        dur = p["end"] - p["start"]
        if dur > hard_max:
            cur = p["start"]
            while cur < p["end"] - 1:
                seg_end = min(cur + target_max, p["end"])
                if seg_end - cur < target_min:
                    seg_end = min(cur + target_min, p["end"])
                axles.append({**p, "start": round(cur, 2), "end": round(seg_end, 2)})
                cur = seg_end
        elif dur >= 20:  # 太短的碎片丢弃（Q3 大量候选，仍留 20 秒以上）
            axles.append({**p, "start": round(p["start"], 2), "end": round(p["end"], 2)})

    max_axles = max(1, int(getattr(axle_cfg, "max_axles", 100)))
    axles.sort(key=lambda a: -(a["score"] or 0))
    return axles[:max_axles]


# ---------------- 静音点精修 ----------------

async def detect_silences(video_path, threshold_db: float = -35,
                          min_seconds: float = 0.4) -> list[dict]:
    """ffmpeg silencedetect 检测全片静音区间，返回 [{start, end}]。"""
    cmd = [
        ffmpeg_bin(), "-hide_banner", "-i", str(video_path),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_seconds}",
        "-f", "null", "-",
    ]
    try:
        _, stderr = await run_async(cmd, timeout=7200)
    except RuntimeError as exc:
        print(f"[axle] silencedetect 执行失败，跳过精修: {exc}")
        return []
    text = stderr.decode("utf-8", errors="ignore")
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", text)]
    return [{"start": s, "end": e} for s, e in zip(starts, ends)]


def refine_axle_bounds(axle: dict, silences: list[dict], pad: float = 0.3) -> dict:
    """用静音点精修轴边界：起点移到最近静音区之后，终点移到最近静音区之前。"""
    start, end = float(axle["start"]), float(axle["end"])

    best_s = None
    for sil in silences:
        if start - 5 <= sil["start"] <= start + 10:
            if best_s is None or abs(sil["start"] - start) < abs(best_s["start"] - start):
                best_s = sil
    if best_s:
        start = min(best_s["end"] + pad, end - 1)

    best_e = None
    for sil in silences:
        if end - 10 <= sil["start"] <= end + 5:
            if best_e is None or abs(sil["start"] - end) < abs(best_e["start"] - end):
                best_e = sil
    if best_e:
        end = max(best_e["start"] - pad, start + 1)

    return {**axle, "start": round(start, 2), "end": round(end, 2)}


# ---------------- 主入口 ----------------

async def build_axles(client, video_path, asr_segments: list[dict], axle_cfg) -> list[dict]:
    """自动打轴主入口：LLM 找点 → 合并约束 → 静音精修。"""
    points = await find_points(client, asr_segments, axle_cfg)
    if not points:
        return []
    axles = merge_points(points, axle_cfg)
    if axles:
        silences = await detect_silences(
            video_path,
            float(getattr(axle_cfg, "silence_threshold_db", -35)),
            float(getattr(axle_cfg, "silence_min_seconds", 0.4)),
        )
        if silences:
            axles = [refine_axle_bounds(a, silences) for a in axles]
    axles.sort(key=lambda a: a["start"])
    return axles
