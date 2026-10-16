"""Placeholder guide entries: so channels with no guide data don't show a blank row in your IPTV app.

Nothing here is stored on your items. When the option is on, a channel with no EPG ID is given a made-up
guide ID (xe.<stream id>) in what the server and exports hand out, and a block-by-block 'show' named after
the channel is added to the merged guide for every channel that has no real guide data."""
from __future__ import annotations

import time
from xml.sax.saxutils import escape, quoteattr

PREFIX = "xe."
BLOCK_HOURS = 3
DAYS_AHEAD = 3
DESCRIPTION = "No guide data from your provider."


def guide_id(it, placeholders):
    """The guide ID to hand out for a live channel."""
    return it.epg_id or (PREFIX + str(it.id) if placeholders else "")


def fill_entries(items):
    """{guide id: channel name} for live channels that might need a placeholder: the ones with no EPG ID,
    and the ones whose ID turns out to be in none of your guides (the merge checks that part)."""
    out = {}
    for it in items:
        if it.kind == "live" and not it.deleted and not it.gone:
            out.setdefault(guide_id(it, True), it.name)
    return out


def _ts(t):
    return time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(t))


def write_channels(out, need):
    for gid, name in need.items():
        out.write(f"<channel id={quoteattr(gid)}><display-name>{escape(name)}</display-name></channel>\n")


def write_programs(out, need, now=None):
    """One program per block, from one block ago to DAYS_AHEAD days from now, titled with the channel name."""
    step = BLOCK_HOURS * 3600
    start = int((now if now is not None else time.time()) // step) * step - step
    n = DAYS_AHEAD * 24 // BLOCK_HOURS + 1
    count = 0
    for gid, name in need.items():
        cid, title, desc = quoteattr(gid), escape(name), escape(DESCRIPTION)
        for i in range(n):
            t = start + i * step
            out.write(f'<programme start="{_ts(t)}" stop="{_ts(t + step)}" channel={cid}>'
                      f"<title>{title}</title><desc>{desc}</desc></programme>\n")
            count += 1
    return count
