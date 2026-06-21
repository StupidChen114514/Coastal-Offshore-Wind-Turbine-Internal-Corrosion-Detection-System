"""
Data model definitions for the Wind Turbine Internal Corrosion Detection System.

Uses @dataclass for clean, type-hinted data structures that represent
sensor readings, corrosion records, alarms, configuration, and audit logs.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4


class AlarmLevel(Enum):
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4


class AlarmStatus(Enum):
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    AUTO_RESOLVED = "AUTO_RESOLVED"


class AlarmType(Enum):
    CORROSION_RATE = "CORROSION_RATE"
    THICKNESS_LOSS = "THICKNESS_LOSS"
    SENSOR_FAULT = "SENSOR_FAULT"
    COMMUNICATION_ERROR = "COMMUNICATION_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    SENSOR_COMM_FAILURE = "SENSOR_COMM_FAILURE"
    CURRENT_SOURCE_UNSTABLE = "CURRENT_SOURCE_UNSTABLE"
    CORROSION_ABNORMAL_ACCELERATION = "CORROSION_ABNORMAL_ACCELERATION"
    PITTING_RISK = "PITTING_RISK"
    SEVERE_PITTING_PERFORATION = "SEVERE_PITTING_PERFORATION"
    REFERENCE_RING_DRIFT = "REFERENCE_RING_DRIFT"
    CONSECUTIVE_FALSE_SIGNALS = "CONSECUTIVE_FALSE_SIGNALS"
    DUAL_SENSOR_FAILURE = "DUAL_SENSOR_FAILURE"
    CORROSION_THRESHOLD_80PCT = "CORROSION_THRESHOLD_80PCT"
    ENVIRONMENT_RAPID_CHANGE = "ENVIRONMENT_RAPID_CHANGE"
    TEMPERATURE_SHOCK = "TEMPERATURE_SHOCK"
    EMERGENCY_MODE = "EMERGENCY_MODE"
    PROBE_CIRCUIT_ANOMALY = "PROBE_CIRCUIT_ANOMALY"
    MEASURED_ESTIMATED_DISCREPANCY = "MEASURED_ESTIMATED_DISCREPANCY"


class OperationType(Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    RESOLVE = "RESOLVE"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    SYSTEM_START = "SYSTEM_START"
    SYSTEM_STOP = "SYSTEM_STOP"
    SYSTEM_RESTART = "SYSTEM_RESTART"


@dataclass
class SensorData:
    """Raw sensor reading from the corrosion detection hardware.

    Attributes:
        timestamp: UTC timestamp of the reading.
        T: Temperature in °C.
        RH: Relative humidity in %.
        Cl_deposition: Chloride deposition rate in mg/m²/day.
        delta_d_ER: Thickness loss from Electrical Resistance sensor in μm.
        delta_d_Inductive: Thickness loss from Inductive sensor in μm.
        V_mid: Midpoint voltage of bridge circuit in V.
        V_diff: Differential voltage of bridge circuit in V.
        L_eq: Equivalent inductance in H.
        delta_f: Frequency shift in Hz.
        valid_flag: Whether the reading passed validation checks.
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    T: float = 0.0
    RH: float = 0.0
    Cl_deposition: float = 0.0
    delta_d_ER: float = 0.0
    delta_d_Inductive: float = 0.0
    V_mid: float = 0.0
    V_diff: float = 0.0
    L_eq: float = 0.0
    delta_f: float = 0.0
    valid_flag: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "T": self.T,
            "RH": self.RH,
            "Cl_deposition": self.Cl_deposition,
            "delta_d_ER": self.delta_d_ER,
            "delta_d_Inductive": self.delta_d_Inductive,
            "V_mid": self.V_mid,
            "V_diff": self.V_diff,
            "L_eq": self.L_eq,
            "delta_f": self.delta_f,
            "valid_flag": self.valid_flag,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SensorData":
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        return cls(
            timestamp=timestamp or datetime.now(timezone.utc),
            T=data.get("T", 0.0),
            RH=data.get("RH", 0.0),
            Cl_deposition=data.get("Cl_deposition", 0.0),
            delta_d_ER=data.get("delta_d_ER", 0.0),
            delta_d_Inductive=data.get("delta_d_Inductive", 0.0),
            V_mid=data.get("V_mid", 0.0),
            V_diff=data.get("V_diff", 0.0),
            L_eq=data.get("L_eq", 0.0),
            delta_f=data.get("delta_f", 0.0),
            valid_flag=data.get("valid_flag", True),
        )


