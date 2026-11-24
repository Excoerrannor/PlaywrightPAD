"""
Makerlab Shopee Dispute Result Checker

Purpose
-------
1. Read the Lark "Results" view.
2. Find records where:
       Decision = Disputed
       Dispute Results = blank
3. Search each Order ID in Shopee Return/Refund/Cancel.
4. Read Shopee's Request Status.
5. Update Lark:
       Dispute Rejected -> Rejected
       Dispute Approved -> Approved
6. Leave unresolved/unknown Shopee statuses unchanged.

This file is standalone and does NOT modify main.py.

It reuses the same BrowserManager / persistent Chrome profile as the
Makerlab Return Processor project.
"""

from __future__ import annotations

import csv
import re
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from browser_manager import BrowserManager


# ============================================================
# CONFIG
# ============================================================

LARK_RESULTS_URL = (
    "https://kjx72am2njb.sg.larksuite.com/wiki/"
    "Cp8ewHPjFiKkTakxzBglPnbqgMe"
    "?table=tblyFQ1CEvB3xw0f&view=vew8iunXt4"
)

SHOPEE_RETURN_URL = (
    "https://seller.shopee.ph/portal/sale/returnrefundcancel"
)

SHOPEE_SEARCH_PLACEHOLDER = (
    "Input Request ID Order ID Return Tracking Number Buyer Name"
)

DEFAULT_TIMEOUT = 30_000
SLOW_TIMEOUT = 60_000

# Exact status mappings only.
# Unknown statuses are NEVER written to Lark automatically.
SHOPEE_STATUS_MAP = {
    "Dispute Rejected": "Rejected",
    "Dispute Approved": "Approved",
}

FINAL_LARK_RESULTS = {
    "Approved",
    "Rejected",
}

ORDER_ID_RE = re.compile(r"^[A-Z0-9]{12,24}$", re.IGNORECASE)


# ============================================================
# DATA
# ============================================================

@dataclass
class LarkRow:
    order_id: str
    decision: str
    dispute_result: str
    y: float


@dataclass
class CheckResult:
    order_id: str
    shopee_status: str
    lark_result: str
    action: str
    detail: str = ""


# ============================================================
# SMALL HELPERS
# ============================================================

def _text(value) -> str:
    return str(value or "").strip()


def _normalize_lines(value: str) -> list[str]:
    return [
        line.strip()
        for line in _text(value).splitlines()
        if line.strip()
    ]


def _visible_exact_text(page, text: str, timeout=SLOW_TIMEOUT):
    """
    Return the first visible exact-text locator.
    Lark can keep hidden duplicate elements in the DOM.
    """
    deadline = time.monotonic() + (timeout / 1000)

    while time.monotonic() < deadline:
        locator = page.get_by_text(text, exact=True)
        count = locator.count()

        for index in range(min(count, 50)):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                pass

        page.wait_for_timeout(250)

    raise TimeoutError(
        f"Could not find visible Lark text: {text!r}"
    )


# ============================================================
# LARK TABLE READER / WRITER
# ============================================================

