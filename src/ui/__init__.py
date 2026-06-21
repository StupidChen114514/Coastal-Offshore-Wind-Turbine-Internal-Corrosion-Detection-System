"""用户界面模块 — 基于PySide6的桌面监控界面"""

from .main_window import MainWindow
from .styles import DARK_THEME_QSS
from .widgets import (
    SensorDisplayWidget,
    AlarmBadge,
    EtaGaugeWidget,
    StatusIndicator,
    TrendArrow,
)

__all__ = [
    "MainWindow",
    "DARK_THEME_QSS",
    "SensorDisplayWidget",
    "AlarmBadge",
    "EtaGaugeWidget",
    "StatusIndicator",
    "TrendArrow",
]
