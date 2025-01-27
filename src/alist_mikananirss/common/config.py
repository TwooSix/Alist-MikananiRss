from collections import defaultdict
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from alist_mikananirss.alist import AlistDownloaderType
from alist_mikananirss.bot import PushPlusChannel

from ..utils import Singleton
from .config_loader import ConfigLoader


class AppConfig(BaseModel):
    # Common settings
    common_interval_time: int = Field(
        ge=0, description="Interval time must be non-negative"
    )
    common_proxies: Optional[Dict]

    # Alist settings
    alist_base_url: str
    alist_token: str
    alist_downloader: AlistDownloaderType
    alist_download_path: str

    # Mikan settings
    mikan_subscribe_url: List[str] = Field(min_length=1)
    mikan_regex_pattern: Dict
    mikan_filters: List

    # Notification settings
    notification_enable: bool
    notification_telegram_enable: bool
    notification_telegram_bot_token: str
    notification_telegram_user_id: str
    notification_pushplus_enable: bool
    notification_pushplus_token: str
    notification_pushplus_channel: PushPlusChannel
    notification_interval_time: int

    # Rename settings
    rename_enable: bool
    rename_chatgpt_api_key: str
    rename_chatgpt_base_url: str
    rename_chatgpt_model: str
    rename_format: str
    rename_remap_enable: bool
    rename_remap_cfg_path: str

    # Bot assistant settings
    bot_assistant_enable: bool
    bot_assistant_telegram_enable: bool
    bot_assistant_telegram_bot_token: str

    # Dev settings
    dev_log_level: str = Field(
        default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$"
    )

    @field_validator("alist_base_url", "mikan_subscribe_url")
    @classmethod
    def validate_url(cls, url: str | List[str]) -> str | List[str]:
        if isinstance(url, list):
            for u in url:
                HttpUrl(u)
        else:
            HttpUrl(url)
        return url

    @model_validator(mode="after")
    def validate_notification_config(self) -> "AppConfig":
        if self.notification_enable:
            if not (
                self.notification_telegram_enable or self.notification_pushplus_enable
            ):
                raise ValueError("At least one notification method should be enabled")

            if self.notification_telegram_enable and not (
                self.notification_telegram_bot_token
                and self.notification_telegram_user_id
            ):
                raise ValueError("Telegram bot token and user id should be provided")

            if (
                self.notification_pushplus_enable
                and not self.notification_pushplus_token
            ):
                raise ValueError("Pushplus token should be provided")

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

    @model_validator(mode="after")
    def validate_bot_assistant_config(self) -> "AppConfig":
        if self.bot_assistant_enable:
            if not self.bot_assistant_telegram_enable:
                raise ValueError("Telegram config should be provided")
            if not self.bot_assistant_telegram_bot_token:
                raise ValueError("Telegram bot token should be provided")
        return self

    def format_output_yaml(self) -> str:
        sections = {
            "common": {
                "interval_time": self.common_interval_time,
                "proxies": self.common_proxies,
            },
            "alist": {
                "base_url": self.alist_base_url,
                "token": "***" if self.alist_token else None,
                "downloader": self.alist_downloader,
                "download_path": self.alist_download_path,
            },
            "mikan": {
                "subscribe_url": self.mikan_subscribe_url,
                "regex_pattern": self.mikan_regex_pattern,
                "filters": self.mikan_filters,
            },
            "notification": {
                "telegram": {
                    "bot_token": "***" if self.notification_telegram_bot_token else "",
                    "user_id": "***" if self.notification_telegram_user_id else "",
                },
                "pushplus": {
                    "token": "***" if self.notification_pushplus_token else ""
                },
                "interval_time": self.notification_interval_time,
            },
            "rename": {
                "chatgpt": {
                    "api_key": "***" if self.rename_chatgpt_api_key else "",
                    "base_url": self.rename_chatgpt_base_url,
                    "model": self.rename_chatgpt_model,
                },
                "rename_format": self.rename_format,
                "remap": {
                    "enable": self.rename_remap_enable,
                    "cfg_path": self.rename_remap_cfg_path,
                },
            },
            "bot_assistant": {
                "telegram": {
                    "bot_token": "***" if self.bot_assistant_telegram_bot_token else "",
                },
            },
            "dev": {"log_level": self.dev_log_level},
        }

        def format_dict(d: dict, indent: int = 0) -> str:
            result = []
            for key, value in d.items():
                spaces = " " * indent
                if isinstance(value, dict):
                    result.append(f"{spaces}{key}:")
                    result.append(format_dict(value, indent + 2))
                elif isinstance(value, list):
                    result.append(f"{spaces}{key}:")
                    result.extend(f"{spaces}  - {item}" for item in value)
                else:
                    result.append(f"{spaces}{key}: {value}")
            return "\n".join(result)

        return format_dict(sections)


