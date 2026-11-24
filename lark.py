import hashlib
import json
import math
import re
from datetime import datetime, timezone
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
    """Create a fresh tab, as Lark prefills are unreliable on reused form tabs.

    The tab stays inside the existing persistent Chrome profile, so Lark
    sign-in remains available. A failed form is left open for inspection.
    """
    return context.new_page()


FIELD_IDS = {
    "order_id": "fldGfpOgy3",
    "sku": "fldZmVCLSz",
    "quantity": "fldp1RHjbO",
    "value": "fld7ICAkSy",
    "classification": "fldc6INoIL",
    "status": "flduWjJhXm",
    "decision": "fldsuY8UMD",
    "platform": "flde3CocnE",
    "transfer_id": "fldLxm5LZH",
    "transfer_link": "fldKACH12T",
    "remarks": "fldxl8I6rt",
    "grade": "fld6aPiebx",
}


def _field_card(page, field_id: str):
    return page.locator(f"#field-item-{field_id}")


def _clean_editor_text(value: str) -> str:
    return _text(value).replace("\u200b", "").strip()


def _wait_for_form_ready(page):
    try:
        _field_card(page, FIELD_IDS["order_id"]).wait_for(
            state="visible",
            timeout=SLOW_TIMEOUT,
        )
    except Exception as error:
        live_url = page.url
        body_text = ""
        try:
            body_text = page.locator("body").inner_text(timeout=2_000)
        except Exception:
            pass
        if "login" in live_url.lower() or "sign in" in body_text.lower():
            raise RuntimeError(
                "Lark is asking for login. Sign in to Lark in the processor "
                "Chrome window, then use Retry Lark Only."
            ) from error
        raise RuntimeError(
            "The Lark Item Returns form did not become ready."
        ) from error


def _text_editor(page, field_id: str):
    editor = _field_card(page, field_id).locator(
        '[contenteditable="true"]'
    ).first
    editor.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    return editor


def _fill_text_field(page, field_id: str, value: str):
    editor = _text_editor(page, field_id)
    wanted = _text(value)
    if _clean_editor_text(editor.inner_text()) != wanted:
        editor.fill(wanted)


def _fill_number_field(page, field_id: str, value):
    input_box = _field_card(page, field_id).locator("input").first
    input_box.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    current = _clean_editor_text(input_box.input_value()).replace(",", "")
    try:
        already_correct = float(current) == float(value)
    except (TypeError, ValueError):
        already_correct = False
    if not already_correct:
        input_box.fill(str(value))


def _selected_option_values(card) -> list[str]:
    """Read existing selections without clicking or toggling any option."""
    return [
        _clean_editor_text(value)
        for value in card.locator(
            ".base-component-select-list-editor-option-checked "
            ".base-component-select-list-editor-text"
        ).all_text_contents()
        if _clean_editor_text(value)
    ]


def _select_option(page, field_id: str, option_text: str):
    """Idempotent single-select: never click an already selected option.

    Some Lark radio-style selectors toggle OFF when clicked a second time.
    Exact matching also prevents 'Returned' matching 'Not Returned'.
    """
    option_text = _text(option_text)
    if not option_text:
        raise ValueError(f"A required Lark option for {field_id} is blank.")

    card = _field_card(page, field_id)
    card.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    if _selected_option_values(card) == [option_text]:
        return

    exact_label = re.compile(rf"^\s*{re.escape(option_text)}\s*$")
    option = card.locator(
        ".base-component-select-list-editor-option"
    ).filter(has_text=exact_label).first
    option.wait_for(state="visible", timeout=SLOW_TIMEOUT)

    # The async prefill can finish while locating the option. Check again.
    if _selected_option_values(card) == [option_text]:
        return
    option.click()

    selected = card.locator(
        ".base-component-select-list-editor-option-checked "
        ".base-component-select-list-editor-text"
    ).filter(has_text=exact_label).first
    try:
        selected.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    except Exception as error:
        actual = _selected_option_values(card)
        raise RuntimeError(
            f"Lark could not select {option_text!r} for {field_id}. "
            f"Selected value(s): {actual!r}."
        ) from error
    if _selected_option_values(card) != [option_text]:
        raise RuntimeError(
            f"Lark {field_id} selection was not stable: "
            f"{_selected_option_values(card)!r}."
        )


