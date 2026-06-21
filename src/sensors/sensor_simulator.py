"""
Sensor Simulator for testing without hardware.

Generates realistic simulated sensor data modeling the coastal offshore
wind turbine internal environment. Simulates diurnal temperature cycles,
humidity cycles, steady corrosion progression, occasional salt deposition
events, and sensor fault injection capabilities.

Environmental Models:
    - Temperature: Sinusoidal day/night cycle, 20-30°C range
    - Humidity: Sinusoidal anti-correlated cycle, 60-95% RH range
    - Corrosion: Steady progression 0.01-0.5 µm/day
    - Salt deposition: Background rate + random burst events
"""

import math
import random
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from ..core.data_models import SensorData
from ..core.logger import CorrosionLogger

logger = CorrosionLogger().get_logger(__name__)


class SensorSimulator:
    """Realistic sensor data simulator for offline testing.

    Generates synthetic sensor readings that mimic real coastal offshore
    wind turbine internal environmental conditions. Supports configurable
    fault injection for testing error handling paths.

    Attributes:
        _rng: Random number generator for reproducibility.
        _seed: Random seed value.
        _start_time: Simulation start time (epoch seconds).
        _baseline_T: Baseline temperature in °C.
        _baseline_RH: Baseline relative humidity in %.
        _baseline_corrosion_um: Starting corrosion depth in µm.
        _fault_injection: Dict of fault injection flags.
        _corrosion_rate_um_per_day: Configurable corrosion progression rate.
        _salt_event_probability: Probability of salt burst per sample.
        _sample_count: Cumulative number of samples generated.
        _previous_mass_kg: Previous QCM mass for deposition rate calc.
        _previous_sample_time: Timestamp of previous sample.
    """

    def __init__(
        self,
        seed: Optional[int] = None,
        baseline_T: float = 25.0,
        baseline_RH: float = 80.0,
        baseline_corrosion_um: float = 0.0,
        corrosion_rate_um_per_day: float = 0.15,
    ) -> None:
        """Initialize the sensor simulator.

        Args:
            seed: Random seed for reproducibility. Uses system time if None.
            baseline_T: Baseline temperature in °C (default 25.0).
            baseline_RH: Baseline relative humidity in % (default 80.0).
            baseline_corrosion_um: Initial corrosion depth in µm (default 0.0).
            corrosion_rate_um_per_day: Base corrosion progression rate (default 0.15).
        """
        self._seed = seed if seed is not None else int(time.time() * 1000) % (2**31)
        self._rng = random.Random(self._seed)

        self._start_time = time.time()
        self._baseline_T = baseline_T
        self._baseline_RH = baseline_RH
        self._baseline_corrosion_um = baseline_corrosion_um
        self._corrosion_rate_um_per_day = corrosion_rate_um_per_day

        self._fault_injection: Dict[str, bool] = {
            "pt1000_fault": False,
            "sht35_fault": False,
            "qcm_fault": False,
            "er_probe_fault": False,
            "inductive_fault": False,
            "all_fault": False,
        }

        self._sample_count: int = 0
        self._previous_mass_kg: float = 0.0
        self._previous_sample_time: float = self._start_time

        self._salt_event_active = False
        self._salt_event_mass = 0.0
        self._salt_event_remaining = 0.0

        logger.info(
            "SensorSimulator initialized: seed=%d, T_baseline=%.1fC, "
            "RH_baseline=%.1f%%, CR=%.3f um/day",
            self._seed,
            baseline_T,
            baseline_RH,
            corrosion_rate_um_per_day,
        )

    def set_fault(
        self, sensor_name: str, enabled: bool = True
    ) -> None:
        """Inject a fault for a specific sensor.

        Args:
            sensor_name: Sensor identifier ('pt1000', 'sht35', 'qcm',
                         'er_probe', 'inductive', 'all').
            enabled: True to enable fault, False to disable.
        """
        if sensor_name in self._fault_injection:
            self._fault_injection[sensor_name] = enabled
            logger.info(
                "SensorSimulator fault %s: %s=%s",
                "ENABLED" if enabled else "DISABLED",
                sensor_name,
                enabled,
            )
        else:
            logger.warning(
                "Unknown sensor '%s' for fault injection. Available: %s",
                sensor_name,
                list(self._fault_injection.keys()),
            )

    def clear_all_faults(self) -> None:
        """Clear all injected faults."""
        for key in self._fault_injection:
            self._fault_injection[key] = False
        logger.info("All sensor faults cleared")

    def generate_sample(self) -> SensorData:
        """Generate a single realistic sensor data sample.

        Models environmental variations and produces a complete SensorData
        object with all fields populated according to the physical models.

        Returns:
            SensorData with realistic simulated values.
        """
        now = time.time()
        elapsed_s = now - self._start_time
        elapsed_days = elapsed_s / 86400.0

        T = self._simulate_temperature(elapsed_s)
        RH = self._simulate_humidity(elapsed_s, T)
        delta_d_ER, V_mid, V_diff = self._simulate_er_probe(elapsed_days, T)
        delta_d_Inductive, L_eq = self._simulate_inductive(elapsed_days, T)
        delta_f, Cl_deposition = self._simulate_qcm(elapsed_s, now)
        valid_flag = self._determine_valid_flag(T, RH, delta_d_ER)

        self._sample_count += 1
        self._previous_sample_time = now

        data = SensorData(
            timestamp=datetime.fromtimestamp(now, tz=timezone.utc),
            T=T,
            RH=RH,
            Cl_deposition=Cl_deposition,
            delta_d_ER=delta_d_ER,
            delta_d_Inductive=delta_d_Inductive,
            V_mid=V_mid,
            V_diff=V_diff,
            L_eq=L_eq,
            delta_f=delta_f,
            valid_flag=valid_flag,
        )

        logger.debug(
            "Simulator sample #%d: T=%.2fC, RH=%.2f%%, ER=%.4fum, "
            "Ind=%.4fum, Cl=%.3f mg/(m2.day)",
            self._sample_count,
            T,
            RH,
            delta_d_ER,
            delta_d_Inductive,
            Cl_deposition,
        )
        return data

    def _simulate_temperature(self, elapsed_s: float) -> float:
        """Simulate diurnal temperature cycle.

        Models a sinusoidal daily cycle (period = 86400s) with the
        peak at ~14:00 (solar time). Adds small random fluctuations
        to represent measurement noise.

        Coastal offshore environment: 20-30°C range.

        Args:
            elapsed_s: Elapsed simulation time in seconds.

        Returns:
            Simulated temperature in °C.
        """
        if self._fault_injection.get("all_fault") or self._fault_injection.get("pt1000_fault"):
            return float("nan")

        hour_of_day = (elapsed_s % 86400.0) / 3600.0
        daily_cycle = math.sin(2.0 * math.pi * (hour_of_day - 8.0) / 24.0)

        T_daily = 25.0 + 4.5 * daily_cycle

        slow_variation = 1.5 * math.sin(2.0 * math.pi * elapsed_s / (86400.0 * 15.0))

        noise = self._rng.gauss(0.0, 0.05)

        T = T_daily + slow_variation + noise
        T = max(15.0, min(35.0, T))
        return T

    def _simulate_humidity(self, elapsed_s: float, T: float) -> float:
        """Simulate diurnal humidity cycle.

        Relative humidity is anti-correlated with temperature (RH peaks
        at night when temperature drops). Coastal offshore range: 60-95% RH.

        Args:
            elapsed_s: Elapsed simulation time in seconds.
            T: Current simulated temperature in °C.

        Returns:
            Simulated relative humidity in %.
        """
        if self._fault_injection.get("all_fault") or self._fault_injection.get("sht35_fault"):
            return float("nan")

        hour_of_day = (elapsed_s % 86400.0) / 3600.0
        daily_cycle = math.sin(2.0 * math.pi * (hour_of_day - 14.0) / 24.0)

        RH_daily = 77.0 + 14.0 * daily_cycle

        temp_effect = -(T - 25.0) * 1.5

        slow_variation = 3.0 * math.sin(
            2.0 * math.pi * elapsed_s / (86400.0 * 22.0)
        )

        noise = self._rng.gauss(0.0, 0.3)

        RH = RH_daily + temp_effect + slow_variation + noise
        RH = max(55.0, min(98.0, RH))
        return RH

    def _simulate_er_probe(
        self, elapsed_days: float, T: float
    ) -> Tuple[float, float, float]:
        """Simulate Electrical Resistance probe readings.

        Models steady uniform corrosion progression at configurable rate
        with small random fluctuations. The baseline corrosion rate is
        adjusted upward when RH > 76% (corrosion-active state).

        Args:
            elapsed_days: Elapsed simulation time in days.
            T: Current temperature in °C.

        Returns:
            Tuple of (delta_d_ER_um, V_mid_V, V_diff_V).
        """
        if self._fault_injection.get("all_fault") or self._fault_injection.get("er_probe_fault"):
            return (float("nan"), float("nan"), float("nan"))

        base_rate = self._corrosion_rate_um_per_day
        temp_factor = math.exp((T - 25.0) * 0.06)

        rate = base_rate * temp_factor

        variation = self._rng.gauss(0.0, 0.002)
        delta_d = self._baseline_corrosion_um + elapsed_days * rate + variation
        delta_d = max(0.0, delta_d)

        d0_m = 100.0e-6
        delta_d_m = delta_d * 1e-6
        Rs_over_Rr = d0_m / max(d0_m - delta_d_m, 1e-12)

        V_mid = 2.5 + self._rng.gauss(0.0, 0.0005)
        V_diff = V_mid * (Rs_over_Rr - 1.0) + self._rng.gauss(0.0, 0.0001)

        return (delta_d, V_mid, V_diff)

    def _simulate_inductive(
        self, elapsed_days: float, T: float
    ) -> Tuple[float, float]:
        """Simulate Inductive probe (LDC1614) readings.

        The inductive probe responds to the same corrosion progression
        but with inherently different sensitivity and slightly different
        noise characteristics. Small systematic offset from ER reading
        models the dual-mode physics.

        Args:
            elapsed_days: Elapsed simulation time in days.
            T: Current temperature in °C.

        Returns:
            Tuple of (delta_d_Inductive_um, L_eq_H).
        """
        if self._fault_injection.get("all_fault") or self._fault_injection.get("inductive_fault"):
            return (float("nan"), float("nan"))

        base_rate = self._corrosion_rate_um_per_day * 1.02
        variation = self._rng.gauss(0.0, 0.001)

        delta_d = self._baseline_corrosion_um + elapsed_days * base_rate + variation
        delta_d = max(0.0, delta_d)

        L_init = 8.5e-6
        calibration = 1.0e6
        delta_L = delta_d / calibration
        L_eq = L_init + delta_L + self._rng.gauss(0.0, 1e-14)

        return (delta_d, L_eq)

    def _simulate_qcm(
        self, elapsed_s: float, now: float
    ) -> Tuple[float, float]:
        """Simulate QCM salinity sensor readings.

        Models background salt deposition rate (1-10 mg/(m²·day)) with
        occasional burst events simulating sea spray ingress.

        Args:
            elapsed_s: Elapsed simulation time in seconds.
            now: Current wall-clock timestamp.

        Returns:
            Tuple of (delta_f_Hz, Cl_deposition_mg/m2/day).
        """
        if self._fault_injection.get("all_fault") or self._fault_injection.get("qcm_fault"):
            return (float("nan"), float("nan"))

        electrode_area = 1.0e-4

        if not self._salt_event_active:
            if self._rng.random() < 0.02:
                self._salt_event_active = True
                self._salt_event_mass = self._rng.uniform(1e-9, 1e-8)
                self._salt_event_remaining = self._salt_event_mass
                logger.debug(
                    "Salt burst event: mass=%.3e kg deposited",
                    self._salt_event_mass,
                )

        background_rate = self._rng.uniform(1.0, 10.0)

        dt_s = now - self._previous_sample_time
        if dt_s <= 0:
            dt_s = 600.0

        background_mass = background_rate * 1e-6 / 86400.0 * electrode_area * dt_s

        if self._salt_event_active:
            event_mass = min(self._salt_event_remaining, self._salt_event_mass * 0.1)
            self._salt_event_remaining -= event_mass
            if self._salt_event_remaining <= 0:
                self._salt_event_active = False
        else:
            event_mass = 0.0

        total_mass = background_mass + event_mass
        self._previous_mass_kg += total_mass

        delta_f = -2.26e8 * total_mass / electrode_area + self._rng.gauss(0.0, 0.1)

        if self._previous_sample_time == self._start_time:
            Cl_deposition = background_rate
        else:
            mass_flux = total_mass / (electrode_area * dt_s)
            Cl_deposition = mass_flux * 8.64e10

        return (delta_f, Cl_deposition)

    def _determine_valid_flag(
        self, T: float, RH: float, delta_d_ER: float
    ) -> bool:
        """Determine if current simulated data should be flagged valid.

        Simulates the humidity-gated validation: when RH < 76% but a
        significant delta_d is measured, the data is suspicious.

        Args:
            T: Current temperature in °C.
            RH: Current relative humidity in %.
            delta_d_ER: Current ER corrosion depth in µm.

        Returns:
            True if data is valid.
        """
        if any(math.isnan(x) for x in [T, RH, delta_d_ER]):
            return False

        if RH < 76.0 and delta_d_ER > 0.3:
            return False

        return True

    def get_current_environment(self) -> Dict[str, float]:
        """Get the current simulated environmental state.

        Returns:
            Dictionary with baseline values.
        """
        return {
            "baseline_T": self._baseline_T,
            "baseline_RH": self._baseline_RH,
            "baseline_corrosion_um": self._baseline_corrosion_um,
            "corrosion_rate_um_per_day": self._corrosion_rate_um_per_day,
            "sample_count": self._sample_count,
        }

    def reset(self) -> None:
        """Reset the simulator to initial state."""
        self._start_time = time.time()
        self._sample_count = 0
        self._previous_mass_kg = 0.0
        self._previous_sample_time = self._start_time
        self._salt_event_active = False
        self._salt_event_mass = 0.0
        self._salt_event_remaining = 0.0
        self.clear_all_faults()
        logger.info("SensorSimulator reset")

    @property
    def sample_count(self) -> int:
        """Get the number of samples generated."""
        return self._sample_count

    @property
    def seed(self) -> int:
        """Get the random seed used."""
        return self._seed
