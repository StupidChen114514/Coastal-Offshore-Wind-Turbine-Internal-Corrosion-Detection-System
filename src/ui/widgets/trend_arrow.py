"""趋势箭头控件"""

from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt


class TrendArrow(QLabel):
    """趋势方向指示器：▲上升 / ▼下降 / ─平稳"""

    UP = "up"
    DOWN = "down"
    FLAT = "flat"

    _COLORS = {
        "up": "#66bb6a",
        "down": "#ef5350",
        "flat": "#9e9e9e",
    }

    _SYMBOLS = {
        "up": "▲",
        "down": "▼",
        "flat": "─",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._direction = self.FLAT
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(24, 24)
        self._render()

    def set_direction(self, direction: str):
        if direction not in (self.UP, self.DOWN, self.FLAT):
            direction = self.FLAT
        self._direction = direction
        self._render()

    def set_trend(self, current: float, previous: float, threshold: float = 0.001):
        if abs(current - previous) < threshold:
            self._direction = self.FLAT
        elif current > previous:
            self._direction = self.UP
        else:
            self._direction = self.DOWN
        self._render()

    @property
    def direction(self) -> str:
        return self._direction

    def _render(self):
        color = self._COLORS.get(self._direction, self._COLORS["flat"])
        symbol = self._SYMBOLS.get(self._direction, self._SYMBOLS["flat"])
        self.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {color}; "
            f"background-color: transparent;"
        )
        self.setText(symbol)
