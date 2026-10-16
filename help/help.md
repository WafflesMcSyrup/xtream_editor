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
   link and it fills in the server, username and password for you. Hit *Fetch channels*.
2. Browse and edit (details below).
3. **File > Save project** so your edits stick around. Next time you can just re-fetch and
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
  buttons too. They work on the selected rows, or on every row shown if none are selected, and nothing changes in
  your list until you press Apply. A tick box keeps your **standard acronym list** uppercase (it starts with ESPN, ABC, CBS, NBC, FOX, BBC, AMC, MGM, NFL, NBA, MLB, NHL, HBO, PBS and more). **Edit standard list...** changes it once and it's remembered, and the box below adds one-off extras.
  Search, the type filter and a *Hide fully deleted categories* box help with long lists, and clicking a column
  header sorts. Renamed categories stay renamed when the provider re-syncs.
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
| Ctrl+E | Export playlist |
| Ctrl+Shift+X | Xtream server for your IPTV apps |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Ctrl+H | Find & replace |
| Ctrl+D | Toggle a star on the selected rows |
| Ctrl+Shift+D | Import a list for Favorites |
| Ctrl+Shift+C or Ctrl+M | Category manager |
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
