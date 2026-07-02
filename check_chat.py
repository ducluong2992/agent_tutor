import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from backend.database.db import SessionLocal
from backend.database.models import ChatMessage

db = SessionLocal()
msgs = db.query(ChatMessage).order_by(ChatMessage.id.desc()).limit(5).all()
for m in msgs:
    print(f'ID={m.id} sender={m.sender} text={repr(m.message[:50])}')
db.close()
