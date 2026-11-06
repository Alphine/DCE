"""Runtime configuration. Every value comes from a DCE_* environment variable (docs/api.md section 9)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DCE_", extra="ignore")

    env: Literal["development", "production"] = "development"
    data_dir: Path = Path("./data")
    database_path: Path = Path("./data/dce.sqlite3")
    serve_frontend: bool | None = None  # None: true outside production
    frontend_dir: Path = Path("../frontend")

    inference_mode: Literal["mock", "vultr"] = "mock"
    inference_base_url: str = "https://api.vultrinference.com/v1"
    inference_model: str = ""
    vultr_inference_key: SecretStr = SecretStr("")

    sandbox_runner: Literal["docker", "local"] = "local"
    sandbox_image: str = "dce-worker:local"
    sandbox_max_concurrent: int = Field(default=1, ge=1, le=4)
    sandbox_timeout_s: int = Field(default=30, ge=1, le=30)
    sandbox_memory_mb: int = Field(default=512, ge=16, le=512)
    sandbox_pids: int = Field(default=64, ge=1, le=64)

    cookie_secure: bool = False
    quota_tasks_per_day: int = Field(default=20, ge=0)
    cors_origins: str = "http://localhost:8000"  # comma-separated
    seed_password: SecretStr | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def frontend_enabled(self) -> bool:
        if self.serve_frontend is None:
            return self.env != "production"
        return self.serve_frontend

    @model_validator(mode="after")
    def _check_production_rules(self) -> "Settings":
        if self.env == "production" and self.sandbox_runner == "local":
            raise ValueError("DCE_SANDBOX_RUNNER=local is refused when DCE_ENV=production")
        if self.inference_mode == "vultr" and (not self.vultr_inference_key.get_secret_value() or not self.inference_model):
            raise ValueError("DCE_INFERENCE_MODE=vultr requires DCE_VULTR_INFERENCE_KEY and DCE_INFERENCE_MODEL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
