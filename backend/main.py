import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Cookie, Response, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from dotenv import load_dotenv

# Load environmental variables
load_dotenv()

# Import local modules
from backend.database.db import engine, Base, get_db
from backend.database.models import Student
from backend.services.llm_service import LLMService
from backend.services.memory_service import MemoryService
from backend.services.rag_service import RAGService
from backend.services.roadmap_service import RoadmapService
from backend.services.scheduler_service import SchedulerService
from backend.services.tutor_service import TutorService
import backend.services.global_services as global_services
from backend.telegram.bot import start_bot, stop_bot

# Create tables
Base.metadata.create_all(bind=engine)

# Initialize Services
llm_service = LLMService()
memory_service = MemoryService()
rag_service = RAGService()
roadmap_service = RoadmapService(llm_service)
scheduler_service = SchedulerService()
tutor_service = TutorService(llm_service, memory_service, rag_service, roadmap_service)

# Establish references
scheduler_service.set_tutor_service(tutor_service)
tutor_service.set_scheduler_service(scheduler_service)

global_services.tutor_service = tutor_service
global_services.rag_service = rag_service
global_services.roadmap_service = roadmap_service
global_services.scheduler_service = scheduler_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start scheduler
    scheduler_service.start()
    
    # Start telegram bot in background if token is available
    bot_task = None
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        bot_task = asyncio.create_task(start_bot())
        
    yield
    
    # Stop telegram bot
    await stop_bot()
    if bot_task:
        bot_task.cancel()
        
    # Stop scheduler
    scheduler_service.shutdown()

app = FastAPI(lifespan=lifespan, title="AI Tutor Platform MVP")

# Store in app state
app.state.tutor_service = tutor_service
app.state.rag_service = rag_service
app.state.roadmap_service = roadmap_service
app.state.scheduler_service = scheduler_service

# Include Routers
from backend.api import chat, upload, roadmap, profile, scheduler
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(roadmap.router)
app.include_router(profile.router)
app.include_router(scheduler.router)

# Static & Templates setup
os.makedirs("frontend/static", exist_ok=True)
os.makedirs("frontend/templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="frontend/templates")

# View Routes
@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request, student_id: str = Cookie(None), db: Session = Depends(get_db)):
    if not student_id:
        return RedirectResponse(url="/onboarding")
    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if not student:
        response = RedirectResponse(url="/onboarding")
        response.delete_cookie("student_id")
        return response
    
    from backend.database.models import Roadmap, Document, ScheduledJob
    latest_roadmap = db.query(Roadmap).filter(Roadmap.student_id == student.id).order_by(Roadmap.created_at.desc()).first()
    documents = db.query(Document).filter(Document.student_id == student.id).all()
    scheduled_jobs = db.query(ScheduledJob).filter(ScheduledJob.student_id == student.id).all()
    
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "student": student,
            "latest_roadmap": latest_roadmap,
            "documents": documents,
            "scheduled_jobs": scheduled_jobs
        }
    )

@app.get("/onboarding", response_class=HTMLResponse)
async def get_onboarding(request: Request, student_id: str = Cookie(None)):
    if student_id:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request, "onboarding.html")

@app.post("/onboarding")
async def post_onboarding(
    response: Response,
    action: str = Form(...),  # 'register' or 'login'
    name: str = Form(None),
    email: str = Form(...),
    learning_goals: str = Form(None),
    skill_level: str = Form(None),
    db: Session = Depends(get_db)
):
    email = email.strip().lower()
    
    if action == "login":
        student = db.query(Student).filter(Student.email == email).first()
        if not student:
            # If login email doesn't exist, create student
            import uuid
            linking_code = f"TUTOR-{uuid.uuid4().hex[:6].upper()}"
            student = Student(
                name=email.split("@")[0].capitalize(),
                email=email,
                linking_code=linking_code,
                learning_goals="Học tập tổng hợp",
                skill_level="Beginner"
            )
            db.add(student)
            db.commit()
            db.refresh(student)
    else:  # register
        student = db.query(Student).filter(Student.email == email).first()
        if student:
            # If exists, log them in
            pass
        else:
            import uuid
            linking_code = f"TUTOR-{uuid.uuid4().hex[:6].upper()}"
            student = Student(
                name=name or "Học sinh mới",
                email=email,
                linking_code=linking_code,
                learning_goals=learning_goals or "Học tập tổng hợp",
                skill_level=skill_level or "Beginner"
            )
            db.add(student)
            db.commit()
            db.refresh(student)
            
    # Set session cookie
    redirect = RedirectResponse(url="/", status_code=303)
    redirect.set_cookie("student_id", str(student.id), max_age=30*24*60*60)  # 30 days
    return redirect

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/onboarding")
    response.delete_cookie("student_id")
    return response
