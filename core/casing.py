"""Proper-case suggestions for category names (pure text, no UI)."""
from __future__ import annotations

import re

SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "of", "on", "or",
         "the", "to", "vs", "via", "with", "de", "la", "le", "el", "du", "des", "und", "et"}
# Always uppercase (structure, not names of channels or leagues)
STRUCTURAL = {"uk", "usa", "us", "uae", "eu", "hd", "fhd", "uhd", "sd", "hdr", "tv", "vod", "iptv", "epg", "dvd",
              "diy", "vip", "ii", "iii", "iv", "vi", "vii", "viii", "ix", "xi", "xii"}
# Default "standard" list of channel / league acronyms; the user can edit it in the Category manager.
DEFAULT_STANDARD = ("ESPN, ABC, CBS, NBC, FOX, BBC, BBCI, AMC, AMC+, MGM, MGM+, AFL, NFL, MLB, NBA, WNBA, NCAA, "
                    "HBO, FX, PPV, HVEC, HEVC, GP, BTN, FIFA, FLO, MILB, MLS, NCAAB, NCAAF, NFHS, NHL, PBS")
COUNTRY_CODES = {"ca", "au", "nz", "ie", "de", "fr", "es", "it", "pt", "nl", "be", "ch", "at", "se", "no", "dk",
                 "fi", "pl", "ru", "tr", "gr", "mx", "br", "ar", "in", "pk", "za", "ae", "sa", "qa", "kw", "il",
                 "jp", "kr", "cn", "hk", "tw", "sg", "my", "th", "ph", "id", "vn"}
# two-letter country codes only count as acronyms right in front of a separator ("DE | Sport")
_TOKEN = re.compile(r"[A-Za-z0-9À-ɏ']+|[^A-Za-z0-9À-ɏ']+")
_SEG_BREAK = re.compile(r"[|:]|\s[-–—]\s")


def parse_extra(text):
    """'bbc, itv espn' -> {'bbc','itv','espn'}"""
    return {w.lower().strip("+") for w in re.split(r"[,\s]+", text or "") if w.strip("+")}


def _word(tok, first, extra, before_sep):
    low = tok.lower()
    if low in extra or low in STRUCTURAL:
        return tok.upper()
    if before_sep and low in COUNTRY_CODES:
        return tok.upper()
    if any(c.isdigit() for c in tok):                 # 24, 4K, 1080p, S01, 3D ...
        return tok.upper() if re.fullmatch(r"\d+[kKdD]", tok) else tok
    if tok != tok.upper() and tok != tok.lower():     # already mixed (BritBox, iPlayer, McDonald): leave it
        return tok
    if not first and low in SMALL:
        return low
    return low[:1].upper() + low[1:]


def proper_case(name, extra=()):
    extra = {w.lower() for w in extra}
    parts = _TOKEN.findall(name)
    out = []
    first = True
    for i, p in enumerate(parts):
        if not re.match(r"[A-Za-z0-9À-ɏ']", p):
            out.append(p)
            if _SEG_BREAK.search(p):
                first = True
            continue
        rest = "".join(parts[i + 1:i + 2])
        before_sep = bool(re.match(r"\s*[|:]", rest)) or bool(re.match(r"\s+[-–—]\s", rest))
        out.append(_word(p, first, extra, before_sep))
        first = False
    return "".join(out)
