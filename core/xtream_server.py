"""A small local Xtream Codes server.

IPTV apps (IPTVnator, UHF, OneTV...) log into it like any Xtream provider and get your *edited*
list, split into Live / Movies / Series with categories. When you press play, they are sent to
the real provider (or the stream is relayed through this PC, if you pick that mode).
"""
from __future__ import annotations

import base64
import calendar
import collections
import gzip
import json
import logging
import logging.handlers
import os
import re
import threading
import time
import traceback
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from . import epg, placeholder
from .common import APP_DIR
from .exporter import _extinf
from .models import KINDS
from .xtream import DEFAULT_UA, XtreamClient, stream_url, timeshift_php_url, timeshift_url, xmltv_url

SERVER_DIR = APP_DIR / "xtream_server"
EPG_FILE = SERVER_DIR / "epg.xml.gz"
EPG_META = SERVER_DIR / "epg.meta.json"
STREAM_RE = re.compile(r"^/(live|movie|series)/([^/]+)/([^/]+)/([^/.]+)(?:\.(\w+))?$")
TIMESHIFT_RE = re.compile(r"^/timeshift/([^/]+)/([^/]+)/([^/]+)/([^/]+)/([^/.]+)(?:\.(\w+))?$")

LIST_ACTIONS = {
    "get_live_categories": ("cats", "live"), "get_vod_categories": ("cats", "vod"),
    "get_series_categories": ("cats", "series"),
    "get_live_streams": ("rows", "live"), "get_vod_streams": ("rows", "vod"),
    "get_series": ("rows", "series"),
}
CAT_ID_PARAM = "category_id"
GUIDE_RETRY_DELAYS = (1800, 7200)      # after a failed guide download: retry in 30 min, then 2 h, then give up until the next cycle
FAV_NAME = "\u2605 Favorites"
FAV_BASE = 1_000_000_000          # a favorite's copy gets id FAV_BASE + real id, so apps never see two items with one id


def fav_id(v):
    return FAV_BASE + int(v) if str(v).isdigit() else "fav-" + str(v)


def unfav(v):
    """Map a favorite-copy id back to the provider's real id (real ids pass through)."""
    v = str(v)
    if v.startswith("fav-"):
        return v[4:]
    if v.isdigit() and int(v) >= FAV_BASE:
        return str(int(v) - FAV_BASE)
    return v


# ======================================================================
# Snapshot: the edited library, frozen into what the API will serve
# ======================================================================
def _sid(v):
    return int(v) if str(v).isdigit() else str(v)


def _rating5(r):
    try:
        return round(float(r) / 2, 1)
    except (TypeError, ValueError):
        return 0


def category_ids(names, kind):
    """Stable numeric ids from the category name, so apps keep their caches/favorites
    when other categories come and go."""
    out, used = {}, set()
    for name in sorted(names, key=str.lower):
        cid = 100000 + zlib.crc32(f"{kind}|{name}".encode("utf-8")) % 900000
        while cid in used:
            cid += 1
        used.add(cid)
        out[name] = cid
    return out


def _entry(kind, it, n, cid, epg=None):
    cat = {"category_id": cid, "category_ids": [int(cid)]}
    if kind == "live":
        return {"num": n, "name": it.name, "stream_type": "live", "stream_id": _sid(it.id),
                "stream_icon": it.logo, "epg_channel_id": (epg if epg is not None else it.epg_id) or None,
                "added": it.added or "0", "is_adult": "0", "custom_sid": "", "tv_archive": 1 if it.arch else 0,
                "direct_source": "", "tv_archive_duration": it.arch or 0, **cat}
    if kind == "vod":
        return {"num": n, "name": it.name, "stream_type": "movie", "stream_id": _sid(it.id),
                "stream_icon": it.logo, "rating": it.rating or "0", "rating_5based": _rating5(it.rating),
                "added": it.added or "0", "is_adult": "0", "container_extension": it.ext or "mp4",
                "custom_sid": "", "direct_source": "", **cat}
    return {"num": n, "name": it.name, "series_id": _sid(it.id), "cover": it.logo, "plot": it.plot,
            "cast": "", "director": "", "genre": "", "releaseDate": "", "last_modified": it.added or "0",
            "rating": it.rating or "0", "rating_5based": _rating5(it.rating), "backdrop_path": [],
            "youtube_trailer": "", "episode_run_time": "0", **cat}


