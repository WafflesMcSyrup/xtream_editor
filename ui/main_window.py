"""The main window: category sidebar, big editable table, and all the actions."""
from __future__ import annotations

import os
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from PySide6.QtCore import QByteArray, QItemSelectionModel, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QProgressDialog, QSplitter, QTabBar, QTableView,
                               QToolBar, QVBoxLayout, QHBoxLayout, QWidget, QAbstractItemView)

from core import epg, settings as cfg
from core.common import APP_NAME, APP_VERSION, Cancelled
from core import matcher, placeholder
from core.casing import DEFAULT_STANDARD
from core.exporter import export_list, export_playlists
from core.models import KIND_LABEL, KINDS, Library
from core.webserver import FileServer, lan_ip
from core.xtream_server import XtreamServer
from core.xtream import DEFAULT_UA, XtreamClient, fetch_all, fetch_episodes, xmltv_url
from .dialogs import (ConnectDialog, ImportFavoritesDialog, ListExportDialog, EpgSourcesDialog, EpisodesDialog, ExportDialog,
                      CategoryManagerDialog, DuplicateFinderDialog, FindReplaceDialog, HelpDialog, RegexRulesDialog, SortDialog, TermsDialog, ServeDialog, XtreamServerDialog, about_text)
from . import themes
from .table_model import COLS, ItemModel
from .workers import Task

