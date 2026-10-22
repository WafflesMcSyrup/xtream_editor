"""Regex rules: tidy names, move items into clean categories, or delete them, in bulk."""
from __future__ import annotations

import re

KIND_CHOICES = (("All types", "all"), ("Live", "live"), ("Movies", "vod"), ("Series", "series"))
FIELD_CHOICES = (("Item name", "name"), ("Category", "category"))

_DOLLAR = re.compile(r"\$\{(\d+)\}|\$(\d+)")
_REFS = re.compile(r"\\g<(\d+)>|\\(\d+)")


# Superscript and subscript letters/numbers (ᴴᴰ, ⁶⁰ᶠᵖˢ, ᴿᴬᵂ, ², ...) and the space in front of them
_SUPER = (r"\s*[\u00B2\u00B3\u00B9\u02B0-\u02B8\u02E0-\u02E4\u1D2C-\u1D6A\u1D78\u1D9B-\u1DBF\u2070-\u209F]+")
# Two-letter country/language codes in front of a pipe: "US| CNN", "US | CNN", "|US| CNN", "[UK] BBC"
_CODES = ("US|UK|USA|CA|AU|NZ|IE|DE|FR|ES|IT|PT|NL|BE|CH|AT|SE|NO|DK|FI|PL|RU|TR|GR|MX|BR|AR|IN|PK|ZA|AE|SA|QA|"
          "KW|IL|JP|KR|CN|HK|TW|SG|MY|TH|PH|ID|VN|EN")
_COUNTRY = (r"^\s*(?:[|\u2503\u2502]\s*)?(?:(?:" + _CODES + r")\s*[|\u2503\u2502]|\[(?:" + _CODES + r")\])\s*")

# Ready-made rules that ship with the app. They can be switched on and off but not edited or deleted
# (Copy makes an editable version). Only their on/off state is saved in your settings.
BUILTIN = (
    {"id": "super_names", "name": "Remove superscript text (names)", "kinds": "all", "field": "name",
     "pattern": _SUPER, "ignore_case": True, "rewrite_on": True, "rewrite": "", "move": "", "delete": False,
     "note": "Takes the little raised letters and numbers (like ᴴᴰ or ⁶⁰ᶠᵖˢ) out of item names."},
    {"id": "super_cats", "name": "Remove superscript text (categories)", "kinds": "all", "field": "category",
     "pattern": _SUPER, "ignore_case": True, "rewrite_on": True, "rewrite": "", "move": "", "delete": False,
     "note": "The same for category names. Two categories that end up with the same name are merged."},
    {"id": "country_names", "name": "Remove country prefixes (names)", "kinds": "all", "field": "name",
     "pattern": _COUNTRY, "ignore_case": True, "rewrite_on": True, "rewrite": "", "move": "", "delete": False,
     "note": "Takes a prefix like \"US| \", \"UK | \", \"|US| \" or \"[CA] \" off the start of item names."},
    {"id": "country_cats", "name": "Remove country prefixes (categories)", "kinds": "all", "field": "category",
     "pattern": _COUNTRY, "ignore_case": True, "rewrite_on": True, "rewrite": "", "move": "", "delete": False,
     "note": "The same for category names. Careful: \"US | Sports\" and \"UK | Sports\" would both become "
             "\"Sports\" and merge."},
)


def builtin_rules(states=None):
    """The built-in rules as normal rule dicts (plus 'builtin', 'id' and 'note'); 'on' comes from the saved
    states {id: bool}. They start switched off."""
    states = states if isinstance(states, dict) else {}
    out = []
    for b in BUILTIN:
        r = normalize(b)
        r.update(builtin=True, id=b["id"], note=b["note"], on=bool(states.get(b["id"], False)))
        out.append(r)
    return out


def new_rule():
    return {"name": "", "on": True, "kinds": "all", "field": "name", "only_cat": "", "pattern": "", "ignore_case": True,
            "rewrite_on": False, "rewrite": "", "move": "", "delete": False}


