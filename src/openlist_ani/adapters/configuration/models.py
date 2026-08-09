"""Public Pydantic models for ``config.toml``."""

from __future__ import annotations

import re
import string
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

DEFAULT_TMDB_API_KEY = "8ed20a12d9f37dcf9484a505c8be696c"

_OPENLIST_TOOL_NAMES = {
    item.casefold(): item
    for item in (
        "aria2",
        "qBittorrent",
        "PikPak",
        "115 Cloud",
        "115 Open",
        "123Pan",
        "123 Open",
        "SimpleHttp",
        "Thunder",
        "ThunderBrowser",
        "ThunderX",
        "Transmission",
    )
}

_SUPPORTED_RENAME_FIELDS = frozenset(
    {"anime_name", "season", "episode", "fansub", "quality", "languages"}
)

MetadataParserProvider = Literal["llm", "regex"]
MetadataValidatorProvider = Literal["tmdb", "none"]
LLMProviderType = Literal["openai", "anthropic"]


class ConfigModel(BaseModel):
    """Base model that also validates values changed after loading."""

    model_config = ConfigDict(validate_assignment=True)


def _normalize_choice(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


def _normalize_offline_download_tool_name(value: str) -> str:
    stripped = value.strip()
    return _OPENLIST_TOOL_NAMES.get(stripped.casefold(), stripped)


class PriorityConfig(ConfigModel):
    """Configuration for release download priority filtering.

    Each field is an ordered list where earlier entries have higher priority.
    When a higher-priority release has already been downloaded for the same
    (anime_name, season, episode), lower-priority releases are skipped.

    The ``version`` field is exempt: a newer version is always downloaded
    regardless of priority rules.
    """

    field_order: list[str] = Field(
        default_factory=lambda: ["fansub", "quality", "languages"]
    )  # Order in which fields are compared; earlier fields take precedence
    fansub: list[str] = Field(
        default_factory=list
    )  # Fansub group priority, e.g. ["Fansub_A", "Fansub_B"]
    languages: list[str] = Field(default_factory=list)  # Language priority labels
    quality: list[str] = Field(
        default_factory=lambda: ["2160p", "1080p", "720p", "480p", "360p"]
    )  # Quality priority (high to low); set to [] to disable


class MetadataFilterConfig(ConfigModel):
    """Configuration for metadata-based blacklist filtering.

    Each field is a list of values to exclude.  An RSS entry whose
    metadata matches any value in the corresponding list is filtered out.
    """

    exclude_fansub: list[str] = Field(default_factory=list)  # Fansub groups to exclude
    exclude_quality: list[str] = Field(
        default_factory=list
    )  # Quality values to exclude, e.g. ["480p"]
    exclude_languages: list[str] = Field(
        default_factory=list
    )  # Language labels to exclude
    exclude_patterns: list[str] = Field(
        default_factory=list
    )  # Regex patterns to exclude RSS entries by title

    @field_validator("exclude_patterns")
    @classmethod
    def _validate_exclude_patterns(cls, patterns: list[str]) -> list[str]:
        for index, pattern in enumerate(patterns):
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(
                    f"exclude_patterns[{index}] is not a valid regex: "
                    f"'{pattern}'. Error: {error}"
                ) from error
        return patterns


class RSSConfig(ConfigModel):
    urls: list[str] = Field(default_factory=list)
    interval_time: int = 300  # RSS fetch interval in seconds (default: 5 minutes)
    strict: bool = (
        False  # Strict mode: filter entries whose rename stem matches existing downloads
    )
    filter: MetadataFilterConfig = MetadataFilterConfig()
    priority: PriorityConfig = PriorityConfig()


class OpenListConfig(ConfigModel):
    url: str = "http://localhost:5244"
    token: str = ""
    download_path: str = "/"
    offline_download_tool: str = "qBittorrent"
    rename_format: str = (
        "{anime_name} S{season:02d}E{episode:02d} {fansub} {quality} {languages}"
    )

    @field_validator("offline_download_tool", mode="before")
    @classmethod
    def _validate_offline_download_tool(cls, value: str) -> str:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("offline_download_tool cannot be empty.")
            return _normalize_offline_download_tool_name(normalized)
        return value

    @field_validator("rename_format")
    @classmethod
    def _validate_rename_format(cls, value: str) -> str:
        if not value:
            return value
        try:
            fields = {
                field_name
                for _, field_name, _, _ in string.Formatter().parse(value)
                if field_name is not None
            }
        except (ValueError, KeyError) as error:
            raise ValueError(f"invalid rename_format syntax: {error}") from error
        unsupported = fields - _SUPPORTED_RENAME_FIELDS
        if unsupported:
            raise ValueError(
                f"rename_format contains unsupported fields: {unsupported}. "
                f"Supported fields: {sorted(_SUPPORTED_RENAME_FIELDS)}"
            )
        return value


class DownloaderConfig(ConfigModel):
    provider: str = "openlist"


class FileRenamerConfig(ConfigModel):
    provider: str = "openlist"


class LLMConfig(ConfigModel):
    provider_type: LLMProviderType = "openai"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    tmdb_api_key: str = DEFAULT_TMDB_API_KEY
    tmdb_language: str = "zh-CN"  # TMDB metadata language (zh-CN, en-US, ja-JP, etc.)

    @field_validator("tmdb_api_key", mode="before")
    @classmethod
    def _default_tmdb_api_key_when_blank(cls, value: str) -> str:
        if isinstance(value, str) and not value.strip():
            return DEFAULT_TMDB_API_KEY
        return value

    @field_validator("provider_type", mode="before")
    @classmethod
    def _normalize_provider_type(cls, value: Any) -> Any:
        return _normalize_choice(value)


class MetadataParserConfig(ConfigModel):
    provider: MetadataParserProvider = "regex"

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: Any) -> Any:
        return _normalize_choice(value)


