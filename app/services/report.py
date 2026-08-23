"""Markdown / JSON 报告生成。"""
from __future__ import annotations

import json
from pathlib import Path

from .ffmpeg_utils import format_ts

_LANG = {
    "zh": {
        "title": "直播切片分析报告",
        "overview": "概览",
        "video_duration": "视频时长",
        "scene_count": "时间轴片段数",
        "long_count": "长切片候选",
        "sentence_count": "单句素材候选",
        "timeline": "详细时间轴",
        "long_candidates": "长切片候选",
        "sentence_candidates": "单句素材候选",
        "visual": "画面",
        "content": "内容",
        "asr": "语音",
        "danmaku": "弹幕",
        "score": "评分",
        "rank": "推荐",
        "rank_names": {"high": "高", "medium": "中", "low": "低"},
        "reason": "推荐理由",
        "keywords": "关键词",
    },
    "en": {
        "title": "Live Clip Analysis Report",
        "overview": "Overview",
        "video_duration": "Duration",
        "scene_count": "Timeline segments",
        "long_count": "Long clip candidates",
        "sentence_count": "Quote candidates",
        "timeline": "Detailed Timeline",
        "long_candidates": "Long Clip Candidates",
        "sentence_candidates": "Quote Candidates",
        "visual": "Visual",
        "content": "Summary",
        "asr": "ASR",
        "danmaku": "Danmaku",
        "score": "Score",
        "rank": "Rank",
        "rank_names": {"high": "High", "medium": "Medium", "low": "Low"},
        "reason": "Reason",
        "keywords": "Keywords",
    },
}


def _scene_to_md(sc: dict, lang: str) -> str:
    t = _LANG[lang]
    rank = str(sc.get("rank") or "low")
    rank_name = t["rank_names"].get(rank, rank)
    title = sc.get("title_zh") if lang == "zh" else sc.get("title_en")
    summary = sc.get("summary_zh") if lang == "zh" else sc.get("summary_en")
    quote_reason = sc.get("quote_reason_zh") if lang == "zh" else sc.get("quote_reason_en")
    keywords = sc.get("danmaku_keywords") or []
    na = "（无）" if lang == "zh" else "N/A"
    kw_text = "、".join(str(k) for k in keywords) if keywords else na

    lines = [
        f"### [{format_ts(sc['start'])} - {format_ts(sc['end'])}] {title or ''}",
        f"- **{t['content']}**：{summary or na}",
        f"- **{t['visual']}**：{sc.get('visual_summary') or na}",
        f"- **{t['asr']}**：{sc.get('asr_text') or na}",
        f"- **{t['danmaku']}**：数量 {sc.get('danmaku_count', 0)} / 热度 "
        f"{float(sc.get('danmaku_heat') or 0):.2f} / 情绪 {float(sc.get('danmaku_emotion') or 0):.2f} / "
        f"高频：{kw_text}",
        f"- **{t['score']}**：{sc.get('final_score', 0)} / {t['rank']}：{rank_name}",
    ]
    if sc.get("quote"):
        qs = sc.get("quote_start")
        qs = qs if qs is not None else sc["start"]
        lines.append(f"- **Quote**：[{format_ts(qs)}] {sc.get('quote')}")
        if quote_reason:
            lines.append(f"  - {t['reason']}：{quote_reason}")
    return "\n".join(lines)


def _candidate_to_md(c: dict, lang: str) -> str:
    t = _LANG[lang]
    title = c.get("review_title") or (c.get("title_zh") if lang == "zh" else c.get("title_en"))
    start = c.get("review_start") if c.get("review_start") is not None else c.get("start")
    end = c.get("review_end") if c.get("review_end") is not None else c.get("end")
    score = c.get("review_score") if c.get("review_score") is not None else c.get("score")
    rank = c.get("review_rank") if c.get("review_rank") else ("high" if float(score or 0) >= 7.5 else "medium" if float(score or 0) >= 5.0 else "low")
    rank_name = t["rank_names"].get(rank, rank)
    reason = c.get("reason_zh") if lang == "zh" else c.get("reason_en")
    keywords = c.get("keywords") or []
    na = "（无）" if lang == "zh" else "N/A"
    kw_text = "、".join(str(k) for k in keywords) if keywords else na

    if c["type"] == "sentence":
        return (f"1. **[{format_ts(start)}] {title}**（{t['score']} {score}）\n"
                f"   - {t['reason']}：{reason or na}")
    return (f"1. **[{format_ts(start)} - {format_ts(end)}] {title}**"
            f"（{t['score']} {score} / {t['rank']}：{rank_name}）\n"
            f"   - {t['reason']}：{reason or na}\n"
            f"   - {t['keywords']}：{kw_text}")


def build_report_markdown(task: dict, scenes: list[dict], candidates: list[dict], lang: str) -> str:
    """生成指定语言的 Markdown 报告文本。"""
    t = _LANG[lang]
    duration = sum(float(sc["end"]) - float(sc["start"]) for sc in scenes)
    long_cands = [c for c in candidates if c["type"] == "long"]
    sentence_cands = [c for c in candidates if c["type"] == "sentence"]

    lines = [
        f"# {t['title']}",
        "",
        f"> 视频：`{task.get('video_path','')}`",
        f"> 弹幕：`{task.get('danmaku_path') or '（无）'}`",
        f"> 生成时间：{task.get('updated_at') or ''}",
        "",
        f"## {t['overview']}",
        "",
        f"- {t['video_duration']}：{format_ts(duration)}",
        f"- {t['scene_count']}：{len(scenes)}",
        f"- {t['long_count']}：{len(long_cands)}",
        f"- {t['sentence_count']}：{len(sentence_cands)}",
        "",
        f"## {t['timeline']}",
        "",
    ]
    for sc in scenes:
        lines.append(_scene_to_md(sc, lang))
        lines.append("")

    na = "（无）" if lang == "zh" else "None"
    lines += [f"## {t['long_candidates']}", ""]
    if long_cands:
        for c in long_cands:
            lines.append(_candidate_to_md(c, lang))
            lines.append("")
    else:
        lines.append(na)
        lines.append("")

    lines += [f"## {t['sentence_candidates']}", ""]
    if sentence_cands:
        for c in sentence_cands:
            lines.append(_candidate_to_md(c, lang))
            lines.append("")
    else:
        lines.append(na)
        lines.append("")

    return "\n".join(lines)


def build_reports(task: dict, scenes: list[dict], candidates: list[dict],
                  task_dir: str | Path, languages: list[str]) -> dict[str, str]:
    """生成报告文件，返回 {lang: 文件路径}。"""
    task_dir = Path(task_dir)
    task_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for lang in languages:
        if lang not in _LANG:
            continue
        md = build_report_markdown(task, scenes, candidates, lang)
        path = task_dir / f"report_{lang}.md"
        path.write_text(md, encoding="utf-8")
        paths[lang] = str(path)
    return paths


def build_export_json(task: dict, scenes: list[dict], candidates: list[dict]) -> dict:
    """结构化 JSON 导出。"""
    return {
        "task": task,
        "scenes": scenes,
        "candidates": candidates,
    }
