"""Application settings loaded from the environment.

All runtime configuration is provided via environment variables (or a local
`.env` file). See `.env.example` at the repository root for documentation of
each variable.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "EHR Media Intelligence"
    environment: str = Field(default="development")

    anthropic_api_key: str = Field(default="")
    database_url: str = Field(default="sqlite:///./data/ehr.sqlite3")
    chroma_path: str = Field(default="./data/chroma")
    cors_origins: str = Field(default="http://localhost:5173")

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, parsed from a comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()
