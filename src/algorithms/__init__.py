"""Error compensation and data processing algorithms."""

from .algorithm_engine import AlgorithmEngine
from .calibration_curve import (
    CalibrationCurve,
    DEFAULT_CALIBRATION_POINTS,
    INTERP_LINEAR,
    INTERP_POLYNOMIAL,
)
from .cross_validation import CrossValidationEngine
from .dose_response import (
    cross_validate,
    predict_corrosion_rate,
    VERDICT_ABNORMAL_ACCELERATION,
    VERDICT_COATING_EFFECTIVE,
    VERDICT_NORMAL,
)
from .dual_mode_validator import DualModeValidator
from .iso_9223 import (
    CorrosivityCategory,
    ISO9223Assessor,
    ISOResult,
    SalinityGrade,
    TOWGrade,
)
from .iso_assessment import ISOAssessmentEngine
from .kalman_filter import KalmanFilter, MIN_WARMUP_SAMPLES
from .tow_calculator import TOWCalculator

__all__ = [
    "AlgorithmEngine",
    "CalibrationCurve",
    "CorrosivityCategory",
    "CrossValidationEngine",
    "DEFAULT_CALIBRATION_POINTS",
    "DualModeValidator",
    "INTERP_LINEAR",
    "INTERP_POLYNOMIAL",
    "ISO9223Assessor",
    "ISOAssessmentEngine",
    "ISOResult",
    "KalmanFilter",
    "MIN_WARMUP_SAMPLES",
    "SalinityGrade",
    "TOWGrade",
    "TOWCalculator",
    "cross_validate",
    "predict_corrosion_rate",
    "VERDICT_ABNORMAL_ACCELERATION",
    "VERDICT_COATING_EFFECTIVE",
    "VERDICT_NORMAL",
]
