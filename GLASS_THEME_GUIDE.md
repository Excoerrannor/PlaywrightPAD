# v0.4.15-test: Responsive glass-compatible UI

## Installation
Replace `main.py` and `history_window.py`, and **add `ui_theme.py`** to
`C:\PlaywrightPAD`. Keep `workflow_store.py`, `data/`, the browser profile,
all marketplace modules, Odoo, and Lark unchanged. Restart the application.

## What changed
- Same native Tk/Windows title bar and ttk theme: no DWM, Windhawk, alpha,
  window background, or `ttk.Style.theme_use` changes.
- Exact user palette: **amber `#FAAD17`**, **teal `#40A2AF`**, and **white**;
  dark ink is used for contrast on the shown light glass backdrop.
- Left-aligned hero header, visual workflow step hints, numbered sections,
  more legible table and status fields, teal Search and Retry actions,
  amber Submit, amber-tinted copyable TC/IN field.
- Responsive two-column workspace: the SKU table stays on the left, and item
  decisions, status, and Odoo/Lark activity stay on the right. Decision fields
  use two label/control pairs per row; action buttons wrap into two rows on
  wide windows and three rows when compact. Native scrolling makes the entire
  workflow reachable on shorter screens without introducing a solid Canvas.
- Responsive history filters: one row when wide; two rows in compact mode.
- No changes to scanning, classification, Odoo, Lark, JSON recovery,
  duplicate-prevention, marketplace parsers, or saved data.

## Windhawk compatibility
The application **does not** apply a transparent or opaque background to the
root window, modify the Windows titlebar, or change ttk's current theme.
Windhawk owns the translucent window appearance; individual input/table/CTA
surfaces are opaque so they remain readable. Actual glass depends on the
installed Windows/Windhawk theme and should be checked on your workstation.

## Display compatibility
Designed for Windows desktop at 1000px+ wide; test at 1000x735, 1380x930,
and maximized. Horizontal scroll remains available for long item table columns.
If using Windows >125% display scaling, maximize the window for easier use.
