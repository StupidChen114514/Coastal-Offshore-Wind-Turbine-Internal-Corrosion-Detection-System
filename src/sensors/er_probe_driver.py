"""
Electrical Resistance (ER) Probe Driver.

Implements the superimposed dual-ring differential structure for corrosion
depth measurement with intrinsic temperature compensation.

Principle (Chapter 4 of structure.md):

    The ER probe uses two superimposed metal thin-film rings on an alumina
    ceramic substrate:
      - Reference ring (R_r): sealed with Parylene C coating, isolated from
        the corrosive environment. Thickness remains at d0.
      - Sensing ring (R_s): exposed to the environment, thins from d0 to
        (d0 - delta_d) as corrosion progresses.

    When the two rings (identical material and geometry, separated by only
    0.5µm SiO₂) are connected in series with a constant current source:

        Rs/Rr = d0 / (d0 - delta_d)     (Equation 7)

    The resistivity rho(T) cancels out, eliminating temperature error at
    the hardware level.

    Solving for delta_d:

        delta_d = d0 * (1 - Rr/Rs)       (Equation 8)

    Using voltage measurement:
        Rs/Rr = 1 + V_diff / V_mid      (Equation 12)

    Final working formula:
        delta_d = d0 * (1 - 1 / (1 + V_diff / V_mid))    (Equation 13)
"""

import math
from typing import List, Optional, Tuple

from ..core.logger import CorrosionLogger

logger = CorrosionLogger().get_logger(__name__)


