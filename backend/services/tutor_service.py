import os
import re
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple
from sqlalchemy.orm import Session

from backend.database.models import Student, ChatMessage, Progress, HomeworkSubmission
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

        # 5. Build system prompt
        homework_schedule_text = "Chưa cài đặt lịch tự động"
        if student and (student.homework_frequency or 0) > 0:
            freq = student.homework_frequency
            freq_map = {0: 'Tắt', 1: 'Hàng ngày', 2: 'Cách 1 ngày', 3: 'Cách 2 ngày', 7: 'Hàng tuần'}
            freq_text = freq_map.get(freq, f'mỗi {freq} ngày')
            homework_schedule_text = f"Giao bài lúc {student.homework_time}, tần suất: {freq_text}"

        system_prompt = f"""
You are an enthusiastic, flexible, and supportive AI Tutor. Your student's details:
- Name: {student_name}
- Current Level: {skill_level}
- Learning Goals: {learning_goals}
- Auto Homework Schedule: {homework_schedule_text}

Guidelines:
- Speak naturally, dynamically, and flexibly like a real human tutor. Avoid being rigid, robotic, or using generic templates.
- Tailor your explanations to their skill level ({skill_level}).
- Refer to their uploaded documents if relevant context is provided.
- Respond in Vietnamese.
- **IMPORTANT**: If the student has no auto homework schedule set (homework_frequency=0) and they haven't mentioned scheduling yet, you should PROACTIVELY ask them in a friendly way when they want to receive daily homework (e.g. "Bạn muốn nhận bài tập tự động lúc mấy giờ mỗi ngày?"). Do this once, not every message.
- If the student requests or expresses intent to perform an action (e.g. schedule homework, create a roadmap, update their goals, set auto homework schedule, or grade homework), you MUST output the corresponding action JSON. At the same time, in your text response ("reply"), guide them naturally:
  * To schedule a one-time homework: Use the "Lịch bài tập đã hẹn" form in the right sidebar.
  * To set up AUTOMATIC daily/recurring homework: Just tell the AI directly (e.g. "giao bài lúc 8h tối mỗi ngày") — the AI will update your schedule automatically.
  * To create a learning roadmap: Use the "Lộ trình học tập" form in the right sidebar, type the subject, and click "Tạo".
  * To update learning profile/goals: Edit fields in the "Thông tin học tập" form in the left sidebar.
  * To upload study documents for RAG: Click "Tải tài liệu lên" in the left sidebar.
  * To link Telegram: Copy the code from "Liên kết Telegram" card in the left sidebar, then send `/start <linking_code>` to the bot.

CRITICAL: You MUST respond in a valid JSON object only. Do not wrap it in markdown block like ```json ```.
The JSON object must have EXACTLY this structure:
{{
  "reply": "Your actual text response here. Use formatting (like markdown headings, bullet points, code blocks) inside this string.",
  "action": null or an object
}}

Supported actions:
1. Schedule Homework:
   If the student asks to schedule a one-time homework (e.g. "giao bài tập cho tôi vào ngày mai lúc 8h tối", "schedule python homework in 2 minutes"), parse the time and topic.
   Action format:
   {{
     "type": "schedule_homework",
     "params": {{
       "topic": "Python basics",
       "scheduled_time": "2026-06-17T20:00:00"  // ISO 8601 string in the future. Today's date is: {datetime.now().isoformat()}
     }}
   }}
   NOTE: If they don't specify a date, schedule for tomorrow. If they ask for "now" or "in 1 minute", schedule it 1 minute from now.

2. Generate Roadmap:
   If they want a study roadmap for a topic (e.g., "lập lộ trình học Python", "roadmap for web design"):
   Action format:
   {{
     "type": "generate_roadmap",
     "params": {{
       "subject": "Python"
     }}
   }}

3. Update Profile (including auto homework schedule):
   If they want to update goals, level, OR set up automatic recurring homework (e.g. "tôi muốn làm bài tập lúc 8h tối mỗi ngày", "đổi lịch sang 21:30 cách 2 ngày", "tắt tự động giao bài", "giao bài tập cho tôi hàng ngày lúc 7 giờ sáng"):
   Action format:
   {{
     "type": "update_profile",
     "params": {{
       "learning_goals": "Machine Learning",
       "skill_level": "Intermediate",
       "homework_time": "20:00",
       "homework_frequency": 1
     }}
   }}
   NOTE: homework_time is "HH:MM" 24h format. homework_frequency: 0=tắt tự động, 1=hàng ngày, 2=cách 1 ngày, 3=cách 2 ngày, 7=hàng tuần. Only include params that are being changed.

4. Grade Homework:
   If the student is answering/submitting a homework (e.g. "đây là bài làm của em", "câu 1: ..., câu 2: ...", writing answers to your previous homework questions), grade their work and output:
   Action format:
   {{
     "type": "grade_homework",
     "params": {{
       "topic": "Python basics",
       "score": 8.5,
       "feedback": "Detailed Vietnamese feedback on what was done well and what needs improvement"
     }}
   }}
   NOTE: score is a float 0.0 to 10.0. Be fair, constructive, and encouraging. If score < 5, the topic stays 'in_progress' so the student can retry.
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
                if scheduled_time_str:
                    try:
                        run_time = datetime.fromisoformat(scheduled_time_str)
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
                
                job_id = await self.scheduler_service.schedule_homework(student_id, topic, run_time)
                executed_action_log = {"type": "schedule_homework", "job_id": job_id, "topic": topic, "time": run_time.isoformat()}
                reply += f"\n\n⏰ **Đã lên lịch bài tập về nhà!** Chủ đề: *{topic}* vào lúc {run_time.strftime('%Y-%m-%d %H:%M:%S')}."
                
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
                
                executed_action_log = {"type": "generate_roadmap", "roadmap_id": roadmap.id, "subject": subject}
                reply += f"\n\n🗺️ **Lộ trình học {subject} đã được tạo thành công!** Bạn có thể xem chi tiết trong phần Dashboard."

            elif action_type == "update_profile":
                updated_fields = {}
                if "learning_goals" in params:
                    student.learning_goals = params["learning_goals"]
                    updated_fields["learning_goals"] = params["learning_goals"]
                if "skill_level" in params:
                    student.skill_level = params["skill_level"]
                    updated_fields["skill_level"] = params["skill_level"]
                if "name" in params:
                    student.name = params["name"]
                    updated_fields["name"] = params["name"]
                if "homework_time" in params:
                    student.homework_time = params["homework_time"]
                    updated_fields["homework_time"] = params["homework_time"]
                if "homework_frequency" in params:
                    student.homework_frequency = int(params["homework_frequency"])
                    updated_fields["homework_frequency"] = params["homework_frequency"]
                db.commit()
                executed_action_log = {"type": "update_profile", "updated": updated_fields}
                schedule_msg = ""
                if "homework_time" in updated_fields or "homework_frequency" in updated_fields:
                    freq = student.homework_frequency
                    freq_map = {0: "tắt", 1: "hàng ngày", 2: "cách 1 ngày", 3: "cách 2 ngày", 7: "hàng tuần"}
                    freq_text = freq_map.get(freq, f"mỗi {freq} ngày")
                    schedule_msg = f" Lịch tự giao bài: **{student.homework_time}**, tần suất **{freq_text}**."
                reply += f"\n\n⚙️ **Thông tin học tập đã được cập nhật!**{schedule_msg}"

            elif action_type == "grade_homework":
                topic = params.get("topic", "General review")
                score = float(params.get("score", 0.0))
                feedback = params.get("feedback", "")

                # Find matching progress record (by topic name, fuzzy)
                from backend.database.models import Roadmap
                progress_record = db.query(Progress).filter(
                    Progress.student_id == student_id,
                    Progress.topic.ilike(f"%{topic}%")
                ).first()
                # Fallback: first incomplete progress record
                if not progress_record:
                    progress_record = db.query(Progress).filter(
                        Progress.student_id == student_id,
                        Progress.status != "completed"
                    ).order_by(Progress.id.asc()).first()

                if progress_record:
                    # Log this submission in HomeworkSubmission table
                    submission = HomeworkSubmission(
                        student_id=student_id,
                        progress_id=progress_record.id,
                        topic=progress_record.topic,
                        score=score,
                        feedback=feedback
                    )
                    db.add(submission)

                    # Update attempt count
                    progress_record.attempt_count = (progress_record.attempt_count or 0) + 1

                    # Keep best score
                    if progress_record.score is None or score > progress_record.score:
                        progress_record.score = score

                    # Update status based on score
                    if score >= 5.0:
                        progress_record.status = "completed"
                    else:
                        progress_record.status = "in_progress"  # Allow retry

                    db.commit()
                    executed_action_log = {"type": "grade_homework", "topic": progress_record.topic, "score": score}

                    # Build score-weighted progress percentage
                    roadmap_obj = db.query(Roadmap).filter(
                        Roadmap.student_id == student_id
                    ).order_by(Roadmap.created_at.desc()).first()

                    progress_pct = 0
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
                        completed_in_roadmap = 0
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

                        # Check milestone: every 3 completions or all done
                        is_milestone = total_steps > 0 and (
                            (completed_in_roadmap % 3 == 0) or (completed_in_roadmap == total_steps)
                        )
                        if is_milestone and completed_in_roadmap > 0 and score >= 5.0:
                            milestone_report = await self.generate_milestone_report(
                                db, student_id, progress_record.topic, completed_in_roadmap, total_steps
                            )
                            reply += f"\n\n{milestone_report}"

                    score_bar = "🟩" * int(score) + "⬜" * (10 - int(score))
                    status_text = "✅ Hoàn thành" if score >= 5.0 else "🔄 Cần ôn thêm (có thể thử lại)"
                    reply += f"\n\n📝 **Kết quả chấm điểm:** {score}/10 {score_bar}\n**Chủ đề:** {progress_record.topic}\n**Trạng thái:** {status_text}\n**Tiến độ lộ trình:** {progress_pct}%\n\n💬 *Phản hồi:* {feedback}"
                else:
                    reply += f"\n\n📝 **Điểm số:** {score}/10. Rất tiếc, tôi không tìm thấy phần bài học tương ứng để cập nhật tiến độ lộ trình."

        # 9. Save AI response to DB
        self.memory_service.add_message(db, student_id, "ai", reply)

        return reply, executed_action_log

    async def generate_homework(self, student_id: int, topic: str) -> str:
        from backend.database.db import SessionLocal
        db = SessionLocal()
        try:
            student = db.query(Student).filter(Student.id == student_id).first()
            subject = student.learning_goals if student and student.learning_goals else "General knowledge"
            level = student.skill_level if student and student.skill_level else "Beginner"
        finally:
            db.close()

        prompt = f"""
