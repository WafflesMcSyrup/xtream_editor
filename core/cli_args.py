"""Command-line options shared by main.py (editor) and server_main.py (no-window server)."""
import argparse


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Xtream Editor")
    ap.add_argument("--serve", nargs="?", const="LAST", metavar="PROJECT",
                    help="skip the window and just run the local Xtream server "
                         "(uses your last saved project if no file is given)")
    ap.add_argument("--port", type=int, help="server port (default: saved setting, 8090)")
    ap.add_argument("--user", help="username your IPTV apps will use")
    ap.add_argument("--password", help="password your IPTV apps will use")
    ap.add_argument("--proxy", action="store_true",
                    help="relay streams through this PC instead of sending apps straight to the provider")
    ap.add_argument("--no-epg", action="store_true", help="don't serve a guide")
    ap.add_argument("--refresh-at", metavar="HH:MM",
                    help="with --serve: re-sync with the provider every day at this time (default 03:00, this PC's clock)")
    ap.add_argument("--no-auto-refresh", action="store_true", help="with --serve: turn off the daily re-sync")
    ap.add_argument("--first-refresh-in", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch the channel list from the provider on startup (edits are kept)")
    return ap.parse_args(argv)
