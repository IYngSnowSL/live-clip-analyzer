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
    "ai.endpoints.llm.base_url": "LCA_LLM_BASE_URL",
    "ai.endpoints.llm.api_key": "LCA_LLM_API_KEY",
    "ai.endpoints.vision.base_url": "LCA_VISION_BASE_URL",
    "ai.endpoints.vision.api_key": "LCA_VISION_API_KEY",
    "ai.endpoints.asr.base_url": "LCA_ASR_BASE_URL",
    "ai.endpoints.asr.api_key": "LCA_ASR_API_KEY",
    "asr.engine": "LCA_ASR_ENGINE",
    "asr.local_model_path": "LCA_LOCAL_MODEL_PATH",
    "asr.local_device": "LCA_LOCAL_DEVICE",
    "asr.local_compute_type": "LCA_LOCAL_COMPUTE_TYPE",
}

# 回环地址（本服务无鉴权，非回环绑定必须显式确认）
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def check_bind_guard(cfg: "DotDict") -> None:
    """回环地址保护：绑定非回环地址（局域网/公网）时必须显式开启开关。

    文件浏览 / 连通测试等接口无鉴权，暴露到局域网会泄露整机目录枚举能力。
    """
    host = str(getattr(cfg.server, "host", "127.0.0.1") or "127.0.0.1").strip().lower()
    if host in LOOPBACK_HOSTS:
        return
    if not bool(getattr(cfg.server, "allow_non_localhost", False)):
        raise RuntimeError(
            f"拒绝以非回环地址 {host!r} 启动：本服务无鉴权，暴露到局域网/公网会泄露"
            "文件浏览与连通测试能力。若确需开放，请在 config.yaml 设置 "
            "server.allow_non_localhost: true（风险自担）")

# 注意：以下 DEFAULTS 与项目根 config.yaml 是同一份配置的两处拷贝，
# 修改任何一项时两处必须同步（config.yaml 同时承担用户文档职责）。
DEFAULTS: dict[str, Any] = {
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "allow_non_localhost": False,  # 无鉴权服务，绑定非回环地址必须显式置 true（风险自担）
    },
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
    "asr": {
        "chunk_seconds": 1800,       # 音频切片长度（秒）= 30 分钟，长音频会自动分段
        "language": "",              # 云端 ASR 语言代码；留空为自动识别
        "engine": "local",           # local=本地 faster-whisper（默认）/ api=云端 OpenAI 兼容 ASR
        "local_model_path": r"D:\AdobE\VideoCaptioner\AppData\models\faster-whisper-large-v2",
        "local_whisper_bin": "",    # 独立转写程序路径；留空自动探测 VideoCaptioner 目录 / PATH
        "local_device": "cuda",     # cuda / cpu（CUDA 块失败自动回退 CPU 重试）
        "local_compute_type": "default",  # default=程序自动；也可 float16 / int8_float16 / int8
        "local_cpu_threads": 6,     # CPU 模式线程数（仅回退 CPU 时生效）
        "local_vad_threshold": 0.4,  # Silero VAD 语音概率阈值（与卡卡字幕助手一致）
        "local_fallback_cpu": False,  # true=CUDA 多次失败后回退 CPU；false=强制 CUDA（默认）
        "local_batched": True,       # 动态批解码（--batched）：解码阶段显著提速
        "local_beam_size": 5,        # beam search 宽度（1=最快，5=默认质量）
        "local_hotwords": "",        # 热词（空格分隔）：专名/梗词识别增强；留空不启用
        "subtitle_max_chars": 30,    # 字幕每行最大字符数（卡卡式精细化断句）
    },
    "axle": {
        "window_seconds": 600,        # LLM 找内容点的分窗大小（秒）
        "overlap_seconds": 60,        # 相邻窗重叠（秒），避免漏掉跨窗内容点
        "target_min_seconds": 30,     # 目标最短时长（秒）= 30 秒
        "target_max_seconds": 3600,   # 目标最长时长（秒）= 1 小时
        "hard_max_seconds": 3600,     # 硬上限（秒）= 1 小时，超过自动拆分
        "min_axle_seconds": 20,       # 最短轴时长（秒），过短碎片丢弃
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
