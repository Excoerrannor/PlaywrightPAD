import copy
import tkinter as tk
from tkinter import ttk, messagebox

from browser_manager import BrowserManager
from shopee import (
    get_order_id,
    get_returned_products,
    get_return_case_data,
)
from odoo import create_odoo_tickets
from lark import file_lark_returns


ODOO_TAGS = [
    "Change of Mind (Sealed)",
    "Change of Mind (Unsealed)",
    "Consultation",
    "Damaged / Defective Item",
    "For Repair",
    "Lost / Missing Item",
    "Others (Refund) e.g Shipping Fee etc.",
]

CLASSIFICATIONS = [
    "New",
    "Unsealed",
    "Defective",
    "Wrong Item",
    "Missing Item",
]

DECISIONS = [
    "Refunded",
    "Disputed",
    "Replaced",
]

RETURN_STATUSES = [
    "Returned",
    "Not Returned",
]

GRADES = [
    "A",
    "B",
    "C",
    "D",
]


class ReturnProcessorApp(tk.Tk):

    def __init__(self):
        super().__init__()

        self.browser = BrowserManager()

        self.current_order_page = None
        self.current_order_id = None
        self.shopee_return_page = None
        self.return_case = None

        # Each dictionary now contains the item's own decisions.
        self.returned_products = []

        # Confirmation flag. The actual decisions live per item.
        self.case_decision = None

        # Odoo now returns one ticket containing one or more stock returns.
        self.odoo_results = None
        self.lark_results = []

        # In-place table editor.
        self.table_editor = None
        self.table_edit_item = None
        self.table_edit_column = None
        self.table_edit_original = None

        self.title("Makerlab Return Processor")
        self.geometry("1380x930")
        self.minsize(1050, 760)

        self.create_gui()

        self.after(300, self.start_browser)
        self.protocol(
            "WM_DELETE_WINDOW",
            self.on_close,
        )

    # =========================================================
    # GUI
    # =========================================================

    def create_gui(self):

        ttk.Label(
            self,
            text="Makerlab Return Processor",
            font=("Segoe UI", 18, "bold"),
        ).pack(
            pady=(18, 4),
        )

        ttk.Label(
            self,
            text=(
                "One Shopee order = one Odoo ticket. "
                "Each returned item can have its own amount and decision."
            ),
        ).pack(
            pady=(0, 14),
        )

        main_frame = ttk.Frame(
            self,
            padding=18,
        )
        main_frame.pack(
            fill="both",
            expand=True,
        )

        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=0)
        main_frame.rowconfigure(5, weight=1)

        # -----------------------------------------------------
        # Shopee Order
        # -----------------------------------------------------

        ttk.Label(
            main_frame,
            text="Shopee Order Link:",
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 5),
        )

        self.order_url_entry = ttk.Entry(
            main_frame,
        )
        self.order_url_entry.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 10),
        )
        self.order_url_entry.bind(
            "<Return>",
            lambda _event: self.open_order_from_url(),
        )

        self.open_order_button = ttk.Button(
            main_frame,
            text="Open & Load Order",
            command=self.open_order_from_url,
        )
        self.open_order_button.grid(
            row=1,
            column=1,
            padx=(10, 0),
            pady=(0, 10),
        )

        ttk.Separator(
            main_frame,
            orient="horizontal",
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 14),
        )

        # -----------------------------------------------------
        # Order Summary
        # -----------------------------------------------------

        summary = ttk.Frame(
            main_frame,
        )
        summary.grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 14),
        )
        summary.columnconfigure(0, weight=1)
        summary.columnconfigure(1, weight=1)

        ttk.Label(
            summary,
            text="Order ID:",
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            summary,
            text="Shopee Total Refund:",
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(30, 0),
        )

        self.order_id_label = ttk.Label(
            summary,
            text="Not loaded",
            font=("Segoe UI", 13, "bold"),
        )
        self.order_id_label.grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 0),
        )

        self.product_value_label = ttk.Label(
            summary,
            text="Not loaded",
            font=("Segoe UI", 13, "bold"),
        )
        self.product_value_label.grid(
            row=1,
            column=1,
            sticky="w",
            padx=(30, 0),
            pady=(4, 0),
        )

        # -----------------------------------------------------
        # Returned Products Table
        # -----------------------------------------------------

        ttk.Label(
            main_frame,
            text=(
                "Returned Items — double-click SKU, QTY, or Amount to edit. "
                "The same SKU may appear on multiple rows for different handling."
            ),
        ).grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 5),
        )

        table_frame = ttk.Frame(
            main_frame,
        )
        table_frame.grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 14),
        )
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        columns = (
            "sku",
            "quantity",
            "amount",
            "classification",
            "decision",
            "status",
            "grade",
            "odoo_tag",
        )

        self.products_table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            height=7,
            selectmode="browse",
        )

        headings = {
            "sku": "SKU",
            "quantity": "QTY",
            "amount": "Amount",
            "classification": "Classification",
            "decision": "Decision",
            "status": "Status",
            "grade": "Grade",
            "odoo_tag": "Odoo Tag",
        }

        widths = {
            "sku": 120,
            "quantity": 60,
            "amount": 90,
            "classification": 115,
            "decision": 95,
            "status": 95,
            "grade": 60,
            "odoo_tag": 230,
        }

        for column in columns:
            self.products_table.heading(
                column,
                text=headings[column],
            )
            self.products_table.column(
                column,
                width=widths[column],
                minwidth=55,
                anchor=(
                    "center"
                    if column in {"quantity", "amount", "grade"}
                    else "w"
                ),
            )

        self.products_table.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        hscroll = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.products_table.xview,
        )
        hscroll.grid(
            row=1,
            column=0,
            sticky="ew",
        )
        self.products_table.configure(
            xscrollcommand=hscroll.set,
        )

        self.products_table.bind(
            "<<TreeviewSelect>>",
            self.on_product_selected,
        )
        self.products_table.bind(
            "<Double-1>",
            self.begin_table_edit,
        )
        self.products_table.bind(
            "<Delete>",
            lambda _event: self.remove_selected_item(),
        )

        item_list_actions = ttk.Frame(
            table_frame,
        )
        item_list_actions.grid(
            row=2,
            column=0,
            sticky="e",
            pady=(8, 0),
        )

        self.add_item_button = ttk.Button(
            item_list_actions,
            text="Add Item",
            command=self.add_return_item,
        )
        self.add_item_button.pack(
            side="left",
        )

        self.remove_item_button = ttk.Button(
            item_list_actions,
            text="Remove Selected",
            command=self.remove_selected_item,
            state="disabled",
        )
        self.remove_item_button.pack(
            side="left",
            padx=(8, 0),
        )

        # -----------------------------------------------------
        # Selected Item Decision
        # -----------------------------------------------------

        self.item_frame = ttk.LabelFrame(
            main_frame,
            text="Selected Item Decision",
            padding=12,
        )
        self.item_frame.grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 12),
        )

        for column in (1, 3, 5):
            self.item_frame.columnconfigure(
                column,
                weight=1,
            )

        # Row 0: Amount / Classification / Tag
        ttk.Label(
            self.item_frame,
            text="Amount:",
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 6),
            pady=4,
        )

        self.amount_entry = ttk.Entry(
            self.item_frame,
            state="disabled",
        )
        self.amount_entry.grid(
            row=0,
            column=1,
            sticky="ew",
            pady=4,
        )

        ttk.Label(
            self.item_frame,
            text="Classification:",
        ).grid(
            row=0,
            column=2,
            sticky="w",
            padx=(16, 6),
            pady=4,
        )

        self.classification_combo = ttk.Combobox(
            self.item_frame,
            values=CLASSIFICATIONS,
            state="disabled",
        )
        self.classification_combo.grid(
            row=0,
            column=3,
            sticky="ew",
            pady=4,
        )
        self.classification_combo.bind(
            "<<ComboboxSelected>>",
            self.on_classification_changed,
        )

        ttk.Label(
            self.item_frame,
            text="Odoo Tag:",
        ).grid(
            row=0,
            column=4,
            sticky="w",
            padx=(16, 6),
            pady=4,
        )

        self.odoo_tag_combo = ttk.Combobox(
            self.item_frame,
            values=ODOO_TAGS,
            state="disabled",
        )
        self.odoo_tag_combo.grid(
            row=0,
            column=5,
            sticky="ew",
            pady=4,
        )

        # Row 1: Decision / Status / Grade
        ttk.Label(
            self.item_frame,
            text="Decision:",
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 6),
            pady=4,
        )

        self.decision_combo = ttk.Combobox(
            self.item_frame,
            values=DECISIONS,
            state="disabled",
        )
        self.decision_combo.grid(
            row=1,
            column=1,
            sticky="ew",
            pady=4,
        )

        ttk.Label(
            self.item_frame,
            text="Status:",
        ).grid(
            row=1,
            column=2,
            sticky="w",
            padx=(16, 6),
            pady=4,
        )

        self.return_status_combo = ttk.Combobox(
            self.item_frame,
            values=RETURN_STATUSES,
            state="disabled",
        )
        self.return_status_combo.grid(
            row=1,
            column=3,
            sticky="ew",
            pady=4,
        )

        ttk.Label(
            self.item_frame,
            text="Grade:",
        ).grid(
            row=1,
            column=4,
            sticky="w",
            padx=(16, 6),
            pady=4,
        )

        self.grade_combo = ttk.Combobox(
            self.item_frame,
            values=GRADES,
            state="disabled",
        )
        self.grade_combo.grid(
            row=1,
            column=5,
            sticky="ew",
            pady=4,
        )

        # Remarks
        ttk.Label(
            self.item_frame,
            text="Remarks:",
        ).grid(
            row=2,
            column=0,
            sticky="nw",
            padx=(0, 6),
            pady=4,
        )

        self.remarks_text = tk.Text(
            self.item_frame,
            height=3,
            wrap="word",
            state="disabled",
        )
        self.remarks_text.grid(
            row=2,
            column=1,
            columnspan=5,
            sticky="ew",
            pady=4,
        )

        item_actions = ttk.Frame(
            self.item_frame,
        )
        item_actions.grid(
            row=3,
            column=0,
            columnspan=6,
            sticky="e",
            pady=(10, 0),
        )

        self.save_item_button = ttk.Button(
            item_actions,
            text="Save Item Decision",
            command=self.save_selected_item,
            state="disabled",
        )
        self.save_item_button.pack(
            side="left",
        )

        self.apply_all_button = ttk.Button(
            item_actions,
            text="Apply Decision to All Items",
            command=self.apply_selected_decision_to_all,
            state="disabled",
        )
        self.apply_all_button.pack(
            side="left",
            padx=(8, 0),
        )

        self.confirm_decision_button = ttk.Button(
            item_actions,
            text="Confirm All Items",
            command=self.confirm_decision,
            state="disabled",
        )
        self.confirm_decision_button.pack(
            side="left",
            padx=(8, 0),
        )

        self.create_odoo_button = ttk.Button(
            item_actions,
            text="Create Odoo Ticket / Return(s)",
            command=self.create_odoo_ticket,
            state="disabled",
        )
        self.create_odoo_button.pack(
            side="left",
            padx=(8, 0),
        )

        self.file_lark_button = ttk.Button(
            item_actions,
            text="File Lark Form(s)",
            command=self.file_lark_form,
            state="disabled",
        )
        self.file_lark_button.pack(
            side="left",
            padx=(8, 0),
        )

        # -----------------------------------------------------
        # Status / Results
        # -----------------------------------------------------

        ttk.Label(
            main_frame,
            text="Status:",
        ).grid(
            row=7,
            column=0,
            columnspan=2,
            sticky="w",
        )

        self.status_label = ttk.Label(
            main_frame,
            text="Starting...",
            wraplength=1280,
        )
        self.status_label.grid(
            row=8,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(3, 8),
        )

        self.odoo_result_frame = ttk.LabelFrame(
            main_frame,
            text="Odoo / Lark Result",
            padding=10,
        )
        self.odoo_result_frame.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="ew",
        )

        self.odoo_result_label = ttk.Label(
            self.odoo_result_frame,
            text="No Odoo return completed yet.",
            wraplength=1280,
            justify="left",
        )
        self.odoo_result_label.pack(
            fill="x",
            anchor="w",
        )

    # =========================================================
    # BROWSER / SHOPEE
    # =========================================================

    def start_browser(self):
        self.set_status(
            "Opening Playwright browser..."
        )

        try:
            self.browser.start()
            self.set_status(
                "Browser ready. Paste a Shopee Order link."
            )
        except Exception as error:
            self.set_status(
                "Could not start browser."
            )
            messagebox.showerror(
                "Browser Error",
                str(error),
            )

    def open_order_from_url(self):
        url = self.order_url_entry.get().strip()

        if not url:
            messagebox.showwarning(
                "Missing Order Link",
                "Paste the Shopee Order page link first.",
            )
            return

        if "/portal/sale/order/" not in url:
            messagebox.showwarning(
                "Invalid Order Link",
                "Please paste a Shopee Order page link.",
            )
            return

        try:
            self.open_order_button.config(
                state="disabled",
            )
            self.set_status(
                "Opening Shopee Order..."
            )

            page = self.browser.open_shopee_order(
                url
            )
            self.current_order_page = page

            self.process_order_page(
                page
            )

        except Exception as error:
            self.set_status(
                "Could not open Shopee Order."
            )
            messagebox.showerror(
                "Open Order Error",
                str(error),
            )

        finally:
            self.open_order_button.config(
                state="normal",
            )

    def process_order_page(self, page):
        self.reset_case()

        self.order_id_label.config(
            text="Loading...",
        )
        self.product_value_label.config(
            text="Loading...",
        )

        self.set_status(
            "Reading Shopee Order ID..."
        )

        order_id = get_order_id(
            page
        )
        self.current_order_id = order_id
        self.order_id_label.config(
            text=order_id,
        )

        self.set_status(
            "Reading returned products..."
        )

        raw_products = get_returned_products(
            page
        )

        self.set_status(
            "Searching Shopee Return List..."
        )

        return_case = None

        try:
            return_page = self.browser.get_shopee_return_page()
            self.shopee_return_page = return_page

            if return_page:
                return_case = get_return_case_data(
                    return_page,
                    order_id,
                )
        except Exception as error:
            print(
                "\nRETURN CASE LOOKUP FAILED:"
            )
            print(
                error
            )

        self.return_case = return_case

        if return_case:
            self.product_value_label.config(
                text=return_case["refund_text"],
            )
        else:
            self.product_value_label.config(
                text="Not found",
            )

        # Build item-level records.
        # Shopee now supplies:
        #   unit_price
        #   returned quantity
        #   amount = unit_price * returned quantity
        #
        # Amount remains editable in the GUI for exceptional cases.
        items = []

        for product in raw_products:
            amount = product.get(
                "amount",
                "",
            )

            items.append({
                "sku": str(product["sku"]).strip().upper(),
                "quantity": int(product["quantity"]),
                "unit_price": product.get(
                    "unit_price",
                    "",
                ),
                "amount": amount,
                "classification": "",
                "odoo_tag": "",
                "decision": "Disputed",
                "status": "Returned",
                "platform": "Shopee",
                "grade": "",
                "remarks": "",
            })

        self.returned_products = items
        self.populate_products_table()

        self.set_item_controls_enabled(
            bool(items)
        )

        if items:
            first_iid = self.products_table.get_children()[0]
            self.products_table.selection_set(
                first_iid
            )
            self.products_table.focus(
                first_iid
            )
            self.load_selected_item()

        self.confirm_decision_button.config(
            state=(
                "normal"
                if items
                else "disabled"
            ),
        )

        amount_note = (
            "Individual amounts calculated from Shopee Unit Price × Return QTY."
            if items
            else "No returned items found."
        )

        self.set_status(
            (
                f"Order loaded: {order_id} | "
                f"{len(items)} returned item(s). "
                f"{amount_note}"
            )
        )

    # =========================================================
    # ITEM TABLE / EDITING
    # =========================================================

    def reset_case(self):
        self.cancel_table_edit()

        self.current_order_id = None
        self.return_case = None
        self.returned_products = []
        self.case_decision = None
        self.odoo_results = None
        self.lark_results = []

        self.clear_products_table()
        self.clear_item_editor()
        self.set_item_controls_enabled(
            False
        )

        self.create_odoo_button.config(
            state="disabled",
        )
        self.file_lark_button.config(
            state="disabled",
        )
        self.odoo_result_label.config(
            text="No Odoo return completed yet.",
        )

        self.remove_item_button.config(
            state="disabled",
        )

    def clear_products_table(self):
        for iid in self.products_table.get_children():
            self.products_table.delete(
                iid
            )

    def populate_products_table(self):
        self.clear_products_table()

        for index, item in enumerate(self.returned_products):
            self.products_table.insert(
                "",
                "end",
                iid=str(index),
                values=self.item_table_values(
                    item
                ),
            )

    @staticmethod
    def item_table_values(item):
        amount = item.get(
            "amount",
            "",
        )

        if amount != "":
            try:
                amount = f"{float(amount):.2f}"
            except (TypeError, ValueError):
                pass

        return (
            item.get("sku", ""),
            item.get("quantity", ""),
            amount,
            item.get("classification", ""),
            item.get("decision", ""),
            item.get("status", ""),
            item.get("grade", ""),
            item.get("odoo_tag", ""),
        )

    def refresh_product_row(self, index):
        iid = str(index)

        if self.products_table.exists(
            iid
        ):
            self.products_table.item(
                iid,
                values=self.item_table_values(
                    self.returned_products[index]
                ),
            )

    def on_product_selected(self, _event=None):
        self.remove_item_button.config(
            state=(
                "normal"
                if self.products_table.selection()
                else "disabled"
            ),
        )

        self.load_selected_item()

    def selected_item_index(self):
        selection = self.products_table.selection()

        if not selection:
            return None

        return int(
            selection[0]
        )

    def load_selected_item(self):
        index = self.selected_item_index()

        if index is None:
            return

        item = self.returned_products[index]

        self.amount_entry.config(
            state="normal",
        )
        self.amount_entry.delete(
            0,
            tk.END,
        )
        self.amount_entry.insert(
            0,
            (
                f"{float(item['amount']):.2f}"
                if item.get("amount", "") != ""
                else ""
            ),
        )

        self.classification_combo.set(
            item.get("classification", "")
        )
        self.odoo_tag_combo.set(
            item.get("odoo_tag", "")
        )
        self.decision_combo.set(
            item.get("decision", "Disputed")
        )
        self.return_status_combo.set(
            item.get("status", "Returned")
        )
        self.grade_combo.set(
            item.get("grade", "")
        )

        self.remarks_text.config(
            state="normal",
        )
        self.remarks_text.delete(
            "1.0",
            tk.END,
        )
        self.remarks_text.insert(
            "1.0",
            item.get("remarks", ""),
        )

        self.update_grade_state()

    def _ensure_item_list_mutable(self):
        """
        Do not alter the returned-item list after Odoo has already created
        the ticket/return records. That would make the GUI disagree with
        data already committed in Odoo.
        """

        if self.odoo_results:
            messagebox.showwarning(
                "Odoo Already Processed",
                (
                    "This order has already been processed in Odoo.\n\n"
                    "The returned-item list cannot be changed now because "
                    "it would no longer match the Odoo ticket/transfer."
                ),
            )
            return False

        return True

    def add_return_item(self):
        """
        Add a manual returned-item row.

        Defaults:
            QTY      = 1
            Decision = Disputed
            Status   = Returned
            Platform = Shopee

        SKU, Amount, Classification and Odoo Tag must be completed before
        Confirm All Items.
        """

        if not self.current_order_id:
            messagebox.showwarning(
                "No Order Loaded",
                "Load a Shopee Order before adding an item.",
            )
            return

        if not self._ensure_item_list_mutable():
            return

        try:
            self.commit_table_edit()
        except ValueError as error:
            messagebox.showwarning(
                "Invalid Item",
                str(error),
            )
            return

        new_item = {
            "sku": "",
            "quantity": 1,
            "unit_price": "",
            "amount": "",
            "classification": "",
            "odoo_tag": "",
            "decision": "Disputed",
            "status": "Returned",
            "platform": "Shopee",
            "grade": "",
            "remarks": "",
        }

        self.returned_products.append(
            new_item
        )

        new_index = (
            len(self.returned_products) - 1
        )

        self.populate_products_table()

        iid = str(
            new_index
        )

        self.products_table.selection_set(
            iid
        )
        self.products_table.focus(
            iid
        )
        self.products_table.see(
            iid
        )

        self.set_item_controls_enabled(
            True
        )
        self.confirm_decision_button.config(
            state="normal",
        )
        self.remove_item_button.config(
            state="normal",
        )

        self.load_selected_item()
        self.invalidate_confirmation()

        self.set_status(
            (
                "New item added. Double-click its SKU, QTY or Amount "
                "to edit, then set its decision fields below."
            )
        )

    def remove_selected_item(self):
        """
        Remove the selected returned SKU from this order.
        """

        if not self.returned_products:
            return

        if not self._ensure_item_list_mutable():
            return

        try:
            self.commit_table_edit()
        except ValueError as error:
            messagebox.showwarning(
                "Invalid Item",
                str(error),
            )
            return

        index = self.selected_item_index()

        if index is None:
            messagebox.showwarning(
                "No Item Selected",
                "Select an item to remove.",
            )
            return

        item = self.returned_products[index]

        sku = (
            str(item.get("sku", "")).strip()
            or "New Item"
        )

        confirmed = messagebox.askyesno(
            "Remove Returned Item",
            (
                f"Remove {sku} from this return?\n\n"
                "It will not be included in the Odoo ticket/return "
                "or the Lark filing."
            ),
        )

        if not confirmed:
            return

        self.returned_products.pop(
            index
        )

        self.invalidate_confirmation()
        self.populate_products_table()

        if self.returned_products:
            next_index = min(
                index,
                len(self.returned_products) - 1,
            )

            iid = str(
                next_index
            )

            self.products_table.selection_set(
                iid
            )
            self.products_table.focus(
                iid
            )
            self.products_table.see(
                iid
            )

            self.set_item_controls_enabled(
                True
            )
            self.confirm_decision_button.config(
                state="normal",
            )
            self.remove_item_button.config(
                state="normal",
            )

            self.load_selected_item()

        else:
            self.clear_item_editor()
            self.set_item_controls_enabled(
                False
            )
            self.confirm_decision_button.config(
                state="disabled",
            )
            self.create_odoo_button.config(
                state="disabled",
            )
            self.file_lark_button.config(
                state="disabled",
            )
            self.remove_item_button.config(
                state="disabled",
            )

        self.set_status(
            f"Removed {sku} from the returned-item list."
        )

    def begin_table_edit(self, event):

        if not self._ensure_item_list_mutable():
            return

        if self.products_table.identify_region(
            event.x,
            event.y,
        ) != "cell":
            return

        iid = self.products_table.identify_row(
            event.y
        )
        column_id = self.products_table.identify_column(
            event.x
        )

        editable_columns = {
            "#1": "sku",
            "#2": "quantity",
            "#3": "amount",
        }

        if not iid or column_id not in editable_columns:
            return

        self.commit_table_edit()

        bbox = self.products_table.bbox(
            iid,
            column_id,
        )
        if not bbox:
            return

        x, y, width, height = bbox
        column_name = editable_columns[column_id]
        current = self.products_table.set(
            iid,
            column_name,
        )

        editor = ttk.Entry(
            self.products_table,
        )
        editor.place(
            x=x,
            y=y,
            width=width,
            height=height,
        )
        editor.insert(
            0,
            current,
        )
        editor.focus_set()
        editor.selection_range(
            0,
            tk.END,
        )

        self.table_editor = editor
        self.table_edit_item = int(iid)
        self.table_edit_column = column_name
        self.table_edit_original = current

        editor.bind(
            "<Return>",
            lambda _event: self.commit_table_edit(),
        )
        editor.bind(
            "<Escape>",
            lambda _event: self.cancel_table_edit(),
        )

    def commit_table_edit(self):
        if not self.table_editor:
            return

        index = self.table_edit_item
        column = self.table_edit_column
        value = self.table_editor.get().strip()

        if column == "sku":
            value = value.upper()
            if not value:
                raise ValueError(
                    "SKU cannot be blank."
                )

        elif column == "quantity":
            try:
                value = int(value)
            except ValueError as error:
                raise ValueError(
                    "QTY must be a whole number."
                ) from error

            if value <= 0:
                raise ValueError(
                    "QTY must be at least 1."
                )

        elif column == "amount":
            try:
                value = float(value)
            except ValueError as error:
                raise ValueError(
                    "Amount must be a number."
                ) from error

            if value < 0:
                raise ValueError(
                    "Amount cannot be negative."
                )

            value = round(
                value,
                2,
            )

        self.returned_products[index][column] = value

        self.table_editor.destroy()
        self.table_editor = None
        self.table_edit_item = None
        self.table_edit_column = None
        self.table_edit_original = None

        self.refresh_product_row(
            index
        )
        self.invalidate_confirmation()

        if self.selected_item_index() == index:
            self.load_selected_item()

    def cancel_table_edit(self):
        if self.table_editor:
            self.table_editor.destroy()

        self.table_editor = None
        self.table_edit_item = None
        self.table_edit_column = None
        self.table_edit_original = None

    # =========================================================
    # ITEM DECISIONS
    # =========================================================

    def set_item_controls_enabled(self, enabled):
        state = (
            "readonly"
            if enabled
            else "disabled"
        )

        self.classification_combo.config(
            state=state,
        )
        self.odoo_tag_combo.config(
            state=state,
        )
        self.decision_combo.config(
            state=state,
        )
        self.return_status_combo.config(
            state=state,
        )

        self.amount_entry.config(
            state=(
                "normal"
                if enabled
                else "disabled"
            ),
        )
        self.remarks_text.config(
            state=(
                "normal"
                if enabled
                else "disabled"
            ),
        )

        self.save_item_button.config(
            state=(
                "normal"
                if enabled
                else "disabled"
            ),
        )
        self.apply_all_button.config(
            state=(
                "normal"
                if enabled
                else "disabled"
            ),
        )

        if not enabled:
            self.grade_combo.config(
                state="disabled",
            )

    def clear_item_editor(self):
        self.amount_entry.config(
            state="normal",
        )
        self.amount_entry.delete(
            0,
            tk.END,
        )

        self.classification_combo.set("")
        self.odoo_tag_combo.set("")
        self.decision_combo.set("Disputed")
        self.return_status_combo.set("Returned")
        self.grade_combo.set("")

        self.remarks_text.config(
            state="normal",
        )
        self.remarks_text.delete(
            "1.0",
            tk.END,
        )

    def on_classification_changed(self, _event=None):
        self.update_grade_state()

    def update_grade_state(self):
        enabled = (
            str(self.classification_combo.cget("state"))
            != "disabled"
        )

        if (
            enabled
            and self.classification_combo.get()
            == "Unsealed"
        ):
            self.grade_combo.config(
                state="readonly",
            )
        else:
            self.grade_combo.set("")
            self.grade_combo.config(
                state="disabled",
            )

    def read_item_editor(self):
        index = self.selected_item_index()

        if index is None:
            raise ValueError(
                "Select a returned item first."
            )

        item = self.returned_products[index]

        raw_amount = self.amount_entry.get().strip()

        try:
            amount = float(
                raw_amount
            )
        except ValueError as error:
            raise ValueError(
                f"Enter a valid Amount for {item['sku']}."
            ) from error

        if amount < 0:
            raise ValueError(
                "Amount cannot be negative."
            )

        classification = self.classification_combo.get().strip()
        odoo_tag = self.odoo_tag_combo.get().strip()
        decision = self.decision_combo.get().strip()
        status = self.return_status_combo.get().strip()
        grade = self.grade_combo.get().strip()
        remarks = self.remarks_text.get(
            "1.0",
            tk.END,
        ).strip()

        if not classification:
            raise ValueError(
                f"Select Classification for {item['sku']}."
            )
        if not odoo_tag:
            raise ValueError(
                f"Select Odoo Tag for {item['sku']}."
            )
        if not decision:
            raise ValueError(
                f"Select Decision for {item['sku']}."
            )
        if not status:
            raise ValueError(
                f"Select Status for {item['sku']}."
            )
        if classification == "Unsealed" and not grade:
            raise ValueError(
                f"Select Grade for unsealed item {item['sku']}."
            )

        return {
            "amount": round(amount, 2),
            "classification": classification,
            "odoo_tag": odoo_tag,
            "decision": decision,
            "status": status,
            "platform": "Shopee",
            "grade": grade,
            "remarks": remarks,
        }

    def save_selected_item(self):
        try:
            self.commit_table_edit()
            index = self.selected_item_index()

            if index is None:
                raise ValueError(
                    "Select a returned item first."
                )

            changes = self.read_item_editor()

            self.returned_products[index].update(
                changes
            )
            self.refresh_product_row(
                index
            )
            self.invalidate_confirmation()

            self.set_status(
                f"Saved decision for {self.returned_products[index]['sku']}."
            )

        except ValueError as error:
            messagebox.showwarning(
                "Invalid Item Decision",
                str(error),
            )

    def apply_selected_decision_to_all(self):
        try:
            self.commit_table_edit()

            index = self.selected_item_index()
            if index is None:
                raise ValueError(
                    "Select an item first."
                )

            changes = self.read_item_editor()

            # Save the selected item's amount too.
            self.returned_products[index].update(
                changes
            )

            # Only decision-related fields are copied. SKU, QTY and Amount
            # remain unique per returned item.
            copied_fields = (
                "classification",
                "odoo_tag",
                "decision",
                "status",
                "platform",
                "grade",
                "remarks",
            )

            for item in self.returned_products:
                for field in copied_fields:
                    item[field] = changes[field]

            self.populate_products_table()

            # Keep the same selected row after rebuilding.
            iid = str(index)
            if self.products_table.exists(iid):
                self.products_table.selection_set(iid)
                self.products_table.focus(iid)

            self.load_selected_item()
            self.invalidate_confirmation()

            self.set_status(
                "Applied the selected decision to all returned items. "
                "Amounts were left unchanged."
            )

        except ValueError as error:
            messagebox.showwarning(
                "Cannot Apply Decision",
                str(error),
            )

    def validate_all_items(self):
        if not self.returned_products:
            raise ValueError(
                "No returned items are loaded."
            )

        # Duplicate SKUs are intentionally allowed.
        #
        # Example:
        #   MLE03495 | QTY 1 | Unsealed  | Refunded
        #   MLE03495 | QTY 1 | Defective | Refunded
        #
        # These are two physical units of the same SKU that require
        # different Odoo return/QC handling.
        for item in self.returned_products:
            sku = str(item.get("sku", "")).strip().upper()

            if not sku:
                raise ValueError(
                    "SKU cannot be blank."
                )

            try:
                quantity = int(item.get("quantity", 0))
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Invalid QTY for {sku}."
                ) from error

            if quantity <= 0:
                raise ValueError(
                    f"QTY for {sku} must be at least 1."
                )

            try:
                amount = float(item.get("amount", ""))
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Enter the Amount for {sku}."
                ) from error

            if amount < 0:
                raise ValueError(
                    f"Amount for {sku} cannot be negative."
                )

            for field, label in (
                ("classification", "Classification"),
                ("odoo_tag", "Odoo Tag"),
                ("decision", "Decision"),
                ("status", "Status"),
            ):
                if not str(item.get(field, "")).strip():
                    raise ValueError(
                        f"{label} is missing for {sku}."
                    )

            if (
                item["classification"] == "Unsealed"
                and not str(item.get("grade", "")).strip()
            ):
                raise ValueError(
                    f"Grade is required for unsealed item {sku}."
                )

    def confirm_decision(self):
        try:
            self.commit_table_edit()

            # Save the currently selected item editor before confirming all.
            if self.selected_item_index() is not None:
                changes = self.read_item_editor()
                index = self.selected_item_index()
                self.returned_products[index].update(
                    changes
                )
                self.refresh_product_row(
                    index
                )

            self.validate_all_items()

            # Freeze a copy that Odoo/Lark will receive.
            self.returned_products = copy.deepcopy(
                self.returned_products
            )
            self.case_decision = {
                "confirmed": True,
            }

            self.create_odoo_button.config(
                state="normal",
            )
            self.file_lark_button.config(
                state="disabled",
            )

            print(
                "\nCONFIRMED RETURN ITEMS:"
            )
            for item in self.returned_products:
                print(
                    f"{item['sku']} | QTY {item['quantity']} | "
                    f"Amount {item['amount']:.2f} | "
                    f"{item['classification']} | "
                    f"{item['decision']} | {item['odoo_tag']}"
                )

            self.set_status(
                "All item decisions confirmed. Ready for Odoo."
            )

        except ValueError as error:
            messagebox.showwarning(
                "Cannot Confirm Items",
                str(error),
            )

    def invalidate_confirmation(self):
        if self.case_decision is None:
            return

        self.case_decision = None
        self.odoo_results = None
        self.lark_results = []

        self.create_odoo_button.config(
            state="disabled",
        )
        self.file_lark_button.config(
            state="disabled",
        )

        self.odoo_result_label.config(
            text=(
                "Item data changed. Confirm All Items again "
                "before Odoo processing."
            ),
        )

    # =========================================================
    # ODOO
    # =========================================================

    def create_odoo_ticket(self):
        if not self.case_decision:
            messagebox.showwarning(
                "Confirmation Required",
                "Confirm all returned items before creating the Odoo ticket.",
            )
            return

        if not self.browser.context:
            messagebox.showerror(
                "Browser Error",
                "Playwright browser context is unavailable.",
            )
            return

        try:
            self.set_processing_buttons(
                True
            )
            self.set_status(
                "Creating Odoo ticket..."
            )

            self.odoo_results = create_odoo_tickets(
                context=self.browser.context,
                order_id=self.current_order_id,
                returned_products=self.returned_products,
                case_decision=self.case_decision,
                progress_callback=self.set_status,
            )

            lines = [
                "Odoo completed.",
                f"Ticket: {self.odoo_results['ticket_title']}",
                self.odoo_results["ticket_url"],
                (
                    "Product field: "
                    f"{self.odoo_results['product_sku']}"
                ),
                (
                    "Tags: "
                    + ", ".join(self.odoo_results["tags"])
                ),
            ]

            for return_group in self.odoo_results["returns"]:
                item_text = ", ".join(
                    f"{item['sku']}_{item['quantity']}"
                    for item in return_group["items"]
                )

                lines.append(
                    (
                        f"Return #{return_group['return_index']}: "
                        f"{return_group['transfer_id']} | "
                        f"{return_group['classification']} | "
                        f"{return_group['decision']} | {item_text}"
                    )
                )
                lines.append(
                    return_group["transfer_url"]
                )

            self.odoo_result_label.config(
                text="\n".join(lines),
            )

            self.file_lark_button.config(
                state="normal",
            )

            self.set_status(
                (
                    f"Odoo completed: 1 ticket, "
                    f"{len(self.odoo_results['returns'])} return(s). "
                    "Ready for Lark filing."
                )
            )

        except Exception as error:
            self.set_status(
                "Odoo processing failed."
            )
            self.odoo_result_label.config(
                text=(
                    "Odoo processing failed.\n"
                    f"{error}"
                ),
            )
            messagebox.showerror(
                "Odoo Error",
                str(error),
            )

        finally:
            self.set_processing_buttons(
                False
            )

    # =========================================================
    # LARK
    # =========================================================

    def file_lark_form(self):
        if not self.odoo_results:
            messagebox.showwarning(
                "Odoo Required",
                "Complete Odoo processing before filing Lark.",
            )
            return

        try:
            self.set_processing_buttons(
                True
            )
            self.set_status(
                "Filing Lark Item Returns..."
            )

            self.lark_results = file_lark_returns(
                context=self.browser.context,
                order_id=self.current_order_id,
                returned_products=self.returned_products,
                return_case=self.return_case,
                case_decision=self.case_decision,
                odoo_results=self.odoo_results,
                progress_callback=self.set_status,
            )

            lines = [
                self.odoo_result_label.cget("text"),
                "",
                (
                    f"Lark filed {len(self.lark_results)} "
                    "Odoo transfer(s):"
                ),
            ]

            for result in self.lark_results:
                lines.append(
                    (
                        f"{result['transfer_id']} | "
                        f"Decision: {result['decision']} | "
                        f"{result['sku']} | "
                        f"Total QTY {result['quantity']} | "
                        f"Order/Refund Value {result['value']:.2f}"
                    )
                )

            self.odoo_result_label.config(
                text="\n".join(lines),
            )

            self.set_status(
                (
                    f"Lark filing completed: "
                    f"{len(self.lark_results)} Transfer ID(s) filed."
                )
            )

        except Exception as error:
            self.set_status(
                "Lark filing failed."
            )
            messagebox.showerror(
                "Lark Error",
                str(error),
            )

        finally:
            self.set_processing_buttons(
                False
            )

    # =========================================================
    # HELPERS
    # =========================================================

    def set_status(self, text):
        self.status_label.config(
            text=text,
        )
        self.update_idletasks()

    def set_processing_buttons(self, busy):
        if busy:
            self.open_order_button.config(
                state="disabled",
            )
            self.confirm_decision_button.config(
                state="disabled",
            )
            self.create_odoo_button.config(
                state="disabled",
            )
            self.file_lark_button.config(
                state="disabled",
            )
            return

        self.open_order_button.config(
            state="normal",
        )

        if self.returned_products:
            self.confirm_decision_button.config(
                state="normal",
            )

        if self.case_decision:
            self.create_odoo_button.config(
                state="normal",
            )

        if self.odoo_results:
            self.file_lark_button.config(
                state="normal",
            )

    def on_close(self):
        try:
            self.browser.stop()
        finally:
            self.destroy()


if __name__ == "__main__":
    app = ReturnProcessorApp()
    app.mainloop()