class Snapshot:
    def __init__(self, lib, placeholders=False):
        self.placeholders = placeholders
        self.fill = {}                 # {guide id: channel name} for placeholder guide entries (when on)
        self.conn = dict(lib.connection)
        self.use_provider_epg = lib.use_provider_epg
        self.extra_epg = list(lib.epg_sources)
        self.cats, self.rows, self.meta = {}, {}, {}
        self.wanted_epg = set()
        for kind in KINDS:
            active = [it for it in lib.ordered(kind) if not it.deleted and not it.gone]
            favs = [(n, it) for n, it in enumerate(active, 1) if it.fav]
            names = {it.category for it in active}
            if favs:
                names.add(FAV_NAME)
            ids = category_ids(names, kind)
            order = sorted(ids, key=lambda n: (n != FAV_NAME, n.lower()))      # favorites first
            self.cats[kind] = [{"category_id": str(ids[n]), "category_name": n, "parent_id": 0}
                               for n in order]
            rows, meta = [], {}
            for n, it in enumerate(active, 1):
                cid = str(ids[it.category])
                gid = placeholder.guide_id(it, placeholders) if kind == "live" else it.epg_id
                rows.append((cid, _entry(kind, it, n, cid, gid)))
                if kind == "live" and placeholders:
                    self.fill.setdefault(gid, it.name)
                m = {"name": it.name, "cid": cid, "logo": it.logo, "epg": gid, "ext": it.ext,
                     "plot": it.plot}
                if kind == "series":
                    m["skip"] = {e["id"] for e in (it.episodes or []) if e.get("skip")}
                    m["eps"] = it.episodes
                meta[it.id] = m
                if kind == "live" and it.epg_id:
                    self.wanted_epg.add(it.epg_id)
            fcid = str(ids[FAV_NAME]) if favs else None
            for n, it in favs:                       # copies, listed again under "Favorites"
                copy = _entry(kind, it, n, fcid, placeholder.guide_id(it, placeholders) if kind == "live" else it.epg_id)
                copy["series_id" if kind == "series" else "stream_id"] = _sid(fav_id(it.id))
                rows.append((fcid, copy))
            self.rows[kind], self.meta[kind] = rows, meta
        self._cache, self._lock = {}, threading.Lock()

    def counts(self):
        return {k: len(self.rows[k]) for k in KINDS}

    def payload(self, what, kind, cid=None):
        """(raw_json, gzipped_json) for a category list or stream list, cached."""
        key = (what, kind, cid)
        with self._lock:
            hit = self._cache.get(key)
        if hit:
            return hit
        if what == "cats":
            data = self.cats[kind]
        else:
            data = [e for c, e in self.rows[kind] if cid in (None, "") or c == cid]
        raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        hit = (raw, gzip.compress(raw, 5))
        with self._lock:
            self._cache[key] = hit
        return hit

    def epg_sources(self):
        out = []
        if self.use_provider_epg and self.conn.get("server"):
            out.append(("Provider guide", xmltv_url(self.conn)))
        for u in self.extra_epg:
            out.append((epg.label_for(u), u))
        return out


# ======================================================================
# Guide handling
# ======================================================================
def _xmltv_ts(s):
    if not s:
        return None
    parts = s.strip().split()
    try:
        t = calendar.timegm(time.strptime(parts[0][:14], "%Y%m%d%H%M%S"))
    except ValueError:
        return None
    if len(parts) > 1 and re.fullmatch(r"[+-]\d{4}", parts[1]):
        sign = 1 if parts[1][0] == "+" else -1
        t -= sign * (int(parts[1][1:3]) * 3600 + int(parts[1][3:5]) * 60)
    return t


def _b64(s):
    return base64.b64encode((s or "").encode("utf-8")).decode("ascii")


