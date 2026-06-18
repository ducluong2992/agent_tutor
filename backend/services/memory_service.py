import logging
from typing import List, Dict
from sqlalchemy.orm import Session
from backend.database.models import ChatMessage

logger = logging.getLogger(__name__)

class MemoryService:
    def __init__(self):
        pass

    def add_message(self, db: Session, student_id: int, sender: str, message: str) -> ChatMessage:
        db_msg = ChatMessage(
            student_id=student_id,
            sender=sender,
            message=message
        )
        db.add(db_msg)
        db.commit()
        db.refresh(db_msg)
        return db_msg

    def get_chat_history(self, db: Session, student_id: int, limit: int = 10) -> List[Dict[str, str]]:
        messages = db.query(ChatMessage)\
            .filter(ChatMessage.student_id == student_id)\
            .order_by(ChatMessage.created_at.desc())\
            .limit(limit)\
            .all()
        
        # We order them chronologically
        messages.reverse()
        
        return [
            {
                "role": "user" if msg.sender == "user" else "assistant",
                "content": msg.message
            }
            for msg in messages
        ]