class MetadataValidatorConfig(ConfigModel):
    provider: MetadataValidatorProvider = "tmdb"

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: Any) -> Any:
        return _normalize_choice(value)


class MetadataPipelineConfig(ConfigModel):
    """Optional ordered provider pipeline used by the refactored core."""

    providers: list[str] = Field(default_factory=list)

    @field_validator("providers")
    @classmethod
    def _normalize_providers(cls, providers: list[str]) -> list[str]:
        normalized = [item.strip().lower() for item in providers if item.strip()]
        return list(dict.fromkeys(normalized))


class NotificationBotDetails(ConfigModel):
    """Mapping-compatible base for typed notification bot settings."""

    model_config = ConfigDict(validate_assignment=True, extra="allow")

    def get(self, key: str, default: Any = None) -> Any:
        return self.model_dump(exclude_none=True).get(key, default)


class TelegramNotificationBotDetails(NotificationBotDetails):
    bot_token: str = ""
    user_id: str | int | None = None


class PushPlusNotificationBotDetails(NotificationBotDetails):
    user_token: str = ""
    channel: str | None = None


class WechatNotificationBotDetails(NotificationBotDetails):
    account_id: str = ""
    token: str = ""
    base_url: str = "https://ilinkai.weixin.qq.com"
    home_channel: str = ""
    chat_id: str = ""


class FeishuNotificationBotDetails(NotificationBotDetails):
    app_id: str = ""
    app_secret: str = ""
    receive_id: str | None = None
    receive_id_type: str | None = None
    domain: str = "feishu"
    state_dir: str = "data/messaging"


_NOTIFICATION_BOT_DETAIL_TYPES: dict[str, type[NotificationBotDetails]] = {
    "telegram": TelegramNotificationBotDetails,
    "pushplus": PushPlusNotificationBotDetails,
    "wechat": WechatNotificationBotDetails,
    "feishu": FeishuNotificationBotDetails,
}


class BotConfig(ConfigModel):
    """Configuration for one notification bot with type-specific details."""

    type: str
    enabled: bool = True
    config: NotificationBotDetails | dict[str, Any] = Field(default_factory=dict)

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_type(cls, value: Any) -> Any:
        return _normalize_choice(value)

    @model_validator(mode="after")
    def _parse_typed_config(self) -> BotConfig:
        details_type = _NOTIFICATION_BOT_DETAIL_TYPES.get(
            self.type, NotificationBotDetails
        )
        raw = (
            self.config
            if isinstance(self.config, dict)
            else self.config.model_dump(exclude_none=True)
        )
        object.__setattr__(self, "config", details_type.model_validate(raw))
        return self

    @field_serializer("config")
    def _serialize_config(self, config: NotificationBotDetails) -> dict[str, Any]:
        return config.model_dump(exclude_none=True, exclude_defaults=True)

    def config_dict(self) -> dict[str, Any]:
        return self.config.model_dump(exclude_none=True, exclude_defaults=True)


class NotificationConfig(ConfigModel):
    """Configuration for notification system."""

    enabled: bool = False
    batch_interval: float = (
        300.0  # Batch notifications interval in seconds (default: 5 minutes, 0 to disable)
    )
    bots: list[BotConfig] = Field(default_factory=list)


class TelegramAssistantConfig(ConfigModel):
    """Configuration for Telegram assistant bot."""

    enabled: bool = False
    bot_token: str = ""
    allowed_users: list[int] = Field(default_factory=list)


class WechatAssistantConfig(ConfigModel):
    """Configuration for WeChat/iLink assistant bot."""

    enabled: bool = False
    account_id: str = ""
    token: str = ""
    base_url: str = "https://ilinkai.weixin.qq.com"
    home_channel: str = ""
    allowed_users: list[str] = Field(default_factory=list)
    dm_policy: str = "open"


class FeishuAssistantConfig(ConfigModel):
    """Configuration for Feishu/Lark assistant bot."""

    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    domain: str = "feishu"
    connection_mode: str = "websocket"
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8765
    webhook_path: str = "/feishu/webhook"
    bot_open_id: str = ""
    require_mention: bool = True
    state_dir: str = "data/messaging"
    allowed_users: list[str] = Field(default_factory=list)


