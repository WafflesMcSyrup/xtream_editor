"""Remembers login details and a few paths between runs (plain JSON in your home folder)."""
from __future__ import annotations

import json

from .common import APP_DIR
from .xtream import DEFAULT_UA

_FILE = APP_DIR / "settings.json"
DEFAULTS = {
    "server": "", "username": "", "password": "", "ua": DEFAULT_UA,
    "last_project": "", "export_dir": "", "export_base": "playlist",
    "serve_port": 8765,
    # local Xtream server
    "xs_port": 8090, "xs_user": "local", "xs_pass": "", "xs_mode": "redirect",
    "xs_epg": "merged", "xs_epg_hours": 12, "xs_placeholders": False,
    "xs_refresh_at": "03:00",
}


def make_password(n=8):
    import secrets
    import string
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def load():
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return data


def save(data):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
