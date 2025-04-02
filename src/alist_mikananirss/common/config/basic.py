from collections import defaultdict
from typing import Annotated, Dict, List

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from alist_mikananirss.alist import AlistDownloaderType

from .bot_assistant import TelegramBotAssistantConfig
from .extractor import DeepSeekConfig, OpenAIConfig
from .notifier import PushPlusConfig, TelegramConfig
from .remap import RemapConfig


class CommonConfig(BaseModel):
    interval_time: int = Field(
        default=300, ge=0, description="Interval time must be non-negative"
    )
    proxies: Dict[str, str] = Field(
        default_factory=dict, description="Proxies for requests"
    )


class AlistConfig(BaseModel):
    base_url: str = Field(..., description="Base URL of Alist")
    token: str = Field(..., description="Token for Alist API")
    downloader: AlistDownloaderType = Field(
        default=AlistDownloaderType.QBIT, description="Alist Downloader type"
    )
    download_path: str = Field(..., description="Download path for Alist Downloader")

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, url: str) -> str:
        try:
            # 正确的URL验证方式
            parsed_url = HttpUrl(url)
            return str(parsed_url)
        except ValueError:
            raise ValueError(f"Invalid URL: {url}")


class MikanConfig(BaseModel):
    subscribe_url: List[str] = Field(min_length=1)
    regex_pattern: Dict[str, str] = Field(
        default_factory=dict,
        description="Regex pattern for filter",
    )

    filters: List[str] = Field(default_factory=list, description="Filters for rss")

    @field_validator("subscribe_url")
    @classmethod
    def validate_url(cls, url: List[str]) -> List[str]:
        for u in url:
            HttpUrl(u)
        return url

    @field_validator("regex_pattern")
    @classmethod
    def merge_regex_patterns(cls, patterns: Dict[str, str]) -> Dict[str, str]:
        default_patterns = {
            "简体": "(简体|简中|简日|CHS)",
            "繁体": "(繁体|繁中|繁日|CHT|Baha)",
            "1080p": "(X1080|1080P)",
            "非合集": "^(?!.*(\\d{2}-\\d{2}|合集)).*",
        }
        default_patterns.update(patterns)
        return default_patterns


class RenameConfig(BaseModel):
    enable: bool = Field(default=False)
    extractor: OpenAIConfig | DeepSeekConfig = Field(
        default=None, discriminator="extractor_type"
    )
    rename_format: str = Field(
        "{name} S{season:02d}E{episode:02d}", description="Rename format"
    )
    remap: RemapConfig = Field(
        default_factory=RemapConfig, description="Remap configuration"
    )

    @model_validator(mode="after")
    def validate_rename_config(self):
        if self.enable and not self.extractor:
            raise ValueError("Rename is enabled but no extractor config provided")
        return self

    @field_validator("rename_format")
    @classmethod
    def validate_rename_format(cls, rename_format: str) -> str:
        if not rename_format:
            return rename_format

        all_key_test_data = {
            "name": "test",
            "season": 1,
            "episode": 1,
            "fansub": "fansub",
            "quality": "1080p",
            "language": "简体中文",
        }
        safe_dict = defaultdict(lambda: "undefined", all_key_test_data)
        res = rename_format.format_map(safe_dict)
        if "undefined" in res:
            unknown_keys = [
                key for key, value in safe_dict.items() if value == "undefined"
            ]
            raise ValueError(f"Error keys in rename format: {', '.join(unknown_keys)}")
        return rename_format


NotificationBotConfig = Annotated[
    TelegramConfig | PushPlusConfig, Field(discriminator="bot_type")
]


class NotificationConfig(BaseModel):
    enable: bool = Field(default=False)
    interval_time: int = Field(
        default=300, ge=0, description="Interval time must be non-negative"
    )
    bots: List[NotificationBotConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_notification_config(self):
        if self.enable and not len(self.bots):
            raise ValueError("Notification is enabled but no notifier config provided")
        return self


class BotAssistantConfig(BaseModel):
    enable: bool = Field(default=False)
    bots: List[TelegramBotAssistantConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_bot_assistant_config(self):
        if self.enable and len(self.bots) == 0:
            raise ValueError("Bot assistant is enabled but no bot config provided")
        return self


class DevConfig(BaseModel):
    log_level: str = Field(
        default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"
    )
