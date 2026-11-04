"""Searchable Tkinter scan history and safe restore-point picker.

Read-only for completed scans. A resume action is available only for entries
that still have a snapshot in restore_points.json. No Odoo/Lark side effects
happen in this window: resuming simply loads a snapshot into the main GUI.
"""

import copy
import tkinter as tk
from tkinter import ttk, messagebox
from ui_theme import (
    apply_theme, RoundedCard, RoundedButton, configure_readonly_text,
    AMBER, AMBER_TINT, TEAL_TINT, INK, MUTED, DEEP_TEAL, WHITE,
)


STATUS_LABELS = {
    "loaded": "Loaded",
    "confirmed": "Ready to submit",
    "odoo_return_pending": "Inventory pending",
    "lark_pending": "Lark pending",
    "manual_review": "Manual Odoo review",
    "odoo_error_manual_review": "Odoo error - review",
    "completed": "Completed",
}

STATUS_FILTERS = (
    "All statuses",
    "Pending / Recoverable",
    "Manual review",
    "Completed",
    "Loaded / Unconfirmed",
    "Other errors",
)


def _safe_str(value):
    return "" if value is None else str(value)


def _total_quantity(items):
    total = 0
    for item in items or []:
        try:
            total += int(item.get("quantity", 0))
        except (ValueError, TypeError, AttributeError):
            continue
    return total


def _transfer_ids(record):
    transfers = []
    for source in (
        record.get("odoo_results") or {},
        record.get("odoo_checkpoint") or {},
    ):
        for group in source.get("returns") or []:
            transfer_id = _safe_str(group.get("transfer_id")).strip()
            if transfer_id and transfer_id not in transfers:
                transfers.append(transfer_id)
    return transfers


def _display_state(record, has_restore):
    state = _safe_str(record.get("workflow_state") or "loaded")
    display = STATUS_LABELS.get(state, state.replace("_", " ").title())
    if state == "manual_review":
        return display
    if has_restore and state != "completed":
        return display
    return display


def _matching_status(record, has_restore, selected):
    state = _safe_str(record.get("workflow_state") or "loaded")
    if selected == "All statuses":
        return True
    if selected == "Pending / Recoverable":
        return has_restore and state != "completed"
    if selected == "Manual review":
        return state in {"manual_review", "odoo_error_manual_review"}
    if selected == "Completed":
        return state == "completed"
    if selected == "Loaded / Unconfirmed":
        return state == "loaded"
    if selected == "Other errors":
        return "error" in state or state == "manual_review"
    return True


