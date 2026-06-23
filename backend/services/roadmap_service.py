import json
import logging
from typing import List, Dict, Any
import os
from sqlalchemy.orm import Session
from backend.database.models import Roadmap, Student, Document
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
        grade_level = student.grade_level if student.grade_level else "Không xác định"

        # Fetch uploaded documents for context
        documents = db.query(Document).filter(Document.student_id == student_id).all()
        doc_context = ""
        for doc in documents:
            if os.path.exists(doc.file_path):
                try:
                    with open(doc.file_path, "r", encoding="utf-8") as f:
                        text = f.read()
                        # Limit each doc to 5000 chars to avoid overwhelming context
                        doc_context += f"\n--- Tài liệu: {doc.filename} ---\n{text[:5000]}\n"
                except Exception as e:
                    logger.error(f"Failed to read document {doc.filename}: {e}")
        
        if not doc_context:
            doc_context = "Không có tài liệu nào được tải lên."

        # Ask LLM to generate a structured roadmap
        prompt = f"""
Bạn là một chuyên gia thiết kế chương trình học (Curriculum Designer) môn Toán.
Hãy tạo một lộ trình học tập chi tiết, đa dạng và cụ thể cho học viên với các thông tin sau:
- Môn học/Chủ đề (Subject): {subject}
- Trình độ hiện tại (Skill Level): {level}
- Lớp (Grade Level): {grade_level}
- Mục tiêu học tập (Learning Goals): {goals}

Tài liệu tham khảo (hãy bám sát nội dung tài liệu này để tạo lộ trình nếu có):
{doc_context}

Yêu cầu bắt buộc:
1. Lộ trình bao gồm nhiều Task, trong đó mỗi Task tương ứng với 1 Unit (Bài học). Hãy tạo ra từ 5 đến 10 Unit chi tiết.
2. Tiêu đề từng bài học (title) BẮT BUỘC phải theo định dạng "Unit 1: [Tiêu đề môn Toán]", "Unit 2: [Tiêu đề môn Toán]", v.v. (Ví dụ: "Unit 1: Phép cộng trừ", "Unit 2: Phân số").
3. Nội dung mô tả (description) ở dưới BẮT BUỘC viết bằng Tiếng Việt. Bạn phải ghi rõ rằng mỗi Unit sẽ bao gồm 3 phần độc lập:
   - Học lý thuyết
   - Bài tập vận dụng (5 câu): Trắc nghiệm, Tự luận giải toán
   - Kiểm tra (8 câu): Trắc nghiệm, Tự luận giải toán
4. Output MUST BE ONLY a raw JSON list of objects.

Mỗi step trong JSON list phải chứa các key sau:
1. "title": Tiêu đề bài học theo định dạng Unit X.
2. "description": Mô tả chi tiết nội dung (Tiếng Việt) và nhắc lại cấu trúc 3 phần.
3. "estimated_hours": Thời gian ước tính để hoàn thành (số nguyên, ví dụ: 2, 4).

Ví dụ định dạng đúng:
[
    {{"title": "Unit 1: Phép tính cơ bản", "description": "Học về các phép cộng trừ cơ bản.", "estimated_hours": 2}}
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