class LarkResultsView:
    """
    Reads and edits the visible Lark Base grid.

    This intentionally does not depend on Lark's private API.
    It uses the same browser session already used by the project.

    The table is virtualized, so rows are collected while scrolling.
    """

    SCROLL_MARKER = "data-makerlab-dispute-scroll"

    def __init__(self, page, log_callback=None):
        self.page = page
        self.log_callback = log_callback

        self.order_header_box = None
        self.decision_header_box = None
        self.result_header_box = None

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)
        print(message)

    # --------------------------------------------------------
    # OPEN / HEADERS
    # --------------------------------------------------------

    def open(self):
        self.log("Opening Lark Results view...")

        self.page.goto(
            LARK_RESULTS_URL,
            wait_until="domcontentloaded",
            timeout=SLOW_TIMEOUT,
        )

        # Wait for the three columns used by this checker.
        order_header = _visible_exact_text(
            self.page,
            "Order ID",
        )
        decision_header = _visible_exact_text(
            self.page,
            "Decision",
        )
        result_header = _visible_exact_text(
            self.page,
            "Dispute Results",
        )

        self.order_header_box = order_header.bounding_box()
        self.decision_header_box = decision_header.bounding_box()
        self.result_header_box = result_header.bounding_box()

        if not all(
            (
                self.order_header_box,
                self.decision_header_box,
                self.result_header_box,
            )
        ):
            raise RuntimeError(
                "Could not read Lark table column positions."
            )

        self._mark_scroll_container()
        self.log("Lark Results view ready.")

    @property
    def order_x(self) -> float:
        box = self.order_header_box
        return box["x"] + (box["width"] / 2)

    @property
    def decision_x(self) -> float:
        box = self.decision_header_box
        return box["x"] + (box["width"] / 2)

    @property
    def result_x(self) -> float:
        box = self.result_header_box
        return box["x"] + (box["width"] / 2)

    @property
    def header_bottom(self) -> float:
        boxes = (
            self.order_header_box,
            self.decision_header_box,
            self.result_header_box,
        )
        return max(
            box["y"] + box["height"]
            for box in boxes
        )

    # --------------------------------------------------------
    # SCROLL CONTAINER
    # --------------------------------------------------------

    def _mark_scroll_container(self):
        """
        Find the nearest vertically-scrollable ancestor below the Order ID
        column. Fall back to the document scroller.
        """

        result = self.page.evaluate(
            """
            ({x, y, marker}) => {
                document.querySelectorAll(`[${marker}]`).forEach(
                    el => el.removeAttribute(marker)
                );

                let node = document.elementFromPoint(x, y);

                while (node && node !== document.body) {
                    const style = getComputedStyle(node);
                    const scrollable =
                        node.scrollHeight > node.clientHeight + 50 &&
                        (
                            style.overflowY === "auto" ||
                            style.overflowY === "scroll" ||
                            style.overflowY === "overlay"
                        );

                    if (scrollable) {
                        node.setAttribute(marker, "1");
                        return {
                            type: "element",
                            scrollTop: node.scrollTop,
                            scrollHeight: node.scrollHeight,
                            clientHeight: node.clientHeight
                        };
                    }

                    node = node.parentElement;
                }

                const scroller =
                    document.scrollingElement ||
                    document.documentElement;

                scroller.setAttribute(marker, "1");

                return {
                    type: "document",
                    scrollTop: scroller.scrollTop,
                    scrollHeight: scroller.scrollHeight,
                    clientHeight: scroller.clientHeight
                };
            }
            """,
            {
                "x": self.order_x,
                "y": self.header_bottom + 80,
                "marker": self.SCROLL_MARKER,
            },
        )

        self.log(
            "Lark scroll container detected "
            f"({result['type']})."
        )

    def _scroll_info(self) -> dict:
        return self.page.evaluate(
            """
            marker => {
                const el = document.querySelector(`[${marker}]`);
                if (!el) return null;

                return {
                    scrollTop: el.scrollTop,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    maxScroll: Math.max(
                        0,
                        el.scrollHeight - el.clientHeight
                    )
                };
            }
            """,
            self.SCROLL_MARKER,
        )

    def _set_scroll_top(self, value: float):
        self.page.evaluate(
            """
            ({marker, value}) => {
                const el = document.querySelector(`[${marker}]`);
                if (!el) return;
                el.scrollTop = value;
                el.dispatchEvent(
                    new Event("scroll", {bubbles: true})
                );
            }
            """,
            {
                "marker": self.SCROLL_MARKER,
                "value": value,
            },
        )

        self.page.wait_for_timeout(250)

    # --------------------------------------------------------
    # VISIBLE ROW EXTRACTION
    # --------------------------------------------------------

    def _visible_rows(self) -> list[LarkRow]:
        """
        Identify Order ID text in the Order ID column, then sample the
        Decision and Dispute Results cells at the same row Y coordinate.

        This avoids coupling the checker to Lark's frequently-changing
        internal CSS class names.
        """

        raw_rows = self.page.evaluate(
            """
            args => {
                const {
                    orderHeaderX,
                    orderHeaderLeft,
                    orderHeaderWidth,
                    decisionX,
                    resultX,
                    decisionWidth,
                    resultWidth,
                    headerBottom
                } = args;

                const viewportHeight = window.innerHeight;

                function clean(value) {
                    return (value || "")
                        .replace(/\\s+/g, " ")
                        .trim();
                }

                function cellTextAt(x, y, expectedWidth) {
                    let node = document.elementFromPoint(x, y);
                    if (!node) return "";

                    let fallback = clean(
                        node.innerText || node.textContent
                    );

                    for (let depth = 0; node && depth < 9; depth++) {
                        const rect = node.getBoundingClientRect();

                        const widthOk =
                            rect.width >= Math.max(24, expectedWidth * 0.35) &&
                            rect.width <= Math.max(360, expectedWidth * 4);

                        const heightOk =
                            rect.height >= 14 &&
                            rect.height <= 72;

                        if (widthOk && heightOk) {
                            return clean(
                                node.innerText || node.textContent
                            );
                        }

                        node = node.parentElement;
                    }

                    return fallback;
                }

                const elements = [
                    ...document.querySelectorAll("div, span")
                ];

                const candidates = [];

                for (const el of elements) {
                    const text = clean(el.innerText || el.textContent);

                    if (!/^[A-Z0-9]{12,24}$/i.test(text)) {
                        continue;
                    }

                    // Prefer the deepest element that owns this text.
                    let childHasSameText = false;
                    for (const child of el.children) {
                        if (
                            clean(child.innerText || child.textContent) === text
                        ) {
                            childHasSameText = true;
                            break;
                        }
                    }

                    if (childHasSameText) continue;

                    const rect = el.getBoundingClientRect();

                    if (
                        rect.width <= 0 ||
                        rect.height <= 0 ||
                        rect.top <= headerBottom + 2 ||
                        rect.top >= viewportHeight - 4
                    ) {
                        continue;
                    }

                    // Order IDs are left-aligned near the Order ID header.
                    const xClose =
                        Math.abs(rect.left - orderHeaderLeft) <=
                        Math.max(150, orderHeaderWidth * 3);

                    if (!xClose) continue;

                    const y = rect.top + (rect.height / 2);

                    candidates.push({
                        order_id: text.toUpperCase(),
                        decision: cellTextAt(
                            decisionX,
                            y,
                            decisionWidth
                        ),
                        dispute_result: cellTextAt(
                            resultX,
                            y,
                            resultWidth
                        ),
                        y
                    });
                }

                // De-duplicate nested/overlapping candidates.
                const unique = [];
                const seen = new Set();

                candidates
                    .sort((a, b) => a.y - b.y)
                    .forEach(row => {
                        const key =
                            row.order_id + ":" + Math.round(row.y / 3);

                        if (!seen.has(key)) {
                            seen.add(key);
                            unique.push(row);
                        }
                    });

                return unique;
            }
            """,
            {
                "orderHeaderX": self.order_x,
                "orderHeaderLeft": self.order_header_box["x"],
                "orderHeaderWidth": self.order_header_box["width"],
                "decisionX": self.decision_x,
                "resultX": self.result_x,
                "decisionWidth": self.decision_header_box["width"],
                "resultWidth": self.result_header_box["width"],
                "headerBottom": self.header_bottom,
            },
        )

        result = []

        for row in raw_rows:
            order_id = _text(row.get("order_id")).upper()

            if not ORDER_ID_RE.fullmatch(order_id):
                continue

            result.append(
                LarkRow(
                    order_id=order_id,
                    decision=_text(row.get("decision")),
                    dispute_result=_text(
                        row.get("dispute_result")
                    ),
                    y=float(row["y"]),
                )
            )

        return result

    # --------------------------------------------------------
    # COLLECT CHECK QUEUE
    # --------------------------------------------------------

    def collect_pending_disputes(self) -> list[str]:
        """
        Collect unique Order IDs where:
            Decision contains "Disputed"
            Dispute Results is blank

        Existing Approved/Rejected records are ignored.
        """

        self.log(
            "Scanning Lark for disputed records "
            "with blank Dispute Results..."
        )

        self._set_scroll_top(0)

        pending = []
        seen_pending = set()

        last_scroll = -1
        no_progress_count = 0

        while True:
            rows = self._visible_rows()

            for row in rows:
                decision = row.decision.lower()
                result = row.dispute_result.strip()

                if "disputed" not in decision:
                    continue

                if result in FINAL_LARK_RESULTS:
                    continue

                # Only blank result cells are eligible.
                # If Lark contains some other text, do not overwrite it.
                if result:
                    continue

                if row.order_id not in seen_pending:
                    seen_pending.add(row.order_id)
                    pending.append(row.order_id)

            info = self._scroll_info()

            if not info:
                break

            top = float(info["scrollTop"])
            maximum = float(info["maxScroll"])
            client = float(info["clientHeight"])

            if maximum <= 0 or top >= maximum - 3:
                break

            step = max(300, client * 0.78)
            next_top = min(maximum, top + step)

            if next_top <= top + 1 or top == last_scroll:
                no_progress_count += 1
            else:
                no_progress_count = 0

            if no_progress_count >= 3:
                break

            last_scroll = top
            self._set_scroll_top(next_top)

        self._set_scroll_top(0)

        self.log(
            f"Lark queue collected: {len(pending)} "
            "pending dispute(s)."
        )

        return pending

    # --------------------------------------------------------
    # UPDATE LARK CELLS
    # --------------------------------------------------------

    def _choose_single_select_value(
        self,
        y: float,
        value: str,
    ) -> bool:
        """
        Edit the Dispute Results single-select cell.

        Strategy:
        1. Click the target cell.
        2. Press Enter to enter cell edit mode.
        3. Prefer a visible role=option exact match.
        4. Otherwise type the value and press Enter.
        """

        self.page.mouse.click(
            self.result_x,
            y,
        )
        self.page.wait_for_timeout(150)

        self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(200)

        # Preferred path: click a real dropdown option.
        try:
            options = self.page.get_by_role(
                "option",
                name=value,
                exact=True,
            )

            for index in range(options.count() - 1, -1, -1):
                option = options.nth(index)

                if option.is_visible():
                    option.click()
                    self.page.wait_for_timeout(350)
                    return True
        except Exception:
            pass

        # Generic Lark-grid fallback.
        try:
            self.page.keyboard.type(
                value,
                delay=35,
            )
            self.page.wait_for_timeout(150)
            self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(400)
            return True
        except Exception:
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass

            return False

    def apply_updates(
        self,
        updates: dict[str, str],
    ) -> dict:
        """
        Fill blank Dispute Results cells for matching Order IDs.

        Existing Approved/Rejected values are never overwritten.
        """

        if not updates:
            return {
                "updated": 0,
                "already": 0,
                "conflicts": [],
                "not_found": [],
            }

        self.log(
            f"Applying {len(updates)} resolved dispute result(s) "
            "to Lark..."
        )

        self._set_scroll_top(0)

        unresolved = set(updates)
        updated_orders = set()
        already_orders = set()
        conflicts = []

        last_scroll = -1
        no_progress_count = 0

        while True:
            rows = self._visible_rows()

            for row in rows:
                if row.order_id not in unresolved:
                    continue

                wanted = updates[row.order_id]
                current = row.dispute_result.strip()

                if current == wanted:
                    already_orders.add(row.order_id)
                    unresolved.discard(row.order_id)
                    continue

                if current in FINAL_LARK_RESULTS:
                    conflicts.append(
                        (
                            row.order_id,
                            current,
                            wanted,
                        )
                    )
                    unresolved.discard(row.order_id)
                    continue

                if current:
                    # Never overwrite unexpected content.
                    conflicts.append(
                        (
                            row.order_id,
                            current,
                            wanted,
                        )
                    )
                    unresolved.discard(row.order_id)
                    continue

                self.log(
                    f"Lark update: {row.order_id} -> {wanted}"
                )

                success = self._choose_single_select_value(
                    y=row.y,
                    value=wanted,
                )

                if not success:
                    self.log(
                        f"WARNING: could not edit Lark cell "
                        f"for {row.order_id}."
                    )
                    continue

                # Re-read the visible grid to verify the saved result.
                self.page.wait_for_timeout(300)

                verified = False

                for fresh_row in self._visible_rows():
                    if fresh_row.order_id != row.order_id:
                        continue

                    if fresh_row.dispute_result.strip() == wanted:
                        verified = True
                        break

                if verified:
                    updated_orders.add(row.order_id)
                    unresolved.discard(row.order_id)
                else:
                    self.log(
                        f"WARNING: Lark update for {row.order_id} "
                        "could not be verified. It was not counted as saved."
                    )

            if not unresolved:
                break

            info = self._scroll_info()

            if not info:
                break

            top = float(info["scrollTop"])
            maximum = float(info["maxScroll"])
            client = float(info["clientHeight"])

            if maximum <= 0 or top >= maximum - 3:
                break

            next_top = min(
                maximum,
                top + max(300, client * 0.78),
            )

            if next_top <= top + 1 or top == last_scroll:
                no_progress_count += 1
            else:
                no_progress_count = 0

            if no_progress_count >= 3:
                break

            last_scroll = top
            self._set_scroll_top(next_top)

        self._set_scroll_top(0)

        return {
            "updated": len(updated_orders),
            "already": len(already_orders),
            "conflicts": conflicts,
            "not_found": sorted(unresolved),
        }