def normalize(r):
    """Fill in anything missing (rules come from a settings file the user could have edited)."""
    out = new_rule()
    if isinstance(r, dict):
        out.update({k: r[k] for k in out if k in r})
    out["on"] = bool(out["on"])
    out["ignore_case"] = bool(out["ignore_case"])
    out["rewrite_on"] = bool(out["rewrite_on"])
    out["delete"] = bool(out["delete"])
    if out["kinds"] not in {k for _, k in KIND_CHOICES}:
        out["kinds"] = "all"
    if out["field"] not in {k for _, k in FIELD_CHOICES}:
        out["field"] = "name"
    for k in ("name", "only_cat", "pattern", "rewrite", "move"):
        out[k] = str(out[k] or "")
    return out


def template(text):
    """$1 and ${1} work like \\1 (people expect both)."""
    return _DOLLAR.sub(lambda m: "\\g<%s>" % (m.group(1) or m.group(2)), text)


def compile_rule(rule):
    """-> (compiled regex or None, error text)."""
    pat = rule.get("pattern", "")
    if not pat:
        return None, "Type a pattern."
    try:
        rx = re.compile(pat, re.IGNORECASE if rule.get("ignore_case", True) else 0)
    except re.error as e:
        return None, f"Not a valid pattern: {e}"
    if rule.get("rewrite_on"):
        refs = [int(a or b) for a, b in _REFS.findall(template(rule.get("rewrite", "")))]
        if refs and max(refs) > rx.groups:
            return None, f"The replacement uses group {max(refs)}, but the pattern only has {rx.groups}."
    if not (rule.get("rewrite_on") or rule.get("move", "").strip() or rule.get("delete")):
        return None, "Choose what to do with matches (rewrite, move or delete)."
    return rx, ""


def plan(items, rules):
    """Run the enabled rules in order, each one seeing the result of the one before.

    -> (changes, matches, errors)
       changes: {item.key: {'item', 'name', 'category', 'deleted'}} for items that end up different
       matches: [count per rule]; errors: {rule index: text}"""
    state = {}
    matches = [0] * len(rules)
    errors = {}
    for ri, rule in enumerate(rules):
        if not rule.get("on", True):
            continue
        rx, err = compile_rule(rule)
        if err:
            errors[ri] = err
            continue
        field, kinds = rule["field"], rule["kinds"]
        repl = template(rule["rewrite"]) if rule["rewrite_on"] else None
        move = rule["move"].strip()
        only = rule["only_cat"].strip().casefold()          # blank = every category
        try:
            for it in items:
                if it.deleted or it.gone or (kinds != "all" and it.kind != kinds):
                    continue
                st = state.get(it.key)
                if st is None:
                    st = state[it.key] = {"item": it, "name": it.name, "category": it.category, "deleted": False}
                if st["deleted"]:
                    continue
                if only and st["category"].casefold() != only:     # only items in that category (as of this rule)
                    continue
                cur = st[field]
                if not rx.search(cur):
                    continue
                matches[ri] += 1
                if repl is not None:
                    new = rx.sub(repl, cur).strip()
                    if new:                               # never blank a name or category
                        st[field] = new
                if move:
                    st["category"] = move
                if rule["delete"]:
                    st["deleted"] = True
        except (re.error, IndexError) as e:
            errors[ri] = f"The replacement doesn't work with this pattern: {e}"
    changed = {k: st for k, st in state.items()
               if st["deleted"] or st["name"] != st["item"].name or st["category"] != st["item"].category}
    return changed, matches, errors


def to_changes(changed):
    """The (item, field, value) list that Library.change() takes."""
    out = []
    for st in changed.values():
        it = st["item"]
        if st["deleted"]:
            out.append((it, "deleted", True))
        if st["name"] != it.name:
            out.append((it, "name", st["name"]))
        if st["category"] != it.category:
            out.append((it, "category", st["category"]))
    return out
