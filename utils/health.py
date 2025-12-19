import time
from typing import Dict


class HealthMonitor:
    def __init__(self):
        self._errors = 0
        self._warnings = 0
        self._api_latency = []
        self._last_heartbeat = time.time()

    def log_error(self):
        self._errors += 1

    def log_warning(self):
        self._warnings += 1

    def record_latency(self, latency_ms: float):
        self._api_latency.append(latency_ms)
        if len(self._api_latency) > 100:
            self._api_latency.pop(0)

    def heartbeat(self):
        self._last_heartbeat = time.time()

    def get_stats(self) -> Dict:
        avg_latency = (
            sum(self._api_latency) / len(self._api_latency) if self._api_latency else 0
        )
        return {
            "status": "HEALTHY"
            if (time.time() - self._last_heartbeat) < 60
            else "STALLED",
            "errors_last_hour": self._errors,  # TODO: Reset hourly
            "warnings_count": self._warnings,
            "avg_api_latency_ms": round(avg_latency, 2),
            "last_heartbeat": self._last_heartbeat,
        }


# Global Instance
health_system = HealthMonitor()
