"""
Assistant module - frontend-to-agent-harness bridge.

Architecture:
- Thin frontend layer (Telegram / Feishu / WeChat / CLI)
- External agent harness session (Pi / Claude Code / Codex)
- Standard Agent Skills executed through each harness's native tools

Entry point: `main()` is registered as `openlist-ani-assistant` console script.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openlist_ani.logger import (
    CONSOLE_LOG_FORMAT,
    FATAL_LEVEL,
    LOG_DIR,
    LOG_FORMAT,
    file_logging_enabled_from_env,
    logger,
)


def _configure_assistant_logger(
    *,
    is_cli: bool,
    level: str = "INFO",
    rotation: str = "00:00",
    retention: str = "1 week",
) -> None:
    """Configure assistant logs to match project logging format.

    Logs are written to file by default and console logging is enabled for
    remote messaging frontends.
    """
    logger.remove()

    if file_logging_enabled_from_env():
        LOG_DIR.mkdir(exist_ok=True)
        logger.add(
            LOG_DIR / "assistant_{time:YYYY-MM-DD}.log",
            rotation=rotation,
            retention=retention,
            level=level,
            encoding="utf-8",
            mode="a",
            format=LOG_FORMAT,
            backtrace=False,
            diagnose=False,
        )

    if not is_cli:
        logger.add(
            sys.stderr,
            level=level,
            format=CONSOLE_LOG_FORMAT,
            colorize=True,
            backtrace=False,
            diagnose=False,
        )


def _platform_frontends_enabled(assistant_cfg: Any) -> dict[str, bool]:
    return {
        "telegram": _telegram_frontend_enabled(assistant_cfg),
        "wechat": assistant_cfg.wechat.enabled,
        "feishu": assistant_cfg.feishu.enabled,
    }


def _enabled_frontend_names(assistant_cfg: Any) -> list[str]:
    return [
        name
        for name, enabled in _platform_frontends_enabled(assistant_cfg).items()
        if enabled
    ]


def _telegram_frontend_enabled(assistant_cfg: Any) -> bool:
    return bool(assistant_cfg.telegram.enabled or assistant_cfg.telegram.bot_token)


def _validate_frontend_config(assistant_cfg: Any) -> list[str]:
    if not assistant_cfg.enabled:
        return [
            "Assistant is disabled. Set [assistant] enabled = true before "
            "starting remote frontends."
        ]

    frontends_enabled = _platform_frontends_enabled(assistant_cfg)

    errors: list[str] = []
    if frontends_enabled["telegram"] and not assistant_cfg.telegram.bot_token:
        errors.append("Telegram assistant is enabled but bot_token is missing.")
    if frontends_enabled["telegram"] and not assistant_cfg.telegram.allowed_users:
        errors.append(
            "Telegram assistant requires at least one allowed user. Set "
            "[assistant.telegram] allowed_users = [123456789]."
        )

    if frontends_enabled["wechat"]:
        errors.extend(_validate_wechat_frontend_config(assistant_cfg.wechat))

    if frontends_enabled["feishu"]:
        errors.extend(_validate_feishu_frontend_config(assistant_cfg.feishu))

    if not any(frontends_enabled.values()):
        errors.append(
            "Assistant enabled but no frontend is configured. "
            "Enable [assistant.telegram], [assistant.wechat], or [assistant.feishu]."
        )

    return errors


def _validate_wechat_frontend_config(wechat_cfg: Any) -> list[str]:
    hint = "Run openlist-ani-wechat-login and copy the printed config."
    errors: list[str] = []
    if not wechat_cfg.account_id:
        errors.append(f"WeChat assistant is enabled but account_id is missing. {hint}")
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
    return errors


def _validate_feishu_frontend_config(feishu_cfg: Any) -> list[str]:
    errors: list[str] = []
    if not feishu_cfg.app_id:
        errors.append("Feishu assistant is enabled but app_id is missing.")
    if not feishu_cfg.app_secret:
        errors.append("Feishu assistant is enabled but app_secret is missing.")
    if not feishu_cfg.allowed_users:
        errors.append(
            "Feishu assistant requires at least one allowed user. Set "
            '[assistant.feishu] allowed_users = ["ou_xxx"].'
        )
    return errors


def _create_telegram_frontend(
    *,
    loop: Any,
    loop_factory: Callable[[], Any],
    assistant_cfg: Any,
) -> Any:
    from .frontend.telegram import TelegramFrontend

    bot_token = assistant_cfg.telegram.bot_token
    if not bot_token:
        raise ValueError("Telegram assistant is enabled but bot_token is missing.")
    return TelegramFrontend(
        loop,
        bot_token=bot_token,
        allowed_users=assistant_cfg.telegram.allowed_users,
        loop_factory=loop_factory,
    )


def _create_wechat_frontend(
    *, loop: Any, loop_factory: Callable[[], Any], assistant_cfg: Any
) -> Any:
    from .frontend.messaging import (
        AllOfAuthorizer,
        AllowedChatAuthorizer,
        AllowedUserAuthorizer,
        MessagingFrontend,
    )
    from openlist_ani.integrations.messaging.wechat_ilink import WechatIlinkMessenger

    wechat_cfg = assistant_cfg.wechat
    messenger = WechatIlinkMessenger(
        account_id=wechat_cfg.account_id,
        token=wechat_cfg.token,
        base_url=wechat_cfg.base_url,
        interactive_login=False,
    )
    return MessagingFrontend(
        platform="wechat",
        messenger=messenger,
        loop=loop,
        loop_factory=loop_factory,
        authorizer=AllOfAuthorizer(
            AllowedChatAuthorizer([wechat_cfg.home_channel]),
            AllowedUserAuthorizer(wechat_cfg.allowed_users),
        ),
        enable_notify_home_command=False,
    )


def _create_feishu_frontend(
    *, loop: Any, loop_factory: Callable[[], Any], assistant_cfg: Any
) -> Any:
    from .frontend.messaging import MessagingFrontend
    from openlist_ani.integrations.messaging.feishu import FeishuMessenger
    from openlist_ani.integrations.messaging.state_store import MessagingStateStore

    feishu_cfg = assistant_cfg.feishu
    state_store = MessagingStateStore(feishu_cfg.state_dir)
    messenger = FeishuMessenger(
        app_id=feishu_cfg.app_id,
        app_secret=feishu_cfg.app_secret,
        domain=feishu_cfg.domain,
        connection_mode=feishu_cfg.connection_mode,
        webhook_host=feishu_cfg.webhook_host,
        webhook_port=feishu_cfg.webhook_port,
        webhook_path=feishu_cfg.webhook_path,
        bot_open_id=feishu_cfg.bot_open_id,
        require_mention=feishu_cfg.require_mention,
        store=state_store,
    )
    return MessagingFrontend(
        platform="feishu",
        messenger=messenger,
        loop=loop,
        loop_factory=loop_factory,
        state_store=state_store,
        allowed_users=feishu_cfg.allowed_users,
    )


def _create_messaging_frontends(
    *,
    loop: Any,
    loop_factory: Callable[[], Any],
    assistant_cfg: Any,
) -> list[Any]:
    frontends = []
    if _telegram_frontend_enabled(assistant_cfg):
        frontends.append(
            _create_telegram_frontend(
                loop=loop,
                loop_factory=loop_factory,
                assistant_cfg=assistant_cfg,
            )
        )
    if assistant_cfg.wechat.enabled:
        frontends.append(
            _create_wechat_frontend(
                loop=loop,
                loop_factory=loop_factory,
                assistant_cfg=assistant_cfg,
            )
        )
    if assistant_cfg.feishu.enabled:
        frontends.append(
            _create_feishu_frontend(
                loop=loop,
                loop_factory=loop_factory,
                assistant_cfg=assistant_cfg,
            )
        )
    return frontends


def _ensure_valid_frontend_config(assistant_cfg: Any, *, is_cli: bool) -> None:
    if is_cli:
        return
    frontend_errors = _validate_frontend_config(assistant_cfg)
    if not frontend_errors:
        return
    for error in frontend_errors:
        logger.log(FATAL_LEVEL, error)
    raise SystemExit(1)


async def _prepare_agent_runtime(source: Any, config_path: Path) -> None:
    agent_name = "pi" if source is None or source.type == "api" else source.agent
    if agent_name != "pi":
        return
    from .harness.adapters import get_agent_adapter
    from .harness.pi_runtime import ensure_pi_shell

    configured_executable = (
        source.executable if source is not None and source.type == "agent" else ""
    )
    logger.info("Preparing the Pi agent runtime...")
    executable = await get_agent_adapter("pi").resolve_executable(
        configured_executable,
        config_path=config_path,
    )
    logger.info(f"Pi agent runtime is ready: {executable}")
    if sys.platform == "win32":
        logger.info("Preparing Pi's managed Git Bash runtime...")
        shell = await asyncio.to_thread(ensure_pi_shell, config_path=config_path)
        logger.info(f"Pi shell runtime is ready: {shell}")


async def _serve_frontends(*, cli_frontend: Any | None, frontends: list[Any]) -> None:
    if cli_frontend is not None:
        await cli_frontend.run()
        return
    await asyncio.gather(*(frontend.run() for frontend in frontends))


async def _shutdown_frontends(frontends: list[Any], loop: Any) -> None:
    logger.info("Shutting down assistant - cleaning up resources")
    for running_frontend in frontends:
        shutdown = getattr(running_frontend, "shutdown", None)
        if shutdown is not None:
            await shutdown()
    await loop.shutdown()


async def run() -> None:
    """Start the thin frontend-to-agent-harness bridge."""
    from .harness.cli import HarnessCLIFrontend
    from .harness.loop import HarnessLoop
    from .harness.runtime import create_harness_session
    from .builtin_skills import PLUGIN_ROOT, SKILLS_ROOT
    from .builtin_skills._migration import (
        migrate_legacy_copied_builtin_skills,
    )
    from openlist_ani.adapters.configuration import config

    if config.load_failed:
        logger.log(FATAL_LEVEL, "Configuration could not be parsed; exiting")
        raise SystemExit(1)

    assistant_cfg = config.assistant
    is_cli = "--cli" in sys.argv
    _ensure_valid_frontend_config(assistant_cfg, is_cli=is_cli)

    selected = config.data.resolve_assistant_source()
    source_name = selected[0] if selected else "builtin-pi"
    source = selected[1] if selected else None
    config_path = config.config_path

    await _prepare_agent_runtime(source, config_path)

    skills_dir = Path(assistant_cfg.skills_dir).expanduser()
    migrate_legacy_copied_builtin_skills(skills_dir, SKILLS_ROOT)

    def _build_loop() -> HarnessLoop:
        return HarnessLoop(
            lambda: create_harness_session(
                source,
                builtin_plugin_root=PLUGIN_ROOT,
                user_skills_root=skills_dir,
                config_path=config_path,
            )
        )

    loop = _build_loop()
    frontends: list[Any] = []
    cli_frontend: Any | None = None
    if is_cli:
        cli_frontend = HarnessCLIFrontend(loop)
    else:
        frontends = _create_messaging_frontends(
            loop=loop,
            loop_factory=_build_loop,
            assistant_cfg=assistant_cfg,
        )
        if not frontends:
            logger.log(
                FATAL_LEVEL,
                "Assistant enabled but no frontend is configured. "
                "Enable [assistant.telegram], [assistant.wechat], or [assistant.feishu].",
            )
            sys.exit(1)

    logger.info(
        f"Starting harness-backed assistant (source={source_name}); "
        f"frontends={_enabled_frontend_names(assistant_cfg)}"
    )
    try:
        await _serve_frontends(cli_frontend=cli_frontend, frontends=frontends)
    finally:
        await _shutdown_frontends(frontends, loop)


def main() -> None:
    """Console script entry point."""
    from openlist_ani.adapters.configuration import get_config

    is_cli = "--cli" in sys.argv

    # Suppress noisy third-party loggers (stdlib logging side)
    for noisy_logger in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    runtime_config = get_config()
    _configure_assistant_logger(
        is_cli=is_cli,
        level=runtime_config.log.level,
        rotation=runtime_config.log.rotation,
        retention=runtime_config.log.retention,
    )

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Assistant interrupted by user.")
    except Exception as exc:
        logger.opt(exception=True).log(FATAL_LEVEL, f"Assistant crashed: {exc}")
        raise