def _read_text_field(page, field_id: str) -> str:
    return _clean_editor_text(_text_editor(page, field_id).inner_text())


def _read_number_field(page, field_id: str) -> str:
    input_box = _field_card(page, field_id).locator("input").first
    input_box.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return _clean_editor_text(input_box.input_value())


def _read_selected_option(page, field_id: str) -> str:
    selected = _field_card(page, field_id).locator(
        ".base-component-select-list-editor-option-checked "
        ".base-component-select-list-editor-text"
    ).first
    selected.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    return _clean_editor_text(selected.inner_text())


def _verify_form_values(page, expected: dict):
    text_checks = {
        "Order ID": (FIELD_IDS["order_id"], expected["order_id"]),
        "SKU": (FIELD_IDS["sku"], expected["sku"]),
        "Transfer ID": (FIELD_IDS["transfer_id"], expected["transfer_id"]),
        "Transfer Link": (FIELD_IDS["transfer_link"], expected["transfer_link"]),
        "Remarks": (FIELD_IDS["remarks"], expected["remarks"]),
    }
    for label, (field_id, wanted) in text_checks.items():
        actual = _read_text_field(page, field_id)
        if actual != _text(wanted):
            raise RuntimeError(
                f"Lark {label} verification failed. "
                f"Expected {_text(wanted)!r}, got {actual!r}."
            )

    qty_actual = _read_number_field(page, FIELD_IDS["quantity"])
    try:
        qty_ok = int(float(qty_actual.replace(",", ""))) == int(expected["quantity"])
    except (TypeError, ValueError):
        qty_ok = False
    if not qty_ok:
        raise RuntimeError(
            "Lark QTY verification failed. "
            f"Expected {int(expected['quantity'])}, got {qty_actual!r}."
        )

    value_actual = _read_number_field(page, FIELD_IDS["value"])
    try:
        actual_value = float(value_actual.replace(",", ""))
        expected_value = float(expected["value"])
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"Lark Value verification failed: {value_actual!r}."
        ) from error
    if abs(actual_value - expected_value) > 0.005:
        raise RuntimeError(
            "Lark Value verification failed. "
            f"Expected {expected_value:.2f}, got {actual_value:.2f}."
        )

    select_checks = {
        "Classification": (FIELD_IDS["classification"], expected["classification"]),
        "Status": (FIELD_IDS["status"], expected["status"]),
        "Decision": (FIELD_IDS["decision"], expected["decision"]),
        "Platform": (FIELD_IDS["platform"], expected["platform"]),
    }
    for label, (field_id, wanted) in select_checks.items():
        actual = _read_selected_option(page, field_id)
        if actual != _text(wanted):
            raise RuntimeError(
                f"Lark {label} verification failed. "
                f"Expected {_text(wanted)!r}, got {actual!r}."
            )

    if expected["classification"] == "Unsealed":
        wanted_grade = _normalize_grade(expected["grade"])
        actual_grade = _read_selected_option(page, FIELD_IDS["grade"])
        if actual_grade != wanted_grade:
            raise RuntimeError(
                "Lark Grade verification failed. "
                f"Expected {wanted_grade!r}, got {actual_grade!r}."
            )


