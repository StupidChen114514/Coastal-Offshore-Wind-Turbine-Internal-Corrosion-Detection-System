"""
Adaptive Kalman Filter for corrosion depth and rate estimation.

Implements a 2-state linear Kalman filter with adaptive process noise
covariance that responds to environmental fluctuation levels (dT/dt, dRH/dt).
Uses the Joseph form for numerically stable covariance updates.

State vector:
    x = [Δd, CR]^T
    Δd: corrosion depth loss (μm)
    CR: corrosion rate (μm/year)

State transition (constant rate model):
    F = [[1, dt], [0, 1]]
    dt: sampling interval in years

Measurement:
    H = [[1, 0]]
    We directly measure Δd
"""

import logging
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

MIN_WARMUP_SAMPLES = 36
HOURS_PER_YEAR = 8760.0


class KalmanFilter:
    """
    Adaptive 2-state Kalman filter for corrosion monitoring.

    Tracks corrosion depth (Δd) and corrosion rate (CR) using a
    constant-rate process model with environmentally-adaptive
    process noise covariance.
    """

    def __init__(
        self,
        measurement_noise_var: float = 1.0,
        base_process_noise: float = 0.01,
    ) -> None:
        """
        Initialize the Kalman filter.

        Args:
            measurement_noise_var: Measurement noise variance (σ_n²),
                typically derived from 24h initial calibration.
            base_process_noise: Base process noise for the rate state.
        """
        self._R = np.array([[measurement_noise_var]], dtype=np.float64)

        self._Q_base = np.array(
            [[0.0, 0.0], [0.0, base_process_noise]],
            dtype=np.float64,
        )

        self._x = np.array([[0.0], [0.0]], dtype=np.float64)

        self._P = np.array(
            [[1e6, 0.0], [0.0, 1e4]],
            dtype=np.float64,
        )

        self._F = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float64)
        self._H = np.array([[1.0, 0.0]], dtype=np.float64)

        self._I = np.eye(2, dtype=np.float64)

        self._dt_years: float = 0.0
        self._sample_count: int = 0
        self._warmed_up: bool = False

        self._prev_T: Optional[float] = None
        self._prev_RH: Optional[float] = None
        self._prev_timestamp: Optional[float] = None

    @property
    def is_warmed_up(self) -> bool:
        """Check if the filter has accumulated sufficient warm-up data."""
        return self._warmed_up

    @property
    def sample_count(self) -> int:
        """Return the number of samples processed."""
        return self._sample_count

    def predict(
        self,
        dt_seconds: float,
        dT_dt: float = 0.0,
        dRH_dt: float = 0.0,
    ) -> np.ndarray:
        """
        Perform the Kalman prediction step.

        Updates the state transition matrix F based on dt and computes
        adaptive process noise Q based on environmental fluctuation.

        Args:
            dt_seconds: Time since last update in seconds.
            dT_dt: Rate of temperature change (°C/s).
            dRH_dt: Rate of humidity change (%/s).

        Returns:
            Predicted state vector x (2×1).
        """
        dt_seconds = max(dt_seconds, 0.0)
        self._dt_years = dt_seconds / (HOURS_PER_YEAR * 3600.0)
        self._dt_years = max(self._dt_years, 1e-9)

        dt = self._dt_years
        self._F = np.array([[1.0, dt], [0.0, 1.0]], dtype=np.float64)

        env_scale = 1.0 + abs(dT_dt) / 10.0 + abs(dRH_dt) / 50.0
        env_scale = max(1.0, min(env_scale, 100.0))

        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt3 * dt

        q_rate = self._Q_base[1, 1] * env_scale
        G = np.array(
            [[dt3 / 3.0, dt2 / 2.0], [dt2 / 2.0, dt]],
            dtype=np.float64,
        )
        Q = G * q_rate

        self._x = self._F @ self._x
        self._P = self._F @ self._P @ self._F.T + Q

        self._P = 0.5 * (self._P + self._P.T)

        logger.debug(
            "Kalman predict: dt=%.3e yr, env_scale=%.2f, x=[%.4f, %.4f]",
            dt, env_scale, self._x[0, 0], self._x[1, 0],
        )

        return self._x.copy()

    def update(self, measurement: float) -> np.ndarray:
        """
        Perform the Kalman update (correction) step using Joseph form.

        Joseph form:
            K = P·H^T·(H·P·H^T + R)^{-1}
            x = x + K·(z - H·x)
            P = (I - K·H)·P·(I - K·H)^T + K·R·K^T

        Args:
            measurement: Measured corrosion depth Δd in μm.

        Returns:
            Updated state vector x (2×1).
        """
        self._sample_count += 1

        z = np.array([[float(measurement)]], dtype=np.float64)

        y = z - self._H @ self._x

        S = self._H @ self._P @ self._H.T + self._R

        if S[0, 0] <= 0:
            logger.warning("Kalman update: Innovation covariance ≤ 0, skipping update")
            return self._x.copy()

        K = self._P @ self._H.T / S[0, 0]

        self._x = self._x + K * y[0, 0]

        I_KH = self._I - K @ self._H
        self._P = I_KH @ self._P @ I_KH.T + K @ self._R @ K.T

        self._P = 0.5 * (self._P + self._P.T)

        if self._sample_count >= MIN_WARMUP_SAMPLES and not self._warmed_up:
            self._warmed_up = True
            logger.info("Kalman filter warm-up complete (%d samples)", self._sample_count)

        logger.debug(
            "Kalman update: z=%.4f, y=%.4f, x=[%.4f, %.4f]",
            measurement, y[0, 0], self._x[0, 0], self._x[1, 0],
        )

        return self._x.copy()

    def get_state(self) -> Tuple[float, float]:
        """
        Get the current estimated state.

        Returns:
            Tuple of (delta_d_filtered, CR_filtered):
                - delta_d_filtered: Filtered corrosion depth in μm.
                - CR_filtered: Filtered corrosion rate in μm/year.
        """
        delta_d = max(0.0, float(self._x[0, 0]))
        cr = float(self._x[1, 0])

        if self._dt_years > 1e-9 and self._warmed_up:
            if cr < 0 and delta_d > 1e-6:
                cr = max(cr, 0.0)

        return delta_d, cr

    def get_covariance(self) -> np.ndarray:
        """
        Get the current state covariance matrix.

        Returns:
            2×2 covariance matrix P.
        """
        return self._P.copy()

    def set_measurement_noise(self, variance: float) -> None:
        """
        Update measurement noise covariance R.

        Args:
            variance: New measurement noise variance.
        """
        if variance > 0:
            self._R = np.array([[variance]], dtype=np.float64)

    def reset(self) -> None:
        """Reset filter to initial state."""
        self._x = np.array([[0.0], [0.0]], dtype=np.float64)
        self._P = np.array(
            [[1e6, 0.0], [0.0, 1e4]],
            dtype=np.float64,
        )
        self._sample_count = 0
        self._warmed_up = False
        self._prev_T = None
        self._prev_RH = None
        self._prev_timestamp = None
        logger.debug("Kalman filter reset")
