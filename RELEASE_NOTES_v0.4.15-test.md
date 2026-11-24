# Makerlab Return Processor v0.4.15-test — Glass UI / Responsive Layout

## Interface redesign
- Adopted the supplied Makerlab palette: amber `#FAAD17`, teal `#40A2AF`, white, and high-contrast dark text.
- Preserved Windows native titlebar and existing Windhawk glass effects. No DWM/acrylic manipulation, ttk theme switching, or opaque root background.
- Introduced a consistent toolbar, compact hero header, numbered workflow sections, and visible scan → review → Odoo → Lark workflow hints.
- Placed returned-item list beside the decision/results workspace so SKU rows stay visible when resizing.
- Added compact-width button reflow and native-frame vertical scrolling for shorter windows.
- Highlighted the copyable Odoo TC/IN transfer field with an amber tint.
- Restyled Scan History & Recovery with matching typography, controls, and responsive filters.

## Functionality retained
- Shopee, Lazada, TikTok scanning, parsing, SKU and quantity logic.
- Odoo helpdesk/stock return steps, safe retry checkpoints, and Lark filing.
- Persistent JSON scan history and recovery, including duplicate-prevention safeguards.
- Copyable case fields, item rows, tracking, transfer IDs, and history details.

## Scope and testing
Changed: `main.py`, `history_window.py`. New: `ui_theme.py`.
All marketplace, Odoo, Lark, and JSON storage modules are unchanged.
Python compilation and offline Tk resize/selection/scroll tests passed. Windows Windhawk visual effects and live marketplace/Odoo/Lark actions still require testing on the actual workstation.

**Test / pre-release:** back up `data/` and current processor files before installing; do not include browser profile, credentials, or history JSON in version control or release packages.
