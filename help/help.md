# Welcome

Pulls everything off an Xtream Codes account (live, movies, series), shows it in one big
searchable window, lets you edit it, and then either exports a playlist (M3U) plus an EPG file, or serves your
edited list straight to IPTVnator, UHF, OneTV and friends as a local Xtream server. Built for lists with
50k+ entries.

## Getting it running

You need Python 3.10 or newer.

```
pip install -r requirements.txt
python main.py
```

(`lxml` in the requirements is optional, but it makes merging giant EPG files a lot faster.)

**Don't want to install Python?** You can build ready-to-run Windows programs instead. Once they're built, you
just double-click `XtreamEditor.exe` and never need the `py main.py` command again. See *As Windows programs*
below under the *"The Xtream Server"* help topic for how.

## The basic flow

1. **File > Connect / fetch from server** (Ctrl+K). Paste your `get.php?username=...&password=...`
   link and it fills in the server, username and password for you. The optional **Label** box at the top lets you name the list (like "Provider A - Home"); it shows in the window title and in the master list builder. Hit *Fetch channels*.
2. Browse and edit (details below).
3. **File > Save project** so your edits stick around. **File > Recent projects** remembers the last five you opened or saved. Next time you can just re-fetch and
   your edits are kept (see *Re-syncing*).
4. **File > Xtream server for IPTV apps** (Ctrl+Shift+X) to serve your edited list to your apps. Or
   **File > Export playlist** (Ctrl+E) if you'd rather use a file.
5. In your IPTV app, add an **Xtream** account with the address, username and password the server shows
   you (or import the exported file, see *Getting it onto your players*).

## Editing

