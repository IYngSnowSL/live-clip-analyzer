"""本地 Faster-Whisper 转录（独立程序子进程批量方式，参考卡卡字幕助手 VideoCaptioner）。

设计（用户拍板 2026-09-03）：
- 引擎：faster-whisper-xxl.exe（whisper-standalone-win 独立程序，自带 CUDA 栈），
  以子进程方式调用——转写崩溃/卡死完全隔离在子进程，不影响主服务
- 批量模式：一次 exe 调用转完任务的全部音频块（模型只加载一次），
  失败重试用 --skip 只补跑缺失的块
- 语言：自动检测（不传 -l，exe 自动识别，中日混播友好；JSON 的 language 字段回读）
- VAD：exe 内置 Silero VAD（--vad_filter，阈值 0.4 可配，静音切分 500ms）
- 热词：--hotwords 专名/梗词增强（local_hotwords 配置，空格分隔）
- 精细化：exe 输出 JSON（词级时间戳）→ 本项目 refine_segments 卡卡式断句
  （每行 ≤30 字符可配；无词级数据自动按字符比例兜底）
- 加速：--batched 动态批解码（默认开）；beam_size 可配（默认 5）
- 容错：**强制 CUDA**（默认）——失败自动重试（含显存预检等待），
  最后一次尝试自动降级为非 batched（显存更省）；仍失败跳过缺失块；
  可选 `local_fallback_cpu: true` 时最终回退 CPU；串行锁防止多任务同时抢单 GPU
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from .ffmpeg_utils import ffprobe_duration

# 句尾断句标点（中日混合）
_PUNCT_END = "，。！？、…；：,.!?;:…～~"

# 独立转写程序候选路径（配置未指定时自动探测：VideoCaptioner 自带目录 → PATH）
_DEFAULT_BIN_CANDIDATES = [
    r"D:\AdobE\VideoCaptioner\resource\bin\Faster-Whisper-XXL\faster-whisper-xxl.exe",
]

# 转录串行锁：单 GPU 上同时跑多个转写子进程毫无收益，串行化避免争抢显存
_transcribe_lock = asyncio.Lock()


def _find_whisper_bin(cfg) -> str:
    """定位独立转写程序：配置 > VideoCaptioner 目录 > PATH。"""
    explicit = str(getattr(cfg.asr, "local_whisper_bin", "") or "").strip()
    if explicit:
        if not Path(explicit).exists():
            raise FileNotFoundError(f"配置的 whisper 程序不存在: {explicit}")
        return explicit
    for cand in _DEFAULT_BIN_CANDIDATES:
        if Path(cand).exists():
            return cand
    for name in ("faster-whisper-xxl", "faster-whisper"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError(
        "未找到 faster-whisper 独立程序：请安装 whisper-standalone-win "
        "（卡卡字幕助手 VideoCaptioner 同款，见 README），"
        "或在 config.yaml 设置 asr.local_whisper_bin")


def _build_cmd(bin_path: str, model_path: str, device: str, compute: str,
               threads: int, vad_threshold: float, out_dir: str,
               batched: bool, beam_size: int, hotwords: str,
               input_dir: Path) -> list[str]:
    """构建批量转写命令行（参数用法参考 VideoCaptioner / MAW）。

    whisper-standalone-win 的 -m 接受"模型名"而非路径：
    它会在 --model_dir 下查找 faster-whisper-<名称> 目录。
    输入传目录即批量模式：一次加载模型转完目录内全部媒体文件。
    """
    model_dir = str(Path(model_path).parent)
    model_name = Path(model_path).name
    if model_name.startswith("faster-whisper-"):
        model_name = model_name[len("faster-whisper-"):]
    cmd = [
        bin_path, "-m", model_name, "--model_dir", model_dir,
        "-d", device,
        "-o", out_dir,
        "--output_format", "json",
        "--word_timestamps", "true",       # 词级时间戳 → 卡卡式精细化
        "--vad_filter", "true",
        "--vad_threshold", f"{float(vad_threshold):.2f}",
        "--vad_min_silence_duration_ms", "500",  # MAW 经验值：静音切分更细
        # MAW 经验：长音频中一句幻觉会被跨窗上下文持续放大，关闭更稳
        "--condition_on_previous_text", "false",
        "--beep_off",
        "--print_progress",
    ]
    if compute and compute not in ("default", "auto"):
        cmd += ["--compute_type", compute]  # 默认交给 exe 自行选择
    if device == "cpu" and int(threads) > 0:
        cmd += ["--threads", str(int(threads))]
    if batched and device == "cuda":
        cmd += ["--batched"]               # 动态批解码：解码阶段显著提速
    if int(beam_size) != 5:
        cmd += ["--beam_size", str(int(beam_size))]
    if hotwords.strip():
        cmd += ["--hotwords", " ".join(hotwords.split())]
    cmd.append(str(input_dir))
    return cmd


async def _run_exe(cmd: list[str], timeout: float = 14400) -> tuple[bytes, bytes]:
    """执行独立转写程序；超时/取消时杀掉子进程。返回 (stdout, stderr)。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"whisper 转写超时（>{timeout}s）")
    except asyncio.CancelledError:
        proc.kill()
        try:
            await proc.wait()
        except Exception:  # noqa: BLE001
            pass
        raise
    if proc.returncode != 0:
        # exe 的错误信息可能打在 stdout 或 stderr，两者都要保留
        out_tail = stdout.decode("utf-8", errors="ignore")[-800:].strip()
        err_tail = stderr.decode("utf-8", errors="ignore")[-800:].strip()
        tail = (err_tail or out_tail) or "(无输出)"
        raise RuntimeError(f"whisper 转写失败（退出码 {proc.returncode}）:\n{tail}")
    return stdout, stderr


