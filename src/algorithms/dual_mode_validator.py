"""
Dual-Mode Redundant Cross-Validation and Pitting Diagnosis System.

Implements Chapter 7.2 of the technical specification for cross-validating
Electrical Resistance (ER) and Inductive probe measurements to detect
non-uniform corrosion (pitting) and temperature-induced artifacts.

Three scenarios are handled:
    1. Dual-mode verification passed (diff < 0.15)  → uniform corrosion
    2. Temperature shock (diff >= 0.15 AND dT/dt > 2°C/10min)
    3. Pitting risk diagnosis (diff >= 0.15 AND dT/dt <= 2°C/10min)
"""

import logging
import math
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..core.config_manager import ConfigManager
from ..core.data_models import DualModeResult, DualModeStatus
from .calibration_curve import CalibrationCurve

logger = logging.getLogger(__name__)

SECONDS_PER_YEAR = 8760.0 * 3600.0
MINUTES_PER_YEAR = 8760.0 * 60.0

DIFF_THRESHOLD = 0.15
DT_DT_THRESHOLD = 2.0

WEIGHT_ER_CONSISTENT = 0.6
WEIGHT_INDUCTIVE_CONSISTENT = 0.4
WEIGHT_ER_TEMP_SHOCK = 0.2
WEIGHT_INDUCTIVE_TEMP_SHOCK = 0.8

ETA_THRESHOLD_PITTING = 3.0
ETA_THRESHOLD_SEVERE = 5.0

EWMA_ALPHA_DEFAULT = 0.3
MAX_T_HISTORY = 5
DT_DT_WINDOW_MINUTES = 10.0


