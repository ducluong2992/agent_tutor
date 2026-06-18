import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from backend.telegram.handlers import handle_start, handle_message, handle_document

logger = logging.getLogger(__name__)

bot_app = None

async def start_bot():
    global bot_app
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not found in environment. Telegram bot will not start.")
        return
        
    try:
        # Build application
        bot_app = Application.builder().token(token).build()
        
        # Add handlers
        bot_app.add_handler(CommandHandler("start", handle_start))
        bot_app.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r"^/link\s+"), handle_start))
        bot_app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Initialize and start
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
        logger.info("Telegram Bot started and polling successfully.")
    except Exception as e:
        logger.error(f"Failed to start Telegram Bot: {e}")

async def stop_bot():
    global bot_app
    if bot_app:
        try:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
            logger.info("Telegram Bot stopped.")
        except Exception as e:
            logger.error(f"Error while stopping Telegram Bot: {e}")

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
