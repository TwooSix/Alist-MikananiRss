from alist_mikananirss.common.config import ConfigManager


def test_full_config_example():
    config = ConfigManager()
    config.load_config("full_config.yaml.example")


def test_simple_config_example():
    config = ConfigManager()
    config.load_config("config.yaml.example")
