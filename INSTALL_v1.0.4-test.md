# Install Makerlab Return Processor v1.0.4-test

## Files to replace

In `C:\PlaywrightPAD`, back up, then replace **all four** files:

- `main.py` — Save for Recovery, Settings and per-case destination UI
- `odoo.py` — both Brand New destination routes + frozen checkpoint recovery
- `workflow_store.py` — atomic settings.json and destination persistence
- `history_window.py` — show saved destination and manually saved scan state

The four files must be installed **together**. Do **not** replace `lark.py`, `shopee.py`, `lazada.py`, `tiktok.py`, `browser_manager.py`, `ui_theme.py`, `dispute_checker.py`, or your personal/custom modules.

**DO NOT delete or overwrite:**

- `C:\PlaywrightPAD\data\` (including `scan_history.json` and `restore_points.json`)
- `C:\PlaywrightPAD\OdooProfile\`

The application creates `C:\PlaywrightPAD\data\settings.json` the first time it runs if missing. The original history and restore files are not reset.

## Operator workflow

### Save for Recovery

1. Load the marketplace return as usual.
2. Enter any desired item decisions and remarks; incomplete classifications are allowed.
3. Choose the current **Brand New destination**, if applicable.
4. Click **Save for Recovery** in the top toolbar.
5. Later, click **Recovery** > select the order > **Restore Selected**. Review and confirm the items before submitting.

**Save for Recovery does not submit to Odoo/Lark or make unconfirmed decisions final.** It reuses the current scan ID.

### Default destination

1. Open **Settings** in the top toolbar.
2. Select the default for **New** items: `MNL/Stock` or `BLC/Stock`.
3. Optionally apply it to the current scan if Odoo work has not begun.
4. Click **Save Settings**. Future new scans use the stored default.

### One-off destination

Use **Brand New destination** on the main scan panel before submitting. It overrides the default **for this scan only** and is persisted through recovery. The selection is locked once Odoo work begins.

### Verification in PowerShell

From `C:\PlaywrightPAD`:

```powershell
& .\.venv\Scripts\python.exe -m py_compile .\main.py .\odoo.py .\workflow_store.py .\history_window.py
& .\.venv\Scripts\python.exe -c "from odoo import create_odoo_tickets, resume_odoo_returns, recover_existing_odoo_draft, OdooWorkflowPausedError; print('Odoo imports OK')"
& .\.venv\Scripts\python.exe .\main.py
```

If using PyInstaller/EXE, the executable must be rebuilt from these four modified modules.

## Safety

- Older saved Odoo checkpoints continue using their original `MNL/Stock` behavior. Never change the route of a transfer that already exists.
- `BLC/Stock` must be an available selectable Odoo destination. If it is missing, the automation stops before continuing validation.
- A manual save is **not** permission to recreate an existing Helpdesk ticket or `TC/IN` transfer.
- After an error during transfer creation or validation, use the existing Recovery/manual-review safeguards.

**This is a test release.** Test one single New `BLC/Stock` case and one mixed-classification case in a controlled Odoo environment.
