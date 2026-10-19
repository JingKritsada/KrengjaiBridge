"""Runtime settings, read from environment variables or `.env`."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.line"), extra="ignore")

    # OpenAI-compatible LLM endpoint. Course LiteLLM proxy (qwen3.5) in dev,
    # Huawei Cloud ModelArts MaaS (deepseek-v4.1-flash) when a MaaS key is set.
    llm_base_url: str = "https://llm.nattee.net/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen3.5"
    llm_timeout_s: float = 60.0
    # "openai" (LiteLLM, MaaS), "ollama" (native /api/chat), "lmstudio" (OpenAI-compatible with
    # reasoning_effort=none), or "auto": ollama when the URL uses port 11434, else openai.
    llm_api_style: str = "auto"
    # Optional secondary backend used when the primary fails (e.g. team GPU box over Tailscale).
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_model: str = ""
    llm_fallback_api_style: str = "auto"
    # A failed backend is skipped for this long; quota/auth errors (401/403/422...) use the long value.
    llm_cooldown_s: float = 60.0
    llm_cooldown_long_s: float = 600.0
    # The SDLC context judge is optional on top of rules; never let it hold up a request for long.
    llm_judge_timeout_s: float = 8.0

    # SQLite locally, RDS for PostgreSQL in the cloud.
    database_url: str = "sqlite:///./data/runtime/app.db"
    # Empty means in-process fakeredis; DCS Redis in the cloud.
    redis_url: str = ""

    # Fernet key that encrypts reply tokens (stand-in for a DEW/KMS data key).
    token_enc_key: str = ""

    line_channel_secret: str = ""
    line_channel_access_token: str = ""

    public_base_url: str = "http://localhost:8000"

    # Privacy pipeline knobs.
    k_anonymity: int = 3
    attacker_max_rounds: int = 3
    gate_max_delay_s: int = 20
    nudge_weekly_limit: int = 3

    @property
    def line_enabled(self) -> bool:
        return bool(self.line_channel_secret and self.line_channel_access_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()
