"""
Core framework module for the Wind Turbine Internal Corrosion Detection System.

Provides the application lifecycle, configuration management, logging,
data model definitions, authentication/authorization, audit logging,
cryptographic utilities, data integrity verification, alarm management,
notification services, diagnostics, and health management.
"""

from .alarm_definitions import ALARM_DEFINITIONS, format_alarm_message, get_alarm_definition, get_alarm_level
from .alarm_manager import AlarmManager
from .app import App, AppState, Signal
from .audit_logger import AuditLogger
from .auth_manager import AuthManager, Permission, PermissionError as AuthPermError, ROLE_PERMISSIONS
from .config_manager import ConfigManager
from .crypto_utils import CryptoUtils
from .data_integrity import DataIntegrityGuard
from .data_models import (
    AlarmLevel,
    AlarmRecord,
    AlarmStatus,
    AlarmType,
    AuditLogEntry,
    ConfigData,
    CorrosionRecord,
    CrossValidationResult,
    DualModeResult,
    DualModeStatus,
    OperationType,
    SensorData,
)
from .diagnostics import (
    DiagnosticsManager,
    POSTResult,
    SystemHealth,
)
from .health_monitor import HealthMonitor
from .logger import CorrosionLogger
from .notification_service import NotificationService
from .watchdog import WatchdogTimer

__all__ = [
    "App",
    "AppState",
    "Signal",
    "AuditLogger",
    "AuthManager",
    "ConfigManager",
    "CorrosionLogger",
    "CryptoUtils",
    "DataIntegrityGuard",
    "Permission",
    "ROLE_PERMISSIONS",
    "SensorData",
    "CorrosionRecord",
    "CrossValidationResult",
    "DualModeResult",
    "DualModeStatus",
    "AlarmRecord",
    "ConfigData",
    "AuditLogEntry",
    "AlarmLevel",
    "AlarmStatus",
    "AlarmType",
    "OperationType",
    "AlarmManager",
    "NotificationService",
    "ALARM_DEFINITIONS",
    "get_alarm_definition",
    "get_alarm_level",
    "format_alarm_message",
    "DiagnosticsManager",
    "POSTResult",
    "SystemHealth",
    "HealthMonitor",
    "WatchdogTimer",
]
