import copy
import json
import os
import shutil
import sys
import uuid
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCHEMA_VERSION = 1
# Approved, exact Odoo location names. Do not accept arbitrary freeform paths.
NEW_STOCK_DESTINATIONS = ("MNL/Stock", "BLC/Stock")
DEFAULT_NEW_STOCK_DESTINATION = "MNL/Stock"


def normalize_new_stock_destination(value, *, default=DEFAULT_NEW_STOCK_DESTINATION):
    """Validate a destination. Invalid settings never change the stock route."""
    if value in NEW_STOCK_DESTINATIONS:
        return value
    if default in NEW_STOCK_DESTINATIONS:
        return default
    raise ValueError(f"Unsupported Brand New destination: {value!r}")

# Odoo/Lark-linked history records are protected from accidental deletion.
# The processor checks active and archived history for recorded tickets. Only
# the separately-confirmed permanent local delete may remove this guard.
PROTECTED_WORKFLOW_STATES = frozenset({
    "odoo_ticket_created", "odoo_ticket_setup_pending", "odoo_ticket_ready",
    "odoo_return_pending", "odoo_error_manual_review", "manual_review",
    "lark_pending", "completed",
})

EDITABLE_ITEM_FIELDS = frozenset({
    "sku", "quantity", "amount", "classification", "decision", "status",
    "grade", "odoo_tag", "remarks", "received_item", "wrong_item_status",
})


def has_external_work(*records):
    """Conservatively detect whether deletion or editing could hide Odoo/Lark work."""
    for record in records:
        if not isinstance(record, dict):
            continue
        if (record.get("odoo_checkpoint") or record.get("odoo_results")
                or record.get("lark_results") or record.get("normal_lark_results")
                or record.get("wrong_item_lark_results")):
            return True
        if record.get("workflow_state") in PROTECTED_WORKFLOW_STATES:
            return True
        # Older checkpoints may be nested in a restore point.
        if record.get("pending_return") or record.get("ticket_url"):
            return True
    return False


MANILA_TZ = timezone(timedelta(hours=8))


def _now_iso():
    return datetime.now(MANILA_TZ).isoformat(timespec="seconds")


