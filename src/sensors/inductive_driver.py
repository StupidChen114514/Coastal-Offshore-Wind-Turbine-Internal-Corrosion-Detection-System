"""
Inductive Probe Driver (LDC1614-based).

Implements eddy-current-based non-contact thickness measurement using the
TI LDC1614 4-channel inductance-to-digital converter.

Principle (Chapter 5 of structure.md):

    A coil placed beneath the metal specimen generates an alternating
    magnetic field that induces eddy currents in the specimen. These eddy
    currents produce an opposing magnetic field that couples back to the
    coil, changing its effective inductance.

    When corrosion reduces the specimen thickness d:
        d ↓ → eddy cross-section A_eddy ↓ → eddy resistance R₂ ↑
        → counter-field weakens → equivalent inductance L_eq ↑

    The LDC1614 measures this change with 28-bit resolution.

LDC1614 Key Specifications:
    - Resolution: 28 bits
    - I2C address: 0x2A (7-bit)
    - Output: DATAx registers (0x00-0x03 for channels 0-3)
    - Conversion: f_sensor = f_ref * (DATAx / 2^28)
    - L_eq formula: L = 1 / (C * (2*pi*f_sensor)^2)
"""

import math
from dataclasses import dataclass
from typing import Dict, Optional

from ..core.logger import CorrosionLogger

logger = CorrosionLogger().get_logger(__name__)


@dataclass
class LDC1614Config:
    """LDC1614 inductance-to-digital converter configuration.

    Attributes:
        f_ref: Reference clock frequency in Hz (typically 40 MHz).
        C_sensor: Parallel tank capacitor value in F (typically 100 pF).
        channel: LDC1614 channel number (0-3).
        i2c_address: 7-bit I2C address (default 0x2A).
        R_COUNT: Conversion time setting in reference clock cycles.
        SETTLECOUNT: Settling time before conversion.
        IDRIVE: Sensor drive current setting (0-31, ~16µA per step).
    """

    f_ref: float = 40.0e6
    C_sensor: float = 100.0e-12
    channel: int = 0
    i2c_address: int = 0x2A
    R_COUNT: int = 0x04E2
    SETTLECOUNT: int = 0x000A
    IDRIVE: int = 0x10


