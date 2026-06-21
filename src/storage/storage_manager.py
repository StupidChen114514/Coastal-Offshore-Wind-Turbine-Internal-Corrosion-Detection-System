"""
Multi-level data storage and query module for the Wind Turbine Internal
Corrosion Detection System.

Three-layer storage architecture:
    L1: RingBuffer – memory-based, 100ms resolution, 72-hour max retention
    L2: SQLite   – disk-based, 10-min resolution, 1-year retention
    L3: CloudSyncQueue – pending upload queue for cloud synchronization

Provides thread-safe read/write operations, paginated queries,
CSV/JSON export with Excel-compatible formatting, and database maintenance.
"""

import csv
import json
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from ..core.data_models import (
    AlarmRecord,
    AuditLogEntry,
    CorrosionRecord,
    SensorData,
)
from ..core.logger import CorrosionLogger

_logger = CorrosionLogger().get_logger("Storage")


class RingBuffer:
    """
    Thread-safe fixed-size circular buffer for high-frequency raw sensor data.

    Stores up to *max_entries* SensorData objects.  When full the oldest entry
    is overwritten silently.
    """

    def __init__(self, max_entries: int = 100000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._buffer: List[SensorData] = []
        self._max_entries = max_entries
        self._lock = threading.Lock()
        _logger.info("RingBuffer initialised – capacity=%d", max_entries)

    def push(self, data: SensorData) -> None:
        with self._lock:
            if len(self._buffer) >= self._max_entries:
                self._buffer.pop(0)
            self._buffer.append(data)

    def get_latest(self, count: int = 100) -> List[SensorData]:
        with self._lock:
            return list(self._buffer[-count:])

    def get_range(self, start: datetime, end: datetime) -> List[SensorData]:
        with self._lock:
            return [
                d for d in self._buffer
                if start <= d.timestamp <= end
            ]

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            _logger.info("RingBuffer cleared")

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._buffer)

    def __len__(self) -> int:
        return self.size


class CloudSyncQueue:
    """
    Persistent queue tracking data that has not yet been synced to the cloud.

    Uses the same SQLite database as StorageManager so that queue entries
    survive application restarts.
    """

    _TABLE_DDL = """
        CREATE TABLE IF NOT EXISTS cloud_sync_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_type TEXT NOT NULL,
            data_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            sent_at TEXT,
            retry_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending'
        );
        CREATE INDEX IF NOT EXISTS idx_cloud_sync_status
            ON cloud_sync_queue(status);
    """

    def __init__(self, connection: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = connection
        self._lock = lock

    def _ensure_table(self) -> None:
        with self._lock:
            try:
                self._conn.executescript(self._TABLE_DDL)
                self._conn.commit()
            except sqlite3.Error as exc:
                _logger.error("CloudSyncQueue table creation failed: %s", exc)

    def enqueue(self, data_type: str, data: dict) -> int:
        with self._lock:
            try:
                cursor = self._conn.execute(
                    "INSERT INTO cloud_sync_queue (data_type, data_json) VALUES (?, ?)",
                    (data_type, json.dumps(data, default=str, ensure_ascii=False)),
                )
                self._conn.commit()
                return cursor.lastrowid or -1
            except sqlite3.Error as exc:
                _logger.error("CloudSyncQueue enqueue failed: %s", exc)
                return -1

    def dequeue_batch(self, limit: int = 100) -> List[dict]:
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT id, data_type, data_json, retry_count "
                    "FROM cloud_sync_queue WHERE status = 'pending' "
                    "ORDER BY id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [
                    {
                        "id": r[0],
                        "data_type": r[1],
                        "data": json.loads(r[2]),
                        "retry_count": r[3],
                    }
                    for r in rows
                ]
            except (sqlite3.Error, json.JSONDecodeError) as exc:
                _logger.error("CloudSyncQueue dequeue_batch failed: %s", exc)
                return []

    def mark_sent(self, ids: List[int]) -> None:
        if not ids:
            return
        placeholders = ",".join(["?"] * len(ids))
        with self._lock:
            try:
                self._conn.execute(
                    f"UPDATE cloud_sync_queue SET status = 'sent', "
                    f"sent_at = ? WHERE id IN ({placeholders})",
                    [datetime.now(timezone.utc).isoformat()] + ids,
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                _logger.error("CloudSyncQueue mark_sent failed: %s", exc)

    def get_pending_count(self) -> int:
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM cloud_sync_queue WHERE status = 'pending'"
                ).fetchone()
                return row[0] if row else 0
            except sqlite3.Error as exc:
                _logger.error("CloudSyncQueue get_pending_count failed: %s", exc)
                return 0

    def get_sync_status(self) -> dict:
        with self._lock:
            try:
                pending = self._conn.execute(
                    "SELECT COUNT(*) FROM cloud_sync_queue WHERE status = 'pending'"
                ).fetchone()
                sent = self._conn.execute(
                    "SELECT COUNT(*) FROM cloud_sync_queue WHERE status = 'sent'"
                ).fetchone()
                failed = self._conn.execute(
                    "SELECT COUNT(*) FROM cloud_sync_queue WHERE status = 'failed'"
                ).fetchone()
                return {
                    "pending": pending[0] if pending else 0,
                    "sent": sent[0] if sent else 0,
                    "failed": failed[0] if failed else 0,
                }
            except sqlite3.Error as exc:
                _logger.error("CloudSyncQueue get_sync_status failed: %s", exc)
                return {"pending": 0, "sent": 0, "failed": 0}


