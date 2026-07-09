import os
import re
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple
from sqlalchemy.orm import Session

from backend.database.models import Student, ChatMessage, Progress, HomeworkSubmission, Roadmap
from backend.services.llm_service import LLMService
from backend.services.memory_service import MemoryService
from backend.services.rag_service import RAGService
from backend.services.roadmap_service import RoadmapService

logger = logging.getLogger(__name__)

class TutorService:
    def __init__(
        self,
        llm_service: LLMService,
        memory_service: MemoryService,
        rag_service: RAGService,
        roadmap_service: RoadmapService,
        scheduler_service = None  # Set after to avoid circular import
    ):
        self.llm_service = llm_service
        self.memory_service = memory_service
        self.rag_service = rag_service
        self.roadmap_service = roadmap_service
        self.scheduler_service = scheduler_service

    def set_scheduler_service(self, scheduler_service):
        self.scheduler_service = scheduler_service

    async def handle_message(self, db: Session, student_id: int, message_content: str) -> Tuple[str, Dict[str, Any]]:
        # 1. Save user message
        self.memory_service.add_message(db, student_id, "user", message_content)

        # 2. Get student profile
        student = db.query(Student).filter(Student.id == student_id).first()
        student_name = student.name if student else "Học sinh"
        skill_level = student.skill_level if student else "Beginner"
        learning_goals = student.learning_goals if student else "General learning"
        grade_level = student.grade_level if student and student.grade_level else "Not specified"
        age = student.age if student and student.age else "Not specified"
        strengths_weaknesses = student.strengths_weaknesses if student and student.strengths_weaknesses else "Not specified"

        # 3. Retrieve RAG context if applicable
        rag_context = ""
        rag_results = self.rag_service.query_documents(student_id, message_content, limit=3)
        if rag_results:
            rag_context = "\n--- Context from uploaded documents ---\n"
            for res in rag_results:
                rag_context += f"Source: {res['filename']}\nContent: {res['content']}\n\n"
            rag_context += "---------------------------------------\n"

        # 4. Get chat history (last 10 messages)
        chat_history = self.memory_service.get_chat_history(db, student_id, limit=10)

        # 4.5. Fetch current roadmap topics and progress for prompt injection
        roadmap_topics_text = ""
        current_unit_text = "Chưa có lộ trình"
        roadmap_obj = db.query(Roadmap).filter(
            Roadmap.student_id == student_id
        ).order_by(Roadmap.created_at.desc()).first()
        if roadmap_obj:
            try:
                roadmap_steps = json.loads(roadmap_obj.content)
                all_progress = {p.topic: p for p in db.query(Progress).filter(
                    Progress.student_id == student_id
                ).all()}
                topic_lines = []
                current_topic = None
                for step in roadmap_steps:
                    title = step.get("title", "")
                    p = all_progress.get(title)
                    status = p.status if p else "not_started"
                    score_str = f" (điểm: {p.score}/10)" if p and p.score is not None else ""
                    topic_lines.append(f"  - {title} [{status}{score_str}]")
                    if not current_topic and status != "completed":
                        current_topic = title
                roadmap_topics_text = "\n".join(topic_lines)
                if current_topic:
                    current_unit_text = current_topic
            except Exception:
                pass

        # 5. Build system prompt
        homework_schedule_text = "Chưa cài đặt lịch tự động"
        if student and (student.homework_frequency or 0) > 0:
            freq = student.homework_frequency
            freq_map = {0: 'Tắt', 1: 'Hàng ngày', 2: 'Cách 1 ngày', 3: 'Cách 2 ngày', 7: 'Hàng tuần'}
            freq_text = freq_map.get(freq, f'mỗi {freq} ngày')
            homework_schedule_text = f"Giao bài lúc {student.homework_time}, tần suất: {freq_text}"

        system_prompt = f"""
You are an AI Math Tutor (Gia sư Toán học) for a student with the following profile:
- Name: {student_name}
- Age (Tuổi): {age}
- Current Level: {skill_level}
- Grade Level (Lớp): {grade_level}
- Learning Goals: {learning_goals}
- Strengths and Weaknesses (Điểm mạnh/yếu): {strengths_weaknesses}
- Auto Exam Schedule: {homework_schedule_text}
- Current Unit (bài đang học): {current_unit_text}

## ROADMAP TOPICS (danh sách bài học trong lộ trình — BẮT BUỘC dùng CHÍNH XÁC tên này):
{roadmap_topics_text if roadmap_topics_text else '  Chưa có lộ trình.'}

CRITICAL: When using actions (grade_exam, grade_homework, update_subtask, schedule_homework), the "topic" field MUST be the EXACT topic title from the roadmap list above. DO NOT invent or shorten topic names. Copy the exact string.

## Your Role
You are a dedicated, personalized Math tutor. You:
1. TEACH Math (theory, formulas, problem-solving methods, examples)
2. GIVE practice exercises (multiple choice, problem solving)
3. GRADE submitted answers and update roadmap progress
4. Support unlimited revision if the student asks to review or practice more

## Teaching Flow for Each Unit — 3 DISTINCT CONTENT TYPES:

### 1. LY THUYET (Theory — HOC SINH DOC VA GHI NHO, KHONG phai bai tap)
When a student asks for "ly thuyet" / "bai hoc" / "xem ly thuyet":
- Provide READING/LEARNING content, NOT exercises, NOT questions to answer
- Include: concepts, formulas, step-by-step example problem solving
- End with: "Hay doc va ghi nho phan ly thuyet nay. Khi san sang hay noi 'lam bai tap' de luyen tap!"
- Do NOT ask student to answer questions in theory phase

### 2. BAI TAP VAN DUNG (Practice — luyen tap, KHONG tinh diem lo trinh)
When a student asks for "bai tap" / "luyen tap" / "practice exercises":
- Provide 5 diverse math exercises.
- Instructions in Vietnamese, no answers yet
- When grading practice: use action "grade_homework" — does NOT update roadmap score

### 3. BAI KIEM TRA (Exam — tinh diem LO TRINH, mo khoa Unit tiep theo)
When a student says "kiem tra" / "thi" / "bai kiem tra" / when exam is sent by scheduler:
- Provide 8 math questions covering the full unit
- When grading: use action "grade_exam" — SAVES score to roadmap, unlocks next Unit if score >= 5

CRITICAL GRADING RULE:
- grade_exam: ONLY for official KIEM TRA → saves to roadmap
- grade_homework: for BAI TAP VAN DUNG or student self-initiated practice → does NOT touch roadmap

## Language Rules
- Always respond in Vietnamese
- IMPORTANT: DO NOT use LaTeX formatting like $$, \[, \], \(, or \) for math formulas. Use plain text and standard unicode characters instead (e.g. x^2, a/b, +, -, *, /, =).
- Format your reply beautifully using Markdown. Use proper line breaks (double newline \n\n) between paragraphs and use bullet points (-) for lists.
- Be warm, encouraging and natural — like a real human tutor

CRITICAL: You MUST respond ONLY as a valid JSON object. Do NOT wrap your response in markdown blocks like ```json ... ```. 
Your entire output MUST be parsable by json.loads().
Structure:
{{
  "reply": "Your full tutor response here using markdown for formatting.",
  "action": null or an action object
}}

## Supported Actions:

1. Schedule Homework (one-time):
{{
  "type": "schedule_homework",
  "params": {{
    "topic": "Unit 1: Phép tính cơ bản",
    "scheduled_time": "2026-06-20T20:00:00",
    "delay_minutes": 5,
    "job_type": "free_practice"
  }}
}}
NOTE: job_type can be "theory", "practice", "exam", or "free_practice". If student asks for exercises/practice freely, use "free_practice". 
Today's datetime is {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. 
CRITICAL: If the user says "sau X phút" (in X minutes), you MUST provide "delay_minutes": X. If they specify an exact time (like "lúc 20:00"), provide "scheduled_time": "YYYY-MM-DDTHH:MM:00". If no date/time given, schedule for tomorrow.

2. Generate Roadmap:
{{
  "type": "generate_roadmap",
  "params": {{
    "subject": "Toán"
  }}
}}

3. Update Profile / Auto Schedule:
{{
  "type": "update_profile",
  "params": {{
    "learning_goals": "...",
    "skill_level": "Beginner",
    "learning_frequency": "Hàng ngày",
    "theory_time": "19:00",
    "practice_time": "19:30",
    "exam_time": "20:00"
  }}
}}
NOTE: When student provides learning frequency and specific times for theory, practice, and exam, update them using this action. Only include changed params. IMPORTANT: Time MUST be in strictly 'HH:MM' 24-hour format (e.g. '09:59', '10:00', '14:30'). Do NOT use '9h59', '2h30'.

4. Grade EXAM (Bài KIỂM TRA — khi học sinh nộp bài kiểm tra chính thức):
Dùng action này KHI VÀ CHỈ KHI học sinh nộp bài KIỂM TRA (bài do scheduler gửi hoặc bài kiểm tra cuối unit).
Điểm này sẽ được LƯU VÀO LỘ TRÌNH và quyết định việc mở khóa Unit tiếp theo.
{{
  "type": "grade_exam",
  "params": {{
    "topic": "Unit 1: Phép tính cơ bản",
    "score": 8.5,
    "feedback": "Chi tiết phản hồi bằng tiếng Việt: những gì đúng, những gì cần cải thiện"
  }}
}}
NOTE: score is 0.0–10.0. If score >= 5: Unit is completed, student unlocks next Unit. If score < 5: Unit stays in_progress, student must retry.

5. Grade PRACTICE (Bài TẬP VẬN DỤNG hoặc bài tập tự phát):
Dùng action này khi học sinh làm bài TẬP VẬN DỤNG (practice) hoặc bài tập do học sinh tự yêu cầu.
Điểm này KHÔNG lưu vào lộ trình, chỉ là phản hồi luyện tập.
{{
  "type": "grade_homework",
  "params": {{
    "topic": "Unit 1: Phép tính cơ bản",
    "score": 8.5,
    "feedback": "Chi tiết phản hồi bằng tiếng Việt: những gì đúng, những gì cần cải thiện"
  }}
}}
NOTE: Điểm bài tập vận dụng chỉ dùng để khuyến khích học sinh, KHÔNG cập nhật trạng thái lộ trình.

6. Update Subtask (when student says they finished theory or exercises):
{{
  "type": "update_subtask",
  "params": {{
    "topic": "Unit 1: Phép tính cơ bản",
    "task_type": "theory",
    "completed": true
  }}
}}
NOTE: task_type = 'theory' or 'exercise'. Only use when student explicitly says they finished.
"""

        # Add RAG context to the user prompt
        user_prompt = f"{rag_context}Student Message: {message_content}"

        # 6. Call LLM
        response_text = await self.llm_service.generate_response(system_prompt, user_prompt, chat_history)

        # 7. Parse response
        reply = ""
        action = None
        
        clean_text = response_text.strip()
        
        # 1. Remove thinking block if present (common in DeepSeek and reasoning models)
        if "<think>" in clean_text and "</think>" in clean_text:
            parts = clean_text.split("</think>", 1)
            clean_text = parts[1].strip()
        elif "<think>" in clean_text:
            clean_text = clean_text.split("<think>", 1)[0].strip() or clean_text.split("<think>", 1)[1].strip()

        # 2. Clean markdown wrappers
        if clean_text.startswith("```json"):
            clean_text = clean_text.split("```json", 1)[1]
        elif clean_text.startswith("```"):
            clean_text = clean_text.split("```", 1)[1]
            
        if clean_text.endswith("```"):
            clean_text = clean_text.rsplit("```", 1)[0]
        clean_text = clean_text.strip()

        # 3. Find the first '{' and last '}' to parse JSON candidate
        start_idx = clean_text.find('{')
        end_idx = clean_text.rfind('}')
        
        parsed_successfully = False
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_candidate = clean_text[start_idx:end_idx+1]
            
            # Pre-process json_candidate to fix unescaped backslashes (e.g., LaTeX generated by mistake)
            json_candidate = re.sub(r'\\(?!["\\/bfnrt])', r'\\\\', json_candidate)
            
            try:
                data = json.loads(json_candidate)
                reply = data.get("reply", "")
                action = data.get("action", None)
                parsed_successfully = True
            except Exception as e:
                logger.warning(f"Standard JSON loads failed, attempting regex fallback: {e}")
                # Try regex repair: extract the "reply" string directly
                reply_match = re.search(r'"reply"\s*:\s*"(.*?)"(?=\s*,\s*"action"\s*:|\s*})', json_candidate, re.DOTALL)
                if reply_match:
                    reply_str = reply_match.group(1)
                    try:
                        # Decode escape sequences in string
                        reply = json.loads('"' + reply_str + '"')
                    except:
                        reply = reply_str
                    
                    # Try to parse the action field as well
                    action_match = re.search(r'"action"\s*:\s*(\{.*?\}|null)', json_candidate, re.DOTALL)
                    if action_match:
                        action_str = action_match.group(1)
                        if action_str != "null":
                            try:
                                action = json.loads(action_str)
                            except:
                                pass
                    parsed_successfully = True

        if not parsed_successfully:
            # Fallback: if it's not a JSON candidate, treat the whole clean_text as the reply
            if "{" not in clean_text:
                reply = response_text
            else:
                # Try basic regex extraction of reply
                reply_match = re.search(r'"reply"\s*:\s*"(.*?)"', clean_text, re.DOTALL)
                if reply_match:
                    reply_str = reply_match.group(1)
                    try:
                        reply = json.loads('"' + reply_str + '"')
                    except:
                        reply = reply_str
                else:
                    reply = response_text
            action = None

        # 8. Execute action if present
        executed_action_log = None
        if action and isinstance(action, dict):
            action_type = action.get("type")
            params = action.get("params", {})
            
            if action_type == "schedule_homework" and self.scheduler_service:
                topic = params.get("topic", "General review")
                
                # Parse scheduled time
                scheduled_time_str = params.get("scheduled_time")
                run_time = None
                
                # Check for delay_minutes first
                if "delay_minutes" in params:
                    try:
                        delay_mins = int(params["delay_minutes"])
                        run_time = datetime.now() + timedelta(minutes=delay_mins)
                    except (ValueError, TypeError):
                        pass
                
                if not run_time and scheduled_time_str:
                    try:
                        run_time = datetime.fromisoformat(scheduled_time_str)
                    except ValueError:
                        # Sometimes LLM outputs YYYY-MM-DD HH:MM:SS instead of ISO format
                        try:
                            run_time = datetime.strptime(scheduled_time_str, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass
                
                # Handling mock fallback parameter delay_seconds
                if not run_time and "delay_seconds" in params:
                    run_time = datetime.now() + timedelta(seconds=params["delay_seconds"])
                elif not run_time:
                    # Fallback to tomorrow
                    run_time = datetime.now() + timedelta(days=1)
                
                # Ensure it's in the future
                if run_time <= datetime.now():
                    run_time = datetime.now() + timedelta(minutes=1)
                
                job_type = params.get("job_type", "free_practice")
                job_id = await self.scheduler_service.schedule_homework(student_id, topic, run_time, job_type=job_type)
                executed_action_log = {"type": "schedule_homework", "job_id": job_id, "topic": topic, "time": run_time.isoformat(), "job_type": job_type}
                
                job_type_vn = "bài tập tự do" if job_type == "free_practice" else "bài tập vận dụng" if job_type == "practice" else "bài kiểm tra" if job_type == "exam" else "bài học lý thuyết"
                reply += f"\n\n⏰ **Đã lên lịch {job_type_vn}!** Chủ đề: *{topic}* vào lúc {run_time.strftime('%Y-%m-%d %H:%M:%S')}."
                
            elif action_type == "generate_roadmap":
                subject = params.get("subject", "General Subject")
                roadmap = await self.roadmap_service.generate_roadmap(db, student_id, subject)
                
                # Initialize progress records for each step
                steps = json.loads(roadmap.content)
                for step in steps:
                    existing = db.query(Progress).filter(
                        Progress.student_id == student_id,
                        Progress.topic == step["title"]
                    ).first()
                    if not existing:
                        progress = Progress(
                            student_id=student_id,
                            topic=step["title"],
                            status="not_started"
                        )
                        db.add(progress)
                db.commit()
                if self.scheduler_service:
                    await self.scheduler_service.update_schedule(student_id)
                
                executed_action_log = {"type": "generate_roadmap", "roadmap_id": roadmap.id, "subject": subject}
                reply += f"\n\n🗺️ **Lộ trình học {subject} đã được tạo thành công!** Bạn có thể xem chi tiết trong phần Dashboard.\n\n👉 **Bây giờ, hãy cùng thiết lập lịch học cho bạn nhé!**\n- Bạn muốn học theo chu kỳ nào (Ví dụ: Hằng ngày, cách 1 ngày, Thứ 2-4-6)?\n- Khung giờ học cụ thể cho mỗi phần trong ngày:\n  + Mấy giờ học lý thuyết?\n  + Mấy giờ làm bài tập vận dụng?\n  + Mấy giờ làm bài kiểm tra?"

            elif action_type == "update_profile":
                updated_fields = {}
                if "learning_goals" in params:
                    student.learning_goals = params["learning_goals"]
                    updated_fields["learning_goals"] = params["learning_goals"]
                if "skill_level" in params:
                    student.skill_level = params["skill_level"]
                    updated_fields["skill_level"] = params["skill_level"]
                if "grade_level" in params:
                    student.grade_level = params["grade_level"]
                    updated_fields["grade_level"] = params["grade_level"]
                if "name" in params:
                    student.name = params["name"]
                    updated_fields["name"] = params["name"]
                if "homework_time" in params:
                    student.homework_time = params["homework_time"]
                    updated_fields["homework_time"] = params["homework_time"]
                if "learning_frequency" in params:
                    student.learning_frequency = params["learning_frequency"]
                    updated_fields["learning_frequency"] = params["learning_frequency"]
                for t_field in ["theory_time", "practice_time", "exam_time"]:
                    if t_field in params:
                        val = str(params[t_field]).strip()
                        val = val.lower().replace('h', ':').replace('g', ':')
                        if ':' in val:
                            parts = val.split(':')
                            try:
                                h, m = int(parts[0]), int(parts[1])
                                val = f"{h:02d}:{m:02d}"
                            except ValueError:
                                pass
                        setattr(student, t_field, val)
                        updated_fields[t_field] = val
                db.commit()
                if self.scheduler_service:
                    await self.scheduler_service.update_schedule(student_id)
                executed_action_log = {"type": "update_profile", "updated": updated_fields}
                schedule_msg = ""
                if "learning_frequency" in updated_fields or "theory_time" in updated_fields:
                    freq_text = student.learning_frequency or "chưa rõ"
                    schedule_msg = f"\nLịch học của bạn: Tần suất **{freq_text}**.\n- Lý thuyết: {student.theory_time or 'chưa rõ'}\n- Bài tập: {student.practice_time or 'chưa rõ'}\n- Kiểm tra: {student.exam_time or 'chưa rõ'}"
                reply += f"\n\n⚙️ **Thông tin đã được cập nhật!**{schedule_msg}"

            elif action_type == "grade_exam":
                # ✅ KIỂM TRA CHÍNH THỨC — lưu điểm vào roadmap, quyết định mở khóa Unit tiếp theo
                topic = params.get("topic", "General review")
                score = float(params.get("score", 0.0))
                feedback = params.get("feedback", "")

                # Try exact match first, then ilike, then fuzzy fallback by "Bài X" prefix
                progress_record = db.query(Progress).filter(
                    Progress.student_id == student_id,
                    Progress.topic == topic
                ).first()

                if not progress_record:
                    progress_record = db.query(Progress).filter(
                        Progress.student_id == student_id,
                        Progress.topic.ilike(f"%{topic}%")
                    ).first()

                if not progress_record:
                    # Fuzzy fallback: extract "Bài X" or "Unit X" number and match
                    unit_match = re.search(r'(?:Bài|Unit|Chương)\s*(\d+)', topic, re.IGNORECASE)
                    if unit_match:
                        unit_num = unit_match.group(1)
                        all_progress = db.query(Progress).filter(
                            Progress.student_id == student_id
                        ).all()
                        for p in all_progress:
                            p_match = re.search(r'(?:Bài|Unit|Chương)\s*(\d+)', p.topic, re.IGNORECASE)
                            if p_match and p_match.group(1) == unit_num:
                                progress_record = p
                                logger.info(f"Fuzzy matched topic '{topic}' -> '{p.topic}'")
                                break

                if not progress_record:
                    # Last resort: match the first uncompleted topic in roadmap order
                    _roadmap = db.query(Roadmap).filter(
                        Roadmap.student_id == student_id
                    ).order_by(Roadmap.created_at.desc()).first()
                    if _roadmap:
                        try:
                            _steps = json.loads(_roadmap.content)
                            for _step in _steps:
                                _title = _step.get("title", "")
                                _pr = db.query(Progress).filter(
                                    Progress.student_id == student_id,
                                    Progress.topic == _title,
                                    Progress.status != "completed"
                                ).first()
                                if _pr:
                                    progress_record = _pr
                                    logger.info(f"Last-resort matched topic '{topic}' -> '{_pr.topic}'")
                                    break
                        except Exception:
                            pass

                if progress_record:
                    submission = HomeworkSubmission(
                        student_id=student_id,
                        progress_id=progress_record.id,
                        topic=progress_record.topic,
                        score=score,
                        feedback=feedback
                    )
                    db.add(submission)

                    progress_record.attempt_count = (progress_record.attempt_count or 0) + 1

                    # Keep best score
                    if progress_record.score is None or score > progress_record.score:
                        progress_record.score = score

                    # Update status based on score
                    if score >= 5.0:
                        progress_record.status = "completed"
                    else:
                        progress_record.status = "in_progress"

                    db.commit()
                    if self.scheduler_service:
                        await self.scheduler_service.update_schedule(student_id)
                    executed_action_log = {"type": "grade_exam", "topic": progress_record.topic, "score": score}

                    # Build score-weighted progress percentage
                    roadmap_obj = db.query(Roadmap).filter(
                        Roadmap.student_id == student_id
                    ).order_by(Roadmap.created_at.desc()).first()

                    progress_pct = 0
                    completed_in_roadmap = 0
                    total_steps = 0
                    if roadmap_obj:
                        try:
                            all_steps = json.loads(roadmap_obj.content)
                        except Exception:
                            all_steps = []
                        all_progress = {p.topic: p for p in db.query(Progress).filter(
                            Progress.student_id == student_id
                        ).all()}
                        weighted_sum = 0.0
                        total_steps = len(all_steps)
                        for s in all_steps:
                            p = all_progress.get(s.get("title", ""))
                            if p and p.status == "completed":
                                completed_in_roadmap += 1
                                w = (p.score / 10.0) if p.score is not None else 1.0
                                weighted_sum += w
                            elif p and p.status == "in_progress":
                                w = (p.score / 20.0) if p.score is not None else 0.3
                                weighted_sum += w
                        if total_steps > 0:
                            progress_pct = round((weighted_sum / total_steps) * 100, 1)

                        is_milestone = total_steps > 0 and (
                            (completed_in_roadmap % 3 == 0) or (completed_in_roadmap == total_steps)
                        )
                        if is_milestone and completed_in_roadmap > 0 and score >= 5.0:
                            milestone_report = await self.generate_milestone_report(
                                db, student_id, progress_record.topic, completed_in_roadmap, total_steps
                            )
                            reply += f"\n\n{milestone_report}"

                    score_bar = "🟩" * int(score) + "⬜" * (10 - int(score))
                    status_text = "✅ Hoàn thành — Mở khóa Unit tiếp theo!" if score >= 5.0 else "🔄 Chưa đạt (< 5 điểm) — Cần ôn lại và kiểm tra lại"
                    reply += f"\n\n📋 **KẾT QUẢ KIỂM TRA:** {score}/10 {score_bar}\n**Chủ đề:** {progress_record.topic}\n**Trạng thái:** {status_text}\n**Tiến độ lộ trình:** {progress_pct}%\n\n💬 *Nhận xét:* {feedback}"
                else:
                    # Kiểm tra không tìm thấy trong roadmap — vẫn ghi nhận
                    submission = HomeworkSubmission(
                        student_id=student_id,
                        progress_id=None,
                        topic=topic,
                        score=score,
                        feedback=feedback
                    )
                    db.add(submission)
                    db.commit()
                    executed_action_log = {"type": "grade_exam", "topic": topic, "score": score, "roadmap_linked": False}
                    score_bar = "🟩" * int(score) + "⬜" * (10 - int(score))
                    reply += f"\n\n📋 **KẾT QUẢ KIỂM TRA ({topic})**: {score}/10 {score_bar}\n{feedback}"

            elif action_type == "grade_homework":
                # 📝 BÀI TẬP VẬN DỤNG / TỰ PHÁT — KHÔNG lưu điểm vào roadmap
                topic = params.get("topic", "General review")
                score = float(params.get("score", 0.0))
                feedback = params.get("feedback", "")

                # Chỉ lưu vào HomeworkSubmission để theo dõi, không cập nhật Progress/roadmap
                submission = HomeworkSubmission(
                    student_id=student_id,
                    progress_id=None,
                    topic=topic,
                    score=score,
                    feedback=feedback
                )
                db.add(submission)
                db.commit()
                executed_action_log = {"type": "grade_homework", "topic": topic, "score": score, "roadmap_linked": False}
                score_bar = "🟩" * int(score) + "⬜" * (10 - int(score))
                reply += f"\n\n📝 **Kết quả bài tập ({topic})**: {score}/10 {score_bar}\n💬 *Phản hồi:* {feedback}\n\n*(Bài tập vận dụng không tính vào điểm lộ trình. Chỉ bài **Kiểm tra** mới cập nhật tiến độ!)*"

            elif action_type == "update_subtask":
                topic = params.get("topic")
                task_type = params.get("task_type")
                completed = params.get("completed", True)

                # Multi-level matching (same as grade_exam)
                progress_record = db.query(Progress).filter(
                    Progress.student_id == student_id,
                    Progress.topic == topic
                ).first()
                if not progress_record:
                    progress_record = db.query(Progress).filter(
                        Progress.student_id == student_id,
                        Progress.topic.ilike(f"%{topic}%")
                    ).first()
                if not progress_record and topic:
                    unit_match = re.search(r'(?:Bài|Unit|Chương)\s*(\d+)', topic, re.IGNORECASE)
                    if unit_match:
                        unit_num = unit_match.group(1)
                        for p in db.query(Progress).filter(Progress.student_id == student_id).all():
                            p_match = re.search(r'(?:Bài|Unit|Chương)\s*(\d+)', p.topic, re.IGNORECASE)
                            if p_match and p_match.group(1) == unit_num:
                                progress_record = p
                                break
                
                if progress_record:
                    if task_type == 'theory':
                        progress_record.theory_completed = completed
                        reply += f"\n\n✅ Đã đánh dấu hoàn thành phần **Học lí thuyết** cho bài {progress_record.topic}."
                    elif task_type == 'exercise':
                        progress_record.exercise_completed = completed
                        reply += f"\n\n✅ Đã đánh dấu hoàn thành phần **Làm bài tập** cho bài {progress_record.topic}."
                    db.commit()
                    executed_action_log = {"type": "update_subtask", "topic": progress_record.topic, "task_type": task_type}

        # 9. Save AI response to DB
        self.memory_service.add_message(db, student_id, "ai", reply)

        return reply, executed_action_log

    async def generate_unit_test(self, student_id: int, topic: str) -> str:
        """Generate a unit exam for the current roadmap Unit."""
        from backend.database.db import SessionLocal
        db = SessionLocal()
        try:
            student = db.query(Student).filter(Student.id == student_id).first()
            level = student.skill_level if student and student.skill_level else "Beginner"
            grade = student.grade_level if student and student.grade_level else "Unknown"
        finally:
            db.close()

        prompt = f"""Bạn là một giáo viên Toán. Hãy tạo một **bài kiểm tra đánh giá** cho học sinh.

Thông tin học sinh:
- Lớp: {grade}
- Trình độ: {level}
- Nội dung kiểm tra: {topic}

Yêu cầu bài kiểm tra:
1. Gồm 5 câu hỏi đa dạng: trắc nghiệm, giải toán tự luận.
2. Hướng dẫn rõ ràng bằng tiếng Việt.
3. Thang điểm 10, mỗi câu 2 điểm.
4. Phù hợp với trình độ {level} của học sinh lớp {grade}.
5. KHÔNG đưa đáp án.
6. LƯU Ý QUAN TRỌNG: KHÔNG sử dụng định dạng LaTeX như $$, \[, \] hay \( \). Hãy dùng văn bản thuần túy (e.g., x^2, a/b, +, -, *, /, =).

Kết thúc bằng dòng nhắc: "📌 Hãy trả lời tất cả các câu hỏi trên để được chấm điểm và cập nhật tiến độ lộ trình!"
"""
        try:
            response = await self.llm_service.generate_response(
                system_prompt="You are a Math teacher. Create a math exam in Vietnamese. DO NOT use LaTeX formatting like $$, \[, \( for math formulas. Use plain text. Return plain text only, no JSON.",
                user_prompt=prompt
            )
            response = response.strip()
            # Strip JSON wrapper if LLM returns JSON
            if response.startswith("{") and response.endswith("}"):
                try:
                    data = json.loads(response)
                    if "reply" in data:
                        return data["reply"]
                except:
                    pass
            return f"📝 **BÀI KIỂM TRA: {topic}**\n\n{response}"
        except Exception as e:
            logger.error(f"Failed to generate unit test: {e}")
            return f"""📝 **BÀI KIỂM TRA: {topic}**

**Câu 1 (2đ):** Tính: 2 + 3 = ?

**Câu 2 (2đ):** Điền số thích hợp: 5 + ... = 10

**Câu 3 (2đ):** Một hình vuông có cạnh 4cm. Tính chu vi.

**Câu 4 (2đ):** Giải phương trình: x + 2 = 5

**Câu 5 (2đ):** Đúng hay Sai: 10 - 3 = 6.

📌 Hãy trả lời tất cả các câu hỏi trên để được chấm điểm và cập nhật tiến độ lộ trình!"""

    async def generate_theory(self, student_id: int, topic: str) -> str:
        """Generate theory/lesson content for a unit — to be READ by the student, NOT an exercise."""
        from backend.database.db import SessionLocal
        db = SessionLocal()
        try:
            student = db.query(Student).filter(Student.id == student_id).first()
            level = student.skill_level if student and student.skill_level else "Beginner"
            grade = student.grade_level if student and student.grade_level else "Unknown"
        finally:
            db.close()

        prompt = f"""Bạn là một giáo viên Toán. Hãy soạn **BÀI HỌC LÝ THUYẾT** cho học sinh.

Thông tin học sinh:
- Lớp: {grade}
- Trình độ: {level}
- Chủ đề bài học: {topic}

Yêu cầu bài học lý thuyết:
1. Đây là phần để HỌC SINH ĐỌC VÀ GHI NHỚ, KHÔNG phải bài tập.
2. Nội dung phải liên quan chủ đề của bài học {topic} gồm:
   - 📚 **Khái niệm / Định lý**: giải thích rõ ràng, dễ hiểu bằng tiếng Việt
   - 📖 **Công thức toán học**: trình bày dạng văn bản đơn giản (không dùng LaTeX, dùng x^2, a/b, ...)
   - 💡 **Ví dụ minh họa**: 3-5 câu ví dụ thực tế có giải thích từng bước
   - 🗣️ **Mẹo ghi nhớ** (nếu có): các quy tắc đặc biệt
3. Viết hướng dẫn và giải thích bằng Tiếng Việt.
4. Phù hợp với trình độ {level} của học sinh lớp {grade}.
5. KHÔNG sử dụng định dạng LaTeX như $$, \[, \] hay \( \).
6. Cuối bài học thêm dòng: "✅ Đọc và ghi nhớ phần lý thuyết trên. Khi sẵn sàng, hãy báo để làm bài tập vận dụng!"
"""
        try:
            response = await self.llm_service.generate_response(
                system_prompt="You are a Math teacher. Create a theory/lesson content in Vietnamese for students to read and learn from. DO NOT use LaTeX formatting like $$, \[, \( for math formulas. Use plain text. Return plain text only, no JSON.",
                user_prompt=prompt
            )
            response = response.strip()
            if response.startswith("{") and response.endswith("}"):
                try:
                    data = json.loads(response)
                    if "reply" in data:
                        return data["reply"]
                except:
                    pass
            return f"📚 **BÀI HỌC LÝ THUYẾT: {topic}**\n\n{response}"
        except Exception as e:
            logger.error(f"Failed to generate theory: {e}")
            return f"""📚 **BÀI HỌC LÝ THUYẾT: {topic}**

📖 **Khái niệm:**
- Phép cộng là phép tính gộp hai hay nhiều số lại với nhau.
- Phép trừ là phép tính bớt đi một số khỏi một số khác.

📖 **Công thức cơ bản:**
- a + b = c
- a - b = c

💡 **Ví dụ minh họa:**
1. 2 + 3 = 5 (Có 2 quả táo, thêm 3 quả táo thành 5 quả).
2. 5 - 2 = 3 (Có 5 quả táo, ăn 2 quả còn 3 quả).

✅ Đọc và ghi nhớ phần lý thuyết trên. Khi sẵn sàng, hãy báo để làm bài tập vận dụng!"""

    async def generate_free_practice(self, student_id: int, topic: str) -> str:
        """Generate a free practice exercise requested ad-hoc via chat."""
        from backend.database.db import SessionLocal
        db = SessionLocal()
        try:
            student = db.query(Student).filter(Student.id == student_id).first()
            level = student.skill_level if student and student.skill_level else "Beginner"
            grade = student.grade_level if student and student.grade_level else "Unknown"
        finally:
            db.close()

        prompt = f"""Bạn là một gia sư Toán thân thiện. Hãy tạo **BÀI TẬP TỰ DO Luyện Tập** cho học sinh theo yêu cầu.

Thông tin học sinh:
- Lớp: {grade}
- Trình độ: {level}
- Nội dung luyện tập: {topic}

Yêu cầu:
1. Gồm 3-5 câu hỏi thú vị, có thể kết hợp trắc nghiệm, giải toán hoặc đố vui nhẹ nhàng.
2. Hướng dẫn rõ ràng bằng tiếng Việt với giọng điệu động viên, khích lệ.
3. KHÔNG đưa đáp án trước.
4. Phù hợp với trình độ {level} của học sinh lớp {grade}.
5. KHÔNG gán mác là "Bài kiểm tra" hay "Bài tập vận dụng" của lộ trình. Hãy gọi nó là "Bài tập tự do".
6. LƯU Ý QUAN TRỌNG: KHÔNG sử dụng định dạng LaTeX như $$, \[, \] hay \( \). Hãy dùng văn bản thuần túy.
"""
        try:
            response = await self.llm_service.generate_response(
                system_prompt="You are a Math tutor. Create a free practice exercise in Vietnamese. DO NOT use LaTeX formatting like $$, \[, \( for math formulas. Use plain text. Return plain text only, no JSON.",
                user_prompt=prompt
            )
            return response.strip()
        except Exception as e:
            return f"❌ Lỗi khi tạo bài tập tự do: {e}"

    async def generate_practice(self, student_id: int, topic: str) -> str:
        """Generate 5-question practice exercises (NOT saved to roadmap score)."""
        from backend.database.db import SessionLocal
        db = SessionLocal()
        try:
            student = db.query(Student).filter(Student.id == student_id).first()
            level = student.skill_level if student and student.skill_level else "Beginner"
            grade = student.grade_level if student and student.grade_level else "Unknown"
        finally:
            db.close()

        prompt = f"""Bạn là một giáo viên Toán. Hãy tạo **BÀI TẬP VẬN DỤNG** cho học sinh.

Thông tin học sinh:
- Lớp: {grade}
- Trình độ: {level}
- Nội dung luyện tập: {topic}

Yêu cầu bài tập vận dụng:
1. Gồm đúng 5 câu hỏi đa dạng: trắc nghiệm, giải toán tự luận.
2. Hướng dẫn rõ ràng bằng tiếng Việt.
3. KHÔNG đưa đáp án.
4. Phù hợp với trình độ {level} của học sinh lớp {grade}.
5. KHÔNG sử dụng định dạng LaTeX như $$, \[, \] hay \( \). Hãy dùng văn bản thuần túy.
6. Cuối thêm dòng: "📌 Hãy trả lời 5 câu trên. Bài tập vận dụng không tính điểm lộ trình nhưng giúp bạn luyện tập!"
"""
        try:
            response = await self.llm_service.generate_response(
                system_prompt="You are a Math teacher. Create practice exercises in Vietnamese. DO NOT use LaTeX formatting like $$, \[, \( for math formulas. Use plain text. Return plain text only, no JSON.",
                user_prompt=prompt
            )
            response = response.strip()
            if response.startswith("{") and response.endswith("}"):
                try:
                    data = json.loads(response)
                    if "reply" in data:
                        return data["reply"]
                except:
                    pass
            return f"✏️ **BÀI TẬP VẬN DỤNG: {topic}**\n\n{response}"
        except Exception as e:
            return f"✏️ **BÀI TẬP VẬN DỤNG: {topic}**\n\n**Câu 1:** Tính 5 + 5 = ?\n**Câu 2:** Điền số: 10 - ... = 2\n**Câu 3:** 2 * 3 = ?\n**Câu 4:** Giải x + 1 = 10\n**Câu 5:** Đúng hay sai: 3 + 3 = 7\n\n📌 Hãy trả lời 5 câu trên. Bài tập vận dụng không tính điểm lộ trình nhưng giúp bạn luyện tập!"

    async def generate_exam(self, student_id: int, topic: str) -> str:
        """Generate 8-question exam — score WILL be saved to roadmap."""
        return await self.generate_unit_test(student_id, topic)

    async def generate_homework(self, student_id: int, topic: str) -> str:
        """Alias for generate_unit_test — called by scheduler for exam type."""
        return await self.generate_unit_test(student_id, topic)


    async def generate_milestone_report(self, db: Session, student_id: int, milestone_topic: str, completed_count: int, total_count: int) -> str:
        """Generate a milestone progress report when student completes a section of their roadmap."""
        student = db.query(Student).filter(Student.id == student_id).first()
        student_name = student.name if student else "Học sinh"
        is_completed = completed_count == total_count

        prompt = f"""Học sinh {student_name} vừa hoàn thành chủ đề '{milestone_topic}'.
- Tiến độ: {completed_count}/{total_count} bước trong lộ trình.
- {'Đây là bước CUỐI CÙNG, học sinh đã HOÀN THÀNH TOÀN BỘ lộ trình!' if is_completed else f'Đây là cột mốc quan trọng ({completed_count} bước xong).'}

Hãy viết một báo cáo chặng đường ngắn gọn (5-8 dòng) bằng tiếng Việt, dùng markdown, gồm:
- 🏆 Tiêu đề báo cáo cột mốc
- Lời chúc mừng cá nhân hóa
- Nhận xét về sự kiên trì
- Khuyến khích tiếp tục bước tiếp theo (hoặc ăn mừng hoàn thành nếu xong toàn bộ)"""
        try:
            response = await self.llm_service.generate_response(
                system_prompt="You are an encouraging AI Tutor. Write a short milestone progress report in Vietnamese.",
                user_prompt=prompt
            )
            report = response.strip()
            # Strip any JSON wrapper if LLM returned JSON
            if report.startswith('{'):
                try:
                    data = json.loads(report)
                    report = data.get("reply", report)
                except:
                    pass
            return report
        except Exception as e:
            logger.error(f"Failed to generate milestone report: {e}")
            if is_completed:
                return f"🎉 **Chúc mừng {student_name}! Bạn đã hoàn thành TOÀN BỘ lộ trình học tập!** Đây là một thành tích đáng tự hào. Hãy ôn lại kiến thức và chinh phục thử thách tiếp theo nhé!"
            return f"🏆 **Cột mốc {completed_count}/{total_count}!** Xuất sắc lắm {student_name}! Bạn đang tiến rất tốt trên lộ trình học tập. Hãy tiếp tục phát huy!"



    async def generate_daily_report(self, db: Session, student_id: int, topic: str = "") -> str:
        """Generate a daily learning evaluation report after task completion."""
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            return ""
        student_name = student.name

        from backend.database.models import ChatMessage
        one_day_ago = datetime.now() - timedelta(days=1)
        recent_messages = db.query(ChatMessage).filter(
            ChatMessage.student_id == student_id,
            ChatMessage.created_at >= one_day_ago
        ).order_by(ChatMessage.created_at.asc()).all()

        chat_summary = "\n".join([
            f"{m.sender.upper()}: {m.message[:120]}" for m in recent_messages[-20:]
        ]) or "Không có hoạt động nào trong ngày."

        progress_records = db.query(Progress).filter(Progress.student_id == student_id).all()
        progress_summary = "\n".join([
            f"- {p.topic}: {p.status}" + (f", điểm={p.score}/10" if p.score is not None else "")
            for p in progress_records
        ]) or "Chưa có tiến độ nào được ghi nhận."

        prompt = f"""Viết Báo Cáo Tóm Tắt Hằng Ngày cho học sinh {student_name}.

Học sinh vừa hoàn thành xuất sắc bài học/kiểm tra: {topic}

Hoạt động ngày qua:
{chat_summary}

Tiến độ lộ trình:
{progress_summary}

Báo cáo cần bằng tiếng Việt, dùng markdown đẹp mắt, ngắn gọn gồm 3 phần:
1. **📊 Tóm tắt ngày**: Chúc mừng hoàn thành bài học {topic}
2. **💪 Nhận xét**: Đánh giá kết quả nhanh
3. **🎯 Nhắc nhở ngày mai**: Lời khuyên ngắn gọn"""
        try:
            response = await self.llm_service.generate_response(
                system_prompt="You are a personal AI Tutor writing a daily learning evaluation report in Vietnamese.",
                user_prompt=prompt
            )
            report = response.strip()
            if report.startswith('{'):
                try:
                    data = json.loads(report)
                    report = data.get("reply", report)
                except:
                    pass
            return report
        except Exception as e:
            logger.error(f"Failed to generate daily report: {e}")
            return f"**📋 Báo Cáo Học Tập Ngày - {student_name}**\n\nHôm nay bạn đã cố gắng rất nhiều. Hãy chuẩn bị tốt cho ngày mai nhé!"
