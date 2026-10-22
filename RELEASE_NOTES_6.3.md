## Xtream Editor 6.3

Master lists, copying your edits to a new provider, and a bunch of cleanup tools.

**What's new**
- **Build a master list** (Edit menu): pick channels from two provider projects and collect them in one list. Each channel keeps playing from its own provider, the guide merges both, and your names, categories, logos and stars come along. Works in the editor's server and headless. A **Source** column and filter show where each channel came from, and **Name manager** can add a tag like `[A]` in front of names (you choose what goes in the brackets).
- **Copy edits from another project**: spent days editing one provider's list and got a new provider? Make the new list follow your deletes, favorites, renames, categories, logos and order. Preview first, one undo step, and a favorites-only option so the important ones go first.
- **Name manager** (Ctrl+Shift+N): Proper Case, UPPERCASE, lowercase, trim spaces, remove a prefix, find and replace, with preview and undo.
- **Built-in regex rules**: strip superscript text and `US|` / `UK |` style country prefixes from names and categories. Tick them on, no setup. Rules can also be limited to one category.
- **Second login**: one list, two provider accounts, for example one to watch and one to record. Run a second server with `--account 2`.
- **File > Close project** (Ctrl+W), and double-click a category to rename or merge it.

**Fixes**
- Tool windows now follow the project you have open instead of the one you had before.
- A fetch that gets cut off mid-download retries instead of failing, with a clear message if it keeps dropping.
- Two servers on one PC no longer share guide or log files.

**Getting it**
- Windows: download the programs from the assets below, no Python needed. Windows may show a SmartScreen warning because the apps aren't code-signed; choose *More info > Run anyway*.
- Any system: grab the source zip and run `python main.py` (needs Python 3.10+ and `pip install -r requirements.txt`).

Full list in [CHANGELOG.md](CHANGELOG.md).
