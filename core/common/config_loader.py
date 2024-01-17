# config_loader.py
import config
from core.alist.api import DownloaderType


def get_base_url():
    _base_url = getattr(config, "BASE_URL", None)
    assert _base_url, "Please set BASE_URL in config.py"
    return _base_url


def get_user_name():
    _user_name = getattr(config, "USER_NAME", None)
    assert _user_name, "Please set USER_NAME in config.py"
    return _user_name


def get_password():
    _password = getattr(config, "PASSWORD", None)
    assert _password, "Please set PASSWORD in config.py"
    return _password


def get_download_path():
    _download_path = getattr(config, "DOWNLOAD_PATH", None)
    assert _download_path, "Please set DOWNLOAD_PATH in config.py"
    return _download_path


def get_regex_pattern():
    return getattr(config, "REGEX_PATTERN", {})


def get_subscribe_url():
    _subscribe_url = getattr(config, "SUBSCRIBE_URL", None)
    assert _subscribe_url, "Please set SUBSCRIBE_URL in config.py"
    return _subscribe_url


def get_filters():
    return getattr(config, "FILTERS", [])


def get_downloader():
    downloader_str = getattr(config, "DOWNLOADER", None)
    assert downloader_str, "Please set DOWNLOADER in config.py"
    try:
        return DownloaderType(downloader_str)
    except ValueError:
        raise ValueError("DOWNLOADER must be 'aria' or 'qbit'")


def get_interval_time():
    return getattr(config, "INTERVAL_TIME", 0)


def get_use_proxy():
    return getattr(config, "USE_PROXY", False)


def get_proxies():
    return getattr(config, "PROXIES", None)


def get_telegram_notification():
    return getattr(config, "TELEGRAM_NOTIFICATION", False)


def get_bot_token():
    return getattr(config, "BOT_TOKEN", None)


def get_user_id():
    return getattr(config, "USER_ID", None)


def get_use_renamer():
    return getattr(config, "USE_RENAMER", False)


def get_chatgpt_api_key():
    api_key = getattr(config, "CHATGPT_API_KEY", None)
    assert api_key, "Please set CHATGPT_API_KEY in config.py"
    return api_key


def get_chatgpt_base_url():
    return getattr(config, "CHATGPT_BASE_URL", None)


def get_chatgpt_model():
    return getattr(config, "CHATGPT_MODEL", "gpt-3.5-turbo")


def get_debug_mode():
    return getattr(config, "DEBUG_MODE", False)