def _fill_lark_form(page, expected: dict):
    """Wait for URL prefill, fill any missing values, and verify everything."""
    _wait_for_form_ready(page)

    # Lark applies prefill asynchronously. A new tab often fills correctly
    # after hydration; acting before that point can toggle values back off.
    # If prefill did not arrive, continue to explicit field filling below.
    try:
        page.wait_for_function(
            """expected => {
                const editor = document.querySelector(
                    '#field-item-fldGfpOgy3 [contenteditable="true"]'
                );
                const order_id = (editor?.textContent || '')
                    .replace(/\u200b/g, '').trim();
                const fieldIds = {
                    classification: 'fldc6INoIL',
                    status: 'flduWjJhXm',
                    decision: 'fldsuY8UMD',
                    platform: 'flde3CocnE',
                };
                return order_id === expected.order_id &&
                    Object.entries(fieldIds).every(([name, id]) => {
                        const selected = document.querySelector(
                            '#field-item-' + id + ' ' +
                            '.base-component-select-list-editor-option-checked ' +
                            '.base-component-select-list-editor-text'
                        );
                        return (selected?.textContent || '').trim() === expected[name];
                    });
            }""",
            arg={name: _text(expected[name]) for name in (
                "order_id", "classification", "status", "decision", "platform"
            )},
            timeout=6_000,
        )
    except Exception:
        # An incomplete prefill is not fatal: set only the missing fields.
        print("LARK PREFILL: Incomplete after waiting; correcting form fields.")

    # Select choices first because Classification can change conditional
    # visibility (Grade) and may rerender part of the form.
    _select_option(page, FIELD_IDS["classification"], expected["classification"])
    _select_option(page, FIELD_IDS["status"], expected["status"])
    _select_option(page, FIELD_IDS["decision"], expected["decision"])
    _select_option(page, FIELD_IDS["platform"], expected["platform"])

    if expected["classification"] == "Unsealed":
        _field_card(page, FIELD_IDS["grade"]).wait_for(
            state="visible", timeout=SLOW_TIMEOUT
        )
        _select_option(
            page, FIELD_IDS["grade"], _normalize_grade(expected["grade"])
        )

    # Fill text/number values after select-driven rerenders are complete.
    _fill_text_field(page, FIELD_IDS["order_id"], expected["order_id"])
    _fill_text_field(page, FIELD_IDS["sku"], expected["sku"])
    _fill_number_field(page, FIELD_IDS["quantity"], int(expected["quantity"]))
    _fill_number_field(page, FIELD_IDS["value"], float(expected["value"]))
    _fill_text_field(page, FIELD_IDS["transfer_id"], expected["transfer_id"])
    _fill_text_field(page, FIELD_IDS["transfer_link"], expected["transfer_link"])
    _fill_text_field(page, FIELD_IDS["remarks"], expected["remarks"])

    _verify_form_values(page, expected)


def _visible_form_errors(page) -> str:
    messages = []
    for selector in ('[class*="error"]', '[class*="invalid"]', '[role="alert"]'):
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 20)):
                node = locator.nth(index)
                if not node.is_visible():
                    continue
                value = _clean_editor_text(node.inner_text(timeout=500))
                if value and value not in messages:
                    messages.append(value)
        except Exception:
            continue
    return " | ".join(messages[:8])


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

    expected = {
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
        "grade": grade,
    }
    _progress(progress_callback, f"Filling and verifying Lark form for {sku}...")
    _fill_lark_form(page, expected)

    button = page.get_by_role("button", name="File Return", exact=True)
    button.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    button.scroll_into_view_if_needed()

    _progress(progress_callback, f"Submitting Lark return for {sku}...")
    button.click()

    submitted = page.get_by_text("Submitted", exact=True).first
    try:
        submitted.wait_for(state="visible", timeout=SLOW_TIMEOUT)
    except Exception as error:
        details = _visible_form_errors(page)
        suffix = f" Visible form message(s): {details}" if details else ""
        raise RuntimeError(
            "Lark did not confirm the submission with the 'Submitted' page."
            + suffix
        ) from error

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
        raise ValueError("Return/refund data is required for Lark filing.")
    try:
        value = float(return_case["refund_value"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Return/refund value is missing or invalid.") from error
    if value < 0:
        raise ValueError("Return/refund value cannot be negative.")
    return value


def _value_source(return_case: dict | None) -> str:
    if not return_case:
        return "Return/refund value"
    if (return_case.get("tiktok_manual_selection") or {}).get("mode") == "operator_curated":
        return "Operator-confirmed selected TikTok item refunds"
    return _text(return_case.get("value_source")) or "Return/refund value"


def _tiktok_selection_rows(items: list[dict]) -> list[dict]:
    """Canonical selected source rows; changing any Lark-critical field voids approval."""
    rows = []
    for item in items:
        src = item.get("source_data") or {}
        if not isinstance(src, dict):
            src = {}
        rows.append({
            "return_order_id": _text(src.get("return_order_id")),
            "sku": _text(item.get("sku")).upper(),
            "quantity": item.get("quantity"),
            "amount": item.get("amount"),
            "classification": _text(item.get("classification")),
            "decision": _text(item.get("decision")),
            "status": _text(item.get("status")),
            "grade": _text(item.get("grade")),
            "odoo_tag": _text(item.get("odoo_tag")),
        })
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, default=str))


