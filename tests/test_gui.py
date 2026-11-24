import os, sys, tempfile
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
sys.path.insert(0,str(Path(__file__).resolve().parent/'runtime'))
from workflow_store import WorkflowStore
from history_window import HistoryRecoveryWindow,ManualOdooEntryDialog
import main

with tempfile.TemporaryDirectory() as d:
    os.environ['MAKERLAB_RETURN_DATA_DIR']=d
    st=WorkflowStore(d)
    scan=st.start_scan(platform='Shopee', search_by='Tracking Number', search_input='PH2613470488395',
         order_id='2611028C6TU9DE', return_case={'order_id':'2611028C6TU9DE','refund_text':'1934.00'},
         items=[{'sku':'MLE01249','quantity':1,'amount':2179.0,'classification':'New',
           'decision':'Refunded','status':'Returned','odoo_tag':'Change of Mind (Sealed)',
           'remarks':'New - Stock to BLC','grade':'','platform':'Shopee'}],
         new_stock_destination='BLC/Stock')
    root=tk.Tk(); root.withdraw()
    w=HistoryRecoveryWindow(root,store=st,on_restore=lambda id:True,on_record_changed=lambda *_:None)
    root.update()
    assert w.tree.selection() and w.tree.selection()[0]==scan
    assert w.make_recoverable_button.cget('state')=='normal'
    assert w.manual_odoo_button.cget('state')=='normal'
    st.make_scan_recoverable(scan)
    w.refresh_from_store(); root.update()
    assert w.make_recoverable_button.cget('state')=='disabled'
    snapshot=st.get_restore_point(scan)
    dlg=ManualOdooEntryDialog(w,store=st,scan_id=scan,record=snapshot,
           on_saved=lambda:None,before_save=lambda:True)
    root.update()
    assert len(dlg.entry_vars)==1
    dlg.ticket_url_var.set('https://makerlab.odoo.com/odoo/helpdesk/3/tickets/3647')
    dlg.entry_vars[0][0].set('TC/IN/12232')
    dlg.entry_vars[0][1].set('https://makerlab.odoo.com/odoo/helpdesk/3/tickets/3647/stock.picking/770384')
    dlg.order_confirmation.set('2611028C6TU9DE')
    dlg.confirmed.set(True)
    dlg.note_editor.insert('1.0','Manual warehouse handoff completed in Odoo')
    dlg._save()
    root.update()
    assert not dlg.winfo_exists()
    w.refresh_from_store(); root.update()
    assert w.tree.item(scan,'values')[7]=='TC/IN/12232'
    assert w.tree.item(scan,'values')[8]=='Yes'
    w.destroy(); root.destroy()
    # Check main controller actually enables the existing Lark-only action.
    main.ReturnProcessorApp.start_browser=lambda self: None
    app=main.ReturnProcessorApp()
    app.update()
    app._load_restored_snapshot(st.get_restore_point(scan))
    app.update()
    assert app.manual_lark_button.cget('state')=='normal'
    assert 'Manual TC/IN' in app.manual_lark_button.cget('text')
    assert app.submit_button.cget('state')=='disabled'
    assert app.resume_odoo_button.cget('state')=='disabled'
    app.destroy()
print('GUI / RECOVERY INTEGRATION PASSED')
