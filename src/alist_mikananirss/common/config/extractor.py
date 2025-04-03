from typing import Literal

from pydantic import BaseModel, Field

from alist_mikananirss.extractor.llm.prompt import PromptType


class OpenAIConfig(BaseModel):
    extractor_type: Literal["openai"]
    api_key: str = Field(..., description="OpenAI API key")
    base_url: str = Field(
        "https://api.openai.com/v1", description="Base URL for OpenAI API"
    )
    model: str = Field("gpt-4o-2024-11-20", description="Model to use for OpenAI API")
    output_type: PromptType = Field(
        PromptType.JSON_OBJECT, description="Structure output type for OpenAI API"
    )


class DeepSeekConfig(BaseModel):
    extractor_type: Literal["deepseek"]
    api_key: str = Field(..., description="DeepSeek API key")
    base_url: str = Field(
        "https://api.deepseek.com", description="Base URL for DeepSeek API"
    )
    model: str = Field("gpt-4o-2024-11-20", description="Model to use for DeepSeek API")
    output_type: PromptType = Field(
        PromptType.JSON_OBJECT, description="Structure output type for DeepSeek API"
    )