def _tiktok_selection_fingerprint(items: list[dict]) -> str:
    encoded = json.dumps(_tiktok_selection_rows(items), sort_keys=True,
                         separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tiktok_source_fingerprint(case: dict) -> str:
    encoded = json.dumps({
        "order_id": _text(case.get("order_id")),
        "return_group_totals": case.get("return_group_totals"),
        "return_group_quantities": case.get("return_group_quantities"),
    }, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def preview_tiktok_manual_selection(return_case: dict, items: list[dict]) -> dict:
    """Safely preview an operator-curated *subset* of an original TikTok scan.

    Source return cards stay immutable. Every retained row requires its own
    explicitly assigned total refund amount; no original card's whole amount
    is implicitly copied to a partial set of SKUs. This never touches Odoo.
    """
    case = return_case or {}
    if _text(case.get("value_mode")) != "tiktok_return_groups":
        raise ValueError("Manual TikTok selection applies to multi-return scans only.")
    totals = case.get("return_group_totals") or {}
    quantities = case.get("return_group_quantities") or {}
    if not isinstance(totals, dict) or not isinstance(quantities, dict) or not totals or set(totals) != set(quantities):
        raise ValueError("Original TikTok return-card totals or quantities are unavailable.")
    if not items:
        raise ValueError("At least one item must remain for Lark filing.")
    selected_qty = {}
    selected_amounts = {}
    for item in items:
        source = item.get("source_data") or {}
        rid = _text(source.get("return_order_id") if isinstance(source, dict) else "")
        sku = _text(item.get("sku")).upper()
        if not rid or rid not in totals or rid not in quantities:
            raise ValueError(f"SKU {sku or '?'} has an unknown TikTok Return Order ID; do not bypass reconciliation.")
        if not sku:
            raise ValueError("Every retained TikTok item must have a SKU.")
        try:
            qty = int(item.get("quantity"))
            if qty <= 0 or float(item.get("quantity")) != qty:
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise ValueError(f"SKU {sku} must have a positive, whole-number QTY.") from exc
        raw_amount = item.get("amount")
        if raw_amount is None or str(raw_amount).strip() == "":
            raise ValueError(
                f"SKU {sku} (return {rid}) needs its verified, manually entered "
                "refund Amount before an edited TikTok selection can be filed."
            )
        try:
            amount = float(raw_amount)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"SKU {sku} has an invalid refund Amount.") from exc
        if not math.isfinite(amount) or amount < 0:
            raise ValueError(f"SKU {sku} must have a finite, nonnegative refund Amount.")
        selected_qty[rid] = selected_qty.get(rid, 0) + qty
        selected_amounts[rid] = selected_amounts.get(rid, 0.0) + amount

    for rid, qty in selected_qty.items():
        try:
            source_qty = int(quantities[rid])
            source_amount = float(totals[rid])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Original TikTok values are invalid for {rid}.") from exc
        if source_qty <= 0 or not math.isfinite(source_amount) or source_amount < 0:
            raise ValueError(f"Original TikTok values are invalid for {rid}.")
        if qty > source_qty:
            raise ValueError(f"Return {rid} has {qty} selected unit(s), above the original {source_qty}.")
        if round(selected_amounts[rid], 2) > round(source_amount, 2) + 0.01:
            raise ValueError(
                f"Return {rid} selected amount PHP {selected_amounts[rid]:,.2f} "
                f"exceeds original TikTok refund PHP {source_amount:,.2f}."
            )

    return {
        "source_return_count": len(totals),
        "selected_return_count": len(selected_qty),
        "source_units": sum(int(q) for q in quantities.values()),
        "selected_units": sum(selected_qty.values()),
        "source_refund": round(sum(float(v) for v in totals.values()), 2),
        "selected_refund": round(sum(selected_amounts.values()), 2),
        "excluded_return_ids": sorted(set(totals) - set(selected_qty)),
        "selected_return_quantities": dict(sorted(selected_qty.items())),
        "selected_return_amounts": {rid: round(val, 2) for rid, val in sorted(selected_amounts.items())},
    }


def confirm_tiktok_manual_selection(return_case: dict, items: list[dict], reason: str) -> dict:
    """Create durable audit evidence of the user's explicitly curated subset."""
    reason = _text(reason)
    if len(reason) < 5:
        raise ValueError("Provide a reason (at least five characters) for the edited selection.")
    summary = preview_tiktok_manual_selection(return_case, items)
    return {
        "mode": "operator_curated",
        "reason": reason,
        "confirmed_at_utc": datetime.now(timezone.utc).isoformat(),
        "order_id": _text((return_case or {}).get("order_id")),
        "source_fingerprint": _tiktok_source_fingerprint(return_case),
        "selection_fingerprint": _tiktok_selection_fingerprint(items),
        **summary,
    }


def _confirmed_tiktok_manual_selection(return_case: dict | None, items: list[dict]) -> bool:
    case = return_case or {}
    approved = case.get("tiktok_manual_selection") or {}
    if not isinstance(approved, dict) or approved.get("mode") != "operator_curated":
        return False
    if _text(approved.get("order_id")) != _text(case.get("order_id")):
        raise ValueError("TikTok selection approval belongs to another Order ID.")
    if approved.get("source_fingerprint") != _tiktok_source_fingerprint(case):
        raise ValueError("TikTok source metadata changed after manual selection approval.")
    if approved.get("selection_fingerprint") != _tiktok_selection_fingerprint(items):
        raise ValueError(
            "TikTok selected items changed after manual approval. "
            "Reconfirm the selection before Lark filing."
        )
    if case.get("tiktok_selection_pending"):
        raise ValueError("TikTok edits have not been reconfirmed for Lark filing.")
    preview_tiktok_manual_selection(case, items)
    return True


def _record_value(return_case: dict | None, items: list[dict]) -> float:
    """
    Shopee keeps the existing order/refund-total behavior.
    Lazada can opt into item-level values by setting value_mode=item_amounts.
    """
    default_value = _refund_value(return_case)
    if _text((return_case or {}).get("value_mode")) == "tiktok_return_groups":
        # Operator-curated items use explicitly entered *row* refund amounts;
        # never apply a full source card's refund to a partial selection.
        if ((return_case or {}).get("tiktok_manual_selection") or {}).get("mode") == "operator_curated":
            subtotal = 0.0
            for item in items:
                raw = item.get("amount")
                try:
                    value = float(raw)
                    quantity = int(item["quantity"])
                    source_qty = int(item.get("_lark_source_quantity") or quantity)
                except (ValueError, TypeError, KeyError) as exc:
                    raise ValueError("Edited TikTok item has invalid amount or quantity.") from exc
                if not math.isfinite(value) or value < 0 or source_qty <= 0 or quantity <= 0 or quantity > source_qty:
                    raise ValueError("Edited TikTok item has invalid amount or quantity.")
                subtotal += value * quantity / source_qty
            return round(subtotal, 2)
        # One marketplace Order ID can have multiple return requests, each
        # with its own refund amount. Never repeat the full order refund for
        # every Odoo transfer/Lark entry, and never divide a refund across
        # individual products without verified source amounts.
        totals = (return_case or {}).get("return_group_totals") or {}
        quantities = (return_case or {}).get("return_group_quantities") or {}
        groups = {}
        for item in items:
            source = item.get("source_data") or {}
            rid = _text(source.get("return_order_id"))
            if not rid or rid not in totals or rid not in quantities:
                raise ValueError(
                    "A TikTok item lacks a verified Return Order ID or return-card "
                    "refund total. Restore the original scan before Lark filing."
                )
            groups.setdefault(rid, []).append(item)

        group_total = 0.0
        for rid, group_items in groups.items():
            actual_qty = sum(int(item.get("quantity") or 0) for item in group_items)
            expected_qty = int(quantities[rid])
            if actual_qty == expected_qty:
                # All units of this return request belong to this one Lark
                # filing, so the return-card's real refund can be used.
                group_total += float(totals[rid])
                continue
            if actual_qty > expected_qty:
                raise ValueError(
                    f"TikTok return {rid} has {actual_qty} selected unit(s), "
                    f"but the return card has only {expected_qty}."
                )
            # Only part of one return request is in this Lark record. Require
            # manually entered SKU amounts, never guess an allocation.
            subtotal = 0.0
            for item in group_items:
                raw = item.get("amount")
                if raw is None or str(raw).strip() == "":
                    raise ValueError(
                        f"TikTok return {rid} is split across multiple Lark "
                        "records. Enter the correct refund Amount for each "
                        "SKU in this return before filing; the card's total "
                        "cannot be attributed to individual SKUs safely."
                    )
                try:
                    value = float(raw)
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        f"Invalid TikTok item Amount for {item.get('sku')}."
                    ) from error
                if value < 0:
                    raise ValueError("TikTok item Amount cannot be negative.")
                source_qty = int(item.get("_lark_source_quantity") or item["quantity"])
                subtotal += value * int(item["quantity"]) / source_qty
            group_total += subtotal
        return round(group_total, 2)

    if _text((return_case or {}).get("value_mode")) != "item_amounts":
        return default_value

    total = 0.0
    for item in items:
        sku = _text(item.get("sku"))
        try:
            amount = float(item.get("amount", 0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid return amount for {sku or 'item'}.") from error
        if amount < 0:
            raise ValueError(f"Return amount for {sku or 'item'} cannot be negative.")
        total += amount
    return round(total, 2)

def verify_tiktok_source_coverage(return_case: dict | None,
                                  items: list[dict]) -> None:
    """Verify *all* TikTok return-card IDs/units before Odoo or Lark.

    A marketplace order can contain several independent return cards. The
    order-level refund must not be assigned to only one of those cards. This
    runs at scan confirmation as well as immediately before Lark filing, so
    partial or legacy saved scans cannot create misleading financial data.
    """
    if _text((return_case or {}).get("value_mode")) != "tiktok_return_groups":
        return
    if _confirmed_tiktok_manual_selection(return_case, items):
        return  # audited, valid subset; Odoo-to-items match checked separately
    if (return_case or {}).get("tiktok_selection_pending"):
        raise ValueError(
            "TikTok items were manually edited. Confirm the selected source "
            "items and their refund amounts before Odoo/Lark filing."
        )
    totals = (return_case or {}).get("return_group_totals") or {}
    quantities = (return_case or {}).get("return_group_quantities") or {}
    if not totals or not quantities or set(totals) != set(quantities):
        raise ValueError(
            "TikTok saved return-card metadata is incomplete. Rescan the order; "
            "if Odoo has already been processed, do not create another ticket."
        )
    actual = {}
    for item in items:
        source = item.get("source_data") or {}
        rid = _text(source.get("return_order_id"))
        if not rid:
            raise ValueError(
                f"TikTok SKU {_text(item.get('sku')) or '?'} has no Return Order ID. "
                "This scan must be reconciled before Lark filing."
            )
        try:
            qty = int(item.get("quantity") or 0)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"TikTok SKU {_text(item.get('sku'))} has invalid QTY.") from exc
        if qty <= 0:
            raise ValueError(f"TikTok SKU {_text(item.get('sku'))} has invalid QTY {qty}.")
        actual[rid] = actual.get(rid, 0) + qty
    expected_ids = set(quantities)
    actual_ids = set(actual)
    missing = sorted(expected_ids - actual_ids)
    extra = sorted(actual_ids - expected_ids)
    quantities_wrong = [
        f"{rid}: saved {actual[rid]}, TikTok {int(quantities[rid])}"
        for rid in sorted(expected_ids & actual_ids)
        if actual[rid] != int(quantities[rid])
    ]
    if missing or extra or quantities_wrong:
        details = []
        if missing:
            details.append("Missing return-card ID(s): " + ", ".join(missing))
        if extra:
            details.append("Unexpected return-card ID(s): " + ", ".join(extra))
        if quantities_wrong:
            details.append("Quantity mismatch: " + "; ".join(quantities_wrong))
        details.append(
            f"Loaded {sum(actual.values())} of "
            f"{sum(int(q) for q in quantities.values())} expected unit(s)."
        )
        raise ValueError(
            "TikTok multi-return scan does not cover all saved return cards. "
            + " | ".join(details)
            + " Correct/reconcile the saved source items before Lark filing. "
            "If Odoo has already completed, do NOT submit to Odoo again."
        )


def _preflight_tiktok_return_groups(
    return_case: dict | None,
    physically_returned: list[dict],
    not_returned: list[dict],
    transfers: list[dict],
) -> None:
    """Verify that TikTok per-return refunds will not be duplicated in Lark.

    Run BEFORE filing any record. If one TikTok return card is split across
    different Odoo transfers (or direct Not Returned items), require manual
    SKU allocations that sum back to the verified refund for that card.
    """
    if _text((return_case or {}).get("value_mode")) != "tiktok_return_groups":
        return
    verify_tiktok_source_coverage(return_case, physically_returned + not_returned)
    totals = return_case.get("return_group_totals") or {}
    expected_qtys = return_case.get("return_group_quantities") or {}
    curated = _confirmed_tiktok_manual_selection(
        return_case, physically_returned + not_returned,
    )
    assignments = {}
    pool = _build_returned_item_pool(physically_returned)
    for ix, transfer in enumerate(transfers, start=1):
        for item in _take_items_for_transfer(transfer, pool):
            rid = _text((item.get("source_data") or {}).get("return_order_id"))
            assignments.setdefault(rid, []).append((f"transfer:{ix}", item))
    if any(entry["remaining"] for entry in pool):
        raise ValueError(
            "Some physically returned TikTok items are not represented in "
            "the recorded Odoo transfer(s). Lark filing is blocked."
        )
    for ix, item in enumerate(not_returned, start=1):
        rid = _text((item.get("source_data") or {}).get("return_order_id"))
        assignments.setdefault(rid, []).append((f"direct:{ix}", item))

    expected_selected = (
        return_case["tiktok_manual_selection"]["selected_return_quantities"]
        if curated else expected_qtys
    )
    if set(assignments) != set(expected_selected):
        raise ValueError(
            "TikTok Lark transfers do not cover the confirmed selected return "
            "cards. Review the existing Odoo transfer(s) and item list."
        )
    for rid, entries in assignments.items():
        actual = sum(int(item.get("quantity") or 0) for _, item in entries)
        expected = int(expected_selected[rid])
        if actual != expected:
            raise ValueError(
                f"TikTok return {rid} has {actual} item unit(s) allocated to "
                f"Lark, but the confirmed selection has {expected}."
            )
        filings = {key for key, _ in entries}
        if curated:
            # The operator has already confirmed each retained item's
            # refund. Values may be lower than the original return-card total.
            subtotal = 0.0
            for _, item in entries:
                q = int(item["quantity"])
                source_q = int(item.get("_lark_source_quantity") or q)
                subtotal += float(item["amount"]) * q / source_q
            if round(subtotal, 2) > round(float(totals[rid]), 2) + 0.01:
                raise ValueError(f"Selected refund exceeds source return {rid}.")
            continue
        if len(filings) <= 1:
            continue
        subtotal = 0.0
        for _, item in entries:
            raw = item.get("amount")
            if raw is None or str(raw).strip() == "":
                raise ValueError(
                    f"TikTok return {rid} is split across {len(filings)} "
                    "Lark filings. Enter an accurate Amount for every "
                    "SKU in that return card before submitting."
                )
            try:
                amount = float(raw)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid Amount for SKU {item.get('sku')}.") from error
            source_qty = int(item.get("_lark_source_quantity") or item["quantity"])
            subtotal += amount * int(item["quantity"]) / source_qty
        if abs(round(subtotal, 2) - round(float(totals[rid]), 2)) > 0.01:
            raise ValueError(
                f"TikTok return {rid} is allocated ₱{subtotal:,.2f} across "
                f"multiple filings, but the source refund is "
                f"₱{float(totals[rid]):,.2f}. Correct per-item Amounts first."
            )


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
            allocated_item["_lark_source_quantity"] = int(item["quantity"])
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
    return_case: dict | None,
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
        "value": _record_value(return_case, items),
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
            "value_source": _value_source(return_case),
            "items": [
                {
                    "sku": _text(item.get("sku")),
                    "quantity": int(item["quantity"]),
                }
                for item in items
            ],
        },
    }


