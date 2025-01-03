import pytest

from alist_mikananirss.common.config import ConfigManager


@pytest.fixture(autouse=True)
def clear_manager():
    ConfigManager._instances.pop(ConfigManager, None)


def test_load_config():
    config_path = "tests/common/test_config.yaml"
    cfg = ConfigManager(config_path).get_config()
    assert cfg.common_proxies is None
    assert cfg.rename_format == "{name} S{season:02d}E{episode:02d} {fansub}"
    assert cfg.notification_telegram_enable is True
    assert cfg.notification_pushplus_enable is False

def test_load_config_with_error():
    config_path = "tests/common/test_config2.yaml"
    with pytest.raises(KeyError) as excinfo:
        ConfigManager(config_path)
    assert "alist.token is not found in config file" in str(excinfo.value)