- **Tabs** across the top: All / Live / Movies / Series. **Sidebar**: categories with counts.
  You can **select several categories at once** (Ctrl-click / Shift-click) and the table shows all of
  them together. With the sidebar focused, press **Delete** to delete everything in the selected
  categories (no popup unless it's more than 5,000 items at once, and Ctrl+Z undoes it).
  Right-click the selection to delete, restore, or rename/merge it (merging several categories into
  one just means typing the new name). "All categories" on its own never deletes anything.
- **Category manager** (**Edit > Category manager**, Ctrl+Shift+C or Ctrl+M, or right-click the sidebar): one window listing
  every category with its type, item count and deleted count. Type a new name in the *New name* column (changed
  rows turn yellow) and press **Apply**. Giving two categories the same name merges them, and it's one undo step.
  The **Proper Case** button suggests tidy capitalization (small words like "of" and "the" stay lowercase, and
  acronyms like UK, USA, HD and TV stay uppercase), and there are **UPPERCASE** / **lowercase** / **Reset**
  buttons too. **Remove Country Code** takes a prefix like `|EN|`, `EN |` or `[UK]` off the start of the name
  (real country codes only), and you can combine it with Proper Case. They work on the selected rows, or on every row shown if none are selected, and nothing changes in
  your list until you press Apply. A tick box keeps your **standard acronym list** uppercase (it starts with ESPN, ABC, CBS, NBC, FOX, BBC, AMC, MGM, NFL, NBA, MLB, NHL, HBO, PBS and more). **Edit standard list...** changes it once and it's remembered, and the box below adds one-off extras.
  Search, the type filter and a *Hide fully deleted categories* box help with long lists, and clicking a column
  header sorts. Renamed categories stay renamed when the provider re-syncs.
- **Name manager** (**Edit > Name manager**, Ctrl+Shift+N): bulk tidy-ups for item names, like the Category manager but for the names of channels, movies and series. Pick the type (Live, Movies, Series or all) and which items (everything, the rows selected in the main list, or the category selected in the sidebar), then what to do: **Proper Case** (numbers are left alone, small words like "of" and "the" stay lowercase, and your standard acronym list from the Category manager stays uppercase), **UPPERCASE**, **lowercase**, **Trim extra spaces**, **Remove a prefix** (type something like `US |` and it comes off the start of each name), or **Find and replace**. **Preview** lists every name that would change, with the before and after, and **Apply** only unlocks once you've previewed. It's one undo step, with the same confirmation popup and **Undo last action** button as the other tools. Renamed items count as edited, so a re-sync keeps your names.
- **Copy edits from another project** (**Edit > Copy edits from another project...**): for when you've spent days editing one provider's list and get a new list from a different provider with mostly the same Live channels. Open the new list as your project, pick the `.xtp` you've been editing, and press **Preview**. Channels are matched by **EPG ID** first, then by **name** (ignoring prefixes like `US|` and tags like HD or 4K). Channels you deleted in the other list are never listed as missing; they get their own tab, and the **Delete the channels you deleted in the other list** box decides whether their matches are deleted here too (ones already gone here aren't shown). Tick **Only the channels I starred in the other list** to do your favorites first; it covers just those channels, and the whole-list steps (order, marking new, deleting) wait until you untick it and go again. Tick what to copy: deleted channels, favorites, names, categories, logos, EPG IDs you set by hand, and the order of the channels. Channels the new list has that your old one didn't are marked **new**, so you can find them. The tabs show every change, the channels only in one list, and any unclear matches (the same name several times, which are skipped). Nothing is touched until **Apply**, which is one undo step, and the other project file is never changed. Live channels only for now. If you renamed a channel a lot in the old list and it has no EPG ID, it may not match; it'll show up under *Only in the other list*.
- **Build a master list** (**Edit > Build a master list...**): pick channels from two provider projects and collect them in a third, master project. Choose the master file (a new one, or an existing master to add more to), then pick your two lists as **List A** and **List B**. Each side has search, a category filter and a favorites-only filter; select channels and press **Add selected**, or **Add all shown**. Channels keep the names, categories, logos and stars you already set, and the master is saved every time you add. If a channel looks like one the master already has from the other provider (same guide ID or same name), you can add both, skip it, or replace the master's version. The third window on the right shows the master as you build it (with which list each channel came from); **Remove selected** (or the Delete key) takes channels back out, and the arrow buttons move them up, down, to the top or to the bottom (clear the search first). In the main editor a master list gets a **Source** column (which list each channel came from) and a **Source** filter next to the search box. Each list also has a short tag, set in the master builder (**Tag: [ ]** under each list's login, A and B by default). To put the tag in front of the names, open the **Name manager**, pick **Add source tag**, check or change the tags, and Preview/Apply: `ESPN` becomes `[A] ESPN`. The tag can be anything you like between the brackets. **Remove source tag** takes them back off. Each channel in the master plays from the provider it came from, and the guide is built from both providers' guides. Open the master like any project to reorder, rename or export it, and run it in the local server (or headless with `--serve master.xtp`). Live channels only for now, and a master isn't fetched from a provider: to change what's in it, come back to this window. Each provider's connection limit still applies to its own channels. Don't have the master open in the editor while you add to it. If the project you want to use is open, **File > Close project** (Ctrl+W) empties the editor first.
- **Duplicate finder** (**Edit > Find duplicates**, Ctrl+Shift+U): looks for the same movie, series or channel listed
  more than once. Pick the type (Movies, Series, Live, or a mix) and the scope (active items, favorites, new since
  the last sync, or everything including deleted), then press **Find duplicates**. Copies are grouped by title with
  the language prefix (`US |`), quality tags (HD, 4K...) and brackets ignored, so `US | Heat (1995) [HD]` and
  `Heat (1995)` land together. Different years count as different titles unless you tick **Ignore the year**.
  Select copies and choose **Keep**, **Delete**, **Rename...** or **Move to category...** (or right-click), or let it
  decide for the whole list with *keep the one earliest in my list / newest / with the most info, delete the rest*.
  Your choices are colored (red = delete, yellow = rename or move, green = keep) and nothing changes until you press
  **Apply**, which is one undo step. A popup shows what's about to happen first (tick *Don't ask me again* to skip it,
  and turn it back on with **Ask before applying** at the bottom of the window). Changed your mind? The
  **Undo last action** button (or Ctrl+Z in that window) goes back one step. **Clear all choices** wipes every mark at once. Live channels repeat on purpose (the same channel in several categories), so
  for Live try **Same title in the same category** first.
