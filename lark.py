from urllib.parse import quote, urlencode

LARK_FORM_BASE_URL = (
    "https://kjx72am2njb.sg.larksuite.com/share/base/form/"
    "shrlgCvlgAlYpqw3TAThRikY3ig"
)

DEFAULT_TIMEOUT = 30_000
SLOW_TIMEOUT = 60_000
RETURNED_STATUS = "Returned"


def _text(value) -> str:
    return str(value or "").strip()


def _progress(callback, message: str):
    if callback:
        callback(message)
    print(message)


def _normalize_grade(grade: str) -> str:
    grade = _text(grade)
    if not grade:
        return ""
    return grade if grade.lower().startswith("grade ") else f"Grade {grade}"


def build_prefilled_lark_url(
    *,
    order_id: str,
    sku: str,
    quantity: int,
    value: float,
    classification: str,
    status: str,
    decision: str,
    platform: str,
    transfer_id: str,
    transfer_link: str,
    remarks: str = "",
    grade: str = "",
) -> str:
    """Build the Lark Item Returns prefill URL."""
    params = {
        "prefill_Order ID": order_id,
        "prefill_SKU": sku,
        "prefill_QTY": str(quantity),
        "prefill_Value": str(value),
        "prefill_Classification": classification,
        "prefill_Status": status,
        "prefill_Decision": decision,
        "prefill_Platform": platform,
    }

    # Not Returned items intentionally omit both fields so Lark leaves them blank.
    if transfer_id:
        params["prefill_Transfer ID"] = transfer_id
    if transfer_link:
        params["prefill_Transfer Link"] = transfer_link
    if remarks:
        params["prefill_Remarks"] = remarks

    if classification == "Unsealed":
        normalized = _normalize_grade(grade)
        if not normalized:
            raise ValueError("Grade is required for an Unsealed Lark return.")
        params["prefill_Grade"] = normalized

    return (
        f"{LARK_FORM_BASE_URL}?"
        + urlencode(params, quote_via=quote, safe="")
    )


def get_or_open_lark_page(context):
    for page in context.pages:
        if not page.is_closed() and "shrlgCvlgAlYpqw3TAThRikY3ig" in page.url:
            return page
    return context.new_page()


def _verify_prefilled_form(page, classification: str):
    page.locator(
        '#field-item-fldGfpOgy3 [contenteditable="true"]'
    ).first.wait_for(state="visible", timeout=SLOW_TIMEOUT)

    page.locator("#number-editor-input-fldp1RHjbO").wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )
    page.locator("#number-editor-input-fld7ICAkSy").wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    if classification == "Unsealed":
        page.locator("#field-item-fld6aPiebx").wait_for(
            state="visible",
            timeout=SLOW_TIMEOUT,
        )


def file_lark_return(
    page,
    *,
    order_id: str,
    sku: str,
    quantity: int,
    value: float,
    classification: str,
    status: str,
    decision: str,
    platform: str,
    transfer_id: str,
    transfer_link: str,
    remarks: str = "",
    grade: str = "",
    progress_callback=None,
) -> dict:
    """Open, verify, and submit one prefilled Lark return form."""
    prefilled_url = build_prefilled_lark_url(
        order_id=order_id,
        sku=sku,
        quantity=quantity,
        value=value,
        classification=classification,
        status=status,
        decision=decision,
        platform=platform,
        transfer_id=transfer_id,
        transfer_link=transfer_link,
        remarks=remarks,
        grade=grade,
    )

    _progress(progress_callback, f"Opening prefilled Lark form for {sku}...")
    page.goto(
        prefilled_url,
        wait_until="domcontentloaded",
        timeout=SLOW_TIMEOUT,
    )

    _verify_prefilled_form(page, classification)

    button = page.get_by_role("button", name="File Return", exact=True)
    button.wait_for(state="visible", timeout=SLOW_TIMEOUT)

    _progress(progress_callback, f"Submitting Lark return for {sku}...")
    button.click()

    page.get_by_text("Submitted", exact=True).first.wait_for(
        state="visible",
        timeout=SLOW_TIMEOUT,
    )
    _progress(
        progress_callback,
        f"Lark return submitted successfully for {sku}.",
    )

    return {
        "order_id": order_id,
        "sku": sku,
        "quantity": quantity,
        "value": value,
        "classification": classification,
        "status": status,
        "decision": decision,
        "platform": platform,
        "transfer_id": transfer_id,
        "transfer_link": transfer_link,
        "remarks": remarks,
        "grade": (
            _normalize_grade(grade)
            if classification == "Unsealed"
            else ""
        ),
        "prefilled_url": prefilled_url,
        "submitted": True,
    }


