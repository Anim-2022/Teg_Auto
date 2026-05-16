import asyncio
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_INTERVAL, TARGET_URL
from checker import check_available_dates

logger = logging.getLogger(__name__)

# State
monitoring_task: asyncio.Task | None = None
is_monitoring = False
check_count = 0
last_check_time: str = "—"


def format_dates(dates: list[dict]) -> str:
    """Format available dates for Telegram message."""
    lines = []
    current_month = ""
    for d in dates:
        if d["month"] != current_month:
            current_month = d["month"]
            lines.append(f"\n📅 *{current_month}*")
        day = d["day"]
        if d["link"]:
            lines.append(f"  • [{day} число]({d['link']})")
        else:
            lines.append(f"  • {day} число")
    return "\n".join(lines)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 *Монитор записи на права — Gelsenkirchen*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Бот проверяет сайт Führerscheinstelle на свободные\n"
        "даты для *Ersterteilung/Erweiterung* прав\\.\n\n"
        "📋 *Команды:*\n"
        "/check — разовая проверка\n"
        "/monitor — запустить мониторинг\n"
        "/stop — остановить мониторинг\n"
        "/status — текущее состояние\n"
        "/info — как работает бот\n\n"
        "💡 _Новые термины появляются ПН с 7:30_",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *Как работает бот:*\n\n"
        "1\\. Открывает сайт через headless\\-браузер\n"
        "2\\. Выбирает услугу «Ersterteilung/Erweiterung»\n"
        "3\\. Принимает Datenschutz, жмёт «Weiter»\n"
        "4\\. Сканирует календарь на свободные даты\n"
        "5\\. Если есть — присылает уведомление со ссылкой\n\n"
        "🔗 *Прямая ссылка для записи:*\n"
        "Когда бот находит свободную дату, он даёт ссылку\n"
        "которая ведёт на страницу выбора времени\\.\n"
        "Там нужно выбрать время и ввести данные\\.\n\n"
        "⚠️ *Ссылка работает ограниченное время\\!*\n"
        "Бронируйте сразу после уведомления\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Проверяю сайт...")

    result = await check_available_dates()

    if result["error"]:
        await msg.edit_text(f"❌ Ошибка: {result['error']}")
    elif result["available_dates"]:
        dates_text = format_dates(result["available_dates"])
        await msg.edit_text(
            f"🟢 *ЕСТЬ СВОБОДНЫЕ ДАТЫ\\!*\n"
            f"{dates_text}\n\n"
            f"🔗 [Записаться сейчас]({TARGET_URL})",
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
    else:
        await msg.edit_text(
            "🔴 Свободных дат нет\n\n"
            f"⏰ Проверено: {datetime.now().strftime('%H:%M:%S')}\n"
            "Используй /monitor для автоматической проверки"
        )


async def monitor_loop(app: Application):
    global is_monitoring, check_count, last_check_time
    chat_id = TELEGRAM_CHAT_ID

    while is_monitoring:
        try:
            result = await check_available_dates()
            check_count += 1
            last_check_time = datetime.now().strftime("%H:%M:%S")

            if result["available_dates"]:
                dates_text = format_dates(result["available_dates"])
                n = len(result["available_dates"])
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🚨🚨🚨 *ТЕРМИН НАЙДЕН\\!* 🚨🚨🚨\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"Найдено дат: *{n}*\n"
                        f"{dates_text}\n\n"
                        f"⏰ {datetime.now().strftime('%d\\.%m\\.%Y %H:%M:%S')}\n\n"
                        f"👇 *ЗАПИСЫВАЙСЯ НЕМЕДЛЕННО:*\n"
                        f"🔗 [Открыть сайт записи]({TARGET_URL})"
                    ),
                    parse_mode=ParseMode.MARKDOWN_V2,
                    disable_web_page_preview=True,
                )
                logger.info("ALERT SENT! %d dates found", n)
            elif result["error"]:
                logger.warning("Check error: %s", result["error"])
            else:
                logger.info("No dates [check #%d at %s]", check_count, last_check_time)

        except Exception as e:
            logger.error("Monitor error: %s", e, exc_info=True)

        await asyncio.sleep(CHECK_INTERVAL)


async def cmd_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring_task, is_monitoring, check_count

    if is_monitoring:
        await update.message.reply_text("⚡ Мониторинг уже запущен! /stop чтобы остановить")
        return

    # Use sender's chat_id if not configured
    if not TELEGRAM_CHAT_ID:
        import config
        config.TELEGRAM_CHAT_ID = str(update.effective_chat.id)

    is_monitoring = True
    check_count = 0
    monitoring_task = asyncio.create_task(monitor_loop(context.application))

    interval_min = CHECK_INTERVAL // 60
    await update.message.reply_text(
        f"✅ *Мониторинг запущен\\!*\n\n"
        f"⏱ Интервал: каждые {interval_min} мин\n"
        f"🎯 Услуга: Ersterteilung/Erweiterung\n"
        f"📍 Gelsenkirchen, Wildenbruchstr\\. 10\n\n"
        f"Пришлю уведомление как только появится дата\\.\n"
        f"Для остановки: /stop",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitoring_task, is_monitoring

    if not is_monitoring:
        await update.message.reply_text("ℹ️ Мониторинг не запущен. /monitor чтобы начать")
        return

    is_monitoring = False
    if monitoring_task:
        monitoring_task.cancel()
        monitoring_task = None

    await update.message.reply_text(
        f"⏹ Мониторинг остановлен\n"
        f"📊 Выполнено проверок: {check_count}"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = "🟢 Работает" if is_monitoring else "🔴 Остановлен"
    interval_min = CHECK_INTERVAL // 60
    await update.message.reply_text(
        f"📊 *Статус бота*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Мониторинг: {state}\n"
        f"Интервал: {interval_min} мин\n"
        f"Проверок: {check_count}\n"
        f"Последняя: {last_check_time}\n"
        f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
        parse_mode="Markdown",
    )


def create_bot() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("monitor", cmd_monitor))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("info", cmd_info))
    return app
