import copy
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCHEMA_VERSION = 1
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
        self.last_warning = ""

        self._ensure_file(
            self.scan_history_path,
            {"schema_version": SCHEMA_VERSION, "scans": []},
        )
        self._ensure_file(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}},
        )

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
            "odoo_results": None,
            "odoo_checkpoint": None,
            "lark_results": [],
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
        points = data.setdefault("restore_points", {})
        existing = points.get(scan_id, {})
        created_at = existing.get("created_at") or _now_iso()
        points[scan_id] = {
            "scan_id": scan_id,
            "created_at": created_at,
            "updated_at": _now_iso(),
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
        return copy.deepcopy(value) if value else None

    def list_restore_points(self):
        data = self._read_json(
            self.restore_points_path,
            {"schema_version": SCHEMA_VERSION, "restore_points": {}},
        )
        points = list(data.get("restore_points", {}).values())
        points.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return copy.deepcopy(points)

    @property
    def paths(self):
        return {
            "data_dir": str(self.data_dir),
            "scan_history": str(self.scan_history_path),
            "restore_points": str(self.restore_points_path),
        }
