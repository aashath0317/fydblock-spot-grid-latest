import asyncio
import time
from typing import Callable, List


class Scheduler:
    def __init__(self):
        self.tasks = []
        self.running = False

    def add_job(self, func: Callable, interval_seconds: int):
        self.tasks.append({"func": func, "interval": interval_seconds, "last_run": 0})

    async def run(self):
        self.running = True
        while self.running:
            now = time.time()
            for job in self.tasks:
                if now - job["last_run"] >= job["interval"]:
                    try:
                        if asyncio.iscoroutinefunction(job["func"]):
                            await job["func"]()
                        else:
                            job["func"]()
                        job["last_run"] = now
                    except Exception as e:
                        print(f"Job failed: {e}")

            await asyncio.sleep(1)

    def stop(self):
        self.running = False
