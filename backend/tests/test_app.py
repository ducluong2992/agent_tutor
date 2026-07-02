import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.main import app
from backend.database.db import Base, get_db

# Create isolated test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./backend/storage/test_tutor.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

# Override dependency injection in FastAPI
app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    # Remove test db file
    if os.path.exists("./backend/storage/test_tutor.db"):
        try:
            os.remove("./backend/storage/test_tutor.db")
        except Exception:
            pass

client = TestClient(app)

def test_onboarding_register():
    response = client.post(
        "/onboarding",
        data={
            "action": "register",
            "name": "Test Student",
            "email": "test@student.com",
            "learning_goals": "Learn Python",
            "skill_level": "Beginner"
        },
        follow_redirects=False
    )
    assert response.status_code == 303
    assert "student_id" in response.headers.get("set-cookie", "")

def test_onboarding_login():
    # Pre-register
    client.post(
        "/onboarding",
        data={
            "action": "register",
            "name": "Test Student",
            "email": "test@student.com",
            "learning_goals": "Learn Python",
            "skill_level": "Beginner"
        }
    )
    
    # Login
    response = client.post(
        "/onboarding",
        data={
            "action": "login",
            "email": "test@student.com"
        },
        follow_redirects=False
    )
    assert response.status_code == 303
    assert "student_id" in response.headers.get("set-cookie", "")

def test_get_profile():
    # Register and set cookie automatically via TestClient session handling
    client.post(
        "/onboarding",
        data={
            "action": "register",
            "name": "Test Student",
            "email": "test@student.com",
            "learning_goals": "Learn Python",
            "skill_level": "Beginner"
        }
    )
    
    # Get profile
    profile_response = client.get("/api/profile")
    assert profile_response.status_code == 200
    data = profile_response.json()
    assert data["name"] == "Test Student"
    assert data["email"] == "test@student.com"
    assert data["skill_level"] == "Beginner"

def test_update_profile():
    # Register
    client.post(
        "/onboarding",
        data={
            "action": "register",
            "name": "Test Student",
            "email": "test@student.com",
            "learning_goals": "Learn Python",
            "skill_level": "Beginner"
        }
    )
    
    # Update profile
    update_response = client.post(
        "/api/profile",
        json={
            "name": "Updated Student",
            "learning_goals": "Advanced Python",
            "skill_level": "Intermediate"
        }
    )
    assert update_response.status_code == 200
    
    # Fetch again to verify updates
    profile_response = client.get("/api/profile")
    data = profile_response.json()
    assert data["name"] == "Updated Student"
    assert data["learning_goals"] == "Advanced Python"
    assert data["skill_level"] == "Intermediate"

def test_chat():
    # Register
    client.post(
        "/onboarding",
        data={
            "action": "register",
            "name": "Test Student",
            "email": "test@student.com",
            "learning_goals": "Learn Python",
            "skill_level": "Beginner"
        }
    )
    
    # Send chat message (tutor mock mode triggers automatically)
    chat_response = client.post(
        "/api/chat",
        json={"message": "hello tutor"}
    )
    assert chat_response.status_code == 200
    data = chat_response.json()
    assert "reply" in data
    assert "status" in data
    
    # Verify chat history is logged
    history_response = client.get("/api/chat/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 2  # user message and AI response
    assert history[0]["sender"] == "user"
    assert history[1]["sender"] == "ai"

def test_roadmap_generation():
    # Register
    client.post(
        "/onboarding",
        data={
            "action": "register",
            "name": "Test Student",
            "email": "test@student.com",
            "learning_goals": "Learn Python",
            "skill_level": "Beginner"
        }
    )
    
    # Generate roadmap
    roadmap_response = client.post(
        "/api/roadmap/generate",
        json={"subject": "Python Basics"}
    )
    assert roadmap_response.status_code == 200
    data = roadmap_response.json()
    assert data["status"] == "success"
    assert data["roadmap"]["subject"] == "Python Basics"
    assert len(data["roadmap"]["steps"]) > 0

    # Get enriched roadmap
    get_response = client.get("/api/roadmap")
    assert get_response.status_code == 200
    get_data = get_response.json()
    assert get_data["roadmap"]["subject"] == "Python Basics"
    assert len(get_data["steps"]) > 0
    assert get_data["steps"][0]["status"] == "not_started"

    # Toggle step completion
    first_step_title = get_data["steps"][0]["title"]
    toggle_response = client.post(
        "/api/roadmap/step/toggle",
        json={"topic": first_step_title, "completed": True}
    )
    assert toggle_response.status_code == 200
    assert toggle_response.json()["new_status"] == "completed"

    # Verify status changed
    get_response2 = client.get("/api/roadmap")
    get_data2 = get_response2.json()
    assert get_data2["steps"][0]["status"] == "completed"

def test_upload_txt():
    # Register/Login to get cookies
    client.post(
        "/onboarding",
        data={
            "action": "register",
            "name": "Test Student",
            "email": "test@student.com",
            "learning_goals": "Learn Python",
            "skill_level": "Beginner"
        }
    )

    # Upload txt file
    file_content = b"Day la tai lieu kiem tra text file."
    response = client.post(
        "/api/upload",
        files={"file": ("test_doc.txt", file_content, "text/plain")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["document"]["filename"] == "test_doc.txt"
    assert data["document"]["file_type"] == "txt"

def test_upload_pdf():
    # Register/Login
    client.post(
        "/onboarding",
        data={
            "action": "register",
            "name": "Test Student",
            "email": "test@student.com",
            "learning_goals": "Learn Python",
            "skill_level": "Beginner"
        }
    )

    # Create a dummy PDF with fitz
    import fitz
    from PIL import Image
    import io

    doc = fitz.open()
    # Page 1: Text only
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Day la trang 1 chua text.")

    # Page 2: Contains an image
    page2 = doc.new_page()
    img = Image.new('RGB', (100, 100), color='blue')
    img_io = io.BytesIO()
    img.save(img_io, format='PNG')
    img_bytes = img_io.getvalue()
    page2.insert_image(page2.rect, stream=img_bytes)

    pdf_bytes = doc.write()
    doc.close()

    # Upload PDF file
    response = client.post(
        "/api/upload",
        files={"file": ("test_doc.pdf", pdf_bytes, "application/pdf")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["document"]["filename"] == "test_doc.pdf"
    assert data["document"]["file_type"] == "pdf"
