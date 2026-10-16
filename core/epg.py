"""XMLTV handling: download, scan channel ids, name-matching, streaming merge."""
from __future__ import annotations

import gzip
import hashlib
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from .common import CACHE_DIR, Cancelled, never_cancelled, noop_progress

try:                                   # optional, much faster on huge guides
    from lxml import etree as LET
except ImportError:                    # pragma: no cover
    LET = None


class EpgError(Exception):
    pass


# ---- files -------------------------------------------------------------
def local_path(src):
    """If `src` names a file on this PC (D:\\guides\\x.xml, a UNC path, or file:///D:/guides/x.xml)
    return it as a Path, else None (it's a web address)."""
    s = (src or "").strip().strip('"').strip("'").strip()
    if not s:
        return None
    if s.lower().startswith("file:"):
        u = urllib.parse.urlparse(s)
        p = urllib.request.url2pathname(urllib.parse.unquote(u.path))
        if u.netloc and u.netloc.lower() != "localhost":          # file://server/share/x.xml
            p = "\\\\" + u.netloc + p.replace("/", "\\")
        return Path(p)
    if "://" in s:
        return None
    if re.match(r"^[A-Za-z]:[\\/]", s) or s.startswith(("\\\\", "/", "~")) or os.path.exists(s):
        return Path(os.path.expanduser(s))
    return None


def normalize_source(src):
    """Tidy what the user typed or dropped: drop quotes, turn file:// addresses into plain paths."""
    s = (src or "").strip().strip('"').strip("'").strip()
    lp = local_path(s) if s.lower().startswith("file:") else None
    return str(lp) if lp else s


def label_for(src):
    lp = local_path(src)
    if lp:
        return lp.name or str(lp)
    return urllib.parse.urlparse(src).netloc or src


def local_stamp(src):
    """(mtime, size) of a local guide file, or None for web addresses / missing files."""
    lp = local_path(src)
    try:
        st = lp.stat() if lp else None
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size] if st else None


def cache_path(url):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".xml")


def source_path(src):
    """Where to read this guide from: the file itself if it's local, else its cached download."""
    return local_path(src) or cache_path(src)


def open_maybe_gz(path):
    with open(path, "rb") as f:
        magic = f.read(2)
    return gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")


def download(url, dest, ua, progress=None, cancelled=never_cancelled):
    lp = local_path(url)
    if lp:                                  # nothing to download, just make sure it's really there
        if not lp.is_file():
            raise EpgError(f"file not found: {lp}")
        return
    try:
        with requests.get(url, stream=True, headers={"User-Agent": ua},
                          timeout=(15, 120)) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if cancelled():
                        raise Cancelled()
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    except requests.RequestException as e:
        raise EpgError(f"{url}: {e}")


# ---- streaming iteration ---------------------------------------------------
def iter_top(f):
    """Yield <channel> and <programme> elements one at a time, freeing memory as we go."""
    if LET is not None:
        for _, el in LET.iterparse(f, events=("end",), tag=("channel", "programme"),
                                   recover=True, huge_tree=True):
            yield el
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
    else:
        root = None
        for ev, el in ET.iterparse(f, events=("start", "end")):
            if ev == "start":
                if root is None:
                    root = el
            elif el.tag in ("channel", "programme"):
                yield el
                root.clear()


def _to_str(el):
    if LET is not None:
        return LET.tostring(el, encoding="unicode", with_tail=False)
    el.tail = None
    return ET.tostring(el, encoding="unicode")


def scan_channels(path):
    """{channel_id: [display names]} from one XMLTV file."""
    chans = {}
    try:
        with open_maybe_gz(path) as f:
            for el in iter_top(f):
                if el.tag == "channel":
                    cid = el.get("id") or ""
                    if cid:
                        chans[cid] = [(d.text or "").strip()
                                      for d in el.findall("display-name") if d.text]
                elif chans:                 # first programme and we already have channels
                    break
    except (ET.ParseError, OSError, EOFError) as e:
        if not chans:
            raise EpgError(f"Could not read guide: {e}")
    return chans