def _direct_record(item: dict, return_case: dict | None) -> dict:
    sku = _text(item.get("sku"))
    quantity = int(item.get("quantity", 0))
    return {
        "order_id": None,  # injected by caller
        "sku": sku,
        "quantity": quantity,
        "value": _record_value(return_case, [item]),
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
            "value_source": _value_source(return_case),
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
    result["value_source"] = meta.get("value_source", "Return/refund value")
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
    existing_results=None,
    on_record_complete=None,
) -> list[dict]:
    """
    Returned items -> one Lark filing per Odoo Transfer ID.
    Not Returned items -> direct Lark filing with blank Transfer ID/Link.
    """
    if not order_id:
        raise ValueError("Order ID is required for Lark filing.")
    if not returned_products:
        raise ValueError("No returned products are available for Lark filing.")

    _refund_value(return_case)  # validate source value before any filing
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
    _preflight_tiktok_return_groups(
        return_case, physically_returned, not_returned, transfers,
    )
    # Prebuild and validate EVERY Lark record before clicking Submit on any
    # one of them. An invalid later record must not leave an earlier filing
    # submitted while the case appears to have failed validation.
    planned_records = []
    planning_pool = _build_returned_item_pool(physically_returned)
    for index, transfer in enumerate(transfers, start=1):
        planned_records.append(_transfer_record(
            transfer, planning_pool, return_case, index,
        ))
    for item in not_returned:
        planned_records.append(_direct_record(item, return_case))
    if any(entry['remaining'] for entry in planning_pool):
        raise ValueError(
            'Some returned units have no matching Odoo transfer. '
            'Lark was not opened; do not repeat Odoo.'
        )

    results = []
    previous_success_page = None

    def file_in_fresh_tab(record: dict) -> dict:
        nonlocal previous_success_page
        page = get_or_open_lark_page(context)
        page.bring_to_front()
        # On failure, leave this tab open for the operator to inspect.
        result = _submit_record(page, record, order_id, progress_callback)
        # Keep only the latest successful 'Submitted' tab open.
        if previous_success_page is not None:
            try:
                if not previous_success_page.is_closed():
                    previous_success_page.close()
            except Exception:
                pass
        previous_success_page = page
        return result

    # Route key includes the intended form contents and position; previously
    # confirmed records cannot be silently submitted again on a partial retry.
    prior = {str(r.get("route_key")): r for r in (existing_results or [])
             if r.get("route_key") and r.get("submitted")}
    for index, record in enumerate(planned_records, start=1):
        canonical = json.dumps({"order_id": order_id, "index": index,
                                "record": record}, sort_keys=True, default=str)
        route_key = "normal:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        previous = prior.get(route_key)
        if previous:
            _progress(progress_callback, f"Skipping previously filed {record['sku']}.")
            results.append(previous)
            continue
        _progress(
            progress_callback,
            f"Filing Lark record {index}/{len(planned_records)}: "
            f"{record.get('transfer_id') or 'Direct'} | {record['sku']}",
        )
        result = file_in_fresh_tab(record)
        result["route_key"] = route_key
        # Callback saves an atomic, verified Recovery point before another form.
        if on_record_complete:
            on_record_complete(result)
        results.append(result)

    if not results:
        raise ValueError("No Lark filing records were generated.")
    return results


__all__ = [
    "preview_tiktok_manual_selection",
    "confirm_tiktok_manual_selection",
    "build_prefilled_lark_url",
    "get_or_open_lark_page",
    "file_lark_return",
    "file_lark_returns",
]