class ConfigManager(metaclass=Singleton):
    def __init__(self, config_path=None):
        if config_path:
            self.config: AppConfig = self.__load_config(config_path)
            self.config_path = config_path

    def __load_config(self, path):
        config_loader = ConfigLoader(path)
        # ----------common----------
        common_interval_time = config_loader.get("common.interval_time", 300)
        common_proxies = config_loader.get("common.proxies", None)
        # ----------alist----------
        alist_base_url = config_loader.get("alist.base_url")
        alist_token = config_loader.get("alist.token")
        alist_downloader = AlistDownloaderType(
            config_loader.get("alist.downloader", AlistDownloaderType.ARIA.value)
        )
        alist_download_path = config_loader.get("alist.download_path")
        # ----------mikan----------
        urls = config_loader.get("mikan.subscribe_url")
        if isinstance(urls, str):
            urls = [urls]
        mikan_subscribe_url = urls
        default_regex_pattern = {
            "简体": "(简体|简中|简日|CHS)",
            "繁体": "(繁体|繁中|繁日|CHT|Baha)",
            "1080p": "(X1080|1080P)",
            "非合集": "^(?!.*(\\d{2}-\\d{2}|合集)).*",
        }
        default_regex_pattern.update(config_loader.get("mikan.regex_pattern", {}))
        mikan_regex_pattern = default_regex_pattern
        mikan_filters = config_loader.get("mikan.filters", ["1080p", "非合集"])
        # ----------notification----------
        notification_enable = (
            False if not config_loader.get("notification", {}) else True
        )
        notification_telegram_enable = (
            False if not config_loader.get("notification.telegram", {}) else True
        )
        notification_telegram_bot_token = config_loader.get(
            "notification.telegram.bot_token", ""
        )
        notification_telegram_user_id = str(
            config_loader.get("notification.telegram.user_id", "")
        )
        notification_pushplus_enable = (
            False if not config_loader.get("notification.pushplus", {}) else True
        )
        notification_pushplus_token = config_loader.get(
            "notification.pushplus.token", ""
        )
        notification_pushplus_channel = PushPlusChannel(
            config_loader.get(
                "notification.pushplus.channel", PushPlusChannel.WECHAT.value
            )
        )
        notification_interval_time = config_loader.get(
            "notification.interval_time", 300
        )
        # ----------rename----------
        rename_enable = False if not config_loader.get("rename", {}) else True
        rename_chatgpt_api_key = config_loader.get("rename.chatgpt.api_key", "")
        rename_chatgpt_base_url = config_loader.get("rename.chatgpt.base_url", "")
        rename_chatgpt_model = config_loader.get("rename.chatgpt.model", "gpt-4o-mini")
        rename_format = config_loader.get(
            "rename.rename_format", "{name} S{season:02d}E{episode:02d}"
        )
        rename_remap_enable = config_loader.get("rename.remap.enable", False)
        rename_remap_cfg_path = config_loader.get("rename.remap.cfg_path", "remap.yaml")
        # ----------bot_assistant----------
        bot_assistant_enable = (
            False if not config_loader.get("bot_assistant", {}) else True
        )
        bot_assistant_telegram_enable = (
            False if not config_loader.get("bot_assistant.telegram", {}) else True
        )
        bot_assistant_telegram_bot_token = config_loader.get(
            "bot_assistant.telegram.bot_token", ""
        )
        # ----------dev----------
        dev_log_level = config_loader.get("dev.log_level", "INFO")

        return AppConfig(
            common_interval_time=common_interval_time,
            common_proxies=common_proxies,
            alist_base_url=alist_base_url,
            alist_token=alist_token,
            alist_downloader=alist_downloader,
            alist_download_path=alist_download_path,
            mikan_subscribe_url=mikan_subscribe_url,
            mikan_regex_pattern=mikan_regex_pattern,
            mikan_filters=mikan_filters,
            notification_enable=notification_enable,
            notification_telegram_enable=notification_telegram_enable,
            notification_telegram_bot_token=notification_telegram_bot_token,
            notification_telegram_user_id=notification_telegram_user_id,
            notification_pushplus_enable=notification_pushplus_enable,
            notification_pushplus_token=notification_pushplus_token,
            notification_pushplus_channel=notification_pushplus_channel,
            notification_interval_time=notification_interval_time,
            rename_enable=rename_enable,
            rename_chatgpt_api_key=rename_chatgpt_api_key,
            rename_chatgpt_base_url=rename_chatgpt_base_url,
            rename_chatgpt_model=rename_chatgpt_model,
            rename_format=rename_format,
            rename_remap_enable=rename_remap_enable,
            rename_remap_cfg_path=rename_remap_cfg_path,
            bot_assistant_enable=bot_assistant_enable,
            bot_assistant_telegram_enable=bot_assistant_telegram_enable,
            bot_assistant_telegram_bot_token=bot_assistant_telegram_bot_token,
            dev_log_level=dev_log_level,
        )

    def load_config(self, path):
        self.config = self.__load_config(path)
        self.config_path = path

    def reload_config(self):
        self.config = self.__load_config(self.config_path)

    def get_config(self):
        if not self.config:
            raise RuntimeError("Config not loaded")
        return self.config
