"""连接状态指示灯控件"""

from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PySide6.QtCore import Qt, QTimer, Property
from PySide6.QtGui import QPainter, QColor, QBrush, QPen


class _IndicatorDot(QWidget):
    """绘制圆形状态指示灯"""

    def __init__(self, color: str = "#66bb6a", size: int = 10, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size + 4, size + 4)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self._color))
        cx = self.width() / 2
        cy = self.height() / 2
        r = self._size / 2
        painter.drawEllipse(int(cx - r), int(cy - r), self._size, self._size)


class StatusIndicator(QWidget):
    """连接状态指示灯 + 文字"""

    ONLINE = "online"
    OFFLINE = "offline"
    WARNING = "warning"

    _COLOR_MAP = {
        "online": "#66bb6a",
        "offline": "#ef5350",
        "warning": "#ffa726",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = self.ONLINE

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._dot = _IndicatorDot(self._COLOR_MAP[self._status], 8)
        self._label = QLabel("在线")
        self._label.setStyleSheet("color: #b0b0c0; font-size: 12px; background: transparent;")

        layout.addWidget(self._dot)
        layout.addWidget(self._label)
        layout.addStretch()

    def set_status(self, status: str):
        self._status = status
        color = self._COLOR_MAP.get(status, self._COLOR_MAP["offline"])
        self._dot.set_color(color)
        labels = {"online": "在线", "offline": "离线", "warning": "警告"}
        self._label.setText(labels.get(status, "未知"))

    @property
    def status(self) -> str:
        return self._status
