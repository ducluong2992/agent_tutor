from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from backend.database.db import Base

class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String, unique=True, index=True, nullable=True)
    linking_code = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    grade_level = Column(Integer, nullable=True) # Lớp từ 1 đến 12
    learning_goals = Column(Text, nullable=True)
    skill_level = Column(String, default="Beginner")
    homework_time = Column(String, default="20:00")
    homework_frequency = Column(Integer, default=0)  # 0 = manual, 1 = daily, 2 = every 2 days, etc.
    theory_time = Column(String, nullable=True)
    practice_time = Column(String, nullable=True)
    exam_time = Column(String, nullable=True)
    learning_frequency = Column(String, nullable=True)
    # API configuration (stored per-user for dynamic key management)
    gemini_api_key = Column(String, nullable=True)
    openrouter_api_key = Column(String, nullable=True)
    openai_api_key = Column(String, nullable=True)
    preferred_core = Column(String, default="gemini")  # 'gemini' | 'openrouter' | 'openai'
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("ChatMessage", back_populates="student", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="student", cascade="all, delete-orphan")
    roadmaps = relationship("Roadmap", back_populates="student", cascade="all, delete-orphan")
    progress_records = relationship("Progress", back_populates="student", cascade="all, delete-orphan")
    scheduled_jobs = relationship("ScheduledJob", back_populates="student", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    sender = Column(String, nullable=False)  # 'user' or 'ai'
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="messages")

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # 'pdf', 'docx', 'txt'
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="documents")

class Roadmap(Base):
    __tablename__ = "roadmaps"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    subject = Column(String, nullable=False, default="Toán")
    content = Column(Text, nullable=False)  # JSON-serialized list of roadmap steps
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="roadmaps")

class Progress(Base):
    __tablename__ = "progress"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    topic = Column(String, nullable=False)
    status = Column(String, default="not_started")  # 'not_started', 'in_progress', 'completed'
    score = Column(Float, nullable=True)  # Best score achieved for this topic
    theory_completed = Column(Boolean, default=False)
    exercise_completed = Column(Boolean, default=False)
    scheduled_date = Column(String, nullable=True)
    attempt_count = Column(Integer, default=0)  # Number of homework attempts
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = relationship("Student", back_populates="progress_records")
    submissions = relationship("HomeworkSubmission", back_populates="progress", cascade="all, delete-orphan")


class HomeworkSubmission(Base):
    """Records each homework submission attempt with score and feedback."""
    __tablename__ = "homework_submissions"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    progress_id = Column(Integer, ForeignKey("progress.id", ondelete="CASCADE"), nullable=True)
    topic = Column(String, nullable=False)
    score = Column(Float, nullable=False)  # Score 0-10
    feedback = Column(Text, nullable=True)  # AI feedback
    submitted_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student")
    progress = relationship("Progress", back_populates="submissions")

class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    job_type = Column(String, nullable=False)  # 'homework', 'report'
    topic = Column(String, nullable=False)
    scheduled_time = Column(DateTime, nullable=False)
    status = Column(String, default="pending")  # 'pending', 'sent', 'cancelled'
    apscheduler_job_id = Column(String, nullable=True)
    is_auto = Column(Boolean, default=False)  # True = auto-generated from roadmap schedule
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="scheduled_jobs")
