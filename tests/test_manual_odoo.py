import copy
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow_store import WorkflowStore
from odoo import confirm_existing_transfers_for_lark

ORDER = '2611028C6TU9DE'
TICKET = 'https://makerlab.odoo.com/odoo/helpdesk/3/tickets/3647'

def item(sku='MLE01249', classification='New', qty=1, status='Returned'):
    return {'sku':sku, 'quantity':qty, 'amount':2179.0,
            'classification':classification, 'decision':'Refunded', 'status':status,
            'grade': 'B' if classification == 'Unsealed' else '',
            'odoo_tag':'Change of Mind (Sealed)' if classification == 'New' else 'Damaged / Defective Item',
            'remarks':'Operator manually fixed Odoo', 'platform':'Shopee'}

def setup(items=None, *, platform='Shopee'):
    tmp=tempfile.TemporaryDirectory()
    store=WorkflowStore(tmp.name)
    store.start_scan(platform=platform, search_by='Tracking Number', search_input='TEST',
                     order_id=ORDER, return_case={'order_id':ORDER,'refund_value': 2179.0},
                     items=items if items is not None else [item()],
                     new_stock_destination='BLC/Stock')
    scan_id=store.list_recent_scans()[0]['scan_id']
    return tmp,store,scan_id

def links(n=1):
    return [{'transfer_id': f'TC/IN/{12232+i}',
             'transfer_url':f'{TICKET}/stock.picking/{770384+i}'} for i in range(n)]

def manual(store, scan_id, entries=None, **kw):
    return store.record_manual_odoo_transfers(
        scan_id, ticket_url=kw.get('ticket_url',TICKET),
        transfer_entries=entries if entries is not None else links(),
        typed_order_id=kw.get('typed_order_id',ORDER),
        acknowledged=kw.get('acknowledged',True),
        operator_reason=kw.get('operator_reason','Odoo repaired manually; filing Lark only.'),
        expected_updated_at=kw.get('expected_updated_at'),
    )

def fails(fn, needle=''):
    try:
        fn()
    except (ValueError, RuntimeError, PermissionError) as err:
        if needle and needle.lower() not in str(err).lower():
            raise AssertionError((needle,repr(err))) from err
        return
    raise AssertionError('Expected error')

def test_new_scan_manual_workflow():
    tmp, st, id = setup()
    try:
        assert st.get_restore_point(id) is None
        initial=st.make_scan_recoverable(id)
        assert initial['workflow_state']=='manually_saved'
        assert st.get_scan(id)['workflow_state']=='manually_saved'
        manual(st, id, expected_updated_at=initial['updated_at'])
        snapshot=st.get_restore_point(id)
        assert snapshot['workflow_state']=='manual_review'
        assert snapshot['case_decision']['confirmed']
        assert snapshot['odoo_results'] is None
        cp=snapshot['odoo_checkpoint']
        assert cp['resume_safe'] is False and cp['manual_entry']
        assert cp['new_stock_destination']=='BLC/Stock'
        assert cp['ticket_url']==TICKET
        assert cp['returns'][0]['transfer_id']=='TC/IN/12232'
        assert st.get_scan(id)['odoo_checkpoint']==cp
        result=confirm_existing_transfers_for_lark(checkpoint=cp,order_id=ORDER,
                        returned_products=snapshot['items'],confirmed_transfer_id='TC/IN/12232')
        assert result['returns'][0]['manual_verified_for_lark']
        assert result['stage']=='returns_complete_operator_verified_for_lark'
        assert not st.get_scan(id).get('lark_results')
    finally: tmp.cleanup()

def test_multiple_groups_and_reroute():
    tmp, st, id=setup([item(), item('MLE01499','Defective',2)])
    try:
        st.make_scan_recoverable(id)
        manual(st, id, links(2))
        cp=st.get_restore_point(id)['odoo_checkpoint']
        assert [g['classification'] for g in cp['returns']]==['New','Defective']
        result=confirm_existing_transfers_for_lark(checkpoint=cp,order_id=ORDER,
            returned_products=st.get_restore_point(id)['items'],
            confirmed_transfer_id='TC/IN/12233')
        assert len(result['returns'])==2
    finally: tmp.cleanup()

def test_previous_odoo_checkpoint_replaced_with_audit():
    tmp, st, id=setup()
    try:
        point=st.make_scan_recoverable(id)
        cp={'order_id':ORDER,'ticket_title':ORDER+' - MLE01249_1',
            'ticket_url':TICKET,'pending_return':{'return_index':1,'transfer_id':'TC/IN/12000',
            'transfer_url':f'{TICKET}/stock.picking/111'},
            'returns':[], 'resume_safe':False, 'stage':'manual_review'}
        point.update(odoo_checkpoint=cp, case_decision={'confirmed':True}, workflow_state='manual_review')
        st.save_restore_point(id,point)
        st.update_scan(id,workflow_state='manual_review',odoo_checkpoint=cp,case_decision=point['case_decision'])
        manual(st,id)
        s=st.get_restore_point(id)
        assert s['manual_odoo_reconciliation_history'][-1]['previous_ticket_url']==TICKET
        assert s['odoo_checkpoint']['returns'][0]['transfer_id']=='TC/IN/12232'
        assert st.get_scan(id)['manual_odoo_reconciliation_history']
    finally: tmp.cleanup()

