"""Background jobs so the window never freezes."""
from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from core.common import Cancelled


class Task(QThread):
    progress = Signal(int, str)      # percent (-1 = unknown), message
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def is_cancelled(self):
        return self._cancel

    def run(self):
        try:
            res = self._fn(lambda p, m="": self.progress.emit(int(p), m), self.is_cancelled)
        except Cancelled:
            self.cancelled.emit()
            return
        except Exception as e:                          # noqa: BLE001 - shown to the user
            traceback.print_exc()
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.succeeded.emit(res)
