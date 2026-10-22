"""Copy your edits from one project onto another (same channels, different provider). Pure logic, no UI."""
from __future__ import annotations

from .matcher import norm_tokens

OPTIONS = (("deleted", "Delete the channels you deleted in the other list"),
           ("fav", "Favorites (the star)"),
           ("name", "Names"),
           ("category", "Categories"),
           ("logo", "Logos (when the other list has one)"),
           ("epg", "EPG IDs you set by hand"),
           ("order", "The order of the channels"),
           ("mark_new", "Mark channels the other list doesn't have as new"))
DEFAULTS = {k: True for k, _ in OPTIONS}
DEFAULTS["fav_only"] = False        # only the channels starred in the other list (do the important ones first)


def _live(items):
    return [it for it in items if it.kind == "live" and not it.gone]


def match(src, dst):
    """Pair up the live channels of the source project with those of the target.
    -> (pairs [(src item, dst item, how)], only_dst, only_src_kept, ambiguous [(src items, dst items)])"""
    src, dst = _live(src), _live(dst)
    pairs, left_s, left_d = [], [], []

    def by(items, keyfn):
        out = {}
        for it in items:
            k = keyfn(it)
            if k:
                out.setdefault(k, []).append(it)
        return out

    # 1. the same EPG ID, when it picks out exactly one channel on each side
    es, ed = by(src, lambda i: i.epg_id.strip().lower()), by(dst, lambda i: i.epg_id.strip().lower())
    used_s, used_d = set(), set()
    for k, a in es.items():
        b = ed.get(k)
        if b and len(a) == 1 and len(b) == 1:
            pairs.append((a[0], b[0], "EPG ID"))
            used_s.add(id(a[0]))
            used_d.add(id(b[0]))
    left_s = [i for i in src if id(i) not in used_s]
    left_d = [i for i in dst if id(i) not in used_d]

    # 2. the same name once prefixes, quality tags and so on are ignored
    ns, nd = by(left_s, lambda i: norm_tokens(i.name)), by(left_d, lambda i: norm_tokens(i.name))
    ambiguous = []
    for k, a in ns.items():
        b = nd.get(k)
        if not b:
            continue
        if len(a) == 1 and len(b) == 1:
            pairs.append((a[0], b[0], "name"))
            used_s.add(id(a[0]))
            used_d.add(id(b[0]))
            continue
        cs, cd = by(a, lambda i: norm_tokens(i.category)), by(b, lambda i: norm_tokens(i.category))
        for ck, x in cs.items():
            y = cd.get(ck)
            if y and len(x) == 1 and len(y) == 1:
                pairs.append((x[0], y[0], "name + category"))
                used_s.add(id(x[0]))
                used_d.add(id(y[0]))
        rest_a = [i for i in a if id(i) not in used_s]
        rest_b = [i for i in b if id(i) not in used_d]
        if rest_a and rest_b:
            ambiguous.append((rest_a, rest_b))
    only_dst = [i for i in dst if id(i) not in used_d and not any(i in bs for _, bs in ambiguous)]
    only_src = [i for i in src if id(i) not in used_s and not i.deleted and not any(i in a for a, _ in ambiguous)]
    return pairs, only_dst, only_src, ambiguous


def plan(src_items, dst_items, opts=None):
    """What to change on the target so it follows the source.
    -> dict: pairs, only_dst, only_src, ambiguous, deleted_there [(src, dst)], changes [(item, field, value)],
             rows [(dst item, src item, how, [texts])], counts {field: n}"""
    o = dict(DEFAULTS)
    o.update(opts or {})
    pairs, only_dst, only_src, ambiguous = match(src_items, dst_items)
    if o["fav_only"]:                               # just the starred ones; the whole-list steps wait for the next pass
        pairs = [p for p in pairs if p[0].fav and not p[0].deleted]
        only_src = [a for a in only_src if a.fav]
        ambiguous = [(xs, ys) for xs, ys in ambiguous if any(x.fav for x in xs)]
        only_dst = []
        o["order"] = o["mark_new"] = False
    gone_there = [(a, b) for a, b, _ in pairs if a.deleted and not b.deleted]     # deleted in the other list, still here
    changes, rows, counts = [], [], {}

    def add(b, field, value, text, texts):
        changes.append((b, field, value))
        counts[field] = counts.get(field, 0) + 1
        if text:
            texts.append(text)

    for a, b, how in pairs:
        texts = []
        if o["deleted"] and a.deleted != b.deleted:
            add(b, "deleted", a.deleted, "Delete" if a.deleted else "Restore", texts)
        if not a.deleted:
            if o["fav"] and a.fav != b.fav:
                add(b, "fav", a.fav, "Favorite" if a.fav else "Un-favorite", texts)
            if o["name"] and a.name != b.name:
                add(b, "name", a.name, f"Name: {a.name}", texts)
            if o["category"] and a.category != b.category:
                add(b, "category", a.category, f"Category: {a.category}", texts)
            if o["logo"] and a.logo and a.logo != b.logo:
                add(b, "logo", a.logo, "Logo", texts)
            if o["epg"] and "epg_id" in a.edits and a.epg_id != b.epg_id:
                add(b, "epg_id", a.epg_id, f"EPG ID: {a.epg_id}", texts)
        if b.new:                                   # accounted for now, so it isn't "new" any more
            add(b, "new", False, "", texts)
        if texts:
            rows.append((b, a, how, texts))
    if o["mark_new"]:
        for b in only_dst:
            if not b.new and not b.deleted:
                add(b, "new", True, "", [])
                rows.append((b, None, "only in this list", ["Mark as new"]))
    if o["order"]:
        pos = {id(b): a.num for a, b, _ in pairs}
        order = sorted(_live(dst_items), key=lambda b: (0, pos[id(b)], b.num) if id(b) in pos else (1, b.num, 0))
        # keep the target's non-live items out of it: only live channels are renumbered
        moves = [(it, "num", float(i)) for i, it in enumerate(order) if it.num != float(i)]
        changes.extend(moves)
        counts["num"] = len(moves)
    return {"pairs": pairs, "only_dst": only_dst, "only_src": only_src, "ambiguous": ambiguous,
            "deleted_there": gone_there, "changes": changes, "rows": rows, "counts": counts}
