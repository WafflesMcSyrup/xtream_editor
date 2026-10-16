"""Virtualized table model: only visible rows are ever touched, so 100k+ rows stay snappy."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from core.models import KIND_LABEL

COLS = ["#", "Name", "Category", "EPG ID", "Logo URL", "Type", "Status"]
FIELD = {1: "name", 2: "category", 3: "epg_id", 4: "logo"}

_EDITED_BG = QBrush(QColor(255, 215, 0, 55))
_GONE_FG = QBrush(QColor(210, 120, 30))
_DEL_FG = QBrush(QColor(140, 140, 140))
_BAD_EPG_FG = QBrush(QColor(220, 60, 60))


def status_text(it):
    if it.deleted:
        return "deleted"
    if it.gone:
        return "gone from server"
    if it.edits:
        return "edited"
    if it.new:
        return "new"
    return ""


class ItemModel(QAbstractTableModel):
    def __init__(self, on_edit, parent=None):
        super().__init__(parent)
        self.rows = []
        self.on_edit = on_edit          # callback(item, field, value)
        self.epg_has = None             # callable(epg_id) -> bool, or None if no guide scanned
        self.sort_col = 0
        self.sort_desc = False
        self._del_font = QFont()
        self._del_font.setItalic(True)
        self._del_font.setStrikeOut(True)

    # ---- data ----------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        it = self.rows[index.row()]
        c = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            if c == 0:
                return int(it.num) + 1
            if c == 1:
                return "\u2605 " + it.name if it.fav and role == Qt.DisplayRole else it.name
            if c == 2:
                return it.category
            if c == 3:
                return it.epg_id
            if c == 4:
                return it.logo
            if c == 5:
                return KIND_LABEL[it.kind]
            return status_text(it)
        if role == Qt.ForegroundRole:
            if it.deleted:
                return _DEL_FG
            if it.gone:
                return _GONE_FG
            if c == 3 and it.kind == "live" and it.epg_id and self.epg_has \
                    and not self.epg_has(it.epg_id):
                return _BAD_EPG_FG
            return None
        if role == Qt.FontRole:
            return self._del_font if it.deleted else None
        if role == Qt.BackgroundRole:
            f = FIELD.get(c)
            if f and f in it.edits:
                return _EDITED_BG
            return None
        if role == Qt.ToolTipRole and c == 3 and it.kind == "live" and it.epg_id \
                and self.epg_has and not self.epg_has(it.epg_id):
            return "This EPG ID isn't in any of your scanned guides"
        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        c = index.column()
        if c in FIELD:
            it = self.rows[index.row()]
            if c != 3 or it.kind == "live":
                f |= Qt.ItemIsEditable
        return f

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        field = FIELD.get(index.column())
        if not field:
            return False
        value = str(value).strip()
        it = self.rows[index.row()]
        if field == "name" and not value:
            return False
        if field == "category" and not value:
            value = "Uncategorized"
        self.on_edit(it, field, value)
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), len(COLS) - 1))
        return True

    # ---- rows / sorting --------------------------------------------------
    def _key(self):
        c = self.sort_col
        if c == 0:
            return lambda it: it.num
        if c == 1:
            return lambda it: it.name.lower()
        if c == 2:
            return lambda it: (it.category.lower(), it.num)
        if c == 3:
            return lambda it: it.epg_id.lower()
        if c == 4:
            return lambda it: it.logo.lower()
        if c == 5:
            return lambda it: (it.kind, it.num)
        return status_text

    def _sorted(self, rows):
        rows.sort(key=lambda it: it.num)           # stable base order
        if self.sort_col != 0 or self.sort_desc:
            rows.sort(key=self._key(), reverse=self.sort_desc)
        return rows

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = self._sorted(list(rows))
        self.endResetModel()

    def sort(self, column, order=Qt.AscendingOrder):
        self.sort_col = column
        self.sort_desc = order == Qt.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self.rows = self._sorted(self.rows)
        self.layoutChanged.emit()

    def sorted_by_order(self):
        return self.sort_col == 0 and not self.sort_desc

    def refresh_all(self):
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLS) - 1))
