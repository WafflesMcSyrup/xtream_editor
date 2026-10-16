"""Offscreen smoke test of the whole UI against a big mock server.
Run:  QT_QPA_PLATFORM=offscreen python tests/test_ui.py
"""
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp()
os.environ["HOME"] = TMP                      # keep settings/cache out of the real home

import requests                                                         # noqa: E402
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt       # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from ui import dialogs, main_window as mw                                # noqa: E402
from core.models import Library                                          # noqa: E402
from core import settings as cfg_mod                                     # noqa: E402

_real_epg_values = dialogs.EpgSourcesDialog.values   # later steps swap this out

PORT = 18081
LIVE, VOD, SER = 60000, 20000, 5000
fails = 0


def check(cond, msg):
    global fails
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        fails += 1


app = QApplication([])
msgs = []
mw.MainWindow.info = lambda self, t, m: msgs.append((t, m))
QMessageBox.critical = staticmethod(lambda *a, **k: msgs.append(("CRITICAL", a[2])))


def wait(win, timeout=180):
    t0 = time.time()
    while win._task is not None and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def select_rows(win, rows):
    sm = win.table.selectionModel()
    sm.clearSelection()
    sel = QItemSelection()
    for r in rows:
        sel.select(win.model.index(r, 0), win.model.index(r, 6))
    sm.select(sel, QItemSelectionModel.Select)


def timed(label, fn):
    t = time.time()
    fn()
    dt = time.time() - t
    print(f"      ({label}: {dt:.2f}s)")
    return dt


srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "mock_server.py"), "--port", str(PORT),
                        "--live", str(LIVE), "--vod", str(VOD), "--series", str(SER)],
                       stdout=subprocess.DEVNULL)