# ============================================================
# SHOPEE CHECKER
# ============================================================

class ShopeeDisputeChecker:

    def __init__(self, page, log_callback=None):
        self.page = page
        self.log_callback = log_callback

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)
        print(message)

    def open(self):
        if "/portal/sale/returnrefundcancel" not in self.page.url:
            self.log("Opening Shopee Return/Refund/Cancel...")
            self.page.goto(
                SHOPEE_RETURN_URL,
                wait_until="domcontentloaded",
                timeout=SLOW_TIMEOUT,
            )

        panel = self.page.locator(
            ".advance-filter-container"
        )

        panel.wait_for(
            state="attached",
            timeout=SLOW_TIMEOUT,
        )

    def check_order(self, order_id: str) -> tuple[str, str]:
        """
        Returns:
            (Shopee Request Status, mapped Lark result)

        mapped Lark result is blank for unresolved/unknown statuses.
        """

        panel = self.page.locator(
            ".advance-filter-container"
        )

        search = panel.locator(
            f'input[placeholder="{SHOPEE_SEARCH_PLACEHOLDER}"]'
        )

        search.wait_for(
            state="visible",
            timeout=DEFAULT_TIMEOUT,
        )

        search.fill(order_id)

        panel.get_by_role(
            "button",
            name="Apply",
            exact=True,
        ).click()

        matching_row = self.page.locator(
            "a.return-row-item"
        ).filter(
            has_text=order_id
        ).first

        try:
            matching_row.wait_for(
                state="attached",
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception:
            return "Not Found", ""

        # Safety check against the exact Order ID in the row.
        found_order = _text(
            matching_row.locator(
                ".order-id .id-content"
            ).inner_text()
        )

        if found_order != order_id:
            return (
                f"Wrong Record: {found_order}",
                "",
            )

        status_cell = matching_row.locator(
            ".item-request-status"
        )

        try:
            raw_status = status_cell.inner_text().strip()
        except Exception:
            return "Status Not Found", ""

        lines = _normalize_lines(raw_status)

        # Prefer the explicit "Dispute ..." status line.
        status = next(
            (
                line
                for line in lines
                if line.lower().startswith("dispute ")
            ),
            lines[0] if lines else "",
        )

        mapped = SHOPEE_STATUS_MAP.get(
            status,
            "",
        )

        return status, mapped


# ============================================================
# CONTROLLER
# ============================================================

class DisputeCheckerController:

    def __init__(
        self,
        browser: BrowserManager,
        log_callback=None,
    ):
        self.browser = browser
        self.log_callback = log_callback

    def log(self, message: str):
        if self.log_callback:
            self.log_callback(message)
        print(message)

    def _context(self):
        context = getattr(
            self.browser,
            "context",
            None,
        )

        if not context:
            raise RuntimeError(
                "Playwright browser context is unavailable."
            )

        return context

    def _get_or_open_page(
        self,
        url_contains: str,
        open_url: str,
    ):
        context = self._context()

        for page in context.pages:
            if page.is_closed():
                continue

            if url_contains in page.url:
                return page

        page = context.new_page()
        page.goto(
            open_url,
            wait_until="domcontentloaded",
            timeout=SLOW_TIMEOUT,
        )

        return page

    def _lark_page(self):
        return self._get_or_open_page(
            "Cp8ewHPjFiKkTakxzBglPnbqgMe",
            LARK_RESULTS_URL,
        )

    def _shopee_page(self):
        # Reuse BrowserManager's normal Shopee return page when available.
        getter = getattr(
            self.browser,
            "get_shopee_return_page",
            None,
        )

        if getter:
            try:
                page = getter()
                if page:
                    return page
            except Exception:
                pass

        return self._get_or_open_page(
            "/portal/sale/returnrefundcancel",
            SHOPEE_RETURN_URL,
        )

    def run(
        self,
        *,
        update_lark: bool = True,
    ) -> list[CheckResult]:

        lark_page = self._lark_page()
        lark = LarkResultsView(
            lark_page,
            log_callback=self.log_callback,
        )

        lark.open()

        order_ids = lark.collect_pending_disputes()

        if not order_ids:
            self.log(
                "No pending disputed records with blank "
                "Dispute Results were found."
            )
            return []

        shopee_page = self._shopee_page()
        shopee = ShopeeDisputeChecker(
            shopee_page,
            log_callback=self.log_callback,
        )

        shopee.open()
        shopee_page.bring_to_front()

        results = []
        updates = {}

        total = len(order_ids)

        for index, order_id in enumerate(
            order_ids,
            start=1,
        ):
            self.log(
                f"[{index}/{total}] Checking {order_id}..."
            )

            try:
                status, mapped = shopee.check_order(
                    order_id
                )

                if mapped:
                    updates[order_id] = mapped
                    action = (
                        f"Ready -> {mapped}"
                        if update_lark
                        else f"Dry Run -> {mapped}"
                    )
                else:
                    action = "No final dispute result; skipped"

                results.append(
                    CheckResult(
                        order_id=order_id,
                        shopee_status=status,
                        lark_result=mapped,
                        action=action,
                    )
                )

                self.log(
                    f"{order_id}: {status or 'Unknown'}"
                    + (
                        f" -> {mapped}"
                        if mapped
                        else " -> no Lark change"
                    )
                )

            except Exception as error:
                results.append(
                    CheckResult(
                        order_id=order_id,
                        shopee_status="ERROR",
                        lark_result="",
                        action="Skipped",
                        detail=str(error),
                    )
                )

                self.log(
                    f"ERROR checking {order_id}: {error}"
                )

        if update_lark and updates:
            lark_page.bring_to_front()
            lark.open()

            update_summary = lark.apply_updates(
                updates
            )

            self.log(
                "Lark update summary: "
                f"{update_summary['updated']} updated, "
                f"{update_summary['already']} already correct, "
                f"{len(update_summary['conflicts'])} conflict(s), "
                f"{len(update_summary['not_found'])} not found."
            )

            for order_id, current, wanted in update_summary[
                "conflicts"
            ]:
                self.log(
                    f"CONFLICT {order_id}: "
                    f"Lark already has {current!r}; "
                    f"Shopee maps to {wanted!r}. "
                    "No overwrite performed."
                )

            for order_id in update_summary[
                "not_found"
            ]:
                self.log(
                    f"WARNING: could not locate/update "
                    f"{order_id} in Lark."
                )

        return results


# ============================================================
# REPORT
# ============================================================

def write_report(
    results: list[CheckResult],
) -> Path:

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    path = Path.cwd() / (
        f"dispute_checker_report_{stamp}.csv"
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.writer(file)

        writer.writerow(
            [
                "Order ID",
                "Shopee Status",
                "Lark Result",
                "Action",
                "Detail",
            ]
        )

        for item in results:
            writer.writerow(
                [
                    item.order_id,
                    item.shopee_status,
                    item.lark_result,
                    item.action,
                    item.detail,
                ]
            )

    return path


# ============================================================
# GUI
# ============================================================

class DisputeCheckerApp(tk.Tk):

    def __init__(self):
        super().__init__()

        self.browser = BrowserManager()
        self.controller = DisputeCheckerController(
            self.browser,
            log_callback=self.log,
        )

        self.title(
            "Makerlab Dispute Result Checker"
        )
        self.geometry(
            "900x650"
        )
        self.minsize(
            760,
            520,
        )

        self.update_lark_var = tk.BooleanVar(
            value=True
        )

        self._create_gui()

        self.after(
            300,
            self.start_browser,
        )

        self.protocol(
            "WM_DELETE_WINDOW",
            self.on_close,
        )

    def _create_gui(self):
        frame = ttk.Frame(
            self,
            padding=18,
        )
        frame.pack(
            fill="both",
            expand=True,
        )

        ttk.Label(
            frame,
            text="Makerlab Dispute Result Checker",
            font=("Segoe UI", 17, "bold"),
        ).pack(
            anchor="w",
        )

        ttk.Label(
            frame,
            text=(
                "Lark pending disputes -> Shopee status check "
                "-> update Dispute Results"
            ),
        ).pack(
            anchor="w",
            pady=(4, 14),
        )

        options = ttk.Frame(
            frame
        )
        options.pack(
            fill="x",
            pady=(0, 10),
        )

        ttk.Checkbutton(
            options,
            text=(
                "Update Lark automatically "
                "(uncheck for dry run)"
            ),
            variable=self.update_lark_var,
        ).pack(
            side="left",
        )

        actions = ttk.Frame(
            frame
        )
        actions.pack(
            fill="x",
            pady=(0, 12),
        )

        self.run_button = ttk.Button(
            actions,
            text="Check Dispute Results",
            command=self.run_checker,
            state="disabled",
        )
        self.run_button.pack(
            side="left",
        )

        self.status_label = ttk.Label(
            actions,
            text="Starting browser...",
        )
        self.status_label.pack(
            side="left",
            padx=(14, 0),
        )

        ttk.Label(
            frame,
            text="Activity Log:",
        ).pack(
            anchor="w",
            pady=(4, 5),
        )

        self.log_text = tk.Text(
            frame,
            wrap="word",
            height=26,
        )
        self.log_text.pack(
            fill="both",
            expand=True,
        )

        scroll = ttk.Scrollbar(
            self.log_text,
            command=self.log_text.yview,
        )
        self.log_text.configure(
            yscrollcommand=scroll.set
        )

    def log(self, message: str):
        timestamp = datetime.now().strftime(
            "%H:%M:%S"
        )

        self.log_text.insert(
            tk.END,
            f"[{timestamp}] {message}\n",
        )

        self.log_text.see(
            tk.END
        )

        self.status_label.config(
            text=message
        )

        self.update_idletasks()

    def start_browser(self):
        try:
            self.log(
                "Starting Playwright browser..."
            )

            self.browser.start()

            self.run_button.config(
                state="normal",
            )

            self.log(
                "Browser ready."
            )

        except Exception as error:
            self.log(
                f"Browser startup failed: {error}"
            )

            messagebox.showerror(
                "Browser Error",
                str(error),
            )

    def run_checker(self):
        self.run_button.config(
            state="disabled",
        )

        try:
            results = self.controller.run(
                update_lark=self.update_lark_var.get(),
            )

            if results:
                report_path = write_report(
                    results
                )

                resolved = sum(
                    1
                    for item in results
                    if item.lark_result
                )

                self.log(
                    f"Finished. {len(results)} checked, "
                    f"{resolved} final result(s) detected."
                )

                self.log(
                    f"Audit report: {report_path}"
                )

                messagebox.showinfo(
                    "Dispute Check Complete",
                    (
                        f"Checked: {len(results)}\n"
                        f"Final results detected: {resolved}\n\n"
                        f"Report:\n{report_path}"
                    ),
                )

            else:
                messagebox.showinfo(
                    "Dispute Check Complete",
                    "No pending dispute records were found.",
                )

        except Exception as error:
            self.log(
                f"Checker failed: {error}"
            )

            messagebox.showerror(
                "Dispute Checker Error",
                str(error),
            )

        finally:
            self.run_button.config(
                state="normal",
            )

    def on_close(self):
        try:
            self.browser.stop()
        finally:
            self.destroy()


if __name__ == "__main__":
    app = DisputeCheckerApp()
    app.mainloop()
