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
        self.tutor_service = None  # Set after initialization to avoid circular imports

    def start(self):
        if not self.scheduler.running:
            try:
                self.scheduler.start()
                # Check auto-homework every minute
                self.scheduler.add_job(
                    self._check_auto_homework,
                    'interval',
                    minutes=1,
                    id='auto_homework_check',
                    replace_existing=True
                )
                logger.info("APScheduler started successfully with auto-homework jobs.")
            except Exception as e:
                logger.error(f"Failed to start APScheduler: {e}")

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("APScheduler stopped.")

    def set_tutor_service(self, tutor_service):
        self.tutor_service = tutor_service

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

    async def _trigger_homework_job(self, student_id: int, job_id: int, topic: str):
        logger.info(f"Triggering job {job_id} for student {student_id}")
        db = SessionLocal()
        try:
            job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
            if not job or job.status != "pending":
                logger.warning(f"Job {job_id} not found or not pending.")
                return

            job_type = job.job_type or "practice"  # default fallback
            job.status = "sent"
            db.commit()

            if self.tutor_service:
                # Route to the correct generator based on job_type
                if job_type == "theory":
                    content = await self.tutor_service.generate_theory(student_id, topic)
                    tele_header = f"📚 **BÀI HỌC LÝ THUYẾT MỚI** 📚\n\nChủ đề: **{topic}**\n\n"
                    tele_footer = "\n\n✅ Đọc và ghi nhớ lý thuyết. Khi sẵn sàng, hãy báo giáo viên!"
                elif job_type == "practice":
                    content = await self.tutor_service.generate_practice(student_id, topic)
                    tele_header = f"✏️ **BÀI TẬP VẬN DỤNG** ✏️\n\nChủ đề: **{topic}**\n\n"
                    tele_footer = "\n\n📌 Hãy trả lời các câu trên. Bài tập vận dụng không tính điểm lộ trình!"
                elif job_type == "exam":
                    content = await self.tutor_service.generate_exam(student_id, topic)
                    tele_header = f"📝 **BÀI KIỂM TRA CHÍNH THỨC** 📝\n\nChủ đề: **{topic}**\n\n"
                    tele_footer = "\n\n📌 Hãy trả lời tất cả câu hỏi trên để được chấm điểm và cập nhật tiến độ lộ trình!"
                else:  # free_practice
                    content = await self.tutor_service.generate_free_practice(student_id, topic)
                    tele_header = f"🎮 **BÀI TẬP TỰ DO Luyện Tập** 🎮\n\nChủ đề: **{topic}**\n\n"
                    tele_footer = "\n\n📌 Đây là bài tập tự do bạn yêu cầu, hãy làm thoải mái để ôn tập nhé!"

                ai_message = ChatMessage(
                    student_id=student_id,
                    sender="ai",
                    message=content
                )
                db.add(ai_message)
                db.commit()

                student = db.query(Student).filter(Student.id == student_id).first()
                if student and student.telegram_id:
                    from backend.telegram.bot import send_telegram_message
                    tele_message = tele_header + content + tele_footer
                    await send_telegram_message(student.telegram_id, tele_message)
                    logger.info(f"Sent {job_type} content to student {student_id} via Telegram.")
                else:
                    logger.info(f"Student {student_id} has no Telegram linked. Content saved to database.")
            else:
                logger.error("Tutor service not set in Scheduler.")
        except Exception as e:
            logger.error(f"Error executing job {job_id}: {e}")
        finally:
            db.close()

    async def _check_auto_homework(self):
        """Run every minute: check if any student's scheduled homework time has arrived."""
        db = SessionLocal()
        try:
            now = datetime.now()
            current_time_str = now.strftime("%H:%M")
            day_of_week = now.weekday() # 0 = Monday, 6 = Sunday

            students = db.query(Student).all()
            for student in students:
                # 1. Check if today is a learning day based on learning_frequency
                freqStr = (student.learning_frequency or "").lower()
                is_learning_day = False
                
                if freqStr:
                    if "hằng ngày" in freqStr or "hàng ngày" in freqStr or "mỗi ngày" in freqStr or "daily" in freqStr:
                        is_learning_day = True
                    else:
                        days_map = {
                            'thứ 2': 0, 'thứ hai': 0,
                            'thứ 3': 1, 'thứ ba': 1,
                            'thứ 4': 2, 'thứ tư': 2,
                            'thứ 5': 3, 'thứ năm': 3,
                            'thứ 6': 4, 'thứ sáu': 4,
                            'thứ 7': 5, 'thứ bảy': 5,
                            'chủ nhật': 6
                        }
                        for day_str, day_num in days_map.items():
                            if day_str in freqStr and day_of_week == day_num:
                                is_learning_day = True
                                break
                        # fallback
                        if not any(day_str in freqStr for day_str in days_map):
                            is_learning_day = True
                
                # 2. Legacy check
                if not is_learning_day and student.homework_frequency and student.homework_frequency > 0:
                    if student.homework_time == current_time_str:
                        is_learning_day = True
                        times_to_trigger = [("Bài tập", student.homework_time)]
                    else:
                        times_to_trigger = []
                elif is_learning_day:
                    times_to_trigger = [
                        ("Lý thuyết", student.theory_time),
                        ("Bài tập vận dụng", student.practice_time),
                        ("Kiểm tra", student.exam_time)
                    ]
                else:
                    continue

                # 3. Trigger jobs
                for job_name, job_time in times_to_trigger:
                    if not job_time:
                        continue
                        
                    try:
                        h, m = map(int, job_time.split(':'))
                        run_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    except ValueError:
                        continue

                    # Map job_name to job_type
                    if job_name == "Lý thuyết":
                        job_type = "theory"
                    elif job_name == "Bài tập vận dụng":
                        job_type = "practice"
                    else:  # Kiểm tra
                        job_type = "exam"

                    # Find the active topic
                    topic = "Ôn tập tổng hợp"
                    roadmap = db.query(Roadmap).filter(
                        Roadmap.student_id == student.id
                    ).order_by(Roadmap.created_at.desc()).first()

                    if roadmap:
                        try:
                            steps = json.loads(roadmap.content)
                        except Exception:
                            steps = []
                        for step in steps:
                            step_title = step.get("title", "")
                            if not step_title:
                                continue
                            progress = db.query(Progress).filter(
                                Progress.student_id == student.id,
                                Progress.topic == step_title
                            ).first()
                            if not progress or progress.status != "completed":
                                topic = step_title
                                break

                    full_topic = f"{topic} - {job_name}"
                    
                    # Check if already scheduled for this exact time
                    existing_job = db.query(ScheduledJob).filter(
                        ScheduledJob.student_id == student.id,
                        ScheduledJob.topic == full_topic,
                        ScheduledJob.scheduled_time == run_time
                    ).first()

                    if not existing_job:
                        # Schedule if it's in the future or exactly now
                        if run_time >= now:
                            logger.info(f"Pre-scheduling {job_type} ({full_topic}) for student {student.id} at {run_time}")
                            # await inside a sync loop? APScheduler is async, so we await
                            await self.schedule_homework(student.id, full_topic, run_time, is_auto=True, job_type=job_type)
                        elif run_time.hour == now.hour and run_time.minute == now.minute:
                            logger.info(f"Auto-triggering {job_type} ({full_topic}) for student {student.id}")
                            await self.schedule_homework(student.id, full_topic, now + timedelta(seconds=5), is_auto=True, job_type=job_type)

        except Exception as e:
            logger.error(f"Error in _check_auto_homework: {e}")
        finally:
            db.close()

    async def schedule_post_task_report(self, student_id: int, topic: str, run_time: datetime) -> None:
        try:
            self.scheduler.add_job(
                self._trigger_post_task_report,
                'date',
                run_date=run_time,
                args=[student_id, topic],
                id=f"post_task_report_{student_id}_{int(run_time.timestamp())}"
            )
            logger.info(f"Scheduled post-task report for student {student_id} at {run_time}")
        except Exception as e:
            logger.error(f"Failed to schedule post-task report: {e}")

    async def _trigger_post_task_report(self, student_id: int, topic: str):
        logger.info(f"Triggering post-task report for student {student_id} on {topic}")
        if not self.tutor_service:
            return
        
        db = SessionLocal()
        try:
            student = db.query(Student).filter(Student.id == student_id).first()
            if not student or not student.telegram_id:
                return

            report = await self.tutor_service.generate_daily_report(db, student.id, topic)
            if not report:
                return

            header = f"📊 **BÁO CÁO TÓM TẮT HẰNG NGÀY** 📊\n\n"
            full_report = header + report

            from backend.telegram.bot import send_telegram_message
            await send_telegram_message(student.telegram_id, full_report)

            # Also save to chat history
            ai_message = ChatMessage(
                student_id=student.id,
                sender="ai",
                message=full_report
            )
            db.add(ai_message)
            db.commit()
            logger.info(f"Sent post-task report to student {student.id}")
        except Exception as e:
            logger.error(f"Failed to send post-task report: {e}")
        finally:
            db.close()
