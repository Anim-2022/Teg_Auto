import asyncio
import logging
from datetime import datetime

from telegram.constants import ParseMode

from bot import create_bot
from config import TELEGRAM_CHAT_ID, CHECK_INTERVAL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

START_TIME = datetime.now().strftime("%d.%m.%Y %H:%M:%S")


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
        interval_min = CHECK_INTERVAL // 60
        await app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=(
                f"🔄 <b>Бот обновлён и перезапущен</b>\n\n"
                f"⏰ {START_TIME}\n"
                f"📡 Мониторинг активен (каждые {interval_min} мин)\n"
                f"🎯 Ersterteilung/Erweiterung"
            ),
            parse_mode=ParseMode.HTML,
        )


def main():
    logger.info("Starting Termin Monitor Bot...")
    app = create_bot()
    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
