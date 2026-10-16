"""Data model: Item, plus Library (edits, undo/redo, re-sync merge, project save/load)."""
from __future__ import annotations

import gzip
import json
import os
import time

KINDS = ("live", "vod", "series")
KIND_LABEL = {"live": "Live", "vod": "Movie", "series": "Series"}
EDITABLE = ("name", "category", "logo", "epg_id")
MAX_UNDO = 30
PROJECT_VERSION = 1

_SHORT = (
    ("ci", "category_id"),
    ("l", "logo"),
    ("e", "epg_id"),
    ("x", "ext"),
    ("a", "added"),
    ("r", "rating"),
    ("p", "plot"),
)


class Item:
    __slots__ = (
        "kind", "id", "name", "category", "category_id", "logo", "epg_id",
        "ext", "num", "added", "rating", "plot", "arch",
        "deleted", "gone", "fav", "new", "edits", "episodes",
    )

    def __init__(self, kind, id, name="", category="Uncategorized", category_id="",
                 logo="", epg_id="", ext="", num=0.0, added="", rating="", plot=""):
        self.kind = kind
        self.id = str(id)
        self.name = name
        self.category = category
        self.category_id = category_id
        self.logo = logo
        self.epg_id = epg_id
        self.ext = ext
        self.num = float(num)
        self.added = added
        self.rating = rating
        self.plot = plot
        self.arch = 0             # live only: days of catch-up the provider keeps (0 = none)
        self.deleted = False      # user removed it from the list
        self.fav = False          # starred: also listed under "★ Favorites" on the server
        self.new = False          # arrived in the most recent re-sync (until you mark it seen)
        self.gone = False         # no longer on the server after a re-sync
        self.edits = set()        # which fields the user changed (kept on re-sync)
        self.episodes = None      # series only: list of dicts once fetched

    @property
    def key(self):
        return (self.kind, self.id)

    def to_dict(self):
        d = {"k": self.kind, "i": self.id, "n": self.name, "c": self.category}
        for short, attr in _SHORT:
            v = getattr(self, attr)
            if v:
                d[short] = v
        if self.num:
            d["o"] = self.num
        if self.deleted:
            d["d"] = 1
        if self.gone:
            d["g"] = 1
        if self.fav:
            d["f"] = 1
        if self.new:
            d["nw"] = 1
        if self.arch:
            d["ar"] = self.arch
        if self.edits:
            d["ed"] = sorted(self.edits)
        if self.episodes is not None:
            d["eps"] = self.episodes
        return d

    @classmethod
    def from_dict(cls, d):
        it = cls(d["k"], d["i"], d.get("n", ""), d.get("c", "Uncategorized"))
        for short, attr in _SHORT:
            if short in d:
                setattr(it, attr, d[short])
        it.num = float(d.get("o", 0.0))
        it.deleted = bool(d.get("d"))
        it.gone = bool(d.get("g"))
        it.fav = bool(d.get("f"))
        it.new = bool(d.get("nw"))
        it.arch = int(d.get("ar", 0) or 0)
        it.edits = set(d.get("ed", ()))
        it.episodes = d.get("eps")
        return it