@dataclass
class CorrosionRecord:
    """Processed corrosion measurement record.

    Attributes:
        timestamp: UTC timestamp.
        delta_d_raw: Raw thickness loss in μm (before compensation).
        delta_d_corrected: Temperature-compensated thickness loss in μm.
        delta_d_filtered: Filtered thickness loss in μm.
        CR_ER: Electrical Resistance corrosion rate in mm/year.
        CR_Inductive: Inductive corrosion rate in mm/year.
        CR_out: Fused corrosion rate output in mm/year.
        eta: Corrosion efficiency factor.
        valid_flag: Whether the record is valid.
        status: Processing status string.
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    delta_d_raw: float = 0.0
    delta_d_corrected: float = 0.0
    delta_d_filtered: float = 0.0
    CR_ER: float = 0.0
    CR_Inductive: float = 0.0
    CR_out: float = 0.0
    eta: float = 0.0
    valid_flag: bool = True
    status: str = "OK"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "delta_d_raw": self.delta_d_raw,
            "delta_d_corrected": self.delta_d_corrected,
            "delta_d_filtered": self.delta_d_filtered,
            "CR_ER": self.CR_ER,
            "CR_Inductive": self.CR_Inductive,
            "CR_out": self.CR_out,
            "eta": self.eta,
            "valid_flag": self.valid_flag,
            "status": self.status,
        }


@dataclass
class AlarmRecord:
    """Alarm record for corrosion rate threshold violations.

    Attributes:
        alarm_id: Unique UUID for the alarm.
        timestamp: UTC timestamp when the alarm was raised.
        level: Alarm severity level (1-4).
        alarm_type: Type of alarm (corrosion rate, thickness loss, etc.).
        details: Additional details as a dictionary.
        sensor_id: Identifier of the sensor that triggered the alarm.
        status: Current alarm status.
        operator: Name of the operator who acknowledged/resolved.
        resolved_time: UTC timestamp when the alarm was resolved.
    """

    alarm_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    level: AlarmLevel = AlarmLevel.LEVEL_1
    alarm_type: AlarmType = AlarmType.CORROSION_RATE
    details: Dict[str, Any] = field(default_factory=dict)
    sensor_id: str = ""
    status: AlarmStatus = AlarmStatus.ACTIVE
    operator: Optional[str] = None
    resolved_time: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alarm_id": str(self.alarm_id),
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "alarm_type": self.alarm_type.value,
            "details": self.details,
            "sensor_id": self.sensor_id,
            "status": self.status.value,
            "operator": self.operator,
            "resolved_time": self.resolved_time.isoformat() if self.resolved_time else None,
        }


@dataclass
class ConfigData:
    """Configuration data container with nested structures.

    Attributes:
        version: Configuration version string.
        description: Human-readable description.
        sensor: Sensor configuration parameters.
        sampling: Sampling configuration parameters.
        algorithm: Algorithm configuration parameters.
        alarm: Alarm threshold configuration.
        comms: Communication configuration parameters.
        storage: Data storage configuration.
        logging: Logging configuration.
    """

    version: str = "1.0.0"
    description: str = ""
    sensor: Dict[str, Any] = field(default_factory=dict)
    sampling: Dict[str, Any] = field(default_factory=dict)
    algorithm: Dict[str, Any] = field(default_factory=dict)
    alarm: Dict[str, Any] = field(default_factory=dict)
    comms: Dict[str, Any] = field(default_factory=dict)
    storage: Dict[str, Any] = field(default_factory=dict)
    logging: Dict[str, Any] = field(default_factory=dict)

    def get_value(self, path: str, default: Any = None) -> Any:
        """Get a configuration value by dot-separated path.

        Args:
            path: Dot-separated path, e.g. 'sensor.d0.value'.
            default: Default value if path not found.

        Returns:
            The configuration value, or default if not found.
        """
        keys = path.split(".")
        current: Any = self.__dict__
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return default
            if current is None:
                return default
        return current


@dataclass
class AuditLogEntry:
    """Audit log entry for tracking operator actions.

    Attributes:
        timestamp: UTC timestamp of the action.
        operator: Name of the operator performing the action.
        operation_type: Type of operation performed.
        details: Additional operation details.
        result: Result of the operation (success/failure).
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    operator: str = ""
    operation_type: OperationType = OperationType.CREATE
    details: Dict[str, Any] = field(default_factory=dict)
    result: str = "success"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "operator": self.operator,
            "operation_type": self.operation_type.value,
            "details": self.details,
            "result": self.result,
        }


