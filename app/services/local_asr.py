"""本地 Faster-Whisper 转录（独立程序子进程方式，参考卡卡字幕助手 VideoCaptioner）。

设计（用户拍板 2026-09-03）：
- 引擎：faster-whisper-xxl.exe（whisper-standalone-win 独立程序，自带 CUDA 栈），
  以子进程方式调用——转写崩溃/卡死完全隔离在子进程，不影响主服务
  （此前进程内 Python 库 ctranslate2 CUDA 推理在本机死锁，改子进程方案根治）
- 语言：固定中文（-l zh，与 VideoCaptioner 默认一致）
- VAD：exe 内置 Silero VAD（--vad_filter，阈值 0.4 可配）
- 精细化：exe 输出 JSON（词级时间戳）→ 本项目 refine_segments 卡卡式断句
  （每行 ≤30 字符可配；无词级数据自动按字符比例兜底）
- 容错：**强制 CUDA**（默认）——失败自动同块重试（含显存预检等待），仍失败跳过该块；
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
               audio_path: Path) -> list[str]:
    """构建转写命令行（参数用法与 VideoCaptioner 保持一致）。

    whisper-standalone-win 的 -m 接受"模型名"而非路径：
    它会在 --model_dir 下查找 faster-whisper-<名称> 目录。
    """
    model_dir = str(Path(model_path).parent)
    model_name = Path(model_path).name
    if model_name.startswith("faster-whisper-"):
        model_name = model_name[len("faster-whisper-"):]
    cmd = [
        bin_path, "-m", model_name, "--model_dir", model_dir,
        "-l", "zh",                        # 固定中文（与 VideoCaptioner 默认一致）
        "-d", device,
        "-o", out_dir,
        "--output_format", "json",
        "--word_timestamps", "true",       # 词级时间戳 → 卡卡式精细化
        "--vad_filter", "true",
        "--vad_threshold", f"{float(vad_threshold):.2f}",
        "--beep_off",
        "--print_progress",
    ]
    if compute and compute not in ("default", "auto"):
        cmd += ["--compute_type", compute]  # 默认交给 exe 自行选择
    if device == "cpu" and int(threads) > 0:
        cmd += ["--threads", str(int(threads))]
    cmd.append(str(audio_path))
    return cmd


async def _run_exe(cmd: list[str], timeout: float = 7200) -> tuple[bytes, bytes]:
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
        raise TimeoutError(f"whisper 转写超时（>{timeout}s）: {Path(cmd[-1]).name}")
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
        raise RuntimeError(
            f"whisper 转写失败（退出码 {proc.returncode}）: {Path(cmd[-1]).name}\n{tail}")
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


def _vram_need_mb(compute: str) -> int:
    """模型 + 推理工作区所需空闲显存的保守估计（MB）。"""
    if "int8" in str(compute).lower():
        return 2600
    return 4400


def _read_parsed(fp: Path, stderr: bytes) -> list[dict]:
    """读取并解析独立程序生成的 JSON 输出，用后即删。"""
    out_json = fp.with_suffix(".json")
    if not out_json.exists():
        # 程序可能退出码为 0 但实际失败（如模型名不合法），必须显式报错
        tail = stderr.decode("utf-8", errors="ignore")[-400:]
        raise RuntimeError(f"whisper 未生成输出文件: {tail}")
    parsed = _parse_json_result(out_json.read_text(encoding="utf-8"))
    try:
        out_json.unlink()  # 用后即删，保持块目录干净
    except OSError:
        pass
    return parsed


def _parse_json_result(json_text: str) -> list[dict]:
    """解析独立程序的 JSON 输出 → [{start, end, text, words?}]。"""
    data = json.loads(json_text)
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
    return out


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


async def _run_cuda_with_retries(cmd: list[str], fp: Path, compute: str,
                                 retries: int = 3) -> list[dict] | None:
    """强制 CUDA：显存预检（不足则等待）+ 失败同块重试，不回退 CPU。

    返回解析后的段落；多次重试仍失败返回 None（跳过该块）。
    """
    need = _vram_need_mb(compute)
    for attempt in range(1, retries + 1):
        # 显存预检：桌面应用（壁纸/浏览器等）可能临时占用显存，等待其释放
        waited = 0
        while waited < 600:
            free = await _free_vram_mb()
            if free is None or free >= need:
                break
            print(f"[local-asr] 空闲显存不足（{free}MB < 需约 {need}MB），"
                  f"等待释放… 已等 {waited}s", flush=True)
            await asyncio.sleep(15)
            waited += 15
        try:
            async with _transcribe_lock:
                _, stderr = await _run_exe(cmd)
            return _read_parsed(fp, stderr)
        except RuntimeError as exc:
            if attempt >= retries:
                print(f"[local-asr] {fp.name} CUDA 转写失败"
                      f"（已重试 {retries} 次，跳过该块）:\n{exc}")
                return None
            wait_s = 20 * attempt
            print(f"[local-asr] {fp.name} CUDA 转写失败"
                  f"（第 {attempt}/{retries} 次），{wait_s}s 后重试:\n{exc}")
            await asyncio.sleep(wait_s)
    return None


async def _run_once(cmd: list[str], fp: Path) -> list[dict] | None:
    """单次执行（CPU 回退路径），失败返回 None。"""
    try:
        async with _transcribe_lock:
            _, stderr = await _run_exe(cmd)
        return _read_parsed(fp, stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[local-asr] {fp.name} 转写失败，跳过该块:\n{exc}")
        return None


async def transcribe_chunks_local(chunks_dir: str | Path, cfg) -> list[dict]:
    """本地转录音频块目录（独立程序子进程，固定中文），返回精细化 segments。"""
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
    # 默认强制 CUDA（失败同块重试，不回退）；显式开启时才允许 CPU 兜底
    fallback_cpu = bool(getattr(cfg.asr, "local_fallback_cpu", False))

    print(f"[local-asr] 引擎: {bin_path}（device={device}, compute={compute}, "
          f"回退CPU={fallback_cpu}）")
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

        cmd = _build_cmd(bin_path, model_path, device, compute, threads,
                         vad_threshold, str(chunks_dir), fp)
        if device == "cuda":
            parsed = await _run_cuda_with_retries(cmd, fp, compute)
            if parsed is None and fallback_cpu:
                print(f"[local-asr] {fp.name} CUDA 多次失败，按配置回退 CPU 兜底…")
                cpu_cmd = _build_cmd(bin_path, model_path, "cpu", compute, threads,
                                     vad_threshold, str(chunks_dir), fp)
                parsed = await _run_once(cpu_cmd, fp)
        else:
            parsed = await _run_once(cmd, fp)

        if parsed is None:
            offset += duration
            continue
        refined = refine_segments(_to_seg_objects(parsed), max_chars)
        for s in refined:
            all_segments.append({
                "start": round(offset + s["start"], 2),
                "end": round(offset + s["end"], 2),
                "text": s["text"],
            })
        offset += duration
        print(f"[local-asr] {fp.name} 完成: 精细化后 {len(refined)} 句")

    if not all_segments:
        raise RuntimeError("本地转录结果为空，请检查模型与音频")
    return all_segments
