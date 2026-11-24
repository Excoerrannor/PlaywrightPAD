# Makerlab Return Processor v1.0.4.3-test — Installation

**Baseline:** v1.0.4.2-test. This is a three-file replacement.

## 1. Back up the current installation

Exit the Makerlab Return Processor first. In PowerShell:

```powershell
cd C:\PlaywrightPAD
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = ".\backup-v1043-$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item .\main.py, .\history_window.py, .\workflow_store.py $backup -ErrorAction Stop
Copy-Item .\data "$backup\data" -Recurse -ErrorAction Stop
```

If you have not previously created `data`, omit the second `Copy-Item` command. Do **not** delete/replace `C:\PlaywrightPAD\data` or `OdooProfile`.

## 2. Replace exactly three files

From this package, replace:

- `C:\PlaywrightPAD\main.py`
- `C:\PlaywrightPAD\history_window.py`
- `C:\PlaywrightPAD\workflow_store.py`

**Do not replace** `odoo.py`, `lark.py`, `shopee.py`, `lazada.py`, `tiktok.py`, `browser_manager.py`, `ui_theme.py`, or other existing modules. The patch retains v1.0.4.2's Odoo/Lark integration.

## 3. Check before launching

```powershell
& .\.venv\Scripts\python.exe -m py_compile .\main.py .\history_window.py .\workflow_store.py .\odoo.py
& .\.venv\Scripts\python.exe -c "from workflow_store import WorkflowStore; from history_window import HistoryRecoveryWindow, DuplicateTicketResolutionDialog; from main import ReturnProcessorApp; print('Imports OK')"
& .\.venv\Scripts\python.exe .\main.py
```

If you run a PyInstaller EXE, rebuild the EXE using the updated source files.

## 4. Find records that were previously "deleted"

1. Open **Scan History**.
2. Set **Status → Archived records**.
3. Search for the order number (for example `1133739140128180`).
4. Select the archived entry to inspect the original Odoo ticket and transfer information.
5. Click **Unarchive / Recover** if you want the record visible again. Any Odoo-linked case with enough saved data is restored **for manual review**, not automatic Odoo resubmission.
6. Completed cases and incomplete legacy checkpoints are view-only; they are not automatically reopened for submission.

## 5. Record management

- **Delete Unprocessed:** permanently deletes a local scan and any Recovery point ONLY when no Odoo/Lark work was recorded.
- **Archive Selected:** hides either unprocessed or processed scans, keeping the original Odoo/Lark evidence. Archived items are viewable in the Archived filter.
- **Unarchive / Recover:** brings an archived entry back to History; creates a recovery checkpoint only if sufficient information is present. Previously processed Odoo records are *never* automatically marked safe to retry.
- **Edit Selected:** full editing for unprocessed scans; internal audit notes only for processed or archived cases.

## 6. Resolve the existing-ticket warning

When you scan an order that already has a saved Odoo ticket, the dialog offers:

1. **Inspect Existing** — opens the original Scan History record, including archived records.
2. **Recover Existing** — restores a saved existing transaction for review when sufficient checkpoint information exists; it does not create a new ticket.
3. **Create Separate Ticket** — an exceptional, one-time operator action **only if this is genuinely a different return that requires an additional Helpdesk ticket**. Review the original Odoo ticket and all existing transfers and Lark filings first. Enter a reason with at least 15 characters, re-enter the exact Order ID, type `CREATE SEPARATE TICKET`, and accept the confirmation. The program records an audit event in the new scan before sending any Odoo action.
4. **Cancel** — performs nothing.

The app does **not** remotely verify the operator's claim that the second return is legitimate. It never deletes the original duplicate evidence. Repeated attempts require a new manual confirmation; there is no permanent duplicate-disable setting.

## 7. Validation / limitations

Offline unit and Tkinter UI tests passed, including recovery of pre-v1.0.4.3 archived entries; existing Settings and manual Odoo-to-Lark tests also passed. **Live authenticated Odoo/Lark testing and Windows Windhawk rendering are not verified.** Start with a non-critical case and retain backups.

The local JSON store is designed for **one processor instance at a time**. Do not run two copies against the same `data` directory.
