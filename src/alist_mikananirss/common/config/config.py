from enum import Enum

import yaml
from pydantic import BaseModel, Field

from .basic import (
    AlistConfig,
    BotAssistantConfig,
    CommonConfig,
    DevConfig,
    MikanConfig,
    NotificationConfig,
    RenameConfig,
)


class AppConfig(BaseModel):
    common: CommonConfig = Field(default_factory=CommonConfig)
    alist: AlistConfig = Field(default_factory=AlistConfig)
    mikan: MikanConfig = Field(default_factory=MikanConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    rename: RenameConfig = Field(default_factory=RenameConfig)
    bot_assistant: BotAssistantConfig = Field(default_factory=BotAssistantConfig)
    dev: DevConfig = Field(default_factory=DevConfig)

    def __str__(self):
        # 为所有Enum子类定义representer
        def enum_representer(dumper, data):
            return dumper.represent_scalar("tag:yaml.org,2002:str", data.value)

        yaml.add_multi_representer(Enum, enum_representer)

        config_dict = self.model_dump()
        yaml_str = yaml.dump(
            config_dict, sort_keys=False, default_flow_style=False, allow_unicode=True
        )
        return yaml_str


class ConfigManager:
    def __init__(self):
        self.config_path = None
        self.config = None

    def load_config(self, path):
        with open(path, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f)
        self.config_path = path
        self.config = AppConfig.model_validate(config_dict)
        return self.config

    def get_config(self):
        if not self.config:
            raise RuntimeError("Config not loaded")
        return self.config
