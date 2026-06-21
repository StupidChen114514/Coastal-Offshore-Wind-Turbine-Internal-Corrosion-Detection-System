"""
Dose-response function for corrosion rate prediction in offshore environments.

Implements Equation (25) from the technical specification for predicting
corrosion rates based on environmental parameters, with cross-validation
against measured rates to detect abnormal behavior.
"""

import logging
import math
from typing import Tuple

logger = logging.getLogger(__name__)

VERDICT_NORMAL = "NORMAL"
VERDICT_ABNORMAL_ACCELERATION = "ABNORMAL_ACCELERATION"
VERDICT_COATING_EFFECTIVE = "COATING_EFFECTIVE"


def predict_corrosion_rate(
    T_avg: float, RH_avg: float, Cl_avg: float
) -> Tuple[float, float]:
    """
    Predict corrosion rate using the dose-response function.

    Implements Equation (25):
        r_pred = 0.102 × [Cl⁻]^0.62 × e^(0.033×RH + 0.040×T)

    [SO₂] is assumed ≈ 0 for offshore wind (no industrial pollution).

    Args:
        T_avg: Average temperature in °C.
        RH_avg: Average relative humidity in %.
        Cl_avg: Average chloride deposition rate in mg/m²/day.

    Returns:
        Tuple of (r_pred, confidence):
            - r_pred: Predicted corrosion rate in μm/year.
            - confidence: Confidence factor in [0, 1] based on input validity.
    """
    T = float(T_avg)
    RH = float(RH_avg)
    Cl = float(Cl_avg)

    if Cl < 0 or RH < 0 or RH > 100:
        logger.warning(
            "Dose-response: Invalid input values T=%.1f, RH=%.1f, Cl=%.3f",
            T, RH, Cl,
        )
        return 0.0, 0.0

    confidence = 1.0

    if Cl <= 0:
        confidence = 0.0
        Cl_safe = 1e-6
    else:
        Cl_safe = Cl

    if RH <= 0:
        confidence = max(0.0, confidence - 0.3)
        RH_safe = 0.1
    else:
        RH_safe = RH

    if T < -50 or T > 80:
        confidence = max(0.0, confidence - 0.3)

    try:
        exponent = 0.033 * RH_safe + 0.040 * T
        exponent = max(-50.0, min(50.0, exponent))

        r_pred = 0.102 * (Cl_safe ** 0.62) * math.exp(exponent)
    except (OverflowError, ValueError):
        logger.error(
            "Dose-response: Numerical overflow T=%.1f, RH=%.1f, Cl=%.3f",
            T, RH, Cl,
        )
        return 0.0, 0.0

    if not math.isfinite(r_pred):
        return 0.0, 0.0

    r_pred = max(0.0, r_pred)

    logger.debug(
        "Dose-response predicted r=%.4f μm/year (T=%.1f, RH=%.1f, Cl=%.3f, confidence=%.2f)",
        r_pred, T, RH, Cl, confidence,
    )

    return r_pred, confidence


def cross_validate(
    r_meas: float, r_pred: float
) -> Tuple[float, str, int]:
    """
    Cross-validate measured corrosion rate against dose-response prediction.

    The ratio r_meas / r_pred is interpreted as follows:
        - [0.5, 2.0]: NORMAL corrosion behavior
        - > 2.0: ABNORMAL_ACCELERATION (possible coating failure or localized attack)
        - < 0.5: COATING_EFFECTIVE (protective coating functioning)

    Args:
        r_meas: Measured corrosion rate in μm/year.
        r_pred: Predicted corrosion rate from dose-response function in μm/year.

    Returns:
        Tuple of (ratio, verdict, alarm_level):
            - ratio: r_meas / r_pred, or float('inf') if r_pred ≈ 0.
            - verdict: One of "NORMAL", "ABNORMAL_ACCELERATION", "COATING_EFFECTIVE".
            - alarm_level: 0 = normal, 1 = acceleration warning, 2 = acceleration alarm.
    """
    r_meas = float(r_meas)
    r_pred = float(r_pred)

    if r_meas < 0:
        logger.debug("Cross-validate: Negative measured rate %.4f, treating as 0", r_meas)
        r_meas = 0.0

    if r_pred <= 1e-9:
        if r_meas > 1e-9:
            logger.debug("Cross-validate: r_pred ≈ 0 but r_meas > 0, ratio → inf")
            return float("inf"), VERDICT_ABNORMAL_ACCELERATION, 1
        else:
            return 1.0, VERDICT_NORMAL, 0

    try:
        ratio = r_meas / r_pred
    except (ZeroDivisionError, ValueError):
        return float("inf"), VERDICT_ABNORMAL_ACCELERATION, 1

    if not math.isfinite(ratio):
        return float("inf"), VERDICT_ABNORMAL_ACCELERATION, 1

    if 0.5 <= ratio <= 2.0:
        verdict = VERDICT_NORMAL
        alarm_level = 0
    elif ratio > 2.0:
        verdict = VERDICT_ABNORMAL_ACCELERATION
        alarm_level = 2 if ratio > 4.0 else 1
    else:
        verdict = VERDICT_COATING_EFFECTIVE
        alarm_level = 0

    logger.debug(
        "Cross-validate: r_meas=%.4f / r_pred=%.4f = %.3f → %s (alarm_level=%d)",
        r_meas, r_pred, ratio, verdict, alarm_level,
    )

    return ratio, verdict, alarm_level
