import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    # Tat reload khi co Telegram bot de tranh 2 instance polling cung token
    use_reload = not bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    if not use_reload:
        print("[Telegram] reload=False vi co TELEGRAM_BOT_TOKEN (tranh conflict polling)")

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=use_reload)