def _refund_value(return_case: dict | None) -> float:
    if not return_case:
        raise ValueError("Shopee return/refund data is required for Lark filing.")
    try:
        value = float(return_case["refund_value"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "Shopee refunded/order value is missing or invalid."
        ) from error
    if value < 0:
        raise ValueError("Shopee refunded/order value cannot be negative.")
    return value


def _build_returned_item_pool(items: list[dict]) -> list[dict]:
    pool = []
    for item in items:
        sku = _text(item.get("sku"))
        if not sku:
            raise ValueError("A returned product has a blank SKU.")
        try:
            quantity = int(item.get("quantity", 0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid QTY for {sku}.") from error
        if quantity <= 0:
            raise ValueError(f"QTY for {sku} must be at least 1.")
        pool.append({"item": item, "remaining": quantity})
    return pool


def _matches_transfer(item: dict, transfer: dict, sku: str) -> bool:
    checks = (
        ("sku", sku),
        ("decision", _text(transfer.get("decision"))),
        ("classification", _text(transfer.get("classification"))),
        ("status", _text(transfer.get("status"))),
    )
    return all(
        not expected or _text(item.get(field)) == expected
        for field, expected in checks
    )


def _take_items_for_transfer(
    transfer: dict,
    pool: list[dict],
) -> list[dict]:
    """Quantity-aware matching that safely supports duplicate SKU rows."""
    matched = []

    for transfer_item in transfer.get("items", []):
        sku = _text(transfer_item.get("sku"))
        try:
            needed = int(transfer_item.get("quantity", 0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid Odoo transfer QTY for {sku}.") from error

        if not sku or needed <= 0:
            raise ValueError("Odoo transfer contains an invalid SKU/QTY row.")

        for entry in pool:
            if needed <= 0:
                break
            if entry["remaining"] <= 0:
                continue

            item = entry["item"]
            if not _matches_transfer(item, transfer, sku):
                continue

            allocated = min(entry["remaining"], needed)
            allocated_item = dict(item)
            allocated_item["quantity"] = allocated
            matched.append(allocated_item)

            entry["remaining"] -= allocated
            needed -= allocated

        if needed:
            raise ValueError(
                f"Could not match {needed} remaining unit(s) of {sku} "
                f"to Odoo Transfer {_text(transfer.get('transfer_id'))}. "
                f"Expected handling: {_text(transfer.get('classification'))} / "
                f"{_text(transfer.get('decision'))} / "
                f"{_text(transfer.get('status'))}."
            )

    if not matched:
        raise ValueError(
            f"Odoo Transfer {_text(transfer.get('transfer_id'))} "
            "contains no returned items."
        )
    return matched


def _shared_value(
    items: list[dict],
    field: str,
    label: str,
    *,
    default: str = "",
) -> str:
    values = list(dict.fromkeys(
        _text(item.get(field, default))
        for item in items
    ))
    if len(values) > 1:
        raise ValueError(
            f"Odoo Transfer contains different {label} values: "
            + ", ".join(values)
        )
    return values[0] if values else default


def _combine_transfer_remarks(items: list[dict]) -> str:
    parts = []
    for item in items:
        details = []
        grade = _text(item.get("grade"))
        remarks = _text(item.get("remarks"))
        if grade:
            details.append(_normalize_grade(grade))
        if remarks:
            details.append(remarks)
        if details:
            parts.append(f"{_text(item.get('sku'))}: " + " | ".join(details))
    return " ; ".join(parts)


def _transfer_record(
    transfer: dict,
    pool: list[dict],
    refund_value: float,
    index: int,
) -> dict:
    transfer_id = _text(transfer.get("transfer_id"))
    transfer_url = _text(transfer.get("transfer_url"))
    if not transfer_id or not transfer_url:
        raise ValueError(
            f"Odoo Transfer #{index} is missing its Transfer ID or Transfer Link."
        )

    items = _take_items_for_transfer(transfer, pool)
    decision = _text(transfer.get("decision")) or _shared_value(
        items, "decision", "Decision"
    )
    classification = _text(transfer.get("classification")) or _shared_value(
        items, "classification", "Classification"
    )
    status = _text(transfer.get("status")) or _shared_value(
        items, "status", "Status"
    )
    platform = _shared_value(
        items, "platform", "Platform", default="Shopee"
    ) or "Shopee"

    grade = ""
    if classification == "Unsealed":
        grade = _shared_value(items, "grade", "Grade")
        if not grade:
            raise ValueError(
                f"Grade is required for Unsealed Transfer {transfer_id}."
            )

    return {
        "order_id": None,  # injected by caller
        "sku": ", ".join(
            f"{_text(item.get('sku'))}_{int(item['quantity'])}"
            for item in items
        ),
        "quantity": sum(int(item["quantity"]) for item in items),
        "value": refund_value,
        "classification": classification,
        "status": status,
        "decision": decision,
        "platform": platform,
        "transfer_id": transfer_id,
        "transfer_link": transfer_url,
        "remarks": _combine_transfer_remarks(items),
        "grade": grade,
        "_meta": {
            "filing_type": "odoo_transfer",
            "transfer_index": index,
            "items": [
                {
                    "sku": _text(item.get("sku")),
                    "quantity": int(item["quantity"]),
                }
                for item in items
            ],
        },
    }


def _direct_record(item: dict, refund_value: float) -> dict:
    sku = _text(item.get("sku"))
    quantity = int(item.get("quantity", 0))
    return {
        "order_id": None,  # injected by caller
        "sku": sku,
        "quantity": quantity,
        "value": refund_value,
        "classification": _text(item.get("classification")),
        "status": _text(item.get("status")),
        "decision": _text(item.get("decision")),
        "platform": _text(item.get("platform")) or "Shopee",
        "transfer_id": "",
        "transfer_link": "",
        "remarks": _text(item.get("remarks")),
        "grade": _text(item.get("grade")),
        "_meta": {
            "filing_type": "not_returned_direct",
            "items": [{"sku": sku, "quantity": quantity}],
        },
    }


def _submit_record(
    page,
    record: dict,
    order_id: str,
    progress_callback,
) -> dict:
    record = dict(record)
    meta = record.pop("_meta")
    record["order_id"] = order_id

    result = file_lark_return(
        page=page,
        progress_callback=progress_callback,
        **record,
    )
    result.update(meta)
    result["item_count"] = len(meta["items"])
    result["value_source"] = "Shopee refunded/order value"
    return result


def file_lark_returns(
    context,
    *,
    order_id: str,
    returned_products: list[dict],
    return_case: dict | None,
    case_decision: dict | None,
    odoo_results: dict | None,
    progress_callback=None,
) -> list[dict]:
    """
    Returned items -> one Lark filing per Odoo Transfer ID.
    Not Returned items -> direct Lark filing with blank Transfer ID/Link.
    """
    if not order_id:
        raise ValueError("Order ID is required for Lark filing.")
    if not returned_products:
        raise ValueError("No returned products are available for Lark filing.")

    refund = _refund_value(return_case)
    physically_returned = [
        item for item in returned_products
        if _text(item.get("status")) == RETURNED_STATUS
    ]
    not_returned = [
        item for item in returned_products
        if _text(item.get("status")) != RETURNED_STATUS
    ]

    if physically_returned and not odoo_results:
        raise ValueError(
            "Odoo processing is required for item(s) with Status = Returned."
        )

    transfers = odoo_results.get("returns", []) if odoo_results else []
    pool = _build_returned_item_pool(physically_returned)

    page = get_or_open_lark_page(context)
    page.bring_to_front()
    results = []

    for index, transfer in enumerate(transfers, start=1):
        record = _transfer_record(transfer, pool, refund, index)
        _progress(
            progress_callback,
            f"Filing Lark Transfer {index}/{len(transfers)}: "
            f"{record['transfer_id']} | {record['sku']}",
        )
        results.append(
            _submit_record(page, record, order_id, progress_callback)
        )

    for index, item in enumerate(not_returned, start=1):
        record = _direct_record(item, refund)
        _progress(
            progress_callback,
            f"Filing direct Lark item {index}/{len(not_returned)}: "
            f"{record['sku']} | {record['status']}",
        )
        results.append(
            _submit_record(page, record, order_id, progress_callback)
        )

    if not results:
        raise ValueError("No Lark filing records were generated.")
    return results


__all__ = [
    "build_prefilled_lark_url",
    "get_or_open_lark_page",
    "file_lark_return",
    "file_lark_returns",
]
