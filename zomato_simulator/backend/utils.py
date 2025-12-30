"""
Database helper functions (DB-only).
Put this file at: backend/Database/utils.py

This module exposes plain Python functions that operate on the SQLite DB.
No Flask/FastAPI/HTTP logic here — just DB access functions ready to be imported by app.py.
Extra helpers:
 - remove_worker now cascades deletes to related tables
 - add_field_to_worker / remove_field_from_worker store extra fields inside `notes` JSON
"""

import sqlite3
import os
import json
from typing import Dict, Any, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "gigworkers.db")


# ---------------------------
# Low-level helpers
# ---------------------------
def _ensure_db_exists():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database file not found at: {DB_PATH}. Run init_db.py first.")


def _get_conn():
    _ensure_db_exists()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None else None


# ---------------------------
# Read functions
# ---------------------------
def print_database() -> Dict[str, List[Dict[str, Any]]]:
    """Return all rows from all main tables as a dict."""
    tables = ["workers", "orders", "termination_status", "termination_logs", "review_counts"]
    out: Dict[str, List[Dict[str, Any]]] = {}
    conn = _get_conn()
    cur = conn.cursor()
    for t in tables:
        try:
            cur.execute(f"SELECT * FROM {t}")
            out[t] = [dict(r) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            out[t] = []
    conn.close()
    return out


def list_workers() -> List[Dict[str, Any]]:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM workers ORDER BY joined_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_worker_summary(worker_id: str) -> Dict[str, Any]:
    """Return aggregated worker data (worker row, orders, termination_status, logs, review_counts)."""
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,))
    worker = _row_to_dict(cur.fetchone())

    cur.execute("SELECT * FROM orders WHERE worker_id = ? ORDER BY order_date DESC", (worker_id,))
    orders = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM termination_status WHERE worker_id = ?", (worker_id,))
    termination_status = _row_to_dict(cur.fetchone())

    cur.execute("SELECT * FROM termination_logs WHERE worker_id = ? ORDER BY logged_at DESC", (worker_id,))
    termination_logs = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM review_counts WHERE worker_id = ?", (worker_id,))
    review_counts = _row_to_dict(cur.fetchone())

    conn.close()
    return {
        "worker": worker,
        "orders": orders,
        "termination_status": termination_status,
        "termination_logs": termination_logs,
        "review_counts": review_counts
    }