class ERProbeDriver:
    """Electrical Resistance probe driver for corrosion depth measurement.

    Implements the superimposed dual-ring differential structure with
    hardware-level temperature compensation and ratio-metric self-calibration.

    Attributes:
        DEFAULT_D0: Default initial sensing element thickness (100 µm).
        MIN_VALID_RATIO: Minimum valid Rs/Rr ratio.
        MAX_VALID_RATIO: Maximum valid Rs/Rr ratio.
    """

    DEFAULT_D0: float = 100.0e-6
    MIN_VALID_RATIO: float = 0.5
    MAX_VALID_RATIO: float = 2.0

    @classmethod
    def calculate_ratio_from_voltage(
        cls, V_mid: float, V_diff: float
    ) -> float:
        """Calculate the resistance ratio Rs/Rr from voltage measurements.

        For series-connected Rs and Rr with constant current I:
            V_mid = I * Rr           (midpoint to ground)
            V_diff = I * (Rs - Rr)   (differential across Rs)

            Rs/Rr = 1 + V_diff / V_mid      (Equation 12)

        Args:
            V_mid: Midpoint voltage across Rr in V.
            V_diff: Differential voltage across Rs-Rr in V.

        Returns:
            Resistance ratio Rs/Rr (dimensionless).

        Raises:
            ValueError: If V_mid is zero or negative.
        """
        if V_mid <= 0.0:
            raise ValueError(
                f"V_mid must be positive, got {V_mid:.6f} V"
            )

        ratio = 1.0 + V_diff / V_mid

        logger.debug(
            "ER probe: V_mid=%.6f V, V_diff=%.6f V -> Rs/Rr=%.6f",
            V_mid,
            V_diff,
            ratio,
        )
        return ratio

    @classmethod
    def calculate_delta_d_raw(
        cls,
        V_mid: float,
        V_diff: float,
        d0: float = 100.0e-6,
    ) -> float:
        """Calculate raw corrosion depth from voltage measurements.

        Uses the full working equation (Equation 13):
            delta_d = d0 * (1 - 1 / (1 + V_diff / V_mid))

        Args:
            V_mid: Midpoint voltage across Rr in V.
            V_diff: Differential voltage across Rs-Rr in V.
            d0: Initial sensing element thickness in m (default 100 µm).

        Returns:
            Corrosion depth delta_d in µm.

        Raises:
            ValueError: If d0 <= 0 or V_mid <= 0.
        """
        if d0 <= 0.0:
            raise ValueError(
                f"Initial thickness d0 must be positive, got {d0:.6e} m"
            )

        ratio = cls.calculate_ratio_from_voltage(V_mid, V_diff)
        delta_d_m = d0 * (1.0 - 1.0 / ratio)
        delta_d_um = delta_d_m * 1e6

        logger.debug(
            "ER probe: delta_d_raw=%.4f um (d0=%.2f um, Rs/Rr=%.6f)",
            delta_d_um,
            d0 * 1e6,
            ratio,
        )
        return delta_d_um

    @classmethod
    def calculate_delta_d_from_ratio(
        cls,
        ratio: float,
        d0: float = 100.0e-6,
    ) -> float:
        """Calculate corrosion depth directly from the Rs/Rr resistance ratio.

        delta_d = d0 * (1 - 1 / ratio)    (Equation 8)

        Args:
            ratio: Resistance ratio Rs/Rr.
            d0: Initial sensing element thickness in m (default 100 µm).

        Returns:
            Corrosion depth delta_d in µm.
        """
        if d0 <= 0.0:
            raise ValueError(
                f"Initial thickness d0 must be positive, got {d0:.6e} m"
            )
        if ratio <= 0.0:
            raise ValueError(
                f"Resistance ratio must be positive, got {ratio:.6f}"
            )

        delta_d_m = d0 * (1.0 - 1.0 / ratio)
        delta_d_um = delta_d_m * 1e6
        return delta_d_um

    @classmethod
    def validate_ratio(cls, Rs_over_Rr: float) -> bool:
        """Validate that Rs/Rr is within physically reasonable bounds.

        A healthy probe should have Rs/Rr close to 1.0 at installation.
        As the sensing ring corrodes and thins, Rs increases, so Rs/Rr > 1.

        Range check: 0.5 < Rs/Rr < 2.0
        - Below 0.5: likely a wiring fault or reversed polarity
        - Above 2.0: severe corrosion beyond design limits or open circuit

        Args:
            Rs_over_Rr: Resistance ratio Rs/Rr.

        Returns:
            True if the ratio is within valid bounds.
        """
        is_valid = cls.MIN_VALID_RATIO < Rs_over_Rr < cls.MAX_VALID_RATIO
        if not is_valid:
            logger.warning(
                "ER probe ratio %.4f outside valid range (%.2f, %.2f)",
                Rs_over_Rr,
                cls.MIN_VALID_RATIO,
                cls.MAX_VALID_RATIO,
            )
        return is_valid

    @classmethod
    def check_current_source_stability(
        cls,
        V_ref_history: List[float],
        window_size: int = 10,
        tolerance: float = 0.001,
    ) -> bool:
        """Check if the constant current source is stable over recent readings.

        Stability is determined by examining the variation in V_ref (V_mid)
        across a sliding window of recent measurements. Since V_mid = I * Rr
        and Rr is protected from corrosion, changes in V_mid primarily
        reflect drift in the current source I.

        Args:
            V_ref_history: List of recent V_ref (V_mid) readings in V.
            window_size: Number of most recent readings to include.
            tolerance: Maximum allowed fractional deviation (default 0.1%).

        Returns:
            True if the current source is stable within tolerance.
        """
        if len(V_ref_history) < 2:
            logger.debug(
                "ER probe current source check: insufficient data (%d samples)",
                len(V_ref_history),
            )
            return True

        recent = V_ref_history[-window_size:] if len(V_ref_history) >= window_size else V_ref_history

        if not recent:
            return True

        mean_v = sum(recent) / len(recent)
        if mean_v == 0.0:
            return True

        max_deviation = max(abs(v - mean_v) / mean_v for v in recent)

        is_stable = max_deviation <= tolerance
        if not is_stable:
            logger.warning(
                "ER probe current source unstable: max deviation=%.4f%% "
                "(tolerance=%.4f%%)",
                max_deviation * 100.0,
                tolerance * 100.0,
            )
        else:
            logger.debug(
                "ER probe current source stable: max deviation=%.4f%%",
                max_deviation * 100.0,
            )

        return is_stable

    @classmethod
    def apply_residual_temperature_correction(
        cls,
        delta_d_raw_um: float,
        T: float,
        T0_ref: float = 25.0,
        alpha_res: float = 0.0,
        beta_res: float = 0.0,
    ) -> float:
        """Apply third-level software compensation for residual temperature error.

        Although the hardware differential structure already eliminates the
        primary rho(T) effect, manufacturing tolerances may cause slight
        geometric mismatches between the two rings. This software correction
        compensates for the residual temperature dependency:

            delta_d_corrected = delta_d_raw / (1 + alpha_res*(T-T0) + beta_res*(T-T0)²)

        (Equation 21, Chapter 8.3)

        Args:
            delta_d_raw_um: Raw corrosion depth from ER probe in µm.
            T: Current temperature in °C.
            T0_ref: Reference temperature in °C (default 25°C).
            alpha_res: Residual linear temperature coefficient (/°C).
            beta_res: Residual quadratic temperature coefficient (/°C²).

        Returns:
            Temperature-corrected corrosion depth in µm.
        """
        dT = T - T0_ref
        correction = 1.0 + alpha_res * dT + beta_res * dT * dT

        if correction <= 0.0:
            logger.warning(
                "ER probe temperature correction factor %.6f is invalid; "
                "returning raw value",
                correction,
            )
            return delta_d_raw_um

        delta_d_corrected = delta_d_raw_um / correction

        logger.debug(
            "ER probe temp correction: T=%.2f°C, dT=%.2f°C, "
            "raw=%.4f um -> corrected=%.4f um (factor=%.6f)",
            T,
            dT,
            delta_d_raw_um,
            delta_d_corrected,
            correction,
        )
        return delta_d_corrected

    @classmethod
    def compute_corrosion_rate(
        cls,
        delta_d_current_um: float,
        delta_d_previous_um: float,
        time_interval_s: float,
    ) -> float:
        """Compute instantaneous corrosion rate from two consecutive readings.

        Args:
            delta_d_current_um: Current corrosion depth in µm.
            delta_d_previous_um: Previous corrosion depth in µm.
            time_interval_s: Time between readings in seconds.

        Returns:
            Corrosion rate in mm/year.

        Raises:
            ValueError: If time_interval_s is not positive.
        """
        if time_interval_s <= 0.0:
            raise ValueError(
                f"Time interval must be positive, got {time_interval_s} s"
            )

        delta_um = delta_d_current_um - delta_d_previous_um
        delta_mm = delta_um * 0.001
        hours_per_year = 365.25 * 24.0
        seconds_per_year = hours_per_year * 3600.0
        cr_mm_per_year = delta_mm * (seconds_per_year / time_interval_s)

        logger.debug(
            "ER probe CR: delta_d=%.4f um, dt=%.0f s -> CR=%.6f mm/year",
            delta_um,
            time_interval_s,
            cr_mm_per_year,
        )
        return cr_mm_per_year

    @classmethod
    def compute_pitting_eta(
        cls,
        delta_d_ER_um: float,
        delta_d_Inductive_um: float,
    ) -> float:
        """Estimate the pitting factor eta from dual-mode probe disagreement.

        The difference between ER and Inductive measurements provides an
        indirect indication of non-uniform (pitting) corrosion.

            delta = |delta_d_ER - delta_d_Inductive| / delta_d_ER   (Equation 20)

        When delta is large, corrosion is likely non-uniform.

        Args:
            delta_d_ER_um: Corrosion depth from ER probe in µm.
            delta_d_Inductive_um: Corrosion depth from inductive probe in µm.

        Returns:
            Estimated pitting factor eta (>= 1.0). eta = 1.0 means uniform
            corrosion; larger values indicate pitting.
        """
        if delta_d_ER_um <= 0.0:
            return 1.0

        delta = abs(delta_d_ER_um - delta_d_Inductive_um) / delta_d_ER_um
        eta = 1.0 + delta * 5.0
        eta = max(1.0, min(eta, 20.0))

        logger.debug(
            "ER/Inductive pitting: delta_ER=%.4f um, delta_Ind=%.4f um, "
            "delta=%.4f, eta=%.2f",
            delta_d_ER_um,
            delta_d_Inductive_um,
            delta,
            eta,
        )
        return eta

    @classmethod
    def is_data_valid_in_dry_conditions(
        cls,
        delta_d_raw_um: float,
        RH: float,
        RH_crit: float = 76.0,
        epsilon_noise_um: float = 0.2,
    ) -> Tuple[bool, str]:
        """Humidity-gated data validity check.

        When RH < RH_crit (NaCl deliquescence threshold), the surface salt
        particles are not deliquesced and cannot form a continuous electrolyte
        film. Any significant measured delta_d in dry conditions is likely
        a false signal from electronic noise or thermal drift.

        (Equation 22, Chapter 8.3)

        Args:
            delta_d_raw_um: Raw corrosion depth from ER probe in µm.
            RH: Current relative humidity in %.
            RH_crit: Critical humidity threshold (default 76%).
            epsilon_noise_um: Noise threshold in µm (3 * sigma_n).

        Returns:
            Tuple of (is_valid, reason).
        """
        if RH >= RH_crit:
            return (True, "RH above critical threshold")

        if abs(delta_d_raw_um) < epsilon_noise_um:
            return (True, "Signal within noise floor")

        logger.warning(
            "ER probe: suspicious signal %.4f um detected at RH=%.1f%% "
            "(below RH_crit=%.1f%%)",
            delta_d_raw_um,
            RH,
            RH_crit,
        )
        return (False, "Suspicious: signal exceeds noise floor in dry conditions")
