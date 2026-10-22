"""Xtream Codes API client: login, categories, streams, series episodes, URL building."""
from __future__ import annotations

import re
import time
import urllib.parse

import requests

from .common import Cancelled, never_cancelled, noop_progress
from .models import Item

DEFAULT_UA = "VLC/3.0.20 LibVLC/3.0.20"


class XtreamError(Exception):
    pass


def normalize_server(server):
    s = (server or "").strip()
    if not s:
        raise XtreamError("Server URL is empty.")
    if "://" not in s:
        s = "http://" + s
    return s.rstrip("/")


def parse_link(text):
    """Pull server/username/password out of a pasted get.php, player_api.php,
    xmltv.php or stream URL. Returns None if it doesn't look like one."""
    text = (text or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "http://" + text
    u = urllib.parse.urlparse(text)
    if not u.netloc:
        return None
    q = urllib.parse.parse_qs(u.query)
    user = (q.get("username") or [""])[0]
    pw = (q.get("password") or [""])[0]
    if user and pw:
        base = re.sub(r"/(get|player_api|xmltv|panel_api|portal)\.php$", "", u.path)
    else:
        m = re.match(r"^(.*?)/(?:live|movie|series)/([^/]+)/([^/]+)/[^/]+$", u.path)
        if not m:
            return None
        base = m.group(1)
        user = urllib.parse.unquote(m.group(2))
        pw = urllib.parse.unquote(m.group(3))
    server = f"{u.scheme}://{u.netloc}{base.rstrip('/')}"
    return {"server": server, "username": user, "password": pw}


def _q(s):
    return urllib.parse.quote(str(s), safe="")


def stream_url(conn, kind, sid, ext=""):
    server = normalize_server(conn["server"])
    u, p = _q(conn["username"]), _q(conn["password"])
    if kind == "live":
        return f"{server}/live/{u}/{p}/{sid}.{ext or 'ts'}"
    if kind == "vod":
        return f"{server}/movie/{u}/{p}/{sid}.{ext or 'mp4'}"
    return f"{server}/series/{u}/{p}/{sid}.{ext or 'mp4'}"


def timeshift_url(conn, stream_id, duration, start, ext="ts"):
    """Catch-up address, path style: /timeshift/user/pass/<minutes>/<start>/<id>.ts"""
    server = normalize_server(conn["server"])
    return (f"{server}/timeshift/{_q(conn['username'])}/{_q(conn['password'])}/"
            f"{_q(str(duration))}/{_q(str(start))}/{stream_id}.{ext or 'ts'}")


def timeshift_php_url(conn, stream_id, duration, start):
    """Catch-up address, php style: /streaming/timeshift.php?username=..&password=..&stream=..&start=..&duration=.."""
    server = normalize_server(conn["server"])
    return (f"{server}/streaming/timeshift.php?username={_q(conn['username'])}&password={_q(conn['password'])}"
            f"&stream={_q(str(stream_id))}&start={_q(str(start))}&duration={_q(str(duration))}")


def xmltv_url(conn):
    server = normalize_server(conn["server"])
    return f"{server}/xmltv.php?username={_q(conn['username'])}&password={_q(conn['password'])}"


def _s(v):
    return "" if v is None else str(v).strip()


class XtreamClient:
    def __init__(self, server, username, password, ua=DEFAULT_UA, timeout=90, **_ignored):
        self.server = normalize_server(server)
        self.username = username
        self.password = password
        self.ua = ua or DEFAULT_UA
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.ua, "Accept": "*/*"})

    def _api(self, action=None, **extra):
        params = {"username": self.username, "password": self.password}
        if action:
            params["action"] = action
        params.update(extra)
        url = f"{self.server}/player_api.php"
        last = None
        for attempt in range(4):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:      # dropped connection, cut-off download, timeout...
                last = e
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code in (401, 403):
                raise XtreamError(
                    f"Server refused the request (HTTP {r.status_code}). "
                    "Check the login, or try a different User-Agent.")
            if r.status_code >= 500 and attempt < 3:
                last = XtreamError(f"HTTP {r.status_code}")
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise XtreamError(f"Server answered HTTP {r.status_code}.")
            try:
                return r.json()
            except ValueError:
                raise XtreamError(
                    "Server didn't return JSON. The URL may be wrong, or the provider "
                    "blocks this client.")
        raise XtreamError(
            "The connection to the server kept dropping, so the list couldn't be downloaded "
            f"(tried {attempt + 1} times). The provider may be busy, or the account may already be in use on "
            f"another player (one connection per account). Try again in a few minutes.\nDetails: {last}"
            if isinstance(last, (requests.exceptions.ChunkedEncodingError, requests.exceptions.ContentDecodingError))
            else f"Could not reach the server: {last}")

    def authenticate(self):
        data = self._api()
        if not isinstance(data, dict) or "user_info" not in data:
            raise XtreamError("Unexpected login response from server.")
        ui = data["user_info"]
        if str(ui.get("auth", "1")) != "1":
            raise XtreamError("Login failed (server says auth=0). Check username/password.")
        return data

    def get_list(self, action):
        data = self._api(action)
        if isinstance(data, dict):          # a few panels wrap lists in a dict
            data = list(data.values())
        return data if isinstance(data, list) else []

    def conn_dict(self):
        return {"server": self.server, "username": self.username,
                "password": self.password, "ua": self.ua}


