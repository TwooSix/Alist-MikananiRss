"""Pure validation for user configuration."""

from __future__ import annotations

from openlist_ani.logger import FATAL_LEVEL, logger
from openlist_ani.application.settings import CoreSettings

from .models import BotConfig, UserConfig

_NOTIFICATION_REQUIREMENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "telegram": ("Telegram", ("bot_token", "user_id")),
    "pushplus": ("PushPlus", ("user_token",)),
    "wechat": ("WeChat", ("account_id", "token")),
    "feishu": ("Feishu", ("app_id", "app_secret")),
}


def validate_core_settings(settings: CoreSettings) -> None:
    """Validate compiled core settings without external side effects."""
    positive_values = {
        "rss interval": settings.rss_interval_seconds,
        "feed concurrency": settings.feed_concurrency,
        "metadata concurrency": settings.metadata_concurrency,
        "metadata batch size": settings.metadata_batch_size,
        "download concurrency": settings.download_concurrency,
        "notification concurrency": settings.notification_concurrency,
        "job lease": settings.job_lease_seconds,
        "job heartbeat": settings.job_heartbeat_seconds,
        "shutdown timeout": settings.shutdown_timeout_seconds,
    }
    invalid = [name for name, value in positive_values.items() if value <= 0]
    if invalid:
        raise ValueError(f"Core settings must be positive: {', '.join(invalid)}")
    if not settings.metadata_providers:
        raise ValueError("At least one metadata provider is required")
    if not settings.downloader.strip():
        raise ValueError("A download backend is required")
    if not settings.organizer.strip():
        raise ValueError("An organizer is required")
    if settings.job_heartbeat_seconds >= settings.job_lease_seconds:
        raise ValueError("Job heartbeat must be shorter than the job lease")


