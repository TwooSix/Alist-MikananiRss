import json
from typing import Any, Dict, List, Type, TypeVar, Optional
from openai import AsyncOpenAI
from .base import LLMProvider

T = TypeVar("T")


class DeepSeekProvider(LLMProvider):
    """DeepSeek-based LLM provider using OpenAI-compatible API"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
    ):
        self._api_key = api_key
        self._base_url = base_url
        self.model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._api_key)
            if self._base_url:
                self._client.base_url = self._base_url
        return self._client

    async def parse_with_schema(
        self, messages: List[Dict[str, str]], response_format: Type[T]
    ) -> Optional[T]:
        raise NotImplementedError(
            "DeepSeek does not support parsing with json schema. Use parse_as_json instead."
        )

    async def parse_as_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Parse response as a JSON object"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
