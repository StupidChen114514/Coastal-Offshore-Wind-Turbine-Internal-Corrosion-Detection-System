"""
Quartz Crystal Microbalance (QCM) Salinity Sensor Driver.

Implements the Sauerbrey equation for converting frequency shifts from
a 10MHz AT-cut quartz crystal into deposited salt mass measurements.

Core Equation (Sauerbrey):
    delta_f = -(2 * f0^2) / (A * sqrt(rho_q * mu_q)) * delta_m

Where:
    f0 = 10e6 Hz       (crystal fundamental frequency)
    A                    (electrode active area in m²)
    rho_q = 2648 kg/m³  (quartz density)
    mu_q = 2.947e10 Pa  (quartz shear modulus)

Simplified for 10MHz crystal, 1cm² electrode:
    delta_f ≈ -2.26e8 * delta_m / A  (Hz * m² / kg)

Chloride deposition rate:
    [Cl⁻] = d(delta_m/A) / dt  in mg/(m²·day)

Sensitivity: ~1 ng salt mass with 1cm² electrode.
"""

import math
from typing import Tuple

from ..core.logger import CorrosionLogger

logger = CorrosionLogger().get_logger(__name__)


class QCMDriver:
    """QCM salinity sensor driver implementing Sauerbrey equation.

    Converts frequency shift measurements from a 10 MHz AT-cut quartz
    crystal into deposited salt mass and chloride deposition rate.

    Attributes:
        F0: Crystal fundamental frequency (10 MHz).
        RHO_Q: Quartz crystal density (2648 kg/m³).
        MU_Q: Quartz crystal shear modulus (2.947e10 Pa).
        SENSITIVITY_FACTOR: Simplified sensitivity factor for 10 MHz, 1 cm².
    """

    F0: float = 10.0e6
    RHO_Q: float = 2648.0
    MU_Q: float = 2.947e10
    SENSITIVITY_FACTOR: float = (
        2.0 * F0 * F0 / math.sqrt(RHO_Q * MU_Q)
    )

    @classmethod
    def mass_from_frequency_shift(
        cls, delta_f_Hz: float, electrode_area_m2: float
    ) -> float:
        """Calculate deposited mass from measured frequency shift.

        Uses the Sauerbrey equation:
            delta_m = -(delta_f * A * sqrt(rho_q * mu_q)) / (2 * f0^2)

        Args:
            delta_f_Hz: Frequency shift in Hz (negative for mass gain).
            electrode_area_m2: Electrode active area in m².

        Returns:
            Deposited mass delta_m in kg. Positive value indicates mass gain.

        Raises:
            ValueError: If electrode_area_m2 is not positive.
        """
        if electrode_area_m2 <= 0.0:
            raise ValueError(
                f"Electrode area must be positive, got {electrode_area_m2} m²"
            )

        delta_m = -(delta_f_Hz * electrode_area_m2 * math.sqrt(cls.RHO_Q * cls.MU_Q)) / (
            2.0 * cls.F0 * cls.F0
        )

        logger.debug(
            "QCM: delta_f=%.2f Hz, A=%.2e m² -> delta_m=%.6e kg (%.3f µg)",
            delta_f_Hz,
            electrode_area_m2,
            delta_m,
            delta_m * 1e9,
        )
        return delta_m

    @classmethod
    def frequency_shift_from_mass(
        cls, delta_m_kg: float, electrode_area_m2: float
    ) -> float:
        """Calculate expected frequency shift for a given mass change.

        Args:
            delta_m_kg: Deposited mass in kg.
            electrode_area_m2: Electrode active area in m².

        Returns:
            Frequency shift in Hz (negative for mass gain).
        """
        if electrode_area_m2 <= 0.0:
            raise ValueError(
                f"Electrode area must be positive, got {electrode_area_m2} m²"
            )

        delta_f = -(2.0 * cls.F0 * cls.F0) / (
            electrode_area_m2 * math.sqrt(cls.RHO_Q * cls.MU_Q)
        ) * delta_m_kg

        return delta_f

    @classmethod
    def deposition_rate(
        cls,
        mass_current_kg: float,
        mass_previous_kg: float,
        time_interval_s: float,
        electrode_area_m2: float,
    ) -> float:
        """Calculate chloride deposition rate from two consecutive mass readings.

        The deposition rate [Cl⁻] is computed as:
            Cl_deposition = (delta_m / area) / delta_t

        Unit conversion: kg/(m²·s) -> mg/(m²·day)
            1 kg = 1e6 mg
            1 day = 86400 s
            factor = 1e6 * 86400 = 8.64e10

        Args:
            mass_current_kg: Current deposited mass in kg.
            mass_previous_kg: Previous deposited mass in kg.
            time_interval_s: Time between readings in seconds.
            electrode_area_m2: Electrode active area in m².

        Returns:
            Chloride deposition rate in mg/(m²·day).

        Raises:
            ValueError: If time_interval_s or electrode_area_m2 is not positive.
        """
        if time_interval_s <= 0.0:
            raise ValueError(
                f"Time interval must be positive, got {time_interval_s} s"
            )
        if electrode_area_m2 <= 0.0:
            raise ValueError(
                f"Electrode area must be positive, got {electrode_area_m2} m²"
            )

        delta_m_kg = mass_current_kg - mass_previous_kg
        mass_flux_kg_per_m2_s = delta_m_kg / (electrode_area_m2 * time_interval_s)

        cl_deposition = mass_flux_kg_per_m2_s * 8.64e10

        logger.debug(
            "QCM deposition: delta_m=%.6e kg, dt=%.0f s -> Cl=%.3f mg/(m²·day)",
            delta_m_kg,
            time_interval_s,
            cl_deposition,
        )
        return cl_deposition

    @classmethod
    def get_simplified_factor(cls, electrode_area_m2: float) -> float:
        """Get the simplified Sauerbrey sensitivity factor for a given electrode.

        For 10 MHz crystal: delta_f ≈ -2.26e8 * delta_m / A

        Args:
            electrode_area_m2: Electrode active area in m².

        Returns:
            Sensitivity factor in Hz·m²/kg.
        """
        return cls.SENSITIVITY_FACTOR / electrode_area_m2

    @classmethod
    def estimate_min_detectable_mass(
        cls, frequency_resolution_Hz: float, electrode_area_m2: float
    ) -> float:
        """Estimate the minimum detectable mass given frequency resolution.

        Args:
            frequency_resolution_Hz: Frequency measurement resolution in Hz.
            electrode_area_m2: Electrode active area in m².

        Returns:
            Minimum detectable mass in kg.
        """
        return cls.mass_from_frequency_shift(
            frequency_resolution_Hz, electrode_area_m2
        )

    @classmethod
    def validate_frequency_shift(
        cls, delta_f_Hz: float, electrode_area_m2: float, max_mass_kg: float = 1e-6
    ) -> bool:
        """Validate that a frequency shift is within physically reasonable bounds.

        Args:
            delta_f_Hz: Measured frequency shift in Hz.
            electrode_area_m2: Electrode active area in m².
            max_mass_kg: Maximum expected mass per reading (default 1 µg).

        Returns:
            True if the shift is within reasonable bounds.
        """
        expected_max_shift = abs(
            cls.frequency_shift_from_mass(max_mass_kg, electrode_area_m2)
        )

        if abs(delta_f_Hz) > expected_max_shift * 10.0:
            logger.warning(
                "QCM frequency shift %.2f Hz exceeds expected maximum "
                "%.2f Hz for max mass %.2e kg",
                delta_f_Hz,
                expected_max_shift * 10.0,
                max_mass_kg,
            )
            return False
        return True