def _format_details(record, has_restore):
    items = record.get("items") or []
    case = record.get("return_case") or {}
    odoo = record.get("odoo_results") or record.get("odoo_checkpoint") or {}
    transfers = _transfer_ids(record)
    state = _safe_str(record.get("workflow_state") or "loaded")
    lines = [
        "SCAN DETAILS",
        "=" * 70,
        f"Platform:           {_safe_str(record.get('platform'))}",
        f"Order ID:           {_safe_str(record.get('order_id'))}",
        f"Search by:          {_safe_str(record.get('search_by'))}",
        f"Search input:       {_safe_str(record.get('search_input'))}",
        f"Tracking number:    {_safe_str(record.get('tracking_number') or case.get('tracking_number'))}",
        f"Return/Request ID:  {_safe_str(record.get('request_id') or case.get('return_order_id') or case.get('request_id'))}",
        f"First scanned:      {_safe_str(record.get('created_at'))}",
        f"Last updated:       {_safe_str(record.get('updated_at'))}",
        f"Workflow state:     {_display_state(record, has_restore)}",
        f"Restore available:  {'Yes' if has_restore else 'No'}",
        "",
        "ITEMS",
        "-" * 70,
    ]
    if items:
        for i, item in enumerate(items, start=1):
            lines.append(
                f"{i}. SKU: {_safe_str(item.get('sku'))} | "
                f"QTY: {_safe_str(item.get('quantity'))} | "
                f"Amount: {_safe_str(item.get('amount'))}"
            )
            lines.append(
                "   Classification: " + _safe_str(item.get("classification"))
                + " | Decision: " + _safe_str(item.get("decision"))
                + " | Status: " + _safe_str(item.get("status"))
            )
            if item.get("grade") or item.get("odoo_tag"):
                lines.append(
                    "   Grade: " + _safe_str(item.get("grade"))
                    + " | Odoo tag: " + _safe_str(item.get("odoo_tag"))
                )
            if item.get("remarks"):
                lines.append("   Remarks: " + _safe_str(item.get("remarks")))
            source = item.get("source_data") or {}
            if isinstance(source, dict):
                return_ids = source.get("return_item_ids") or []
                if return_ids:
                    lines.append("   Lazada Return Item IDs: " + ", ".join(
                        _safe_str(value) for value in return_ids
                    ))
                order_item_ids = source.get("order_item_ids") or []
                if order_item_ids:
                    lines.append("   Lazada Order Item IDs: " + ", ".join(
                        _safe_str(value) for value in order_item_ids
                    ))
    else:
        lines.append("No product rows saved.")

    lines.extend([
        "",
        "ODOO / LARK PROGRESS",
        "-" * 70,
        "Odoo ticket: " + _safe_str(odoo.get("ticket_title")),
        "Odoo ticket link: " + _safe_str(odoo.get("ticket_url")),
        "Transfer IDs: " + (" | ".join(transfers) if transfers else "Not recorded"),
    ])
    checkpoint = record.get("odoo_checkpoint") or {}
    if checkpoint:
        lines.append(
            "Safe to retry stock return: "
            + ("Yes" if checkpoint.get("resume_safe") else "No - manual review required")
        )
        pending = checkpoint.get("pending_return") or {}
        if pending:
            lines.append("Pending Odoo return: " + _safe_str(pending.get("return_index")))
            for item in pending.get("items") or []:
                lines.append(
                    "   " + _safe_str(item.get("sku")) + " x "
                    + _safe_str(item.get("quantity"))
                )

    lark = record.get("lark_results") or []
    lines.append("Lark records filed: " + str(len(lark)))
    for result in lark:
        lines.append(
            "   " + _safe_str(result.get("transfer_id"))
            + " | " + _safe_str(result.get("sku"))
            + " x " + _safe_str(result.get("quantity"))
        )
    if record.get("last_error"):
        lines.extend(["", "LAST ERROR", "-" * 70, _safe_str(record["last_error"])])
    if state == "completed":
        lines.extend(["", "Completed scans are view-only and cannot be restored."])
    elif not has_restore:
        lines.extend([
            "",
            "No restore snapshot exists for this scan. View/copy details only.",
        ])
    elif checkpoint and not checkpoint.get("resume_safe", False):
        lines.extend([
            "",
            "Manual Odoo review is required. Restoring this case does NOT",
            "automatically retry any Odoo transfer.",
        ])
    return "\n".join(lines)