class InductiveDriver:
    """Inductive probe driver for LDC1614-based non-contact thickness measurement.

    Converts LDC1614 raw data readings to equivalent inductance and computes
    corrosion-induced thickness changes through eddy current coupling analysis.

    Attributes:
        RESOLUTION_BITS: LDC1614 ADC resolution (28 bits).
        I2C_ADDRESS: Default 7-bit I2C address.
    """

    RESOLUTION_BITS: int = 28
    I2C_ADDRESS: int = 0x2A
    RESOLUTION_MAX: float = float(1 << 28)

    @classmethod
    def convert_raw_to_inductance(
        cls,
        raw_value: int,
        config: Optional[LDC1614Config] = None,
    ) -> float:
        """Convert LDC1614 raw data register value to equivalent inductance.

        The LDC1614 measures the sensor oscillation frequency:

            f_sensor = f_ref * (DATAx / 2^28)

        The tank circuit resonant frequency relates to inductance:

            f_sensor = 1 / (2 * pi * sqrt(L * C))

        Therefore:

            L = 1 / (C * (2 * pi * f_sensor)^2)

        Args:
            raw_value: Raw 28-bit DATAx register value.
            config: LDC1614 configuration. Uses defaults if None.

        Returns:
            Equivalent inductance L_eq in Henry (H).

        Raises:
            ValueError: If raw_value is out of 28-bit range.
        """
        if config is None:
            config = LDC1614Config()

        max_raw = int(cls.RESOLUTION_MAX)
        if raw_value < 0 or raw_value >= max_raw:
            raise ValueError(
                f"Raw value {raw_value} out of range [0, {max_raw})"
            )

        f_sensor = config.f_ref * (raw_value / cls.RESOLUTION_MAX)

        if f_sensor <= 0.0:
            raise ValueError(
                f"Computed sensor frequency {f_sensor:.2f} Hz is invalid"
            )

        L_eq = 1.0 / (config.C_sensor * (2.0 * math.pi * f_sensor) ** 2)

        logger.debug(
            "LDC1614: raw=%d -> f_sensor=%.2f MHz -> L_eq=%.6e H (%.3f uH)",
            raw_value,
            f_sensor / 1e6,
            L_eq,
            L_eq * 1e6,
        )
        return L_eq

    @classmethod
    def convert_inductance_to_raw(
        cls,
        L_eq: float,
        config: Optional[LDC1614Config] = None,
    ) -> int:
        """Convert equivalent inductance back to LDC1614 raw data value.

        Args:
            L_eq: Equivalent inductance in H.
            config: LDC1614 configuration.

        Returns:
            Raw 28-bit DATAx register value.
        """
        if config is None:
            config = LDC1614Config()

        if L_eq <= 0.0:
            raise ValueError(
                f"Inductance must be positive, got {L_eq:.6e} H"
            )

        f_sensor = 1.0 / (2.0 * math.pi * math.sqrt(L_eq * config.C_sensor))
        raw_value = int(f_sensor / config.f_ref * cls.RESOLUTION_MAX)
        raw_value = max(0, min(raw_value, int(cls.RESOLUTION_MAX) - 1))
        return raw_value

    @classmethod
    def calculate_delta_d_inductive(
        cls,
        L_eq_current: float,
        L_eq_initial: float,
        calibration_factor: float,
    ) -> float:
        """Calculate corrosion depth from inductance change.

        As the specimen corrodes and thins, the eddy current path resistance
        increases, reducing the counter-field and increasing L_eq.

        The relationship is approximately linear for small thickness changes:

            delta_d = calibration_factor * (L_eq_current - L_eq_initial)

        The calibration factor (µm/H) is determined experimentally by
        correlating known thickness reductions with L_eq shifts.

        Args:
            L_eq_current: Current equivalent inductance in H.
            L_eq_initial: Initial (reference) equivalent inductance in H.
            calibration_factor: Calibration factor in µm/H.

        Returns:
            Corrosion depth delta_d in µm.

        Raises:
            ValueError: If calibration_factor is not positive.
        """
        if calibration_factor <= 0.0:
            raise ValueError(
                f"Calibration factor must be positive, got {calibration_factor}"
            )

        if L_eq_initial <= 0.0:
            raise ValueError(
                f"Initial inductance must be positive, got {L_eq_initial:.6e} H"
            )

        delta_L = L_eq_current - L_eq_initial
        delta_d_um = calibration_factor * delta_L

        logger.debug(
            "Inductive: L_init=%.6e H, L_curr=%.6e H, delta_L=%.6e H "
            "-> delta_d=%.4f um",
            L_eq_initial,
            L_eq_current,
            delta_L,
            delta_d_um,
        )
        return delta_d_um

    @classmethod
    def calibrate_factor(
        cls,
        L_eq_initial: float,
        L_eq_measured: float,
        known_delta_d_um: float,
    ) -> float:
        """Determine the calibration factor from a known thickness change.

        calibration_factor = known_delta_d / (L_eq_measured - L_eq_initial)

        Args:
            L_eq_initial: Inductance at reference thickness in H.
            L_eq_measured: Inductance at reduced thickness in H.
            known_delta_d_um: Known thickness reduction in µm.

        Returns:
            Calibration factor in µm/H.

        Raises:
            ValueError: If the inductance change is too small for calibration.
        """
        delta_L = L_eq_measured - L_eq_initial

        if abs(delta_L) < 1e-15:
            raise ValueError(
                "Inductance change too small for calibration: "
                f"delta_L={delta_L:.3e} H"
            )
        if known_delta_d_um <= 0.0:
            raise ValueError(
                f"Known delta_d must be positive, got {known_delta_d_um} um"
            )

        factor = known_delta_d_um / delta_L
        logger.info(
            "Inductive calibration: delta_L=%.6e H, delta_d=%.2f um "
            "-> factor=%.6e um/H",
            delta_L,
            known_delta_d_um,
            factor,
        )
        return factor

    @classmethod
    def compute_resolution_limit_um(
        cls,
        calibration_factor: float,
        config: Optional[LDC1614Config] = None,
    ) -> float:
        """Estimate the minimum detectable thickness change (resolution limit).

        With 28-bit resolution, the LDC1614 can detect extremely small
        inductance changes. This method estimates the equivalent thickness
        resolution based on the calibration factor.

        Args:
            calibration_factor: Calibration factor in µm/H.
            config: LDC1614 configuration.

        Returns:
            Minimum detectable thickness change in µm.
        """
        if config is None:
            config = LDC1614Config()

        raw_resolution = 1
        L_base = cls.convert_raw_to_inductance(0x1000000, config)
        L_step = cls.convert_raw_to_inductance(0x1000000 + raw_resolution, config)
        delta_L_min = abs(L_step - L_base)
        delta_d_min = calibration_factor * delta_L_min

        return delta_d_min

    @classmethod
    def is_coupling_healthy(
        cls,
        L_eq: float,
        L_open_air: Optional[float] = None,
        max_ratio: float = 0.95,
    ) -> bool:
        """Check if coil-specimen coupling is healthy.

        If L_eq approaches the open-air inductance, it indicates poor
        or lost coupling with the specimen (e.g., coil detached).

        Args:
            L_eq: Current measured equivalent inductance in H.
            L_open_air: Open-air inductance (no specimen). If None, skip check.
            max_ratio: Maximum acceptable L_eq / L_open_air ratio.

        Returns:
            True if coupling appears healthy.
        """
        if L_open_air is None:
            return True

        if L_open_air <= 0.0:
            return True

        ratio = L_eq / L_open_air
        is_healthy = ratio < max_ratio
        if not is_healthy:
            logger.warning(
                "Inductive probe coupling suspect: L_eq/L_open=%.4f >= %.4f",
                ratio,
                max_ratio,
            )
        return is_healthy

    @classmethod
    def convert_ldc1614_to_delta_d(
        cls,
        raw_current: int,
        raw_initial: int,
        calibration_factor: float,
        config: Optional[LDC1614Config] = None,
    ) -> float:
        """Full pipeline: LDC1614 raw values -> corrosion depth.

        Convenience method that combines raw-to-inductance conversion
        and delta_d calculation in one call.

        Args:
            raw_current: Current LDC1614 DATAx raw value.
            raw_initial: Initial (reference) LDC1614 DATAx raw value.
            calibration_factor: Calibration factor in µm/H.
            config: LDC1614 configuration.

        Returns:
            Corrosion depth delta_d in µm.
        """
        L_current = cls.convert_raw_to_inductance(raw_current, config)
        L_initial = cls.convert_raw_to_inductance(raw_initial, config)
        return cls.calculate_delta_d_inductive(L_current, L_initial, calibration_factor)
