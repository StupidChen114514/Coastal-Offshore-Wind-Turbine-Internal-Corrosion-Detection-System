"""
ISO 9223/9224 assessment orchestrator for the corrosion detection system.

Bridges the gap between raw sensor data, processed corrosion records,
and the ISO standard classification engine. Provides assessment execution
and historical retrieval capabilities.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..core.data_models import CorrosionRecord, SensorData
from .dose_response import predict_corrosion_rate
from .iso_9223 import (
    ISOResult,
    ISO9223Assessor,
    CorrosivityCategory,
    SalinityGrade,
    TOWGrade,
)
from .tow_calculator import TOWCalculator

logger = logging.getLogger(__name__)

HOURS_PER_YEAR = 8760.0


class ISOAssessmentEngine:
    """Orchestrates ISO 9223/9224 standard compliance assessment.

    Consumes processed corrosion records and raw sensor data to produce
    comprehensive ISO assessment results, including:
        - TOW grade classification
        - Corrosivity category from measured rates
        - Salinity grade from Cl⁻ deposition
        - Environmental estimation of corrosivity
        - Measured vs estimated comparison with alarms
        - ISO 9224 long-term corrosion prediction

    Usage:
        engine = ISOAssessmentEngine(app_instance)
        result = engine.assess(corrosion_records, sensor_data)
    """

    def __init__(self, app_instance: Any = None) -> None:
        self._app = app_instance
        self._assessor = ISO9223Assessor()
        self._tow_calculator = TOWCalculator()
        self._history: List[ISOResult] = []

    def assess(
        self,
        corrosion_records: List[CorrosionRecord],
        sensor_data: List[SensorData],
    ) -> ISOResult:
        """Execute a complete ISO 9223/9224 assessment.

        Processes all available data to compute:
            1. Annual TOW projection from sensor data
            2. Effective corrosion rate from corrosion records
            3. Average Cl⁻ deposition rate
            4. Full ISO classification and prediction

        Args:
            corrosion_records: Processed CorrosionRecord objects.
            sensor_data: Raw SensorData objects for TOW and Cl⁻ computation.

        Returns:
            ISOResult with complete assessment data.

        Raises:
            ValueError: If both corrosion_records and sensor_data are empty.
        """
        if not corrosion_records and not sensor_data:
            raise ValueError("At least one of corrosion_records or sensor_data must be non-empty")

        tow_hours = self._compute_tow_from_sensors(sensor_data)
        cl_avg = self._compute_average_cl_deposition(sensor_data)

        effective_rate = self._compute_effective_corrosion_rate(corrosion_records, sensor_data)
        first_year_rate = self._estimate_first_year_rate(corrosion_records)

        result = self._build_result(
            tow_hours=tow_hours,
            cl_avg=cl_avg,
            effective_rate=effective_rate,
            first_year_rate=first_year_rate,
            total_records=len(corrosion_records),
            sensor_data_count=len(sensor_data),
            data_period_days=self._compute_data_period(corrosion_records, sensor_data),
        )

        self._history.append(result)
        self._emit_alarm_if_needed(result)

        logger.info(
            "ISO assessment complete: TOW=%s(%.0fh), Cl=%s(%.1f), "
            "Corrosivity=%s(%.2f μm/year), Estimated=%s, Alarm=%s",
            result.tow_grade.label if result.tow_grade else "?",
            result.tow_hours_per_year,
            result.salinity_grade.label if result.salinity_grade else "?",
            result.cl_deposition_mg_per_m2_day,
            result.corrosivity_category.label if result.corrosivity_category else "?",
            result.corrosion_rate_um_per_year,
            result.estimated_category.label if result.estimated_category else "?",
            result.needs_alarm,
        )

        return result

    def get_assessment_history(self, year: Optional[int] = None) -> List[ISOResult]:
        """Retrieve historical ISO assessments.

        Args:
            year: Optional year filter. If provided, returns only assessments
                from that calendar year.

        Returns:
            List of ISOResult objects.
        """
        if year is None:
            return list(self._history)

        return [
            r for r in self._history
            if r.assessment_time.year == year
        ]

    def get_latest_assessment(self) -> Optional[ISOResult]:
        """Get the most recent assessment result.

        Returns:
            The latest ISOResult, or None if no assessment has been run.
        """
        if not self._history:
            return None
        return self._history[-1]

    def clear_history(self) -> None:
        """Clear all stored assessment history."""
        self._history.clear()
        logger.info("ISO assessment history cleared")

    def _compute_tow_from_sensors(self, sensor_data: List[SensorData]) -> float:
        """Compute projected annual Time of Wetness from sensor data.

        Each unique hour with T > 0°C and RH > 80% counts as one wet hour.
        The accumulated TOW is projected to an annual rate based on the
        total sampling period.

        Args:
            sensor_data: List of sensor readings.

        Returns:
            Projected annual TOW in hours/year.
        """
        if not sensor_data:
            return 0.0

        tow_calc = TOWCalculator()

        processed_hours: set = set()
        for record in sensor_data:
            hour_key = record.timestamp.replace(minute=0, second=0, microsecond=0)
            if hour_key not in processed_hours:
                processed_hours.add(hour_key)
                tow_calc.add_hour(record.T, record.RH)

        annual_tow = tow_calc.get_annual_tow()
        logger.debug(
            "TOW computed from %d sensor records: %d unique hours, %.1f h/year projected",
            len(sensor_data), len(processed_hours), annual_tow,
        )
        return annual_tow

    def _compute_average_cl_deposition(self, sensor_data: List[SensorData]) -> float:
        """Compute arithmetic mean of Cl⁻ deposition rate.

        Args:
            sensor_data: List of sensor readings.

        Returns:
            Average Cl⁻ deposition in mg/(m²·day).
        """
        if not sensor_data:
            return 0.0

        valid_cl = [s.Cl_deposition for s in sensor_data if s.valid_flag]
        if not valid_cl:
            valid_cl = [s.Cl_deposition for s in sensor_data]

        avg = sum(valid_cl) / len(valid_cl)
        logger.debug("Average Cl⁻ deposition: %.3f mg/(m²·day) from %d records", avg, len(valid_cl))
        return avg

    def _compute_effective_corrosion_rate(
        self,
        corrosion_records: List[CorrosionRecord],
        sensor_data: List[SensorData],
    ) -> float:
        """Determine the best available corrosion rate for classification.

        Priority:
            1. Average CR_out from valid corrosion records
            2. Dose-response predicted rate from environmental averages
            3. 0.0 if no data available

        Args:
            corrosion_records: Processed corrosion records.
            sensor_data: Raw sensor data for dose-response prediction fallback.

        Returns:
            Effective corrosion rate in μm/year.
        """
        valid_records = [r for r in corrosion_records if r.valid_flag]
        if not valid_records:
            valid_records = corrosion_records

        if valid_records:
            cr_values = [r.CR_out for r in valid_records if r.CR_out > 0]
            if cr_values:
                avg_cr = sum(cr_values) / len(cr_values)
                logger.debug("Effective CR from records: %.3f μm/year (%d records)", avg_cr, len(cr_values))
                return avg_cr

        if sensor_data:
            T_avg, RH_avg, Cl_avg = self._compute_environmental_averages(sensor_data)
            r_pred, _ = predict_corrosion_rate(T_avg, RH_avg, Cl_avg)
            logger.debug("Effective CR from dose-response: %.3f μm/year", r_pred)
            return r_pred

        logger.warning("No corrosion rate data available, returning 0.0")
        return 0.0

    def _estimate_first_year_rate(
        self,
        corrosion_records: List[CorrosionRecord],
    ) -> Optional[float]:
        """Estimate first-year corrosion rate for long-term prediction.

        If the system has been running less than a year, projects the
        accumulated rate to an annual equivalent.

        Args:
            corrosion_records: Processed corrosion records.

        Returns:
            Estimated first-year rate in μm/year, or None if unavailable.
        """
        if not corrosion_records:
            return None

        sorted_records = sorted(corrosion_records, key=lambda r: r.timestamp)
        first_ts = sorted_records[0].timestamp
        last_ts = sorted_records[-1].timestamp
        period_days = max((last_ts - first_ts).total_seconds() / 86400.0, 1.0 / 24.0)

        total_thickness_loss = 0.0
        prev_delta_d = None
        for record in sorted_records:
            if record.valid_flag and record.delta_d_filtered > 0:
                if prev_delta_d is not None and record.delta_d_filtered > prev_delta_d:
                    total_thickness_loss += record.delta_d_filtered - prev_delta_d
                prev_delta_d = record.delta_d_filtered

        if total_thickness_loss <= 0 and sorted_records:
            total_thickness_loss = sorted_records[-1].delta_d_filtered

        if total_thickness_loss <= 0:
            return None

        annual_rate = total_thickness_loss * (365.0 / period_days)
        logger.debug(
            "First-year rate estimate: %.3f μm over %.1f days → %.3f μm/year",
            total_thickness_loss, period_days, annual_rate,
        )
        return annual_rate

    def _compute_environmental_averages(
        self, sensor_data: List[SensorData]
    ) -> Tuple[float, float, float]:
        """Compute average T, RH, Cl from sensor data.

        Args:
            sensor_data: List of sensor readings.

        Returns:
            Tuple of (T_avg, RH_avg, Cl_avg).
        """
        if not sensor_data:
            return 0.0, 0.0, 0.0

        n = len(sensor_data)
        T_sum = sum(s.T for s in sensor_data)
        RH_sum = sum(s.RH for s in sensor_data)
        Cl_sum = sum(s.Cl_deposition for s in sensor_data)

        return T_sum / n, RH_sum / n, Cl_sum / n

    def _compute_data_period(
        self,
        corrosion_records: List[CorrosionRecord],
        sensor_data: List[SensorData],
    ) -> float:
        """Compute the data collection period in days.

        Args:
            corrosion_records: Processed corrosion records.
            sensor_data: Raw sensor data.

        Returns:
            Data period in days.
        """
        all_data = list(corrosion_records) + list(sensor_data)
        if not all_data:
            return 0.0

        timestamps = [d.timestamp for d in all_data]
        period_seconds = (max(timestamps) - min(timestamps)).total_seconds()
        return max(period_seconds / 86400.0, 0.0)

    def _build_result(
        self,
        tow_hours: float,
        cl_avg: float,
        effective_rate: float,
        first_year_rate: Optional[float],
        total_records: int,
        sensor_data_count: int,
        data_period_days: float,
    ) -> ISOResult:
        """Build a complete ISOResult from computed parameters.

        Args:
            tow_hours: Projected annual TOW.
            cl_avg: Average Cl⁻ deposition.
            effective_rate: Effective corrosion rate.
            first_year_rate: Estimated first-year rate.
            total_records: Number of corrosion records.
            sensor_data_count: Number of sensor data points.
            data_period_days: Data collection period in days.

        Returns:
            Populated ISOResult.
        """
        tow_grade = self._assessor.classify_tow_grade(tow_hours)
        corr_category = self._assessor.classify_corrosivity(effective_rate)
        sal_grade = self._assessor.classify_salinity(cl_avg)
        estimated = self._assessor.estimate_category_from_environment(tow_grade, sal_grade)
        comparison = self._assessor.compare_measured_vs_estimated(corr_category, estimated)

        pred_rate = first_year_rate if first_year_rate is not None else effective_rate
        predictions = self._assessor.predict_long_term(pred_rate)

        needs_alarm = comparison.get("alarm", False)

        if needs_alarm:
            alarm_msg = (
                f"ISO 9223 ALARM: {comparison.get('message', '')}. "
                f"TOW={tow_grade.label}({tow_hours:.0f}h), "
                f"Cl⁻={sal_grade.label}({cl_avg:.1f} mg/m²/day), "
                f"Measured={corr_category.label}, Estimated={estimated.label}"
            )
        else:
            alarm_msg = ""

        summary = (
            f"ISO 9223 Assessment: TOW Grade {tow_grade.label} ({tow_hours:.0f} h/year), "
            f"Salinity {sal_grade.label} ({cl_avg:.1f} mg/m²/day), "
            f"Corrosivity {corr_category.label} ({effective_rate:.2f} μm/year), "
            f"Estimated {estimated.label}. "
            f"{'⚠ ALARM' if needs_alarm else '✓ Normal'}: {comparison.get('message', '')}"
        )

        return ISOResult(
            assessment_time=datetime.now(timezone.utc),
            tow_grade=tow_grade,
            tow_hours_per_year=tow_hours,
            corrosivity_category=corr_category,
            corrosion_rate_um_per_year=effective_rate,
            salinity_grade=sal_grade,
            cl_deposition_mg_per_m2_day=cl_avg,
            estimated_category=estimated,
            measured_vs_estimated_comparison=comparison,
            long_term_prediction=predictions,
            assessment_summary=summary,
            needs_alarm=needs_alarm,
            alarm_message=alarm_msg,
            data_period_days=data_period_days,
            total_records=total_records,
        )

    def _emit_alarm_if_needed(self, result: ISOResult) -> None:
        """Emit an alarm signal through the app if assessment triggers one.

        Args:
            result: The ISOResult to check for alarm conditions.
        """
        if not result.needs_alarm or self._app is None:
            return

        try:
            self._app.emit("alarm_raised", {
                "type": "ISO_ASSESSMENT",
                "message": result.alarm_message,
                "details": result.to_dict(),
            })
            logger.warning("ISO assessment alarm emitted: %s", result.alarm_message)
        except Exception:
            logger.exception("Failed to emit ISO assessment alarm")
