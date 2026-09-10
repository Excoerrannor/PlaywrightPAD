import re

ODOO_TICKETS_URL = "https://makerlab.odoo.com/odoo/helpdesk/3/tickets"

DEFAULT_TIMEOUT = 30_000
SLOW_ODOO_TIMEOUT = 60_000
ODOO_COMMIT_BUFFER_MS = 700


def build_ticket_title(order_id: str, returned_products: list[dict]) -> str:
    """
    Build: ORDER ID - SKU_QTY, SKU_QTY...

    Duplicate SKU rows are combined in the ticket title only.

    Example:
        MLE03495_1 Unsealed
        MLE03495_1 Defective

    becomes:
        ORDER ID - MLE03495_2

    The item rows themselves remain separate so Odoo can still create
    different Return / QC flows for each classification.
    """
    if not returned_products:
        raise ValueError("At least one returned product is required.")

    qty_by_sku = {}
    sku_order = []

    for item in returned_products:
        sku = str(item["sku"]).strip()
        quantity = int(item["quantity"])

        if sku not in qty_by_sku:
            qty_by_sku[sku] = 0
            sku_order.append(sku)

        qty_by_sku[sku] += quantity

    parts = [
        f"{sku}_{qty_by_sku[sku]}"
        for sku in sku_order
    ]

    return f"{order_id} - " + ", ".join(parts)


def get_or_open_odoo_page(context):
    for page in context.pages:
        if page.is_closed():
            continue

        if "/odoo/helpdesk/3/tickets" in page.url:
            return page

    page = context.new_page()
    page.goto(
        ODOO_TICKETS_URL,
        wait_until="domcontentloaded",
        timeout=SLOW_ODOO_TIMEOUT,
    )
    return page


def _set_basic_ticket_fields(page, ticket_title: str):
    page.get_by_role("button", name="New").click()

    title_box = page.get_by_role(
        "textbox",
        name="Ticket Title",
    )
    title_box.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )
    title_box.fill(ticket_title)

    assigned_to = page.get_by_role(
        "combobox",
        name="Assigned to",
    )
    assigned_to.click()
    assigned_to.fill("Tech")

    page.get_by_role(
        "option",
        name="Technical Department",
        exact=True,
    ).click()

    customer = page.get_by_role(
        "combobox",
        name="Customer",
    )
    customer.click()
    customer.fill("Shop")

    page.get_by_role(
        "option",
        name="ECOMMERCE, SHOPEE",
        exact=True,
    ).click()


def _create_and_open_ticket(page, ticket_title: str) -> str:
    page.get_by_role(
        "button",
        name="Add",
        exact=True,
    ).click()

    created_ticket = page.get_by_text(
        ticket_title,
        exact=True,
    ).first

    created_ticket.wait_for(
        state="visible",
        timeout=SLOW_ODOO_TIMEOUT,
    )

    created_ticket.click()

    page.wait_for_url(
        re.compile(
            r".*/odoo/helpdesk/3/tickets/\d+(?:[/?#].*)?$"
        ),
        timeout=SLOW_ODOO_TIMEOUT,
    )

    product_field = page.get_by_role(
        "combobox",
        name="Product?",
    )
    product_field.wait_for(
        state="visible",
        timeout=SLOW_ODOO_TIMEOUT,
    )

    return page.url


def _select_product(page, sku: str):
    product_field = page.get_by_role(
        "combobox",
        name="Product?",
    )

    product_field.click()
    product_field.fill(sku)

    sku_option = page.get_by_role(
        "option",
        name=re.compile(
            rf"^\[{re.escape(sku)}\]"
        ),
    ).first

    sku_option.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    sku_option.click()


def _select_tags(page, tags: list[str]):
    """
    Add all unique Odoo tags to the same Helpdesk ticket.
    Odoo's Tags field is many-to-many, so several tags can coexist.
    """
    unique_tags = []
    for tag in tags:
        tag = str(tag).strip()
        if tag and tag not in unique_tags:
            unique_tags.append(tag)

    if not unique_tags:
        raise ValueError("At least one Odoo tag is required.")

    for tag in unique_tags:
        tag_field = page.get_by_role(
            "combobox",
            name="Tags",
        )
        tag_field.wait_for(
            state="visible",
            timeout=DEFAULT_TIMEOUT,
        )
        tag_field.click()
        tag_field.fill(tag[:12])

        tag_option = page.get_by_role(
            "option",
            name=tag,
            exact=True,
        )
        tag_option.wait_for(
            state="visible",
            timeout=DEFAULT_TIMEOUT,
        )
        tag_option.click()



