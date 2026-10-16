"""M3U export."""
from __future__ import annotations

import csv
import os

from . import placeholder
from .common import Cancelled, never_cancelled, noop_progress
from .models import KIND_LABEL, KINDS
from .xtream import stream_url

GROUP_PREFIX = {"live": "", "vod": "Movies | ", "series": "Series | "}


def _attr(v):
    return str(v or "").replace('"', "'").replace("\r", " ").replace("\n", " ").strip()


def _extinf(tvg_id, name, logo, group):
    name = _attr(name)
    return (f'#EXTINF:-1 tvg-id="{_attr(tvg_id)}" tvg-name="{name}" '
            f'tvg-logo="{_attr(logo)}" group-title="{_attr(group)}",{name}')


def _entries(lib, kind, live_ext, prefix, stats, placeholders=False):
    conn = lib.connection
    for it in lib.ordered(kind):
        if it.deleted or it.gone:
            continue
        group = prefix + it.category
        if kind == "live":
            stats["live"] += 1
            yield _extinf(placeholder.guide_id(it, placeholders), it.name, it.logo, group), stream_url(conn, "live", it.id, live_ext)
        elif kind == "vod":
            stats["vod"] += 1
            yield _extinf("", it.name, it.logo, group), stream_url(conn, "vod", it.id, it.ext)
        else:
            if not it.episodes:
                stats["series_no_eps"] += 1
                continue
            for e in it.episodes:
                if e.get("skip"):
                    continue
                label = f"{it.name} S{int(e['season']):02d}E{int(e['ep']):02d}"
                if e.get("title"):
                    label += f" - {e['title']}"
                stats["series_eps"] += 1
                yield _extinf("", label, it.logo, group), stream_url(conn, "series", e["id"], e.get("ext"))


def _write_file(lib, path, kinds, live_ext, epg_header, prefix_groups, stats, cancelled, placeholders=False):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        head = "#EXTM3U"
        if epg_header:
            head += f' url-tvg="{epg_header}" x-tvg-url="{epg_header}"'
        f.write(head + "\n")
        n = 0
        for kind in kinds:
            prefix = GROUP_PREFIX[kind] if prefix_groups else ""
            for extinf, url in _entries(lib, kind, live_ext, prefix, stats, placeholders):
                f.write(extinf + "\n" + url + "\n")
                n += 1
                if n % 5000 == 0 and cancelled():
                    raise Cancelled()


def export_playlists(lib, out_dir, base, kinds, split=False, live_ext="ts",
                     epg_header="", prefix_groups=True,
                     progress=noop_progress, cancelled=never_cancelled, placeholders=False):
    """Write one combined M3U, or one per type. Returns stats incl. list of files."""
    os.makedirs(out_dir, exist_ok=True)
    stats = {"live": 0, "vod": 0, "series_eps": 0, "series_no_eps": 0, "files": []}
    kinds = [k for k in ("live", "vod", "series") if k in kinds]
    if split:
        plan = [([k], os.path.join(out_dir, f"{base}_{KIND_LABEL[k].lower()}.m3u")) for k in kinds]
    else:
        plan = [(kinds, os.path.join(out_dir, f"{base}.m3u"))]
    for i, (ks, path) in enumerate(plan):
        progress(int(100 * i / max(1, len(plan))), f"Writing {os.path.basename(path)}...")
        _write_file(lib, path, ks, live_ext, epg_header,
                    prefix_groups and not split, stats, cancelled, placeholders)
        stats["files"].append(path)
    progress(100, "Done")
    return stats


def list_rows(lib, kinds=KINDS, categories=None, skip_deleted=True, fav_only=False):
    """Items for a plain-text/CSV list, in playlist order. `categories` is None (all) or a set of
    (kind, category) pairs."""
    out = []
    for kind in KINDS:
        if kind not in kinds:
            continue
        for it in lib.ordered(kind):
            if it.gone or (skip_deleted and it.deleted) or (fav_only and not it.fav):
                continue
            if categories is not None and (kind, it.category) not in categories:
                continue
            out.append(it)
    return out


def export_list(lib, path, fmt="csv", kinds=KINDS, categories=None, skip_deleted=True, fav_only=False):
    """Write a simple list of what's in the playlist. CSV: Type, Name, Category (opens in Excel).
    TXT: names grouped under their category. Returns the number of items written."""
    items = list_rows(lib, kinds, categories, skip_deleted, fav_only)
    if fmt == "csv":
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Type", "Name", "Category"])
            for it in items:
                w.writerow([KIND_LABEL[it.kind], it.name, it.category])
    else:
        groups = {}
        for it in items:
            groups.setdefault(it.kind, {}).setdefault(it.category, []).append(it.name)
        lines = []
        for kind in KINDS:
            cats = groups.get(kind)
            if not cats:
                continue
            title = {"live": "LIVE TV", "vod": "MOVIES", "series": "SERIES"}[kind]
            lines += [f"##### {title} #####", ""]
            for cat in sorted(cats, key=str.lower):
                lines.append(f"== {cat} ({len(cats[cat]):,}) ==")
                lines += [f"  {n}" for n in cats[cat]]
                lines.append("")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))
    return len(items)