class LocalEpg:
    """Short-EPG lookups from the merged guide file (only a window around 'now' is kept in memory)."""

    def __init__(self, path, back_hours=2, fwd_hours=36):
        self.path, self.back, self.fwd = path, back_hours, fwd_hours
        self._idx, self._mtime, self._lock = None, None, threading.Lock()

    def _ensure(self):
        try:
            m = os.path.getmtime(self.path)
        except OSError:
            return False
        with self._lock:
            if self._idx is not None and self._mtime == m:
                return True
            now = time.time()
            lo, hi = now - 3600 * self.back, now + 3600 * self.fwd
            idx = collections.defaultdict(list)
            with epg.open_maybe_gz(self.path) as f:
                for el in epg.iter_top(f):
                    if el.tag != "programme":
                        continue
                    st, sp = _xmltv_ts(el.get("start")), _xmltv_ts(el.get("stop"))
                    if st is None or sp is None or sp < lo or st > hi:
                        continue
                    idx[el.get("channel")].append(
                        (st, sp, el.findtext("title") or "", (el.findtext("desc") or "")[:300]))
            for lst in idx.values():
                lst.sort()
            self._idx, self._mtime = idx, m
            return True

    def listings(self, epg_id, limit):
        if not epg_id or not self._ensure():
            return []
        now = time.time()
        out = []
        for st, sp, title, desc in self._idx.get(epg_id, ()):
            if sp <= now:
                continue
            fmt = lambda t: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))   # noqa: E731
            out.append({"id": str(st), "epg_id": epg_id, "title": _b64(title), "lang": "",
                        "start": fmt(st), "end": fmt(sp), "description": _b64(desc),
                        "channel_id": epg_id, "start_timestamp": str(st), "stop_timestamp": str(sp)})
            if len(out) >= limit:
                break
        return out


class EpgKeeper(threading.Thread):
    """Keeps one merged guide file (epg.xml.gz) fresh in the background."""

    def __init__(self, owner, hours):
        super().__init__(daemon=True)
        self.owner, self.hours = owner, max(1, hours)
        self.stop_evt, self.kick_evt = threading.Event(), threading.Event()
        self.status = "waiting"
        self.retries, self.retry_at, self.hold_until = 0, None, 0.0

    def kick(self):
        self.kick_evt.set()

    def stop(self):
        self.stop_evt.set()
        self.kick_evt.set()

    def _meta(self):
        try:
            return json.loads(EPG_META.read_text())
        except (OSError, ValueError):
            return {}

    def _sig(self, snap):
        urls = [u for _, u in snap.epg_sources()]
        fill = "\n".join(f"{g}\t{n}" for g, n in sorted(snap.fill.items()))
        return {"ids": zlib.crc32("\n".join(sorted(snap.wanted_epg)).encode()), "sources": urls,
                "local": [epg.local_stamp(u) for u in urls], "fill": zlib.crc32(fill.encode()) if fill else 0,
                "ph": bool(snap.placeholders)}

    def _due(self, snap, force):
        if force or not EPG_FILE.exists():
            return True
        meta = self._meta()
        age = time.time() - meta.get("ts", 0)
        if age > self.hours * 3600:
            return True
        sig = self._sig(snap)
        if meta.get("ph", False) != sig["ph"]:              # placeholders switched on or off: rebuild right away
            return True
        if meta.get("local") != sig["local"]:               # a guide file on this PC was replaced/edited
            return True
        return age > 900 and (meta.get("ids") != sig["ids"] or meta.get("sources") != sig["sources"]
                              or meta.get("fill", 0) != sig["fill"])

    def rebuild(self, snap):
        sources = snap.epg_sources()
        if not sources and not snap.fill:
            self.status = "no guide sources"
            return
        self.status = "reading guides..."
        usable, failed = [], 0
        for label, url in sources:
            p = epg.source_path(url)
            try:
                epg.download(url, p, self.owner.ua)
            except Exception as e:                              # noqa: BLE001
                failed += 1
                self.owner.log(f"guide download failed ({label}): {e}")
            if p.exists():
                usable.append((label, url))
        if not usable and not snap.fill:
            self.status = "failed: no guide could be downloaded"
            return failed or 1
        self.status = "merging guides..."
        SERVER_DIR.mkdir(parents=True, exist_ok=True)
        tmp = str(EPG_FILE) + ".tmp"
        stats = epg.merge_xmltv(usable, snap.wanted_epg, tmp, self.owner.ua, gz=True, fill=snap.fill)
        os.replace(tmp, EPG_FILE)
        meta = self._sig(snap)
        meta.update(ts=time.time(), **stats)
        EPG_META.write_text(json.dumps(meta))
        self.owner.local_epg = LocalEpg(str(EPG_FILE))
        extra = f", plus {stats['placeholders']:,} placeholders" if stats.get("placeholders") else ""
        self.status = (f"guide ready: {stats['channels']:,} channels{extra}, {stats['programs']:,} programs "
                       f"(updated {time.strftime('%H:%M')})")
        self.owner.log(self.status)
        return failed

    @staticmethod
    def _human(secs):
        return f"{secs // 3600} hour{'s' if secs // 3600 != 1 else ''}" if secs >= 3600 else f"{max(1, round(secs / 60))} minutes"

    def _after_attempt(self, failed):
        """A source failing to download schedules a couple of gentle retries, then waits for the normal cycle."""
        now = time.time()
        if not failed:
            self.retries, self.retry_at, self.hold_until = 0, None, 0.0
            return
        if self.retries < len(GUIDE_RETRY_DELAYS):
            delay = GUIDE_RETRY_DELAYS[self.retries]
            self.retries += 1
            self.retry_at = self.hold_until = now + delay
            self.owner.log(f"guide: {failed} source(s) couldn't be downloaded; trying again in {self._human(delay)} "
                           f"(retry {self.retries} of {len(GUIDE_RETRY_DELAYS)})")
        else:
            self.retries, self.retry_at = 0, None
            self.hold_until = now + self.hours * 3600
            self.owner.log(f"guide: still can't download everything; giving up for now and trying again at the "
                           f"next regular refresh (in about {self._human(self.hours * 3600)})")

    def run(self):
        force = False
        while not self.stop_evt.is_set():
            snap = self.owner.snap
            now = time.time()
            try:
                retrying = self.retry_at is not None and now >= self.retry_at
                if snap and (force or retrying or (now >= self.hold_until and self._due(snap, False))):
                    if force:
                        self.retries, self.retry_at, self.hold_until = 0, None, 0.0
                    self._after_attempt(self.rebuild(snap))
                elif snap and self.status == "waiting":
                    m = self._meta()
                    self.status = f"guide ready ({m.get('channels', 0):,} channels)"
            except Exception as e:                              # noqa: BLE001
                self.status = f"failed: {e}"
                self.owner.log(f"guide rebuild failed: {e}")
                self._after_attempt(1)
            wait = 900
            if self.retry_at:
                wait = max(1, min(900, self.retry_at - time.time()))
            self.kick_evt.wait(wait)
            force = self.kick_evt.is_set() and not self.stop_evt.is_set()
            self.kick_evt.clear()


