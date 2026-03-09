from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque

import redis

from .config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self._memory: dict[str, Deque[datetime]] = defaultdict(deque)
        self._redis = None
        try:
            client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
            client.ping()
            self._redis = client
        except Exception:
            # TODO: require Redis in hardened production deployments.
            self._redis = None

    def allow(self, key: str, *, limit: int = 8, window_seconds: int = 60) -> bool:
        now = datetime.now(timezone.utc)
        if self._redis is not None:
            bucket = f"rag:{key}"
            cutoff = now - timedelta(seconds=window_seconds)
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(bucket, 0, cutoff.timestamp())
            pipe.zcard(bucket)
            _, count = pipe.execute()
            if int(count) >= limit:
                return False
            self._redis.zadd(bucket, {now.isoformat(): now.timestamp()})
            self._redis.expire(bucket, window_seconds)
            return True

        q = self._memory[key]
        cutoff = now - timedelta(seconds=window_seconds)
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._memory.clear()
        if self._redis is not None:
            try:
                for key in self._redis.scan_iter(match="rag:*"):
                    self._redis.delete(key)
            except Exception:
                pass


rate_limiter = RateLimiter()
