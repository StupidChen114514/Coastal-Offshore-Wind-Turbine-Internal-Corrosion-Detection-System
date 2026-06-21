"""
Time of Wetness (TOW) calculator per ISO 9223.

Accumulates hours where T > 0°C AND RH > 80% to compute
annual Time of Wetness for corrosion rate normalization.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TOWCalculator:
    """
    Accumulates Time of Wetness hours per ISO 9223.

    A "wet" hour is defined as an hour where temperature exceeds 0°C
    and relative humidity exceeds 80%. The accumulated TOW is used
    to normalize corrosion rates to standard reference conditions.

    TOW grades per ISO 9223:
        τ1: TOW ≤ 10 h/year
        τ2: 10 < TOW ≤ 250 h/year
        τ3: 250 < TOW ≤ 2500 h/year
        τ4: 2500 < TOW ≤ 5500 h/year
        τ5: 5500 < TOW ≤ 8760 h/year
    """

    TOW_GRADE_BOUNDARIES = [10, 250, 2500, 5500, 8760]

    def __init__(self) -> None:
        self._tow_hours: float = 0.0
        self._total_hours: float = 0.0

    def add_hour(self, T: float, RH: float) -> bool:
        """
        Evaluate one hour of environmental data and increment TOW if wet.

        Args:
            T: Temperature in °C.
            RH: Relative humidity in %.

        Returns:
            True if the hour was counted as wet, False otherwise.
        """
        self._total_hours += 1.0

        if T > 0.0 and RH > 80.0:
            self._tow_hours += 1.0
            return True
        return False

    def get_tow_hours(self) -> float:
        """
        Return accumulated Time of Wetness in hours.

        Returns:
            Total wet hours accumulated.
        """
        return self._tow_hours

    def get_annual_tow(self) -> float:
        """
        Project TOW to an annual rate based on accumulated data.

        If fewer than 24 hours have been recorded, returns 0.0.

        Returns:
            Projected annual TOW in hours/year.
        """
        if self._total_hours < 24.0:
            return 0.0

        return self._tow_hours * (8760.0 / self._total_hours)

    def get_tow_grade(self) -> str:
        """
        Determine the ISO 9223 TOW grade.

        Returns:
            ISO 9223 grade string: τ1, τ2, τ3, τ4, or τ5.
        """
        annual_tow = self.get_annual_tow()
        if annual_tow <= 0:
            return "τ1"

        for i, boundary in enumerate(self.TOW_GRADE_BOUNDARIES, start=1):
            if annual_tow <= boundary:
                return f"τ{i}"

        return "τ5"

    def reset(self) -> None:
        """Reset all accumulated counters to zero."""
        self._tow_hours = 0.0
        self._total_hours = 0.0
        logger.debug("TOW calculator statistics reset")