class DualModeStatus:
    DUAL_CONSISTENT = "DUAL_CONSISTENT"
    TEMPERATURE_SHOCK = "TEMPERATURE_SHOCK"
    PITTING_SUSPECTED = "PITTING_SUSPECTED"


@dataclass
class DualModeResult:
    """Result from dual-mode cross-validation analysis.

    Attributes:
        cr_out: Final fused corrosion rate output in μm/year.
        cr_er: ER probe corrosion rate in μm/year.
        cr_inductive: Inductive probe corrosion rate in μm/year.
        eta: Pitting factor from calibration curve.
        delta_d_actual: Actual maximum pitting depth in μm.
        status: Validation status (DUAL_CONSISTENT / TEMPERATURE_SHOCK / PITTING_SUSPECTED).
        alarm_level: Alarm level (0=none, 1=info, 3=warning, 4=emergency).
        verdict: Human-readable diagnosis string.
        diff: Computed relative difference between the two probe rates.
        timestamp: UTC timestamp of the analysis.
    """

    cr_out: float = 0.0
    cr_er: float = 0.0
    cr_inductive: float = 0.0
    eta: float = 1.0
    delta_d_actual: float = 0.0
    status: str = DualModeStatus.DUAL_CONSISTENT
    alarm_level: int = 0
    verdict: str = ""
    diff: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cr_out": self.cr_out,
            "cr_er": self.cr_er,
            "cr_inductive": self.cr_inductive,
            "eta": self.eta,
            "delta_d_actual": self.delta_d_actual,
            "status": self.status,
            "alarm_level": self.alarm_level,
            "verdict": self.verdict,
            "diff": self.diff,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class CrossValidationResult:
    """Combined result from corrosion processing + dual-mode cross-validation.

    Attributes:
        corrosion_record: Processed corrosion record from AlgorithmEngine.
        dual_mode_result: Dual-mode validation analysis result.
        alarms_to_trigger: List of alarm dictionaries ready for dispatch.
        final_cr: Final consolidated corrosion rate in μm/year.
        final_delta_d: Final consolidated corrosion depth in μm.
        timestamp: UTC timestamp of the processing cycle.
    """

    corrosion_record: Optional[CorrosionRecord] = None
    dual_mode_result: Optional[DualModeResult] = None
    alarms_to_trigger: List[Dict[str, Any]] = field(default_factory=list)
    final_cr: float = 0.0
    final_delta_d: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "final_cr": self.final_cr,
            "final_delta_d": self.final_delta_d,
            "timestamp": self.timestamp.isoformat(),
            "alarms_to_trigger": self.alarms_to_trigger,
        }
        if self.corrosion_record is not None:
            result["corrosion_record"] = self.corrosion_record.to_dict()
        if self.dual_mode_result is not None:
            result["dual_mode_result"] = self.dual_mode_result.to_dict()
        return result
