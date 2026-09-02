"""配置加载：读取 config.yaml，提供属性式访问。

加载顺序（后者覆盖前者）：
1. 内置 DEFAULTS
2. config.yaml（提交到 git，只放占位符）
3. config.local.yaml（不提交，放真实 key）
4. 环境变量（LCA_*，优先级最高，适合本机开发）
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 环境变量覆盖映射："配置路径" -> "环境变量名"
ENV_OVERRIDES: dict[str, str] = {
    "ai.base_url": "LCA_BASE_URL",
    "ai.api_key": "LCA_API_KEY",
    "ai.vision_model": "LCA_VISION_MODEL",
    "ai.llm_model": "LCA_LLM_MODEL",
    "ai.asr_model": "LCA_ASR_MODEL",
}

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
        # 高级设置：每个模型能力可单独指定接口地址与密钥（空值 = 继承上面的全局配置）
        "endpoints": {
            "llm": {"base_url": "", "api_key": ""},
            "vision": {"base_url": "", "api_key": ""},
            "asr": {"base_url": "", "api_key": ""},
        },
    },
    "asr": {"chunk_seconds": 1200, "language": ""},
    "axle": {
        "window_seconds": 600,        # LLM 找内容点的分窗大小（秒）
        "overlap_seconds": 60,        # 相邻窗重叠（秒），避免漏掉跨窗内容点
        "target_min_seconds": 30,     # 目标最短时长（秒）= 30 秒
        "target_max_seconds": 3600,   # 目标最长时长（秒）= 1 小时
        "hard_max_seconds": 3600,     # 硬上限（秒）= 1 小时，超过自动拆分
        "merge_gap_seconds": 30,      # 相邻内容点合并间隔（秒）
        "max_axles": 100,             # 最多输出轴数
        "silence_threshold_db": -35,  # 静音检测阈值（dB）
        "silence_min_seconds": 0.4,   # 静音最短时长（秒）
    },
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


def _apply_env_overrides(cfg: dict) -> None:
    """把 LCA_* 环境变量写入配置树（仅覆盖已显式设置的变量）。"""
    for dotted, env_name in ENV_OVERRIDES.items():
        val = os.environ.get(env_name)
        if not val:
            continue
        node = cfg
        keys = dotted.split(".")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = val


def load_config(path: str | Path | None = None) -> DotDict:
    """加载配置。path 为空时使用项目根目录 config.yaml（可被 config.local.yaml 覆盖）。"""
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    loaded: dict = {}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
    local_path = cfg_path.with_name("config.local.yaml")
    if local_path.exists():
        with open(local_path, "r", encoding="utf-8") as f:
            loaded = deep_merge(loaded, yaml.safe_load(f) or {})
    merged = deep_merge(DEFAULTS, loaded)
    _apply_env_overrides(merged)
    cfg = DotDict(merged)

    # 解析数据目录
    data_dir = Path(cfg.data.data_dir)
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    cfg.data.data_dir = str(data_dir)
    cfg.data.tasks_dir = str(data_dir / "tasks")
    cfg.data.db_path = str(data_dir / "app.db")
    return cfg
