from fastapi import APIRouter, Depends, HTTPException, Cookie, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from backend.database.db import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])

class ChatRequest(BaseModel):
    message: str

@router.post("")
async def send_message(
    request: Request,
    payload: ChatRequest,
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    
    tutor_service = request.app.state.tutor_service
    if not tutor_service:
        raise HTTPException(status_code=500, detail="Tutor service not initialized")
        
    try:
        reply, action = await tutor_service.handle_message(
            db, int(student_id), payload.message
        )
        return {
            "status": "success",
            "reply": reply,
            "action": action
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
def get_chat_history(
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    from backend.database.models import ChatMessage
    messages = db.query(ChatMessage)\
        .filter(ChatMessage.student_id == int(student_id))\
        .order_by(ChatMessage.created_at.asc())\
        .all()
        
    return [
        {
            "id": msg.id,
            "sender": msg.sender,
            "message": msg.message,
            "created_at": msg.created_at.isoformat()
        }
        for msg in messages
    ]

@router.delete("/history")
def delete_chat_history(
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    from backend.database.models import ChatMessage
    db.query(ChatMessage).filter(ChatMessage.student_id == int(student_id)).delete()
    db.commit()
    
    return {"status": "success", "message": "Chat history cleared"}
