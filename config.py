import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Required environment variable {key!r} is not set. See .env.example.")
    return val


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# Microsoft Graph (Outlook)
AZURE_TENANT_ID = _optional("AZURE_TENANT_ID")
AZURE_CLIENT_ID = _optional("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = _optional("AZURE_CLIENT_SECRET")
OUTLOOK_USER_EMAIL = _optional("OUTLOOK_USER_EMAIL")

# Basecamp
BASECAMP_ACCOUNT_ID = _optional("BASECAMP_ACCOUNT_ID")
BASECAMP_ACCESS_TOKEN = _optional("BASECAMP_ACCESS_TOKEN")

# Dialpad
DIALPAD_API_KEY = _optional("DIALPAD_API_KEY")

# Zoom
ZOOM_ACCOUNT_ID = _optional("ZOOM_ACCOUNT_ID")
ZOOM_CLIENT_ID = _optional("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = _optional("ZOOM_CLIENT_SECRET")

# Clio Manage
CLIO_BASE_URL = _optional("CLIO_BASE_URL", "https://app.clio.com/api/v4")
CLIO_ACCESS_TOKEN = _optional("CLIO_ACCESS_TOKEN")

# Ajax
AJAX_BASE_URL = _optional("AJAX_BASE_URL", "")
AJAX_API_KEY = _optional("AJAX_API_KEY")
AJAX_TIMEKEEPER_ID = _optional("AJAX_TIMEKEEPER_ID")

# Anthropic
ANTHROPIC_API_KEY = _optional("ANTHROPIC_API_KEY")

# App
DAILY_SYNC_HOUR = int(_optional("DAILY_SYNC_HOUR", "8"))
PORT = int(_optional("PORT", "8000"))


def validate():
    """Call at startup to assert all required credentials are present."""
    missing = []
    required = {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "AJAX_BASE_URL": AJAX_BASE_URL,
        "AJAX_API_KEY": AJAX_API_KEY,
        "AJAX_TIMEKEEPER_ID": AJAX_TIMEKEEPER_ID,
    }
    for key, val in required.items():
        if not val:
            missing.append(key)
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in the values."
        )


def outlook_configured() -> bool:
    return bool(AZURE_TENANT_ID and AZURE_CLIENT_ID and AZURE_CLIENT_SECRET and OUTLOOK_USER_EMAIL)


def basecamp_configured() -> bool:
    return bool(BASECAMP_ACCOUNT_ID and BASECAMP_ACCESS_TOKEN)


def dialpad_configured() -> bool:
    return bool(DIALPAD_API_KEY)


def zoom_configured() -> bool:
    return bool(ZOOM_ACCOUNT_ID and ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET)


def clio_configured() -> bool:
    return bool(CLIO_ACCESS_TOKEN)
