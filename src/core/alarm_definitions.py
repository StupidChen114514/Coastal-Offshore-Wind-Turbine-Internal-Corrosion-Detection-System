"""
Alarm type definitions and metadata for the Wind Turbine Internal
Corrosion Detection System.

Defines the complete four-level alarm hierarchy mapped to specific
detection conditions, severity labels, message templates, and
auto-resolve conditions.
"""

from .data_models import AlarmLevel

_ALARM_LEVEL_MAP = {
    1: AlarmLevel.LEVEL_1,
    2: AlarmLevel.LEVEL_2,
    3: AlarmLevel.LEVEL_3,
    4: AlarmLevel.LEVEL_4,
}

ALARM_DEFINITIONS = {
    "SENSOR_COMM_FAILURE": {
        "level": 2,
        "severity": "\u4e00\u822c",
        "message_template": "\u4f20\u611f\u5668 {sensor_id} \u901a\u4fe1\u6545\u969c: {error_detail}",
        "auto_resolve_condition": "sensor_reconnected",
    },
    "CURRENT_SOURCE_UNSTABLE": {
        "level": 2,
        "severity": "\u4e00\u822c",
        "message_template": "\u6052\u6d41\u6e90\u77ed\u671f\u7a33\u5b9a\u6027\u5f02\u5e38: \u6ce2\u52a8\u7387 {fluctuation_rate:.2%}",
        "auto_resolve_condition": "stability_restored",
    },
    "D_TEMP_SHOCK_DIFF_GT_15PCT": {
        "level": 2,
        "severity": "\u4e00\u822c",
        "message_template": "\u6e29\u5ea6\u51b2\u51fb\uff0c\u53cc\u6a21\u5f0f\u5dee\u5f02 > 15%: diff = {diff:.2%}",
        "auto_resolve_condition": "temperature_stabilized",
    },
    "CORROSION_ABNORMAL_ACCELERATION": {
        "level": 3,
        "severity": "\u9ad8\u7ea7",
        "message_template": "\u8150\u8680\u5f02\u5e38\u52a0\u901f: \u5b9e\u6d4b/\u9884\u6d4b\u6bd4\u503c = {ratio:.2f}",
        "auto_resolve_condition": "acceleration_normalized",
    },
    "PITTING_RISK": {
        "level": 3,
        "severity": "\u9ad8\u7ea7",
        "message_template": "\u975e\u5747\u5300\u8150\u8680/\u70b9\u8680\u98ce\u9669: \u03b7 = {eta:.2f}",
        "auto_resolve_condition": "eta_normalized",
    },
    "SEVERE_PITTING_PERFORATION": {
        "level": 4,
        "severity": "\u7d27\u6025",
        "message_template": "\u4e25\u91cd\u70b9\u8680\uff0c\u7a7f\u5b54\u98ce\u9669: \u03b7 = {eta:.2f}",
        "auto_resolve_condition": "manual_only",
    },
    "REFERENCE_RING_DRIFT": {
        "level": 3,
        "severity": "\u9ad8\u7ea7",
        "message_template": "\u53c2\u8003\u73af\u6d82\u5c42\u53ef\u80fd\u5931\u6548: \u6f02\u79fb\u7387 {drift_rate:.2%}",
        "auto_resolve_condition": "manual_only",
    },
    "CONSECUTIVE_FALSE_SIGNALS": {
        "level": 3,
        "severity": "\u9ad8\u7ea7",
        "message_template": "\u8fde\u7eed\u865a\u5047\u4fe1\u53f7\u8d85\u8fc7\u9608\u503c: {count}\u6b21",
        "auto_resolve_condition": "signal_normalized",
    },
    "DUAL_SENSOR_FAILURE": {
        "level": 4,
        "severity": "\u7d27\u6025",
        "message_template": "\u53cc\u4f20\u611f\u5668\u540c\u65f6\u6545\u969c",
        "auto_resolve_condition": "manual_only",
    },
    "CORROSION_THRESHOLD_80PCT": {
        "level": 4,
        "severity": "\u7d27\u6025",
        "message_template": "\u7d2f\u8ba1\u8150\u8680\u8d85\u8fc7\u5b89\u5168\u9608\u503c\u768480%: {current_depth:.1f}\u03bcm",
        "auto_resolve_condition": "manual_only",
    },
    "ENVIRONMENT_RAPID_CHANGE": {
        "level": 1,
        "severity": "\u4fe1\u606f",
        "message_template": "\u73af\u5883\u5267\u70c8\u53d8\u5316: dT/dt = {dt_dt:.1f}\u00b0C/10min",
        "auto_resolve_condition": "environment_stabilized",
    },
    "TEMPERATURE_SHOCK": {
        "level": 2,
        "severity": "\u4e00\u822c",
        "message_template": "\u6e29\u5ea6\u51b2\u51fb\uff0cER\u53ef\u80fd\u542b\u4f2a\u4fe1\u53f7: diff = {diff:.2%}",
        "auto_resolve_condition": "temperature_stabilized",
    },
    "EMERGENCY_MODE": {
        "level": 1,
        "severity": "\u4fe1\u606f",
        "message_template": "\u8fdb\u5165\u5e94\u6025\u91c7\u6837\u6a21\u5f0f, \u539f\u56e0: {reason}",
        "auto_resolve_condition": "emergency_mode_exited",
    },
    "PROBE_CIRCUIT_ANOMALY": {
        "level": 3,
        "severity": "\u9ad8\u7ea7",
        "message_template": "\u63a2\u5934/\u7535\u8def\u5f02\u5e38: {detail}",
        "auto_resolve_condition": "manual_only",
    },
    "MEASURED_ESTIMATED_DISCREPANCY": {
        "level": 3,
        "severity": "\u9ad8\u7ea7",
        "message_template": "\u5b9e\u6d4b\u8150\u8680\u7b49\u7ea7\u6bd4\u4f30\u8ba1\u9ad8{delta}\u7ea7\u4ee5\u4e0a",
        "auto_resolve_condition": "discrepancy_resolved",
    },
}


def get_alarm_definition(alarm_type_key: str) -> dict:
    return ALARM_DEFINITIONS.get(alarm_type_key, {})


def get_alarm_level(alarm_type_key: str) -> AlarmLevel:
    definition = ALARM_DEFINITIONS.get(alarm_type_key, {})
    level_int = definition.get("level", 1)
    return _ALARM_LEVEL_MAP.get(level_int, AlarmLevel.LEVEL_1)


def format_alarm_message(alarm_type_key: str, details: dict) -> str:
    definition = ALARM_DEFINITIONS.get(alarm_type_key)
    if definition is None:
        return f"\u672a\u77e5\u544a\u8b66\u7c7b\u578b: {alarm_type_key}"
    template = definition.get("message_template", "")
    try:
        return template.format(**details)
    except (KeyError, ValueError):
        return f"{template} (\u53c2\u6570\u4e0d\u5b8c\u6574)"
