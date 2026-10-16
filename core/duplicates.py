"""Duplicate finder: group entries that are probably the same movie / series / channel."""
from __future__ import annotations

import re
import unicodedata

# Words that describe the copy, not the title. Dropped when comparing.
QUALITY = {"hd", "fhd", "uhd", "sd", "4k", "8k", "hevc", "h265", "h264", "x264", "x265", "1080p", "720p",
           "2160p", "480p", "hdr", "hdr10", "60fps", "50fps", "raw"}
LANGUAGE = {"en", "eng", "english", "es", "spa", "spanish", "fr", "french", "de", "german", "it", "italian",
            "pt", "multi", "sub", "subs", "subbed", "dub", "dubbed", "vostfr", "audio"}
NOISE = QUALITY | LANGUAGE

_BRACKETS = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")
_YEAR = re.compile(r"^(?:19|20)\d\d$")
_PREFIX = re.compile(r"^\s*(?:[A-Za-z]{2,4}\s*[|┃│:]\s*|[A-Za-z]{2}\s+-\s+)")
_WORDS = re.compile(r"[^0-9a-z]+")


def title_key(name, ignore_year=False):
    """-> (key, year). 'US | The Matrix (1999) [HD]' and 'Matrix, The (1999)' style variants share a key."""
    s = name or ""
    year = ""

    def bracket(m):
        nonlocal year
        inner = m.group(1).strip()
        if _YEAR.match(inner):
            year = inner
            return " "
        words = [w for w in _WORDS.split(inner.lower()) if w]
        if words and all(w in NOISE for w in words):
            return " "
        return " " + inner + " "

    s = _PREFIX.sub("", s, count=1)
    s = _BRACKETS.sub(bracket, s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("&", " and ")
    words = [w for w in _WORDS.split(s) if w and w not in QUALITY]
    if words and words[0] == "the":
        words = words[1:]
    key = " ".join(words) or (name or "").strip().lower()
    return key, ("" if ignore_year else year)


def find_groups(items, kinds=("vod", "series"), scope="active", same_category=False, ignore_year=False):
    """Groups (lists of 2+ items, in list order) sharing a title. Biggest groups first.

    scope: 'active' (not deleted), 'fav', 'new', 'all' (everything, deleted included)."""
    pick = {
        "active": lambda it: not it.deleted,
        "fav": lambda it: it.fav and not it.deleted,
        "new": lambda it: it.new and not it.deleted,
        "all": lambda it: True,
    }[scope]
    buckets = {}
    for it in items:
        if it.kind not in kinds or it.gone or not pick(it):
            continue
        key, year = title_key(it.name, ignore_year)
        buckets.setdefault((it.kind, key, year, it.category if same_category else ""), []).append(it)
    groups = [sorted(g, key=lambda x: x.num) for g in buckets.values() if len(g) > 1]
    groups.sort(key=lambda g: (-len(g), title_key(g[0].name, ignore_year)[0]))
    return groups


def _added(it):
    try:
        return float(it.added)
    except (TypeError, ValueError):
        return 0.0


def _complete(it):
    return sum(1 for v in (it.logo, it.rating, it.plot, it.epg_id, it.ext) if v)


def keeper(group, rule="first"):
    """Which copy to keep: 'first' (earliest in your list), 'newest' (most recently added by the provider),
    'complete' (most info: logo, rating, plot...). Ties go to the one earliest in the list."""
    if rule == "newest":
        return max(group, key=lambda it: (_added(it), -it.num))
    if rule == "complete":
        return max(group, key=lambda it: (_complete(it), -it.num))
    return min(group, key=lambda it: it.num)
