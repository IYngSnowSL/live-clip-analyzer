"""B站 XML 弹幕解析与统计。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from bisect import bisect_left
from collections import Counter
from pathlib import Path

EMOTION_KEYWORDS = [
    "哈哈", "笑死", "？？", "??", "?", "？", "666", "卧槽", "草", "牛逼",
    "厉害", "离谱", "典", "绷", "急了", "破防", "泪目", "高能", "名场面",
    "啊", "嗯", "绝了", "神", "我去", "天", "真的假的", "下饭", "好看",
    "帅", "强", "顶", "到位", "有东西", "质量局", "nb", "hhh", "hhhh",
    "lol", "lmao", "wtf", "omg", "insane", "crazy", "no way", "!!!",
]

_EMOTION_RE = re.compile("|".join(re.escape(k) for k in EMOTION_KEYWORDS), re.IGNORECASE)


def parse_danmaku_xml(path: str | Path, offset_seconds: float = 0.0) -> list[dict]:
    """解析 B站弹幕 XML（流式，低内存）。返回 [{time, text, mode, ...}, ...]。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"弹幕文件不存在: {path}")
    danmakus: list[dict] = []

    def _process(elem) -> None:
        text = (elem.text or "").strip()
        if not text:
            return
        p = elem.get("p") or ""
        parts = p.split(",")
        try:
            time = float(parts[0]) + offset_seconds
        except (ValueError, IndexError):
            time = 0.0
        if time < 0:
            time = 0.0
        danmakus.append({
            "time": time,
            "text": text,
            "mode": parts[1] if len(parts) > 1 else "",
            "fontsize": parts[2] if len(parts) > 2 else "",
            "color": parts[3] if len(parts) > 3 else "",
            "timestamp": parts[4] if len(parts) > 4 else "",
            "pool": parts[5] if len(parts) > 5 else "",
            "user_hash": parts[6] if len(parts) > 6 else "",
            "dmid": parts[7] if len(parts) > 7 else "",
        })

    parser = ET.XMLPullParser(events=("end",))
    try:
        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                parser.feed(chunk)
                for _, elem in parser.read_events():
                    if elem.tag == "d":
                        _process(elem)
                        elem.clear()
        parser.close()
        for _, elem in parser.read_events():
            if elem.tag == "d":
                _process(elem)
                elem.clear()
    except ET.ParseError as exc:
        raise ValueError(f"弹幕 XML 解析失败: {exc}") from exc
    danmakus.sort(key=lambda d: d["time"])
    return danmakus


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def build_danmaku_stats(danmakus: list[dict], scenes: list[dict]) -> dict[int, dict]:
    """按场景统计弹幕：数量、密度、热度（0-1）、情绪强度（0-1）、高频词。"""
    if not danmakus:
        return {}
    times = [d["time"] for d in danmakus]

    per_scene: list[dict] = []
    max_density = 0.0
    for i, sc in enumerate(scenes):
        start = sc["start"]
        end = sc["end"]
        lo = bisect_left(times, start)
        hi = bisect_left(times, end)
        items = danmakus[lo:hi]
        count = len(items)
        duration = max(0.0, end - start)
        density = count / duration if duration > 0 else 0.0
        max_density = max(max_density, density)

        emotion_hits = 0
        counter: Counter = Counter()
        for d in items:
            text = d["text"]
            emotion_hits += len(_EMOTION_RE.findall(text))
            norm = _normalize(text)
            if 1 <= len(norm) <= 20:
                counter[norm] += 1

        keywords = [d["text"].strip() for d in items if 1 <= len(d["text"].strip()) <= 20]
        keyword_counter = Counter(keywords)
        top_keywords = [k for k, c in keyword_counter.most_common(8) if c >= 2]

        per_scene.append({
            "scene_index": i,
            "count": count,
            "density": density,
            "emotion_hits": emotion_hits,
            "top_keywords": top_keywords,
        })

    stats: dict[int, dict] = {}
    for s in per_scene:
        count = s["count"]
        emotion = 0.0
        if count > 0:
            # 情绪弹幕占比的 3 倍并封顶到 1
            emotion = min(1.0, (s["emotion_hits"] / count) * 3.0)
        heat = s["density"] / max_density if max_density > 0 else 0.0
        stats[s["scene_index"]] = {
            "count": count,
            "density": round(s["density"], 4),
            "heat": round(heat, 4),
            "emotion": round(emotion, 4),
            "keywords": s["top_keywords"],
        }
    return stats
