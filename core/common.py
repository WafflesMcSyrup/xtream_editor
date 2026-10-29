"""Small shared bits: app folder, cancel exception."""
from __future__ import annotations

from pathlib import Path

APP_NAME = "Xtream Editor"
APP_VERSION = "6.4"
APP_DIR = Path.home() / ".xtream_editor"
CACHE_DIR = APP_DIR / "epg_cache"


class Cancelled(Exception):
    """Raised inside background jobs when the user hits Cancel."""


def noop_progress(pct: int, msg: str = "") -> None:
    pass


def never_cancelled() -> bool:
    return False