def _set_urgent_priority(page):
    urgent = page.get_by_role(
        "radio",
        name="Urgent",
    )

    urgent.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    urgent.click()


def _get_return_dialog(page):
    """
    Return the active Odoo Return modal.
    """

    dialog = page.get_by_role(
        "dialog",
    ).last

    dialog.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    return dialog


def _get_return_rows(dialog):
    """
    Return only actual product rows from product_return_moves.
    """

    moves_table = dialog.locator(
        'div[name="product_return_moves"]'
    )

    moves_table.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    rows = moves_table.locator(
        "tbody > tr.o_data_row"
    )

    rows.first.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    return rows


def _debug_return_rows(rows):
    """
    Print products currently detected in the Odoo return table.
    """

    data = rows.evaluate_all(
        """
        rows => rows.map(row => ({
            product:
                row.querySelector('td[name="product_id"]')
                    ?.textContent?.trim() || "",
            quantity:
                row.querySelector('td[name="quantity"]')
                    ?.textContent?.trim() || ""
        }))
        """
    )

    print("\nODOO RETURN PRODUCT ROWS:")

    for item in data:
        print(
            f"{item['product']} | "
            f"QTY {item['quantity']}"
        )

    return data


def _find_return_product_row(dialog, sku: str):
    """
    Find the exact Odoo return row for the requested SKU.

    Important:
    when Odoo puts a row into edit mode, the visible product text can
    disappear and be replaced by a combobox input. However, the stable
    td[name="product_id"] data-tooltip still contains the original product
    text, e.g.:

        data-tooltip="[MLE08858] Bambu Lab Filament ..."

    Therefore we identify and verify rows using data-tooltip, not inner_text.
    """

    moves_table = dialog.locator(
        'div[name="product_return_moves"]'
    )

    moves_table.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    target_row = moves_table.locator(
        (
            "tbody > tr.o_data_row:"
            f'has(td[name="product_id"][data-tooltip^="[{sku}]"])'
        )
    ).first

    target_row.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    product_cell = target_row.locator(
        'td[name="product_id"]'
    )

    product_tooltip = (
        product_cell.get_attribute("data-tooltip")
        or ""
    ).strip()

    if not product_tooltip.startswith(
        f"[{sku}]"
    ):
        raise ValueError(
            f"Odoo row safety check failed. "
            f"Expected SKU {sku}, found: {product_tooltip!r}"
        )

    return target_row



