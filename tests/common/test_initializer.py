import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from alist_mikananirss.bot import PushPlusBot, TelegramBot
from alist_mikananirss.common import initializer
from alist_mikananirss.core import RegexFilter, RssMonitor

# 模拟的YAML配置文件内容
MOCK_YAML_CONTENT = """
common:
  interval_time: 300
  proxies:
    http: https://127.0.0.1:7890
    https: https://127.0.0.1:7890

alist:
  base_url: https://www.example.com
  token: alist-xxx
  downloader: aria2
  download_path: Onedrive/Anime

mikan:
  subscribe_url: 
    - https://mikanani.me/RSS/MyBangumi?token=xxx
  regex_pattern:
    简体: "(简体|简中|简日|CHS)"
    1080p: "(X1080|1080P)"
  filters:
    - 1080p

notification:
  telegram:
    bot_token: your_token
    user_id: your_id
  pushplus: 
    token: xxxxx
  interval_time: 300

rename: 
  chatgpt: 
    api_key: sk-xxx
    base_url: https://example.com/v1
    model: gpt-3.5-turbo
  rename_format: "{name} S{season:02d}E{episode:02d}"

dev:
  log_level: INFO
"""


@pytest.fixture(scope="module")
def temp_config_file():
    config_path = "temp_config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(MOCK_YAML_CONTENT)
    yield config_path
    os.remove(config_path)


@pytest.fixture(autouse=True)
def setup_config(temp_config_file):
    initializer.read_config(temp_config_file)
    yield
    initializer.config_loader = None


def test_read_config(temp_config_file):
    initializer.read_config(temp_config_file)
    assert initializer.config_loader is not None


@patch("alist_mikananirss.common.initializer.logger")
def test_setup_logger(mock_logger):
    initializer.setup_logger()
    mock_logger.remove.assert_called_once()
    mock_logger.add.assert_called()


def test_setup_proxy():
    with patch.dict(os.environ, {}, clear=True):
        initializer.setup_proxy()
        assert os.environ.get("HTTP_PROXY") == "https://127.0.0.1:7890"
        assert os.environ.get("HTTPS_PROXY") == "https://127.0.0.1:7890"


@pytest.mark.asyncio
async def test_init_alist():
    with patch("alist_mikananirss.common.initializer.Alist") as MockAlist:
        mock_alist = MockAlist.return_value
        mock_alist.get_alist_ver = AsyncMock(return_value="3.29.0")
        result = await initializer.init_alist()
        assert isinstance(result, MagicMock)
        MockAlist.assert_called_once()


def test_init_extrator():
    with patch(
        "alist_mikananirss.common.initializer.ChatGPTExtractor"
    ) as MockChatGPTExtractor:
        initializer.init_extrator()
        MockChatGPTExtractor.assert_called_once_with(
            "sk-xxx", "https://example.com/v1", "gpt-3.5-turbo"
        )


def test_init_notification_bots():
    result = initializer.init_notification_bots()
    assert len(result) == 2
    assert isinstance(result[0].bot, TelegramBot)
    assert result[0].bot.bot_token == "your_token"
    assert result[0].bot.user_id == "your_id"
    assert isinstance(result[1].bot, PushPlusBot)
    assert result[1].bot.user_token == "xxxxx"
    assert result[1].bot.channel.value == "wechat"


def test_init_notification_sender():
    with patch(
        "alist_mikananirss.common.initializer.NotificationSender"
    ) as MockNotificationSender:
        initializer.init_notification_sender()
        MockNotificationSender.initialize.assert_called_once()


def test_init_resource_filter():
    result = initializer.init_resource_filter()
    assert isinstance(result, RegexFilter)
    assert len(result.patterns) == 1


def test_init_rss_monitor():
    regex_filter = RegexFilter()
    result = initializer.init_rss_monitor(regex_filter)
    assert isinstance(result, RssMonitor)
    assert result.interval_time == 300


def test_init_download_manager():
    with patch(
        "alist_mikananirss.common.initializer.DownloadManager"
    ) as MockDownloadManager:
        mock_alist = MagicMock()
        initializer.init_download_manager(mock_alist)
        MockDownloadManager.initialize.assert_called_once_with(
            mock_alist, "Onedrive/Anime", True, True
        )


def test_init_renamer():
    with patch("alist_mikananirss.common.initializer.AnimeRenamer") as MockAnimeRenamer:
        mock_alist = MagicMock()
        initializer.init_renamer(mock_alist)
        MockAnimeRenamer.initialize.assert_called_once_with(
            mock_alist, "{name} S{season:02d}E{episode:02d}"
        )


def test_missing_optional_configs(temp_config_file):
    yaml_without_optional = yaml.safe_load(MOCK_YAML_CONTENT)
    del yaml_without_optional["notification"]
    del yaml_without_optional["rename"]

    with open(temp_config_file, "w", encoding="utf-8") as f:
        yaml.dump(yaml_without_optional, f)

    initializer.read_config(temp_config_file)

    result = initializer.init_notification_bots()
    assert len(result) == 0

    with patch(
        "alist_mikananirss.common.initializer.DownloadManager"
    ) as MockDownloadManager:
        mock_alist = MagicMock()
        initializer.init_download_manager(mock_alist)
        MockDownloadManager.initialize.assert_called_once_with(
            mock_alist, "Onedrive/Anime", False, False
        )


@pytest.mark.asyncio
async def test_missing_required_configs(temp_config_file):
    yaml_without_required = yaml.safe_load(MOCK_YAML_CONTENT)
    del yaml_without_required["alist"]

    with open(temp_config_file, "w", encoding="utf-8") as f:
        yaml.dump(yaml_without_required, f)
    initializer.read_config(temp_config_file)

    with pytest.raises(KeyError):
        await initializer.init_alist()


def test_invalid_configs(temp_config_file):
    yaml_with_invalid = yaml.safe_load(MOCK_YAML_CONTENT)
    yaml_with_invalid["common"]["interval_time"] = -1

    with open(temp_config_file, "w", encoding="utf-8") as f:
        yaml.dump(yaml_with_invalid, f)

    initializer.read_config(temp_config_file)

    with pytest.raises(ValueError):
        initializer.init_rss_monitor(RegexFilter())
