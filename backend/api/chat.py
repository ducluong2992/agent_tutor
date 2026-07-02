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
        import time
        start_time = time.time()
        
        reply, action = await tutor_service.handle_message(
            db, int(student_id), payload.message
        )
        
        end_time = time.time()
        exec_time = round(end_time - start_time, 2)
        
        llm_service = request.app.state.llm_service
        token_usage = getattr(llm_service, "last_token_usage", None)
        
        return {
            "status": "success",
            "reply": reply,
            "action": action,
            "execution_time_seconds": exec_time,
            "token_usage": token_usage
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
    request: Request,
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    from backend.database.models import ChatMessage, Roadmap, Progress, HomeworkSubmission, ScheduledJob, Document
    import os
    
    sid = int(student_id)
    
    # Cancel all scheduled jobs in apscheduler before deleting from DB
    scheduler_service = request.app.state.scheduler_service
    if scheduler_service:
        jobs = db.query(ScheduledJob).filter(ScheduledJob.student_id == sid).all()
        for job in jobs:
            if job.apscheduler_job_id:
                try:
                    scheduler_service.scheduler.remove_job(job.apscheduler_job_id)
                except Exception:
                    pass
    
    # Delete physical document files
    docs = db.query(Document).filter(Document.student_id == sid).all()
    for doc in docs:
        try:
            if doc.file_path and os.path.exists(doc.file_path):
                os.remove(doc.file_path)
        except Exception:
            pass
    
    # Clear RAG vector store for this student
    rag_service = request.app.state.rag_service
    if rag_service:
        try:
            rag_service.clear_student_documents(sid)
        except Exception:
            pass
    
    db.query(ChatMessage).filter(ChatMessage.student_id == sid).delete()
    db.query(Roadmap).filter(Roadmap.student_id == sid).delete()
    db.query(Progress).filter(Progress.student_id == sid).delete()
    db.query(HomeworkSubmission).filter(HomeworkSubmission.student_id == sid).delete()
    db.query(ScheduledJob).filter(ScheduledJob.student_id == sid).delete()
    db.query(Document).filter(Document.student_id == sid).delete()
    
    # Delete the user as well
    from backend.database.models import Student
    db.query(Student).filter(Student.id == sid).delete()
    db.commit()
    
    return {"status": "success", "message": "All user data cleared"}

