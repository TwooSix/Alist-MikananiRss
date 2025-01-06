from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from alist_mikananirss import RssMonitor
from alist_mikananirss.websites import ResourceInfo


class BotAssistant:
    def __init__(self, token: str, rss_monitor: RssMonitor):
        """_summary_

        Args:
            token (str): Telegram Bot Token
            rss_monitor (RssMonitor): RssMonitor instance

        Example:
            bot_assistant = BotAssistant(cfg.bot_assistant_telegram_bot_token, rss_monitor)
            asyncio.create_task(bot_assistant.run())
        """
        self.app = Application.builder().token(token).build()
        self.rss_monitor = rss_monitor
        self._setup_handlers()

    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("download_rss", self._download_rss_command))

    async def _download_rss_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ):
        if not context.args:
            await update.message.reply_text("usage: /download_rss <rss_url>")
            return

        rss_url = context.args[0]
        try:
            await update.message.reply_text("分析 RSS 链接...")
            results: ResourceInfo = await self.rss_monitor.run_once_with_url(rss_url)
            if results:
                replymsg = "开始下载:\n" + "\n".join(
                    [r_info.resource_title for r_info in results]
                )
                await update.message.reply_text(replymsg)
            else:
                await update.message.reply_text("未能找到新的资源")
        except Exception as e:
            await update.message.reply_text(f"RSS 下载失败:\n{str(e)}")

    async def run(self):
        """Initialize and start the bot"""
        await self.app.initialize()
        await self.app.start()
        # Instead of run_polling(), we'll use update_queue
        await self.app.updater.start_polling()

    async def stop(self):
        """Stop the bot gracefully"""
        await self.app.updater.stop()
        await self.app.stop()
