"""本地 Faster-Whisper 转录 + 卡卡字幕助手式精细化。

设计（用户拍板 2026-09-03）：
- 引擎：faster-whisper（复用 VideoCaptioner 已下载的 large-v2 模型）
- 设备：CUDA float16（默认；CUDA 不可用自动回退 CPU int8）
- VAD：faster-whisper 内置 Silero VAD（vad_filter=True）
- 语言：逐音频块自动检测，仅在中文/日文间二选一（Vtuber 中日混播）
- 精细化：继承卡卡字幕助手——按中日标点断句，每行 ≤30 字符（可配），
  词级时间戳精确切分，"一句话对应精细的一个轴"
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
from pathlib import Path

# Anaconda 环境：ctranslate2 与 numpy/onnxruntime 的 OpenMP 冲突（libiomp5md.dll 重复加载），
# 官方 workaround（KMP_DUPLICATE_LIB_OK）——必须在任何相关库导入前设置
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from .ffmpeg_utils import ffprobe_duration

# 句尾断句标点（中日混合）
_PUNCT_END = "，。！？、…；：,.!?;:…～~"

_model_cache: dict = {}
# 模型加载锁：防止多任务并发触发重复加载（double-checked）
_model_lock = threading.Lock()
# 转录串行锁：faster-whisper 默认 num_workers=1，同一模型实例上的并发 transcribe()
# 在部分环境下会死锁（2026-09-03 实测：3 任务并发转写全线程 Wait、零 CPU/GPU 40 分钟）。
# 单 GPU 上 beam-5 转写本就无法真并行，串行化几乎不损失吞吐，但彻底消除此类死锁。
_transcribe_lock = asyncio.Lock()


def _get_model(cfg):
    """加载（并缓存）faster-whisper 模型——3GB 模型只加载一次。"""
    model_path = str(getattr(cfg.asr, "local_model_path", "") or "")
    if not model_path or not Path(model_path).exists():
        raise FileNotFoundError(f"本地 whisper 模型路径不存在: {model_path}")
    if model_path not in _model_cache:
        with _model_lock:
            if model_path in _model_cache:  # 双重检查：等锁期间可能已被其他线程加载
                return _model_cache[model_path]
            from faster_whisper import WhisperModel
            device = str(getattr(cfg.asr, "local_device", "cuda") or "cuda")
            compute = str(getattr(cfg.asr, "local_compute_type", "float16") or "float16")
            # CUDA 可用性检测：GPU 缺失/异常时自动回退 CPU，避免任务直接失败。
            # 注意：float16 等精度在 CPU 上不受支持，回退时一并换成 CPU 的 int8。
            if device == "cuda":
                try:
                    import ctranslate2
                    if ctranslate2.get_cuda_device_count() == 0:
                        raise RuntimeError("no CUDA device")
                except Exception as exc:  # noqa: BLE001
                    print(f"[local-asr] CUDA 不可用（{exc}），自动回退 CPU")
                    device = "cpu"
                    if compute in ("float16", "int8_float16", "bfloat16"):
                        compute = "int8"
            # 限制 CPU 线程数：whisper 默认吃满全部核心会导致 uvicorn 事件循环饿死
            # （HTTP 请求超时、WebUI 无响应），留出核心给服务本身（仅 CPU 模式生效）
            cpu_threads = int(getattr(cfg.asr, "local_cpu_threads", 6) or 6)
            try:
                cpu_count = os.cpu_count() or 2
                cpu_threads = max(2, min(cpu_threads, cpu_count - 2))
            except Exception:
                pass
            _model_cache[model_path] = WhisperModel(
                model_path, device=device, compute_type=compute, cpu_threads=cpu_threads)
            print(f"[local-asr] 模型已加载: device={device}, compute_type={compute}, "
                  f"cpu_threads={cpu_threads}（路径 {model_path}）")
    return _model_cache[model_path]


def _run_transcribe(model, audio_path: str, language: str | None):
    """同步转录（调用方用 asyncio.to_thread 包裹）。"""
    return model.transcribe(
        audio_path,
        language=language,          # None = whisper 自动检测（每块独立检测 → 中日二选一）
        beam_size=5,
        vad_filter=True,            # 内置 Silero VAD
        vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=True,       # 词级时间戳 → 精细切轴
    )


def _split_by_words(words, max_chars: int) -> list[dict]:
    """按词级时间戳断句：标点结尾即断；接近宽度上限时提前断，保证不超宽。"""
    subs: list[dict] = []
    buf: list = []
    buf_len = 0
    for w in words:
        word = (w.word or "").strip()
        if not word:
            continue
        # 宽度限制：提前断句（除非 buf 为空，即单个词本身就超宽）
        if buf and buf_len + len(word) > max_chars:
            subs.append(_pack_words(buf))
            buf = []
            buf_len = 0
        buf.append(w)
        buf_len += len(word)
        if buf_len >= max_chars or (word and word[-1] in _PUNCT_END):
            subs.append(_pack_words(buf))
            buf = []
            buf_len = 0
    if buf:
        subs.append(_pack_words(buf))
    return subs


def _pack_words(words) -> dict:
    text = "".join((w.word or "").strip() for w in words)
    return {
        "start": round(float(words[0].start), 2),
        "end": round(float(words[-1].end), 2),
        "text": text,
    }


def _split_by_ratio(start: float, end: float, text: str, max_chars: int) -> list[dict]:
    """无词级时间戳的兜底：按字符比例分配时间。"""
    text = (text or "").strip()
    if not text:
        return []
    total = len(text)
    if total <= max_chars:
        return [{"start": round(start, 2), "end": round(end, 2), "text": text}]
    dur = end - start
    out = []
    for i in range(0, total, max_chars):
        chunk = text[i:i + max_chars]
        s = start + dur * i / total
        e = start + dur * (i + len(chunk)) / total
        out.append({"start": round(s, 2), "end": round(e, 2), "text": chunk})
    return out


def refine_segments(segments, max_chars: int = 30) -> list[dict]:
    """卡卡式精细化：长句按标点/宽度断成短句，每句一个精细的时间轴。"""
    out: list[dict] = []
    for seg in segments:
        words = getattr(seg, "words", None)
        if words:
            out.extend(_split_by_words(words, max_chars))
        else:
            out.extend(_split_by_ratio(float(seg.start), float(seg.end), seg.text, max_chars))
    return out


async def transcribe_chunks_local(chunks_dir: str | Path, cfg) -> list[dict]:
    """本地转录音频块目录（逐块自动检测语言 zh/ja），返回精细化 segments。"""
    chunks_dir = Path(chunks_dir)
    files = sorted(chunks_dir.glob("chunk_*.mp3")) or sorted(chunks_dir.glob("*.mp3"))
    if not files:
        raise FileNotFoundError(f"未找到音频块: {chunks_dir}")

    model = await asyncio.to_thread(_get_model, cfg)
    max_chars = int(getattr(cfg.asr, "subtitle_max_chars", 30) or 30)
    all_segments: list[dict] = []
    offset = 0.0

    for fp in files:
        duration = float(getattr(cfg.asr, "chunk_seconds", 1200))
        try:
            probed = await ffprobe_duration(fp)
            if probed > 0:
                duration = probed
        except Exception:
            pass

        # 第一次：自动检测语言；非中/日则强制中文重转（中日二选一）
        # 单块失败只跳过该块继续（与云端引擎行为一致），不中断整个任务
        # 全程持有串行锁：同一时刻只允许一个转写调用（防共享模型并发死锁）
        try:
            async with _transcribe_lock:
                segments, info = await asyncio.to_thread(_run_transcribe, model, str(fp), None)
                if (getattr(info, "language", "") or "") not in ("zh", "ja"):
                    segments, info = await asyncio.to_thread(_run_transcribe, model, str(fp), "zh")
        except Exception as exc:  # noqa: BLE001
            print(f"[local-asr] {fp.name} 转写失败，跳过该块: {exc}")
            offset += duration
            continue
        refined = refine_segments(segments, max_chars)
        for s in refined:
            all_segments.append({
                "start": round(offset + s["start"], 2),
                "end": round(offset + s["end"], 2),
                "text": s["text"],
            })
        offset += duration
        print(f"[local-asr] {fp.name} 完成: 语言={info.language}，精细化后 {len(refined)} 句")

    if not all_segments:
        raise RuntimeError("本地转录结果为空，请检查模型与音频")
    return all_segments
