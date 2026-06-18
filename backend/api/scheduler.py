from fastapi import APIRouter, Depends, HTTPException, Cookie, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from backend.database.db import get_db
from backend.database.models import ScheduledJob, Student, Progress, Roadmap, HomeworkSubmission
import json

router = APIRouter(prefix="/api/schedule", tags=["scheduler"])

class ScheduleHomeworkRequest(BaseModel):
    topic: str
    scheduled_time: datetime

class ScheduleConfigRequest(BaseModel):
    homework_time: Optional[str] = None    # "HH:MM" 24h format
    homework_frequency: Optional[int] = None  # 0=off, 1=daily, 2=every 2 days, etc.

@router.get("")
def get_scheduled_jobs(
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    jobs = db.query(ScheduledJob)\
        .filter(ScheduledJob.student_id == int(student_id))\
        .order_by(ScheduledJob.scheduled_time.asc())\
        .all()
        
    return [
        {
            "id": job.id,
            "topic": job.topic,
            "scheduled_time": job.scheduled_time.isoformat(),
            "status": job.status,
            "created_at": job.created_at.isoformat()
        }
        for job in jobs
    ]

@router.post("")
async def schedule_homework_job(
    request: Request,
    payload: ScheduleHomeworkRequest,
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    student_id_int = int(student_id)
    scheduler_service = request.app.state.scheduler_service
    if not scheduler_service:
        raise HTTPException(status_code=500, detail="Scheduler service not initialized")
        
    if payload.scheduled_time <= datetime.now():
        raise HTTPException(status_code=400, detail="Scheduled time must be in the future")
        
    try:
        job_id = await scheduler_service.schedule_homework(
            student_id_int, payload.topic, payload.scheduled_time
        )
        
        from backend.database.models import ChatMessage
        msg = f"⏰ Đã thêm lịch bài tập chủ đề **{payload.topic}** vào danh sách hẹn giờ!"
        db.add(ChatMessage(student_id=student_id_int, sender="ai", message=msg))
        db.commit()
        
        return {"status": "success", "job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{job_id}")
def delete_scheduled_job(
    request: Request,
    job_id: int,
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
        
    student_id_int = int(student_id)
    job = db.query(ScheduledJob).filter(
        ScheduledJob.id == job_id,
        ScheduledJob.student_id == student_id_int
    ).first()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    # Cancel in APScheduler
    scheduler_service = request.app.state.scheduler_service
    if scheduler_service and job.apscheduler_job_id:
        try:
            scheduler_service.scheduler.remove_job(job.apscheduler_job_id)
        except Exception:
            pass
            
    job.status = "cancelled"
    db.commit()
    return {"status": "success", "message": "Job cancelled successfully"}


# ─── Schedule Config Endpoints ────────────────────────────────────────────────

@router.get("/config")
def get_schedule_config(
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    """Return current homework schedule config for the logged-in student."""
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    freq_labels = {0: "Tắt", 1: "Hàng ngày", 2: "Cách 1 ngày", 3: "Cách 2 ngày", 7: "Hàng tuần"}
    return {
        "homework_time": student.homework_time or "20:00",
        "homework_frequency": student.homework_frequency or 0,
        "homework_frequency_label": freq_labels.get(student.homework_frequency or 0, f"Mỗi {student.homework_frequency} ngày"),
        "is_active": (student.homework_frequency or 0) > 0
    }


@router.post("/config")
def save_schedule_config(
    payload: ScheduleConfigRequest,
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    """Save homework schedule config (time & frequency) for the logged-in student."""
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if payload.homework_time is not None:
        student.homework_time = payload.homework_time
    if payload.homework_frequency is not None:
        student.homework_frequency = int(payload.homework_frequency)

    db.commit()
    freq_labels = {0: "Tắt", 1: "Hàng ngày", 2: "Cách 1 ngày", 3: "Cách 2 ngày", 7: "Hàng tuần"}
    
    from backend.database.models import ChatMessage
    if payload.homework_frequency is not None:
        if payload.homework_frequency > 0:
            lbl = freq_labels.get(student.homework_frequency, f"Mỗi {student.homework_frequency} ngày")
            msg = f"🤖 **Đã bật lịch tự động giao bài!**\n⏰ Giờ giao bài: **{student.homework_time or '20:00'}**\n📅 Tần suất: **{lbl}**\n\nAI sẽ tự động lấy chủ đề tiếp theo trong lộ trình của bạn và gửi bài tập đúng giờ. Chúc bạn học tốt! 📚"
            db.add(ChatMessage(student_id=student.id, sender="ai", message=msg))
        else:
            db.add(ChatMessage(student_id=student.id, sender="ai", message="⏸ Đã tắt lịch giao bài tự động."))
        db.commit()

    return {
        "status": "success",
        "homework_time": student.homework_time,
        "homework_frequency": student.homework_frequency,
        "homework_frequency_label": freq_labels.get(student.homework_frequency, f"Mỗi {student.homework_frequency} ngày"),
        "is_active": student.homework_frequency > 0
    }


# ─── Roadmap Progress (score-weighted) ────────────────────────────────────────

@router.get("/progress")
def get_roadmap_progress(
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    """
    Return score-weighted roadmap progress.
    Each completed step contributes (score/10) to progress instead of binary 0/1.
    A step with score=8 out of 10 counts as 80% done for that step.
    """
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    student_id_int = int(student_id)
    roadmap = db.query(Roadmap).filter(
        Roadmap.student_id == student_id_int
    ).order_by(Roadmap.created_at.desc()).first()

    if not roadmap:
        return {"percent": 0, "completed_steps": 0, "total_steps": 0, "steps_detail": []}

    try:
        steps = json.loads(roadmap.content)
    except Exception:
        steps = []

    total_steps = len(steps)
    if total_steps == 0:
        return {"percent": 0, "completed_steps": 0, "total_steps": 0, "steps_detail": []}

    steps_detail = []
    weighted_sum = 0.0
    completed_count = 0

    for step in steps:
        title = step.get("title", "")
        progress = db.query(Progress).filter(
            Progress.student_id == student_id_int,
            Progress.topic == title
        ).first()

        status = progress.status if progress else "not_started"
        score = progress.score if (progress and progress.score is not None) else None
        attempt_count = progress.attempt_count if progress else 0

        # Weight: completed with score → score/10; completed without score → 1.0; others → 0
        if status == "completed":
            weight = (score / 10.0) if score is not None else 1.0
            completed_count += 1
        elif status == "in_progress":
            weight = (score / 20.0) if score is not None else 0.3  # half credit for in-progress
        else:
            weight = 0.0

        weighted_sum += weight
        steps_detail.append({
            "title": title,
            "status": status,
            "score": score,
            "attempt_count": attempt_count,
            "weight": round(weight, 2)
        })

    percent = round((weighted_sum / total_steps) * 100, 1)
    return {
        "percent": percent,
        "completed_steps": completed_count,
        "total_steps": total_steps,
        "steps_detail": steps_detail
    }
