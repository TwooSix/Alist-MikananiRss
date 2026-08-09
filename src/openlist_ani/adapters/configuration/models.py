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
CURRENT_CONFIG_VERSION = 2
OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1"
ANTHROPIC_MESSAGES_BASE_URL = "https://api.anthropic.com"

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
    {"anime_name", "season", "episode", "year", "fansub", "quality", "languages"}
)

MetadataParserProvider = Literal["llm", "regex"]
MetadataValidatorProvider = Literal["tmdb", "none"]
LLMProviderType = Literal["openai", "anthropic"]
AISourceType = Literal["api", "agent"]
AIProvider = Literal["openai-compatible", "anthropic-messages"]
NotificationBotType = Literal["telegram", "pushplus", "wechat", "feishu"]
FeishuConnectionMode = Literal["websocket", "webhook"]
FeishuDomain = Literal["feishu", "lark"]
LogLevel = Literal[
    "TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL", "FATAL"
]

_METADATA_PROVIDER_PHASES = {
    "regex": "title",
    "ai": "title",
    "tmdb": "enrichment",
}
_PRIORITY_FIELDS = frozenset({"fansub", "quality", "languages"})


class ConfigModel(BaseModel):
    """Base model that also validates values changed after loading."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")


def _normalize_choice(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


def _normalize_offline_download_tool_name(value: str) -> str:
    stripped = value.strip()
    return _OPENLIST_TOOL_NAMES.get(stripped.casefold(), stripped)


def normalize_metadata_pipeline(providers: list[str]) -> list[str]:
    """Return canonical provider names while preserving declared order."""
    normalized = [
        "ai" if item.strip().lower() == "llm" else item.strip().lower()
        for item in providers
        if item.strip()
    ]
    return list(dict.fromkeys(normalized))


def validate_metadata_pipeline(
    providers: list[str] | tuple[str, ...], *, allow_empty: bool = False
) -> None:
    """Validate provider availability and the title-before-enrichment contract."""
    if not providers:
        if allow_empty:
            return
        raise ValueError("At least one metadata provider is required.")

    unknown = [name for name in providers if name not in _METADATA_PROVIDER_PHASES]
    if unknown:
        supported = ", ".join(_METADATA_PROVIDER_PHASES)
        raise ValueError(
            f"Unknown metadata provider(s): {', '.join(unknown)}. "
            f"Supported providers: {supported}."
        )

    if not any(_METADATA_PROVIDER_PHASES[name] == "title" for name in providers):
        raise ValueError(
            "metadata.pipeline requires 'regex' or 'ai' before enrichment; "
            "'tmdb' cannot extract episode metadata by itself."
        )

    enrichment_started = False
    for name in providers:
        phase = _METADATA_PROVIDER_PHASES[name]
        if phase == "enrichment":
            enrichment_started = True
        elif enrichment_started:
            raise ValueError(
                "metadata.pipeline must place title extraction ('regex' or 'ai') "
                "before enrichment ('tmdb')."
            )


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

    @field_validator("field_order")
    @classmethod
    def _validate_field_order(cls, fields: list[str]) -> list[str]:
        normalized = [field.strip().lower() for field in fields]
        unknown = [field for field in normalized if field not in _PRIORITY_FIELDS]
        if unknown:
            raise ValueError(
                f"Unknown priority field(s): {', '.join(unknown)}. "
                f"Supported fields: {', '.join(sorted(_PRIORITY_FIELDS))}."
            )
        if len(normalized) != len(set(normalized)):
            raise ValueError("rss.priority.field_order cannot contain duplicates.")
        return normalized


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
    interval_time: int = Field(
        default=300, gt=0
    )  # RSS fetch interval in seconds (default: 5 minutes)
    strict: bool = (
        False  # Strict mode: filter entries whose rename stem matches existing downloads
    )
    torrent_to_magnet: bool = False
    filter: MetadataFilterConfig = MetadataFilterConfig()
    priority: PriorityConfig = PriorityConfig()


class OpenListConfig(ConfigModel):
    url: str = "http://localhost:5244"
    token: str = ""
    # Retained as non-serialised compatibility attributes.  In config v2 these
    # values live on [downloader].
    download_path: str = Field(default="/", exclude=True)
    offline_download_tool: str = "qBittorrent"
    rename_format: str = Field(
        default="{anime_name} S{season:02d}E{episode:02d} {fansub} {quality} {languages}",
        exclude=True,
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
    download_path: str = "/"
    rename_format: str = (
        "{anime_name} S{season:02d}E{episode:02d} {fansub} {quality} {languages}"
    )
    openlist: OpenListConfig = Field(default_factory=OpenListConfig)
    # Compatibility attribute for callers compiled against config v1.
    provider: str = Field(default="openlist", exclude=True)

    @field_validator("rename_format")
    @classmethod
    def _validate_rename_format(cls, value: str) -> str:
        return OpenListConfig(rename_format=value).rename_format


class FileRenamerConfig(ConfigModel):
    provider: str = "openlist"


class AISourceConfig(ConfigModel):
    """One named API endpoint or external agent harness."""

    type: AISourceType
    provider: AIProvider | Literal[""] = ""
    agent: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    executable: str = ""

    @field_validator("type", "provider", "agent", mode="before")
    @classmethod
    def _normalize_source_choice(cls, value: Any) -> Any:
        return _normalize_choice(value)

    @model_validator(mode="after")
    def _validate_shape(self) -> AISourceConfig:
        if self.type == "api":
            self._validate_api_shape()
        else:
            self._validate_agent_shape()
        return self

    def _validate_api_shape(self) -> None:
        if not self.provider:
            raise ValueError("API source requires 'provider'.")
        if self.agent:
            raise ValueError("API source cannot configure 'agent'.")
        if self.executable:
            raise ValueError("API source cannot configure 'executable'.")
        if not self.api_key.strip():
            raise ValueError("API source requires a non-empty 'api_key'.")
        if not self.model.strip():
            raise ValueError("API source requires a non-empty 'model'.")
        if not self.base_url:
            self.base_url = (
                OPENAI_COMPATIBLE_BASE_URL
                if self.provider == "openai-compatible"
                else ANTHROPIC_MESSAGES_BASE_URL
            )

    def _validate_agent_shape(self) -> None:
        if not self.agent:
            raise ValueError("Agent source requires 'agent'.")
        forbidden = []
        if self.provider:
            forbidden.append("provider")
        if self.api_key:
            forbidden.append("api_key")
        if self.base_url:
            forbidden.append("base_url")
        if forbidden:
            raise ValueError(
                "Agent source cannot configure API fields: " + ", ".join(forbidden)
            )

    @property
    def provider_type(self) -> str:
        """Translate the public provider name to the existing SDK adapter name."""
        if self.provider == "openai-compatible":
            return "openai"
        if self.provider == "anthropic-messages":
            return "anthropic"
        raise ValueError("Agent sources do not have an API provider type.")


class AIConfig(ConfigModel):
    sources: dict[str, AISourceConfig] = Field(default_factory=dict)

    @field_validator("sources")
    @classmethod
    def _validate_source_names(
        cls, sources: dict[str, AISourceConfig]
    ) -> dict[str, AISourceConfig]:
        for name in sources:
            if not name.strip():
                raise ValueError("AI source names cannot be empty.")
            if name != name.strip():
                raise ValueError("AI source names cannot have surrounding whitespace.")
        return sources

    def resolve(
        self, name: str | None, *, consumer: str
    ) -> tuple[str, AISourceConfig] | None:
        selected_name = name.strip() if name else ""
        if not self.sources:
            if selected_name:
                raise ValueError(
                    f"AI source '{selected_name}' selected by {consumer}, but no "
                    "[ai.sources.*] entries are configured."
                )
            return None
        if not selected_name:
            return next(iter(self.sources.items()))
        try:
            return selected_name, self.sources[selected_name]
        except KeyError as error:
            available = ", ".join(self.sources)
            raise ValueError(
                f"Unknown AI source '{selected_name}' selected by {consumer}. "
                f"Available sources: {available}."
            ) from error


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
    """Ordered metadata pipeline and the AI implementation used by its ai step."""

    pipeline: list[str] = Field(default_factory=list)
    ai_source: str = ""
    tmdb: "TMDBConfig" = Field(default_factory=lambda: TMDBConfig())
    # Input compatibility for direct library users.  File migration removes it.
    providers: list[str] = Field(default_factory=list, exclude=True)

    @field_validator("pipeline", "providers")
    @classmethod
    def _normalize_providers(cls, providers: list[str]) -> list[str]:
        normalized = normalize_metadata_pipeline(providers)
        validate_metadata_pipeline(normalized, allow_empty=True)
        return normalized


class TMDBConfig(ConfigModel):
    api_key: str = DEFAULT_TMDB_API_KEY
    language: str = "zh-CN"

    @field_validator("api_key", mode="before")
    @classmethod
    def _default_api_key_when_blank(cls, value: str) -> str:
        if isinstance(value, str) and not value.strip():
            return DEFAULT_TMDB_API_KEY
        return value


class NotificationBotDetails(ConfigModel):
    """Mapping-compatible base for typed notification bot settings."""

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
    domain: FeishuDomain = "feishu"
    state_dir: str = "data/messaging"

    @field_validator("domain", mode="before")
    @classmethod
    def _normalize_domain(cls, value: Any) -> Any:
        return _normalize_choice(value)


_NOTIFICATION_BOT_DETAIL_TYPES: dict[str, type[NotificationBotDetails]] = {
    "telegram": TelegramNotificationBotDetails,
    "pushplus": PushPlusNotificationBotDetails,
    "wechat": WechatNotificationBotDetails,
    "feishu": FeishuNotificationBotDetails,
}


class BotConfig(ConfigModel):
    """Configuration for one notification bot with type-specific details."""

    type: NotificationBotType
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
    batch_interval: float = Field(
        default=300.0,
        ge=0,
        description="Batch interval in seconds; 0 sends each event immediately.",
    )
    bots: list[BotConfig] = Field(default_factory=list)


def _validate_remote_user_ids(values: list[str], *, platform: str) -> list[str]:
    normalized = [value.strip() for value in values]
    if any(not value for value in normalized):
        raise ValueError(f"{platform} allowed_users cannot contain empty user IDs.")
    return list(dict.fromkeys(normalized))


class TelegramAssistantConfig(ConfigModel):
    """Configuration for Telegram assistant bot."""

    enabled: bool = False
    bot_token: str = ""
    allowed_users: list[int] = Field(default_factory=list)

    @field_validator("allowed_users")
    @classmethod
    def _validate_allowed_users(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("Telegram allowed_users must contain positive user IDs.")
        return list(dict.fromkeys(values))


class WechatAssistantConfig(ConfigModel):
    """Configuration for WeChat/iLink assistant bot."""

    enabled: bool = False
    account_id: str = ""
    token: str = ""
    base_url: str = "https://ilinkai.weixin.qq.com"
    home_channel: str = ""
    allowed_users: list[str] = Field(default_factory=list)
    # Accepted only so existing v2 files keep loading. Access is enforced by
    # home_channel + allowed_users; this legacy field has no runtime effect.
    dm_policy: str = Field(default="open", exclude=True)

    @field_validator("allowed_users")
    @classmethod
    def _validate_allowed_users(cls, values: list[str]) -> list[str]:
        return _validate_remote_user_ids(values, platform="WeChat")


class FeishuAssistantConfig(ConfigModel):
    """Configuration for Feishu/Lark assistant bot."""

    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    domain: FeishuDomain = "feishu"
    connection_mode: FeishuConnectionMode = "websocket"
    webhook_host: str = "127.0.0.1"
    webhook_port: int = Field(default=8765, ge=1, le=65535)
    webhook_path: str = "/feishu/webhook"
    bot_open_id: str = ""
    require_mention: bool = True
    state_dir: str = "data/messaging"
    allowed_users: list[str] = Field(default_factory=list)

    @field_validator("allowed_users")
    @classmethod
    def _validate_allowed_users(cls, values: list[str]) -> list[str]:
        return _validate_remote_user_ids(values, platform="Feishu")

    @field_validator("connection_mode", "domain", mode="before")
    @classmethod
    def _normalize_connection_mode(cls, value: Any) -> Any:
        return _normalize_choice(value)


class AssistantConfig(ConfigModel):
    """Configuration for assistant module."""

    enabled: bool = False
    backend: str = ""
    skills_dir: str = "skills"  # Direct for Pi/Claude; projected for Codex
    telegram: TelegramAssistantConfig = Field(default_factory=TelegramAssistantConfig)
    wechat: WechatAssistantConfig = Field(default_factory=WechatAssistantConfig)
    feishu: FeishuAssistantConfig = Field(default_factory=FeishuAssistantConfig)


class LogConfig(ConfigModel):
    """Configuration for logging."""

    level: LogLevel = "INFO"  # Log level: DEBUG, INFO, WARNING, ERROR, FATAL
    rotation: str = (
        "00:00"  # Log rotation time (e.g., "00:00" for midnight, "500 MB" for size-based)
    )
    retention: str = "1 week"  # How long to keep old logs

    @field_validator("level", mode="before")
    @classmethod
    def _normalize_level(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value


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
    port: int = Field(default=26666, ge=1, le=65535)  # Listening port


class UserConfig(ConfigModel):
    config_version: Literal[2] = CURRENT_CONFIG_VERSION
    ai: AIConfig = Field(default_factory=AIConfig)
    downloader: DownloaderConfig = DownloaderConfig()
    metadata: MetadataPipelineConfig = MetadataPipelineConfig()
    rss: RSSConfig = RSSConfig()
    notification: NotificationConfig = NotificationConfig()
    assistant: AssistantConfig = AssistantConfig()
    log: LogConfig = LogConfig()
    proxy: ProxyConfig = ProxyConfig()
    bangumi: BangumiConfig = BangumiConfig()
    mikan: MikanConfig = MikanConfig()
    backend: BackendConfig = BackendConfig()
    # Python API compatibility only.  These fields are excluded from v2 TOML
    # serialisation and are never consumed by the v2 runtime.
    file_renamer: FileRenamerConfig = Field(
        default_factory=FileRenamerConfig, exclude=True
    )
    metadata_parser: MetadataParserConfig = Field(
        default_factory=MetadataParserConfig, exclude=True
    )
    metadata_validator: MetadataValidatorConfig = Field(
        default_factory=MetadataValidatorConfig, exclude=True
    )
    openlist: OpenListConfig = Field(default_factory=OpenListConfig, exclude=True)
    llm: LLMConfig = Field(default_factory=LLMConfig, exclude=True)

    def metadata_provider_names(self) -> tuple[str, ...]:
        """Return the canonical v2 provider pipeline."""
        if self.metadata.pipeline:
            return tuple(self.metadata.pipeline)
        if self.metadata.providers:
            return tuple(self.metadata.providers)
        return "regex", "tmdb"

    def resolve_metadata_ai_source(self) -> tuple[str, AISourceConfig] | None:
        return self.ai.resolve(self.metadata.ai_source, consumer="metadata.ai_source")

    def resolve_assistant_source(self) -> tuple[str, AISourceConfig] | None:
        return self.ai.resolve(self.assistant.backend, consumer="assistant.backend")

    @model_validator(mode="after")
    def _validate_source_references(self) -> UserConfig:
        if self.metadata.ai_source:
            if "ai" not in self.metadata_provider_names():
                raise ValueError(
                    "metadata.ai_source is configured, but metadata.pipeline does "
                    "not contain 'ai'."
                )
            self.resolve_metadata_ai_source()
        if self.assistant.backend:
            self.resolve_assistant_source()
        return self

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
