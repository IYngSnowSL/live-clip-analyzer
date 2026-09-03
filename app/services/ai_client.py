"""OpenAI 兼容 API 客户端：统一 AI 能力门面。

对外提供语义化能力接口：
- analyze_document：文档 / 字幕分析（LLM）
- transcribe：语音转写（ASR 模型）

上层模块（打轴、语音转写）统一走本门面，不再各自拼装 HTTP。
（视觉能力随 ADR-0006 推倒重建删除，配置页视觉字段仅作预留。）
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx


class AIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AIClient:
    """各模型能力（LLM / ASR）可各自配置独立接口地址与密钥。

    高级设置（ai.endpoints）中某项为空时，继承全局 ai.base_url / ai.api_key。
    """

    def __init__(self, ai_cfg):
        self.base_url = str(ai_cfg.base_url).rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise AIError("config ai.base_url 必须以 http:// 或 https:// 开头")
        self.api_key = str(ai_cfg.api_key or "")
        self.vision_model = str(ai_cfg.vision_model)
        self.llm_model = str(ai_cfg.llm_model)
        self.asr_model = str(ai_cfg.asr_model)
        # 参数钳制：避免 0/负超时与失控并发
        try:
            self.timeout = max(10.0, min(float(ai_cfg.timeout), 3600.0))
        except (TypeError, ValueError):
            self.timeout = 180.0
        try:
            self.concurrency = max(1, min(int(ai_cfg.concurrency), 32))
        except (TypeError, ValueError):
            self.concurrency = 4

        eps = getattr(ai_cfg, "endpoints", None)
        eps = eps if isinstance(eps, dict) else {}
        self._clients: dict[str, httpx.AsyncClient] = {}
        for kind in ("llm", "asr"):
            ep = eps.get(kind) if isinstance(eps.get(kind), dict) else {}
            base = str((ep or {}).get("base_url") or "").strip() or self.base_url
            key = str((ep or {}).get("api_key") or "").strip() or self.api_key
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            self._clients[kind] = httpx.AsyncClient(
                base_url=base.rstrip("/"), headers=headers, timeout=self.timeout)

    def _client(self, kind: str) -> httpx.AsyncClient:
        return self._clients.get(kind) or self._clients["llm"]

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()

    async def _post_json(self, kind: str, path: str, payload: dict, retries: int = 3) -> dict:
        client = self._client(kind)
        last_exc: AIError | None = None
        for attempt in range(retries):
            try:
                resp = await client.post(path, json=payload)
            except httpx.HTTPError as exc:
                # 传输层异常（连接失败/超时/DNS）同样包装并重试，
                # 避免打轴路径因一次网络抖动整体失败
                last_exc = AIError(f"API {path} 网络错误: {type(exc).__name__}: {exc}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise last_exc
            if resp.status_code < 400:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise AIError(f"API {path} 返回非 JSON: {resp.text[:200]}",
                                  status_code=resp.status_code) from exc
            text = resp.text[:500]
            last_exc = AIError(f"API {path} 返回 {resp.status_code}: {text}",
                               status_code=resp.status_code)
            if resp.status_code in (429, 500, 502, 503) and attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise last_exc
        raise last_exc if last_exc else AIError(f"API {path} 请求失败")

    async def chat(self, messages: list[dict], model: str | None = None,
                   temperature: float = 0.3, max_tokens: int = 1200,
                   json_mode: bool = False, kind: str = "llm") -> str:
        model = model or (self.llm_model if kind == "llm" else self.vision_model)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            data = await self._post_json(kind, "/chat/completions", payload)
        except AIError as exc:
            if json_mode and exc.status_code in (400, 404, 422):
                payload.pop("response_format", None)
                data = await self._post_json(kind, "/chat/completions", payload)
            else:
                raise
        choices = data.get("choices") or []
        if not choices:
            return ""
        content = choices[0].get("message", {}).get("content", "")
        return content or ""

    async def chat_json(self, messages: list[dict], model: str | None = None,
                        temperature: float = 0.3, max_tokens: int = 1200,
                        kind: str = "llm") -> dict:
        content = await self.chat(messages, model=model, temperature=temperature,
                                  max_tokens=max_tokens, json_mode=True, kind=kind)
        return extract_json(content)

    # ---------------- 能力接口 ----------------

    async def analyze_document(self, text: str, instruction: str,
                               json_mode: bool = False, model: str | None = None,
                               max_tokens: int = 1600) -> str | dict:
        """文档 / 字幕分析：把 instruction + text 组合成 prompt 调 LLM。

        用于找内容点、打轴等"对一段文本做分析"的场景。
        """
        prompt = f"{instruction}\n\n【文档内容】\n{text}"
        messages = [
            {"role": "system", "content": "你是专业的文档分析助手，只根据给定内容作答。"},
            {"role": "user", "content": prompt},
        ]
        if json_mode:
            return await self.chat_json(messages, model=model, max_tokens=max_tokens, kind="llm")
        return await self.chat(messages, model=model, max_tokens=max_tokens, kind="llm")

    async def transcribe(self, file_path: str | Path, language: str | None = None,
                         response_format: str | None = "verbose_json",
                         retries: int = 3) -> dict:
        """语音转写：上传音频文件，返回带时间戳的转写结果。"""
        data = {"model": self.asr_model}
        if response_format:
            data["response_format"] = response_format
        if language:
            data["language"] = language
        path = Path(file_path)
        mime = "audio/mpeg"
        if path.suffix.lower() in (".m4a", ".mp4"):
            mime = "audio/mp4"
        elif path.suffix.lower() in (".wav",):
            mime = "audio/wav"

        client = self._client("asr")
        last_exc: AIError | None = None
        for attempt in range(retries):
            try:
                with open(path, "rb") as f:
                    files = {"file": (path.name, f, mime)}
                    resp = await client.post("/audio/transcriptions", data=data, files=files)
            except httpx.HTTPError as exc:
                last_exc = AIError(f"ASR API 网络错误: {type(exc).__name__}: {exc}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise last_exc
            if resp.status_code < 400:
                try:
                    return resp.json()
                except ValueError:
                    if resp.text.strip():
                        return {"text": resp.text.strip()}
                    raise AIError("ASR API 返回空响应", status_code=resp.status_code)
            text = resp.text[:500]
            last_exc = AIError(f"ASR API 返回 {resp.status_code}: {text}",
                               status_code=resp.status_code)
            if resp.status_code in (429, 500, 502, 503) and attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise last_exc
        raise last_exc if last_exc else AIError("ASR API 请求失败")


def extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（支持对象与数组根，多个 JSON 时取第一个合法项）。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {"items": obj}
    except Exception:
        pass
    # 用增量解析器提取首个完整 JSON 值，避免贪婪正则匹配到错误边界
    decoder = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", text):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except Exception:
            continue
        return obj if isinstance(obj, dict) else {"items": obj}
    raise AIError(f"无法从模型输出中解析 JSON: {text[:300]}")
