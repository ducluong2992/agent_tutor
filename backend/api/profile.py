from fastapi import APIRouter, Depends, HTTPException, Cookie
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from backend.database.db import get_db
from backend.database.models import Student

router = APIRouter(prefix="/api/profile", tags=["profile"])

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    learning_goals: Optional[str] = None
    skill_level: Optional[str] = None
    grade_level: Optional[int] = None
    homework_time: Optional[str] = None
    homework_frequency: Optional[int] = None

@router.get("")
def get_profile(student_id: Optional[str] = Cookie(None), db: Session = Depends(get_db)):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return {
        "id": student.id,
        "name": student.name,
        "email": student.email,
        "learning_goals": student.learning_goals,
        "skill_level": student.skill_level,
        "grade_level": student.grade_level,
        "homework_time": student.homework_time,
        "homework_frequency": student.homework_frequency,
        "linking_code": student.linking_code,
        "telegram_id": student.telegram_id,
        "theory_time": student.theory_time,
        "practice_time": student.practice_time,
        "exam_time": student.exam_time,
        "learning_frequency": student.learning_frequency
    }

@router.post("")
def update_profile(
    profile_data: ProfileUpdate,
    student_id: Optional[str] = Cookie(None),
    db: Session = Depends(get_db)
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
        
    if profile_data.name is not None:
        student.name = profile_data.name
    if profile_data.email is not None:
        student.email = profile_data.email
    if profile_data.learning_goals is not None:
        student.learning_goals = profile_data.learning_goals
    if profile_data.skill_level is not None:
        student.skill_level = profile_data.skill_level
    if profile_data.grade_level is not None:
        student.grade_level = profile_data.grade_level
    if profile_data.homework_time is not None:
        student.homework_time = profile_data.homework_time
    if profile_data.homework_frequency is not None:
        student.homework_frequency = profile_data.homework_frequency
        
    db.commit()
    return {"status": "success", "message": "Profile updated successfully"}
