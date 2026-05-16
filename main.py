import asyncio
import logging

from bot import create_bot, cmd_monitor
from config import TELEGRAM_CHAT_ID, CHECK_INTERVAL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


async def post_init(app):
    """Auto-start monitoring after bot launches (for deploy)."""
    if TELEGRAM_CHAT_ID:
        import bot as bot_module
        bot_module.is_monitoring = True
        bot_module.monitoring_task = asyncio.create_task(
            bot_module.monitor_loop(app)
        )
        logger.info(
            "Auto-started monitoring (chat_id=%s, interval=%ds)",
            TELEGRAM_CHAT_ID, CHECK_INTERVAL,
        )
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="🟢 Бот запущен, мониторинг активен!",
        )


def main():
    logger.info("Starting Termin Monitor Bot...")
    app = create_bot()
    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
