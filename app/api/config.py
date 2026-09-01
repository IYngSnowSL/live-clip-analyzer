"""配置读写接口：供 WebUI 配置页使用。

设计（见 docs/adr/0004）：
- 只写入 config.local.yaml（gitignore），不触碰 config.yaml。
- api_key 读取时脱敏，写入时仅当传入非掩码的新值才更新。
- 环境变量优先级高于配置文件，若某项被 LCA_* 覆盖，配置页改动不生效（UI 会提示）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

from ..config import PROJECT_ROOT, load_config

router = APIRouter(prefix="/api/config", tags=["config"])

# 前端扁平字段 -> 配置路径（点分隔）。api_key 单独特殊处理。
_FIELD_MAP: dict[str, str] = {
    "base_url": "ai.base_url",
    "api_key": "ai.api_key",
    "vision_model": "ai.vision_model",
    "llm_model": "ai.llm_model",
    "asr_model": "ai.asr_model",
    "target_min_seconds": "axle.target_min_seconds",
    "target_max_seconds": "axle.target_max_seconds",
    "export_accurate": "export.accurate",
}

_PLACEHOLDER_KEY = "sk-xxxx"


def mask_key(key: str) -> str:
    """脱敏：短 key 全掩，长 key 保留前 3 + 后 4 位。"""
    key = str(key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}{'*' * (len(key) - 7)}{key[-4:]}"


def _get_dotted(cfg: dict, dotted: str, default: Any = None) -> Any:
    node: Any = cfg
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def _set_dotted(target: dict, dotted: str, value: Any) -> None:
    node = target
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _local_config_path() -> Path:
    return PROJECT_ROOT / "config.local.yaml"


@router.get("")
async def get_config() -> dict:
    """返回当前生效配置，api_key 脱敏。"""
    cfg = load_config()
    result: dict[str, Any] = {}
    for flat, dotted in _FIELD_MAP.items():
        val = _get_dotted(cfg, dotted)
        if flat == "api_key":
            result[flat] = mask_key(val)
        else:
            result[flat] = val
    raw_key = str(cfg.ai.api_key or "").strip()
    result["has_api_key"] = bool(raw_key) and raw_key != _PLACEHOLDER_KEY
    return result


class ConfigUpdate(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    vision_model: str | None = None
    llm_model: str | None = None
    asr_model: str | None = None
    target_min_seconds: float | None = None
    target_max_seconds: float | None = None
    export_accurate: bool | None = None


@router.put("")
async def update_config(payload: ConfigUpdate) -> dict:
    """把配置写入 config.local.yaml，返回脱敏后的最新配置。"""
    local_path = _local_config_path()
    local: dict = {}
    if local_path.exists():
        with open(local_path, "r", encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}

    data = payload.model_dump(exclude_none=True)

    # api_key：仅当传入的是非掩码、非占位符的新值才更新
    key = (data.get("api_key") or "").strip()
    if key and "*" not in key and key != _PLACEHOLDER_KEY:
        _set_dotted(local, "ai.api_key", key)

    for flat, dotted in _FIELD_MAP.items():
        if flat == "api_key" or flat not in data:
            continue
        _set_dotted(local, dotted, data[flat])

    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(local, f, allow_unicode=True, sort_keys=False)

    return await get_config()
