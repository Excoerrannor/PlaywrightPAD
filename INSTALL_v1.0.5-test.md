# Makerlab Return Processor v1.0.5-test — Installation

**Purpose:** Add manual recovery editing and operator-entered Odoo Helpdesk/TC-IN details for subsequent **Lark-only** filing. This release does not change Odoo automation itself.

## Baseline and files

This release combines:
- `main.py` from v1.0.4.8-test + manual-reconciliation workspace refresh and button labels
- `history_window.py` from v1.0.4.5-test + manual Odoo entry UI and Make Recoverable
- `workflow_store.py` from v1.0.4.5-test + durable manual reconciliation records

Replace **all three** files in `C:\PlaywrightPAD`:

- `main.py`
- `history_window.py`
- `workflow_store.py`

**Keep unchanged** your current `odoo.py` (v1.0.4.9-test), `lark.py` (v1.0.4.8-test), `tiktok.py` (v1.0.4.6-test), `ui_theme.py` (v1.0.4.4-test), the other marketplace modules, browser profiles and every file in `data`.

1. Exit the app fully.
2. Back up the three Python files and the **entire** `C:\PlaywrightPAD\data` folder. Back up the `.bak` JSON copies too.
3. Replace the three files in the project root. Do **not** replace or erase your `data` folder.
4. Launch the program using your usual `.venv`.
5. Confirm that Scan History now shows **Make Recoverable** and **Enter Manual Odoo / TC-IN**.

Optional import check:

```powershell
& .\.venv\Scripts\python.exe -c "from workflow_store import WorkflowStore; from history_window import ManualOdooEntryDialog; from main import ReturnProcessorApp; print('Manual recovery imports OK')"
```

## Operator workflow — existing Odoo ticket manually fixed

1. Open **Scan History**, find and select the correct marketplace order.
2. Click **Edit Selected** to correct *unsubmitted* item details, remarks, destination, etc. If Odoo work was already recorded, transactional item fields remain locked; manual Odoo identifiers can still be edited separately. Do not confuse an existing Odoo-linked scan with a fresh scan.
3. If the row says Recovery **No**, click **Make Recoverable**. This preserves previously recorded Odoo work and does not create a Helpdesk ticket.
4. Click **Enter Manual Odoo / TC-IN**. The dialog accepts an existing **Helpdesk ticket URL** and (optionally) its title, plus an exact **TC/IN ID** and **transfer URL** for *each* distinct classification/decision return group. The fields are prefilled from any existing checkpoint; correct them if needed.
5. Enter your audit note describing what you fixed manually. Check the verification acknowledgment and type the exact marketplace **Order ID**.
6. Click **Save Existing Odoo Details**. This writes `odoo_checkpoint` / `manual_odoo_reconciliation_history` into the Recovery and History JSON files. **No Odoo or Lark browser action takes place here.**
7. Select the scan and click **Restore for Review**.
8. In the main processor click **Confirm Manual TC/IN & File Lark**. Verify all original Odoo tickets and transfers, classifications, SKU/QTY, warehouse approval or QC handoffs, and that no Lark record has already been filed.
9. Confirm Yes and type the last recorded `TC/IN/#####` exactly.
10. The app saves a durable Lark-pending checkpoint, then files Lark **only**. Odoo browser automation is not called. After confirmed Lark success, the same Scan History record is marked Completed and its Recovery record is removed.

### Example format

- Helpdesk ticket URL: `https://makerlab.odoo.com/odoo/helpdesk/3/tickets/3647`
- Transfer ID: `TC/IN/12232`
- Transfer URL: `https://makerlab.odoo.com/odoo/helpdesk/3/tickets/3647/stock.picking/770384`

For multiple classifications, enter the **individual** TC/IN ID/URL for every group; one transfer cannot be reused for different groups.

## Safety limits

- The app does **not** verify the real external Odoo status on this manual route. The confirmation is an operator audit; `validated` is not invented as true.
- It rejects mismatched Order IDs, malformed ticket/transfer links, transfer IDs from different Helpdesk tickets, duplicate transfer IDs, wrong SKU/quantity groupings, missing item decisions, previously saved Lark results, or completed/archived cases.
- It does not enable **Submit to Odoo + Lark** or automatic Odoo retry for manual checkpoints; it enables only the separate confirmation-gated Lark path.
- Existing filed Lark records and immutable Odoo-linked item decisions remain protected from casual edits. Correct identifiers through the manual Odoo dialog; use the existing external reconciliation/reset workflows only for intentionally restarted cases.
- If a Lark attempt might have partially submitted, **inspect Lark before any retry**. Do not duplicate filing. If a manual save reports a disk error, inspect both JSON files and their `.bak` copies before continuing.

## Testing scope

- Python syntax and full application imports: passed.
- 10 offline storage tests, GUI saved-record tests, main-workspace button-state check: passed.
- Mocked end-to-end Lark-only checkpoint sequence: passed.
- **Not tested:** live authenticated Odoo or Lark filing on the actual Windows workstation.
