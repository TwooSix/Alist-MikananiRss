import pytest
import yaml
from alist_mikananirss.common.config_loader import ConfigLoader


@pytest.fixture
def sample_config():
    return {
        "common": {
            "interval_time": 300,
            "proxies": {
                "http": "http://127.0.0.1:7890",
                "https": "http://127.0.0.1:7890",
            },
        },
        "alist": {
            "base_url": "http://www.example.com",
            "token": "alist-xxx",
            "downloader": "aria2",
            "download_path": "Onedrive/Anime",
        },
        "mikan": {
            "subscribe_url": [
                "https://mikanani.me/RSS/MyBangumi?token=xxx",
                "https://mikanani.me/RSS/rss2",
            ],
            "filters": ["1080p", "非合集"],
        },
    }


@pytest.fixture
def config_file(tmp_path, sample_config):
    config_file = tmp_path / "test_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(sample_config, f)
    return config_file


def test_load_config(config_file, sample_config):
    loader = ConfigLoader(str(config_file))
    assert loader.config == sample_config


def test_get_existing_key(config_file):
    loader = ConfigLoader(str(config_file))
    assert loader.get("common.interval_time") == 300
    assert loader.get("alist.base_url") == "http://www.example.com"
    assert loader.get("mikan.subscribe_url") == [
        "https://mikanani.me/RSS/MyBangumi?token=xxx",
        "https://mikanani.me/RSS/rss2",
    ]


def test_get_nested_key(config_file):
    loader = ConfigLoader(str(config_file))
    assert loader.get("common.proxies.http") == "http://127.0.0.1:7890"


def test_get_non_existent_key_with_default(config_file):
    loader = ConfigLoader(str(config_file))
    assert loader.get("non_existent_key", default="default_value") == "default_value"


def test_get_non_existent_key_without_default(config_file):
    loader = ConfigLoader(str(config_file))
    with pytest.raises(KeyError):
        loader.get("non_existent_key")


def test_get_partial_non_existent_key(config_file):
    loader = ConfigLoader(str(config_file))
    with pytest.raises(KeyError):
        loader.get("common.non_existent_key")