Generate a homework assignment for a student on the topic: "{topic}".
The student is currently learning: "{subject}" at a "{level}" level. 
The questions MUST test their knowledge about "{subject}" regarding the topic "{topic}".
Do NOT test them on the Vietnamese language itself unless "{subject}" is Vietnamese.

The homework should consist of:
1. 3 questions (mix of multiple-choice and short answer).
2. Clear instructions in Vietnamese.
3. A small hint for each question in Vietnamese.

Do NOT generate answers, just the assignment questions.
Output the homework in a friendly tutor tone in Vietnamese.
End with a reminder that the student should reply with their answers to receive grading.
"""
        try:
            response = await self.llm_service.generate_response(
                system_prompt="You are a helpful and detailed tutor. Output markdown-formatted homework assignments in Vietnamese.",
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
            return response
        except Exception as e:
            logger.error(f"Failed to generate homework: {e}")
            return f"""**Bài tập về nhà: {topic}**

Câu 1: Hãy giải thích khái niệm cơ bản của {topic}.
*Gợi ý: Nhớ lại những gì đã học và dùng lời của mình.*

Câu 2: Cho một ví dụ thực tế về việc áp dụng {topic}.
*Gợi ý: Nghĩ đến các tình huống thực tế trong cuộc sống.*

Câu 3: Viết một đoạn mã/phân tích ngắn áp dụng {topic}.
*Gợi ý: Tham khảo tài liệu đã học.*