def _set_return_row_quantity(
    page,
    dialog,
    sku: str,
    quantity: int,
):
    """
    Set the return quantity for the exact SKU row.

    This avoids bounding_box()/mouse coordinates entirely.

    Odoo behavior observed during testing:
      - locator.click() DOES activate/highlight the correct cell
      - but Odoo immediately rerenders the row
      - Playwright can then report a click timeout even though the click worked

    Strategy:
      1. locate exact SKU row from stable product data-tooltip
      2. click its quantity cell with a very short timeout
      3. ignore a click timeout because the DOM may have rerendered
      4. reacquire the exact SKU row
      5. check for the quantity input inside that same row
      6. if no input exists yet, repeat the click once
      7. fill and verify the quantity

    No Ctrl+A, Tab, Enter, click-away, or coordinate-based clicking is used.
    """

    for attempt in range(2):

        # Always reacquire because Odoo may replace the row after each click.
        target_row = _find_return_product_row(
            dialog=dialog,
            sku=sku,
        )

        qty_cell = target_row.locator(
            'td[name="quantity"]'
        )

        qty_cell.wait_for(
            state="visible",
            timeout=DEFAULT_TIMEOUT,
        )

        try:
            # Short timeout is intentional. The click can succeed visually
            # and then Odoo replaces the clicked DOM node immediately.
            qty_cell.click(
                force=True,
                timeout=1_500,
            )
        except Exception:
            # Do not fail here. Reacquire the row and inspect whether
            # Odoo actually entered inline edit mode.
            pass

        page.wait_for_timeout(
            200
        )

        # Reacquire the exact same SKU row after Odoo's rerender.
        target_row = _find_return_product_row(
            dialog=dialog,
            sku=sku,
        )

        qty_input = target_row.locator(
            'td[name="quantity"] input'
        ).first

        try:
            qty_input.wait_for(
                state="visible",
                timeout=1_500,
            )
        except Exception:
            if attempt == 0:
                # First click may only select/highlight the cell.
                # Repeat once on the exact same SKU row.
                continue

            raise RuntimeError(
                f"Odoo found and selected SKU {sku}, "
                "but its Quantity input did not enter edit mode."
            )

        qty_input.fill(
            str(quantity)
        )

        actual_value = qty_input.input_value().strip()

        try:
            actual_number = float(
                actual_value
            )
        except ValueError as error:
            raise RuntimeError(
                f"Invalid quantity value for {sku}: "
                f"{actual_value!r}"
            ) from error

        if actual_number != float(quantity):
            raise RuntimeError(
                f"Quantity verification failed for {sku}. "
                f"Expected {quantity}, got {actual_value!r}."
            )

        print(
            f"ODOO RETURN QTY SET: {sku} = {quantity}"
        )

        return

    raise RuntimeError(
        f"Could not enter return quantity for {sku}."
    )



def _verify_return_quantities(
    dialog,
    expected_by_sku: dict[str, int],
):
    """
    Final safety gate before Return.

    Every SKU in expected_by_sku must equal the requested quantity.
    Every other product in the Sales Order must remain at 0.
    """
    rows = _get_return_rows(dialog)

    data = rows.evaluate_all(
        """
        rows => rows.map(row => {
            const productCell = row.querySelector('td[name="product_id"]');
            const qtyCell = row.querySelector('td[name="quantity"]');
            const qtyInput = qtyCell?.querySelector('input');

            return {
                product:
                    productCell?.getAttribute('data-tooltip') ||
                    productCell?.textContent?.trim() ||
                    "",
                quantity:
                    qtyInput
                        ? qtyInput.value
                        : qtyCell?.textContent?.trim() || ""
            };
        })
        """
    )

    found = set()

    print("\nODOO RETURN PRE-SUBMIT CHECK:")

    for item in data:
        product_text = str(item["product"]).strip()
        match = re.search(r"\[(MLE\d+)\]", product_text)
        if not match:
            continue

        sku = match.group(1)
        raw_qty = str(item["quantity"]).strip().replace(",", "") or "0"

        try:
            qty = float(raw_qty)
        except ValueError as error:
            raise RuntimeError(
                f"Could not read return quantity for {sku}: {raw_qty!r}"
            ) from error

        expected = float(expected_by_sku.get(sku, 0))
        print(f"{sku} | actual {qty} | expected {expected}")

        if sku in expected_by_sku:
            found.add(sku)

        if qty != expected:
            raise RuntimeError(
                f"Safety stop: {sku} should return {expected:g}, "
                f"but Odoo currently shows {qty:g}. Return was NOT submitted."
            )

    missing = set(expected_by_sku) - found
    if missing:
        raise RuntimeError(
            "Safety stop: target SKU(s) not found in Odoo Return table: "
            + ", ".join(sorted(missing))
        )



def _read_return_table(dialog) -> dict[str, float]:
    """Read current Odoo return quantities keyed by SKU."""
    rows = _get_return_rows(dialog)

    data = rows.evaluate_all(
        """
        rows => rows.map(row => {
            const productCell = row.querySelector('td[name="product_id"]');
            const qtyCell = row.querySelector('td[name="quantity"]');
            const qtyInput = qtyCell?.querySelector('input');

            return {
                product:
                    productCell?.getAttribute('data-tooltip') ||
                    productCell?.textContent?.trim() ||
                    "",
                quantity:
                    qtyInput
                        ? qtyInput.value
                        : qtyCell?.textContent?.trim() || ""
            };
        })
        """
    )

    result = {}
    for item in data:
        match = re.search(r"\[(MLE\d+)\]", str(item["product"]))
        if not match:
            continue

        raw = str(item["quantity"]).strip().replace(",", "") or "0"
        try:
            result[match.group(1)] = float(raw)
        except ValueError:
            result[match.group(1)] = 0.0

    return result


