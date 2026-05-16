import asyncio
import logging
import logging.handlers
from collections import deque
from datetime import datetime

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_INTERVAL, TARGET_URL
from checker import check_available_dates, screenshot_calendar, cleanup_screenshot

logger = logging.getLogger(__name__)

# In-memory log buffer for /logs command
_log_buffer: deque = deque(maxlen=200)


class _BufferHandler(logging.Handler):
    """Pushes formatted log records into _log_buffer."""
    def emit(self, record):
        try:
            _log_buffer.append(self.format(record))
        except Exception:
            pass


def setup_log_buffer():
    """Attach a memory handler to the root logger so /logs can read recent entries."""
    handler = _BufferHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)

# State
monitoring_task: asyncio.Task | None = None
is_monitoring = False
check_count = 0
error_count = 0
last_check_time: str = "—"
last_found_dates: set = set()  # avoid duplicate alerts


def format_dates_html(dates: list[dict]) -> str:
    """Format available dates for Telegram (HTML)."""
    lines = []
    current_month = ""
    for d in dates:
        if d["month"] != current_month:
            current_month = d["month"]
            lines.append(f"\n📅 <b>{current_month}</b>")
        day = d["day"]
        if d["link"]:
            lines.append(f"  • <a href='{d['link']}'>{day} число</a>")
        else:
            lines.append(f"  • {day} число")
    return "\n".join(lines)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 <b>Монитор записи на права — Gelsenkirchen</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Бот проверяет сайт Führerscheinstelle на свободные\n"
        "даты для <b>Ersterteilung/Erweiterung</b> прав.\n\n"
        "📋 <b>Команды:</b>\n"
        "/check — разовая проверка\n"
        "/calendar — 📸 скриншот календаря\n"
        "/monitor — запустить мониторинг\n"
        "/stop — остановить мониторинг\n"
        "/status — текущее состояние\n"
        "/info — как работает бот\n"
        "/logs — последние логи (отладка)\n\n"
        "💡 <i>Новые термины появляются ПН с 7:30</i>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ <b>Как работает бот:</b>\n\n"
        "1. Открывает сайт через headless-браузер\n"
        "2. Выбирает услугу «Ersterteilung/Erweiterung»\n"
        "3. Принимает Datenschutz, жмёт «Weiter»\n"
        "4. Сканирует календарь на свободные даты\n"
        "5. Если есть — присылает уведомление со ссылкой\n\n"
        "🔗 <b>Прямая ссылка для записи:</b>\n"
        "Когда бот находит свободную дату, он даёт ссылку\n"
        "которая ведёт на страницу выбора времени.\n"
        "Там нужно выбрать время и ввести данные.\n\n"
        "⚠️ <b>Ссылка работает ограниченное время!</b>\n"
        "Бронируйте сразу после уведомления.",
        parse_mode=ParseMode.HTML,
    )


async def _make_progress_updater(msg):
    """Create a progress callback that edits a Telegram message."""
    last_text = [None]

    async def _update(text):
        if text != last_text[0]:
            last_text[0] = text
            try:
                await msg.edit_text(text)
            except Exception:
                pass  # ignore edit errors (rate limits, same text, etc.)

    return _update