# ======================================================================
# HTTP handler
# ======================================================================
def _mask(path):
    path = re.sub(r"(password=)[^&]*", r"\1***", path)
    path = re.sub(r"^(/(?:live|movie|series|timeshift)/[^/]+/)[^/]+/", r"\1***/", path)
    return path


class _Handler(BaseHTTPRequestHandler):
    server_version = "XtreamLocal/1.0"

    # -- plumbing ----------------------------------------------------
    def log_message(self, *a):
        pass

    def log_request(self, code="-", size="-"):
        self.srv.log(f"{self.client_address[0]}  {self.command} {_mask(self.path)}  ->  {code}")

    @property
    def srv(self):
        return self.server.owner

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", gz=None, extra=None):
        use_gz = gz is not None and "gzip" in self.headers.get("Accept-Encoding", "")
        data = gz if use_gz else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        if use_gz:
            self.send_header("Content-Encoding", "gzip")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            self._route()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:                                  # noqa: BLE001
            self.srv.log(f"ERROR {self.path}: {e}")
            logging.getLogger("xtream_server").error(traceback.format_exc())
            try:
                self._json({"error": str(e)}, 500)
            except OSError:
                pass

    # -- routing -----------------------------------------------------
    def _route(self):
        u = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query, keep_blank_values=True).items()}
        path = urllib.parse.unquote(u.path)
        srv = self.srv
        m = STREAM_RE.match(path)
        if m:
            kind, user, pw, sid, ext = m.groups()
            if not srv.auth(user, pw):
                return self._send(403, b"forbidden", "text/plain")
            return self._stream(kind, unfav(sid), ext)
        t = TIMESHIFT_RE.match(path)
        if t:                                           # catch-up, path style
            user, pw, dur, start, sid, ext = t.groups()
            if not srv.auth(user, pw):
                return self._send(403, b"forbidden", "text/plain")
            return self._play(timeshift_url(srv.snap.conn, unfav(sid), dur, start, ext or "ts"))
        if path == "/streaming/timeshift.php":          # catch-up, php style
            if not srv.auth(q.get("username"), q.get("password")):
                return self._send(403, b"forbidden", "text/plain")
            return self._play(timeshift_php_url(srv.snap.conn, unfav(q.get("stream", "")), q.get("duration", ""),
                                                q.get("start", "")))
        if path in ("/player_api.php", "/panel_api.php"):
            if not srv.auth(q.get("username"), q.get("password")):
                return self._json({"user_info": {"auth": 0}, "server_info": {}})
            return self._api(q)
        if path == "/xmltv.php":
            if not srv.auth(q.get("username"), q.get("password")):
                return self._send(403, b"forbidden", "text/plain")
            return self._xmltv()
        if path == "/get.php":
            if not srv.auth(q.get("username"), q.get("password")):
                return self._send(403, b"forbidden", "text/plain")
            return self._m3u()
        if path in ("/", "/index.html"):
            c = srv.snap.counts()
            return self._send(200, (f"Xtream Editor local server is running. Live {c['live']:,}, "
                                    f"Movies {c['vod']:,}, Series {c['series']:,}.").encode(), "text/plain")
        self._send(404, b"not found", "text/plain")

    # -- API ---------------------------------------------------------
    def _api(self, q):
        srv, snap = self.srv, self.srv.snap
        action = q.get("action")
        if not action or action == "get_account_info":
            return self._json(srv.account_info(self.headers.get("Host", "")))
        if action in LIST_ACTIONS:
            what, kind = LIST_ACTIONS[action]
            raw, gz = snap.payload(what, kind, q.get(CAT_ID_PARAM) or None)
            return self._send(200, raw, gz=gz)
        if action == "get_series_info":
            return self._json(srv.series_info(snap, unfav(q.get("series_id", ""))))
        if action == "get_vod_info":
            return self._json(srv.vod_info(snap, unfav(q.get("vod_id", ""))))
        if action == "get_simple_data_table":           # full-day guide incl. past shows (has_archive flags)
            return self._json(srv.day_epg(snap, unfav(q.get("stream_id", ""))))
        if action == "get_short_epg":
            return self._json(srv.short_epg(snap, unfav(q.get("stream_id", "")), int(q.get("limit") or 4)))
        self._json([])

    def _xmltv(self):
        srv = self.srv
        if srv.epg_mode == "provider":
            self.send_response(302)
            self.send_header("Location", xmltv_url(srv.snap.conn))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if srv.epg_mode == "none" or not EPG_FILE.exists():
            return self._send(200, b'<?xml version="1.0" encoding="UTF-8"?><tv></tv>', "application/xml")
        size = EPG_FILE.stat().st_size
        gz_ok = "gzip" in self.headers.get("Accept-Encoding", "")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        if gz_ok:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(size))
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(EPG_FILE, "rb") as raw:
            f = raw if gz_ok else gzip.GzipFile(fileobj=raw)
            while True:
                chunk = f.read(1 << 16)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def _m3u(self):
        srv, snap = self.srv, self.srv.snap
        base = f"http://{self.headers.get('Host') or srv.base_url().split('//')[1]}"
        u, p = urllib.parse.quote(srv.user, safe=""), urllib.parse.quote(srv.password, safe="")
        cat = {k: {c["category_id"]: c["category_name"] for c in snap.cats[k]} for k in KINDS}
        lines = ["#EXTM3U"]
        for kind, seg, defext in (("live", "live", "ts"), ("vod", "movie", "mp4")):
            for cid, e in snap.rows[kind]:
                sid = e["stream_id"]
                ext = defext if kind == "live" else e.get("container_extension", defext)
                lines.append(_extinf(e.get("epg_channel_id") or "", e["name"], e["stream_icon"], cat[kind][cid]))
                lines.append(f"{base}/{seg}/{u}/{p}/{sid}.{ext}")
        self._send(200, ("\n".join(lines) + "\n").encode("utf-8"), "audio/x-mpegurl; charset=utf-8")

    # -- playback ----------------------------------------------------
    def _stream(self, kind, sid, ext):
        kind = "vod" if kind == "movie" else kind               # URL says "movie", the library says "vod"
        conn = self.srv.snap.conn
        self._play(stream_url(conn, kind, sid, ext or ""))

    def _play(self, url):
        conn = self.srv.snap.conn
        if self.srv.stream_mode == "proxy":
            return self._proxy(url, conn.get("ua") or DEFAULT_UA)
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _proxy(self, url, ua):
        headers = {"User-Agent": ua}
        if self.headers.get("Range"):
            headers["Range"] = self.headers["Range"]
        try:
            r = requests.request("HEAD" if self.command == "HEAD" else "GET", url, headers=headers,
                                 stream=True, timeout=(10, 60), allow_redirects=True)
        except requests.RequestException as e:
            return self._send(502, f"provider unreachable: {e}".encode(), "text/plain")
        try:
            self.send_response(r.status_code)
            for k in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                if k in r.headers:
                    self.send_header(k, r.headers[k])
            self.end_headers()
            if self.command != "HEAD":
                for chunk in r.iter_content(1 << 16):
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass                                                # player stopped watching
        finally:
            r.close()


