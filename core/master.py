"""Master lists: pick channels from two (or more) projects and collect them in a third.

A master project is an ordinary .xtp whose channels each remember which provider they came from
(Library.sources + Item.src/Item.orig). The master's own channel ids are fresh numbers, so two providers
that both have a "stream 101" never clash."""
from __future__ import annotations

from .matcher import norm_tokens
from .models import Item, Library


def source_label(path):
    import os
    return os.path.splitext(os.path.basename(path or ""))[0] or "List"


def find_source(master, conn):
    """Index of this login in master.sources (same server + username), or -1."""
    for n, s in enumerate(master.sources):
        if s["conn"].get("server", "").rstrip("/") == conn.get("server", "").rstrip("/") \
                and s["conn"].get("username") == conn.get("username"):
            return n
    return -1


def default_tag(n):
    """A, B, C ... for the first sources, then 27, 28 ..."""
    return chr(65 + n) if n < 26 else str(n + 1)


def tag_for(master, n):
    """The short tag for source n (what goes between the brackets in names like [A] ESPN)."""
    if 0 <= n < len(master.sources):
        return master.sources[n].get("tag") or default_tag(n)
    return ""


def add_source(master, conn, label, tag=""):
    n = find_source(master, conn)
    if n >= 0:
        master.sources[n]["conn"] = dict(conn)            # keep the newest password
        if tag:
            master.sources[n]["tag"] = tag
        return n
    master.sources.append({"label": label, "conn": dict(conn), "tag": tag or default_tag(len(master.sources))})
    return len(master.sources) - 1


def _name_key(it):
    return " ".join(norm_tokens(it.name))


def duplicates(master, src_idx, cand):
    """Channels already in the master that look like `cand` (items from source `src_idx`) but come from a
    different provider: same EPG ID, or the same normalized name. Returns {cand id: master item}."""
    by_epg, by_name = {}, {}
    for m in master.items:
        if m.kind != "live" or m.deleted or m.src == src_idx:
            continue
        if m.epg_id:
            by_epg.setdefault(m.epg_id.lower(), m)
        by_name.setdefault(_name_key(m), m)
    out = {}
    for c in cand:
        hit = by_epg.get(c.epg_id.lower()) if c.epg_id else None
        hit = hit or (by_name.get(_name_key(c)) if _name_key(c) else None)
        if hit:
            out[c.id] = hit
    return out


def already_in(master, src_idx, items):
    have = {(m.src, m.orig) for m in master.items}
    return {it.id for it in items if (src_idx, it.id) in have}


def add_items(master, src_idx, items, replace=None):
    """Copy `items` (Live items from a source project) into the master, keeping their edits. `replace` maps a
    source item id to the master item it should take over (the other provider's version leaves the list).
    Returns (added, replaced)."""
    replace = replace or {}
    nxt = max((int(m.id) for m in master.items if m.id.isdigit()), default=0) + 1
    pos = max((m.num for m in master.items if m.kind == "live"), default=-1.0) + 1
    added = swapped = 0
    for it in sorted(items, key=lambda i: i.num):
        old = replace.get(it.id)
        n = Item("live", str(nxt), it.name, it.category, it.category_id, it.logo, it.epg_id, it.ext,
                 old.num if old else pos, it.added, it.rating, it.plot)
        nxt += 1
        n.arch, n.fav, n.src, n.orig = it.arch, it.fav, src_idx, it.id
        n.edits = set(it.edits)
        if old:
            master.items.remove(old)
            master.index.pop(old.key, None)
            swapped += 1
        else:
            pos += 1
            added += 1
        master.items.append(n)
        master.index[n.key] = n
    master.dirty = True
    return added, swapped
