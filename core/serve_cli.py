"""No-window mode:  python main.py --serve [project.xtp]   (this file never imports Qt)."""
from __future__ import annotations

import os
import re
import sys
import time

from . import settings as cfg
from .models import KINDS, Library
from .xtream import XtreamClient, fetch_all
from .xtream_server import XtreamServer


def parse_hhmm(text):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"'{text}' isn't a time like 03:00")
    return int(m.group(1)), int(m.group(2))


def next_run(after, hhmm):
    """Next local-clock occurrence of HH:MM strictly after the timestamp `after`."""
    h, m = parse_hhmm(hhmm)
    t = time.localtime(after)
    for add in (0, 1):
        cand = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + add, h, m, 0, 0, 0, -1))
        if cand > after:
            return cand


def refresh_project(project, fetch=fetch_all):
    """Re-pull the provider list and fold it into the project file (edits kept). Returns (library, info).
    Refuses to apply a result that looks like a provider glitch (a section suddenly far smaller)."""
    conn = Library()
    conn.load(project)
    fresh = fetch(XtreamClient(**conn.connection), lambda p, m="": None)["items"]
    lib = Library()
    lib.load(project)                                 # re-read: you may have saved while we were fetching
    for kind in KINDS:
        have = sum(1 for it in lib.items if it.kind == kind and not it.gone)
        got = sum(1 for it in fresh if it.kind == kind)
        if have >= 20 and got < have * 0.5:
            raise RuntimeError(f"provider returned only {got:,} {kind} items (we have {have:,}), "
                               "so I'm not applying it")
    info = lib.merge_server(fresh)
    lib.save(project)
    return lib, info


def run(args):
    from .terms import SERVER_NOTICE
    print(SERVER_NOTICE + "\n")
    s = cfg.load()
    project = args.serve if isinstance(args.serve, str) and args.serve != "LAST" else s.get("last_project")
    if not project or not os.path.exists(project):
        print("I can't find a project to serve. Open the app once, fetch your list, save it (Ctrl+S),\n"
              "or pass the file:  python main.py --serve path\\to\\project.xtp")
        return 2
    lib = Library()
    lib.load(project)
    if not lib.connection.get("server"):
        print("That project has no provider login saved. Fetch from the server in the app first.")
        return 2

    fresh_items = None
    if args.refresh:
        print("Refreshing from the provider (your edits are kept)...")
        res = fetch_all(XtreamClient(**lib.connection), lambda p, m="": None)
        fresh_items = res["items"]
        print("  ", lib.merge_server(fresh_items))

    # command line wins, then saved settings
    port = args.port or int(s.get("xs_port", 8090))
    user = args.user or s.get("xs_user") or "local"
    password = args.password or s.get("xs_pass")
    if not password:
        password = cfg.make_password()
        s["xs_pass"] = password
        cfg.save(s)
    mode = "proxy" if args.proxy else s.get("xs_mode", "redirect")
    epg_mode = "none" if args.no_epg else s.get("xs_epg", "merged")

    refresh_at = None if args.no_auto_refresh else (args.refresh_at or s.get("xs_refresh_at", "03:00"))
    if refresh_at:
        try:
            parse_hhmm(refresh_at)
        except ValueError as e:
            print(f"Bad --refresh-at: {e}")
            return 2

    srv = XtreamServer()
    srv.echo = print
    try:
        srv.start(lib, port, user, password, mode, epg_mode, int(s.get("xs_epg_hours", 12)),
                  placeholders=bool(args.placeholder_epg or s.get("xs_placeholders", False)))
    except OSError as e:
        print(f"Couldn't start on port {port}: {e}\nTry another port with --port.")
        return 1
    print("\n  Xtream server is running. In your IPTV app add an Xtream login:")
    print(f"     Server:    {srv.base_url()}")
    print(f"     Username:  {user}")
    print(f"     Password:  {password}")
    print(f"     Guide:     {srv.epg_status()}")
    print("  Save in the editor and this picks up your changes by itself (refresh the app to see them).")
    next_at = None
    if refresh_at:
        next_at = time.time() + args.first_refresh_in if args.first_refresh_in else next_run(time.time(), refresh_at)
        print(f"  Re-syncing with your provider every day at {refresh_at} (this PC's clock); next: "
              f"{time.strftime('%a %H:%M', time.localtime(next_at))}.")
    print("  Leave this window open (minimizing is also fine). Ctrl+C to stop.\n")

    def stamp():
        try:
            st = os.stat(project)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    last, bad = stamp(), None
    try:
        while True:
            time.sleep(2)
            if next_at and time.time() >= next_at:
                srv.log("daily re-sync with the provider: starting...")
                try:
                    lib2, info = refresh_project(project)
                    old_ids = set(srv.snap.wanted_epg)
                    srv.update(lib2)
                    last, bad, fresh_items = stamp(), None, None
                    srv.log(f"daily re-sync done: {info['added']:,} new, {info['gone']:,} gone, "
                            f"{info['total']:,} total")
                    if srv.snap.wanted_epg != old_ids:
                        srv.rebuild_guide()
                    next_at = next_run(time.time(), refresh_at)
                except Exception as e:                 # noqa: BLE001 - provider down etc.: keep serving, retry soon
                    srv.log(f"daily re-sync failed ({e}); still serving the current list, trying again in 30 minutes")
                    next_at = time.time() + 1800
                continue
            now = stamp()
            if not now or now == last or now == bad:
                continue
            time.sleep(1)                          # let a save in progress finish
            now = stamp()
            try:
                new = Library()
                new.load(project)
                if not new.connection.get("server"):
                    raise ValueError("no provider login in the file")
                if fresh_items is not None:        # keep the startup --refresh results
                    new.merge_server(fresh_items)
            except Exception as e:                 # noqa: BLE001 - half-written or bad file: keep serving the old list
                srv.log(f"project file changed but couldn't be read ({e}); still serving the previous version")
                bad = now
                continue
            old_ids = set(srv.snap.wanted_epg)
            srv.update(new)
            last, bad = now, None
            c = srv.snap.counts()
            srv.log(f"project reloaded: {c['live']:,} live, {c['vod']:,} movies, {c['series']:,} series")
            if srv.snap.wanted_epg != old_ids:
                srv.rebuild_guide()                # EPG IDs changed, so refresh the guide now
    except KeyboardInterrupt:
        pass
    srv.stop()
    return 0