def _wait_for_return_skus(
    page,
    dialog,
    expected_skus,
):
    """
    Wait until Odoo has finished rendering ALL expected returned products.

    Odoo can render the first product row before the remaining rows appear.
    The previous code continued as soon as the first row was visible, which
    could make a valid second SKU look "missing".

    Returns the fully observed SKU -> quantity mapping.
    """

    expected_skus = {
        str(sku).strip()
        for sku in expected_skus
    }

    deadline_ms = SLOW_ODOO_TIMEOUT
    elapsed_ms = 0
    poll_ms = 250
    last_seen = {}

    while elapsed_ms < deadline_ms:
        last_seen = _read_return_table(
            dialog
        )

        seen_skus = set(
            last_seen
        )

        missing = (
            expected_skus
            - seen_skus
        )

        if not missing:
            print(
                "ODOO RETURN ITEMS READY:",
                ", ".join(sorted(seen_skus)),
            )
            return last_seen

        page.wait_for_timeout(
            poll_ms
        )
        elapsed_ms += poll_ms

    raise RuntimeError(
        "These returned SKU(s) were not found in the Odoo Sales Order "
        "after waiting for the full Return table to load: "
        + ", ".join(sorted(expected_skus - set(last_seen)))
    )


def _open_return_transfer(
    page,
    order_id: str,
    items: list[dict],
):
    """
    Create ONE Odoo Return for all items in this return group.

    Example:
        MLE02804 | QTY 1 | New | Disputed
        MLE05243 | QTY 1 | New | Disputed

    becomes one Return with:
        MLE02804 = 1
        MLE05243 = 1
        all unrelated products = 0

    Important:
    Odoo can render multi-item return rows progressively, so the automation
    waits until every expected SKU is actually present before editing QTY.
    """

    if not items:
        raise ValueError(
            "Return group contains no items."
        )

    desired = {}

    for item in items:
        sku = str(
            item["sku"]
        ).strip()

        desired[sku] = (
            desired.get(sku, 0)
            + int(item["quantity"])
        )

    # --------------------------------------------------------
    # Open Return wizard
    # --------------------------------------------------------

    return_button = page.get_by_role(
        "button",
        name="Return",
        exact=True,
    )

    return_button.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    return_button.click()

    dialog = _get_return_dialog(
        page
    )

    # --------------------------------------------------------
    # Select Sales Order
    # --------------------------------------------------------

    sales_order = dialog.get_by_role(
        "combobox",
        name="Sales Order",
    )

    sales_order.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    sales_order.fill(
        order_id[-4:]
    )

    order_option = page.get_by_role(
        "option",
        name=order_id,
        exact=True,
    )

    order_option.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    order_option.click()

    # --------------------------------------------------------
    # WAIT FOR ALL RETURNED SKUs
    # --------------------------------------------------------
    # Previously we only waited for the first o_data_row. On multi-item
    # orders Odoo may display row 1 before row 2 has been rendered.

    current = _wait_for_return_skus(
        page=page,
        dialog=dialog,
        expected_skus=set(desired),
    )

    print(
        "\nODOO RETURN TABLE BEFORE EDIT:"
    )

    for sku, qty in current.items():
        print(
            f"{sku} | QTY {qty}"
        )

    # --------------------------------------------------------
    # Set every item belonging to this Return
    # --------------------------------------------------------

    for sku, wanted in desired.items():
        print(
            f"SETTING ODOO RETURN: {sku} -> {wanted}"
        )

        _set_return_row_quantity(
            page=page,
            dialog=dialog,
            sku=sku,
            quantity=wanted,
        )

    # --------------------------------------------------------
    # Safety verification
    # --------------------------------------------------------
    # Every target must have the requested QTY and every unrelated item
    # must remain zero before Return is allowed to continue.

    _verify_return_quantities(
        dialog=dialog,
        expected_by_sku=desired,
    )

    # --------------------------------------------------------
    # Submit ONE Return containing all grouped SKUs
    # --------------------------------------------------------

    create_returns = dialog.locator(
        'button[name="action_create_returns"]'
    )

    create_returns.wait_for(
        state="visible",
        timeout=DEFAULT_TIMEOUT,
    )

    create_returns.click()



