"""Application settings, read from environment variables (see .env.example).

No secrets are hardcoded. If SECRET_KEY is unset, a random per-process key is generated
(fine for local development; tokens then die on restart).
"""
from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
logger = logging.getLogger(__name__)


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines; real environment variables always win)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_dotenv(PROJECT_DIR / ".env")

SYNTHETIC_NOTICE = ("All data in this project is SYNTHETIC. No real identity documents, PAN/Aadhaar numbers, "
                    "bank accounts or customers are used.")
DEMO_RULES_NOTICE = ("Rules are DEMONSTRATION rules for a portfolio project. They are not legal, RBI or "
                     "regulatory requirements.")


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", f"sqlite:///{(PROJECT_DIR / 'data' / 'loan_compliance.db').as_posix()}"))
    upload_dir: Path = field(default_factory=lambda: Path(os.environ.get("UPLOAD_DIR", PROJECT_DIR / "data" / "uploads")))
    max_upload_mb: float = field(default_factory=lambda: _env_float("MAX_UPLOAD_MB", 10))
    secret_key: str = field(default_factory=lambda: os.environ.get("SECRET_KEY") or secrets.token_urlsafe(48))
    token_ttl_minutes: int = field(default_factory=lambda: int(_env_float("TOKEN_TTL_MINUTES", 480)))
    cors_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()])
    # demo users are created ONLY when the users table is empty; change these outside demos
    demo_admin_password: str = field(default_factory=lambda: os.environ.get("DEMO_ADMIN_PASSWORD", "Admin#Demo2026"))
    demo_reviewer_password: str = field(default_factory=lambda: os.environ.get("DEMO_REVIEWER_PASSWORD", "Review#Demo2026"))
    seed_demo_users: bool = field(default_factory=lambda: _env_bool("SEED_DEMO_USERS", True))
    # OCR / classification
    ocr_enabled: bool = field(default_factory=lambda: _env_bool("OCR_ENABLED", True))
    ocr_dpi: int = field(default_factory=lambda: int(_env_float("OCR_DPI", 200)))
    classification_min_confidence: float = field(default_factory=lambda: _env_float("CLASSIFICATION_MIN_CONFIDENCE", 0.5))
    # optional LLM (Anthropic Messages API). Empty key => deterministic extraction only.
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "claude-sonnet-5-5"))
    llm_timeout_s: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT_S", 30))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings(**overrides) -> Settings:
    """Rebuild settings (tests / scripts). Keyword overrides replace individual fields."""
    global _settings
    _settings = Settings()
    for k, v in overrides.items():
        setattr(_settings, k, v)
    return _settings
