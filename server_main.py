"""The no-window Xtream server on its own (no Qt). This is what the console exe is built from.

Run:  python server_main.py [project.xtp] [--port 8090] [--user U] [--password P] ...
Same options as `python main.py --serve`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.cli_args import parse_args  # noqa: E402


def main():
    argv = sys.argv[1:]
    if not any(a == "--serve" or a.startswith("--serve=") for a in argv):
        argv = ["--serve"] + argv                 # this program only ever serves
    args = parse_args(argv)
    from core.serve_cli import run
    sys.exit(run(args))


if __name__ == "__main__":
    main()
