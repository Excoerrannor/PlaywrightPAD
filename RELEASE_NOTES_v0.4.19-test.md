# Makerlab Return Processor v0.4.19-test — Button Hover Palette

**UI-only update based on v0.4.17-test.** The v0.4.18 Scan History selection-contrast change is intentionally excluded as requested.

## Button colors
- **Enabled / default:** `#47B0BB` (teal) with dark text `#17313B`
- **Mouse hover:** `#DF9A19` (amber) with the same dark text
- **Pressed:** `#C88714` (darker amber) with dark text
- **Disabled:** existing muted gray colors remain unchanged

All rounded buttons in both the main processor and Scan History/Recovery inherit these colors automatically. The fallback ttk buttons and legacy AccentButton also use the same palette. Existing buttons still resize, respond to mouse/keyboard, and retain the same commands and enabled/disabled logic.

## Installation
Replace **`C:\PlaywrightPAD\ui_theme.py`** and restart the Python application. If you installed the previous v0.4.18 selection-highlight change, also replace **`history_window.py`** from this bundle to restore the v0.4.17 selection style. If you use an EXE, rebuild it with PyInstaller.

The bundled `history_window.py` is the unchanged v0.4.17 version (provided only for reverting v0.4.18). No changes were made to marketplace scrapers, Odoo, Lark, JSON store, Windows titlebar, or Windhawk glass.
