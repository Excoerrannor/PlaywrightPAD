"""Offline tests only. Never access Odoo/Lark or a real browser."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import lark
import main
from workflow_store import WorkflowStore, has_external_work
import wrong_item_lark as wrong


def item(sku='MLE00001', qty=2, kind='Wrong Item', received='Different USB adapter',
         status='In-Dispute', marketplace='Shopee'):
    return {'sku': sku, 'quantity': qty, 'amount': 250.00,
            'classification': kind, 'decision': 'Disputed', 'status': 'Returned',
            'odoo_tag': '', 'received_item': received,
            'wrong_item_status': status, 'platform': marketplace,
            'grade': '', 'remarks': 'Sealed bag received'}


class FakeWidget:
    def __init__(self, text=''):
        self.text = text
    def cget(self, name):
        return self.text
    def config(self, **kwargs):
        self.text = kwargs.get('text', self.text)


class PlanTests(unittest.TestCase):
    def test_form_identity_and_exact_status_options(self):
        self.assertIn('shrlgqkLCe66MOX6wjiz9QbGaqb', wrong.FORM_URL)
        self.assertEqual(wrong.FORM_FIELDS['order_id'], 'fldF74VqNi')
        self.assertEqual(wrong.FORM_FIELDS['sku'], 'fldzpfI9B4')
        self.assertEqual(wrong.FORM_FIELDS['received_item'], 'fldQGBqpuv')
        self.assertEqual(wrong.FORM_FIELDS['status'], 'fld6Fri64S')
        self.assertEqual(tuple(wrong.WRONG_ITEM_STATUSES),
            ('Refunded (Seller Fault)', 'Dispute Approved',
             'Dispute Rejected', 'In-Dispute'))

    def test_sku_quantity_and_individual_values(self):
        rows = [item(), item('MLE00002', 1, 'Scam', 'Different fan', 'Dispute Rejected')]
        plans = wrong.plan_wrong_item_filings('ORDER123', rows)
        self.assertEqual([x['sku'] for x in plans], ['MLE00001_2', 'MLE00002_1'])
        self.assertNotEqual(plans[0]['route_key'], plans[1]['route_key'])
        self.assertIn('prefill_Received%20Item=', wrong.form_prefill_url(plans[0]))
        self.assertEqual(plans[1]['status'], 'Dispute Rejected')

    def test_missing_received_and_status_block(self):
        for changes in ({'received_item': ''}, {'wrong_item_status': ''},
                        {'wrong_item_status': 'Dispute Won'}):
            row = item()
            row.update(changes)
            with self.assertRaises(ValueError):
                wrong.plan_wrong_item_filings('ORDER123', [row])

    def test_normal_classifications_excluded(self):
        normal = item('MLE00002', 1, 'Defective')
        rows = [normal, item()]
        self.assertEqual(len(wrong.plan_wrong_item_filings('ORDER123', rows)), 1)
        fake = SimpleNamespace(returned_products=rows)
        self.assertEqual(main.ReturnProcessorApp.returned_items_for_odoo(fake), [normal])

    def test_validator_requires_tag_only_for_normal_return(self):
        fake = SimpleNamespace(returned_products=[item()],
                               current_order_id='ORDER123',
                               current_platform='Shopee')
        main.ReturnProcessorApp.validate_all_items(fake)
        fake.returned_products = [item('A', kind='Defective')]
        with self.assertRaisesRegex(ValueError, 'Odoo Tag'):
            main.ReturnProcessorApp.validate_all_items(fake)

    def test_default_status(self):
        self.assertEqual(wrong.default_wrong_item_status('Disputed'), 'In-Dispute')
        self.assertEqual(wrong.default_wrong_item_status('Refunded'),
                         'Refunded (Seller Fault)')


class PersistenceTests(unittest.TestCase):
    def test_partial_lark_progress_is_protected_and_restorable(self):
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStore(Path(temp))
            rows = [item()]
            scan = store.start_scan(platform='Shopee', search_by='Order ID',
                   search_input='ORDER123', order_id='ORDER123',
                   return_case={'refund_value':250}, items=rows)
            result = {'route_key':'wrong:123', 'submitted': True}
            store.save_restore_point(scan, {
                'order_id':'ORDER123', 'items':rows,
                'wrong_item_lark_results':[result], 'normal_lark_results':[],
                'workflow_state':'lark_pending',
            })
            store.update_scan(scan, workflow_state='lark_pending',
                wrong_item_lark_results=[result])
            restored = store.get_restore_point(scan)
            self.assertEqual(restored['wrong_item_lark_results'], [result])
            self.assertTrue(has_external_work(store.get_scan(scan), restored))
            with self.assertRaises(ValueError):
                store.edit_saved_record(scan, {'items':[item(sku='DIFFERENT')]})


class SubmissionTests(unittest.TestCase):
    def test_form_writes_only_four_fields_and_verifies_before_submit(self):
        plan = wrong.plan_wrong_item_filings('ORDER123', [item()])[0]
        entered = {}
        selected = {}
        clicks = []
        class FakeLocator:
            @property
            def first(self): return self
            def wait_for(self, **kwargs): return None
        class FakePage:
            def bring_to_front(self): return None
            def goto(self, url, **kwargs): self.url = url
            def get_by_role(self, role, name, exact=False):
                self.role = (role, name, exact)
                return self
            def click(self): clicks.append('Submit')
            def wait_for(self, **kwargs): return None
            def get_by_text(self, name, exact=False):
                self.success = (name,exact)
                return FakeLocator()
        class FakeContext:
            def new_page(self): return FakePage()
        with (patch.object(wrong, '_field_card', return_value=FakeLocator()),
              patch.object(wrong, '_fill_text_field', side_effect=lambda page, fid, value: entered.__setitem__(fid,value)),
              patch.object(wrong, '_read_text_field', side_effect=lambda page, fid: entered[fid]),
              patch.object(wrong, '_select_option', side_effect=lambda page, fid, value: selected.__setitem__(fid,value)),
              patch.object(wrong, '_read_selected_option', side_effect=lambda page, fid: selected[fid])):
            result = wrong.submit_wrong_item_plan(FakeContext(), plan)
        self.assertTrue(result['submitted'])
        self.assertEqual(clicks, ['Submit'])
        self.assertEqual(entered, {
            wrong.FORM_FIELDS['order_id']: 'ORDER123',
            wrong.FORM_FIELDS['sku']: 'MLE00001_2',
            wrong.FORM_FIELDS['received_item']: 'Different USB adapter',
        })
        self.assertEqual(selected[wrong.FORM_FIELDS['status']], 'In-Dispute')

    def test_form_wrong_field_blocks_submission(self):
        plan = wrong.plan_wrong_item_filings('ORDER123', [item()])[0]
        class Page:
            def bring_to_front(self): pass
            def goto(self, *args, **kwargs): pass
        class Context:
            def new_page(self): return Page()
        class Loc:
            def wait_for(self, **kwargs): pass
        with (patch.object(wrong, '_field_card', return_value=Loc()),
              patch.object(wrong, '_fill_text_field'),
              patch.object(wrong, '_read_text_field', return_value='WRONG'),
              patch.object(wrong, '_select_option')):
            with self.assertRaisesRegex(RuntimeError, 'was not verified'):
                wrong.submit_wrong_item_plan(Context(), plan)

    def test_normal_lark_records_are_skipped_after_successful_checkpoint(self):
        # A physically Not Returned normal item needs no Odoo transfer.
        normal = {**item('MLE00003', 1, 'Missing Item'), 'status':'Not Returned',
                  'odoo_tag':'', 'received_item':'', 'wrong_item_status':''}
        class Page:
            def bring_to_front(self): pass
            def is_closed(self): return False
            def close(self): pass
        saved = []
        def fake_submit(page, record, order_id, callback):
            saved.append(record['sku'])
            return {'sku':record['sku'], 'submitted':True, 'quantity':1,
                    'decision':'Refunded', 'value':10, 'transfer_id':'',
                    'status':'Not Returned'}
        with (patch.object(lark, 'get_or_open_lark_page', return_value=Page()),
              patch.object(lark, '_submit_record', side_effect=fake_submit)):
            first_results=[]
            first = lark.file_lark_returns(object(), order_id='ORDER123',
                returned_products=[normal], return_case={'refund_value':10},
                case_decision={'confirmed':True}, odoo_results=None,
                on_record_complete=lambda r:first_results.append(r))
            self.assertEqual(len(first_results),1)
            second = lark.file_lark_returns(object(), order_id='ORDER123',
                returned_products=[normal], return_case={'refund_value':10},
                case_decision={'confirmed':True}, odoo_results=None,
                existing_results=first)
        self.assertEqual(len(saved),1)
        self.assertEqual(first,second)


if __name__ == '__main__': unittest.main()

class MixedWorkflowTests(unittest.TestCase):
    def _app(self, store):
        from types import MethodType
        normal = {**item('MLE09901', 1, 'Defective'),
                  'status':'Not Returned', 'odoo_tag':'Damaged / Defective Item',
                  'received_item':'', 'wrong_item_status':''}
        special = item('MLE09902',1,'Scam','Small screw instead of product','Dispute Approved')
        items=[normal,special]
        scan_id=store.start_scan(platform='Shopee', search_by='Order ID',
            search_input='ORDER123', order_id='ORDER123',
            return_case={'order_id':'ORDER123','refund_value':300}, items=items)
        a=SimpleNamespace(
            current_order_id='ORDER123', current_platform='Shopee',
            current_search_mode='Order ID', current_scan_id=scan_id,
            return_case={'order_id':'ORDER123','refund_value':300},
            returned_products=items, case_decision={'confirmed':True},
            new_stock_destination='MNL/Stock', odoo_results=None,
            odoo_checkpoint=None, lark_results=[],
            normal_lark_results=[], wrong_item_lark_results=[],
            order_url_entry=SimpleNamespace(get=lambda:'ORDER123'),
            transfer_id_label=FakeWidget('No Odoo transfer'),
            status_label=FakeWidget(''), odoo_result_label=FakeWidget(''),
            browser=SimpleNamespace(context=object()),
            workflow_store=store,
            set_status=lambda text:None,
            _refresh_restore_button=lambda **kw:None,
        )
        for name in ('_workflow_snapshot','_persist_workflow','_persist_lark_progress_strict',
                     '_check_other_lark_filing', '_run_lark_submit_step'):
            setattr(a,name,MethodType(getattr(main.ReturnProcessorApp,name),a))
        return a

    def test_mixed_normal_and_wrong_item_saves_independent_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkflowStore(Path(tmp))
            a=self._app(store)
            calls=[]
            def normal_mock(**kwargs):
                calls.append('normal')
                result={'sku':'MLE09901','route_key':'normal:A','submitted':True,
                        'status':'Not Returned','transfer_id':''}
                kwargs['on_record_complete'](result)
                return [result]
            def special_mock(context,plan,progress_callback=None):
                calls.append('wrong')
                return {'sku':plan['sku'],'route_key':plan['route_key'],
                        'status':plan['status'],'submitted':True,
                        'filing_type':'wrong_item_scam','quantity':1,'transfer_id':''}
            with (patch.object(main,'file_lark_returns',side_effect=normal_mock),
                  patch.object(main,'submit_wrong_item_plan',side_effect=special_mock)):
                a._run_lark_submit_step()
            self.assertEqual(calls,['normal','wrong'])
            self.assertEqual(len(a.lark_results),2)
            self.assertEqual(store.get_scan(a.current_scan_id)['workflow_state'],'completed')
            self.assertIsNone(store.get_restore_point(a.current_scan_id))

    def test_partial_success_persists_so_later_route_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=WorkflowStore(Path(tmp))
            a=self._app(store)
            counts={'normal':0,'wrong':0}
            def normal_mock(**kwargs):
                if kwargs['existing_results']:
                    return kwargs['existing_results']
                counts['normal']+=1
                result={'sku':'MLE09901','route_key':'normal:A','submitted':True,
                        'status':'Not Returned','transfer_id':''}
                kwargs['on_record_complete'](result)
                return [result]
            def special_mock(context,plan,progress_callback=None):
                counts['wrong']+=1
                if counts['wrong']==1:
                    raise RuntimeError('Lark returned uncertain error')
                return {'sku':plan['sku'],'route_key':plan['route_key'],
                        'submitted':True,'status':plan['status'],
                        'filing_type':'wrong_item_scam','quantity':1,'transfer_id':''}
            with (patch.object(main,'file_lark_returns',side_effect=normal_mock),
                  patch.object(main,'submit_wrong_item_plan',side_effect=special_mock)):
                with self.assertRaisesRegex(RuntimeError, 'uncertain error'):
                    a._run_lark_submit_step()
                pending=store.get_restore_point(a.current_scan_id)
                self.assertEqual(pending['workflow_state'],'lark_pending')
                self.assertEqual(len(pending['normal_lark_results']),1)
                a._run_lark_submit_step()
            self.assertEqual(counts,{'normal':1,'wrong':2})
            self.assertEqual(len(store.get_scan(a.current_scan_id)['lark_results']),2)
