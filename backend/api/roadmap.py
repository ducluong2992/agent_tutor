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
        for step in steps:
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
                    status="not_started"
                )
                db.add(progress)
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
        
        enriched_steps.append({
            **step,
            "status": status,
            "score": score
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
    
    new_status = "completed" if payload.completed else "not_started"
    
    if progress:
        progress.status = new_status
    else:
        progress = Progress(
            student_id=student_id_int,
            topic=payload.topic,
            status=new_status
        )
        db.add(progress)
        
    db.commit()
    return {"status": "success", "topic": payload.topic, "new_status": new_status}
