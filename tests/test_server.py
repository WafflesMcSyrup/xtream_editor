"""Checks the local Xtream server against the mock provider.
Run:  python tests/test_server.py
"""
import gzip
import json
import os
import subprocess
import sys
import tempfile
import time

TMP = tempfile.mkdtemp()
os.environ["HOME"] = TMP                    # keep cache/settings/logs out of the real home
os.environ["USERPROFILE"] = TMP
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import requests                                                  # noqa: E402

from core.models import Library                                  # noqa: E402
from core.xtream import XtreamClient, fetch_all, fetch_episodes  # noqa: E402
from core.xtream_server import XtreamServer, category_ids        # noqa: E402

PROV, LOCAL = 18090, 18091
LIVE, VOD, SER = 5000, 2000, 90
fails = 0


def check(cond, msg):
    global fails
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        fails += 1


def api(action=None, user="u1", pw="p1", **kw):
    params = {"username": user, "password": pw, **kw}
    if action:
        params["action"] = action
    r = requests.get(f"http://127.0.0.1:{LOCAL}/player_api.php", params=params, timeout=30)
    return r.json()


prov = subprocess.Popen([sys.executable, os.path.join(ROOT, "mock_server.py"), "--port", str(PROV),
                         "--live", str(LIVE), "--vod", str(VOD), "--series", str(SER)],
                        stdout=subprocess.DEVNULL)
