"""Dialogs: connect, find/replace, export, EPG sources, LAN server, episodes."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QTextEdit, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from core import matcher
from core.common import APP_DIR, APP_NAME, APP_VERSION
from core.models import KIND_LABEL, Library
from core.xtream import DEFAULT_UA, parse_link


class ConnectDialog(QDialog):
    def __init__(self, parent, conn, title="Connect to Xtream server", ok_text="Fetch channels", note=""):
        super().__init__(parent)
        self.setWindowTitle(title)
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
        if note:
            top = QLabel(note)
            top.setWordWrap(True)
            form.insertRow(0, top)
        hint = QLabel("Some providers block unknown clients. If login fails with a 403, "
                      "try another User-Agent (for example the name of the app you normally use).")
        hint.setWordWrap(True)
        form.addRow(hint)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText(ok_text)
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
        self.fill = QCheckBox("Fill channels that have no guide data with a placeholder (the channel's name)")
        self.fill.setToolTip("Channels with no EPG ID, or whose ID isn't in any of your guides, get a made-up show "
                             "named after the channel (3-hour blocks, next 3 days), and the playlist gives them a "
                             "guide ID so players can line them up. Needs the merged guide.")
        self.fill.setEnabled(False)
        self.e_merge.toggled.connect(lambda on: self.fill.setEnabled(bool(on) and can_merge))
        self.base_url = QLineEdit(lan_base)
        self.base_url.setPlaceholderText("http://192.168.1.50:8765  (where the files will be served from)")
        l3.addWidget(self.e_provider)
        l3.addWidget(self.e_merge)
        l3.addWidget(self.gz)
        l3.addWidget(self.fill)
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
                "gz": self.gz.isChecked(), "base_url": self.base_url.text().strip().rstrip("/"),
                "placeholders": self.fill.isChecked() and mode == "merge" and "live" in kinds}


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
        self.fill = QCheckBox("Fill channels that have no guide data with a placeholder (the channel's name)")
        self.fill.setToolTip("Channels with no EPG ID, or whose ID isn't in any of your guides, get a made-up "
                             "show named after the channel (in 3-hour blocks for the next 3 days) so your app's "
                             "guide isn't blank. Only works with the merged guide. Takes effect the next time "
                             "the server starts.")
        self.fill.setChecked(bool(cfg.get("xs_placeholders", False)))
        self.epg.currentIndexChanged.connect(lambda *_: self.fill.setEnabled(self.epg.currentData() == "merged"))
        self.fill.setEnabled(self.epg.currentData() == "merged")
        form.addRow("Port:", self.port)
        form.addRow("Username for the apps:", self.user)
        form.addRow("Password for the apps:", self.pw)
        form.addRow("Playback:", self.mode)
        form.addRow("Guide:", self.epg)
        form.addRow("Refresh guide every:", self.hours)
        form.addRow("", self.fill)
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
                "xs_epg": self.epg.currentData(), "xs_epg_hours": self.hours.value(),
                "xs_placeholders": self.fill.isChecked() and self.epg.currentData() == "merged"}

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
def edit_standard_list(parent, current):
    """The 'Standard acronyms' editor. -> the new list as 'A, B, C', or None if cancelled."""
    from core.casing import DEFAULT_STANDARD
    d = QDialog(parent)
    d.setWindowTitle("Standard acronyms")
    d.resize(520, 300)
    v = QVBoxLayout(d)
    v.addWidget(QLabel("Words that Proper Case always writes in uppercase. Separate with commas, spaces or new lines."))
    box = QPlainTextEdit(current)
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
        return ", ".join(w for w in box.toPlainText().replace("\n", ",").replace(",", " ").split())
    return None


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
        text = edit_standard_list(self, self.prefs.get("std", ""))
        if text is not None:
            self.prefs["std"] = text
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


# ---- name manager ----------------------------------------------------------
class NameManagerDialog(QDialog):
    """Bulk tidy-ups for item names: pick what to do and to which items, preview, then Apply."""
    MAX_ROWS = 2000
    YELLOW = QColor(255, 215, 0, 70)
    TYPES = (("All types", "all"), ("Live", "live"), ("Movies", "vod"), ("Series", "series"))
    SCOPES = (("All items", "all"), ("Items selected in the main list", "selected"),
              ("Items in the category selected in the sidebar", "category"))

    def __init__(self, parent, lib, prefs, on_prefs, on_apply, ask, on_ask, on_undo, get_selected, get_category_items):
        super().__init__(parent)
        from core import names
        self.N = names
        self.setWindowTitle("Name manager")
        self.resize(1000, 680)
        self.lib, self.on_prefs, self.on_apply, self.on_ask, self.on_undo = lib, on_prefs, on_apply, on_ask, on_undo
        self.get_selected, self.get_category_items = get_selected, get_category_items
        self.prefs = dict(prefs)
        self.changed = []
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Change the names of:"))
        self.kind = QComboBox()
        for label, key in self.TYPES:
            self.kind.addItem(label, key)
        self.scope = QComboBox()
        for label, key in self.SCOPES:
            self.scope.addItem(label, key)
        row.addWidget(self.kind)
        row.addWidget(self.scope)
        row.addStretch(1)
        lay.addLayout(row)

        box = QGroupBox("What to do")
        form = QFormLayout(box)
        self.op = QComboBox()
        self.fill_ops()
        self.tag_box = QGroupBox("Source tags (what goes between the brackets)")
        self.tag_form = QFormLayout(self.tag_box)
        self.tag_edits = []
        self.f_prefix = QLineEdit()
        self.f_prefix.setPlaceholderText("e.g.  US |   (removed from the start of each name)")
        self.f_find = QLineEdit()
        self.f_find.setPlaceholderText("text to find")
        self.f_repl = QLineEdit()
        self.f_repl.setPlaceholderText("replace with (empty removes it)")
        self.f_case = QCheckBox("Ignore upper/lower case when finding")
        self.f_case.setChecked(True)
        form.addRow("Action:", self.op)
        form.addRow("Prefix:", self.f_prefix)
        form.addRow("Find:", self.f_find)
        form.addRow("Replace with:", self.f_repl)
        form.addRow("", self.f_case)
        lay.addWidget(box)
        lay.addWidget(self.tag_box)

        std = QHBoxLayout()
        self.std_on = QCheckBox("Keep my standard acronyms uppercase (ESPN, NFL, HBO, ...)")
        self.std_on.setChecked(bool(self.prefs.get("std_on", True)))
        std_btn = QPushButton("Edit standard list...")
        std_btn.setAutoDefault(False)
        std_btn.clicked.connect(self.edit_standard)
        std.addWidget(self.std_on)
        std.addWidget(std_btn)
        std.addWidget(QLabel("Plus these extra words:"))
        self.extra = QLineEdit(self.prefs.get("extra", ""))
        self.extra.setPlaceholderText("e.g. DAZN, TSN")
        std.addWidget(self.extra, 1)
        self.acr_row = [self.std_on, std_btn, self.extra]
        lay.addLayout(std)

        pv = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setAutoDefault(False)
        self.preview_btn.clicked.connect(self.preview)
        pv.addWidget(self.preview_btn)
        self.counts = QLabel("")
        pv.addWidget(self.counts, 1)
        lay.addLayout(pv)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Type", "Name now", "Name after", "Category"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for col, w in enumerate((70, 380, 380)):
            self.table.setColumnWidth(col, w)
        lay.addWidget(self.table, 1)

        self.ask_box = QCheckBox("Ask before applying")
        self.ask_box.setChecked(bool(ask))
        self.ask_box.toggled.connect(lambda on: self.on_ask(on) if self.on_ask else None)
        lay.addWidget(self.ask_box)
        bottom = QHBoxLayout()
        self.summary = QLabel("Preview shows exactly what would change. Nothing changes until you press Apply.")
        bottom.addWidget(self.summary, 1)
        self.undo_btn = QPushButton("Undo last action")
        self.undo_btn.setAutoDefault(False)
        self.undo_btn.clicked.connect(self.undo_last)
        QShortcut(QKeySequence.Undo, self, activated=self.undo_last)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setAutoDefault(False)
        self.apply_btn.clicked.connect(self.apply)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        for b in (self.undo_btn, self.apply_btn, close):
            bottom.addWidget(b)
        lay.addLayout(bottom)

        self.build_tags()
        self.op.currentIndexChanged.connect(self.op_changed)
        for w in (self.kind, self.scope):
            w.currentIndexChanged.connect(self.stale)
        for w in (self.f_prefix, self.f_find, self.f_repl):
            w.textEdited.connect(self.stale)
        self.f_case.toggled.connect(self.stale)
        self.std_on.toggled.connect(self.prefs_changed)
        self.extra.textEdited.connect(self.prefs_changed)
        self.op_changed()
        self.update_undo()
        self.apply_btn.setEnabled(False)

    # ---- form -----------------------------------------------------------
    def fill_ops(self):
        """The source-tag actions only make sense for a master list."""
        keep = self.op.currentData()
        self.op.blockSignals(True)
        self.op.clear()
        for label, key in self.N.OPS:
            if key not in self.N.MASTER_OPS or self.lib.is_master:
                self.op.addItem(label, key)
        self.op.setCurrentIndex(max(self.op.findData(keep), 0))
        self.op.blockSignals(False)

    def build_tags(self):
        from core import master
        while self.tag_form.rowCount():
            self.tag_form.removeRow(0)
        self.tag_edits = []
        for n, s in enumerate(self.lib.sources):
            e = QLineEdit(master.tag_for(self.lib, n))
            e.setMaxLength(16)
            e.setFixedWidth(160)
            e.textEdited.connect(self.stale)
            self.tag_edits.append(e)
            self.tag_form.addRow(f"{s['label']}:", e)
        self.tag_box.setVisible(self.lib.is_master and self.op.currentData() in self.N.MASTER_OPS)

    def tags(self):
        return [e.text().strip() for e in self.tag_edits]

    def op_changed(self, *_):
        op = self.op.currentData()
        self.tag_box.setVisible(self.lib.is_master and op in self.N.MASTER_OPS)
        self.f_prefix.setEnabled(op == "prefix")
        self.f_find.setEnabled(op == "replace")
        self.f_repl.setEnabled(op == "replace")
        self.f_case.setEnabled(op == "replace")
        for w in self.acr_row:
            w.setEnabled(op == "proper")
        self.stale()

    def prefs_changed(self, *_):
        self.prefs.update(std_on=self.std_on.isChecked(), extra=self.extra.text())
        self.on_prefs(dict(self.prefs))
        self.stale()

    def edit_standard(self):
        text = edit_standard_list(self, self.prefs.get("std", ""))
        if text is not None:
            self.prefs["std"] = text
            self.prefs_changed()

    def words(self):
        from core.casing import parse_extra
        words = parse_extra(self.extra.text())
        if self.std_on.isChecked():
            words |= parse_extra(self.prefs.get("std", ""))
        return words

    def stale(self, *_):
        """Any change makes the old preview untrustworthy, so Apply waits for a fresh one."""
        self.changed = []
        self.apply_btn.setEnabled(False)
        if self.table.rowCount() or self.counts.text():
            self.table.setRowCount(0)
            self.counts.setText("")
            self.summary.setText("You changed something, so the old preview was cleared. Press Preview again.")

    def reload(self):
        """Window shown again: your list and selection may have changed."""
        self.fill_ops()
        self.build_tags()
        self.changed = []
        self.table.setRowCount(0)
        self.counts.setText("")
        self.summary.setText("Preview shows exactly what would change. Nothing changes until you press Apply.")
        self.apply_btn.setEnabled(False)
        self.update_undo()

    # ---- preview / apply ------------------------------------------------
    def scope_items(self):
        which = self.scope.currentData()
        if which == "selected":
            items = self.get_selected()
        elif which == "category":
            items = self.get_category_items()
        else:
            items = self.lib.items
        kind = self.kind.currentData()
        return [it for it in items if kind == "all" or it.kind == kind]

    def preview(self):
        op = self.op.currentData()
        if op == "prefix" and not self.f_prefix.text().strip():
            self.summary.setText("Type the prefix to remove first.")
            return
        if op == "replace" and not self.f_find.text():
            self.summary.setText("Type the text to find first.")
            return
        if op == "addtag" and not any(self.tags()):
            self.summary.setText("Type a tag for at least one source first.")
            return
        if op == "proper":
            self.prefs_changed()
        items = self.scope_items()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.changed = self.N.plan(items, op, tags=self.tags(), extra=self.words(), prefix=self.f_prefix.text(),
                                       find=self.f_find.text(), repl=self.f_repl.text(),
                                       ignore_case=self.f_case.isChecked())
        finally:
            QApplication.restoreOverrideCursor()
        live = sum(1 for it in items if not it.deleted and not it.gone)
        self.counts.setText(f"{live:,} item{'s' if live != 1 else ''} looked at.")
        rows = self.changed
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(min(len(rows), self.MAX_ROWS))
        for n, (it, new) in enumerate(rows[:self.MAX_ROWS]):
            for col, text in enumerate((KIND_LABEL[it.kind], it.name, new, it.category)):
                cell = QTableWidgetItem(text)
                cell.setBackground(QBrush(self.YELLOW))
                self.table.setItem(n, col, cell)
        self.table.setUpdatesEnabled(True)
        extra = f" (showing the first {self.MAX_ROWS:,})" if len(rows) > self.MAX_ROWS else ""
        self.summary.setText(f"{len(rows):,} name{'s' if len(rows) != 1 else ''} would change{extra}."
                             if rows else "No names would change.")
        self.apply_btn.setEnabled(bool(rows))
        self.update_undo()

    def apply(self):
        ch = [(it, "name", new) for it, new in self.changed]
        if not ch:
            return
        if self.ask_box.isChecked():
            ok, again = confirm_changes(self, ch)
            if not ok:
                return
            if again:
                self.ask_box.setChecked(False)
        if self.lib.is_master and self.op.currentData() == "addtag":      # remember the tags you used
            for s, t in zip(self.lib.sources, self.tags()):
                if t and s.get("tag") != t:
                    s["tag"] = t
                    self.lib.dirty = True
        self.on_apply(ch)
        self.preview()                    # whatever is left to do after that

    def undo_last(self):
        if not self.lib.undo_stack or not self.on_undo:
            return
        self.on_undo()
        self.preview() if self.changed or self.table.rowCount() else self.update_undo()

    def update_undo(self):
        stack = self.lib.undo_stack
        self.undo_btn.setEnabled(bool(stack))
        self.undo_btn.setText(f"Undo last action ({stack[-1][0]})" if stack else "Undo last action")
        self.undo_btn.setToolTip("Goes back one step. Undoes the last change made to your list (for example your last "
                                 "Apply here). Click again to go back another step.")


# ---- copy edits from another project -----------------------------------------
class CopyEditsDialog(QDialog):
    """Make this project's Live channels follow another project's edits (same channels, different provider)."""
    MAX_ROWS = 2000
    YELLOW = QColor(255, 215, 0, 70)

    def __init__(self, parent, lib, on_apply, ask, on_ask, on_undo, start_dir=""):
        super().__init__(parent)
        from core import carry
        self.C = carry
        self.setWindowTitle("Copy edits from another project")
        self.resize(1100, 720)
        self.lib, self.on_apply, self.on_ask, self.on_undo = lib, on_apply, on_ask, on_undo
        self.start_dir = start_dir
        self.src, self.src_path, self.src_stamp = None, "", None
        self.result = None
        lay = QVBoxLayout(self)
        intro = QLabel("Open the NEW list as your project (this one). Pick the project you've been editing, and this "
                       "makes this project's Live channels match it: what you deleted, starred, renamed and moved. "
                       "Channels are matched by EPG ID first, then by name (ignoring prefixes like US| and tags like HD). "
                       "Nothing changes until you press Apply.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("Copy edits from:"))
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("Choose the project file (.xtp) you've been editing")
        browse = QPushButton("Browse...")
        browse.setAutoDefault(False)
        browse.clicked.connect(self.browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        lay.addLayout(row)

        box = QGroupBox("What to copy")
        grid = QGridLayout(box)
        self.opts = {}
        for n, (key, label) in enumerate(carry.OPTIONS):
            cb = QCheckBox(label)
            cb.setChecked(carry.DEFAULTS[key])
            cb.toggled.connect(self.stale)
            self.opts[key] = cb
            grid.addWidget(cb, n // 2, n % 2)
        self.fav_only = QCheckBox("Only the channels I starred in the other list (do the important ones first)")
        self.fav_only.setToolTip("Limits everything below to the other list's favorites. The whole-list steps (order, "
                                 "marking new, deleting) wait until you untick this and go again.")
        self.fav_only.toggled.connect(self.fav_toggled)
        self.opts["fav_only"] = self.fav_only
        grid.addWidget(self.fav_only, (len(carry.OPTIONS) + 1) // 2, 0, 1, 2)
        lay.addWidget(box)

        pv = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setAutoDefault(False)
        self.preview_btn.clicked.connect(self.preview)
        pv.addWidget(self.preview_btn)
        self.counts = QLabel("")
        self.counts.setWordWrap(True)
        pv.addWidget(self.counts, 1)
        lay.addLayout(pv)

        self.tabs = QTabWidget()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Channel in this list", "Matched with (other list)", "Matched by", "What changes"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for col, w in enumerate((300, 300, 110)):
            self.table.setColumnWidth(col, w)
        self.lists = {k: QListWidget() for k in ("only_dst", "only_src", "deleted_there", "ambiguous")}
        self.tabs.addTab(self.table, "Changes")
        self.tabs.addTab(self.lists["only_dst"], "Only in this list")
        self.tabs.addTab(self.lists["only_src"], "Only in the other list")
        self.tabs.addTab(self.lists["deleted_there"], "Deleted in the other list")
        self.tabs.addTab(self.lists["ambiguous"], "Unclear matches")
        lay.addWidget(self.tabs, 1)

        self.ask_box = QCheckBox("Ask before applying")
        self.ask_box.setChecked(bool(ask))
        self.ask_box.toggled.connect(lambda on: self.on_ask(on) if self.on_ask else None)
        lay.addWidget(self.ask_box)
        bottom = QHBoxLayout()
        self.summary = QLabel("Preview shows exactly what would change. Nothing changes until you press Apply.")
        bottom.addWidget(self.summary, 1)
        self.undo_btn = QPushButton("Undo last action")
        self.undo_btn.setAutoDefault(False)
        self.undo_btn.clicked.connect(self.undo_last)
        QShortcut(QKeySequence.Undo, self, activated=self.undo_last)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setAutoDefault(False)
        self.apply_btn.clicked.connect(self.apply)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        for b in (self.undo_btn, self.apply_btn, close):
            bottom.addWidget(b)
        lay.addLayout(bottom)
        self.update_undo()
        self.apply_btn.setEnabled(False)

    def fav_toggled(self, on):
        for key in ("order", "mark_new"):                   # whole-list steps don't apply to a favorites-only pass
            self.opts[key].setEnabled(not on)
        self.stale()

    # ---- source project -------------------------------------------------
    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Project to copy edits from", self.start_dir,
                                              "Xtream Editor projects (*.xtp);;All files (*)")
        if path:
            self.set_source(path)

    def set_source(self, path):
        self.path.setText(path)
        self.src, self.src_path, self.src_stamp = None, path, None
        self.stale()

    def load_source(self):
        """-> True when the other project is loaded (re-read when the file changed)."""
        if not self.src_path:
            self.summary.setText("Choose the project you've been editing first.")
            return False
        try:
            st = os.stat(self.src_path)
            stamp = (st.st_mtime_ns, st.st_size)
            if self.src is None or stamp != self.src_stamp:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    lib = Library()
                    lib.load(self.src_path)
                finally:
                    QApplication.restoreOverrideCursor()
                self.src, self.src_stamp = lib, stamp
        except Exception as e:                                   # noqa: BLE001 - unreadable file
            self.src = None
            self.summary.setText(f"Couldn't read that project: {e}")
            return False
        if self.src is self.lib:
            self.summary.setText("That's this same project. Pick the other one.")
            return False
        return True

    # ---- preview / apply ------------------------------------------------
    def stale(self, *_):
        self.result = None
        self.apply_btn.setEnabled(False)
        if self.table.rowCount() or self.counts.text():
            self.table.setRowCount(0)
            for w in self.lists.values():
                w.clear()
            self.counts.setText("")
            self.summary.setText("You changed something, so the old preview was cleared. Press Preview again.")

    def reload(self):
        self.result = None
        self.apply_btn.setEnabled(False)
        self.update_undo()

    def preview(self):
        if not self.load_source():
            return
        opts = {k: cb.isChecked() for k, cb in self.opts.items()}
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = self.result = self.C.plan(self.src.items, self.lib.items, opts)
        finally:
            QApplication.restoreOverrideCursor()
        live_src = sum(1 for i in self.src.items if i.kind == "live" and not i.gone and not i.deleted)
        self.counts.setText(
            f"{len(res['pairs']):,} channels matched (of {live_src:,} kept in the other list).   "
            f"Only in this list: {len(res['only_dst']):,}.   Only in the other list: {len(res['only_src']):,}.   "
            f"Unclear: {len(res['ambiguous']):,}.")
        rows = res["rows"]
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(min(len(rows), self.MAX_ROWS))
        for n, (b, a, how, texts) in enumerate(rows[:self.MAX_ROWS]):
            for col, text in enumerate((b.name, a.name if a else "", how, "; ".join(texts))):
                cell = QTableWidgetItem(text)
                cell.setBackground(QBrush(self.YELLOW))
                self.table.setItem(n, col, cell)
        self.table.setUpdatesEnabled(True)
        for key, w in self.lists.items():
            w.clear()
        for b in res["only_dst"]:
            self.lists["only_dst"].addItem(f"{b.name}   [{b.category}]")
        for a in res["only_src"]:
            self.lists["only_src"].addItem(f"{a.name}   [{a.category}]")
        will = self.opts["deleted"].isChecked() and not self.fav_only.isChecked()
        for a, b in res["deleted_there"]:
            self.lists["deleted_there"].addItem(
                f"{b.name}   [{b.category}]   " + ("-> will be deleted here" if will else "-> left alone")
                + ("  (already deleted)" if b.deleted else ""))
        for xs, ys in res["ambiguous"]:
            self.lists["ambiguous"].addItem("Other list: " + ", ".join(f"{x.name} [{x.category}]" for x in xs[:4])
                                            + "   ->   This list: " + ", ".join(f"{y.name} [{y.category}]" for y in ys[:4]))
        for i, (label, key) in enumerate((("Changes", None), ("Only in this list", "only_dst"),
                                          ("Only in the other list", "only_src"),
                                          ("Deleted in the other list", "deleted_there"), ("Unclear matches", "ambiguous"))):
            n = len(rows) if key is None else len(res[key])
            self.tabs.setTabText(i, f"{label} ({n:,})")
        c = res["counts"]
        bits = [f"{c[k]:,} {t}" for k, t in (("deleted", "deleted/restored"), ("fav", "favorites"), ("name", "renamed"),
                                             ("category", "moved"), ("logo", "logos"), ("epg_id", "EPG IDs"),
                                             ("num", "reordered"), ("new", "marked new")) if c.get(k)]
        extra = f" (showing the first {self.MAX_ROWS:,})" if len(rows) > self.MAX_ROWS else ""
        self.summary.setText((", ".join(bits) + f" would change{extra}.") if bits else "Nothing would change.")
        self.apply_btn.setEnabled(bool(res["changes"]))
        self.update_undo()

    def apply(self):
        if not self.result or not self.result["changes"]:
            return
        ch = self.result["changes"]
        if self.ask_box.isChecked():
            ok, again = confirm_changes(self, ch)
            if not ok:
                return
            if again:
                self.ask_box.setChecked(False)
        self.on_apply(ch)
        self.preview()

    def undo_last(self):
        if not self.lib.undo_stack or not self.on_undo:
            return
        self.on_undo()
        if self.result is not None:
            self.preview()
        else:
            self.update_undo()

    def update_undo(self):
        stack = self.lib.undo_stack
        self.undo_btn.setEnabled(bool(stack))
        self.undo_btn.setText(f"Undo last action ({stack[-1][0]})" if stack else "Undo last action")
        self.undo_btn.setToolTip("Goes back one step. Undoes the last change made to your list (for example your last "
                                 "Apply here). Click again to go back another step.")


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


def confirm_changes(parent, ch):
    """The 'Apply these changes?' popup. ch is a Library.change() list. -> (accepted, don't-ask-again ticked)."""
    deleted = sum(1 for _, f, _v in ch if f == "deleted")
    renamed = sum(1 for _, f, _v in ch if f == "name")
    moved = sum(1 for _, f, _v in ch if f == "category")
    total = len({it.key for it, _f, _v in ch})
    lines = []
    if deleted:
        lines.append(f"{deleted:,} deleted")
    if renamed:
        lines.append(f"{renamed:,} renamed")
    if moved:
        lines.append(f"{moved:,} moved to another category")
    box = QMessageBox(parent)
    box.setWindowTitle("Apply these changes?")
    box.setIcon(QMessageBox.Question)
    box.setText(f"{total:,} item{'s' if total != 1 else ''} will be changed:")
    box.setInformativeText("\n".join("  \u2022 " + t for t in lines)
                           + "\n\nYou can undo this afterward with the Undo last action button (or Ctrl+Z).")
    again = QCheckBox("Don't ask me again")
    box.setCheckBox(again)
    box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
    box.button(QMessageBox.Ok).setText("Apply")
    return box.exec() == QMessageBox.Ok, again.isChecked()


# ---- duplicate finder ------------------------------------------------------
class _ClearOnBlankTree(QTreeWidget):
    """A tree where clicking empty space deselects everything."""

    def mousePressEvent(self, ev):
        if not self.indexAt(ev.position().toPoint()).isValid():
            self.clearSelection()
        super().mousePressEvent(ev)


class DuplicateFinderDialog(QDialog):
    """Groups entries that look like the same title. Mark what to do with each copy, then Apply."""
    TYPES = (("Movies", ("vod",)), ("Series", ("series",)), ("Movies + Series", ("vod", "series")),
             ("Live", ("live",)), ("All types", ("live", "vod", "series")))
    SCOPES = (("Active items", "active"), ("Favorites only", "fav"), ("New since last sync", "new"),
              ("Everything (incl. deleted)", "all"))
    KEEP_RULES = (("the one earliest in my list", "first"), ("the newest one the provider added", "newest"),
                  ("the one with the most info (logo, rating, plot)", "complete"))
    MAX_GROUPS = 5000
    RED = QColor(220, 60, 60, 70)
    YELLOW = QColor(255, 215, 0, 70)
    GREEN = QColor(60, 180, 90, 60)

    def __init__(self, parent, lib, on_apply, ask=True, on_ask=None, on_undo=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate finder")
        self.resize(1050, 680)
        self.lib, self.on_apply, self.on_ask, self.on_undo = lib, on_apply, on_ask, on_undo
        self.groups = []
        self.searched = False
        self.total_groups = 0
        self.pending = {}            # item.key -> {'deleted': True} / {'name': ..} / {'category': ..} / {'keep': True}
        self.nodes = {}              # item.key -> (tree item, Item)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self.kind = QComboBox()
        for label, _ in self.TYPES:
            self.kind.addItem(label)
        self.scope = QComboBox()
        for label, _ in self.SCOPES:
            self.scope.addItem(label)
        self.within = QComboBox()
        self.within.addItems(["Same title anywhere", "Same title in the same category"])
        self.no_year = QCheckBox("Ignore the year")
        self.no_year.setToolTip("Off: 'Dune (1984)' and 'Dune (2021)' are different titles.")
        self.find_btn = QPushButton("Find duplicates")
        self.find_btn.setDefault(True)
        self.find_btn.clicked.connect(self.search)
        for w in (QLabel("Look in:"), self.kind, self.scope, self.within, self.no_year):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(self.find_btn)
        lay.addLayout(top)

        self.tree = _ClearOnBlankTree()
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels(["Title", "Type", "Category", "ID", "Added", "Rating", "Your choice"])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.menu)
        hh = self.tree.header()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for col, w in enumerate((430, 70, 220, 90, 90, 60)):
            self.tree.setColumnWidth(col, w)
        lay.addWidget(self.tree, 1)

        act = QHBoxLayout()
        act.addWidget(QLabel("For the selected copies:"))
        for text, fn in (("Keep", self.do_keep), ("Delete", self.do_delete), ("Rename...", self.do_rename),
                         ("Move to category...", self.do_move), ("Clear choice", self.do_clear)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            act.addWidget(b)
        clear_all = QPushButton("Clear all choices")
        clear_all.setToolTip("Removes every Keep / Delete / Rename / Move mark in this window, no selection needed. "
                             "Nothing in your list changes until you press Apply.")
        clear_all.clicked.connect(self.clear_all)
        act.addWidget(clear_all)
        self.undo_btn = QPushButton("Undo last action")
        self.undo_btn.clicked.connect(self.undo_last)
        act.addWidget(self.undo_btn)
        QShortcut(QKeySequence.Undo, self, activated=self.undo_last)
        act.addStretch(1)
        lay.addLayout(act)

        auto = QHBoxLayout()
        auto.addWidget(QLabel("Or in every group, keep"))
        self.rule = QComboBox()
        for label, _ in self.KEEP_RULES:
            self.rule.addItem(label)
        auto.addWidget(self.rule)
        auto.addWidget(QLabel("and delete the rest"))
        b = QPushButton("Mark them all")
        b.clicked.connect(self.auto_pick)
        auto.addWidget(b)
        auto.addStretch(1)
        lay.addLayout(auto)

        tip = QLabel("Nothing changes in your list until you press Apply, and Apply is one undo step. "
                     "Live channels repeat a lot on purpose, so they're best checked with 'same category' on.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.ask_box = QCheckBox("Ask before applying")
        self.ask_box.setChecked(bool(ask))
        self.ask_box.toggled.connect(lambda on: self.on_ask(on) if self.on_ask else None)
        lay.addWidget(self.ask_box)
        bottom = QHBoxLayout()
        self.summary = QLabel("Pick what to look for and press Find duplicates.")
        bottom.addWidget(self.summary, 1)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self.apply)
        self.apply_btn.setAutoDefault(False)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        bottom.addWidget(self.apply_btn)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        self.update_summary()

    # ---- search -------------------------------------------------------
    def search(self):
        kinds = self.TYPES[self.kind.currentIndex()][1]
        scope = self.SCOPES[self.scope.currentIndex()][1]
        from core.duplicates import find_groups
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            groups = find_groups(self.lib.items, kinds, scope, self.within.currentIndex() == 1,
                                 self.no_year.isChecked())
        finally:
            QApplication.restoreOverrideCursor()
        self.total_groups = len(groups)
        self.searched = True
        self.groups = groups[:self.MAX_GROUPS]
        self.pending.clear()
        self.fill()

    def undo_last(self):
        """Same as Edit > Undo in the main window (Ctrl+Z doesn't reach it from this separate window)."""
        if not self.lib.undo_stack or not self.on_undo:
            return
        self.on_undo()
        self.search()                 # the groups may have changed; marks are cleared

    def update_undo(self):
        stack = self.lib.undo_stack
        self.undo_btn.setEnabled(bool(stack))
        self.undo_btn.setText(f"Undo last action ({stack[-1][0]})" if stack else "Undo last action")
        self.undo_btn.setToolTip("Goes back one step. Undoes the last change made to your list (for example your last "
                                 "Apply here). Click again to go back another step.")

    def reload(self):
        """Called when the window is shown again: forget stale results."""
        self.groups, self.pending, self.nodes = [], {}, {}
        self.searched = False
        self.tree.clear()
        self.summary.setText("Pick what to look for and press Find duplicates.")
        self.update_summary()

    def fill(self):
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        self.nodes = {}
        for g in self.groups:
            head = QTreeWidgetItem(self.tree, [f"{g[0].name}   ({len(g)} copies)"])
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            for it in g:
                child = QTreeWidgetItem(head, [it.name, KIND_LABEL[it.kind], it.category, it.id, self.added_text(it),
                                               str(it.rating or ""), ""])
                child.setData(0, Qt.UserRole, it.key)
                self.nodes[it.key] = (child, it)
                self.paint(it)
            head.setExpanded(True)
        self.tree.setUpdatesEnabled(True)
        self.update_summary()

    @staticmethod
    def added_text(it):
        try:
            import time
            return time.strftime("%Y-%m-%d", time.localtime(float(it.added)))
        except (TypeError, ValueError, OverflowError, OSError):
            return str(it.added or "")

    # ---- choices ------------------------------------------------------
    def selected(self):
        out, seen = [], set()
        for node in self.tree.selectedItems():
            kids = [node.child(i) for i in range(node.childCount())] if node.childCount() else [node]
            for k in kids:
                key = k.data(0, Qt.UserRole)
                if key in self.nodes and key not in seen:
                    seen.add(key)
                    out.append(self.nodes[key][1])
        return out

    def paint(self, it):
        node = self.nodes[it.key][0]
        p = self.pending.get(it.key, {})
        parts = []
        if p.get("deleted"):
            parts.append("Delete")
        if "name" in p:
            parts.append(f"Rename to {p['name']}")
        if "category" in p:
            parts.append(f"Move to {p['category']}")
        if p.get("keep") and not parts:
            parts.append("Keep")
        node.setText(6, ", ".join(parts))
        color = self.RED if p.get("deleted") else self.YELLOW if ("name" in p or "category" in p) \
            else self.GREEN if p.get("keep") else None
        for c in range(7):
            node.setBackground(c, QBrush(color) if color else QBrush())

    def set_pending(self, items, **fields):
        for it in items:
            if fields.get("keep"):
                self.pending[it.key] = {"keep": True}
            else:
                self.pending.setdefault(it.key, {}).update(fields)
                self.pending[it.key].pop("keep", None)
            self.paint(it)
        self.update_summary()

    def need_selection(self):
        sel = self.selected()
        if not sel:
            self.summary.setText("Select one or more copies first (or a whole group).")
        return sel

    def do_keep(self):
        sel = self.need_selection()
        if sel:
            self.set_pending(sel, keep=True)

    def do_delete(self):
        sel = self.need_selection()
        if sel:
            self.set_pending(sel, deleted=True)

    def do_clear(self):
        for it in self.need_selection():
            self.pending.pop(it.key, None)
            self.paint(it)
        self.update_summary()

    def clear_all(self):
        self.pending.clear()
        for key in self.nodes:
            self.paint(self.nodes[key][1])
        self.update_summary()

    def do_rename(self):
        sel = self.need_selection()
        if not sel:
            return
        text, ok = QInputDialog.getText(self, "Rename", f"New name for {len(sel)} item{'s' if len(sel) != 1 else ''}:",
                                        text=sel[0].name)
        if ok and text.strip():
            self.set_pending(sel, name=text.strip())

    def do_move(self):
        sel = self.need_selection()
        if not sel:
            return
        kinds = {it.kind for it in sel}
        cats = sorted({c for k in kinds for c in self.lib.categories(k)}, key=str.lower)
        cat, ok = QInputDialog.getItem(self, "Move to category", "Pick one, or type a new name:", cats,
                                       cats.index(sel[0].category) if sel[0].category in cats else 0, True)
        if ok and cat.strip():
            self.set_pending(sel, category=cat.strip())

    def auto_pick(self):
        from core.duplicates import keeper
        rule = self.KEEP_RULES[self.rule.currentIndex()][1]
        for g in self.groups:
            best = keeper(g, rule)
            for it in g:
                if it is best:
                    self.pending[it.key] = {"keep": True}
                else:
                    self.pending[it.key] = {"deleted": True}
                self.paint(it)
        self.update_summary()

    def menu(self, pos):
        m = QMenu(self)
        for text, fn in (("Keep", self.do_keep), ("Delete", self.do_delete), ("Rename...", self.do_rename),
                         ("Move to category...", self.do_move), ("Clear choice", self.do_clear)):
            m.addAction(text, fn)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ---- apply --------------------------------------------------------
    def changes(self):
        out = []
        for key, p in self.pending.items():
            node = self.nodes.get(key)
            if not node:
                continue
            it = node[1]
            if p.get("deleted") and not it.deleted:
                out.append((it, "deleted", True))
            if "name" in p:
                out.append((it, "name", p["name"]))
            if "category" in p:
                out.append((it, "category", p["category"]))
        return out

    def update_summary(self):
        n_del = sum(1 for p in self.pending.values() if p.get("deleted"))
        n_edit = sum(1 for p in self.pending.values() if "name" in p or "category" in p)
        shown = len(self.groups)
        total = getattr(self, "total_groups", shown)
        head = ""
        if shown:
            head = f"{shown:,} group{'s' if shown != 1 else ''} of duplicates"
            if total > shown:
                head += f" (showing the first {shown:,} of {total:,})"
            head += "   |   "
        elif self.searched:
            head = "No duplicates found.   |   "
        self.summary.setText(f"{head}{n_del:,} to delete, {n_edit:,} to rename or move")
        self.apply_btn.setEnabled(bool(n_del or n_edit))
        self.update_undo()

    def confirm(self, ch):
        """Popup listing what is about to happen. 'Don't ask again' just unticks the box in the window."""
        ok, again = confirm_changes(self, ch)
        if ok and again:
            self.ask_box.setChecked(False)           # saves through on_ask; the box in this window turns it back on
        return ok

    def apply(self):
        ch = self.changes()
        if not ch:
            return
        if self.ask_box.isChecked() and not self.confirm(ch):
            return
        self.on_apply(ch)
        self.search()                 # what's left after the changes


# ---- regex rules -----------------------------------------------------------
class RegexRulesDialog(QDialog):
    """Rules list on the left, the selected rule on the right, a preview of what would change underneath."""
    MAX_ROWS = 2000
    RED = QColor(220, 60, 60, 70)
    YELLOW = QColor(255, 215, 0, 70)

    def __init__(self, parent, lib, rules, on_save, on_apply, ask=True, on_ask=None, on_undo=None,
                 builtin_states=None, on_builtin=None):
        super().__init__(parent)
        from core import rules as R
        self.R = R
        self.setWindowTitle("Regex rules")
        self.resize(1100, 760)
        self.lib, self.on_save, self.on_apply, self.on_ask, self.on_undo = lib, on_save, on_apply, on_ask, on_undo
        self.on_builtin = on_builtin
        self.builtin = R.builtin_rules(builtin_states)       # ready-made rules: on/off only
        self.rules = [R.normalize(r) for r in rules]         # your own rules
        self.changed = {}
        self._loading = False
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Rules (run top to bottom; tick to switch one on). The grey ones are built in:"))
        self.listw = QListWidget()
        self.listw.setMinimumWidth(260)
        self.listw.currentRowChanged.connect(self.load_rule)
        self.listw.itemChanged.connect(self.item_toggled)
        left.addWidget(self.listw, 1)
        row = QHBoxLayout()
        for text, fn in (("Add", self.add_rule), ("Copy", self.copy_rule), ("Remove", self.remove_rule),
                         ("Up", lambda: self.move_rule(-1)), ("Down", lambda: self.move_rule(1))):
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.clicked.connect(fn)
            row.addWidget(b)
        left.addLayout(row)
        self.row_btns = {b.text(): b for b in (row.itemAt(i).widget() for i in range(row.count()))}
        top.addLayout(left, 1)

        self.form_box = QGroupBox("This rule")
        form = QFormLayout(self.form_box)
        self.f_name = QLineEdit()
        self.f_name.setPlaceholderText("Optional label, e.g. Strip US prefix")
        self.f_kinds = QComboBox()
        for label, _ in R.KIND_CHOICES:
            self.f_kinds.addItem(label)
        self.f_field = QComboBox()
        for label, _ in R.FIELD_CHOICES:
            self.f_field.addItem(label)
        mrow = QHBoxLayout()
        mrow.addWidget(self.f_kinds)
        mrow.addWidget(QLabel("whose"))
        mrow.addWidget(self.f_field)
        mrow.addWidget(QLabel("matches:"))
        mrow.addStretch(1)
        self.f_pattern = QLineEdit()
        self.f_pattern.setPlaceholderText(r"e.g.  ^US \| (.*)")
        self.f_case = QCheckBox("Ignore upper/lower case")
        self.f_err = QLabel("")
        self.f_err.setStyleSheet("color: #d04040;")
        self.f_err.setWordWrap(True)
        self.f_rewrite_on = QCheckBox("Rewrite the matched field with:")
        self.f_rewrite = QLineEdit()
        self.f_rewrite.setPlaceholderText(r"e.g.  \1  (or $1) keeps what's in the first ( ); leave empty to just remove the match")
        def cat_box(hint):
            box = QComboBox()
            box.setEditable(True)
            box.setInsertPolicy(QComboBox.NoInsert)
            box.setMaxVisibleItems(20)
            box.lineEdit().setPlaceholderText(hint)
            comp = box.completer()
            comp.setFilterMode(Qt.MatchContains)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            return box
        self.f_only = cat_box("pick one, or type a name (blank = every category)")
        self.f_move = cat_box("pick one, or type a new name (blank keeps the current category)")
        self.f_delete = QCheckBox("Delete the items that match")
        self.f_note = QLabel("")
        self.f_note.setWordWrap(True)
        self.f_note.setStyleSheet("color: #5a6b85;")
        form.addRow(self.f_note)
        form.addRow("Name:", self.f_name)
        form.addRow("Look at:", mrow)
        form.addRow("Only in category:", self.f_only)
        form.addRow("Pattern:", self.f_pattern)
        form.addRow("", self.f_case)
        form.addRow("", self.f_err)
        form.addRow(self.f_rewrite_on, self.f_rewrite)
        form.addRow("Move matches to category:", self.f_move)
        form.addRow("", self.f_delete)
        hint = QLabel("Patterns are Python regular expressions. Rules run in order, so a later rule sees the result of "
                      "an earlier one. A name is never rewritten to nothing.")
        hint.setWordWrap(True)
        form.addRow(hint)
        top.addWidget(self.form_box, 2)
        lay.addLayout(top)

        for w in (self.f_name, self.f_pattern, self.f_rewrite):
            w.textEdited.connect(self.form_changed)
        self.f_move.editTextChanged.connect(self.form_changed)        # typing or picking from the list
        self.f_only.editTextChanged.connect(self.form_changed)
        self.f_kinds.currentIndexChanged.connect(self.update_cats)    # the list follows the rule's type
        for w in (self.f_kinds, self.f_field):
            w.currentIndexChanged.connect(self.form_changed)
        for w in (self.f_case, self.f_rewrite_on, self.f_delete):
            w.toggled.connect(self.form_changed)

        pv = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setAutoDefault(False)
        self.preview_btn.clicked.connect(self.preview)
        pv.addWidget(self.preview_btn)
        self.counts = QLabel("")
        self.counts.setWordWrap(True)
        pv.addWidget(self.counts, 1)
        lay.addLayout(pv)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Type", "Name now", "Name after", "Category now", "Category after", "Action"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for col, w in enumerate((70, 300, 300, 160, 160)):
            self.table.setColumnWidth(col, w)
        lay.addWidget(self.table, 2)

        self.ask_box = QCheckBox("Ask before applying")
        self.ask_box.setChecked(bool(ask))
        self.ask_box.toggled.connect(lambda on: self.on_ask(on) if self.on_ask else None)
        lay.addWidget(self.ask_box)
        bottom = QHBoxLayout()
        self.summary = QLabel("Preview shows exactly what would change. Nothing changes until you press Apply.")
        bottom.addWidget(self.summary, 1)
        self.undo_btn = QPushButton("Undo last action")
        self.undo_btn.setAutoDefault(False)
        self.undo_btn.clicked.connect(self.undo_last)
        QShortcut(QKeySequence.Undo, self, activated=self.undo_last)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setAutoDefault(False)
        self.apply_btn.clicked.connect(self.apply)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        for b in (self.undo_btn, self.apply_btn, close):
            bottom.addWidget(b)
        lay.addLayout(bottom)

        self.refill()
        self.update_cats()
        self.update_undo()
        self.apply_btn.setEnabled(False)

    # ---- the rule list --------------------------------------------------
    def label(self, r):
        return r["name"].strip() or r["pattern"] or "(new rule)"

    def all_rules(self):
        """Built-in rules first, then yours (the order they run in)."""
        return self.builtin + self.rules

    def refill(self, select=None):
        """select: row number in the combined list (default: your first rule, or the first built-in)."""
        nb = len(self.builtin)
        if select is None:
            select = nb if self.rules else 0
        self.listw.blockSignals(True)
        self.listw.clear()
        for r in self.all_rules():
            it = QListWidgetItem(self.label(r))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if r["on"] else Qt.Unchecked)
            if r.get("builtin"):
                it.setForeground(QBrush(QColor(110, 120, 140)))
            self.listw.addItem(it)
        self.listw.blockSignals(False)
        total = len(self.builtin) + len(self.rules)
        self.listw.setCurrentRow(min(max(select, 0), total - 1))
        self.load_rule(self.listw.currentRow())

    def update_cats(self, *_):
        """Fill the Move-to dropdown with the categories for this rule's type (blank first = keep as is)."""
        kind = self.R.KIND_CHOICES[self.f_kinds.currentIndex()][1]
        cats = sorted({it.category for it in self.lib.items
                       if not it.deleted and (kind == "all" or it.kind == kind)}, key=str.lower)
        for box in (self.f_move, self.f_only):
            text = box.currentText()
            box.blockSignals(True)
            box.clear()
            box.addItem("")
            box.addItems(cats)
            box.setEditText(text)
            box.blockSignals(False)

    def cur(self):
        """The rule shown in the form (built-in or yours)."""
        i = self.listw.currentRow()
        rules = self.all_rules()
        return rules[i] if 0 <= i < len(rules) else None

    def cur_index(self):
        """Index into YOUR rules, or -1 when a built-in rule (or nothing) is selected."""
        i = self.listw.currentRow() - len(self.builtin)
        return i if 0 <= i < len(self.rules) else -1

    def save(self):
        self.on_save([dict(r) for r in self.rules])
        if self.on_builtin:
            self.on_builtin({b["id"]: b["on"] for b in self.builtin})

    def stale(self):
        """Any edit makes the old preview untrustworthy, so Apply waits for a fresh one."""
        self.changed = {}
        self.apply_btn.setEnabled(False)
        if self.table.rowCount() or self.counts.text():
            self.table.setRowCount(0)
            self.counts.setText("")
            self.summary.setText("You changed a rule, so the old preview was cleared. Press Preview again.")

    def add_rule(self):
        self.rules.append(self.R.new_rule())
        self.save()
        self.refill(len(self.builtin) + len(self.rules) - 1)
        self.stale()
        self.f_pattern.setFocus()

    def copy_rule(self):
        r = self.cur()
        if r:
            c = {k: v for k, v in r.items() if k in self.R.new_rule()}      # drops the built-in markers
            c["name"] = (r["name"] + " (copy)").strip()
            c["on"] = True
            i = self.cur_index()
            at = len(self.rules) if i < 0 else i + 1                         # a copy of a built-in goes last
            self.rules.insert(at, c)
            self.save()
            self.refill(len(self.builtin) + at)
            self.stale()

    def remove_rule(self):
        i = self.cur_index()
        if i >= 0:
            del self.rules[i]
            self.save()
            self.refill(len(self.builtin) + i)
            self.stale()

    def move_rule(self, d):
        i = self.cur_index()
        j = i + d
        if i >= 0 and 0 <= j < len(self.rules):
            self.rules[i], self.rules[j] = self.rules[j], self.rules[i]
            self.save()
            self.refill(len(self.builtin) + j)
            self.stale()

    def item_toggled(self, item):
        i = self.listw.row(item)
        rules = self.all_rules()
        if 0 <= i < len(rules):
            rules[i]["on"] = item.checkState() == Qt.Checked
            self.save()
            self.stale()

    # ---- the form -------------------------------------------------------
    def load_rule(self, i):
        rules = self.all_rules()
        r = rules[i] if 0 <= i < len(rules) else None
        built = bool(r and r.get("builtin"))
        self._loading = True
        self.form_box.setEnabled(r is not None and not built)       # built-in rules are look-but-don't-touch
        self.f_note.setText(("Built in: tick it to use it. It can't be edited or removed, but Copy makes a version you can "
                             "change.\n" + r.get("note", "")) if built else "")
        self.f_note.setVisible(built)
        for name, btn in self.row_btns.items():
            btn.setEnabled(name == "Add" or (name == "Copy" and r is not None) or (r is not None and not built))
        if r is None:
            r = self.R.new_rule()
        kinds = [k for _, k in self.R.KIND_CHOICES]
        fields = [k for _, k in self.R.FIELD_CHOICES]
        self.f_name.setText(r["name"])
        self.f_kinds.setCurrentIndex(kinds.index(r["kinds"]))
        self.f_field.setCurrentIndex(fields.index(r["field"]))
        self.f_pattern.setText(r["pattern"])
        self.f_case.setChecked(r["ignore_case"])
        self.f_rewrite_on.setChecked(r["rewrite_on"])
        self.f_rewrite.setText(r["rewrite"])
        self.update_cats()
        self.f_move.setEditText(r["move"])
        self.f_only.setEditText(r["only_cat"])
        self.f_delete.setChecked(r["delete"])
        self._loading = False
        self.show_error()

    def form_changed(self, *_):
        r = self.cur()
        if r is None or r.get("builtin") or self._loading:
            return
        r.update(name=self.f_name.text(), kinds=self.R.KIND_CHOICES[self.f_kinds.currentIndex()][1],
                 field=self.R.FIELD_CHOICES[self.f_field.currentIndex()][1], only_cat=self.f_only.currentText(), pattern=self.f_pattern.text(),
                 ignore_case=self.f_case.isChecked(), rewrite_on=self.f_rewrite_on.isChecked(),
                 rewrite=self.f_rewrite.text(), move=self.f_move.currentText(), delete=self.f_delete.isChecked())
        it = self.listw.currentItem()
        if it is not None:
            it.setText(self.label(r))
        self.save()
        self.show_error()
        self.stale()

    def show_error(self):
        r = self.cur()
        self.f_err.setText("" if r is None else self.R.compile_rule(r)[1])

    # ---- preview / apply ------------------------------------------------
    def preview(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rules = self.all_rules()
            self.changed, matches, errors = self.R.plan(self.lib.items, rules)
        finally:
            QApplication.restoreOverrideCursor()
        parts = []
        for i, r in enumerate(rules):
            if not r["on"]:
                continue
            tag = self.label(r)
            parts.append(f"{tag}: {errors[i]}" if i in errors else f"{tag}: {matches[i]:,} match{'es' if matches[i] != 1 else ''}")
        self.counts.setText("   |   ".join(parts) if parts else "No rules are switched on.")
        rows = list(self.changed.values())
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(min(len(rows), self.MAX_ROWS))
        for n, st in enumerate(rows[:self.MAX_ROWS]):
            it = st["item"]
            action = "Delete" if st["deleted"] else ", ".join(
                t for t, c in (("Rename", st["name"] != it.name), ("Move", st["category"] != it.category)) if c)
            cells = [KIND_LABEL[it.kind], it.name, st["name"], it.category, st["category"], action]
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setBackground(QBrush(self.RED if st["deleted"] else self.YELLOW))
                self.table.setItem(n, col, cell)
        self.table.setUpdatesEnabled(True)
        extra = f" (showing the first {self.MAX_ROWS:,})" if len(rows) > self.MAX_ROWS else ""
        self.summary.setText(f"{len(rows):,} item{'s' if len(rows) != 1 else ''} would change{extra}.")
        self.apply_btn.setEnabled(bool(rows) and not errors)
        self.update_undo()

    def confirm(self, ch):
        ok, again = confirm_changes(self, ch)
        if ok and again:
            self.ask_box.setChecked(False)
        return ok

    def apply(self):
        ch = self.R.to_changes(self.changed)
        if not ch:
            return
        if self.ask_box.isChecked() and not self.confirm(ch):
            return
        self.on_apply(ch)
        self.update_cats()
        self.preview()                    # whatever is left to do after that

    def undo_last(self):
        if not self.lib.undo_stack or not self.on_undo:
            return
        self.on_undo()
        self.update_cats()
        self.preview()

    def update_undo(self):
        stack = self.lib.undo_stack
        self.undo_btn.setEnabled(bool(stack))
        self.undo_btn.setText(f"Undo last action ({stack[-1][0]})" if stack else "Undo last action")
        self.undo_btn.setToolTip("Goes back one step. Undoes the last change made to your list (for example your last "
                                 "Apply here). Click again to go back another step.")

    def only_in(self, category):
        """Opened from the sidebar's right-click menu: aim the current rule at that category."""
        if not self.rules:
            self.add_rule()
        elif self.cur_index() < 0:                    # a built-in rule is showing: switch to your first own rule
            self.listw.setCurrentRow(len(self.builtin))
        self.update_cats()
        self.f_only.setEditText(category)             # form_changed saves it and clears the old preview
        self.f_pattern.setFocus()

    def reload(self):
        """Window shown again: your list may have changed since the last preview."""
        self.update_cats()
        self.changed = {}
        self.table.setRowCount(0)
        self.counts.setText("")
        self.summary.setText("Preview shows exactly what would change. Nothing changes until you press Apply.")
        self.apply_btn.setEnabled(False)
        self.update_undo()


# ---- build a master list from two projects -------------------------------------
class _SourcePane(QGroupBox):
    """One source project: pick the file, filter its Live channels, choose some to add to the master."""
    MAX_ROWS = 3000

    def __init__(self, title, dlg):
        super().__init__(title)
        self.dlg = dlg
        self.lib, self.path, self.shown = None, "", []
        self.src_idx = -1
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Choose a project (.xtp)")
        b = QPushButton("Browse...")
        b.setAutoDefault(False)
        b.clicked.connect(self.browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(b)
        lay.addLayout(row)
        lr = QHBoxLayout()
        self.login_lbl = QLabel("")
        self.tag_edit = QLineEdit()
        self.tag_edit.setMaxLength(16)
        self.tag_edit.setFixedWidth(90)
        self.tag_edit.setToolTip("The short tag for this list, used by Name manager > Add source tag to make names like [A] ESPN.")
        self.tag_touched = False
        self.tag_edit.textEdited.connect(lambda _: setattr(self, "tag_touched", True))
        lr.addWidget(self.login_lbl, 1)
        lr.addWidget(QLabel("Tag: ["))
        lr.addWidget(self.tag_edit)
        lr.addWidget(QLabel("]"))
        lay.addLayout(lr)
        f = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search channels")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refill)
        self.cat = QComboBox()
        self.cat.setMinimumWidth(160)
        self.cat.currentIndexChanged.connect(self.refill)
        f.addWidget(self.search, 1)
        f.addWidget(self.cat)
        lay.addLayout(f)
        o = QHBoxLayout()
        self.favs = QCheckBox("★ Favorites only")
        self.favs.toggled.connect(self.refill)
        self.hide_in = QCheckBox("Hide ones already in the master")
        self.hide_in.setChecked(True)
        self.hide_in.toggled.connect(self.refill)
        o.addWidget(self.favs)
        o.addWidget(self.hide_in)
        o.addStretch(1)
        lay.addLayout(o)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Channel", "Category", "★"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(1, 150)
        self.table.doubleClicked.connect(lambda *_: self.add_selected())
        lay.addWidget(self.table, 1)
        self.status = QLabel("")
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        self.add_sel = QPushButton("Add selected →")
        self.add_sel.setAutoDefault(False)
        self.add_sel.clicked.connect(self.add_selected)
        self.add_all = QPushButton("Add all shown →")
        self.add_all.setAutoDefault(False)
        self.add_all.clicked.connect(self.add_shown)
        btns.addWidget(self.add_sel)
        btns.addWidget(self.add_all)
        lay.addLayout(btns)

    @property
    def label(self):
        from core import master
        return master.source_label(self.path)

    def browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Project to take channels from", self.dlg.start_dir,
                                           "Xtream Editor projects (*.xtp);;All files (*)")
        if p:
            self.set_path(p)

    def set_path(self, p):
        try:
            lib = Library()
            lib.load(p)
        except Exception as e:                                   # noqa: BLE001
            self.dlg.say(f"Couldn't read {os.path.basename(p)}: {e}")
            return False
        if lib.is_master:
            self.dlg.say("That's a master list. Pick one of the provider projects instead.")
            return False
        if not lib.connection.get("server"):
            self.dlg.say("That project has no provider login saved, so its channels can't be played from the master.")
            return False
        self.lib, self.path = lib, p
        self.path_edit.setText(p)
        self.setTitle(self.title().split(":")[0] + f": {self.label}")
        cats = sorted({i.category for i in lib.items if i.kind == "live" and not i.deleted and not i.gone}, key=str.lower)
        self.cat.blockSignals(True)
        self.cat.clear()
        self.cat.addItem("All categories", None)
        for c in cats:
            self.cat.addItem(c, c)
        self.cat.blockSignals(False)
        self.dlg.update_indexes()
        self.refill()
        self.dlg.check_logins()
        return True

    def login_text(self):
        c = self.lib.connection if self.lib else {}
        host = c.get("server", "").split("//")[-1].rstrip("/")
        return f"Plays from: {c.get('username', '?')} @ {host}"

    def matching(self):
        if not self.lib:
            return []
        q = self.search.text().strip().lower()
        cat = self.cat.currentData()
        have = self.dlg.in_master(self) if self.hide_in.isChecked() else set()
        out = []
        for it in self.lib.ordered("live"):
            if it.deleted or it.gone or it.id in have:
                continue
            if cat is not None and it.category != cat:
                continue
            if self.favs.isChecked() and not it.fav:
                continue
            if q and q not in it.name.lower() and q not in it.category.lower():
                continue
            out.append(it)
        return out

    def refill(self, *_):
        items = self.shown = self.matching()
        n = min(len(items), self.MAX_ROWS)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(n)
        for r, it in enumerate(items[:n]):
            for c, text in enumerate((it.name, it.category, "★" if it.fav else "")):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.setUpdatesEnabled(True)
        total = sum(1 for i in self.lib.items if i.kind == "live" and not i.deleted and not i.gone) if self.lib else 0
        more = f" (showing the first {n:,}; narrow the search to see the rest)" if len(items) > n else ""
        self.status.setText(f"{len(items):,} of {total:,} Live channels{more}" if self.lib else "")

    def add_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        items = [self.shown[r] for r in rows if r < len(self.shown)]
        if items:
            self.dlg.add(self, items)

    def add_shown(self):
        if self.shown:
            self.dlg.add(self, list(self.shown))


class _MasterPane(QGroupBox):
    """The master list itself: see what's in it, take channels back out, change the order."""
    MAX_ROWS = 3000

    def __init__(self, dlg):
        super().__init__("Master list")
        self.dlg = dlg
        self.shown = []
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        f = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the master")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refill)
        self.cat = QComboBox()
        self.cat.setMinimumWidth(140)
        self.cat.currentIndexChanged.connect(self.refill)
        f.addWidget(self.search, 1)
        f.addWidget(self.cat)
        lay.addLayout(f)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Channel", "Category", "\u2605", "From"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(1, 130)
        lay.addWidget(self.table, 1)
        self.status = QLabel("")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.btns = {}
        for key, text, tip in (("top", "\u21c8 Top", "Move to the top"), ("up", "\u2191 Up", "Move up one place"),
                               ("down", "\u2193 Down", "Move down one place"), ("bottom", "\u21ca Bottom", "Move to the bottom")):
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self.move(k))
            self.btns[key] = b
            row.addWidget(b)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setAutoDefault(False)
        self.remove_btn.setToolTip("Take the selected channels out of the master (they stay in List A / List B).")
        self.remove_btn.clicked.connect(self.remove)
        row.addWidget(self.remove_btn)
        lay.addLayout(row)
        QShortcut(QKeySequence.Delete, self.table, activated=self.remove, context=Qt.WidgetShortcut)

    def filtering(self):
        return bool(self.search.text().strip()) or self.cat.currentData() is not None

    def refill(self, *_):
        m = self.dlg.master
        live = m.ordered("live")
        cats = sorted({i.category for i in live}, key=str.lower)
        keep = self.cat.currentData()
        self.cat.blockSignals(True)
        self.cat.clear()
        self.cat.addItem("All categories", None)
        for c in cats:
            self.cat.addItem(c, c)
        k = self.cat.findData(keep)
        self.cat.setCurrentIndex(max(k, 0))
        self.cat.blockSignals(False)
        q, cat = self.search.text().strip().lower(), self.cat.currentData()
        items = self.shown = [i for i in live if (cat is None or i.category == cat)
                              and (not q or q in i.name.lower() or q in i.category.lower())]
        n = min(len(items), self.MAX_ROWS)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(n)
        for r, it in enumerate(items[:n]):
            src = m.sources[it.src]["label"] if 0 <= it.src < len(m.sources) else ""
            for c, text in enumerate((it.name, it.category, "\u2605" if it.fav else "", src)):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.setUpdatesEnabled(True)
        per = {}
        for it in live:
            per[it.src] = per.get(it.src, 0) + 1
        parts = ", ".join(f"{c:,} from {m.sources[s]['label']}" for s, c in sorted(per.items()) if 0 <= s < len(m.sources))
        more = f" (showing the first {n:,})" if len(items) > n else ""
        self.setTitle(f"Master list: {len(live):,} channels")
        self.status.setText((parts or "Nothing added yet") + more)
        can = not self.filtering()
        for b in self.btns.values():
            b.setEnabled(can)
            b.setToolTip(b.toolTip().split(" (")[0] + ("" if can else " (clear the search and category first)"))

    def _selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.shown[r] for r in rows if r < len(self.shown)]

    def remove(self):
        items = self._selected()
        if items:
            self.dlg.remove(items)

    def move(self, how):
        items = self._selected()
        if items and not self.filtering():
            self.dlg.move(items, how)
            ids = {i.id for i in items}
            self.table.clearSelection()
            for r, it in enumerate(self.shown[:self.table.rowCount()]):
                if it.id in ids:
                    self.table.selectRow(r)


