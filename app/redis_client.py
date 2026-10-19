"""One shared local Redis, or an external Redis/DCS connection."""
from functools import lru_cache

import fakeredis
import redis

from app.config import get_settings


@lru_cache
def get_redis():
    url = get_settings().redis_url
    return redis.Redis.from_url(url, decode_responses=True) if url else fakeredis.FakeRedis(decode_responses=True)
