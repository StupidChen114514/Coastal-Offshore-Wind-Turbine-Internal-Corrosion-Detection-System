"""
Calibration Curve Management for Pitting Factor η = f(δ).

Manages the relationship between discrepancy ratio δ and pitting factor η
used in dual-mode cross-validation for non-uniform corrosion diagnosis.
Supports linear interpolation and polynomial fitting methods.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..core.config_manager import ConfigManager

logger = logging.getLogger(__name__)

DEFAULT_CALIBRATION_POINTS: List[Tuple[float, float]] = [
    (0.00, 1.00),
    (0.05, 1.20),
    (0.10, 1.50),
    (0.15, 2.00),
    (0.20, 2.80),
    (0.25, 3.50),
    (0.30, 4.50),
    (0.35, 6.00),
    (0.40, 8.00),
    (0.45, 10.00),
]

INTERP_LINEAR = "linear"
INTERP_POLYNOMIAL = "polynomial"
POLYNOMIAL_DEGREE = 3


class CalibrationCurve:
    """
    Manages the pitting factor calibration curve η = f(δ).

    Maps the discrepancy ratio δ (relative difference between ER and inductive
    probe penetration depths) to the pitting factor η, which quantifies the
    severity of non-uniform corrosion.

    Supports two interpolation methods:
        - linear: Uses numpy.interp for piecewise linear interpolation
        - polynomial: Uses numpy.polyfit for polynomial curve fitting

    A built-in default calibration curve is provided based on laboratory data.
    Custom calibration data can be imported via import_calibration_data().
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config = config_manager
        self._lock = threading.Lock()

        self._data_points: List[Tuple[float, float]] = list(DEFAULT_CALIBRATION_POINTS)
        self._delta_array: np.ndarray = np.array([], dtype=np.float64)
        self._eta_array: np.ndarray = np.array([], dtype=np.float64)

        self._method: str = INTERP_LINEAR
        self._poly_coeffs: Optional[np.ndarray] = None

        self._calibration_version: str = "default_v1"
        self._calibration_date: datetime = datetime.now(timezone.utc)
        self._custom_imported: bool = False

        self._load_config_method()
        self._rebuild_arrays()

    def _rebuild_arrays(self) -> None:
        if not self._data_points:
            self._delta_array = np.array([], dtype=np.float64)
            self._eta_array = np.array([], dtype=np.float64)
            return

        sorted_points = sorted(self._data_points, key=lambda p: p[0])
        deltas = [p[0] for p in sorted_points]
        etas = [p[1] for p in sorted_points]
        self._delta_array = np.array(deltas, dtype=np.float64)
        self._eta_array = np.array(etas, dtype=np.float64)

        if self._method == INTERP_POLYNOMIAL and len(self._delta_array) >= POLYNOMIAL_DEGREE + 1:
            self._fit_polynomial()

    def _fit_polynomial(self) -> None:
        if len(self._delta_array) < POLYNOMIAL_DEGREE + 1:
            logger.warning(
                "Insufficient data points for polynomial fit (need %d, have %d)",
                POLYNOMIAL_DEGREE + 1, len(self._delta_array),
            )
            self._poly_coeffs = None
            return

        try:
            self._poly_coeffs = np.polyfit(
                self._delta_array, self._eta_array, POLYNOMIAL_DEGREE
            )
            logger.debug("Polynomial fit coefficients: %s", self._poly_coeffs)
        except Exception as e:
            logger.error("Polynomial fit failed: %s", e)
            self._poly_coeffs = None

    def _load_config_method(self) -> None:
        method = self._config.get("algorithm.calibration.curve_method", INTERP_LINEAR)
        if method in (INTERP_LINEAR, INTERP_POLYNOMIAL):
            self._method = method
            if method == INTERP_POLYNOMIAL:
                self._fit_polynomial()

    def get_eta(self, delta: float) -> float:
        """
        Get the pitting factor η for a given discrepancy δ.

        Uses the configured interpolation method to compute η from the
        calibration curve. Values outside the calibrated range are
        extrapolated (linear) or clamped (polynomial).

        Args:
            delta: Discrepancy ratio δ = |Δd_ER - Δd_Inductive| / Δd_ER.

        Returns:
            Pitting factor η. Returns 1.0 if no data points available.
        """
        delta = float(delta)
        delta = max(0.0, delta)

        with self._lock:
            if len(self._delta_array) == 0:
                logger.warning("No calibration data available, returning η=1.0")
                return 1.0

            if delta <= self._delta_array[0]:
                return float(self._eta_array[0])

            if delta >= self._delta_array[-1]:
                if self._method == INTERP_LINEAR:
                    return float(self._eta_array[-1])
                else:
                    return float(self._eta_array[-1])

            if self._method == INTERP_POLYNOMIAL and self._poly_coeffs is not None:
                eta_val = float(np.polyval(self._poly_coeffs, delta))
                return max(1.0, eta_val)
            else:
                eta_val = float(np.interp(delta, self._delta_array, self._eta_array))
                return max(1.0, eta_val)

    def import_calibration_data(
        self, data_points: List[Tuple[float, float]]
    ) -> bool:
        """
        Import custom (δ, η) calibration data pairs.

        Each data point is a (delta_value, eta_value) tuple where:
            - delta_value: Discrepancy ratio (0.0 to 1.0).
            - eta_value: Pitting factor (>= 1.0).

        Args:
            data_points: List of (δ, η) tuples.

        Returns:
            True if import succeeded, False if validation failed.
        """
        if not data_points:
            logger.warning("Import calibration data: empty list provided")
            return False

        for i, (delta_val, eta_val) in enumerate(data_points):
            if not isinstance(delta_val, (int, float)) or not isinstance(eta_val, (int, float)):
                logger.error("Import calibration data: point %d is not numeric", i)
                return False
            if delta_val < 0 or eta_val < 1.0:
                logger.warning(
                    "Import calibration data: point %d (δ=%.3f, η=%.3f) outside valid range",
                    i, delta_val, eta_val,
                )

        with self._lock:
            self._data_points = list(data_points)
            self._custom_imported = True
            self._calibration_date = datetime.now(timezone.utc)
            self._calibration_version = f"custom_{self._calibration_date.strftime('%Y%m%d_%H%M%S')}"
            self._rebuild_arrays()

        logger.info(
            "Calibration data imported: %d points, version=%s",
            len(data_points), self._calibration_version,
        )
        return True

    def get_curve_info(self) -> dict:
        """
        Get metadata about the current calibration curve.

        Returns:
            Dictionary with version, calibration_date, data_points, method,
            and the number of calibration pairs.
        """
        with self._lock:
            return {
                "version": self._calibration_version,
                "calibration_date": self._calibration_date.isoformat(),
                "data_points": len(self._data_points),
                "method": self._method,
                "custom_imported": self._custom_imported,
                "point_count": len(self._data_points),
            }

    def set_interpolation_method(self, method: str) -> None:
        """
        Set the interpolation method.

        Args:
            method: 'linear' or 'polynomial'.
        """
        if method not in (INTERP_LINEAR, INTERP_POLYNOMIAL):
            logger.warning("Unknown interpolation method '%s', using linear", method)
            method = INTERP_LINEAR

        with self._lock:
            self._method = method
            if method == INTERP_POLYNOMIAL:
                self._fit_polynomial()
            else:
                self._poly_coeffs = None

        logger.info("Calibration interpolation method set to: %s", method)

    def reset_to_default(self) -> None:
        """Reset to the built-in default calibration curve."""
        with self._lock:
            self._data_points = list(DEFAULT_CALIBRATION_POINTS)
            self._custom_imported = False
            self._calibration_version = "default_v1"
            self._calibration_date = datetime.now(timezone.utc)
            self._method = INTERP_LINEAR
            self._poly_coeffs = None
            self._rebuild_arrays()

        logger.info("Calibration curve reset to default")