time.sleep(1.5)
srv = XtreamServer()
try:
    conn = {"server": f"http://127.0.0.1:{PROV}", "username": "demo", "password": "demo", "ua": "t"}
    lib = Library()
    lib.connection = dict(conn)
    lib.merge_server(fetch_all(XtreamClient(**conn))["items"])
    lib.epg_sources = [f"http://127.0.0.1:{PROV}/extra_epg.xml.gz"]
    live = lib.ordered("live")

    # edits: rename, delete, recategorize, EPG id borrowed from the extra guide
    lib.change([(live[0], "name", "Edited One"), (live[1], "deleted", True),
                (live[2], "category", "My Faves"), (live[3], "category", "My Faves")], "edits")
    # the mock's extra guide only covers even-numbered channels that have no ID of their own
    gap = next(i for i in live if not i.epg_id and not i.deleted and (int(i.id) - 1000) % 2 == 0)
    lib.change([(gap, "epg_id", "extra-%d" % (int(gap.id) - 1000))], "epg")
    fast = next(i for i in live if i.epg_id and not i.deleted and i.epg_id.startswith("ch"))

    srv.start(lib, LOCAL, "u1", "p1", "redirect", "merged", 12, host="127.0.0.1")
    check(srv.running, "server started")

    # --- auth
    check(api(user="u1", pw="nope")["user_info"]["auth"] == 0, "wrong password -> auth 0")
    ai = api()
    check(ai["user_info"]["auth"] == 1 and ai["server_info"]["port"] == str(LOCAL), "account info, port from Host header")
    check(requests.get(f"http://127.0.0.1:{LOCAL}/live/u1/bad/1001.ts", allow_redirects=False).status_code == 403,
          "stream URL with wrong password is refused")

    # --- sections like a real provider
    lc, vc, sc = api("get_live_categories"), api("get_vod_categories"), api("get_series_categories")
    check(len(lc) > 10 and len(vc) == 8 and len(sc) == 8, f"three sections with categories ({len(lc)}/{len(vc)}/{len(sc)})")
    check(all(set(c) >= {"category_id", "category_name", "parent_id"} and isinstance(c["category_id"], str) for c in lc),
          "category fields look like Xtream")
    ls = api("get_live_streams")
    check(len(ls) == LIVE - 1, f"all live streams, deleted one hidden ({len(ls)})")
    check(ls[0]["name"] == "Edited One" and ls[0]["stream_id"] == int(live[0].id), "renamed channel served, original stream id kept")
    check(all(live[1].name != e["name"] for e in ls), "deleted channel not served")
    check([e["num"] for e in ls[:3]] == [1, 2, 3], "order numbers follow your order")
    check(len(api("get_vod_streams")) == VOD and len(api("get_series")) == SER, "movies and series lists")

    fav = next(c for c in lc if c["category_name"] == "My Faves")
    in_fav = api("get_live_streams", category_id=fav["category_id"])
    check(len(in_fav) == 2 and {e["name"] for e in in_fav} == {live[2].name, live[3].name}, "category_id filter works + your new category exists")
    check(fav["category_id"] == str(category_ids({"My Faves", "x"}, "live")["My Faves"]), "category ids are stable by name")
    first_cat = next(c for c in lc if c["category_name"].startswith("US | News"))
    sub = api("get_live_streams", category_id=first_cat["category_id"])
    check(sub and all(e["category_id"] == first_cat["category_id"] for e in sub), "streams carry their category id")
    check(api("get_live_streams", category_id="999")[:1] == [], "unknown category -> empty list")

    # gzip
    r = requests.get(f"http://127.0.0.1:{LOCAL}/player_api.php",
                     params={"username": "u1", "password": "p1", "action": "get_live_streams"},
                     headers={"Accept-Encoding": "gzip"})
    check(r.headers.get("Content-Encoding") == "gzip" and len(r.json()) == LIVE - 1, "gzip responses decode fine")

    # --- series: passthrough + skipped episodes hidden + edits shown
    s0 = lib.ordered("series")[0]
    s0.episodes = fetch_episodes(XtreamClient(**conn), s0.id)
    s0.episodes[0]["skip"] = True
    lib.change([(s0, "name", "My Show")], "rename show")
    srv.update(lib)
    si = api("get_series_info", series_id=s0.id)
    ids = [e["id"] for lst in si["episodes"].values() for e in lst]
    check(len(ids) == len(s0.episodes) - 1 and s0.episodes[0]["id"] not in ids, "skipped episodes are hidden")
    check(si["info"]["name"] == "My Show", "edited show name appears in details")

    # --- vod info
    v0 = lib.ordered("vod")[0]
    vi = api("get_vod_info", vod_id=v0.id)
    check(vi["info"]["plot"] == "Provider plot", "movie details come from the provider")

    # --- playback goes to the real provider
    r = requests.get(f"http://127.0.0.1:{LOCAL}/live/u1/p1/{live[0].id}.ts", allow_redirects=False)
    check(r.status_code == 302 and r.headers["Location"] == f"http://127.0.0.1:{PROV}/live/demo/demo/{live[0].id}.ts",
          "live play -> redirect to provider URL")
    r = requests.get(f"http://127.0.0.1:{LOCAL}/movie/u1/p1/{v0.id}.mkv", allow_redirects=False)
    check(r.headers["Location"].endswith(f"/movie/demo/demo/{v0.id}.mkv"), "movie play -> redirect")
    ep = s0.episodes[1]
    r = requests.get(f"http://127.0.0.1:{LOCAL}/series/u1/p1/{ep['id']}.mkv", allow_redirects=False)
    check(r.headers["Location"].endswith(f"/series/demo/demo/{ep['id']}.mkv"), "episode play -> redirect")

    # --- proxy mode (with Range)
    srv.stream_mode = "proxy"
    r = requests.get(f"http://127.0.0.1:{LOCAL}/live/u1/p1/{live[0].id}.ts", allow_redirects=False)
    check(r.status_code == 200 and r.content.startswith(b"STREAM /live/demo/demo/"), "proxy mode relays the stream")
    r = requests.get(f"http://127.0.0.1:{LOCAL}/movie/u1/p1/{v0.id}.mp4", headers={"Range": "bytes=0-9"})
    check(r.status_code == 206 and len(r.content) == 10, "proxy mode passes Range requests")
    srv.stream_mode = "redirect"

    # --- live edits show up after update()
    lib.change([(live[5], "name", "Changed After Start")], "late edit")
    t = srv.update(lib)
    check(any(e["name"] == "Changed After Start" for e in api("get_live_streams")), f"update() picks up edits ({t*1000:.0f} ms)")

    # --- catch-up (timeshift)
    arch_ch = next(i for i in live if i.arch and not i.deleted)
    no_arch = next(i for i in live if not i.arch and not i.deleted)
    es = {e["stream_id"]: e for e in api("get_live_streams")}
    check(es[int(arch_ch.id)]["tv_archive"] == 1 and es[int(arch_ch.id)]["tv_archive_duration"] == 7, "catch-up flag and days are served")
    check(es[int(no_arch.id)]["tv_archive"] == 0, "channels without catch-up say so")
    r = requests.get(f"http://127.0.0.1:{LOCAL}/timeshift/u1/p1/60/2026-10-14:12-00/{arch_ch.id}.ts", allow_redirects=False)
    check(r.status_code == 302 and r.headers["Location"] == f"http://127.0.0.1:{PROV}/timeshift/demo/demo/60/2026-10-14%3A12-00/{arch_ch.id}.ts",
          f"timeshift (path style) redirects to the provider ({r.headers.get('Location')})")
    r = requests.get(f"http://127.0.0.1:{LOCAL}/streaming/timeshift.php", params={"username": "u1", "password": "p1", "stream": arch_ch.id,
                                                                                  "start": "2026-10-14:12-00", "duration": "60"}, allow_redirects=False)
    loc = r.headers.get("Location", "")
    check(r.status_code == 302 and loc.startswith(f"http://127.0.0.1:{PROV}/streaming/timeshift.php?username=demo&password=demo")
          and f"stream={arch_ch.id}" in loc and "duration=60" in loc, "timeshift (php style) redirects to the provider")
    check(requests.get(f"http://127.0.0.1:{LOCAL}/timeshift/u1/WRONG/60/2026-10-14:12-00/{arch_ch.id}.ts", allow_redirects=False).status_code == 403,
          "timeshift needs the local login")
    srv.stream_mode = "proxy"
    r = requests.get(f"http://127.0.0.1:{LOCAL}/timeshift/u1/p1/60/2026-10-14:12-00/{arch_ch.id}.ts")
    check(r.status_code == 200 and r.content.startswith(b"TIMESHIFT /timeshift/demo/demo/60/"), "timeshift is relayed in relay mode")
    r = requests.get(f"http://127.0.0.1:{LOCAL}/streaming/timeshift.php", params={"username": "u1", "password": "p1", "stream": arch_ch.id,
                                                                                  "start": "S", "duration": "5"})
    check(r.content.startswith(b"TIMESHIFT-PHP stream=" + arch_ch.id.encode()), "php-style timeshift is relayed in relay mode")
    srv.stream_mode = "redirect"
    check(not any("p1" in l.split("timeshift")[-1] and "/p1/" in l for l in srv.lines if "timeshift" in l), "timeshift log lines hide the password")
    dt = api("get_simple_data_table", stream_id=str(arch_ch.id))
    check(dt.get("epg_listings") is not None, "get_simple_data_table answers")

    # --- favorites: a "★ Favorites" category with copies that have their own ids
    from core.xtream_server import FAV_BASE, FAV_NAME
    check(not any(c["category_name"] == FAV_NAME for c in api("get_live_categories")), "no favorites -> no category")
    fl = [live[6], live[7]]
    fv = lib.ordered("vod")[2]
    fs = lib.ordered("series")[2]
    lib.change([(i, "fav", True) for i in fl + [fv, fs]], "fav")
    srv.update(lib)
    cats = api("get_live_categories")
    check(cats[0]["category_name"] == FAV_NAME, "Favorites is the first live category")
    fcid = cats[0]["category_id"]
    got = api("get_live_streams", category_id=fcid)
    check([e["name"] for e in got] == [i.name for i in fl], "favorites category lists the starred channels")
    check(all(e["stream_id"] == FAV_BASE + int(i.id) and e["category_id"] == fcid for e, i in zip(got, fl)),
          "copies get distinct ids and the favorites category id")
    check(any(e["stream_id"] == int(fl[0].id) and e["category_id"] != fcid for e in api("get_live_streams")),
          "original stays in its normal category")
    ids = [e["stream_id"] for e in api("get_live_streams")]
    check(len(ids) == len(set(ids)), "no duplicate stream ids in the full list")
    from core.xtream_server import _mask
    check("p1" not in _mask("/timeshift/u1/p1/60/2026-10-14:12-00/5.ts") and "secret" not in _mask("/streaming/timeshift.php?username=u&password=secret&stream=5"),
          "timeshift addresses are masked in the log")
    r = requests.get(f"http://127.0.0.1:{LOCAL}/timeshift/u1/p1/60/2026-10-14:12-00/{got[0]['stream_id']}.ts", allow_redirects=False)
    check(r.headers["Location"].split("/")[-1] == f"{fl[0].id}.ts", "catch-up on a starred copy goes to the real channel")
    r = requests.get(f"http://127.0.0.1:{LOCAL}/live/u1/p1/{got[0]['stream_id']}.ts", allow_redirects=False)
    check(r.headers["Location"].endswith(f"/live/demo/demo/{fl[0].id}.ts"), "favorite copy plays the real stream")
    vf = api("get_vod_streams", category_id=api("get_vod_categories")[0]["category_id"])
    check(len(vf) == 1 and vf[0]["name"] == fv.name, "movies get a favorites category too")
    r = requests.get(f"http://127.0.0.1:{LOCAL}/movie/u1/p1/{vf[0]['stream_id']}.mp4", allow_redirects=False)
    check(r.headers["Location"].endswith(f"/movie/demo/demo/{fv.id}.mp4"), "favorite movie plays the real file")
    check(api("get_vod_info", vod_id=vf[0]["stream_id"])["movie_data"]["name"] == fv.name, "favorite movie info resolves")
    sf = api("get_series", category_id=api("get_series_categories")[0]["category_id"])
    check(len(sf) == 1 and api("get_series_info", series_id=sf[0]["series_id"])["episodes"], "favorite series opens with episodes")
    check(api("get_short_epg", stream_id=got[0]["stream_id"]) is not None, "favorite channel guide lookup works")
    m3u = requests.get(f"http://127.0.0.1:{LOCAL}/get.php?username=u1&password=p1").text
    check(f'group-title="{FAV_NAME}"' in m3u, "get.php lists the favorites group")
    lib.change([(i, "fav", False) for i in fl + [fv, fs]], "unfav")
    srv.update(lib)
    check(not any(c["category_name"] == FAV_NAME for c in api("get_live_categories")), "unstarring removes the category")
    lib.change([(fl[0], "fav", True)], "fav")
    p_fav = os.path.join(tempfile.mkdtemp(), "f.xtp")
    lib.save(p_fav)
    l_back = Library()
    l_back.load(p_fav)
    check(l_back.index[fl[0].key].fav and not l_back.index[fl[1].key].fav, "favorites survive save/load")
    l_back.merge_server(fetch_all(XtreamClient(**conn))["items"])
    check(l_back.index[fl[0].key].fav, "favorites survive re-sync")
    lib.change([(fl[0], "fav", False)], "unfav")
    srv.update(lib)

    # --- guide: merged file built in the background
    t0 = time.time()
    while not os.path.exists(os.path.join(TMP, ".xtream_editor", "xtream_server", "epg.xml.gz")) and time.time() - t0 < 30:
        time.sleep(0.2)
    time.sleep(0.5)
    check("guide ready" in srv.epg_status(), f"guide built ({srv.epg_status()})")
    r = requests.get(f"http://127.0.0.1:{LOCAL}/xmltv.php", params={"username": "u1", "password": "p1"},
                     headers={"Accept-Encoding": "identity"})
    check(r.content.startswith(b"<?xml") and f'id="{fast.epg_id}"'.encode() in r.content, "xmltv.php serves the merged guide (plain)")
    check(f'id="{gap.epg_id}"'.encode() in r.content, "guide includes the ID you borrowed from your extra guide")
    r2 = requests.get(f"http://127.0.0.1:{LOCAL}/xmltv.php", params={"username": "u1", "password": "p1"},
                      headers={"Accept-Encoding": "gzip"}, stream=True)
    check(r2.headers.get("Content-Encoding") == "gzip" and r2.raw.read(2) == b"\x1f\x8b", "xmltv.php serves gzip when asked")
    check(requests.get(f"http://127.0.0.1:{LOCAL}/xmltv.php", params={"username": "x", "password": "y"}).status_code == 403,
          "xmltv.php needs the login")

    # --- a guide file on this PC feeds the server's guide too, and replacing it triggers a rebuild
    import xml.etree.ElementTree as ET
    lf = os.path.join(TMP, "my local guide.xml")
    nowh = int(time.time() // 3600) * 3600
    fm = lambda t: time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(t))
    open(lf, "w", encoding="utf-8").write(
        "<?xml version='1.0'?><tv><channel id='extra-1'><display-name>X</display-name></channel>"
        f"<programme start='{fm(nowh)}' stop='{fm(nowh + 3600)}' channel='extra-1'><title>Local show</title></programme></tv>")
    lib.epg_sources = list(lib.epg_sources) + [lf]
    lib.change([(next(i for i in lib.ordered("live") if not i.epg_id and not i.deleted and i.id != gap.id), "epg_id", "extra-1")], "borrow")
    srv.update(lib)
    srv.keeper.kick()
    t0 = time.time()
    got_local = False
    while time.time() - t0 < 30 and not got_local:
        time.sleep(0.5)
        try:
            import gzip as _gz
            got_local = b'id="extra-1"' in _gz.open(os.path.join(TMP, ".xtream_editor", "xtream_server", "epg.xml.gz")).read()
        except OSError:
            pass
    check(got_local, "server guide includes a channel that only exists in a local guide file")
    meta_path = os.path.join(TMP, ".xtream_editor", "xtream_server", "epg.meta.json")
    meta_before = json.load(open(meta_path))
    open(lf, "a").write("\n")
    from core.xtream_server import EpgKeeper
    check(srv.keeper._due(srv.snap, False), "replacing the local guide file makes the server rebuild the guide")

    # --- failed guide downloads: retry in 30 min, then 2 h, then wait for the normal cycle
    logs = []
    class _Own:                                   # minimal stand-in for the server
        ua = "t"
        def log(self, m): logs.append(m)
    k = EpgKeeper(_Own(), 12)
    t0 = time.time()
    k._after_attempt(1)
    check(k.retries == 1 and 1790 < k.retry_at - t0 < 1810 and "30 minutes" in logs[-1], "first failure: retry in 30 minutes")
    k._after_attempt(1)
    check(k.retries == 2 and 7190 < k.retry_at - t0 < 7210 and "2 hours" in logs[-1], "second failure: retry in 2 hours")
    k._after_attempt(1)
    check(k.retry_at is None and k.retries == 0 and k.hold_until - t0 > 12 * 3600 - 10 and "giving up" in logs[-1],
          "third failure: stop and wait for the regular refresh")
    k._after_attempt(1)
    check(k.retries == 1, "a new cycle starts the retry ladder again")
    k._after_attempt(0)
    check(k.retries == 0 and k.retry_at is None and k.hold_until == 0.0, "a success clears the retry state")

    # --- short EPG: local merged guide first (covers borrowed IDs), provider otherwise
    se = api("get_short_epg", stream_id=gap.id, limit=2)
    check(se["epg_listings"] and se["epg_listings"][0]["epg_id"] == gap.epg_id, "short EPG works for an ID borrowed from another guide")
    se2 = api("get_short_epg", stream_id=fast.id)
    check(se2["epg_listings"], "short EPG works for provider-guide channels")
    check(api("get_short_epg", stream_id="424242")["epg_listings"] == [], "unknown channel -> empty listing")

    # --- get.php fallback playlist
    m = requests.get(f"http://127.0.0.1:{LOCAL}/get.php", params={"username": "u1", "password": "p1", "type": "m3u_plus"})
    lines = m.text.splitlines()
    check(lines[0] == "#EXTM3U" and sum(l.startswith("#EXTINF") for l in lines) == (LIVE - 1) + VOD, "get.php playlist (live+movies)")
    check(f"http://127.0.0.1:{LOCAL}/live/u1/p1/{live[0].id}.ts" in lines, "playlist URLs point at the local server")

    # --- log masks the password
    check(srv.lines and not any("p1" == w for l in srv.lines for w in l.replace("/", " ").split()), "request log doesn't show passwords")

    # --- speed on a big list
    big = Library()
    big.connection = dict(conn)
    from core.models import Item
    big.merge_server([Item("live", 900000 + i, f"Chan {i}", f"Cat {i % 300}", epg_id=f"x{i}") for i in range(60000)]
                     + [Item("vod", 100 + i, f"Movie {i}", f"M {i % 50}") for i in range(30000)])
    t = srv.update(big)
    t0 = time.time()
    big_live = api("get_live_streams")
    t1 = time.time() - t0
    t0 = time.time()
    api("get_live_streams")
    check(len(big_live) == 60000, f"60k live channels served (snapshot {t:.2f}s, first call {t1:.2f}s, cached {time.time()-t0:.2f}s)")
    srv.update(lib)
