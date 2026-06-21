"""
Pt1000 Platinum Resistance Temperature Sensor Driver.

Implements the Callendar-Van Dusen (CVD) equation for converting between
temperature and resistance for Heraeus M222 series Class A Pt1000 sensors.

The CVD equation for T >= 0°C:
    R_T = R_0 * (1 + alpha * T + beta * T^2)

Where:
    R_0 = 1000 Ohm (resistance at 0°C)
    alpha = 3.9083e-3 /°C  (linear temperature coefficient)
    beta = -5.775e-7 /°C²  (quadratic temperature coefficient)

For T < 0°C the full CVD equation with delta term applies:
    R_T = R_0 * (1 + alpha * T + beta * T^2 + delta * (T - 100) * T^3)

Class A accuracy: ±(0.15 + 0.002 * |T|) °C
"""

import math
from typing import Tuple

from ..core.logger import CorrosionLogger

logger = CorrosionLogger().get_logger(__name__)


class Pt1000Driver:
    """Pt1000 temperature sensor driver using the Callendar-Van Dusen equation.

    Attributes:
        R_0: Resistance at 0°C (1000 Ohm).
        alpha: Linear temperature coefficient (/°C).
        beta: Quadratic temperature coefficient (/°C²).
        delta: Full CVD delta term for T < 0°C.
    """

    R_0: float = 1000.0
    alpha: float = 3.9083e-3
    beta: float = -5.775e-7
    delta: float = -1.508e-7

    @classmethod
    def resistance_from_temperature(cls, T: float) -> float:
        """Convert temperature to Pt1000 resistance using the CVD equation.

        Args:
            T: Temperature in °C.

        Returns:
            Resistance R_T in Ohm.

        Raises:
            ValueError: If T is below the sensor minimum rating (-50°C).
        """
        if T < -50.0:
            raise ValueError(
                f"Temperature {T:.2f}°C is below Pt1000 minimum rating (-50°C)"
            )

        if T >= 0.0:
            R_T = cls.R_0 * (1.0 + cls.alpha * T + cls.beta * T * T)
        else:
            R_T = cls.R_0 * (
                1.0
                + cls.alpha * T
                + cls.beta * T * T
                + cls.delta * (T - 100.0) * T * T * T
            )

        logger.debug(
            "Pt1000: T=%.4f°C -> R_T=%.4f Ohm (CVD%s)",
            T,
            R_T,
            " T>=0" if T >= 0 else " T<0",
        )
        return R_T

    @classmethod
    def temperature_from_resistance(cls, R_T: float) -> float:
        """Convert Pt1000 resistance to temperature using the inverse CVD equation.

        Uses the quadratic formula for T >= 0°C range:
            beta * T^2 + alpha * T + (1 - R_T/R_0) = 0
            => T = (-alpha + sqrt(alpha^2 - 4*beta*(1 - R_T/R_0))) / (2*beta)

        For T < 0°C, uses iterative Newton-Raphson refinement since the full
        CVD equation is a 4th-order polynomial.

        Args:
            R_T: Measured resistance in Ohm.

        Returns:
            Temperature T in °C.

        Raises:
            ValueError: If R_T is out of valid range for Pt1000.
        """
        if R_T <= 0.0:
            raise ValueError(
                f"Resistance {R_T:.4f} Ohm is invalid (must be positive)"
            )

        ratio = R_T / cls.R_0

        discriminant = cls.alpha * cls.alpha - 4.0 * cls.beta * (1.0 - ratio)

        if discriminant < 0.0:
            raise ValueError(
                f"Cannot solve CVD equation for R_T={R_T:.4f} Ohm: "
                f"discriminant={discriminant:.6e} < 0"
            )

        T = (-cls.alpha + math.sqrt(discriminant)) / (2.0 * cls.beta)

        if T < 0.0:
            T = cls._newton_raphson_solve(R_T, initial_guess=T)

        logger.debug(
            "Pt1000: R_T=%.4f Ohm -> T=%.4f°C (accuracy: ±%.4f°C)",
            R_T,
            T,
            cls._accuracy_at(T),
        )
        return T

    @classmethod
    def _newton_raphson_solve(
        cls, R_T: float, initial_guess: float, max_iterations: int = 50, tolerance: float = 1e-10
    ) -> float:
        """Solve the full CVD equation for T < 0°C using Newton-Raphson iteration.

        The full CVD equation for T < 0°C:
            f(T) = R_0 * (1 + alpha*T + beta*T² + delta*(T-100)*T³) - R_T = 0

        Args:
            R_T: Target resistance in Ohm.
            initial_guess: Starting temperature guess in °C.
            max_iterations: Maximum number of iterations.
            tolerance: Convergence tolerance in °C.

        Returns:
            Solved temperature T in °C.

        Raises:
            RuntimeError: If the solver fails to converge.
        """
        T = initial_guess
        for i in range(max_iterations):
            T2 = T * T
            T3 = T2 * T

            f_val = (
                cls.R_0 * (1.0 + cls.alpha * T + cls.beta * T2 + cls.delta * (T - 100.0) * T3)
                - R_T
            )

            df_val = cls.R_0 * (
                cls.alpha
                + 2.0 * cls.beta * T
                + cls.delta * (4.0 * T3 - 300.0 * T2)
            )

            if abs(df_val) < 1e-15:
                raise RuntimeError(
                    "Newton-Raphson derivative near zero; solver stalled"
                )

            delta_T = f_val / df_val
            T = T - delta_T

            if abs(delta_T) < tolerance:
                logger.debug(
                    "Pt1000 NR solver converged in %d iterations, T=%.6f°C",
                    i + 1,
                    T,
                )
                return T

        raise RuntimeError(
            f"Newton-Raphson solver did not converge after {max_iterations} "
            f"iterations (last T={T:.6f}°C, residual={abs(f_val):.6e})"
        )

    @classmethod
    def _accuracy_at(cls, T: float) -> float:
        """Compute the Class A accuracy at a given temperature.

        Class A accuracy: ±(0.15 + 0.002 * |T|) °C

        Args:
            T: Temperature in °C.

        Returns:
            Accuracy in °C.
        """
        return 0.15 + 0.002 * abs(T)

    @classmethod
    def get_class_a_accuracy(cls, T: float) -> Tuple[float, float]:
        """Get the Class A accuracy bounds for a given temperature.

        Args:
            T: Temperature in °C.

        Returns:
            Tuple of (lower_bound, upper_bound) in °C.
        """
        acc = cls._accuracy_at(T)
        return (T - acc, T + acc)
