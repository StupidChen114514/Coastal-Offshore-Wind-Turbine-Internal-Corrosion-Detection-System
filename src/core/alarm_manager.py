"""
Alarm lifecycle manager for the Wind Turbine Internal Corrosion Detection System.

Implements the four-level alarm hierarchy state machine:
    ACTIVE  →  acknowledge()  →  ACKNOWLEDGED  →  resolve()        →  RESOLVED
                                                                    →  auto_resolve()   →  AUTO_RESOLVED

Features:
    - Thread-safe singleton with RLock
    - Duplicate suppression (same type + sensor within 10 min)
    - Active alarm sorting (level desc, timestamp desc)
    - Auto-resolve when conditions clear
    - Notification dispatch via registered handlers
    - Full audit logging and persistence
"""

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .alarm_definitions import get_alarm_level, format_alarm_message
from .data_models import (
    AlarmLevel,
    AlarmRecord,
    AlarmStatus,
    AlarmType,
    AuditLogEntry,
    OperationType,
)
from .logger import CorrosionLogger

_logger = CorrosionLogger().get_logger("AlarmManager")

_NOTIFICATION_LEVEL_THRESHOLD = 2
_DUPLICATE_SUPPRESS_WINDOW_SECONDS = 600
_RECENT_RESOLVED_DEFAULT_COUNT = 20


