"""B 站 XML 弹幕：流式解析（大文件低内存）+ 分钟密度聚合 + 轴内峰值查找。

弹幕格式：<d p="time,mode,size,color,timestamp,pool,uid,rowid">文本</d>
p 的第一个字段 = 弹幕出现时间（相对视频的秒数，浮点）。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def parse_danmaku(path: str | Path, offset_seconds: float = 0.0) -> list[dict]:
    """流式解析弹幕 XML，返回 [{t, text}]（t 为应用偏移后的秒数）。

    同步函数，调用方用 asyncio.to_thread 包裹以避免阻塞事件循环。
    """
    out: list[dict] = []
    try:
        for _event, elem in ET.iterparse(str(path), events=("end",)):
            if elem.tag == "d":
                p = (elem.get("p") or "").split(",")
                try:
                    t = float(p[0]) + offset_seconds
                except (ValueError, IndexError):
                    t = 0.0
                out.append({"t": round(t, 1), "text": (elem.text or "").strip()})
                elem.clear()
    except ET.ParseError as exc:
        raise ValueError(f"弹幕 XML 解析失败: {exc}") from exc
    return out


def build_density(danmaku: list[dict], bin_seconds: int = 60) -> list[int]:
    """按分钟聚合弹幕数量，返回列表（索引 = 分钟序号）。"""
    if not danmaku:
        return []
    max_min = int(max(d["t"] for d in danmaku) // bin_seconds)
    density = [0] * (max_min + 1)
    for d in danmaku:
        m = int(d["t"] // bin_seconds)
        if 0 <= m <= max_min:
            density[m] += 1
    return density


def find_peaks(density: list[int], start: float, end: float,
               bin_seconds: int = 60, top_k: int = 3) -> list[dict]:
    """轴时间范围内的弹幕密度峰值，返回 [{t, count}]（t 为该分钟中点，按数量降序）。"""
    if not density:
        return []
    a = int(start // bin_seconds)
    b = min(int(end // bin_seconds), len(density) - 1)
    cands = []
    for m in range(a, b + 1):
        if density[m] > 0:
            cands.append({
                "t": round(m * bin_seconds + bin_seconds / 2, 1),
                "count": density[m],
            })
    cands.sort(key=lambda x: -x["count"])
    return cands[:top_k]
