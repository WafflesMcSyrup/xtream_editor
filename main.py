"""Xtream Editor - fetch an Xtream Codes account, edit the channels, export a playlist
or serve your edited list to IPTV apps as a local Xtream server.

Run the editor:           python main.py
Run only the server:      python main.py --serve [project.xtp]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.cli_args import parse_args  # noqa: E402


def main():
    args = parse_args()
    if args.serve:
        from core.serve_cli import run
        sys.exit(run(args))
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Xtream Editor")
    win = MainWindow()
    win.show()
    if not win.require_terms():
        sys.exit(0)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
