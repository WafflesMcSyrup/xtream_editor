"""Fake Xtream server for trying the editor without a real provider.

    python mock_server.py                       # 2,000 live / 800 movies / 300 series
    python mock_server.py --live 60000 --vod 20000 --series 5000   # stress test

Then in the app use:  http://127.0.0.1:8080/get.php?username=demo&password=demo&type=m3u_plus
"""
import argparse
import gzip
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ARGS = None
LIVE, VOD, SERIES = [], [], []
CATS = {"live": [], "vod": [], "series": []}
GENRES = ["News", "Sports", "Movies", "Kids", "Music", "Documentary", "Comedy", "Drama"]
COUNTRIES = ["US", "UK", "CA", "DE", "FR", "ES"]


def build():
    for i, c in enumerate(COUNTRIES):
        for j, g in enumerate(GENRES):
            CATS["live"].append({"category_id": str(i * 10 + j), "category_name": f"{c} | {g}"})
    for j, g in enumerate(GENRES):
        CATS["vod"].append({"category_id": str(100 + j), "category_name": f"Movies - {g}"})
        CATS["series"].append({"category_id": str(200 + j), "category_name": f"Series - {g}"})
    for n in range(ARGS.live):
        ci = n % len(CATS["live"])
        cat = CATS["live"][ci]["category_name"]
        country = cat.split(" | ")[0]
        epg = f"ch{n}.{country.lower()}" if n % 10 < 7 else ""      # 30% missing EPG ids
        quality = ["", " HD", " FHD", " 4K"][n % 4]
        LIVE.append({
            "num": n + 1, "name": f"{country}: Channel {n}{quality}", "stream_type": "live",
            "stream_id": 1000 + n, "stream_icon": f"http://img.example/{n}.png" if n % 5 else None,
            "epg_channel_id": epg or None, "added": "1600000000",
            "tv_archive": 1 if n % 3 == 0 else 0, "tv_archive_duration": "7" if n % 3 == 0 else "0",
            # mix str and int category ids on purpose: real servers do both
            "category_id": int(cat and CATS["live"][ci]["category_id"]) if n % 2 else CATS["live"][ci]["category_id"],
        })
    for n in range(ARGS.vod):
        VOD.append({"num": n + 1, "name": f"Movie {n} – éè 日本", "stream_id": 500000 + n,
                    "stream_icon": f"http://img.example/m{n}.jpg", "rating": "7.1", "added": "1600000000",
                    "category_id": CATS["vod"][n % len(GENRES)]["category_id"],
                    "container_extension": ["mp4", "mkv"][n % 2]})
    for n in range(ARGS.series):
        SERIES.append({"num": n + 1, "name": f"Show {n}", "series_id": 9000 + n,
                       "cover": f"http://img.example/s{n}.jpg", "plot": "A show.", "rating": "8",
                       "last_modified": "1600000000",
                       "category_id": CATS["series"][n % len(GENRES)]["category_id"]})


def series_info(sid):
    n = sid - 9000
    seasons = 1 + n % 3
    eps = {}
    for s in range(1, seasons + 1):
        eps[str(s)] = [{"id": str(700000 + sid * 100 + s * 10 + e), "episode_num": e,
                        "title": f"Episode {e}", "container_extension": "mkv", "season": s}
                       for e in range(1, 4)]
    return {"seasons": [], "info": {"name": f"Show {n}"}, "episodes": eps}


def short_epg(stream_id):
    ch = next((c for c in LIVE if str(c["stream_id"]) == stream_id), None)
    if not ch or not ch["epg_channel_id"]:
        return {"epg_listings": []}
    now = int(time.time())
    return {"epg_listings": [{"id": "1", "epg_id": ch["epg_channel_id"], "title": "UHJvdmlkZXIgc2hvdw==",
                              "start_timestamp": str(now), "stop_timestamp": str(now + 3600)}]}


