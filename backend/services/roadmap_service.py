import json
import logging
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from backend.database.models import Roadmap, Student
from backend.services.llm_service import LLMService

logger = logging.getLogger(__name__)

class RoadmapService:
    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    async def generate_roadmap(self, db: Session, student_id: int, subject: str) -> Roadmap:
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise ValueError("Student not found")

        goals = student.learning_goals or "General learning"
        level = student.skill_level or "Beginner"

        # Ask LLM to generate a structured roadmap
        prompt = f"""
Bạn là một chuyên gia thiết kế chương trình học (Curriculum Designer).
Hãy tạo một lộ trình học tập chi tiết, đa dạng và cụ thể cho học viên với các thông tin sau:
- Môn học/Chủ đề (Subject): {subject}
- Trình độ hiện tại (Skill Level): {level}
- Mục tiêu học tập (Learning Goals): {goals}

Yêu cầu bắt buộc:
1. KHÔNG sử dụng các tiêu đề chung chung kiểu như "Introduction to X", "Core Concepts of X", "Advanced X". 
2. PHẢI chia thành các bài học cụ thể, đi sâu vào từng khía cạnh của môn học (Ví dụ với Tiếng Anh lớp 1: "Bài 1: Làm quen bảng chữ cái tiếng Anh", "Bài 2: Chào hỏi cơ bản và giới thiệu bản thân", "Bài 3: Từ vựng về màu sắc và con vật", v.v.).
3. Tạo ra từ 5 đến 10 bước (steps) chi tiết và bám sát vào mục tiêu học tập.
4. Ngôn ngữ của lộ trình phải phù hợp với ngôn ngữ của môn học (ưu tiên Tiếng Việt nếu môn học bằng Tiếng Việt).
5. Output MUST BE ONLY a raw JSON list of objects.

Mỗi step trong JSON list phải chứa các key sau:
1. "title": Tiêu đề bài học ngắn gọn nhưng cụ thể.
2. "description": Mô tả chi tiết nội dung sẽ học trong bài này.
3. "estimated_hours": Thời gian ước tính để hoàn thành (số nguyên, ví dụ: 2, 4).

Ví dụ định dạng đúng:
[
    {{"title": "Làm quen với bảng chữ cái", "description": "Học cách phát âm và nhận diện 26 chữ cái tiếng Anh.", "estimated_hours": 2}}
]

Do not include any formatting, markdown wrappers (like ```json ... ```), or text other than the raw JSON list of objects.
"""
        try:
            response_text = await self.llm_service.generate_response(
                system_prompt="You are an expert curriculum designer. Respond only in raw JSON list format.",
                user_prompt=prompt
            )
            # Strip markdown code blocks if any
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text.split("```json", 1)[1]
            if response_text.endswith("```"):
                response_text = response_text.rsplit("```", 1)[0]
            response_text = response_text.strip()
            
            # Parse json to validate
            steps = json.loads(response_text)
            
            # Save to db
            roadmap = Roadmap(
                student_id=student_id,
                subject=subject,
                content=json.dumps(steps, ensure_ascii=False)
            )
            db.add(roadmap)
            db.commit()
            db.refresh(roadmap)
            return roadmap
        except Exception as e:
            logger.error(f"Failed to generate roadmap: {e}")
            # Generate fallback roadmap in case LLM fails
            fallback_steps = [
                {"title": f"Introduction to {subject}", "description": f"Learn the core fundamentals and concepts of {subject}.", "estimated_hours": 4},
                {"title": f"Intermediate {subject}", "description": f"Explore advanced topics, design patterns and tools related to {subject}.", "estimated_hours": 8},
                {"title": f"Hands-on Project", "description": f"Build a practical project to apply everything you've learned about {subject}.", "estimated_hours": 12}
            ]
            roadmap = Roadmap(
                student_id=student_id,
                subject=subject,
                content=json.dumps(fallback_steps, ensure_ascii=False)
            )
            db.add(roadmap)
            db.commit()
            db.refresh(roadmap)
            return roadmap
