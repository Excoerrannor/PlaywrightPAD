# Makerlab Return Processor v1.0.4.5-test

**November 12, 2026 | Test/pre-release**  
**Based on:** v1.0.4.3-test history/recovery and duplicate-resolution logic plus v1.0.4.4-test selection contrast.  
**Changed files:** `main.py`, `history_window.py`, `workflow_store.py` only.

## Why this update

The previous History & Recovery window disabled Delete for any Odoo/Lark-linked scan. Restoring an Odoo Manual Review scan correctly disabled ordinary Submit to avoid duplicate tickets, but users who had independently removed/reconciled the old Odoo ticket could not reset the stale local checkpoint.

## New: Delete Local Record (any scan)

- Replaces **Delete Unprocessed** with **Delete Local Record** in Scan History & Recovery.
- Enabled for unprocessed, Odoo-pending, completed and archived scans.
- Unprocessed records require standard Yes/No confirmation.
- Odoo/Lark-linked scans require a detailed external-side warning, exact Order ID entry, and the exact phrase `DELETE LOCAL RECORD`.
- On confirmation, the app removes the original scan ID from **both** `data/scan_history.json` and `data/restore_points.json`, verifies their absence, and removes the scan from local duplicate detection.
- Deleting a record opened in the main workspace clears that workspace to avoid acting on stale Odoo state.
- **Does not delete anything in Odoo, Lark, or any marketplace.** If prior tickets, stock transfers, approvals, or Lark filings still exist, submitting the same order again could create duplicates. Operator must review and reconcile all external transactions separately.
- Existing `Archive Selected` and `Unarchive / Recover` are retained; Archive still preserves local duplicate protection.
- Normal `WorkflowStore.delete_saved_record` remains backward-compatible (processed records archive by default). Only the new explicitly confirmed method physically removes protected local records.

## New: Reset Odoo for Re-submit (recovery reuse)

- Enabled only for **active unfinished scans** with an Odoo checkpoint and recovery snapshot and **no recorded Lark results**.
- Use it only after inspecting and manually deleting/cancelling the prior Helpdesk ticket and related TC/IN stock transfers in Odoo (including approvals, as appropriate).
- Requires a detailed warning, typed exact Order ID, and `RESET ODOO`.
- Keeps the original scan ID, platform, marketplace identifiers, items, SKU/quantities, individual remarks, warehouse destination, and source case data.
- Clears Odoo checkpoint/results and stale error state in both JSON files. Retains previous ticket/transfer IDs in an **internal reset audit entry** without treating them as active Odoo work.
- Clears confirmed item decisions **as a confirmation flag** (item field values remain), requiring **Confirm All Items** again.
- After reconfirmation, ordinary **Submit to Odoo + Lark** can be enabled. No Odoo automation is executed by Reset itself.
- Completed records, archived records, cases with recorded Lark filings, or inconsistent History/Recovery records cannot be reset with this action. These can still be inspected/archived or intentionally deleted from local JSON as above.

## Safeguards retained

- Restoring an existing Odoo checkpoint still does **not** directly re-enable Submit.
- Existing `Retry Odoo Return & Continue` and `Confirm Existing TC/IN & File Lark` recovery actions remain untouched.
- Same-ticket recovery and idempotency protections for regular Odoo automation remain intact.
- Existing Settings (BLC/Stock or MNL/Stock), Save for Recovery, item remarks, marketplace parsing, zero-demand Keep lines, QC, and Lark integration unchanged.
- No changes to `odoo.py`, `lark.py`, or marketplace modules.

## Technical tests

- `py_compile` passed for all 3 changed Python files.
- 11 store/delete/reset tests passed, including protected deletion validation, archived deletion, stale checkpoint reset, no duplicate scan IDs, no Lark reset, and settings preservation.
- Headless Tkinter tests verified the new Delete and Reset button enablement for a selected Manual Review scan, and Delete-only availability for a draft scan.
- Imported updated `main.py` with the v1.0.4.1 Odoo module, v1.0.4.4 UI theme, and installed marketplace/Lark modules successfully.
- Button-state test verified existing Odoo checkpoint => Submit disabled; reset => Confirm enabled but Submit disabled; reconfirmation => Submit enabled.
- **Not tested against the live Makerlab Odoo/Lark services or in Windows/Windhawk.**

## Important privacy/data detail

Deleting the active JSON entries removes the scan from the app's history, recovery, and duplicate checks. Existing JSON `.bak` files or copies made during your own backup may retain older versions. The processor does not automatically purge those backups. Never include `data/` or `OdooProfile/` in public releases.
