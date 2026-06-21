"""η因子半圆仪表盘控件"""

import math

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QPainterPath, QLinearGradient
)


class EtaGaugeWidget(QWidget):
    """η因子半圆仪表盘: 0.5~10.0范围, 指针式显示"""

    MIN_VALUE = 0.5
    MAX_VALUE = 10.0
    GREEN_MAX = 2.0
    YELLOW_MAX = 3.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 1.0
        self.setMinimumSize(180, 130)

    def set_value(self, value: float):
        self._value = max(self.MIN_VALUE, min(self.MAX_VALUE, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h * 0.85
        radius = min(w, int(h * 1.4)) / 2 - 10

        self._draw_arc_background(painter, cx, cy, radius)
        self._draw_needle(painter, cx, cy, radius)
        self._draw_labels(painter, cx, cy, radius)
        self._draw_digital(painter, w, h)

    def _draw_arc_background(self, painter: QPainter, cx: float, cy: float, r: float):
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        pen = QPen(Qt.NoPen)
        painter.setPen(pen)

        total_range = self.MAX_VALUE - self.MIN_VALUE
        green_end = (self.GREEN_MAX - self.MIN_VALUE) / total_range * 180
        yellow_end = (self.YELLOW_MAX - self.MIN_VALUE) / total_range * 180

        green = QColor("#66bb6a")
        yellow = QColor("#ffa726")
        red = QColor("#ef5350")

        painter.setBrush(QBrush(green))
        painter.drawPie(rect, int(180 * 16), int(green_end * 16))

        painter.setBrush(QBrush(yellow))
        painter.drawPie(rect, int((180 + green_end) * 16), int((yellow_end - green_end) * 16))

        painter.setBrush(QBrush(red))
        painter.drawPie(rect, int((180 + yellow_end) * 16), int((180 - yellow_end) * 16))

        inner_r = r * 0.65
        inner_rect = QRectF(cx - inner_r, cy - inner_r, 2 * inner_r, 2 * inner_r)
        painter.setBrush(QBrush(QColor("#1e1e2e")))
        painter.drawEllipse(inner_rect)

    def _draw_needle(self, painter: QPainter, cx: float, cy: float, r: float):
        total_range = self.MAX_VALUE - self.MIN_VALUE
        angle = 180 - (self._value - self.MIN_VALUE) / total_range * 180
        rad = math.radians(angle)

        needle_len = r * 0.55
        ex = cx + needle_len * math.cos(rad)
        ey = cy - needle_len * math.sin(rad)

        pen = QPen(QColor("#ffffff"), 2, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(int(cx), int(cy), int(ex), int(ey))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawEllipse(int(cx - 5), int(cy - 5), 10, 10)

    def _draw_labels(self, painter: QPainter, cx: float, cy: float, r: float):
        font = QFont("Microsoft YaHei", 8)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#b0b0c0")))

        for val, label in [(0.5, "0.5"), (2.0, "2.0"), (3.0, "3.0"), (6.0, "6.0"), (10.0, "10.0")]:
            angle = 180 - (val - self.MIN_VALUE) / (self.MAX_VALUE - self.MIN_VALUE) * 180
            rad = math.radians(angle)
            label_r = r * 0.88
            lx = cx + label_r * math.cos(rad) - 10
            ly = cy - label_r * math.sin(rad) + 5
            painter.drawText(int(lx), int(ly), label)

        cat_font = QFont("Microsoft YaHei", 8, QFont.Bold)
        painter.setFont(cat_font)
        painter.setPen(QPen(QColor("#66bb6a")))
        painter.drawText(int(cx - r * 0.62), int(cy - r * 0.15), "安全")
        painter.setPen(QPen(QColor("#ffa726")))
        painter.drawText(int(cx + r * 0.05), int(cy - r * 0.55), "警告")
        painter.setPen(QPen(QColor("#ef5350")))
        painter.drawText(int(cx + r * 0.45), int(cy - r * 0.15), "危险")

    def _draw_digital(self, painter: QPainter, w: int, h: int):
        font = QFont("Microsoft YaHei", 18, QFont.Bold)
        painter.setFont(font)

        if self._value <= self.GREEN_MAX:
            color = QColor("#66bb6a")
        elif self._value <= self.YELLOW_MAX:
            color = QColor("#ffa726")
        else:
            color = QColor("#ef5350")

        painter.setPen(QPen(color))
        painter.drawText(QRectF(0, h * 0.72, w, 30), Qt.AlignCenter, f"η = {self._value:.2f}")
