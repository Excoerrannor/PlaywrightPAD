# Installation - Makerlab Return Processor v1.0.4.7-test

1. Close the Makerlab Return Processor and its automated Chrome sessions.
2. Back up `C:\PlaywrightPAD\main.py`, `odoo.py`, `lark.py` and the entire `C:\PlaywrightPAD\data` folder.
3. Extract the ZIP and copy **all three** Python files to `C:\PlaywrightPAD`, replacing the older versions together.
4. Leave the other modules, `data/` JSON, and `OdooProfile/` untouched.
5. From PowerShell in `C:\PlaywrightPAD`, verify imports:

   ```powershell
   & .\.venv\Scripts\python.exe -c "from main import ReturnProcessorApp; from lark import verify_tiktok_source_coverage; from odoo import create_odoo_tickets, resume_odoo_returns, OdooWorkflowPausedError; print('v1.0.4.7 imports OK')"
   ```

6. Restart the application. Test with a controlled non-critical case.

## Usage

- For an Odoo **Zero Demand Warning**, the program clicks **Keep lines** only if the exact `TC/IN` and target SKU/Demand data are verified. Do not click Validate again if the first click may have succeeded.
- After a case reaches Odoo-complete / Lark-pending, the previous Submit control becomes **Retry Lark Only**. Close any open error dialog before using it. Check existing Lark Item Returns records first; the previous attempt may have partially submitted.
- If the case reports **TikTok multi-return source coverage incomplete**, the saved scan does not contain every source return-card unit. Inspect TikTok, the case's saved item data, and existing Odoo transfers. Do not bypass the error or create another Odoo ticket. This release does not automatically repair already-partial scans.
