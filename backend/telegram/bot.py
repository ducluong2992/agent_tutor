import os
import logging
import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.error import Conflict
from backend.telegram.handlers import handle_start, handle_message, handle_document

logger = logging.getLogger(__name__)

bot_app = None
_bot_starting = False


def should_run_telegram_bot() -> bool:
    """Chi chay bot trong worker process (tranh trung khi uvicorn --reload)."""
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        return False
    run_main = os.environ.get("RUN_MAIN")
    if run_main is not None:
        return run_main == "true"
    return True


async def start_bot():
    global bot_app, _bot_starting
    if _bot_starting or bot_app is not None:
        return

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not found in environment. Telegram bot will not start.")
        return

    _bot_starting = True
    try:
        bot_app = Application.builder().token(token).build()

        bot_app.add_handler(CommandHandler("start", handle_start))
        bot_app.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/link\s+"), handle_start))
        bot_app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram Bot started and polling successfully.")
        print("[Telegram] Bot da khoi dong va dang lang nghe tin nhan.")
    except Conflict:
        logger.error(
            "Telegram bot conflict: co instance khac dang polling cung token. "
            "Hay tat cac terminal python main.py cu, chi giu mot instance."
        )
        print(
            "[Telegram] LOI: Co bot khac dang chay cung token. "
            "Tat het cac terminal python main.py, roi chay lai mot lan."
        )
        await stop_bot()
    except Exception as e:
        logger.error(f"Failed to start Telegram Bot: {e}")
        await stop_bot()
    finally:
        _bot_starting = False


async def stop_bot():
    global bot_app, _bot_starting
    if not bot_app:
        return

    try:
        if bot_app.updater.running:
            await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        logger.info("Telegram Bot stopped.")
        print("[Telegram] Bot da dung.")
    except Exception as e:
        logger.error(f"Error while stopping Telegram Bot: {e}")
    finally:
        bot_app = None
        _bot_starting = False

async def send_telegram_message(telegram_id: str, text: str):
    global bot_app
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not bot_app:
        logger.warning("Telegram Bot not running or token missing. Cannot send message.")
        return False
        
    try:
        # Split message if it exceeds Telegram character limit of 4096
        chunks = []
        max_length = 4000
        temp_text = text
        while len(temp_text) > max_length:
            split_idx = temp_text.rfind('\n', 0, max_length)
            if split_idx == -1:
                split_idx = temp_text.rfind(' ', 0, max_length)
            if split_idx == -1:
                split_idx = max_length
            chunks.append(temp_text[:split_idx])
            temp_text = temp_text[split_idx:].lstrip()
        if temp_text:
            chunks.append(temp_text)

        for chunk in chunks:
            try:
                await bot_app.bot.send_message(chat_id=telegram_id, text=chunk, parse_mode="Markdown")
            except Exception as parse_err:
                logger.warning(f"Failed to parse Markdown for Telegram message to {telegram_id}: {parse_err}. Falling back to plain text.")
                await bot_app.bot.send_message(chat_id=telegram_id, text=chunk)
        return True
    except Exception as e:
        logger.error(f"Failed to send telegram message to {telegram_id}: {e}")
        return False
