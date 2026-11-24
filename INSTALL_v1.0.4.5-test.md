# Makerlab Return Processor v1.0.4.5-test — Installation

## 1. Back up first

Close the processor. In PowerShell:

```powershell
cd C:\PlaywrightPAD
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = ".\backup-v1045-$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item .\main.py, .\history_window.py, .\workflow_store.py $backup -ErrorAction Stop
Copy-Item .\data "$backup\data" -Recurse -ErrorAction Stop
```

If `data` does not exist, omit its backup step. **Do not delete the active `data/` or `OdooProfile/` directories.**

## 2. Install exactly these 3 Python files

Copy the package versions to `C:\PlaywrightPAD`, replacing:

- `main.py`
- `history_window.py`
- `workflow_store.py`

Keep `odoo.py`, `lark.py`, `ui_theme.py` (including the v1.0.4.4 highlight fix), all marketplace modules, existing settings and profiles unchanged.

## 3. Verify the imports and launch

```powershell
& .\.venv\Scripts\python.exe -m py_compile .\main.py .\history_window.py .\workflow_store.py
& .\.venv\Scripts\python.exe -c "from main import ReturnProcessorApp; from workflow_store import WorkflowStore; from history_window import HistoryRecoveryWindow; print('Imports OK')"
& .\.venv\Scripts\python.exe .\main.py
```

For a PyInstaller EXE, rebuild it after updating the source.

## 4. To DELETE an existing saved case completely from the app

1. Open **Scan History** or **Recovery**.
2. Find and select the scan (use **Archived records** filter if hidden).
3. Click **Delete Local Record**. This is available for all record types.
4. If the scan has Odoo/Lark work, read the warning, type the **exact Order ID** and `DELETE LOCAL RECORD`.
5. The app removes the scan from both local JSON stores and from local duplicate detection. A currently open deleted scan is cleared from the workspace.
6. **Separately inspect/delete/cancel relevant Odoo tickets, stock transfers and approvals and check for Lark filings before submitting the same order again.** The processor cannot perform that external cleanup for you.
7. Search or scan the order again to create a fresh record.

## 5. To reuse a recovered scan after you have cleaned up the previous Odoo case

1. In Odoo, verify the old Helpdesk ticket and all related stock/warehouse transfers are **deleted, cancelled, or otherwise reconciled**; check there was no Lark filing.
2. In **Scan History & Recovery**, select the **active, unfinished** saved scan (unarchive first if required).
3. Click **Reset Odoo for Re-submit**.
4. Carefully read the warning, type the exact Order ID, then type `RESET ODOO`.
5. The scan's marketplace data, SKUs, quantities, classifications, individual remarks and selected Brand New destination remain saved. Its Odoo checkpoint is cleared, and the reset is recorded in the case's local audit history.
6. Review the loaded scan and click **Confirm All Items** again.
7. **Submit to Odoo + Lark** becomes available. No new ticket is created until you deliberately submit.

**Do not use Reset when an older Odoo ticket/transfer still exists or when Lark filing may already have occurred.** For legitimate continuation of an existing transfer, use the existing Odoo/Lark recovery controls instead.

## 6. Why Submit remains disabled immediately after a normal Restore

A restored Odoo checkpoint means the app has already interacted with Odoo. Enabling ordinary Submit could duplicate the Helpdesk ticket or TC/IN. Either recover the existing transfer/Lark step, or explicitly reset the checkpoint **after external cleanup** using step 5. A normal Restore never silently resets Odoo activity.

## 7. Testing and limits

Offline compilation, storage, UI button-state and module-import checks passed. Test with a non-critical case in the live workstation before production. The app does not verify deletions directly in Odoo and cannot guarantee external reconciliation. Active JSON `.bak` files and your manual backups may contain old records even after a local delete.
