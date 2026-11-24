"""Searchable Tkinter scan history and safe restore-point picker.

Edit, archive, reset or permanently delete local scan records. Destructive
operations on Odoo/Lark-linked records require explicit, typed confirmation.
Nothing in this window deletes external Odoo tickets or Lark records.
Restoring simply loads the saved checkpoint into the main GUI.
"""

import copy
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from workflow_store import (
    has_external_work, NEW_STOCK_DESTINATIONS,
)
from ui_theme import (
    apply_theme, RoundedCard, RoundedButton, configure_readonly_text,
    AMBER, AMBER_TINT, TEAL_TINT, INK, MUTED, DEEP_TEAL, WHITE,
)


STATUS_LABELS = {
    "loaded": "Loaded",
    "manually_saved": "Saved for recovery",
    "manual_odoo_entered": "Manual Odoo details saved",
    "confirmed": "Ready to submit",
    "odoo_ticket_created": "Odoo ticket saved",
    "odoo_ticket_setup_pending": "Ticket setup pending",
    "odoo_ticket_ready": "Ticket ready / return pending",
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
    "Archived records",
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
    if record.get("archived"):
        return "Archived / " + STATUS_LABELS.get(state, state.replace("_", " ").title())
    display = STATUS_LABELS.get(state, state.replace("_", " ").title())
    if state == "manual_review":
        return display
    if has_restore and state != "completed":
        return display
    return display


def _matching_status(record, has_restore, selected):
    if selected == "Archived records":
        return bool(record.get("archived"))
    if record.get("archived"):
        return False
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
        return state in {"loaded", "manually_saved"}
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
        f"Archived:           {'Yes' if record.get('archived') else 'No'}",
        f"Archived at:        {_safe_str(record.get('archived_at'))}",
        f"New stock location: {_safe_str(record.get('new_stock_destination') or 'MNL/Stock')}",
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
            if item.get("classification") in {"Wrong Item", "Scam"}:
                lines.append("   Received Item: " + _safe_str(item.get("received_item")))
                lines.append("   Wrong Item Status: " + _safe_str(item.get("wrong_item_status")))
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
    for entry in (checkpoint.get("returns") or []):
        if entry.get("transfer_id"):
            lines.append(
                "   TC/IN #" + str(entry.get("return_index") or "") + ": "
                + _safe_str(entry.get("transfer_id")) + " | "
                + _safe_str(entry.get("transfer_url"))
            )
    if checkpoint.get("manual_entry"):
        lines.append("Manual entry: YES (operator supplied; not Odoo-verified)")
        lines.append("Manual note: " + _safe_str(checkpoint["manual_entry"].get("reason")))
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
    partial_normal = record.get("normal_lark_results") or []
    partial_wrong = record.get("wrong_item_lark_results") or []
    lines.append("Lark records completed: " + str(len(lark)))
    if partial_normal or partial_wrong:
        lines.append("Lark Item Returns checkpoints: " + str(len(partial_normal)))
        lines.append("Wrong Item / Scam checkpoints: " + str(len(partial_wrong)))
    for result in lark or (partial_normal + partial_wrong):
        lines.append(
            "   " + _safe_str(result.get("lark_base") or "Item Returns")
            + " | " + _safe_str(result.get("transfer_id") or "No Odoo")
            + " | " + _safe_str(result.get("sku"))
            + " x " + _safe_str(result.get("quantity"))
        )
    if record.get("operator_notes"):
        lines.extend(["", "INTERNAL NOTES (LOCAL ONLY)", "-" * 70,
                      _safe_str(record.get("operator_notes"))])
    if record.get("edit_history"):
        lines.append(f"History edits: {len(record.get('edit_history') or [])}")
    for event in record.get("duplicate_override_events") or []:
        lines.extend([
            "", "SEPARATE TICKET EXCEPTION - LOCAL AUDIT", "-" * 70,
            "Recorded: " + _safe_str(event.get("at")),
            "Prior scan: " + _safe_str(event.get("prior_scan_id")),
            "Prior ticket: " + _safe_str(event.get("prior_ticket_url")),
            "Reason: " + _safe_str(event.get("reason")),
        ])
    if record.get("last_error"):
        lines.extend(["", "LAST ERROR", "-" * 70, _safe_str(record["last_error"])])
    if record.get("archived"):
        lines.extend([
            "", "This scan is archived. Its previous Odoo ticket remains protected.",
            "Use Unarchive / Recover to review the existing transaction.",
            "An Odoo-linked record can only reopen in manual-review mode.",
        ])
    elif state == "completed":
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

    def __init__(self, master, *, store, on_restore, pending_only=False, on_record_changed=None):
        super().__init__(master)
        self.store = store
        self.on_restore = on_restore
        self.on_record_changed = on_record_changed
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
        self._layout_job = self.after_idle(self._apply_responsive_layout)
        self.refresh_from_store()
        self.lift()
        self.search_entry.focus_set()

    def destroy(self):
        job = getattr(self, "_layout_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
            self._layout_job = None
        super().destroy()

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
            text="Archived records remain searchable   •   Delete affects local JSON only",
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
        self.tree.tag_configure("archived", foreground=MUTED, background="#E5ECEF")
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
        self.action_hint = ttk.Label(
            bottom, text="Select a scan to inspect it.", style="Hint.TLabel"
        )
        self.action_hint.pack(side="top", anchor="w", pady=(0, 5))
        action_row = ttk.Frame(bottom)
        action_row.pack(fill="x")
        RoundedButton(action_row, text="Close", surface="dark", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        RoundedButton(action_row, text="Copy Details", surface="dark", command=self._copy_details).pack(
            side="right", padx=(8, 0)
        )
        self.restore_button = RoundedButton(
            action_row, kind="teal", surface="dark", text="Restore Selected",
            command=self._attempt_restore, state="disabled",
        )
        self.restore_button.pack(side="right", padx=(8, 0))
        self.edit_button = RoundedButton(
            action_row, surface="dark", text="Edit Selected",
            command=self._attempt_edit, state="disabled",
        )
        self.edit_button.pack(side="right", padx=(8, 0))
        maintenance_row = ttk.Frame(bottom)
        maintenance_row.pack(fill="x", pady=(7, 0))
        self.delete_button = RoundedButton(
            maintenance_row, surface="dark", text="Delete Local Record",
            command=self._attempt_delete, state="disabled",
        )
        self.delete_button.pack(side="right", padx=(8, 0))
        self.reset_odoo_button = RoundedButton(
            maintenance_row, surface="dark", text="Reset Odoo for Re-submit",
            command=self._attempt_reset_odoo, state="disabled",
        )
        self.reset_odoo_button.pack(side="left", padx=(0, 8))
        self.make_recoverable_button = RoundedButton(
            action_row, surface="dark", text="Make Recoverable",
            command=self._attempt_make_recoverable, state="disabled",
        )
        self.make_recoverable_button.pack(side="left", padx=(0, 8))
        self.manual_odoo_button = RoundedButton(
            action_row, kind="teal", surface="dark",
            text="Enter Manual Odoo / TC-IN",
            command=self._attempt_manual_odoo_entry, state="disabled",
        )
        self.manual_odoo_button.pack(side="left", padx=(0, 8))
        self.archive_button = RoundedButton(
            maintenance_row, surface="dark", text="Archive Selected",
            command=self._attempt_archive, state="disabled",
        )
        self.archive_button.pack(side="right", padx=(8, 0))
        self.unarchive_button = RoundedButton(
            maintenance_row, surface="dark", text="Unarchive / Recover",
            command=self._attempt_unarchive, state="disabled",
        )
        self.unarchive_button.pack(side="right", padx=(8, 0))

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
            for point in points if point.get("scan_id") and not point.get("archived")
        }
        archived_ids = {
            _safe_str(scan.get("scan_id"))
            for scan in history if scan.get("archived") and scan.get("scan_id")
        }
        self.snapshots = {
            key: snapshot for key, snapshot in self.snapshots.items()
            if key not in archived_ids
        }
        # Keep archived records in self.rows so the operator can search and
        # unarchive them through the Archived records filter.
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
            if record.get("archived"):
                tags = ("archived",)
            elif state in {"manual_review", "odoo_error_manual_review"}:
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
        count_archived = sum(1 for record in self.rows.values() if record.get("archived"))
        self.count_label.config(
            text=f"Showing {len(matching)} scan(s)  |  "
                 f"{len(self.rows) - count_archived} active  |  "
                 f"{count_archived} archived  |  {count_pending} recoverable"
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
            self.edit_button.config(state="disabled")
            self.delete_button.config(state="disabled")
            self.reset_odoo_button.config(state="disabled")
            self.make_recoverable_button.config(state="disabled")
            self.manual_odoo_button.config(state="disabled")
            self.archive_button.config(state="disabled")
            self.unarchive_button.config(state="disabled")
            self.action_hint.config(text="Select a scan to inspect it.")
            return
        has_restore = scan_id in self.snapshots
        self._set_details(_format_details(record, has_restore))
        archived = bool(record.get("archived"))
        protected = has_external_work(record, self.snapshots.get(scan_id))
        self.edit_button.config(state="normal")  # Archived: notes only.
        self.delete_button.config(state="normal")
        eligible = (not archived and _safe_str(record.get("workflow_state")) != "completed"
                    and not record.get("lark_results"))
        self.make_recoverable_button.config(
            state="normal" if eligible and not has_restore else "disabled"
        )
        self.manual_odoo_button.config(
            state=("normal" if eligible and not record.get("odoo_results")
                   and any(item.get("status") == "Returned"
                           for item in (record.get("items") or [])) else "disabled")
        )
        self.reset_odoo_button.config(
            state=("normal" if not archived and has_restore and protected
                   and _safe_str(record.get("workflow_state")) != "completed"
                   and not record.get("lark_results")
                   and (record.get("odoo_checkpoint") or record.get("odoo_results"))
                   else "disabled")
        )
        self.archive_button.config(state="disabled" if archived else "normal")
        self.unarchive_button.config(state="normal" if archived else "disabled")
        state = _safe_str(record.get("workflow_state"))
        if archived:
            self.restore_button.config(state="disabled", text="Restore Selected")
            self.action_hint.config(text="Archived: view, unarchive, or permanently delete this LOCAL record.")
            return
        if has_restore and state != "completed":
            checkpoint = record.get("odoo_checkpoint") or {}
            manual = bool(checkpoint) and not checkpoint.get("resume_safe", False)
            self.restore_button.config(
                state="normal",
                text="Restore for Review" if manual else "Restore Selected",
            )
            self.action_hint.config(
                text=("Odoo review: use Reset Odoo for Re-submit only AFTER external cleanup."
                      if manual else "Restore the selected pending workflow.")
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

    def _notify_change(self, scan_id, action):
        try:
            if self.on_record_changed:
                self.on_record_changed(scan_id, action)
        except Exception as error:
            messagebox.showwarning(
                "Record Saved - Workspace Refresh Failed",
                "The JSON change was saved, but the main workspace could not "
                f"refresh automatically: {error}. Reload the case before working.",
                parent=self,
            )
        self.refresh_from_store()

    def _confirm_active_workspace_change(self, scan_id):
        current = getattr(self.master, "current_scan_id", None)
        if current != scan_id:
            return True
        return messagebox.askyesno(
            "Current Workspace Case",
            "This scan is currently open in the main processor. Editing or "
            "deleting it may discard unsaved on-screen changes. Continue?",
            parent=self,
        )

    def _attempt_edit(self):
        scan_id = self._selected_id()
        if not scan_id or scan_id not in self.rows:
            return
        SavedScanEditor(
            self,
            store=self.store,
            scan_id=scan_id,
            record=copy.deepcopy(self.rows[scan_id]),
            on_saved=lambda: self._notify_change(scan_id, "edited"),
            before_save=lambda: self._confirm_active_workspace_change(scan_id),
        )

    def _attempt_make_recoverable(self):
        scan_id = self._selected_id()
        record = self.rows.get(scan_id) if scan_id else None
        if not record:
            return
        if not messagebox.askyesno(
            "Make Scan Recoverable",
            f"Save order {record.get('order_id')} to active Recovery?\n\n"
            "No Odoo or Lark action will run. Any previously created Odoo "
            "ticket/stock transfer remains protected from re-submission.",
            parent=self,
        ) or not self._confirm_active_workspace_change(scan_id):
            return
        try:
            self.store.make_scan_recoverable(scan_id)
            self._notify_change(scan_id, "made_recoverable")
            messagebox.showinfo(
                "Recovery Saved",
                "This scan is now available in Recovery. You can enter "
                "manual Helpdesk and TC/IN links, or restore it for review.",
                parent=self,
            )
        except Exception as error:
            messagebox.showerror("Recovery Save Failed", str(error), parent=self)

    def _attempt_manual_odoo_entry(self):
        scan_id = self._selected_id()
        record = self.rows.get(scan_id) if scan_id else None
        if not record:
            return
        try:
            # This is a non-destructive action; it never clears prior Odoo work.
            if scan_id not in self.snapshots:
                if not messagebox.askyesno(
                    "Create Recovery for Manual Odoo Entry",
                    "This scan does not yet have an active Recovery snapshot. "
                    "Create it now and then enter existing Odoo details?",
                    parent=self,
                ) or not self._confirm_active_workspace_change(scan_id):
                    return
                self.store.make_scan_recoverable(scan_id)
                self._notify_change(scan_id, "made_recoverable")
            snapshot = self.store.get_restore_point(scan_id)
            if not snapshot:
                raise RuntimeError("Recovery could not be loaded after saving.")
            ManualOdooEntryDialog(
                self, store=self.store, scan_id=scan_id, record=snapshot,
                before_save=lambda: self._confirm_active_workspace_change(scan_id),
                on_saved=lambda: self._manual_odoo_record_saved(scan_id),
            )
        except Exception as error:
            messagebox.showerror("Manual Odoo Entry Unavailable", str(error), parent=self)

    def _manual_odoo_record_saved(self, scan_id):
        self._notify_change(scan_id, "manual_odoo_entered")
        messagebox.showinfo(
            "Manual TC/IN Saved",
            "The ticket and transfer details are saved in Recovery.\n\n"
            "Select Restore for Review, then use the main app's "
            "Confirm Existing TC/IN & File Lark button. Lark filing still "
            "requires your confirmation and does not run Odoo.",
            parent=self,
        )

    def _attempt_delete(self):
        scan_id = self._selected_id()
        record = self.rows.get(scan_id) if scan_id else None
        if not record:
            return
        protected = has_external_work(record, self.snapshots.get(scan_id))
        order_id = _safe_str(record.get("order_id")).strip()
        odoo = record.get("odoo_checkpoint") or record.get("odoo_results") or {}
        transfer_ids = _transfer_ids(record)
        typed_order = ""
        confirmation = ""
        if protected:
            if not messagebox.askyesno(
                "Permanently Delete Local Scan - EXTERNAL WORK EXISTS",
                f"Order: {order_id}\n"
                f"Odoo ticket: {odoo.get('ticket_title') or '(recorded)'}\n"
                f"TC/IN: {', '.join(transfer_ids) or '(check Odoo)'}\n\n"
                "This will PERMANENTLY REMOVE this case from the app's active "
                "Scan History and Recovery JSON, including its local duplicate "
                "protection. It will NOT delete the Odoo ticket, stock "
                "transfers, approvals, or any Lark records.\n\n"
                "Before filing the order again, you must independently "
                "delete/cancel and verify all prior external transactions "
                "to avoid duplicates. Continue with local deletion?",
                parent=self,
            ):
                return
            typed_order = simpledialog.askstring(
                "Confirm Local Record Deletion",
                f"Type the exact Order ID to delete its local record:\n{order_id}",
                parent=self,
            )
            if typed_order is None:
                return
            confirmation = simpledialog.askstring(
                "Final Permanent Delete Confirmation",
                "Type DELETE LOCAL RECORD (exactly):",
                parent=self,
            )
            if confirmation is None:
                return
        else:
            if not messagebox.askyesno(
                "Permanently Delete Local Scan",
                f"Delete the saved scan for {order_id or scan_id}?\n\n"
                "Both local History and Recovery entries will be removed. "
                "This cannot be undone from the app.",
                parent=self,
            ):
                return
        if not self._confirm_active_workspace_change(scan_id):
            return
        try:
            self.store.permanently_delete_saved_record(
                scan_id, typed_order_id=typed_order,
                confirmation=confirmation,
                external_acknowledged=bool(protected),
            )
            self._notify_change(scan_id, "deleted")
            messagebox.showinfo(
                "Local Record Deleted",
                "The local Scan History and Recovery entries were deleted. "
                "No Odoo or Lark records were changed. Before re-submission, "
                "verify that the previous external transactions are removed "
                "or cancelled.", parent=self,
            )
        except Exception as error:
            messagebox.showerror("Cannot Delete Local Record", str(error), parent=self)

    def _attempt_reset_odoo(self):
        scan_id = self._selected_id()
        record = self.rows.get(scan_id) if scan_id else None
        if not record or scan_id not in self.snapshots or record.get("archived"):
            return
        order_id = _safe_str(record.get("order_id")).strip()
        if not messagebox.askyesno(
            "Reset Old Odoo Checkpoint for NEW Submission",
            f"Order: {order_id}\n\n"
            "This is NOT the normal Recovery action. Use it ONLY after you "
            "have manually deleted/cancelled and verified the previous Odoo "
            "Helpdesk ticket and all linked TC/IN transfers, and checked that "
            "no Lark record was filed.\n\n"
            "The old Odoo checkpoint will be cleared from local JSON. "
            "The scan, SKUs, quantities, decisions and remarks will be kept, "
            "but Confirm All Items must be repeated. Continue?",
            parent=self,
        ):
            return
        typed_order = simpledialog.askstring(
            "Confirm Odoo Cleanup", "Type the exact Order ID:\n" + order_id,
            parent=self,
        )
        if typed_order is None:
            return
        confirmation = simpledialog.askstring(
            "Confirm New Odoo Submission", "Type RESET ODOO (exactly):",
            parent=self,
        )
        if confirmation is None or not self._confirm_active_workspace_change(scan_id):
            return
        try:
            self.store.reset_saved_scan_for_resubmission(
                scan_id, typed_order_id=typed_order,
                confirmation=confirmation, external_acknowledged=True,
            )
            self._notify_change(scan_id, "reset_for_resubmission")
            if getattr(self.master, "current_scan_id", None) != scan_id:
                # Let the operator load the newly cleaned scan without a fresh
                # marketplace search. A different active case stays protected.
                if messagebox.askyesno(
                    "Odoo Checkpoint Reset",
                    "The local checkpoint was reset. Load this saved scan now "
                    "to review its items and Confirm All Items again?",
                    parent=self,
                ):
                    if self.on_restore(scan_id):
                        self.destroy()
                        return
            else:
                messagebox.showinfo(
                    "Ready to Review and Re-confirm",
                    "The existing scan is now a local draft without an Odoo "
                    "checkpoint. Review it and click Confirm All Items to "
                    "re-enable Submit to Odoo + Lark.", parent=self,
                )
                self.destroy()
        except Exception as error:
            messagebox.showerror("Odoo Reset Blocked", str(error), parent=self)

    def _attempt_archive(self):
        scan_id = self._selected_id()
        record = self.rows.get(scan_id) if scan_id else None
        if not record or record.get("archived"):
            return
        if not messagebox.askyesno(
            "Archive Scan",
            f"Archive order {record.get('order_id') or scan_id}?\n\n"
            "The scan will be hidden from active History and Recovery, but "
            "remains available under Archived records. Existing Odoo/Lark "
            "identifiers will stay protected. No external transaction is changed.",
            parent=self,
        ) or not self._confirm_active_workspace_change(scan_id):
            return
        try:
            self.store.archive_saved_record(scan_id)
            self._notify_change(scan_id, "archived")
            messagebox.showinfo(
                "Scan Archived", "Use Status > Archived records to view and reopen it.",
                parent=self,
            )
        except Exception as error:
            messagebox.showerror("Archive Failed", str(error), parent=self)

    def _attempt_unarchive(self):
        scan_id = self._selected_id()
        record = self.rows.get(scan_id) if scan_id else None
        if not record or not record.get("archived"):
            return
        if not messagebox.askyesno(
            "Unarchive Existing Scan",
            f"Make order {record.get('order_id') or scan_id} visible again?\n\n"
            "Previously created Odoo tickets and transfers remain protected. "
            "Recovery of externally processed cases is restricted to manual "
            "review; this never creates a new ticket or clicks Validate.",
            parent=self,
        ):
            return
        try:
            result = self.store.reactivate_archived_record(scan_id)
            self.status_var.set("All statuses")
            self._notify_change(scan_id, "unarchived")
            self.focus_record(scan_id)
            if result["recoverable"]:
                if messagebox.askyesno(
                    "Recovery Reopened",
                    "The original scan is visible and a review-safe Recovery "
                    "snapshot has been restored. Load it into the processor now?",
                    parent=self,
                ):
                    if self.on_restore(scan_id):
                        self.destroy()
            else:
                messagebox.showinfo(
                    "Archived Scan Restored to History",
                    "This scan is now visible in History but no automatic "
                    "Recovery was opened. It was completed or lacks enough "
                    "verified saved information for safe restoration. "
                    "Inspect its original Odoo/Lark record.", parent=self,
                )
        except Exception as error:
            messagebox.showerror("Unarchive Failed", str(error), parent=self)

    def focus_record(self, scan_id):
        """Navigate from the duplicate warning to a specific stored scan."""
        record = self.store.get_scan(scan_id)
        if not record:
            return False
        self.status_var.set("Archived records" if record.get("archived") else "All statuses")
        self.platform_var.set("All platforms")
        self.search_var.set("")
        self.refresh_from_store()
        if self.tree.exists(scan_id):
            self.tree.selection_set(scan_id)
            self.tree.focus(scan_id)
            self.tree.see(scan_id)
            self._on_select()
            self.lift()
            return True
        return False

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



class DuplicateTicketResolutionDialog(tk.Toplevel):
    """Human-reviewed, one-off duplicate resolution; never auto-submits."""

    def __init__(self, master, *, order_id, platform, previous):
        super().__init__(master)
        self.order_id = str(order_id)
        self.previous = previous
        self.choice = "cancel"
        self.reason = ""
        self.typed_order_id = ""
        self.confirmation = ""
        self.title("Resolve Existing Odoo Ticket")
        self.geometry("750x580")
        self.minsize(670, 515)
        self.transient(master)
        self.grab_set()
        apply_theme(self)
        container = RoundedCard(self, title="EXISTING ODOO TICKET / DUPLICATE PROTECTION")
        container.pack(fill="both", expand=True, padx=14, pady=12)
        panel = container.content
        ticket = previous.get("odoo_checkpoint") or previous.get("odoo_results") or {}
        ttk.Label(panel, text=f"{platform}  |  Order {order_id}",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 7))
        ttk.Label(panel, text="Existing ticket: " + str(ticket.get("ticket_title") or "Recorded in History"),
                  wraplength=680).pack(anchor="w")
        ttk.Label(panel, text=str(ticket.get("ticket_url") or "Ticket link not saved"),
                  wraplength=680).pack(anchor="w", pady=(2, 8))
        ttk.Label(panel, text=(
            "An existing Odoo transaction was recorded. Inspect it or recover "
            "the saved case instead of generating a duplicate. A new ticket is "
            "permitted ONLY for a verified, separate return and is recorded in the audit log."
        ), wraplength=680).pack(anchor="w", pady=(0, 11))
        fields = ttk.Frame(panel, style="Card.TFrame")
        fields.pack(fill="x")
        ttk.Label(fields, text="Reason for a distinct NEW ticket (minimum 15 characters):").pack(anchor="w")
        self.reason_entry = tk.Text(fields, height=3, wrap="word", font=("Segoe UI", 10))
        configure_readonly_text(self.reason_entry, detail=True)
        self.reason_entry.pack(fill="x", pady=(3, 7))
        ttk.Label(fields, text="Re-enter the exact Order ID:").pack(anchor="w")
        self.order_entry = ttk.Entry(fields)
        self.order_entry.pack(fill="x", pady=(3, 7))
        ttk.Label(fields, text="Type CREATE SEPARATE TICKET:").pack(anchor="w")
        self.attest_entry = ttk.Entry(fields)
        self.attest_entry.pack(fill="x", pady=(3, 11))
        buttons = ttk.Frame(panel, style="Card.TFrame")
        buttons.pack(fill="x", side="bottom")
        RoundedButton(buttons, text="Cancel", command=self._cancel).pack(side="right", padx=(5, 0))
        RoundedButton(buttons, text="Create Separate Ticket", command=self._new_ticket).pack(side="right", padx=(5, 0))
        RoundedButton(buttons, text="Recover Existing", command=lambda: self._choose("recover")).pack(
            side="left", padx=(0, 5))
        RoundedButton(buttons, text="Inspect Existing", command=lambda: self._choose("inspect")).pack(
            side="left", padx=(0, 5))
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after_idle(self.reason_entry.focus_set)

    def _cancel(self):
        self.choice = "cancel"
        self.destroy()

    def _choose(self, choice):
        self.choice = choice
        self.destroy()

    def _new_ticket(self):
        reason = self.reason_entry.get("1.0", "end-1c").strip()
        typed = self.order_entry.get().strip()
        phrase = self.attest_entry.get().strip()
        if len(reason) < 15 or typed != self.order_id or phrase != "CREATE SEPARATE TICKET":
            messagebox.showerror(
                "Confirmation Incomplete",
                "A separate ticket requires a specific reason (15+ characters), "
                "the exact Order ID, and the confirmation phrase CREATE SEPARATE TICKET.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Confirm New Odoo Ticket Exception",
            "Have you reviewed the earlier Odoo ticket and any associated transfers, "
            "verified this is a separate return requiring a NEW Helpdesk ticket, "
            "and checked that this filing does not duplicate any existing Lark record?\n\n"
            "Your reason and previous ticket link will be saved in the local audit.",
            parent=self,
        ):
            return
        self.reason = reason
        self.typed_order_id = typed
        self.confirmation = phrase
        self.choice = "new_ticket"
        self.destroy()

class ManualOdooEntryDialog(tk.Toplevel):
    """Operator-only existing Odoo ticket/transfer registration.

    This dialog NEVER navigates Odoo or Lark. It only saves verified local
    identifiers so the normal, confirmation-gated Lark-only recovery can run.
    """

    def __init__(self, master, *, store, scan_id, record, on_saved, before_save):
        from odoo import _build_return_groups
        super().__init__(master)
        self.store, self.scan_id = store, scan_id
        self.record = copy.deepcopy(record)
        self.on_saved, self.before_save = on_saved, before_save
        self.groups = _build_return_groups([
            i for i in (record.get("items") or [])
            if isinstance(i, dict) and i.get("status") == "Returned"
        ])
        if not self.groups:
            self.destroy()
            raise ValueError("No returned items in this scan.")
        self.entry_vars = []
        self.title("Manual Odoo Transfer Reconciliation | " + _safe_str(record.get("order_id")))
        self.geometry("1020x775")
        self.minsize(790, 600)
        apply_theme(self)
        self.transient(master)
        self._build()
        self.grab_set()

    def _build(self):
        shell = ttk.Frame(self, padding=16)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)
        ttk.Label(shell, text="MANUAL ODOO → RECOVERY → LARK",
                  style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            shell, style="Hint.TLabel",
            text="Enter EXISTING Odoo records only. This will NOT create a ticket, "
                 "validate stock, or submit Lark. A separate confirmation is required before filing.",
            wraplength=950,
        ).grid(row=1, column=0, sticky="ew", pady=(4, 10))

        frame = ttk.Frame(shell)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(frame, highlightthickness=0, borderwidth=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, command=canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)
        content = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
        content.columnconfigure(1, weight=1)

        checkpoint = self.record.get("odoo_checkpoint") or {}
        ticket_card = RoundedCard(content, title="EXISTING HELP DESK TICKET")
        ticket_card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        cf = ticket_card.content
        cf.columnconfigure(1, weight=1)
        self.ticket_title_var = tk.StringVar(value=_safe_str(checkpoint.get("ticket_title")))
        self.ticket_url_var = tk.StringVar(value=_safe_str(checkpoint.get("ticket_url")))
        for idx, (caption, var) in enumerate((
            ("Ticket title (optional)", self.ticket_title_var),
            ("Ticket URL (required)", self.ticket_url_var),
        )):
            ttk.Label(cf, text=caption + ":").grid(row=idx, column=0, sticky="w", padx=(0, 10), pady=5)
            ttk.Entry(cf, textvariable=var).grid(row=idx, column=1, sticky="ew", pady=5)

        recorded = list(checkpoint.get("returns") or [])
        pending = checkpoint.get("pending_return") or {}
        if pending:
            recorded.append(pending)
        for index, group in enumerate(self.groups, start=1):
            sku_qty = ", ".join(
                f"{i.get('sku')} × {i.get('quantity')}" for i in group["items"]
            )
            card = RoundedCard(
                content,
                title=f"RETURN #{index}  /  {group['classification']} · {group['decision']} · {sku_qty}",
            )
            card.grid(row=index, column=0, columnspan=2, sticky="ew", pady=(0, 10))
            fields = card.content
            fields.columnconfigure(1, weight=1)
            old = next((r for r in recorded if int(r.get("return_index") or 0) == index), {})
            trans_id = tk.StringVar(value=_safe_str(old.get("transfer_id")))
            trans_url = tk.StringVar(value=_safe_str(old.get("transfer_url")))
            self.entry_vars.append((trans_id, trans_url))
            ttk.Label(fields, text="Transfer ID:").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
            ttk.Entry(fields, textvariable=trans_id).grid(row=0, column=1, sticky="ew", pady=5)
            ttk.Label(fields, text="Transfer link:").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
            ttk.Entry(fields, textvariable=trans_url).grid(row=1, column=1, sticky="ew", pady=5)

        final = RoundedCard(content, title="OPERATOR VERIFICATION / AUDIT")
        final.grid(row=len(self.groups) + 1, column=0, columnspan=2, sticky="ew")
        inner = final.content
        inner.columnconfigure(1, weight=1)
        ttk.Label(inner, text="Manual repair notes:").grid(row=0, column=0, columnspan=2, sticky="w")
        self.note_editor = tk.Text(inner, height=3, wrap="word")
        configure_readonly_text(self.note_editor, detail=True)
        self.note_editor.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        self.confirmed = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            inner, variable=self.confirmed,
            text="I verified ticket links, transfers, SKU/quantity, warehouse handoff/QC "
                 "and that these items have NOT already been filed in Lark.",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 8))
        ttk.Label(inner, text="Type exact Order ID:").grid(row=3, column=0, sticky="w")
        self.order_confirmation = tk.StringVar()
        ttk.Entry(inner, textvariable=self.order_confirmation).grid(row=3, column=1, sticky="ew")

        bottom = ttk.Frame(shell)
        bottom.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(bottom, text="Local JSON only · Lark is NOT submitted by Save",
                  style="Hint.TLabel").pack(side="left")
        RoundedButton(bottom, text="Cancel", command=self.destroy,
                      surface="dark").pack(side="right", padx=(8, 0))
        RoundedButton(bottom, text="Save Existing Odoo Details", command=self._save,
                      surface="dark", kind="teal").pack(side="right", padx=(8, 0))

    def _save(self):
        if not self.before_save():
            return
        try:
            self.store.record_manual_odoo_transfers(
                self.scan_id, ticket_title=self.ticket_title_var.get(),
                ticket_url=self.ticket_url_var.get(),
                transfer_entries=[
                    {"transfer_id": transfer_id.get(), "transfer_url": transfer_url.get()}
                    for transfer_id, transfer_url in self.entry_vars
                ],
                operator_reason=self.note_editor.get("1.0", tk.END).strip(),
                typed_order_id=self.order_confirmation.get().strip(),
                acknowledged=bool(self.confirmed.get()),
                expected_updated_at=self.record.get("updated_at"),
            )
        except Exception as error:
            messagebox.showerror("Cannot Save Existing Odoo Transfer", str(error), parent=self)
            return
        self.destroy()
        self.on_saved()


