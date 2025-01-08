from dataclasses import dataclass
from typing import Optional

import yaml

from alist_mikananirss.alist.api import AlistDownloaderType
from alist_mikananirss.bot.pushplus_bot import PushPlusChannel

from ..utils import Singleton


class ConfigLoader:
    """A class for loading and accessing YAML configuration files.

    This class provides methods to load a YAML config file and retrieve values
    using dot notation paths.

    Attributes:
        config_path (str): The path to the YAML configuration file.
        config (dict): The loaded configuration data.

    Example:
        >>> config_loader = ConfigLoader('config.yaml')
        >>> database_url = config_loader.get('database.url')
        >>> port = config_loader.get('server.port', default=8080)
    """

    _MISSING = object()

    def __init__(self, config_path):
        """Initializes the ConfigLoader with the given config file path.

        Args:
            config_path (str): The path to the YAML configuration file.
        """
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self):
        """Loads the YAML configuration file.

        Returns:
            dict: The loaded configuration data.

        Raises:
            yaml.YAMLError: If there's an error parsing the YAML file.
        """
        with open(self.config_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file)

    def get(self, path, default=_MISSING):
        """Retrieves a value from the configuration using a dot notation path.

        Args:
            path (str): The dot notation path to the desired configuration value.
            default: The default value to return if the path is not found.
                     If not provided, a KeyError will be raised.

        Returns:
            The value at the specified path in the configuration.

        Raises:
            KeyError: If the path is not found and no default value is provided.
        """
        keys = path.split(".")
        value = self.config
        for key in keys:
            if value.get(key) is None:
                if default is not self._MISSING:
                    return default
                else:
                    raise KeyError(
                        f"{path} is not found in config file {self.config_path}"
                    )
            value = value[key]
        return value