class _HTTPD(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


# ======================================================================
# The server object the app and the CLI use
# ======================================================================
class XtreamServer:
    def __init__(self):
        self.httpd = self.thread = self.snap = self.keeper = self.local_epg = None
        self.port = None
        self.user = self.password = ""
        self.stream_mode = "redirect"
        self.epg_mode = "merged"
        self.placeholders = False
        self.ua = DEFAULT_UA
        self.lines = collections.deque(maxlen=400)
        self.echo = None                      # optional callable(str), e.g. print for the CLI
        self._local = threading.local()
        self._pcache, self._plock = {}, threading.Lock()
        self._logger = None

    @property
    def running(self):
        return self.httpd is not None

    # -- lifecycle -----------------------------------------------------
    def start(self, lib, port, user, password, stream_mode="redirect", epg_mode="merged",
              epg_hours=12, host="0.0.0.0", placeholders=False):
        self.stop()
        if not lib.connection.get("server"):
            raise ValueError("No provider login in this project yet. Fetch from the server first.")
        self.user, self.password = user, password
        self.stream_mode, self.epg_mode = stream_mode, epg_mode
        self.ua = lib.connection.get("ua") or DEFAULT_UA
        self.placeholders = bool(placeholders) and epg_mode == "merged"
        self.snap = Snapshot(lib, self.placeholders)
        self._init_logger()
        self.httpd = _HTTPD((host, int(port)), _Handler)
        self.httpd.owner = self
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.local_epg = LocalEpg(str(EPG_FILE)) if epg_mode == "merged" else None
        if epg_mode == "merged":
            self.keeper = EpgKeeper(self, epg_hours)
            self.keeper.start()
        c = self.snap.counts()
        self.log(f"server started on port {self.port}: {c['live']:,} live, {c['vod']:,} movies, "
                 f"{c['series']:,} series ({stream_mode} mode)")

    def update(self, lib):
        """Swap in a fresh snapshot after edits. Cheap enough to call after every burst of changes."""
        if not self.running:
            return 0.0
        t = time.time()
        self.snap = Snapshot(lib, self.placeholders)
        with self._plock:
            self._pcache.clear()
        return time.time() - t

    def rebuild_guide(self):
        if self.keeper:
            self.keeper.kick()

    def stop(self):
        if self.keeper:
            self.keeper.stop()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.httpd = self.thread = self.keeper = None

    # -- helpers -------------------------------------------------------
    def _init_logger(self):
        if self._logger:
            return
        SERVER_DIR.mkdir(parents=True, exist_ok=True)
        lg = logging.getLogger("xtream_server")
        lg.setLevel(logging.INFO)
        if not lg.handlers:
            h = logging.handlers.RotatingFileHandler(SERVER_DIR / "server.log", maxBytes=1_000_000,
                                                     backupCount=2, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
            lg.addHandler(h)
        self._logger = lg

    def log(self, line):
        stamp = time.strftime("%H:%M:%S")
        self.lines.append(f"{stamp}  {line}")
        if self._logger:
            self._logger.info(line)
        if self.echo:
            try:
                self.echo(f"{stamp}  {line}")
            except Exception:                                   # noqa: BLE001
                pass

    def auth(self, user, pw):
        return user == self.user and pw == self.password

    def base_url(self):
        from .webserver import lan_ip
        return f"http://{lan_ip()}:{self.port}"

    def epg_status(self):
        if self.epg_mode == "provider":
            return "using the provider's own guide"
        if self.epg_mode == "none":
            return "no guide"
        return self.keeper.status if self.keeper else "off"

    def account_info(self, host):
        name, _, port = host.partition(":")
        return {
            "user_info": {"username": self.user, "password": self.password, "message": "",
                          "auth": 1, "status": "Active", "exp_date": "4102444800", "is_trial": "0",
                          "active_cons": "0", "created_at": "1600000000", "max_connections": "10",
                          "allowed_output_formats": ["m3u8", "ts"]},
            "server_info": {"url": name or "127.0.0.1", "port": port or str(self.port), "https_port": "",
                            "server_protocol": "http", "rtmp_port": "", "timezone": time.tzname[0],
                            "timestamp_now": int(time.time()),
                            "time_now": time.strftime("%Y-%m-%d %H:%M:%S")},
        }

    # -- calls to the real provider ---------------------------------------
    def _client(self, conn):
        key = tuple(sorted(conn.items()))
        if getattr(self._local, "key", None) != key:
            self._local.client = XtreamClient(**{**conn, "timeout": 25})
            self._local.key = key
        return self._local.client

    def provider_json(self, snap, action, ttl=0, **params):
        key = (action, tuple(sorted(params.items())))
        now = time.time()
        if ttl:
            with self._plock:
                hit = self._pcache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        try:
            data = self._client(snap.conn)._api(action, **params)
        except Exception as e:                                  # noqa: BLE001
            self.log(f"provider call {action} failed: {e}")
            return None
        if ttl and data:
            with self._plock:
                if len(self._pcache) > 800:
                    self._pcache.clear()
                self._pcache[key] = (now, data)
        return data

    def series_info(self, snap, sid):
        m = snap.meta["series"].get(sid)
        data = self.provider_json(snap, "get_series_info", ttl=1800, series_id=sid)
        if not isinstance(data, dict) or not data.get("episodes"):
            # provider unreachable: fall back on whatever episodes we already pulled
            eps = {}
            for e in (m or {}).get("eps") or []:
                eps.setdefault(str(e["season"]), []).append(
                    {"id": e["id"], "episode_num": e["ep"], "title": e["title"], "season": e["season"],
                     "container_extension": e.get("ext", "mp4"), "info": {}})
            data = {"seasons": [], "info": {}, "episodes": eps}
        else:
            data = dict(data)
            skip = (m or {}).get("skip") or set()
            raw = data["episodes"]
            if skip:
                if isinstance(raw, dict):
                    data["episodes"] = {s: [e for e in lst if str(e.get("id")) not in skip]
                                        for s, lst in raw.items()}
                elif isinstance(raw, list):
                    data["episodes"] = [[e for e in lst if str(e.get("id")) not in skip]
                                        if isinstance(lst, list) else lst for lst in raw]
        if m:                                                   # show your edits in the details page
            info = dict(data.get("info") or {})
            info.update(name=m["name"], cover=m["logo"], category_id=m["cid"])
            if m["plot"] and not info.get("plot"):
                info["plot"] = m["plot"]
            data["info"] = info
        return data

    def vod_info(self, snap, vid):
        m = snap.meta["vod"].get(vid)
        data = self.provider_json(snap, "get_vod_info", ttl=3600, vod_id=vid)
        if isinstance(data, dict) and data.get("info") is not None:
            data = dict(data)
            if m:
                md = dict(data.get("movie_data") or {})
                md.update(name=m["name"], category_id=m["cid"])
                data["movie_data"] = md
            return data
        return {"info": {"name": (m or {}).get("name", ""), "movie_image": (m or {}).get("logo", "")},
                "movie_data": {"stream_id": _sid(vid), "name": (m or {}).get("name", ""),
                               "category_id": (m or {}).get("cid", ""),
                               "container_extension": (m or {}).get("ext") or "mp4"}}

    def day_epg(self, snap, sid):
        """The provider's own day listing (it marks which past shows can still be watched via catch-up);
        falls back to the local guide's upcoming shows if the provider can't be reached."""
        if sid in snap.meta["live"]:
            data = self.provider_json(snap, "get_simple_data_table", ttl=300, stream_id=sid)
            if isinstance(data, dict) and data.get("epg_listings"):
                return data
        return self.short_epg(snap, sid, 20)

    def short_epg(self, snap, sid, limit):
        m = snap.meta["live"].get(sid)
        if not m:
            return {"epg_listings": []}
        if self.local_epg and m["epg"]:
            got = self.local_epg.listings(m["epg"], limit)
            if got:
                return {"epg_listings": got}
        data = self.provider_json(snap, "get_short_epg", stream_id=sid, limit=limit)
        if isinstance(data, dict) and data.get("epg_listings"):
            return data
        return {"epg_listings": []}
