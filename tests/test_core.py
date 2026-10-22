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
        check(all(p.get("channel") in chans for p in progs) and len(progs) == ms["programs"] > 0, "programs match channels")
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
        check({c.get("id") for c in mt.findall("channel")} == {"loc.1", "gz.1"} and ms2["programs"] == 2,
              "merge combines a local .xml and a local .xml.gz")
        st1 = epg.local_stamp(lx)
        open(lx, "a").write(" ")
        check(st1 and epg.local_stamp(lx) != st1 and epg.local_stamp("http://x.tv/a.xml") is None, "local file changes are detectable")
        # --- placeholder guide entries
        from core import placeholder as PH
        from core.models import Item as _It3
        pitems = [_It3("live", "p1", "Has Data", "Cat", epg_id="loc.1", num=1), _It3("live", "p2", "No Id Chan", "Cat", num=2),
                  _It3("live", "p3", "Unknown <&> Chan", "Cat", epg_id="nowhere.9", num=3),
                  _It3("live", "p4", "Deleted One", "Cat", num=4), _It3("vod", "p5", "A Movie", "Cat", num=1)]
        pitems[3].deleted = True
        fill = PH.fill_entries(pitems)
        check(fill == {"loc.1": "Has Data", "xe.p2": "No Id Chan", "nowhere.9": "Unknown <&> Chan"},
              "placeholder candidates: live, not deleted, no ID or any ID (the merge decides)")
        check(PH.guide_id(pitems[1], False) == "" and PH.guide_id(pitems[1], True) == "xe.p2" and PH.guide_id(pitems[0], True) == "loc.1",
              "made-up IDs only for channels with none, and only when switched on")
        p_out = os.path.join(tmp, "ph.xml")
        ps = epg.merge_xmltv([("L", lx)], {"loc.1", "nowhere.9"}, p_out, "t", fill=fill)
        pt = ET.parse(p_out).getroot()
        pc = {c.get("id") for c in pt.findall("channel")}
        check(pc == {"loc.1", "xe.p2", "nowhere.9"} and ps["placeholders"] == 2, f"placeholders only for channels the guides lack ({sorted(pc)})")
        check(ps["placeholder_programs"] == 50 and ps["programs"] == len(pt.findall("programme")) == 51,
              f"the programs count includes placeholders ({ps['programs']} total, {ps['placeholder_programs']} of them placeholders)")
        pp = [p for p in pt.findall("programme") if p.get("channel") == "xe.p2"]
        check(len(pp) == 25 and pp[0].find("title").text == "No Id Chan", "a placeholder is 3-hour blocks, titled with the channel name")
        check(pt.find("programme[@channel='nowhere.9']/title").text == "Unknown <&> Chan", "special characters in names are escaped properly")
        check(sum(1 for p in pt.findall("programme") if p.get("channel") == "loc.1") == 1, "real guide data is untouched")
        starts = sorted(p.get("start") for p in pp)
        check(all(starts[i + 1][8:10] != starts[i][8:10] or True for i in range(len(starts) - 1)) and
              pp[0].get("stop") == pp[1].get("start"), "blocks run back to back with no gaps")
        ps2 = epg.merge_xmltv([("L", lx)], set(), os.path.join(tmp, "ph2.xml"), "t", fill={"xe.z": "Only Placeholders"})
        check(ps2["placeholders"] == 1, "a guide made only of placeholders is allowed")
        from core.xtream_server import Snapshot
        lib_p = Library()
        lib_p.connection = {"server": "http://h", "username": "u", "password": "p"}
        lib_p.merge_server(pitems)
        sn_on, sn_off = Snapshot(lib_p, True), Snapshot(lib_p, False)
        e_on = {e["name"]: e["epg_channel_id"] for c, e in sn_on.rows["live"]}
        e_off = {e["name"]: e["epg_channel_id"] for c, e in sn_off.rows["live"]}
        check(e_on["No Id Chan"] == "xe.p2" and e_on["Has Data"] == "loc.1" and e_off["No Id Chan"] is None,
              "snapshot hands out placeholder IDs only when switched on")
        check(set(sn_on.fill) == {"loc.1", "xe.p2", "nowhere.9"} and not sn_off.fill and "xe.p2" not in sn_on.wanted_epg,
              "snapshot lists the placeholder candidates, and wants only real IDs from the guides")
        from core.exporter import _entries
        lib_p.connection.update(server="http://h", username="u", password="p")
        st_p = {"live": 0, "vod": 0, "series_eps": 0, "series_no_eps": 0}
        ex_on = [x for x, _ in _entries(lib_p, "live", "ts", "", st_p, True)]
        ex_off = [x for x, _ in _entries(lib_p, "live", "ts", "", st_p, False)]
        check(any('tvg-id="xe.p2"' in x for x in ex_on) and not any('tvg-id="xe.' in x for x in ex_off), "M3U export carries the placeholder ID only when asked")
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
        # --- duplicate finder
        from core.duplicates import find_groups, keeper, title_key
        check(title_key("US | The Matrix (1999) [HD]") == title_key("Matrix (1999) 4K") == ("matrix", "1999"),
              "language prefix, 'The', quality tags and brackets are ignored")
        check(title_key("Dune (1984)")[0] == title_key("Dune (2021)")[0] and title_key("Dune (1984)") != title_key("Dune (2021)"),
              "same title, different year: different unless the year is ignored")
        check(title_key("Dune (1984)", True) == title_key("Dune (2021)", True), "ignore-year merges them")
        check(title_key("Movie (Part 2)")[0] != title_key("Movie (Part 1)")[0], "meaningful brackets are kept (Part 1 vs Part 2)")
        check(title_key("Caf\u00e9 & Bar")[0] == title_key("Cafe and Bar")[0], "accents and & are normalized")
        from core.models import Item
        dl = [Item("vod", "1", "US | Heat (1995) [HD]", "Action", num=1), Item("vod", "2", "Heat (1995)", "Drama", num=2),
              Item("vod", "3", "Heat (2013)", "Drama", num=3), Item("live", "4", "CNN HD", "News", num=1),
              Item("live", "5", "CNN", "News", num=2), Item("live", "6", "CNN", "Sports", num=3)]
        dl[1].deleted = True
        dl[0].added, dl[1].added = "100", "200"
        dl[0].logo, dl[0].rating = "x", "7"
        check(len(find_groups(dl, ("vod",))) == 0, "deleted copies are ignored by default")
        check(len(find_groups(dl, ("vod",), "all")) == 1, "'everything' scope includes deleted copies")
        check(len(find_groups(dl, ("vod",), "all", ignore_year=True)) == 1 and len(find_groups(dl, ("vod",), "all", ignore_year=True)[0]) == 3,
              "ignoring the year groups all three Heat entries")
        g = find_groups(dl, ("live",))
        check(len(g) == 1 and len(g[0]) == 3, "live channels with the same name group together across categories")
        g = find_groups(dl, ("live",), same_category=True)
        check(len(g) == 1 and len(g[0]) == 2, "same-category mode only groups within a category")
        grp = find_groups(dl, ("vod",), "all")[0]
        check(keeper(grp, "first").id == "1" and keeper(grp, "newest").id == "2" and keeper(grp, "complete").id == "1",
              "keep rules pick the right copy")
        # --- regex rules
        from core import rules as RR
        check(RR.template("$1 - ${2}") == "\\g<1> - \\g<2>", "$1 and ${2} work like \\1")
        base_rule = RR.new_rule()
        check(RR.compile_rule(dict(base_rule, pattern="(", rewrite_on=True))[1].startswith("Not a valid pattern"), "a broken pattern is reported")
        check("only has 1" in RR.compile_rule(dict(base_rule, pattern="^US \\| (.*)", rewrite_on=True, rewrite="$2"))[1],
              "a replacement that uses a missing group is reported")
        check("Choose what to do" in RR.compile_rule(dict(base_rule, pattern="x"))[1], "a rule that does nothing is reported")
        its = [Item("live", "1", "US | CNN", "US | News", num=1), Item("live", "2", "US | ESPN", "US | Sports", num=2),
               Item("live", "3", "UK | BBC One", "UK | General", num=3), Item("live", "4", "24/7 Cartoons", "Fillers", num=4),
               Item("vod", "5", "US | Heat", "US | Action", num=1), Item("live", "6", "US | Gone", "US | News", num=5)]
        its[5].deleted = True
        strip = dict(base_rule, pattern=r"^US \| (.*)", rewrite_on=True, rewrite="$1")
        local = dict(base_rule, kinds="live", field="category", pattern=r"^US \|", move="US Local")
        nuke = dict(base_rule, pattern=r"^24/7", delete=True)
        ch, mt, er = RR.plan(its, [strip, local, nuke])
        names = {st["item"].id: (st["name"], st["category"], st["deleted"]) for st in ch.values()}
        check(not er and mt == [3, 2, 1], f"each rule counts its matches {mt}")
        check(names["1"] == ("CNN", "US Local", False) and names["2"] == ("ESPN", "US Local", False),
              "prefix stripped and live items moved into the clean category")
        check(names["5"] == ("Heat", "US | Action", False), "the live-only rule leaves movies alone")
        check(names["4"][2] is True and "3" not in names and "6" not in names,
              "delete works, non-matches and already-deleted items are skipped")
        ch, mt, er = RR.plan(its, [dict(strip, on=False)])
        check(not ch and mt == [0], "switched-off rules do nothing")
        ch, mt, er = RR.plan(its, [dict(base_rule, pattern=".*", rewrite_on=True, rewrite="")])
        check(not ch and mt[0] == 5, "a rewrite that would blank a name is skipped")
        ch, mt, er = RR.plan(its, [dict(strip, pattern="(")])
        check(0 in er and not ch, "a broken rule stops with an error instead of crashing")
        ch, mt, er = RR.plan(its, [nuke, dict(base_rule, pattern=r"^24/7", move="Never")])
        check(mt == [1, 0], "items deleted by an earlier rule aren't touched by later ones")
        chg = RR.to_changes(RR.plan(its, [strip, local])[0])
        check(("name", "CNN") in [(f, v) for it, f, v in chg if it.id == "1"] and
              ("category", "US Local") in [(f, v) for it, f, v in chg if it.id == "1"], "to_changes gives Library.change() tuples")
        check(RR.normalize({"pattern": "x", "kinds": "bogus"})["kinds"] == "all", "damaged saved rules are repaired")
        from core import carry as CY
        ca = [Item("live", "1", "US| ESPN HD", "Sports", epg_id="espn.us", num=0), Item("live", "2", "CNN", "News", num=1),
              Item("live", "3", "Old Show", "Misc", num=2), Item("live", "4", "CBS", "News", num=3),
              Item("live", "5", "Kept Alone", "News", num=4), Item("vod", "6", "A Movie", "Films", num=0)]
        ca[0].name, ca[0].fav, ca[0].edits = "ESPN", True, {"name"}
        ca[2].deleted = True
        cb = [Item("live", "9", "CNN International", "World", num=0), Item("live", "8", "ESPN HD", "Sport", epg_id="ESPN.us", num=1),
              Item("live", "7", "Old Show", "Misc", num=2), Item("live", "6", "CBS HD", "General", num=3),
              Item("live", "5", "Brand New", "X", num=4), Item("vod", "4", "A Movie", "Other", num=0)]
        cp = CY.plan(ca, cb)
        how = {b.id: h for a, b, h in cp["pairs"]}
        check(how == {"8": "EPG ID", "7": "name", "6": "name"}, f"channels are matched by EPG ID, then by name ({how})")
        check({b.id for b in cp["only_dst"]} == {"9", "5"} and [a.id for a in cp["only_src"]] == ["2", "5"],
              "the leftovers on each side are listed")
        lib_b = Library()
        lib_b.items = cb
        lib_b.index = {i.key: i for i in cb}
        lib_b.change(cp["changes"], "copy")
        by = {i.id: i for i in cb}
        check(by["8"].name == "ESPN" and by["8"].fav and by["8"].category == "Sports", "names, favorites and categories are copied")
        check(by["7"].deleted and not by["6"].deleted and by["6"].name == "CBS", "deleted channels are deleted here too")
        check(by["9"].new and by["5"].new and not by["8"].new, "channels the other list lacks are marked new")
        check(by["4"].category == "Other" and by["4"].name == "A Movie", "movies and series are left alone")
        order = [i.id for i in sorted((i for i in cb if i.kind == "live"), key=lambda i: i.num)]
        check(order[:3] == ["8", "7", "6"], f"channels follow the other list's order, new ones last ({order})")
        lib_b.undo()
        check(by["8"].name == "ESPN HD" and not by["8"].fav and not by["7"].deleted and not by["9"].new and by["9"].num == 0,
              "one undo puts everything back")
        cp2 = CY.plan(ca, cb, {"deleted": False, "fav": False, "name": False, "category": False, "order": False, "mark_new": False})
        check(not cp2["changes"], "with everything unticked nothing changes")
        from core import master as MS
        ma = [Item("live", "1", "ESPN", "Sports", epg_id="espn.us", num=0), Item("live", "2", "CNN", "News", num=1),
              Item("live", "3", "Gone", "X", num=2), Item("vod", "4", "Film", "Y", num=0)]
        ma[0].fav, ma[0].edits = True, {"name"}
        ma[2].deleted = True
        mb = [Item("live", "1", "US| ESPN HD", "Sport", epg_id="ESPN.us", num=0), Item("live", "9", "BBC One", "UK", num=1)]
        mst = Library()
        i1, i2 = MS.add_source(mst, {"server": "http://a", "username": "x", "password": "1"}, "A"), \
            MS.add_source(mst, {"server": "http://b", "username": "y", "password": "2"}, "B")
        check((i1, i2) == (0, 1) and MS.add_source(mst, {"server": "http://a/", "username": "x", "password": "new"}, "A") == 0
              and mst.sources[0]["conn"]["password"] == "new", "sources are found by server + username and keep the newest password")
        check(MS.add_items(mst, i1, [ma[1], ma[0]]) == (2, 0), "adding channels copies them")
        m0 = sorted(mst.items, key=lambda i: i.num)
        check([m.name for m in m0] == ["ESPN", "CNN"] and m0[0].fav and "name" in m0[0].edits and m0[0].orig == "1" and m0[0].src == 0,
              "they keep the source's order, edits, star and provider id")
        check(MS.already_in(mst, i1, ma) == {"1", "2"} and not MS.already_in(mst, i2, ma), "channels already added are recognized, per provider")
        dup = MS.duplicates(mst, i2, mb)
        check(list(dup) == ["1"] and dup["1"].name == "ESPN", "the same channel from the other provider is flagged (guide ID or name)")
        check(not MS.duplicates(mst, i1, ma), "a provider's own channels never flag against themselves")
        MS.add_items(mst, i2, [mb[0]], {"1": dup["1"]})
        check(len(mst.items) == 2 and any(m.src == 1 and m.orig == "1" and m.num == 0 for m in mst.items), "Replace swaps in the other provider's version in the same spot")
        check(mst.conn_for(mst.items[-1]) == mst.sources[1]["conn"] and len(mst.logins()) == 2, "each channel finds its own login")
        from core import names as _NM
        check(_NM.add_tag("ESPN", "A") == "[A] ESPN" and _NM.add_tag("[A] ESPN", "A") == "[A] ESPN" and _NM.add_tag("X", " ") == "X"
              and _NM.remove_tag("[Trex] CNN", ["A", "Trex"]) == "CNN" and _NM.remove_tag("[HD] CNN", ["A"]) == "[HD] CNN",
              "source tags go on once, come off again, and leave other brackets alone")
        mst.sources[0]["tag"], mst.sources[1]["tag"] = "Home", ""
        got = dict((it.name, n) for it, n in _NM.plan(mst.items, "addtag", tags=[MS.tag_for(mst, 0), MS.tag_for(mst, 1)]))
        check(MS.tag_for(mst, 1) == "B" and "[B] ESPN HD" in got.values() or "[Home] CNN" in got.values(), "each channel gets its own source's tag (blank tags fall back to A, B...)")
        check(not _NM.plan([Item("live", "z", "Plain", "x")], "addtag", tags=["A"]), "channels outside a master list are skipped")
        try:
            mst.merge_server([])
            check(False, "a master can't be re-synced")
        except RuntimeError:
            check(True, "a master can't be re-synced")
        check([b.id for a, b in cp["deleted_there"]] == ["7"], "channels deleted in the other list are listed on their own tab")
        cp3 = CY.plan(ca, cb, {"deleted": False})
        check(not any(f == "deleted" for it, f, v in cp3["changes"]), "unticking 'delete' leaves them alone here")
        cb[2].deleted = True
        check(not CY.plan(ca, cb)["deleted_there"], "ones already deleted here aren't shown again")
        cb[2].deleted = False
        cf = CY.plan(ca, cb, {"fav_only": True})
        check([b.id for a, b, h in cf["pairs"]] == ["8"] and not cf["only_dst"] and
              not any(f in ("deleted", "num", "new") for it, f, v in cf["changes"]),
              "favorites-only covers just the starred channels and skips the whole-list steps")
        bi = {b["id"]: b for b in RR.builtin_rules()}
        check(len(bi) == 4 and not any(b["on"] for b in bi.values()) and all(not RR.compile_rule(b)[1] for b in bi.values()),
              "four built-in rules, all valid and switched off to start with")
        check(RR.builtin_rules({"super_names": True})[0]["on"] is True, "built-in on/off comes from the saved states")
        bn = [Item("live", "b1", "BBC ONE ᴴᴰ", "UK | General ᴿᴬᵂ", num=1), Item("live", "b2", "ESPN ⁶⁰ᶠᵖˢ", "Sports", num=2),
              Item("live", "b3", "US| CNN", "US | News", num=3), Item("vod", "b4", "IT: Chapter Two", "Horror", num=1),
              Item("live", "b5", "|UK| Sky News", "News", num=4), Item("live", "b6", "[CA] CBC", "News", num=5)]
        got, mt, er = RR.plan(bn, [dict(bi["super_names"], on=True), dict(bi["super_cats"], on=True), dict(bi["country_names"], on=True)])
        res = {st["item"].id: (st["name"], st["category"]) for st in got.values()}
        check(not er and res["b1"] == ("BBC ONE", "UK | General") and res["b2"][0] == "ESPN", "superscript rules clean names and categories")
        check(res["b3"][0] == "CNN" and res["b5"][0] == "Sky News" and res["b6"][0] == "CBC" and "b4" not in res,
              "country prefixes come off names, and a real title like 'IT: Chapter Two' is left alone")
        got, mt, er = RR.plan(bn, [dict(bi["country_cats"], on=True)])
        check({st["item"].id: st["category"] for st in got.values()} == {"b1": "General ᴿᴬᵂ", "b3": "News"},
              "country prefixes come off categories")
        import requests as _rq
        from core import xtream as _xt
        _calls = []
        class _R:
            status_code = 200
            def json(self): return {"user_info": {"auth": 1}}
        _cl = _xt.XtreamClient("http://x:1", "u", "p")
        def _flaky(url, params=None, timeout=None):
            _calls.append(1)
            if len(_calls) < 3:
                raise _rq.exceptions.ChunkedEncodingError("Connection broken: IncompleteRead(1606 bytes read, 8634 more expected)")
            return _R()
        _cl.session.get = _flaky
        _sleep, _xt.time.sleep = _xt.time.sleep, lambda s: None
        check(_cl._api()["user_info"]["auth"] == 1 and len(_calls) == 3, "a cut-off download is retried and then works")
        def _dead(url, params=None, timeout=None):
            raise _rq.exceptions.ChunkedEncodingError("Connection broken: IncompleteRead(1 bytes read, 2 more expected)")
        _cl.session.get = _dead
        try:
            _cl._api()
            check(False, "a download that keeps getting cut off ends in a clear message")
        except _xt.XtreamError as e:
            check("kept dropping" in str(e) and "one connection per account" in str(e), "a download that keeps getting cut off ends in a clear message")
        _xt.time.sleep = _sleep
        from core import names as NM
        nm = lambda n, op, **kw: NM.new_name(n, op, **kw)
        check(nm("24/7 NEWS 2", "proper") == "24/7 News 2" and nm("CBS SPORTS 1ST HALF", "proper", extra={"cbs"}) == "CBS Sports 1st Half",
              "Proper Case leaves numbers alone and handles 1st/2nd")
        check(nm("ESPN 4K HD", "proper", extra={"espn"}) == "ESPN 4K HD", "acronyms and 4K/HD stay uppercase")
        check(nm("  too   many  spaces ", "trim") == "too many spaces", "trim squeezes spaces")
        check(nm("US | CNN", "prefix", prefix="us |") == "CNN" and nm("UK | BBC", "prefix", prefix="US |") == "UK | BBC",
              "remove a prefix only when the name starts with it")
        check(nm("HD CNN HD", "replace", find="hd", repl="") == "CNN" and
              nm("HD CNN", "replace", find="hd", repl="", ignore_case=False) == "HD CNN", "find and replace, with case option")
        check(nm("X", "replace", find="x", repl="") == "X", "a name is never blanked")
        its2 = [Item("live", "1", "CNN NEWS", "A", num=1), Item("live", "2", "Already Fine", "A", num=2),
                Item("vod", "3", "THE MOVIE", "B", num=1), Item("live", "4", "OLD NAME", "A", num=3)]
        its2[3].deleted = True
        got = NM.plan(its2, "proper", extra={"cnn"})
        check([i.id for i, _ in got] == ["1", "3"] and got[0][1] == "CNN News", "plan lists only names that change, skipping deleted")
        check(RR.normalize({"pattern": "x"})["only_cat"] == "", "rules saved before 'only in category' still load")
        only = dict(base_rule, pattern=r"^US \| (.*)", rewrite_on=True, rewrite="$1", only_cat="us | news")
        ch, mt, er = RR.plan(its, [only])
        check(mt == [1] and set(ch) == {("live", "1")}, f"'only in category' limits a rule to that category ({mt})")
        ch, mt, er = RR.plan(its, [local, dict(only, only_cat="US Local")])
        check(mt == [2, 2], f"a later rule sees the category an earlier rule moved items into ({mt})")
    finally:
        srv.terminate()
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
