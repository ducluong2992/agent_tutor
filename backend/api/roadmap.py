import json
from fastapi import APIRouter, Depends, HTTPException, Cookie, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from backend.database.db import get_db
from backend.database.models import Roadmap, Progress

router = APIRouter(prefix="/api/roadmap", tags=["roadmap"])

class RoadmapGenerateRequest(BaseModel):
    subject: str

class StepToggleRequest(BaseModel):
    topic: str
    task_type: Optional[str] = None  # 'theory', 'exercise'
    completed: bool

@router.post("/generate")
async def generate_roadmap(
    request: Request,
    payload: RoadmapGenerateRequest,
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    student_id_int = int(student_id)
    roadmap_service = request.app.state.roadmap_service
    if not roadmap_service:
        raise HTTPException(status_code=500, detail="Roadmap service not initialized")
        
    try:
        roadmap = await roadmap_service.generate_roadmap(db, student_id_int, payload.subject)
        
        # Initialize progress records for each step
        steps = json.loads(roadmap.content)
        if not isinstance(steps, list):
            steps = []
        import datetime
        base_date = datetime.date.today() + datetime.timedelta(days=1)
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or "title" not in step:
                continue
            # Check if progress record already exists
            existing = db.query(Progress).filter(
                Progress.student_id == student_id_int,
                Progress.topic == step["title"]
            ).first()
            if not existing:
                progress = Progress(
                    student_id=student_id_int,
                    topic=step["title"],
                    status="not_started",
                    scheduled_date=(base_date + datetime.timedelta(days=index)).isoformat()
                )
                db.add(progress)
        db.commit()
        
        import backend.services.global_services as global_services
        if global_services.scheduler_service:
            import asyncio
            asyncio.create_task(global_services.scheduler_service.update_schedule(student_id_int))
        
        from backend.database.models import ChatMessage
        ai_msg = f"🗺️ **Lộ trình học tập môn {payload.subject} vừa được tạo!** Xem chi tiết ở cột bên phải.\n\n👉 **Bây giờ, hãy cùng thiết lập lịch học cho bạn nhé!**\n- Bạn muốn học theo chu kỳ nào (Ví dụ: Hằng ngày, cách 1 ngày, Thứ 2-4-6)?\n- Khung giờ học cụ thể cho mỗi phần trong ngày:\n  + Mấy giờ học lý thuyết?\n  + Mấy giờ làm bài tập vận dụng?\n  + Mấy giờ làm bài kiểm tra?"
        db.add(ChatMessage(student_id=student_id_int, sender="ai", message=ai_msg))
        db.commit()
        
        return {
            "status": "success",
            "roadmap": {
                "id": roadmap.id,
                "subject": roadmap.subject,
                "steps": steps
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("")
def get_roadmap(
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    student_id_int = int(student_id)
    roadmap = db.query(Roadmap)\
        .filter(Roadmap.student_id == student_id_int)\
        .order_by(Roadmap.created_at.desc())\
        .first()
        
    if not roadmap:
        return {"roadmap": None, "steps": []}
        
    try:
        steps = json.loads(roadmap.content)
        if not isinstance(steps, list):
            steps = []
    except Exception:
        steps = []
    
    # Enrich steps with progress
    enriched_steps = []
    for step in steps:
        if not isinstance(step, dict) or "title" not in step:
            continue
        progress = db.query(Progress).filter(
            Progress.student_id == student_id_int,
            Progress.topic == step["title"]
        ).first()
        
        status = progress.status if progress else "not_started"
        score = progress.score if progress else None
        theory_completed = progress.theory_completed if progress else False
        exercise_completed = progress.exercise_completed if progress else False
        scheduled_date = progress.scheduled_date if progress else None
        updated_at = progress.updated_at.isoformat() if progress and progress.updated_at else None
        
        enriched_steps.append({
            **step,
            "status": status,
            "score": score,
            "theory_completed": theory_completed,
            "exercise_completed": exercise_completed,
            "scheduled_date": scheduled_date,
            "updated_at": updated_at
        })
        
    return {
        "roadmap": {
            "id": roadmap.id,
            "subject": roadmap.subject,
            "created_at": roadmap.created_at.isoformat()
        },
        "steps": enriched_steps
    }

@router.post("/step/toggle")
def toggle_step(
    payload: StepToggleRequest,
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    student_id_int = int(student_id)
    progress = db.query(Progress).filter(
        Progress.student_id == student_id_int,
        Progress.topic == payload.topic
    ).first()
    
    if not progress:
        progress = Progress(
            student_id=student_id_int,
            topic=payload.topic,
            status="not_started"
        )
        db.add(progress)
        
    if payload.task_type == "theory":
        progress.theory_completed = payload.completed
    elif payload.task_type == "exercise":
        progress.exercise_completed = payload.completed
    else:
        new_status = "completed" if payload.completed else "not_started"
        progress.status = new_status
        
    db.commit()
    return {"status": "success", "topic": payload.topic}
