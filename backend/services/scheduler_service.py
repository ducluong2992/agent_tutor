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
                # Weekly report: every Sunday at 20:00
                self.scheduler.add_job(
                    self._send_weekly_reports,
                    'cron',
                    day_of_week='sun',
                    hour=20,
                    minute=0,
                    id='weekly_report',
                    replace_existing=True
                )
                # Daily report: every day at 20:30
                self.scheduler.add_job(
                    self._send_daily_reports,
                    'cron',
                    hour=20,
                    minute=30,
                    id='daily_report',
                    replace_existing=True
                )
                logger.info("APScheduler started successfully with auto-homework, daily and weekly report jobs.")
            except Exception as e:
                logger.error(f"Failed to start APScheduler: {e}")

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("APScheduler stopped.")

    def set_tutor_service(self, tutor_service):
        self.tutor_service = tutor_service

    async def schedule_homework(self, student_id: int, topic: str, run_time: datetime, is_auto: bool = False) -> int:
        db = SessionLocal()
        try:
            db_job = ScheduledJob(
                student_id=student_id,
                job_type="homework",
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
            logger.info(f"Scheduled homework job {db_job.id} for student {student_id} at {run_time}")
            return db_job.id
        except Exception as e:
            logger.error(f"Failed to schedule homework: {e}")
            db.rollback()
            raise e
        finally:
            db.close()

    async def _trigger_homework_job(self, student_id: int, job_id: int, topic: str):
        logger.info(f"Triggering homework job {job_id} for student {student_id}")
        db = SessionLocal()
        try:
            job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
            if not job or job.status != "pending":
                logger.warning(f"Job {job_id} not found or not pending.")
                return

            job.status = "sent"
            db.commit()

            if self.tutor_service:
                homework_text = await self.tutor_service.generate_homework(student_id, topic)

                ai_message = ChatMessage(
                    student_id=student_id,
                    sender="ai",
                    message=homework_text
                )
                db.add(ai_message)
                db.commit()

                student = db.query(Student).filter(Student.id == student_id).first()
                if student and student.telegram_id:
                    from backend.telegram.bot import send_telegram_message
                    tele_message = (
                        f"📝 **BÀI TẬP VỀ NHÀ MỚI** 📝\n\n"
                        f"Chủ đề: **{topic}**\n\n"
                        f"{homework_text}\n\n"
                        f"📌 Hãy trả lời bài tập này trực tiếp qua chat để được chấm điểm!"
                    )
                    await send_telegram_message(student.telegram_id, tele_message)
                    logger.info(f"Sent homework to student {student_id} via Telegram.")
                else:
                    logger.info(f"Student {student_id} has no Telegram linked. Homework saved to database.")
            else:
                logger.error("Tutor service not set in Scheduler.")
        except Exception as e:
            logger.error(f"Error executing homework job {job_id}: {e}")
        finally:
            db.close()

    async def _check_auto_homework(self):
        """Run every minute: check if any student's scheduled homework time has arrived."""
        db = SessionLocal()
        try:
            now = datetime.now()
            current_time_str = now.strftime("%H:%M")

            students = db.query(Student).filter(Student.homework_frequency > 0).all()
            for student in students:
                if student.homework_time != current_time_str:
                    continue

                # Always trigger if the current time matches the configured time.
                # Since this function runs every minute, it will only match once per day.
                should_trigger = True

                if not should_trigger:
                    continue

                # Find the next uncompleted topic in the student's active roadmap
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

                logger.info(f"Auto-triggering homework for student {student.id}: '{topic}'")
                await self.schedule_homework(student.id, topic, now + timedelta(seconds=5), is_auto=True)

        except Exception as e:
            logger.error(f"Error in _check_auto_homework: {e}")
        finally:
            db.close()

    async def _send_weekly_reports(self):
        """Send weekly learning evaluation reports to all students with Telegram linked."""
        if not self.tutor_service:
            logger.warning("Tutor service not set. Cannot send weekly reports.")
            return

        db = SessionLocal()
        try:
            students = db.query(Student).filter(Student.telegram_id.isnot(None)).all()
            for student in students:
                try:
                    report = await self.tutor_service.generate_weekly_report(db, student.id)
                    if not report:
                        continue

                    header = f"📊 **BÁO CÁO HỌC TẬP TUẦN** 📊\n\n"
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
                    logger.info(f"Sent weekly report to student {student.id}")
                except Exception as e:
                    logger.error(f"Failed to send weekly report for student {student.id}: {e}")
        except Exception as e:
            logger.error(f"Error in _send_weekly_reports: {e}")
        finally:
            db.close()

    async def _send_daily_reports(self):
        """Send daily learning evaluation reports to all students with Telegram linked."""
        if not self.tutor_service:
            logger.warning("Tutor service not set. Cannot send daily reports.")
            return

        db = SessionLocal()
        try:
            students = db.query(Student).filter(Student.telegram_id.isnot(None)).all()
            for student in students:
                try:
                    report = await self.tutor_service.generate_daily_report(db, student.id)
                    if not report:
                        continue

                    header = f"📊 **BÁO CÁO HỌC TẬP NGÀY** 📊\n\n"
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
                    logger.info(f"Sent daily report to student {student.id}")
                except Exception as e:
                    logger.error(f"Failed to send daily report for student {student.id}: {e}")
        except Exception as e:
            logger.error(f"Error in _send_daily_reports: {e}")
        finally:
            db.close()