def _json_safe(value):
    """Convert processor state into plain JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _default_data_dir():
    override = os.environ.get("MAKERLAB_RETURN_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parent
    return app_dir / "data"


class WorkflowStore:
    """Atomic JSON persistence for scan history and unfinished workflows."""

    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir else _default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.scan_history_path = self.data_dir / "scan_history.json"
        self.restore_points_path = self.data_dir / "restore_points.json"
        self.settings_path = self.data_dir / "settings.json"
        self.last_warning = ""

        self._ensure_file(
            self.scan_history_path,
            {"schema_version": SCHEMA_VERSION, "scans": []},
        )
        self._ensure_file(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}},
        )
        self._ensure_file(self.settings_path, self._default_settings())

    @staticmethod
    def _blank_copy(value):
        return copy.deepcopy(value)

    def _ensure_file(self, path, default):
        if not path.exists():
            self._atomic_write(path, default, create_backup=False)
            return
        # Read once on startup so corruption is recovered immediately.
        self._read_json(path, default)

    def _read_json(self, path, default):
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, dict):
                raise ValueError("JSON root must be an object")
            return value
        except Exception as error:
            backup_path = path.with_suffix(path.suffix + ".bak")
            if backup_path.exists():
                try:
                    with backup_path.open("r", encoding="utf-8") as handle:
                        value = json.load(handle)
                    if not isinstance(value, dict):
                        raise ValueError("backup JSON root must be an object")
                    self.last_warning = (
                        f"Recovered {path.name} from backup after read error: {error}"
                    )
                    self._atomic_write(path, value, create_backup=False)
                    return value
                except Exception:
                    pass

            timestamp = datetime.now(MANILA_TZ).strftime("%Y%m%d-%H%M%S")
            corrupt_path = path.with_name(f"{path.stem}.corrupt-{timestamp}{path.suffix}")
            try:
                if path.exists():
                    path.replace(corrupt_path)
            except Exception:
                pass
            self.last_warning = (
                f"Could not read {path.name}; a fresh file was created. "
                f"Original saved as {corrupt_path.name}. Error: {error}"
            )
            fresh = self._blank_copy(default)
            self._atomic_write(path, fresh, create_backup=False)
            return fresh

    def _atomic_write(self, path, value, create_backup=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        backup_path = path.with_suffix(path.suffix + ".bak")
        safe_value = _json_safe(value)

        if create_backup and path.exists():
            try:
                shutil.copy2(path, backup_path)
            except OSError:
                # Backup failure should not prevent the current state from saving.
                pass

        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                safe_value,
                handle,
                indent=2,
                ensure_ascii=False,
                sort_keys=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)

    # ------------------------------------------------------------------
    # Persistent application settings (extendable without changing scan data)
    # ------------------------------------------------------------------
    @staticmethod
    def _default_settings():
        return {
            "schema_version": SCHEMA_VERSION,
            "new_stock_destination": DEFAULT_NEW_STOCK_DESTINATION,
        }

    def load_settings(self):
        data = self._read_json(self.settings_path, self._default_settings())
        destination = normalize_new_stock_destination(
            data.get("new_stock_destination"),
            default=DEFAULT_NEW_STOCK_DESTINATION,
        )
        return {**data, "new_stock_destination": destination}

    def save_settings(self, *, new_stock_destination):
        if new_stock_destination not in NEW_STOCK_DESTINATIONS:
            raise ValueError("Brand New destination must be MNL/Stock or BLC/Stock.")
        data = self.load_settings()
        data.update({
            "schema_version": SCHEMA_VERSION,
            "new_stock_destination": new_stock_destination,
        })
        self._atomic_write(self.settings_path, data)
        return self.load_settings()

    # ------------------------------------------------------------------
    # Scan history
    # ------------------------------------------------------------------
    def start_scan(
        self,
        *,
        platform,
        search_by,
        search_input,
        order_id,
        return_case,
        items,
        new_stock_destination=DEFAULT_NEW_STOCK_DESTINATION,
    ):
        data = self._read_json(
            self.scan_history_path,
            {"schema_version": SCHEMA_VERSION, "scans": []},
        )
        scans = data.setdefault("scans", [])
        scan_id = uuid.uuid4().hex
        now = _now_iso()
        record = {
            "scan_id": scan_id,
            "created_at": now,
            "updated_at": now,
            "workflow_state": "loaded",
            "platform": str(platform or ""),
            "search_by": str(search_by or ""),
            "search_input": str(search_input or ""),
            "order_id": str(order_id or ""),
            "request_id": str((return_case or {}).get("request_id") or ""),
            "tracking_number": str(
                (return_case or {}).get("tracking_number") or ""
            ),
            "return_case": _json_safe(return_case or {}),
            "items": _json_safe(items or []),
            "case_decision": None,
            "new_stock_destination": normalize_new_stock_destination(
                new_stock_destination,
            ),
            "odoo_results": None,
            "odoo_checkpoint": None,
            "lark_results": [],
            "normal_lark_results": [],
            "wrong_item_lark_results": [],
            "last_error": "",
            "completed_at": "",
        }
        scans.append(record)
        self._atomic_write(self.scan_history_path, data)
        return scan_id

    def update_scan(self, scan_id, *, workflow_state=None, **updates):
        if not scan_id:
            return None
        data = self._read_json(
            self.scan_history_path,
            {"schema_version": SCHEMA_VERSION, "scans": []},
        )
        for record in data.setdefault("scans", []):
            if record.get("scan_id") != scan_id:
                continue
            if record.get("archived"):
                raise RuntimeError(
                    "This scan is archived and cannot be updated or submitted again."
                )
            if workflow_state:
                record["workflow_state"] = str(workflow_state)
            for key, value in updates.items():
                record[str(key)] = _json_safe(value)
            record["updated_at"] = _now_iso()
            if workflow_state == "completed":
                record["completed_at"] = record["updated_at"]
            self._atomic_write(self.scan_history_path, data)
            return copy.deepcopy(record)
        return None

    def get_scan(self, scan_id):
        data = self._read_json(
            self.scan_history_path,
            {"schema_version": SCHEMA_VERSION, "scans": []},
        )
        for record in data.get("scans", []):
            if record.get("scan_id") == scan_id:
                return copy.deepcopy(record)
        return None

    def list_recent_scans(self, limit=50):
        """Return newest scans; limit=None returns the full history for the GUI."""
        data = self._read_json(
            self.scan_history_path,
            {"schema_version": SCHEMA_VERSION, "scans": []},
        )
        scans = list(data.get("scans", []))
        scans.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        if limit is not None:
            scans = scans[: max(0, int(limit))]
        return copy.deepcopy(scans)

    # ------------------------------------------------------------------
    # Persistent restore points
    # ------------------------------------------------------------------
    def save_restore_point(self, scan_id, snapshot):
        if not scan_id:
            raise ValueError("scan_id is required to save a restore point")
        data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}},
        )
        # Archived history must never receive a fresh Recovery point, even
        # when an earlier processor instance still holds the old scan ID.
        existing_scan = self.get_scan(scan_id)
        if existing_scan and existing_scan.get("archived"):
            raise RuntimeError("Cannot restore an archived Odoo/Lark scan.")
        points = data.setdefault("restore_points", {})
        existing = points.get(scan_id, {})
        created_at = existing.get("created_at") or _now_iso()
        # Workflow snapshots are regenerated by main.py at each Odoo/Lark
        # milestone. Preserve operator edits that are local audit metadata,
        # rather than accidentally losing them during a normal checkpoint.
        history_metadata = self.get_scan(scan_id) or {}
        metadata = {}
        for field in (
            "operator_notes", "edit_history", "manual_recovery_events",
            "manual_odoo_reconciliation_history", "duplicate_override_events",
            "reset_history",
        ):
            if field not in snapshot:
                if field in existing:
                    metadata[field] = copy.deepcopy(existing[field])
                elif field in history_metadata:
                    metadata[field] = copy.deepcopy(history_metadata[field])
        points[scan_id] = {
            "scan_id": scan_id,
            "created_at": created_at,
            "updated_at": _now_iso(),
            **metadata,
            **_json_safe(snapshot),
        }
        self._atomic_write(self.restore_points_path, data)
        return copy.deepcopy(points[scan_id])

    def delete_restore_point(self, scan_id):
        if not scan_id:
            return False
        data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}},
        )
        points = data.setdefault("restore_points", {})
        if scan_id not in points:
            return False
        points.pop(scan_id, None)
        self._atomic_write(self.restore_points_path, data)
        return True

    def get_restore_point(self, scan_id):
        data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}},
        )
        value = data.get("restore_points", {}).get(scan_id)
        if value and (value.get("archived") or
                      (self.get_scan(scan_id) or {}).get("archived")):
            return None
        return copy.deepcopy(value) if value else None

    def list_restore_points(self):
        data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}},
        )
        history = self._read_json(
            self.scan_history_path,
            {"schema_version": SCHEMA_VERSION, "scans": []},
        )
        archived_ids = {
            record.get("scan_id") for record in history.get("scans", [])
            if record.get("archived")
        }
        points = [
            value for key, value in data.get("restore_points", {}).items()
            if key not in archived_ids and not value.get("archived")
        ]
        points.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return copy.deepcopy(points)

    # ------------------------------------------------------------------
    # Operator changes to saved Scan History / Recovery
    # ------------------------------------------------------------------
    def make_scan_recoverable(self, scan_id):
        """Create a durable Recovery point from existing Scan History.

        This performs NO browser action and never clears external Odoo evidence.
        In-flight work is kept in manual-review mode (not safe to resubmit).
        """
        scan_id = str(scan_id or "").strip()
        record = self.get_scan(scan_id)
        if not record:
            raise ValueError("Choose an existing Scan History record.")
        if record.get("archived"):
            raise ValueError("Unarchive the record before making it recoverable.")
        if record.get("workflow_state") == "completed" or record.get("lark_results"):
            raise ValueError("Completed/Lark-filed scans cannot be made recoverable for new filing.")
        if not record.get("order_id") or not isinstance(record.get("items"), list) or not record["items"]:
            raise ValueError("The scan needs an Order ID and at least one item.")
        existing = self.get_restore_point(scan_id)
        if existing:
            return existing

        snapshot = copy.deepcopy(record)
        external = has_external_work(record)
        # A legacy scan may say "Odoo ticket created" while lacking the
        # actual checkpoint. Do NOT convert it into a confirmed, submit-ready
        # draft: that could create a duplicate ticket. Use a locked sentinel
        # until the operator records the real ticket/transfer identities.
        if external and not snapshot.get("odoo_checkpoint") and not snapshot.get("odoo_results"):
            snapshot["odoo_checkpoint"] = {
                "order_id": str(record.get("order_id") or ""),
                "stage": "manual_review", "resume_safe": False,
                "returns": [], "needs_operator_reconciliation": True,
            }
        snapshot["workflow_state"] = (
            "lark_pending" if snapshot.get("odoo_results")
            else "manual_review" if snapshot.get("odoo_checkpoint")
            else "manually_saved"
        )
        if isinstance(snapshot.get("odoo_checkpoint"), dict):
            snapshot["odoo_checkpoint"]["resume_safe"] = False
            snapshot["odoo_checkpoint"]["stage"] = "manual_review"
        snapshot.setdefault("manual_recovery_events", []).append({
            "at": _now_iso(), "action": "make_recoverable_from_scan_history",
            "preserved_external_odoo": bool(external),
        })
        self.save_restore_point(scan_id, snapshot)
        verified = self.get_restore_point(scan_id)
        if not verified or verified.get("order_id") != record["order_id"]:
            raise RuntimeError("Recovery could not be verified on disk.")
        # History is a mirror; durable Recovery is written before this.
        updated = self.update_scan(
            scan_id, workflow_state=snapshot["workflow_state"],
            odoo_checkpoint=snapshot.get("odoo_checkpoint"),
            manual_recovery_events=snapshot["manual_recovery_events"],
        )
        if not updated:
            raise RuntimeError("Recovery was saved, but History could not be updated.")
        return verified

    def record_manual_odoo_transfers(
        self, scan_id, *, ticket_url, transfer_entries,
        ticket_title="", operator_reason="", typed_order_id="",
        acknowledged=False, expected_updated_at=None,
    ):
        """Store operator-entered Odoo identities for Lark-only recovery.

        Grouping and the exact URL/SKU/quantity rules are verified using the
        same validator as the existing Lark-only recovery button. A ticket or
        stock transfer is NEVER created or modified by this method.
        """
        from odoo import (  # Keep grouping identical to normal automation.
            _build_return_groups, build_ticket_title,
            confirm_existing_transfers_for_lark,
        )

        scan_id = str(scan_id or "").strip()
        history_data = self._read_json(
            self.scan_history_path, {"schema_version": SCHEMA_VERSION, "scans": []})
        restore_data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}})
        history = next((r for r in history_data.get("scans", [])
                        if r.get("scan_id") == scan_id), None)
        restore = restore_data.get("restore_points", {}).get(scan_id)
        # An interrupted History mirror can leave only the durable Recovery
        # record. Reconstruct the missing scan without losing that checkpoint.
        if history is None and restore is not None and not restore.get("archived"):
            history = copy.deepcopy(restore)
            history_data.setdefault("scans", []).append(history)
        if history and history.get("archived"):
            raise ValueError("Unarchive the scan before entering manual Odoo work.")
        if not history or not restore:
            raise ValueError("Make this scan recoverable first, then enter its Odoo details.")
        if restore.get("archived"):
            raise ValueError("Unarchive the scan before entering manual Odoo work.")
        if (history.get("workflow_state") == "completed"
                or restore.get("workflow_state") == "completed"
                or history.get("lark_results") or restore.get("lark_results")):
            raise RuntimeError("This scan is completed or already has Lark results.")
        if history.get("odoo_results") or restore.get("odoo_results"):
            raise RuntimeError(
                "This scan already records completed Odoo results. Use Retry Lark Only; "
                "do not replace those results with manually entered transfers."
            )
        order_id = str(restore.get("order_id") or "").strip()
        platform = str(restore.get("platform") or "").strip()
        if (not order_id or history.get("order_id") != order_id
                or history.get("platform") != platform):
            raise ValueError("Scan History and Recovery identities disagree.")
        if str(typed_order_id or "").strip() != order_id or acknowledged is not True:
            raise PermissionError("Type the exact Order ID and confirm manual Odoo review.")
        reason = str(operator_reason or "").strip()
        if len(reason) < 8 or len(reason) > 2000:
            raise ValueError("Enter a reason of 8-2000 characters describing the manual Odoo work.")
        if (expected_updated_at is not None
                and restore.get("updated_at") != expected_updated_at):
            raise RuntimeError("Recovery was changed. Refresh and reopen the manual editor.")

        returned = [copy.deepcopy(item) for item in (restore.get("items") or [])
                    if isinstance(item, dict) and str(item.get("status") or "").strip() == "Returned"]
        if not returned:
            raise ValueError("No physically Returned items require a TC/IN transfer.")
        for index, item in enumerate(restore.get("items") or [], 1):
            sku = str(item.get("sku") or "").strip().upper()
            try:
                qty = int(item.get("quantity"))
                money = item.get("amount")
                if str(money).strip() != "":
                    amount = float(money)
                    if not 0 <= amount < float("inf"):
                        raise ValueError()
                elif platform != "TikTok":
                    raise ValueError()
            except (TypeError, ValueError) as error:
                raise ValueError(f"Item #{index} has an invalid QTY/Amount.") from error
            if (not re.fullmatch(r"[A-Za-z0-9_+.-]+", sku) or qty <= 0
                    or any(not str(item.get(field) or "").strip()
                           for field in ("decision", "classification", "status"))):
                raise ValueError(f"Item #{index} has incomplete SKU, QTY or decisions.")
            if item.get("status") == "Returned" and not item.get("odoo_tag"):
                raise ValueError(f"Odoo Tag is missing for {sku}.")
            if item.get("classification") == "Unsealed" and not item.get("grade"):
                raise ValueError(f"Grade is missing for unsealed item {sku}.")
        groups = _build_return_groups(returned)
        if not isinstance(transfer_entries, list) or len(transfer_entries) != len(groups):
            raise ValueError(
                "Enter exactly one TC/IN ID and link per classification/decision group."
            )
        all_prior = list(history_data.get("scans", [])) + list(
            restore_data.get("restore_points", {}).values())
        for previous in all_prior:
            if previous.get("scan_id") == scan_id:
                continue
            if (previous.get("platform") == platform
                    and previous.get("order_id") == order_id
                    and previous.get("lark_results")):
                raise RuntimeError(
                    "Another local scan of this order already has Lark results. "
                    "Check the earlier filing before proceeding."
                )
        previous_cp = restore.get("odoo_checkpoint") or history.get("odoo_checkpoint") or {}
        ticket_title = str(ticket_title or previous_cp.get("ticket_title") or "").strip()
        if not ticket_title:
            ticket_title = build_ticket_title(order_id, returned)
        if not ticket_title.startswith(order_id):
            raise ValueError("Odoo ticket title must begin with this marketplace Order ID.")
        ticket_url = str(ticket_url or "").strip()
        destination = normalize_new_stock_destination(
            restore.get("new_stock_destination"), default=DEFAULT_NEW_STOCK_DESTINATION)
        transfers = []
        for index, (group, entered) in enumerate(zip(groups, transfer_entries), 1):
            if not isinstance(entered, dict):
                raise ValueError(f"Return #{index} must have a TC/IN ID and URL.")
            transfers.append({
                "return_index": index,
                "decision": str(group["decision"]),
                "classification": str(group["classification"]),
                "status": str(group["status"]),
                "items": [{"sku": str(item.get("sku") or "").strip(),
                           "quantity": int(item["quantity"])} for item in group["items"]],
                "transfer_id": str(entered.get("transfer_id") or "").strip(),
                "transfer_url": str(entered.get("transfer_url") or "").strip(),
                "validated": False,
                "stock_state": "not_checked",
                "qc_completed": False,
                "manual_entry": True,
            })
        checkpoint = {
            "order_id": order_id,
            "ticket_title": ticket_title,
            "ticket_url": ticket_url,
            "product_sku": str(returned[0].get("sku") or "").strip(),
            "tags": list(dict.fromkeys(str(item.get("odoo_tag") or "") for item in returned)),
            "platform": platform,
            "new_stock_destination": destination,
            "returns": transfers,
            "next_return_index": None,
            "resume_safe": False,
            "setup_complete": False,
            "stage": "manual_review",
            "manual_entry": {
                "at": _now_iso(), "reason": reason,
                "method": "operator_entered_existing_odoo_identifiers",
                "operator_acknowledged_manual_completion": True,
            },
        }
        # This checks URL host/path, exact Helpdesk association, unique TC/IN
        # IDs, classification grouping, and every SKU/QTY BEFORE saving.
        confirm_existing_transfers_for_lark(
            checkpoint=checkpoint, order_id=order_id,
            returned_products=returned,
            confirmed_transfer_id=transfers[-1]["transfer_id"],
        )

        now = _now_iso()
        old_cp = copy.deepcopy(previous_cp)
        event = {
            "at": now, "action": "operator_entered_odoo_transfers",
            "reason": reason, "order_id": order_id,
            "previous_ticket_url": str(old_cp.get("ticket_url") or ""),
            "new_ticket_url": ticket_url,
            "previous_transfer_ids": [
                entry.get("transfer_id") for entry in (
                    list(old_cp.get("returns") or []) +
                    ([old_cp["pending_return"]] if isinstance(old_cp.get("pending_return"), dict)
                     else [])
                ) if isinstance(entry, dict) and entry.get("transfer_id")
            ],
            "previous_transfer_links": [
                entry.get("transfer_url") for entry in (
                    list(old_cp.get("returns") or []) +
                    ([old_cp["pending_return"]] if isinstance(old_cp.get("pending_return"), dict)
                     else [])
                ) if isinstance(entry, dict) and entry.get("transfer_url")
            ],
            "new_transfer_ids": [entry["transfer_id"] for entry in transfers],
        }
        # Recovery may contain newer decisions than its History mirror after
        # an earlier failed history write. Preserve the authoritative items.
        for field in ("items", "return_case", "new_stock_destination", "order_id",
                      "platform", "search_by", "search_input", "tracking_number"):
            if field in restore:
                history[field] = copy.deepcopy(restore[field])
        for obj in (history, restore):
            obj["workflow_state"] = "manual_review"
            obj["odoo_checkpoint"] = copy.deepcopy(checkpoint)
            obj["odoo_results"] = None
            obj["case_decision"] = {
                **(obj.get("case_decision") or {}),
                "confirmed": True,
                "confirmed_by": "operator_manual_odoo_reconciliation",
            }
            obj["transfer_display"] = " | ".join(event["new_transfer_ids"])
            obj["updated_at"] = now
            obj.setdefault("manual_odoo_reconciliation_history", []).append(copy.deepcopy(event))
            obj["last_error"] = "Manual Odoo review completed by operator; confirm before Lark filing."
        # Recovery is authoritative, so write it first. Never clear old Odoo
        # checkpoint before a validated replacement is ready on disk.
        self._atomic_write(self.restore_points_path, restore_data)
        self._atomic_write(self.scan_history_path, history_data)
        recovered = self.get_restore_point(scan_id)
        mirrored = self.get_scan(scan_id)
        if (not recovered or not mirrored
                or recovered.get("odoo_checkpoint") != checkpoint
                or mirrored.get("odoo_checkpoint") != checkpoint
                or not recovered.get("case_decision", {}).get("confirmed")):
            raise RuntimeError("Manual Odoo data could not be verified on disk.")
        return recovered

    def edit_saved_record(self, scan_id, edits, *, expected_updated_at=None):
        """Edit a saved scan, also updating its authoritative recovery snapshot.

        Only identity/item data of NOT-YET-FILED scans may change. If Odoo or
        Lark work exists, edit ONLY operator_notes; never rewrite the actual
        submitted marketplace, ticket, SKU/quantity or Lark values.

        If there is an active recovery snapshot it is written FIRST, so a
        failure writing the history mirror cannot destroy safe recovery data.
        """
        scan_id = str(scan_id or "").strip()
        if not scan_id or not isinstance(edits, dict):
            raise ValueError("A valid scan ID and changes are required.")
        history_data = self._read_json(
            self.scan_history_path,
            {"schema_version": SCHEMA_VERSION, "scans": []},
        )
        restore_data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}},
        )
        history_list = history_data.setdefault("scans", [])
        history = next((v for v in history_list if v.get("scan_id") == scan_id), None)
        points = restore_data.setdefault("restore_points", {})
        restore = points.get(scan_id)
        if history is None and restore is None:
            raise ValueError("This scan no longer exists in History or Recovery.")
        archived = any(v and v.get("archived") for v in (history, restore))
        if archived and set(edits) - {"operator_notes"}:
            raise ValueError("An archived scan permits internal audit notes only.")
        latest = restore if restore is not None else history
        if (expected_updated_at is not None and
                latest.get("updated_at") != expected_updated_at):
            raise RuntimeError(
                "This scan was changed since the editor opened. Refresh History "
                "and reopen Edit before saving."
            )
        locked = archived or has_external_work(history, restore)
        allowed = {"operator_notes"} if locked else {
            "operator_notes", "order_id", "search_by", "search_input",
            "tracking_number", "new_stock_destination", "items",
        }
        unknown = set(edits) - allowed
        if unknown:
            raise ValueError(
                "This case already has Odoo/Lark progress. Only internal notes "
                "can be edited; transactional data is locked."
                if locked else f"Unsupported edit fields: {', '.join(sorted(unknown))}"
            )
        if not edits:
            return copy.deepcopy(latest)

        clean = {}
        if "operator_notes" in edits:
            clean["operator_notes"] = str(edits["operator_notes"] or "").strip()[:5000]
        if not locked:
            if "order_id" in edits:
                clean["order_id"] = str(edits["order_id"] or "").strip()
                if not clean["order_id"]:
                    raise ValueError("Order ID cannot be blank.")
            if "search_by" in edits:
                clean["search_by"] = str(edits["search_by"] or "").strip()
                modes = {
                    "Shopee": {"Tracking Number", "Order ID", "Order Link"},
                    "Lazada": {"Tracking Number", "Order ID"},
                    "TikTok": {"Tracking Number", "Order ID", "Return Order ID"},
                }
                if clean["search_by"] not in modes.get(latest.get("platform"), set()):
                    raise ValueError("Invalid search mode for this marketplace.")
            for field in ("search_input", "tracking_number"):
                if field in edits:
                    clean[field] = str(edits[field] or "").strip()
            if "new_stock_destination" in edits:
                chosen = edits["new_stock_destination"]
                if chosen not in NEW_STOCK_DESTINATIONS:
                    raise ValueError("Warehouse must be MNL/Stock or BLC/Stock.")
                clean["new_stock_destination"] = chosen
            if "items" in edits:
                items = edits["items"]
                if not isinstance(items, list) or not items:
                    raise ValueError("At least one item must remain in a scan.")
                verified_items = []
                for index, raw_item in enumerate(items, start=1):
                    if not isinstance(raw_item, dict):
                        raise ValueError(f"Item {index} must be a record.")
                    item = copy.deepcopy(raw_item)
                    sku = str(item.get("sku") or "").strip().upper()
                    if not re.fullmatch(r"[A-Z0-9_+.-]+", sku):
                        raise ValueError(f"Invalid SKU in item {index}: {sku!r}.")
                    try:
                        qty = int(str(item.get("quantity", "")).strip())
                    except (ValueError, TypeError) as error:
                        raise ValueError(f"Item {index} must have a whole-number QTY.") from error
                    if qty < 1:
                        raise ValueError(f"Item {index} QTY must be at least 1.")
                    item["sku"] = sku
                    item["quantity"] = qty
                    amount = item.get("amount", "")
                    if str(amount).strip() == "":
                        if latest.get("platform") != "TikTok":
                            raise ValueError(f"Enter the Amount for {sku}.")
                        item["amount"] = ""
                    else:
                        try:
                            money = float(amount)
                        except (ValueError, TypeError) as error:
                            raise ValueError(f"Invalid Amount for {sku}.") from error
                        if not (0 <= money < float("inf")):
                            raise ValueError(f"Amount must be finite and nonnegative for {sku}.")
                        item["amount"] = round(money, 2)
                    for field in ("classification", "decision", "status", "grade", "odoo_tag",
                                  "remarks", "received_item", "wrong_item_status"):
                        item[field] = str(item.get(field) or "").strip()
                    if item.get("classification") in {"Wrong Item", "Scam"}:
                        from wrong_item_lark import WRONG_ITEM_STATUSES
                        # Allow partial edits, but reject malformed saved choices.
                        choice = item.get("wrong_item_status")
                        if choice and choice not in WRONG_ITEM_STATUSES:
                            raise ValueError(f"Invalid Wrong Item / Scam Status for {sku}.")
                    # Unconfirmed, partially completed choices are allowed.
                    verified_items.append(item)
                clean["items"] = verified_items

        changed_fields = {
            field for field, value in clean.items()
            if latest.get(field, "") != value
        }
        if not changed_fields:
            return copy.deepcopy(latest)
        now = _now_iso()
        changes_log = {
            "at": now,
            "action": "operator_edit",
            "changed_fields": sorted(changed_fields),
            "protected": bool(locked),
        }
        # Draft changes invalidate the old confirmation so the user must review
        # all items again. A historical Odoo/Lark result is NEVER unconfirmed.
        unconfirm = bool(changed_fields - {"operator_notes"}) and not locked
        targets = [obj for obj in (history, restore) if obj is not None]
        for record in targets:
            record.update(copy.deepcopy(clean))
            if unconfirm:
                record["case_decision"] = None
                record["workflow_state"] = "manually_saved"
            if "order_id" in clean or "tracking_number" in clean:
                case = copy.deepcopy(record.get("return_case") or {})
                if "order_id" in clean:
                    case["order_id"] = clean["order_id"]
                if "tracking_number" in clean:
                    case["tracking_number"] = clean["tracking_number"]
                record["return_case"] = case
            record["updated_at"] = now
            record.setdefault("edit_history", []).append(changes_log)

        if restore is not None:
            self._atomic_write(self.restore_points_path, restore_data)
        if history is None:
            history_list.append(copy.deepcopy(restore))
        self._atomic_write(self.scan_history_path, history_data)
        saved = self.get_restore_point(scan_id) if restore is not None else self.get_scan(scan_id)
        if saved is None:
            raise RuntimeError("Edited scan could not be verified on disk.")
        return saved

    def delete_saved_record(self, scan_id):
        """Delete a draft scan, or safely archive one with Odoo/Lark evidence.

        Archived records are hidden from the History GUI but remain inside
        scan_history.json so the existing duplicate-ticket guard still sees
        their original Odoo ticket and transfer identifiers.
        """
        scan_id = str(scan_id or "").strip()
        if not scan_id:
            raise ValueError("Choose a scan to delete.")
        history_data = self._read_json(
            self.scan_history_path,
            {"schema_version": SCHEMA_VERSION, "scans": []},
        )
        restore_data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}},
        )
        history_list = history_data.setdefault("scans", [])
        history = next((v for v in history_list if v.get("scan_id") == scan_id), None)
        restore_points = restore_data.setdefault("restore_points", {})
        restore = restore_points.get(scan_id)
        if history is None and restore is None:
            raise ValueError("This scan has already been deleted.")
        if history and history.get("archived"):
            # A previous attempt may have saved the safe archive but failed
            # while removing Recovery. Reattempt the cleanup idempotently.
            if restore is not None:
                restore_points.pop(scan_id)
                self._atomic_write(self.restore_points_path, restore_data)
            return {"mode": "archived", "scan_id": scan_id}
        if restore and restore.get("archived"):
            raise ValueError("This scan is already archived.")

        if has_external_work(history, restore):
            # Backward compatibility: a processed "Delete" is archive, not
            # destruction of Odoo evidence. The GUI exposes Archive separately.
            return self.archive_saved_record(scan_id,
                                             reason="delete_requested_protected")

        # Unprocessed scans can be deleted entirely. Remove Recovery FIRST:
        # if the history write then fails, the history remains visible but an
        # incomplete case will never be offered as recoverable accidentally.
        if restore is not None:
            restore_points.pop(scan_id)
            self._atomic_write(self.restore_points_path, restore_data)
        if history is not None:
            history_data["scans"] = [
                record for record in history_list if record.get("scan_id") != scan_id
            ]
            self._atomic_write(self.scan_history_path, history_data)
        return {"mode": "deleted", "scan_id": scan_id}

    def permanently_delete_saved_record(
        self, scan_id, *, typed_order_id="", confirmation="",
        external_acknowledged=False,
    ):
        """Actually remove a scan from BOTH active JSON stores.

        Unlike Archive, this removes the LOCAL duplicate-ticket guard for this
        scan. It NEVER touches Odoo or Lark. Processed scans require an explicit
        operator confirmation; ordinary draft scans do not.

        Crash ordering is conservative: Recovery is removed first, so if the
        History write fails, the previous ticket is still visible and will
        continue blocking duplicate creation. JSON .bak files may retain prior
        copies; they are not active application records.
        """
        scan_id = str(scan_id or "").strip()
        if not scan_id:
            raise ValueError("Select a saved scan first.")
        history_data = self._read_json(
            self.scan_history_path, {"schema_version": SCHEMA_VERSION, "scans": []})
        restore_data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}})
        history_list = history_data.setdefault("scans", [])
        history = next((r for r in history_list if r.get("scan_id") == scan_id), None)
        restore = restore_data.setdefault("restore_points", {}).get(scan_id)
        if history is None and restore is None:
            raise ValueError("This local scan no longer exists.")
        protected = has_external_work(history, restore)
        record = restore or history
        if protected:
            order_id = str(record.get("order_id") or "").strip()
            if (not order_id or str(typed_order_id or "").strip() != order_id
                    or confirmation != "DELETE LOCAL RECORD"
                    or external_acknowledged is not True):
                raise PermissionError(
                    "A scan with Odoo/Lark work requires the exact Order ID, "
                    "DELETE LOCAL RECORD, and explicit acknowledgment that "
                    "external transactions are NOT deleted automatically."
                )
        old_restore = copy.deepcopy(restore_data)
        if restore is not None:
            restore_data["restore_points"].pop(scan_id, None)
            self._atomic_write(self.restore_points_path, restore_data)
        try:
            if history is not None:
                history_data["scans"] = [
                    r for r in history_list if r.get("scan_id") != scan_id
                ]
                self._atomic_write(self.scan_history_path, history_data)
        except Exception:
            # If possible, restore the recovery checkpoint, keeping the case
            # recoverable until the operator retries the deletion.
            if restore is not None:
                try:
                    self._atomic_write(self.restore_points_path, old_restore)
                except Exception as rollback_error:
                    raise RuntimeError(
                        "Local delete failed and recovery rollback also failed. "
                        "Restore from the JSON .bak files before resubmitting."
                    ) from rollback_error
            raise
        remaining_history = self._read_json(
            self.scan_history_path, {"schema_version": SCHEMA_VERSION, "scans": []})
        remaining_restore = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}})
        if (any(r.get("scan_id") == scan_id for r in remaining_history.get("scans", []))
                or scan_id in remaining_restore.get("restore_points", {})):
            raise RuntimeError("Local scan deletion could not be verified.")
        return {"mode": "deleted", "scan_id": scan_id,
                "had_external_work": protected}

    def reset_saved_scan_for_resubmission(
        self, scan_id, *, typed_order_id, confirmation,
        external_acknowledged=False,
    ):
        """Clear stale Odoo progress only after an explicit external review.

        Preserve marketplace data and per-item remarks, but require all item
        decisions to be re-confirmed. Cannot reset a case with recorded Lark
        results. The old ticket/transfer identifiers are retained ONLY as a
        local reset-audit event, not as an active Odoo checkpoint.
        """
        scan_id = str(scan_id or "").strip()
        history_data = self._read_json(
            self.scan_history_path, {"schema_version": SCHEMA_VERSION, "scans": []})
        restore_data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}})
        history = next((r for r in history_data.get("scans", [])
                        if r.get("scan_id") == scan_id), None)
        restore = restore_data.get("restore_points", {}).get(scan_id)
        if not history or not restore:
            raise ValueError("Select an active scan with a Recovery snapshot.")
        if history.get("archived") or restore.get("archived"):
            raise ValueError("Unarchive the record before resetting its Odoo work.")
        source = restore
        order_id = str(source.get("order_id") or "").strip()
        if (not order_id or str(typed_order_id or "").strip() != order_id
                or confirmation != "RESET ODOO"
                or external_acknowledged is not True):
            raise PermissionError(
                "Reset requires the exact Order ID and RESET ODOO after "
                "reviewing/deleting or cancelling the old Odoo transactions."
            )
        if (source.get("workflow_state") == "completed" or source.get("completed_at")
                or history.get("workflow_state") == "completed" or history.get("completed_at")):
            raise RuntimeError("Completed filings cannot be reset; inspect/delete instead.")
        if (str(history.get("order_id") or "").strip() != order_id
                or str(history.get("platform") or "").strip()
                != str(source.get("platform") or "").strip()):
            raise RuntimeError("History and Recovery do not match. Resolve JSON before reset.")
        if any(v.get(field) for v in (source, history)
               for field in ("lark_results", "normal_lark_results",
                             "wrong_item_lark_results")):
            raise RuntimeError("This scan has Lark results. Reset is not allowed.")
        if not (source.get("odoo_checkpoint") or source.get("odoo_results")
                or history.get("odoo_checkpoint") or history.get("odoo_results")):
            raise ValueError("There is no recorded Odoo checkpoint to reset.")
        if not source.get("items") or not source.get("order_id"):
            raise ValueError("Cannot reset a scan without its original Order ID and items.")
        old_history = copy.deepcopy(history_data)
        now = _now_iso()
        checkpoint = source.get("odoo_checkpoint") or history.get("odoo_checkpoint") or {}
        results = source.get("odoo_results") or history.get("odoo_results") or {}
        transfers = []
        for group in list(checkpoint.get("returns") or []) + list(results.get("returns") or []):
            transfer_id = str(group.get("transfer_id") or "")
            if transfer_id and transfer_id not in transfers:
                transfers.append(transfer_id)
        pending = checkpoint.get("pending_return") or {}
        if pending.get("transfer_id") and pending["transfer_id"] not in transfers:
            transfers.append(pending["transfer_id"])
        audit = {
            "at": now,
            "action": "manual_odoo_cleanup_reset",
            "previous_ticket_title": str(checkpoint.get("ticket_title") or results.get("ticket_title") or ""),
            "previous_ticket_url": str(checkpoint.get("ticket_url") or results.get("ticket_url") or ""),
            "previous_transfer_ids": transfers,
            "acknowledgment": (
                "Operator reviewed prior Odoo ticket and inventory transfers "
                "and confirmed external cleanup before resubmission"
            ),
        }
        def cleared(record):
            record.update({
                "workflow_state": "manually_saved",
                "case_decision": None,
                "odoo_checkpoint": None,
                "odoo_results": None,
                "lark_results": [],
                "last_error": "",
                "completed_at": "",
                "transfer_display": "Not created yet",
                "updated_at": now,
            })
            record.setdefault("reset_history", []).append(copy.deepcopy(audit))
        # The restore point is the freshest source of item decisions/remarks.
        for field in ("items", "return_case", "new_stock_destination",
                      "platform", "search_by", "search_input", "order_id"):
            if field in source:
                history[field] = copy.deepcopy(source[field])
        cleared(history)
        new_restore = copy.deepcopy(source)
        cleared(new_restore)
        # History first: if the app crashes before writing Recovery, the OLD
        # Recovery checkpoint still blocks resubmitting the Odoo transaction.
        self._atomic_write(self.scan_history_path, history_data)
        try:
            restore_data["restore_points"][scan_id] = new_restore
            self._atomic_write(self.restore_points_path, restore_data)
        except Exception:
            try:
                self._atomic_write(self.scan_history_path, old_history)
            except Exception as rollback_error:
                raise RuntimeError(
                    "Reset failed and history rollback failed; reconcile the JSON "
                    "files from .bak before resubmitting."
                ) from rollback_error
            raise
        updated_scan = self.get_scan(scan_id)
        updated_restore = self.get_restore_point(scan_id)
        if (not updated_scan or not updated_restore
                or updated_scan.get("odoo_checkpoint")
                or updated_restore.get("odoo_checkpoint")
                or updated_restore.get("case_decision")
                or updated_scan.get("workflow_state") != "manually_saved"):
            raise RuntimeError("The Odoo reset could not be verified. Do not submit.")
        return {"mode": "reset_for_resubmission", "scan_id": scan_id,
                "prior_ticket_url": audit["previous_ticket_url"],
                "prior_transfer_ids": transfers}

    def find_prior_odoo_scans(self, platform, order_id, *, exclude_scan_id=None):
        """Return ALL earlier local Odoo records, including archived ones.

        Does not infer external status: it is a local duplicate-prevention guard.
        Recovery may be fresher than its history mirror; prefer it when present.
        """
        platform, order_id = str(platform or "").strip(), str(order_id or "").strip()
        history = self.list_recent_scans(limit=None)
        points = {v["scan_id"]: v for v in self.list_restore_points()}
        by_id = {v["scan_id"]: v for v in history if v.get("scan_id")}
        for scan_id, point in points.items():
            if scan_id not in by_id:
                by_id[scan_id] = point
        found = []
        for scan_id, history_row in by_id.items():
            if scan_id == exclude_scan_id:
                continue
            if history_row.get("platform") != platform or str(history_row.get("order_id") or "") != order_id:
                continue
            record = copy.deepcopy(history_row)
            if scan_id in points:
                point = points[scan_id]
                for field in ("odoo_checkpoint", "odoo_results", "lark_results",
                              "case_decision", "workflow_state", "items"):
                    if field in point:
                        record[field] = copy.deepcopy(point[field])
            if not (record.get("odoo_checkpoint") or record.get("odoo_results")):
                continue
            record["has_restore_point"] = scan_id in points
            found.append(record)
        found.sort(key=lambda r: (bool(r.get("has_restore_point")),
                                  str(r.get("updated_at") or "")), reverse=True)
        return found

    def archive_saved_record(self, scan_id, *, reason="operator_archived"):
        """Hide a scan without destroying Odoo evidence or losing its snapshot.

        Write the archived history record FIRST; remove Recovery only after
        the audit + original checkpoint have been durably saved.
        """
        scan_id = str(scan_id or "").strip()
        if not scan_id:
            raise ValueError("Choose a scan to archive.")
        history_data = self._read_json(
            self.scan_history_path, {"schema_version": SCHEMA_VERSION, "scans": []})
        restore_data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}})
        scans = history_data.setdefault("scans", [])
        history = next((v for v in scans if v.get("scan_id") == scan_id), None)
        restore = restore_data.setdefault("restore_points", {}).get(scan_id)
        if history is None and restore is None:
            raise ValueError("Scan does not exist.")
        if history and history.get("archived"):
            if restore is not None:
                restore_data["restore_points"].pop(scan_id, None)
                self._atomic_write(self.restore_points_path, restore_data)
            return {"mode": "archived", "scan_id": scan_id}
        source = copy.deepcopy(history or restore)
        if restore is not None:
            # Recovery is the authoritative Odoo/Lark state if a prior history
            # write failed. Never replace newer external identifiers with an
            # older history mirror.
            for field in ("odoo_checkpoint", "odoo_results", "lark_results",
                          "case_decision", "workflow_state", "items",
                          "new_stock_destination", "return_case", "last_error"):
                if field in restore:
                    source[field] = copy.deepcopy(restore[field])
        snapshot = copy.deepcopy(restore or source)
        snapshot.pop("archived_restore_snapshot", None)
        source["archived_restore_snapshot"] = snapshot
        now = _now_iso()
        source.update({"archived": True, "archived_at": now,
                       "archived_reason": str(reason or "operator_archived"),
                       "updated_at": now})
        source.setdefault("edit_history", []).append(
            {"at": now, "action": "archive", "reason": source["archived_reason"]})
        if history is None:
            scans.append(source)
        else:
            history.clear()
            history.update(source)
        self._atomic_write(self.scan_history_path, history_data)
        if restore is not None:
            restore_data["restore_points"].pop(scan_id, None)
            self._atomic_write(self.restore_points_path, restore_data)
        return {"mode": "archived", "scan_id": scan_id}

    def reactivate_archived_record(self, scan_id):
        """Return an archived scan to History and, when safe, to Recovery.

        Any previously created Odoo ticket/TC/IN is REVIEW-ONLY on return.
        An archived external checkpoint is *never* made resume_safe=True.
        """
        scan_id = str(scan_id or "").strip()
        data = self._read_json(
            self.scan_history_path, {"schema_version": SCHEMA_VERSION, "scans": []})
        record = next((r for r in data.get("scans", [])
                       if r.get("scan_id") == scan_id), None)
        if record is None or not record.get("archived"):
            raise ValueError("Select an archived record.")
        original = copy.deepcopy(record.get("archived_restore_snapshot") or record)
        for key in ("archived", "archived_at", "archived_reason", "archived_restore_snapshot"):
            original.pop(key, None)
        old_state = str(original.get("workflow_state") or "loaded")
        is_completed = old_state == "completed" or bool(original.get("completed_at"))
        had_external = has_external_work(original)
        can_restore = bool(original.get("order_id") and original.get("items")) and not is_completed
        if had_external:
            checkpoint = original.get("odoo_checkpoint")
            if checkpoint:
                if not original.get("case_decision"):
                    can_restore = False
                else:
                    checkpoint = copy.deepcopy(checkpoint)
                    checkpoint["resume_safe"] = False
                    checkpoint["archived_original_stage"] = checkpoint.get("stage")
                    checkpoint["stage"] = "archived_manual_review"
                    original["odoo_checkpoint"] = checkpoint
                    original["workflow_state"] = "manual_review"
            elif original.get("odoo_results"):
                if not original.get("case_decision") or original.get("lark_results"):
                    can_restore = False
                else:
                    original["workflow_state"] = "lark_pending"
            else:
                can_restore = False
        now = _now_iso()
        record.pop("archived_restore_snapshot", None)
        record.pop("archived", None)
        record.pop("archived_at", None)
        record.pop("archived_reason", None)
        record["updated_at"] = now
        record.setdefault("edit_history", []).append(
            {"at": now, "action": "unarchive", "recovery_reopened": bool(can_restore)})
        if can_restore:
            record["workflow_state"] = original.get("workflow_state", old_state)
            if had_external and original.get("odoo_checkpoint"):
                record["odoo_checkpoint"] = copy.deepcopy(original["odoo_checkpoint"])
        self._atomic_write(self.scan_history_path, data)
        if can_restore:
            original["updated_at"] = now
            original["edit_history"] = copy.deepcopy(record.get("edit_history") or [])
            self.save_restore_point(scan_id, original)
            verified = self.get_restore_point(scan_id)
            if not verified or verified.get("order_id") != record.get("order_id"):
                raise RuntimeError("Reopened Recovery snapshot could not be verified.")
        return {"mode": "unarchived", "scan_id": scan_id,
                "recoverable": bool(can_restore),
                "review_only": bool(had_external)}

    def record_duplicate_override(self, scan_id, *, prior_scan_id,
                                  typed_order_id, reason, confirmation):
        """Write an auditable one-off operator exception BEFORE Odoo submission.

        This does not remove the earlier duplicate evidence and does not turn
        off the duplicate guard for later attempts. A fresh confirmation is
        required each time another Helpdesk ticket is about to be created.
        """
        reason = str(reason or "").strip()
        if len(reason) < 15:
            raise ValueError("Describe why a separate ticket is required (15+ characters).")
        if str(confirmation or "").strip() != "CREATE SEPARATE TICKET":
            raise ValueError("Type CREATE SEPARATE TICKET to confirm the exception.")
        data = self._read_json(
            self.scan_history_path, {"schema_version": SCHEMA_VERSION, "scans": []})
        records = {r.get("scan_id"): r for r in data.get("scans", [])}
        current = records.get(scan_id)
        previous = records.get(prior_scan_id)
        if not current or current.get("archived") or not previous or prior_scan_id == scan_id:
            raise ValueError("Both the new scan and previous recorded case are required.")
        if current.get("odoo_checkpoint") or current.get("odoo_results") or current.get("lark_results"):
            raise RuntimeError("This scan already has Odoo/Lark work; cannot override.")
        if (current.get("platform") != previous.get("platform") or
            current.get("order_id") != previous.get("order_id") or
            str(typed_order_id or "").strip() != str(current.get("order_id") or "")):
            raise ValueError("The exact marketplace Order ID must match both saved scans.")
        prior = previous.get("odoo_checkpoint") or previous.get("odoo_results") or {}
        if not (previous.get("odoo_checkpoint") or previous.get("odoo_results")):
            raise ValueError("The earlier Odoo ticket must be present in local audit records.")
        now = _now_iso()
        event = {
            "at": now, "action": "separate_odoo_ticket_operator_exception",
            "prior_scan_id": prior_scan_id,
            "prior_ticket_title": str(prior.get("ticket_title") or ""),
            "prior_ticket_url": str(prior.get("ticket_url") or ""),
            "reason": reason,
            "verified_order_id": str(typed_order_id).strip(),
            "attestation": "Operator inspected existing Odoo case and confirmed a distinct return",
        }
        current.setdefault("duplicate_override_events", []).append(event)
        current["updated_at"] = now
        self._atomic_write(self.scan_history_path, data)
        saved = self.get_scan(scan_id)
        if not saved or event not in saved.get("duplicate_override_events", []):
            raise RuntimeError("Duplicate exception audit could not be verified.")
        return copy.deepcopy(event)

    @property
    def paths(self):
        return {
            "data_dir": str(self.data_dir),
            "scan_history": str(self.scan_history_path),
            "restore_points": str(self.restore_points_path),
            "settings": str(self.settings_path),
        }