class Library:
    def __init__(self):
        self.items = []
        self.index = {}
        self.connection = {}
        self.epg_sources = []        # extra XMLTV URLs (one string each)
        self.use_provider_epg = True
        self.undo_stack = []
        self.redo_stack = []
        self.dirty = False
        self.path = None

    # ---- basics -------------------------------------------------------
    def clear(self):
        self.items = []
        self.index = {}
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = False
        self.path = None

    def ordered(self, kind):
        return sorted((it for it in self.items if it.kind == kind), key=lambda it: it.num)

    def counts(self):
        out = {k: [0, 0] for k in KINDS}   # [active, deleted]
        for it in self.items:
            out[it.kind][1 if it.deleted else 0] += 1
        return out

    def categories(self, kind=None):
        return sorted({it.category for it in self.items if kind in (None, it.kind)},
                      key=str.lower)

    # ---- edits with undo ---------------------------------------------
    def change(self, changes, label=""):
        """changes: iterable of (item, field, new_value). Returns how many really changed."""
        recs = []
        for item, field, new in changes:
            old = getattr(item, field)
            if old == new:
                continue
            recs.append((item, field, old, new, field in item.edits))
        if not recs:
            return 0
        self._apply(recs, forward=True)
        self.undo_stack.append((label, recs))
        del self.undo_stack[:-MAX_UNDO]
        self.redo_stack.clear()
        self.dirty = True
        return len(recs)

    def _apply(self, recs, forward):
        seq = recs if forward else reversed(recs)
        for item, field, old, new, was_edited in seq:
            if forward:
                setattr(item, field, new)
                if field in EDITABLE:
                    item.edits.add(field)
            else:
                setattr(item, field, old)
                if field in EDITABLE and not was_edited:
                    item.edits.discard(field)

    def undo(self):
        if not self.undo_stack:
            return None
        label, recs = self.undo_stack.pop()
        self._apply(recs, forward=False)
        self.redo_stack.append((label, recs))
        self.dirty = True
        return label

    def redo(self):
        if not self.redo_stack:
            return None
        label, recs = self.redo_stack.pop()
        self._apply(recs, forward=True)
        self.undo_stack.append((label, recs))
        self.dirty = True
        return label

    @staticmethod
    def renumber_changes(order):
        """Turn a desired ordering (list of items of one kind) into num changes."""
        return [(it, "num", float(i)) for i, it in enumerate(order) if it.num != float(i)]

    def sort_az_changes(self, kinds=KINDS, categories=None, mode="category"):
        """num changes that put items in A-Z order, reusing the slots those items already occupy.
        mode "category": each category sorted on its own (categories keep their place relative to each other).
        mode "all": one big A-Z list per type, no matter the category. categories=None means every category."""
        from .sorting import sort_key
        changes = []
        for kind in kinds:
            groups = {}
            for it in self.ordered(kind):
                if categories is None or it.category in categories:
                    groups.setdefault(it.category if mode == "category" else None, []).append(it)
            for items in groups.values():
                slots = sorted(it.num for it in items)
                for it, num in zip(sorted(items, key=lambda i: (sort_key(i.name), i.num)), slots):
                    if it.num != num:
                        changes.append((it, "num", num))
        return changes

    # ---- re-sync with server -----------------------------------------
    def merge_server(self, fresh):
        """Fold freshly fetched items in. User edits survive; vanished items get flagged."""
        fresh_map = {it.key: it for it in fresh}
        first_load = not self.items
        newly_gone = 0
        for it in self.items:
            f = fresh_map.pop(it.key, None)
            if f is None:
                if not it.gone:
                    it.gone = True
                    newly_gone += 1
                continue
            it.gone = False
            for fld in ("name", "category", "logo", "epg_id"):
                if fld not in it.edits:
                    setattr(it, fld, getattr(f, fld))
            it.category_id = f.category_id
            it.ext = f.ext
            it.added = f.added
            it.rating = f.rating
            it.plot = f.plot
            it.arch = f.arch
        next_num = {k: -1.0 for k in KINDS}
        for it in self.items:
            if it.num > next_num[it.kind]:
                next_num[it.kind] = it.num
        added = 0
        newcomers = []
        for f in fresh_map.values():          # dict keeps server order
            next_num[f.kind] += 1
            f.num = next_num[f.kind]
            self.items.append(f)
            self.index[f.key] = f
            newcomers.append(f)
            added += 1
        if newcomers and not first_load:      # "New since last sync": only when something actually arrived
            for it in self.items:
                it.new = False
            for f in newcomers:
                f.new = True
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = True
        return {"added": added, "gone": newly_gone, "total": len(self.items)}

    # ---- project files -----------------------------------------------
    def save(self, path):
        data = {
            "version": PROJECT_VERSION,
            "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "connection": self.connection,
            "epg_sources": self.epg_sources,
            "use_provider_epg": self.use_provider_epg,
            "items": [it.to_dict() for it in self.items],
        }
        tmp = str(path) + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, path)
        self.path = str(path)
        self.dirty = False

    def load(self, path):
        with open(path, "rb") as f:
            magic = f.read(2)
        opener = gzip.open if magic == b"\x1f\x8b" else open
        with opener(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        self.clear()
        self.connection = data.get("connection", {})
        self.epg_sources = data.get("epg_sources", [])
        self.use_provider_epg = data.get("use_provider_epg", True)
        self.items = [Item.from_dict(d) for d in data.get("items", [])]
        self.index = {it.key: it for it in self.items}
        self.path = str(path)
        self.dirty = False
