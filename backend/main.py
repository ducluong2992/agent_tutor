import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Cookie, Response, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session
import hashlib
import random
from dotenv import load_dotenv

# Load environmental variables (.env chỉ cho Telegram và cấu hình tĩnh)
load_dotenv()

from backend.services.config_service import init_llm_config
init_llm_config()

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
from backend.telegram.bot import start_bot, stop_bot, should_run_telegram_bot

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
global_services.llm_service = llm_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start scheduler
    scheduler_service.start()
    
    # Start telegram bot in background if token is available
    bot_task = None
    if should_run_telegram_bot():
        await asyncio.sleep(0.5)  # cho worker cu giai phong polling khi reload
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
app.state.llm_service = llm_service
app.state.tutor_service = tutor_service
app.state.rag_service = rag_service
app.state.roadmap_service = roadmap_service
app.state.scheduler_service = scheduler_service

# Include Routers
from backend.api import chat, upload, roadmap, profile, scheduler, settings
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(roadmap.router)
app.include_router(profile.router)
app.include_router(scheduler.router)
app.include_router(settings.router)

# Static & Templates setup
os.makedirs("frontend/static", exist_ok=True)
os.makedirs("frontend/templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
_jinja_env = Environment(loader=FileSystemLoader("frontend/templates"), auto_reload=True)
templates = Jinja2Templates(env=_jinja_env)

# View Routes
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from fastapi.responses import FileResponse
    return FileResponse("frontend/static/images/home1.png")

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

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# Temporary in-memory storage for unverified accounts
pending_registrations = {}

@app.post("/onboarding")
async def post_onboarding(
    response: Response,
    action: str = Form(...),  # 'register' or 'login'
    name: str = Form(None),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    email = email.strip().lower()
    
    if action == "login":
        student = db.query(Student).filter(Student.email == email).first()
        if not student or student.password_hash != hash_password(password):
            return RedirectResponse(url="/onboarding?error=invalid_credentials", status_code=303)
            
        if not student.is_verified:
            return RedirectResponse(url=f"/verify-otp?email={email}", status_code=303)
            
        # Check if 360 review is completed
        if not student.age or not student.strengths_weaknesses:
            redirect = RedirectResponse(url="/360-review", status_code=303)
            redirect.set_cookie("student_id", str(student.id), max_age=30*24*60*60)
            return redirect
            
        redirect = RedirectResponse(url="/", status_code=303)
        redirect.set_cookie("student_id", str(student.id), max_age=30*24*60*60)
        return redirect
    else:  # register
        student = db.query(Student).filter(Student.email == email).first()
        if student:
            return RedirectResponse(url="/onboarding?error=email_exists", status_code=303)
            
        import random
        from backend.services.email_service import send_otp_email
        otp = str(random.randint(100000, 999999))
        
        # Save to memory instead of DB
        pending_registrations[email] = {
            "name": name or "Học sinh mới",
            "password_hash": hash_password(password),
            "otp_code": otp
        }
        
        # Send OTP via Email
        send_otp_email(email, otp)
        
        return RedirectResponse(url=f"/verify-otp?email={email}", status_code=303)

@app.get("/verify-otp", response_class=HTMLResponse)
async def get_verify_otp(request: Request, email: str = ""):
    return templates.TemplateResponse(request, "verify_otp.html", {"email": email})

@app.post("/verify-otp")
async def post_verify_otp(email: str = Form(...), otp: str = Form(...), db: Session = Depends(get_db)):
    if email in pending_registrations:
        data = pending_registrations[email]
        if data["otp_code"] == otp:
            import uuid
            linking_code = f"TUTOR-{uuid.uuid4().hex[:6].upper()}"
            
            new_student = Student(
                name=data["name"],
                email=email,
                linking_code=linking_code,
                password_hash=data["password_hash"],
                is_verified=True
            )
            db.add(new_student)
            db.commit()
            db.refresh(new_student)
            
            del pending_registrations[email]
            
            redirect = RedirectResponse(url="/360-review", status_code=303)
            redirect.set_cookie("student_id", str(new_student.id), max_age=30*24*60*60)
            return redirect

    # Legacy check for old registrations already in DB
    student = db.query(Student).filter(Student.email == email).first()
    if student and student.otp_code == otp:
        student.is_verified = True
        student.otp_code = None
        db.commit()
        redirect = RedirectResponse(url="/360-review", status_code=303)
        redirect.set_cookie("student_id", str(student.id), max_age=30*24*60*60)
        return redirect
        
    return RedirectResponse(url=f"/verify-otp?email={email}&error=invalid_otp", status_code=303)

@app.get("/360-review", response_class=HTMLResponse)
async def get_360_review(request: Request, student_id: str = Cookie(None), db: Session = Depends(get_db)):
    if not student_id:
        return RedirectResponse(url="/onboarding")
    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if not student:
        return RedirectResponse(url="/onboarding")
    return templates.TemplateResponse(request, "review_360.html", {"student": student})

@app.post("/360-review")
async def post_360_review(
    student_id: str = Cookie(None),
    name: str = Form(...),
    age: int = Form(...),
    grade_level: int = Form(...),
    learning_goals: str = Form(...),
    strengths_weaknesses: str = Form(...),
    skill_level: str = Form(...),
    db: Session = Depends(get_db)
):
    if not student_id:
        return RedirectResponse(url="/onboarding")
        
    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if student:
        student.name = name
        student.age = age
        student.grade_level = grade_level
        student.learning_goals = learning_goals
        student.strengths_weaknesses = strengths_weaknesses
        student.skill_level = skill_level
        db.commit()
        
    return RedirectResponse(url="/", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
async def get_settings_page(request: Request, student_id: str = Cookie(None), db: Session = Depends(get_db)):
    if not student_id:
        return RedirectResponse(url="/onboarding")
    student = db.query(Student).filter(Student.id == int(student_id)).first()
    if not student:
        return RedirectResponse(url="/onboarding")
    return templates.TemplateResponse(request, "settings.html", {"student": student})

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/onboarding")
    response.delete_cookie("student_id")
    return response