class SavedScanEditor(tk.Toplevel):
    """Edit a local saved scan without touching any Odoo/Lark browser pages."""

    _ITEM_FIELDS = (
        ("sku", "SKU"), ("quantity", "QTY"), ("amount", "Amount"),
        ("classification", "Classification"), ("decision", "Decision"),
        ("status", "Status"), ("grade", "Grade"), ("odoo_tag", "Odoo Tag"),
        ("wrong_item_status", "Wrong Item / Scam Status"),
    )

    def __init__(self, master, *, store, scan_id, record, on_saved, before_save):
        super().__init__(master)
        self.store = store
        self.scan_id = scan_id
        self.record = copy.deepcopy(record)
        self.on_saved = on_saved
        self.before_save = before_save
        self.locked = bool(record.get("archived")) or has_external_work(record)
        self.items = copy.deepcopy(record.get("items") or [])
        self.active_index = None
        self.item_vars = {}
        self.title("Edit Saved Scan | " + _safe_str(record.get("order_id")))
        self.geometry("1130x900")
        self.minsize(900, 795)
        apply_theme(self)
        self.transient(master)
        self.grab_set()
        self._build_editor()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_editor(self):
        shell = ttk.Frame(self, padding=14)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)
        ttk.Label(shell, text="EDIT SAVED SCAN", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        note = (
            "ODOO/LARK DATA PROTECTED: Only the internal note below can be edited. "
            "Previously filed details cannot be rewritten."
            if self.locked else
            "Not yet processed: edit return details and items. Transactional "
            "changes clear item confirmation; reconfirm before Submit."
        )
        ttk.Label(shell, text=note, style="Hint.TLabel", wraplength=990).grid(
            row=1, column=0, sticky="ew", pady=(0, 9)
        )

        body = ttk.Frame(shell)
        body.grid(row=2, column=0, sticky="nsew")
        body.rowconfigure(1, weight=1, minsize=390)
        body.columnconfigure(0, weight=1)

        case_card = RoundedCard(body, title="CASE / SEARCH FIELDS")
        case_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frm = case_card.content
        for col in (1, 3):
            frm.columnconfigure(col, weight=1)
        self.case_vars = {}
        specs = (
            ("platform", "Platform", None),
            ("order_id", "Order ID", None),
            ("search_by", "Search by", ("Tracking Number", "Order ID", "Order Link", "Return Order ID")),
            ("search_input", "Search input", None),
            ("tracking_number", "Tracking number", None),
            ("new_stock_destination", "Brand New to", NEW_STOCK_DESTINATIONS),
        )
        for idx, (key, label, choices) in enumerate(specs):
            row, pair = divmod(idx, 2)
            col = pair * 2
            ttk.Label(frm, text=label + ":").grid(
                row=row, column=col, sticky="w", padx=(0, 6), pady=3
            )
            var = tk.StringVar(value=_safe_str(self.record.get(key) or
                     ("MNL/Stock" if key == "new_stock_destination" else "")))
            self.case_vars[key] = var
            if choices:
                widget = ttk.Combobox(frm, textvariable=var, values=choices,
                                      state="readonly", width=23)
            else:
                widget = ttk.Entry(frm, textvariable=var, width=24)
            widget.grid(row=row, column=col + 1, sticky="ew", pady=3, padx=(0, 13))
            if self.locked or key == "platform":
                widget.config(state="disabled" if choices else "readonly")

        item_card = RoundedCard(body, title="RETURNED ITEMS / SELECT AN ITEM TO EDIT")
        item_card.grid(row=1, column=0, sticky="nsew")
        item_frm = item_card.content
        item_frm.columnconfigure(0, weight=4)
        item_frm.columnconfigure(1, weight=5)
        item_frm.rowconfigure(0, weight=1)
        left = ttk.Frame(item_frm, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.item_tree = ttk.Treeview(
            left, columns=("sku", "qty", "class", "status"), show="headings",
            height=8, selectmode="browse",
        )
        for key, caption, width in (("sku", "SKU", 125), ("qty", "QTY", 46),
                                    ("class", "Classification", 120),
                                    ("status", "Status", 100)):
            self.item_tree.heading(key, text=caption)
            self.item_tree.column(key, width=width, minwidth=40,
                                  stretch=key != "qty")
        self.item_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(left, command=self.item_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.item_tree.configure(yscrollcommand=scrollbar.set)
        self.item_tree.bind("<<TreeviewSelect>>", self._on_item_selected)
        actions = ttk.Frame(left, style="Card.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(9, 0))
        self.add_button = RoundedButton(
            actions, text="Add Item", command=self._add_item, state="disabled" if self.locked else "normal",
        )
        self.add_button.pack(side="left", padx=(0, 8))
        self.remove_button = RoundedButton(
            actions, text="Remove Item", command=self._remove_item, state="disabled" if self.locked else "normal",
        )
        self.remove_button.pack(side="left")

        right = ttk.Frame(item_frm, style="Card.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        right.columnconfigure(3, weight=1)
        choices = {
            "classification": ("", "New", "Unsealed", "Defective", "Wrong Item", "Scam", "Missing Item"),
            "decision": ("", "Refunded", "Disputed", "Replaced"),
            "wrong_item_status": ("", "Refunded (Seller Fault)", "Dispute Approved",
                                  "Dispute Rejected", "In-Dispute"),
            "status": ("", "Returned", "Not Returned"),
            "grade": ("", "A", "B", "C", "D"),
            "odoo_tag": ("", "Change of Mind (Sealed)", "Change of Mind (Unsealed)",
                         "Consultation", "Damaged / Defective Item", "For Repair",
                         "Lost / Missing Item", "Others (Refund) e.g Shipping Fee etc."),
        }
        for i, (key, caption) in enumerate(self._ITEM_FIELDS):
            row, pair = divmod(i, 2)
            col = pair * 2
            ttk.Label(right, text=caption + ":").grid(
                row=row, column=col, sticky="w", pady=5, padx=(0, 6)
            )
            var = tk.StringVar()
            self.item_vars[key] = var
            if key in choices:
                widget = ttk.Combobox(right, textvariable=var, values=choices[key],
                                      state="readonly", width=20)
            else:
                widget = ttk.Entry(right, textvariable=var, width=23)
            widget.grid(row=row, column=col + 1, sticky="ew", pady=5,
                        padx=(0, 10))
            if self.locked:
                widget.config(state="disabled" if key in choices else "readonly")
        ttk.Label(right, text="Received Item (Wrong Item / Scam):").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(6, 2)
        )
        self.received_item_editor = tk.Text(right, height=2, wrap="word", padx=7, pady=5)
        configure_readonly_text(self.received_item_editor, detail=True)
        self.received_item_editor.grid(row=6, column=0, columnspan=4, sticky="nsew", pady=(0, 5))
        ttk.Label(right, text="Item remarks:").grid(
            row=7, column=0, columnspan=4, sticky="w", pady=(6, 2)
        )
        self.remarks_editor = tk.Text(right, height=2, wrap="word", padx=7, pady=5)
        configure_readonly_text(self.remarks_editor, detail=True)
        self.remarks_editor.grid(row=8, column=0, columnspan=4, sticky="nsew", pady=(0, 6))
        if self.locked:
            self.remarks_editor.config(state="disabled")
            self.received_item_editor.config(state="disabled")

        notes_card = RoundedCard(body, title="INTERNAL NOTES  /  LOCAL AUDIT ONLY")
        notes_card.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.notes_editor = tk.Text(notes_card.content, height=2, wrap="word", padx=7, pady=6)
        configure_readonly_text(self.notes_editor, detail=True)
        self.notes_editor.pack(fill="both", expand=True)
        self.notes_editor.insert("1.0", self.record.get("operator_notes") or "")

        bottom = ttk.Frame(shell)
        bottom.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(bottom, text="Edit affects local JSON only; never modifies Odoo/Lark.",
                  style="Hint.TLabel").pack(side="left")
        RoundedButton(bottom, text="Cancel", surface="dark", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        RoundedButton(bottom, text="Save Changes", surface="dark", command=self._save).pack(
            side="right", padx=(8, 0)
        )
        self._refresh_items(selected=0 if self.items else None)

    def _cache_item(self):
        idx = self.active_index
        if self.locked or idx is None or idx >= len(self.items):
            return
        current = self.items[idx]
        for key, var in self.item_vars.items():
            current[key] = var.get().strip()
        current["remarks"] = self.remarks_editor.get("1.0", tk.END).strip()
        current["received_item"] = self.received_item_editor.get("1.0", tk.END).strip()
        self.item_tree.item(str(idx), values=self._item_preview(current))

    @staticmethod
    def _item_preview(item):
        return (item.get("sku", ""), item.get("quantity", ""),
                item.get("classification", ""), item.get("status", ""))

    def _refresh_items(self, *, selected=None):
        self.item_tree.delete(*self.item_tree.get_children())
        for i, item in enumerate(self.items):
            self.item_tree.insert("", "end", iid=str(i), values=self._item_preview(item))
        self.active_index = None
        if selected is not None and 0 <= selected < len(self.items):
            self.item_tree.selection_set(str(selected))
            self.item_tree.focus(str(selected))
            self._on_item_selected()

    def _on_item_selected(self, _event=None):
        selected = self.item_tree.selection()
        if not selected:
            return
        index = int(selected[0])
        if index == self.active_index:
            return
        self._cache_item()
        self.active_index = index
        item = self.items[index]
        for key, var in self.item_vars.items():
            var.set(_safe_str(item.get(key)))
        if not self.locked:
            self.remarks_editor.delete("1.0", tk.END)
            self.remarks_editor.insert("1.0", _safe_str(item.get("remarks")))
            self.received_item_editor.delete("1.0", tk.END)
            self.received_item_editor.insert("1.0", _safe_str(item.get("received_item")))
        else:
            self.remarks_editor.config(state="normal")
            self.remarks_editor.delete("1.0", tk.END)
            self.remarks_editor.insert("1.0", _safe_str(item.get("remarks")))
            self.remarks_editor.config(state="disabled")
            self.received_item_editor.config(state="normal")
            self.received_item_editor.delete("1.0", tk.END)
            self.received_item_editor.insert("1.0", _safe_str(item.get("received_item")))
            self.received_item_editor.config(state="disabled")

    def _add_item(self):
        if self.locked:
            return
        self._cache_item()
        self.items.append({
            "sku": "", "quantity": 1, "amount": "", "classification": "",
            "decision": "", "status": "", "grade": "", "odoo_tag": "",
            "remarks": "", "received_item": "", "wrong_item_status": "",
            "platform": self.record.get("platform") or "",
        })
        self._refresh_items(selected=len(self.items) - 1)

    def _remove_item(self):
        if self.locked:
            return
        selected = self.item_tree.selection()
        if not selected:
            return
        if len(self.items) < 2:
            messagebox.showwarning("Last Item", "A scan needs at least one item.", parent=self)
            return
        index = int(selected[0])
        self.active_index = None
        self.items.pop(index)
        self._refresh_items(selected=min(index, len(self.items) - 1))

    def _save(self):
        self._cache_item()
        edits = {"operator_notes": self.notes_editor.get("1.0", tk.END).strip()}
        if not self.locked:
            edits.update({key: var.get().strip() for key, var in self.case_vars.items()
                          if key != "platform"})
            edits["items"] = copy.deepcopy(self.items)
        if not self.before_save():
            return
        try:
            self.store.edit_saved_record(
                self.scan_id, edits,
                expected_updated_at=self.record.get("updated_at"),
            )
            self.on_saved()
        except Exception as error:
            messagebox.showerror("Cannot Save Record", str(error), parent=self)
            return
        self.destroy()
