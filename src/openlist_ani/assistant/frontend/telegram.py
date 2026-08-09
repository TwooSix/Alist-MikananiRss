"""
Telegram frontend for the assistant.

Uses python-telegram-bot in polling mode.

Each Telegram chat (user or group) gets its own agent harness session so that
conversation histories are isolated by the selected agent runtime.

Interaction flow (mirrors CLI frontend):
1. User sends a message.
2. Thinking phase: bot sends a temporary status message and dynamically
   edits it to show spinner + tool execution progress.
3. Result phase: delete the temporary message, send the final AI
   response as a new message (MarkdownV2 with plain-text fallback).
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from types import SimpleNamespace

from openlist_ani.logger import logger

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message as TGMessage,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from openlist_ani.assistant.contracts import AssistantLoop, EventType, PendingMessage
from openlist_ani.assistant.frontend.base import Frontend
from openlist_ani.assistant.frontend.progress import narration_preview, progress_line
from openlist_ani.assistant.logging_format import format_log_text

# Telegram message length limit
MAX_MESSAGE_LENGTH = 4096

# Minimum interval between editMessageText calls (seconds).
# Telegram Bot API returns 429 if edits are too frequent.
_EDIT_DEBOUNCE_SECONDS = 1.0

# Interval between repeated sendChatAction(TYPING) calls (seconds).
# Telegram typing status expires after ~5 s; resend every 4 s to keep
# the indicator visible until the agent finishes its turn.
_TYPING_INTERVAL_SECONDS = 4.0

# Shared status text constants
_STATUS_THINKING = "⏳ 正在理解请求…"
_MAX_PROGRESS_LINES = 6
_UNAUTHORIZED_MESSAGE = "Unauthorized."

# ── MarkdownV2 escape ──────────────────────────────────────────────
# Characters that must be escaped in MarkdownV2:
# _ * [ ] ( ) ~ ` > # + - = | { } . !
_MDV2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def _escape_mdv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return _MDV2_ESCAPE_RE.sub(r"\\\1", text)


class TelegramFrontend(Frontend):
    """Telegram bot frontend for the assistant.

    Maintains a per-chat harness session so different users and groups never
    share agent context.
    """

    def __init__(
        self,
        loop: AssistantLoop,
        bot_token: str,
        allowed_users: list[int] | None = None,
        *,
        loop_factory: Callable[[], AssistantLoop] | None = None,
    ) -> None:
        super().__init__(loop)
        self._bot_token = bot_token
        self._allowed_users = set(allowed_users or [])
        self._app: Application | None = None

        # Per-sender bridges. Authorized users in the same group do not share
        # private Agent context with each other.
        self._chat_loops: dict[tuple[int, int], AssistantLoop] = {}

        # Factory callable to create new loops (set by __init__.py)
        # Falls back to returning the shared loop if no factory is set.
        self._loop_factory = loop_factory

        # Track active turns per sender session so concurrent messages
        # are enqueued instead of blocking on the lock.
        self._active_turns: set[tuple[int, int]] = set()
        self._pending_confirmations: set[tuple[int, int]] = set()

    def _get_loop(self, chat_id: int, user_id: int) -> AssistantLoop:
        """Get or create the harness bridge for a Telegram chat."""
        key = (chat_id, user_id)
        if key not in self._chat_loops:
            if self._loop_factory is not None:
                loop = self._loop_factory()
            else:
                # Fallback: use the single shared loop (CLI-style)
                loop = self._loop
            self._chat_loops[key] = loop

        return self._chat_loops[key]

    async def shutdown(self) -> None:
        """Close every per-chat agent harness created by this frontend."""
        loops = list(dict.fromkeys(self._chat_loops.values()))
        if self._loop not in loops:
            loops.append(self._loop)
        self._chat_loops.clear()
        await asyncio.gather(*(loop.shutdown() for loop in loops))

    async def run(self) -> None:
        """Start the Telegram bot in polling mode."""
        self._app = (
            Application.builder()
            .token(self._bot_token)
            .concurrent_updates(True)
            .build()
        )

        # Register handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("clear", self._cmd_clear))
        self._app.add_handler(CommandHandler("cancel", self._cmd_cancel))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("skill", self._cmd_skill))
        self._app.add_handler(
            CallbackQueryHandler(
                self._handle_confirmation,
                pattern=r"^oani:(confirm|cancel)$",
            )
        )
        # Catch-all for unrecognized /commands — handles skill invocations
        self._app.add_handler(
            MessageHandler(filters.COMMAND, self._handle_command_fallback)
        )
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text)
        )

        logger.info("Starting Telegram assistant bot...")
        await self._app.initialize()
        await self._app.start()
        await self._register_commands()
        await self._app.updater.start_polling(drop_pending_updates=True)

        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def _register_commands(self) -> None:
        """Register bot commands with Telegram for the command menu.

        When users type "/" in the chat, Telegram clients display a
        command menu with all registered commands and their descriptions.

        Agent Skills remain harness-native, so OAni registers only its own
        control commands instead of maintaining a second Skill index.
        """
        commands: list[BotCommand] = [
            BotCommand("help", "Show available commands"),
            BotCommand("clear", "Start a new session"),
            BotCommand("cancel", "Cancel the current request"),
            BotCommand("status", "Show session and queue status"),
            BotCommand("skill", "Use a named Agent Skill"),
        ]

        try:
            await self._app.bot.set_my_commands(commands)
            cmd_names = [c.command for c in commands]
            logger.info(f"Registered {len(commands)} bot commands: {cmd_names}")
        except Exception as e:
            logger.warning(f"Failed to register bot commands: {e}")

    async def send_response(self, text: str) -> None:
        """Not used directly — responses go through _handle_text."""
        pass

    def _is_authorized(self, user_id: int) -> bool:
        """Check if a user is authorized to use the bot."""
        return user_id in self._allowed_users

    async def _authorize_update(self, update: Update) -> bool:
        message = update.message
        user_id = message.from_user.id if message and message.from_user else 0
        if self._is_authorized(user_id):
            return True
        logger.warning("Telegram command rejected: unauthorized user")
        if message is not None:
            await message.reply_text(_UNAUTHORIZED_MESSAGE)
        return False

    # ── Debounced message editing ─────────────────────────────────

    async def _debounced_edit(
        self,
        msg: TGMessage,
        lines: list[str],
        state: dict,
    ) -> None:
        """Edit the status message with debounce to avoid Telegram 429.

        Args:
            msg: The Telegram message to edit.
            lines: Current status lines to join and display.
            state: Mutable dict holding ``last_edit_time`` and ``pending``.
        """
        now = time.monotonic()
        elapsed = now - state["last_edit_time"]
        text = "\n".join(lines)

        if elapsed >= _EDIT_DEBOUNCE_SECONDS:
            pending_task = state.get("pending_task")
            if pending_task is not None and not pending_task.done():
                pending_task.cancel()
            await self._safe_edit(msg, text)
            state["last_edit_time"] = time.monotonic()
            state["pending"] = False
        else:
            # Schedule the latest pending status. Without a timer, a long
            # running tool leaves Telegram showing the preceding generic
            # phase until that tool has already completed.
            state["pending"] = True
            state["pending_text"] = text
            pending_task = state.get("pending_task")
            if pending_task is None or pending_task.done():
                delay = max(0.0, _EDIT_DEBOUNCE_SECONDS - elapsed)
                state["pending_task"] = asyncio.create_task(
                    self._apply_pending_edit(msg, state, delay)
                )

    async def _apply_pending_edit(
        self,
        msg: TGMessage,
        state: dict,
        delay: float,
    ) -> None:
        try:
            await asyncio.sleep(delay)
            if state.get("pending") and state.get("pending_text"):
                await self._safe_edit(msg, state["pending_text"])
                state["pending"] = False
                state["last_edit_time"] = time.monotonic()
        finally:
            state["pending_task"] = None

    async def _flush_pending_edit(
        self,
        msg: TGMessage,
        state: dict,
    ) -> None:
        """Flush any pending edit that was deferred by debounce."""
        pending_task = state.get("pending_task")
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
            await asyncio.gather(pending_task, return_exceptions=True)
            state["pending_task"] = None
        if state.get("pending") and state.get("pending_text"):
            await self._safe_edit(msg, state["pending_text"])
            state["pending"] = False
            state["last_edit_time"] = time.monotonic()

    @staticmethod
    async def _safe_edit(msg: TGMessage, text: str) -> None:
        """Edit a message, silently ignoring errors (rate-limit, etc.)."""
        try:
            await msg.edit_text(text)
        except Exception as e:
            # Telegram may throw BadRequest if text hasn't changed,
            # or Flood control — either way, non-fatal.
            logger.debug(f"edit_text failed (non-fatal): {e}")

    # ── Send final result ─────────────────────────────────────────

    async def _send_chunked(
        self,
        update: Update,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Send a long message in chunks to respect Telegram limits.

        If *parse_mode* is set and sending fails (e.g. bad MarkdownV2),
        automatically falls back to plain text.
        """
        if not text:
            return

        chunks = self._split_text(text)

        for index, chunk in enumerate(chunks):
            markup = reply_markup if index == len(chunks) - 1 else None
            try:
                await update.message.reply_text(
                    chunk,
                    parse_mode=parse_mode,
                    reply_markup=markup,
                )
            except Exception:
                if parse_mode is not None:
                    # Fallback: send as plain text
                    logger.warning(
                        "Failed to send with parse_mode=%s, falling back to plain text",
                        parse_mode,
                    )
                    try:
                        await update.message.reply_text(chunk, reply_markup=markup)
                    except Exception as e2:
                        logger.error(f"Failed to send message chunk: {e2}")
                else:
                    logger.error("Failed to send message chunk")

    @staticmethod
    def _split_text(text: str) -> list[str]:
        """Split text into chunks that fit within Telegram limits."""
        chunks: list[str] = []
        while text:
            if len(text) <= MAX_MESSAGE_LENGTH:
                chunks.append(text)
                break
            # Find a good break point
            cut = text.rfind("\n", 0, MAX_MESSAGE_LENGTH)
            if cut == -1:
                cut = MAX_MESSAGE_LENGTH
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        return chunks

    # ── Main message handler ──────────────────────────────────────

    async def _handle_text(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle incoming text messages with real-time progress display.

        Flow:
        1. Validate the message and authorize the user.
        2. Delegate to _process_user_turn which handles the full
           thinking -> streaming -> result lifecycle.
        """
        if not update.message or not update.message.text:
            return

        user_id = update.message.from_user.id if update.message.from_user else 0
        authorized = self._is_authorized(user_id)
        if not authorized:
            logger.warning(
                "Telegram message rejected: unauthorized user "
                f"(chars={len(update.message.text)})"
            )
            logger.debug(
                f"Telegram authorization failed: chat_id={update.message.chat_id}, "
                f"user_id={user_id}"
            )
            await update.message.reply_text(_UNAUTHORIZED_MESSAGE)
            return

        logger.info(
            f"Telegram message received: {format_log_text(update.message.text)}"
        )
        await self._process_user_turn(update, update.message.text)

    async def _stream_events(
        self,
        loop: AssistantLoop,
        user_text: str,
        status_msg: TGMessage,
    ) -> tuple[list[str], bool]:
        """Process all streaming events from the harness bridge.

        Returns:
            List of final text parts collected from TEXT_DONE events.
        """
        lines: list[str] = [_STATUS_THINKING]
        edit_state: dict = {
            "last_edit_time": 0.0,
            "pending": False,
            "pending_text": "",
            "pending_task": None,
        }
        final_parts: list[str] = []
        stream_state = {
            "confirmation_required": False,
            "narration": "",
            "narration_active": False,
        }

        async for event in loop.process(user_text):
            await self._handle_stream_event(
                event,
                status_msg,
                lines,
                edit_state,
                final_parts,
                stream_state,
            )

        # Flush any pending edit before returning
        await self._flush_pending_edit(status_msg, edit_state)
        return final_parts, bool(stream_state["confirmation_required"])

    async def _handle_stream_event(
        self,
        event: object,
        status_msg: TGMessage,
        lines: list[str],
        edit_state: dict,
        final_parts: list[str],
        stream_state: dict,
    ) -> None:
        """Handle a single event from the harness bridge."""
        # DONE is authoritative. TEXT_DELTA also contains narration from
        # earlier tool-calling turns and must never be joined into the final.
        if event.type == EventType.DONE:
            if event.text:
                final_parts[:] = [event.text]
            return
        if event.type == EventType.CONFIRMATION_REQUIRED:
            stream_state["confirmation_required"] = True

        if event.type == EventType.TEXT_DELTA:
            await self._on_text_delta(
                event,
                status_msg,
                lines,
                edit_state,
                stream_state,
            )
            return
        if event.type == EventType.ERROR:
            await self._on_error(event, status_msg, lines, edit_state, final_parts)
            return
        if event.type in {
            EventType.THINKING,
            EventType.SKILL_SELECTED,
            EventType.SCRIPT_STARTED,
            EventType.SCRIPT_FINISHED,
            EventType.RETRYING,
            EventType.CONFIRMATION_REQUIRED,
        }:
            stream_state["narration"] = ""
            stream_state["narration_active"] = False
            self._append_progress_line(lines, progress_line(event))
            await self._debounced_edit(status_msg, lines, edit_state)

    async def _on_text_delta(
        self,
        event,
        status_msg,
        lines,
        edit_state,
        stream_state,
    ):
        stream_state["narration"] += event.text
        preview = narration_preview(stream_state["narration"])
        if not preview:
            return
        rendered = f"💭 {preview}"
        if stream_state["narration_active"] and lines:
            lines[-1] = rendered
        else:
            self._append_progress_line(lines, rendered)
            stream_state["narration_active"] = True
        await self._debounced_edit(status_msg, lines, edit_state)

    async def _on_error(self, event, status_msg, lines, edit_state, final_parts):
        self._append_progress_line(lines, f"❌ {event.text}")
        final_parts[:] = [f"Error: {event.text}"]
        await self._debounced_edit(status_msg, lines, edit_state)

    @staticmethod
    def _append_progress_line(lines: list[str], text: str) -> None:
        if lines == [_STATUS_THINKING]:
            lines.clear()
        if not lines or lines[-1] != text:
            lines.append(text)
        del lines[:-_MAX_PROGRESS_LINES]

    async def _send_final_result(
        self,
        update: Update,
        status_msg: TGMessage,
        final_parts: list[str],
        *,
        confirmation_required: bool,
        session_key: tuple[int, int],
    ) -> None:
        """Delete the status message and send the final result."""
        await self._cleanup_status_message(status_msg)

        full_response = "\n".join(final_parts)
        if full_response:
            escaped = _escape_mdv2(full_response)
            reply_markup = None
            if confirmation_required:
                self._pending_confirmations.add(session_key)
                reply_markup = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "✅ 确认执行", callback_data="oani:confirm"
                            ),
                            InlineKeyboardButton(
                                "❌ 取消", callback_data="oani:cancel"
                            ),
                        ]
                    ]
                )
            await self._send_chunked(
                update,
                escaped,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup,
            )
        else:
            await update.message.reply_text("No response.")

    @staticmethod
    async def _cleanup_status_message(status_msg: TGMessage) -> None:
        """Delete the temporary status message, ignoring errors."""
        try:
            await status_msg.delete()
        except Exception as e:
            logger.debug(f"Failed to delete status message: {e}")

    # ── Typing indicator ─────────────────────────────────────────

    def _start_typing_indicator(self, chat_id: int) -> asyncio.Task:
        """Start a background task that continuously sends TYPING action.

        Telegram's typing indicator expires after ~5 seconds, so this
        task resends it every ``_TYPING_INTERVAL_SECONDS`` until cancelled.

        Args:
            chat_id: The chat to show the typing indicator in.

        Returns:
            The background ``asyncio.Task`` — cancel it to stop.
        """

        async def _keep_typing() -> None:
            try:
                while True:
                    await self._app.bot.send_chat_action(
                        chat_id=chat_id,
                        action=ChatAction.TYPING,
                    )
                    await asyncio.sleep(_TYPING_INTERVAL_SECONDS)
            except Exception as e:  # noqa: BLE001
                if not isinstance(e, asyncio.CancelledError):
                    logger.debug(f"Typing indicator failed (non-fatal): {e}")
                raise

        return asyncio.create_task(_keep_typing())

    @staticmethod
    async def _stop_typing_indicator(task: asyncio.Task) -> None:
        """Cancel the typing indicator background task.

        Args:
            task: The task returned by :meth:`_start_typing_indicator`.
        """
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    # ── Command handlers ──────────────────────────────────────────

    async def _handle_command_fallback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Forward an unrecognized /command as a native Skill request."""
        if not update.message or not update.message.text:
            return

        user_id = update.message.from_user.id if update.message.from_user else 0
        authorized = self._is_authorized(user_id)
        if not authorized:
            logger.warning(
                "Telegram command rejected: unauthorized user "
                f"(chars={len(update.message.text)})"
            )
            logger.debug(
                f"Telegram authorization failed: chat_id={update.message.chat_id}, "
                f"user_id={user_id}"
            )
            await update.message.reply_text(_UNAUTHORIZED_MESSAGE)
            return

        text = update.message.text
        logger.info(f"Telegram command received: {format_log_text(text)}")
        # Parse: "/mikan search frieren" -> cmd_name="mikan", user_msg="search frieren"
        # Telegram may append @botname: "/mikan@mybot search frieren"
        parts = text.strip().split(None, 1)
        cmd_part = parts[0].lstrip("/").split("@")[0].lower() if parts else ""
        user_msg = parts[1] if len(parts) > 1 else ""

        skill_name = cmd_part.replace("_", "-")
        if not skill_name:
            return
        augmented = self._build_skill_message(
            skill_name=skill_name,
            user_message=user_msg,
        )
        await self._process_user_turn(update, augmented)

    async def _handle_confirmation(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        del context
        query = update.callback_query
        if query is None or query.message is None:
            return
        user_id = query.from_user.id if query.from_user else 0
        if not self._is_authorized(user_id):
            await query.answer(_UNAUTHORIZED_MESSAGE, show_alert=True)
            return
        session_key = (query.message.chat_id, user_id)
        if session_key not in self._pending_confirmations:
            await query.answer("该确认请求已失效。", show_alert=True)
            return

        self._pending_confirmations.discard(session_key)
        await query.edit_message_reply_markup(reply_markup=None)
        action = str(query.data or "")
        if action == "oani:cancel":
            await query.answer("已取消")
            await query.message.reply_text("已取消这次写操作。")
            return

        await query.answer("已确认，正在继续")
        await self._process_user_turn(
            SimpleNamespace(message=query.message),
            "I explicitly confirm the exact pending write operation described "
            "in your previous response. Continue it now and pass confirmed=true "
            "to the relevant Skill script.",
            user_id=user_id,
        )

    async def _cmd_skill(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle `/skill <name> [request]` without indexing Skill files."""
        del context
        if not update.message or not await self._authorize_update(update):
            return
        parts = update.message.text.strip().split(None, 2)
        if len(parts) < 2:
            await update.message.reply_text("Usage: /skill <name> [request]")
            return
        skill_name = parts[1].strip().lower().replace("_", "-")
        user_message = parts[2] if len(parts) > 2 else ""
        await self._process_user_turn(
            update,
            self._build_skill_message(skill_name, user_message),
        )

    async def _process_user_turn(
        self,
        update: Update,
        message_text: str,
        *,
        user_id: int | None = None,
    ) -> None:
        """Run a full thinking → streaming → result turn for a message.

        Shared by _handle_text and _handle_command_fallback to avoid
        duplicating the turn lifecycle (status message, streaming, cleanup).
        """
        chat_id = update.message.chat_id
        if user_id is None:
            user_id = update.message.from_user.id if update.message.from_user else 0
        session_key = (chat_id, user_id)
        loop = self._get_loop(chat_id, user_id)

        if session_key in self._active_turns:
            queued = loop.message_queue.enqueue(PendingMessage(content=message_text))
            logger.info(
                "Telegram message received while a reply is running; "
                f"queued for this conversation: {format_log_text(message_text)}"
            )
            logger.debug(
                f"Queued Telegram message: chat_id={chat_id}, "
                f"seq={queued.seq}, queue_len={len(loop.message_queue)}, "
                f"pending_prompts={loop.message_queue.pending_prompt_count()}"
            )
            await update.message.reply_text(
                f"请求已排队（#{queued.seq}），当前任务完成后会继续处理。"
            )
            return

        self._active_turns.add(session_key)
        try:
            pending_texts = [message_text]
            while pending_texts:
                current_text = pending_texts.pop(0)
                await self._process_single_turn(
                    update,
                    loop,
                    current_text,
                    session_key=session_key,
                )
                pending_texts.extend(
                    pending.content for pending in loop.message_queue.drain_prompts()
                )
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            await update.message.reply_text(f"Error: {e}")
        finally:
            self._active_turns.discard(session_key)

    async def _process_single_turn(
        self,
        update: Update,
        loop: AssistantLoop,
        message_text: str,
        *,
        session_key: tuple[int, int],
    ) -> None:
        chat_id = update.message.chat_id
        turn_started_at = time.monotonic()
        logger.debug(
            f"Telegram turn started: chat_id={chat_id}, chars={len(message_text)}, "
            f"active_turns={len(self._active_turns)}"
        )
        status_msg = await update.message.reply_text(_STATUS_THINKING)
        typing_task = self._start_typing_indicator(chat_id)
        try:
            final_parts, confirmation_required = await self._stream_events(
                loop, message_text, status_msg
            )
            await self._send_final_result(
                update,
                status_msg,
                final_parts,
                confirmation_required=confirmation_required,
                session_key=session_key,
            )
            final_chars = sum(len(part) for part in final_parts)
            elapsed_ms = int((time.monotonic() - turn_started_at) * 1000)
            logger.info("Telegram response sent.")
            logger.debug(
                f"Telegram response sent: chat_id={chat_id}, "
                f"final_parts={len(final_parts)}, final_chars={final_chars}, "
                f"elapsed_ms={elapsed_ms}"
            )
        except Exception:
            await self._cleanup_status_message(status_msg)
            raise
        finally:
            await self._stop_typing_indicator(typing_task)

    @staticmethod
    def _build_skill_message(
        skill_name: str,
        user_message: str,
    ) -> str:
        """Ask the harness to use its natively installed Skill."""
        parts = [
            f"Use the installed Agent Skill named '{skill_name}' for this request."
        ]
        if user_message:
            parts.extend(["", f"User request: {user_message}"])
        return "\n".join(parts)

    async def _cmd_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /start command."""
        if not await self._authorize_update(update):
            return
        lines = [
            "Hello! I'm your AI assistant. Send me a message to get started.\n",
            "Commands:",
            "/help - Show this help",
            "/clear - Start a new session",
            "/cancel - Cancel the current request",
            "/status - Show session status",
            "/<skill_name> [request] - Ask the Agent to use a Skill",
        ]

        await update.message.reply_text("\n".join(lines))

    async def _cmd_help(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /help command."""
        await self._cmd_start(update, context)

    async def _cmd_clear(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle /clear command — start a new session for this chat."""
        if not await self._authorize_update(update):
            return

        chat_id = update.message.chat_id
        user_id = update.message.from_user.id if update.message.from_user else 0
        loop = self._get_loop(chat_id, user_id)
        self._pending_confirmations.discard((chat_id, user_id))
        loop.reset()

        await update.message.reply_text("New session started.")

    async def _cmd_cancel(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._authorize_update(update):
            return
        user_id = update.message.from_user.id if update.message.from_user else 0
        loop = self._get_loop(update.message.chat_id, user_id)
        self._pending_confirmations.discard((update.message.chat_id, user_id))
        await loop.cancel()
        await update.message.reply_text("已取消当前请求并清空等待队列。")

    async def _cmd_status(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        if not await self._authorize_update(update):
            return
        user_id = update.message.from_user.id if update.message.from_user else 0
        loop = self._get_loop(update.message.chat_id, user_id)
        await update.message.reply_text(loop.status())
