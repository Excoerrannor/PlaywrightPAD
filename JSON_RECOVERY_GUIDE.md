# JSON Recovery Quick Guide

The processor creates its runtime data automatically. Do not manually create or edit the live files unless troubleshooting.

## Files

`data/scan_history.json`
- permanent local audit history
- completed cases remain here

`data/restore_points.json`
- unfinished workflows only
- completed workflows are removed automatically

`data/*.bak`
- previous valid copy used for corruption recovery

## After restarting the app

If unfinished work exists, click **Restore Pending (N)**.

- If Odoo is waiting for inventory validation: use **Retry Odoo Return & Continue** after validation.
- If Odoo already completed but Lark did not: the existing Odoo result is restored; use **Submit** to continue with Lark.
- If the restored checkpoint is marked unsafe: review Odoo manually. Automatic retry stays disabled to prevent duplicates.

## Git

Add `data/` to `.gitignore`. Runtime history should stay local and should not be published with releases.
