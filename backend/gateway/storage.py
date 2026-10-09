"""SQLite persistence for the single-worker demo server.

Request snapshots, report/approval history, virtual state and adapter receipts are
committed before a successful response. A process lock prevents two servers from
recovering or controlling the same demo database concurrently.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from backend.simulator.model import MODEL


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def initial_demo_state(revision=1):
    now = time.time()
    return {"revision": revision, "temperature_c": 60.0, "load_ratio": 1.0,
            "pump_speed_pct": 100.0, "target_pump_speed_pct": 100.0,
            "sensor_quality": "valid", "observed_at": now, "calculated_at": now,
            "simulation_time_s": 0.0, "model_version": MODEL.version,
            "domain_status": "ready", "domain_reason": None}


class SQLiteStore:
    def __init__(self, path=":memory:"):
        self.lock = threading.RLock()
        self.path = str(path)
        self._process_lock = None
        self.connection = None
        try:
            if self.path != ":memory:":
                db_path = Path(self.path).expanduser().resolve()
                db_path.parent.mkdir(parents=True, exist_ok=True)
                self.path = str(db_path)
                self._acquire_process_lock()
            self.connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self._migrate()
        except BaseException:
            self.close()
            raise

    def _acquire_process_lock(self):
        handle = open(self.path + ".lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, 2)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("Database already in use; run only one server/worker per database.") from exc
        self._process_lock = handle

    def close(self):
        with self.lock:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
            if self._process_lock is not None:
                self._process_lock.close()
                self._process_lock = None

    @contextmanager
    def transaction(self):
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def _migrate(self):
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > 3:
            raise RuntimeError("Database schema is newer than this server supports.")
        if version == 0:
            with self.transaction() as db:
                db.execute("CREATE TABLE requests (id TEXT PRIMARY KEY, record_json TEXT NOT NULL)")
                db.execute("""CREATE TABLE reports (
                    request_id TEXT NOT NULL REFERENCES requests(id),
                    digest TEXT NOT NULL, report_json TEXT NOT NULL,
                    PRIMARY KEY (request_id, digest))""")
                db.execute("""CREATE TABLE approvals (
                    request_id TEXT NOT NULL REFERENCES requests(id),
                    report_digest TEXT NOT NULL, approval_json TEXT NOT NULL,
                    PRIMARY KEY (request_id, report_digest))""")
                db.execute("CREATE TABLE demo_state (id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL)")
                db.execute("CREATE TABLE adapter_executions (id TEXT PRIMARY KEY, result_json TEXT NOT NULL)")
                db.execute("INSERT INTO demo_state VALUES (1, ?)", (encode(initial_demo_state()),))
                db.execute("PRAGMA user_version=2")
            version = 2
        if version == 1:
            # The old adapter had no dynamic temperature or clock. Seed those
            # with explicit demo assumptions; never rewrite historical reports.
            with self.transaction() as db:
                old = json.loads(db.execute("SELECT state_json FROM demo_state WHERE id=1").fetchone()[0])
                state = initial_demo_state(old["revision"] + 1)
                state.update(load_ratio=old["load_ratio"], pump_speed_pct=old["pump_speed_pct"],
                             target_pump_speed_pct=old["pump_speed_pct"], sensor_quality=old["sensor_quality"])
                db.execute("UPDATE demo_state SET state_json=? WHERE id=1", (encode(state),))
                db.execute("PRAGMA user_version=2")
            version = 2

        if version == 2:
            with self.transaction() as db:
                db.execute("CREATE TABLE request_contacts (request_id TEXT PRIMARY KEY REFERENCES requests(id), contact TEXT NOT NULL)")
                db.execute("""CREATE TABLE notifications (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests(id),
                    report_digest TEXT NOT NULL, notification_json TEXT NOT NULL,
                    UNIQUE(request_id, report_digest))""")
                db.execute("PRAGMA user_version=3")

    def get(self, request_id):
        with self.lock:
            value = self.connection.execute("SELECT record_json FROM requests WHERE id=?", (request_id,)).fetchone()
            return json.loads(value[0]) if value else None

    def list_records(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.connection.execute("SELECT record_json FROM requests ORDER BY rowid DESC")]

    def save(self, record, contact=None, notification=None):
        with self.transaction() as db:
            db.execute("""INSERT INTO requests VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET record_json=excluded.record_json""",
                (record["id"], encode(record)))
            if record["report"]:
                db.execute("INSERT OR IGNORE INTO reports VALUES (?, ?, ?)",
                    (record["id"], record["report"]["digest"], encode(record["report"])))
            if record["approval"]:
                db.execute("INSERT OR IGNORE INTO approvals VALUES (?, ?, ?)",
                    (record["id"], record["approval"]["report_digest"], encode(record["approval"])))
            if contact is not None:
                db.execute("INSERT INTO request_contacts VALUES (?, ?) ON CONFLICT(request_id) DO UPDATE SET contact=excluded.contact",
                    (record["id"], contact))
            if notification is not None:
                db.execute("""INSERT INTO notifications VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET notification_json=excluded.notification_json""",
                    (notification["id"], record["id"], notification["report_digest"], encode(notification)))


    def history(self, request_id):
        with self.lock:
            reports = [json.loads(row[0]) for row in self.connection.execute(
                "SELECT report_json FROM reports WHERE request_id=? ORDER BY rowid", (request_id,))]
            approvals = [json.loads(row[0]) for row in self.connection.execute(
                "SELECT approval_json FROM approvals WHERE request_id=? ORDER BY rowid", (request_id,))]
            return {"reports": reports, "approvals": approvals}

    def read_demo_state(self):
        with self.lock:
            return json.loads(self.connection.execute("SELECT state_json FROM demo_state WHERE id=1").fetchone()[0])

    def get_execution(self, execution_id):
        with self.lock:
            row = self.connection.execute("SELECT result_json FROM adapter_executions WHERE id=?", (execution_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list_executions(self):
        with self.lock:
            return {row[0]: json.loads(row[1]) for row in self.connection.execute("SELECT id, result_json FROM adapter_executions")}

    def contact(self, request_id):
        with self.lock:
            row = self.connection.execute("SELECT contact FROM request_contacts WHERE request_id=?", (request_id,)).fetchone()
            return row[0] if row else None


    def notifications(self, request_id=None):
        with self.lock:
            if request_id is None:
                cursor = self.connection.execute("SELECT notification_json FROM notifications ORDER BY rowid")
            else:
                cursor = self.connection.execute("SELECT notification_json FROM notifications WHERE request_id=? ORDER BY rowid", (request_id,))
            return [json.loads(row[0]) for row in cursor]
