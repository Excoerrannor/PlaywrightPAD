# Installation — Makerlab Return Processor v0.4.20-test

1. Close Makerlab Return Processor.
2. Back up `C:\PlaywrightPAD\lazada.py`, `main.py`, and `history_window.py`.
3. Replace only those three files with the ones in this package.
4. Keep your `C:\PlaywrightPAD\data` and `OdooProfile` folders unchanged.
5. Start the processor again. If using the compiled EXE, rebuild it first.
6. Search the provided Lazada tracking number, verify that repeated SKUs appear only once, and check that QTY and Amount equal the sum of the source rows.

For groups with different physical handling or status, split manually before confirming. No Odoo/Lark processing is performed by the installation itself.