def _capture_transfer(page):
    transfer_heading = page.get_by_role(
        "heading",
    ).get_by_text(
        re.compile(r"TC/IN/\d+")
    ).first

    transfer_heading.wait_for(
        state="visible",
        timeout=SLOW_ODOO_TIMEOUT,
    )

    heading_text = transfer_heading.inner_text().strip()

    match = re.search(
        r"TC/IN/\d+",
        heading_text,
    )

    if not match:
        raise ValueError(
            f"Could not extract TC transfer ID from {heading_text!r}"
        )

    return {
        "transfer_id": match.group(0),
        "transfer_url": page.url,
        "heading": transfer_heading,
    }


def _click_validate(page):
    validate_button = page.get_by_role(
        "button",
        name=re.compile(r"^Validate"),
    ).first

    validate_button.wait_for(
        state="visible",
        timeout=SLOW_ODOO_TIMEOUT,
    )

    validate_button.click()


def _process_brand_new(page):
    """
    Classification = New

    Destination Location -> MNL/Stock
    -> click TC/IN/##### heading to commit
    -> Validate
    """

    destination = page.get_by_role(
        "combobox",
        name="Destination Location",
    )

    destination.wait_for(
        state="visible",
        timeout=SLOW_ODOO_TIMEOUT,
    )

    destination.click()
    destination.fill("MNL/Stock")

    page.get_by_role(
        "option",
        name="MNL/Stock",
        exact=True,
    ).click()

    transfer = _capture_transfer(page)

    # Required by the observed Odoo behavior so MNL/Stock is committed
    # before Validate.
    transfer["heading"].click()

    page.wait_for_timeout(
        ODOO_COMMIT_BUFFER_MS
    )

    _click_validate(page)

    return {
        "destination_location": "MNL/Stock",
        "qc_result": None,
        "transfer_id": transfer["transfer_id"],
        "transfer_url": transfer["transfer_url"],
        "validated": True,
    }


def _wait_for_next_qc_dialog(
    page,
    expected_skus: set[str],
    processed_skus: set[str],
):
    """
    Wait for the next automatically-opened TECHNICAL RETURN QC dialog.

    Odoo opens one QC dialog per SKU in the validated transfer. The dialog
    title contains the SKU, for example:

        TECHNICAL RETURN QC : [MLE05696] ...

    We use that SKU to decide whether this specific item should be routed to
    TC/Stock/Open Box or TC/Defective.
    """

    elapsed_ms = 0
    poll_ms = 250

    while elapsed_ms < SLOW_ODOO_TIMEOUT:

        dialogs = page.locator(
            'div[role="dialog"]'
        )

        dialog_count = dialogs.count()

        for index in range(dialog_count - 1, -1, -1):
            dialog = dialogs.nth(index)

            if not dialog.is_visible():
                continue

            title = dialog.locator(
                "h4.modal-title"
            )

            if title.count() == 0:
                continue

            title_text = title.inner_text().strip()

            if "TECHNICAL RETURN QC" not in title_text:
                continue

            match = re.search(
                r"\[(MLE\d+)\]",
                title_text,
            )

            if not match:
                continue

            sku = match.group(1)

            if (
                sku in expected_skus
                and sku not in processed_skus
            ):
                return dialog, sku, title_text

        page.wait_for_timeout(
            poll_ms
        )
        elapsed_ms += poll_ms

    remaining = sorted(
        expected_skus - processed_skus
    )

    raise RuntimeError(
        "Timed out waiting for the next Odoo QC dialog. "
        "Remaining SKU(s): "
        + ", ".join(remaining)
    )


