"""配置读写接口：供 WebUI 配置页使用。

设计（见 docs/adr/0004）：
- 只写入 config.local.yaml（gitignore），不触碰 config.yaml。
- api_key 读取时脱敏，写入时仅当传入非掩码的新值才更新。
- 环境变量优先级高于配置文件，若某项被 LCA_* 覆盖，配置页改动不生效（UI 会提示）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import PROJECT_ROOT, load_config

router = APIRouter(prefix="/api/config", tags=["config"])

# 前端扁平字段 -> 配置路径（点分隔）。api_key 类字段单独特殊处理。
_FIELD_MAP: dict[str, str] = {
    "base_url": "ai.base_url",
    "api_key": "ai.api_key",
    "vision_model": "ai.vision_model",
    "llm_model": "ai.llm_model",
    "asr_model": "ai.asr_model",
    "llm_base_url": "ai.endpoints.llm.base_url",
    "llm_api_key": "ai.endpoints.llm.api_key",
    "vision_base_url": "ai.endpoints.vision.base_url",
    "vision_api_key": "ai.endpoints.vision.api_key",
    "asr_base_url": "ai.endpoints.asr.base_url",
    "asr_api_key": "ai.endpoints.asr.api_key",
    "asr_engine": "asr.engine",
    "local_model_path": "asr.local_model_path",
    "subtitle_max_chars": "asr.subtitle_max_chars",
    "target_min_seconds": "axle.target_min_seconds",
    "target_max_seconds": "axle.target_max_seconds",
    "export_accurate": "export.accurate",
}

_KEY_FIELDS = {"api_key", "llm_api_key", "vision_api_key", "asr_api_key"}

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
    """返回当前生效配置，api_key 类字段脱敏。"""
    cfg = load_config()
    result: dict[str, Any] = {}
    for flat, dotted in _FIELD_MAP.items():
        val = _get_dotted(cfg, dotted)
        result[flat] = mask_key(val) if flat in _KEY_FIELDS else val
    raw_key = str(cfg.ai.api_key or "").strip()
    result["has_api_key"] = bool(raw_key) and raw_key != _PLACEHOLDER_KEY
    # 占位符 key 不显示掩码（否则用户误以为"已配置"而不填新 key）
    if raw_key == _PLACEHOLDER_KEY:
        result["api_key"] = ""
    return result


class ConfigUpdate(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    vision_model: str | None = None
    llm_model: str | None = None
    asr_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    vision_base_url: str | None = None
    vision_api_key: str | None = None
    asr_base_url: str | None = None
    asr_api_key: str | None = None
    asr_engine: str | None = None
    local_model_path: str | None = None
    subtitle_max_chars: float | None = None
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

    # api_key 类字段：仅当传入的是非掩码、非占位符的新值才更新
    for key_field in _KEY_FIELDS:
        key = (data.get(key_field) or "").strip()
        if key and "*" not in key and key != _PLACEHOLDER_KEY:
            _set_dotted(local, _FIELD_MAP[key_field], key)

    for flat, dotted in _FIELD_MAP.items():
        if flat in _KEY_FIELDS or flat not in data:
            continue
        _set_dotted(local, dotted, data[flat])

    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(local, f, allow_unicode=True, sort_keys=False)

    return await get_config()


# ---------------- 连通性测试（ping 后模型列表选择） ----------------


class TestConnectionPayload(BaseModel):
    kind: str = "llm"          # llm / vision / asr / global（global=测试全局默认接口）
    base_url: str = ""
    api_key: str = ""          # 可为空或掩码：掩码时后端取本地对应配置的真实 key


def _resolve_local_key(kind: str) -> str:
    """ping 时若前端传空/掩码 key，取本地对应配置的真实 key。"""
    cfg = load_config()
    if kind == "global":
        return str(cfg.ai.api_key or "")
    eps = getattr(cfg.ai, "endpoints", None)
    eps = eps if isinstance(eps, dict) else {}
    ep = eps.get(kind) if isinstance(eps.get(kind), dict) else {}
    return str((ep or {}).get("api_key") or "") or str(cfg.ai.api_key or "")


@router.post("/test-connection")
async def test_connection(payload: TestConnectionPayload) -> dict:
    """测试接口连通性：GET {base}/models（自动兼容 /v1 前缀），返回模型列表。"""
    base = (payload.base_url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise HTTPException(400, "接口地址需以 http:// 或 https:// 开头")

    key = (payload.api_key or "").strip()
    if not key or "*" in key:
        key = _resolve_local_key(payload.kind)
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    candidates = [base + "/models"]
    if not base.endswith("/v1"):
        candidates.append(base + "/v1/models")

    last_err = "无法连接"
    async with httpx.AsyncClient(timeout=12, headers=headers, follow_redirects=True) as client:
        for url in candidates:
            try:
                resp = await client.get(url)
            except Exception as exc:  # noqa: BLE001
                last_err = f"{url} -> {type(exc).__name__}: {exc}"
                continue
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    models = sorted({str(m.get("id", "")) for m in data.get("data", [])
                                     if m.get("id")})
                except ValueError:
                    models = []
                return {"ok": True, "url": url, "count": len(models), "models": models[:200]}
            last_err = f"{url} -> HTTP {resp.status_code}"
    return {"ok": False, "detail": last_err}
