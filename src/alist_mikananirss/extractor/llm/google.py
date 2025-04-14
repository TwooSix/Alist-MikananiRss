import json
from typing import Any, Dict, List, Optional, Type, TypeVar

from google import genai

from .base import LLMProvider

T = TypeVar("T")


class GoogleProvider(LLMProvider):
    """Google Gemini"""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self._api_key = api_key
        self.model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def parse_with_schema(
        self, messages: List[Dict[str, str]], response_format: Type[T]
    ) -> Optional[T]:
        """Parse response with a schema"""
        prompt = messages[0]["content"]
        content = messages[1]["content"]
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=f"{prompt}: \n{content}",
            config={
                "response_mime_type": "application/json",
                "response_schema": response_format,
            },
        )
        return response.parsed

    async def parse_as_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Parse response as a JSON object"""
        prompt = messages[0]["content"]
        content = messages[1]["content"]
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=f"{prompt}: \n{content}",
            config={
                "response_mime_type": "application/json",
            },
        )
        return json.loads(response.text)
