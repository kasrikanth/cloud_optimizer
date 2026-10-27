from pathlib import Path
from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / '.env',
        extra='ignore',
    )
    database_url: str = 'postgresql+psycopg://optimizer:invalid@127.0.0.1:5433/cloud_optimizer'
    session_hours: int = Field(default=12, ge=1, le=168)
    # Fernet key that encrypts cloud credentials at rest. Generate with scripts/setup.py.
    secrets_key: str = ''
    # Background collector schedule. Accounts in demo/aws/azure mode sync when older than the interval.
    sync_enabled: bool = True
    sync_interval_minutes: int = Field(default=60, ge=5, le=1440)
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    llm_api_key: str = ''
    llm_base_url: str = 'https://api.openai.com/v1'
    llm_model: str = ''

    @field_validator('llm_base_url')
    @classmethod
    def https_only(cls, value: str) -> str:
        if value and not value.startswith('https://'):
            raise ValueError('External integration URLs must use HTTPS')
        return value.rstrip('/')


@lru_cache
def get_settings() -> Settings:
    return Settings()
