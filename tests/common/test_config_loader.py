import pytest

from alist_mikananirss.alist.api import AlistDownloaderType
from alist_mikananirss.common.config import ConfigManager


@pytest.fixture(autouse=True)
def clear_manager():
    ConfigManager._instances.pop(ConfigManager, None)


def test_load_config():
    config_path = "tests/common/test_config_valid.yaml"
    cfg = ConfigManager(config_path).get_config()
    assert cfg.common_interval_time == 300
    assert cfg.common_proxies is None

    assert cfg.alist_base_url == "http://127.0.0.1:5244"
    assert cfg.alist_token == "your_token"
    assert cfg.alist_downloader == AlistDownloaderType.ARIA
    assert cfg.alist_download_path == "Onedrive/Anime"

    assert isinstance(cfg.mikan_subscribe_url, list)
    assert all(
        filter_name in cfg.mikan_regex_pattern for filter_name in cfg.mikan_filters
    )

    assert cfg.notification_enable is True
    assert cfg.notification_telegram_enable is True
    assert cfg.notification_pushplus_enable is False
    assert cfg.notification_interval_time == 300

    assert cfg.rename_enable is True
    assert cfg.rename_chatgpt_api_key == "sk-xxx"
    assert cfg.rename_chatgpt_base_url == "https://example.com/v1"
    assert cfg.rename_chatgpt_model == "gpt-4o-mini"
    assert cfg.rename_format == "{name} S{season:02d}E{episode:02d} {fansub}"
    assert cfg.rename_enable is True
    assert cfg.rename_remap_cfg_path == "remap.yaml"

    assert cfg.bot_assistant_enable is False

    assert cfg.dev_log_level == "INFO"


def test_load_config_with_error():
    config_path = "tests/common/test_config_invalid.yaml"
    with pytest.raises(KeyError) as excinfo:
        ConfigManager(config_path)
    assert "alist.token is not found in config file" in str(excinfo.value)