# ---- name matching -------------------------------------------------------
_QUAL = re.compile(r"\b(uhd|fhd|hd|sd|4k|8k|hevc|h265|h264|raw|backup|multi|vip)\b")


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"^\s*\|[a-z]{2,3}\|\s*", "", s)
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", s)
    s = re.sub(r"^\s*[a-z]{2,3}\s*[:|]\s*", "", s)
    s = _QUAL.sub(" ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


class EpgIndex:
    def __init__(self):
        self.sources = []            # [(label, channel_count)]
        self.ids = set()
        self.by_name = {}

    def add(self, label, channels):
        self.sources.append((label, len(channels)))
        for cid, names in channels.items():
            self.ids.add(cid)
            for n in [cid] + list(names):
                k = norm(n)
                if k and k not in self.by_name:
                    self.by_name[k] = cid

    def has(self, cid):
        return cid in self.ids

    def match(self, name):
        k = norm(name)
        return self.by_name.get(k) if k else None


def refresh_sources(sources, ua, progress=noop_progress, cancelled=never_cancelled):
    """sources: [(label, url)]. Downloads each into the cache and scans it.
    Returns (EpgIndex, [error strings])."""
    idx, errors = EpgIndex(), []
    n = max(1, len(sources))
    for i, (label, url) in enumerate(sources):
        lo = int(100 * i / n)
        span = 100 / n

        def prog(done, total, lo=lo, span=span, label=label):
            frac = (done / total) if total else 0.5
            progress(int(lo + span * 0.9 * frac), f"Downloading {label} ({done // 1048576} MB)...")

        try:
            dest = source_path(url)
            download(url, dest, ua, prog, cancelled)
            progress(int(lo + span * 0.9), f"Scanning {label}...")
            idx.add(label, scan_channels(dest))
        except EpgError as e:
            errors.append(f"{label}: {e}")
    progress(100, "Done")
    return idx, errors


# ---- merge -------------------------------------------------------------------
def merge_xmltv(sources, wanted_ids, out_path, ua, gz=False,
                progress=noop_progress, cancelled=never_cancelled):
    """Merge cached guides into one file holding only `wanted_ids`.
    Earlier sources win when two have the same channel id.
    sources: [(label, url)] in priority order. Downloads any that aren't cached yet."""
    if not wanted_ids:
        raise EpgError("No EPG IDs on the channels being exported, nothing to merge.")
    paths = []
    for i, (label, url) in enumerate(sources):
        p = source_path(url)
        if not p.exists():
            progress(int(20 * i / max(1, len(sources))), f"Downloading {label}...")
            download(url, p, ua, None, cancelled)
        if not p.exists():
            raise EpgError(f"{label}: file not found: {p}")
        paths.append(p)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    opener = gzip.open if gz else open
    chosen, stats = {}, {"channels": 0, "programmes": 0}
    with opener(out_path, "wt", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<tv generator-info-name="Xtream Editor">\n')
        # pass 1: channels
        for i, p in enumerate(paths):
            progress(20 + int(30 * i / len(paths)), f"Merging channels from {sources[i][0]}...")
            seen_channel = False
            with open_maybe_gz(p) as f:
                for el in iter_top(f):
                    if cancelled():
                        raise Cancelled()
                    if el.tag == "channel":
                        seen_channel = True
                        cid = el.get("id")
                        if cid in wanted_ids and cid not in chosen:
                            chosen[cid] = i
                            out.write(_to_str(el) + "\n")
                    elif seen_channel:
                        break
        stats["channels"] = len(chosen)
        # pass 2: programmes
        for i, p in enumerate(paths):
            progress(50 + int(48 * i / len(paths)), f"Merging programmes from {sources[i][0]}...")
            n = 0
            with open_maybe_gz(p) as f:
                for el in iter_top(f):
                    if el.tag != "programme":
                        continue
                    if chosen.get(el.get("channel")) == i:
                        out.write(_to_str(el) + "\n")
                        stats["programmes"] += 1
                    n += 1
                    if n % 20000 == 0 and cancelled():
                        raise Cancelled()
        out.write("</tv>\n")
    progress(100, "Done")
    return stats
