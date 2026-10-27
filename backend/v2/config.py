"""Runtime settings: process environment first, then the git-ignored repo-root .env."""
import os
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _dotenv():
    p = _ROOT / ".env"
    if not p.exists():
        return {}
    return dict(l.split("=", 1) for l in p.read_text().splitlines() if "=" in l and not l.startswith("#"))


_FILE = _dotenv()


def get(key, default=None):
    return os.environ.get(key) or _FILE.get(key) or default


ROOT = _ROOT
SESSION_IDLE_MINUTES = 30
SESSION_ABSOLUTE_HOURS = 8
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
COOKIE_NAME = "uetl_v2_session"
COOKIE_SECURE = get("UETL_COOKIE_SECURE", "true").lower() != "false"
