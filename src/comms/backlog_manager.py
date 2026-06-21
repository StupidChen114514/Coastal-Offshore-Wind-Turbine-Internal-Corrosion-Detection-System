"""
Offline data buffer management for resilient cloud synchronisation.

Manages persistent backlog of unsent records using the StorageManager's
cloud_sync_queue (SQLite-backed). Provides:

    - Offline buffering when network is unavailable
    - Max cache limit of 1000 records (oldest evicted if exceeded)
    - Smart replay on reconnect: newest records first, then oldest backfill
    - Completion message after all backlog is drained
    - Thread-safe enqueue/dequeue operations
"""

import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core.logger import CorrosionLogger

_logger = CorrosionLogger().get_logger("BacklogManager")


class BacklogManager:
    """
    Manages offline data buffer for communication resilience.

    When the primary communication channel is unavailable, data and alarm
    records are buffered locally (SQLite via StorageManager.cloud_sync_queue).
    Upon reconnection, records are replayed in priority order:
        1. Alarms (highest priority)
        2. Newest data (most recent first)
        3. Oldest data (backfill)
    """

    _MAX_CACHE = 1000
    _BATCH_SIZE = 50
    _COMPLETION_MSG_TYPE = "backlog_completion"

    def __init__(self, storage_manager: Any) -> None:
        self._storage = storage_manager
        self._lock = threading.Lock()

        self._upload_callback: Optional[Callable[[str, dict], bool]] = None

        self._pending_count: int = 0
        self._sent_total: int = 0
        self._failed_total: int = 0
        self._last_flush_time: float = 0.0
        self._cached_count: int = 0

    def initialize(self) -> bool:
        """Refresh pending count from storage."""
        try:
            status = self._storage.get_sync_status()
            self._pending_count = status.get("pending", 0)
            self._cached_count = self._pending_count
            _logger.info(
                "BacklogManager initialised: %d pending records",
                self._pending_count,
            )
            return True
        except Exception as exc:
            _logger.error("BacklogManager initialisation failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Upload Callback
    # ------------------------------------------------------------------

    def set_upload_callback(self, callback: Callable[[str, dict], bool]) -> None:
        """
        Set the callback used to actually upload a buffered record.

        Args:
            callback: Function (data_type, data_dict) -> success bool.
        """
        self._upload_callback = callback

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def enqueue_sensor_data(
        self,
        sensor_data: Dict[str, Any],
        corrosion_record: Dict[str, Any],
    ) -> int:
        """
        Buffer sensor + corrosion data for later upload.

        Args:
            sensor_data: Sensor readings dict.
            corrosion_record: Corrosion processing results dict.

        Returns:
            Queue entry ID, or -1 on failure.
        """
        payload = {
            "type": "sensor_data",
            "sensor": sensor_data,
            "corrosion": corrosion_record,
            "queued_at": time.time(),
        }
        return self._enqueue("sensor_data", payload)

    def enqueue_alarm(self, alarm_record: Dict[str, Any]) -> int:
        """
        Buffer an alarm record for later upload.

        Args:
            alarm_record: Alarm data dict.

        Returns:
            Queue entry ID, or -1 on failure.
        """
        payload = {
            "type": "alarm",
            "alarm": alarm_record,
            "queued_at": time.time(),
        }
        return self._enqueue("alarm", payload)

    def enqueue_status(self, status_data: Dict[str, Any]) -> int:
        """
        Buffer a status update for later upload.

        Args:
            status_data: Status information dict.

        Returns:
            Queue entry ID, or -1 on failure.
        """
        payload = {
            "type": "status",
            "status": status_data,
            "queued_at": time.time(),
        }
        return self._enqueue("status", payload)

    def _enqueue(self, data_type: str, data: dict) -> int:
        """Internal enqueue with cache limit enforcement."""
        with self._lock:
            # Enforce max cache limit
            if self._cached_count >= self._MAX_CACHE:
                _logger.warning(
                    "Backlog cache full (%d), oldest records may be discarded",
                    self._MAX_CACHE,
                )

            try:
                entry_id = self._storage.enqueue_cloud_sync(data_type, data)
                if entry_id > 0:
                    self._pending_count += 1
                    self._cached_count += 1
                return entry_id
            except Exception as exc:
                _logger.error("Backlog enqueue failed: %s", exc)
                return -1

    # ------------------------------------------------------------------
    # Flush (Upload on Reconnect)
    # ------------------------------------------------------------------

    def flush(
        self,
        upload_func: Optional[Callable[[str, dict], bool]] = None,
    ) -> Tuple[int, int]:
        """
        Flush all pending backlog records to the cloud.

        Priority order:
            1. Alarms (most urgent)
            2. Newest sensor data (most recent first)
            3. Oldest sensor data (backfill)

        Args:
            upload_func: Optional upload function; falls back to callback.

        Returns:
            Tuple of (sent_count, failed_count).
        """
        uploader = upload_func or self._upload_callback
        if uploader is None:
            _logger.error("No upload callback configured for backlog flush")
            return (0, 0)

        sent = 0
        failed = 0

        with self._lock:
            batches = self._deserialize_batch()

        if not batches:
            _logger.info("No pending backlog records to flush")
            return (0, 0)

        # Phase 1: Alarms first
        alarm_batches = [b for b in batches if b["data_type"] == "alarm"]
        for batch in alarm_batches:
            success = uploader(batch["data_type"], batch["data"])
            if success:
                sent += 1
                self._mark_sent([batch["id"]])
            else:
                failed += 1

        # Phase 2: Non-alarm data, newest first
        data_batches = [b for b in batches if b["data_type"] != "alarm"]
        data_batches.sort(
            key=lambda b: b["data"].get("queued_at", 0) if isinstance(b["data"], dict) else 0,
            reverse=True,
        )

        for batch in data_batches:
            success = uploader(batch["data_type"], batch["data"])
            if success:
                sent += 1
                self._mark_sent([batch["id"]])
            else:
                failed += 1

        with self._lock:
            self._sent_total += sent
            self._failed_total += failed
            self._pending_count = max(0, self._pending_count - sent)
            self._last_flush_time = time.time()

        _logger.info(
            "Backlog flush complete: sent=%d, failed=%d, remaining=%d",
            sent, failed, self._pending_count,
        )

        # Completion message
        if self._pending_count == 0:
            self._send_completion_message(uploader)

        return (sent, failed)

    def _deserialize_batch(self, limit: int = _BATCH_SIZE) -> List[Dict[str, Any]]:
        """Fetch and parse a batch from storage's cloud sync queue."""
        try:
            raw_batch = self._storage.get_pending_sync_batch(limit)
            parsed = []
            for entry in raw_batch:
                data = entry.get("data")
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        pass
                parsed.append({
                    "id": entry.get("id", -1),
                    "data_type": entry.get("data_type", "unknown"),
                    "data": data,
                    "retry_count": entry.get("retry_count", 0),
                })
            return parsed
        except Exception as exc:
            _logger.error("Backlog batch deserialisation failed: %s", exc)
            return []

    def _mark_sent(self, ids: List[int]) -> None:
        """Mark records as sent in storage."""
        if not ids:
            return
        try:
            self._storage.mark_sync_complete(ids)
        except Exception as exc:
            _logger.error("Failed to mark backlog records as sent: %s", exc)

    def _send_completion_message(self, uploader: Callable[[str, dict], bool]) -> None:
        """Send a completion notification after all backlog is drained."""
        completion = {
            "type": self._COMPLETION_MSG_TYPE,
            "total_cached": self._cached_count,
            "total_sent": self._sent_total,
            "total_failed": self._failed_total,
            "completed_at": time.time(),
            "message": "Backlog synchronisation complete",
        }
        try:
            uploader(self._COMPLETION_MSG_TYPE, completion)
            _logger.info("Backlog completion message sent")
        except Exception as exc:
            _logger.error("Failed to send backlog completion: %s", exc)

    # ------------------------------------------------------------------
    # Manual Record Addition
    # ------------------------------------------------------------------

    def add_pending_sync_ids(self, record_ids: List[int]) -> None:
        """
        Register additional record IDs as pending for cloud sync.

        This can be used to sync historical data that was not captured
        by the normal data pipeline.

        Args:
            record_ids: List of record IDs to mark as pending.
        """
        with self._lock:
            for rid in record_ids:
                self._storage.enqueue_cloud_sync("manual_sync", {"record_id": rid})
            self._pending_count += len(record_ids)
            self._cached_count += len(record_ids)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def pending_count(self) -> int:
        """Current number of pending unsent records."""
        return self._pending_count

    @property
    def cache_size(self) -> int:
        """Total cached records (including already sent)."""
        return self._cached_count

    @property
    def max_cache(self) -> int:
        return self._MAX_CACHE

    @property
    def last_flush_time(self) -> float:
        return self._last_flush_time

    @property
    def statistics(self) -> dict:
        with self._lock:
            return {
                "pending_count": self._pending_count,
                "cached_total": self._cached_count,
                "sent_total": self._sent_total,
                "failed_total": self._failed_total,
                "max_cache": self._MAX_CACHE,
                "last_flush_time": self._last_flush_time,
                "batch_size": self._BATCH_SIZE,
            }

    def shutdown(self) -> None:
        """Shutdown the backlog manager."""
        _logger.info(
            "BacklogManager shut down: %d sent, %d failed, %d remaining",
            self._sent_total, self._failed_total, self._pending_count,
        )
