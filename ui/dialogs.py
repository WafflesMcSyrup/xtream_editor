"""Dialogs: connect, find/replace, export, EPG sources, LAN server, episodes."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

from core import matcher
from core.common import APP_DIR, APP_NAME, APP_VERSION
from core.models import KIND_LABEL
from core.xtream import DEFAULT_UA, parse_link


class ConnectDialog(QDialog):
    def __init__(self, parent, conn):
        super().__init__(parent)
        self.setWindowTitle("Connect to Xtream server")
        self.setMinimumWidth(580)
        form = QFormLayout(self)
        self.link = QLineEdit()
        self.link.setPlaceholderText("Paste your get.php / player_api.php link here (optional)")
        self.server = QLineEdit(conn.get("server", ""))
        self.server.setPlaceholderText("http://host:port")
        self.user = QLineEdit(conn.get("username", ""))
        self.pw = QLineEdit(conn.get("password", ""))
        self.pw.setEchoMode(QLineEdit.Password)
        show = QCheckBox("Show password")
        show.toggled.connect(lambda on: self.pw.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.ua = QLineEdit(conn.get("ua") or DEFAULT_UA)
        self.link.textChanged.connect(self._parse)
        form.addRow("Link:", self.link)
        form.addRow(QLabel("<i>...or fill these in yourself:</i>"))
        form.addRow("Server URL:", self.server)
        form.addRow("Username:", self.user)
        form.addRow("Password:", self.pw)
        form.addRow("", show)
        form.addRow("User-Agent:", self.ua)
        hint = QLabel("Some providers block unknown clients. If login fails with a 403, "
                      "try another User-Agent (for example the name of the app you normally use).")
        hint.setWordWrap(True)
        form.addRow(hint)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("Fetch channels")
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def _parse(self, text):
        p = parse_link(text)
        if p:
            self.server.setText(p["server"])
            self.user.setText(p["username"])
            self.pw.setText(p["password"])

    def _ok(self):
        if not (self.server.text().strip() and self.user.text().strip() and self.pw.text()):
            QMessageBox.warning(self, "Missing info", "Server, username and password are all needed.")
            return
        self.accept()

    def values(self):
        return {"server": self.server.text().strip(), "username": self.user.text().strip(),
                "password": self.pw.text(), "ua": self.ua.text().strip() or DEFAULT_UA}


class FindReplaceDialog(QDialog):
    FIELDS = [("Name", "name"), ("Category", "category"), ("EPG ID", "epg_id"), ("Logo URL", "logo")]

    def __init__(self, parent, n_selected, n_visible):
        super().__init__(parent)
        self.setWindowTitle("Find & replace")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.field = QComboBox()
        for label, f in self.FIELDS:
            self.field.addItem(label, f)
        self.find = QLineEdit()
        self.repl = QLineEdit()
        self.regex = QCheckBox("Regular expression")
        self.case = QCheckBox("Match case")
        self.scope_sel = QRadioButton(f"Selected rows ({n_selected:,})")
        self.scope_all = QRadioButton(f"Everything in the current view ({n_visible:,})")
        (self.scope_sel if n_selected else self.scope_all).setChecked(True)
        self.scope_sel.setEnabled(n_selected > 0)
        form.addRow("In field:", self.field)
        form.addRow("Find:", self.find)
        form.addRow("Replace with:", self.repl)
        form.addRow(self.regex)
        form.addRow(self.case)
        form.addRow(self.scope_sel)
        form.addRow(self.scope_all)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def values(self):
        return {"field": self.field.currentData(), "find": self.find.text(),
                "replace": self.repl.text(), "regex": self.regex.isChecked(),
                "case": self.case.isChecked(), "selected_only": self.scope_sel.isChecked()}


class _SourcesEdit(QPlainTextEdit):
    """One guide per line. Dropping files onto it adds each file's path on its own line."""

    def canInsertFromMimeData(self, src):
        return src.hasUrls() or super().canInsertFromMimeData(src)

    def insertFromMimeData(self, src):
        if src.hasUrls():
            from PySide6.QtGui import QTextCursor
            lines = [u.toLocalFile() if u.isLocalFile() else u.toString() for u in src.urls()]
            cur = self.toPlainText()
            sep = "" if not cur or cur.endswith("\n") else "\n"
            self.moveCursor(QTextCursor.End)
            self.insertPlainText(sep + "\n".join(lines) + "\n")
            return
        super().insertFromMimeData(src)


class EpgSourcesDialog(QDialog):
    def __init__(self, parent, sources, use_provider):
        super().__init__(parent)
        self.setWindowTitle("EPG sources")
        self.setMinimumSize(600, 380)
        lay = QVBoxLayout(self)
        self.provider = QCheckBox("Include the provider's own guide (xmltv.php) - highest priority")
        self.provider.setChecked(use_provider)
        lay.addWidget(self.provider)
        intro = QLabel("Extra XMLTV guides to fill gaps, one per line, either a web address or a file on this "
                       "PC (.xml or .xml.gz). Drag files into the box, or use Add file. Earlier lines win when "
                       "two guides have the same channel ID:")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.text = _SourcesEdit("\n".join(sources))
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        add = QPushButton("Add file...")
        add.clicked.connect(self._add_files)
        row.addWidget(add)
        row.addStretch(1)
        lay.addLayout(row)
        note = QLabel("<i>Web guides are downloaded and local files are read from where they are, so "
                      "replacing a local file updates your guide the next time it's rebuilt. After you press OK "
                      "the guides are scanned, so the table can flag EPG IDs that don't exist anywhere, and "
                      "Auto-fill can suggest matches.</i>")
        note.setWordWrap(True)
        lay.addWidget(note)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("Save && scan guides")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Pick XMLTV guide files", "",
                                                "XMLTV guides (*.xml *.gz *.xml.gz);;All files (*)")
        if paths:
            cur = self.text.toPlainText()
            sep = "" if not cur or cur.endswith("\n") else "\n"
            self.text.setPlainText(cur + sep + "\n".join(paths) + "\n")

    def values(self):
        from core.epg import normalize_source
        out = []
        for line in self.text.toPlainText().splitlines():
            src = normalize_source(line)
            if src and src not in out:
                out.append(src)
        return out, self.provider.isChecked()


