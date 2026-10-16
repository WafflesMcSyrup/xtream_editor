# Changelog

## 6.2

New:
- **Duplicate finder** (Edit > Find duplicates, Ctrl+Shift+U). Groups copies of the same movie, series or channel even when the names differ by language prefix, quality tags, year or "The". Pick what to keep, delete, rename or move per copy, or let it auto-pick (earliest, newest or most complete). Confirmation popup, Undo last action button, one undo step for the whole apply.
- **Regex rules** (Edit > Regex rules, Ctrl+Shift+R). Saved find-and-fix rules that run on demand: rewrite names or categories, move matches to a category, or delete them. Match on name or category, per rule. Preview first, then apply in one undo step.
- **Placeholder guide entries.** Channels with no EPG ID, or an ID that isn't in the guide, get a simple "channel name" program block so apps like OneTV still show them in the guide. Off by default. Tick it in the Xtream server window, add `--placeholder-epg` to headless mode, or use the tick box in the export window (with the merged guide).
- **Remembers your layout.** Window size and position, splitter, and column widths come back the way you left them.

Changed:
- "Programmes" is now "programs" everywhere you can see it. (The guide files themselves still use the standard `<programme>` tag, so provider guides keep working.)
- The server's guide status line now counts placeholder programs in the total, and shows how many placeholders were added.

Fixed:
- Program count in the status line and export summary was missing the placeholder programs.