CONFIRM_DELETE_ABOVE = 5000  # category deletes bigger than this ask first; smaller ones just happen (undo covers it)
EPISODE_WORKERS = 2         # parallel requests when pulling series episodes (be gentle with providers)
TAB_KINDS = [None, "live", "vod", "series"]
TAB_NAMES = ["All", "Live", "Movies", "Series"]
SHOW_MODES = [
    ("Active items", "active"),
    ("Everything (incl. deleted)", "all"),
    ("Deleted only", "deleted"),
    ("Edited by me", "edited"),
    ("\u2605 Favorites only", "fav"),
    ("Live: no EPG ID", "noepg"),
    ("Live: EPG ID not in my guides", "badepg"),
    ("No logo", "nologo"),
    ("New since last sync", "new"),
    ("Gone from server", "gone"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = cfg.load()
        self.lib = Library()
        self.epg_index = None
        self.server = FileServer()
        self.xs = XtreamServer()
        self._xs_timer = QTimer(self, singleShot=True, interval=1500)
        self._xs_timer.timeout.connect(lambda: self.xs.update(self.lib))
        self._task = None
        self.kind = None
        self.category = set()
        self.resize(1400, 860)

        self.model = ItemModel(self._on_cell_edit)
        self._side_timer = QTimer(self, singleShot=True, interval=250)
        self._side_timer.timeout.connect(self.refresh_sidebar)
        self._search_timer = QTimer(self, singleShot=True, interval=300)
        self._search_timer.timeout.connect(lambda: self.refresh(rebuild_sidebar=False))

        self._build_ui()
        self._build_actions()
        self._update_title()
        self._update_actions()
        self._restore_layout()
        QTimer.singleShot(200, self._load_last)

    # ---- remember window size, position, divider and column widths -------
    def _restore_layout(self):
        c = self.cfg
        try:
            geo = c.get("win_geometry")
            if geo:
                self.restoreGeometry(QByteArray.fromBase64(str(geo).encode("ascii")))
            sizes = c.get("win_splitter")
            if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(n, int) and n > 0 for n in sizes):
                self.split.setSizes(sizes)
            cols = c.get("win_columns")
            if isinstance(cols, list) and len(cols) == self.model.columnCount():
                for i, w in enumerate(cols):
                    if isinstance(w, int) and 20 <= w <= 4000:
                        self.table.setColumnWidth(i, w)
        except (TypeError, ValueError, UnicodeError):
            pass                                    # a damaged setting just means the default layout

    def _remember_layout(self):
        self.cfg["win_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.cfg["win_splitter"] = [int(n) for n in self.split.sizes()]
        self.cfg["win_columns"] = [int(self.table.columnWidth(i)) for i in range(self.model.columnCount())]

    # ====================================================================
    # UI construction
    # ====================================================================
    def _build_ui(self):
        self.split = split = QSplitter(Qt.Horizontal)
        self.setCentralWidget(split)

        self.cats = QListWidget()
        self.cats.setMinimumWidth(230)
        self.cats.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.cats.itemSelectionChanged.connect(self._cats_selection_changed)
        self.cats.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cats.customContextMenuRequested.connect(self._cats_menu)
        split.addWidget(self.cats)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabBar()
        for n in TAB_NAMES:
            self.tabs.addTab(n)
        self.tabs.currentChanged.connect(self._tab_changed)
        rl.addWidget(self.tabs)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name / category / EPG ID (several words = all must match)...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        self.mode = QComboBox()
        for label, key in SHOW_MODES:
            self.mode.addItem(label, key)
        self.mode.currentIndexChanged.connect(lambda _: self.refresh())
        row.addWidget(self.search, 1)
        row.addWidget(QLabel("Show:"))
        row.addWidget(self.mode)
        rl.addLayout(row)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.verticalHeader().setSectionResizeMode(self.table.verticalHeader().ResizeMode.Fixed)
        hh = self.table.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setSortIndicatorShown(True)
        for i, w in enumerate([55, 330, 190, 170, 220, 60, 120]):
            self.table.setColumnWidth(i, w)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_status())
        rl.addWidget(self.table, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 1140])

        self.status_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.status_lbl)
        self.serve_lbl = QLabel()
        self.statusBar().addPermanentWidget(self.serve_lbl)

    def _act(self, text, slot, shortcut=None, tip=None):
        a = QAction(text, self)
        a.triggered.connect(lambda *_: slot())
        if shortcut:
            a.setShortcut(shortcut)
        if tip:
            a.setStatusTip(tip)
        return a

    def _build_actions(self):
        A = self._act
        self.a_connect = A("Connect / fetch from server...", self.connect_and_fetch, "Ctrl+K",
                           "Log in and pull every channel, movie and series. Re-running keeps your edits.")
        self.a_new = A("New project", self.new_project)
        self.a_open = A("Open project...", self.open_project, QKeySequence.Open)
        self.a_save = A("Save project", self.save_project, QKeySequence.Save)
        self.a_saveas = A("Save project as...", self.save_project_as, "Ctrl+Shift+S")
        self.a_export = A("Export playlist...", self.export, "Ctrl+E")
        self.a_list = A("Export list to CSV / TXT...", self.export_list_file, None,
                        "Save a simple list of names and categories (everything, or just the categories you pick).")
        self.a_xs = A("Xtream server for IPTV apps...", self.xtream_server, "Ctrl+Shift+X",
                      "Let IPTV apps log into this PC like an Xtream provider and get your edited list.")
        self.a_serve = A("Serve files on home network...", self.serve)
        self.a_quit = A("Quit", self.close, "Ctrl+Q")

        self.a_undo = A("Undo", self.undo, QKeySequence.Undo)
        self.a_redo = A("Redo", self.redo, "Ctrl+Y")
        self.a_cat = A("Set category...", lambda: self.set_field("category"))
        self.a_epgid = A("Set EPG ID...", lambda: self.set_field("epg_id"))
        self.a_logo = A("Set logo URL...", lambda: self.set_field("logo"))
        self.a_find = A("Find && replace...", self.find_replace, "Ctrl+H")
        self.a_del = A("Delete selected", self.delete_selected, QKeySequence.Delete)
        self.a_restore = A("Restore selected", self.restore_selected)
        self.a_fav = A("Toggle \u2605 favorite", self.toggle_favorite, "Ctrl+D",
                       "Star or unstar the selected rows. Starred items also appear under \"\u2605 Favorites\" in your apps.")
        self.a_seen = A("Mark all new items as seen", self.mark_seen, None,
                        "Clears the \"new since last sync\" markers once you've looked them over.")
        self.a_impfav = A("Import list for Favorites...", self.import_favorites, "Ctrl+Shift+D",
                          "Load a text file of names (one per line), find the best matches in your list, and star the ones you tick.")
        self.a_top = A("Move to top", lambda: self.move("top"))
        self.a_up = A("Move up", lambda: self.move("up"), "Alt+Up")
        self.a_down = A("Move down", lambda: self.move("down"), "Alt+Down")
        self.a_bottom = A("Move to bottom", lambda: self.move("bottom"))

        self.a_epg_src = A("Sources && scan...", self.epg_sources_dialog)
        self.a_epg_fill = A("Auto-fill EPG IDs by channel name...", self.autofill_epg)

        self.a_eps_sel = A("Fetch episodes for selected series", self.fetch_episodes_selected)
        self.a_eps_all = A("Fetch episodes for ALL series...", self.fetch_episodes_all)
        self.a_eps_edit = A("View / trim episodes of selected series...", self.edit_episodes)

        self.a_catmgr = A("Category manager...", self.category_manager, "Ctrl+Shift+C",
                          "See every category in one list, rename or merge them, and fix capitalization.")
        self.a_catmgr.setShortcuts([QKeySequence("Ctrl+Shift+C"), QKeySequence("Ctrl+M")])   # second key as a fallback
        self.a_catmgr.setShortcutContext(Qt.ApplicationShortcut)
        self.a_dupes = A("Find duplicates...", self.duplicate_finder, "Ctrl+Shift+U",
                         "Look for the same movie, series or channel listed more than once, then keep, delete, rename or move.")
        self.a_dupes.setShortcutContext(Qt.ApplicationShortcut)
        self.a_rules = A("Regex rules...", self.regex_rules, "Ctrl+Shift+R",
                         "Strip messy prefixes, move matches into a clean category, or delete them, using saved rules.")
        self.a_rules.setShortcutContext(Qt.ApplicationShortcut)
        self.a_sort = A("Sort A-Z...", self.sort_az,
                        None, "Put items in alphabetical order, within each category or as one big list (one undo step).")
        self.a_help = A("Help contents", lambda: self.show_help(), "F1")
        self.a_keys = A("Keyboard shortcuts", lambda: self.show_help("Keyboard shortcuts"))
        self.a_terms = A("Disclaimer and terms of use", lambda: self.show_help("Disclaimer and terms of use"))
        self.a_about = A(f"About {APP_NAME}", self.about)

        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.a_connect, None, self.a_new, self.a_open, self.a_save, self.a_saveas, None,
                  self.a_export, self.a_list, self.a_xs, self.a_serve, None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_cat, self.a_catmgr, self.a_dupes, self.a_rules, self.a_epgid, self.a_logo, self.a_find,
                  None, self.a_fav, self.a_impfav, self.a_seen, None, self.a_del, self.a_restore):
            m.addSeparator() if a is None else m.addAction(a)
        mv = m.addMenu("Move")
        for a in (self.a_top, self.a_up, self.a_down, self.a_bottom):
            mv.addAction(a)
        m.addAction(self.a_sort)
        m = mb.addMenu("E&PG")
        m.addAction(self.a_epg_src)
        m.addAction(self.a_epg_fill)
        m = mb.addMenu("&Series")
        for a in (self.a_eps_sel, self.a_eps_all, self.a_eps_edit):
            m.addAction(a)
        m = mb.addMenu("&View")
        tm = m.addMenu("Theme")
        self.theme_group = QActionGroup(self)
        self.theme_actions = {}
        for name in themes.NAMES:
            a = QAction(name, self, checkable=True)
            a.triggered.connect(lambda _=False, n=name: self.set_theme(n))
            self.theme_group.addAction(a)
            tm.addAction(a)
            self.theme_actions[name] = a
        self.set_theme(self.cfg.get("theme", "System"), save=False)
        m = mb.addMenu("&Help")
        for a in (self.a_help, self.a_keys, self.a_terms, None, self.a_about):
            m.addSeparator() if a is None else m.addAction(a)

        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        for a in (self.a_connect, self.a_save, self.a_export, self.a_xs, None, self.a_undo, self.a_redo, None,
                  self.a_fav, self.a_del, self.a_restore, self.a_find):
            tb.addSeparator() if a is None else tb.addAction(a)

    # ====================================================================
    # help
    # ====================================================================
    def set_theme(self, name, save=True):
        name = themes.apply(QApplication.instance(), name)
        self.theme_actions[name].setChecked(True)
        if save:
            self.cfg["theme"] = name
            cfg.save(self.cfg)
            self.statusBar().showMessage(f"Theme: {name}", 4000)

    def show_help(self, topic=None):
        dlg = getattr(self, "_help", None)
        if dlg is None:                      # one help window, made once and reused (close just hides it)
            self._help = dlg = HelpDialog(self)
            dlg.setModal(False)
        dlg.goto(topic or dlg.sections[0][0])      # always start fresh: top page, empty search
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def require_terms(self):
        """First run (or after the text changes): ask for agreement, otherwise close the app. True if agreed."""
        from core.terms import TERMS_VERSION
        if self.cfg.get("terms_accepted") == TERMS_VERSION:
            return True
        if TermsDialog(self).exec() != QDialog.Accepted:
            return False
        self.cfg["terms_accepted"] = TERMS_VERSION
        cfg.save(self.cfg)
        return True

    def about(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setTextFormat(Qt.RichText)
        box.setText(about_text())
        box.exec()

    # ====================================================================
    # helpers
    # ====================================================================
    def info(self, title, text):
        QMessageBox.information(self, title, text)

    def run_task(self, title, fn, on_ok):
        if self._task and self._task.isRunning():
            return
        dlg = QProgressDialog(title, "Cancel", 0, 100, self)
        dlg.setWindowTitle(title)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setMinimumWidth(460)
        dlg.setValue(0)
        task = Task(fn, self)

        def prog(p, m):
            if p < 0:
                dlg.setRange(0, 0)
            else:
                dlg.setRange(0, 100)
                dlg.setValue(min(p, 100))
            if m:
                dlg.setLabelText(m)

        def finish():
            try:
                dlg.canceled.disconnect()
            except (RuntimeError, TypeError):
                pass
            dlg.hide()
            dlg.deleteLater()
            self._task = None

        task.progress.connect(prog)
        dlg.canceled.connect(task.cancel)
        task.succeeded.connect(lambda r: (finish(), on_ok(r)))
        task.failed.connect(lambda msg: (finish(), QMessageBox.critical(self, title, msg)))
        task.cancelled.connect(lambda: (finish(), self.statusBar().showMessage("Cancelled.", 5000)))
        task.finished.connect(task.deleteLater)
        self._task = task
        task.start()
        dlg.show()

    def selected_rows(self):
        rows = set()
        for rng in self.table.selectionModel().selection():
            rows.update(range(rng.top(), rng.bottom() + 1))
        return sorted(rows)

    def selected_items(self):
        r = self.model.rows
        return [r[i] for i in self.selected_rows() if i < len(r)]

    def _need_selection(self):
        sel = self.selected_items()
        if not sel:
            self.statusBar().showMessage("Select some rows first.", 4000)
        return sel

    def _mode_pred(self, mode):
        has = self.epg_index.has if self.epg_index else None
        return {
            "active": lambda it: not it.deleted,
            "all": lambda it: True,
            "deleted": lambda it: it.deleted,
            "edited": lambda it: bool(it.edits),
            "fav": lambda it: it.fav and not it.deleted,
            "noepg": lambda it: it.kind == "live" and not it.epg_id and not it.deleted,
            "badepg": lambda it: (has is not None and it.kind == "live" and bool(it.epg_id)
                                  and not has(it.epg_id) and not it.deleted),
            "nologo": lambda it: not it.logo and not it.deleted,
            "new": lambda it: it.new and not it.deleted,
            "gone": lambda it: it.gone,
        }[mode]

    def _update_title(self):
        name = os.path.basename(self.lib.path) if self.lib.path else "untitled"
        self.setWindowTitle(f"Xtream Editor - {name}{' *' if self.lib.dirty else ''}")

    def _update_actions(self):
        u, r = self.lib.undo_stack, self.lib.redo_stack
        self.a_undo.setEnabled(bool(u))
        self.a_redo.setEnabled(bool(r))
        self.a_undo.setText(f"Undo {u[-1][0]}" if u else "Undo")
        self.a_redo.setText(f"Redo {r[-1][0]}" if r else "Redo")

    def _update_status(self):
        n = len(self.model.rows)
        total = len(self.lib.items)
        deleted = sum(1 for it in self.lib.items if it.deleted)
        sel = len(self.selected_rows())
        self.status_lbl.setText(f"Showing {n:,} of {total:,}   |   {deleted:,} deleted   |   {sel:,} selected")

    def _after_change(self, msg=None):
        self._update_title()
        self._update_actions()
        if self.xs.running:                       # keep the live server in step with your edits
            self._xs_timer.start()
        if msg:
            self.statusBar().showMessage(msg, 6000)

    # ====================================================================
    # view: filtering, sidebar
    # ====================================================================
    def refresh(self, rebuild_sidebar=True):
        sb = self.table.verticalScrollBar()
        pos = sb.value()
        kind, cat = self.kind, self.category
        pred = self._mode_pred(self.mode.currentData())
        tokens = self.search.text().lower().split()
        rows = []
        for it in self.lib.items:
            if kind and it.kind != kind:
                continue
            if cat and it.category not in cat:
                continue
            if not pred(it):
                continue
            if tokens:
                h = (it.name + "\x00" + it.category + "\x00" + it.epg_id).lower()
                if not all(t in h for t in tokens):
                    continue
            rows.append(it)
        self.model.epg_has = self.epg_index.has if self.epg_index else None
        self.model.set_rows(rows)
        sb.setValue(pos)
        self._update_status()
        if self.mode.currentData() == "badepg" and not self.epg_index:
            self.statusBar().showMessage("Scan your EPG sources first (EPG menu) so I know which IDs exist.", 8000)
        if rebuild_sidebar:
            self.refresh_sidebar()

    def refresh_sidebar(self):
        pred = self._mode_pred(self.mode.currentData())
        counts, per_kind = Counter(), Counter()
        for it in self.lib.items:
            if pred(it):
                per_kind[it.kind] += 1
                if self.kind in (None, it.kind):
                    counts[it.category] += 1
        labels = [f"All ({sum(per_kind.values()):,})", f"Live ({per_kind['live']:,})",
                  f"Movies ({per_kind['vod']:,})", f"Series ({per_kind['series']:,})"]
        self.tabs.blockSignals(True)
        for i, n in enumerate(labels):
            self.tabs.setTabText(i, n)
        self.tabs.blockSignals(False)

        if self.category and not self.category <= set(counts):
            self.category &= set(counts)          # drop categories that no longer exist/show
            self.cats.blockSignals(True)
            self._fill_cats(counts)
            self.cats.blockSignals(False)
            self.refresh(rebuild_sidebar=False)
            return
        scroll = self.cats.verticalScrollBar().value()
        self.cats.blockSignals(True)
        self._fill_cats(counts)
        self.cats.blockSignals(False)
        self.cats.verticalScrollBar().setValue(scroll)

    def _fill_cats(self, counts):
        self.cats.clear()
        total = sum(counts.values())
        first = QListWidgetItem(f"All categories ({total:,})")
        first.setData(Qt.UserRole, None)
        self.cats.addItem(first)
        picked = []
        for cat in sorted(counts, key=str.lower):
            li = QListWidgetItem(f"{cat} ({counts[cat]:,})")
            li.setData(Qt.UserRole, cat)
            self.cats.addItem(li)
            if cat in self.category:
                picked.append(li)
        for li in picked or [first]:
            li.setSelected(True)
        self.cats.setCurrentItem(picked[0] if picked else first, QItemSelectionModel.NoUpdate)

    def _selected_cats(self):
        """Specific categories picked in the sidebar (empty if only 'All categories')."""
        return {li.data(Qt.UserRole) for li in self.cats.selectedItems()} - {None}

    def _cats_selection_changed(self):
        items = self.cats.selectedItems()
        picked = {li.data(Qt.UserRole) for li in items}
        # "All categories" row in the mix (or nothing picked) means no category filter
        self.category = set() if (not picked or None in picked) else picked
        self.refresh(rebuild_sidebar=False)

    def _tab_changed(self, i):
        self.kind = TAB_KINDS[i]
        self.category = set()
        self.refresh()

    # ---- sidebar context menu -----------------------------------------
    def _cats_menu(self, pos):
        li = self.cats.itemAt(pos)
        if not li or li.data(Qt.UserRole) is None:
            return
        if not li.isSelected():                 # right-clicked something outside the selection
            self.cats.clearSelection()
            li.setSelected(True)
        cats = self._selected_cats()
        word = f"{len(cats)} categories" if len(cats) > 1 else "this category"
        m = QMenu(self)
        m.addAction(f"Delete everything in {word}", lambda: self.category_bulk(cats, True))
        m.addAction(f"Restore everything in {word}", lambda: self.category_bulk(cats, False))
        m.addSeparator()
        m.addAction("Rename / merge..." if len(cats) > 1 else "Rename / merge category...",
                    lambda: self.rename_category(cats))
        m.addAction("Category manager...", self.category_manager)
        m.addAction("Sort A-Z...", self.sort_az)
        m.exec(self.cats.viewport().mapToGlobal(pos))

    def _cat_items(self, cats):
        return [it for it in self.lib.items if it.category in cats and self.kind in (None, it.kind)]

    def rename_category(self, cats):
        cats = set(cats)
        if not cats:
            return
        first = sorted(cats, key=str.lower)[0]
        text, ok = QInputDialog.getText(
            self, "Rename / merge category",
            "New name (type an existing category's name to merge into it).\n"
            + ("All the selected categories will be merged into it.\n" if len(cats) > 1 else "")
            + "Applies to the current tab.", text=first)
        text = text.strip()
        if not ok or not text or cats == {text}:
            return
        n = self.lib.change([(it, "category", text) for it in self._cat_items(cats)], "rename category")
        self.category = {text}
        self.refresh()
        self._after_change(f"Renamed category on {n:,} items.")

    def sort_az(self):
        sel = set(self.category) if self.category else set()
        dlg = SortDialog(self, sel, default_kinds=(self.kind,) if self.kind else ("live",))
        if dlg.exec() != QDialog.Accepted:
            return
        kinds = dlg.kinds()
        if not kinds:
            self.statusBar().showMessage("Tick at least one type to sort.", 5000)
            return
        changes = self.lib.sort_az_changes(kinds, sel if dlg.only_selected() else None, dlg.mode())
        n = self.lib.change(changes, "sort A-Z")
        self.refresh()
        self._after_change(f"Sorted A-Z: {n:,} item{'s' if n != 1 else ''} moved." if n else "Already in A-Z order.")

    def category_manager(self):
        dlg = getattr(self, "_catmgr", None)
        if dlg is None or not dlg.isVisible():
            self._catmgr = dlg = CategoryManagerDialog(
                self, self.lib,
                {"std_on": self.cfg.get("cat_std_on", True),
                 "std": self.cfg.get("cat_std_list") or DEFAULT_STANDARD,
                 "extra": self.cfg.get("cat_acronyms", "")},
                self.apply_category_names, self._save_acronyms)
            dlg.setModal(False)
            dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        else:
            dlg.load_rows()                   # pick up anything changed since it was last open
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def duplicate_finder(self):
        dlg = getattr(self, "_dupes", None)
        if dlg is None:
            self._dupes = dlg = DuplicateFinderDialog(self, self.lib, self.apply_duplicate_changes,
                                                       self.cfg.get("dupes_ask", True), self._save_dupes_ask, self.undo)
            dlg.setModal(False)
            dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        elif not dlg.isVisible():
            dlg.reload()                      # old results may be stale
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def regex_rules(self):
        dlg = getattr(self, "_rules", None)
        if dlg is None:
            self._rules = dlg = RegexRulesDialog(
                self, self.lib, self.cfg.get("regex_rules", []), self._save_rules, self.apply_rule_changes,
                self.cfg.get("rules_ask", True), self._save_rules_ask, self.undo)
            dlg.setModal(False)
            dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        elif not dlg.isVisible():
            dlg.reload()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _save_rules(self, rules):
        self.cfg["regex_rules"] = rules
        cfg.save(self.cfg)

    def _save_rules_ask(self, on):
        self.cfg["rules_ask"] = bool(on)
        cfg.save(self.cfg)

    def apply_rule_changes(self, changes):
        n = self.lib.change(changes, "regex rules")
        self.category = set()                 # a category you had selected may be gone now
        self.refresh()
        self._after_change(f"Regex rules: {n:,} change{'s' if n != 1 else ''} applied.")

    def _save_dupes_ask(self, on):
        self.cfg["dupes_ask"] = bool(on)
        cfg.save(self.cfg)

    def apply_duplicate_changes(self, changes):
        n = self.lib.change(changes, "resolve duplicates")
        self.refresh()
        self._after_change(f"Duplicates: {n:,} change{'s' if n != 1 else ''} applied.")

    def _save_acronyms(self, prefs):
        self.cfg.update(cat_std_on=bool(prefs.get("std_on", True)), cat_std_list=prefs.get("std", ""),
                        cat_acronyms=prefs.get("extra", ""))
        cfg.save(self.cfg)

    def apply_category_names(self, mapping):
        """mapping: {(kind, old name): new name}. One undo step; merging just means two rows get the same name."""
        changes = [(it, "category", mapping[(it.kind, it.category)])
                   for it in self.lib.items if (it.kind, it.category) in mapping]
        n = self.lib.change(changes, "edit categories")
        self.category = set()
        self.refresh()
        self._after_change(f"Renamed {len(mapping)} categor{'y' if len(mapping) == 1 else 'ies'} ({n:,} items).")

    def category_bulk(self, cats, delete):
        cats = set(cats)
        if not cats:
            self.statusBar().showMessage("Pick one or more specific categories first (not 'All categories').", 6000)
            return
        items = self._cat_items(cats)
        # Undo covers this, so only stop and ask when it would remove a lot at once
        if delete and len(items) > CONFIRM_DELETE_ABOVE and QMessageBox.question(
                self, "Delete categories",
                f"Delete {len(items):,} items across {len(cats)} categor{'y' if len(cats) == 1 else 'ies'}?"
                "\n(You can undo.)") != QMessageBox.Yes:
            return
        n = self.lib.change([(it, "deleted", delete) for it in items],
                            "delete categories" if delete else "restore categories")
        self.refresh()
        self._after_change(f"{'Deleted' if delete else 'Restored'} {n:,} items in {len(cats)} "
                           f"categor{'y' if len(cats) == 1 else 'ies'}.")

    def _sidebar_has_focus(self):
        return self.cats.hasFocus()

    # ---- table context menu ----------------------------------------------
    def _table_menu(self, pos):
        m = QMenu(self)
        m.addAction(self.a_fav)
        m.addSeparator()
        for a in (self.a_cat, self.a_epgid, self.a_logo, self.a_find):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_del)
        m.addAction(self.a_restore)
        m.addSeparator()
        mv = m.addMenu("Move")
        for a in (self.a_top, self.a_up, self.a_down, self.a_bottom):
            mv.addAction(a)
        sel = self.selected_items()
        if sel and all(it.kind == "series" for it in sel):
            m.addSeparator()
            m.addAction(self.a_eps_sel)
            m.addAction(self.a_eps_edit)
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ====================================================================
    # editing
    # ====================================================================
    def _on_cell_edit(self, item, field, value):
        n = self.lib.change([(item, field, value)], f"edit {field}")
        if n:
            self._after_change()
            self._side_timer.start()

    def _apply(self, changes, label):
        n = self.lib.change(changes, label)
        if n:
            self.refresh()
        self._after_change(f"{label}: {n:,} change{'s' if n != 1 else ''}." if n else "Nothing to change.")
        return n

    def set_field(self, field):
        sel = self._need_selection()
        if not sel:
            return
        if field == "epg_id":
            sel = [it for it in sel if it.kind == "live"]
            if not sel:
                self.statusBar().showMessage("EPG IDs only apply to live channels.", 5000)
                return
        if field == "category":
            cats = self.lib.categories()
            text, ok = QInputDialog.getItem(self, "Set category", f"Category for {len(sel):,} item(s) "
                                            "(pick one or type a new name):", cats, 0, True)
            text = text.strip() or "Uncategorized"
        else:
            label = "EPG ID" if field == "epg_id" else "Logo URL"
            text, ok = QInputDialog.getText(self, f"Set {label}", f"{label} for {len(sel):,} item(s) "
                                            "(leave empty to clear):")
            text = text.strip()
        if ok:
            self._apply([(it, field, text) for it in sel], f"set {field}")

    def delete_selected(self):
        if self._sidebar_has_focus():           # Delete key / menu acts on the category list
            self.category_bulk(self._selected_cats(), True)
            return
        sel = self._need_selection()
        if sel:
            self._apply([(it, "deleted", True) for it in sel if not it.deleted], "delete")

    def toggle_favorite(self):
        sel = self._need_selection()
        if sel:
            on = not all(it.fav for it in sel)
            self._apply([(it, "fav", on) for it in sel], "favorite" if on else "unfavorite")

    def mark_seen(self):
        fresh = [it for it in self.lib.items if it.new]
        if not fresh:
            self.statusBar().showMessage("Nothing is marked new.", 4000)
            return
        self._apply([(it, "new", False) for it in fresh], "mark seen")

    def import_favorites(self):
        if not self.lib.items:
            self.info("Nothing to match against", "Fetch or open a list first.")
            return
        folder = self.cfg.get("import_dir") or self.cfg.get("export_dir") or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Import a list of names (one per line)", folder,
                                              "Text files (*.txt *.csv *.lst);;All files (*)")
        if not path:
            return
        try:
            raw = open(path, "rb").read()
        except OSError as e:
            QMessageBox.warning(self, "Couldn't read that file", str(e))
            return
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        lines = matcher.parse_lines(text)
        if not lines:
            self.info("Nothing to import", "I didn't find any names in that file (one name per line).")
            return
        self.cfg["import_dir"] = os.path.dirname(path)
        cfg.save(self.cfg)
        items = [it for it in self.lib.items if not it.deleted and not it.gone]

        def add(chosen):
            return self._apply([(it, "fav", True) for it in chosen if not it.fav], "import favorites")

        dlg = ImportFavoritesDialog(self, lines, items, add)
        dlg.exec()
        n = getattr(dlg, "added", 0)
        if n:
            self.statusBar().showMessage(f"Starred {n:,} item(s) from the imported list. Save the project to keep them.", 8000)

    def restore_selected(self):
        if self._sidebar_has_focus():
            self.category_bulk(self._selected_cats(), False)
            return
        sel = self._need_selection()
        if sel:
            self._apply([(it, "deleted", False) for it in sel if it.deleted], "restore")

    def find_replace(self):
        sel = self.selected_items()
        dlg = FindReplaceDialog(self, len(sel), len(self.model.rows))
        if not dlg.exec():
            return
        v = dlg.values()
        if not v["find"]:
            return
        try:
            pat = re.compile(v["find"] if v["regex"] else re.escape(v["find"]),
                             0 if v["case"] else re.IGNORECASE)
        except re.error as e:
            QMessageBox.warning(self, "Bad pattern", str(e))
            return
        repl = v["replace"]
        sub = repl if v["regex"] else (lambda m: repl)      # plain mode: replacement is literal
        targets = sel if v["selected_only"] else self.model.rows
        field, changes = v["field"], []
        for it in targets:
            if field == "epg_id" and it.kind != "live":
                continue
            old = getattr(it, field)
            try:
                new = pat.sub(sub, old).strip()
            except (re.error, IndexError) as e:
                QMessageBox.warning(self, "Bad replacement", str(e))
                return
            if field == "name" and not new:
                continue
            if field == "category" and not new:
                new = "Uncategorized"
            if new != old:
                changes.append((it, field, new))
        self._apply(changes, "find/replace")

    def move(self, how):
        sel = self._need_selection()
        if not sel:
            return
        if not self.model.sorted_by_order():
            self.info("Sort by order first", "Click the \"#\" column header so the list is in playlist "
                      "order (ascending), then move things.")
            return
        selset = {id(it) for it in sel}
        changes = []
        for kind in KINDS:
            if not any(it.kind == kind for it in sel):
                continue
            order = self.lib.ordered(kind)
            if how in ("top", "bottom"):
                chosen = [it for it in self.model.rows if id(it) in selset and it.kind == kind]
                rest = [it for it in order if id(it) not in selset]
                new = chosen + rest if how == "top" else rest + chosen
            else:
                vis = [it for it in self.model.rows if it.kind == kind]
                newvis = vis[:]
                if how == "up":
                    for i in range(1, len(newvis)):
                        if id(newvis[i]) in selset and id(newvis[i - 1]) not in selset:
                            newvis[i - 1], newvis[i] = newvis[i], newvis[i - 1]
                else:
                    for i in range(len(newvis) - 2, -1, -1):
                        if id(newvis[i]) in selset and id(newvis[i + 1]) not in selset:
                            newvis[i + 1], newvis[i] = newvis[i], newvis[i + 1]
                pos = {id(it): i for i, it in enumerate(order)}
                slots = sorted(pos[id(it)] for it in vis)
                new = order[:]
                for slot, it in zip(slots, newvis):
                    new[slot] = it
            changes += Library.renumber_changes(new)
        n = self.lib.change(changes, f"move {how}")
        if n:
            self.refresh(rebuild_sidebar=False)
            self._reselect(sel)
        self._after_change()

    def _reselect(self, items):
        want = {id(it) for it in items}
        sm = self.table.selectionModel()
        sm.clearSelection()
        from PySide6.QtCore import QItemSelection
        sel = QItemSelection()
        for i, it in enumerate(self.model.rows):
            if id(it) in want:
                sel.select(self.model.index(i, 0), self.model.index(i, len(COLS) - 1))
        sm.select(sel, sm.SelectionFlag.Select)

    def undo(self):
        if self.lib.undo():
            self.refresh()
            self._after_change("Undone.")

    def redo(self):
        if self.lib.redo():
            self.refresh()
            self._after_change("Redone.")

    # ====================================================================
    # server fetch
    # ====================================================================
    def connect_and_fetch(self):
        conn = dict(self.lib.connection) if self.lib.connection else {
            k: self.cfg.get(k, "") for k in ("server", "username", "password", "ua")}
        dlg = ConnectDialog(self, conn)
        if not dlg.exec():
            return
        conn = dlg.values()
        self.cfg.update(conn)
        cfg.save(self.cfg)

        def job(progress, cancelled):
            return fetch_all(XtreamClient(**conn), progress, cancelled)

        def done(res):
            self.lib.connection = conn
            stats = self.lib.merge_server(res["items"])
            self.category = set()
            self.refresh()
            self._after_change()
            ui = res["info"].get("user_info", {})
            bits = []
            if ui.get("status"):
                bits.append(f"status: {ui['status']}")
            try:
                bits.append("expires " + time.strftime("%Y-%m-%d", time.localtime(int(ui["exp_date"]))))
            except (KeyError, TypeError, ValueError):
                pass
            if ui.get("max_connections"):
                bits.append(f"max connections: {ui['max_connections']}")
            msg = (f"Fetched {len(res['items']):,} entries.\n"
                   f"New to this project: {stats['added']:,}   |   No longer on server: {stats['gone']:,}\n")
            if bits:
                msg += "\nAccount - " + ", ".join(bits)
            if res["warnings"]:
                msg += "\n\nHeads up:\n" + "\n".join(res["warnings"])
            self.info("Fetch complete", msg)

        self.run_task("Fetching from server", job, done)

    # ====================================================================
    # projects
    # ====================================================================
    def _load_last(self):
        p = self.cfg.get("last_project")
        if p and os.path.exists(p):
            self._load_project(p)

    def _maybe_save(self):
        if not self.lib.dirty or not self.lib.items:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Save your project first?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            return self.save_project()
        return True

    def new_project(self):
        if not self._maybe_save():
            return
        conn = self.lib.connection
        self.lib = Library()
        self.lib.connection = conn
        self.epg_index = None
        self.category = set()
        self.refresh()
        self._after_change("New project. Use File > Connect to fetch.")

    def open_project(self):
        if not self._maybe_save():
            return
        start = os.path.dirname(self.cfg.get("last_project") or "") or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Open project", start,
                                              "Xtream Editor projects (*.xtp);;All files (*)")
        if path:
            self._load_project(path)

    def _load_project(self, path):
        def job(progress, cancelled):
            progress(-1, "Reading project...")
            lib = Library()
            lib.load(path)
            return lib

        def done(lib):
            self.lib = lib
            self.epg_index = None
            self.category = set()
            self.cfg["last_project"] = path
            cfg.save(self.cfg)
            self.refresh()
            self._after_change(f"Opened {os.path.basename(path)} ({len(lib.items):,} items).")

        self.run_task("Opening project", job, done)

    def save_project(self):
        if not self.lib.path:
            return self.save_project_as()
        return self._save_to(self.lib.path)

    def save_project_as(self):
        start = self.lib.path or os.path.join(os.path.expanduser("~"), "channels.xtp")
        path, _ = QFileDialog.getSaveFileName(self, "Save project", start, "Xtream Editor projects (*.xtp)")
        if not path:
            return False
        if not path.lower().endswith(".xtp"):
            path += ".xtp"
        return self._save_to(path)

    def _save_to(self, path):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.lib.save(path)
        except OSError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Couldn't save", str(e))
            return False
        QApplication.restoreOverrideCursor()
        self.cfg["last_project"] = path
        cfg.save(self.cfg)
        self._after_change(f"Saved {os.path.basename(path)}.")
        return True

    # ====================================================================
    # EPG
    # ====================================================================
    def _epg_sources(self):
        out = []
        if self.lib.use_provider_epg and self.lib.connection.get("server"):
            out.append(("Provider guide", xmltv_url(self.lib.connection)))
        for u in self.lib.epg_sources:
            out.append((epg.label_for(u), u))
        return out

    def _ua(self):
        return self.lib.connection.get("ua") or DEFAULT_UA

    def epg_sources_dialog(self):
        dlg = EpgSourcesDialog(self, self.lib.epg_sources, self.lib.use_provider_epg)
        if dlg.exec():
            self.lib.epg_sources, self.lib.use_provider_epg = dlg.values()
            self.lib.dirty = True
            self._after_change()
            self.scan_epg()

    def scan_epg(self):
        sources = self._epg_sources()
        if not sources:
            self.info("No guides", "Connect to a server first, or add extra guide URLs.")
            return
        ua = self._ua()

        def job(progress, cancelled):
            return epg.refresh_sources(sources, ua, progress, cancelled)

        def done(res):
            idx, errors = res
            if idx.sources:
                self.epg_index = idx
            self.refresh()
            msg = "\n".join(f"{label}: {n:,} channels" for label, n in idx.sources) or "Nothing could be scanned."
            if idx.sources:
                live = [it for it in self.lib.items if it.kind == "live" and not it.deleted]
                with_id = [it for it in live if it.epg_id]
                found = sum(1 for it in with_id if idx.has(it.epg_id))
                msg += (f"\n\nLive channels: {len(live):,}\n  with an EPG ID: {len(with_id):,}\n"
                        f"  ID found in your guides: {found:,}\n  ID not found: {len(with_id) - found:,} "
                        f"(shown in red; filter with Show > \"EPG ID not in my guides\")\n"
                        f"  no ID at all: {len(live) - len(with_id):,}")
            if errors:
                msg += "\n\nProblems:\n" + "\n".join(errors)
            self.info("Guides scanned", msg)

        self.run_task("Downloading and scanning guides", job, done)

    def autofill_epg(self):
        if not self.epg_index:
            if QMessageBox.question(self, "Scan guides first", "I need to scan your guides before I can "
                                    "match names. Do that now?") == QMessageBox.Yes:
                self.scan_epg()
            return
        box = QMessageBox(self)
        box.setWindowTitle("Auto-fill EPG IDs")
        box.setText("Match live channels to guide channels by name.\n\nWhich channels should I try?")
        b1 = box.addButton("Only those with no EPG ID", QMessageBox.AcceptRole)
        b2 = box.addButton("No ID, or ID not in my guides", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (b1, b2):
            return
        idx = self.epg_index
        include_bad = clicked is b2
        changes, samples = [], []
        for it in self.lib.items:
            if it.kind != "live" or it.deleted:
                continue
            if it.epg_id and not (include_bad and not idx.has(it.epg_id)):
                continue
            m = idx.match(it.name)
            if m and m != it.epg_id:
                changes.append((it, "epg_id", m))
                if len(samples) < 25:
                    samples.append(f"{it.name}  ->  {m}")
        if not changes:
            self.info("Auto-fill", "No new matches found.")
            return
        q = QMessageBox(self)
        q.setWindowTitle("Apply matches?")
        q.setText(f"Found {len(changes):,} matches by channel name. Names that look alike can still be "
                  "different channels, so skim the results afterwards (edited cells are highlighted, and "
                  "Undo reverts the whole batch).\n\nApply them?")
        q.setDetailedText("First matches:\n" + "\n".join(samples))
        q.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        if q.exec() == QMessageBox.Yes:
            self._apply(changes, "auto-fill EPG IDs")

    # ====================================================================
    # series episodes
    # ====================================================================
    def fetch_episodes_selected(self):
        sel = [it for it in self.selected_items() if it.kind == "series"]
        if not sel:
            self.statusBar().showMessage("Select one or more series first.", 5000)
            return
        self.fetch_episodes_for(sel)

    def fetch_episodes_all(self):
        todo = [it for it in self.lib.items if it.kind == "series" and not it.deleted and it.episodes is None]
        if not todo:
            self.info("Episodes", "Every active series already has its episodes fetched.")
            return
        if QMessageBox.question(self, "Fetch all episodes",
                                f"This makes one request per series ({len(todo):,}). With big providers "
                                "it can take a while and some rate-limit. You can cancel and keep what "
                                "was fetched so far.\n\nTip: delete the series you don't want first.\n\nGo?") \
                != QMessageBox.Yes:
            return
        self.fetch_episodes_for(todo)

    def fetch_episodes_for(self, items, then=None):
        conn = self.lib.connection
        if not conn:
            self.info("Not connected", "Connect to a server first.")
            return
        local = threading.local()

        def get_client():
            if not hasattr(local, "c"):
                local.c = XtreamClient(**conn)
            return local.c

        def work(it):
            try:
                return it, fetch_episodes(get_client(), it.id), None
            except Exception as e:                      # noqa: BLE001
                return it, None, str(e)

        def job(progress, cancelled):
            total, done, results, errors = len(items), 0, [], []
            with ThreadPoolExecutor(EPISODE_WORKERS) as ex:
                futs = []
                for it in items:
                    futs.append(ex.submit(lambda i=it: (None, None, "cancelled") if cancelled() else work(i)))
                for f in as_completed(futs):
                    it, eps, err = f.result()
                    done += 1
                    if it is not None and eps is not None:
                        results.append((it, eps))
                    elif err and err != "cancelled":
                        errors.append(err)
                    progress(int(done * 100 / total), f"Series {done:,} / {total:,}")
            return {"results": results, "errors": errors, "cancelled": cancelled(), "total": total}

        def finish(res):
            for it, eps in res["results"]:
                old = {e["id"]: e for e in (it.episodes or [])}
                for e in eps:
                    if old.get(e["id"], {}).get("skip"):
                        e["skip"] = True
                it.episodes = eps
            if res["results"]:
                self.lib.dirty = True
            n_eps = sum(len(e) for _, e in res["results"])
            msg = f"Fetched episodes for {len(res['results']):,} of {res['total']:,} series ({n_eps:,} episodes)."
            if res["cancelled"]:
                msg += " (Cancelled - kept what finished.)"
            if res["errors"]:
                msg += f"\n{len(res['errors']):,} failed, e.g.: {res['errors'][0]}"
            self._after_change()
            self.statusBar().showMessage(msg.splitlines()[0], 10000)
            if res["errors"] or res["cancelled"]:
                self.info("Episodes", msg)
            if then:
                then()

        self.run_task("Fetching episodes", job, finish)

    def edit_episodes(self):
        sel = [it for it in self.selected_items() if it.kind == "series"]
        if len(sel) != 1:
            self.statusBar().showMessage("Select exactly one series.", 5000)
            return
        it = sel[0]
        if it.episodes is None:
            self.fetch_episodes_for([it], then=lambda: self._open_episodes(it))
        else:
            self._open_episodes(it)

    def _open_episodes(self, it):
        if not it.episodes:
            self.info("No episodes", f"The server returned no episodes for {it.name}.")
            return
        dlg = EpisodesDialog(self, it)
        if dlg.exec() and dlg.apply():
            self.lib.dirty = True
            self._after_change()

    # ====================================================================
    # export & serve
    # ====================================================================
    def export(self):
        if not self.lib.items:
            self.info("Nothing to export", "Fetch or open something first.")
            return
        lib = self.lib
        counts = {
            "live": sum(1 for i in lib.items if i.kind == "live" and not i.deleted and not i.gone),
            "vod": sum(1 for i in lib.items if i.kind == "vod" and not i.deleted and not i.gone),
            "series": sum(1 for i in lib.items if i.kind == "series" and not i.deleted and not i.gone and i.episodes),
        }
        base = f"http://{lan_ip()}:{self.cfg.get('serve_port', 8765)}"
        dlg = ExportDialog(self, counts, self.cfg, base, can_merge=bool(self._epg_sources()))
        if not dlg.exec():
            return
        v = dlg.values()
        self.cfg["export_dir"], self.cfg["export_base"] = v["folder"], v["base"]
        cfg.save(self.cfg)
        conn, sources, ua = lib.connection, self._epg_sources(), self._ua()
        no_eps = sum(1 for i in lib.items if i.kind == "series" and not i.deleted and not i.gone and not i.episodes)

        def job(progress, cancelled):
            header, epg_stats = "", None
            lo = 0
            if v["epg_mode"] == "provider":
                header = xmltv_url(conn)
            elif v["epg_mode"] == "merge":
                wanted = {i.epg_id for i in lib.items if i.kind == "live" and i.epg_id
                          and not i.deleted and not i.gone} if "live" in v["kinds"] else set()
                fname = "epg.xml.gz" if v["gz"] else "epg.xml"
                fill = placeholder.fill_entries(lib.items) if v.get("placeholders") else None
                epg_stats = epg.merge_xmltv(sources, wanted, os.path.join(v["folder"], fname), ua,
                                            v["gz"], lambda p, m="": progress(int(p * 0.7), m), cancelled, fill)
                if v["base_url"]:
                    header = f"{v['base_url']}/{fname}"
                lo = 70
            os.makedirs(v["folder"], exist_ok=True)
            stats = export_playlists(lib, v["folder"], v["base"], v["kinds"], v["split"], v["live_ext"],
                                     header, v["prefix"], lambda p, m="": progress(lo + int(p * (100 - lo) / 100), m),
                                     cancelled, bool(v.get("placeholders")))
            return stats, epg_stats

        def done(res):
            stats, epg_stats = res
            lines = [f"Saved to {v['folder']}:"] + [f"  {os.path.basename(f)}" for f in stats["files"]]
            if epg_stats:
                lines.append(f"  {'epg.xml.gz' if v['gz'] else 'epg.xml'} "
                             f"({epg_stats['channels']:,} channels, {epg_stats['programs']:,} programs)")
                if epg_stats.get("placeholders"):
                    lines.append(f"  {epg_stats['placeholders']:,} channels had no guide data, so they got a placeholder.")
            lines.append(f"\nLive: {stats['live']:,}   Movies: {stats['vod']:,}   Episodes: {stats['series_eps']:,}")
            if "series" in v["kinds"] and (stats["series_no_eps"] or no_eps):
                lines.append(f"\n{max(stats['series_no_eps'], no_eps):,} series were skipped because their "
                             "episodes haven't been fetched (Series menu).")
            lines.append("\nThe playlist contains your login. Treat it like a password.")
            self.info("Export finished", "\n".join(lines))

        self.run_task("Exporting", job, done)

    def export_list_file(self):
        if not self.lib.items:
            self.info("Nothing to export", "Fetch or open something first.")
            return
        counts = Counter((it.kind, it.category, it.deleted, it.fav) for it in self.lib.items if not it.gone)
        dlg = ListExportDialog(self, counts)
        if not dlg.exec():
            return
        v = dlg.values()
        if not v["kinds"]:
            self.info("Nothing selected", "Tick at least one type.")
            return
        ext = v["fmt"]
        start = os.path.join(self.cfg.get("export_dir") or os.path.expanduser("~"), f"playlist_list.{ext}")
        path, _ = QFileDialog.getSaveFileName(self, "Save list", start,
                                              "CSV files (*.csv)" if ext == "csv" else "Text files (*.txt)")
        if not path:
            return
        try:
            n = export_list(self.lib, path, ext, v["kinds"], v["categories"], v["skip_deleted"], v["fav_only"])
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save", str(e))
            return
        self.cfg["export_dir"] = os.path.dirname(path)
        cfg.save(self.cfg)
        self.statusBar().showMessage(f"Saved {n:,} items to {path}", 8000)

    def serve(self):
        folder = self.cfg.get("export_dir") or os.path.expanduser("~")
        dlg = ServeDialog(self, self.server, folder, self.cfg.get("serve_port", 8765))
        dlg.exec()
        f, p = dlg.values()
        self.cfg["export_dir"], self.cfg["serve_port"] = f, p
        cfg.save(self.cfg)
        self.serve_lbl.setText(f"   Sharing at {self.server.base_url()}" if self.server.running else "")

    def xtream_server(self):
        def start(st):
            if not self.lib.items:
                return "Fetch or open a list first."
            if not self.lib.connection.get("server"):
                return "This project has no provider login yet. Use File > Connect first."
            try:
                self.xs.start(self.lib, st["xs_port"], st["xs_user"], st["xs_pass"], st["xs_mode"],
                              st["xs_epg"], st["xs_epg_hours"], placeholders=st.get("xs_placeholders", False))
            except OSError as e:
                return f"{e}\nTry a different port."
            self.cfg.update(st)
            cfg.save(self.cfg)
            self.serve_lbl.setText(f"   Xtream server: {self.xs.base_url()}")
            return None

        def stop():
            self.xs.stop()
            self.serve_lbl.setText("")

        st = dict(self.cfg)
        if not st.get("xs_pass"):
            st["xs_pass"] = cfg.make_password()
        dlg = XtreamServerDialog(self, self.xs, st, start, stop, self.xs.rebuild_guide)
        dlg.exec()

    # ====================================================================
    def closeEvent(self, e):
        if not self._maybe_save():
            e.ignore()
            return
        self.server.stop()
        self.xs.stop()
        self._remember_layout()
        cfg.save(self.cfg)
        e.accept()