class StorageManager:
    """
    Multi-level storage manager for the corrosion detection system.

    L1  RingBuffer       – volatile, sub-second resolution, hours of retention.
    L2  SQLite database   – persistent, minute resolution, 1 year retention.
    L3  CloudSyncQueue    – pending cloud-upload queue with retry tracking.

    Supports paginated time-range queries, CSV/JSON data export, database
    maintenance (vacuum, backup, data retention enforcement) and thread-safe
    operation.
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            temperature REAL,
            humidity REAL,
            cl_deposition REAL,
            delta_d_er REAL,
            delta_d_inductive REAL,
            v_mid REAL,
            v_diff REAL,
            l_eq REAL,
            delta_f REAL,
            valid_flag INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS corrosion_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            delta_d_raw REAL,
            delta_d_corrected REAL,
            delta_d_filtered REAL,
            cr_er REAL,
            cr_inductive REAL,
            cr_out REAL,
            eta REAL,
            status TEXT,
            valid_flag INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS alarm_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alarm_id TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            level INTEGER NOT NULL,
            alarm_type TEXT NOT NULL,
            details TEXT,
            sensor_id TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            operator TEXT,
            resolved_time TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            operator TEXT,
            operation_type TEXT NOT NULL,
            details TEXT,
            result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS config_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            config_json TEXT NOT NULL,
            changed_by TEXT,
            changed_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_sensor_readings_timestamp
            ON sensor_readings(timestamp);
        CREATE INDEX IF NOT EXISTS idx_sensor_readings_valid
            ON sensor_readings(valid_flag);
        CREATE INDEX IF NOT EXISTS idx_corrosion_records_timestamp
            ON corrosion_records(timestamp);
        CREATE INDEX IF NOT EXISTS idx_corrosion_records_valid
            ON corrosion_records(valid_flag);
        CREATE INDEX IF NOT EXISTS idx_alarm_records_timestamp
            ON alarm_records(timestamp);
        CREATE INDEX IF NOT EXISTS idx_alarm_records_status
            ON alarm_records(status);
        CREATE INDEX IF NOT EXISTS idx_alarm_records_level
            ON alarm_records(level);
        CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
            ON audit_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_log_operation_type
            ON audit_log(operation_type);
        CREATE INDEX IF NOT EXISTS idx_config_history_version
            ON config_history(version);
        CREATE INDEX IF NOT EXISTS idx_config_history_changed_at
            ON config_history(changed_at);
    """

    _DATA_TYPE_COLUMN_MAP = {
        "T": "temperature",
        "RH": "humidity",
        "Cl": "cl_deposition",
        "delta_d_ER": "delta_d_er",
        "delta_d_Inductive": "delta_d_inductive",
        "all": None,
    }

    def __init__(
        self,
        db_path: str = "corrosion_data.db",
        ring_buffer_capacity: int = 100000,
    ) -> None:
        self._db_path = db_path
        self._ring_buffer_capacity = ring_buffer_capacity
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._initialized = False

        self._ring_buffer: Optional[RingBuffer] = None
        self._cloud_sync: Optional[CloudSyncQueue] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        _logger.info("Initialising StorageManager – db=%s", self._db_path)
        try:
            self._ring_buffer = RingBuffer(max_entries=self._ring_buffer_capacity)

            self._conn = self._connect_with_retry()
            self._configure_pragmas()
            with self._lock:
                self._conn.executescript(self._SCHEMA)
                self._conn.commit()

            self._cloud_sync = CloudSyncQueue(self._conn, self._lock)
            self._cloud_sync._ensure_table()

            self._enforce_retention()

            self._initialized = True
            _logger.info("StorageManager initialised successfully")
            return True
        except Exception as exc:
            _logger.error("StorageManager initialisation failed: %s", exc)
            return False

    def shutdown(self) -> None:
        _logger.info("Shutting down StorageManager")
        self._initialized = False
        if self._conn:
            try:
                self._conn.close()
            except sqlite3.Error as exc:
                _logger.error("Error closing database: %s", exc)
            finally:
                self._conn = None
        if self._ring_buffer:
            self._ring_buffer.clear()
        _logger.info("StorageManager shut down")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect_with_retry(self, max_attempts: int = 3) -> sqlite3.Connection:
        last_error: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                conn = sqlite3.connect(self._db_path, check_same_thread=False)
                _logger.debug("Database connection established on attempt %d", attempt)
                return conn
            except sqlite3.Error as exc:
                last_error = exc
                _logger.warning(
                    "DB connection attempt %d/%d failed: %s",
                    attempt, max_attempts, exc,
                )
                if attempt < max_attempts:
                    time.sleep(1.0)
        raise last_error or RuntimeError("Failed to connect to database")

    def _configure_pragmas(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")

    def _require_init(self) -> None:
        if not self._initialized or self._conn is None:
            raise RuntimeError("StorageManager is not initialised")

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _dt_to_iso(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    def _execute_transaction(self, statements: List[tuple]) -> bool:
        self._require_init()
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                for sql, params in statements:
                    self._conn.execute(sql, params)
                self._conn.commit()
                return True
            except sqlite3.Error as exc:
                _logger.error("Transaction failed, rolling back: %s", exc)
                try:
                    self._conn.rollback()
                except sqlite3.Error:
                    pass
                return False

    def _enforce_retention(self, retention_days: int = 365) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        deleted = 0
        with self._lock:
            try:
                cur = self._conn.execute(
                    "DELETE FROM sensor_readings WHERE timestamp < ?", (cutoff,)
                )
                deleted += cur.rowcount
                cur = self._conn.execute(
                    "DELETE FROM corrosion_records WHERE timestamp < ?", (cutoff,)
                )
                deleted += cur.rowcount
                self._conn.commit()
                if deleted:
                    _logger.info("Retention cleanup: %d records deleted", deleted)
            except sqlite3.Error as exc:
                _logger.error("Retention enforcement failed: %s", exc)
        return deleted

    # ------------------------------------------------------------------
    # L1  Ring Buffer
    # ------------------------------------------------------------------

    def push_raw_sensor_data(self, data: SensorData) -> None:
        if self._ring_buffer is not None:
            self._ring_buffer.push(data)

    def get_latest_raw_data(self, count: int = 100) -> List[SensorData]:
        if self._ring_buffer is None:
            return []
        return self._ring_buffer.get_latest(count)

    def get_raw_data_range(self, start: datetime, end: datetime) -> List[SensorData]:
        if self._ring_buffer is None:
            return []
        return self._ring_buffer.get_range(start, end)

    # ------------------------------------------------------------------
    # L2  Database writes
    # ------------------------------------------------------------------

    def save_sensor_reading(self, data: SensorData) -> bool:
        self._require_init()
        return self._execute_transaction([
            (
                """INSERT INTO sensor_readings
                   (timestamp, temperature, humidity, cl_deposition,
                    delta_d_er, delta_d_inductive, v_mid, v_diff, l_eq,
                    delta_f, valid_flag)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._dt_to_iso(data.timestamp),
                    data.T, data.RH, data.Cl_deposition,
                    data.delta_d_ER, data.delta_d_Inductive,
                    data.V_mid, data.V_diff, data.L_eq,
                    data.delta_f,
                    int(data.valid_flag),
                ),
            )
        ])

    def save_corrosion_record(self, record: CorrosionRecord) -> bool:
        self._require_init()
        return self._execute_transaction([
            (
                """INSERT INTO corrosion_records
                   (timestamp, delta_d_raw, delta_d_corrected, delta_d_filtered,
                    cr_er, cr_inductive, cr_out, eta, status, valid_flag)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._dt_to_iso(record.timestamp),
                    record.delta_d_raw, record.delta_d_corrected,
                    record.delta_d_filtered, record.CR_ER,
                    record.CR_Inductive, record.CR_out, record.eta,
                    record.status,
                    int(record.valid_flag),
                ),
            )
        ])

    def save_alarm_record(self, alarm: AlarmRecord) -> bool:
        self._require_init()
        return self._execute_transaction([
            (
                """INSERT OR REPLACE INTO alarm_records
                   (alarm_id, timestamp, level, alarm_type, details,
                    sensor_id, status, operator, resolved_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(alarm.alarm_id),
                    self._dt_to_iso(alarm.timestamp),
                    alarm.level.value,
                    alarm.alarm_type.value,
                    json.dumps(alarm.details, default=str, ensure_ascii=False),
                    alarm.sensor_id,
                    alarm.status.value,
                    alarm.operator,
                    self._dt_to_iso(alarm.resolved_time) if alarm.resolved_time else None,
                ),
            )
        ])

    def save_audit_log(self, entry: AuditLogEntry) -> bool:
        self._require_init()
        return self._execute_transaction([
            (
                """INSERT INTO audit_log
                   (timestamp, operator, operation_type, details, result)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    self._dt_to_iso(entry.timestamp),
                    entry.operator,
                    entry.operation_type.value,
                    json.dumps(entry.details, default=str, ensure_ascii=False),
                    entry.result,
                ),
            )
        ])

    def save_config_version(self, version: str, config_json: str, changed_by: str) -> bool:
        self._require_init()
        return self._execute_transaction([
            (
                """INSERT INTO config_history (version, config_json, changed_by)
                   VALUES (?, ?, ?)""",
                (version, config_json, changed_by),
            )
        ])

    # ------------------------------------------------------------------
    # L2  Database queries
    # ------------------------------------------------------------------

    def query_sensor_data(
        self,
        start: datetime,
        end: datetime,
        data_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 1000,
    ) -> dict:
        self._require_init()
        return self._query_table(
            table="sensor_readings",
            columns=[
                "id", "timestamp", "temperature", "humidity", "cl_deposition",
                "delta_d_er", "delta_d_inductive", "v_mid", "v_diff",
                "l_eq", "delta_f", "valid_flag",
            ],
            start=start,
            end=end,
            data_type=data_type,
            page=page,
            page_size=page_size,
        )

    def query_corrosion_records(
        self,
        start: datetime,
        end: datetime,
        page: int = 1,
    ) -> dict:
        self._require_init()
        return self._query_table(
            table="corrosion_records",
            columns=[
                "id", "timestamp", "delta_d_raw", "delta_d_corrected",
                "delta_d_filtered", "cr_er", "cr_inductive", "cr_out",
                "eta", "status", "valid_flag",
            ],
            start=start,
            end=end,
            data_type=None,
            page=page,
            page_size=1000,
        )

    def query_alarms(
        self,
        status: Optional[str] = None,
        level: Optional[int] = None,
        page: int = 1,
    ) -> dict:
        self._require_init()
        page_size = 100
        base_sql = "FROM alarm_records WHERE 1=1"
        params: list = []

        if status:
            base_sql += " AND status = ?"
            params.append(status)
        if level is not None:
            base_sql += " AND level = ?"
            params.append(level)

        with self._lock:
            try:
                total = self._conn.execute(
                    f"SELECT COUNT(*) {base_sql}", params
                ).fetchone()[0]
            except sqlite3.Error as exc:
                _logger.error("query_alarms count failed: %s", exc)
                return self._empty_page(page, page_size)

        offset = (page - 1) * page_size
        with self._lock:
            try:
                rows = self._conn.execute(
                    f"SELECT * {base_sql} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    params + [page_size, offset],
                ).fetchall()
                cols = [desc[0] for desc in self._conn.execute(
                    "SELECT * FROM alarm_records LIMIT 0"
                ).description]
            except sqlite3.Error as exc:
                _logger.error("query_alarms failed: %s", exc)
                return self._empty_page(page, page_size)

        return self._paginated_result(
            [dict(zip(cols, r)) for r in rows],
            total, page, page_size,
        )

    def query_audit_log(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        operation_type: Optional[str] = None,
        page: int = 1,
    ) -> dict:
        self._require_init()
        page_size = 100
        base_sql = "FROM audit_log WHERE 1=1"
        params: list = []

        if start:
            base_sql += " AND timestamp >= ?"
            params.append(self._dt_to_iso(start))
        if end:
            base_sql += " AND timestamp <= ?"
            params.append(self._dt_to_iso(end))
        if operation_type:
            base_sql += " AND operation_type = ?"
            params.append(operation_type)

        with self._lock:
            try:
                total = self._conn.execute(
                    f"SELECT COUNT(*) {base_sql}", params
                ).fetchone()[0]
            except sqlite3.Error as exc:
                _logger.error("query_audit_log count failed: %s", exc)
                return self._empty_page(page, page_size)

        offset = (page - 1) * page_size
        with self._lock:
            try:
                rows = self._conn.execute(
                    f"SELECT * {base_sql} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                    params + [page_size, offset],
                ).fetchall()
                cols = [desc[0] for desc in self._conn.execute(
                    "SELECT * FROM audit_log LIMIT 0"
                ).description]
            except sqlite3.Error as exc:
                _logger.error("query_audit_log failed: %s", exc)
                return self._empty_page(page, page_size)

        return self._paginated_result(
            [dict(zip(cols, r)) for r in rows],
            total, page, page_size,
        )

    def _query_table(
        self,
        table: str,
        columns: List[str],
        start: datetime,
        end: datetime,
        data_type: Optional[str],
        page: int,
        page_size: int,
    ) -> dict:
        base_sql = f"FROM {table} WHERE timestamp >= ? AND timestamp <= ?"
        params: list = [self._dt_to_iso(start), self._dt_to_iso(end)]

        if data_type and data_type != "all":
            col = self._DATA_TYPE_COLUMN_MAP.get(data_type)
            if col:
                base_sql += f" AND {col} IS NOT NULL"

        with self._lock:
            try:
                total = self._conn.execute(
                    f"SELECT COUNT(*) {base_sql}", params
                ).fetchone()[0]
            except sqlite3.Error as exc:
                _logger.error("_query_table count (%s) failed: %s", table, exc)
                return self._empty_page(page, page_size)

        offset = (page - 1) * page_size
        col_str = ", ".join(columns)
        with self._lock:
            try:
                rows = self._conn.execute(
                    f"SELECT {col_str} {base_sql} ORDER BY timestamp ASC LIMIT ? OFFSET ?",
                    params + [page_size, offset],
                ).fetchall()
            except sqlite3.Error as exc:
                _logger.error("_query_table (%s) fetch failed: %s", table, exc)
                return self._empty_page(page, page_size)

        return self._paginated_result(
            [dict(zip(columns, r)) for r in rows],
            total, page, page_size,
        )

    # ------------------------------------------------------------------
    #  Pagination helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _paginated_result(
        data: List[dict], total: int, page: int, page_size: int
    ) -> dict:
        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "data": data,
            "total_count": total,
            "page": page,
            "page_size": page_size,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }

    @staticmethod
    def _empty_page(page: int, page_size: int) -> dict:
        return {
            "data": [],
            "total_count": 0,
            "page": page,
            "page_size": page_size,
            "has_next": False,
            "has_prev": False,
        }

    # ------------------------------------------------------------------
    #  Data export
    # ------------------------------------------------------------------

    def export_csv(
        self,
        data_type: str,
        start: datetime,
        end: datetime,
        filepath: str,
    ) -> str:
        self._require_init()

        if data_type in ("sensor_readings", "sensor_data", "sensor"):
            table = "sensor_readings"
            headers = [
                "id", "timestamp", "temperature(°C)", "humidity(%)",
                "cl_deposition(mg/(m²·day))", "delta_d_er(μm)",
                "delta_d_inductive(μm)", "v_mid(V)", "v_diff(V)",
                "l_eq(H)", "delta_f(Hz)", "valid_flag",
            ]
            columns = [
                "id", "timestamp", "temperature", "humidity",
                "cl_deposition", "delta_d_er", "delta_d_inductive",
                "v_mid", "v_diff", "l_eq", "delta_f", "valid_flag",
            ]
        elif data_type in ("corrosion_records", "corrosion", "cr"):
            table = "corrosion_records"
            headers = [
                "id", "timestamp", "delta_d_raw(μm)", "delta_d_corrected(μm)",
                "delta_d_filtered(μm)", "cr_er(μm/year)", "cr_inductive(μm/year)",
                "cr_out(μm/year)", "eta", "status", "valid_flag",
            ]
            columns = [
                "id", "timestamp", "delta_d_raw", "delta_d_corrected",
                "delta_d_filtered", "cr_er", "cr_inductive",
                "cr_out", "eta", "status", "valid_flag",
            ]
        elif data_type in ("alarm_records", "alarms", "alarm"):
            table = "alarm_records"
            headers = [
                "id", "alarm_id", "timestamp", "level", "alarm_type",
                "details", "sensor_id", "status", "operator", "resolved_time",
            ]
            columns = headers[:]
        elif data_type in ("audit_log", "audit"):
            table = "audit_log"
            headers = [
                "id", "timestamp", "operator", "operation_type",
                "details", "result",
            ]
            columns = headers[:]
        else:
            raise ValueError(f"Unknown data_type for CSV export: {data_type}")

        col_str = ", ".join(columns)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {col_str} FROM {table} "
                "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC",
                (self._dt_to_iso(start), self._dt_to_iso(end)),
            ).fetchall()

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

        _logger.info("CSV exported: %s (%d rows)", filepath, len(rows))
        return filepath

    def export_json(
        self,
        data_type: str,
        start: datetime,
        end: datetime,
        filepath: str,
    ) -> str:
        self._require_init()

        if data_type in ("sensor_readings", "sensor_data", "sensor"):
            table = "sensor_readings"
            columns = [
                "id", "timestamp", "temperature", "humidity",
                "cl_deposition", "delta_d_er", "delta_d_inductive",
                "v_mid", "v_diff", "l_eq", "delta_f", "valid_flag",
            ]
            data_structure = {
                "temperature": {"unit": "°C", "description": "温度"},
                "humidity": {"unit": "%", "description": "相对湿度"},
                "cl_deposition": {"unit": "mg/(m²·day)", "description": "氯离子沉积速率"},
                "delta_d_er": {"unit": "μm", "description": "电阻传感器厚度损失"},
                "delta_d_inductive": {"unit": "μm", "description": "电感传感器厚度损失"},
                "v_mid": {"unit": "V", "description": "桥路中点电压"},
                "v_diff": {"unit": "V", "description": "桥路差分电压"},
                "l_eq": {"unit": "H", "description": "等效电感"},
                "delta_f": {"unit": "Hz", "description": "频率偏移"},
            }
        elif data_type in ("corrosion_records", "corrosion", "cr"):
            table = "corrosion_records"
            columns = [
                "id", "timestamp", "delta_d_raw", "delta_d_corrected",
                "delta_d_filtered", "cr_er", "cr_inductive",
                "cr_out", "eta", "status", "valid_flag",
            ]
            data_structure = {
                "delta_d_raw": {"unit": "μm", "description": "原始厚度损失"},
                "delta_d_corrected": {"unit": "μm", "description": "温度补偿后厚度损失"},
                "delta_d_filtered": {"unit": "μm", "description": "滤波后厚度损失"},
                "cr_er": {"unit": "μm/year", "description": "电阻法腐蚀速率"},
                "cr_inductive": {"unit": "μm/year", "description": "电感法腐蚀速率"},
                "cr_out": {"unit": "μm/year", "description": "融合输出腐蚀速率"},
                "eta": {"description": "腐蚀效率因子"},
            }
        elif data_type in ("alarm_records", "alarms", "alarm"):
            table = "alarm_records"
            columns = [
                "id", "alarm_id", "timestamp", "level", "alarm_type",
                "details", "sensor_id", "status", "operator", "resolved_time",
            ]
            data_structure = {
                "level": {"description": "报警等级 (1-4)"},
                "alarm_type": {"description": "报警类型"},
                "status": {"description": "报警状态"},
            }
        elif data_type in ("audit_log", "audit"):
            table = "audit_log"
            columns = [
                "id", "timestamp", "operator", "operation_type",
                "details", "result",
            ]
            data_structure = {
                "operation_type": {"description": "操作类型"},
                "result": {"description": "操作结果"},
            }
        else:
            raise ValueError(f"Unknown data_type for JSON export: {data_type}")

        col_str = ", ".join(columns)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {col_str} FROM {table} "
                "WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC",
                (self._dt_to_iso(start), self._dt_to_iso(end)),
            ).fetchall()

        records = [dict(zip(columns, r)) for r in rows]

        export_data = {
            "metadata": {
                "device_id": "WTICDS-001",
                "software_version": "1.0.0",
                "export_time": self._utcnow_iso(),
                "data_type": data_type,
                "start_time": self._dt_to_iso(start),
                "end_time": self._dt_to_iso(end),
                "record_count": len(records),
                "data_structure_description": data_structure,
            },
            "records": records,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)

        _logger.info("JSON exported: %s (%d records)", filepath, len(records))
        return filepath

    # ------------------------------------------------------------------
    #  Maintenance
    # ------------------------------------------------------------------

    def cleanup_old_data(self, retention_days: int = 365) -> int:
        self._require_init()
        return self._enforce_retention(retention_days)

    def get_database_stats(self) -> dict:
        self._require_init()
        stats: Dict[str, Any] = {}
        tables = [
            "sensor_readings", "corrosion_records", "alarm_records",
            "audit_log", "config_history", "cloud_sync_queue",
        ]
        with self._lock:
            for table in tables:
                try:
                    row = self._conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()
                    stats[f"{table}_count"] = row[0] if row else 0
                except sqlite3.Error:
                    stats[f"{table}_count"] = -1

            try:
                row = self._conn.execute(
                    "SELECT MIN(timestamp), MAX(timestamp) FROM sensor_readings"
                ).fetchone()
                stats["sensor_readings_earliest"] = row[0] if row else None
                stats["sensor_readings_latest"] = row[1] if row else None
            except sqlite3.Error:
                stats["sensor_readings_earliest"] = None
                stats["sensor_readings_latest"] = None

            try:
                file_size = os.path.getsize(self._db_path)
                stats["database_size_bytes"] = file_size
                stats["database_size_mb"] = round(file_size / (1024 * 1024), 2)
            except OSError:
                stats["database_size_bytes"] = -1
                stats["database_size_mb"] = -1

        if self._ring_buffer:
            stats["ring_buffer_entries"] = self._ring_buffer.size
            stats["ring_buffer_capacity"] = self._ring_buffer_capacity

        if self._cloud_sync:
            stats["cloud_sync"] = self._cloud_sync.get_sync_status()

        return stats

    def vacuum_database(self) -> None:
        self._require_init()
        _logger.info("Starting database VACUUM")
        with self._lock:
            self._conn.execute("VACUUM")
        _logger.info("Database VACUUM complete")

    def backup_database(self, backup_path: str) -> bool:
        self._require_init()
        try:
            dst_dir = os.path.dirname(backup_path)
            if dst_dir:
                os.makedirs(dst_dir, exist_ok=True)

            with self._lock:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

            shutil.copy2(self._db_path, backup_path)
            _logger.info("Database backed up to %s", backup_path)
            return True
        except (OSError, sqlite3.Error) as exc:
            _logger.error("Database backup failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # L3  Cloud sync
    # ------------------------------------------------------------------

    def enqueue_cloud_sync(self, data_type: str, data: dict) -> int:
        self._require_init()
        if self._cloud_sync is None:
            return -1
        return self._cloud_sync.enqueue(data_type, data)

    def get_pending_sync_batch(self, limit: int = 100) -> List[dict]:
        self._require_init()
        if self._cloud_sync is None:
            return []
        return self._cloud_sync.dequeue_batch(limit)

    def mark_sync_complete(self, ids: List[int]) -> None:
        self._require_init()
        if self._cloud_sync is not None:
            self._cloud_sync.mark_sent(ids)

    def get_sync_status(self) -> dict:
        self._require_init()
        if self._cloud_sync is None:
            return {"pending": 0, "sent": 0, "failed": 0}
        return self._cloud_sync.get_sync_status()
