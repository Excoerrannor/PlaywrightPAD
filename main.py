import copy
import tkinter as tk
from tkinter import ttk, messagebox
from browser_manager import BrowserManager
from shopee import (
    get_order_id,
    get_returned_products,
    get_return_case_data,
    get_return_case_by_tracking,
    open_order_from_return_row,
)
from lazada import get_lazada_return_order, suggested_processor_status
from tiktok import get_tiktok_return_order
from odoo import (
    create_odoo_tickets,
    resume_odoo_returns,
    OdooWorkflowPausedError,
)
from lark import file_lark_returns
from workflow_store import WorkflowStore
from history_window import HistoryRecoveryWindow
from ui_theme import (
    apply_theme, RoundedCard, RoundedButton, configure_readonly_text, configure_transfer_entry,
    INK, DEEP_TEAL, MUTED, TEAL_TINT, AMBER, TEAL,
)
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
RETURNED_STATUS = "Returned"
NOT_RETURNED_STATUS = "Not Returned"
DEFAULT_DECISION = "Disputed"
PLATFORMS = ["Shopee", "Lazada", "TikTok"]
SHOPEE_SEARCH_MODES = ["Tracking Number", "Order ID", "Order Link"]
LAZADA_SEARCH_MODES = ["Tracking Number", "Order ID"]
TIKTOK_SEARCH_MODES = ["Tracking Number", "Order ID", "Return Order ID"]

class SelectableValue(ttk.Entry):
    """Read-only Entry that supports selecting/copying order summary values."""

    def __init__(self, master, *, text="", **kwargs):
        self._display_text = tk.StringVar(master=master, value=str(text))
        super().__init__(
            master,
            textvariable=self._display_text,
            state="readonly",
            **kwargs,
        )
        self.bind("<Control-a>", self._select_all)
        self.bind("<Control-A>", self._select_all)
        self._copy_menu = tk.Menu(self, tearoff=False)
        self._copy_menu.add_command(label="Copy", command=self._copy_selection)
        self._copy_menu.add_command(label="Select All", command=self._select_all)
        self.bind("<Button-3>", self._show_copy_menu)

    def configure(self, cnf=None, **kwargs):
        if "text" in kwargs:
            self._display_text.set(str(kwargs.pop("text")))
        return super().configure(cnf, **kwargs)

    config = configure

    def cget(self, key):
        if key == "text":
            return self._display_text.get()
        return super().cget(key)

    def _select_all(self, _event=None):
        self.selection_range(0, tk.END)
        self.icursor(tk.END)
        return "break"

    def _copy_selection(self):
        try:
            selected = self.selection_get()
        except tk.TclError:
            selected = self._display_text.get()
        if selected:
            self.clipboard_clear()
            self.clipboard_append(selected)
            self.update()

    def _show_copy_menu(self, event):
        self.focus_set()
        self._copy_menu.tk_popup(event.x_root, event.y_root)
        self._copy_menu.grab_release()


class HighlightedSelectableValue(tk.Entry):
    """Read-only highlighted Entry for important copyable values."""

    def __init__(self, master, *, text="", **kwargs):
        self._display_text = tk.StringVar(master=master, value=str(text))
        kwargs.setdefault("relief", "solid")
        kwargs.setdefault("bd", 1)
        kwargs.setdefault("bg", "#FFF2CC")
        kwargs.setdefault("fg", "#7A4B00")
        kwargs.setdefault("readonlybackground", "#FFF2CC")
        kwargs.setdefault("insertbackground", "#7A4B00")
        super().__init__(
            master,
            textvariable=self._display_text,
            state="readonly",
            **kwargs,
        )
        self.bind("<Control-a>", self._select_all)
        self.bind("<Control-A>", self._select_all)
        self._copy_menu = tk.Menu(self, tearoff=False)
        self._copy_menu.add_command(label="Copy", command=self._copy_selection)
        self._copy_menu.add_command(label="Select All", command=self._select_all)
        self.bind("<Button-3>", self._show_copy_menu)

    def configure(self, cnf=None, **kwargs):
        if "text" in kwargs:
            self._display_text.set(str(kwargs.pop("text")))
        return super().configure(cnf, **kwargs)

    config = configure

    def cget(self, key):
        if key == "text":
            return self._display_text.get()
        return super().cget(key)

    def _select_all(self, _event=None):
        self.selection_range(0, tk.END)
        self.icursor(tk.END)
        return "break"

    def _copy_selection(self):
        try:
            selected = self.selection_get()
        except tk.TclError:
            selected = self._display_text.get()
        if selected:
            self.clipboard_clear()
            self.clipboard_append(selected)
            self.update()

    def _show_copy_menu(self, event):
        self.focus_set()
        self._copy_menu.tk_popup(event.x_root, event.y_root)
        self._copy_menu.grab_release()


class SelectableText(tk.Text):
    """Read-only, multi-line text view with Ctrl+C, Ctrl+A and context menu.

    Accepts .config(text=...) / .cget('text') so existing status and
    submission-result updates continue to work without workflow changes.
    """

    def __init__(self, master, *, text="", **kwargs):
        kwargs.setdefault("wrap", "word")
        kwargs.setdefault("takefocus", True)
        kwargs.setdefault("padx", 8)
        kwargs.setdefault("pady", 5)
        super().__init__(master, **kwargs)
        self._text_content = ""
        self._copy_menu = tk.Menu(self, tearoff=False)
        self._copy_menu.add_command(label="Copy Selection", command=self._copy_selection)
        self._copy_menu.add_command(label="Copy All", command=self._copy_all)
        self._copy_menu.add_command(label="Select All", command=self._select_all)
        self.bind("<Control-a>", self._select_all)
        self.bind("<Control-A>", self._select_all)
        self.bind("<Button-3>", self._show_copy_menu)
        self.set_text(text)

    def set_text(self, value):
        content = str(value)
        self._text_content = content
        super().configure(state="normal")
        self.delete("1.0", tk.END)
        self.insert("1.0", content)
        super().configure(state="disabled")
        self.yview_moveto(0)

    def configure(self, cnf=None, **kwargs):
        if "text" in kwargs:
            self.set_text(kwargs.pop("text"))
        return super().configure(cnf, **kwargs)

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text_content
        return super().cget(key)

    def _select_all(self, _event=None):
        self.tag_add(tk.SEL, "1.0", "end-1c")
        self.mark_set(tk.INSERT, "1.0")
        self.see("1.0")
        return "break"

    def _copy_selection(self):
        try:
            selected = self.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return
        if selected:
            self.clipboard_clear()
            self.clipboard_append(selected)
            self.update()

    def _copy_all(self):
        self.clipboard_clear()
        self.clipboard_append(self._text_content)
        self.update()

    def _show_copy_menu(self, event):
        self.focus_set()
        self._copy_menu.tk_popup(event.x_root, event.y_root)
        self._copy_menu.grab_release()


class ReturnProcessorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.browser = BrowserManager()
        self.current_platform = "Shopee"
        self.current_search_mode = "Tracking Number"
        self.current_order_page = None
        self.current_order_id = None
        self.shopee_return_page = None
        self.lazada_return_page = None
        self.tiktok_return_page = None
        self.return_case = None
        # Each dictionary now contains the item's own decisions.
        self.returned_products = []
        # Confirmation flag. The actual decisions live per item.
        self.case_decision = None
        # Odoo now returns one ticket containing one or more stock returns.
        self.odoo_results = None
        # Safe restore point used when the Helpdesk ticket exists but the
        # source inventory transaction is not ready for Odoo Return yet.
        self.odoo_checkpoint = None
        self.lark_results = []
        # Persistent JSON audit/recovery state.
        self.workflow_store = WorkflowStore()
        self.current_scan_id = None
        self._processing_busy = False
        self._history_window = None
        # In-place table editor.
        self.table_editor = None
        self.table_edit_item = None
        self.table_edit_column = None
        self.table_edit_original = None
        self.title("Makerlab Return Processor")
        self.geometry("1380x930")
        self.minsize(1000, 735)
        self.ui_style = apply_theme(self)
        self._responsive_mode = None
        self._resize_job = None
        self.create_gui()
        self.bind("<Configure>", self._schedule_responsive_layout)
        self.after_idle(self._apply_responsive_layout)
        self._refresh_restore_button()
        self.after(300, self.start_browser)
        self.protocol(
            "WM_DELETE_WINDOW",
            self.on_close,
        )

    # =========================================================
    # GUI

    # =========================================================
    def create_gui(self):
        # Keep the native window surface + Windhawk DWM backdrop untouched.
        # The small colored bars and buttons are intentional accent surfaces.
        toolbar = ttk.Frame(self, padding=(18, 8))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="WORKSPACE", style="Toolbar.TLabel").pack(
            side="left", padx=(0, 14)
        )
        self.history_toolbar_button = RoundedButton(
            toolbar, text="Scan History", surface="dark", command=self.open_history_window
        )
        self.history_toolbar_button.pack(side="left", padx=(0, 8))
        self.recovery_toolbar_button = RoundedButton(
            toolbar, text="Recovery", surface="dark", command=self.open_recovery_window,
            state="disabled",
        )
        self.recovery_toolbar_button.pack(side="left")
        self.toolbar_hint = ttk.Label(
            toolbar, text="Saved scans  /  Safe restore points", style="ToolbarHint.TLabel",
        )
        self.toolbar_hint.pack(side="right")

        stripe = ttk.Frame(self, height=3)
        stripe.pack(fill="x")
        stripe.pack_propagate(False)
        tk.Frame(stripe, bg=AMBER, width=100, height=3).pack(side="left", fill="y")
        tk.Frame(stripe, bg=TEAL, height=3).pack(side="left", fill="both", expand=True)

        hero = ttk.Frame(self, padding=(20, 8, 20, 7))
        hero.pack(fill="x")
        hero.columnconfigure(0, weight=1)
        ttk.Label(hero, text="AFTERSALES  /  RETURN OPERATIONS", style="Kicker.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(hero, text="Makerlab Return Processor", style="Title.TLabel").grid(
            row=1, column=0, sticky="w", pady=(1, 1)
        )
        self.hero_subtitle = ttk.Label(
            hero,
            text="One marketplace order  •  One Odoo ticket  •  Odoo + Lark workflow",
            style="Subtitle.TLabel",
        )
        self.hero_subtitle.grid(row=2, column=0, sticky="w")
        self.hero_hint = ttk.Label(
            hero, text="01  SCAN     02  REVIEW     03  ODOO     04  LARK",
            style="Kicker.TLabel",
        )
        self.hero_hint.grid(row=1, column=1, sticky="e", padx=(15, 0))

        # Native ttk scrolling viewport; deliberately NO Canvas, root bgcolor,
        # alpha setting or Windows DWM override (preserves Windhawk glass).
        self.body_viewport = ttk.Frame(self)
        self.body_viewport.pack(fill="both", expand=True)
        self.body_scrollbar = ttk.Scrollbar(
            self.body_viewport, orient="vertical", command=self._scroll_body
        )
        self.body_scrollbar.pack(side="right", fill="y")
        self._body_scroll_y = 0
        self._body_scroll_max = 0
        main_frame = ttk.Frame(self.body_viewport, padding=(18, 3, 18, 10))
        main_frame.place(x=0, y=0, width=1000, height=760)
        self.main_frame = main_frame
        self.body_viewport.bind("<Configure>", self._schedule_body_geometry)
        self.bind("<MouseWheel>", self._on_body_wheel)
        self.bind("<Button-4>", self._on_body_wheel)
        self.bind("<Button-5>", self._on_body_wheel)
        main_frame.columnconfigure(0, weight=12)
        main_frame.columnconfigure(1, weight=11)
        main_frame.rowconfigure(7, weight=1)
        # -----------------------------------------------------
        # Marketplace Source
        # -----------------------------------------------------
        source_panel = RoundedCard(
            main_frame, title="01  FIND A MARKETPLACE RETURN"
        )
        source_panel.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 10),
        )
        source_frame = source_panel.content
        source_frame.columnconfigure(3, weight=1)

        ttk.Label(source_frame, text="Platform:").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.platform_combo = ttk.Combobox(
            source_frame,
            values=PLATFORMS,
            state="readonly",
            width=12,
        )
        self.platform_combo.set(self.current_platform)
        self.platform_combo.grid(
            row=0, column=1, sticky="w", padx=(0, 16)
        )
        self.platform_combo.bind(
            "<<ComboboxSelected>>",
            self.on_platform_changed,
        )

        ttk.Label(source_frame, text="Search By:").grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        self.search_mode_combo = ttk.Combobox(
            source_frame,
            values=SHOPEE_SEARCH_MODES,
            state="readonly",
            width=18,
        )
        self.search_mode_combo.set(self.current_search_mode)
        self.search_mode_combo.grid(
            row=0, column=3, sticky="w"
        )
        self.search_mode_combo.bind(
            "<<ComboboxSelected>>",
            self.on_search_mode_changed,
        )

        self.restore_workflow_button = RoundedButton(
            source_frame,
            text="Restore Pending",
            command=self.restore_latest_workflow,
            state="disabled",
        )
        self.restore_workflow_button.grid(
            row=0, column=4, sticky="e", padx=(10, 0)
        )

        self.order_input_label = ttk.Label(
            source_frame,
            text="Shopee Tracking Number:",
        )
        self.order_input_label.grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(5, 0)
        )

        self.order_url_entry = ttk.Entry(source_frame)
        self.order_url_entry.grid(
            row=1, column=1, columnspan=3, sticky="ew", pady=(5, 0)
        )
        self.order_url_entry.bind(
            "<Return>",
            lambda _event: self.load_platform_order(),
        )
        self.order_url_entry.bind(
            "<KP_Enter>",
            lambda _event: self.load_platform_order(),
        )

        self.open_order_button = RoundedButton(
            source_frame, kind="teal", text="Search & Load",
            command=self.load_platform_order,
        )
        self.open_order_button.grid(
            row=1, column=4, padx=(10, 0), pady=(5, 0)
        )
        self.workspace_separator = ttk.Separator(main_frame, orient="horizontal")
        self.workspace_separator.grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 9),
        )
        # -----------------------------------------------------
        # Order Summary
        # -----------------------------------------------------
        summary_panel = RoundedCard(
            main_frame, title="02  RETURN OVERVIEW"
        )
        summary_panel.grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 14),
        )
        summary = summary_panel.content
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
        self.value_summary_title = ttk.Label(
            summary,
            text="Shopee Total Refund:",
        )
        self.value_summary_title.grid(
            row=0,
            column=1,
            sticky="w",
            padx=(30, 0),
        )
        self.order_id_label = SelectableValue(
            summary,
            text="Not loaded",
            style="Value.TEntry",
        )
        self.order_id_label.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(4, 0),
        )
        self.product_value_label = SelectableValue(
            summary,
            text="Not loaded",
            style="Value.TEntry",
        )
        self.product_value_label.grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(30, 0),
            pady=(4, 0),
        )

        # Keep the Odoo stock transfer visible near the refund value.
        # This is intentionally highlighted because the TC/IN number is
        # frequently copied after processing and can be easy to miss in
        # the multi-line result box at the bottom of the window.
        ttk.Label(
            summary,
            text="Odoo Transfer ID:",
            font=("Segoe UI", 10, "bold"),
        ).grid(
            row=2,
            column=1,
            sticky="w",
            padx=(30, 0),
            pady=(8, 0),
        )
        self.transfer_id_label = HighlightedSelectableValue(
            summary, text="Not created yet",
        )
        configure_transfer_entry(self.transfer_id_label)
        self.transfer_id_label.grid(
            row=3,
            column=1,
            sticky="ew",
            padx=(30, 0),
            pady=(4, 0),
        )
        # -----------------------------------------------------
        # Returned Products Table
        # -----------------------------------------------------
        self.items_heading = ttk.Label(
            main_frame,
            text="03  RETURNED ITEMS   •   Double-click SKU, quantity or amount to edit",
            style="Section.TLabel",
        )
        self.items_heading.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 5),
        )
        table_panel = RoundedCard(main_frame, radius=18)
        self.table_frame = table_panel
        table_panel.grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 14),
        )
        table_frame = table_panel.content
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
        # Treeview does not natively offer Ctrl+C; copy the selected row.
        self.products_table.bind("<Control-c>", self.copy_selected_item)
        self.products_table.bind("<Control-C>", self.copy_selected_item)
        self._table_copy_cell_value = ""
        self._table_copy_menu = tk.Menu(self.products_table, tearoff=False)
        self._table_copy_menu.add_command(
            label="Copy Cell", command=self.copy_clicked_cell
        )
        self._table_copy_menu.add_command(
            label="Copy Selected Item", command=self.copy_selected_item
        )
        self.products_table.bind("<Button-3>", self._show_item_copy_menu)
        item_list_actions = ttk.Frame(
            table_frame,
        )
        item_list_actions.grid(
            row=2,
            column=0,
            sticky="e",
            pady=(8, 0),
        )
        self.add_item_button = RoundedButton(
            item_list_actions,
            text="Add Item",
            command=self.add_return_item,
        )
        self.add_item_button.pack(
            side="left",
        )
        self.remove_item_button = RoundedButton(
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
        self.item_panel = RoundedCard(
            main_frame, title="04  SELECTED ITEM  /  DECISION"
        )
        self.item_panel.grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, 12),
        )
        self.item_frame = self.item_panel.content
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
        self.return_status_combo.bind(
            "<<ComboboxSelected>>",
            self.on_status_changed,
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
        # Capture existing label/input pairs without changing callback bindings.
        self._item_form_pairs = [
            (self.item_frame.grid_slaves(row=0, column=0)[0], self.amount_entry),
            (self.item_frame.grid_slaves(row=0, column=2)[0], self.classification_combo),
            (self.item_frame.grid_slaves(row=0, column=4)[0], self.odoo_tag_combo),
            (self.item_frame.grid_slaves(row=1, column=0)[0], self.decision_combo),
            (self.item_frame.grid_slaves(row=1, column=2)[0], self.return_status_combo),
            (self.item_frame.grid_slaves(row=1, column=4)[0], self.grade_combo),
        ]
        # Remarks
        self.remarks_label = ttk.Label(
            self.item_frame,
            text="Remarks:",
        )
        self.remarks_label.grid(
            row=2, column=0, sticky="nw", padx=(0, 6), pady=4,
        )
        self.remarks_text = tk.Text(
            self.item_frame,
            height=2,
            wrap="word",
            state="disabled",
            bg="#FFFFFF", fg=INK, insertbackground=INK,
            selectbackground=DEEP_TEAL, selectforeground="#FFFFFF",
            relief="flat", highlightthickness=1,
            highlightbackground="#B9D2D5",
        )
        self.remarks_text.grid(
            row=2,
            column=1,
            columnspan=5,
            sticky="ew",
            pady=4,
        )
        item_actions = ttk.Frame(self.item_frame, style="Card.TFrame")
        self.item_actions = item_actions
        item_actions.grid(
            row=3,
            column=0,
            columnspan=6,
            sticky="ew",
            pady=(10, 0),
        )
        self.save_item_button = RoundedButton(
            item_actions,
            text="Save Item Decision",
            command=self.save_selected_item,
            state="disabled",
        )
        self.save_item_button.pack(
            side="left",
        )
        self.apply_all_button = RoundedButton(
            item_actions,
            text="Apply Decision to All Items",
            command=self.apply_selected_decision_to_all,
            state="disabled",
        )
        self.apply_all_button.pack(
            side="left",
            padx=(8, 0),
        )
        self.confirm_decision_button = RoundedButton(
            item_actions,
            text="Confirm All Items",
            command=self.confirm_decision,
            state="disabled",
        )
        self.confirm_decision_button.pack(
            side="left",
            padx=(8, 0),
        )
        self.submit_button = RoundedButton(
            item_actions, kind="amber", text="Submit to Odoo + Lark",
            command=self.submit_case, state="disabled",
        )
        self.submit_button.pack(
            side="left",
            padx=(8, 0),
        )
        self.resume_odoo_button = RoundedButton(
            item_actions, kind="teal", text="Retry Odoo Return & Continue",
            command=self.resume_odoo_workflow, state="disabled",
        )
        self.resume_odoo_button.pack(
            side="left", padx=(8, 0),
        )
        self._decision_actions = [
            self.save_item_button, self.apply_all_button,
            self.confirm_decision_button, self.submit_button,
            self.resume_odoo_button,
        ]
        # -----------------------------------------------------
        # Status / Results
        # -----------------------------------------------------
        self.status_heading = ttk.Label(
            main_frame, text="CURRENT STATUS", style="Section.TLabel",
        )
        self.status_heading.grid(
            row=7,
            column=0,
            columnspan=2,
            sticky="w",
        )
        self.status_label = SelectableText(
            main_frame,
            text="Starting...",
            height=1,
            padx=6,
            pady=2,
            borderwidth=1,
            relief="solid",
        )
        self.status_label.grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=(3, 8),
        )
        configure_readonly_text(self.status_label)

        self.copy_all_button = RoundedButton(
            main_frame, text="Copy All Case Details", surface="dark",
            command=self.copy_case_details,
        )
        self.copy_all_button.grid(row=7, column=1, sticky="e")
        self.odoo_result_frame = RoundedCard(
            main_frame, title="05  ODOO  /  LARK ACTIVITY"
        )
        self.odoo_result_frame.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="ew",
        )
        result_container = ttk.Frame(self.odoo_result_frame.content, style="Card.TFrame")
        result_container.pack(fill="both", expand=True, anchor="w")
        self.odoo_result_label = SelectableText(
            result_container,
            text="No submission completed yet.",
            height=4,
            padx=6,
            pady=3,
            borderwidth=1,
            relief="solid",
        )
        self.odoo_result_label.pack(side="left", fill="both", expand=True)
        configure_readonly_text(self.odoo_result_label, detail=True)
        result_scrollbar = ttk.Scrollbar(
            result_container,
            orient="vertical",
            command=self.odoo_result_label.yview,
        )
        result_scrollbar.pack(side="right", fill="y")
        self.odoo_result_label.configure(yscrollcommand=result_scrollbar.set)
        self._arrange_workspace_columns()
        self.after_idle(self._update_body_geometry)

    def _schedule_body_geometry(self, _event=None):
        if not hasattr(self, "main_frame"):
            return
        if getattr(self, "_geometry_job", None):
            self.after_cancel(self._geometry_job)
        self._geometry_job = self.after_idle(self._update_body_geometry)

    def _update_body_geometry(self):
        self._geometry_job = None
        if not hasattr(self, "main_frame") or not self.main_frame.winfo_exists():
            return
        view_height = max(1, self.body_viewport.winfo_height())
        view_width = max(1, self.body_viewport.winfo_width() - self.body_scrollbar.winfo_width())
        # Use the natural requested height, not the clipped visible height.
        content_height = max(view_height, self.main_frame.winfo_reqheight())
        self._body_scroll_max = max(0, content_height - view_height)
        self._body_scroll_y = min(self._body_scroll_y, self._body_scroll_max)
        current = self.main_frame.place_info()
        if (int(current.get("width", 0)) != view_width
                or int(current.get("height", 0)) != content_height
                or int(current.get("y", 0)) != -self._body_scroll_y):
            self.main_frame.place_configure(
                x=0, y=-self._body_scroll_y, width=view_width, height=content_height
            )
        start = self._body_scroll_y / content_height
        end = min(1, (self._body_scroll_y + view_height) / content_height)
        self.body_scrollbar.set(start, end)

    def _scroll_body(self, *args):
        if not args:
            return
        if args[0] == "moveto":
            next_y = round(float(args[1]) * (self._body_scroll_max + self.body_viewport.winfo_height()))
        elif args[0] == "scroll":
            amount = int(args[1])
            unit = round(self.body_viewport.winfo_height() * 0.8) if args[2] == "pages" else 40
            next_y = self._body_scroll_y + amount * unit
        else:
            return
        self._body_scroll_y = min(max(0, next_y), self._body_scroll_max)
        self._update_body_geometry()

    def _on_body_wheel(self, event):
        if event.widget.winfo_toplevel() is not self or self._body_scroll_max <= 0:
            return
        # Keep native row/text mouse-wheel scrolling in the item/results views.
        if isinstance(event.widget, (ttk.Treeview, tk.Text, ttk.Combobox)):
            return
        delta = -1 if getattr(event, "num", 0) == 5 else (1 if getattr(event, "num", 0) == 4 else 0)
        if not delta:
            delta = int(getattr(event, "delta", 0) / 120)
        if delta:
            self._scroll_body("scroll", -delta, "units")
            return "break"

    def _arrange_workspace_columns(self):
        """Two work areas: readable item list left, form and results right.

        Avoids the old vertical stack collapsing the item table to 1 pixel.
        Widgets are only re-gridded; all old callbacks and values survive.
        """
        panel = self.main_frame
        for row in range(10):
            panel.rowconfigure(row, weight=1 if row == 7 else 0)
        self.source_frame = panel.grid_slaves(row=0, column=0)[0]
        self.source_frame.grid_configure(row=0, column=0, columnspan=2, pady=(0, 7), sticky="ew")
        self.workspace_separator.grid_configure(row=1, column=0, columnspan=2, pady=(1, 8))
        self.summary_frame = panel.grid_slaves(row=3, column=0)[0]
        self.summary_frame.grid_configure(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 11))
        self.items_heading.grid_configure(row=3, column=0, sticky="nw", pady=(0, 5))
        self.table_frame.grid_configure(row=4, column=0, rowspan=5, columnspan=1,
                                        sticky="nsew", pady=(0, 0), padx=(0, 13))
        self.item_panel.grid_configure(row=4, column=1, rowspan=1, columnspan=1,
                                       sticky="new", pady=(0, 9), padx=(8, 0))
        self.status_heading.grid_configure(row=5, column=1, columnspan=1, sticky="w")
        self.status_label.grid_configure(row=6, column=1, columnspan=1,
                                         sticky="ew", pady=(3, 7))
        self.odoo_result_frame.grid_configure(row=7, column=1, columnspan=1,
                                              sticky="nsew", pady=(0, 7))
        self.copy_all_button.grid_configure(row=8, column=1, sticky="e", pady=(0, 1))

    def _schedule_responsive_layout(self, event):
        """Coalesce high-frequency Windows resize events; only reposition widgets."""
        if event.widget is not self:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(90, self._apply_responsive_layout)

    def _apply_responsive_layout(self):
        self._resize_job = None
        if not hasattr(self, "_item_form_pairs"):
            return
        width = self.winfo_width()
        mode = "wide" if width >= 1250 else "compact"
        if mode == self._responsive_mode:
            return
        self._responsive_mode = mode
        # The right review panel is approx. half the window; two field groups
        # per row keep labels readable while the left SKU table stays visible.
        pairs_per_row = 2
        for col in range(6):
            self.item_frame.columnconfigure(col, weight=1 if col in (1,3) else 0)
        # Old 6-column frame contains unused columns 4+5 at this breakpoint.
        # All fields use columns 0..3, remarks and buttons span those columns.
        for index, (label, widget) in enumerate(self._item_form_pairs):
            row = index // pairs_per_row
            pair_column = index % pairs_per_row
            label.grid_configure(row=row, column=pair_column * 2,
                                 sticky="w", padx=(6 if pair_column else 0, 4), pady=3)
            widget.grid_configure(row=row, column=pair_column * 2 + 1,
                                  sticky="ew", padx=0, pady=3)
        next_row = 3
        self.remarks_label.grid_configure(row=next_row, column=0, sticky="nw")
        self.remarks_text.grid_configure(row=next_row, column=1, columnspan=3, sticky="ew")
        self.item_actions.grid_configure(row=next_row+1, column=0, columnspan=4, sticky="ew")
        # Responsive actions: two equal-width columns and a full-width
        # Retry button. In compact mode the critical confirmation and submit
        # actions receive their own rows so labels never get clipped.
        self.item_actions.columnconfigure(0, weight=1, uniform="decision_action")
        self.item_actions.columnconfigure(1, weight=1, uniform="decision_action")
        for action in self._decision_actions:
            action.pack_forget()
            action.grid_forget()
        if mode == "wide":
            positions = (
                (0, 0, 1), (0, 1, 1), (1, 0, 1), (1, 1, 1), (2, 0, 2),
            )
        else:
            positions = (
                (0, 0, 1), (0, 1, 1), (1, 0, 2), (2, 0, 2), (3, 0, 2),
            )
        for button, (row, column, span) in zip(self._decision_actions, positions):
            button.grid(row=row, column=column, columnspan=span,
                        sticky="ew", padx=(4, 4), pady=(0 if row == 0 else 7, 0))
        if mode == "wide":
            self.hero_hint.grid()
            if not self.toolbar_hint.winfo_manager():
                self.toolbar_hint.pack(side="right")
        else:
            self.hero_hint.grid_remove()
            self.toolbar_hint.pack_forget()
        self._schedule_body_geometry()

    # =========================================================
    # BROWSER / SHOPEE

    # =========================================================
    def start_browser(self):
        self.set_status("Opening Playwright browser...")
        try:
            self.browser.start()
            pending_count = len(self.workflow_store.list_restore_points())
            warning = self.workflow_store.last_warning
            if pending_count:
                self.set_status(
                    f"Browser ready. {pending_count} pending workflow(s) can be restored "
                    "with Restore Pending."
                )
            elif warning:
                self.set_status(
                    "Browser ready. JSON recovery warning: " + warning
                )
            else:
                self.set_status(
                    "Browser ready. Choose Shopee, Lazada, or TikTok and load a return."
                )
        except Exception as error:
            self.set_status("Could not start browser.")
            messagebox.showerror("Browser Error", str(error))

    def _search_modes_for_platform(self):
        if self.current_platform == "Lazada":
            return LAZADA_SEARCH_MODES
        if self.current_platform == "TikTok":
            return TIKTOK_SEARCH_MODES
        return SHOPEE_SEARCH_MODES

    def _update_search_controls(self):
        mode = self.current_search_mode
        platform = self.current_platform

        if platform == "Shopee":
            self.value_summary_title.config(text="Shopee Total Refund:")
            if mode == "Order Link":
                self.order_input_label.config(text="Shopee Order Link:")
                self.open_order_button.config(text="Open & Load Order")
                message = "Paste a Shopee Order link and press Enter."
            elif mode == "Order ID":
                self.order_input_label.config(text="Shopee Order ID:")
                self.open_order_button.config(text="Search & Load")
                message = "Enter a Shopee Order ID and press Enter."
            else:
                self.order_input_label.config(text="Shopee Tracking Number:")
                self.open_order_button.config(text="Search & Load")
                message = (
                    "Scan the Shopee return-waybill barcode. The scanner's "
                    "Enter key will search and load the return automatically."
                )
        elif platform == "Lazada":
            self.value_summary_title.config(text="Lazada Refund Total:")
            if mode == "Order ID":
                self.order_input_label.config(text="Lazada Order ID:")
                self.open_order_button.config(text="Load Return")
                message = "Enter the Lazada Order ID and press Enter."
            else:
                self.order_input_label.config(text="Lazada Tracking Number:")
                self.open_order_button.config(text="Search & Load")
                message = (
                    "Scan the Lazada waybill barcode. The processor will switch "
                    "Seller Center's search filter to Tracking Number first."
                )
        else:
            self.value_summary_title.config(text="TikTok Refund Total:")
            self.open_order_button.config(text="Search & Load")
            if mode == "Order ID":
                self.order_input_label.config(text="TikTok Order ID:")
                message = "Enter the TikTok Order ID and press Enter."
            elif mode == "Return Order ID":
                self.order_input_label.config(text="TikTok Return Order ID:")
                message = "Enter the TikTok Return Order ID and press Enter."
            else:
                self.order_input_label.config(text="TikTok Tracking Number:")
                message = (
                    "Scan the TikTok return-waybill barcode. TikTok's Manage "
                    "returns search accepts the tracking number directly."
                )

        self.set_status(message)

    def on_platform_changed(self, _event=None):
        platform = self.platform_combo.get().strip() or "Shopee"
        if platform not in PLATFORMS:
            return

        platform_changed = platform != self.current_platform
        if platform_changed:
            self.current_platform = platform
            self.reset_case()
            self.current_order_page = None
            self.order_id_label.config(text="Not loaded")
            self.product_value_label.config(text="Not loaded")
            self.order_url_entry.delete(0, tk.END)

        modes = self._search_modes_for_platform()
        self.search_mode_combo.config(values=modes)
        if platform_changed or self.current_search_mode not in modes:
            self.current_search_mode = "Tracking Number"
            self.search_mode_combo.set(self.current_search_mode)

        self._update_search_controls()
        self.order_url_entry.focus_set()

    def on_search_mode_changed(self, _event=None):
        mode = self.search_mode_combo.get().strip() or "Tracking Number"
        if mode not in self._search_modes_for_platform():
            return
        self.current_search_mode = mode
        self._update_search_controls()
        self.order_url_entry.focus_set()

    def load_platform_order(self):
        value = self.order_url_entry.get().strip()

        # Keep old Shopee link workflow compatible even while Tracking Number is
        # the default barcode-scanner mode.
        if self.current_platform == "Shopee":
            if "/portal/sale/order/" in value or self.current_search_mode == "Order Link":
                self.open_order_from_url()
            else:
                self.load_shopee_return_search()
        elif self.current_platform == "Lazada":
            self.load_lazada_return()
        else:
            self.load_tiktok_return()

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
            self.open_order_button.config(state="disabled")
            self.set_status("Opening Shopee Order...")
            page = self.browser.open_shopee_order(url)
            self.current_order_page = page
            self.current_platform = "Shopee"
            self.process_order_page(page)
        except Exception as error:
            self.set_status("Could not open Shopee Order.")
            messagebox.showerror("Open Order Error", str(error))
        finally:
            self.open_order_button.config(state="normal")

    def load_shopee_return_search(self):
        query = self.order_url_entry.get().strip()
        mode = self.current_search_mode
        if not query:
            messagebox.showwarning(
                "Missing Search Value",
                f"Enter or scan the Shopee {mode} first.",
            )
            return

        if mode not in {"Tracking Number", "Order ID"}:
            self.open_order_from_url()
            return

        try:
            self.open_order_button.config(state="disabled")
            self.set_status(f"Searching Shopee Return List by {mode}...")
            return_page = self.browser.get_shopee_return_page()
            if not return_page:
                raise RuntimeError("Playwright browser context is unavailable.")
            self.shopee_return_page = return_page
            return_page.bring_to_front()

            if mode == "Tracking Number":
                return_case = get_return_case_by_tracking(return_page, query)
            else:
                return_case = get_return_case_data(return_page, query)

            order_id = str(return_case.get("order_id") or "").strip()
            if not order_id:
                raise RuntimeError(
                    "Shopee found the return but its Order ID is blank."
                )

            self.set_status(
                f"Shopee {mode} found. Clicking Order ID {order_id}..."
            )
            page = open_order_from_return_row(
                return_page,
                order_id,
            )
            self.current_order_page = page
            self.current_platform = "Shopee"
            self.process_order_page(page, known_return_case=return_case)
        except Exception as error:
            self.set_status(f"Could not load Shopee return by {mode}.")
            messagebox.showerror("Shopee Return Search Error", str(error))
        finally:
            self.open_order_button.config(state="normal")

    def load_lazada_return(self):
        query = self.order_url_entry.get().strip()
        mode = self.current_search_mode

        if not query:
            messagebox.showwarning(
                "Missing Search Value",
                f"Enter or scan the Lazada {mode} first.",
            )
            return
        if mode == "Order ID" and not query.isdigit():
            messagebox.showwarning(
                "Invalid Order ID",
                "Lazada Order ID should contain numbers only.",
            )
            return

        try:
            self.open_order_button.config(state="disabled")
            self.set_status("Opening Lazada Return Orders...")
            page = self.browser.get_lazada_return_page()
            if not page:
                raise RuntimeError("Playwright browser context is unavailable.")
            self.lazada_return_page = page
            self.current_order_page = page
            page.bring_to_front()

            self.set_status(f"Searching Lazada by {mode}: {query}...")
            data = get_lazada_return_order(
                page,
                query,
                search_by=mode,
            )
            self.current_platform = "Lazada"
            self.process_lazada_return_data(data)
        except Exception as error:
            self.set_status(f"Could not load Lazada return by {mode}.")
            messagebox.showerror("Lazada Return Error", str(error))
        finally:
            self.open_order_button.config(state="normal")

    def load_tiktok_return(self):
        query = self.order_url_entry.get().strip()
        mode = self.current_search_mode

        if not query:
            messagebox.showwarning(
                "Missing Search Value",
                f"Enter or scan the TikTok {mode} first.",
            )
            return

        try:
            self.open_order_button.config(state="disabled")
            self.set_status("Opening TikTok Manage returns...")
            page = self.browser.get_tiktok_return_page()
            if not page:
                raise RuntimeError("Playwright browser context is unavailable.")
            self.tiktok_return_page = page
            self.current_order_page = page
            page.bring_to_front()

            self.set_status(f"Searching TikTok by {mode}: {query}...")
            data = get_tiktok_return_order(
                page,
                query,
                search_by=mode,
            )
            self.current_platform = "TikTok"
            self.process_tiktok_return_data(data)
        except Exception as error:
            self.set_status(f"Could not load TikTok return by {mode}.")
            messagebox.showerror("TikTok Return Error", str(error))
        finally:
            self.open_order_button.config(state="normal")

    @staticmethod
    def _new_item_record(
        *,
        sku: str = "",
        quantity: int = 1,
        unit_price="",
        amount="",
        platform: str = "Shopee",
        status: str = RETURNED_STATUS,
        source_data: dict | None = None,
    ) -> dict:
        """Create one normalized marketplace return item."""
        record = {
            "sku": str(sku).strip().upper(),
            "quantity": int(quantity),
            "unit_price": unit_price,
            "amount": amount,
            "classification": "",
            "odoo_tag": "",
            "decision": DEFAULT_DECISION,
            "status": status,
            "platform": platform,
            "grade": "",
            "remarks": "",
        }
        if source_data:
            record["source_data"] = copy.deepcopy(source_data)
        return record

    def _show_loaded_items(self, items, status_message):
        self.returned_products = items
        self.populate_products_table()
        self.set_item_controls_enabled(bool(items))

        if items:
            first_iid = self.products_table.get_children()[0]
            self.products_table.selection_set(first_iid)
            self.products_table.focus(first_iid)
            self.load_selected_item()

        self.confirm_decision_button.config(
            state="normal" if items else "disabled"
        )
        self.set_status(status_message)
        self._record_loaded_scan()

    def process_order_page(self, page, known_return_case=None):
        """Load a Shopee order and merge Order-page + Return-list data."""
        self.reset_case()
        self.current_platform = "Shopee"
        self.order_id_label.config(text="Loading...")
        self.product_value_label.config(text="Loading...")

        self.set_status("Reading Shopee Order ID...")
        order_id = get_order_id(page)
        self.current_order_id = order_id
        self.order_id_label.config(text=order_id)

        self.set_status("Reading returned products...")
        raw_products = get_returned_products(page)

        return_case = known_return_case
        if return_case:
            expected_order_id = str(return_case.get("order_id") or "").strip()
            if expected_order_id and expected_order_id != order_id:
                raise ValueError(
                    "Shopee tracking/search resolved to a different Order ID. "
                    f"Expected {expected_order_id}, opened {order_id}."
                )
            self.set_status(
                f"Using Shopee return found by {return_case.get('search_by') or 'search'}..."
            )
        else:
            self.set_status("Searching Shopee Return List...")
            try:
                return_page = self.browser.get_shopee_return_page()
                self.shopee_return_page = return_page
                if return_page:
                    return_case = get_return_case_data(return_page, order_id)
            except Exception as error:
                print("\nRETURN CASE LOOKUP FAILED:")
                print(error)

        self.return_case = return_case
        self.product_value_label.config(
            text=return_case["refund_text"] if return_case else "Not found"
        )

        items = [
            self._new_item_record(
                sku=product["sku"],
                quantity=product["quantity"],
                unit_price=product.get("unit_price", ""),
                amount=product.get("amount", ""),
                platform="Shopee",
            )
            for product in raw_products
        ]

        amount_note = (
            "Individual amounts calculated from Shopee Unit Price × Return QTY."
            if items
            else "No returned items found."
        )
        self._show_loaded_items(
            items,
            f"Order loaded: {order_id} | {len(items)} returned item(s). {amount_note}",
        )

    def process_lazada_return_data(self, data: dict):
        """Normalize one Lazada Return Orders card into the shared workflow."""
        self.reset_case()
        self.current_platform = "Lazada"

        order_id = str(data.get("order_id") or "").strip()
        if not order_id:
            raise ValueError("Lazada return data has no Order ID.")

        self.current_order_id = order_id
        self.return_case = {
            "order_id": order_id,
            "request_id": str(data.get("return_order_id") or "").strip(),
            "refund_text": data.get("refund_text") or "₱0.00",
            "refund_value": float(data.get("refund_value") or 0),
            "return_url": data.get("return_url") or "",
            "tracking_number": str(data.get("tracking_number") or "").strip(),
            "search_by": str(data.get("search_by") or "Order ID").strip(),
            "search_query": str(data.get("search_query") or "").strip(),
            "platform": "Lazada",
            "value_mode": "item_amounts",
            "value_source": data.get("value_source") or "Lazada item Refund Amount",
        }

        self.order_id_label.config(text=order_id)
        self.product_value_label.config(text=self.return_case["refund_text"])

        items = []
        manual_status_count = 0
        mixed_status_count = 0
        for raw in data.get("items") or []:
            status = suggested_processor_status(raw)
            if not status:
                manual_status_count += 1
            if raw.get("mixed_delivery_status"):
                mixed_status_count += 1

            refund_amount = float(raw.get("refund_amount") or 0)
            qty = int(raw.get("quantity") or 1)
            item = self._new_item_record(
                sku=raw.get("sku", ""),
                quantity=qty,
                unit_price=(round(refund_amount / qty, 4) if qty else ""),
                amount=refund_amount,
                platform="Lazada",
                status=status,
                source_data=raw,
            )
            items.append(item)

        if not items:
            raise ValueError("No Lazada return items were found for this order.")

        total_units = sum(item["quantity"] for item in items)
        source_count = int(data.get("source_item_count") or total_units)
        warning_parts = [
            "Repeated Lazada Return Item IDs sharing a SKU are grouped. "
            "QTY counts their units and Amount is the SUM of refund amounts. "
            "Lazada's list assumes QTY 1 per source Return Item ID; verify "
            "the total before confirming."
        ]
        if manual_status_count:
            warning_parts.append(
                f"{manual_status_count} SKU group(s) are not clearly delivered to the "
                "seller, so Status was left blank for manual confirmation."
            )
        if mixed_status_count:
            warning_parts.append(
                f"{mixed_status_count} SKU group(s) contain units with differing "
                "delivery status. Split into separate rows if their return "
                "handling is different."
            )

        self._show_loaded_items(
            items,
            (
                f"Lazada return loaded: {order_id} | {len(items)} unique SKU(s) | "
                f"QTY {total_units} from {source_count} Return Item ID row(s) | "
                f"Return Order ID {data.get('return_order_id') or 'N/A'} | "
                f"Searched by {data.get('search_by') or 'Order ID'}. "
                + " ".join(warning_parts)
            ),
        )

        print("\nLAZADA RETURN SOURCE DETAILS:")
        for item in items:
            src = item.get("source_data", {})
            print(
                f"{item['sku']} | QTY {item['quantity']} | "
                f"Return Item IDs {', '.join(src.get('return_item_ids') or [])} | "
                f"Total Refund {item['amount']:.2f} | {src.get('source_status', '')} | "
                f"{src.get('return_reason', '')}"
            )

    def process_tiktok_return_data(self, data: dict):
        """Normalize one TikTok Manage returns result into the shared workflow."""
        self.reset_case()
        self.current_platform = "TikTok"

        order_id = str(data.get("order_id") or "").strip()
        if not order_id:
            raise ValueError("TikTok return data has no Order ID.")

        refund_value = float(data.get("refund_value") or 0)
        refund_text = data.get("refund_text") or f"₱{refund_value:,.2f}"
        self.current_order_id = order_id
        self.return_case = {
            "order_id": order_id,
            "request_id": str(data.get("return_order_id") or "").strip(),
            "refund_text": refund_text,
            "refund_value": refund_value,
            "return_url": data.get("return_url") or "",
            "tracking_number": str(data.get("tracking_number") or "").strip(),
            "search_by": str(data.get("search_by") or "Tracking Number").strip(),
            "search_query": str(data.get("search_query") or "").strip(),
            "platform": "TikTok",
            # TikTok's overview exposes one refund total for the return, not
            # a dependable per-SKU refund allocation. Keep Shopee-style total
            # value behavior for Lark instead of inventing item amounts.
            "value_source": data.get("value_source") or "TikTok return Refund total",
        }

        self.order_id_label.config(text=order_id)
        self.product_value_label.config(text=refund_text)

        raw_items = list(data.get("items") or [])
        if not raw_items:
            raise ValueError("No TikTok return items were found for this return.")

        single_item = len(raw_items) == 1
        items = []
        for raw in raw_items:
            source_data = dict(raw)
            source_data.update({
                "return_order_id": data.get("return_order_id") or "",
                "return_reason": data.get("return_reason") or "",
                "source_status": data.get("source_status") or "",
                "logistics_status": data.get("logistics_status") or "",
                "logistics_time": data.get("logistics_time") or "",
                "paid_text": data.get("paid_text") or "",
                "refund_text": refund_text,
            })
            items.append(
                self._new_item_record(
                    sku=raw.get("sku", ""),
                    quantity=int(raw.get("quantity") or 1),
                    unit_price="",
                    amount=(refund_value if single_item else ""),
                    platform="TikTok",
                    # A scanned return waybill represents a parcel physically
                    # being processed by the team. TikTok's logistics status can
                    # lag behind the physical handoff, so keep the existing
                    # receiving workflow default of Returned.
                    status=RETURNED_STATUS,
                    source_data=source_data,
                )
            )

        notes = []
        if not single_item:
            notes.append(
                "TikTok provides a return-level refund total but no reliable "
                "per-item refund allocation in this view, so item Amounts are "
                "left blank and are optional for TikTok. Lark uses the TikTok "
                "return refund total."
            )
        logistics = str(data.get("logistics_status") or "").strip()
        if logistics:
            notes.append(f"TikTok source logistics: {logistics}.")

        self._show_loaded_items(
            items,
            (
                f"TikTok return loaded: {order_id} | {len(items)} item(s) | "
                f"Return Order ID {data.get('return_order_id') or 'N/A'} | "
                f"Searched by {data.get('search_by') or 'Tracking Number'}. "
                + " ".join(notes)
            ),
        )

        print("\nTIKTOK RETURN SOURCE DETAILS:")
        print(
            f"Order {order_id} | Return {data.get('return_order_id', '')} | "
            f"Refund {refund_text} | Reason {data.get('return_reason', '')} | "
            f"Logistics {data.get('logistics_status', '')}"
        )
        for item in items:
            src = item.get("source_data", {})
            print(
                f"{item['sku']} | QTY {item['quantity']} | "
                f"{src.get('product_name', '')}"
            )

    # =========================================================
    # JSON HISTORY / RECOVERY
    # =========================================================
    def _record_loaded_scan(self):
        """Create one permanent history entry for each successful marketplace load."""
        try:
            self.current_scan_id = self.workflow_store.start_scan(
                platform=self.current_platform,
                search_by=self.current_search_mode,
                search_input=self.order_url_entry.get().strip(),
                order_id=self.current_order_id,
                return_case=self.return_case or {},
                items=self.returned_products,
            )
            self._refresh_restore_button()
        except Exception as error:
            # Persistence must never block marketplace processing.
            print(f"JSON scan-history save failed: {error}")

    def _workflow_snapshot(self, workflow_state, last_error=""):
        return {
            "workflow_state": workflow_state,
            "platform": self.current_platform,
            "search_by": self.current_search_mode,
            "search_input": self.order_url_entry.get().strip(),
            "order_id": self.current_order_id or "",
            "return_case": copy.deepcopy(self.return_case or {}),
            "items": copy.deepcopy(self.returned_products),
            "case_decision": copy.deepcopy(self.case_decision),
            "odoo_results": copy.deepcopy(self.odoo_results),
            "odoo_checkpoint": copy.deepcopy(self.odoo_checkpoint),
            "lark_results": copy.deepcopy(self.lark_results),
            "transfer_display": self.transfer_id_label.cget("text"),
            "status_text": self.status_label.cget("text"),
            "last_error": str(last_error or ""),
        }

    def _persist_workflow(self, workflow_state, *, keep_restore, last_error=""):
        """Update scan history and optionally keep an on-disk resume snapshot."""
        if not self.current_scan_id:
            return
        snapshot = self._workflow_snapshot(workflow_state, last_error=last_error)
        try:
            self.workflow_store.update_scan(
                self.current_scan_id,
                workflow_state=workflow_state,
                items=snapshot["items"],
                case_decision=snapshot["case_decision"],
                odoo_results=snapshot["odoo_results"],
                odoo_checkpoint=snapshot["odoo_checkpoint"],
                lark_results=snapshot["lark_results"],
                last_error=snapshot["last_error"],
                return_case=snapshot["return_case"],
            )
            if keep_restore:
                self.workflow_store.save_restore_point(
                    self.current_scan_id,
                    snapshot,
                )
            else:
                self.workflow_store.delete_restore_point(self.current_scan_id)
        except Exception as error:
            # Do not interrupt Odoo/Lark solely because the local audit file failed.
            print(f"JSON workflow save failed: {error}")
        finally:
            self._refresh_restore_button()

    def _refresh_restore_button(self, busy=False):
        """Refresh both top-toolbar and existing in-form recovery shortcuts."""
        if not hasattr(self, "restore_workflow_button"):
            return
        try:
            count = len(self.workflow_store.list_restore_points())
        except Exception as error:
            print(f"Could not read restore points: {error}")
            count = 0
        is_busy = bool(busy or self._processing_busy)
        button_state = "normal" if count and not is_busy else "disabled"
        label = f"Recovery ({count})" if count else "Recovery"
        self.recovery_toolbar_button.config(text=label, state=button_state)
        self.history_toolbar_button.config(state="disabled" if is_busy else "normal")
        self.restore_workflow_button.config(
            text=(f"Browse Pending ({count})" if count else "Browse Pending"),
            state=button_state,
        )
        window = self._history_window
        if window is not None and window.winfo_exists():
            window.refresh_from_store()

    def open_recovery_window(self):
        """Open all pending cases so the operator can select one to resume."""
        self.open_history_window(pending_only=True)

    def open_history_window(self, pending_only=False):
        """Show a single non-modal history and recovery browser."""
        if self._processing_busy:
            messagebox.showwarning(
                "Processor Busy", "Wait for the current submission to finish."
            )
            return
        window = self._history_window
        if window is not None and window.winfo_exists():
            if pending_only:
                window.status_var.set("Pending / Recoverable")
            window.refresh_from_store()
            window.lift()
            window.focus_set()
            return
        self._history_window = HistoryRecoveryWindow(
            self,
            store=self.workflow_store,
            on_restore=self.restore_saved_workflow,
            pending_only=pending_only,
        )

    def restore_latest_workflow(self):
        """Compatibility shortcut: show the picker instead of auto-restoring."""
        self.open_recovery_window()

    def restore_saved_workflow(self, scan_id):
        """Load one selected JSON checkpoint without touching Odoo or Lark."""
        if self._processing_busy:
            messagebox.showwarning(
                "Processor Busy", "Wait for the current submission to finish."
            )
            return False
        try:
            snapshot = self.workflow_store.get_restore_point(scan_id)
        except Exception as error:
            messagebox.showerror("Restore Error", str(error))
            return False
        if not snapshot:
            messagebox.showwarning(
                "No Restore Point", "This case has no active saved checkpoint."
            )
            return False
        if snapshot.get("workflow_state") == "completed":
            messagebox.showwarning(
                "Completed Case", "Completed history entries cannot be restored."
            )
            return False
        order_id = str(snapshot.get("order_id") or "").strip()
        items = snapshot.get("items")
        if not order_id or not isinstance(items, list) or not items:
            messagebox.showerror(
                "Invalid Restore Point",
                "The saved case is missing an Order ID or return items. "
                "No current work was changed.",
            )
            return False
        # Fail closed when a checkpoint is incomplete: never offer Submit in a
        # state that might recreate an already-existing Odoo Helpdesk ticket.
        state = str(snapshot.get("workflow_state") or "confirmed")
        checkpoint = snapshot.get("odoo_checkpoint")
        odoo_result = snapshot.get("odoo_results")
        returned_items = any(
            isinstance(item, dict) and item.get("status") == RETURNED_STATUS
            for item in items
        )
        if (
            (state in {"odoo_return_pending", "manual_review"} and not checkpoint)
            or (state == "lark_pending" and returned_items and not odoo_result)
            or (state in {"odoo_return_pending", "manual_review", "lark_pending"}
                and not snapshot.get("case_decision"))
        ):
            messagebox.showerror(
                "Incomplete Restore Point",
                "This saved workflow is missing an Odoo checkpoint/result or "
                "the confirmed item decisions. It cannot safely resume "
                "automatically. Review the existing Odoo work manually."
            )
            return False
        if self.current_scan_id == scan_id and self.current_order_id:
            messagebox.showinfo(
                "Already Open",
                "This workflow is already open in the processor. Continue "
                "using its Submit or Retry Odoo Return & Continue button.",
            )
            return False

        if self.current_order_id:
            active_pending = bool(
                self.case_decision and not self.lark_results
            )
            if active_pending:
                try:
                    existing_snapshot = self.workflow_store.get_restore_point(
                        self.current_scan_id
                    )
                except Exception:
                    existing_snapshot = None
                if not existing_snapshot:
                    messagebox.showwarning(
                        "Cannot Switch Safely",
                        "The current workflow has confirmed work but no "
                        "saved restore point. Finish or save it first."
                    )
                    return False
                prompt = (
                    f"The current order {self.current_order_id} has an "
                    "unfinished workflow saved in JSON.\n\n"
                    f"Switch to order {order_id}? Any unconfirmed on-screen "
                    "edits to the current case will be discarded."
                )
            else:
                prompt = (
                    f"Replace the currently displayed order "
                    f"{self.current_order_id} with saved order {order_id}?\n\n"
                    "Any unsaved edits to the current screen will be discarded."
                )
            if not messagebox.askyesno(
                "Switch Saved Workflow", prompt, parent=self
            ):
                return False

        try:
            self._load_restored_snapshot(snapshot)
        except Exception as error:
            messagebox.showerror("Restore Error", str(error))
            return False
        return True

    def _load_restored_snapshot(self, snapshot):
        """Restore UI and idempotency state; never submit automatically."""
        state = str(snapshot.get("workflow_state") or "confirmed")
        platform = str(snapshot.get("platform") or "Shopee")
        if platform not in PLATFORMS:
            platform = "Shopee"

        self.reset_case()
        self.current_scan_id = str(snapshot.get("scan_id") or "") or None
        self.current_platform = platform
        self.platform_combo.set(platform)

        modes = (
            LAZADA_SEARCH_MODES
            if platform == "Lazada"
            else TIKTOK_SEARCH_MODES
            if platform == "TikTok"
            else SHOPEE_SEARCH_MODES
        )
        self.search_mode_combo.config(values=modes)
        mode = str(snapshot.get("search_by") or "Tracking Number")
        if mode not in modes:
            mode = "Tracking Number"
        self.current_search_mode = mode
        self.search_mode_combo.set(mode)
        self._update_search_controls()

        self.order_url_entry.delete(0, tk.END)
        self.order_url_entry.insert(0, str(snapshot.get("search_input") or ""))
        self.current_order_id = str(snapshot.get("order_id") or "").strip() or None
        self.return_case = copy.deepcopy(snapshot.get("return_case") or {})
        self.returned_products = copy.deepcopy(snapshot.get("items") or [])
        self.case_decision = copy.deepcopy(snapshot.get("case_decision"))
        self.odoo_results = copy.deepcopy(snapshot.get("odoo_results"))
        self.odoo_checkpoint = copy.deepcopy(snapshot.get("odoo_checkpoint"))
        self.lark_results = copy.deepcopy(snapshot.get("lark_results") or [])

        self.order_id_label.config(text=self.current_order_id or "Not loaded")
        refund_text = str((self.return_case or {}).get("refund_text") or "Not loaded")
        self.product_value_label.config(text=refund_text)
        self.populate_products_table()
        self.set_item_controls_enabled(bool(self.returned_products))
        if self.returned_products:
            first_iid = self.products_table.get_children()[0]
            self.products_table.selection_set(first_iid)
            self.products_table.focus(first_iid)
            self.load_selected_item()

        if self.odoo_checkpoint:
            self._render_odoo_checkpoint(snapshot.get("last_error") or "")
        elif self.odoo_results:
            self._render_odoo_results()
        elif state == "lark_pending":
            self.transfer_id_label.config(text="No Odoo transfer (Not Returned)")
            self.odoo_result_label.config(
                text=(
                    "RESTORED WORKFLOW\n"
                    "Odoo was skipped because the confirmed items were Not Returned.\n"
                    "Press Submit to retry Lark only."
                )
            )
        else:
            self.transfer_id_label.config(
                text=str(snapshot.get("transfer_display") or "Not created yet")
            )
            self.odoo_result_label.config(
                text=(
                    "RESTORED WORKFLOW\n"
                    f"State: {state}\n"
                    "Review the restored item decisions, then continue."
                )
            )

        self._sync_action_buttons()
        if self.odoo_checkpoint and self.odoo_checkpoint.get("resume_safe", False):
            message = (
                f"Restored {self.current_order_id}. Validate inventory if needed, "
                "then click Retry Odoo Return & Continue."
            )
        elif self.odoo_checkpoint:
            message = (
                f"Restored {self.current_order_id} for manual Odoo review. "
                "Automatic return retry is disabled."
            )
        elif state == "lark_pending":
            message = (
                f"Restored {self.current_order_id}. Existing Odoo progress "
                "is preserved; click Submit to continue with Lark."
            )
        else:
            message = f"Restored {self.current_order_id}. Continue from: {state}."
        self.set_status(message)

    # =========================================================
    # ITEM TABLE / EDITING

    # =========================================================
    def reset_case(self):
        self.cancel_table_edit()
        self.current_order_id = None
        self.current_order_page = None
        self.return_case = None
        self.returned_products = []
        self.case_decision = None
        self.odoo_results = None
        self.odoo_checkpoint = None
        self.lark_results = []
        self.current_scan_id = None
        self.clear_products_table()
        self.clear_item_editor()
        self.set_item_controls_enabled(
            False
        )
        self.submit_button.config(
            state="disabled",
        )
        self.odoo_result_label.config(
            text="No submission completed yet.",
        )
        self.transfer_id_label.config(
            text="Not created yet",
        )
        self.remove_item_button.config(
            state="disabled",
        )
    def clear_products_table(self):
        children = self.products_table.get_children()
        if children:
            self.products_table.delete(*children)
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
        self.update_odoo_tag_state()
    def _ensure_item_list_mutable(self):
        """

        Do not alter the returned-item list after Odoo has already created

        the ticket/return records. That would make the GUI disagree with

        data already committed in Odoo.

        """
        if self.odoo_results or self.odoo_checkpoint:
            messagebox.showwarning(
                "Odoo Workflow Locked",
                (
                    "An Odoo ticket/restore point already exists for this order.\n\n"
                    "The returned-item list cannot be changed now because it "
                    "would no longer match the saved Odoo workflow."
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

            Platform = active marketplace

        SKU, Classification and Odoo Tag must be completed before Confirm All
        Items. Amount is also required for Shopee/Lazada; TikTok may use the
        return-level refund total when per-item allocation is unavailable.

        """
        if not self.current_order_id:
            messagebox.showwarning(
                "No Order Loaded",
                "Load a Shopee, Lazada, or TikTok return before adding an item.",
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
        new_item = self._new_item_record(platform=self.current_platform)
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
            self.submit_button.config(
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
        if enabled:
            self.update_odoo_tag_state()
            self.update_grade_state()
        else:
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
        self.decision_combo.set(DEFAULT_DECISION)
        self.return_status_combo.set(RETURNED_STATUS)
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
    def on_status_changed(self, _event=None):
        self.update_odoo_tag_state()
    def update_odoo_tag_state(self):
        controls_enabled = (
            str(self.classification_combo.cget("state")) != "disabled"
        )
        self.odoo_tag_combo.config(
            state=(
                "readonly"
                if controls_enabled
                and self.return_status_combo.get().strip() == RETURNED_STATUS
                else "disabled"
            )
        )
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
        platform = str(item.get("platform") or self.current_platform).strip()
        if not raw_amount and platform == "TikTok":
            amount = ""
        else:
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
        if status == RETURNED_STATUS and not odoo_tag:
            raise ValueError(
                f"Select Odoo Tag for returned item {item['sku']}."
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
            "amount": round(amount, 2) if amount != "" else "",
            "classification": classification,
            "odoo_tag": odoo_tag,
            "decision": decision,
            "status": status,
            "platform": item.get("platform") or self.current_platform,
            "grade": grade,
            "remarks": remarks,
        }
    def save_selected_item(self):
        if not self._ensure_item_list_mutable():
            return
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
        if not self._ensure_item_list_mutable():
            return
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
            raw_amount = item.get("amount", "")
            platform = str(item.get("platform") or self.current_platform).strip()
            if platform == "TikTok" and str(raw_amount).strip() == "":
                amount = None
            else:
                try:
                    amount = float(raw_amount)
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
                ("decision", "Decision"),
                ("status", "Status"),
            ):
                if not str(item.get(field, "")).strip():
                    raise ValueError(
                        f"{label} is missing for {sku}."
                    )
            # Odoo Tag is only needed when the physical item was returned
            # and will actually be filed into Odoo.
            if (
                str(item.get("status", "")).strip() == RETURNED_STATUS
                and not str(item.get("odoo_tag", "")).strip()
            ):
                raise ValueError(
                    f"Odoo Tag is missing for returned item {sku}."
                )
            if (
                item["classification"] == "Unsealed"
                and not str(item.get("grade", "")).strip()
            ):
                raise ValueError(
                    f"Grade is required for unsealed item {sku}."
                )
    def returned_items_for_odoo(self):
        """Items that physically came back and therefore require Odoo."""
        return [
            item
            for item in self.returned_products
            if str(item.get("status", "")).strip() == RETURNED_STATUS
        ]
    def not_returned_items(self):
        """Items that require Lark filing but no Odoo stock return."""
        return [
            item
            for item in self.returned_products
            if str(item.get("status", "")).strip() != RETURNED_STATUS
        ]
    def _sync_action_buttons(self, busy=False):
        """Single source of truth for workflow button availability."""
        checkpoint_pending = bool(
            self.odoo_checkpoint
            and self.odoo_checkpoint.get("resume_safe", False)
            and not self.lark_results
        )
        workflow_locked = bool(self.odoo_checkpoint)

        self.platform_combo.config(
            state="disabled" if busy or workflow_locked else "readonly"
        )
        if busy:
            states = {
                self.open_order_button: "disabled",
                self.confirm_decision_button: "disabled",
                self.submit_button: "disabled",
                self.resume_odoo_button: "disabled",
            }
        else:
            states = {
                self.open_order_button: (
                    "disabled" if workflow_locked else "normal"
                ),
                self.confirm_decision_button: (
                    "normal"
                    if self.returned_products and not workflow_locked
                    else "disabled"
                ),
                self.submit_button: (
                    "normal"
                    if (
                        self.case_decision
                        and not self.lark_results
                        and not workflow_locked
                    )
                    else "disabled"
                ),
                self.resume_odoo_button: (
                    "normal" if checkpoint_pending else "disabled"
                ),
            }
        for button, state in states.items():
            button.config(state=state)
        self._refresh_restore_button(busy=busy)
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
            self._persist_workflow(
                "confirmed",
                keep_restore=True,
            )
            returned_items = self.returned_items_for_odoo()
            if not returned_items:
                self.odoo_results = None
                self.odoo_result_label.config(
                    text=(
                        "Odoo will be skipped: all confirmed items are Not Returned.\n"
                        "Click Submit to file directly to Lark."
                    ),
                )
            self._sync_action_buttons()
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
            if returned_items:
                self.set_status(
                    (
                        "All item decisions confirmed. Click Submit to process "
                        "Odoo and file Lark automatically."
                    )
                )
            else:
                self.set_status(
                    (
                        "All items are Not Returned. Click Submit to file Lark; "
                        "Odoo will be skipped automatically."
                    )
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
        self.odoo_checkpoint = None
        self.lark_results = []
        self.submit_button.config(
            state="disabled",
        )
        self.odoo_result_label.config(
            text=(
                "Item data changed. Confirm All Items again "
                "before processing."
            ),
        )
        self.transfer_id_label.config(
            text="Not created yet",
        )
        self._persist_workflow(
            "loaded",
            keep_restore=False,
        )

    # =========================================================
    # SUBMIT WORKFLOW

    # =========================================================
    def _render_odoo_checkpoint(self, error_message=""):
        """Show the saved ticket and pending Odoo return restore point."""
        checkpoint = self.odoo_checkpoint or {}
        transfer_ids = []
        for result in checkpoint.get("returns", []):
            transfer_id = str(result.get("transfer_id", "")).strip()
            if transfer_id and transfer_id not in transfer_ids:
                transfer_ids.append(transfer_id)

        self.transfer_id_label.config(
            text=(
                " | ".join(transfer_ids)
                if transfer_ids
                else "Return pending - ticket saved"
            )
        )

        pending = checkpoint.get("pending_return") or {}
        pending_items = ", ".join(
            f"{item.get('sku', '')}_{item.get('quantity', '')}"
            for item in pending.get("items", [])
        )
        lines = [
            "ODOO RESTORE POINT SAVED",
            f"Ticket: {checkpoint.get('ticket_title', '')}",
            checkpoint.get("ticket_url", ""),
        ]
        if transfer_ids:
            lines.append("Completed transfer(s): " + " | ".join(transfer_ids))
        if pending:
            lines.append(
                f"Pending Return #{pending.get('return_index', '')}: "
                f"{pending_items}"
            )
        if error_message:
            lines.extend(["", error_message])
        if checkpoint.get("resume_safe", False):
            lines.extend([
                "",
                "Validate the related inventory transaction in Odoo, then click",
                "Retry Odoo Return & Continue. No new Helpdesk ticket will be created.",
            ])
        else:
            lines.extend([
                "",
                "Manual Odoo review required. Automatic retry is disabled because",
                "the stock-return state is uncertain. No new ticket is created.",
            ])
        self.odoo_result_label.config(text="\n".join(lines))

    def _render_odoo_results(self):
        """Render completed Odoo ticket / transfer information."""
        if not self.odoo_results:
            self.transfer_id_label.config(
                text="Not created yet",
            )
            return

        transfer_ids = []
        for return_group in self.odoo_results.get("returns", []):
            transfer_id = str(
                return_group.get("transfer_id", "")
            ).strip()
            if transfer_id and transfer_id not in transfer_ids:
                transfer_ids.append(transfer_id)

        self.transfer_id_label.config(
            text=(
                " | ".join(transfer_ids)
                if transfer_ids
                else "No Odoo transfer"
            ),
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
    def _run_odoo_submit_step(self, returned_items):
        """

        Run Odoo for physically returned items.

        If Odoo already succeeded and Lark later failed, Submit will not

        create another Odoo ticket on retry.

        """
        self.set_status(
            "Submit 1/2: Creating Odoo ticket / return(s)..."
        )
        self.odoo_results = create_odoo_tickets(
            context=self.browser.context,
            order_id=self.current_order_id,
            returned_products=returned_items,
            case_decision=self.case_decision,
            platform=self.current_platform,
            progress_callback=self.set_status,
        )
        self.odoo_checkpoint = None
        self._render_odoo_results()
        # Persist the completed Odoo ticket/transfer before Lark starts.
        # A restart at this point will retry Lark only, never Odoo.
        self._persist_workflow(
            "lark_pending",
            keep_restore=True,
        )
        self.set_status(
            (
                f"Odoo completed: 1 ticket, "
                f"{len(self.odoo_results['returns'])} return(s). "
                "Continuing automatically to Lark..."
            )
        )
    def resume_odoo_workflow(self):
        """Retry the pending return on the saved ticket, then continue to Lark."""
        if not self.odoo_checkpoint:
            messagebox.showinfo(
                "No Restore Point",
                "There is no pending Odoo return to resume.",
            )
            return
        if not self.odoo_checkpoint.get("resume_safe", False):
            messagebox.showwarning(
                "Manual Review Required",
                "This restore point is not safe for automatic retry.",
            )
            return
        if not self.browser.context:
            messagebox.showerror(
                "Browser Error",
                "Playwright browser context is unavailable.",
            )
            return

        returned_items = self.returned_items_for_odoo()
        stage = "Odoo"
        try:
            self.set_processing_buttons(True)
            self.set_status(
                "Resuming Odoo from saved ticket; retrying pending return..."
            )
            self.odoo_results = resume_odoo_returns(
                context=self.browser.context,
                order_id=self.current_order_id,
                returned_products=returned_items,
                checkpoint=self.odoo_checkpoint,
                progress_callback=self.set_status,
            )
            self.odoo_checkpoint = None
            self._render_odoo_results()
            self._persist_workflow(
                "lark_pending",
                keep_restore=True,
            )

            stage = "Lark"
            self.set_status(
                "Odoo return completed from restore point. Continuing to Lark..."
            )
            self._run_lark_submit_step()
            self.set_status(
                "Resume complete: Odoo return and Lark filing finished successfully."
            )
        except OdooWorkflowPausedError as error:
            self.odoo_results = None
            self.odoo_checkpoint = error.checkpoint
            self._render_odoo_checkpoint(str(error))
            self._persist_workflow(
                "odoo_return_pending",
                keep_restore=True,
                last_error=str(error),
            )
            self.set_status(
                "Odoo return is still pending inventory validation. Restore point kept."
            )
            messagebox.showwarning(
                "Odoo Return Still Pending",
                str(error),
            )
        except Exception as error:
            if stage == "Odoo":
                if self.odoo_checkpoint:
                    self.odoo_checkpoint["resume_safe"] = False
                    self._persist_workflow(
                        "manual_review",
                        keep_restore=True,
                        last_error=str(error),
                    )
                self.set_status(
                    "Odoo resume stopped. Manual review is required before retrying."
                )
                messagebox.showerror(
                    "Odoo Resume Error",
                    (
                        f"{error}\n\n"
                        "The existing Helpdesk ticket was preserved, but automatic "
                        "retry has been disabled because the stock-return state is "
                        "uncertain. Review Odoo before continuing."
                    ),
                )
            else:
                retry_message = (
                    "Odoo is already complete. Press Submit again to retry "
                    "Lark only; Odoo will not run again."
                )
                self._persist_workflow(
                    "lark_pending",
                    keep_restore=True,
                    last_error=str(error),
                )
                self.set_status("Lark filing failed. " + retry_message)
                messagebox.showerror(
                    "Lark Error",
                    f"{error}\n\n{retry_message}",
                )
        finally:
            self.set_processing_buttons(False)

    def _run_lark_submit_step(self):
        """File Lark after Odoo, or directly when nothing was returned."""
        self.set_status(
            "Submit 2/2: Filing Lark Item Returns..."
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
                "record(s):"
            ),
        ]
        for result in self.lark_results:
            transfer_display = (
                result["transfer_id"]
                if result.get("transfer_id")
                else "No Transfer (Not Returned)"
            )
            lines.append(
                (
                    f"{transfer_display} | "
                    f"Decision: {result['decision']} | "
                    f"{result['sku']} | "
                    f"Total QTY {result['quantity']} | "
                    f"Order/Refund Value {result['value']:.2f}"
                )
            )
        lines.extend(
            [
                "",
                "SUBMISSION COMPLETE",
            ]
        )
        self.odoo_result_label.config(
            text="\n".join(lines),
        )
        self._persist_workflow(
            "completed",
            keep_restore=False,
        )
    def submit_case(self):
        """

        Single-button workflow.

        Returned item(s):

            Submit -> Odoo -> Lark -> Done

        All Not Returned:

            Submit -> Skip Odoo -> Lark -> Done

        Mixed:

            Odoo processes Returned items, then Lark files all applicable

            records using the existing transfer-based rules.

        """
        if not self.case_decision:
            messagebox.showwarning(
                "Confirmation Required",
                "Confirm All Items before submitting.",
            )
            return
        if self.lark_results:
            messagebox.showinfo(
                "Already Submitted",
                "This order has already been filed to Lark.",
            )
            return
        if self.odoo_checkpoint:
            messagebox.showinfo(
                "Odoo Return Pending",
                (
                    "A Helpdesk ticket has already been created for this order.\n\n"
                    "Validate the related inventory transaction, then use "
                    "Retry Odoo Return & Continue."
                ),
            )
            return
        if not self.browser.context:
            messagebox.showerror(
                "Browser Error",
                "Playwright browser context is unavailable.",
            )
            return
        returned_items = self.returned_items_for_odoo()
        stage = "Odoo"
        try:
            self.set_processing_buttons(
                True
            )
            # STEP 1: Odoo only for physically returned items.
            if returned_items:
                if not self.odoo_results:
                    self._run_odoo_submit_step(
                        returned_items
                    )
                else:
                    # Retry safety: Odoo already succeeded, so retry Lark only.
                    self._render_odoo_results()
                    self.set_status(
                        (
                            "Odoo is already complete for this order. "
                            "Retrying Lark only..."
                        )
                    )
            else:
                self.odoo_results = None
                self.transfer_id_label.config(
                    text="No Odoo transfer (Not Returned)",
                )
                self.odoo_result_label.config(
                    text=(
                        "Odoo skipped: all confirmed items are Not Returned.\n"
                        "Filing directly to Lark..."
                    ),
                )
                self._persist_workflow(
                    "lark_pending",
                    keep_restore=True,
                )
            # STEP 2: Lark always follows.
            stage = "Lark"
            self._run_lark_submit_step()
            if returned_items:
                self.set_status(
                    (
                        "Submit complete: Odoo processing and Lark filing "
                        "finished successfully."
                    )
                )
            else:
                self.set_status(
                    (
                        "Submit complete: Odoo skipped and Lark filing "
                        "finished successfully."
                    )
                )
        except OdooWorkflowPausedError as error:
            self.odoo_results = None
            self.odoo_checkpoint = error.checkpoint
            self._render_odoo_checkpoint(str(error))
            self._persist_workflow(
                "odoo_return_pending",
                keep_restore=True,
                last_error=str(error),
            )
            self.set_status(
                "Odoo ticket saved; return is waiting for inventory validation."
            )
            messagebox.showwarning(
                "Odoo Return Pending",
                str(error),
            )
        except Exception as error:
            if stage == "Odoo":
                self._persist_workflow(
                    "odoo_error_manual_review",
                    keep_restore=False,
                    last_error=str(error),
                )
                self.set_status(
                    (
                        "Submit stopped: Odoo processing failed. "
                        "Lark was not filed."
                    )
                )
                self.odoo_result_label.config(
                    text=(
                        "Odoo processing failed.\n"
                        f"{error}\n\n"
                        "Lark was not filed."
                    ),
                )
                messagebox.showerror(
                    "Odoo Error",
                    str(error),
                )
            else:
                if returned_items and self.odoo_results:
                    retry_message = (
                        "Odoo is already complete. Press Submit again "
                        "to retry Lark only; Odoo will not run again."
                    )
                else:
                    retry_message = (
                        "Press Submit again to retry the Lark filing."
                    )
                self.set_status(
                    "Lark filing failed. " + retry_message
                )
                messagebox.showerror(
                    "Lark Error",
                    f"{error}\n\n{retry_message}",
                )
        finally:
            self.set_processing_buttons(
                False
            )

    # =========================================================
    # COPYABLE CASE INFORMATION

    # =========================================================
    def copy_selected_item(self, _event=None):
        """Copy the selected product table row as tab-separated values."""
        selected = self.products_table.selection()
        if not selected:
            return "break"
        values = self.products_table.item(selected[0], "values")
        if values:
            self._copy_to_clipboard("\t".join(str(value) for value in values))
        return "break"

    def copy_clicked_cell(self):
        """Copy just the value in the right-clicked table cell."""
        if self._table_copy_cell_value:
            self._copy_to_clipboard(self._table_copy_cell_value)

    def _show_item_copy_menu(self, event):
        row = self.products_table.identify_row(event.y)
        if not row:
            return
        self.products_table.selection_set(row)
        self.products_table.focus(row)
        column_number = self.products_table.identify_column(event.x)
        column_ids = self.products_table["columns"]
        self._table_copy_cell_value = ""
        if column_number.startswith("#"):
            index = int(column_number[1:]) - 1
            if 0 <= index < len(column_ids):
                self._table_copy_cell_value = str(
                    self.products_table.set(row, column_ids[index])
                )
        self._table_copy_menu.tk_popup(event.x_root, event.y_root)
        self._table_copy_menu.grab_release()

    def _copy_to_clipboard(self, value):
        self.clipboard_clear()
        self.clipboard_append(str(value))
        self.update()

    def copy_case_details(self):
        """Copy case data and results, including fields from the item table."""
        fields = [
            f"Platform: {self.current_platform}",
            f"Search By: {self.current_search_mode}",
            f"Search Input: {self.order_url_entry.get().strip()}",
            f"Order ID: {self.current_order_id or 'Not loaded'}",
            (
                f"{self.value_summary_title.cget('text')} "
                f"{self.product_value_label.cget('text')}"
            ),
            f"Odoo Transfer ID: {self.transfer_id_label.cget('text')}",
        ]
        fields.extend(["", "RETURNED ITEMS"])
        fields.append(
            "SKU\tQTY\tAmount\tClassification\tDecision\t"
            "Status\tGrade\tOdoo Tag"
        )
        for item in self.returned_products:
            fields.append("\t".join(
                str(value) for value in self.item_table_values(item)
            ))
            if item.get("remarks"):
                fields.append(f"Remarks: {item['remarks']}")
            source = item.get("source_data")
            if isinstance(source, dict):
                if source.get("return_item_ids"):
                    fields.append(
                        "Return Item IDs: " + ", ".join(source["return_item_ids"])
                    )
                if source.get("order_item_ids"):
                    fields.append(
                        "Order Item IDs: " + ", ".join(source["order_item_ids"])
                    )
                for name in (
                    "tracking_number", "return_order_id", "return_item_id",
                    "return_reason", "logistic_status", "product_name",
                ):
                    if source.get(name):
                        fields.append(f"{name}: {source[name]}")
        fields.extend([
            "", "ODOO / LARK RESULT", self.odoo_result_label.cget("text")
        ])
        self._copy_to_clipboard("\n".join(fields))
        self.set_status("Copied case details to clipboard.")

    # =========================================================
    # HELPERS

    # =========================================================
    def set_status(self, text):
        self.status_label.config(
            text=text,
        )
        self.update_idletasks()
    def set_processing_buttons(self, busy):
        self._processing_busy = bool(busy)
        self._sync_action_buttons(busy=busy)
    def on_close(self):
        try:
            self.browser.stop()
        finally:
            self.destroy()
if __name__ == "__main__":
    app = ReturnProcessorApp()
    app.mainloop()
