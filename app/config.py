"""Application configuration loaded from environment variables."""

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "app.db")))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(DATA_DIR / "uploads")))

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
APP_NAME = os.getenv("APP_NAME", "Video Scheduler")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

TIKTOK_CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
TIKTOK_REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "").strip() or (
    f"{BASE_URL}/auth/tiktok/callback"
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Scopes requested during Login Kit authorization.
# video.publish = Direct Post, video.upload = upload to the creator's inbox.
TIKTOK_SCOPES = os.getenv(
    "TIKTOK_SCOPES", "user.info.basic,video.upload,video.publish"
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Without real credentials the app stays fully usable in demo mode: every
# screen works, uploads are simulated and nothing is sent to TikTok.
DEMO_MODE = _env_bool(
    "DEMO_MODE", not (TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET)
)

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))
