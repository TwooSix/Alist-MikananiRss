from alist_mikananirss.common.config import ConfigManager


def test_load_config():
    config_path = "tests/common/test_config.yaml"
    ConfigManager(config_path)