def _process_open_box_or_defective(
    page,
    items: list[dict],
):
    """
    Validate one Open Box / Defective Odoo transfer containing one or more SKUs.

    Odoo opens ONE TECHNICAL RETURN QC dialog PER SKU after Validate.

    For every QC dialog:
        identify the SKU from the dialog title
        -> Fail
        -> Unsealed  => TC/Stock/Open Box
        -> Defective => TC/Defective
        -> Confirm
        -> wait for Odoo to automatically open the next SKU's QC dialog

    This continues until every SKU in the transfer has been processed.
    """

    if not items:
        raise ValueError(
            "Open Box / Defective QC requires at least one item."
        )

    item_by_sku = {}

    for item in items:
        sku = str(
            item["sku"]
        ).strip()

        classification = str(
            item.get("classification", "")
        ).strip()

        if classification == "Unsealed":
            qc_result = "TC/Stock/Open Box"
        elif classification == "Defective":
            qc_result = "TC/Defective"
        else:
            raise ValueError(
                f"Unsupported QC classification for {sku}: "
                f"{classification}"
            )

        item_by_sku[sku] = {
            "classification": classification,
            "qc_result": qc_result,
        }

    expected_skus = set(
        item_by_sku
    )

    transfer = _capture_transfer(
        page
    )

    _click_validate(
        page
    )

    processed_skus = set()
    qc_results = []

    while processed_skus != expected_skus:

        dialog, sku, title_text = _wait_for_next_qc_dialog(
            page=page,
            expected_skus=expected_skus,
            processed_skus=processed_skus,
        )

        qc_result = item_by_sku[
            sku
        ]["qc_result"]

        print(
            f"ODOO QC: {sku} -> FAIL -> {qc_result}"
        )
        print(
            f"QC DIALOG: {title_text}"
        )

        fail_button = dialog.get_by_role(
            "button",
            name="Fail",
            exact=True,
        )

        fail_button.wait_for(
            state="visible",
            timeout=DEFAULT_TIMEOUT,
        )

        fail_button.click()

        # The Fail action opens the location/result selector.
        qc_option = page.get_by_text(
            qc_result,
            exact=True,
        ).last

        qc_option.wait_for(
            state="visible",
            timeout=DEFAULT_TIMEOUT,
        )

        qc_option.click()

        confirm_button = page.get_by_role(
            "button",
            name="Confirm",
            exact=True,
        ).last

        confirm_button.wait_for(
            state="visible",
            timeout=DEFAULT_TIMEOUT,
        )

        confirm_button.click()

        processed_skus.add(
            sku
        )

        qc_results.append(
            {
                "sku": sku,
                "classification": item_by_sku[sku][
                    "classification"
                ],
                "qc_result": qc_result,
            }
        )

        # Give Odoo a moment to close this QC dialog and automatically
        # present the next SKU's QC dialog.
        page.wait_for_timeout(
            350
        )

    return {
        "destination_location": None,
        "qc_result": (
            qc_results[0]["qc_result"]
            if len(qc_results) == 1
            else "Multiple"
        ),
        "qc_results": qc_results,
        "transfer_id": transfer["transfer_id"],
        "transfer_url": transfer["transfer_url"],
        "validated": True,
    }



def _return_group_key(item: dict):
    """
    Different Decision = different Odoo Return.
    Classification/status are included because they change the stock route.
    Grade and amount are Lark-only and do not require separate Odoo returns.
    """
    return (
        str(item.get("decision", "")).strip(),
        str(item.get("classification", "")).strip(),
        str(item.get("status", "")).strip(),
    )


def _build_return_groups(items: list[dict]) -> list[dict]:
    groups = []
    index_by_key = {}

    for item in items:
        key = _return_group_key(item)

        if key not in index_by_key:
            index_by_key[key] = len(groups)
            groups.append({
                "decision": key[0],
                "classification": key[1],
                "status": key[2],
                "items": [],
            })

        groups[index_by_key[key]]["items"].append(item)

    return groups