async def cmd_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📸 Запускаю браузер...")
    logger.info("[cmd] /calendar from user %s", update.effective_user.id)
    progress = await _make_progress_updater(msg)

    try:
        result = await screenshot_calendar(on_progress=progress)
    except Exception as e:
        logger.error("[cmd] /calendar crashed: %s", e, exc_info=True)
        await msg.edit_text(f"❌ Крах: {type(e).__name__}: {e}")
        return

    if result["error"]:
        logger.warning("[cmd] /calendar error: %s", result["error"])
        await msg.edit_text(f"❌ Ошибка скриншота:\n<code>{result['error']}</code>", parse_mode=ParseMode.HTML)
        return

    if not result["path"]:
        await msg.edit_text("❌ Скриншот не создан (path=None)")
        return

    try:
        await msg.edit_text("📤 Отправляю фото...")
        with open(result["path"], "rb") as photo:
            now = datetime.now().strftime('%d.%m.%Y %H:%M')
            await update.message.reply_photo(
                photo=photo,
                caption=f"📅 Календарь на {now}",
            )
        await msg.delete()
    except Exception as e:
        logger.error("[cmd] /calendar send photo error: %s", e, exc_info=True)
        await msg.edit_text(f"❌ Не удалось отправить фото:\n<code>{type(e).__name__}: {e}</code>", parse_mode=ParseMode.HTML)
    finally:
        cleanup_screenshot()


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔍 Запускаю проверку...")
    logger.info("[cmd] /check from user %s", update.effective_user.id)
    progress = await _make_progress_updater(msg)

    try:
        result = await check_available_dates(on_progress=progress)
    except Exception as e:
        logger.error("[cmd] /check crashed: %s", e, exc_info=True)
        await msg.edit_text(f"❌ Крах: {type(e).__name__}: {e}")
        return

    if result["error"]:
        await msg.edit_text(f"❌ Ошибка:\n<code>{result['error']}</code>", parse_mode=ParseMode.HTML)
    elif result["available_dates"]:
        dates_text = format_dates_html(result["available_dates"])
        await msg.edit_text(
            f"🟢 <b>ЕСТЬ СВОБОДНЫЕ ДАТЫ!</b>\n"
            f"{dates_text}\n\n"
            f"🔗 <a href='{TARGET_URL}'>Записаться сейчас</a>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    else:
        now = datetime.now().strftime('%H:%M:%S')
        await msg.edit_text(
            f"🔴 Свободных дат нет\n\n"
            f"⏰ Проверено: {now}\n"
            f"Используй /monitor для автоматической проверки"
        )


def _get_check_interval() -> int:
    """Smart interval: aggressive in the morning, normal during day, paused at night."""
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=Mon

    # Night 22:00-06:59 → skip (check every 30 min just in case)
    if hour >= 22 or hour < 7:
        return 1800

    # Mon 7:00-8:30 → every 60 sec (prime time for new slots)
    if weekday == 0 and 7 <= hour < 9:
        return 60

    # Weekday mornings 7:00-8:30 → every 90 sec (daily slots drop)
    if hour < 9:
        return 90

    # Normal daytime → use configured interval
    return CHECK_INTERVAL


async def monitor_loop(app: Application):
    global is_monitoring, check_count, error_count, last_check_time, last_found_dates
    chat_id = TELEGRAM_CHAT_ID

    while is_monitoring:
        try:
            result = await check_available_dates()
            check_count += 1
            last_check_time = datetime.now().strftime("%H:%M:%S")

            if result["available_dates"]:
                error_count = 0
                current_dates = {f"{d['day']}.{d['month']}" for d in result["available_dates"]}
                new_dates = current_dates - last_found_dates

                if new_dates:
                    last_found_dates = current_dates
                    dates_text = format_dates_html(result["available_dates"])
                    n = len(result["available_dates"])
                    now_str = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🚨🚨🚨 <b>ТЕРМИН НАЙДЕН!</b> 🚨🚨🚨\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"Найдено дат: <b>{n}</b>\n"
                            f"{dates_text}\n\n"
                            f"⏰ {now_str}\n\n"
                            f"👇 <b>ЗАПИСЫВАЙСЯ НЕМЕДЛЕННО:</b>\n"
                            f"🔗 <a href='{TARGET_URL}'>Открыть сайт записи</a>"
                        ),
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                    logger.info("ALERT SENT! %d dates (%d new)", n, len(new_dates))
                else:
                    logger.info("Same dates still available, no new alert")
            elif result["error"]:
                error_count += 1
                logger.warning("Check error (#%d): %s", error_count, result["error"])
                if error_count == 5:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ 5 ошибок подряд: {result['error']}",
                    )
            else:
                error_count = 0
                if last_found_dates:
                    last_found_dates.clear()
                logger.info("No dates [check #%d at %s]", check_count, last_check_time)

        except Exception as e:
            logger.error("Monitor error: %s", e, exc_info=True)

        interval = _get_check_interval()
        await asyncio.sleep(interval)


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
        f"✅ <b>Мониторинг запущен!</b>\n\n"
        f"⏱ Интервал: каждые {interval_min} мин\n"
        f"🎯 Услуга: Ersterteilung/Erweiterung\n"
        f"📍 Gelsenkirchen, Wildenbruchstr. 10\n\n"
        f"Пришлю уведомление как только появится дата.\n"
        f"Для остановки: /stop",
        parse_mode=ParseMode.HTML,
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
    interval = _get_check_interval() if is_monitoring else CHECK_INTERVAL
    now = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    hour = datetime.now().hour
    if hour >= 22 or hour < 7:
        mode = "🌙 Ночной (30 мин)"
    elif hour < 9:
        mode = "⚡ Утренний (60-90 сек)"
    else:
        mode = "☀️ Дневной (3 мин)"
    await update.message.reply_text(
        f"📊 <b>Статус бота</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Мониторинг: {state}\n"
        f"Режим: {mode}\n"
        f"Интервал: {interval} сек\n"
        f"Проверок: {check_count}\n"
        f"Ошибок подряд: {error_count}\n"
        f"Последняя: {last_check_time}\n"
        f"Время: {now}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent log entries for debugging."""
    logger.info("[cmd] /logs from user %s", update.effective_user.id)

    if _log_buffer:
        lines = list(_log_buffer)
        text = "\n".join(lines[-40:])  # last 40 lines
        if len(text) > 4000:
            text = text[-4000:]
        await update.message.reply_text(
            f"📋 <b>Последние логи ({len(lines)} всего):</b>\n\n<pre>{text}</pre>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text("📋 Логов пока нет")


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Suppress 409 Conflict errors during deploy transitions."""
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        logger.debug("Conflict (another instance), ignoring")
        return
    logger.error("Unhandled error: %s", context.error, exc_info=context.error)


BOT_COMMANDS = [
    BotCommand("check", "🔍 Разовая проверка"),
    BotCommand("calendar", "📸 Скриншот календаря"),
    BotCommand("monitor", "▶️ Запустить мониторинг"),
    BotCommand("stop", "⏹ Остановить мониторинг"),
    BotCommand("status", "📊 Текущее состояние"),
    BotCommand("logs", "📋 Последние логи"),
    BotCommand("info", "ℹ️ Как работает бот"),
]


def create_bot() -> Application:
    setup_log_buffer()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("calendar", cmd_calendar))
    app.add_handler(CommandHandler("monitor", cmd_monitor))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_error_handler(_error_handler)
    return app
