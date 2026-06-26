import json
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
from backend.database.db import SessionLocal
from backend.database.models import ScheduledJob, Student, ChatMessage, Roadmap, Progress

logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.tutor_service = None

    def start(self):
        if not self.scheduler.running:
            try:
                self.scheduler.start()
                self._reload_pending_jobs()
                logger.info("APScheduler started successfully and reloaded jobs.")
            except Exception as e:
                logger.error(f"Failed to start APScheduler: {e}")

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("APScheduler stopped.")

    def set_tutor_service(self, tutor_service):
        self.tutor_service = tutor_service

    def _reload_pending_jobs(self):
        db = SessionLocal()
        try:
            now = datetime.now()
            jobs = db.query(ScheduledJob).filter(ScheduledJob.status == "pending").all()
            for job in jobs:
                run_time = job.scheduled_time
                if run_time < now:
                    run_time = now + timedelta(seconds=10) # run shortly if missed
                try:
                    new_job = self.scheduler.add_job(
                        self._trigger_homework_job,
                        'date',
                        run_date=run_time,
                        args=[job.student_id, job.id, job.topic],
                        id=f"homework_{job.id}",
                        replace_existing=True
                    )
                    job.apscheduler_job_id = new_job.id
                except Exception as e:
                    logger.error(f"Failed to reload job {job.id}: {e}")
            db.commit()
        finally:
            db.close()

    async def schedule_homework(self, student_id: int, topic: str, run_time: datetime, is_auto: bool = False, job_type: str = "practice") -> int:
        db = SessionLocal()
        try:
            db_job = ScheduledJob(
                student_id=student_id,
                job_type=job_type,
                topic=topic,
                scheduled_time=run_time,
                status="pending",
                is_auto=is_auto
            )
            db.add(db_job)
            db.commit()
            db.refresh(db_job)

            job = self.scheduler.add_job(
                self._trigger_homework_job,
                'date',
                run_date=run_time,
                args=[student_id, db_job.id, topic],
                id=f"homework_{db_job.id}"
            )

            db_job.apscheduler_job_id = job.id
            db.commit()
            logger.info(f"Scheduled {job_type} job {db_job.id} for student {student_id} at {run_time}")
            return db_job.id
        except Exception as e:
            logger.error(f"Failed to schedule {job_type} job: {e}")
            db.rollback()
            raise e
        finally:
            db.close()

    async def update_schedule(self, student_id: int):
        """Called when schedule is updated, or roadmap is created, or a unit is completed."""
        db = SessionLocal()
        try:
            # 1. Cancel all pending auto jobs
            jobs = db.query(ScheduledJob).filter(
                ScheduledJob.student_id == student_id,
                ScheduledJob.status == "pending",
                ScheduledJob.is_auto == True
            ).all()
            for job in jobs:
                job.status = "cancelled"
                if job.apscheduler_job_id:
                    try:
                        self.scheduler.remove_job(job.apscheduler_job_id)
                    except Exception:
                        pass
            db.commit()
            
            # 2. Get active roadmap and uncompleted topics
            student = db.query(Student).filter(Student.id == student_id).first()
            if not student: return
            
            roadmap = db.query(Roadmap).filter(Roadmap.student_id == student_id).order_by(Roadmap.created_at.desc()).first()
            if not roadmap: return
            
            # Require student to explicitly chat to set learning_frequency first!
            if not student.learning_frequency: return
            
            try: steps = json.loads(roadmap.content)
            except: return
            
            uncompleted_topics = []
            for step in steps:
                title = step.get("title")
                if not title: continue
                progress = db.query(Progress).filter(
                    Progress.student_id == student_id,
                    Progress.topic == title
                ).first()
                if not progress or progress.status != "completed":
                    uncompleted_topics.append(title)
                    # No break — collect ALL uncompleted topics to schedule across future dates
                    
            if not uncompleted_topics: return
            
            logger.info(f"Scheduling {len(uncompleted_topics)} uncompleted topics for student {student_id}")
            
            # 3. Generate future dates (1 date per uncompleted topic)
            now = datetime.now()
            theory_time = self._parse_time(student.theory_time, "19:00")
            practice_time = self._parse_time(student.practice_time, "19:30")
            exam_time = self._parse_time(student.exam_time, "20:00")
            
            dates = self._get_learning_dates(student, now, len(uncompleted_topics), exam_time)
            
            # 4. Schedule Theory, Practice, Exam for each topic on its corresponding date
            for i, topic in enumerate(uncompleted_topics):
                if i >= len(dates): break
                day = dates[i]
                
                for j_type, t_str in [("theory", theory_time), ("practice", practice_time), ("exam", exam_time)]:
                    h, m = map(int, t_str.split(':'))
                    run_time = datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m)
                    
                    full_topic = f"{topic} - {j_type.capitalize()}"
                    
                    if run_time < now:
                        # Stagger past jobs by a few seconds so they execute in order and don't hit LLM rate limits
                        offset = {"theory": 5, "practice": 15, "exam": 25}
                        run_time = now + timedelta(seconds=offset.get(j_type, 10))
                        
                    await self.schedule_homework(student_id, full_topic, run_time, is_auto=True, job_type=j_type)
                
                logger.info(f"  Scheduled '{topic}' on {day} (theory={theory_time}, practice={practice_time}, exam={exam_time})")
                    
        except Exception as e:
            logger.error(f"Error in update_schedule: {e}")
        finally:
            db.close()

    def _parse_time(self, time_str, default):
        try:
            if not time_str: return default
            h, m = map(int, time_str.split(':'))
            return f"{h:02d}:{m:02d}"
        except:
            return default

    def _get_learning_dates(self, student, start_date: datetime, count: int, exam_time_str: str):
        days = []
        current_date = start_date.date()
        freq_str = (student.learning_frequency or "").lower()
        
        days_map = {
            'thứ 2': 0, 'thứ hai': 0, 'monday': 0,
            'thứ 3': 1, 'thứ ba': 1, 'tuesday': 1,
            'thứ 4': 2, 'thứ tư': 2, 'wednesday': 2,
            'thứ 5': 3, 'thứ năm': 3, 'thursday': 3,
            'thứ 6': 4, 'thứ sáu': 4, 'friday': 4,
            'thứ 7': 5, 'thứ bảy': 5, 'saturday': 5,
            'chủ nhật': 6, 'sunday': 6, 'cn': 6
        }
        selected_weekdays = set()
        
        # 1. First pass: Check for full words
        for d_str, d_num in days_map.items():
            if d_str in freq_str:
                selected_weekdays.add(d_num)
                
        # 2. Second pass: If it's a short format like "3-5-7" or "2,4,6", extract digits
        import re
        digits = re.findall(r'\b[2-7]\b', freq_str.replace('-', ' ').replace(',', ' '))
        for d in digits:
            selected_weekdays.add(int(d) - 2) # e.g. '2' -> 0 (Monday)
            
        interval = 1
        if "cách 1 ngày" in freq_str or "2 ngày 1 lần" in freq_str:
            interval = 2
        elif "cách 2 ngày" in freq_str or "3 ngày 1 lần" in freq_str:
            interval = 3
        elif not selected_weekdays:
            interval = 1
            
        h, m = map(int, exam_time_str.split(':'))
        start_datetime_exam = datetime.combine(current_date, datetime.min.time()).replace(hour=h, minute=m)
        if start_datetime_exam < start_date:
            current_date += timedelta(days=1)
            
        days_found = 0
        while days_found < count:
            if selected_weekdays:
                if current_date.weekday() in selected_weekdays:
                    days.append(current_date)
                    days_found += 1
                current_date += timedelta(days=1)
            else:
                days.append(current_date)
                days_found += 1
                current_date += timedelta(days=interval)
                
        return days

    async def _trigger_homework_job(self, student_id: int, job_id: int, topic: str):
        logger.info(f"Triggering job {job_id} for student {student_id}")
        db = SessionLocal()
        try:
            job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
            if not job or job.status != "pending":
                return

            job_type = job.job_type or "practice"
            job.status = "sent"
            db.commit()

            if self.tutor_service:
                clean_topic = topic.split(" - ")[0] if " - " in topic else topic
                
                if job_type == "theory":
                    content = await self.tutor_service.generate_theory(student_id, clean_topic)
                    tele_header = f"📚 **BÀI HỌC LÝ THUYẾT MỚI** 📚\n\nChủ đề: **{clean_topic}**\n\n"
                    tele_footer = "\n\n✅ Đọc và ghi nhớ lý thuyết. Khi sẵn sàng, hãy báo giáo viên!"
                elif job_type == "practice":
                    content = await self.tutor_service.generate_practice(student_id, clean_topic)
                    tele_header = f"✏️ **BÀI TẬP VẬN DỤNG** ✏️\n\nChủ đề: **{clean_topic}**\n\n"
                    tele_footer = "\n\n📌 Hãy trả lời các câu trên. Bài tập vận dụng không tính điểm lộ trình!"
                elif job_type == "exam":
                    content = await self.tutor_service.generate_exam(student_id, clean_topic)
                    tele_header = f"📝 **BÀI KIỂM TRA CHÍNH THỨC** 📝\n\nChủ đề: **{clean_topic}**\n\n"
                    tele_footer = "\n\n📌 Hãy trả lời tất cả câu hỏi trên để được chấm điểm và cập nhật tiến độ lộ trình!"
                else:
                    content = await self.tutor_service.generate_free_practice(student_id, clean_topic)
                    tele_header = f"🎮 **BÀI TẬP TỰ DO Luyện Tập** 🎮\n\nChủ đề: **{clean_topic}**\n\n"
                    tele_footer = "\n\n📌 Đây là bài tập tự do bạn yêu cầu, hãy làm thoải mái để ôn tập nhé!"

                ai_message = ChatMessage(student_id=student_id, sender="ai", message=content)
                db.add(ai_message)
                db.commit()

                student = db.query(Student).filter(Student.id == student_id).first()
                if student and student.telegram_id:
                    from backend.telegram.bot import send_telegram_message
                    tele_message = tele_header + content + tele_footer
                    await send_telegram_message(student.telegram_id, tele_message)
            else:
                logger.error("Tutor service not set in Scheduler.")
        except Exception as e:
            logger.error(f"Error executing job {job_id}: {e}")
        finally:
            db.close()