class HistoryRecoveryWindow(tk.Toplevel):
    """Non-modal searchable history, with selected-case recovery callback."""

    def __init__(self, master, *, store, on_restore, pending_only=False):
        super().__init__(master)
        self.store = store
        self.on_restore = on_restore
        self.rows = {}
        self.snapshots = {}
        self._details_content = ""
        self._initial_filter = "Pending / Recoverable" if pending_only else "All statuses"

        self.title("Makerlab | Scan History & Recovery")
        self.geometry("1280x775")
        self.minsize(900, 585)
        apply_theme(self)
        self._layout_mode = None
        self._layout_job = None
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build()
        self.bind("<Configure>", self._schedule_layout)
        self.after_idle(self._apply_responsive_layout)
        self.refresh_from_store()
        self.lift()
        self.search_entry.focus_set()

    def _build(self):
        outer = ttk.Frame(self, padding=(17, 15))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=3)
        outer.rowconfigure(4, weight=2)

        titlebar = ttk.Frame(outer)
        titlebar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        heading_left = ttk.Frame(titlebar)
        heading_left.pack(side="left", fill="x", expand=True)
        ttk.Label(heading_left, text="AFTERSALES  /  WORKSPACE", style="Kicker.TLabel").pack(anchor="w")
        ttk.Label(heading_left, text="Scan History & Recovery", style="Title.TLabel").pack(anchor="w")
        self.title_hint = ttk.Label(
            titlebar,
            text="Completed: view only   •   Pending: restore saved Odoo / Lark progress",
            style="Hint.TLabel",
        )
        self.title_hint.pack(side="right", padx=(12, 0))

        # Filter labels sit on the same opaque light surface as the inputs,
        # rather than inheriting unpredictable Windhawk glass colors.
        filter_panel = RoundedCard(outer, radius=18)
        filter_panel.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        filterbar = filter_panel.content
        filterbar.columnconfigure(1, weight=1)
        self.filterbar = filterbar
        self.search_filter_label = ttk.Label(filterbar, text="Search:")
        self.search_filter_label.grid(row=0, column=0, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filterbar, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.platform_filter_label = ttk.Label(filterbar, text="Platform:")
        self.platform_filter_label.grid(row=0, column=2, padx=(0, 5))
        self.platform_var = tk.StringVar(value="All platforms")
        self.platform_combo = ttk.Combobox(
            filterbar, textvariable=self.platform_var,
            values=("All platforms", "Shopee", "Lazada", "TikTok"),
            state="readonly", width=15,
        )
        self.platform_combo.grid(row=0, column=3, padx=(0, 12))
        self.status_filter_label = ttk.Label(filterbar, text="Status:")
        self.status_filter_label.grid(row=0, column=4, padx=(0, 5))
        self.status_var = tk.StringVar(value=self._initial_filter)
        self.status_combo = ttk.Combobox(
            filterbar, textvariable=self.status_var,
            values=STATUS_FILTERS, state="readonly", width=24,
        )
        self.status_combo.grid(row=0, column=5, padx=(0, 12))
        self.refresh_button = RoundedButton(filterbar, text="Refresh", command=self.refresh_from_store)
        self.refresh_button.grid(row=0, column=6)

        table_panel = RoundedCard(outer, radius=18)
        table_panel.grid(row=2, column=0, sticky="nsew")
        tree_frame = table_panel.content
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        columns = (
            "updated", "platform", "order", "tracking", "sku", "qty",
            "status", "transfer", "restore",
        )
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse",
        )
        columns_meta = {
            "updated": ("Last updated", 152),
            "platform": ("Platform", 80),
            "order": ("Order ID", 170),
            "tracking": ("Tracking / Search", 165),
            "sku": ("SKUs", 170),
            "qty": ("QTY", 48),
            "status": ("Workflow status", 150),
            "transfer": ("TC/IN Transfer", 135),
            "restore": ("Recovery", 80),
        }
        for key, (label, width) in columns_meta.items():
            self.tree.heading(key, text=label, command=lambda col=key: self._sort_by(col))
            self.tree.column(
                key, width=width, minwidth=45,
                anchor="center" if key in {"qty", "restore"} else "w",
                stretch=key in {"order", "sku", "status"},
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        hscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        self.tree.tag_configure("pending", background=AMBER_TINT, foreground=INK)
        self.tree.tag_configure("complete", foreground=MUTED)
        self.tree.tag_configure("review", background="#FBE8E7", foreground=INK)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.count_label = ttk.Label(outer, text="", style="Kicker.TLabel")
        self.count_label.grid(row=3, column=0, sticky="w", pady=(6, 7))

        details_panel = RoundedCard(outer, title="CASE DETAILS  /  SELECT AND COPY")
        details_panel.grid(row=4, column=0, sticky="nsew")
        details_frame = details_panel.content
        details_frame.rowconfigure(0, weight=1)
        details_frame.columnconfigure(0, weight=1)
        self.details = tk.Text(
            details_frame, wrap="word", font=("Consolas", 10),
            height=11, relief="flat", state="disabled", padx=7, pady=7,
        )
        self.details.grid(row=0, column=0, sticky="nsew")
        configure_readonly_text(self.details, detail=True)
        details_scroll = ttk.Scrollbar(details_frame, orient="vertical", command=self.details.yview)
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=details_scroll.set)
        self.details.bind("<Control-a>", self._select_all_details)
        self.details.bind("<Control-A>", self._select_all_details)

        bottom = ttk.Frame(outer)
        bottom.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        self.action_hint = ttk.Label(bottom, text="Select a scan to inspect it.", style="Hint.TLabel")
        self.action_hint.pack(side="left")
        RoundedButton(bottom, text="Close", surface="dark", command=self.destroy).pack(side="right", padx=(8, 0))
        RoundedButton(bottom, text="Copy Details", surface="dark", command=self._copy_details).pack(side="right", padx=(8, 0))
        self.restore_button = RoundedButton(
            bottom, kind="teal", surface="dark", text="Restore Selected",
            command=self._attempt_restore, state="disabled",
        )
        self.restore_button.pack(side="right")

        self.search_var.trace_add("write", lambda *_args: self._apply_filters())
        self.platform_var.trace_add("write", lambda *_args: self._apply_filters())
        self.status_var.trace_add("write", lambda *_args: self._apply_filters())

    def _schedule_layout(self, event):
        if event.widget is not self:
            return
        if self._layout_job is not None:
            self.after_cancel(self._layout_job)
        self._layout_job = self.after(90, self._apply_responsive_layout)

    def _apply_responsive_layout(self):
        self._layout_job = None
        if not hasattr(self, "filterbar"):
            return
        mode = "wide" if self.winfo_width() >= 1130 else "compact"
        if self._layout_mode == mode:
            return
        self._layout_mode = mode
        widgets = (
            self.search_filter_label, self.search_entry,
            self.platform_filter_label, self.platform_combo,
            self.status_filter_label, self.status_combo,
            self.refresh_button,
        )
        for widget in widgets:
            widget.grid_forget()
        if mode == "wide":
            self.filterbar.columnconfigure(1, weight=1)
            self.filterbar.columnconfigure(3, weight=0)
            self.search_filter_label.grid(row=0, column=0, padx=(0, 5))
            self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12))
            self.platform_filter_label.grid(row=0, column=2, padx=(0, 5))
            self.platform_combo.grid(row=0, column=3, padx=(0, 12))
            self.status_filter_label.grid(row=0, column=4, padx=(0, 5))
            self.status_combo.grid(row=0, column=5, padx=(0, 12))
            self.refresh_button.grid(row=0, column=6)
            self.title_hint.pack(side="right", padx=(12, 0)) if not self.title_hint.winfo_manager() else None
        else:
            self.filterbar.columnconfigure(1, weight=1)
            self.search_filter_label.grid(row=0, column=0, padx=(0, 5))
            self.search_entry.grid(row=0, column=1, columnspan=4, sticky="ew", padx=(0, 12))
            self.refresh_button.grid(row=0, column=6, sticky="e")
            self.platform_filter_label.grid(row=1, column=0, pady=(9, 0))
            self.platform_combo.grid(row=1, column=1, sticky="w", pady=(9, 0))
            self.status_filter_label.grid(row=1, column=2, padx=(12, 5), pady=(9, 0))
            self.status_combo.grid(row=1, column=3, sticky="w", pady=(9, 0))
            self.title_hint.pack_forget()

    def refresh_from_store(self):
        """Reload the JSON files; keep the user's current selection if possible."""
        try:
            history = self.store.list_recent_scans(limit=None)
            points = self.store.list_restore_points()
        except Exception as error:
            messagebox.showerror("History Error", str(error), parent=self)
            return
        self.snapshots = {
            _safe_str(point.get("scan_id")): copy.deepcopy(point)
            for point in points if point.get("scan_id")
        }
        self.rows = {
            _safe_str(scan.get("scan_id")): copy.deepcopy(scan)
            for scan in history if scan.get("scan_id")
        }
        # A recoverable case must remain visible even if the history file was
        # repaired or an earlier scan-history write failed.
        for scan_id, point in self.snapshots.items():
            if scan_id not in self.rows:
                self.rows[scan_id] = copy.deepcopy(point)
                self.rows[scan_id].setdefault("scan_id", scan_id)
            else:
                # Snapshots are the source of truth for the latest resume state.
                self.rows[scan_id].update({
                    key: copy.deepcopy(value)
                    for key, value in point.items()
                    if key not in {"scan_id", "created_at"}
                })
        self._apply_filters()

    def _apply_filters(self):
        if not hasattr(self, "tree"):
            return
        selected_id = self.tree.selection()[0] if self.tree.selection() else None
        query = self.search_var.get().strip().casefold()
        platform = self.platform_var.get()
        status_filter = self.status_var.get()
        matching = []
        for scan_id, record in self.rows.items():
            has_restore = scan_id in self.snapshots
            if platform != "All platforms" and record.get("platform") != platform:
                continue
            if not _matching_status(record, has_restore, status_filter):
                continue
            if query:
                items = record.get("items") or []
                searchable = " ".join([
                    _safe_str(record.get("order_id")),
                    _safe_str(record.get("search_input")),
                    _safe_str(record.get("tracking_number")),
                    _safe_str(record.get("request_id")),
                    _safe_str(record.get("platform")),
                    _safe_str(record.get("workflow_state")),
                    _safe_str((record.get("odoo_results") or record.get("odoo_checkpoint") or {}).get("ticket_title")),
                    " ".join(_safe_str(item.get("sku")) for item in items),
                    " ".join(_transfer_ids(record)),
                ]).casefold()
                if query not in searchable:
                    continue
            matching.append((scan_id, record, has_restore))
        matching.sort(key=lambda entry: _safe_str(entry[1].get("updated_at")), reverse=True)
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for scan_id, record, has_restore in matching:
            items = record.get("items") or []
            sku_list = list(dict.fromkeys(_safe_str(i.get("sku")) for i in items if i.get("sku")))
            sku_preview = ", ".join(sku_list[:3])
            if len(sku_list) > 3:
                sku_preview += f" (+{len(sku_list) - 3})"
            case = record.get("return_case") or {}
            tracking = record.get("tracking_number") or case.get("tracking_number") or record.get("search_input")
            transfers = _transfer_ids(record)
            state = _safe_str(record.get("workflow_state"))
            tags = ()
            if state in {"manual_review", "odoo_error_manual_review"}:
                tags = ("review",)
            elif state == "completed":
                tags = ("complete",)
            elif has_restore:
                tags = ("pending",)
            self.tree.insert("", "end", iid=scan_id, values=(
                _safe_str(record.get("updated_at")).replace("T", " ")[:19],
                record.get("platform", ""),
                record.get("order_id", ""),
                tracking or "",
                sku_preview,
                _total_quantity(items),
                _display_state(record, has_restore),
                " | ".join(transfers),
                "Yes" if has_restore and state != "completed" else "No",
            ), tags=tags)
        count_pending = sum(1 for scan_id in self.rows if scan_id in self.snapshots)
        self.count_label.config(
            text=f"Showing {len(matching)} scan(s)  |  "
                 f"{len(self.rows)} saved scan(s)  |  {count_pending} recoverable case(s)"
        )
        if selected_id and self.tree.exists(selected_id):
            self.tree.selection_set(selected_id)
            self.tree.focus(selected_id)
        elif matching:
            self.tree.selection_set(matching[0][0])
            self.tree.focus(matching[0][0])
        self._on_select()

    def _selected_id(self):
        chosen = self.tree.selection()
        return chosen[0] if chosen else None

    def _on_select(self, _event=None):
        scan_id = self._selected_id()
        record = self.rows.get(scan_id) if scan_id else None
        if not record:
            self._set_details("Select a scan above to view its saved information.")
            self.restore_button.config(state="disabled", text="Restore Selected")
            self.action_hint.config(text="Select a scan to inspect it.")
            return
        has_restore = scan_id in self.snapshots
        self._set_details(_format_details(record, has_restore))
        state = _safe_str(record.get("workflow_state"))
        if has_restore and state != "completed":
            checkpoint = record.get("odoo_checkpoint") or {}
            manual = bool(checkpoint) and not checkpoint.get("resume_safe", False)
            self.restore_button.config(
                state="normal",
                text="Restore for Review" if manual else "Restore Selected",
            )
            self.action_hint.config(
                text=("Odoo requires manual review." if manual else "Restore the selected pending workflow.")
            )
        else:
            self.restore_button.config(state="disabled", text="Restore Selected")
            self.action_hint.config(text="View/copy only. No active restore point.")

    def _set_details(self, text):
        self._details_content = text
        self.details.config(state="normal")
        self.details.delete("1.0", tk.END)
        self.details.insert("1.0", text)
        self.details.config(state="disabled")

    def _select_all_details(self, _event=None):
        self.details.tag_add(tk.SEL, "1.0", "end-1c")
        self.details.mark_set(tk.INSERT, "1.0")
        return "break"

    def _copy_details(self):
        if not self._details_content:
            return
        try:
            value = self.details.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            value = self._details_content
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update_idletasks()

    def _attempt_restore(self):
        scan_id = self._selected_id()
        if not scan_id or scan_id not in self.snapshots:
            return
        record = self.rows.get(scan_id, {})
        if record.get("workflow_state") == "completed":
            return
        if self.on_restore(scan_id):
            self.destroy()
        else:
            self.refresh_from_store()

    def _sort_by(self, column):
        """Sort the visible table; click again for the opposite direction."""
        old_col = getattr(self, "_sort_column", "updated")
        descending = not getattr(self, "_sort_descending", True) if column == old_col else False
        self._sort_column, self._sort_descending = column, descending
        contents = list(self.tree.get_children())
        values = [(self.tree.set(iid, column).casefold(), iid) for iid in contents]
        if column == "qty":
            values = [(int(value or 0), iid) for value, iid in values]
        values.sort(reverse=descending)
        for index, (_value, iid) in enumerate(values):
            self.tree.move(iid, "", index)