def xmltv(kind):
    """kind 'main' = ids for 70% of live channels; 'extra' = guide using different ids but
    matching channel *names*, to exercise auto-match."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<tv>"]
    prog = []
    for n, ch in enumerate(LIVE):
        if kind == "main" and ch["epg_channel_id"]:
            cid, disp = ch["epg_channel_id"], ch["name"]
        elif kind == "extra" and not ch["epg_channel_id"] and n % 2 == 0:
            cid = f"extra-{n}"
            disp = ch["name"].replace("US: ", "").replace("UK: ", "")   # name drifts a bit
        else:
            continue
        out.append(f'<channel id="{cid}"><display-name>{disp}</display-name></channel>')
        base = int(time.time() // 3600) * 3600
        for k in range(ARGS.programs):
            a, b = base + (k - 1) * 3600, base + k * 3600
            fmt = lambda t: time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(t))
            prog.append(f'<programme start="{fmt(a)}" stop="{fmt(b)}" '
                        f'channel="{cid}"><title>Show {k}</title><desc>About show {k}</desc></programme>')
    out.extend(prog)
    out.append("</tv>")
    return "\n".join(out).encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        if ARGS.verbose:
            sys.stderr.write(fmt % a + "\n")

    def _send(self, body, ctype="application/json", extra=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, code, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        authed = q.get("username") == "demo" and q.get("password") == "demo"
        if u.path.endswith("player_api.php"):
            if not authed:
                return self._send(json.dumps({"user_info": {"auth": 0}}).encode())
            a = q.get("action")
            if not a:
                return self._send(json.dumps({
                    "user_info": {"auth": 1, "status": "Active", "exp_date": "1893456000",
                                  "max_connections": "2", "active_cons": "0"},
                    "server_info": {"url": "127.0.0.1"}}).encode())
            data = {
                "get_live_categories": lambda: CATS["live"], "get_live_streams": lambda: LIVE,
                "get_vod_categories": lambda: CATS["vod"], "get_vod_streams": lambda: VOD,
                "get_series_categories": lambda: CATS["series"], "get_series": lambda: SERIES,
                "get_series_info": lambda: series_info(int(q["series_id"])),
                "get_short_epg": lambda: short_epg(q.get("stream_id", "")),
                "get_simple_data_table": lambda: {"epg_listings": [dict(x, has_archive=1) for x in
                                                                   short_epg(q.get("stream_id", "")).get("epg_listings", [])]},
                "get_vod_info": lambda: {"info": {"plot": "Provider plot", "name": "Provider name"},
                                         "movie_data": {"stream_id": int(q.get("vod_id", 0)),
                                                        "name": "Provider name", "container_extension": "mkv"}},
            }.get(a)
            return self._send(json.dumps(data() if data else []).encode())
        parts = u.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] in ("live", "movie", "series"):
            if parts[1:3] != ["demo", "demo"]:
                self.send_response(403)
                self.end_headers()
                return
            body = (f"STREAM {u.path} " * 200).encode()
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                a, b = int(a or 0), int(b) if b else len(body) - 1
                chunk = body[a:b + 1]
                return self._send_raw(206, chunk, {"Content-Range": f"bytes {a}-{a + len(chunk) - 1}/{len(body)}"})
            return self._send_raw(200, body)
        if parts[0] == "timeshift" and len(parts) == 6 and parts[1:3] == ["demo", "demo"]:
            return self._send_raw(200, f"TIMESHIFT {u.path}".encode())
        if u.path.endswith("timeshift.php") and authed:
            return self._send_raw(200, f"TIMESHIFT-PHP stream={q.get('stream')} start={q.get('start')} dur={q.get('duration')}".encode())
        if u.path.endswith("xmltv.php"):
            return self._send(xmltv("main"), "application/xml") if authed else self._send(b"", "text/plain")
        if u.path == "/extra_epg.xml.gz":
            return self._send(gzip.compress(xmltv("extra")), "application/gzip")
        self.send_response(404)
        self.end_headers()


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--live", type=int, default=2000)
    ap.add_argument("--vod", type=int, default=800)
    ap.add_argument("--series", type=int, default=300)
    ap.add_argument("--programs", type=int, default=3, help="programs per channel in the fake guides")
    ap.add_argument("--verbose", action="store_true")
    ARGS = ap.parse_args()
    build()
    print(f"Mock Xtream server on http://127.0.0.1:{ARGS.port}  (login demo / demo)")
    print(f"  link: http://127.0.0.1:{ARGS.port}/get.php?username=demo&password=demo&type=m3u_plus")
    print(f"  extra guide for testing: http://127.0.0.1:{ARGS.port}/extra_epg.xml.gz")
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
