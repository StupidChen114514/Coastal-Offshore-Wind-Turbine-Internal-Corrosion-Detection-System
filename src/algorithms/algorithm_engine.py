"""
Four-Level Error Compensation Algorithm Engine.

Implements the complete error compensation pipeline for coastal offshore
wind turbine corrosion detection sensors. The four levels are:

    Level 1  - Hardware Differential Compensation
    Level 2  - Ratio Method Self-Calibration
    Level 3A - Residual Temperature Coefficient Polynomial Correction
    Level 3B - Humidity Gating Data Validity Filter
    Level 3C - Environmental Factor Corrected Corrosion Rate
    Level 3D - Dose-Response Function Environmental Prediction
    Level 4  - Adaptive Kalman Filter
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..core.config_manager import ConfigManager
from ..core.data_models import CorrosionRecord, SensorData
from ..core.logger import CorrosionLogger
from .dose_response import (
    VERDICT_ABNORMAL_ACCELERATION,
    VERDICT_COATING_EFFECTIVE,
    VERDICT_NORMAL,
    cross_validate,
    predict_corrosion_rate,
)
from .kalman_filter import KalmanFilter, MIN_WARMUP_SAMPLES
from .tow_calculator import TOWCalculator

logger = logging.getLogger(__name__)

HOURS_PER_YEAR = 8760.0
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_YEAR = HOURS_PER_YEAR * SECONDS_PER_HOUR

DEFAULT_D0 = 100.0
DEFAULT_T0 = 25.0
DEFAULT_ALPHA_RES = 0.0
DEFAULT_BETA_RES = 0.0
DEFAULT_RH_CRIT = 76.0
DEFAULT_EPSILON_MULTIPLIER = 3.0
DEFAULT_K_S = 0.01
DEFAULT_TOW_REF = 4000.0
DEFAULT_V_REF_FLUCTUATION_THRESHOLD = 0.001

MAX_CONSECUTIVE_INVALID = 10
RS_RR_MIN = 0.5
RS_RR_MAX = 2.0


class AlgorithmEngine:
    """
    Four-level error compensation algorithm engine.

    Processes raw sensor data through a sequential compensation pipeline:
    hardware differential correction → current source calibration → temperature
    polynomial correction → humidity gating → environmental normalization →
    dose-response prediction → Kalman filtering.

    Each level logs its correction values at DEBUG level for traceability.
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        """
        Initialize the algorithm engine.

        Args:
            config_manager: System ConfigManager for parameter retrieval.
        """
        self._config = config_manager
        self._initialized = False

        self._d0: float = DEFAULT_D0
        self._T0: float = DEFAULT_T0
        self._alpha_res: float = DEFAULT_ALPHA_RES
        self._beta_res: float = DEFAULT_BETA_RES
        self._RH_crit: float = DEFAULT_RH_CRIT
        self._epsilon_multiplier: float = DEFAULT_EPSILON_MULTIPLIER
        self._k_S: float = DEFAULT_K_S
        self._TOW_ref: float = DEFAULT_TOW_REF

        self._sigma_n: float = 0.0
        self._epsilon_noise: float = 0.0

        self._tow_calculator = TOWCalculator()
        self._kalman_filter = KalmanFilter()

        self._consecutive_invalid: int = 0
        self._v_ref_buffer: List[float] = []
        self._max_v_ref_buffer: int = 20

        self._prev_timestamp: Optional[datetime] = None
        self._prev_delta_d: Optional[float] = None
        self._prev_T: Optional[float] = None
        self._prev_RH: Optional[float] = None

        self._running_T_sum: float = 0.0
        self._running_RH_sum: float = 0.0
        self._running_Cl_sum: float = 0.0
        self._running_count: int = 0

        self._last_hour_bucket: Optional[int] = None

        self._corrosion_logger: Optional[CorrosionLogger] = None

    def initialize(self) -> bool:
        """
        Initialize the engine with configuration parameters.

        Loads all configurable parameters from the ConfigManager and
        sets up the Kalman filter with default noise values.

        Returns:
            True if initialization succeeded.
        """
        logger.info("Initializing Four-Level Algorithm Engine")

        try:
            self._d0 = float(self._config.get("sensor.d0.value", DEFAULT_D0))
            self._T0 = float(self._config.get("algorithm.T0_ref.value", DEFAULT_T0))
            self._alpha_res = float(self._config.get("algorithm.alpha_res.value", DEFAULT_ALPHA_RES))
            self._beta_res = float(self._config.get("algorithm.beta_res.value", DEFAULT_BETA_RES))
            self._RH_crit = float(self._config.get("algorithm.RH_crit.value", DEFAULT_RH_CRIT))
            self._epsilon_multiplier = float(
                self._config.get("algorithm.epsilon_noise_multiplier.value", DEFAULT_EPSILON_MULTIPLIER)
            )
            self._k_S = float(self._config.get("algorithm.k_S.value", DEFAULT_K_S))
            self._TOW_ref = float(self._config.get("algorithm.TOW_ref.value", DEFAULT_TOW_REF))
        except (ValueError, TypeError) as e:
            logger.error("Invalid configuration value: %s", e)
            return False

        if self._sigma_n <= 0:
            self._sigma_n = 0.0
            self._epsilon_noise = 0.0
            self._kalman_filter.set_measurement_noise(0.01)
        else:
            self._epsilon_noise = self._epsilon_multiplier * self._sigma_n
            self._kalman_filter.set_measurement_noise(self._sigma_n * self._sigma_n)

        self._initialized = True

        logger.info(
            "Algorithm engine initialized: d0=%.1f μm, T0=%.1f°C, α=%.6f, β=%.6f, "
            "RH_crit=%.1f%%, ε_mult=%.1f, k_S=%.3f, TOW_ref=%.1f h/yr",
            self._d0, self._T0, self._alpha_res, self._beta_res,
            self._RH_crit, self._epsilon_multiplier, self._k_S, self._TOW_ref,
        )

        return True

    def _push_v_ref(self, V_ref: float) -> None:
        """Store a V_ref reading in the rolling buffer."""
        self._v_ref_buffer.append(float(V_ref))
        if len(self._v_ref_buffer) > self._max_v_ref_buffer:
            self._v_ref_buffer.pop(0)

    def _get_v_ref_fluctuation(self) -> float:
        """
        Compute the short-term V_ref fluctuation rate.

        Returns:
            Maximum relative deviation from the buffer mean, or 0.0 if
            insufficient data.
        """
        if len(self._v_ref_buffer) < 2:
            return 0.0

        arr = np.array(self._v_ref_buffer, dtype=np.float64)
        mean_val = float(np.mean(arr))
        if mean_val <= 1e-9:
            return 0.0

        max_dev = float(np.max(np.abs(arr - mean_val)))
        return max_dev / mean_val

    def _accumulate_environmental_stats(self, T: float, RH: float, Cl: float) -> None:
        """Accumulate running averages for dose-response prediction."""
        self._running_T_sum += T
        self._running_RH_sum += RH
        self._running_Cl_sum += Cl
        self._running_count += 1

    def _get_environmental_averages(self) -> Tuple[float, float, float]:
        """Return running averages of T, RH, Cl."""
        if self._running_count == 0:
            return 0.0, 0.0, 0.0
        n = float(self._running_count)
        return self._running_T_sum / n, self._running_RH_sum / n, self._running_Cl_sum / n

    def process_sensor_data(self, sensor_data: SensorData) -> Optional[CorrosionRecord]:
        """
        Process raw sensor data through the full four-level compensation pipeline.

        Args:
            sensor_data: Raw sensor reading from acquisition system.

        Returns:
            CorrosionRecord with compensated and filtered values, or None
            if the engine is not initialized.
        """
        if not self._initialized:
            logger.warning("Algorithm engine not initialized, cannot process data")
            return None

        logger.debug(
            "Processing sensor data at %s: T=%.2f, RH=%.2f, V_mid=%.6f, V_diff=%.6f",
            sensor_data.timestamp.isoformat(),
            sensor_data.T,
            sensor_data.RH,
            sensor_data.V_mid,
            sensor_data.V_diff,
        )

        self._push_v_ref(sensor_data.V_mid)

        self.update_tow_statistics(sensor_data.T, sensor_data.RH)
        self._accumulate_environmental_stats(
            sensor_data.T, sensor_data.RH, sensor_data.Cl_deposition
        )

        delta_d_raw, status_l1 = self._compensate_level1_hardware_diff(
            sensor_data.V_mid, sensor_data.V_diff, self._d0
        )
        logger.debug("Level 1: Δd_raw=%.4f μm, status=%s", delta_d_raw, status_l1)

        status_l2 = self._verify_level2_ratio_calibration()
        logger.debug("Level 2: status=%s", status_l2)

        delta_d_corrected = self._compensate_level3a_temperature(
            delta_d_raw, sensor_data.T, self._alpha_res, self._beta_res, self._T0
        )
        logger.debug("Level 3A: Δd_corrected=%.4f μm", delta_d_corrected)

        valid_flag, status_l3b = self._filter_level3b_humidity_gate(
            delta_d_raw,
            sensor_data.RH,
            self._epsilon_noise,
            self._consecutive_invalid,
        )
        if not valid_flag:
            self._consecutive_invalid += 1
        else:
            self._consecutive_invalid = 0
        logger.debug(
            "Level 3B: valid=%s, consecutive_invalid=%d, status=%s",
            valid_flag, self._consecutive_invalid, status_l3b,
        )

        cr_raw = self._compute_corrosion_rate(delta_d_raw, sensor_data.timestamp)

        tow_actual = self._tow_calculator.get_annual_tow()
        cr_normalized = self._correct_level3c_environment(
            cr_raw, tow_actual, self._TOW_ref, self._k_S, sensor_data.Cl_deposition
        )
        logger.debug("Level 3C: CR_raw=%.4f, CR_normalized=%.4f μm/year", cr_raw, cr_normalized)

        T_avg, RH_avg, Cl_avg = self._get_environmental_averages()
        r_pred, verdict_3d, alarm_3d = self._predict_level3d_dose_response(
            T_avg, RH_avg, Cl_avg, cr_normalized
        )
        logger.debug(
            "Level 3D: r_pred=%.4f μm/year, verdict=%s, alarm=%d",
            r_pred, verdict_3d, alarm_3d,
        )

        cr_input = cr_normalized if valid_flag else cr_raw

        delta_d_filtered = self._filter_level4_kalman(
            delta_d_corrected if valid_flag else delta_d_raw,
            sensor_data.timestamp,
            sensor_data.T,
            sensor_data.RH,
        )

        kalman_state = self._kalman_filter.get_state()
        cr_filtered = kalman_state[1]
        delta_d_kalman = kalman_state[0]

        if not valid_flag:
            cr_filtered = 0.0

        status_parts = []
        if status_l1 != "OK":
            status_parts.append(f"L1:{status_l1}")
        if status_l2 != "OK":
            status_parts.append(f"L2:{status_l2}")
        if status_l3b != "OK":
            status_parts.append(f"L3B:{status_l3b}")
        if verdict_3d != VERDICT_NORMAL:
            status_parts.append(f"L3D:{verdict_3d}")

        combined_status = "; ".join(status_parts) if status_parts else "OK"

        record = CorrosionRecord(
            timestamp=sensor_data.timestamp,
            delta_d_raw=delta_d_raw,
            delta_d_corrected=delta_d_corrected,
            delta_d_filtered=delta_d_kalman,
            CR_ER=cr_normalized,
            CR_Inductive=0.0,
            CR_out=cr_filtered,
            eta=r_pred if math.isfinite(r_pred) else 0.0,
            valid_flag=valid_flag,
            status=combined_status,
        )

        self._prev_timestamp = sensor_data.timestamp
        self._prev_delta_d = delta_d_corrected
        self._prev_T = sensor_data.T
        self._prev_RH = sensor_data.RH

        logger.debug(
            "Processing complete: raw=%.4f, corrected=%.4f, filtered=%.4f, "
            "CR=%.4f μm/year, valid=%s, status=%s",
            delta_d_raw, delta_d_corrected, delta_d_kalman,
            cr_filtered, valid_flag, combined_status,
        )

        return record

    def _compute_corrosion_rate(
        self, delta_d: float, current_timestamp: datetime
    ) -> float:
        """
        Compute instantaneous corrosion rate from Δd and time difference.

        Args:
            delta_d: Current thickness loss in μm.
            current_timestamp: Timestamp of the current reading.

        Returns:
            Corrosion rate in μm/year. Returns 0 if previous data not available.
        """
        if self._prev_delta_d is None or self._prev_timestamp is None:
            return 0.0

        dt_seconds = (current_timestamp - self._prev_timestamp).total_seconds()
        if dt_seconds <= 0:
            return 0.0

        dd = delta_d - self._prev_delta_d
        if dd < 0:
            dd = 0.0

        cr = (dd / dt_seconds) * SECONDS_PER_YEAR
        return cr

    def _compensate_level1_hardware_diff(
        self, V_mid: float, V_diff: float, d0: float
    ) -> Tuple[float, str]:
        """
        Level 1: Hardware differential compensation.

        Equation (12): Rs/Rr = 1 + V_diff / V_mid
        Equation (8):  Δd_raw = d₀ × (1 - Rr/Rs)

        Validates that the Rs/Rr ratio falls within the physical range [0.5, 2.0].

        Args:
            V_mid: Midpoint voltage of the bridge circuit (V_ref equivalent).
            V_diff: Differential voltage.
            d0: Initial electrode thickness in μm.

        Returns:
            Tuple of (Δd_raw in μm, status string).
        """
        V_mid = float(V_mid)
        V_diff = float(V_diff)
        d0 = float(d0)

        if d0 <= 0:
            logger.warning("Level 1: Invalid d0=%.2f, using 100 μm default", d0)
            d0 = DEFAULT_D0

        if abs(V_mid) < 1e-9:
            logger.warning("Level 1: V_mid ≈ 0, cannot compute Rs/Rr ratio")
            return 0.0, "V_mid_zero"

        rs_rr = 1.0 + V_diff / V_mid

        if not (RS_RR_MIN <= rs_rr <= RS_RR_MAX):
            logger.warning(
                "Level 1: Rs/Rr=%.4f outside physical range [%.1f, %.1f]",
                rs_rr, RS_RR_MIN, RS_RR_MAX,
            )
            rs_rr = max(RS_RR_MIN, min(RS_RR_MAX, rs_rr))
            status = "RsRr_clamped"
        else:
            status = "OK"

        if abs(rs_rr) < 1e-9:
            logger.warning("Level 1: Rs/Rr ≈ 0, returning Δd_raw = d0")
            return d0, "division_by_zero"

        rr_rs = 1.0 / rs_rr
        delta_d_raw = d0 * (1.0 - rr_rs)
        delta_d_raw = max(0.0, min(delta_d_raw, d0))

        logger.debug(
            "Level 1: V_mid=%.6f V, V_diff=%.6f V → Rs/Rr=%.4f → Δd_raw=%.4f μm",
            V_mid, V_diff, rs_rr, delta_d_raw,
        )

        return delta_d_raw, status

    def _verify_level2_ratio_calibration(self) -> str:
        """
        Level 2: Ratio method self-calibration.

        Monitors short-term V_ref fluctuation. If the fluctuation exceeds
        0.1%, flags a current source stability anomaly.

        Returns:
            Status string: "OK" or "Current source short-term stability anomaly".
        """
        fluctuation = self._get_v_ref_fluctuation()

        if fluctuation > DEFAULT_V_REF_FLUCTUATION_THRESHOLD:
            logger.warning(
                "Level 2: V_ref fluctuation rate %.4f%% exceeds %.2f%% threshold",
                fluctuation * 100.0, DEFAULT_V_REF_FLUCTUATION_THRESHOLD * 100.0,
            )
            return "Current source short-term stability anomaly"

        return "OK"

    def _compensate_level3a_temperature(
        self,
        delta_d_raw: float,
        T: float,
        alpha_res: float,
        beta_res: float,
        T0: float,
    ) -> float:
        """
        Level 3A: Residual temperature coefficient polynomial correction.

        Equation (21):
            Δd_corrected = Δd_raw / [1 + α_res × (T - T₀) + β_res × (T - T₀)²]

        If both α_res and β_res are 0, returns Δd_raw unchanged.

        Args:
            delta_d_raw: Raw thickness loss from Level 1 in μm.
            T: Current temperature in °C.
            alpha_res: Linear residual temperature coefficient.
            beta_res: Quadratic residual temperature coefficient.
            T0: Reference temperature (default 25°C).

        Returns:
            Temperature-corrected Δd in μm.
        """
        delta_d_raw = float(delta_d_raw)
        T = float(T)
        alpha_res = float(alpha_res)
        beta_res = float(beta_res)
        T0 = float(T0)

        if delta_d_raw <= 0:
            return 0.0

        if alpha_res == 0.0 and beta_res == 0.0:
            return delta_d_raw

        dT = T - T0
        denominator = 1.0 + alpha_res * dT + beta_res * dT * dT

        if abs(denominator) < 1e-9:
            logger.warning(
                "Level 3A: Denominator ≈ 0 (α=%.6f, β=%.6f, dT=%.2f), returning raw value",
                alpha_res, beta_res, dT,
            )
            return delta_d_raw

        delta_d_corrected = delta_d_raw / denominator
        delta_d_corrected = max(0.0, delta_d_corrected)

        logger.debug(
            "Level 3A: Δd_raw=%.4f, T=%.2f, dT=%.2f → Δd_corrected=%.4f μm",
            delta_d_raw, T, dT, delta_d_corrected,
        )

        return delta_d_corrected

    def _filter_level3b_humidity_gate(
        self,
        delta_d_raw: float,
        RH: float,
        epsilon_noise: float,
        consecutive_invalid: int,
    ) -> Tuple[bool, str]:
        """
        Level 3B: Humidity gating data validity filter.

        NaCl deliquescence threshold at 76% RH:
            - If RH < 76% AND Δd_raw ≥ ε_noise → invalid (noise-only signal)
            - Otherwise → valid

        Equation (22):
            ValidFlag = 1 if (RH >= RH_crit OR Δd_raw < ε_noise) else 0

        If 10 consecutive invalid readings, triggers probe/circuit anomaly alarm.

        Args:
            delta_d_raw: Thickness loss in μm.
            RH: Relative humidity in %.
            epsilon_noise: Noise threshold (3 × σ_n).
            consecutive_invalid: Running count of consecutive invalid readings.

        Returns:
            Tuple of (valid_flag, status_string).
        """
        delta_d_raw = float(delta_d_raw)
        RH = float(RH)

        if epsilon_noise <= 0:
            return True, "OK"

        if RH >= self._RH_crit or abs(delta_d_raw) < epsilon_noise:
            return True, "OK"

        if consecutive_invalid + 1 >= MAX_CONSECUTIVE_INVALID:
            logger.error(
                "Level 3B: %d consecutive invalid readings → Probe/Circuit anomaly alarm",
                consecutive_invalid + 1,
            )
            return False, "Probe/Circuit anomaly"

        return False, "Below RH threshold with signal above noise"

    def _correct_level3c_environment(
        self,
        CR_raw: float,
        TOW_actual: float,
        TOW_ref: float,
        k_S: float,
        S_Cl: float,
    ) -> float:
        """
        Level 3C: Environmental factor corrected corrosion rate.

        Equation (23):
            CR_normalized = CR_raw × (TOW_ref / TOW_actual) × 1/(1 + k_S × S_Cl⁻)

        If TOW_actual is 0 (insufficient data), returns CR_raw unchanged.

        Args:
            CR_raw: Raw corrosion rate in μm/year.
            TOW_actual: Actual/projected time of wetness in hours/year.
            TOW_ref: Reference time of wetness (default 4000 h/year).
            k_S: Chloride sensitivity coefficient (default 0.01 m²·day/mg).
            S_Cl: Chloride deposition rate in mg/m²/day.

        Returns:
            Environmental-factor-normalized corrosion rate in μm/year.
        """
        CR_raw = float(CR_raw)
        TOW_actual = float(TOW_actual)
        TOW_ref = float(TOW_ref)
        k_S = float(k_S)
        S_Cl = float(S_Cl)

        if CR_raw <= 0:
            return 0.0

        if TOW_actual <= 0 or TOW_ref <= 0:
            return CR_raw

        tow_factor = TOW_ref / TOW_actual
        tow_factor = max(0.1, min(tow_factor, 10.0))

        chloride_factor = 1.0 / (1.0 + k_S * max(0.0, S_Cl))

        CR_normalized = CR_raw * tow_factor * chloride_factor
        CR_normalized = max(0.0, CR_normalized)

        logger.debug(
            "Level 3C: CR_raw=%.4f, TOW=%.1f/%.1f, Cl=%.3f → CR_norm=%.4f μm/year",
            CR_raw, TOW_actual, TOW_ref, S_Cl, CR_normalized,
        )

        return CR_normalized

    def _predict_level3d_dose_response(
        self, T_avg: float, RH_avg: float, Cl_avg: float, r_meas: float
    ) -> Tuple[float, str, int]:
        """
        Level 3D: Dose-response function environmental prediction.

        Uses Equation (25) to predict corrosion rate and cross-validates
        against the measured rate.

        Args:
            T_avg: Average temperature in °C.
            RH_avg: Average relative humidity in %.
            Cl_avg: Average chloride deposition in mg/m²/day.
            r_meas: Measured corrosion rate in μm/year.

        Returns:
            Tuple of (r_pred, verdict, alarm_level).
        """
        r_pred, confidence = predict_corrosion_rate(T_avg, RH_avg, Cl_avg)

        if confidence <= 0.1:
            return r_pred, VERDICT_NORMAL, 0

        ratio, verdict, alarm_level = cross_validate(r_meas, r_pred)

        return r_pred, verdict, alarm_level

    def _filter_level4_kalman(
        self,
        delta_d: float,
        timestamp: datetime,
        T: float,
        RH: float,
    ) -> float:
        """
        Level 4: Adaptive Kalman filter for corrosion depth and rate.

        Estimates the true corrosion depth using a 2-state Kalman filter
        with environmentally-adaptive process noise.

        Args:
            delta_d: Input corrosion depth (from Level 3A) in μm.
            timestamp: Timestamp of the current measurement.
            T: Current temperature in °C.
            RH: Current relative humidity in %.

        Returns:
            Kalman-filtered corrosion depth in μm.
        """
        delta_d = float(delta_d)
        T = float(T)
        RH = float(RH)

        dT_dt = 0.0
        dRH_dt = 0.0

        if self._prev_timestamp is not None:
            dt_seconds = (timestamp - self._prev_timestamp).total_seconds()
            dt_seconds = max(dt_seconds, 1e-6)
        else:
            dt_seconds = 600.0

        if self._prev_T is not None and dt_seconds > 1e-6:
            dT_dt = (T - self._prev_T) / dt_seconds
        if self._prev_RH is not None and dt_seconds > 1e-6:
            dRH_dt = (RH - self._prev_RH) / dt_seconds

        self._kalman_filter.predict(dt_seconds, dT_dt, dRH_dt)
        self._kalman_filter.update(delta_d)

        state = self._kalman_filter.get_state()
        return state[0]

    def calibrate_noise_threshold(self, sensor_data_24h: List[SensorData]) -> float:
        """
        Calibrate the noise threshold from 24 hours of initial measurements.

        Computes σ_n as the standard deviation of Δd_raw over the calibration
        period, excluding outliers using the IQR method. Then sets
        ε_noise = ε_multiplier × σ_n.

        Args:
            sensor_data_24h: List of at least 24 hours of SensorData.

        Returns:
            The computed ε_noise value, or 0.0 if insufficient data.
        """
        if not sensor_data_24h or len(sensor_data_24h) < 10:
            logger.warning("Noise calibration: insufficient data (%d samples)", len(sensor_data_24h))
            return 0.0

        delta_d_values = []
        for sd in sensor_data_24h:
            dd, _ = self._compensate_level1_hardware_diff(sd.V_mid, sd.V_diff, self._d0)
            if math.isfinite(dd):
                delta_d_values.append(dd)

        if len(delta_d_values) < 10:
            return 0.0

        arr = np.array(delta_d_values, dtype=np.float64)

        q1 = float(np.percentile(arr, 25))
        q3 = float(np.percentile(arr, 75))
        iqr = q3 - q1

        if iqr <= 0:
            self._sigma_n = float(np.std(arr))
        else:
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            mask = (arr >= lower) & (arr <= upper)
            filtered = arr[mask]

            if len(filtered) < 3:
                self._sigma_n = float(np.std(arr))
            else:
                self._sigma_n = float(np.std(filtered))

        self._epsilon_noise = self._epsilon_multiplier * self._sigma_n
        self._kalman_filter.set_measurement_noise(self._sigma_n * self._sigma_n)

        logger.info(
            "Noise calibration complete: σ_n=%.4f μm, ε_noise=%.4f μm (%d samples, %d after IQR filter)",
            self._sigma_n, self._epsilon_noise, len(delta_d_values),
            len(filtered) if iqr > 0 else len(delta_d_values),
        )

        return self._epsilon_noise

    def update_tow_statistics(self, T: float, RH: float) -> None:
        """
        Update Time of Wetness statistics with a new environmental data point.

        Accumulates hourly TOW buckets. A new "wet hour" is counted once
        per hour if T > 0°C and RH > 80%.

        Args:
            T: Temperature in °C.
            RH: Relative humidity in %.
        """
        now = datetime.now(timezone.utc)
        current_hour = now.hour

        if self._last_hour_bucket is None or current_hour != self._last_hour_bucket:
            self._last_hour_bucket = current_hour
            self._tow_calculator.add_hour(T, RH)

    def get_tow_actual(self) -> float:
        """
        Get the current projected annual Time of Wetness.

        Returns:
            Projected annual TOW in hours/year.
        """
        return self._tow_calculator.get_annual_tow()

    def get_tow_grade(self) -> str:
        """
        Get the current ISO 9223 TOW grade.

        Returns:
            ISO 9223 grade string (τ1-τ5).
        """
        return self._tow_calculator.get_tow_grade()

    def is_kalman_warmed_up(self) -> bool:
        """
        Check if the Kalman filter has completed its warm-up period.

        Returns:
            True if at least 36 samples have been processed.
        """
        return self._kalman_filter.is_warmed_up

    def get_kalman_state(self) -> Tuple[float, float]:
        """
        Get the current Kalman filter state estimate.

        Returns:
            Tuple of (Δd_filtered, CR_filtered).
        """
        return self._kalman_filter.get_state()

    def reset_statistics(self) -> None:
        """Reset all accumulated statistics and internal state."""
        self._tow_calculator.reset()
        self._kalman_filter.reset()
        self._consecutive_invalid = 0
        self._v_ref_buffer.clear()
        self._prev_timestamp = None
        self._prev_delta_d = None
        self._prev_T = None
        self._prev_RH = None
        self._last_hour_bucket = None
        self._running_T_sum = 0.0
        self._running_RH_sum = 0.0
        self._running_Cl_sum = 0.0
        self._running_count = 0
        logger.info("Algorithm engine statistics reset")
