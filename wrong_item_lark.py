"""Wrong Item / Scam Lark Base filing. No Odoo navigation or stock actions.

Form fields verified from the Nov 18, 2026 supplied Lark form HTML.
Each wrong-item item is one separate form submission to preserve per-item status.
"""
import hashlib
import json
from urllib.parse import urlencode, quote

from lark import (
    _clean_editor_text, _field_card, _fill_text_field, _read_text_field,
    _read_selected_option, _select_option, _visible_form_errors,
    SLOW_TIMEOUT,
)

FORM_URL = (
    'https://kjx72am2njb.sg.larksuite.com/share/base/form/'
    'shrlgqkLCe66MOX6wjiz9QbGaqb'
)
FORM_FIELDS = {
    'order_id': 'fldF74VqNi',
    'sku': 'fldzpfI9B4',
    'received_item': 'fldQGBqpuv',
    'status': 'fld6Fri64S',
}
WRONG_ITEM_CLASSIFICATIONS = frozenset({'Wrong Item', 'Scam'})
WRONG_ITEM_STATUSES = (
    'Refunded (Seller Fault)',
    'Dispute Approved',
    'Dispute Rejected',
    'In-Dispute',
)


def is_wrong_item(item):
    return str(item.get('classification') or '').strip() in WRONG_ITEM_CLASSIFICATIONS


def default_wrong_item_status(decision):
    return 'Refunded (Seller Fault)' if str(decision).strip() == 'Refunded' else 'In-Dispute'


def _name(value):
    return str(value or '').strip()


def validate_wrong_item_item(order_id, item):
    if not _name(order_id):
        raise ValueError('Order ID is required for Wrong Item / Scam filing.')
    if not is_wrong_item(item):
        raise ValueError('Item must be classified Wrong Item or Scam.')
    sku = _name(item.get('sku')).upper()
    if not sku:
        raise ValueError('Supposed-item SKU is required.')
    qty = item.get('quantity')
    try:
        q = int(qty)
    except (TypeError, ValueError) as error:
        raise ValueError(f'Invalid quantity for {sku}.') from error
    if q <= 0 or str(qty).strip() not in {str(q), str(float(q))}:
        raise ValueError(f'Quantity for {sku} must be a positive whole number.')
    received = _name(item.get('received_item'))
    if not received:
        raise ValueError(f'Enter the actual Received Item for {sku}.')
    status = _name(item.get('wrong_item_status'))
    if status not in WRONG_ITEM_STATUSES:
        raise ValueError(f'Choose the Wrong Item / Scam Status for {sku}.')
    return {'order_id': _name(order_id), 'sku': f'{sku}_{q}',
            'source_sku': sku, 'quantity': q, 'received_item': received,
            'status': status, 'classification': _name(item.get('classification'))}


def make_route_key(order_id, item, index):
    clean = validate_wrong_item_item(order_id, item)
    payload = {'index': int(index), **clean}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return 'wrong:' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def plan_wrong_item_filings(order_id, items):
    plans = []
    for ix, item in enumerate(items):
        if is_wrong_item(item):
            data = validate_wrong_item_item(order_id, item)
            data['route_key'] = make_route_key(order_id, item, ix)
            plans.append(data)
    return plans


def form_prefill_url(plan):
    params = {
        'prefill_Order ID': plan['order_id'],
        'prefill_SKU': plan['sku'],
        'prefill_Received Item': plan['received_item'],
        'prefill_Status': plan['status'],
    }
    return FORM_URL + '?' + urlencode(params, quote_via=quote, safe='')


def submit_wrong_item_plan(context, plan, progress_callback=None):
    """Submit one plan; caller must save checkpoint before and after this call.

    On uncertain Submit result the browser tab stays open for manual review.
    """
    def notify(message):
        if progress_callback:
            progress_callback(message)

    page = context.new_page()
    page.bring_to_front()
    url = form_prefill_url(plan)
    notify(f"Opening Wrong Item / Scam Base for {plan['sku']}...")
    page.goto(url, wait_until='domcontentloaded', timeout=SLOW_TIMEOUT)
    _field_card(page, FORM_FIELDS['order_id']).wait_for(
        state='visible', timeout=SLOW_TIMEOUT
    )
    for key in ('order_id', 'sku', 'received_item'):
        _fill_text_field(page, FORM_FIELDS[key], plan[key])
    _select_option(page, FORM_FIELDS['status'], plan['status'])
    for key in ('order_id', 'sku', 'received_item'):
        actual = _read_text_field(page, FORM_FIELDS[key])
        if actual != plan[key]:
            raise RuntimeError(f'Wrong Item Lark {key} was not verified: {actual!r}.')
    actual_status = _read_selected_option(page, FORM_FIELDS['status'])
    if actual_status != plan['status']:
        raise RuntimeError(f'Wrong Item Lark Status mismatch: {actual_status!r}.')
    button = page.get_by_role('button', name='Submit', exact=True)
    button.wait_for(state='visible', timeout=SLOW_TIMEOUT)
    notify(f"Submitting Wrong Item / Scam record for {plan['sku']}...")
    button.click()
    try:
        page.get_by_text('Submitted', exact=True).first.wait_for(
            state='visible', timeout=SLOW_TIMEOUT
        )
    except Exception as error:
        details = _visible_form_errors(page)
        raise RuntimeError(
            'Wrong Item / Scam form submission was not visibly confirmed. '
            'Inspect the Lark Base before retrying to avoid duplicate entries.'
            + (' Form message: ' + details if details else '')
        ) from error
    notify(f"Wrong Item / Scam filed: {plan['sku']}")
    return {
        'route_key': plan['route_key'],
        'filing_type': 'wrong_item_scam',
        'lark_base': 'Wrong Item / Scam',
        'order_id': plan['order_id'],
        'sku': plan['sku'],
        'quantity': plan['quantity'],
        'received_item': plan['received_item'],
        'classification': plan['classification'],
        'status': plan['status'],
        'decision': plan['status'],
        'transfer_id': '',
        'transfer_link': '',
        'value': None,  # new form has no refund/value field
        'prefilled_url': url,
        'submitted': True,
    }
