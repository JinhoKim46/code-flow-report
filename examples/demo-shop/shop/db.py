"""SQLite connection and the one write gateway every change goes through."""
import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "shop.db"


def connect():
    return sqlite3.connect(DB_PATH)


def run_write(action, actor, payload, work):
    """Runs work(cur) and its audit row in one transaction, so a change is never unrecorded."""
    with connect() as conn:
        cur = conn.cursor()
        result = work(cur)
        cur.execute("INSERT INTO audit_log (action, actor, detail, at) VALUES (?, ?, ?, ?)",
                    (action, actor, json.dumps(payload), datetime.now(timezone.utc).isoformat()))
        return result