📌 Hãy trả lời bài tập này trực tiếp trong chat để được chấm điểm!"""

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

    async def generate_weekly_report(self, db: Session, student_id: int) -> str:
        """Generate a weekly learning evaluation report."""
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            return ""
        student_name = student.name

        from backend.database.models import ChatMessage
        one_week_ago = datetime.now() - timedelta(days=7)
        recent_messages = db.query(ChatMessage).filter(
            ChatMessage.student_id == student_id,
            ChatMessage.created_at >= one_week_ago
        ).order_by(ChatMessage.created_at.asc()).all()

        chat_summary = "\n".join([
            f"{m.sender.upper()}: {m.message[:120]}" for m in recent_messages[-20:]
        ]) or "Không có hoạt động nào trong tuần."

        progress_records = db.query(Progress).filter(Progress.student_id == student_id).all()
        progress_summary = "\n".join([
            f"- {p.topic}: {p.status}" + (f", điểm={p.score}/10" if p.score is not None else "")
            for p in progress_records
        ]) or "Chưa có tiến độ nào được ghi nhận."

        prompt = f"""Viết Báo Cáo Đánh Giá Học Tập Tuần cho học sinh {student_name}.

Hoạt động tuần qua:
{chat_summary}

Tiến độ lộ trình:
{progress_summary}

Báo cáo cần bằng tiếng Việt, dùng markdown đẹp mắt, gồm 4 phần:
1. **📊 Tóm tắt tuần**: Học sinh đã làm gì, hoàn thành bài tập nào
2. **💪 Điểm mạnh**: Nội dung làm tốt, điểm cao
3. **📈 Cần cải thiện**: Chủ đề còn yếu hoặc điểm chưa cao
4. **🎯 Mục tiêu tuần tới**: 2-3 đề xuất cụ thể"""
        try:
            response = await self.llm_service.generate_response(
                system_prompt="You are a personal AI Tutor writing a weekly learning evaluation report in Vietnamese.",
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
            logger.error(f"Failed to generate weekly report: {e}")
            return f"**📋 Báo Cáo Học Tập Tuần - {student_name}**\n\nBạn đã tích cực tham gia học tập trong tuần qua. Hãy tiếp tục duy trì nhịp độ này và chinh phục các mục tiêu tiếp theo!"

    async def generate_daily_report(self, db: Session, student_id: int) -> str:
        """Generate a daily learning evaluation report."""
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

        prompt = f"""Viết Báo Cáo Đánh Giá Học Tập Ngày cho học sinh {student_name}.

Hoạt động ngày qua:
{chat_summary}

Tiến độ lộ trình:
{progress_summary}

Báo cáo cần bằng tiếng Việt, dùng markdown đẹp mắt, ngắn gọn gồm 3 phần:
1. **📊 Tóm tắt ngày**: Hôm nay học sinh đã học gì
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
