"""Lightweight in-process latency instrumentation for the dashboard pipeline."""

import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict

from app.core.config import settings


class MetricsRegistry:
    """Rolling samples for request totals and named pipeline stages."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: deque = deque(maxlen=settings.LATENCY_SAMPLE_SIZE)
        self._stages: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=settings.LATENCY_SAMPLE_SIZE)
        )

    def record_request(self, path: str, duration_ms: float) -> None:
        with self._lock:
            self._requests.append((path, duration_ms))

    def record_stage(self, stage: str, duration_ms: float) -> None:
        with self._lock:
            self._stages[stage].append(duration_ms)

    @staticmethod
    def _summary(values) -> Dict[str, float]:
        if not values:
            return {"count": 0, "avg_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(values)
        p95_index = max(0, int(len(ordered) * 0.95) - 1)
        return {
            "count": len(ordered),
            "avg_ms": round(sum(ordered) / len(ordered), 2),
            "p95_ms": round(ordered[p95_index], 2),
            "max_ms": round(ordered[-1], 2),
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            samples = [value for _, value in self._requests]
            stages = {name: list(values) for name, values in self._stages.items()}
        return {
            "requests": self._summary(samples),
            "stages": {name: self._summary(values) for name, values in stages.items()},
            "sample_size": settings.LATENCY_SAMPLE_SIZE,
            "generated_at": time.time(),
        }


metrics = MetricsRegistry()
