"""No external requests. Lark submission mocked to test checkpoint transitions."""
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'runtime'))
import main
from workflow_store import WorkflowStore

with tempfile.TemporaryDirectory() as temp:
    os.environ['MAKERLAB_RETURN_DATA_DIR']=temp
    st=WorkflowStore(temp)
    scan_id=st.start_scan(platform='Shopee',search_by='Tracking Number',search_input='PH2613470488395',
        order_id='2611028C6TU9DE', return_case={'order_id':'2611028C6TU9DE','refund_value':1934.0},
        items=[{'sku':'MLE01249','quantity':1,'amount':2179.0,'classification':'New',
                'decision':'Refunded','status':'Returned','grade':'','odoo_tag':'Change of Mind (Sealed)',
                'remarks':'New - Stock to BLC','platform':'Shopee'}],new_stock_destination='BLC/Stock')
    st.make_scan_recoverable(scan_id)
    st.record_manual_odoo_transfers(scan_id,
        ticket_url='https://makerlab.odoo.com/odoo/helpdesk/3/tickets/3647',
        transfer_entries=[{'transfer_id':'TC/IN/12232','transfer_url':
            'https://makerlab.odoo.com/odoo/helpdesk/3/tickets/3647/stock.picking/770384'}],
        operator_reason='Warehouse confirmed manually; no additional Odoo automation.',
        typed_order_id='2611028C6TU9DE', acknowledged=True)
    main.ReturnProcessorApp.start_browser=lambda self:None
    main.messagebox.askyesno=lambda *args,**kwargs:True
    main.simpledialog.askstring=lambda *args,**kwargs:'TC/IN/12232'
    errors=[]
    main.messagebox.showerror=lambda *args,**kwargs:errors.append(args)
    main.messagebox.showwarning=lambda *args,**kwargs:errors.append(args)
    invoked=[]
    def fake_lark(**kwargs):
        invoked.append(kwargs)
        return [{'transfer_id':'TC/IN/12232','sku':'MLE01249_1','quantity':1,
                 'value':1934.0,'decision':'Refunded'}]
    main.file_lark_returns=fake_lark
    app=main.ReturnProcessorApp()
    app.browser.context=object()
    app._load_restored_snapshot(st.get_restore_point(scan_id))
    assert app.manual_lark_button.cget('state')=='normal'
    app.file_lark_from_verified_transfer()
    assert not errors,errors
    assert len(invoked)==1
    assert invoked[0]['odoo_results']['returns'][0]['transfer_id']=='TC/IN/12232'
    assert st.get_scan(scan_id)['workflow_state']=='completed'
    assert st.get_scan(scan_id)['lark_results']
    assert st.get_restore_point(scan_id) is None
    assert st.get_scan(scan_id)['manual_odoo_reconciliation_history']
    app.destroy()
print('MOCKED LARK-ONLY END-TO-END PASSED; NO ODOO OR LARK NETWORK CALLS')
