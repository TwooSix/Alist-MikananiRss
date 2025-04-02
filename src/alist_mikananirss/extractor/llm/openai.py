from typing import Any, Dict, List, Type, TypeVar, Optional
from openai import AsyncOpenAI
from .base import LLMProvider
import json

T = TypeVar("T")


class OpenAIProvider(LLMProvider):
    """OpenAI-based LLM provider"""

    def __init__(self, api_key: str, base_url: str = None, model: str = "gpt-4o-mini"):
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
        """Parse response with a schema (native OpenAI parsing)"""
        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=response_format,
        )
        return response.choices[0].message.parsed

    async def parse_as_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Parse response as a JSON object"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