class ExportDialog(QDialog):
    def __init__(self, parent, counts, settings, lan_base, can_merge):
        super().__init__(parent)
        self.setWindowTitle("Export playlist")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)

        g = QGroupBox("What to include")
        gl = QVBoxLayout(g)
        self.k_live = QCheckBox(f"Live channels ({counts['live']:,})")
        self.k_vod = QCheckBox(f"Movies ({counts['vod']:,})")
        self.k_series = QCheckBox(f"Series episodes ({counts['series']:,} shows with episodes fetched)")
        for cb, n in ((self.k_live, counts["live"]), (self.k_vod, counts["vod"]), (self.k_series, counts["series"])):
            cb.setChecked(n > 0)
            cb.setEnabled(n > 0)
            gl.addWidget(cb)
        lay.addWidget(g)

        g2 = QGroupBox("Files")
        f2 = QFormLayout(g2)
        self.split = QCheckBox("One file per type (playlist_live.m3u, playlist_movie.m3u, ...)")
        self.prefix = QCheckBox("Prefix group names when combined (e.g. \"Movies | Action\")")
        self.prefix.setChecked(True)
        self.live_ext = QComboBox()
        self.live_ext.addItems(["ts", "m3u8"])
        self.folder = QLineEdit(settings.get("export_dir", ""))
        br = QPushButton("Browse...")
        br.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(br)
        self.base = QLineEdit(settings.get("export_base", "playlist"))
        f2.addRow(self.split)
        f2.addRow(self.prefix)
        f2.addRow("Live stream format:", self.live_ext)
        f2.addRow("Folder:", row)
        f2.addRow("File name:", self.base)
        lay.addWidget(g2)

        g3 = QGroupBox("EPG")
        l3 = QVBoxLayout(g3)
        self.e_provider = QRadioButton("Point the playlist at the provider's guide URL")
        self.e_merge = QRadioButton("Merge provider + my extra guides into a local epg file")
        self.e_none = QRadioButton("No EPG reference in the playlist")
        self.e_provider.setChecked(True)
        self.e_merge.setEnabled(can_merge)
        self.gz = QCheckBox("Compress the merged guide (.xml.gz)")
        self.base_url = QLineEdit(lan_base)
        self.base_url.setPlaceholderText("http://192.168.1.50:8765  (where the files will be served from)")
        l3.addWidget(self.e_provider)
        l3.addWidget(self.e_merge)
        l3.addWidget(self.gz)
        hint = QLabel("Address the merged guide will be hosted at (goes in the playlist header; "
                      "leave blank to add the guide URL in your IPTV app by hand):")
        hint.setWordWrap(True)
        l3.addWidget(hint)
        l3.addWidget(self.base_url)
        l3.addWidget(self.e_none)
        lay.addWidget(g3)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("Export")
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Export folder", self.folder.text())
        if d:
            self.folder.setText(d)

    def _ok(self):
        if not self.folder.text().strip():
            QMessageBox.warning(self, "Pick a folder", "Choose where to save the files.")
            return
        if not (self.k_live.isChecked() or self.k_vod.isChecked() or self.k_series.isChecked()):
            QMessageBox.warning(self, "Nothing selected", "Tick at least one type.")
            return
        self.accept()

    def values(self):
        kinds = [k for k, cb in (("live", self.k_live), ("vod", self.k_vod), ("series", self.k_series))
                 if cb.isChecked()]
        mode = "merge" if self.e_merge.isChecked() else ("none" if self.e_none.isChecked() else "provider")
        return {"kinds": kinds, "split": self.split.isChecked(), "prefix": self.prefix.isChecked(),
                "live_ext": self.live_ext.currentText(), "folder": self.folder.text().strip(),
                "base": self.base.text().strip() or "playlist", "epg_mode": mode,
                "gz": self.gz.isChecked(), "base_url": self.base_url.text().strip().rstrip("/")}


class ServeDialog(QDialog):
    def __init__(self, parent, server, folder, port):
        super().__init__(parent)
        self.server = server
        self.setWindowTitle("Serve on your home network")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Apple TV apps like UHF and OneTV load playlists by URL. This shares a folder "
                             "over your local network while this app is open. Anyone on your network can "
                             "read those files, and the playlist contains your login, so don't use this on "
                             "a network you don't trust."))
        lay.itemAt(0).widget().setWordWrap(True)
        form = QFormLayout()
        self.folder = QLineEdit(folder)
        br = QPushButton("Browse...")
        br.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(br)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(port))
        form.addRow("Folder:", row)
        form.addRow("Port:", self.port)
        lay.addLayout(form)
        self.btn = QPushButton()
        self.btn.clicked.connect(self._toggle)
        lay.addWidget(self.btn)
        self.urls = QPlainTextEdit()
        self.urls.setReadOnly(True)
        lay.addWidget(self.urls)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        close.accepted.connect(self.accept)
        lay.addWidget(close)
        self._update()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Folder to share", self.folder.text())
        if d:
            self.folder.setText(d)

    def _toggle(self):
        if self.server.running:
            self.server.stop()
        else:
            if not os.path.isdir(self.folder.text()):
                QMessageBox.warning(self, "No folder", "That folder doesn't exist.")
                return
            try:
                self.server.start(self.folder.text(), self.port.value())
            except OSError as e:
                QMessageBox.critical(self, "Couldn't start", f"{e}\nTry a different port.")
                return
        self._update()

    def _update(self):
        running = self.server.running
        self.btn.setText("Stop sharing" if running else "Start sharing")
        self.folder.setEnabled(not running)
        self.port.setEnabled(not running)
        if running:
            base = self.server.base_url()
            files = sorted(f for f in os.listdir(self.server.directory)
                           if f.lower().endswith((".m3u", ".m3u8", ".xml", ".gz")))
            self.urls.setPlainText("Sharing! Put these URLs into your IPTV app:\n\n" +
                                   "\n".join(f"{base}/{f}" for f in files) if files else
                                   f"Sharing {self.server.directory}\n{base}/\n\n(no playlist files in that folder yet)")
        else:
            self.urls.setPlainText("Not sharing.")

    def values(self):
        return self.folder.text(), self.port.value()


