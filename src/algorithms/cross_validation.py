"""
Cross-Validation Engine integrating error compensation and dual-mode validation.

Combines the four-level error compensation pipeline (AlgorithmEngine) with
dual-mode redundant cross-validation (DualModeValidator) into a single
processing cycle for the coastal offshore wind turbine corrosion detection system.

Each 10-minute cycle:
    1. Runs AlgorithmEngine.process_sensor_data() → CorrosionRecord
    2. Runs DualModeValidator.validate() on the results → DualModeResult
    3. Generates alarms based on validation decisions
    4. Returns combined CrossValidationResult
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..core.config_manager import ConfigManager
from ..core.data_models import (
    AlarmLevel,
    AlarmType,
    CorrosionRecord,
    CrossValidationResult,
    DualModeResult,
    DualModeStatus,
    SensorData,
)
from .algorithm_engine import AlgorithmEngine
from .dual_mode_validator import DualModeValidator

logger = logging.getLogger(__name__)

WARNING_ALARM_LEVELS = {3, 4}


class CrossValidationEngine:
    """
    Integrates error compensation and dual-mode cross-validation.

    Orchestrates the full processing pipeline for each sensor data reading:
    first compensates raw data through the four-level algorithm engine,
    then cross-validates ER and inductive probe measurements to detect
    temperature artifacts and non-uniform (pitting) corrosion.

    Alarms are generated automatically based on validation outcomes and
    dispatched through the application signal system.
    """

    def __init__(self, app_instance: Any) -> None:
        self._app = app_instance
        self._config: ConfigManager = app_instance.config_manager

        self._algorithm_engine = AlgorithmEngine(self._config)
        self._algorithm_engine.initialize()

        self._validator = DualModeValidator(self._config)

        self._lock = threading.Lock()
        self._T_history: List[Tuple[datetime, float]] = []
        self._max_T_history: int = 5
        self._initialized: bool = False

    def initialize(self) -> bool:
        """Initialize both sub-engines."""
        logger.info("Initializing CrossValidationEngine")
        engine_ok = self._algorithm_engine.initialize()
        if not engine_ok:
            logger.error("AlgorithmEngine initialization failed")
            return False

        self._initialized = True
        logger.info("CrossValidationEngine initialized successfully")
        return True

    def process_cycle(self, sensor_data: SensorData) -> CrossValidationResult:
        """
        Process one complete sensor data cycle through both engines.

        Args:
            sensor_data: Raw sensor reading with ER, inductive, temperature,
                         and humidity data.

        Returns:
            CrossValidationResult with the corrosion record, dual-mode result,
            generated alarms, and final consolidated values.
        """
        if not self._initialized:
            logger.warning("CrossValidationEngine not initialized, initializing now")
            if not self.initialize():
                return CrossValidationResult(
                    final_cr=0.0,
                    final_delta_d=0.0,
                    timestamp=sensor_data.timestamp,
                )

        with self._lock:
            corrosion_record = self._algorithm_engine.process_sensor_data(
                sensor_data
            )

            self._update_T_history(sensor_data.timestamp, sensor_data.T)

            if corrosion_record is not None:
                cr_er = corrosion_record.CR_ER
                cr_inductive = corrosion_record.CR_Inductive

                if cr_inductive == 0.0:
                    cr_inductive = self._estimate_inductive_cr(sensor_data)
            else:
                cr_er = 0.0
                cr_inductive = 0.0

            dual_mode_result = self._validator.validate(
                delta_d_er=sensor_data.delta_d_ER,
                delta_d_inductive=sensor_data.delta_d_Inductive,
                timestamp=sensor_data.timestamp,
                dT_dt=None,
                T_history=list(self._T_history),
            )

            if corrosion_record is not None and cr_inductive == 0.0:
                corrosion_record.CR_Inductive = dual_mode_result.cr_inductive

            alarms = self._generate_alarms(dual_mode_result, sensor_data)

            final_cr = dual_mode_result.cr_out
            final_delta_d = dual_mode_result.delta_d_actual

            if dual_mode_result.status == DualModeStatus.DUAL_CONSISTENT and final_delta_d == 0.0:
                if corrosion_record is not None:
                    final_delta_d = corrosion_record.delta_d_filtered
                else:
                    final_delta_d = sensor_data.delta_d_ER

        result = CrossValidationResult(
            corrosion_record=corrosion_record,
            dual_mode_result=dual_mode_result,
            alarms_to_trigger=alarms,
            final_cr=final_cr,
            final_delta_d=final_delta_d,
            timestamp=sensor_data.timestamp,
        )

        for alarm in alarms:
            self._dispatch_alarm(alarm)

        logger.debug(
            "Process cycle complete: CR=%.4f μm/year, Δd=%.4f μm, "
            "status=%s, alarms=%d",
            final_cr, final_delta_d, dual_mode_result.status, len(alarms),
        )

        return result

    def _estimate_inductive_cr(self, sensor_data: SensorData) -> float:
        dt_seconds = 600.0
        dd = sensor_data.delta_d_Inductive
        if dd <= 0:
            return 0.0
        cr = (dd / dt_seconds) * 8760.0 * 3600.0
        return cr

    def _update_T_history(self, timestamp: datetime, T: float) -> None:
        self._T_history.append((timestamp, T))
        if len(self._T_history) > self._max_T_history:
            self._T_history.pop(0)

    def _generate_alarms(
        self, dual_result: DualModeResult, sensor_data: SensorData
    ) -> List[Dict[str, Any]]:
        alarms: List[Dict[str, Any]] = []

        if dual_result.alarm_level == 0:
            return alarms

        alarm = {
            "timestamp": dual_result.timestamp.isoformat(),
            "level": dual_result.alarm_level,
            "alarm_type": AlarmType.CORROSION_RATE.value,
            "details": {
                "status": dual_result.status,
                "verdict": dual_result.verdict,
                "cr_out": dual_result.cr_out,
                "cr_er": dual_result.cr_er,
                "cr_inductive": dual_result.cr_inductive,
                "eta": dual_result.eta,
                "delta_d_actual": dual_result.delta_d_actual,
                "diff": dual_result.diff,
                "sensor_T": sensor_data.T,
                "sensor_RH": sensor_data.RH,
            },
            "sensor_id": "",
        }

        if dual_result.status == DualModeStatus.TEMPERATURE_SHOCK:
            alarm["details"]["event"] = "Environment rapid change"
            alarm["details"]["description"] = (
                "Temperature shock detected, ER probe may contain spurious signal. "
                "Inductive probe weighted higher for this cycle."
            )
        elif dual_result.status == DualModeStatus.PITTING_SUSPECTED:
            if dual_result.alarm_level >= 3:
                alarm["details"]["event"] = (
                    "Non-uniform corrosion / Pitting risk"
                    if dual_result.alarm_level == 3
                    else "Severe pitting, perforation risk"
                )
                alarm["details"]["description"] = (
                    f"Pitting factor η={dual_result.eta:.2f} exceeds threshold. "
                    f"Actual max pitting depth estimated at {dual_result.delta_d_actual:.2f} μm."
                )

        alarms.append(alarm)
        return alarms

    def _dispatch_alarm(self, alarm: Dict[str, Any]) -> None:
        try:
            signal = self._app.get_signal("alarm_raised")
            if signal is not None:
                signal.emit(alarm)
                logger.info(
                    "Alarm dispatched: level=%d, type=%s, status=%s",
                    alarm["level"],
                    alarm["alarm_type"],
                    alarm["details"].get("status", "N/A"),
                )
            else:
                logger.warning(
                    "alarm_raised signal not available, alarm not dispatched: %s",
                    alarm.get("details", {}).get("verdict", ""),
                )
        except Exception as e:
            logger.error("Failed to dispatch alarm: %s", e)

    def get_algorithm_engine(self) -> AlgorithmEngine:
        """Get the underlying AlgorithmEngine instance."""
        return self._algorithm_engine

    def get_validator(self) -> DualModeValidator:
        """Get the underlying DualModeValidator instance."""
        return self._validator

    def get_calibration_curve(self) -> Any:
        """Get the CalibrationCurve from the validator."""
        return self._validator.get_calibration_curve()

    def reset(self) -> None:
        """Reset all internal state, history, and statistics."""
        with self._lock:
            self._algorithm_engine.reset_statistics()
            self._validator.reset_history()
            self._T_history.clear()
        logger.info("CrossValidationEngine state reset")
