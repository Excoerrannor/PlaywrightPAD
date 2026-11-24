# Makerlab Return Processor v1.0.4.6-test - Installation

This is a focused TikTok multi-return update on top of v1.0.4.5-test.

## Backup

Close the desktop application first. In PowerShell:

```powershell
cd C:\PlaywrightPAD
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = ".\backup-v1046-$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item .\tiktok.py, .\main.py, .\lark.py $backup -ErrorAction Stop
Copy-Item .\data "$backup\data" -Recurse -ErrorAction Stop
```

If there is no `data` directory, omit its backup line. Do not delete `data/` or `OdooProfile/`.

## Replace exactly 3 files

Copy these files into `C:\PlaywrightPAD`:

- `tiktok.py` - support multiple TikTok return cards for one marketplace order
- `main.py` - preserve return IDs/metadata and show the combined scan
- `lark.py` - use individual return-card refunds instead of duplicating the order total

Keep your existing `odoo.py`, `history_window.py`, `workflow_store.py`, `ui_theme.py`, `shopee.py`, `lazada.py`, `browser_manager.py`, Settings, scan history and restore points. **Do not install any unrelated files from an older package.**

## Verify syntax and launch

```powershell
& .\.venv\Scripts\python.exe -m py_compile .\tiktok.py .\main.py .\lark.py
& .\.venv\Scripts\python.exe -c "from tiktok import get_tiktok_return_order; from lark import file_lark_returns; from main import ReturnProcessorApp; print('Imports OK')"
& .\.venv\Scripts\python.exe .\main.py
```

If you use a packaged EXE, rebuild it from these sources.

## Testing a multi-return TikTok order

1. Open TikTok -> Tracking Number and scan the tracking barcode, or search by **Order ID**.
2. If TikTok displays multiple return cards with **the same Order ID**, they may now be loaded together. The application's summary uses the **sum of each return card's Refund**, not the repeated Paid value.
3. Check that the combined **quantity** matches the sum of the returned units, and inspect the per-item Seller SKU and `return_order_id` in copied Case Details.
4. Choose item classifications, decisions, tags, grade and remarks as usual. The system still creates **one Helpdesk ticket per marketplace order** and returns by existing Odoo rules.
5. If one TikTok return card contains several SKUs split across separate Lark filings, manually fill their accurate **Amount** values first. Lark checks that these add up to that return card's refund before starting any submission.
6. Keep the normal Recovery/duplicate-prevention rules. Do not resubmit a case with an existing Odoo ticket just to test this update.

## Limitations

The saved TikTok HTML contained four return-card rows but did not contain an *open* Seller SKU popover. Browser tests used the real four-card row HTML plus synthetic SKU popovers to exercise the complete parser. Actual product SKU values were not established from that file. Live TikTok/Lark/Odoo transactions have not been run.

Tracking number is not displayed inside the return overview row. The scraper still rejects result sets that mix marketplace Order IDs or appear unchanged after a different tracking number is searched. In that situation, **Search By: Order ID** is the safest alternative.