finally:
    srv.stop()
    prov.terminate()

# --- no-window mode
prov2 = subprocess.Popen([sys.executable, os.path.join(ROOT, "mock_server.py"), "--port", str(PROV + 5),
                          "--live", "300", "--vod", "100", "--series", "10"], stdout=subprocess.DEVNULL)
time.sleep(1.2)
try:
    c2 = {"server": f"http://127.0.0.1:{PROV + 5}", "username": "demo", "password": "demo", "ua": "t"}
    l2 = Library()
    l2.connection = c2
    l2.merge_server(fetch_all(XtreamClient(**c2))["items"])
    proj = os.path.join(TMP, "cli.xtp")
    l2.save(proj)
    cli = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py"), "--serve", proj, "--port", str(LOCAL + 1),
                            "--user", "ann", "--password", "secret", "--no-epg"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2.5)
    r = requests.get(f"http://127.0.0.1:{LOCAL + 1}/player_api.php",
                     params={"username": "ann", "password": "secret", "action": "get_live_streams"}, timeout=10)
    check(r.status_code == 200 and len(r.json()) == 300, "CLI --serve runs without Qt and serves the project")
    check(requests.get(f"http://127.0.0.1:{LOCAL + 1}/xmltv.php", params={"username": "ann", "password": "secret"}).text.endswith("</tv>"),
          "CLI --no-epg serves an empty guide")

    def cli_live():
        return requests.get(f"http://127.0.0.1:{LOCAL + 1}/player_api.php",
                            params={"username": "ann", "password": "secret", "action": "get_live_streams"}, timeout=10).json()

    def wait_for(pred, secs=10):
        t0 = time.time()
        while time.time() - t0 < secs:
            if pred():
                return True
            time.sleep(0.3)
        return pred()

    # saving in the editor changes what the running CLI server hands out
    first = l2.ordered("live")[0]
    l2.change([(first, "name", "Saved While Running"), (l2.ordered("live")[1], "deleted", True)], "edit")
    l2.save(proj)
    check(wait_for(lambda: any(e["name"] == "Saved While Running" for e in cli_live())),
          "CLI server picks up a saved project on its own")
    check(len(cli_live()) == 299, "...including deletions")
    # a broken/half-written file must not take the server down
    with open(proj, "wb") as f:
        f.write(b"not a project")
    time.sleep(5)
    check(len(cli_live()) == 299, "garbage in the project file: keeps serving the previous list")
    l2.change([(first, "name", "Back To Normal")], "edit2")
    l2.save(proj)
    check(wait_for(lambda: any(e["name"] == "Back To Normal" for e in cli_live())),
          "recovers when a good file is saved again")
    cli.terminate()
    out = cli.communicate(timeout=10)[0]
    check("Username:  ann" in out and "Password:  secret" in out, "CLI prints what to type into the app")

    # --- daily re-sync
    from core import serve_cli
    from core.models import Item
    t0 = time.mktime((2026, 10, 14, 14, 0, 0, 0, 0, -1))
    nr = time.localtime(serve_cli.next_run(t0, "03:00"))
    check((nr.tm_mday, nr.tm_hour, nr.tm_min) == (15, 3, 0), "next 03:00 after 14:00 is tomorrow")
    nr = time.localtime(serve_cli.next_run(time.mktime((2026, 10, 14, 1, 0, 0, 0, 0, -1)), "03:00"))
    check((nr.tm_mday, nr.tm_hour) == (14, 3), "next 03:00 after 01:00 is today")
    nr = time.localtime(serve_cli.next_run(time.mktime((2026, 10, 31, 4, 0, 0, 0, 0, -1)), "3:00"))
    check((nr.tm_mon, nr.tm_mday) == (11, 1), "rolls over the end of the month")
    for bad_t in ("25:00", "3am", "03:60", ""):
        try:
            serve_cli.parse_hhmm(bad_t)
            check(False, f"bad time {bad_t!r} rejected")
        except ValueError:
            check(True, f"bad time {bad_t!r} rejected")

    rp = os.path.join(TMP, "resync.xtp")
    l2.change([(first, "name", "My Edited Name")], "e")
    l2.save(rp)
    base = l2.ordered("live")

    def fake_fetch(extra=(), drop=()):
        def f(client, progress):
            keep = [Item(i.kind, i.id, "Server " + i.name, i.category) for i in l2.items if i.key not in drop]
            return {"items": keep + list(extra), "info": {}, "warnings": []}
        return f
    newbie = Item("live", "777777", "Brand New Channel", "US | News")
    lib3, info = serve_cli.refresh_project(rp, fake_fetch([newbie], {base[5].key}))
    check(info["added"] == 1 and info["gone"] == 1, "re-sync adds new and flags vanished")
    on_disk = Library()
    on_disk.load(rp)
    check(on_disk.index[("live", "777777")].num > base[-1].num, "re-sync is saved to the project file")
    check(on_disk.index[first.key].name == "My Edited Name", "re-sync keeps your edits")
    check(on_disk.index[base[5].key].gone, "vanished channel is flagged gone in the file")
    try:
        serve_cli.refresh_project(rp, lambda c, p: {"items": [i for i in l2.items if i.kind != "live"], "info": {}, "warnings": []})
        check(False, "a half-empty provider answer is refused")
    except RuntimeError:
        again = Library()
        again.load(rp)
        check(not again.index[base[0].key].gone and not again.index[base[1].key].gone,
              "a half-empty provider answer is refused and nothing is marked gone")

    cli2 = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py"), "--serve", rp, "--port", str(LOCAL + 2),
                             "--user", "ann", "--password", "secret", "--no-epg", "--first-refresh-in", "4"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(9)
    cli2.terminate()
    out2 = cli2.communicate(timeout=10)[0]
    check("Re-syncing with your provider every day at 03:00" in out2, "CLI announces the daily re-sync time")
    check("daily re-sync done" in out2, "CLI runs the daily re-sync on schedule")
    cli3 = subprocess.Popen([sys.executable, os.path.join(ROOT, "main.py"), "--serve", rp, "--port", str(LOCAL + 3),
                             "--no-epg", "--refresh-at", "99:99"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    check("Bad --refresh-at" in cli3.communicate(timeout=15)[0], "bad --refresh-at is reported")
finally:
    prov2.terminate()

print("\nFAILED: %d" % fails if fails else "\nALL PASSED")
sys.exit(1 if fails else 0)
