"""OpenAI 兼容 API 客户端：chat / chat_json / ASR 转写。"""
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
    def __init__(self, ai_cfg):
        self.base_url = str(ai_cfg.base_url).rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise AIError("config ai.base_url 必须以 http:// 或 https:// 开头")
        self.api_key = str(ai_cfg.api_key or "")
        self.vision_model = str(ai_cfg.vision_model)
        self.llm_model = str(ai_cfg.llm_model)
        self.asr_model = str(ai_cfg.asr_model)
        self.timeout = float(ai_cfg.timeout)
        self.concurrency = int(ai_cfg.concurrency)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        self.client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=self.timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def _post_json(self, path: str, payload: dict, retries: int = 3) -> dict:
        last_exc: AIError | None = None
        for attempt in range(retries):
            resp = await self.client.post(path, json=payload)
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
                   json_mode: bool = False) -> str:
        model = model or self.llm_model
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            data = await self._post_json("/chat/completions", payload)
        except AIError as exc:
            if json_mode and exc.status_code in (400, 404, 422):
                payload.pop("response_format", None)
                data = await self._post_json("/chat/completions", payload)
            else:
                raise
        choices = data.get("choices") or []
        if not choices:
            return ""
        content = choices[0].get("message", {}).get("content", "")
        return content or ""

    async def chat_json(self, messages: list[dict], model: str | None = None,
                        temperature: float = 0.3, max_tokens: int = 1200) -> dict:
        content = await self.chat(messages, model=model, temperature=temperature,
                                  max_tokens=max_tokens, json_mode=True)
        return extract_json(content)

    async def transcribe_audio(self, file_path: str | Path, language: str | None = None,
                               response_format: str | None = "verbose_json",
                               retries: int = 3) -> dict:
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

        last_exc: AIError | None = None
        for attempt in range(retries):
            with open(path, "rb") as f:
                files = {"file": (path.name, f, mime)}
                resp = await self.client.post("/audio/transcriptions", data=data, files=files)
            if resp.status_code < 400:
                try:
                    return resp.json()
                except ValueError:
                    # 部分兼容接口会直接返回纯文本，包装为 dict 供上层解析
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
    """从模型输出中提取 JSON 对象。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    raise AIError(f"无法从模型输出中解析 JSON: {text[:300]}")