def test_validation():
    tmp, st, id=setup()
    try:
        st.make_scan_recoverable(id)
        fails(lambda: manual(st,id,typed_order_id='WRONG'),'order')
        fails(lambda: manual(st,id,acknowledged=False),'order')
        fails(lambda: manual(st,id, operator_reason='short'),'reason')
        fails(lambda: manual(st,id,entries=links(2)),'exactly')
        fails(lambda: manual(st,id,entries=[{'transfer_id':'TC/IN/12232','transfer_url':TICKET+'/stock.picking/999'}],ticket_url='https://attacker.example/odoo/helpdesk/3/tickets/3647'),'helpdesk')
        fails(lambda: manual(st,id,entries=[{'transfer_id':'TC/IN/12232','transfer_url':TICKET.replace('3647','3648')+'/stock.picking/770384'}]), 'belong')
        fails(lambda: manual(st,id,entries=[{'transfer_id':'Bad ID','transfer_url':TICKET+'/stock.picking/770384'}]),'TC/IN')
        fails(lambda: manual(st,id,expected_updated_at='expired'),'changed')
        assert st.get_restore_point(id)['odoo_checkpoint'] is None
    finally: tmp.cleanup()

def test_archived_complete_refusal():
    tmp, st, id=setup()
    try:
        st.make_scan_recoverable(id)
        st.archive_saved_record(id)
        fails(lambda: st.make_scan_recoverable(id),'unarchive')
        fails(lambda: manual(st,id),'unarchive')
    finally: tmp.cleanup()

def test_locked_scan_edits_do_not_rewrite_odoo():
    tmp,st,id=setup()
    try:
        st.make_scan_recoverable(id)
        manual(st,id)
        fails(lambda: st.edit_saved_record(id, {'items':[item('MLE00001')]}),'only internal notes')
        st.edit_saved_record(id, {'operator_notes':'Operator corrected warehouse case manually'})
        assert st.get_restore_point(id)['odoo_checkpoint']['returns'][0]['transfer_id']=='TC/IN/12232'
    finally: tmp.cleanup()

def test_lark_previously_filed_refusal():
    tmp,st,id=setup()
    try:
        st.make_scan_recoverable(id)
        st.update_scan(id,workflow_state='completed',lark_results=[{'sku':'MLE01249'}])
        fails(lambda: manual(st,id),'completed')
    finally: tmp.cleanup()

for fn in [test_new_scan_manual_workflow,test_multiple_groups_and_reroute,
           test_previous_odoo_checkpoint_replaced_with_audit,test_validation,
           test_archived_complete_refusal,test_locked_scan_edits_do_not_rewrite_odoo,
           test_lark_previously_filed_refusal]:
    fn()
    print('PASS',fn.__name__)
print('ALL 7 MANUAL RECOVERY TESTS PASSED')

def test_audit_retained_when_lark_checkpoint_regenerated():
    tmp,st,id=setup()
    try:
        st.make_scan_recoverable(id)
        manual(st,id)
        saved=st.get_restore_point(id)
        event=saved['manual_odoo_reconciliation_history'][-1]
        # Main generates a new snapshot without custom audit keys.
        newer={k:v for k,v in saved.items() if k not in (
            'manual_odoo_reconciliation_history','manual_recovery_events')}
        newer.update(workflow_state='lark_pending',odoo_results={
            **saved['odoo_checkpoint'],'stage':'returns_complete_operator_verified_for_lark'},
            odoo_checkpoint=None)
        st.save_restore_point(id,newer)
        restored=st.get_restore_point(id)
        assert restored['manual_odoo_reconciliation_history'][-1]==event
        assert restored['manual_recovery_events']
    finally: tmp.cleanup()

def test_legacy_history_only_odoo_is_locked():
    tmp,st,id=setup()
    try:
        st.update_scan(id,workflow_state='odoo_ticket_created',case_decision={'confirmed':True})
        s=st.make_scan_recoverable(id)
        assert s['odoo_checkpoint']['needs_operator_reconciliation']
        assert not s['odoo_checkpoint']['resume_safe']
        assert s['workflow_state']=='manual_review'
    finally: tmp.cleanup()

test_audit_retained_when_lark_checkpoint_regenerated()
print('PASS test_audit_retained_when_lark_checkpoint_regenerated')
test_legacy_history_only_odoo_is_locked()
print('PASS test_legacy_history_only_odoo_is_locked')

def test_orphan_recovery_restores_missing_history():
    tmp,st,id=setup()
    try:
        st.make_scan_recoverable(id)
        data=st._read_json(st.scan_history_path, {'schema_version':1,'scans':[]})
        data['scans']=[]
        st._atomic_write(st.scan_history_path,data)
        assert st.get_scan(id) is None
        manual(st,id)
        assert st.get_scan(id)['odoo_checkpoint']['returns'][0]['transfer_id']=='TC/IN/12232'
    finally: tmp.cleanup()

test_orphan_recovery_restores_missing_history()
print('PASS test_orphan_recovery_restores_missing_history')