@dataclass
class AppConfig:
    common_interval_time: int
    common_proxies: Optional[dict]

    alist_base_url: str
    alist_token: str
    alist_downloader: AlistDownloaderType
    alist_download_path: str

    mikan_subscribe_url: list
    mikan_regex_pattern: dict
    mikan_filters: list

    notification_enable: bool
    notification_telegram_enable: bool
    notification_telegram_bot_token: str
    notification_telegram_user_id: str
    notification_pushplus_enable: bool
    notification_pushplus_token: str
    notification_pushplus_channel: PushPlusChannel
    notification_interval_time: int

    rename_enable: bool
    rename_chatgpt_api_key: str
    rename_chatgpt_base_url: str
    rename_chatgpt_model: str
    rename_format: str
    rename_remap_enable: bool
    rename_remap_cfg_path: str

    bot_assistant_enable: bool
    bot_assistant_telegram_enable: bool
    bot_assistant_telegram_bot_token: str

    dev_log_level: str

    def __post_init__(self):
        """Check the validity of the configuration."""
        if self.notification_enable:
            assert (
                self.notification_telegram_enable or self.notification_pushplus_enable
            ), "At least one notification method should be enabled."
        if self.notification_telegram_enable:
            assert (
                self.notification_telegram_bot_token
                and self.notification_telegram_user_id
            ), "Telegram bot token and user id should be provided."
        if self.notification_pushplus_enable:
            assert (
                self.notification_pushplus_token
            ), "Pushplus token should be provided."
        if self.rename_enable:
            assert self.rename_chatgpt_api_key, "ChatGPT API key should be provided."
            self.__check_rename_format(self.rename_format)
        if self.bot_assistant_enable:
            assert (
                self.bot_assistant_telegram_enable
            ), "Telegram config should be provided."
            assert (
                self.bot_assistant_telegram_bot_token
            ), "Telegram bot token should be provided."

        assert self.common_interval_time >= 0, "Invalid interval time."
        assert self.dev_log_level in [
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ], "Invalid log level."

    def __repr__(self) -> str:
        sections = {
            "common": {
                "interval_time": self.common_interval_time,
                "proxies": self.common_proxies,
            },
            "alist": {
                "base_url": self.alist_base_url,
                "token": self.alist_token,
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
                    "bot_token": self.notification_telegram_bot_token,
                    "user_id": self.notification_telegram_user_id,
                },
                "pushplus": {"token": self.notification_pushplus_token},
                "interval_time": self.notification_interval_time,
            },
            "rename": {
                "chatgpt": {
                    "api_key": self.rename_chatgpt_api_key,
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
                    "bot_token": self.bot_assistant_telegram_bot_token,
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
                    for item in value:
                        result.append(f"{spaces}  - {item}")
                else:
                    result.append(f"{spaces}{key}: {value}")
            return "\n".join(result)

        return format_dict(sections)

    def __check_rename_format(self, rename_format: str):
        # Check if there are unknown keys in rename format
        from collections import defaultdict

        all_key_test_data = {
            "name": "test",
            "season": 1,
            "episode": 1,
            "fansub": "fansub",
            "quality": "1080p",
            "language": "简体中文",
        }
        # if the key in rename_format is not in all_key_test_data, it will be replaced by "undefined"
        safe_dict = defaultdict(lambda: "undefined", all_key_test_data)
        res = rename_format.format_map(safe_dict)
        if "undefined" in res:
            unknown_keys = [
                key for key, value in safe_dict.items() if value == "undefined"
            ]
            raise KeyError(f"Error keys in rename format: {', '.join(unknown_keys)}")


class ConfigManager(metaclass=Singleton):
    def __init__(self, config_path):
        self.config: AppConfig = self.__load_config(config_path)

    def __load_config(self, path):
        config_loader = ConfigLoader(path)

        default_regex_pattern = {
            "简体": "(简体|简中|简日|CHS)",
            "繁体": "(繁体|繁中|繁日|CHT|Baha)",
            "1080p": "(X1080|1080P)",
            "非合集": "^(?!.*(\\d{2}-\\d{2}|合集)).*",
        }

        alist_downloader = AlistDownloaderType(
            config_loader.get("alist.downloader", AlistDownloaderType.ARIA.value)
        )

        return AppConfig(
            common_interval_time=config_loader.get("common.interval_time", 300),
            common_proxies=config_loader.get("common.proxies", None),
            alist_base_url=config_loader.get("alist.base_url"),
            alist_token=config_loader.get("alist.token"),
            alist_downloader=alist_downloader,
            alist_download_path=config_loader.get("alist.download_path"),
            mikan_subscribe_url=config_loader.get("mikan.subscribe_url"),
            mikan_regex_pattern=default_regex_pattern
            | config_loader.get("mikan.regex_pattern", {}),
            mikan_filters=config_loader.get("mikan.filters", ["1080p", "非合集"]),
            notification_enable=(
                False if not config_loader.get("notification", {}) else True
            ),
            notification_telegram_enable=(
                False if not config_loader.get("notification.telegram", {}) else True
            ),
            notification_telegram_bot_token=config_loader.get(
                "notification.telegram.bot_token", ""
            ),
            notification_telegram_user_id=config_loader.get(
                "notification.telegram.user_id", ""
            ),
            notification_pushplus_enable=(
                False if not config_loader.get("notification.pushplus", {}) else True
            ),
            notification_pushplus_token=config_loader.get(
                "notification.pushplus.token", ""
            ),
            notification_pushplus_channel=PushPlusChannel(
                config_loader.get(
                    "notification.pushplus.channel", PushPlusChannel.WECHAT.value
                )
            ),
            notification_interval_time=config_loader.get(
                "notification.interval_time", 300
            ),
            rename_enable=False if not config_loader.get("rename", {}) else True,
            rename_chatgpt_api_key=config_loader.get("rename.chatgpt.api_key", ""),
            rename_chatgpt_base_url=config_loader.get("rename.chatgpt.base_url", ""),
            rename_chatgpt_model=config_loader.get(
                "rename.chatgpt.model", "gpt-3.5-turbo"
            ),
            rename_format=config_loader.get(
                "rename.rename_format", "{name} S{season:02d}E{episode:02d}"
            ),
            rename_remap_enable=config_loader.get("rename.remap.enable", False),
            rename_remap_cfg_path=config_loader.get(
                "rename.remap.cfg_path", "remap.yaml"
            ),
            bot_assistant_enable=(
                False if not config_loader.get("bot_assistant", {}) else True
            ),
            bot_assistant_telegram_enable=(
                False if not config_loader.get("bot_assistant.telegram", {}) else True
            ),
            bot_assistant_telegram_bot_token=config_loader.get(
                "bot_assistant.telegram.bot_token", ""
            ),
            dev_log_level=config_loader.get("dev.log_level", "INFO"),
        )

    def get_config(self):
        return self.config