class AlarmManager:
    """
    Manages the complete alarm lifecycle: trigger → record → notify → confirm → resolve.

    Thread-safe singleton that coordinates between alarm detection logic,
    persistence layer (StorageManager), and notification channels.

    State machine transitions:
        ACTIVE ──acknowledge()──▶ ACKNOWLEDGED ──resolve()────────▶ RESOLVED
                                                   ──auto_resolve()──▶ AUTO_RESOLVED
    """

    _instance: Optional["AlarmManager"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "AlarmManager":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, storage_manager: Any = None) -> None:
        if hasattr(self, "_initialized") and self._initialized:
            if storage_manager is not None:
                self._storage = storage_manager
            return

        self._initialized = True
        self._active_alarms: Dict[str, AlarmRecord] = {}
        self._alarm_history: List[AlarmRecord] = []
        self._lock = threading.RLock()
        self._notification_handlers: List[Callable[[AlarmRecord], None]] = []
        self._storage = storage_manager
        _logger.info("AlarmManager initialised")

    @classmethod
    def reset_instance(cls) -> None:
        with cls._class_lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Alarm Lifecycle
    # ------------------------------------------------------------------

    def raise_alarm(
        self,
        level: int,
        alarm_type: str,
        details: dict,
        sensor_id: Optional[str] = None,
    ) -> Optional[AlarmRecord]:
        """
        Create and activate a new alarm.

        Args:
            level: Alarm severity level (1-4).
            alarm_type: Alarm type key matching ALARM_DEFINITIONS.
            details: Contextual data for message formatting.
            sensor_id: Optional sensor identifier.

        Returns:
            Created AlarmRecord, or None if duplicate was suppressed.
        """
        if self._is_duplicate(level, alarm_type, sensor_id or ""):
            _logger.debug(
                "Duplicate alarm suppressed: type=%s, sensor=%s",
                alarm_type, sensor_id,
            )
            return None

        alarm_level = get_alarm_level(alarm_type)
        alarm_type_enum = self._resolve_alarm_type_enum(alarm_type)
        message = format_alarm_message(alarm_type, details)

        alarm = AlarmRecord(
            level=alarm_level,
            alarm_type=alarm_type_enum,
            details={"type_key": alarm_type, "message": message, **details},
            sensor_id=sensor_id or "",
            status=AlarmStatus.ACTIVE,
        )

        with self._lock:
            self._active_alarms[str(alarm.alarm_id)] = alarm
            self._alarm_history.append(alarm)

        if self._storage is not None:
            self._storage.save_alarm_record(alarm)
            self._log_audit(alarm, OperationType.CREATE, "system")

        _logger.warning(
            "[LEVEL %d] %s | sensor=%s | %s",
            level, alarm_type, sensor_id, message,
        )

        if level >= _NOTIFICATION_LEVEL_THRESHOLD:
            self._notify_handlers(alarm)

        return alarm

    def acknowledge_alarm(self, alarm_id: str, operator: str) -> bool:
        """
        Acknowledge an active alarm (ACTIVE → ACKNOWLEDGED).

        Args:
            alarm_id: UUID string of the alarm.
            operator: Name of the operator acknowledging.

        Returns:
            True if the transition succeeded, False otherwise.
        """
        with self._lock:
            alarm = self._active_alarms.get(alarm_id)
            if alarm is None:
                _logger.warning("Acknowledge failed: alarm %s not found", alarm_id)
                return False

            if alarm.status != AlarmStatus.ACTIVE:
                _logger.warning(
                    "Acknowledge failed: alarm %s is %s (not ACTIVE)",
                    alarm_id, alarm.status.value,
                )
                return False

            alarm.status = AlarmStatus.ACKNOWLEDGED
            alarm.operator = operator
            _logger.info("Alarm %s acknowledged by %s", alarm_id, operator)

        self._persist_alarm(alarm)
        self._log_audit(alarm, OperationType.ACKNOWLEDGE, operator)
        return True

    def resolve_alarm(
        self,
        alarm_id: str,
        operator: Optional[str] = None,
        auto: bool = False,
    ) -> bool:
        """
        Resolve an acknowledged alarm (ACKNOWLEDGED → RESOLVED or AUTO_RESOLVED).

        Args:
            alarm_id: UUID string of the alarm.
            operator: Operator name (for manual resolve).
            auto: If True, transitions to AUTO_RESOLVED instead of RESOLVED.

        Returns:
            True if the transition succeeded, False otherwise.
        """
        with self._lock:
            alarm = self._active_alarms.get(alarm_id)
            if alarm is None:
                _logger.warning("Resolve failed: alarm %s not found", alarm_id)
                return False

            if alarm.status == AlarmStatus.RESOLVED or alarm.status == AlarmStatus.AUTO_RESOLVED:
                _logger.debug("Alarm %s already resolved", alarm_id)
                return False

            if alarm.status == AlarmStatus.ACTIVE:
                _logger.debug(
                    "Alarm %s is ACTIVE, implicitly acknowledging before resolve", alarm_id
                )

            new_status = AlarmStatus.AUTO_RESOLVED if auto else AlarmStatus.RESOLVED
            alarm.status = new_status
            alarm.resolved_time = datetime.now(timezone.utc)
            if operator:
                alarm.operator = operator

            _logger.info(
                "Alarm %s %s by %s",
                alarm_id,
                "auto-resolved" if auto else "resolved",
                operator or "auto",
            )

        self._persist_alarm(alarm)
        self._log_audit(alarm, OperationType.RESOLVE, operator or "auto")
        return True

    def check_auto_resolve(self, alarm_id: str) -> bool:
        """
        Check if alarm conditions have cleared and auto-resolve if so.

        An alarm can be auto-resolved if:
            - It is in ACTIVE or ACKNOWLEDGED state.
            - Its alarm type definition has an auto_resolve_condition
              other than 'manual_only'.

        Args:
            alarm_id: UUID string of the alarm.

        Returns:
            True if alarm was auto-resolved, False otherwise.
        """
        from .alarm_definitions import get_alarm_definition

        with self._lock:
            alarm = self._active_alarms.get(alarm_id)
            if alarm is None:
                return False

            if alarm.status not in (AlarmStatus.ACTIVE, AlarmStatus.ACKNOWLEDGED):
                return False

            type_key = alarm.details.get("type_key", "")
            definition = get_alarm_definition(type_key)
            auto_condition = definition.get("auto_resolve_condition", "manual_only")

        if auto_condition == "manual_only":
            _logger.debug(
                "Alarm %s (type=%s) requires manual resolution", alarm_id, type_key
            )
            return False

        return self.resolve_alarm(alarm_id, auto=True)

    # ------------------------------------------------------------------
    # Query Methods
    # ------------------------------------------------------------------

    def get_active_alarms(self, min_level: int = 1) -> List[AlarmRecord]:
        """
        Get all active alarms, sorted by level (highest first) then timestamp (newest first).

        Args:
            min_level: Minimum alarm level to include (inclusive).

        Returns:
            Sorted list of active AlarmRecord objects.
        """
        with self._lock:
            active = [
                a for a in self._active_alarms.values()
                if a.status in (AlarmStatus.ACTIVE, AlarmStatus.ACKNOWLEDGED)
                and a.level.value >= min_level
            ]
        active.sort(key=lambda a: (-a.level.value, -a.timestamp.timestamp()))
        return active

    def get_alarm_by_id(self, alarm_id: str) -> Optional[AlarmRecord]:
        """Get an alarm by its UUID string."""
        with self._lock:
            return self._active_alarms.get(alarm_id)

    def get_recent_resolved(self, count: int = _RECENT_RESOLVED_DEFAULT_COUNT) -> List[AlarmRecord]:
        """
        Get recently resolved alarms from history.

        Args:
            count: Maximum number of records to return.

        Returns:
            List of resolved AlarmRecord objects, newest first.
        """
        with self._lock:
            resolved = [
                a for a in self._alarm_history
                if a.status in (AlarmStatus.RESOLVED, AlarmStatus.AUTO_RESOLVED)
            ]
        resolved.sort(key=lambda a: (
            a.resolved_time.timestamp() if a.resolved_time else 0
        ), reverse=True)
        return resolved[:count]

    def get_alarm_statistics(self) -> dict:
        """
        Get alarm statistics: counts by level, type, and status.

        Returns:
            Dictionary with keys 'by_level', 'by_type', 'by_status',
            'total_active', 'total_resolved'.
        """
        with self._lock:
            all_alarms = list(self._alarm_history)
            active = list(self._active_alarms.values())

        by_level: Dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
        by_type: Dict[str, int] = {}
        by_status: Dict[str, int] = {
            "ACTIVE": 0,
            "ACKNOWLEDGED": 0,
            "RESOLVED": 0,
            "AUTO_RESOLVED": 0,
        }

        for alarm in all_alarms:
            lv = alarm.level.value
            by_level[lv] = by_level.get(lv, 0) + 1
            at = alarm.alarm_type.value
            by_type[at] = by_type.get(at, 0) + 1
            st = alarm.status.value
            by_status[st] = by_status.get(st, 0) + 1

        total_active = sum(
            1 for a in active
            if a.status in (AlarmStatus.ACTIVE, AlarmStatus.ACKNOWLEDGED)
        )
        total_resolved = sum(
            1 for a in self._alarm_history
            if a.status in (AlarmStatus.RESOLVED, AlarmStatus.AUTO_RESOLVED)
        )

        return {
            "by_level": by_level,
            "by_type": by_type,
            "by_status": by_status,
            "total_active": total_active,
            "total_resolved": total_resolved,
        }

    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------

    def register_notification_handler(self, handler: Callable[[AlarmRecord], None]) -> None:
        """Register a callback for alarm notification (e.g., LoRa, MQTT push)."""
        with self._lock:
            if handler not in self._notification_handlers:
                self._notification_handlers.append(handler)
                _logger.debug("Notification handler registered: %s", handler)

    def unregister_notification_handler(self, handler: Callable[[AlarmRecord], None]) -> None:
        """Unregister a previously registered notification handler."""
        with self._lock:
            if handler in self._notification_handlers:
                self._notification_handlers.remove(handler)
                _logger.debug("Notification handler unregistered: %s", handler)

    def _notify_handlers(self, alarm: AlarmRecord) -> None:
        """
        Call all registered notification handlers for an alarm.

        Each handler runs in its own thread to prevent blocking the caller.
        Handler exceptions are logged but do not stop other handlers.
        """
        with self._lock:
            handlers = list(self._notification_handlers)

        if not handlers:
            _logger.debug("No notification handlers registered, alarm %s not pushed", alarm.alarm_id)
            return

        for handler in handlers:
            t = threading.Thread(
                target=self._safe_notify,
                args=(handler, alarm),
                daemon=True,
            )
            t.start()

    @staticmethod
    def _safe_notify(handler: Callable[[AlarmRecord], None], alarm: AlarmRecord) -> None:
        try:
            handler(alarm)
        except Exception:
            _logger.exception(
                "Notification handler %s failed for alarm %s", handler, alarm.alarm_id
            )

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _is_duplicate(
        self,
        level: int,
        alarm_type: str,
        sensor_id: str,
        time_window_seconds: int = _DUPLICATE_SUPPRESS_WINDOW_SECONDS,
    ) -> bool:
        """
        Suppress duplicate alarms of the same type+sensor within the time window.

        Args:
            level: Alarm level being checked.
            alarm_type: Alarm type key string.
            sensor_id: Sensor identifier.
            time_window_seconds: Suppression window in seconds.

        Returns:
            True if a recent duplicate was found and should be suppressed.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=time_window_seconds)

        with self._lock:
            for alarm in self._active_alarms.values():
                if alarm.status in (AlarmStatus.RESOLVED, AlarmStatus.AUTO_RESOLVED):
                    continue
                if alarm.timestamp < cutoff:
                    continue
                existing_type = alarm.details.get("type_key", "")
                existing_sensor = alarm.sensor_id
                if existing_type == alarm_type and existing_sensor == sensor_id:
                    return True

            for alarm in self._alarm_history:
                if alarm.status not in (AlarmStatus.ACTIVE, AlarmStatus.ACKNOWLEDGED):
                    continue
                if alarm.timestamp < cutoff:
                    continue
                existing_type = alarm.details.get("type_key", "")
                existing_sensor = alarm.sensor_id
                if existing_type == alarm_type and existing_sensor == sensor_id:
                    return True

        return False

    @staticmethod
    def _resolve_alarm_type_enum(alarm_type: str) -> AlarmType:
        try:
            return AlarmType(alarm_type)
        except ValueError:
            _logger.warning("Unknown alarm type '%s', falling back to SYSTEM_ERROR", alarm_type)
            return AlarmType.SYSTEM_ERROR

    def _persist_alarm(self, alarm: AlarmRecord) -> None:
        if self._storage is not None:
            try:
                self._storage.save_alarm_record(alarm)
            except Exception:
                _logger.exception("Failed to persist alarm %s", alarm.alarm_id)

    def _log_audit(self, alarm: AlarmRecord, operation: OperationType, operator: str) -> None:
        if self._storage is None:
            return
        try:
            entry = AuditLogEntry(
                operator=operator,
                operation_type=operation,
                details={
                    "alarm_id": str(alarm.alarm_id),
                    "alarm_type": alarm.alarm_type.value,
                    "level": alarm.level.value,
                    "status": alarm.status.value,
                },
                result="success",
            )
            self._storage.save_audit_log(entry)
        except Exception:
            _logger.exception("Failed to log audit for alarm %s", alarm.alarm_id)
