# Makerlab Return Processor v0.4.14-test

## New: Scan History & Recovery window

This extends v0.4.13-test JSON Recovery. It does not replace the JSON schema or discard any stored records.

New top toolbar:
- **Scan History**: browse all successful marketplace scans recorded so far.
- **Recovery (N)**: open the same window with only unfinished workflows that have saved restore points.

The existing button beside the search controls is retained and renamed **Browse Pending (N)**; it opens the picker instead of silently restoring the most recent pending case.

The window supports:
- Search by Order ID, tracking/search value, SKU, Odoo ticket, or TC/IN transfer ID.
- Filter by marketplace (Shopee, Lazada, TikTok) and workflow status.
- View the scan timestamp, order, SKU list, total QTY, state, transfer, and whether recovery is available.
- Read and copy selected case details, including item decisions, status, remarks, links, error, and saved Odoo/Lark progress.
- **Restore Selected**: load the exact selected unfinished JSON checkpoint into the main interface.
- **Restore for Review**: load an unsafe Odoo checkpoint with automatic stock-return retry disabled.

**Completed cases are view-only.** Scans loaded but never confirmed appear in history but are not automatically recoverable, because v0.4.13 saves restore points only after Confirm All Items.

## Duplicate-prevention safeguards

- Restoring a saved case never submits to Odoo or Lark automatically.
- For a safely paused stock return, the existing ticket and pending Odoo checkpoint are reloaded; operator then clicks **Retry Odoo Return & Continue** after inventory validation.
- For `lark_pending`, the existing Odoo result (including TC/IN) is reloaded; operator clicks **Submit** to retry only Lark.
- Unsafe Odoo checkpoints remain locked for manual review.
- Switching away from an unfinished case requires confirmation and is disallowed when it has no saved restore point.
- Incomplete/corrupt checkpoints missing essential Odoo results are rejected instead of risking duplicate creation.
- The history window does not delete, purge, or modify scan records.

## Files to replace / add

- `main.py` - new toolbar and targeted restoration; uses the new module.
- `history_window.py` - **NEW**, searchable window.
- `workflow_store.py` - supports retrieving full history by passing `limit=None` (existing JSON schema unchanged).

All other Python modules are byte-for-byte unchanged from v0.4.13-test:
`browser_manager.py`, `shopee.py`, `lazada.py`, `tiktok.py`, `odoo.py`, `lark.py`.

## Installation (Python source)

1. Close Makerlab Return Processor.
2. Back up `C:\PlaywrightPAD\data\` to a safe local location.
3. Place these **three** files in `C:\PlaywrightPAD\`:
   - `main.py` (replace)
   - `workflow_store.py` (replace)
   - `history_window.py` (new)
4. Leave `data/`, browser profile, and other Python files untouched.
5. Restart the processor with the usual Python command.

## Building an EXE

Rebuild with PyInstaller after installing all three files. `history_window.py` is statically imported by `main.py` and should be included automatically. Test the rebuilt EXE before sharing it.

## Data privacy and backups

Local history stays in:
- `data/scan_history.json`
- `data/restore_points.json`

Those JSON files contain operational order information. Do not commit `data/`, the Chrome browser profile, or saved credentials to Git. Add `data/` to `.gitignore`. The distributable source ZIP does not include any user runtime JSON records, virtual environment, cookies, or credentials.

The store assumes one processor instance at a time writing to these JSON files. Recovery only guarantees against the workflow state actually saved; always inspect existing Odoo transfers before retrying an uncertain case.

## Verification performed

- Python compilation of all 9 modules.
- Xvfb/Tk UI smoke and screenshot checks.
- History listing and search/filter cases; completed entries view-only.
- Restore a specific TikTok inventory-pending case retaining its existing Odoo Helpdesk checkpoint.
- Restore a separate Lazada Lark-pending case retaining the existing Odoo transfer.
- Confirm before replacing another active unfinished case.
- An unsafe Odoo checkpoint restores for manual inspection but cannot trigger automatic return retry.

These were offline tests with simulated saved JSON and a stub browser; no live Odoo/Lark/TikTok marketplace submission was performed.
