"""A-Z sort keys for channel / movie / series names."""
from __future__ import annotations

import re
import unicodedata

_DIGITS = re.compile(r"(\d+)")


def sort_key(name):
    """Case/accents ignored, leading symbols and 'The ' ignored, numbers in natural order (2 before 10)."""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().strip()
    s = re.sub(r"^[^0-9a-z]+", "", s)                  # leading ★ # | ( etc.
    s = re.sub(r"^the\s+", "", s)
    return [(1, int(p)) if p.isdigit() else (0, p) for p in _DIGITS.split(s) if p != ""]