_ACTIONS = {
    "live": ("get_live_categories", "get_live_streams"),
    "vod": ("get_vod_categories", "get_vod_streams"),
    "series": ("get_series_categories", "get_series"),
}


def _first_cat_id(s):
    cid = s.get("category_id")
    if cid in (None, "") and isinstance(s.get("category_ids"), list) and s["category_ids"]:
        cid = s["category_ids"][0]
    return _s(cid)


def _archive_days(s):
    """Days of catch-up the provider keeps for a live channel (0 = none)."""
    if str(s.get("tv_archive") or "0").strip().lower() not in ("1", "true", "yes"):
        return 0
    try:
        days = int(float(s.get("tv_archive_duration") or 0))
    except (TypeError, ValueError):
        days = 0
    return days if days > 0 else 1


def _build_item(kind, s, cats, idx):
    cid = _first_cat_id(s)
    cat = cats.get(cid) or "Uncategorized"
    if kind == "live":
        it = Item("live", s.get("stream_id"), _s(s.get("name")), cat, cid,
                  logo=_s(s.get("stream_icon")), epg_id=_s(s.get("epg_channel_id")),
                  ext="ts", num=idx, added=_s(s.get("added")))
        it.arch = _archive_days(s)
        return it
    if kind == "vod":
        return Item("vod", s.get("stream_id"), _s(s.get("name")), cat, cid,
                    logo=_s(s.get("stream_icon")),
                    ext=_s(s.get("container_extension")) or "mp4",
                    num=idx, added=_s(s.get("added")), rating=_s(s.get("rating")))
    return Item("series", s.get("series_id"), _s(s.get("name")), cat, cid,
                logo=_s(s.get("cover")), num=idx, added=_s(s.get("last_modified")),
                rating=_s(s.get("rating")), plot=_s(s.get("plot")))


def fetch_all(client, progress=noop_progress, cancelled=never_cancelled):
    """Pull everything the account offers. Returns {"items", "info", "warnings"}."""
    def check():
        if cancelled():
            raise Cancelled()

    progress(1, "Logging in...")
    info = client.authenticate()
    items, warnings = [], []
    plan = [("live", "Live channels"), ("vod", "Movies"), ("series", "Series")]
    for n, (kind, label) in enumerate(plan):
        base = 5 + n * 31
        check()
        cat_action, list_action = _ACTIONS[kind]
        progress(base, f"{label}: categories...")
        try:
            cats = {}
            for c in client.get_list(cat_action):
                if isinstance(c, dict):
                    cats[_s(c.get("category_id"))] = _s(c.get("category_name")) or "Uncategorized"
            check()
            progress(base + 10, f"{label}: downloading list...")
            raw = client.get_list(list_action)
        except Cancelled:
            raise
        except XtreamError as e:
            warnings.append(f"{label}: {e}")
            continue
        check()
        progress(base + 24, f"{label}: processing {len(raw):,} entries...")
        for idx, s in enumerate(raw):
            if isinstance(s, dict):
                items.append(_build_item(kind, s, cats, idx))
    progress(100, "Done")
    return {"items": items, "info": info, "warnings": warnings}


def fetch_episodes(client, series_id):
    """Episodes for one series as a list of dicts (id, season, ep, title, ext)."""
    data = client._api("get_series_info", series_id=series_id)
    raw = data.get("episodes") if isinstance(data, dict) else None
    if isinstance(raw, dict):
        groups = list(raw.items())
    elif isinstance(raw, list):
        groups = [(None, g) for g in raw]
    else:
        groups = []
    out = []
    for season_key, lst in groups:
        if isinstance(lst, dict):
            lst = list(lst.values())
        for e in lst or []:
            if not isinstance(e, dict) or e.get("id") in (None, ""):
                continue
            season = e.get("season", season_key)
            try:
                season = int(season)
            except (TypeError, ValueError):
                season = 0
            try:
                epn = int(e.get("episode_num") or 0)
            except (TypeError, ValueError):
                epn = 0
            out.append({"id": _s(e.get("id")), "season": season, "ep": epn,
                        "title": _s(e.get("title")),
                        "ext": _s(e.get("container_extension")) or "mp4"})
    out.sort(key=lambda x: (x["season"], x["ep"]))
    return out
