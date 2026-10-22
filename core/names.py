"""Name manager: bulk tidy-ups for item names (case, spaces, prefixes, find and replace). Pure text, no UI."""
from __future__ import annotations

import re

from .casing import proper_case

OPS = (("Proper Case", "proper"), ("UPPERCASE", "upper"), ("lowercase", "lower"),
       ("Trim extra spaces", "trim"), ("Remove a prefix", "prefix"), ("Find and replace", "replace"),
       ("Add source tag, like [A] (master lists)", "addtag"), ("Remove source tag (master lists)", "rmtag"))
MASTER_OPS = ("addtag", "rmtag")
_SPACES = re.compile(r"\s+")


def new_name(name, op, extra=(), prefix="", find="", repl="", ignore_case=True):
    """The name after one tidy-up. Never returns an empty name (the old one is kept instead)."""
    if op == "proper":
        out = proper_case(name, extra)
    elif op == "upper":
        out = name.upper()
    elif op == "lower":
        out = name.lower()
    elif op == "trim":
        out = _SPACES.sub(" ", name).strip()
    elif op == "prefix":
        pre = prefix.strip()
        out = name
        if pre and name.lstrip().lower().startswith(pre.lower()):
            out = name.lstrip()[len(pre):].strip()
    elif op == "replace":
        out = name
        if find:
            out = re.sub(re.escape(find), lambda m: repl, name, flags=re.IGNORECASE if ignore_case else 0)
        out = _SPACES.sub(" ", out).strip() if out != name else out
    else:
        out = name
    return out if out.strip() else name


def add_tag(name, tag):
    """'[A] name'. Leaves the name alone when it already starts with that tag."""
    tag = tag.strip()
    if not tag or name.startswith(f"[{tag}]"):
        return name
    return f"[{tag}] {name}"


def remove_tag(name, tags):
    """Takes a leading '[tag] ' off, for any of the given tags."""
    for t in tags:
        t = t.strip()
        if t and name.startswith(f"[{t}]"):
            rest = name[len(t) + 2:].strip()
            return rest or name
    return name


def plan(items, op, tags=(), **kw):
    """[(item, new name)] for the items whose name would change. Deleted and gone items are skipped.
    tags: a master list's source tags, indexed by Item.src (only the two source-tag actions use them)."""
    out = []
    for it in items:
        if it.deleted or it.gone:
            continue
        if op in MASTER_OPS:
            if not 0 <= it.src < len(tags):
                continue                                    # not a master-list channel
            new = add_tag(it.name, tags[it.src]) if op == "addtag" else remove_tag(it.name, [tags[it.src]] + list(tags))
            if new != it.name:
                out.append((it, new))
            continue
        new = new_name(it.name, op, **kw)
        if new != it.name:
            out.append((it, new))
    return out
