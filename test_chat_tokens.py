import asyncio
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database.db import Base, get_db
from backend.services.tutor_service import TutorService
from backend.services.llm_service import LLMService

async def test_api():
    # Setup mock DB
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    # Mock student
    from backend.database.models import Student
    student = Student(id=1, name="Test", email="test@test.com")
    db.add(student)
    db.commit()

    llm = LLMService()
    tutor = TutorService(llm_service=llm)

    start_time = time.time()
    reply, action = await tutor.handle_message(db, 1, "xin chào")
    end_time = time.time()
    exec_time = round(end_time - start_time, 2)

    usage = getattr(llm, "last_token_usage", None)
    
    print("REPLY:", reply)
    print("EXEC TIME:", exec_time)
    print("TOKEN USAGE:", usage)

if __name__ == "__main__":
    asyncio.run(test_api())
