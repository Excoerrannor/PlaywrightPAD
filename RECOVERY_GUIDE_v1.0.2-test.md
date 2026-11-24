# Makerlab Return Processor - Odoo Ticket Checkpoints (v1.0.2-test)

## What changed

New Odoo tickets are protected by **durable JSON checkpoints** at these boundaries:

1. **Before clicking `Add`**: save `ticket_creation_in_progress` (manual-review-only). This prevents an unconfirmed Add operation from being blindly repeated after a crash.
2. **As soon as Odoo confirms the created ticket URL**: save `ticket_created`, including the exact ticket title and URL. This happens **before** any product dropdown, tag, or priority interaction.
3. **After ticket product/tag/priority setup**: save `return_preparing` so the existing ticket can be reopened for pending stock returns.
4. **Before clicking Create Return in Odoo**: save `return_creation_in_flight` and disable automatic retry. If Odoo creates a TC/IN but Chrome disconnects before it is captured, the operator must review Odoo instead of risking another stock return.
5. **After each successfully validated TC/IN**: save transfer ID/URL and advance the next return index. Later returns can resume without recreating completed transfers.
6. **When all Odoo returns finish**: save complete Odoo results as `lark_pending`, before Lark starts.

JSON is written atomically in the existing `data/restore_points.json` store, with related audit entries in `data/scan_history.json`. The software stops Odoo if a required recovery checkpoint cannot be written.

## If Odoo product selection fails

* The processor keeps the newly created ticket and its URL in JSON.
* **Recovery** -> select the correct order -> **Restore Selected**.
* Choose **Retry Odoo Return & Continue**. The processor opens the existing ticket, retries product/tag/priority setup, then continues pending returns and Lark.
* **Do not use Submit** to attempt to create another ticket for the same order.

## If the stock return is uncertain

If Odoo already received `Create Return` but a subsequent step fails, the checkpoint is marked **Manual Review**. Automatic retry is disabled until the operator verifies the corresponding Odoo picking/transfer. This intentionally avoids duplicate inventory movements.

## Duplicate protection

Scanning the same marketplace order a second time does not bypass a saved Odoo checkpoint: before creating a new ticket, the processor checks active recovery points **and completed scan history** for the same platform and Order ID. If an Odoo ticket was recorded, submission is blocked and the operator is directed to History/Recovery.

## Installation

1. Exit the processor. Back up `C:\PlaywrightPAD\main.py`, `odoo.py`, and `history_window.py`.
2. Copy the three updated Python files to `C:\PlaywrightPAD`, overwriting those files.
3. **Do not replace or delete** `C:\PlaywrightPAD\data` or `C:\PlaywrightPAD\OdooProfile`.
4. Restart the Python application. If you use a packaged EXE, rebuild it with the updated files.
5. Test with a non-critical case or a test Odoo environment before relying on the release in production.

## Limits

* This change cannot retroactively reconstruct ticket checkpoints for tickets created with older versions. **Ticket #03546**, for example, must be inspected in Odoo before any further attempt unless it was independently saved in your existing JSON.
* The software does not recover or automatically retry an uncertain Odoo stock-return transaction. Manual reconciliation remains necessary.
* One return-order scan does not necessarily cover every unusual Odoo interface change. This build passed offline simulations; **live Odoo/Lark submission was not tested here**.
* Multiple simultaneous processor instances sharing one data directory are not supported by this JSON store.
