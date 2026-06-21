"""
Continuous system health monitoring for the corrosion detection system.

Provides comprehensive health reports, critical systems checks, uptime
tracking, and resource usage statistics. Works as a companion to the
DiagnosticsManager, providing a higher-level health assessment interface.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

from .logger import CorrosionLogger

if TYPE_CHECKING:
    from .diagnostics import DiagnosticsManager

_logger = CorrosionLogger().get_logger("HealthMonitor")

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False
    _logger.warning("psutil not installed; resource usage stats will be limited")


class HealthMonitor:
    """Continuous system health monitoring.

    Provides a high-level interface for generating health reports,
    checking critical systems, and tracking system resource usage.

    Attributes:
        _diag: Reference to the DiagnosticsManager instance.
        _start_time: Timestamp when this monitor was created (system start).
    """

    def __init__(self, diagnostics_manager: "DiagnosticsManager") -> None:
        self._diag = diagnostics_manager
        self._start_time = time.time()

    def get_health_report(self) -> dict:
        """Generate a comprehensive health report as a JSON-serializable dict.

        Returns:
            Dictionary with health status, POST results, sensor status,
            resource usage, uptime, and critical system status.
        """
        health = self._diag.get_health_status()
        critical_issues = self.check_critical_systems()

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system_health": health.get("health", "unknown"),
            "post_results": health.get("post_results", {}),
            "critical_issues": critical_issues,
            "critical_issues_count": len(critical_issues),
            "sensor_status": health.get("sensor_status", {}),
            "resource_usage": self.get_resource_usage(),
            "uptime_seconds": self.get_uptime().total_seconds(),
            "uptime_formatted": str(self.get_uptime()),
            "memory_usage_mb": health.get("memory_usage", 0),
            "disk_usage_percent": health.get("disk_usage", 0),
        }

        return report

    def check_critical_systems(self) -> List[str]:
        """Check all critical systems and return a list of issue descriptions.

        Verifies:
            - Database/storage accessibility
            - Sensor subsystem status
            - Configuration integrity
            - Logging subsystem status
            - Watchdog health

        Returns:
            List of human-readable issue strings. Empty list if all clear.
        """
        issues: List[str] = []

        diag_health = self._diag.get_health_status()
        if diag_health.get("health") == "faulty":
            issues.append("System health status is FAULTY")

        sensor_status = diag_health.get("sensor_status", {})
        if sensor_status:
            offline_sensors = [
                name for name, info in sensor_status.items()
                if info.get("online") is False
            ]
            if offline_sensors:
                issues.append(f"Sensors offline: {', '.join(offline_sensors)}")

        try:
            app = self._diag._app
            if app is not None:
                storage = getattr(app, '_modules', {}).get('storage')
                if storage is not None and hasattr(storage, '_initialized'):
                    if not storage._initialized:
                        issues.append("Storage subsystem is not initialized")
                if app._state is not None and app._state.name == "ERROR":
                    issues.append(f"Application is in ERROR state")
        except Exception:
            pass

        if not self._diag._watchdog_timer.is_alive():
            issues.append("Watchdog timer has not been fed within timeout")

        return issues

    def get_uptime(self) -> timedelta:
        """Get the current system uptime.

        Returns:
            timedelta representing elapsed time since system start.
        """
        elapsed = time.time() - self._start_time
        return timedelta(seconds=elapsed)

    def get_resource_usage(self) -> dict:
        """Get CPU, memory, and disk usage statistics.

        Returns:
            Dictionary with cpu_percent, memory_mb, memory_percent,
            disk_total_gb, disk_used_gb, disk_free_gb, disk_percent.
        """
        stats: dict = {
            "cpu_percent": None,
            "memory_mb": None,
            "memory_percent": None,
            "disk_total_gb": None,
            "disk_used_gb": None,
            "disk_free_gb": None,
            "disk_percent": None,
        }

        if not _PSUTIL_AVAILABLE:
            return stats

        try:
            stats["cpu_percent"] = psutil.cpu_percent(interval=0.1)

            mem = psutil.virtual_memory()
            stats["memory_mb"] = round(mem.used / (1024 * 1024), 1)
            stats["memory_percent"] = mem.percent

            disk = psutil.disk_usage(os.getcwd())
            stats["disk_total_gb"] = round(disk.total / (1024 ** 3), 2)
            stats["disk_used_gb"] = round(disk.used / (1024 ** 3), 2)
            stats["disk_free_gb"] = round(disk.free / (1024 ** 3), 2)
            stats["disk_percent"] = disk.percent
        except Exception:
            _logger.warning("Failed to collect resource usage statistics")

        return stats