class ConfigValidator:
    """Validate config values without reading files or calling external systems."""

    def __init__(self, data: UserConfig, load_failed: bool = False) -> None:
        self._data = data
        self._load_failed = load_failed

    def validate(self) -> bool:
        if self._load_failed:
            return False

        errors: list[str] = []
        warnings: list[str] = []

        self._validate_core_config(errors)
        self._validate_metadata_dependencies(errors, warnings)
        self._validate_notification_config(errors, warnings)
        self._validate_assistant_config(errors, warnings)
        self._log_validation_results(errors, warnings)

        return not errors

    def _validate_core_config(self, errors: list[str]) -> None:
        if not self._data.rss.urls:
            errors.append("No RSS URLs configured. Please add RSS URLs in [rss] urls.")

        openlist = self._data.downloader.openlist
        # Direct Python users may still construct the deprecated v1 field; all
        # file-based configuration is migrated before reaching this point.
        if self._data.openlist.token and not openlist.token:
            openlist = self._data.openlist

        if not openlist.url:
            errors.append(
                "OpenList URL is not configured in [downloader.openlist] url."
            )

        if not openlist.token:
            errors.append(
                "OpenList token is not configured in [downloader.openlist] token. "
                "Authentication will fail without a valid token."
            )

    def _validate_metadata_dependencies(
        self, errors: list[str], warnings: list[str]
    ) -> None:
        from openlist_ani.assistant.harness.adapters import agent_adapter_names

        providers = self._data.metadata_provider_names()
        if self._data.metadata.ai_source and "ai" not in providers:
            warnings.append(
                "metadata.ai_source is configured but metadata.pipeline does not "
                "contain 'ai'; the source selection will be ignored."
            )

        # Compatibility for direct callers which still build v1 models.  A
        # migrated file never reaches this branch.
        if (
            not self._data.ai.sources
            and self._data.metadata_parser.provider == "llm"
            and not self._data.llm.openai_api_key
        ):
            errors.append(
                "The legacy metadata parser is 'llm' but [llm] "
                "openai_api_key is missing. Migrate to [ai.sources]."
            )

        available_agents = set(agent_adapter_names())
        for source_name, source in self._data.ai.sources.items():
            if source.type == "agent" and source.agent not in available_agents:
                available = ", ".join(sorted(available_agents)) or "<none>"
                errors.append(
                    f"ai.sources.{source_name} selects unknown agent "
                    f"'{source.agent}'. Available agents: {available}."
                )

    def _validate_notification_config(
        self, errors: list[str], warnings: list[str]
    ) -> None:
        if not self._data.notification.enabled:
            return

        if not self._data.notification.bots:
            errors.append(
                "Notification is enabled but no bots are configured. "
                "Please add bot entries in [[notification.bots]]."
            )
            return

        for i, bot_cfg in enumerate(self._data.notification.bots):
            if not bot_cfg.enabled:
                continue
            self._validate_notification_bot(i, bot_cfg, errors, warnings)

    def _validate_notification_bot(
        self,
        index: int,
        bot_cfg: BotConfig,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        bot_label = f"notification.bots[{index}] (type={bot_cfg.type})"

        requirement = _NOTIFICATION_REQUIREMENTS.get(bot_cfg.type)
        if requirement is None:
            warnings.append(f"{bot_label}: Unknown bot type '{bot_cfg.type}'.")
            return
        bot_name, required_keys = requirement
        hint = (
            " Run openlist-ani-wechat-login and copy the printed config."
            if bot_cfg.type == "wechat"
            else ""
        )
        for key in required_keys:
            if not bot_cfg.config.get(key):
                errors.append(
                    f"{bot_label}: '{key}' is required for {bot_name} bot.{hint}"
                )

        if bot_cfg.type == "wechat" and not (
            bot_cfg.config.get("chat_id") or bot_cfg.config.get("home_channel")
        ):
            errors.append(
                f"{bot_label}: 'home_channel' or 'chat_id' is required for "
                "WeChat notification. Run openlist-ani-wechat-login, send "
                "one message to the bot, and copy the printed config."
            )
        elif bot_cfg.type == "feishu" and not bot_cfg.config.get("receive_id"):
            warnings.append(
                f"{bot_label}: 'receive_id' is not set. Start the Feishu "
                "assistant and send /set-notify-home before notifications "
                "can be delivered."
            )

    def _validate_assistant_config(
        self, errors: list[str], warnings: list[str]
    ) -> None:
        if not self._data.assistant.enabled:
            return

        telegram_enabled = self._assistant_telegram_enabled()
        wechat_enabled = self._data.assistant.wechat.enabled
        feishu_enabled = self._data.assistant.feishu.enabled

        if not (telegram_enabled or wechat_enabled or feishu_enabled):
            errors.append(
                "Assistant is enabled but no frontend is configured. "
                "Enable [assistant.telegram], [assistant.wechat], or [assistant.feishu]."
            )
            return

        self._validate_telegram_assistant(telegram_enabled, errors)
        self._validate_wechat_assistant(wechat_enabled, errors)
        self._validate_feishu_assistant(feishu_enabled, errors)

    def _assistant_telegram_enabled(self) -> bool:
        return bool(
            self._data.assistant.telegram.enabled
            or self._data.assistant.telegram.bot_token
        )

    def _validate_telegram_assistant(self, enabled: bool, errors: list[str]) -> None:
        if not enabled:
            return
        telegram_cfg = self._data.assistant.telegram
        if not telegram_cfg.bot_token:
            errors.append(
                "Telegram assistant is enabled but bot_token is missing. "
                "Please set [assistant.telegram] bot_token."
            )
        if not telegram_cfg.allowed_users:
            errors.append(
                "Telegram assistant requires at least one allowed user. Set "
                "[assistant.telegram] allowed_users = [123456789]."
            )

    def _validate_wechat_assistant(self, enabled: bool, errors: list[str]) -> None:
        if not enabled:
            return
        wechat_cfg = self._data.assistant.wechat
        hint = "Run openlist-ani-wechat-login and copy the printed config."
        if not wechat_cfg.account_id:
            errors.append(
                f"WeChat assistant is enabled but account_id is missing. {hint}"
            )
        if not wechat_cfg.token:
            errors.append(f"WeChat assistant is enabled but token is missing. {hint}")
        if not wechat_cfg.home_channel:
            errors.append(
                f"WeChat assistant is enabled but home_channel is missing. {hint}"
            )
        if not wechat_cfg.allowed_users:
            errors.append(
                "WeChat assistant requires at least one allowed user. Set "
                '[assistant.wechat] allowed_users = ["user@im.wechat"].'
            )

    def _validate_feishu_assistant(self, enabled: bool, errors: list[str]) -> None:
        if not enabled:
            return
        feishu_cfg = self._data.assistant.feishu
        if not feishu_cfg.app_id:
            errors.append(
                "Feishu assistant is enabled but app_id is missing. "
                "Please set [assistant.feishu] app_id."
            )
        if not feishu_cfg.app_secret:
            errors.append(
                "Feishu assistant is enabled but app_secret is missing. "
                "Please set [assistant.feishu] app_secret."
            )
        if not feishu_cfg.allowed_users:
            errors.append(
                "Feishu assistant requires at least one allowed user. Set "
                '[assistant.feishu] allowed_users = ["ou_xxx"].'
            )

    def _log_validation_results(self, errors: list[str], warnings: list[str]) -> None:
        for warning in warnings:
            logger.warning(f"Config Warning: {warning}")
        for error in errors:
            logger.log(FATAL_LEVEL, f"Config Error: {error}")