class DualModeValidator:
    """
    Validates corrosion measurements by cross-checking ER and Inductive probes.

    Every 10-minute cycle, compares the independently measured corrosion rates
    from the two probe types. When rates agree (diff < 15%), outputs a weighted
    average. When rates diverge, diagnoses the cause as either temperature
    shock or non-uniform pitting corrosion.

    Thread-safe for concurrent validation calls.
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config = config_manager
        self._lock = threading.Lock()

        self._calibration_curve = CalibrationCurve(config_manager)

        self._prev_timestamp: Optional[datetime] = None
        self._prev_delta_d_er: Optional[float] = None
        self._prev_delta_d_inductive: Optional[float] = None
        self._prev_cr_er_ewma: Optional[float] = None
        self._prev_cr_inductive_ewma: Optional[float] = None

        self._ewma_alpha: float = EWMA_ALPHA_DEFAULT
        self._load_config()

    def _load_config(self) -> None:
        alpha = self._config.get("algorithm.dual_mode.ewma_alpha", EWMA_ALPHA_DEFAULT)
        try:
            alpha = float(alpha)
            self._ewma_alpha = max(0.01, min(alpha, 1.0))
        except (ValueError, TypeError):
            self._ewma_alpha = EWMA_ALPHA_DEFAULT

    def validate(
        self,
        delta_d_er: float,
        delta_d_inductive: float,
        timestamp: datetime,
        dT_dt: Optional[float] = None,
        T_history: Optional[List[Tuple[datetime, float]]] = None,
    ) -> DualModeResult:
        """
        Perform dual-mode cross-validation on the latest probe readings.

        Args:
            delta_d_er: Latest ER probe corrosion depth in μm.
            delta_d_inductive: Latest inductive probe corrosion depth in μm.
            timestamp: Current UTC timestamp.
            dT_dt: Temperature change rate in °C per 10 minutes. If None,
                   auto-calculated from T_history.
            T_history: List of (timestamp, temperature) tuples for dT/dt
                       calculation. Used only when dT_dt is None.

        Returns:
            DualModeResult with the validated corrosion rate, pitting factor,
            status, and alarm information.
        """
        delta_d_er = float(delta_d_er)
        delta_d_inductive = float(delta_d_inductive)
        delta_d_er = max(0.0, delta_d_er)
        delta_d_inductive = max(0.0, delta_d_inductive)

        with self._lock:
            cr_er = self._compute_cr(
                delta_d_er, timestamp, is_er=True
            )
            cr_inductive = self._compute_cr(
                delta_d_inductive, timestamp, is_er=False
            )

            self._prev_delta_d_er = delta_d_er
            self._prev_delta_d_inductive = delta_d_inductive
            self._prev_timestamp = timestamp

        if dT_dt is None:
            dT_dt = self._calculate_dT_dt(T_history)

        diff = self._compute_diff(cr_er, cr_inductive)

        logger.info(
            "Dual-mode validation: CR_ER=%.4f, CR_Inductive=%.4f, "
            "diff=%.4f, dT/dt=%.4f °C/10min",
            cr_er, cr_inductive, diff, dT_dt,
        )

        result = self._classify_scenario(
            cr_er=cr_er,
            cr_inductive=cr_inductive,
            delta_d_er=delta_d_er,
            delta_d_inductive=delta_d_inductive,
            diff=diff,
            dT_dt=dT_dt,
            timestamp=timestamp,
        )

        logger.info(
            "Dual-mode result: status=%s, alarm_level=%d, CR_out=%.4f, "
            "η=%.3f, verdict=%s",
            result.status, result.alarm_level, result.cr_out,
            result.eta, result.verdict,
        )

        return result

    def _compute_cr(
        self, delta_d: float, timestamp: datetime, is_er: bool
    ) -> float:
        prev_delta_d = (
            self._prev_delta_d_er if is_er else self._prev_delta_d_inductive
        )

        if prev_delta_d is None or self._prev_timestamp is None:
            return 0.0

        dt_seconds = (timestamp - self._prev_timestamp).total_seconds()
        if dt_seconds <= 0:
            return 0.0

        dd = delta_d - prev_delta_d
        if dd < 0:
            dd = 0.0

        cr_instant = (dd / dt_seconds) * SECONDS_PER_YEAR

        prev_ewma = (
            self._prev_cr_er_ewma if is_er else self._prev_cr_inductive_ewma
        )

        if prev_ewma is not None and prev_ewma > 0:
            cr_smooth = self._ewma_alpha * cr_instant + (1.0 - self._ewma_alpha) * prev_ewma
        else:
            cr_smooth = cr_instant

        if is_er:
            self._prev_cr_er_ewma = cr_smooth
        else:
            self._prev_cr_inductive_ewma = cr_smooth

        return cr_smooth

    def _compute_diff(self, cr_er: float, cr_inductive: float) -> float:
        numerator = abs(cr_er - cr_inductive)
        denominator = (cr_er + cr_inductive) / 2.0

        if denominator < 1e-9:
            return 0.0

        return numerator / denominator

    def _calculate_dT_dt(
        self, T_history: Optional[List[Tuple[datetime, float]]]
    ) -> float:
        if not T_history or len(T_history) < 2:
            return 0.0

        sorted_history = sorted(T_history, key=lambda x: x[0])
        first_ts, first_T = sorted_history[0]
        last_ts, last_T = sorted_history[-1]

        dt_minutes = (last_ts - first_ts).total_seconds() / 60.0
        if dt_minutes <= 0:
            return 0.0

        dT_per_10min = (last_T - first_T) / dt_minutes * 10.0
        return dT_per_10min

    def _compute_delta(self, delta_d_er: float, delta_d_inductive: float) -> Optional[float]:
        if delta_d_er <= 1e-9:
            logger.warning(
                "Δd_ER=%.6f μm is too small, cannot compute discrepancy δ",
                delta_d_er,
            )
            return None

        delta = abs(delta_d_er - delta_d_inductive) / delta_d_er
        return delta

    def _classify_scenario(
        self,
        cr_er: float,
        cr_inductive: float,
        delta_d_er: float,
        delta_d_inductive: float,
        diff: float,
        dT_dt: float,
        timestamp: datetime,
    ) -> DualModeResult:
        abs_dT_dt = abs(dT_dt)

        if diff < DIFF_THRESHOLD:
            return self._scenario_consistent(
                cr_er, cr_inductive, diff, timestamp
            )

        if abs_dT_dt > DT_DT_THRESHOLD:
            return self._scenario_temperature_shock(
                cr_er, cr_inductive, diff, dT_dt, timestamp
            )

        return self._scenario_pitting_risk(
            cr_er, cr_inductive, delta_d_er, delta_d_inductive, diff, timestamp
        )

    def _scenario_consistent(
        self, cr_er: float, cr_inductive: float, diff: float, timestamp: datetime
    ) -> DualModeResult:
        cr_out = WEIGHT_ER_CONSISTENT * cr_er + WEIGHT_INDUCTIVE_CONSISTENT * cr_inductive

        return DualModeResult(
            cr_out=cr_out,
            cr_er=cr_er,
            cr_inductive=cr_inductive,
            eta=1.0,
            delta_d_actual=0.0,
            status=DualModeStatus.DUAL_CONSISTENT,
            alarm_level=0,
            verdict="Dual-mode consistent: uniform corrosion, rates agree within threshold",
            diff=diff,
            timestamp=timestamp,
        )

    def _scenario_temperature_shock(
        self,
        cr_er: float,
        cr_inductive: float,
        diff: float,
        dT_dt: float,
        timestamp: datetime,
    ) -> DualModeResult:
        cr_out = WEIGHT_ER_TEMP_SHOCK * cr_er + WEIGHT_INDUCTIVE_TEMP_SHOCK * cr_inductive

        return DualModeResult(
            cr_out=cr_out,
            cr_er=cr_er,
            cr_inductive=cr_inductive,
            eta=1.0,
            delta_d_actual=0.0,
            status=DualModeStatus.TEMPERATURE_SHOCK,
            alarm_level=1,
            verdict=(
                f"Temperature shock detected (dT/dt={dT_dt:.2f}°C/10min): "
                "ER probe may contain spurious signal, inductive probe weighted higher"
            ),
            diff=diff,
            timestamp=timestamp,
        )

    def _scenario_pitting_risk(
        self,
        cr_er: float,
        cr_inductive: float,
        delta_d_er: float,
        delta_d_inductive: float,
        diff: float,
        timestamp: datetime,
    ) -> DualModeResult:
        delta = self._compute_delta(delta_d_er, delta_d_inductive)

        if delta is None:
            return DualModeResult(
                cr_out=cr_er,
                cr_er=cr_er,
                cr_inductive=cr_inductive,
                eta=1.0,
                delta_d_actual=delta_d_er,
                status=DualModeStatus.PITTING_SUSPECTED,
                alarm_level=1,
                verdict=(
                    "Pitting diagnosis skipped: Δd_ER too small to compute discrepancy δ. "
                    "Falling back to ER-only rate."
                ),
                diff=diff,
                timestamp=timestamp,
            )

        eta = self._calibration_curve.get_eta(delta)
        delta_d_actual = eta * delta_d_er

        alarm_level = 0
        verdict = (
            f"Dual-mode divergence (diff={diff:.4f}): non-uniform corrosion suspected. "
            f"η={eta:.2f}, Δd_actual={delta_d_actual:.2f} μm"
        )

        if eta > ETA_THRESHOLD_SEVERE:
            alarm_level = 4
            verdict = (
                f"SEVERE PITTING - PERFORATION RISK! η={eta:.2f} > {ETA_THRESHOLD_SEVERE}, "
                f"Δd_actual={delta_d_actual:.2f} μm. Immediate inspection required."
            )
            logger.warning(verdict)
        elif eta > ETA_THRESHOLD_PITTING:
            alarm_level = 3
            verdict = (
                f"Non-uniform corrosion / Pitting risk: η={eta:.2f} > {ETA_THRESHOLD_PITTING}, "
                f"Δd_actual={delta_d_actual:.2f} μm. Schedule inspection."
            )
            logger.warning(verdict)
        else:
            alarm_level = 0
            logger.info(
                "Pitting suspected but η=%.2f below warning thresholds", eta
            )

        return DualModeResult(
            cr_out=cr_er,
            cr_er=cr_er,
            cr_inductive=cr_inductive,
            eta=eta,
            delta_d_actual=delta_d_actual,
            status=DualModeStatus.PITTING_SUSPECTED,
            alarm_level=alarm_level,
            verdict=verdict,
            diff=diff,
            timestamp=timestamp,
        )

    def get_calibration_curve(self) -> CalibrationCurve:
        """Get the CalibrationCurve instance used by this validator."""
        return self._calibration_curve

    def reset_history(self) -> None:
        """Reset all internal rate history and tracking state."""
        with self._lock:
            self._prev_timestamp = None
            self._prev_delta_d_er = None
            self._prev_delta_d_inductive = None
            self._prev_cr_er_ewma = None
            self._prev_cr_inductive_ewma = None
        logger.info("DualModeValidator history reset")
