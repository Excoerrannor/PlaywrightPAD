# Makerlab Return Processor v0.4.20-test — Lazada SKU Aggregation

## What's changed

- Lazada returns with repeated Seller SKU IDs now display one line per distinct SKU.
- The displayed QTY is the sum of quantities across matching Lazada Return Item ID rows. Lazada's Returns listing ordinarily exposes one unit per Return Item ID.
- The displayed Amount is the **sum of Refund Amounts**, not an amount to multiply by QTY again.
- The underlying `source_rows`, `return_item_ids`, and `order_item_ids` retain each return's original identifiers for scan history, JSON restore points, and manual auditing.
- The Scan History & Recovery details and Copy All Case Details output list all underlying Lazada Return/Order Item IDs.
- Tracking-number searches still restrict the source lines to that exact tracking number **before** SKU aggregation. Other parcels are not included.
- If any same-SKU source unit is not clearly delivered, the combined Status is left blank for manual review rather than auto-marked Returned.
- Duplicate Return Item IDs within a result are rejected to avoid double-counting.

## Example

Eight Lazada entries for SKU `MLE04875`, each at QTY 1 and Refund Amount ₱140.00:

Before: `MLE04875` appears on eight separate rows, each QTY 1 / Amount 140.00.

After: **one** `MLE04875` row with **QTY 8** and **Amount 1120.00**.

Odoo quantities and Lark amounts use the grouped values once (no repeated multiplication).

## Installation

From v0.4.19-test, replace **only** these files in `C:\PlaywrightPAD`:
- `lazada.py` — grouping logic and source ID preservation
- `main.py` — grouped quantity, refund, and clearer source details
- `history_window.py` — show original Lazada return-item IDs in saved case details

Leave `workflow_store.py`, `odoo.py`, `lark.py`, `tiktok.py`, `shopee.py`, `browser_manager.py`, and `ui_theme.py` unchanged. Back up the three originals first. Restart the processor after replacing them; rebuild the EXE if using a compiled build.

**Do not delete** `data/`, `OdooProfile/`, or the existing restore points. This ZIP includes source code, not an EXE, credentials, or saved browser data.

## Operational note

A single SKU row receives one Classification/Decision/Status for the entire grouped quantity. If individual units of the same SKU require different handling, split them manually into separate rows and adjust quantities/amounts before confirming. Check all original Return Item IDs in Scan History when needed.

## Verification

Python compilation and offline parser/HTML, mock-workflow, Odoo-title, Lark-value, and JSON history/restore tests passed. This is **not** a live Lazada/Odoo/Lark submission test.
