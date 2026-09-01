"""OpenAI 兼容 API 客户端：统一 AI 能力门面。

对外提供三类语义化能力接口：
- analyze_document：文档 / 字幕分析（LLM）
- describe_images：视频 / 画面解析（视觉模型）
- transcribe：语音转写（ASR 模型）

上层模块（字幕切分、画面理解、语音转写）统一走本门面，不再各自拼装 HTTP。
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from typing import Any

import httpx


class AIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def image_to_data_url(path: str | Path) -> str:
    """把图片文件转成 base64 data URL，供视觉模型调用。"""
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


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

    # ---------------- 能力接口 ----------------

    async def analyze_document(self, text: str, instruction: str,
                               json_mode: bool = False, model: str | None = None,
                               max_tokens: int = 1600) -> str | dict:
        """文档 / 字幕分析：把 instruction + text 组合成 prompt 调 LLM。

        用于字幕切分、字幕整理、话题摘要等"对一段文本做分析"的场景。
        """
        prompt = f"{instruction}\n\n【文档内容】\n{text}"
        messages = [
            {"role": "system", "content": "你是专业的文档分析助手，只根据给定内容作答。"},
            {"role": "user", "content": prompt},
        ]
        if json_mode:
            return await self.chat_json(messages, model=model, max_tokens=max_tokens)
        return await self.chat(messages, model=model, max_tokens=max_tokens)

    async def describe_images(self, image_paths: list[str | Path], prompt: str,
                              max_tokens: int = 500) -> str:
        """视频 / 画面解析：把图片转 base64 data URL，调视觉模型。

        多图失败时自动退回单图（兼容不支持单消息多图的接口）。
        """
        content: list[dict] = [{"type": "text", "text": prompt}]
        for fp in image_paths:
            if Path(fp).exists():
                url = await asyncio.to_thread(image_to_data_url, fp)
                content.append({"type": "image_url", "image_url": {"url": url}})
        if len(content) == 1:
            return ""
        messages = [{"role": "user", "content": content}]
        try:
            text = await self.chat(messages, model=self.vision_model, max_tokens=max_tokens)
        except AIError:
            if len(content) > 2:
                messages = [{"role": "user", "content": content[:2]}]
                text = await self.chat(messages, model=self.vision_model, max_tokens=max_tokens)
            else:
                raise
        return text or ""

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

        last_exc: AIError | None = None
        for attempt in range(retries):
            with open(path, "rb") as f:
                files = {"file": (path.name, f, mime)}
                resp = await self.client.post("/audio/transcriptions", data=data, files=files)
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
