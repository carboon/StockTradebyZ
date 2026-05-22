"""DeepSeek structured inference service."""
from __future__ import annotations

import json
from typing import Any, Optional

from openai import OpenAI

from app.config import settings


class DeepSeekService:
    """调用 DeepSeek 进行结构化二次确认。"""

    BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-chat"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = str(api_key or settings.deepseek_api_key or "").strip()
        self._client: Optional[OpenAI] = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not self.api_key:
                raise ValueError("DeepSeek API Key 未配置")
            self._client = OpenAI(api_key=self.api_key, base_url=self.BASE_URL)
        return self._client

    def infer_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=model or self.DEFAULT_MODEL,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise ValueError("DeepSeek 未返回内容")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("DeepSeek 返回格式不是 JSON object")
        return payload
