# Scan History / Recovery - Quick Guide

1. Launch the processor.
2. Use the top toolbar: **Scan History** to browse all cases, or **Recovery (N)** to view pending cases only.
3. Use **Search** to find an Order ID, tracking number, SKU, Odoo ticket, or `TC/IN/#####`.
4. Optionally filter **Platform** and **Status**.
5. Select a case in the table; review the saved details below. Use **Copy Details** if needed.
6. If **Restore Selected** is enabled, click it. Confirm switching if another case is currently displayed.
7. The saved order appears in the main processor. Then:
   - **Inventory pending**: validate the inventory transaction in Odoo, then click **Retry Odoo Return & Continue**.
   - **Lark pending**: click **Submit** to continue **Lark only** with the existing Odoo results.
   - **Manual Odoo review**: examine existing Odoo activity; automatic retry remains disabled.
   - **Ready to submit**: review saved decisions and click **Submit** when ready.

**Safety:** Simply opening the history window or restoring a case never creates a new Odoo ticket/stock return or files Lark. Completed cases have no Restore button.

## Installation

Required files in `C:\PlaywrightPAD`:

- `main.py` (replace)
- `workflow_store.py` (replace)
- `history_window.py` (new)

Keep your existing `data` directory. Back it up before upgrading. Do **not** push `data/` to GitHub.

## Important limitations

- History is recorded for successful return loads; failed searches may not appear.
- Unconfirmed scans are view-only because no restore checkpoint exists for them.
- JSON files are intended for one concurrently running app instance.
- Always verify Odoo/Lark records before resuming a workflow whose external state is uncertain.