- **Regex rules** (**Edit > Regex rules**, Ctrl+Shift+R): saved find-and-fix rules for tidying lots of items at once.
  Each rule says which type to look at (Live, Movies, Series or all), whether to test the item **name** or its
  **category**, an optional **Only in category** (so a rule only touches items in one category), and a pattern (a Python regular expression). Right-click a category in the left list and choose **Regex rules...** to open this window with that category already filled in. Then pick what happens to matches: **rewrite** the
  matched field (use `\1` or `$1` to keep what's inside the first set of parentheses), **move** them to a category
  (pick one from the dropdown or type a new name), and/or **delete** them. Rules run top to bottom, so a later rule sees what an earlier one did, and a name
  is never rewritten to nothing. Tick or untick a rule to switch it on or off; they're saved in your settings, so
  they're there next time (and for other projects). **Preview** lists every item that would change, with the before and
  after, and **Apply** only unlocks once you've previewed (any edit to a rule means preview again). Apply is one undo
  step, with the same confirmation popup and **Undo last action** button as the duplicate finder.
  The first four rules in the list are **built in** (greyed): remove superscript text (like ᴴᴰ or ⁶⁰ᶠᵖˢ) from names or from categories, and remove country prefixes (like `US|`, `UK |`, `|US|` or `[CA]`) from names or from categories. They start switched off; tick the ones you want, then Preview. They can't be edited or deleted, but **Copy** gives you your own editable version. (Heads up: removing the country from categories merges "US | Sports" and "UK | Sports" into one "Sports".) The switched-on ones run first, then your own rules.
  A few examples:
  - Strip a `US | ` prefix from names: look at the name, pattern `^US \| (.*)`, rewrite with `\1`.
  - Put everything in a `US |` category into one clean category: look at the category, pattern `^US \|`, move to `US Local`.
  - Remove "(HD)" or "[4K]" tags from names: look at the name, pattern `\s*[\(\[](HD|4K)[\)\]]`, tick rewrite and leave it empty.
  - Delete 24/7 filler channels: look at the name, pattern `^24/7`, tick **Delete the items that match**.
- **Search** box: type several words and a row must contain all of them (checks name, category
  and EPG ID).
- **Show** dropdown: handy filters like *Live: no EPG ID*, *Live: EPG ID not in my guides*,
  *No logo*, *Edited by me*, *Deleted only*, *Gone from server*.
- **Double-click** (or F2) a Name, Category, EPG ID or Logo cell to edit it right in the table.
  Cells you've changed turn yellow.
- Select lots of rows (Shift/Ctrl-click, Ctrl+A) and use the **Edit** menu or right-click:
  set category, set EPG ID, set logo URL, find & replace (plain or regex), delete, restore.
- **Sort A-Z** (**Edit > Sort A-Z...**, or right-click the sidebar): puts items in alphabetical order so they show up A-Z
  in your apps. Pick which types to sort (Live is ticked by default), then **how**: *within each category* (categories
  keep their place) or *one big A-Z list* (everything together no matter the category, handy for scrolling one long
  Live list in an app). You can do all categories or only the ones selected in the sidebar. It ignores case,
  accents, a leading "The" and leading symbols like ★, and numbers sort naturally (Channel 2 before Channel 10).
  Nothing is renamed or moved to another category, it's one undo step, and the Xtream server picks it up like any
  other edit. The server sends categories alphabetically already, and the items in each one in the order you see in
  the `#` column, so this is what makes them A-Z.
- **Move** (Edit > Move, or Alt+Up / Alt+Down): changes playlist order. The list has to be
  sorted by the `#` column (click its header) for this to work.
- **Undo / redo** (Ctrl+Z / Ctrl+Y) covers everything above, including 50,000-row bulk edits.
  It remembers the last 30 steps.
- **Favorites**: select rows and press **Ctrl+D** (or right-click > Toggle favorite) to star them. Starred
  rows show a ★ and you can see them all with *Show > ★ Favorites only*. Favorites are saved in the project
  and survive re-syncs. See *The Xtream server* for how they show up in your apps.
- **Import a list of names into Favorites**: **Edit > Import list for Favorites...** (Ctrl+Shift+D). Pick a
  text file with one name per line (bullets, numbers, "(564)" channel numbers and "== headers ==" are ignored, so
  the editor's own TXT export works too). A window opens with your imported names on the left and the best matches
  from your list on the right, best first, with their category so you can tell similar ones apart. It ignores
  country prefixes, HD/FHD, case, accents and spacing, finds East/West flavors, and copes with small typos.
  Tick the matches you want (one, several or none per line), or press **Tick all good matches** to tick the
  near-exact ones and then look them over. Nothing is starred until you press **Add checked to Favorites**, and
  the whole import is one undo step. If the best try misses, retype the name in the box above the matches and
  press Enter. Live channels are searched by default; tick *Also search Movies and Series* to include those.
  Lines show Good / Check / No match / Already starred, and the filter at the top hides the ones you're done with.
- **New since last sync**: after a re-sync (you fetching again, or the nightly 03:00 one) that finds new
  channels, movies or shows, they get a "new" tag and show up under *Show > New since last sync*. The tags stay
  until a later sync finds more new items (a sync that finds nothing leaves them alone) or you use
  **Edit > Mark all new items as seen**. The very first fetch doesn't tag everything. The tags are saved in the
  project, so you can look them over the next morning.
- **Themes**: **View > Theme** switches the look of the whole app: System (your Windows setting), Light, Dark,
  Nord, Dracula, High Contrast, and the lighter Paper, Catppuccin Latte, Sky and Mint. Your pick is remembered.
- **Remembers your layout**: the main window's size and position (and whether it was maximized), the divider
  between the category list and the table, and your column widths are saved when you close the program and come back
  next time. If a saved position is on a monitor that's no longer there, the window moves onto one that is.
- Deleting just hides a row from the export. You can bring it back any time (*Show > Deleted only*).

## Series

The server only lists show names up front. Episodes take one extra request per show, so they
are fetched on demand:

- Select series and use **Series > Fetch episodes for selected**, or
- **Series > Fetch episodes for ALL series** (cancel any time and it keeps what finished), or
- **Series > View / trim episodes** to untick episodes you don't want.

Series whose episodes haven't been fetched are left out of the export, and the export summary
tells you how many were skipped. Tip: delete the shows you don't care about *before* fetching all.

## EPG (guide data)

- **EPG > Sources & scan**: the provider's own guide is included automatically. Add as many extra
  XMLTV guides as you like (plain `.xml` or `.xml.gz`), one per line. Each line can be a **web address**
  or a **file on your PC** (`D:\Guides\epg.xml.gz`). You can drag files into the box, use **Add file...**,
  or paste a path (quotes from Explorer's "Copy as path" are fine). Local files are read right where they
  are, nothing is copied, so replacing the file updates your guide the next time it's rebuilt. (The server
  notices a changed local file within about 15 minutes, or right away with **Rebuild guide now**.) Earlier ones win when two guides
  have the same channel ID. The app downloads and scans them all.
- After a scan, EPG IDs that don't exist in any guide show up **red**, and you get a coverage summary.
- **EPG > Auto-fill EPG IDs by channel name** matches channels missing an ID against channel names
  in your guides. It ignores country prefixes and things like HD/FHD/4K, so *US: ESPN HD* and
  *UK: ESPN* both look like "ESPN". That means it can guess wrong. It shows you a sample, applies
  everything as one undoable step, and the changed cells are highlighted so you can skim them.
- When exporting you can either point the playlist at the provider's guide URL, or **merge** the
  provider guide and your extra guides into one local `epg.xml` (only channels in your export are
  kept, which keeps it small). If you tick the merge option, fill in the address where you'll host
  the file so the playlist header can reference it.
  The merge also has a **Fill channels that have no guide data with a placeholder** tick box (off by default),
  which adds a made-up show named after the channel for any live channel the guides don't cover, and gives
  channels without an EPG ID a made-up one (`xe.` plus the channel's number) in the playlist so players can line
  them up.

## Exporting

Choose what to include, one combined file or one per type, `ts` or `m3u8` for live streams, and
an optional group-name prefix (like `Movies | Action`) so movie and series categories don't collide
when combined. Every entry gets `tvg-id`, `tvg-name`, `tvg-logo` and `group-title`.

### Export a plain list (CSV / TXT)

**File > Export list to CSV / TXT...** saves a simple list of what's in your playlist. Pick everything or
just certain categories (there's a filter box and Tick shown / Untick shown buttons), limit it to
Live / Movies / Series, and choose the format:

- **CSV**: three columns, Type, Name, Category. Opens in Excel.
- **TXT**: names grouped under their category, with a section for each type:
  ```
  ##### LIVE TV #####

  == UK | Drama (214) ==
    Name 1
    Name 2
  ```

Items you deleted are left out unless you untick "Leave out items I deleted", and categories with nothing
left in them disappear from the picker so there's less to scroll through. Tick **★ Favorites only** to export just
your starred items; the category list then shrinks to categories that have favorites, and the counts show only
those. A running total shows how many items will be written. Edited names and categories are what get written. No logins or stream URLs are in these files.

**Heads up:** an Xtream "list" is really a login, not a file, so an edited channel list can't be
imported as a login. The export is an M3U with your stream URLs baked in. That means the file contains
your username and password. Treat it like a password.

## The Xtream server

- **Recommended for apps such as IPTVnator, UHF, OneTV, etc.**

Giant M3U files choke IPTV apps. This does it the way real providers do:

**File > Xtream server for IPTV apps** turns this PC into a small Xtream provider that serves your
*edited* list. Apps log in with a server address, username and password, and get Live / Movies /
Series with your categories (and your renames, ordering and deletions). They load a section at a time,
and the app does its own searching.

1. Fetch and edit as usual, save the project (Ctrl+S).
2. Open the server dialog, pick a port/username/password if you don't like the defaults, hit **Start server**.
3. It shows what to type into your apps. In IPTVnator, UHF or OneTV add an **Xtream** account with:
   - Server: `http://<this PC's address>:8090`
   - Username / password: the ones from the dialog (these are *not* your provider login)
4. Pick a channel and it plays straight from your real provider.

Good to know:
- **★ Favorites category.** Anything you star in the editor also appears in a "★ Favorites" category at the top of
  Live, Movies and Series in every app (the items stay in their normal categories too). It only shows up once
  you've starred something in that section, and apps need a refresh to see changes. It works the same whether the
  server runs from the editor or `start_server.bat` (save the project and it reloads). The apps' own built-in
  favorites still exist, you just don't have to use them. Behind the scenes each favorite is a copy with its own
  id (so apps don't get confused by one channel in two places) that plays the real stream.
- **Catch-up (watch past shows).** Channels the provider offers catch-up for keep that, and past shows play
  through your server just like live TV (redirected or relayed to the provider, depending on your playback
  setting). The editor saves each channel's catch-up days when it fetches from the provider, so **re-sync once**
  (Connect / fetch, then save; the nightly re-sync does it too) if your project was fetched before this was added.
  Whether the catch-up button shows up is up to each app, and it works from the app's guide data, so the guide has
  to line up with the provider's times. Try one catch-up channel in each app first.
- **No need to fetch series episodes first.** When you open a show, the server asks your provider for
  that one show's episodes (and hides any you trimmed).
- **Edits go live.** Keep the editor open and changes show up on the server a couple of seconds later
  (apps may need a refresh to see them).
- **Playback:** the default sends the app to the provider directly, so no video goes through your PC.
  That does mean the app is told the provider URL. If an app won't play, switch to *Relay streams through
  this PC*, which hides it and works with any app, but uses this PC's bandwidth (and may not work with
  HLS/m3u8 streams, so use ts).
- **Guide:** it keeps one merged guide file (provider + your extra guides, only your channels) fresh in the
  background, every 12 hours by default. If a guide download fails (a provider 502, say), it quietly tries
  again 30 minutes later, then 2 hours after that, and then waits for the next regular refresh. That's at
  most two extra downloads, and the log says plainly what it's doing. Until a retry works, the last good
  copy of that guide keeps being served.
- **Placeholder guide entries** (a tick box under *Refresh guide every*, off by default; or `--placeholder-epg` for the
  no-window server): channels that have no guide data would show a blank row in your app, so this gives them a
  made-up show named after the channel ("No guide data from your provider"), in 3-hour blocks for the next 3 days.
  It covers channels with no EPG ID and channels whose ID isn't in any of your guides, and never touches channels
  that have real guide data. Channels with no EPG ID are handed a made-up ID (`xe.` plus the channel's number) in
  what the server and its playlist send out, and nothing is stored on your items. It only works with the merged
  guide, and switching it on or off rebuilds the guide right away.
- **Windows firewall** will ask once. Allow it on private networks. Give this PC a fixed address (a DHCP
  reservation in your router) so the apps don't lose it.
- **Don't port-forward it.** It's for your home network only.
- **Recent activity** in the dialog shows each request the apps make (passwords hidden). If an app can't
  connect or load something, that log is the first place to look.

### Without the editor window

Double-click **`start_server.bat`** (or run `python main.py --serve`). It serves your last saved project
and prints the address/username/password. Options: `python main.py --serve myproject.xtp --port 8090 --proxy
--refresh`. `--refresh` re-pulls the channel list from your provider on startup (your edits are kept).
To start it automatically with Windows, put a shortcut to `start_server.bat` in the Startup folder
(Win+R, type `shell:startup`).

**Daily re-sync.** The no-window server also re-pulls your channel list from the provider once a day, at
**03:00 by this PC's clock** (set the PC to Eastern time and that's 3am Eastern). New channels, movies and
shows are added at the end of their category, your edits are kept, and anything the provider dropped is flagged
"gone" and stops being served. The result is saved into the project file, so the editor sees it too. Change the
time with `--refresh-at 04:30`, or turn it off with `--no-auto-refresh`. If the provider is down it keeps serving
the current list and tries again 30 minutes later, and if the provider hands back a suspiciously small list
(a hiccup) it ignores it rather than wiping your channels. If the PC was asleep at 03:00 it runs as soon as it
wakes. This only happens in the no-window server, not when the server is started from the editor. Heads up: if
you have the project open in the editor with unsaved changes at 03:00, saving later overwrites the re-synced
file (the next night's re-sync catches it up).

The no-window server **watches your project file**: save in the editor (Ctrl+S) and within a few seconds it
reloads the list by itself, no restart needed. If the file is ever half-written or damaged it just keeps
serving the previous list. (Your apps still need a refresh to see the changes.) The one thing it doesn't
do is stop you from running two servers on the same port, so close the editor's server first.

### Two logins, one list (two servers)

If your provider only allows one connection per account and you have two accounts with the same channels
(say one for watching and one for recording), you only have to edit the list once. In the editor use
**File > Second login...**, enter the second account, and save the project (Ctrl+S). Then run two servers
from that project: `start_server.bat` (first account) and `start_server_2.bat` (second account, same as
`python main.py --serve --account 2`). The second one picks the next port up (8091), the user name plus a 2
(`local2`) and its own password, all printed in its window; add `--port`, `--user` or `--password` to choose
your own. Point one player at each. Both watch the project file, so a save in the editor updates both, and only
the first server does the daily re-sync. The two servers keep separate guide and log files (named after their
port), so they don't step on each other. This assumes both accounts see the same stream IDs, which is normal
for one provider.

### As Windows programs (no Python needed)

Run **build_exe.bat** on Windows (it installs PyInstaller for you). It makes two folders in `dist`:
`XtreamEditor` (the editor, with the server window inside it) and `XtreamServer` (the no-window server,
which runs in a console and is much smaller). Give people those folders. Their logins and projects are
stored in their own user folder, so nothing of yours goes along. Inside `XtreamServer`, `start_server.bat`
runs it, and you can add options on the end, like `start_server.bat --port 8091`.

After the build, just double-click `XtreamEditor.exe`, no Python needed. You can move the whole `XtreamEditor`
folder anywhere you like, even to another PC. Move the whole folder, not just the exe, since the exe needs the
files next to it. Your login, settings and projects live in your own user folder, so they don't travel with it.
Copy a saved `.xtp` project file over to carry your edits.

## Getting it onto your players (static playlist files)

**Most people can skip this section.** The easier way is the **Xtream server** (see *The Xtream server* above).
Your app just logs in with a server address, username and password, with no playlist file to import. Use the
plain files below only if your app can't do an Xtream login.

If you'd rather use plain files:

- **IPTVnator (Windows):** add the `.m3u` as a file or URL playlist. Add the EPG under its EPG settings.
- **UHF / OneTV (Apple TV):** these want a URL. Use **File > Serve on home network**: point it at the
  export folder, start sharing, and it shows URLs like `http://192.168.1.50:8765/playlist.m3u` to paste
  into the app. The sharing only lasts while this app is running, so for a permanent setup put the
  exported files on any always-on PC or NAS web server.

## Re-syncing

Run **Connect / fetch** again on an open project. Your edits (renames, categories, EPG IDs, logos,
deletions, order) are kept. New channels are added at the end of their list. Channels that vanished
from the server are flagged *gone from server* and left out of the export.
New items land at the end of their category, so run **Sort A-Z** again if you keep your lists alphabetical.

## Files it creates

- `~/.xtream_editor/settings.json` remembers the last login (including the password, in plain text),
  last folders and port. Delete it if you don't want that.
- `~/.xtream_editor/epg_cache/` downloaded guides.
- Your `.xtp` project files hold the edited list and the login too, so don't share them.

## If login fails

- **HTTP 403 / refused:** some providers block unknown clients. Change the *User-Agent* in the connect
  dialog to the name of an app you normally use.
- **"Server didn't return JSON":** check the server URL (port included, no `/get.php` on the end).
- **Fetch is slow:** the first pull of a huge account can take a bit, the provider is the bottleneck.
  Everything after that is local and quick.

## Keyboard shortcuts

| Keys | What it does |
|---|---|
| F1 | Open this help |
| Enter / F3 (in the help search) | Next match, across sections |
| Shift+F3 | Previous match |
| Esc | Close the help window |
| Ctrl+K | Connect / fetch from server |
| Ctrl+O / Ctrl+S / Ctrl+Shift+S | Open / save / save as |
| Ctrl+W | Close the project (empties the editor) |
| Ctrl+E | Export playlist |
| Ctrl+Shift+X | Xtream server for your IPTV apps |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Ctrl+H | Find & replace |
| Ctrl+D | Toggle a star on the selected rows |
| Ctrl+Shift+D | Import a list for Favorites |
| Ctrl+Shift+C or Ctrl+M | Category manager |
| Ctrl+Shift+N | Name manager |
| Ctrl+Shift+U | Duplicate finder |
| Ctrl+Shift+R | Regex rules |
| Delete | Delete selected rows (or categories, with the sidebar focused) |
| F2 or double-click | Edit a cell |
| Alt+Up / Alt+Down | Move selected rows up / down |
| Ctrl+A | Select all rows |
| Ctrl+Q | Quit |

## Disclaimer and terms of use

Xtream Editor is a personal tool for organizing and playing an IPTV subscription that **you already have a legal right to use**. It doesn't supply, host, or link to any channels, movies, shows, playlists, or guide data, and it comes with no subscription or login of its own.

**By using this software, you agree that:**

1. You will use it only with accounts and content you are legally entitled to access, and only in ways that comply with all applicable laws, your provider's terms of service, and the rights of copyright holders.
2. You will not use it to obtain, share, resell, or distribute pirated or unauthorized content, or to get around any access controls, geographic restrictions, or account limits.
3. You are solely responsible for how you use it, for the accounts and content you connect to it, and for any consequences of that use.

The software is provided **"as is," without warranty of any kind**, express or implied, including fitness for a particular purpose and non-infringement. To the fullest extent the law allows, the author is not liable for any claim, damages, data loss, account suspension, or other harm arising from the use of, or inability to use, this software.

This project isn't affiliated with, endorsed by, or connected to any IPTV provider, service, or app, including IPTVnator, UHF, or OneTV. All names and trademarks belong to their owners.

If you don't agree with these terms, don't use the software.
