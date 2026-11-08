"""Runtime configuration. Every value comes from a DCE_* environment variable (docs/api.md section 9)."""

import ipaddress
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_trusted_proxies(raw: str) -> tuple[IPNetwork, ...]:
    """Parse DCE_TRUSTED_PROXIES: comma-separated IP addresses or CIDR ranges. Empty means no trusted peers."""
    networks: list[IPNetwork] = []
    for item in raw.split(","):
        entry = item.strip()
        if entry:
            networks.append(ipaddress.ip_network(entry, strict=False))
    return tuple(networks)


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
    inference_connect_timeout_s: float = Field(default=5.0, gt=0, le=60)
    inference_read_timeout_s: float = Field(default=15.0, gt=0, le=120)
    inference_total_timeout_s: float = Field(default=20.0, gt=0, le=120)
    inference_max_retries: int = Field(default=2, ge=0, le=2)
    inference_retry_after_cap_s: float = Field(default=5.0, ge=0, le=30)
    inference_model_list_ttl_s: float = Field(default=600.0, ge=0, le=86400)
    inference_budget_input_tokens: int = Field(default=12_000, ge=1)
    inference_budget_output_tokens: int = Field(default=4_000, ge=1)

    sandbox_runner: Literal["docker", "local"] = "local"
    sandbox_image: str = "dce-worker:local"
    sandbox_max_concurrent: int = Field(default=1, ge=1, le=4)
    sandbox_timeout_s: int = Field(default=30, ge=1, le=30)
    sandbox_memory_mb: int = Field(default=512, ge=16, le=512)
    sandbox_pids: int = Field(default=64, ge=1, le=64)

    cookie_secure: bool = False
    quota_tasks_per_day: int = Field(default=20, ge=0)
    cors_origins: str = "http://localhost:8000"  # comma-separated
    # Comma-separated IPs or CIDRs. Only these direct peers may supply X-Forwarded-For (docs/api.md section 9).
    trusted_proxies: str = ""
    seed_password: SecretStr | None = None

    # Outgoing email for password reset (SMTP with STARTTLS, for example Gmail with an app password).
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    # Base of the links in reset emails, without a trailing slash, for example https://commander.basyid.dev
    public_base_url: str = "http://localhost:8000"

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password.get_secret_value())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_proxy_networks(self) -> tuple[IPNetwork, ...]:
        return parse_trusted_proxies(self.trusted_proxies)

    @property
    def frontend_enabled(self) -> bool:
        if self.serve_frontend is None:
            return self.env != "production"
        return self.serve_frontend

    @model_validator(mode="after")
    def _check_production_rules(self) -> "Settings":
        _ = self.trusted_proxy_networks  # raises ValueError for a malformed DCE_TRUSTED_PROXIES entry
        if self.env == "production" and self.sandbox_runner == "local":
            raise ValueError("DCE_SANDBOX_RUNNER=local is refused when DCE_ENV=production")
        if self.inference_mode == "vultr" and (not self.vultr_inference_key.get_secret_value() or not self.inference_model):
            raise ValueError("DCE_INFERENCE_MODE=vultr requires DCE_VULTR_INFERENCE_KEY and DCE_INFERENCE_MODEL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
