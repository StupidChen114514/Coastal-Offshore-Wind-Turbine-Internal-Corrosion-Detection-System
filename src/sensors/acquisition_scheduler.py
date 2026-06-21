"""
Acquisition Scheduler for timed sensor data collection.

Manages periodic sensor data acquisition with two operating modes:
    - Normal mode: 10-minute interval (configurable)
    - Emergency mode: 1-minute interval for 30 minutes, triggered when
      |d(CR)/dt| exceeds threshold

Implements sequential sensor acquisition order (Pt1000 -> SHT35 -> QCM -> ER
-> Inductive), retry logic with timeout, and callback-based data delivery.

Thread-safe operation using threading primitives.
"""

import threading
import time
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Callable, Dict, List, Optional

from ..core.data_models import SensorData
from ..core.logger import CorrosionLogger

logger = CorrosionLogger().get_logger(__name__)


class SchedulerState(Enum):
    """Acquisition scheduler states."""

    IDLE = auto()
    NORMAL = auto()
    EMERGENCY = auto()
    STOPPED = auto()
    ERROR = auto()


class SensorAcquisitionStatus(Enum):
    """Per-sensor acquisition status."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"


class AcquisitionScheduler:
    """Timed sensor data acquisition scheduler.

    Manages periodic data acquisition with dual-mode operation:
      - NORMAL: Standard interval (default 10 minutes)
      - EMERGENCY: Accelerated interval (default 1 minute, max 30 minutes)

    The acquisition order is fixed: Pt1000 -> SHT35 -> QCM -> ER -> Inductive.
    Each sensor is attempted up to 3 times before being marked as failed.
    After a successful acquisition cycle, the registered callback is invoked
    with the collected SensorData.

    Attributes:
        normal_interval_s: Normal mode sampling period (default 600s).
        emergency_interval_s: Emergency mode sampling period (default 60s).
        emergency_duration_s: Maximum emergency mode duration (default 1800s).
        max_retries: Maximum retry attempts per sensor (default 3).
        retry_delay_s: Delay between retries in seconds (default 0.5).
        threshold_CR_change: CR rate-of-change threshold for emergency trigger.
    """

    ACQUISITION_ORDER: List[str] = [
        "pt1000",
        "sht35",
        "qcm",
        "er",
        "inductive",
    ]

    def __init__(
        self,
        normal_interval_s: float = 600.0,
        emergency_interval_s: float = 60.0,
        emergency_duration_s: float = 1800.0,
        max_retries: int = 3,
        retry_delay_s: float = 0.5,
        threshold_CR_change: float = 0.005,
    ) -> None:
        """Initialize the acquisition scheduler.

        Args:
            normal_interval_s: Normal sampling period in seconds (default 600).
            emergency_interval_s: Emergency sampling period in seconds (default 60).
            emergency_duration_s: Maximum emergency mode duration in seconds (default 1800).
            max_retries: Maximum acquisition retries per sensor (default 3).
            retry_delay_s: Delay between retries in seconds (default 0.5).
            threshold_CR_change: CR rate-of-change threshold for emergency (mm/yr/min).
        """
        self.normal_interval_s = normal_interval_s
        self.emergency_interval_s = emergency_interval_s
        self.emergency_duration_s = emergency_duration_s
        self.max_retries = max_retries
        self.retry_delay_s = retry_delay_s
        self.threshold_CR_change = threshold_CR_change

        self._state = SchedulerState.IDLE
        self._state_lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._stop_event = threading.Event()

        self._sensor_manager = None
        self._data_callback: Optional[Callable[[SensorData], None]] = None
        self._status_callback: Optional[Callable[[Dict], None]] = None

        self._emergency_start_time: Optional[float] = None
        self._last_acquisition_time: Optional[float] = None
        self._previous_sensor_data: Optional[SensorData] = None
        self._last_CR_ER: Optional[float] = None
        self._last_CR_Inductive: Optional[float] = None

        self._acquisition_count: int = 0
        self._failed_acquisitions: int = 0
        self._sensor_status: Dict[str, List[Dict]] = {}
        self._stats_lock = threading.Lock()

        logger.info(
            "AcquisitionScheduler created: normal=%ds, emergency=%ds, "
            "emergency_duration=%ds, retries=%d",
            normal_interval_s,
            emergency_interval_s,
            emergency_duration_s,
            max_retries,
        )

    def set_sensor_manager(self, sensor_manager) -> None:
        """Bind a SensorManager instance for data acquisition.

        Args:
            sensor_manager: SensorManager instance.
        """
        self._sensor_manager = sensor_manager
        logger.debug("AcquisitionScheduler bound to SensorManager")

    def set_data_callback(
        self, callback: Callable[[SensorData], None]
    ) -> None:
        """Register a callback for completed acquisition cycles.

        Args:
            callback: Callable that receives a SensorData object.
        """
        self._data_callback = callback
        logger.debug("AcquisitionScheduler data callback registered")

    def set_status_callback(
        self, callback: Callable[[Dict], None]
    ) -> None:
        """Register a callback for acquisition status updates.

        Args:
            callback: Callable that receives a status dictionary.
        """
        self._status_callback = callback
        logger.debug("AcquisitionScheduler status callback registered")

    def start(self) -> None:
        """Start the acquisition scheduler.

        Raises:
            RuntimeError: If no SensorManager is bound.
        """
        if self._sensor_manager is None:
            raise RuntimeError(
                "SensorManager must be bound before starting scheduler"
            )

        with self._state_lock:
            self._state = SchedulerState.NORMAL
        self._stop_event.clear()
        self._schedule_next()
        logger.info(
            "AcquisitionScheduler started in %s mode (interval=%.0fs)",
            self._state.name,
            self._get_current_interval(),
        )

    def stop(self) -> None:
        """Stop the acquisition scheduler."""
        self._stop_event.set()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

        with self._state_lock:
            self._state = SchedulerState.STOPPED
        logger.info(
            "AcquisitionScheduler stopped (cycles: %d, failures: %d)",
            self._acquisition_count,
            self._failed_acquisitions,
        )

    def trigger_emergency(self, reason: str = "manual") -> None:
        """Manually trigger emergency acquisition mode.

        Args:
            reason: Human-readable reason for emergency mode.
        """
        with self._state_lock:
            if self._state == SchedulerState.EMERGENCY:
                self._emergency_start_time = time.time()
                logger.info("Emergency mode extended (reason: %s)", reason)
                return

            self._state = SchedulerState.EMERGENCY
            self._emergency_start_time = time.time()

        logger.warning(
            "Emergency acquisition mode activated (reason: %s, interval=%.0fs, "
            "duration=%.0fs)",
            reason,
            self.emergency_interval_s,
            self.emergency_duration_s,
        )

        if self._timer is not None:
            self._timer.cancel()
        self._schedule_next()

    def _schedule_next(self) -> None:
        """Schedule the next acquisition cycle."""
        if self._stop_event.is_set():
            return

        interval = self._get_current_interval()
        self._timer = threading.Timer(interval, self._acquisition_cycle)
        self._timer.daemon = True
        self._timer.start()

        logger.debug("Next acquisition scheduled in %.0fs", interval)

    def _get_current_interval(self) -> float:
        """Get the current sampling interval based on mode.

        Returns:
            Sampling interval in seconds.
        """
        with self._state_lock:
            if self._state == SchedulerState.EMERGENCY:
                return self.emergency_interval_s
            return self.normal_interval_s

    def _acquisition_cycle(self) -> None:
        """Execute a single acquisition cycle for all sensors.

        Performs sequential acquisition in the order:
            Pt1000 -> SHT35 -> QCM -> ER -> Inductive

        Each sensor gets up to max_retries attempts. After all sensors are
        read, the data is aggregated into a SensorData object and the
        callback is invoked.
        """
        if self._stop_event.is_set():
            return

        cycle_start = time.time()
        logger.debug("Acquisition cycle %d started", self._acquisition_count + 1)

        results: Dict[str, Optional[SensorData]] = {}
        statuses: Dict[str, SensorAcquisitionStatus] = {}

        for sensor_name in self.ACQUISITION_ORDER:
            if self._stop_event.is_set():
                return

            success, data = self._acquire_with_retry(sensor_name)
            results[sensor_name] = data
            statuses[sensor_name] = (
                SensorAcquisitionStatus.SUCCESS
                if success
                else SensorAcquisitionStatus.FAILED
            )

        sensor_data = self._aggregate_results(results, statuses, cycle_start)

        self._update_stats(sensor_data, statuses)

        if sensor_data is not None and self._data_callback:
            try:
                self._data_callback(sensor_data)
            except Exception as e:
                logger.error("Data callback error: %s", e)

        if self._status_callback:
            try:
                self._status_callback(self._get_status_dict(statuses))
            except Exception as e:
                logger.error("Status callback error: %s", e)

        self._check_emergency_conditions(sensor_data)
        self._check_emergency_timeout()

        cycle_elapsed = time.time() - cycle_start
        logger.debug(
            "Acquisition cycle %d completed in %.3fs",
            self._acquisition_count,
            cycle_elapsed,
        )

        with self._stats_lock:
            self._acquisition_count += 1
            self._last_acquisition_time = time.time()

        self._schedule_next()

    def _acquire_with_retry(
        self, sensor_name: str
    ) -> tuple:
        """Attempt to acquire data from a sensor with retry logic.

        Args:
            sensor_name: Sensor identifier string.

        Returns:
            Tuple of (success_bool, SensorData_or_None).
        """
        for attempt in range(self.max_retries):
            if self._stop_event.is_set():
                return (False, None)

            try:
                data = self._acquire_single(sensor_name)
                if data is not None:
                    logger.debug(
                        "%s acquisition succeeded (attempt %d/%d)",
                        sensor_name,
                        attempt + 1,
                        self.max_retries,
                    )
                    return (True, data)

                if attempt < self.max_retries - 1:
                    logger.debug(
                        "%s acquisition failed, retrying (%d/%d)...",
                        sensor_name,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(self.retry_delay_s)

            except Exception as e:
                logger.error(
                    "%s acquisition error on attempt %d: %s",
                    sensor_name,
                    attempt + 1,
                    e,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay_s)

        logger.warning(
            "%s acquisition FAILED after %d attempts",
            sensor_name,
            self.max_retries,
        )
        return (False, None)

    def _acquire_single(self, sensor_name: str) -> Optional[SensorData]:
        """Acquire data from a single sensor.

        In the current architecture, all sensor data comes through the MCU
        as a unified packet. This method extracts the relevant portion.

        Args:
            sensor_name: Sensor identifier string.

        Returns:
            SensorData for this sensor's data subset, or None on failure.
        """
        if self._sensor_manager is None:
            return None

        full_data = self._sensor_manager.read_single_shot()

        if full_data is None:
            return None

        return full_data

    def _aggregate_results(
        self,
        results: Dict[str, Optional[SensorData]],
        statuses: Dict[str, SensorAcquisitionStatus],
        cycle_start: float,
    ) -> Optional[SensorData]:
        """Aggregate individual sensor results into a unified SensorData.

        Args:
            results: Per-sensor acquisition results.
            statuses: Per-sensor acquisition statuses.
            cycle_start: Cycle start timestamp.

        Returns:
            Aggregated SensorData, or None if all sensors failed.
        """
        all_failed = all(
            s != SensorAcquisitionStatus.SUCCESS for s in statuses.values()
        )
        if all_failed:
            with self._stats_lock:
                self._failed_acquisitions += 1
            logger.error("All sensors failed in acquisition cycle")
            return None

        data = results.get("pt1000") or results.get("er") or SensorData()

        combined_timestamp = datetime.fromtimestamp(cycle_start, tz=timezone.utc)
        data.timestamp = combined_timestamp

        failed_sensors = [
            name
            for name, status in statuses.items()
            if status != SensorAcquisitionStatus.SUCCESS
        ]
        if failed_sensors:
            data.valid_flag = False
            logger.warning(
                "Partial acquisition: sensors %s failed", failed_sensors
            )

        self._previous_sensor_data = data
        return data

    def _update_stats(
        self,
        sensor_data: Optional[SensorData],
        statuses: Dict[str, SensorAcquisitionStatus],
    ) -> None:
        """Update internal statistics from acquisition results.

        Args:
            sensor_data: Aggregated sensor data.
            statuses: Per-sensor statuses.
        """
        with self._stats_lock:
            for name, status in statuses.items():
                if name not in self._sensor_status:
                    self._sensor_status[name] = []
                self._sensor_status[name].append(
                    {
                        "timestamp": time.time(),
                        "status": status.value,
                    }
                )
                entry_count = len(self._sensor_status[name])
                if entry_count > 100:
                    self._sensor_status[name] = self._sensor_status[name][-50:]

    def _get_status_dict(
        self, statuses: Dict[str, SensorAcquisitionStatus]
    ) -> Dict:
        """Build a status dictionary for callback.

        Args:
            statuses: Per-sensor statuses.

        Returns:
            Status dictionary.
        """
        with self._stats_lock:
            return {
                "timestamp": time.time(),
                "mode": self._state.name,
                "cycle": self._acquisition_count + 1,
                "sensor_statuses": {k: v.value for k, v in statuses.items()},
                "total_acquisitions": self._acquisition_count,
                "total_failures": self._failed_acquisitions,
            }

    def _check_emergency_conditions(
        self, sensor_data: Optional[SensorData]
    ) -> None:
        """Check if emergency conditions are met based on corrosion rate change.

        When |d(CR)/dt| exceeds the threshold, emergency mode is triggered.

        Args:
            sensor_data: Most recent SensorData.
        """
        if sensor_data is None:
            return

        with self._state_lock:
            current_state = self._state

        if current_state == SchedulerState.EMERGENCY:
            return

        if self._previous_sensor_data is None:
            return

        prev = self._previous_sensor_data
        if prev is sensor_data:
            return

        dt = (
            sensor_data.timestamp.timestamp() - prev.timestamp.timestamp()
        )
        if dt <= 0:
            return

        dCR_ER = abs(sensor_data.delta_d_ER - prev.delta_d_ER) / dt
        dCR_Inductive = abs(
            sensor_data.delta_d_Inductive - prev.delta_d_Inductive
        ) / dt

        if (
            dCR_ER > self.threshold_CR_change
            or dCR_Inductive > self.threshold_CR_change
        ):
            reason = (
                f"d(CR_ER)/dt={dCR_ER:.4f} um/s, "
                f"d(CR_Inductive)/dt={dCR_Inductive:.4f} um/s"
            )
            self.trigger_emergency(reason)

    def _check_emergency_timeout(self) -> None:
        """Check if emergency mode has timed out and revert to normal."""
        with self._state_lock:
            if self._state != SchedulerState.EMERGENCY:
                return

        if self._emergency_start_time is None:
            return

        elapsed = time.time() - self._emergency_start_time
        if elapsed >= self.emergency_duration_s:
            with self._state_lock:
                self._state = SchedulerState.NORMAL
                self._emergency_start_time = None
            logger.info(
                "Emergency mode timed out after %.0fs, reverting to NORMAL mode",
                elapsed,
            )

    def get_state(self) -> SchedulerState:
        """Get the current scheduler state.

        Returns:
            Current SchedulerState.
        """
        return self._state

    def get_stats(self) -> Dict:
        """Get comprehensive scheduler statistics.

        Returns:
            Statistics dictionary.
        """
        with self._stats_lock:
            return {
                "state": self._state.name,
                "acquisition_count": self._acquisition_count,
                "failed_acquisitions": self._failed_acquisitions,
                "last_acquisition_time": self._last_acquisition_time,
                "sensor_status_counts": {
                    name: len([e for e in entries if e["status"] == "SUCCESS"])
                    for name, entries in self._sensor_status.items()
                },
            }

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is actively running."""
        with self._state_lock:
            return self._state not in (SchedulerState.IDLE, SchedulerState.STOPPED)