class EpisodesDialog(QDialog):
    def __init__(self, parent, item):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle(f"Episodes - {item.name}")
        self.setMinimumSize(460, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Untick episodes you don't want in the export:"))
        self.list = QListWidget()
        for e in item.episodes or []:
            label = f"S{int(e['season']):02d}E{int(e['ep']):02d}"
            if e.get("title"):
                label += f" - {e['title']}"
            li = QListWidgetItem(label)
            li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
            li.setCheckState(Qt.Unchecked if e.get("skip") else Qt.Checked)
            self.list.addItem(li)
        lay.addWidget(self.list)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def apply(self):
        changed = False
        for i, e in enumerate(self.item.episodes or []):
            skip = self.list.item(i).checkState() != Qt.Checked
            if bool(e.get("skip")) != skip:
                changed = True
                if skip:
                    e["skip"] = True
                else:
                    e.pop("skip", None)
        return changed


class XtreamServerDialog(QDialog):
    """Start/stop the local Xtream server and show what to type into the IPTV apps."""

    def __init__(self, parent, xs, cfg, start_cb, stop_cb, rebuild_cb):
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QFontDatabase
        from core.webserver import lan_ip
        self.xs, self.start_cb, self.stop_cb, self.rebuild_cb = xs, start_cb, stop_cb, rebuild_cb
        self.ip = lan_ip()
        self.setWindowTitle("Xtream server for your IPTV apps")
        self.setMinimumSize(640, 640)
        lay = QVBoxLayout(self)
        intro = QLabel("Serves your <b>edited</b> list to IPTV apps as if this PC were an Xtream provider: "
                       "Live / Movies / Series with your categories. Pressing play sends the app to your real "
                       "provider. Anyone on your home network who knows the login below can use it, so don't "
                       "expose it to the internet.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(cfg.get("xs_port", 8090)))
        self.user = QLineEdit(cfg.get("xs_user", "local"))
        self.pw = QLineEdit(cfg.get("xs_pass", ""))
        self.mode = QComboBox()
        self.mode.addItem("Send the app straight to the provider (recommended)", "redirect")
        self.mode.addItem("Relay streams through this PC (if an app won't follow redirects)", "proxy")
        self.mode.setCurrentIndex(max(0, self.mode.findData(cfg.get("xs_mode", "redirect"))))
        self.epg = QComboBox()
        self.epg.addItem("Merged guide: provider + my extra guides", "merged")
        self.epg.addItem("The provider's own guide only", "provider")
        self.epg.addItem("No guide", "none")
        self.epg.setCurrentIndex(max(0, self.epg.findData(cfg.get("xs_epg", "merged"))))
        self.hours = QSpinBox()
        self.hours.setRange(1, 72)
        self.hours.setSuffix(" hours")
        self.hours.setValue(int(cfg.get("xs_epg_hours", 12)))
        form.addRow("Port:", self.port)
        form.addRow("Username for the apps:", self.user)
        form.addRow("Password for the apps:", self.pw)
        form.addRow("Playback:", self.mode)
        form.addRow("Guide:", self.epg)
        form.addRow("Refresh guide every:", self.hours)
        lay.addLayout(form)

        self.btn = QPushButton()
        self.btn.clicked.connect(self._toggle)
        lay.addWidget(self.btn)
        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(110)
        lay.addWidget(self.info)
        row = QHBoxLayout()
        self.guide_lbl = QLabel()
        rb = QPushButton("Rebuild guide now")
        rb.clicked.connect(self.rebuild_cb)
        row.addWidget(self.guide_lbl, 1)
        row.addWidget(rb)
        lay.addLayout(row)
        lay.addWidget(QLabel("Recent activity (handy if an app can't connect):"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(self.log, 1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        lay.addWidget(close)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(1500)
        self._update()

    def settings(self):
        return {"xs_port": self.port.value(), "xs_user": self.user.text().strip() or "local",
                "xs_pass": self.pw.text().strip(), "xs_mode": self.mode.currentData(),
                "xs_epg": self.epg.currentData(), "xs_epg_hours": self.hours.value()}

    def _toggle(self):
        if self.xs.running:
            self.stop_cb()
        else:
            if not self.pw.text().strip():
                QMessageBox.warning(self, "Password needed", "Pick any password for your apps to use.")
                return
            err = self.start_cb(self.settings())
            if err:
                QMessageBox.warning(self, "Couldn't start", err)
        self._update()

    def _update(self):
        running = self.xs.running
        self.btn.setText("Stop server" if running else "Start server")
        for w in (self.port, self.user, self.pw, self.mode, self.epg, self.hours):
            w.setEnabled(not running)
        if running:
            self.info.setPlainText(
                "Running. In UHF / OneTV / IPTVnator add an Xtream login:\n\n"
                f"   Server:    {self.xs.base_url()}\n"
                f"   Username:  {self.xs.user}\n"
                f"   Password:  {self.xs.password}")
        else:
            self.info.setPlainText("Not running.")
        self._refresh()

    def _refresh(self):
        self.guide_lbl.setText(f"Guide: {self.xs.epg_status()}" if self.xs.running else "")
        bar = self.log.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.log.setPlainText("\n".join(self.xs.lines))
        if at_end:
            bar.setValue(bar.maximum())

    def done(self, r):
        self.timer.stop()
        super().done(r)


class ListExportDialog(QDialog):
    """Pick what goes into a CSV / TXT list: types, categories, format."""

    def __init__(self, parent, counts):
        """counts: {(kind, category, deleted, fav): number of items} for everything still on the server."""
        super().__init__(parent)
        self.setWindowTitle("Export list to CSV / TXT")
        self.setMinimumSize(520, 580)
        self._counts = counts
        lay = QVBoxLayout(self)
        fm = QFormLayout()
        self.fmt = QComboBox()
        self.fmt.addItem("CSV  (Type, Name, Category - opens in Excel)", "csv")
        self.fmt.addItem("TXT  (names grouped by category)", "txt")
        fm.addRow("Format:", self.fmt)
        lay.addLayout(fm)
        g = QGroupBox("Types")
        gl = QHBoxLayout(g)
        self.kinds = {}
        for k, label in (("live", "Live"), ("vod", "Movies"), ("series", "Series")):
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.toggled.connect(self._refilter)
            self.kinds[k] = cb
            gl.addWidget(cb)
        gl.addSpacing(16)
        self.fav_only = QCheckBox("\u2605 Favorites only")
        self.fav_only.toggled.connect(self._refilter)
        gl.addWidget(self.fav_only)
        gl.addStretch(1)
        lay.addWidget(g)
        self.skip_del = QCheckBox("Leave out items I deleted")
        self.skip_del.setChecked(True)
        self.skip_del.toggled.connect(self._refilter)
        lay.addWidget(self.skip_del)
        self.all_cb = QCheckBox("Everything (all categories shown below)")
        self.all_cb.setChecked(True)
        self.all_cb.toggled.connect(self._all_toggled)
        lay.addWidget(self.all_cb)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter the category list...")
        self.search.textChanged.connect(self._refilter)
        lay.addWidget(self.search)
        self.lst = QListWidget()
        names = {"live": "Live", "vod": "Movies", "series": "Series"}
        order = {"live": 0, "vod": 1, "series": 2}
        for kind, cat in sorted({(k, c) for k, c, _d, _f in counts}, key=lambda t: (order[t[0]], t[1].lower())):
            it = QListWidgetItem()
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, (kind, cat))
            it.setData(Qt.UserRole + 1, f"{names[kind]}  |  {cat}")
            self.lst.addItem(it)
        lay.addWidget(self.lst, 1)
        row = QHBoxLayout()
        for text, state in (("Tick shown", Qt.Checked), ("Untick shown", Qt.Unchecked)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, st=state: self._set_shown(st))
            row.addWidget(b)
        row.addStretch(1)
        self.total = QLabel()
        row.addWidget(self.total)
        lay.addLayout(row)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._all_toggled(True)

    def _count(self, kind, cat):
        skip, fav = self.skip_del.isChecked(), self.fav_only.isChecked()
        return sum(n for (k, c, d, f), n in self._counts.items()
                   if k == kind and c == cat and not (skip and d) and (f or not fav))

    def _refilter(self, *_):
        q = self.search.text().strip().lower()
        everything = self.all_cb.isChecked()
        shown_total = 0
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            kind, cat = it.data(Qt.UserRole)
            n = self._count(kind, cat)
            it.setText(f"{it.data(Qt.UserRole + 1)}  ({n:,})")
            ok = n > 0 and self.kinds[kind].isChecked() and (not q or q in cat.lower())
            it.setHidden(not ok)
            if self.kinds[kind].isChecked() and (everything or it.checkState() == Qt.Checked):
                shown_total += n
        self.total.setText(f"{shown_total:,} items will be exported")

    def _all_toggled(self, on):
        self.lst.setEnabled(not on)
        self.search.setEnabled(not on)
        self._refilter()

    def _set_shown(self, state):
        for i in range(self.lst.count()):
            it = self.lst.item(i)
            if not it.isHidden():
                it.setCheckState(state)
        self._refilter()

    def values(self):
        kinds = tuple(k for k, cb in self.kinds.items() if cb.isChecked())
        cats = None
        if not self.all_cb.isChecked():
            cats = {self.lst.item(i).data(Qt.UserRole) for i in range(self.lst.count())
                    if self.lst.item(i).checkState() == Qt.Checked}
        return {"fmt": self.fmt.currentData(), "kinds": kinds, "categories": cats,
                "skip_deleted": self.skip_del.isChecked(), "fav_only": self.fav_only.isChecked()}

ALREADY = "Already \u2605"


class ImportFavoritesDialog(QDialog):
    """Imported names on the left, best matches from your list on the right; tick what to star."""
    STATUS_COLOR = {"Good": "#43a047", "Check": "#e69500", "No match": "#9e9e9e", ALREADY: "#42a5f5"}

    def __init__(self, parent, lines, items, on_add):
        """lines: imported names. items: every active item. on_add(list_of_items) stars them (returns count)."""
        super().__init__(parent)
        self.setWindowTitle("Import list for Favorites")
        self.resize(1180, 680)
        self.lines, self.items, self.on_add = lines, list(items), on_add
        self.queries = list(lines)                  # what each line is currently searched as
        self.results = [None] * len(lines)          # [(score, item)] per line, filled in as needed
        self.checked = [set() for _ in lines]       # item keys ticked per line
        self._idx = {}
        self.cur = -1
        self._busy = False

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.more = QCheckBox("Also search Movies and Series")
        self.more.toggled.connect(self._scope_changed)
        top.addWidget(self.more)
        top.addSpacing(18)
        top.addWidget(QLabel("Show lines:"))
        self.flt = QComboBox()
        for label, key in (("All", "all"), ("Not added yet", "todo"), ("Good matches", "Good"),
                           ("Needs a look", "Check"), ("No match", "No match"), ("Already in favorites", ALREADY)):
            self.flt.addItem(label, key)
        self.flt.currentIndexChanged.connect(self._apply_filter)
        top.addWidget(self.flt)
        top.addStretch(1)
        self.summary = QLabel()
        top.addWidget(self.summary)
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        lw = QWidget()
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("<b>Your imported list</b>"))
        self.left = QTableWidget(len(lines), 3)
        self.left.setHorizontalHeaderLabels(["Imported name", "Status", "Ticked"])
        self.left.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.left.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.left.setSelectionMode(QAbstractItemView.SingleSelection)
        self.left.verticalHeader().setVisible(False)
        self.left.verticalHeader().setDefaultSectionSize(24)
        self.left.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.left.setColumnWidth(1, 90)
        self.left.setColumnWidth(2, 54)
        self.left.currentCellChanged.connect(lambda r, *_: self._show_line(r))
        ll.addWidget(self.left)
        split.addWidget(lw)

        rw = QWidget()
        rl = QVBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        sr = QHBoxLayout()
        sr.addWidget(QLabel("<b>Matches for:</b>"))
        self.q = QLineEdit()
        self.q.setPlaceholderText("Retype the name here if the best try missed, then press Enter")
        self.q.returnPressed.connect(self._research)
        sr.addWidget(self.q, 1)
        b = QPushButton("Search")
        b.clicked.connect(self._research)
        sr.addWidget(b)
        rl.addLayout(sr)
        self.right = QTableWidget(0, 5)
        self.right.setHorizontalHeaderLabels(["Add", "Name in your list", "Category", "Type", "Match"])
        self.right.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.right.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.right.verticalHeader().setVisible(False)
        self.right.verticalHeader().setDefaultSectionSize(24)
        self.right.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for c, w in ((0, 46), (2, 200), (3, 62), (4, 62)):
            self.right.setColumnWidth(c, w)
        self.right.itemChanged.connect(self._ticked)
        rl.addWidget(self.right, 1)
        rb = QHBoxLayout()
        for text, st in (("Tick all shown", Qt.Checked), ("Untick all shown", Qt.Unchecked)):
            bb = QPushButton(text)
            bb.clicked.connect(lambda _=False, s=st: self._set_all_shown(s))
            rb.addWidget(bb)
        rb.addStretch(1)
        rl.addLayout(rb)
        split.addWidget(rw)
        split.setSizes([430, 750])
        lay.addWidget(split, 1)

        bot = QHBoxLayout()
        self.b_auto = QPushButton("Tick all good matches")
        self.b_auto.setToolTip("Ticks every near-exact match (and East/West/HD flavors) on every line. "
                               "Nothing is added until you press the Add button, so you can review first.")
        self.b_auto.clicked.connect(self._tick_good)
        self.b_clear = QPushButton("Untick everything")
        self.b_clear.clicked.connect(self._untick_all)
        bot.addWidget(self.b_auto)
        bot.addWidget(self.b_clear)
        bot.addStretch(1)
        self.b_add = QPushButton()
        self.b_add.setDefault(False)
        self.b_add.clicked.connect(self._add)
        bot.addWidget(self.b_add)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bot.addWidget(close)
        lay.addLayout(bot)

        self._compute_all()
        self._refresh_left()
        self._apply_filter()
        if lines:
            self.left.selectRow(0)
        self._update_counts()

    # ---- matching -------------------------------------------------------
    def _index(self):
        key = self.more.isChecked()
        if key not in self._idx:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                pool = self.items if key else [i for i in self.items if i.kind == "live"]
                self._idx[key] = matcher.NameIndex(pool)
            finally:
                QApplication.restoreOverrideCursor()
        return self._idx[key]

    def _compute_all(self):
        idx = self._index()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, q in enumerate(self.queries):
                self.results[i] = idx.search(q)
        finally:
            QApplication.restoreOverrideCursor()

    def _scope_changed(self, _on):
        self.checked = [set() for _ in self.lines]
        self._compute_all()
        self._refresh_left()
        self._show_line(self.cur, force=True)
        self._apply_filter()
        self._update_counts()

    def status(self, i):
        res = self.results[i] or []
        if any(it.fav and s >= matcher.TICK for s, it in res):
            return ALREADY
        best = res[0][0] if res else 0.0
        return "Good" if best >= matcher.GOOD else "Check" if best >= 0.6 else "No match"

    # ---- left list ------------------------------------------------------------
    def _refresh_left(self, only=None):
        rows = range(len(self.lines)) if only is None else [only]
        self.left.blockSignals(True)
        for i in rows:
            st = self.status(i)
            vals = [self.lines[i] + ("" if self.queries[i] == self.lines[i] else f"   (searched: {self.queries[i]})"),
                    st, str(len(self.checked[i])) if self.checked[i] else ""]
            for c, v in enumerate(vals):
                it = self.left.item(i, c)
                if it is None:
                    it = QTableWidgetItem()
                    self.left.setItem(i, c, it)
                it.setText(v)
                if c == 1:
                    it.setForeground(QBrush(QColor(self.STATUS_COLOR[st])))
        self.left.blockSignals(False)

    def _apply_filter(self, *_):
        key = self.flt.currentData()
        for i in range(len(self.lines)):
            st = self.status(i)
            if key == "all":
                hide = False
            elif key == "todo":
                hide = st == ALREADY or st == "No match" and not self.checked[i]
            else:
                hide = st != key
            self.left.setRowHidden(i, hide)

    # ---- right list -----------------------------------------------------------------
    def _show_line(self, row, force=False):
        if row < 0 or (row == self.cur and not force):
            return
        self.cur = row
        self.q.setText(self.queries[row])
        res = self.results[row] or []
        self._busy = True
        self.right.setRowCount(len(res))
        for r, (sc, it) in enumerate(res):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if it.key in self.checked[row] else Qt.Unchecked)
            chk.setData(Qt.UserRole, it.key)
            self.right.setItem(r, 0, chk)
            name = QTableWidgetItem(("\u2605 " if it.fav else "") + it.name)
            for c, v in ((1, name), (2, QTableWidgetItem(it.category)), (3, QTableWidgetItem(KIND_LABEL[it.kind])),
                         (4, QTableWidgetItem(f"{int(round(sc * 100))}%"))):
                v.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.right.setItem(r, c, v)
            if it.fav:
                chk.setFlags(Qt.ItemIsEnabled)             # already a favorite: nothing to add
        self._busy = False

    def _research(self):
        if self.cur < 0:
            return
        text = self.q.text().strip()
        if not text:
            return
        self.queries[self.cur] = text
        self.results[self.cur] = self._index().search(text)
        self.checked[self.cur] = set()
        self._refresh_left(self.cur)
        self._show_line(self.cur, force=True)
        self._update_counts()

    def _ticked(self, item):
        if self._busy or item.column() != 0 or self.cur < 0:
            return
        key = item.data(Qt.UserRole)
        (self.checked[self.cur].add if item.checkState() == Qt.Checked else self.checked[self.cur].discard)(key)
        self._refresh_left(self.cur)
        self._update_counts()

    def _set_all_shown(self, state):
        self._busy = True
        for r in range(self.right.rowCount()):
            c = self.right.item(r, 0)
            if c.flags() & Qt.ItemIsUserCheckable:
                c.setCheckState(state)
                (self.checked[self.cur].add if state == Qt.Checked else self.checked[self.cur].discard)(c.data(Qt.UserRole))
        self._busy = False
        self._refresh_left(self.cur)
        self._update_counts()

    # ---- bulk actions -------------------------------------------------------------------
    def _tick_good(self):
        for i, res in enumerate(self.results):
            if res and res[0][0] >= matcher.GOOD:
                self.checked[i] |= {it.key for s, it in res if s >= matcher.TICK and not it.fav}
        self._refresh_left()
        self._show_line(self.cur, force=True)
        self._apply_filter()
        self._update_counts()

    def _untick_all(self):
        self.checked = [set() for _ in self.lines]
        self._refresh_left()
        self._show_line(self.cur, force=True)
        self._apply_filter()
        self._update_counts()

    def _all_ticked_keys(self):
        keys = set()
        for s in self.checked:
            keys |= s
        return keys

    def _update_counts(self):
        n = len(self._all_ticked_keys())
        self.b_add.setText(f"Add {n:,} checked to Favorites")
        self.b_add.setEnabled(n > 0)
        sts = [self.status(i) for i in range(len(self.lines))]
        self.summary.setText(f"{len(self.lines):,} lines: {sts.count('Good'):,} good, {sts.count('Check'):,} to check, "
                             f"{sts.count('No match'):,} no match, {sts.count(ALREADY):,} already starred")

    def _add(self):
        keys = self._all_ticked_keys()
        by_key = {it.key: it for it in self.items}
        todo = [by_key[k] for k in keys if k in by_key and not by_key[k].fav]
        if not todo:
            return
        self.on_add(todo)
        self.checked = [set() for _ in self.lines]
        self._refresh_left()
        self._show_line(self.cur, force=True)
        self._apply_filter()
        self._update_counts()
        self.added = getattr(self, "added", 0) + len(todo)


# ---- help & about ----------------------------------------------------------
HELP_FILE = Path(__file__).resolve().parent.parent / "help" / "help.md"


def help_sections():
    """Split the help file into [(title, markdown)] on its '## ' headings; the intro comes first."""
    try:
        text = HELP_FILE.read_text(encoding="utf-8")
    except OSError:
        return [("Help", "# Help\n\nThe help file (help/help.md) wasn't found next to the program.")]
    out, title, buf = [], None, []
    for line in text.splitlines():
        if line.startswith("## ") or (title is None and line.startswith("# ")):
            if title is not None:
                out.append((title, "\n".join(buf)))
            title, buf = line.lstrip("# ").strip(), [line if line.startswith("## ") else line]
        else:
            buf.append(line)
    if title is not None:
        out.append((title, "\n".join(buf)))
    return out


class HelpDialog(QDialog):
    """Non-modal help window: contents on the left, text on the right, search on top.
    Enter / F3 jump to the next match (across sections), Shift+F3 to the previous one, Esc closes."""

    def __init__(self, parent=None, topic=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} - Help")
        self.resize(980, 680)
        self.sections = help_sections()
        self.plain = []                       # rendered text of each section, lowercase, for counting matches
        for _, body in self.sections:
            d = QTextDocument()
            d.setMarkdown(body)
            self.plain.append(d.toPlainText().lower())
        self._from_end = False
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the help (Enter = next match)...")
        self.search.setClearButtonEnabled(True)
        top.addWidget(self.search, 1)
        self.prev_btn = QPushButton("Previous")
        self.next_btn = QPushButton("Next")
        for b in (self.prev_btn, self.next_btn):
            b.setAutoDefault(False)
            b.setEnabled(False)
            top.addWidget(b)
        lay.addLayout(top)
        split = QSplitter()
        self.toc = QListWidget()
        self.toc.setMaximumWidth(260)
        for title, _ in self.sections:
            self.toc.addItem(title)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        split.addWidget(self.toc)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        self.hits = QLabel("")
        row.addWidget(self.hits, 1)
        close = QPushButton("Close")
        close.setAutoDefault(False)           # so Enter in the search box never closes the window
        close.setDefault(False)
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.toc.currentRowChanged.connect(self.show_section)
        self.search.textChanged.connect(self.filter)
        self.search.returnPressed.connect(lambda: self.find_next())
        self.next_btn.clicked.connect(lambda: self.find_next())
        self.prev_btn.clicked.connect(lambda: self.find_next(backwards=True))
        QShortcut(QKeySequence("F3"), self, activated=lambda: self.find_next())
        QShortcut(QKeySequence("Shift+F3"), self, activated=lambda: self.find_next(backwards=True))
        self.toc.setCurrentRow(0)
        if topic:
            self.goto(topic)

    def goto(self, title):
        for i, (t, _) in enumerate(self.sections):
            if t.lower() == title.lower():
                self.search.clear()
                self.toc.setCurrentRow(i)
                return

    def _query(self):
        return self.search.text().strip()

    def _highlight(self, q):
        sels = []
        doc = self.view.document()
        cur = doc.find(q)
        while not cur.isNull():
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cur
            sel.format.setBackground(QColor(255, 226, 90))
            sel.format.setForeground(QColor(0, 0, 0))
            sels.append(sel)
            cur = doc.find(q, cur)
        self.view.setExtraSelections(sels)

    def show_section(self, row):
        if not 0 <= row < len(self.sections):
            return
        self.view.setMarkdown(self.sections[row][1])
        q = self._query()
        self.view.setExtraSelections([])
        if q:
            self._highlight(q)
            if self._from_end:
                self.view.moveCursor(QTextCursor.End)
                self.view.find(q, QTextDocument.FindBackward)
            else:
                self.view.moveCursor(QTextCursor.Start)
                self.view.find(q)
        else:
            self.view.moveCursor(QTextCursor.Start)
        self._from_end = False

    def find_next(self, backwards=False):
        """Next/previous match; when the current section has no more, carry on in the next matching section."""
        q = self._query()
        if not q:
            return
        flags = QTextDocument.FindBackward if backwards else QTextDocument.FindFlag(0)
        if self.view.find(q, flags):
            return
        visible = [i for i in range(len(self.sections)) if not self.toc.item(i).isHidden()]
        if not visible:
            return
        cur = self.toc.currentRow()
        if backwards:
            idx = max((i for i in visible if i < cur), default=visible[-1])
        else:
            idx = min((i for i in visible if i > cur), default=visible[0])
        self._from_end = backwards
        if idx == cur:
            self.show_section(cur)
        else:
            self.toc.setCurrentRow(idx)

    def filter(self, text):
        q = text.strip().lower()
        first, shown, total = -1, 0, 0
        for i, (title, _) in enumerate(self.sections):
            n = self.plain[i].count(q) if q else 0
            ok = not q or n > 0
            self.toc.item(i).setHidden(not ok)
            if ok:
                shown += 1
                total += n
                if first < 0:
                    first = i
        if q:
            self.hits.setText(f"{total} match{'es' if total != 1 else ''} in {shown} of {len(self.sections)} sections"
                              if total else "No matches")
        else:
            self.hits.setText("")
        self.prev_btn.setEnabled(bool(q) and total > 0)
        self.next_btn.setEnabled(bool(q) and total > 0)
        if first >= 0:
            if self.toc.item(self.toc.currentRow()).isHidden():
                self.toc.setCurrentRow(first)
            else:
                self.show_section(self.toc.currentRow())


def about_text():
    return (f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            "<p>Fetch an Xtream Codes IPTV account, tidy it up, and serve or export your edited list "
            "to IPTVnator, UHF, OneTV and friends.</p>"
            "<p>There are no logins or provider details built in. Everything you enter is stored on this "
            f"PC, in <code>{APP_DIR}</code> and in the project files you save.</p>"
            "<p>Use it only with accounts and content you have the right to access. "
            "See <b>Help &gt; Disclaimer and terms of use</b> for the full text.</p>"
            "<p>Press F1 for the help.</p>")


# ---- category manager ------------------------------------------------------
class CategoryManagerDialog(QDialog):
    """Every category in one table. Type new names (or use the case buttons), then Apply."""
    KINDS = (("All types", None), ("Live", "live"), ("Movies", "vod"), ("Series", "series"))
    YELLOW = QColor(255, 215, 0, 70)

    def __init__(self, parent, lib, prefs, on_apply, on_prefs):
        super().__init__(parent)
        self.setWindowTitle("Category manager")
        self.resize(900, 640)
        self.lib, self.on_apply, self.on_prefs = lib, on_apply, on_prefs
        self.prefs = dict(prefs)          # {'std_on': bool, 'std': str, 'extra': str}
        self.rows = []                    # dicts: kind, cat, items, deleted, new
        self.sort_col, self.sort_desc = 1, False
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter categories...")
        self.search.setClearButtonEnabled(True)
        self.kind = QComboBox()
        for label, key in self.KINDS:
            self.kind.addItem(label, key)
        self.hide_dead = QCheckBox("Hide fully deleted categories")
        top.addWidget(self.search, 1)
        top.addWidget(self.kind)
        top.addWidget(self.hide_dead)
        lay.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Type", "Current name", "New name (double-click to edit)", "Items", "Deleted"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionsClickable(True)
        hh.sectionClicked.connect(self.sort_by)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Tidy up the New name column:"))
        for text, fn in (("Proper Case", self.do_proper), ("UPPERCASE", lambda: self.do_case(str.upper)),
                         ("lowercase", lambda: self.do_case(str.lower)), ("Reset", self.do_reset)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            tools.addWidget(b)
        tools.addStretch(1)
        lay.addLayout(tools)
        tip = QLabel("These buttons work on the selected rows, or on every row shown if none are selected. "
                     "Nothing changes in your list until you press Apply.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        std = QHBoxLayout()
        self.std_on = QCheckBox("Keep my standard acronyms uppercase (ESPN, NFL, HBO, ...)")
        self.std_on.setChecked(bool(self.prefs.get("std_on", True)))
        self.std_on.toggled.connect(self.prefs_changed)
        std_btn = QPushButton("Edit standard list...")
        std_btn.clicked.connect(self.edit_standard)
        std.addWidget(self.std_on)
        std.addWidget(std_btn)
        std.addStretch(1)
        lay.addLayout(std)
        ex = QHBoxLayout()
        ex.addWidget(QLabel("Plus these extra words (commas):"))
        self.extra = QLineEdit(self.prefs.get("extra", ""))
        self.extra.setPlaceholderText("e.g. DAZN, TSN")
        ex.addWidget(self.extra, 1)
        lay.addLayout(ex)

        bottom = QHBoxLayout()
        self.summary = QLabel("")
        bottom.addWidget(self.summary, 1)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self.apply)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(self.apply_btn)
        bottom.addWidget(close)
        lay.addLayout(bottom)

        self.load_rows()
        self.search.textChanged.connect(self.fill)
        self.kind.currentIndexChanged.connect(self.fill)
        self.hide_dead.toggled.connect(self.fill)
        self.table.itemChanged.connect(self.cell_edited)
        self.extra.editingFinished.connect(self.prefs_changed)

    # ---- data ---------------------------------------------------------
    def load_rows(self):
        counts = {}
        for it in self.lib.items:
            c = counts.setdefault((it.kind, it.category), [0, 0])
            c[1 if it.deleted else 0] += 1
        self.rows = [{"kind": k, "cat": c, "items": a + d, "deleted": d, "new": c}
                     for (k, c), (a, d) in counts.items()]
        self.fill()

    def visible(self):
        q = self.search.text().strip().lower().split()
        kind = self.kind.currentData()
        out = []
        for i, r in enumerate(self.rows):
            if kind and r["kind"] != kind:
                continue
            if self.hide_dead.isChecked() and r["deleted"] >= r["items"]:
                continue
            hay = (r["cat"] + " " + r["new"]).lower()
            if q and not all(w in hay for w in q):
                continue
            out.append(i)
        keys = {0: lambda r: KIND_LABEL[r["kind"]], 1: lambda r: r["cat"].lower(), 2: lambda r: r["new"].lower(),
                3: lambda r: r["items"], 4: lambda r: r["deleted"]}
        out.sort(key=lambda i: (keys[self.sort_col](self.rows[i]), self.rows[i]["cat"].lower()), reverse=self.sort_desc)
        return out

    def sort_by(self, col):
        self.sort_desc = (not self.sort_desc) if col == self.sort_col else (col in (3, 4))
        self.sort_col = col
        self.fill()

    def fill(self, *_):
        self.table.blockSignals(True)
        idx = self.visible()
        self.table.setRowCount(len(idx))
        for row, i in enumerate(idx):
            r = self.rows[i]
            cells = [KIND_LABEL[r["kind"]], r["cat"], r["new"], f"{r['items']:,}", f"{r['deleted']:,}"]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
                if col == 2:
                    flags |= Qt.ItemIsEditable
                if col >= 3:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it.setFlags(flags)
                if col == 0:
                    it.setData(Qt.UserRole, i)
                if r["new"] != r["cat"]:
                    it.setBackground(QBrush(self.YELLOW))
                self.table.setItem(row, col, it)
        self.table.blockSignals(False)
        self.update_summary()

    def cell_edited(self, cell):
        if cell.column() != 2:
            return
        i = self.table.item(cell.row(), 0).data(Qt.UserRole)
        self.rows[i]["new"] = cell.text().strip() or self.rows[i]["cat"]
        self.fill()

    # ---- tools --------------------------------------------------------
    def targets(self):
        sel = {self.table.item(ix.row(), 0).data(Qt.UserRole) for ix in self.table.selectionModel().selectedRows()}
        return sel or {self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount())}

    def do_case(self, fn):
        for i in self.targets():
            self.rows[i]["new"] = fn(self.rows[i]["new"])
        self.fill()

    def words(self):
        from core.casing import parse_extra
        words = parse_extra(self.extra.text())
        if self.std_on.isChecked():
            words |= parse_extra(self.prefs.get("std", ""))
        return words

    def prefs_changed(self, *_):
        self.prefs.update(std_on=self.std_on.isChecked(), extra=self.extra.text())
        self.on_prefs(dict(self.prefs))

    def edit_standard(self):
        from core.casing import DEFAULT_STANDARD
        d = QDialog(self)
        d.setWindowTitle("Standard acronyms")
        d.resize(520, 300)
        v = QVBoxLayout(d)
        v.addWidget(QLabel("Words that Proper Case always writes in uppercase. Separate with commas, spaces or new lines."))
        box = QPlainTextEdit(self.prefs.get("std", ""))
        v.addWidget(box, 1)
        row = QHBoxLayout()
        reset = QPushButton("Reset to default")
        reset.clicked.connect(lambda: box.setPlainText(DEFAULT_STANDARD))
        row.addWidget(reset)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        row.addWidget(bb)
        v.addLayout(row)
        if d.exec():
            self.prefs["std"] = ", ".join(w for w in box.toPlainText().replace("\n", ",").replace(",", " ").split())
            self.prefs_changed()

    def do_proper(self):
        from core.casing import proper_case
        self.prefs_changed()
        extra = self.words()
        for i in self.targets():
            self.rows[i]["new"] = proper_case(self.rows[i]["new"], extra)
        self.fill()

    def do_reset(self):
        for i in self.targets():
            self.rows[i]["new"] = self.rows[i]["cat"]
        self.fill()

    # ---- apply --------------------------------------------------------
    def plan(self):
        """(renames, merges): rows that change, and how many of those land on a name that already exists."""
        changed = [r for r in self.rows if r["new"] != r["cat"]]
        names = {}
        for r in self.rows:
            names.setdefault((r["kind"], r["new"]), []).append(r)
        merges = sum(1 for r in changed if len(names[(r["kind"], r["new"])]) > 1)
        return changed, merges

    def update_summary(self):
        changed, merges = self.plan()
        total = len(self.rows)
        if changed:
            self.summary.setText(f"{len(changed)} categor{'y' if len(changed) == 1 else 'ies'} to rename"
                                 + (f", {merges} of them merging into another" if merges else "")
                                 + f"   ({total} categories in all)")
        else:
            self.summary.setText(f"{total} categories. No changes pending.")
        self.apply_btn.setEnabled(bool(changed))

    def apply(self):
        changed, _ = self.plan()
        if not changed:
            return
        self.on_apply({(r["kind"], r["cat"]): r["new"] for r in changed})
        self.load_rows()


class TermsDialog(QDialog):
    """First-run disclaimer: Agree continues, Decline closes the app."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.terms import TERMS_TEXT, TERMS_TITLE
        self.setWindowTitle(f"{APP_NAME} - {TERMS_TITLE}")
        self.resize(640, 480)
        lay = QVBoxLayout(self)
        box = QTextBrowser()
        box.setPlainText(TERMS_TEXT)
        lay.addWidget(box, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        no = QPushButton("Decline and quit")
        no.clicked.connect(self.reject)
        yes = QPushButton("I agree")
        yes.setDefault(True)
        yes.clicked.connect(self.accept)
        row.addWidget(no)
        row.addWidget(yes)
        lay.addLayout(row)


class SortDialog(QDialog):
    """Pick what to sort A-Z: which types, how, and all categories or just the ones selected in the sidebar."""

    def __init__(self, parent, selected_cats, default_kinds=("live",)):
        super().__init__(parent)
        self.setWindowTitle("Sort A-Z")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Nothing is renamed or moved to another category. You can undo it."))
        box = QGroupBox("Sort which types")
        bl = QVBoxLayout(box)
        self.kind_boxes = {}
        for kind, label in (("live", "Live"), ("vod", "Movies"), ("series", "Series")):
            cb = QCheckBox(label)
            cb.setChecked(kind in default_kinds)
            self.kind_boxes[kind] = cb
            bl.addWidget(cb)
        lay.addWidget(box)
        box2 = QGroupBox("How")
        hl = QVBoxLayout(box2)
        self.cat_rb = QRadioButton("Within each category (categories keep their place)")
        self.all_list_rb = QRadioButton("One big A-Z list (everything together, no matter the category)")
        self.cat_rb.setChecked(True)
        hl.addWidget(self.cat_rb)
        hl.addWidget(self.all_list_rb)
        lay.addWidget(box2)
        box3 = QGroupBox("Which categories")
        sl = QVBoxLayout(box3)
        self.all_rb = QRadioButton("All categories")
        self.sel_rb = QRadioButton(f"Only the {len(selected_cats)} category(ies) selected in the sidebar")
        self.all_rb.setChecked(True)
        self.sel_rb.setEnabled(bool(selected_cats))
        sl.addWidget(self.all_rb)
        sl.addWidget(self.sel_rb)
        lay.addWidget(box3)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Sort")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def kinds(self):
        return [k for k, cb in self.kind_boxes.items() if cb.isChecked()]

    def only_selected(self):
        return self.sel_rb.isChecked()

    def mode(self):
        return "all" if self.all_list_rb.isChecked() else "category"
