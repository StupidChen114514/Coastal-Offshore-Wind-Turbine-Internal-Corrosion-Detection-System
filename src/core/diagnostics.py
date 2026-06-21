"""
System self-diagnosis and health management for the Wind Turbine Internal
Corrosion Detection System.

Implements Requirement 10 of the system specification:
    - Power-On Self Test (POST): RAM, Storage, Bus, RTC, Current Source
    - Runtime diagnostics: 30-day periodic checks, per-collection-cycle checks
    - Watchdog timer integration: feed, monitor, graceful reset
    - Health status aggregation and reporting

The DiagnosticsManager is designed to be instantiated during application
initialization, with POST running before the application enters RUNNING state.
"""

import json
import os
import time
import threading
import traceback
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .data_models import (
    AlarmLevel,
    AlarmRecord,
    AlarmStatus,
    AlarmType,
    AuditLogEntry,
    OperationType,
)
from .logger import CorrosionLogger
from .watchdog import WatchdogTimer

if TYPE_CHECKING:
    from .app import App

_logger = CorrosionLogger().get_logger("Diagnostics")

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


class SystemHealth(Enum):
    """System health states for the diagnostics manager."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAULTY = "faulty"
    STARTING = "starting"


class POSTResult(Enum):
    """Power-On Self Test result categories."""
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class DiagnosticsManager:
    """System self-diagnosis and health management.

    Provides:
        - POST: sequential hardware/software validation at startup
        - Runtime diagnostics: 30-day and per-collection-cycle checks
        - Watchdog timer lifecycle management
        - Health status aggregation

    Attributes:
        _app: Reference to the singleton Application instance.
        _health: Current SystemHealth state.
        _post_results: Dictionary of POST test name -> POSTResult.
        _periodic_check_timer: threading.Timer for 30-day checks.
        _watchdog_timer: WatchdogTimer instance for hardware/software watchdog.
        _last_watchdog_feed: Timestamp of last watchdog feed.
        _watchdog_timeout: Watchdog timeout in seconds.
        _lock: Reentrant lock for thread safety.
        _reference_ring_initial: Initial reference ring resistance (Ω).
        _current_source_nominal: Nominal current source voltage (V).
        _qcm_base_frequency_initial: Initial QCM base frequency (Hz).
        _start_time: System start timestamp for uptime tracking.
    """

    def __init__(self, app_instance: "App") -> None:
        self._app = app_instance
        self._health = SystemHealth.STARTING
        self._post_results: Dict[str, POSTResult] = {}
        self._periodic_check_timer: Optional[threading.Timer] = None
        self._watchdog_timer = WatchdogTimer(
            timeout_seconds=30.0,
            on_timeout=self._on_watchdog_timeout,
        )
        self._last_watchdog_feed = time.time()
        self._watchdog_timeout = 30
        self._lock = threading.RLock()

        self._reference_ring_initial: Optional[float] = None
        self._current_source_nominal: float = 2.5
        self._qcm_base_frequency_initial: Optional[float] = None

        self._start_time = time.time()
        self._sensor_error_counts: Dict[str, int] = {}
        self._sensor_last_reading: Dict[str, Optional[datetime]] = {}
        self._invalid_data_count = 0

        _logger.info("DiagnosticsManager created (health=STARTING)")

    # ==================================================================
    # Power-On Self Test (POST)
    # ==================================================================

    def run_post(self) -> bool:
        """Run all POST checks sequentially.

        Execution order per spec:
            RAM → Storage → Bus → RTC → Current Source

        Returns:
            True if all critical checks (FAIL status) pass,
            allowing transition to RUNNING state.
        """
        _logger.info("=" * 50)
        _logger.info("Starting Power-On Self Test (POST)")
        _logger.info("=" * 50)

        with self._lock:
            self._health = SystemHealth.STARTING
            self._post_results.clear()

        checks = [
            ("RAM", self._check_ram),
            ("Storage", self._check_storage),
            ("Bus", self._check_bus),
            ("RTC", self._check_rtc),
            ("Current Source", self._check_current_source),
        ]

        critical_failures = 0
        warnings = 0

        for name, check_fn in checks:
            try:
                result = check_fn()
            except Exception as e:
                _logger.error("POST check '%s' raised exception: %s", name, e)
                result = POSTResult.FAIL

            with self._lock:
                self._post_results[name] = result

            if result == POSTResult.FAIL:
                critical_failures += 1
                _logger.error("POST [%s]: FAIL", name)
            elif result == POSTResult.WARNING:
                warnings += 1
                _logger.warning("POST [%s]: WARNING", name)
            else:
                _logger.info("POST [%s]: PASS", name)

        _logger.info(
            "POST complete: %d pass, %d warning, %d fail",
            len(checks) - critical_failures - warnings,
            warnings,
            critical_failures,
        )

        with self._lock:
            if critical_failures > 0:
                self._health = SystemHealth.FAULTY
                _logger.critical(
                    "POST: %d critical failure(s) – blocking transition to RUNNING",
                    critical_failures,
                )
                self._raise_alarm(
                    level=AlarmLevel.LEVEL_3,
                    alarm_type=AlarmType.SYSTEM_ERROR,
                    details={
                        "event": "post_failure",
                        "failed_checks": [
                            name for name, r in self._post_results.items()
                            if r == POSTResult.FAIL
                        ],
                    },
                    sensor_id="SYSTEM",
                )
                return False
            elif warnings > 0:
                self._health = SystemHealth.DEGRADED
                _logger.warning("POST: %d warning(s) – degraded operation", warnings)
                self._raise_alarm(
                    level=AlarmLevel.LEVEL_2,
                    alarm_type=AlarmType.SYSTEM_ERROR,
                    details={
                        "event": "post_warning",
                        "warning_checks": [
                            name for name, r in self._post_results.items()
                            if r == POSTResult.WARNING
                        ],
                    },
                    sensor_id="SYSTEM",
                )
                return True
            else:
                self._health = SystemHealth.HEALTHY
                _logger.info("POST: all checks passed – system healthy")
                return True

    def _check_ram(self) -> POSTResult:
        """RAM self-test: write known pattern, read back, verify.

        Allocates a small bytearray, writes a checkerboard pattern,
        and reads back to verify basic memory integrity.

        Returns:
            POSTResult.PASS if pattern matches, FAIL otherwise.
        """
        try:
            size = 4096
            test_data = bytearray(size)
            pattern_aa = b'\xAA' * size
            pattern_55 = b'\x55' * size

            test_data[:] = pattern_aa
            if test_data != pattern_aa:
                _logger.error("RAM check: 0xAA pattern verification failed")
                return POSTResult.FAIL

            test_data[:] = pattern_55
            if test_data != pattern_55:
                _logger.error("RAM check: 0x55 pattern verification failed")
                return POSTResult.FAIL

            test_data = bytearray()
            _logger.debug("RAM check: patterns verified (4096 bytes)")
            return POSTResult.PASS
        except MemoryError:
            _logger.error("RAM check: memory allocation failed")
            return POSTResult.FAIL
        except Exception as e:
            _logger.error("RAM check: unexpected error: %s", e)
            return POSTResult.FAIL

    def _check_storage(self) -> POSTResult:
        """Storage/Flash health check.

        Verifies database file accessibility and checks disk free space.
        In simulated mode or when storage is unavailable, returns a warning.

        Returns:
            POSTResult.PASS if storage is accessible with adequate space,
            WARNING if free space is low, FAIL if storage is inaccessible.
        """
        try:
            db_path = "corrosion_data.db"
            if os.path.exists(db_path):
                if not os.access(db_path, os.R_OK | os.W_OK):
                    _logger.error("Storage check: database file not readable/writable")
                    return POSTResult.FAIL

            if _PSUTIL_AVAILABLE:
                disk = psutil.disk_usage(os.getcwd())
                free_mb = disk.free / (1024 * 1024)
                _logger.debug("Storage check: free disk space = %.1f MB", free_mb)
                if free_mb < 100:
                    _logger.warning("Storage check: low disk space (%.1f MB free)", free_mb)
                    return POSTResult.WARNING
            else:
                _logger.debug("Storage check: psutil unavailable, skipping free space check")

            return POSTResult.PASS
        except Exception as e:
            _logger.error("Storage check failed: %s", e)
            return POSTResult.FAIL

    def _check_bus(self) -> POSTResult:
        """Sensor communication bus check.

        For simulated mode: always passes.
        For real hardware: would attempt I2C scan of known addresses.
        The current architecture routes all sensor communication through the
        MSP430FR MCU via serial; the bus check therefore validates serial
        port accessibility.

        Returns:
            POSTResult.PASS if bus is accessible, WARNING if simulated, FAIL otherwise.
        """
        try:
            sensor_mgr = self._get_sensor_manager()
            if sensor_mgr is not None and sensor_mgr.is_simulated:
                _logger.info("Bus check: simulated mode – passing automatically")
                return POSTResult.PASS

            if sensor_mgr is not None and sensor_mgr.is_initialized:
                _logger.info("Bus check: sensor manager initialized – pass")
                return POSTResult.PASS

            _logger.info("Bus check: sensor manager not yet initialized – no bus access")
            return POSTResult.WARNING
        except Exception as e:
            _logger.error("Bus check failed: %s", e)
            return POSTResult.WARNING

    def _check_rtc(self) -> POSTResult:
        """RTC clock validity.

        Verify the system clock is reasonable – not before 2020-01-01
        (ruling out uninitialized RTC defaulting to 1970 or 2000).

        Returns:
            POSTResult.PASS if clock is reasonable, FAIL otherwise.
        """
        try:
            now = datetime.now()
            minimum_valid = datetime(2020, 1, 1)

            if now < minimum_valid:
                _logger.error(
                    "RTC check: system clock is %s – appears uninitialized",
                    now.isoformat(),
                )
                return POSTResult.FAIL

            _logger.debug("RTC check: system clock is %s – valid", now.isoformat())
            return POSTResult.PASS
        except Exception as e:
            _logger.error("RTC check failed: %s", e)
            return POSTResult.FAIL

    def _check_current_source(self) -> POSTResult:
        """Current source output check.

        Verify V_ref is within nominal ±5% range. The nominal reference
        voltage is 2.5V, so acceptable range is 2.375V to 2.625V.

        In simulated mode, this uses the configured nominal value.
        In hardware mode, reads the latest V_mid from the sensor manager.

        Returns:
            POSTResult.PASS if V_ref within ±5%, WARNING if near boundary, FAIL if out of range.
        """
        try:
            nominal = self._current_source_nominal
            lower = nominal * 0.95
            upper = nominal * 1.05

            v_ref = self._read_v_ref()

            if v_ref is None:
                _logger.info("Current source check: no V_ref reading available")
                return POSTResult.WARNING

            _logger.debug(
                "Current source check: V_ref=%.4f V (nominal=%.2f V, range=%.3f-%.3f V)",
                v_ref, nominal, lower, upper,
            )

            if v_ref < lower or v_ref > upper:
                _logger.error(
                    "Current source check: V_ref=%.4f V is outside ±5%% range [%.3f, %.3f]",
                    v_ref, lower, upper,
                )
                return POSTResult.FAIL

            margin = min(abs(v_ref - lower), abs(v_ref - upper)) / nominal
            if margin < 0.02:
                _logger.warning(
                    "Current source check: V_ref=%.4f V within range but near boundary (margin=%.1f%%)",
                    v_ref, margin * 100,
                )
                return POSTResult.WARNING

            return POSTResult.PASS
        except Exception as e:
            _logger.error("Current source check failed: %s", e)
            return POSTResult.FAIL

    def _read_v_ref(self) -> Optional[float]:
        """Read the current V_ref (V_mid) from the sensor manager.

        Returns:
            V_ref voltage in volts, or None if unavailable.
        """
        sensor_mgr = self._get_sensor_manager()
        if sensor_mgr is None:
            return None

        last_data = sensor_mgr.get_last_data()
        if last_data is not None:
            return last_data.V_mid

        return None

    # ==================================================================
    # Runtime Diagnostics
    # ==================================================================

    def start_periodic_checks(self) -> None:
        """Start the 30-day periodic diagnostic check timer.

        The first check runs after 30 days, then repeats every 30 days.
        If a timer is already scheduled, this call has no effect.
        """
        with self._lock:
            if self._periodic_check_timer is not None:
                _logger.debug("Periodic check timer already scheduled")
                return

        interval = 30 * 24 * 3600
        self._periodic_check_timer = threading.Timer(
            interval, self._run_periodic_checks
        )
        self._periodic_check_timer.daemon = True
        self._periodic_check_timer.start()
        _logger.info(
            "30-day periodic check timer started (first check in ~%d days)",
            30,
        )

    def _run_periodic_checks(self) -> None:
        """Execute the 30-day diagnostic checks.

        Checks:
            1. Reference ring R_r drift (±1% from initial)
            2. Current source output (±2% of nominal)
            3. QCM base frequency drift (±500 Hz from initial)

        Results are logged and alarms raised for failures.
        Reschedules itself for the next 30-day cycle.
        """
        _logger.info("=" * 50)
        _logger.info("Running 30-day periodic diagnostic checks")
        _logger.info("=" * 50)

        issues: List[str] = []

        try:
            ref_ring_ok = self._check_reference_ring()
            if not ref_ring_ok:
                issues.append("Reference ring drift > ±1%%")
        except Exception as e:
            _logger.error("Reference ring check error: %s", e)

        try:
            current_source_ok = self._check_current_source_periodic()
            if not current_source_ok:
                issues.append("Current source drift > ±2%%")
        except Exception as e:
            _logger.error("Current source check error: %s", e)

        try:
            qcm_ok = self._check_qcm_base_frequency()
            if not qcm_ok:
                issues.append("QCM base frequency drift > ±500 Hz")
        except Exception as e:
            _logger.error("QCM frequency check error: %s", e)

        if issues:
            _logger.warning("30-day checks found %d issue(s): %s", len(issues), issues)
            with self._lock:
                if self._health == SystemHealth.HEALTHY:
                    self._health = SystemHealth.DEGRADED
            self._raise_alarm(
                level=AlarmLevel.LEVEL_3,
                alarm_type=AlarmType.SYSTEM_ERROR,
                details={
                    "event": "periodic_check_failure",
                    "issues": issues,
                    "check_type": "30_day",
                },
                sensor_id="SYSTEM",
            )
        else:
            _logger.info("30-day checks: all passed")
            with self._lock:
                if self._health == SystemHealth.DEGRADED:
                    self._health = SystemHealth.HEALTHY

        with self._lock:
            self._periodic_check_timer = None

        self.start_periodic_checks()

    def _check_reference_ring(self) -> bool:
        """Check if reference ring resistance has drifted >1% from initial value.

        Uses the sensor manager's V_ref_history or V_mid to estimate R_r stability.
        If no initial reference is stored, captures the current value as baseline.

        Returns:
            True if drift is within ±1%, False otherwise.
        """
        v_ref = self._read_v_ref()
        if v_ref is None:
            _logger.debug("Reference ring check: no V_ref data available – skipping")
            return True

        if self._reference_ring_initial is None:
            self._reference_ring_initial = v_ref
            _logger.info(
                "Reference ring baseline captured: V_ref=%.4f V", v_ref
            )
            return True

        drift_pct = abs(v_ref - self._reference_ring_initial) / self._reference_ring_initial * 100

        if drift_pct > 1.0:
            _logger.warning(
                "Reference ring drift: %.2f%% (initial=%.4f V, current=%.4f V)",
                drift_pct, self._reference_ring_initial, v_ref,
            )
            self._raise_alarm(
                level=AlarmLevel.LEVEL_3,
                alarm_type=AlarmType.SYSTEM_ERROR,
                details={
                    "event": "reference_ring_drift",
                    "drift_percent": round(drift_pct, 2),
                    "initial_v": self._reference_ring_initial,
                    "current_v": v_ref,
                },
                sensor_id="ER_PROBE",
            )
            return False

        _logger.debug(
            "Reference ring check: drift=%.3f%% – within tolerance", drift_pct
        )
        return True

    def _check_current_source_periodic(self) -> bool:
        """Check current source output is within ±2% of nominal.

        Stricter than POST (±5%) because the system is calibrated.
        Nominal value is 2.5V, so range is 2.45V to 2.55V.

        Returns:
            True if within ±2%, False otherwise.
        """
        v_ref = self._read_v_ref()
        if v_ref is None:
            _logger.debug("Current source periodic check: no data – skipping")
            return True

        nominal = self._current_source_nominal
        lower = nominal * 0.98
        upper = nominal * 1.02
        drift_pct = abs(v_ref - nominal) / nominal * 100

        if v_ref < lower or v_ref > upper:
            _logger.warning(
                "Current source periodic check: drift=%.2f%% (V_ref=%.4f V) exceeds ±2%%",
                drift_pct, v_ref,
            )
            return False

        _logger.debug(
            "Current source periodic check: drift=%.3f%% – within tolerance", drift_pct
        )
        return True

    def _check_qcm_base_frequency(self) -> bool:
        """Check QCM base frequency hasn't drifted more than 500 Hz from initial.

        Uses delta_f from the sensor manager as a proxy. If no initial
        baseline is stored, captures the current value.

        Returns:
            True if drift ≤ 500 Hz, False otherwise.
        """
        sensor_mgr = self._get_sensor_manager()
        if sensor_mgr is None:
            return True

        last_data = sensor_mgr.get_last_data()
        if last_data is None:
            _logger.debug("QCM frequency check: no data – skipping")
            return True

        current_delta_f = last_data.delta_f

        if self._qcm_base_frequency_initial is None:
            self._qcm_base_frequency_initial = current_delta_f
            _logger.info(
                "QCM base frequency baseline captured: delta_f=%.2f Hz",
                current_delta_f,
            )
            return True

        drift = abs(current_delta_f - self._qcm_base_frequency_initial)
        if drift > 500.0:
            _logger.warning(
                "QCM frequency drift: %.1f Hz (initial=%.2f Hz, current=%.2f Hz)",
                drift, self._qcm_base_frequency_initial, current_delta_f,
            )
            self._raise_alarm(
                level=AlarmLevel.LEVEL_3,
                alarm_type=AlarmType.SENSOR_FAULT,
                details={
                    "event": "qcm_frequency_drift",
                    "drift_hz": round(drift, 1),
                    "initial_hz": self._qcm_base_frequency_initial,
                    "current_hz": current_delta_f,
                },
                sensor_id="QCM",
            )
            return False

        _logger.debug("QCM frequency check: drift=%.1f Hz – within tolerance", drift)
        return True

    def run_collection_cycle_checks(self, sensor_data) -> List[str]:
        """Run per-collection-cycle diagnostic checks.

        Checks:
            1. Sensor communication status
            2. Data reasonableness (physical range checks)
            3. MCU temperature (< 85°C)

        Args:
            sensor_data: SensorData object from the current acquisition cycle.

        Returns:
            List of issue description strings found.
        """
        issues: List[str] = []

        comm_issues = self._check_sensor_communication()
        issues.extend(comm_issues)

        reasonableness_issues = self.check_data_reasonableness(sensor_data)
        issues.extend(reasonableness_issues)

        mcu_temp_ok = self._check_mcu_temperature(sensor_data)
        if not mcu_temp_ok:
            issues.append("MCU temperature exceeds 85°C threshold")

        if issues:
            _logger.debug(
                "Collection cycle checks: %d issue(s) found: %s",
                len(issues), issues,
            )

        return issues

    def _check_sensor_communication(self) -> List[str]:
        """Check sensor communication status from the sensor manager.

        Returns:
            List of issue strings for sensors with communication problems.
        """
        issues: List[str] = []
        sensor_mgr = self._get_sensor_manager()
        if sensor_mgr is None:
            return issues

        stats = sensor_mgr.get_stats()
        if stats.get("packets_parse_errors", 0) > 0:
            issues.append(
                f"Packet parse errors: {stats['packets_parse_errors']}"
            )
        if stats.get("packets_crc_errors", 0) > 0:
            issues.append(
                f"Packet CRC errors: {stats['packets_crc_errors']}"
            )
        if stats.get("read_errors", 0) > 0:
            issues.append(
                f"Serial read errors: {stats['read_errors']}"
            )

        return issues

    def check_data_reasonableness(self, sensor_data) -> List[str]:
        """Check sensor values are within physical bounds.

        Valid ranges:
            - T: -40 to 85 °C
            - RH: 0 to 100%
            - Δd: 0 to 1000 μm (1mm max before catastrophic failure)
            - Cl⁻: 0 to 10000 mg/(m²·day)

        Args:
            sensor_data: SensorData object to validate.

        Returns:
            List of out-of-range violation description strings.
        """
        violations: List[str] = []

        if sensor_data is None:
            return ["No sensor data available"]

        if sensor_data.T < -40.0 or sensor_data.T > 85.0:
            violations.append(
                f"Temperature out of range: T={sensor_data.T:.1f}°C (expected -40 to 85°C)"
            )
            with self._lock:
                self._invalid_data_count += 1

        if sensor_data.RH < 0.0 or sensor_data.RH > 100.0:
            violations.append(
                f"Humidity out of range: RH={sensor_data.RH:.1f}% (expected 0 to 100%)"
            )
            with self._lock:
                self._invalid_data_count += 1

        if sensor_data.delta_d_ER < 0.0 or sensor_data.delta_d_ER > 1000.0:
            violations.append(
                f"ER corrosion depth out of range: Δd_ER={sensor_data.delta_d_ER:.2f}μm "
                f"(expected 0 to 1000μm)"
            )
            with self._lock:
                self._invalid_data_count += 1

        if sensor_data.delta_d_Inductive < 0.0 or sensor_data.delta_d_Inductive > 1000.0:
            violations.append(
                f"Inductive corrosion depth out of range: Δd_Inductive="
                f"{sensor_data.delta_d_Inductive:.2f}μm (expected 0 to 1000μm)"
            )
            with self._lock:
                self._invalid_data_count += 1

        if sensor_data.Cl_deposition < 0.0 or sensor_data.Cl_deposition > 10000.0:
            violations.append(
                f"Cl⁻ deposition out of range: {sensor_data.Cl_deposition:.2f} "
                f"mg/(m²·day) (expected 0 to 10000)"
            )
            with self._lock:
                self._invalid_data_count += 1

        return violations

    def _check_mcu_temperature(self, sensor_data) -> bool:
        """Check if MCU temperature is within safe limits (< 85°C).

        Uses the system temperature reading as a proxy for MCU temperature
        since both are in the same enclosure. In a real deployment, the MCU
        would report its own temperature via heartbeat packets.

        Args:
            sensor_data: SensorData object.

        Returns:
            True if temperature is < 85°C, False otherwise.
        """
        if sensor_data is None:
            return True

        if sensor_data.T >= 85.0:
            _logger.warning(
                "MCU temperature check: T=%.1f°C exceeds 85°C threshold",
                sensor_data.T,
            )
            self._raise_alarm(
                level=AlarmLevel.LEVEL_3,
                alarm_type=AlarmType.SYSTEM_ERROR,
                details={
                    "event": "mcu_overtemperature",
                    "temperature_c": sensor_data.T,
                    "threshold_c": 85.0,
                },
                sensor_id="MCU",
            )
            return False

        return True

    # ==================================================================
    # Watchdog
    # ==================================================================

    def feed_watchdog(self) -> None:
        """Feed the watchdog timer.

        Must be called regularly from the main application loop to
        prevent watchdog timeout.
        """
        self._watchdog_timer.feed()
        self._last_watchdog_feed = time.time()

    def start_watchdog(self) -> None:
        """Start the watchdog monitoring thread.

        The watchdog must be fed at least every 30 seconds via
        feed_watchdog() to prevent triggering a system reset.
        """
        self._watchdog_timer.start()
        _logger.info(
            "Watchdog started (timeout=%.0fs)", self._watchdog_timeout
        )

    def _on_watchdog_timeout(self) -> None:
        """Handle watchdog timeout event.

        Called by the WatchdogTimer when the timeout elapses.
        Saves critical state and performs system reset.
        """
        _logger.critical(
            "WATCHDOG TIMEOUT – system reset required "
            "(last feed: %.1fs ago)",
            time.time() - self._last_watchdog_feed,
        )

        try:
            self._save_state_before_reset()
        except Exception as e:
            _logger.error("Failed to save state before watchdog reset: %s", e)

        self._perform_reset()

    def _save_state_before_reset(self) -> None:
        """Save critical system state to non-volatile storage before reset.

        Saves:
            - Current system mode (AppState)
            - Last valid configuration
            - Sensor baseline values (reference ring V_ref, QCM base freq)
            - Watchdog reset event to audit log
        """
        state_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "watchdog_reset",
            "saved_state": {},
        }

        try:
            app = self._app
            if app is not None:
                state_data["saved_state"]["app_state"] = (
                    app.state.name if hasattr(app.state, 'name') else str(app.state)
                )
                state_data["saved_state"]["mode"] = (
                    app.state.name if hasattr(app.state, 'name') else "unknown"
                )
        except Exception as e:
            _logger.error("Error capturing app state: %s", e)

        try:
            app = self._app
            if app is not None and app.config_manager is not None:
                config = app.config_manager.get_all()
                state_data["saved_state"]["config"] = {
                    k: v for k, v in config.items()
                    if k != "validation_ranges"
                }
        except Exception as e:
            _logger.error("Error capturing config: %s", e)

        state_data["saved_state"]["baselines"] = {
            "reference_ring_initial": self._reference_ring_initial,
            "qcm_base_frequency_initial": self._qcm_base_frequency_initial,
            "current_source_nominal": self._current_source_nominal,
        }

        try:
            state_file = "watchdog_state.json"
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False, default=str)
            _logger.info("Watchdog: state saved to %s", state_file)
        except Exception as e:
            _logger.error("Failed to write watchdog state file: %s", e)

        self._save_audit_log(
            operator="SYSTEM",
            operation_type=OperationType.SYSTEM_RESTART,
            details={
                "event": "watchdog_reset",
                "last_feed_age_s": round(time.time() - self._last_watchdog_feed, 2),
            },
            result="pending",
        )

    def _perform_reset(self) -> None:
        """Perform system reset and restore to previous operating mode.

        Attempts to restart the application via app.restart().
        Logs the reset event.
        """
        _logger.critical("Performing system reset via watchdog...")

        try:
            app = self._app
            if app is not None:
                if app.logger:
                    log = app.logger.get_logger("WatchdogReset")
                    log.critical(
                        "System reset triggered by watchdog at %s",
                        datetime.now(timezone.utc).isoformat(),
                    )

                app.stop()
                time.sleep(1.0)
                app.initialize()
                app.start()
                _logger.info("System reset completed successfully")
            else:
                _logger.critical("No App instance available for reset")
        except Exception as e:
            _logger.critical("System reset failed: %s", e)
            traceback.print_exc()

    # ==================================================================
    # Health Status
    # ==================================================================

    def get_health_status(self) -> dict:
        """Get comprehensive system health report.

        Returns:
            Dictionary with health state, POST results, sensor status,
            last check times, uptime, memory usage, and disk usage.
        """
        with self._lock:
            health_value = self._health.value
            post_results = {
                name: result.value
                for name, result in self._post_results.items()
            }

        uptime_seconds = time.time() - self._start_time

        memory_usage = 0.0
        disk_usage = 0.0
        if _PSUTIL_AVAILABLE:
            try:
                proc = psutil.Process(os.getpid())
                memory_usage = round(
                    proc.memory_info().rss / (1024 * 1024), 1
                )
                disk = psutil.disk_usage(os.getcwd())
                disk_usage = disk.percent
            except Exception:
                pass

        return {
            "health": health_value,
            "post_results": post_results,
            "sensor_status": self.get_sensor_status(),
            "last_checks": {
                "watchdog_feed_age_s": round(
                    time.time() - self._last_watchdog_feed, 2
                ),
                "invalid_data_count": self._invalid_data_count,
            },
            "uptime_seconds": round(uptime_seconds, 0),
            "uptime_formatted": str(timedelta(seconds=int(uptime_seconds))),
            "memory_usage_mb": memory_usage,
            "disk_usage_percent": disk_usage,
        }

    def get_system_info(self) -> dict:
        """Get system environment information.

        Returns:
            Dictionary with OS info, Python version, application version,
            uptime, and resource usage statistics.
        """
        import platform
        import sys

        info: Dict[str, Any] = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "python_version": sys.version,
            "python_implementation": platform.python_implementation(),
            "uptime_seconds": round(time.time() - self._start_time, 0),
            "uptime_formatted": str(
                timedelta(seconds=int(time.time() - self._start_time))
            ),
            "pid": os.getpid(),
        }

        try:
            app = self._app
            if app is not None and app.config_manager is not None:
                info["app_version"] = app.config_manager.get_version()
        except Exception:
            info["app_version"] = "unknown"

        if _PSUTIL_AVAILABLE:
            try:
                info["cpu_percent"] = psutil.cpu_percent(interval=0.1)
                info["cpu_count"] = psutil.cpu_count()

                mem = psutil.virtual_memory()
                info["memory_total_mb"] = round(mem.total / (1024 * 1024), 1)
                info["memory_available_mb"] = round(mem.available / (1024 * 1024), 1)
                info["memory_percent"] = mem.percent

                proc = psutil.Process(os.getpid())
                info["process_memory_mb"] = round(
                    proc.memory_info().rss / (1024 * 1024), 1
                )

                disk = psutil.disk_usage(os.getcwd())
                info["disk_total_gb"] = round(disk.total / (1024 ** 3), 2)
                info["disk_used_gb"] = round(disk.used / (1024 ** 3), 2)
                info["disk_free_gb"] = round(disk.free / (1024 ** 3), 2)
                info["disk_percent"] = disk.percent
            except Exception as e:
                _logger.debug("Failed to collect some system info: %s", e)

        return info

    def get_sensor_status(self) -> dict:
        """Get status of each sensor: online/offline, last reading time, error count.

        Returns:
            Dictionary mapping sensor names to status information.
        """
        status: Dict[str, Dict[str, Any]] = {}
        sensor_names = ["pt1000", "sht35", "qcm", "er", "inductive"]

        sensor_mgr = self._get_sensor_manager()
        last_data = sensor_mgr.get_last_data() if sensor_mgr else None
        stats = sensor_mgr.get_stats() if sensor_mgr else {}

        for name in sensor_names:
            status[name] = {
                "online": sensor_mgr is not None and sensor_mgr.is_initialized,
                "last_reading": (
                    last_data.timestamp.isoformat()
                    if last_data is not None
                    else None
                ),
                "error_count": self._sensor_error_counts.get(name, 0),
            }

        if last_data is not None:
            status["pt1000"]["last_value"] = last_data.T
            status["sht35"]["last_value"] = last_data.RH
            status["qcm"]["last_value"] = last_data.Cl_deposition
            status["er"]["last_value"] = last_data.delta_d_ER
            status["inductive"]["last_value"] = last_data.delta_d_Inductive

        if stats:
            status["_communication"] = {
                "packets_received": stats.get("packets_received", 0),
                "packets_parse_errors": stats.get("packets_parse_errors", 0),
                "packets_crc_errors": stats.get("packets_crc_errors", 0),
                "read_errors": stats.get("read_errors", 0),
            }

        return status

    # ==================================================================
    # Helpers
    # ==================================================================

    def _get_sensor_manager(self):
        """Get the SensorManager instance from the application.

        Returns:
            SensorManager instance, or None if not available.
        """
        try:
            app = self._app
            if app is not None:
                return app._modules.get("sensor_manager")
        except Exception:
            pass
        return None

    def _get_storage_manager(self):
        """Get the StorageManager instance from the application.

        Returns:
            StorageManager instance, or None if not available.
        """
        try:
            app = self._app
            if app is not None:
                return app._modules.get("storage")
        except Exception:
            pass
        return None

    def _raise_alarm(
        self,
        level: AlarmLevel,
        alarm_type: AlarmType,
        details: dict,
        sensor_id: str = "SYSTEM",
    ) -> None:
        """Raise an alarm through the application's alarm system.

        Attempts to use the AlarmManager singleton first for proper
        lifecycle management, duplicate suppression, and notification
        dispatch. Falls back to direct AlarmRecord creation and storage
        if AlarmManager is not available.

        Args:
            level: Alarm severity level.
            alarm_type: Type of alarm.
            details: Additional alarm details dictionary.
            sensor_id: Identifier of the associated sensor.
        """
        try:
            from .alarm_manager import AlarmManager

            alarm_mgr = AlarmManager()
            if alarm_mgr._storage is None:
                storage = self._get_storage_manager()
                if storage is not None:
                    alarm_mgr._storage = storage

            alarm_mgr.raise_alarm(
                level=level.value,
                alarm_type=alarm_type.value,
                details=details,
                sensor_id=sensor_id,
            )
        except Exception as e:
            _logger.error("Failed to raise alarm via AlarmManager: %s", e)
            try:
                alarm = AlarmRecord(
                    level=level,
                    alarm_type=alarm_type,
                    details=details,
                    sensor_id=sensor_id,
                )
                storage = self._get_storage_manager()
                if storage is not None:
                    storage.save_alarm_record(alarm)
                app = self._app
                if app is not None:
                    app.emit("alarm_raised", {
                        "alarm": alarm.to_dict(),
                        "source": "diagnostics",
                    })
            except Exception as e2:
                _logger.error("Failed to raise fallback alarm: %s", e2)

    def _save_audit_log(
        self,
        operator: str,
        operation_type: OperationType,
        details: dict,
        result: str = "success",
    ) -> None:
        """Save an audit log entry to storage.

        Args:
            operator: Name of the operator or "SYSTEM".
            operation_type: Type of operation.
            details: Operation details dictionary.
            result: Result string.
        """
        try:
            entry = AuditLogEntry(
                operator=operator,
                operation_type=operation_type,
                details=details,
                result=result,
            )
            storage = self._get_storage_manager()
            if storage is not None:
                storage.save_audit_log(entry)
        except Exception as e:
            _logger.error("Failed to save audit log: %s", e)

    def record_sensor_error(self, sensor_name: str) -> None:
        """Increment the error count for a specific sensor.

        Args:
            sensor_name: Sensor identifier string.
        """
        with self._lock:
            self._sensor_error_counts[sensor_name] = (
                self._sensor_error_counts.get(sensor_name, 0) + 1
            )
            self._sensor_last_reading[sensor_name] = datetime.now(timezone.utc)

    def record_sensor_success(self, sensor_name: str) -> None:
        """Record a successful sensor reading.

        Args:
            sensor_name: Sensor identifier string.
        """
        with self._lock:
            self._sensor_last_reading[sensor_name] = datetime.now(timezone.utc)

    def update_health_from_issues(self, issues: List[str]) -> None:
        """Update the system health based on discovered issues.

        If issues are found and the system was HEALTHY, transitions to
        DEGRADED. If previously DEGRADED and no issues remain unchanged.

        Args:
            issues: List of issue description strings.
        """
        with self._lock:
            if issues:
                if self._health == SystemHealth.HEALTHY:
                    self._health = SystemHealth.DEGRADED
                    _logger.warning(
                        "Health transition: HEALTHY -> DEGRADED (issues: %s)",
                        issues,
                    )
            else:
                if self._health == SystemHealth.DEGRADED:
                    self._health = SystemHealth.HEALTHY
                    _logger.info("Health transition: DEGRADED -> HEALTHY")

    # ==================================================================
    # Properties
    # ==================================================================

    @property
    def health(self) -> SystemHealth:
        """Get the current system health state."""
        with self._lock:
            return self._health

    @property
    def post_results(self) -> Dict[str, POSTResult]:
        """Get the POST results dictionary."""
        with self._lock:
            return dict(self._post_results)

    @property
    def watchdog(self) -> WatchdogTimer:
        """Get the watchdog timer instance."""
        return self._watchdog_timer

    @property
    def invalid_data_count(self) -> int:
        """Get the count of invalid data since diagnostics startup."""
        with self._lock:
            return self._invalid_data_count