class MasterListDialog(QDialog):
    """Pick channels from two provider projects and collect them in a third, master project."""

    def __init__(self, parent, start_dir="", open_path=None, on_open=None):
        super().__init__(parent)
        from core import master
        self.M = master
        self.setWindowTitle("Build a master list")
        self.resize(1700, 780)
        self.start_dir, self.open_path, self.on_open = start_dir, open_path, on_open
        self.master, self.master_path = Library(), ""
        lay = QVBoxLayout(self)
        intro = QLabel("Pick channels from two provider projects and collect them in one master list. Each channel keeps "
                       "playing from the provider it came from, with the names, categories, logos and stars you already set. "
                       "The master is saved every time you add channels.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel("Master list file:"))
        self.mpath = QLineEdit()
        self.mpath.setReadOnly(True)
        self.mpath.setPlaceholderText("Choose a new file, or an existing master to add to")
        mb = QPushButton("Choose...")
        mb.setAutoDefault(False)
        mb.clicked.connect(self.choose_master)
        row.addWidget(self.mpath, 1)
        row.addWidget(mb)
        lay.addLayout(row)
        split = QSplitter()
        self.panes = [_SourcePane("List A", self), _SourcePane("List B", self)]
        for n, p in enumerate(self.panes):
            p.tag_edit.setText(self.M.default_tag(n))
        self.mpane = _MasterPane(self)
        for p in self.panes + [self.mpane]:
            split.addWidget(p)
        lay.addWidget(split, 1)
        bottom = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        bottom.addWidget(self.summary, 1)
        self.open_btn = QPushButton("Open the master")
        self.open_btn.setAutoDefault(False)
        self.open_btn.clicked.connect(self.open_master)
        self.open_btn.setEnabled(False)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        bottom.addWidget(self.open_btn)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        self.say("Choose the master file and the two lists to start.")

    def reload(self):
        for p in self.panes:
            p.refill()
        self.mpane.refill()

    def remove(self, items):
        m = self.master
        gone = {i.id for i in items}
        m.items = [i for i in m.items if i.id not in gone]
        for i in items:
            m.index.pop(i.key, None)
        self._saved(f"Removed {len(items):,} from the master. Master list now has {len(m.items):,} channels.")

    def move(self, items, how):
        order = self.master.ordered("live")
        sel = {i.id for i in items}
        if how in ("top", "bottom"):
            a, b = [i for i in order if i.id in sel], [i for i in order if i.id not in sel]
            order = a + b if how == "top" else b + a
        else:
            rng = range(len(order)) if how == "up" else range(len(order) - 1, -1, -1)
            d = -1 if how == "up" else 1
            for n in rng:
                j = n + d
                if order[n].id in sel and 0 <= j < len(order) and order[j].id not in sel:
                    order[n], order[j] = order[j], order[n]
        for n, it in enumerate(order):
            it.num = float(n)
        self._saved("Order changed.")

    def _saved(self, msg):
        self.master.dirty = True
        try:
            self.master.save(self.master_path)
        except OSError as e:
            self.say(f"Couldn't save the master: {e}")
            return
        self.say(msg)
        self.open_btn.setEnabled(bool(self.master.items))
        self.update_indexes()
        self.reload()

    def say(self, text):
        self.summary.setText(text)

    # ---- master file ----------------------------------------------------
    def choose_master(self):
        p, _ = QFileDialog.getSaveFileName(self, "Master list file", self.start_dir or os.path.expanduser("~"),
                                           "Xtream Editor projects (*.xtp)", options=QFileDialog.DontConfirmOverwrite)
        if p:
            self.set_master(p)

    def set_master(self, p):
        if not p.lower().endswith(".xtp"):
            p += ".xtp"
        if self.open_path and self.open_path() and os.path.abspath(self.open_path()) == os.path.abspath(p):
            self.say("That project is open in the editor right now. Pick a different file, or open something else first.")
            return False
        lib = Library()
        if os.path.exists(p):
            try:
                lib.load(p)
            except Exception as e:                               # noqa: BLE001
                self.say(f"Couldn't read that file: {e}")
                return False
            if lib.items and not lib.is_master:
                self.say("That file is an ordinary project, not a master list. Pick a new file name.")
                return False
        self.master, self.master_path = lib, p
        self.mpath.setText(p)
        self.open_btn.setEnabled(bool(lib.items))
        self.update_indexes()
        self.reload()
        self.say(f"Master list: {len(lib.items):,} channels." if lib.items else "New master list. Add some channels.")
        return True

    def check_logins(self):
        """Show each side's login, and warn when both sides would play from the same account."""
        a, b = (p.lib.connection if p.lib else None for p in self.panes)
        for p in self.panes:
            if p.lib:
                p.login_lbl.setText(p.login_text())
        same = bool(a and b and a.get("server", "").rstrip("/") == b.get("server", "").rstrip("/")
                    and a.get("username") == b.get("username"))
        for p in self.panes:
            p.login_lbl.setStyleSheet("color: #d9534f; font-weight: bold;" if same else "")
        if same:
            self.say("Heads up: List A and List B have the same login saved (same server and username), so the master "
                     "treats them as one provider and everything plays from that account. Open the project for the "
                     "other provider and use File > Connect to give it its own login, then pick it again here.")

    def update_indexes(self):
        """Match each pane to its entry in the master (so 'already in the master' works across sessions)."""
        for p in self.panes:
            p.src_idx = self.M.find_source(self.master, p.lib.connection) if p.lib else -1
            if p.src_idx >= 0 and not p.tag_touched:
                p.tag_edit.setText(self.M.tag_for(self.master, p.src_idx))

    def in_master(self, pane):
        if pane.src_idx < 0:
            return set()
        return {m.orig for m in self.master.items if m.src == pane.src_idx}

    # ---- adding ---------------------------------------------------------
    def add(self, pane, items):
        if not self.master_path:
            self.say("Choose the master list file first.")
            return
        idx = self.M.add_source(self.master, pane.lib.connection, pane.label, pane.tag_edit.text().strip())
        pane.src_idx = idx
        have = self.M.already_in(self.master, idx, items)
        items = [i for i in items if i.id not in have]
        if not items:
            self.say("Those are already in the master.")
            return
        replace = {}
        dups = self.M.duplicates(self.master, idx, items)
        if dups:
            box = QMessageBox(self)
            box.setWindowTitle("Already in the master")
            names = "\n".join(f"  {c.name}   (master has: {m.name} from "
                              f"{self.master.sources[m.src]['label']})" for c in items if c.id in dups
                              for m in [dups[c.id]])
            box.setText(f"{len(dups):,} of these look like channels the master already has from the other provider "
                        f"(same guide ID or same name).")
            box.setInformativeText("Add both, skip these, or replace the master's version with this one?")
            box.setDetailedText(names)
            both = box.addButton("Add both", QMessageBox.AcceptRole)
            skip = box.addButton("Skip these", QMessageBox.RejectRole)
            swap = box.addButton("Replace", QMessageBox.DestructiveRole)
            cancel = box.addButton(QMessageBox.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel or clicked is None:
                return
            if clicked is skip:
                items = [i for i in items if i.id not in dups]
            elif clicked is swap:
                replace = {k: v for k, v in dups.items()}
        if not items:
            self.say("Nothing added.")
            return
        added, swapped = self.M.add_items(self.master, idx, items, replace)
        try:
            self.master.save(self.master_path)
        except OSError as e:
            self.say(f"Couldn't save the master: {e}")
            return
        bits = [f"{added:,} added"] + ([f"{swapped:,} replaced"] if swapped else [])
        self.say(f"{', '.join(bits)}. Master list now has {len(self.master.items):,} channels.")
        self.open_btn.setEnabled(True)
        self.update_indexes()
        self.reload()

    def open_master(self):
        if self.on_open and self.master_path:
            self.on_open(self.master_path)