def create_odoo_tickets(
    context,
    order_id: str,
    returned_products: list[dict],
    case_decision: dict | None = None,
    progress_callback=None,
) -> dict:
    """
    Create ONE Helpdesk ticket for the entire Shopee order.

    Ticket title:
        ORDER ID - SKU_QTY, SKU_QTY, SKU_QTY...

    Product:
        first returned SKU

    Tags:
        all unique item Odoo tags

    Returns:
        items with the same Decision + Classification + Status share one
        Odoo Return. Different handling creates another Return on the same
        ticket.
    """
    if not order_id:
        raise ValueError("Order ID is required.")
    if not returned_products:
        raise ValueError("No returned products were found.")

    def progress(message):
        if progress_callback:
            progress_callback(message)
        print(message)

    # Validate currently supported physical return routes.
    for item in returned_products:
        classification = str(item.get("classification", "")).strip()
        status = str(item.get("status", "")).strip()

        if classification not in {"New", "Unsealed", "Defective"}:
            raise NotImplementedError(
                f"Odoo stock-return route is not implemented for "
                f"{classification or 'blank classification'}."
            )

        if status != "Returned":
            raise NotImplementedError(
                "Odoo stock-return processing currently requires "
                "Status = Returned."
            )

    ticket_title = build_ticket_title(
        order_id,
        returned_products,
    )

    first_sku = str(returned_products[0]["sku"]).strip()

    tags = []
    for item in returned_products:
        tag = str(item.get("odoo_tag", "")).strip()
        if tag and tag not in tags:
            tags.append(tag)

    page = get_or_open_odoo_page(context)
    page.bring_to_front()

    if (
        "/odoo/helpdesk/3/tickets" not in page.url
        or re.search(r"/tickets/\d+", page.url)
    ):
        page.goto(
            ODOO_TICKETS_URL,
            wait_until="domcontentloaded",
            timeout=SLOW_ODOO_TIMEOUT,
        )

    page.get_by_role("button", name="New").wait_for(
        state="visible",
        timeout=SLOW_ODOO_TIMEOUT,
    )

    progress(f"Creating one Odoo ticket: {ticket_title}")
    _set_basic_ticket_fields(page, ticket_title)

    progress("Saving new Odoo ticket...")
    ticket_url = _create_and_open_ticket(page, ticket_title)

    progress(f"Selecting first returned product: {first_sku}")
    _select_product(page, first_sku)

    progress("Adding Odoo tag(s): " + ", ".join(tags))
    _select_tags(page, tags)

    progress("Setting priority to Urgent...")
    _set_urgent_priority(page)

    groups = _build_return_groups(returned_products)
    return_results = []

    for group_index, group in enumerate(groups, start=1):
        # After the first return, Odoo is on the stock-picking page.
        # Return to the SAME Helpdesk ticket before opening another Return.
        if group_index > 1:
            progress(
                f"Returning to Helpdesk ticket for Return #{group_index}..."
            )
            page.goto(
                ticket_url,
                wait_until="domcontentloaded",
                timeout=SLOW_ODOO_TIMEOUT,
            )
            page.get_by_role(
                "button",
                name="Return",
                exact=True,
            ).wait_for(
                state="visible",
                timeout=SLOW_ODOO_TIMEOUT,
            )

        item_text = ", ".join(
            f"{item['sku']}_{item['quantity']}"
            for item in group["items"]
        )

        progress(
            f"Creating Return #{group_index}: {item_text} | "
            f"{group['classification']} | {group['decision']}"
        )

        _open_return_transfer(
            page=page,
            order_id=order_id,
            items=group["items"],
        )

        if group["classification"] == "New":
            stock_result = _process_brand_new(page)
        else:
            stock_result = _process_open_box_or_defective(
                page=page,
                items=group["items"],
            )

        return_results.append({
            "return_index": group_index,
            "decision": group["decision"],
            "classification": group["classification"],
            "status": group["status"],
            "items": [
                {
                    "sku": str(item["sku"]).strip(),
                    "quantity": int(item["quantity"]),
                }
                for item in group["items"]
            ],
            **stock_result,
        })

        progress(
            f"Return #{group_index} completed: "
            f"{stock_result['transfer_id']}"
        )

    return {
        "ticket_title": ticket_title,
        "ticket_url": ticket_url,
        "product_sku": first_sku,
        "tags": tags,
        "returns": return_results,
    }


__all__ = [
    "build_ticket_title",
    "get_or_open_odoo_page",
    "create_odoo_tickets",
]
