"""Color themes: a palette per theme applied app-wide on top of Qt's Fusion style. 'System' leaves Qt alone."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

# window, base (text boxes/tables), alt row, text, button, accent (selection), selected text, link, disabled text
THEMES = {
    "Light":           ("#f0f0f0", "#ffffff", "#f5f5f5", "#1a1a1a", "#e6e6e6", "#2f6fdb", "#ffffff", "#1565c0", "#9a9a9a"),
    "Dark":            ("#2b2b2b", "#1e1e1e", "#262626", "#e6e6e6", "#3a3a3a", "#3d7fe0", "#ffffff", "#6cb0ff", "#7a7a7a"),
    "Nord":            ("#2e3440", "#3b4252", "#353c4a", "#eceff4", "#434c5e", "#5e81ac", "#eceff4", "#88c0d0", "#7b869a"),
    "Dracula":         ("#282a36", "#21222c", "#262833", "#f8f8f2", "#44475a", "#6272a4", "#f8f8f2", "#8be9fd", "#7a7d93"),
    "Paper":           ("#ebe8e1", "#f7f5f0", "#f0ede6", "#2e2e2e", "#e0dcd3", "#4a6fa5", "#ffffff", "#3d5a8a", "#9a968c"),
    "Catppuccin Latte": ("#e6e9ef", "#eff1f5", "#e8ebf1", "#4c4f69", "#dce0e8", "#1e66f5", "#ffffff", "#209fb5", "#9ca0b0"),
    "Sky":             ("#e8f0f8", "#f7fbff", "#eef5fb", "#1d2b3a", "#d9e6f3", "#1976d2", "#ffffff", "#0d5bb5", "#8da2b8"),
    "Mint":            ("#e6f2ee", "#f6fbf9", "#edf6f2", "#1f332d", "#d6e8e1", "#00897b", "#ffffff", "#00695c", "#8aa69c"),
    "High Contrast":   ("#000000", "#000000", "#101010", "#ffffff", "#1a1a1a", "#ffff00", "#000000", "#00ffff", "#a0a0a0"),
}
NAMES = ["System"] + list(THEMES)
_original = {}


def _palette(spec):
    win, base, alt, text, btn, acc, acc_text, link, dis = (QColor(c) for c in spec)
    p = QPalette()
    for role, col in ((QPalette.Window, win), (QPalette.WindowText, text), (QPalette.Base, base),
                      (QPalette.AlternateBase, alt), (QPalette.Text, text), (QPalette.Button, btn),
                      (QPalette.ButtonText, text), (QPalette.Highlight, acc), (QPalette.HighlightedText, acc_text),
                      (QPalette.Link, link), (QPalette.ToolTipBase, base), (QPalette.ToolTipText, text),
                      (QPalette.PlaceholderText, dis), (QPalette.BrightText, QColor("#ff5555"))):
        p.setColor(role, col)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, dis)
    return p


def apply(app: QApplication, name: str) -> str:
    """Switch the whole app to a theme. Unknown names fall back to System. Returns the name actually used."""
    if not _original:
        _original.update(style=app.style().objectName(), palette=QPalette(app.palette()))
    if name not in THEMES:
        app.setStyle(_original["style"])
        app.setPalette(_original["palette"])
        return "System"
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setPalette(_palette(THEMES[name]))
    return name