# ---------------------------
# Workers CRUD
# ---------------------------
def add_worker(worker: Dict[str, Any]) -> bool:
    """Insert a worker row. Returns True on success, False if worker_id exists."""
    if "worker_id" not in worker:
        raise ValueError("worker must contain 'worker_id'")

    fields = ["worker_id", "name", "phone", "email", "joined_at", "current_status", "notes"]
    values = [worker.get(f) for f in fields]

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO workers (worker_id, name, phone, email, joined_at, current_status, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            values
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_worker(worker_id: str) -> bool:
    """
    Delete the worker row AND cascade-delete associated rows:
     - orders
     - termination_status
     - termination_logs
     - review_counts

    Returns True if a worker row was deleted, False otherwise.
    """
    conn = _get_conn()
    cur = conn.cursor()
    # Delete related rows first to avoid FK issues
    cur.execute("DELETE FROM orders WHERE worker_id = ?", (worker_id,))
    cur.execute("DELETE FROM termination_status WHERE worker_id = ?", (worker_id,))
    cur.execute("DELETE FROM termination_logs WHERE worker_id = ?", (worker_id,))
    cur.execute("DELETE FROM review_counts WHERE worker_id = ?", (worker_id,))

    # Delete worker
    cur.execute("DELETE FROM workers WHERE worker_id = ?", (worker_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


# ---------------------------
# Orders CRUD
# ---------------------------
def add_order(order: Dict[str, Any]) -> bool:
    """Insert an order row. Required: order_id, worker_id"""
    if "order_id" not in order or "worker_id" not in order:
        raise ValueError("order must contain 'order_id' and 'worker_id'")

    fields = [
        "order_id", "worker_id", "order_date", "distance_km", "duration_min",
        "payout_amount", "status", "flags", "payment_compliant", "reduction_reason"
    ]
    values = [order.get(f) for f in fields]

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO orders
            (order_id, worker_id, order_date, distance_km, duration_min, payout_amount, status, flags, payment_compliant, reduction_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_order(order_id: str) -> bool:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


# ---------------------------
# Termination status (upsert) & remove
# ---------------------------
def add_or_update_termination_status(status: Dict[str, Any]) -> None:
    if "worker_id" not in status:
        raise ValueError("status must contain 'worker_id'")

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT OR REPLACE INTO termination_status
        (worker_id, is_terminated, terminated_at, termination_reason_code, termination_reason_text, appeal_allowed, appeal_deadline)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            status.get("worker_id"),
            status.get("is_terminated", 0),
            status.get("terminated_at"),
            status.get("termination_reason_code"),
            status.get("termination_reason_text"),
            status.get("appeal_allowed", 0),
            status.get("appeal_deadline")
        )
    )
    conn.commit()
    conn.close()


def remove_termination_status(worker_id: str) -> bool:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM termination_status WHERE worker_id = ?", (worker_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


# ---------------------------
# Termination logs CRUD
# ---------------------------
def add_termination_log(log: Dict[str, Any]) -> int:
    if "worker_id" not in log:
        raise ValueError("log must contain 'worker_id'")

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO termination_logs
        (worker_id, logged_at, reason_code, reason_text, related_order_id, evidence, severity, action_taken, recorded_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            log.get("worker_id"),
            log.get("logged_at"),
            log.get("reason_code"),
            log.get("reason_text"),
            log.get("related_order_id"),
            log.get("evidence"),
            log.get("severity", 0),
            log.get("action_taken"),
            log.get("recorded_by")
        )
    )
    conn.commit()
    log_id = cur.lastrowid
    conn.close()
    return log_id


def remove_termination_log(log_id: int) -> bool:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM termination_logs WHERE log_id = ?", (log_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


# ---------------------------
# Review counts upsert & remove
# ---------------------------
def add_or_update_review_counts(rc: Dict[str, Any]) -> None:
    if "worker_id" not in rc:
        raise ValueError("rc must contain 'worker_id'")

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT OR REPLACE INTO review_counts
        (worker_id, count_5, count_4, count_3, count_2, count_1, total_reviews)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            rc.get("worker_id"),
            rc.get("count_5", 0),
            rc.get("count_4", 0),
            rc.get("count_3", 0),
            rc.get("count_2", 0),
            rc.get("count_1", 0),
            rc.get("total_reviews", 0)
        )
    )
    conn.commit()
    conn.close()


def remove_review_counts(worker_id: str) -> bool:
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM review_counts WHERE worker_id = ?", (worker_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


# ---------------------------
# Extra helpers: add/remove arbitrary fields inside a worker record (stored as JSON in notes)
# ---------------------------
def _read_notes_json(notes_value: Optional[str]) -> Dict[str, Any]:
    if not notes_value:
        return {}
    try:
        return json.loads(notes_value)
    except Exception:
        # if notes isn't valid JSON, preserve it under a special key
        return {"__raw_notes": notes_value}


def add_field_to_worker(worker_id: str, field: str, value: Any) -> bool:
    """
    Add or update a key inside the worker.notes JSON blob.
    Returns True if worker existed and update succeeded, False if worker not found.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT notes FROM workers WHERE worker_id = ?", (worker_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return False

    notes = _read_notes_json(row["notes"])
    notes[field] = value
    notes_str = json.dumps(notes)
    cur.execute("UPDATE workers SET notes = ? WHERE worker_id = ?", (notes_str, worker_id))
    conn.commit()
    conn.close()
    return True


def remove_field_from_worker(worker_id: str, field: str) -> bool:
    """
    Remove a key from the worker.notes JSON blob.
    Returns True if worker existed and field removed or not present; False if worker not found.
    """
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT notes FROM workers WHERE worker_id = ?", (worker_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return False

    notes = _read_notes_json(row["notes"])
    if field in notes:
        notes.pop(field)
        notes_str = json.dumps(notes)
        cur.execute("UPDATE workers SET notes = ? WHERE worker_id = ?", (notes_str, worker_id))
        conn.commit()
    conn.close()
    return True
