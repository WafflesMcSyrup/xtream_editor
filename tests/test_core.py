"""Headless checks of the non-UI logic against the mock server.
Run:  python tests/test_core.py
"""
import gzip
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import epg                                      # noqa: E402
from core.exporter import export_list, export_playlists                # noqa: E402
from core.models import Library                           # noqa: E402
from core.xtream import (XtreamClient, XtreamError, fetch_all,  # noqa: E402
                         fetch_episodes, parse_link, stream_url, xmltv_url)

PORT = 18080
LIVE, VOD, SER = 6000, 1500, 120


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        check.failed += 1


check.failed = 0


def main():
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "mock_server.py"), "--port", str(PORT),
                            "--live", str(LIVE), "--vod", str(VOD), "--series", str(SER)],
                           stdout=subprocess.DEVNULL)
    time.sleep(1.5)
    tmp = tempfile.mkdtemp()
    try:
        # --- link parsing
        p = parse_link(f"http://127.0.0.1:{PORT}/get.php?username=demo&password=demo&type=m3u_plus&output=ts")
        check(p == {"server": f"http://127.0.0.1:{PORT}", "username": "demo", "password": "demo"}, "parse get.php link")
        p2 = parse_link("http://host.tv:8000/live/bob/p%40ss/123.ts")
        check(p2 == {"server": "http://host.tv:8000", "username": "bob", "password": "p@ss"}, "parse stream link")
        check(parse_link("http://host.tv:8000") is None, "bare host is not a login link")
        pp = parse_link("http://host.tv/sub/player_api.php?username=a&password=b")
        check(pp["server"] == "http://host.tv/sub", "keeps sub-path")

        # --- bad login
        bad = XtreamClient(f"http://127.0.0.1:{PORT}", "demo", "wrong")
        try:
            bad.authenticate()
            check(False, "bad login rejected")
        except XtreamError:
            check(True, "bad login rejected")

        # --- fetch
        conn = {"server": f"http://127.0.0.1:{PORT}", "username": "demo", "password": "demo"}
        client = XtreamClient(**conn)
        t0 = time.time()
        res = fetch_all(client)
        items = res["items"]
        n = {k: sum(1 for i in items if i.kind == k) for k in ("live", "vod", "series")}
        check(n == {"live": LIVE, "vod": VOD, "series": SER}, f"fetched all kinds {n} in {time.time()-t0:.1f}s")
        live0 = next(i for i in items if i.kind == "live")
        check(live0.category.startswith("US |"), "category name resolved")
        odd = [i for i in items if i.kind == "live" and i.id == "1001"][0]
        check(odd.category != "Uncategorized", "int category_id resolved")
        check(any(i.epg_id == "" for i in items if i.kind == "live"), "missing EPG ids kept empty")
        vod0 = next(i for i in items if i.kind == "vod")
        check("日本" in vod0.name, "unicode names survive")

        arch_items = [i for i in items if i.kind == "live" and i.arch]
        check(arch_items and all(i.arch == 7 for i in arch_items) and next(i for i in items if i.kind == "live" and i.id == "1001").arch == 0
              and next(i for i in items if i.kind == "live" and i.id == "1000").arch == 7, "catch-up days are read from the provider")
        from core.xtream import _archive_days
        check(_archive_days({"tv_archive": 1, "tv_archive_duration": "3"}) == 3 and _archive_days({"tv_archive": "0"}) == 0
              and _archive_days({"tv_archive": 1}) == 1 and _archive_days({}) == 0, "catch-up flag parsing (strings, ints, missing)")
        # --- library edits / undo / redo
        lib = Library()
        lib.connection = dict(conn)
        lib.merge_server(items)
        check(not any(i.new for i in lib.items), "first load marks nothing as new")
        lives = lib.ordered("live")
        a, b = lives[0], lives[1]
        lib.change([(a, "name", "Renamed"), (b, "deleted", True)], "test")
        check(a.name == "Renamed" and "name" in a.edits and b.deleted, "edit + delete applied")
        lib.undo()
        check(a.name != "Renamed" and "name" not in a.edits and not b.deleted, "undo restores values and edit flags")
        lib.redo()
        check(a.name == "Renamed" and b.deleted, "redo works")

        # --- re-sync keeps edits, flags gone, appends new
        fresh = fetch_all(client)["items"]
        fresh = [i for i in fresh if not (i.kind == "live" and i.id == lives[2].id)]   # simulate removal
        fresh.append(type(a)("live", "999999", "Brand New", "US | News", "0"))
        info = lib.merge_server(fresh)
        check(a.name == "Renamed", "re-sync keeps user rename")
        check(lives[2].gone, "vanished channel flagged gone")
        check(info["added"] == 1 and lib.index[("live", "999999")].num > lives[-1].num, "new channel appended at end")

        check(info["added"] == 1 and [i.key for i in lib.items if i.new] == [("live", "999999")], "only items that arrived in the re-sync are marked new")
        again = lib.merge_server([i for i in fresh])
        check(again["added"] == 0 and lib.index[("live", "999999")].new, "a sync that finds nothing keeps the earlier 'new' markers")
        lib.merge_server(fresh + [type(a)("live", "999998", "Another New", "US | News", "0")])
        check([i.key for i in lib.items if i.new] == [("live", "999998")], "a sync that finds more replaces the markers")
        lib.change([(lib.index[("live", "999998")], "new", False)], "seen")
        check(not any(i.new for i in lib.items), "mark as seen clears the markers")
        lib.undo()
        check(lib.index[("live", "999998")].new, "mark as seen can be undone")
        # --- project save/load round trip
        lib.change([(lives[3], "category", "My Faves")], "cat")
        path = os.path.join(tmp, "p.xtp")
        lib.save(path)
        lib2 = Library()
        lib2.load(path)
        check(len(lib2.items) == len(lib.items), "project round-trip item count")
        check(lib2.index[lives[3].key].category == "My Faves" and "category" in lib2.index[lives[3].key].edits,
              "project round-trip keeps edits")
        check(lib2.connection["username"] == "demo", "project keeps connection")
        check(lib2.index[("live", "999998")].new and not lib2.index[lives[0].key].new, "'new' markers survive save/load")
        check(lib2.index[("live", "1000")].arch == 7 and lib2.index[("live", "1001")].arch == 0, "catch-up days survive save/load")

        # --- episodes
        some = lib.ordered("series")[:3]
        for s in some:
            s.episodes = fetch_episodes(client, s.id)
        check(all(len(s.episodes) >= 3 for s in some), "episodes fetched")
        some[0].episodes[0]["skip"] = True

        # --- export
        out = os.path.join(tmp, "out")
        st = export_playlists(lib, out, "list", ["live", "vod", "series"], split=False,
                              live_ext="ts", epg_header="http://x/epg.xml", prefix_groups=True)
        text = open(os.path.join(out, "list.m3u"), encoding="utf-8").read().splitlines()
        check(text[0].startswith("#EXTM3U") and 'url-tvg="http://x/epg.xml"' in text[0], "m3u header with EPG url")
        expected_live = sum(1 for i in lib.items if i.kind == "live" and not i.deleted and not i.gone)
        check(st["live"] == expected_live, f"live count excludes deleted/gone ({st['live']})")
        check(any("Renamed" in l for l in text), "export uses edited name")
        check("tvg-name=\"Brand New\"" in "\n".join(text), "new channel exported")
        check(not any("S01E01" in l and some[0].name in l and some[0].episodes[0]["title"] in l and l.startswith("#EXTINF")
                      for l in text), "skipped episode not exported")
        check(any(l.startswith(f"http://127.0.0.1:{PORT}/series/demo/demo/") for l in text), "series episode URLs")
        check(st["series_no_eps"] == SER - 3, "series without fetched episodes are reported, not exported")
        check(any('group-title="Movies | ' in l for l in text), "movie group prefix when combined")
        # every EXTINF followed by a URL
        ok = all(text[i + 1].startswith("http") for i in range(1, len(text) - 1) if text[i].startswith("#EXTINF"))
        check(ok, "every #EXTINF is followed by a URL")
        st2 = export_playlists(lib, out, "list", ["live", "vod"], split=True, live_ext="m3u8")
        check(len(st2["files"]) == 2 and any(".m3u8" in l for l in open(st2["files"][0]).read().splitlines()),
              "split export + m3u8 extension")
        check(stream_url(conn, "vod", "5", "mkv").endswith("/movie/demo/demo/5.mkv"), "vod url shape")

        # --- plain list export (CSV / TXT)
        import csv
        read_csv = lambda path: list(csv.reader(open(path, encoding="utf-8-sig", newline="")))   # noqa: E731
        cp = os.path.join(tmp, "list.csv")
        n_all = export_list(lib, cp, "csv")
        rows = read_csv(cp)
        want = sum(1 for i in lib.items if not i.deleted and not i.gone)
        check(rows[0] == ["Type", "Name", "Category"] and len(rows) == n_all + 1 == want + 1, f"CSV has header + every active item ({n_all})")
        check(["Live", "Renamed", a.category] in rows, "CSV uses edited names")
        check(not any(r[1] == b.name for r in rows), "CSV leaves out deleted items")
        n_del = export_list(lib, cp, "csv", skip_deleted=False)
        check(n_del == n_all + sum(1 for i in lib.items if i.deleted and not i.gone), "option to include deleted items")
        pick = {("live", a.category), ("vod", vod0.category)}
        n_pick = export_list(lib, cp, "csv", categories=pick)
        rows = read_csv(cp)[1:]
        check(n_pick == len(rows) > 0 and {(r[0], r[2]) for r in rows} <= {("Live", a.category), ("Movie", vod0.category)},
              "CSV limited to chosen categories")
        n_live = export_list(lib, cp, "csv", kinds=("live",))
        check(n_live < n_all and all(r[0] == "Live" for r in read_csv(cp)[1:]), "CSV limited to one type")
        tp = os.path.join(tmp, "list.txt")
        export_list(lib, tp, "txt", kinds=("live",), categories={("live", a.category)})
        txt = open(tp, encoding="utf-8").read().splitlines()
        cnt = sum(1 for i in lib.items if i.kind == "live" and i.category == a.category and not i.deleted and not i.gone)
        check(txt[0] == "##### LIVE TV #####" and f"== {a.category} ({cnt:,}) ==" in txt and "  Renamed" in txt,
              "TXT groups names under their category")
        fav_it = lib.ordered("live")[10]
        lib.change([(fav_it, "fav", True)], "star")
        n_fav = export_list(lib, cp, "csv", fav_only=True)
        check(n_fav == 1 and read_csv(cp)[1][1] == fav_it.name, "CSV 'favorites only'")
        lib.undo()
        from core.models import Item
        q = Library()
        q.merge_server([Item("live", "1", 'Say "hi", ok', "Odd, Cat")])
        qp = os.path.join(tmp, "q.csv")
        export_list(q, qp, "csv")
        check(read_csv(qp)[1] == ["Live", 'Say "hi", ok', "Odd, Cat"], "CSV quotes commas and quote marks properly")
        # --- name matching for the favorites import
        from core import matcher
        pool = [Item("live", str(n), nm, "c") for n, nm in enumerate(
            ["US | ESPN HD", "ESPN2", "Showtime East", "Showtime West", "Disney Channel East", "Disney Junior", "QVC2",
             "CNN En Español", "UK | BBC One", "Paramount+ with SHOWTIME", "MGM HD", "Nick Jr."])]
        ix = matcher.NameIndex(pool)
        top = lambda q: [(round(sc, 2), it.name) for sc, it in ix.search(q)]   # noqa: E731
        check(top("ESPN")[0] == (1.0, "US | ESPN HD"), "match ignores country prefix and HD")
        check({n for sc, n in top("Showtime") if sc >= matcher.TICK} == {"Showtime East", "Showtime West"},
              "East/West flavors all come back as good matches")
        check(top("QVC 2")[0][1] == "QVC2" and top("cnn en espanol")[0] == (1.0, "CNN En Español"),
              "spacing, case and accents don't matter")
        check(top("Disney Chanel")[0][1] == "Disney Channel East", "typo still finds the channel")
        check(top("Nick")[0][1] == "Nick Jr.", "first letters find the channel")
        check(top("Xyzzy Quux") == [], "nonsense gives no matches")
        check(matcher.parse_lines("# h\n== c (2) ==\n  A One\n- B Two (12)\n3. C Three [tag]\nD Four*\n\na one\n20/20\n")
              == ["A One", "B Two", "C Three", "D Four", "20/20"], "import file parsing (headers, bullets, tags, dupes)")
        # --- EPG
        prov = ("Provider", xmltv_url(conn))
        extra = ("Extra", f"http://127.0.0.1:{PORT}/extra_epg.xml.gz")
        idx, errs = epg.refresh_sources([prov, extra], "test")
        check(not errs and len(idx.sources) == 2, f"EPG sources downloaded+scanned {idx.sources}")
        check(idx.has("ch0.us") and not idx.has("nope"), "EPG index lookups")
        live_missing = [i for i in lib.items if i.kind == "live" and not i.epg_id]
        matched = [(i, idx.match(i.name)) for i in live_missing]
        got = [m for _, m in matched if m]
        check(len(got) > 0 and all(m.startswith("extra-") for m in got), f"name auto-match found {len(got)} IDs")
        outx = os.path.join(tmp, "epg.xml")
        wanted = {i.epg_id for i in lib.items if i.kind == "live" and i.epg_id}
        wanted |= set(got)
        ms = epg.merge_xmltv([prov, extra], wanted, outx, "test")
        tree = ET.parse(outx)
        chans = {c.get("id") for c in tree.getroot().findall("channel")}
        progs = tree.getroot().findall("programme")
        check(ms["channels"] == len(chans) and chans <= wanted, f"merged guide has only wanted channels ({len(chans)})")
        check(any(c.startswith("extra-") for c in chans) and any(c.startswith("ch") for c in chans),
              "merged guide combines both sources")
        check(all(p.get("channel") in chans for p in progs) and len(progs) == ms["programmes"] > 0, "programmes match channels")
        outgz = os.path.join(tmp, "epg.xml.gz")
        epg.merge_xmltv([prov, extra], wanted, outgz, "test", gz=True)
        check(gzip.open(outgz).read(5) == b"<?xml", "gz merge output readable")
        # --- local guide files (plain path, file:// URL, .xml and .xml.gz, quotes from "Copy as path")
        lx = os.path.join(tmp, "my local guide.xml")
        lg = os.path.join(tmp, "other.xml.gz")
        now = int(time.time() // 3600) * 3600
        fmt = lambda t: time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(t))
        mk = lambda cid, name: (f'<channel id="{cid}"><display-name>{name}</display-name></channel>'
                                f'<programme start="{fmt(now)}" stop="{fmt(now + 3600)}" channel="{cid}"><title>T {cid}</title></programme>')
        open(lx, "w", encoding="utf-8").write("<?xml version='1.0'?><tv>" + mk("loc.1", "Local One") + mk("loc.2", "Local Two") + "</tv>")
        with gzip.open(lg, "wt", encoding="utf-8") as f:
            f.write("<?xml version='1.0'?><tv>" + mk("gz.1", "Zipped One") + "</tv>")
        check(epg.local_path('"%s"' % lx) == type(epg.local_path(lx))(lx), "quoted path (Copy as path) is understood")
        furl = "file://" + lg
        check(str(epg.local_path(furl)) == lg and epg.normalize_source(furl) == lg, "file:// address becomes a plain path")
        check(epg.local_path("http://x.tv/a.xml") is None and epg.local_path(f"http://127.0.0.1:{PORT}/extra_epg.xml.gz") is None,
              "web addresses are not mistaken for files")
        check(epg.label_for(lx) == "my local guide.xml", "local guide label is the file name")
        idx2, errs2 = epg.refresh_sources([("L", lx), ("G", furl), ("Missing", os.path.join(tmp, "nope.xml"))], "t")
        check(idx2.has("loc.1") and idx2.has("gz.1") and not idx2.has("nope"), "local .xml and .xml.gz guides are scanned in place")
        check(len(errs2) == 1 and "file not found" in errs2[0], "missing local file gives a clear error")
        check(idx2.match("Zipped One") == "gz.1", "name matching works for local guides")
        m_out = os.path.join(tmp, "m.xml")
        ms2 = epg.merge_xmltv([("L", lx), ("G", furl)], {"loc.1", "gz.1", "x"}, m_out, "t")
        mt = ET.parse(m_out).getroot()
        check({c.get("id") for c in mt.findall("channel")} == {"loc.1", "gz.1"} and ms2["programmes"] == 2,
              "merge combines a local .xml and a local .xml.gz")
        st1 = epg.local_stamp(lx)
        open(lx, "a").write(" ")
        check(st1 and epg.local_stamp(lx) != st1 and epg.local_stamp("http://x.tv/a.xml") is None, "local file changes are detectable")
        # --- A-Z sort within categories
        from core.models import Item as _Item
        from core.sorting import sort_key
        lib_s = Library()
        for i, (nm, cat) in enumerate([("Zed", "B"), ("The Alpha", "A"), ("Mike 10", "B"), ("Mike 2", "B"),
                                       ("beta", "A"), ("\u2605 Charlie", "A"), ("Solo", "C")]):
            it = _Item("live", i, nm, cat, num=float(i))
            lib_s.items.append(it)
            lib_s.index[it.key] = it
        before = {it.id: it.category for it in lib_s.items}
        n_s = lib_s.change(lib_s.sort_az_changes(("live",)), "sort A-Z")
        order = [it.name for it in lib_s.ordered("live")]
        a_names = [n for n in order if n in ("The Alpha", "beta", "\u2605 Charlie")]
        b_names = [n for n in order if n in ("Zed", "Mike 10", "Mike 2")]
        check(a_names == ["The Alpha", "beta", "\u2605 Charlie"], f"category A sorted A-Z ({a_names})")
        check(b_names == ["Mike 2", "Mike 10", "Zed"], f"numbers sort naturally ({b_names})")
        check([it.category for it in lib_s.ordered("live")][1] in ("A", "B") and before == {it.id: it.category for it in lib_s.items},
              "sorting never changes names or categories")
        check(not any("num" in it.edits for it in lib_s.items), "sorting doesn't mark items as edited")
        check(lib_s.change(lib_s.sort_az_changes(("live",)), "again") == 0, "sorting twice changes nothing")
        lib_s.undo()
        check([it.name for it in lib_s.ordered("live")][0] == "Zed", "undo restores the old order")
        only_c = lib_s.sort_az_changes(("live",), {"C"})
        check(only_c == [], "limiting to one category leaves the others alone")
        # one big A-Z list, no matter the category
        n_all = lib_s.change(lib_s.sort_az_changes(("live",), None, "all"), "sort all")
        big = [it.name for it in lib_s.ordered("live")]
        check(big == sorted(big, key=sort_key), f"one big A-Z list ({big})")
        check(before == {it.id: it.category for it in lib_s.items}, "big list sort keeps every item's category")
        check(lib_s.change(lib_s.sort_az_changes(("live",), None, "all"), "again") == 0, "big list sort twice changes nothing")
        lib_s.undo()
        b_before = {it.id: it.num for it in lib_s.items if it.category == "B"}
        only_ab = lib_s.sort_az_changes(("live",), {"A", "C"}, "all")
        lib_s.change(only_ab, "partial")
        check({it.id: it.num for it in lib_s.items if it.category == "B"} == b_before,
              "big list limited to some categories leaves the rest in their slots")
        lib_s.undo()
        # --- proper-case suggestions for category names
        from core.casing import DEFAULT_STANDARD, parse_extra, proper_case
        for src, want in (("UK DRAMA", "UK Drama"), ("24/7 CARTOON NETWORK", "24/7 Cartoon Network"),
                          ("US | SPORTS NBA", "US | Sports NBA"), ("de | sport", "DE | Sport"),
                          ("the lord of the rings", "The Lord of the Rings"), ("NEWS & WEATHER", "News & Weather"),
                          ("MOVIES - ACTION AND ADVENTURE", "Movies - Action and Adventure"),
                          ("4K UHD movies", "4K UHD Movies"), ("kids/family", "Kids/Family"),
                          ("BritBox originals", "BritBox Originals"), ("in the news", "In the News")):
            got = proper_case(src, parse_extra(DEFAULT_STANDARD))
            check(got == want, f"proper case: {src!r} -> {got!r}")
        std = parse_extra(DEFAULT_STANDARD)
        check(proper_case("amc+ and mgm+ originals", std) == "AMC+ and MGM+ Originals", "AMC+ / MGM+ keep their plus signs")
        check(proper_case("nfl network on espn", std) == "NFL Network on ESPN", "standard networks and leagues stay uppercase")
        check(proper_case("nfl network") == "Nfl Network", "without the standard list, they are capitalized like normal words")
        check(proper_case("uk drama hd") == "UK Drama HD", "structural acronyms are always uppercase")
        check(proper_case("bbc iplayer", parse_extra("iplayer, BBC")) == "BBC IPLAYER", "your own always-uppercase words are honored")
        check(proper_case(proper_case("LIVE: PPV EVENTS", std), std) == proper_case("LIVE: PPV EVENTS", std), "proper case is stable when run twice")
    finally:
        srv.terminate()
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
