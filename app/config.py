"""配置加载：读取 config.yaml，提供属性式访问。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULTS: dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8000},
    "data": {"data_dir": "./data"},
    "ai": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-xxxx",
        "vision_model": "gpt-4o",
        "llm_model": "gpt-4o-mini",
        "asr_model": "whisper-1",
        "timeout": 180,
        "concurrency": 4,
    },
    "asr": {"chunk_seconds": 1200, "language": ""},
    "vision": {"frame_interval": 15, "max_frames_per_scene": 2},
    "scene": {"min_scene_seconds": 8, "max_scene_seconds": 30, "threshold": 0.35},
    "scoring": {
        "weights": {
            "danmaku_heat": 0.25,
            "danmaku_emotion": 0.20,
            "fun": 0.35,
            "highlight": 0.20,
        },
        "long_candidate_min_score": 6.5,
        "long_candidate_min_minutes": 1.0,
        "long_candidate_max_minutes": 5.0,
        "merge_gap_seconds": 20.0,
        "max_long_candidates": 20,
        "sentence_candidate_min_score": 5.0,
        "max_sentence_candidates": 30,
    },
    "report": {"languages": ["zh", "en"]},
    "export": {
        "accurate": False,       # False=无损快速剪切（关键帧对齐），True=重编码精切
        "concurrency": 1,        # 同时导出几个切片
    },
}


class DotDict(dict):
    """支持属性访问的字典，嵌套字典自动转换。"""

    def __getattr__(self, item: str) -> Any:
        try:
            val = self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc
        if isinstance(val, dict) and not isinstance(val, DotDict):
            val = DotDict(val)
            self[item] = val
        return val

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value

    def __delattr__(self, item: str) -> None:
        try:
            del self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并 override 到 base。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> DotDict:
    """加载配置。path 为空时使用项目根目录 config.yaml。"""
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    loaded: dict = {}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
    merged = deep_merge(DEFAULTS, loaded)
    cfg = DotDict(merged)

    # 解析数据目录
    data_dir = Path(cfg.data.data_dir)
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    cfg.data.data_dir = str(data_dir)
    cfg.data.tasks_dir = str(data_dir / "tasks")
    cfg.data.db_path = str(data_dir / "app.db")
    return cfg
