# Makerlab Return Processor v1.0.4.3-test

**Date:** November 11, 2026  
**Build type:** Test/pre-release  
**Upgrade:** Three files changed: `main.py`, `history_window.py`, `workflow_store.py`.

## Why this patch is needed

v1.0.4.2-test archived Odoo-linked scans when the user clicked Delete. The archived entries disappeared from History and Recovery but stayed in `scan_history.json` to block duplicate tickets. The user could not see or reopen the archived evidence and instead encountered an unexpected **Existing Odoo Ticket Saved** warning.

## Changes

### Archived records now visible

- Added **Archived records** status filter in Scan History & Recovery.
- Archived cases display their original Odoo ticket, transfer references, original workflow state and local notes.
- `Inspect Existing` from the duplicate warning navigates directly to the archived/active matching scan.

### Explicit archive and delete

- **Archive Selected** is a separate action and retains Odoo/Lark evidence. A fresh archive preserves a full copy of the original Recovery snapshot within local history before removing the active restore point.
- **Delete Unprocessed** permanently removes only unprocessed local scans from history and recovery.
- Processed and archived records cannot be permanently deleted from the interface. This prevents losing the only ticket/transfer evidence.
- Archived items remain searchable and accept local audit notes (not transactional edits).

### Unarchive / Recover

- Reopens archived records in History, including records archived by the earlier v1.0.4.2-test build.
- Reconstructs a Recovery snapshot only when saved case data is sufficient.
- Odoo-linked checkpoints resume **manual-review-only** with `resume_safe=False`; no new Return, Validate, or Odoo ticket is sent by reopening.
- Completed Lark cases and legacy records missing required confirmation remain view-only rather than inventing data or permitting unsafe submission.

### Duplicate-ticket resolution

- Replaced the one-way warning with **Inspect Existing**, **Recover Existing**, **Create Separate Ticket**, and **Cancel**.
- Separate Ticket requires a specific reason, exactly retyped Order ID, typed phrase `CREATE SEPARATE TICKET`, and an additional acknowledgement that the original Odoo/Lark case has been checked.
- Writes/reads back a `duplicate_override_events` audit entry **before** proceeding toward Odoo.
- Preserves the original scan and its duplicate guard; no permanent whitelist or silent bypass.
- If the exception cannot be saved, Odoo remains blocked. A new exception is required for subsequent attempts.

### Compatibility retained

- Configurable `MNL/Stock` / `BLC/Stock` Brand New destination.
- Save for Recovery and per-item remarks.
- Existing Odoo Helpdesk, stock return grouping, warehouse handoff, zero-demand Keep lines, QC, Lark integration.
- Operator-confirmed **Existing TC/IN -> Lark only** path from v1.0.4.1-test.
- Atomic JSON recovery and persisted scan IDs.

## Test results

- 33 offline automated history/archive/GUI/integration tests passed.
- Prior v1.0.4 Settings, destination routing, save/restore regression checks passed.
- Prior v1.0.4.1 manual Odoo-to-Lark recovery regression checks passed.
- Python syntax compilation and Tkinter layout screenshot inspection completed.
- **No live Odoo or Lark transaction was performed.**

## Limits

- Archived cases missing a verified checkpoint or required item confirmation can be viewed but cannot be automatically recovered.
- The *Create Separate Ticket* exception relies on explicit operator review; the app does not confirm directly with Odoo that the previous ticket is fully reconciled.
- This release doesn't delete or change existing Odoo tickets, stock transfers, warehouse approval tasks, or Lark records.
- Keep backups of `data/` and original Python files. Do not run simultaneous instances sharing the same data directory.
