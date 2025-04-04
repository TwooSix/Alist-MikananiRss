from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, TypeVar

T = TypeVar("T")


class LLMProvider(ABC):
    """Base class for LLM providers"""

    @abstractmethod
    async def parse_with_schema(
        self, messages: List[Dict[str, str]], response_format: Type[T]
    ) -> Optional[T]:
        """Parse response with a schema"""
        pass

    @abstractmethod
    async def parse_as_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Parse response as a JSON object"""
        pass
