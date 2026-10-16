"""Best-try name matching: "ESPN HD" ~ "US | ESPN", "Showtime" ~ "Showtime East / West", typos, and so on.
No UI in here, so it can be tested headless."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

STOP = {"hd", "fhd", "uhd", "sd", "4k", "hevc", "the", "raw", "vip"}
GOOD = 0.90            # best candidate at/above this = "Good" line
TICK = 0.885           # "tick good matches" ticks candidates at/above this (one extra word like East/West is OK, two is not)
SHOW = 0.45            # weaker than this isn't worth listing
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_PREFIX = re.compile(r"^\s*[A-Za-z]{2,3}\s*[|:]\s*")
_NONWORD = re.compile(r"[^a-z0-9]+")


def norm_tokens(name):
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _BRACKETS.sub(" ", s)
    s = _PREFIX.sub("", s)                      # "US | ", "UK: "
    s = s.lower().replace("&", " and ").replace("+", " plus ")
    return tuple(t for t in _NONWORD.split(s) if t and t not in STOP)


def parse_lines(text):
    """One entry per line. Skips blanks and section headers, strips bullets, numbers and tags like
    '(564)', '[already in Core]' or a trailing '*'. Handles the editor's own TXT export too."""
    out, seen = [], set()
    for raw in text.splitlines():
        s = raw.strip().lstrip("﻿")
        if not s or s.startswith("#") or s.startswith("=="):
            continue
        s = re.sub(r"^([-*•–]\s+|\d+[.)]\s+)", "", s)
        s = re.sub(r"\s*\[[^\]]*\]\s*$", "", s)
        s = re.sub(r"\s*\(\d{1,5}\)\s*$", "", s)
        s = s.rstrip("*").strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def score(qt, nt):
    jq, jn = "".join(qt), "".join(nt)
    if not jq or not jn:
        return 0.0
    if jq == jn:
        return 1.0
    qs, ns = set(qt), set(nt)
    if qs <= ns:                                 # every query word is in the name: East/West/extra words
        return max(0.78, 0.94 - 0.03 * (len(nt) - len(qt)))
    if ns <= qs:                                 # the name is a shorter form of what was typed
        return max(0.70, 0.90 - 0.04 * (len(qt) - len(nt)))
    best = SequenceMatcher(None, jq, jn, autojunk=False).ratio()
    jac = len(qs & ns) / len(qs | ns)
    s = min(0.89, 0.7 * best + 0.3 * jac)
    if len(jq) >= 4 and jn.startswith(jq):       # "first few letters"
        s = max(s, 0.82)
    return s


class NameIndex:
    """Index of item names built once, then searched many times."""

    def __init__(self, items):
        self.items = list(items)
        self.toks = [norm_tokens(it.name) for it in self.items]
        self.by_tok, self.by_pre = {}, {}
        for i, t in enumerate(self.toks):
            j = "".join(t)
            for w in set(t):
                self.by_tok.setdefault(w, []).append(i)
                if len(w) >= 3:
                    self.by_pre.setdefault(w[:3], []).append(i)
            if len(j) >= 3:
                self.by_pre.setdefault("j" + j[:3], []).append(i)

    def search(self, query, limit=40):
        qt = norm_tokens(query)
        if not qt:
            return []
        cand = set()
        for w in qt:
            cand.update(self.by_tok.get(w, ()))
            if len(w) >= 3:
                cand.update(self.by_pre.get(w[:3], ()))
        j = "".join(qt)
        if len(j) >= 3:
            cand.update(self.by_pre.get("j" + j[:3], ()))
        if not cand:
            return []
        qs = set(qt)
        if len(cand) > 600:                      # very common words: keep the likeliest by word overlap
            cand = sorted(cand, key=lambda i: -len(qs & set(self.toks[i])))[:600]
        out = []
        for i in cand:
            s = score(qt, self.toks[i])
            if s >= SHOW:
                out.append((s, i))
        out.sort(key=lambda p: (-p[0], self.items[p[1]].name.lower()))
        return [(s, self.items[i]) for s, i in out[:limit]]
