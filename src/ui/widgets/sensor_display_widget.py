"""传感器数据显示控件"""

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from .trend_arrow import TrendArrow


class SensorDisplayWidget(QFrame):
    """可复用的传感器值显示：图标、数值、趋势、时间"""

    clicked = Signal()

    _WARNING_COLORS = {
        0: "#2a2a3e",
        2: "#5a4a00",
        3: "#5a3000",
        4: "#5a1a1a",
    }

    def __init__(self, name: str, icon: str, unit: str, parent=None):
        super().__init__(parent)
        self._name = name
        self._unit = unit
        self._value = 0.0
        self._previous_value = 0.0
        self._warning_level = 0

        self.setObjectName("sensorFrame")
        self.setFrameStyle(QFrame.Box)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        self._icon_label = QLabel(icon)
        self._icon_label.setStyleSheet("font-size: 20px; background: transparent;")
        header_layout.addWidget(self._icon_label)
        header_layout.addStretch()

        self._trend_arrow = TrendArrow()
        header_layout.addWidget(self._trend_arrow)
        layout.addLayout(header_layout)

        self._name_label = QLabel(name)
        self._name_label.setStyleSheet(
            "color: #b0b0c0; font-size: 11px; font-weight: bold; background: transparent;"
        )
        layout.addWidget(self._name_label)

        value_layout = QHBoxLayout()
        value_layout.setSpacing(4)

        self._value_label = QLabel("--.--")
        self._value_label.setObjectName("sensorValueLabel")
        value_layout.addWidget(self._value_label)

        self._unit_label = QLabel(unit)
        self._unit_label.setObjectName("sensorUnitLabel")
        value_layout.addWidget(self._unit_label)

        value_layout.addStretch()
        layout.addLayout(value_layout)

        self._time_label = QLabel("--:--:--")
        self._time_label.setStyleSheet(
            "color: #606070; font-size: 10px; background: transparent;"
        )
        layout.addWidget(self._time_label)

    def _apply_style(self):
        from ..styles import DARK_THEME_QSS
        self.setStyleSheet(
            "SensorDisplayWidget {"
            f"  background-color: {self._WARNING_COLORS.get(0)}; "
            "  border: 1px solid #3a3a4e; "
            "  border-radius: 8px; "
            "}"
            "SensorDisplayWidget:hover {"
            "  border-color: #4fc3f7; "
            "}"
        )

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def update_value(self, value: float, timestamp: str = ""):
        self._previous_value = self._value
        self._value = value
        self._value_label.setText(f"{value:.2f}")
        self._trend_arrow.set_trend(value, self._previous_value)
        if timestamp:
            self._time_label.setText(timestamp)

    def set_warning_level(self, level: int):
        self._warning_level = level
        bg = self._WARNING_COLORS.get(level, self._WARNING_COLORS[0])
        self.setStyleSheet(
            f"SensorDisplayWidget {{"
            f"  background-color: {bg}; "
            f"  border: 1px solid #3a3a4e; "
            f"  border-radius: 8px; "
            f"}}"
            f"SensorDisplayWidget:hover {{"
            f"  border-color: #4fc3f7; "
            f"}}"
        )

    @property
    def value(self) -> float:
        return self._value
