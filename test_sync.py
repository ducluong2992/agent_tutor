import os
import asyncio
from dotenv import load_dotenv

# Load env
load_dotenv()

from backend.database.db import SessionLocal
from backend.database.models import Student
from backend.telegram.bot import bot_app, start_bot, stop_bot, send_telegram_message

async def main():
    db = SessionLocal()
    students = db.query(Student).all()
    print(f"Total students: {len(students)}")
    for s in students:
        print(f"Student ID: {s.id}, Telegram ID: {s.telegram_id}, Linking Code: {s.linking_code}")
    
    # Try to send a message if there's a telegram_id
    test_target = next((s for s in students if s.telegram_id), None)
    if not test_target:
        print("No student with telegram_id found. Linking hasn't happened successfully!")
        db.close()
        return

    print(f"Testing Telegram send to {test_target.telegram_id}...")
    
    # Need to start bot momentarily to send message
    await start_bot()
    
    success = await send_telegram_message(test_target.telegram_id, "🔧 Test đồng bộ từ script debug.")
    if success:
        print("Telegram send SUCCESS!")
    else:
        print("Telegram send FAILED!")
        
    await stop_bot()
    db.close()

if __name__ == "__main__":
    asyncio.run(main())