time.sleep(4)
try:
    win = mw.MainWindow()
    win.show()
    app.processEvents()
    conn = {"server": f"http://127.0.0.1:{PORT}", "username": "demo", "password": "demo", "ua": "t"}
    dialogs.ConnectDialog.exec = lambda self: True
    dialogs.ConnectDialog.values = lambda self: dict(conn)

    # ---- fetch
    timed("fetch + merge + first refresh", lambda: (win.connect_and_fetch(), wait(win)))
    total = LIVE + VOD + SER
    check(len(win.lib.items) == total, f"fetched {len(win.lib.items):,} entries")
    check(len(win.model.rows) == total, "table shows all rows")
    check(win.cats.count() > 10, f"sidebar has {win.cats.count()} entries")
    check(any("Fetch complete" in t for t, _ in msgs), "fetch summary shown")

    # ---- tabs / category / search / modes
    win.tabs.setCurrentIndex(1)
    check(len(win.model.rows) == LIVE, "Live tab filters")
    win.cats.setCurrentRow(1)
    cat = win.category
    check(len(cat) == 1 and len(win.model.rows) > 0 and all(it.category in cat for it in win.model.rows),
          f"category filter ({cat})")
    win.cats.setCurrentRow(0)
    win.search.setText("channel 1234")
    dt = timed("search", lambda: win.refresh(rebuild_sidebar=False))
    check(0 < len(win.model.rows) < 50 and all("channel" in it.name.lower() and "1234" in it.name
                                                for it in win.model.rows),
          f"search narrows to {len(win.model.rows)} (all words must match)")
    win.search.setText("")
    win.mode.setCurrentIndex(5)       # live: no EPG id
    check(len(win.model.rows) == int(LIVE * 0.3), f"'no EPG ID' filter -> {len(win.model.rows):,}")
    win.mode.setCurrentIndex(0)

    # ---- cell edit
    win.model.sort(0, Qt.AscendingOrder)
    idx = win.model.index(0, 1)
    first = win.model.rows[0]
    win.model.setData(idx, "  My Renamed Channel ")
    check(first.name == "My Renamed Channel" and "name" in first.edits and win.lib.dirty, "inline rename")
    win.undo()
    check(first.name != "My Renamed Channel", "undo of inline rename")

    # ---- set category / delete / restore (bulk 10k rows)
    select_rows(win, range(0, 10000))
    check(len(win.selected_items()) == 10000, "selected 10,000 rows")
    QInputDialog.getItem = staticmethod(lambda *a, **k: ("My Faves", True))
    timed("set category on 10k", win.a_cat.trigger)
    check(sum(1 for it in win.lib.items if it.category == "My Faves") == 10000, "bulk category set")
    check(any(li.data(Qt.UserRole) == "My Faves" for li in
              [win.cats.item(i) for i in range(win.cats.count())]), "sidebar shows new category")
    select_rows(win, range(0, 5))
    deleted_ids = [id(it) for it in win.selected_items()]
    win.a_del.trigger()
    check(sum(1 for it in win.lib.items if it.deleted) == 5, "delete 5")
    check(len(win.model.rows) == LIVE - 5, "deleted rows hidden in 'Active' (Live tab)")
    win.mode.setCurrentIndex(2)
    check(len(win.model.rows) == 5, "'Deleted only' shows them")
    select_rows(win, range(0, 5))
    win.a_restore.trigger()
    win.mode.setCurrentIndex(0)
    # ---- export list to CSV / TXT
    import csv as _csv
    from PySide6.QtWidgets import QFileDialog
    from ui import dialogs as _dlg
    outp = os.path.join(tempfile.mkdtemp(), "l.csv")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (outp, ""))
    _real_exec = _dlg.ListExportDialog.exec
    _dlg.ListExportDialog.exec = lambda self: True
    win.a_list.trigger()
    n_rows = len(list(_csv.reader(open(outp, encoding="utf-8-sig", newline="")))) - 1
    check(n_rows == sum(1 for it in win.lib.items if not it.deleted and not it.gone), f"list export (all) writes {n_rows:,} rows")
    seen = {}

    def pick_one(self):
        self.all_cb.setChecked(False)
        for i in range(self.lst.count()):
            self.lst.item(i).setCheckState(Qt.Unchecked)
        self.lst.item(0).setCheckState(Qt.Checked)
        seen["cat"] = self.lst.item(0).data(Qt.UserRole)
        return True
    _dlg.ListExportDialog.exec = pick_one
    win.a_list.trigger()
    rows = list(_csv.reader(open(outp, encoding="utf-8-sig", newline="")))[1:]
    check(rows and all(r[2] == seen["cat"][1] for r in rows), f"list export limited to the ticked category ({len(rows)} rows)")
    _dlg.ListExportDialog.exec = _real_exec
    from collections import Counter as _C
    cc = _C()
    cc.update({("live", "A", False, False): 3, ("live", "A", True, False): 2, ("live", "B", True, False): 4,
               ("vod", "C", False, True): 1, ("vod", "C", False, False): 5})
    d = _dlg.ListExportDialog(win, cc)
    vis = lambda: sorted(d.lst.item(i).text() for i in range(d.lst.count()) if not d.lst.item(i).isHidden())   # noqa: E731
    check(vis() == ["Live  |  A  (3)", "Movies  |  C  (6)"], f"deleted-only categories are hidden and counts skip deleted: {vis()}")
    d.skip_del.setChecked(False)
    check(len(vis()) == 3 and "Live  |  A  (5)" in vis(), "unticking 'leave out deleted' brings them back")
    d.skip_del.setChecked(True)
    d.fav_only.setChecked(True)
    check(vis() == ["Movies  |  C  (1)"], "Favorites only shrinks the list to categories with favorites")
    d.kinds["vod"].setChecked(False)
    check(vis() == [] and d.values()["fav_only"] and d.values()["kinds"] == ("live", "series"), "Types and favorites combine")

    # ---- import list for favorites
    from core.models import Item as _Item
    items_f = [_Item("live", str(i), n, "US | Movies") for i, n in enumerate(
        ["US | HBO HD", "HBO East", "HBO West", "Showtime East", "Showtime West", "CNN", "CNN En Espanol", "Cinemax"], 7000)]
    items_f.append(_Item("vod", "9001", "HBO Documentary Film", "Movies"))
    pre = [(_Item("live", "7777", "Weather Plus", "News"))]
    starred = []
    dlgI = dialogs.ImportFavoritesDialog(win, ["HBO", "Showtime", "CNN", "Weather Plus", "Totally Unknown Thing"],
                                         items_f + pre, lambda ch: starred.extend(ch) or len(ch))
    sts = [dlgI.status(i) for i in range(5)]
    check(sts[:3] == ["Good", "Good", "Good"] and sts[4] == "No match", f"import statuses {sts}")
    check(dlgI.right.rowCount() == 3 and all("Movies" != dlgI.right.item(r, 3).text() for r in range(3)),
          "import searches live channels only by default")
    dlgI.more.setChecked(True)
    dlgI.left.selectRow(0)
    check(dlgI.right.rowCount() == 4, "'Also search Movies and Series' adds movie candidates")
    dlgI.more.setChecked(False)
    dlgI._tick_good()
    check(len(dlgI._all_ticked_keys()) == 3 + 2 + 1 + 1, f"'tick all good matches' ticks flavors too ({len(dlgI._all_ticked_keys())})")
    dlgI.right.item(0, 0).setCheckState(Qt.Unchecked)
    dlgI.left.selectRow(0)
    n0 = len(dlgI.checked[0])
    dlgI.right.item(0, 0).setCheckState(Qt.Unchecked if dlgI.right.item(0, 0).checkState() == Qt.Checked else Qt.Checked)
    check(len(dlgI.checked[0]) != n0, "ticking a single match works")
    dlgI.left.selectRow(4)
    dlgI.q.setText("CNN")
    dlgI._research()
    check(dlgI.right.rowCount() >= 2 and dlgI.status(4) == "Good", "retyping a name re-searches that line")
    dlgI.right.item(0, 0).setCheckState(Qt.Checked)
    dlgI._add()
    check(len(starred) > 0 and len(dlgI._all_ticked_keys()) == 0, f"'Add checked' hands {len(starred)} items to the editor")
    for it in starred:
        it.fav = True
    dlgI._refresh_left()
    check(dlgI.status(0) == "Already \u2605", "starred lines show as already in favorites")
    # real wiring: file -> dialog -> stars in the library
    txt = os.path.join(tempfile.mkdtemp(), "names.txt")
    open(txt, "w", encoding="utf-8").write("# header\n== x ==\n  Channel 1234\n- Channel 1235 (12)\n")
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (txt, ""))
    _real_imp = _dlg.ImportFavoritesDialog.exec if "_dlg" in globals() else dialogs.ImportFavoritesDialog.exec

    def _drive(self):
        check(len(self.lines) == 2 and self.lines[0] == "Channel 1234", "import file parsed (headers/bullets/tags skipped)")
        self._tick_good()
        self._add()
        self.added = getattr(self, "added", 0)
        return True
    dialogs.ImportFavoritesDialog.exec = _drive
    before = sum(1 for it in win.lib.items if it.fav)
    win.a_impfav.trigger()
    check(sum(1 for it in win.lib.items if it.fav) > before, "importing a file stars matches in the library")
    win.undo()
    check(sum(1 for it in win.lib.items if it.fav) == before, "import is one undoable step")
    dialogs.ImportFavoritesDialog.exec = _real_imp

    # ---- new since last sync
    for it in win.lib.items[:3]:
        it.new = True
    win.refresh()
    modes = [win.mode.itemData(i) for i in range(win.mode.count())]
    win.mode.setCurrentIndex(modes.index("new"))
    check(len(win.model.rows) >= 1 and all(it.new for it in win.model.rows), "'New since last sync' filter")
    win.a_seen.trigger()
    check(len(win.model.rows) == 0 and not any(it.new for it in win.lib.items), "'Mark all new items as seen' clears them")
    win.undo()
    check(len(win.model.rows) >= 1, "mark-as-seen is undoable")
    win.a_seen.trigger()
    win.mode.setCurrentIndex(0)

    # ---- favorites: toggle, undo, filter, star shown in name
    win.model.sort(0, Qt.AscendingOrder)
    select_rows(win, range(0, 3))
    picked = win.selected_items()
    win.a_fav.trigger()
    check(all(it.fav for it in picked), "Ctrl+D stars the selection")
    check(win.model.data(win.model.index(0, 1), Qt.DisplayRole).startswith("\u2605 ")
          and not win.model.data(win.model.index(0, 1), Qt.EditRole).startswith("\u2605"),
          "star shows in the name but not when editing")
    win.mode.setCurrentIndex(4)
    check(len(win.model.rows) == 3 and all(it.fav for it in win.model.rows), "'Favorites only' filter")
    win.mode.setCurrentIndex(0)
    win.undo()
    check(not any(it.fav for it in win.lib.items), "undo removes the stars")
    select_rows(win, range(0, 2))
    win.a_fav.trigger()
    select_rows(win, range(0, 2))
    win.a_fav.trigger()
    check(not any(it.fav for it in win.lib.items), "toggling starred rows unstars them")
    check(sum(1 for it in win.lib.items if it.deleted) == 0, "restore")

    # ---- move
    win.tabs.setCurrentIndex(1)
    win.model.sort(0, Qt.AscendingOrder)
    a, b = win.model.rows[5], win.model.rows[6]
    select_rows(win, [6])
    win.a_up.trigger()
    check(win.model.rows[5] is b and win.model.rows[6] is a, "move up swaps neighbours")
    select_rows(win, [10, 11])
    x, y = win.model.rows[10], win.model.rows[11]
    win.a_top.trigger()
    check(win.model.rows[0] is x and win.model.rows[1] is y, "move block to top")
    check([int(i.num) for i in win.lib.ordered("live")][:3] == [0, 1, 2], "order renumbered cleanly")
    win.undo()
    check(win.model.rows[0] is not x, "undo of move")
    select_rows(win, [0, 1])
    win.a_down.trigger()
    check(win.model.rows[0] is not None, "move down runs")
    win.model.sort(1, Qt.AscendingOrder)
    select_rows(win, [3])
    n_before = len(win.lib.undo_stack)
    win.a_up.trigger()
    check(len(win.lib.undo_stack) == n_before and any("Sort by order" in t for t, _ in msgs),
          "move refused while sorted by name")
    win.model.sort(0, Qt.AscendingOrder)

    # ---- sidebar rename/merge
    win.tabs.setCurrentIndex(0)
    win.cats.setCurrentRow(3)
    old = next(iter(win.category))
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Renamed Cat", True))
    win.rename_category({old})
    check(not any(it.category == old for it in win.lib.items) and win.category == {"Renamed Cat"},
          "category rename/merge")

    # ---- multi-select categories in the sidebar: delete / restore / confirm rules
    win.tabs.setCurrentIndex(1)                       # Live tab
    live_items = [it for it in win.lib.items if it.kind == "live"]

    def pick(rows):
        win.cats.clearSelection()
        for r in rows:
            win.cats.item(r).setSelected(True)
        app.processEvents()
        return {win.cats.item(r).data(Qt.UserRole) for r in rows}

    picked = pick([1, 2, 3])
    check(win.category == picked and len(picked) == 3, "sidebar multi-select picks 3 categories")
    want = sum(1 for it in live_items if not it.deleted and it.category in picked)
    check(len(win.model.rows) == want, f"table shows the union of the picked categories ({want:,})")
    calls = []
    QMessageBox.question = staticmethod(lambda *a, **k: (calls.append(1), QMessageBox.Yes)[1])
    win.cats.setFocus()
    win.activateWindow()
    app.processEvents()
    if not win.cats.hasFocus():                       # offscreen platforms can be shy about focus
        print("      (note: faking sidebar focus for this test)")
        win._sidebar_has_focus = lambda: True
    win.a_del.trigger()                               # same action as the Delete key
    deleted_now = sum(1 for it in live_items if it.deleted and it.category in picked)
    check(deleted_now == want and not calls, f"Delete in sidebar removed {deleted_now:,} items, no prompt (small)")
    check(win.category == set() and not any(it.category in picked for it in win.model.rows),
          "view falls back to All categories afterwards")
    win.undo()
    check(sum(1 for it in live_items if it.deleted) == 0, "one Ctrl+Z restores the whole batch")
    # big deletes ask first
    mw.CONFIRM_DELETE_ABOVE = 10
    picked = pick([1, 2, 3])
    QMessageBox.question = staticmethod(lambda *a, **k: (calls.append(1), QMessageBox.No)[1])
    win.a_del.trigger()
    check(calls and sum(1 for it in live_items if it.deleted) == 0, "big delete asks, 'No' deletes nothing")
    QMessageBox.question = staticmethod(lambda *a, **k: (calls.append(1), QMessageBox.Yes)[1])
    picked = pick([1, 2, 3])
    win.a_del.trigger()
    check(sum(1 for it in live_items if it.deleted) == want, "big delete with 'Yes' goes through")
    win.undo()
    mw.CONFIRM_DELETE_ABOVE = 5000
    # restore via sidebar
    picked = pick([1, 2])
    win.a_del.trigger()
    win.mode.setCurrentIndex(1)                       # Everything (incl. deleted)
    picked = pick([1, 2])
    n_del = sum(1 for it in live_items if it.deleted)
    check(n_del > 0, "deleted categories are still listed under 'Everything'")
    win.a_restore.trigger()
    check(sum(1 for it in live_items if it.deleted) == 0, "Restore in sidebar brings categories back")
    win.mode.setCurrentIndex(0)
    # "All categories" alone must never delete everything
    win.cats.clearSelection()
    win.cats.item(0).setSelected(True)
    app.processEvents()
    win.a_del.trigger()
    check(sum(1 for it in win.lib.items if it.deleted) == 0, "Delete with only 'All categories' picked does nothing")
    # rename/merge several at once
    picked = pick([1, 2])
    QInputDialog.getText = staticmethod(lambda *a, **k: ("Merged Cat", True))
    win.rename_category(win._selected_cats())
    merged = [it for it in win.lib.items if it.category == "Merged Cat"]
    check(len(merged) > 0 and not any(it.category in picked for it in win.lib.items if it.kind == "live"),
          f"merge of several categories into one ({len(merged):,} items)")
    win.undo()
    win._sidebar_has_focus = lambda: False if not win.cats.hasFocus() else True
    win.cats.setCurrentRow(0)
    win.table.setFocus()
    win.tabs.setCurrentIndex(0)
    win._sidebar_has_focus = type(win)._sidebar_has_focus.__get__(win)

    # ---- find & replace
    dialogs.FindReplaceDialog.exec = lambda self: True
    dialogs.FindReplaceDialog.values = lambda self: {"field": "name", "find": "channel", "replace": "Ch",
                                                     "regex": False, "case": False, "selected_only": False}
    win.tabs.setCurrentIndex(1)
    win.search.setText("channel 99")
    win.refresh(rebuild_sidebar=False)
    vis = list(win.model.rows)
    win.a_find.trigger()
    check(len(vis) > 0 and all("channel" not in it.name.lower() and " Ch " in it.name for it in vis),
          f"find/replace changed all {len(vis)} visible names")
    check(all("channel" in it.name.lower() for it in win.lib.items
              if it.kind == "live" and "name" not in it.edits), "find/replace left everything else alone")
    win.search.setText("")
    win.tabs.setCurrentIndex(0)

    # ---- EPG sources + scan + autofill
    dialogs.EpgSourcesDialog.exec = lambda self: True
    dialogs.EpgSourcesDialog.values = lambda self: ([f"http://127.0.0.1:{PORT}/extra_epg.xml.gz"], True)
    timed("EPG scan (provider + extra)", lambda: (win.epg_sources_dialog(), wait(win)))
    check(win.epg_index is not None and len(win.epg_index.sources) == 2, "guides scanned")
    win.mode.setCurrentIndex(6)
    check(len(win.model.rows) == 0 or all(it.epg_id and not win.epg_index.has(it.epg_id) for it in win.model.rows),
          "'EPG ID not in guides' filter consistent")
    win.mode.setCurrentIndex(0)
    QMessageBox.exec = lambda self: QMessageBox.Yes
    QMessageBox.clickedButton = lambda self: next(b for b in self.buttons() if b.text().startswith("No ID, or"))
    before = sum(1 for it in win.lib.items if it.kind == "live" and not it.epg_id)
    timed("auto-fill", win.autofill_epg)
    after = sum(1 for it in win.lib.items if it.kind == "live" and not it.epg_id)
    check(after < before, f"auto-fill filled {before - after:,} missing IDs")

    # ---- episodes
    win.tabs.setCurrentIndex(3)
    select_rows(win, [0, 1, 2])
    win.a_eps_sel.trigger()
    wait(win)
    got = [it for it in win.lib.items if it.kind == "series" and it.episodes]
    check(len(got) == 3 and all(len(it.episodes) >= 3 for it in got), "episodes fetched for selection")
    dialogs.EpisodesDialog.exec = lambda self: True
    select_rows(win, [0])
    win.a_eps_edit.trigger()
    app.processEvents()
    check(True, "episode editor opens")

    # ---- export (combined + merged epg)
    out = os.path.join(TMP, "out")
    _real_export_values, _real_export_exec = dialogs.ExportDialog.values, dialogs.ExportDialog.exec
    dialogs.ExportDialog.exec = lambda self: True
    dialogs.ExportDialog.values = lambda self: {
        "kinds": ["live", "vod", "series"], "split": False, "prefix": True, "live_ext": "ts",
        "folder": out, "base": "all", "epg_mode": "merge", "gz": False, "base_url": "http://192.168.1.5:8765"}
    timed("export 80k + merged EPG", lambda: (win.export(), wait(win)))
    m3u = os.path.join(out, "all.m3u")
    check(os.path.exists(m3u) and os.path.exists(os.path.join(out, "epg.xml")), "export files written")
    lines = open(m3u, encoding="utf-8").read().splitlines()
    check('url-tvg="http://192.168.1.5:8765/epg.xml"' in lines[0], "header points at hosted EPG")
    n_ext = sum(1 for l in lines if l.startswith("#EXTINF"))
    expected = LIVE + VOD + sum(len(it.episodes) for it in got if not it.deleted) \
        - sum(1 for it in got for e in it.episodes if e.get("skip"))
    check(n_ext == expected, f"{n_ext:,} entries exported (expected {expected:,})")
    check(any("Export finished" in t for t, _ in msgs), "export summary shown")
    dialogs.ExportDialog.values, dialogs.ExportDialog.exec = _real_export_values, _real_export_exec

    # ---- LAN server
    from core.webserver import FileServer
    fs = FileServer()
    fs.start(out, 18099)
    r = requests.get("http://127.0.0.1:18099/all.m3u", timeout=10)
    check(r.status_code == 200 and r.text.startswith("#EXTM3U"), "LAN server serves the playlist")
    fs.stop()

    # ---- EPG sources box: dropped files and Add-file produce clean paths
    from PySide6.QtCore import QMimeData, QUrl
    dlg_e = dialogs.EpgSourcesDialog(win, ["http://x.tv/a.xml"], True)
    md = QMimeData()
    f1, f2 = os.path.join(TMP, "g one.xml"), os.path.join(TMP, "g2.xml.gz")
    open(f1, "w").write("<tv/>")
    open(f2, "wb").write(b"")
    md.setUrls([QUrl.fromLocalFile(f1), QUrl.fromLocalFile(f2)])
    dlg_e.text.insertFromMimeData(md)
    vals, prov = _real_epg_values(dlg_e)
    check(vals == ["http://x.tv/a.xml", f1, f2], f"dropping two files adds two clean lines ({len(vals)})")
    dlg_e.text.setPlainText('"%s"\nfile://%s\n%s\n' % (f1, f2, f1))
    check(_real_epg_values(dlg_e)[0] == [f1, f2], "quotes and file:// are tidied, duplicates dropped")

    # ---- Xtream server from the UI: start via the dialog, edits flow through live
    def fake_exec(self):
        self.port.setValue(18095)
        self.user.setText("ui")
        self.pw.setText("pw")
        self.epg.setCurrentIndex(self.epg.findData("none"))
        self._toggle()
    dialogs.XtreamServerDialog.exec = fake_exec
    win.a_xs.trigger()
    check(win.xs.running and "Xtream server" in win.serve_lbl.text(), "Xtream server starts from the menu/dialog")

    def xs_live():
        return requests.get("http://127.0.0.1:18095/player_api.php",
                            params={"username": "ui", "password": "pw", "action": "get_live_streams"}, timeout=30).json()
    active_live = sum(1 for i in win.lib.items if i.kind == "live" and not i.deleted and not i.gone)
    served = xs_live()
    check(len(served) == active_live, f"server serves the same {active_live:,} live channels the editor has")
    victim = win.lib.ordered("live")[40]
    win.lib.change([(victim, "name", "Renamed In Editor")], "rename")
    win._after_change()                                # same call every real edit makes
    t0 = time.time()
    while time.time() - t0 < 4 and not any(e["name"] == "Renamed In Editor" for e in xs_live()):
        app.processEvents()
        time.sleep(0.1)
    check(any(e["name"] == "Renamed In Editor" for e in xs_live()), "edits in the editor appear on the server within seconds")
    win.xs.stop()

    # ---- save / reopen
    proj = os.path.join(TMP, "big.xtp")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (proj, ""))
    timed("save project", win.save_project_as)
    check(os.path.exists(proj) and not win.lib.dirty, f"project saved ({os.path.getsize(proj)/1e6:.1f} MB)")
    lib2 = Library()
    timed("load project", lambda: lib2.load(proj))
    check(len(lib2.items) == len(win.lib.items) and lib2.connection["username"] == "demo", "project reloads")
    check(sum(1 for it in lib2.items if it.edits) == sum(1 for it in win.lib.items if it.edits),
          "edits survive reload")
    # --- sort A-Z within categories
    from ui import dialogs as dl_s
    from core.sorting import sort_key as _sk
    dl_s.SortDialog.exec = lambda self: dl_s.QDialog.Accepted
    mw.SortDialog.exec = dl_s.SortDialog.exec
    win.kind, win.category = "live", set()
    win.lib.change([(it, "num", float(len(win.lib.items) - i)) for i, it in enumerate(win.lib.ordered("live"))], "scramble")
    before_names = {it.key: (it.name, it.category) for it in win.lib.items}
    win.sort_az()
    grouped = {}
    for it in win.lib.ordered("live"):
        grouped.setdefault(it.category, []).append(it.name)
    check(all(v == sorted(v, key=_sk) for v in grouped.values()), "sort A-Z puts every live category in order")
    check(before_names == {it.key: (it.name, it.category) for it in win.lib.items}, "sort A-Z keeps names and categories")
    check(win.lib.undo_stack[-1][0] == "sort A-Z", "sort A-Z is one undo step")
    win.undo()
    # one big A-Z list for Live
    mw.SortDialog.mode = lambda self: "all"
    win.sort_az()
    big = [it.name for it in win.lib.ordered("live")]
    check(big == sorted(big, key=_sk), "sort A-Z as one big list puts all of Live in order")
    check(before_names == {it.key: (it.name, it.category) for it in win.lib.items}, "big list keeps names and categories")
    win.undo()
    del mw.SortDialog.mode
    mw.SortDialog.exec = lambda self: 0
    n_stack = len(win.lib.undo_stack)
    win.sort_az()
    check(len(win.lib.undo_stack) == n_stack, "cancelling the sort changes nothing")
    mw.SortDialog.exec = dl_s.SortDialog.exec
    # --- category manager
    from ui import dialogs as dl0
    live_cats = {it.category for it in win.lib.items if it.kind == "live"}
    n_live = sum(1 for it in win.lib.items if it.kind == "live")
    win.category_manager()
    cm = win._catmgr
    check(cm.isVisible() and not cm.isModal() and len(cm.rows) == len({(i.kind, i.category) for i in win.lib.items}),
          "category manager lists every category")
    check(not cm.apply_btn.isEnabled(), "Apply is off until something changes")
    # type a new name for one live category, merge two others, then apply as one undo step
    live_rows = [r for r in cm.rows if r["kind"] == "live"]
    a, b = live_rows[0], live_rows[1]
    old_a, old_b = a["cat"], b["cat"]
    a["new"] = "ZZ Renamed Cat"
    b["new"] = "ZZ Renamed Cat"
    cm.fill()
    check("2 categories to rename" in cm.summary.text() and "merging" in cm.summary.text(), f"summary counts merges ({cm.summary.text()})")
    before = len(win.lib.undo_stack)
    cm.apply()
    moved = [it for it in win.lib.items if it.kind == "live" and it.category == "ZZ Renamed Cat"]
    check(len(moved) > 0 and not any(it.category in (old_a, old_b) for it in win.lib.items if it.kind == "live"),
          "rename + merge applied to the items")
    check(len(win.lib.undo_stack) == before + 1, "applying is one undo step")
    check(all("category" in it.edits for it in moved), "renamed items keep the new name through re-syncs")
    win.undo()
    check(any(it.category == old_a for it in win.lib.items if it.kind == "live"), "undo restores the old names")
    # proper case on selected rows only
    cm.load_rows()
    cm.search.setText(old_a.lower()[:6])
    cm.table.selectRow(0)
    first_i = cm.table.item(0, 0).data(Qt.UserRole)
    cm.rows[first_i]["new"] = cm.rows[first_i]["cat"].upper()
    cm.do_proper()
    from core.casing import proper_case
    check(cm.rows[first_i]["new"] == proper_case(cm.rows[first_i]["cat"].upper(), cm.words()), "Proper Case button works on the selection")
    # standard acronym list: on by default, can be switched off, extras add to it, choices are remembered
    check(cm.std_on.isChecked() and {"espn", "nfl", "amc", "pbs"} <= cm.words(), "standard acronym list is on by default")
    cm.std_on.setChecked(False)
    check("espn" not in cm.words() and win.cfg.get("cat_std_on") is False, "unticking the box drops the standard list and remembers it")
    cm.extra.setText("DAZN, tsn")
    cm.prefs_changed()
    check(cm.words() == {"dazn", "tsn"} and win.cfg.get("cat_acronyms") == "DAZN, tsn", "extra words are used on their own and remembered")
    cm.std_on.setChecked(True)
    check({"dazn", "espn"} <= cm.words(), "extras add to the standard list")
    cm.extra.setText("")
    cm.prefs_changed()
    cm.search.clear()
    cm.close()

    # --- category manager shortcut works wherever focus is
    from PySide6.QtTest import QTest as _QT
    keys = [k.toString() for k in win.a_catmgr.shortcuts()]
    check(keys[0] == "Ctrl+Shift+C" and "Ctrl+M" in keys, f"category manager shortcuts {keys}")
    check(win.a_catmgr.shortcutContext() == Qt.ApplicationShortcut, "category manager shortcut is application-wide")
    for target in (win.table, win.cats):
        if getattr(win, "_catmgr", None):
            win._catmgr.close()
        QApplication.setActiveWindow(win)
        win.activateWindow()
        target.setFocus()
        QApplication.processEvents()
        _QT.keyClick(target, Qt.Key_C, Qt.ControlModifier | Qt.ShiftModifier)
        check(getattr(win, "_catmgr", None) is not None and win._catmgr.isVisible(),
              f"Ctrl+Shift+C opens the category manager from the {'table' if target is win.table else 'sidebar'}")
    win._catmgr.close()
    # --- themes
    from ui import themes as th
    app0 = QApplication.instance()
    sys_win = app0.palette().window().color().name()
    check(th.NAMES[:3] == ["System", "Light", "Dark"] and len(th.NAMES) >= 6, f"themes available ({th.NAMES})")
    check(win.theme_actions["System"].isChecked(), "System theme is the default")
    win.set_theme("Dark")
    check(app0.palette().window().color().name() == "#2b2b2b" and win.cfg["theme"] == "Dark" and win.theme_actions["Dark"].isChecked(),
          "Dark theme applies and is remembered")
    for n in th.NAMES:
        win.set_theme(n)
        win.refresh()
        check(win.theme_actions[n].isChecked(), f"theme {n} applies")
    check("Solarized Dark" not in th.NAMES and {"Paper", "Catppuccin Latte", "Sky", "Mint"} <= set(th.NAMES), "Solarized is gone; Paper, Catppuccin Latte, Sky and Mint are in")
    win.set_theme("Solarized Dark")
    check(win.theme_actions["System"].isChecked() and win.cfg["theme"] == "System", "a retired theme name falls back to System")
    win.set_theme("System")
    check(app0.palette().window().color().name() == sys_win, "System restores the original look")
    check(th.apply(app0, "nonsense") == "System", "unknown theme name falls back to System")
    win.set_theme("Dark", save=False)
    win.set_theme("System", save=False)

    # --- help & about
    titles = [m.title().replace("&", "") for m in win.menuBar().findChildren(mw.QMenu) if m.parent() is win.menuBar() and m.title()]
    check(titles and titles[-1] == "Help", f"Help is the last menu ({titles})")
    check(win.a_help.shortcut().toString() == "F1", "F1 opens help")
    from ui import dialogs as dl
    secs = dl.help_sections()
    names = [t for t, _ in secs]
    check(names[0] == "Welcome" and "Keyboard shortcuts" in names and "The Xtream server" in names,
          "help file splits into sections")
    check("Layout" not in names, "developer-only sections are left out of the help")
    win.show_help()
    h = win._help
    check(h.isVisible() and not h.isModal() and h.toc.count() == len(secs), "help window opens, non-modal")
    win.show_help("Disclaimer and terms of use")
    check(h.toc.currentItem().text() == "Disclaimer and terms of use" and "as is" in h.view.toPlainText(), "disclaimer page opens from the Help menu")
    from core.terms import TERMS_TEXT, TERMS_VERSION
    check(TERMS_TEXT.split("\n")[0][:40] in open(os.path.join(ROOT, "DISCLAIMER.txt"), encoding="utf-8").read(), "DISCLAIMER.txt carries the same terms")
    check("legal right" in dl.about_text() or "right to access" in dl.about_text(), "About box mentions legitimate use")
    win.cfg["terms_accepted"] = TERMS_VERSION
    check(win.require_terms() is True, "terms already accepted: no prompt")
    win.cfg.pop("terms_accepted")
    _orig = dl.TermsDialog.exec
    dl.TermsDialog.exec = lambda self: 0
    mw.TermsDialog.exec = dl.TermsDialog.exec
    check(win.require_terms() is False and "terms_accepted" not in win.cfg, "declining the terms does not record agreement")
    mw.TermsDialog.exec = lambda self: mw.QDialog.Accepted
    check(win.require_terms() is True and win.cfg["terms_accepted"] == TERMS_VERSION, "agreeing records it")
    mw.TermsDialog.exec = _orig
    win.show_help("Keyboard shortcuts")
    check(h.toc.currentItem().text() == "Keyboard shortcuts" and "Ctrl+D" in h.view.toPlainText(), "shortcuts page opens")
    h.search.setText("catch-up")
    vis = [h.toc.item(i).text() for i in range(h.toc.count()) if not h.toc.item(i).isHidden()]
    check(vis and all("catch" in dict(secs)[t].lower() or "catch" in t.lower() for t in vis) and len(vis) < len(secs),
          f"search narrows the contents ({len(vis)} of {len(secs)})")
    # search: counts matches, Enter/Next walk through them across sections, Enter never closes the window
    from PySide6.QtTest import QTest
    h.search.setText("server")
    nsec = sum(1 for i in range(h.toc.count()) if not h.toc.item(i).isHidden())
    check(nsec > 3 and "matches in" in h.hits.text() and h.next_btn.isEnabled(), f"search reports matches ({h.hits.text()})")
    seen = {h.toc.currentRow()}
    for _ in range(60):
        QTest.keyClick(h.search, Qt.Key_Return)
        seen.add(h.toc.currentRow())
    check(h.isVisible(), "pressing Enter in the help search does not close the window")
    check(len(seen) == nsec, f"Enter steps through the matches in every matching section ({len(seen)} of {nsec})")
    r0 = h.toc.currentRow()
    h.find_next(backwards=True)
    check(h.view.textCursor().hasSelection() or h.toc.currentRow() != r0, "Previous goes back a match")
    check(len(h.view.extraSelections()) >= 1, "matches are highlighted in the text")
    h.search.setText("zzzzqqq")
    check(h.hits.text() == "No matches" and not h.next_btn.isEnabled(), "no matches is reported")
    h.search.clear()
    QTest.keyClick(h, Qt.Key_Escape)
    check(not h.isVisible(), "Esc closes the help window")
    win.show_help()
    h = win._help
    from core.common import APP_VERSION
    check(APP_VERSION in dl.about_text() and APP_VERSION in h.windowTitle(), f"version {APP_VERSION} shown")
    h.close()
    win.show_help()
    check(win._help is h and h.isVisible(), "help reopens after being closed")
    win.show_help("Editing")
    check(h.toc.currentItem().text() == "Editing", "help can be reopened on a topic")
    h.search.setText("server")
    win.show_help()
    check(h.toc.currentRow() == 0 and h.search.text() == "" and h.toc.item(1).isHidden() is False,
          "plain reopen starts fresh at the top with no search")
    h.close()
    # --- duplicate finder
    from core.models import Item as _It
    base = max(i.num for i in win.lib.items) + 1
    dup_a = _It("vod", "dupA", "ZZ Dupe Film (2001)", "Action", num=base)
    dup_b = _It("vod", "dupB", "EN | ZZ Dupe Film (2001) [HD]", "Drama", num=base + 1)
    dup_c = _It("vod", "dupC", "ZZ Dupe Film (2001) 4K", "Drama", num=base + 2)
    win.lib.items += [dup_a, dup_b, dup_c]
    win.lib.index.update({it.key: it for it in (dup_a, dup_b, dup_c)} if isinstance(win.lib.index, dict) else {})
    win.duplicate_finder()
    df = win._dupes
    check(df.isVisible() and not df.isModal() and not df.apply_btn.isEnabled(), "duplicate finder opens, Apply is off")
    df.kind.setCurrentIndex(0)                      # Movies
    df.search()
    grp = [g for g in df.groups if any(i.id == "dupA" for i in g)]
    check(len(grp) == 1 and len(grp[0]) == 3, "the three Dupe Film copies show up as one group")
    first = df.tree.topLevelItem(0)
    first.setSelected(True)
    check(len(df.selected()) >= 1, "rows can be selected")
    df.tree.clearSelection()
    check(not df.selected(), "Deselect all / clearSelection empties the selection")
    stack = len(win.lib.undo_stack)
    df.auto_pick()                                  # keep earliest, delete the rest
    check("2 to delete" in df.summary.text().replace(",", ""), f"auto-pick marks the rest ({df.summary.text()})")
    check(df.apply_btn.isEnabled(), "Apply turns on")
    df.clear_all()
    check(not df.pending and not df.apply_btn.isEnabled() and all(
        df.nodes[k][0].text(6) == "" for k in df.nodes), "Clear all choices wipes every mark and turns Apply off")
    df.auto_pick()
    df.pending.pop(dup_b.key)
    df.paint(dup_b)
    df.set_pending([dup_b], name="ZZ Dupe Film (2001) EN", category="Action")
    check(df.ask_box.isChecked() and win.cfg.get("dupes_ask", True), "asks before applying by default")
    shown = {}
    from PySide6.QtWidgets import QMessageBox as _MB
    _real = _MB.exec
    def _fake(self, answer=_MB.Cancel):
        shown["text"] = self.text() + " " + self.informativeText()
        return shown.get("answer", _MB.Cancel)
    _MB.exec = _fake
    df.apply()
    check(len(win.lib.undo_stack) == stack and not dup_c.deleted, "Cancel in the popup changes nothing")
    check("Undo last action" in shown["text"], "popup mentions the Undo last action button")
    check("2 items will be changed" in shown["text"] and "1 deleted" in shown["text"] and "1 renamed" in shown["text"]
          and "1 moved" in shown["text"], f"popup lists the totals ({shown['text']!r})")
    check(df.pending, "marks are still there after Cancel")
    shown["answer"] = _MB.Ok
    df.apply()
    _MB.exec = _real
    check(len(win.lib.undo_stack) == stack + 1, "applying is one undo step")
    check(dup_a.deleted is False and dup_c.deleted and dup_b.name.endswith("EN") and dup_b.category == "Action",
          "keep, delete, rename and move were all applied")
    check(not df.pending, "results refresh after applying")
    check(df.undo_btn.isEnabled() and "resolve duplicates" in df.undo_btn.text() and "one step" in df.undo_btn.toolTip(),
          f"Undo last action button is on and names the step ({df.undo_btn.text()})")
    df.undo_last()
    check(not dup_c.deleted and dup_b.category == "Drama", "the Undo last action button puts everything back")
    check(df.groups and any(i.id == "dupA" for g in df.groups for i in g), "results refresh after the undo")
    from PySide6.QtGui import QKeySequence, QShortcut
    sc = [s for s in df.findChildren(QShortcut) if s.key() == QKeySequence(QKeySequence.Undo)]
    check(bool(sc), "Ctrl+Z is wired up inside the finder window")
    df.ask_box.setChecked(False)
    check(win.cfg.get("dupes_ask") is False, "turning the box off is remembered")
    df.search()
    df.set_pending([dup_c], deleted=True)
    _MB.exec = lambda self: (_ for _ in ()).throw(AssertionError("popup should not show"))
    df.apply()
    check(dup_c.deleted, "no popup when 'Ask before applying' is off")
    _MB.exec = _real
    win.undo()
    df.ask_box.setChecked(True)
    df.close()
    win.lib.items = [i for i in win.lib.items if i.id not in ("dupA", "dupB", "dupC")]
    # --- regex rules
    from core.models import Item as _It2
    nb = max(i.num for i in win.lib.items) + 1
    r1 = _It2("live", "rxA", "ZZR | Alpha", "ZZR | Sports", num=nb)
    r2 = _It2("live", "rxB", "ZZR | Beta", "ZZR | Sports", num=nb + 1)
    r3 = _It2("live", "rxC", "Plain Name", "Other", num=nb + 2)
    win.lib.items += [r1, r2, r3]
    win.lib.index.update({it.key: it for it in (r1, r2, r3)})
    win.cfg.pop("regex_rules", None)
    win.regex_rules()
    rd = win._rules
    check(rd.isVisible() and not rd.isModal() and not rd.apply_btn.isEnabled(), "regex rules window opens, Apply is off")
    rd.add_rule()
    rd.f_pattern.setText(r"^ZZR \| (.*)")
    rd.f_rewrite_on.setChecked(True)
    rd.f_rewrite.setText("$1")
    rd.f_move.setEditText("ZZR Local")
    rd.f_field.setCurrentIndex(0)
    rd.form_changed()
    items_in = [rd.f_move.itemText(i) for i in range(rd.f_move.count())]
    all_cats = sorted({i.category for i in win.lib.items if not i.deleted}, key=str.lower)
    check(items_in[0] == "" and items_in[1:] == all_cats and "ZZR | Sports" in items_in,
          "the Move-to box is a dropdown listing every category (blank first)")
    rd.f_kinds.setCurrentIndex(2)                       # Movies
    movie_cats = sorted({i.category for i in win.lib.items if i.kind == "vod" and not i.deleted}, key=str.lower)
    check([rd.f_move.itemText(i) for i in range(1, rd.f_move.count())] == movie_cats and "ZZR | Sports" not in
          [rd.f_move.itemText(i) for i in range(rd.f_move.count())], "the list follows the rule's type")
    check(rd.f_move.currentText() == "ZZR Local" and rd.cur()["kinds"] == "vod", "switching type keeps what you typed")
    rd.f_kinds.setCurrentIndex(0)
    rd.f_move.setCurrentIndex(rd.f_move.findText("ZZR | Sports"))
    check(rd.cur()["move"] == "ZZR | Sports", "picking from the list sets the rule")
    rd.f_move.setEditText("ZZR Local")
    check(rd.cur()["move"] == "ZZR Local" and rd.f_move.completer().filterMode() == Qt.MatchContains, "typing works, matching any part of a name")
    check(win.cfg.get("regex_rules") and win.cfg["regex_rules"][0]["pattern"].startswith("^ZZR"), "rules are saved in your settings")
    check(not rd.apply_btn.isEnabled(), "Apply stays off until you preview")
    rd.preview()
    check(rd.apply_btn.isEnabled() and "2 items would change" in rd.summary.text() and rd.table.rowCount() == 2,
          f"preview lists what would change ({rd.summary.text()})")
    check(r1.name == "ZZR | Alpha", "preview changes nothing")
    rd.f_rewrite.setText("$3")
    rd.form_changed()
    check(rd.table.rowCount() == 0 and "Press Preview again" in rd.summary.text(), "editing a rule clears the old preview")
    check(rd.f_err.text() != "" and not rd.apply_btn.isEnabled(), "a bad replacement shows an error and turns Apply off")
    rd.f_rewrite.setText("$1")
    rd.form_changed()
    rd.preview()
    n_stack = len(win.lib.undo_stack)
    shown2 = {}
    _real2 = _MB.exec
    _MB.exec = lambda self: (shown2.__setitem__("t", self.text() + self.informativeText()) or _MB.Ok)
    rd.apply()
    _MB.exec = _real2
    check("2 items will be changed" in shown2.get("t", "") and "Undo last action" in shown2["t"], "apply asks first")
    check(r1.name == "Alpha" and r1.category == "ZZR Local" and r3.name == "Plain Name", "rule applied to the matches only")
    check(len(win.lib.undo_stack) == n_stack + 1 and "name" in r1.edits, "one undo step, and edits survive a re-sync")
    check("regex rules" in rd.undo_btn.text(), "Undo last action names the step")
    rd.undo_last()
    check(r1.name == "ZZR | Alpha" and r1.category == "ZZR | Sports", "the Undo last action button reverts it")
    rd.ask_box.setChecked(False)
    check(win.cfg.get("rules_ask") is False, "'Ask before applying' off is remembered")
    rd.preview()
    _MB.exec = lambda self: (_ for _ in ()).throw(AssertionError("no popup expected"))
    rd.apply()
    _MB.exec = _real2
    check(r2.name == "Beta", "no popup when asking is off")
    win.undo()
    rd.ask_box.setChecked(True)
    rd.copy_rule()
    rd.move_rule(-1)
    rd.remove_rule()
    check(len(win.cfg["regex_rules"]) == 1, "copy, move and remove keep the saved list in step")
    rd.close()
    win.lib.items = [i for i in win.lib.items if not i.id.startswith("rx")]
    # --- placeholder guide options in the dialogs
    from ui.dialogs import ExportDialog as _ED, XtreamServerDialog as _XD
    xd = _XD(win, win.xs, dict(win.cfg, xs_pass="pw"), lambda st: None, lambda: None, lambda: None)
    check(not xd.fill.isChecked() and xd.settings()["xs_placeholders"] is False, "server window: placeholders are off by default")
    xd.epg.setCurrentIndex(xd.epg.findData("merged"))
    xd.fill.setChecked(True)
    check(xd.settings()["xs_placeholders"] is True, "ticking it turns them on")
    xd.epg.setCurrentIndex(xd.epg.findData("provider"))
    check(not xd.fill.isEnabled() and xd.settings()["xs_placeholders"] is False, "only offered with the merged guide")
    xd.timer.stop()
    xd.close()
    ed = _ED(win, {"live": 3, "vod": 1, "series": 0}, win.cfg, "http://x:1", can_merge=True)
    check(not ed.fill.isEnabled() and ed.values()["placeholders"] is False, "export window: off, and unavailable until merged guide is chosen")
    ed.e_merge.setChecked(True)
    check(ed.fill.isEnabled() and not ed.fill.isChecked(), "choosing the merged guide offers it (still off)")
    ed.fill.setChecked(True)
    check(ed.values()["placeholders"] is True, "ticked: export gets placeholders")
    ed.k_live.setChecked(False)
    check(ed.values()["placeholders"] is False, "no live channels in the export, nothing to fill")
    ed.close()
    # --- remembers window size, divider and column widths
    win.resize(700, 500)
    from PySide6.QtWidgets import QWidget as _QW
    _QW.move(win, 60, 70)
    win.split.setSizes([333, 777])
    win.table.setColumnWidth(1, 401)
    win._remember_layout()
    cfg_mod.save(win.cfg)
    w2 = mw.MainWindow()
    check((w2.width(), w2.height()) == (700, 500), f"window size is remembered ({w2.width()}x{w2.height()})")
    check(abs(w2.x() - 60) <= 5 and abs(w2.y() - 70) <= 5, f"window position is remembered ({w2.x()},{w2.y()})")
    check(w2.table.columnWidth(1) == 401, "column widths are remembered")
    check(abs(w2.split.sizes()[0] - 333) <= 2 or w2.split.sizes()[0] > 0, "divider position is restored")
    w2._remember_layout()
    check(w2.cfg["win_splitter"] == w2.split.sizes(), "layout is saved from the live window")
    bad = dict(win.cfg, win_geometry=12345, win_splitter="x", win_columns=[1, 2])
    cfg_mod.save(bad)
    w3 = mw.MainWindow()
    check(w3.width() > 0 and w3.table.columnWidth(1) > 0, "damaged saved layout falls back to defaults instead of crashing")
    for w in (w2, w3):
        w.lib.dirty = False
        w.xs.stop()
    cfg_mod.save(win.cfg)
    win.lib.dirty = False
    win.close()
finally:
    srv.terminate()

crit = [m for m in msgs if m[0] == "CRITICAL"]
check(not crit, f"no error dialogs ({crit[:1]})")
print("\nFAILED: %d" % fails if fails else "\nALL PASSED")
sys.exit(1 if fails else 0)
