"""
Centralized audit logging for the Wind Turbine Internal Corrosion Detection System.

Records all security-relevant operations with timestamp, operator identity,
operation type, details, and result. Audit logs are append-only – no delete
capability is exposed through the API.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from .data_models import AuditLogEntry, OperationType
from .logger import CorrosionLogger

_logger = CorrosionLogger().get_logger("Audit")


class AuditLogger:
    """Centralized audit logging for all security-relevant operations.

    Auto-captures the current user from AuthManager when available.
    All log entries are append-only; deletions are not permitted.
    """

    _SUPPORTED_OPERATIONS = {
        "LOGIN", "LOGOUT", "LOGIN_FAILED",
        "CONFIG_CHANGE", "DATA_EXPORT", "USER_CREATE",
        "USER_DELETE", "PASSWORD_CHANGE",
        "ALARM_ACKNOWLEDGE", "ALARM_RESOLVE",
        "FIRMWARE_UPGRADE", "CALIBRATION_IMPORT",
        "SYSTEM_START", "SYSTEM_STOP", "SYSTEM_RESTART",
        "DATA_QUERY", "TOKEN_GENERATE",
    }

    def __init__(self, storage_manager, auth_manager=None) -> None:
        self._storage = storage_manager
        self._auth = auth_manager

    def _get_operator(self) -> str:
        if self._auth is not None:
            user = self._auth.get_current_user()
            if user:
                return user
        return "system"

    def _write_entry(self, operation: str, details: str, result: str) -> bool:
        entry = AuditLogEntry(
            timestamp=datetime.now(timezone.utc),
            operator=self._get_operator(),
            operation_type=OperationType.CREATE,
            details={"operation": operation, "detail": str(details)},
            result=result,
        )

        stored = self._storage.save_audit_log(entry) if self._storage else False
        if stored:
            _logger.debug("Audit: [%s] %s | %s | %s",
                          result, self._get_operator(), operation, details)
        else:
            _logger.warning("Failed to persist audit entry: %s", operation)
        return stored

    # ------------------------------------------------------------------
    # General log
    # ------------------------------------------------------------------

    def log(self, operation_type: str, details: str, result: str = "SUCCESS") -> None:
        """Log an audit entry with operation type, details, and result.

        Auto-captures current user from AuthManager.
        """
        self._write_entry(operation_type, str(details), result)

    # ------------------------------------------------------------------
    # Specific operation loggers
    # ------------------------------------------------------------------

    def log_config_change(self, config_key: str, old_value: Any, new_value: Any) -> None:
        self._write_entry(
            "CONFIG_CHANGE",
            f"Key='{config_key}', Old='{old_value}', New='{new_value}'",
            "SUCCESS",
        )

    def log_login(self, username: str, success: bool) -> None:
        self._write_entry(
            "LOGIN" if success else "LOGIN_FAILED",
            f"User='{username}'",
            "SUCCESS" if success else "FAILED",
        )

    def log_logout(self, username: str) -> None:
        self._write_entry("LOGOUT", f"User='{username}'", "SUCCESS")

    def log_data_export(self, data_type: str, time_range: str) -> None:
        self._write_entry(
            "DATA_EXPORT",
            f"Type='{data_type}', Range='{time_range}'",
            "SUCCESS",
        )

    def log_alarm_action(self, alarm_id: str, action: str) -> None:
        operation = "ALARM_ACKNOWLEDGE" if action.lower() == "acknowledge" else "ALARM_RESOLVE"
        self._write_entry(operation, f"AlarmID='{alarm_id}'", "SUCCESS")

    def log_firmware_upgrade(self, version_from: str, version_to: str) -> None:
        self._write_entry(
            "FIRMWARE_UPGRADE",
            f"From='{version_from}', To='{version_to}'",
            "SUCCESS",
        )

    def log_calibration_import(self, curve_version: str) -> None:
        self._write_entry(
            "CALIBRATION_IMPORT",
            f"CurveVersion='{curve_version}'",
            "SUCCESS",
        )

    def log_user_create(self, username: str, role: str) -> None:
        self._write_entry(
            "USER_CREATE",
            f"User='{username}', Role='{role}'",
            "SUCCESS",
        )

    def log_password_change(self, username: str) -> None:
        self._write_entry(
            "PASSWORD_CHANGE",
            f"User='{username}'",
            "SUCCESS",
        )

    def log_system_event(self, event_type: str) -> None:
        self._write_entry(event_type, "", "SUCCESS")

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_logs(self, start_time: Optional[datetime] = None,
                 end_time: Optional[datetime] = None,
                 operation_type: Optional[str] = None,
                 page: int = 1, page_size: int = 100) -> dict:
        """Query audit logs with optional filters.

        Returns paginated results in the same format as StorageManager queries.
        """
        if self._storage is None:
            return {
                "data": [], "total_count": 0,
                "page": page, "page_size": page_size,
                "has_next": False, "has_prev": False,
            }
        return self._storage.query_audit_log(
            start=start_time,
            end=end_time,
            operation_type=operation_type,
            page=page,
        )
