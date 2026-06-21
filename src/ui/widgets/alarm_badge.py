"""告警等级徽章控件"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont


class AlarmBadge(QWidget):
    """彩色圆形告警等级徽章: 红色4级 / 橙色3级 / 黄色2级 / 蓝色1级"""

    _LEVEL_COLORS = {
        4: "#ef5350",
        3: "#ffa726",
        2: "#fdd835",
        1: "#42a5f5",
    }

    _LEVEL_LABELS = {
        4: "4",
        3: "3",
        2: "2",
        1: "1",
    }

    def __init__(self, level: int = 1, parent=None):
        super().__init__(parent)
        self._level = level
        self.setFixedSize(24, 24)

    def set_level(self, level: int):
        self._level = max(1, min(4, level))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        color = QColor(self._LEVEL_COLORS.get(self._level, "#42a5f5"))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawEllipse(2, 2, 20, 20)

        painter.setPen(QPen(QColor("#ffffff")))
        font = QFont("Microsoft YaHei", 10, QFont.Bold)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, str(self._level))
