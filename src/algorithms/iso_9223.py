"""
ISO 9223:2012 and ISO 9224:2012 atmospheric corrosivity assessment.

Implements the full ISO standard classification for atmospheric corrosivity
based on Time of Wetness (TOW), chloride deposition rate, and measured
first-year corrosion rates. Includes long-term corrosion prediction via
the power law model from ISO 9224.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TOWGrade(Enum):
    """ISO 9223 Time of Wetness grade classification.

    Each grade maps to a specific range of annual wet hours
    where T > 0°C and RH > 80%.
    """

    TAU1 = (1, "τ1", 0, 10, "Very short")
    TAU2 = (2, "τ2", 10, 250, "Short")
    TAU3 = (3, "τ3", 250, 2500, "Medium")
    TAU4 = (4, "τ4", 2500, 5500, "Long")
    TAU5 = (5, "τ5", 5500, float("inf"), "Very long")

    def __init__(self, num: int, label: str, lo: float, hi: float, desc: str) -> None:
        self._num = num
        self._label = label
        self._lo = lo
        self._hi = hi
        self._desc = desc

    @property
    def number(self) -> int:
        return self._num

    @property
    def label(self) -> str:
        return self._label

    @property
    def lower_bound(self) -> float:
        return self._lo

    @property
    def upper_bound(self) -> float:
        return self._hi

    @property
    def description(self) -> str:
        return self._desc

    def __str__(self) -> str:
        return f"{self._label} ({self._desc})"


class CorrosivityCategory(Enum):
    """ISO 9223 corrosivity categories for carbon steel.

    Based on first-year corrosion rate (r_corr) in μm/year.
    """

    C1 = (1, "C1", 0, 1.3, "Very Low")
    C2 = (2, "C2", 1.3, 25, "Low")
    C3 = (3, "C3", 25, 50, "Medium")
    C4 = (4, "C4", 50, 80, "High")
    C5 = (5, "C5", 80, 200, "Very High")
    CX = (6, "CX", 200, float("inf"), "Extreme")

    def __init__(self, num: int, label: str, lo: float, hi: float, desc: str) -> None:
        self._num = num
        self._label = label
        self._lo = lo
        self._hi = hi
        self._desc = desc

    @property
    def number(self) -> int:
        return self._num

    @property
    def label(self) -> str:
        return self._label

    @property
    def lower_bound(self) -> float:
        return self._lo

    @property
    def upper_bound(self) -> float:
        return self._hi

    @property
    def description(self) -> str:
        return self._desc

    def __str__(self) -> str:
        return f"{self._label} ({self._desc})"


class SalinityGrade(Enum):
    """ISO 9223 chloride deposition rate classification.

    S0-S3 based on Cl⁻ deposition in mg/(m²·day).
    """

    S0 = (0, "S0", 0, 3, "Negligible")
    S1 = (1, "S1", 3, 60, "Moderate")
    S2 = (2, "S2", 60, 300, "High")
    S3 = (3, "S3", 300, float("inf"), "Very High")

    def __init__(self, num: int, label: str, lo: float, hi: float, desc: str) -> None:
        self._num = num
        self._label = label
        self._lo = lo
        self._hi = hi
        self._desc = desc

    @property
    def number(self) -> int:
        return self._num

    @property
    def label(self) -> str:
        return self._label

    @property
    def lower_bound(self) -> float:
        return self._lo

    @property
    def upper_bound(self) -> float:
        return self._hi

    @property
    def description(self) -> str:
        return self._desc

    def __str__(self) -> str:
        return f"{self._label} ({self._desc})"


@dataclass
class ISOResult:
    """Complete ISO 9223/9224 assessment result container.

    Attributes:
        assessment_time: UTC timestamp when the assessment was performed.
        tow_grade: Time of Wetness grade (τ1-τ5).
        tow_hours_per_year: Projected annual TOW in hours.
        corrosivity_category: Measured/derived corrosivity category (C1-CX).
        corrosion_rate_um_per_year: First-year corrosion rate in μm/year.
        salinity_grade: Chloride deposition grade (S0-S3).
        cl_deposition_mg_per_m2_day: Average Cl⁻ deposition rate.
        estimated_category: Environmentally estimated corrosivity category.
        measured_vs_estimated_comparison: Comparison dictionary.
        long_term_prediction: ISO 9224 power law predictions.
        assessment_summary: Human-readable summary string.
        needs_alarm: Whether the assessment triggered an alarm.
        alarm_message: Alarm message if applicable.
    """

    assessment_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tow_grade: Optional[TOWGrade] = None
    tow_hours_per_year: float = 0.0
    corrosivity_category: Optional[CorrosivityCategory] = None
    corrosion_rate_um_per_year: float = 0.0
    salinity_grade: Optional[SalinityGrade] = None
    cl_deposition_mg_per_m2_day: float = 0.0
    estimated_category: Optional[CorrosivityCategory] = None
    measured_vs_estimated_comparison: Dict[str, Any] = field(default_factory=dict)
    long_term_prediction: Dict[int, float] = field(default_factory=dict)
    assessment_summary: str = ""
    needs_alarm: bool = False
    alarm_message: str = ""
    data_period_days: float = 0.0
    total_records: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assessment_time": self.assessment_time.isoformat(),
            "tow_grade": self.tow_grade.label if self.tow_grade else None,
            "tow_grade_description": self.tow_grade.description if self.tow_grade else None,
            "tow_hours_per_year": self.tow_hours_per_year,
            "corrosivity_category": self.corrosivity_category.label if self.corrosivity_category else None,
            "corrosivity_description": self.corrosivity_category.description if self.corrosivity_category else None,
            "corrosion_rate_um_per_year": self.corrosion_rate_um_per_year,
            "salinity_grade": self.salinity_grade.label if self.salinity_grade else None,
            "salinity_description": self.salinity_grade.description if self.salinity_grade else None,
            "cl_deposition_mg_per_m2_day": self.cl_deposition_mg_per_m2_day,
            "estimated_category": self.estimated_category.label if self.estimated_category else None,
            "estimated_description": self.estimated_category.description if self.estimated_category else None,
            "measured_vs_estimated": self.measured_vs_estimated_comparison,
            "long_term_prediction": self.long_term_prediction,
            "assessment_summary": self.assessment_summary,
            "needs_alarm": self.needs_alarm,
            "alarm_message": self.alarm_message,
            "data_period_days": self.data_period_days,
            "total_records": self.total_records,
        }


class ISO9223Assessor:
    """Core ISO 9223:2012 and ISO 9224:2012 assessment engine.

    Provides classification of environmental parameters into standard
    ISO grades and prediction of long-term corrosion using the power
    law model.

    Classification references:
        - ISO 9223:2012 - Corrosivity of atmospheres
        - ISO 9224:2012 - Guiding values for corrosivity categories
    """

    TOW_CORROSIVITY_TABLE: Dict[TOWGrade, Dict[SalinityGrade, CorrosivityCategory]] = {
        TOWGrade.TAU1: {
            SalinityGrade.S0: CorrosivityCategory.C1,
            SalinityGrade.S1: CorrosivityCategory.C1,
            SalinityGrade.S2: CorrosivityCategory.C1,
            SalinityGrade.S3: CorrosivityCategory.C2,
        },
        TOWGrade.TAU2: {
            SalinityGrade.S0: CorrosivityCategory.C1,
            SalinityGrade.S1: CorrosivityCategory.C2,
            SalinityGrade.S2: CorrosivityCategory.C2,
            SalinityGrade.S3: CorrosivityCategory.C3,
        },
        TOWGrade.TAU3: {
            SalinityGrade.S0: CorrosivityCategory.C2,
            SalinityGrade.S1: CorrosivityCategory.C3,
            SalinityGrade.S2: CorrosivityCategory.C4,
            SalinityGrade.S3: CorrosivityCategory.C4,
        },
        TOWGrade.TAU4: {
            SalinityGrade.S0: CorrosivityCategory.C3,
            SalinityGrade.S1: CorrosivityCategory.C4,
            SalinityGrade.S2: CorrosivityCategory.C5,
            SalinityGrade.S3: CorrosivityCategory.C5,
        },
        TOWGrade.TAU5: {
            SalinityGrade.S0: CorrosivityCategory.C4,
            SalinityGrade.S1: CorrosivityCategory.C5,
            SalinityGrade.S2: CorrosivityCategory.CX,
            SalinityGrade.S3: CorrosivityCategory.CX,
        },
    }

    DEFAULT_B_EXPONENT: float = 0.523
    DEFAULT_PREDICTION_YEARS: List[int] = [1, 5, 10, 25]

    def classify_tow_grade(self, tow_hours_per_year: float) -> TOWGrade:
        """Classify annual Time of Wetness into τ1-τ5 grade.

        Args:
            tow_hours_per_year: Projected annual TOW in hours.

        Returns:
            Corresponding TOWGrade enum value.
        """
        tow = float(tow_hours_per_year)

        if tow < 0:
            logger.warning("TOW hours negative (%.1f), treating as 0", tow)
            tow = 0.0

        for grade in TOWGrade:
            if grade.lower_bound < tow <= grade.upper_bound:
                logger.debug("TOW %.1f h/year classified as %s", tow, grade.label)
                return grade

        return TOWGrade.TAU5

    def classify_corrosivity(self, corrosion_rate_um_per_year: float) -> CorrosivityCategory:
        """Classify measured first-year corrosion rate into C1-CX category.

        Args:
            corrosion_rate_um_per_year: First-year corrosion rate in μm/year.

        Returns:
            Corresponding CorrosivityCategory enum value.
        """
        rate = float(corrosion_rate_um_per_year)

        if rate < 0:
            logger.warning("Negative corrosion rate (%.3f μm/year), treating as 0", rate)
            rate = 0.0

        for category in CorrosivityCategory:
            if category.lower_bound < rate <= category.upper_bound:
                logger.debug("Corrosion rate %.3f μm/year classified as %s", rate, category.label)
                return category

        return CorrosivityCategory.CX

    def classify_salinity(self, cl_deposition_mg_per_m2_day: float) -> SalinityGrade:
        """Classify Cl⁻ deposition rate into S0-S3 grade.

        Args:
            cl_deposition_mg_per_m2_day: Chloride deposition in mg/(m²·day).

        Returns:
            Corresponding SalinityGrade enum value.
        """
        cl = float(cl_deposition_mg_per_m2_day)

        if cl < 0:
            logger.warning("Negative Cl⁻ deposition (%.3f), treating as 0", cl)
            cl = 0.0

        for grade in SalinityGrade:
            if grade.lower_bound < cl <= grade.upper_bound:
                logger.debug("Cl⁻ %.3f mg/(m²·day) classified as %s", cl, grade.label)
                return grade

        return SalinityGrade.S3

    def estimate_category_from_environment(
        self,
        tow_grade: TOWGrade,
        salinity_grade: SalinityGrade,
    ) -> CorrosivityCategory:
        """Estimate corrosivity category from environmental parameters.

        Uses the ISO 9223 informative Annex look-up table that combines
        TOW grade and salinity grade to produce an estimated corrosivity
        category for carbon steel.

        Args:
            tow_grade: Time of Wetness grade (τ1-τ5).
            salinity_grade: Chloride deposition grade (S0-S3).

        Returns:
            Estimated CorrosivityCategory.
        """
        estimated = self.TOW_CORROSIVITY_TABLE.get(tow_grade, {}).get(salinity_grade)

        if estimated is None:
            logger.error(
                "No look-up entry for TOW=%s, Salinity=%s, defaulting to CX",
                tow_grade.label, salinity_grade.label,
            )
            estimated = CorrosivityCategory.CX

        logger.debug(
            "Environmental estimation: TOW=%s + Salinity=%s → %s",
            tow_grade.label, salinity_grade.label, estimated.label,
        )
        return estimated

    def compare_measured_vs_estimated(
        self,
        measured: CorrosivityCategory,
        estimated: CorrosivityCategory,
    ) -> Dict[str, Any]:
        """Compare measured corrosivity category against environmental estimate.

        A difference of 2 or more category levels triggers an alarm,
        suggesting either measurement error or unexpected environmental
        acceleration (e.g. coating failure, localized corrosion).

        Args:
            measured: Corrosivity category from measured corrosion rate.
            estimated: Corrosivity category from environmental estimation.

        Returns:
            Dictionary with comparison details.
        """
        diff = abs(measured.number - estimated.number)
        alarm = diff >= 2

        if diff == 0:
            message = f"Measured ({measured.label}) matches estimated ({estimated.label})"
        elif not alarm:
            message = (
                f"Minor deviation: measured {measured.label} vs estimated "
                f"{estimated.label} (1 level)"
            )
        else:
            message = (
                f"Significant deviation: measured {measured.label} vs estimated "
                f"{estimated.label} ({diff} levels). Investigation recommended."
            )

        logger.info("Measured vs Estimated: %s", message)

        return {
            "measured": str(measured),
            "measured_label": measured.label,
            "estimated": str(estimated),
            "estimated_label": estimated.label,
            "difference": diff,
            "alarm": alarm,
            "message": message,
        }

    def predict_long_term(
        self,
        first_year_rate_um: float,
        years: Optional[List[int]] = None,
        b_exponent: float = DEFAULT_B_EXPONENT,
    ) -> Dict[int, float]:
        """Predict cumulative corrosion depth using ISO 9224 power law model.

        The power law model is:
            D(t) = r_corr_year1 × t^b

        where:
            D(t) is the cumulative corrosion depth at year t in μm
            r_corr_year1 is the first-year corrosion rate in μm/year
            t is the exposure time in years
            b is the metal-environment-specific time exponent

        For carbon steel, b ≈ 0.523 per ISO 9224.

        Args:
            first_year_rate_um: First-year corrosion rate in μm/year.
            years: List of years to predict for (default: [1, 5, 10, 25]).
            b_exponent: Power law exponent (default: 0.523 for carbon steel).

        Returns:
            Dictionary mapping year to cumulative corrosion depth in μm.
        """
        if years is None:
            years = self.DEFAULT_PREDICTION_YEARS

        rate = float(first_year_rate_um)
        if rate < 0:
            logger.warning("Negative first-year rate (%.3f), using 0", rate)
            rate = 0.0

        predictions: Dict[int, float] = {}
        for year in sorted(years):
            depth = rate * (float(year) ** b_exponent)
            predictions[year] = round(depth, 3)
            logger.debug("Year %d: cumulative depth = %.3f μm", year, depth)

        return predictions

    def generate_assessment_report(
        self,
        measured_rate: float,
        tow_hours: float,
        cl_deposition: float,
        first_year_rate: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generate a comprehensive ISO 9223/9224 assessment report.

        Performs full classification and comparison, producing a
        JSON-serializable report suitable for storage and display.

        Args:
            measured_rate: Measured/derived corrosion rate in μm/year.
            tow_hours: Projected annual Time of Wetness in hours.
            cl_deposition: Average Cl⁻ deposition rate in mg/(m²·day).
            first_year_rate: Optional first-year rate for long-term prediction.
                If None, uses measured_rate.

        Returns:
            Dictionary with all classification results and predictions.
        """
        effective_rate = first_year_rate if first_year_rate is not None else measured_rate

        tow_grade = self.classify_tow_grade(tow_hours)
        corr_category = self.classify_corrosivity(effective_rate)
        sal_grade = self.classify_salinity(cl_deposition)
        estimated = self.estimate_category_from_environment(tow_grade, sal_grade)
        comparison = self.compare_measured_vs_estimated(corr_category, estimated)
        predictions = self.predict_long_term(effective_rate)

        needs_alarm = comparison.get("alarm", False)

        if needs_alarm:
            alarm_msg = (
                f"ISO 9223 ALARM: {comparison.get('message', '')}. "
                f"TOW={tow_grade.label}({tow_hours:.0f}h), "
                f"Cl⁻={sal_grade.label}({cl_deposition:.1f} mg/m²/day), "
                f"Measured={corr_category.label}, Estimated={estimated.label}"
            )
        else:
            alarm_msg = ""

        summary = (
            f"ISO 9223 Assessment: TOW Grade {tow_grade.label} ({tow_hours:.0f} h/year), "
            f"Salinity {sal_grade.label} ({cl_deposition:.1f} mg/m²/day), "
            f"Corrosivity {corr_category.label} ({effective_rate:.2f} μm/year), "
            f"Estimated {estimated.label}. "
            f"{'⚠ ALARM' if needs_alarm else '✓ Normal'}: {comparison.get('message', '')}"
        )

        logger.info("ISO 9223 Assessment Report: %s", summary)

        report = {
            "tow_grade": tow_grade.label,
            "tow_grade_description": tow_grade.description,
            "tow_hours_per_year": tow_hours,
            "corrosivity_category": corr_category.label,
            "corrosivity_description": corr_category.description,
            "corrosion_rate_um_per_year": effective_rate,
            "salinity_grade": sal_grade.label,
            "salinity_description": sal_grade.description,
            "cl_deposition_mg_per_m2_day": cl_deposition,
            "estimated_category": estimated.label,
            "estimated_description": estimated.description,
            "measured_vs_estimated": comparison,
            "long_term_prediction_um": predictions,
            "assessment_summary": summary,
            "needs_alarm": needs_alarm,
            "alarm_message": alarm_msg,
        }

        return report
