"""Redis-backed confirmation gate; never called by preview generation."""

import hashlib
import json
import secrets

from app.config import get_settings


def count_range(n: int) -> str:
    if n < 3:
        return "รอสมาชิกเพิ่มเติม"
    if n <= 5:
        return "3–5 คน"
    lower = 6 + ((n - 6) // 5) * 5
    return f"{lower}–{lower + 4} คน"


class KGate:
    def __init__(self, redis, k: int | None = None, max_delay_s: int | None = None):
        settings = get_settings()
        self.redis = redis
        self.k = settings.k_anonymity if k is None else k
        self.max_delay_s = settings.gate_max_delay_s if max_delay_s is None else max_delay_s
        if self.k < 3 or self.max_delay_s < 0:
            raise ValueError("Gate requires k >= 3 and a nonnegative delay")

    @staticmethod
    def _key(team_id: str, theme_slug: str) -> str:
        digest = hashlib.sha256(json.dumps([team_id, theme_slug]).encode()).hexdigest()
        return f"privacy:gate:{digest}"

    def add(self, team_id: str, theme_slug: str, item_id: str) -> int:
        with self.redis.pipeline() as pipe:
            pipe.sadd(self._key(team_id, theme_slug), item_id)
            pipe.scard(self._key(team_id, theme_slug))
            return int(pipe.execute()[-1])

    def count(self, team_id: str, theme_slug: str) -> int:
        return int(self.redis.scard(self._key(team_id, theme_slug)))

    def is_open(self, team_id: str, theme_slug: str) -> bool:
        return self.count(team_id, theme_slug) >= self.k

    def release_delay(self) -> int:
        return secrets.randbelow(self.max_delay_s + 1)

    count_range = staticmethod(count_range)
