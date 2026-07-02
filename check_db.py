import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from backend.database.db import SessionLocal
from backend.database.models import ScheduledJob

db = SessionLocal()
jobs = db.query(ScheduledJob).order_by(ScheduledJob.id.desc()).limit(10).all()
for j in jobs:
    print(f'ID={j.id} type={j.job_type} status={j.status} time={j.scheduled_time} auto={j.is_auto}')
db.close()
