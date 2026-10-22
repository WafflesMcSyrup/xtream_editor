# Changelog

## 6.3 (2026-10-22)

New:
- **Build a master list** (Edit > Build a master list...): pick Live channels from two provider projects and collect them in a third, master project. Names, categories, logos and stars come along; duplicates across providers are flagged (add both, skip, or replace). A third window shows the master as you build it, with Remove and reorder buttons. Each channel plays from its own provider (redirect or proxy), the guide merges both providers, and it works in the editor's server and headless (`--serve master.xtp`).
- Master lists get a **Source** column and a Source filter in the main editor. Each list has a short tag (A and B by default, anything you like), and **Name manager > Add source tag** puts it in front of names as `[A] ESPN` (and **Remove source tag** takes it off).
- **File > Close project** (Ctrl+W) empties the editor.
- **Copy edits from another project** (Edit menu): make a new provider's Live channels follow the edits (deleted, favorites, names, categories, logos, EPG IDs, order) from a project you've already edited. Matched by EPG ID then name; new channels marked new; preview, then one undo step. Channels deleted in the other list get their own tab, with a box to delete their matches here, and an "only the channels I starred" filter does your favorites first.
- **Name manager** (Edit > Name manager, Ctrl+Shift+N): bulk name tidy-ups for channels, movies and series: Proper Case (numbers left alone, 1st/2nd handled, standard acronyms kept uppercase), UPPERCASE, lowercase, trim spaces, remove a prefix, find and replace. Scope by type and by all / selected rows / the sidebar's category. Preview, confirmation popup, Undo last action.
- **Built-in regex rules:** remove superscript text (names, categories) and remove country prefixes like `US|` / `UK |` (names, categories). Ready to tick on, can't be deleted, and Copy makes an editable version.
- Regex rules: new **Only in category** box on each rule, and a **Regex rules...** entry in the category list's right-click menu that opens the window with that category filled in.
- **Second login.** File > Second login saves a second provider account in the project. Run a second server with `--account 2` (or `start_server_2.bat`) and you can use one list with two accounts, for example one to watch and one to record. Edit once; both servers follow your saves. The second server takes the next port, a user name plus 2 and its own password by default, and leaves the daily re-sync to the first.
- Double-click a category in the left list to rename / merge it.

Fixed:
- Tool windows (Name manager, Regex rules, Duplicate finder, Category manager, Copy edits) kept pointing at the old project after you opened, closed or started another one. They now follow the open project.
- A fetch that got cut off mid-download ("ChunkedEncodingError / IncompleteRead") now retries a few times instead of failing at once, and if it keeps dropping you get a plain-English message instead of the raw error.
- Each server now keeps its own guide and log files (named after its port), and guide downloads use their own temporary files, so two servers on one PC no longer collide.

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