class AutoDreamConfig(ConfigModel):
    """Configuration for auto-dream memory consolidation."""

    enabled: bool = True
    min_hours: float = 24.0  # Minimum hours since last consolidation
    min_sessions: int = 5  # Minimum sessions since last consolidation


class AssistantConfig(ConfigModel):
    """Configuration for assistant module."""

    enabled: bool = False
    max_context_tokens: int = 128_000
    session_compact_threshold: int = 100_000
    skills_dir: str = "skills"  # Skill search directory
    data_dir: str = "data/assistant"  # Memory file directory
    telegram: TelegramAssistantConfig = Field(default_factory=TelegramAssistantConfig)
    wechat: WechatAssistantConfig = Field(default_factory=WechatAssistantConfig)
    feishu: FeishuAssistantConfig = Field(default_factory=FeishuAssistantConfig)
    auto_dream: AutoDreamConfig = Field(default_factory=AutoDreamConfig)


class LogConfig(ConfigModel):
    """Configuration for logging."""

    level: str = "INFO"  # Log level: DEBUG, INFO, WARNING, ERROR, FATAL
    rotation: str = (
        "00:00"  # Log rotation time (e.g., "00:00" for midnight, "500 MB" for size-based)
    )
    retention: str = "1 week"  # How long to keep old logs


class BangumiConfig(ConfigModel):
    """Configuration for Bangumi API integration."""

    access_token: str = (
        ""  # Bangumi API Access Token (also supports env var BANGUMI_TOKEN)
    )


class MikanConfig(ConfigModel):
    """Configuration for Mikan (mikanani.me) integration."""

    username: str = ""  # Mikan account username
    password: str = ""  # Mikan account password


class ProxyConfig(ConfigModel):
    """Configuration for proxy settings."""

    http: str = ""  # HTTP proxy URL (e.g., "http://127.0.0.1:7890")
    https: str = ""  # HTTPS proxy URL (e.g., "http://127.0.0.1:7890")


class BackendConfig(ConfigModel):
    """Configuration for the backend API server."""

    host: str = "127.0.0.1"  # Bind address (localhost only by default)
    port: int = 26666  # Listening port


class UserConfig(ConfigModel):
    downloader: DownloaderConfig = DownloaderConfig()
    file_renamer: FileRenamerConfig = FileRenamerConfig()
    metadata_parser: MetadataParserConfig = MetadataParserConfig()
    metadata_validator: MetadataValidatorConfig = MetadataValidatorConfig()
    metadata: MetadataPipelineConfig = MetadataPipelineConfig()
    rss: RSSConfig = RSSConfig()
    openlist: OpenListConfig = OpenListConfig()
    llm: LLMConfig = LLMConfig()
    notification: NotificationConfig = NotificationConfig()
    assistant: AssistantConfig = AssistantConfig()
    log: LogConfig = LogConfig()
    proxy: ProxyConfig = ProxyConfig()
    bangumi: BangumiConfig = BangumiConfig()
    mikan: MikanConfig = MikanConfig()
    backend: BackendConfig = BackendConfig()

    def metadata_provider_names(self) -> tuple[str, ...]:
        """Return the canonical provider pipeline, including legacy fallback."""
        if self.metadata.providers:
            return tuple(self.metadata.providers)
        providers = [self.metadata_parser.provider]
        if self.metadata_validator.provider != "none":
            providers.append(self.metadata_validator.provider)
        return tuple(dict.fromkeys(providers))

    @model_validator(mode="before")
    @classmethod
    def _prefer_llm_parser_when_llm_key_is_configured(cls, values: Any) -> Any:
        """Keep regex as the default, but prefer LLM when a key is configured.

        Explicit ``metadata_parser.provider`` always wins so users can keep
        regex parsing while using LLM for other modules, such as the assistant.
        """
        if not isinstance(values, dict):
            return values

        metadata_parser = values.get("metadata_parser")
        if cls._has_explicit_metadata_parser_provider(metadata_parser):
            return values

        if not cls._has_llm_api_key(values.get("llm")):
            return values

        updated_values = dict(values)
        parser_config = (
            dict(metadata_parser) if isinstance(metadata_parser, dict) else {}
        )
        parser_config["provider"] = "llm"
        updated_values["metadata_parser"] = parser_config
        return updated_values

    @staticmethod
    def _has_explicit_metadata_parser_provider(metadata_parser: Any) -> bool:
        if isinstance(metadata_parser, dict):
            provider = metadata_parser.get("provider")
        else:
            provider = getattr(metadata_parser, "provider", None)
        return isinstance(provider, str) and bool(provider.strip())

    @staticmethod
    def _has_llm_api_key(llm_config: Any) -> bool:
        if isinstance(llm_config, dict):
            api_key = llm_config.get("openai_api_key")
        else:
            api_key = getattr(llm_config, "openai_api_key", None)
        return isinstance(api_key, str) and bool(api_key.strip())
