import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default)


# Twilio
TWILIO_ACCOUNT_SID = _require("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _require("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = _require("TWILIO_PHONE_NUMBER")

# Anthropic / OpenRouter
ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = _optional("ANTHROPIC_BASE_URL")
CLAUDE_MODEL = _optional("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# Google Chat
GOOGLE_CHAT_WEBHOOK_URL = _optional("GOOGLE_CHAT_WEBHOOK_URL")

# Gmail
GOOGLE_CLIENT_ID = _optional("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _optional("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = _optional("GOOGLE_REFRESH_TOKEN")
GMAIL_FROM_ADDRESS = _optional("GMAIL_FROM_ADDRESS")
GMAIL_TO_ADDRESS = _optional("GMAIL_TO_ADDRESS")

# Server
PORT = int(_optional("PORT", "8080"))
HOST = _optional("HOST", "0.0.0.0")
BASE_URL = _optional("BASE_URL", "http://localhost:8080")

# Claude
CLAUDE_TIMEOUT = int(_optional("CLAUDE_TIMEOUT", "30"))

# CSV
CSV_OUTPUT_DIR = _optional("CSV_OUTPUT_DIR", "./data")

# Logging
ENV = _optional("ENV", "development")

# Admin
ADMIN_API_KEY = _optional("ADMIN_API_KEY")
