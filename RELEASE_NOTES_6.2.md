## Xtream Editor 6.2

Four new tools and a bit of polish.

**What's new**
- **Duplicate finder** (Ctrl+Shift+U): finds the same movie, series or channel across different names, prefixes, quality tags and years. Keep, delete, rename or move, or auto-pick the best copy. Confirmation popup and an Undo last action button.
- **Regex rules** (Ctrl+Shift+R): saved rules to clean up names, move items into tidy categories, or delete junk. Preview before you apply, one undo step.
- **Placeholder guide entries**: channels with no guide data get a simple program block so IPTV apps still list them. Off by default. Server window tick box, `--placeholder-epg` for headless, or tick it on export.
- **Remembers your layout**: window size, position, splitter and columns.

**Changes**
- "Programmes" is now "programs" in the interface and messages.
- Guide status counts placeholder programs in the total.

**Getting it**
- Windows: download the programs from the assets below, no Python needed. Windows may show a SmartScreen warning because the apps aren't code-signed; choose *More info > Run anyway*.
- Any system: grab the source zip and run `python main.py` (needs Python 3.10+ and `pip install -r requirements.txt`).

Full list in [CHANGELOG.md](CHANGELOG.md).
