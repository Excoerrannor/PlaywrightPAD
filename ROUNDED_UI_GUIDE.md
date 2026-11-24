# Makerlab Return Processor v0.4.17-test — Rounded, Responsive UI

This is a Tkinter/ttk interface upgrade. No CSS, new Python packages, browser technology, or DWM/Windhawk modifications are needed.

## Changes
- Rounded, opaque pale-teal cards around marketplace search, order overview, SKU table, item decisions, Odoo/Lark activity, and History/Recovery search/details.
- Canvas-drawn rounded action buttons with hover, focus, disabled, and keyboard Enter/Space activation.
- Buttons expand to the width of their form columns. At compact widths, Confirm, Submit, and Retry each gain their own full-width row.
- Dark workspace and light card surfaces retain the Makerlab teal (#40A2AF) and amber (#FAAD17) colors.
- The Odoo Transfer ID remains highlighted, selectable, and copyable.
- Native Windows titlebar and Windhawk glass settings are not modified. Reading surfaces are intentionally opaque for legibility.

## Install over v0.4.16-test
1. Close the processor.
2. Back up your existing `C:\PlaywrightPAD\main.py`, `history_window.py`, and `ui_theme.py`.
3. Copy the three updated files from this package to `C:\PlaywrightPAD`, replacing the originals.
4. Launch your processor normally with your Python virtual environment.

Keep your existing `C:\PlaywrightPAD\data` folder, `OdooProfile` browser profile, and other platform scripts. Do not copy any sample data over your live JSON files.

## If running an EXE
Replacing Python source files does not modify a previously compiled executable. Rebuild with PyInstaller after replacing the source files.

## Scope and tests
Only `main.py`, `history_window.py`, and `ui_theme.py` changed. Shopee/Lazada/TikTok scrapers, Odoo/Lark workflow, browser manager, and JSON storage modules are unchanged.

- Python compile passed for all .py files.
- Offline Tk UI tested at 1000x735, 1140x800, 1380x930, and 1600x1000.
- History/Recovery tested at 900x585 and 1280x775.
- Rounded button state, callback, text updates, and resizing tested.
- Windows/Windhawk compositing and live marketplace/Odoo/Lark interactions were not tested in this environment.

## UI implementation notes
`ui_theme.py` provides `RoundedCard` and `RoundedButton`, using built-in Tk canvas primitives. `RoundedCard` exposes a standard `ttk.Frame` via `.content`; actual inputs stay native ttk controls. `RoundedButton` preserves `.config(text=..., state=...)` behavior and supports Enter and Space from the keyboard.
