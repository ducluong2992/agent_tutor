import asyncio
from backend.services.scheduler_service import SchedulerService

async def test():
    s = SchedulerService()
    await s.update_schedule(1)
    print('Done')

if __name__ == "__main__":
    asyncio.run(test())