async def _free_vram_mb() -> int | None:
    """查询 GPU 空闲显存（MB）；nvidia-smi 不可用时返回 None（跳过预检）。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi", "--query-gpu=memory.free",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        first = out.decode("utf-8", errors="ignore").strip().splitlines()[0].strip()
        return int(float(first))
    except Exception:  # noqa: BLE001
        return None


def _vram_need_mb(compute: str, batched: bool) -> int:
    """模型 + 推理工作区所需空闲显存的保守估计（MB）。"""
    base = 2600 if "int8" in str(compute).lower() else 4400
    return base + 800 if batched else base


def _parse_json_result(json_text: str) -> tuple[list[dict], str]:
    """解析独立程序的 JSON 输出 → (段落列表, 检测到的语言)。"""
    data = json.loads(json_text)
    language = str(data.get("language") or "")
    out: list[dict] = []
    for seg in data.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "start": float(seg.get("start") or 0),
            "end": float(seg.get("end") or 0),
            "text": text,
            "words": seg.get("words") or None,
        })
    return out, language


def _collect_results(chunk_files: list[Path], results: dict) -> None:
    """收集本轮批量转写已产出的 JSON（解析后删除），写入 results。"""
    for fp in chunk_files:
        if fp in results:
            continue
        out_json = fp.with_suffix(".json")
        if not out_json.exists():
            continue
        try:
            parsed, language = _parse_json_result(out_json.read_text(encoding="utf-8"))
            results[fp] = parsed
            print(f"[local-asr] {fp.name} 语言={language or '未知'}，段落 {len(parsed)} 个")
        except Exception as exc:  # noqa: BLE001
            print(f"[local-asr] {fp.name} 输出解析失败: {exc}")
        try:
            out_json.unlink()  # 用后即删，保持块目录干净
        except OSError:
            pass


async def _batch_transcribe(chunk_files: list[Path], make_cmd,
                            variants: list, need_mb: int | None) -> dict:
    """批量转写：按变体依次尝试，每次 --skip 只补跑缺失输出的块。

    make_cmd(variant) -> 完整命令（不含 --skip）。
    返回 {chunk_path: parsed}；缺失的块打印日志。
    """
    results: dict = {}
    for attempt, variant in enumerate(variants, 1):
        # 显存预检（CPU 变体 need_mb=None 跳过）
        if need_mb is not None:
            waited = 0
            while waited < 600:
                free = await _free_vram_mb()
                if free is None or free >= need_mb:
                    break
                print(f"[local-asr] 空闲显存不足（{free}MB < 需约 {need_mb}MB），"
                      f"等待释放… 已等 {waited}s", flush=True)
                await asyncio.sleep(15)
                waited += 15
        cmd = make_cmd(variant) + ["--skip", str(chunk_files[0].parent)]
        try:
            async with _transcribe_lock:
                _, _stderr = await _run_exe(cmd)
        except RuntimeError as exc:
            print(f"[local-asr] 批量转写第 {attempt} 次失败:\n{exc}")
        _collect_results(chunk_files, results)
        missing = [fp.name for fp in chunk_files if fp not in results]
        if not missing:
            break
        if attempt < len(variants):
            print(f"[local-asr] 还缺 {len(missing)} 块，继续重试（--skip 仅补缺失）…")
    missing = [fp.name for fp in chunk_files if fp not in results]
    if missing:
        print(f"[local-asr] 批量转写结束，仍缺失块: {missing}")
    return results


def _to_seg_objects(parsed: list[dict]) -> list[SimpleNamespace]:
    """把 JSON 段落转成 refine_segments 需要的对象（含词级时间戳）。"""
    objs = []
    for p in parsed:
        words = None
        if p["words"]:
            words = [
                SimpleNamespace(
                    word=str(w.get("word") or "").strip(),
                    start=float(w.get("start") or 0),
                    end=float(w.get("end") or 0),
                )
                for w in p["words"]
                if str(w.get("word") or "").strip()
            ]
        objs.append(SimpleNamespace(
            start=p["start"], end=p["end"], text=p["text"], words=words))
    return objs


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
    """本地批量转录音频块目录（独立程序子进程，固定中文），返回精细化 segments。"""
    chunks_dir = Path(chunks_dir)
    files = sorted(chunks_dir.glob("chunk_*.mp3")) or sorted(chunks_dir.glob("*.mp3"))
    if not files:
        raise FileNotFoundError(f"未找到音频块: {chunks_dir}")

    bin_path = await asyncio.to_thread(_find_whisper_bin, cfg)
    model_path = str(getattr(cfg.asr, "local_model_path", "") or "")
    if not model_path or not Path(model_path).exists():
        raise FileNotFoundError(f"本地 whisper 模型路径不存在: {model_path}")
    device = str(getattr(cfg.asr, "local_device", "cuda") or "cuda")
    compute = str(getattr(cfg.asr, "local_compute_type", "default") or "default")
    threads = int(getattr(cfg.asr, "local_cpu_threads", 6) or 6)
    vad_threshold = float(getattr(cfg.asr, "local_vad_threshold", 0.4) or 0.4)
    max_chars = int(getattr(cfg.asr, "subtitle_max_chars", 30) or 30)
    batched = bool(getattr(cfg.asr, "local_batched", True))
    beam = int(getattr(cfg.asr, "local_beam_size", 5) or 5)
    hotwords = str(getattr(cfg.asr, "local_hotwords", "") or "").strip()
    # 默认强制 CUDA（失败重试，不回退）；显式开启时才允许 CPU 兜底
    fallback_cpu = bool(getattr(cfg.asr, "local_fallback_cpu", False))

    print(f"[local-asr] 引擎: {bin_path}（device={device}, compute={compute}, "
          f"batched={batched}, beam={beam}, 热词={hotwords or '无'}, "
          f"回退CPU={fallback_cpu}）")

    # 预扫每块实际时长（时间偏移累计用）
    durations: list[float] = []
    for fp in files:
        dur = float(getattr(cfg.asr, "chunk_seconds", 1800))
        try:
            probed = await ffprobe_duration(fp)
            if probed > 0:
                dur = probed
        except Exception:
            pass
        durations.append(dur)

    def make_cmd(dev: str, use_batched: bool) -> list[str]:
        return _build_cmd(bin_path, model_path, dev, compute, threads,
                          vad_threshold, str(chunks_dir), use_batched, beam,
                          hotwords, chunks_dir)

    results: dict = {}
    if device == "cuda":
        # 前两次 batched（加速），最后一次降级非 batched（显存更省、更稳）
        variants = [True, True, False] if batched else [False] * 3
        results = await _batch_transcribe(
            files, lambda v: make_cmd("cuda", v), variants,
            need_mb=_vram_need_mb(compute, batched))
        if len(results) < len(files) and fallback_cpu:
            print("[local-asr] CUDA 多次失败，按配置回退 CPU 补跑缺失块…")
            cpu_results = await _batch_transcribe(
                files, lambda _v: make_cmd("cpu", False), [False], need_mb=None)
            for fp, parsed in cpu_results.items():
                results.setdefault(fp, parsed)
    else:
        results = await _batch_transcribe(
            files, lambda _v: make_cmd("cpu", False), [False], need_mb=None)

    all_segments: list[dict] = []
    offset = 0.0
    for fp, dur in zip(files, durations):
        parsed = results.get(fp)
        if not parsed:
            offset += dur
            continue
        refined = refine_segments(_to_seg_objects(parsed), max_chars)
        for s in refined:
            all_segments.append({
                "start": round(offset + s["start"], 2),
                "end": round(offset + s["end"], 2),
                "text": s["text"],
            })
        offset += dur
        print(f"[local-asr] {fp.name} 完成: 精细化后 {len(refined)} 句")

    if not all_segments:
        raise RuntimeError("本地转录结果为空，请检查模型与音频")
    return all_segments
