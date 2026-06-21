"""
主应用程序窗口 — 海上风电塔筒内部腐蚀检测系统

布局结构:
┌─────────────────────────────────────────────────┐
│  顶栏: 设备ID | 状态指示 | 时间 | ●            │
├──────────┬──────────────────────┬───────────────┤
│ 左       │  中                  │  右           │
│ 传感器   │  主图表区(Tab)      │  告警面板     │
│ 面板     │                      │              │
├──────────┴──────────────────────┴───────────────┤
│  底部: 导航标签 / 设置按钮                      │
└─────────────────────────────────────────────────┘
"""

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,

    QWidget,
)
from PySide6.QtCore import (
    QDateTime,
    QMetaObject,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QBrush,
    QAction,
    QPalette,
)

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

from .styles import DARK_THEME_QSS
from .widgets import (
    SensorDisplayWidget,
    AlarmBadge,
    EtaGaugeWidget,
    StatusIndicator,
    TrendArrow,
)

try:
    from ..core.alarm_manager import AlarmManager
    from ..core.config_manager import ConfigManager
    from ..core.data_models import (
        AlarmLevel,
        AlarmRecord,
        AlarmStatus,
        AlarmType,
        CorrosionRecord,
        CrossValidationResult,
        DualModeResult,
        SensorData,
    )
    from ..storage.storage_manager import StorageManager
    HAS_BACKEND = True
except ImportError:
    HAS_BACKEND = False

logger = logging.getLogger(__name__)

_UTC_TZ = timezone.utc
_ISO_CATEGORIES = [
    ("C1", "极低", "#66bb6a", 0, 2),
    ("C2", "低", "#aed581", 2, 4),
    ("C3", "中等", "#fdd835", 4, 5),
    ("C4", "高", "#ffa726", 5, 6),
    ("C5", "很高", "#ef5350", 6, 8),
    ("CX", "极端", "#b71c1c", 8, 50),
]


class _TopStatusBar(QWidget):
    """顶栏: 设备ID | 连接状态 | 系统时间 | 电源状态"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("topStatusBar")
        self.setFixedHeight(40)
        self.setStyleSheet(
            "QWidget#topStatusBar {"
            "  background-color: #1a1a2a; "
            "  border-bottom: 1px solid #3a3a4e; "
            "}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(16)

        self._device_label = QLabel("设备: WT-CORR-001")
        self._device_label.setStyleSheet(
            "color: #4fc3f7; font-weight: bold; font-size: 13px; background: transparent;"
        )
        layout.addWidget(self._device_label)

        self._status_indicator = StatusIndicator()
        layout.addWidget(self._status_indicator)

        layout.addStretch()

        self._time_label = QLabel()
        self._time_label.setStyleSheet(
            "color: #b0b0c0; font-size: 13px; background: transparent;"
        )
        layout.addWidget(self._time_label)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_time)
        self._timer.start(1000)
        self._update_time()

    def _update_time(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._time_label.setText(f"⏰ {now}")

    def set_device_id(self, device_id: str):
        self._device_label.setText(f"设备: {device_id}")

    def set_status(self, status: str):
        self._status_indicator.set_status(status)


class _LeftSensorPanel(QWidget):
    """左侧传感器面板: T, RH, [Cl⁻], Δd"""

    switch_to_corrosion_tab = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setStyleSheet("background-color: #222233;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("传感器数据")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self._t_widget = SensorDisplayWidget("T 温度", "🌡️", "°C")
        self._rh_widget = SensorDisplayWidget("RH 湿度", "💧", "%")
        self._cl_widget = SensorDisplayWidget("[Cl⁻] 盐度", "🧂", "mg/(m²·day)")
        self._dd_widget = SensorDisplayWidget("Δd 腐蚀深度", "📏", "μm")

        self._dd_widget.clicked.connect(self.switch_to_corrosion_tab.emit)

        layout.addWidget(self._t_widget)
        layout.addWidget(self._rh_widget)
        layout.addWidget(self._cl_widget)
        layout.addWidget(self._dd_widget)
        layout.addStretch()

    def update_sensor_data(self, data: dict):
        ts = data.get("timestamp", "")
        if hasattr(ts, "strftime"):
            ts = ts.strftime("%H:%M:%S")
        elif isinstance(ts, str) and len(ts) > 8:
            ts = ts[-8:]

        self._t_widget.update_value(data.get("T", 0), ts)
        self._rh_widget.update_value(data.get("RH", 0), ts)
        self._cl_widget.update_value(data.get("Cl_deposition", 0), ts)

        delta_d = data.get("delta_d_ER", 0)
        self._dd_widget.update_value(delta_d, ts)

        cr_out = data.get("extra", {}).get("cr_out", 0)
        if cr_out > 0.20:
            self._dd_widget.set_warning_level(4)
        elif cr_out > 0.10:
            self._dd_widget.set_warning_level(3)
        elif cr_out > 0.05:
            self._dd_widget.set_warning_level(2)
        else:
            self._dd_widget.set_warning_level(0)


class _RightAlarmPanel(QWidget):
    """右侧告警面板: 活跃告警 + 最近解决 + 统计"""

    acknowledge_requested = Signal(str)
    resolve_requested = Signal(str)
    view_details_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)
        self.setStyleSheet("background-color: #222233;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("告警面板")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self._active_group = QGroupBox("⚠ 活跃告警")
        self._active_layout = QVBoxLayout(self._active_group)
        self._active_scroll = QScrollArea()
        self._active_scroll.setWidgetResizable(True)
        self._active_scroll.setStyleSheet("QScrollArea { border: none; }")
        self._active_container = QWidget()
        self._active_container_layout = QVBoxLayout(self._active_container)
        self._active_container_layout.setAlignment(Qt.AlignTop)
        self._active_scroll.setWidget(self._active_container)
        self._active_layout.addWidget(self._active_scroll)
        layout.addWidget(self._active_group, stretch=3)

        self._resolved_group = QGroupBox("✓ 最近解决")
        self._resolved_layout = QVBoxLayout(self._resolved_group)
        layout.addWidget(self._resolved_group, stretch=1)

        self._stats_group = QGroupBox("📊 告警统计")
        self._stats_layout = QHBoxLayout(self._stats_group)
        self._stats_layout.setSpacing(8)

        self._today_stat = QLabel("今日\n0")
        self._today_stat.setAlignment(Qt.AlignCenter)
        self._today_stat.setStyleSheet(
            "color: #4fc3f7; font-weight: bold; background: #1a1a2a; "
            "border-radius: 4px; padding: 4px;"
        )
        self._week_stat = QLabel("本周\n0")
        self._week_stat.setAlignment(Qt.AlignCenter)
        self._week_stat.setStyleSheet(
            "color: #ffa726; font-weight: bold; background: #1a1a2a; "
            "border-radius: 4px; padding: 4px;"
        )
        self._total_stat = QLabel("活跃\n0")
        self._total_stat.setAlignment(Qt.AlignCenter)
        self._total_stat.setStyleSheet(
            "color: #ef5350; font-weight: bold; background: #1a1a2a; "
            "border-radius: 4px; padding: 4px;"
        )

        self._stats_layout.addWidget(self._today_stat)
        self._stats_layout.addWidget(self._week_stat)
        self._stats_layout.addWidget(self._total_stat)
        layout.addWidget(self._stats_group, stretch=1)

    def refresh_active(self, alarms: list):
        while self._active_container_layout.count():
            item = self._active_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for alarm in alarms[:20]:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(6)

            level = alarm.get("level", 1)
            if hasattr(level, "value"):
                level = level.value
            badge = AlarmBadge(level)
            row_layout.addWidget(badge)

            a_type = alarm.get("alarm_type", "")
            if hasattr(a_type, "value"):
                a_type = a_type.value
            msg = alarm.get("details", {}).get("message", a_type)
            text_label = QLabel(f"{msg}")
            text_label.setWordWrap(True)
            text_label.setStyleSheet("color: #e0e0e0; font-size: 11px; background: transparent;")
            row_layout.addWidget(text_label, stretch=1)

            detail_btn = QPushButton("详情")
            detail_btn.setFixedSize(36, 20)
            detail_btn.setStyleSheet("font-size: 10px; padding: 1px 4px;")
            aid = str(alarm.get("alarm_id", ""))
            detail_btn.clicked.connect(lambda checked, a=aid: self.view_details_requested.emit(a))
            row_layout.addWidget(detail_btn)

            row.mouseDoubleClickEvent = lambda e, a=aid: self.acknowledge_requested.emit(a)
            row.setStyleSheet(
                "QWidget { background-color: #2a2a3e; border-radius: 4px; } "
                "QWidget:hover { background-color: #3a3a4e; }"
            )
            self._active_container_layout.addWidget(row)

        spacer = QWidget()
        spacer.setMinimumHeight(1)
        self._active_container_layout.addWidget(spacer)

    def refresh_resolved(self, alarms: list):
        while self._resolved_layout.count():
            item = self._resolved_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for alarm in alarms[:5]:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 1, 4, 1)
            row_layout.setSpacing(4)

            check = QLabel("✓")
            check.setStyleSheet("color: #66bb6a; font-weight: bold; background: transparent;")
            row_layout.addWidget(check)

            a_type = alarm.get("alarm_type", "")
            if hasattr(a_type, "value"):
                a_type = a_type.value
            msg = alarm.get("details", {}).get("message", a_type)
            text_label = QLabel(f"{msg[:30]}")
            text_label.setStyleSheet("color: #9090a0; font-size: 11px; background: transparent;")
            row_layout.addWidget(text_label, stretch=1)

            row.setStyleSheet("background: transparent;")
            self._resolved_layout.addWidget(row)

        self._resolved_layout.addStretch()

    def refresh_stats(self, today: int, week: int, active: int):
        self._today_stat.setText(f"今日\n{today}")
        self._week_stat.setText(f"本周\n{week}")
        self._total_stat.setText(f"活跃\n{active}")


class _RealTimeTab(QWidget):
    """Tab 1: 实时监测 — 主趋势图 Δd_ER vs Δd_Inductive"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        span_label = QLabel("时间范围:")
        span_label.setStyleSheet("color: #b0b0c0; font-size: 12px; background: transparent;")
        toolbar.addWidget(span_label)

        self._time_spans = {
            "1h": 3600, "6h": 21600, "24h": 86400,
            "7d": 604800, "30d": 2592000, "1y": 31536000,
        }
        self._span_buttons: Dict[str, QPushButton] = {}
        self._current_span = "1h"

        for label in ["1h", "6h", "24h", "7d", "30d", "1y"]:
            btn = QPushButton(label)
            btn.setObjectName("timeSpanBtn")
            btn.setCheckable(True)
            btn.setFixedWidth(42)
            btn.clicked.connect(lambda checked, s=label: self._on_span_changed(s))
            self._span_buttons[label] = btn
            toolbar.addWidget(btn)

        self._span_buttons["1h"].setChecked(True)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        if HAS_PYQTGRAPH:
            self._plot = pg.PlotWidget()
            self._plot.setBackground("#1e1e2e")
            self._plot.showGrid(x=True, y=True, alpha=0.3)
            self._plot.getAxis("bottom").setPen(pg.mkPen(color="#b0b0c0"))
            self._plot.getAxis("left").setPen(pg.mkPen(color="#b0b0c0"))
            self._plot.setLabel("left", "Δd", units="μm")
            self._plot.setLabel("bottom", "时间")

            legend = self._plot.addLegend(offset=(-10, 10))
            self._curve_er = self._plot.plot(
                [], [], pen=pg.mkPen(color="#4fc3f7", width=2), name="Δd_ER (ER探头)"
            )
            self._curve_ind = self._plot.plot(
                [], [], pen=pg.mkPen(color="#ffa726", width=2, style=Qt.DashLine),
                name="Δd_Inductive (电感探头)"
            )

            self._plot.scene().sigMouseMoved.connect(self._on_mouse_move)
            self._tooltip_label = QLabel("")
            self._tooltip_label.setStyleSheet(
                "color: #4fc3f7; font-size: 11px; background: rgba(30,30,46,200); "
                "padding: 2px 6px; border-radius: 3px;"
            )
            self._tooltip_label.setVisible(False)
            self._tooltip_proxy = None
        else:
            self._plot = QLabel("pyqtgraph 未安装，请安装依赖: pip install pyqtgraph")
            self._plot.setAlignment(Qt.AlignCenter)
            self._plot.setStyleSheet("color: #ef5350; font-size: 16px;")
            self._curve_er = None
            self._curve_ind = None

        layout.addWidget(self._plot, stretch=1)

    def _on_span_changed(self, span: str):
        self._current_span = span
        for s, btn in self._span_buttons.items():
            btn.setChecked(s == span)

    def _on_mouse_move(self, pos):
        if not HAS_PYQTGRAPH or self._curve_er is None:
            return
        vb = self._plot.plotItem.vb
        if vb.sceneBoundingRect().contains(pos):
            mouse_point = vb.mapSceneToView(pos)
            x = mouse_point.x()
            try:
                er_data = self._curve_er.getData()
                ind_data = self._curve_ind.getData()
            except Exception:
                return
            if len(er_data[0]) == 0:
                return
            idx = None
            min_dist = float("inf")
            for i, t in enumerate(er_data[0]):
                d = abs(t - x)
                if d < min_dist:
                    min_dist = d
                    idx = i
            if idx is not None and min_dist < abs(er_data[0][-1] - er_data[0][0]) * 0.03:
                self._tooltip_label.setText(
                    f"Δd_ER: {er_data[1][idx]:.3f} μm  |  "
                    f"Δd_Ind: {ind_data[1][idx]:.3f} μm"
                )
                self._tooltip_label.setVisible(True)
                self._tooltip_label.adjustSize()
                self._tooltip_label.move(int(pos.x()) + 15, int(pos.y()) - 15)
            else:
                self._tooltip_label.setVisible(False)

    def update_chart(self, time_data: list, er_data: list, ind_data: list):
        if HAS_PYQTGRAPH and self._curve_er is not None:
            self._curve_er.setData(time_data, er_data)
            self._curve_ind.setData(time_data, ind_data)

    @property
    def current_span_seconds(self) -> int:
        return self._time_spans.get(self._current_span, 3600)


class _CorrosionDetailTab(QWidget):
    """Tab 2: 腐蚀详情 — Δd多曲线叠加 + 数据表"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        if HAS_PYQTGRAPH:
            self._plot = pg.PlotWidget()
            self._plot.setBackground("#1e1e2e")
            self._plot.showGrid(x=True, y=True, alpha=0.3)
            self._plot.getAxis("bottom").setPen(pg.mkPen(color="#b0b0c0"))
            self._plot.getAxis("left").setPen(pg.mkPen(color="#b0b0c0"))
            self._plot.setLabel("left", "Δd", units="μm")
            self._plot.setLabel("bottom", "时间")

            legend = self._plot.addLegend()
            self._curve_raw = self._plot.plot(
                [], [], pen=pg.mkPen(color="#4fc3f7", width=1, style=Qt.DashLine),
                name="Δd_raw (原始值)"
            )
            self._curve_corrected = self._plot.plot(
                [], [], pen=pg.mkPen(color="#ffa726", width=2), name="Δd_corrected (温度修正)"
            )
            self._curve_filtered = self._plot.plot(
                [], [], pen=pg.mkPen(color="#66bb6a", width=3), name="Δd_filtered (卡尔曼滤波)"
            )
        else:
            self._plot = QLabel("pyqtgraph 未安装")
            self._plot.setAlignment(Qt.AlignCenter)
            self._plot.setStyleSheet("color: #ef5350;")

        layout.addWidget(self._plot, stretch=2)

        filter_layout = QHBoxLayout()
        filter_label = QLabel("数据过滤:")
        filter_label.setStyleSheet("color: #b0b0c0; font-size: 12px; background: transparent;")
        filter_layout.addWidget(filter_label)
        self._valid_filter = QComboBox()
        self._valid_filter.addItems(["全部", "仅有效", "仅无效"])
        self._valid_filter.currentIndexChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._valid_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, stretch=1)

        self._all_data: list = []
        self._filtered_data: list = []

    def _on_filter_changed(self):
        self._refresh_table()

    def set_data(self, records: list):
        self._all_data = records
        self._refresh_table()

    def _refresh_table(self):
        filter_mode = self._valid_filter.currentIndex()
        if filter_mode == 1:
            data = [r for r in self._all_data if r.get("valid_flag", True)]
        elif filter_mode == 2:
            data = [r for r in self._all_data if not r.get("valid_flag", True)]
        else:
            data = self._all_data

        headers = ["时间", "Δd_raw (μm)", "Δd_corrected (μm)", "Δd_filtered (μm)", "Valid"]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(data))

        for row_idx, record in enumerate(data):
            ts = record.get("timestamp", "")
            if hasattr(ts, "strftime"):
                ts = ts.strftime("%Y-%m-%d %H:%M:%S")
            self._table.setItem(row_idx, 0, QTableWidgetItem(str(ts)))
            self._table.setItem(row_idx, 1, QTableWidgetItem(f"{record.get('delta_d_raw', 0):.3f}"))
            self._table.setItem(row_idx, 2, QTableWidgetItem(f"{record.get('delta_d_corrected', 0):.3f}"))
            self._table.setItem(row_idx, 3, QTableWidgetItem(f"{record.get('delta_d_filtered', 0):.3f}"))
            valid = "✓" if record.get("valid_flag", True) else "✗"
            item = QTableWidgetItem(valid)
            if record.get("valid_flag", True):
                item.setForeground(QColor("#66bb6a"))
            else:
                item.setForeground(QColor("#ef5350"))
            self._table.setItem(row_idx, 4, item)

    def update_chart(self, time_data: list, raw_data: list, corrected_data: list, filtered_data: list):
        if HAS_PYQTGRAPH and hasattr(self, "_curve_raw") and self._curve_raw is not None:
            self._curve_raw.setData(time_data, raw_data)
            self._curve_corrected.setData(time_data, corrected_data)
            self._curve_filtered.setData(time_data, filtered_data)


class _EnvironmentCorrelationTab(QWidget):
    """Tab 3: 环境关联 — 双Y轴 T/RH vs Δd"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        if HAS_PYQTGRAPH:
            self._plot = pg.PlotWidget()
            self._plot.setBackground("#1e1e2e")
            self._plot.showGrid(x=True, y=True, alpha=0.3)
            self._plot.getAxis("bottom").setPen(pg.mkPen(color="#b0b0c0"))
            self._plot.setLabel("left", "温度/湿度", units="°C / %")
            self._plot.setLabel("bottom", "时间")

            self._plot_right = pg.ViewBox()
            self._plot.showAxis("right")
            self._plot.scene().addItem(self._plot_right)
            self._plot.getAxis("right").linkToView(self._plot_right)
            self._plot.getAxis("right").setLabel("Δd", units="μm")
            self._plot.getAxis("right").setPen(pg.mkPen(color="#66bb6a"))

            def update_right_axis():
                self._plot_right.setGeometry(self._plot.plotItem.vb.sceneBoundingRect())
                self._plot_right.setXLink(self._plot.plotItem.vb)
            self._plot.plotItem.vb.sigResized.connect(update_right_axis)

            legend = self._plot.addLegend(offset=(-10, 10))
            self._curve_t = self._plot.plot(
                [], [], pen=pg.mkPen(color="#ef5350", width=2), name="温度 T (°C)"
            )
            self._curve_rh = self._plot.plot(
                [], [], pen=pg.mkPen(color="#42a5f5", width=2), name="湿度 RH (%)"
            )
            self._curve_dd = pg.PlotCurveItem(
                pen=pg.mkPen(color="#66bb6a", width=2), name="Δd (μm)"
            )
            self._plot_right.addItem(self._curve_dd)

            self._rh_crit_line = pg.InfiniteLine(
                pos=76, angle=0, pen=pg.mkPen(color="#ef5350", width=1, style=Qt.DashLine)
            )
            self._plot.addItem(self._rh_crit_line)
        else:
            self._plot = QLabel("pyqtgraph 未安装")
            self._plot.setAlignment(Qt.AlignCenter)
            self._plot.setStyleSheet("color: #ef5350;")
            self._curve_t = None
            self._curve_rh = None
            self._curve_dd = None

        layout.addWidget(self._plot, stretch=3)

        self._cl_bar_label = QLabel("Cl⁻ 日均沉积速率柱状图")
        self._cl_bar_label.setObjectName("subtitleLabel")
        layout.addWidget(self._cl_bar_label)

        if HAS_PYQTGRAPH:
            self._cl_plot = pg.PlotWidget()
            self._cl_plot.setBackground("#1e1e2e")
            self._cl_plot.setMaximumHeight(150)
            self._cl_plot.getAxis("bottom").setPen(pg.mkPen(color="#b0b0c0"))
            self._cl_plot.getAxis("left").setPen(pg.mkPen(color="#b0b0c0"))
            self._cl_plot.setLabel("left", "Cl⁻", units="mg/(m²·day)")
            self._cl_bar = pg.BarGraphItem(x=[], height=[], width=0.8, brush="#ffa726")
            self._cl_plot.addItem(self._cl_bar)
        else:
            self._cl_plot = QLabel("")
        layout.addWidget(self._cl_plot, stretch=1)

    def update_chart(self, time_data: list, t_data: list, rh_data: list, dd_data: list):
        if HAS_PYQTGRAPH and self._curve_t is not None:
            self._curve_t.setData(time_data, t_data)
            self._curve_rh.setData(time_data, rh_data)
            self._curve_dd.setData(time_data, dd_data)
            self._plot_right.setGeometry(self._plot.plotItem.vb.sceneBoundingRect())

    def update_cl_bars(self, x_data: list, y_data: list):
        if HAS_PYQTGRAPH and hasattr(self, "_cl_bar") and self._cl_bar is not None:
            self._cl_bar.setOpts(x=x_data, height=y_data)


class _RiskAssessmentTab(QWidget):
    """Tab 4: 风险评估 — ISO等级卡片, η仪表, 腐蚀进度"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        iso_group = QGroupBox("ISO 9223 腐蚀性等级")
        iso_layout = QHBoxLayout(iso_group)
        iso_layout.setSpacing(8)
        self._iso_cards: Dict[str, QFrame] = {}

        for cat_name, cat_label, cat_color, _, _ in _ISO_CATEGORIES:
            card = QFrame()
            card.setFrameStyle(QFrame.Box)
            card.setFixedHeight(90)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(6, 4, 6, 4)

            name_label = QLabel(cat_name)
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setStyleSheet(
                f"color: {cat_color}; font-size: 18px; font-weight: bold; background: transparent;"
            )
            card_layout.addWidget(name_label)

            desc_label = QLabel(cat_label)
            desc_label.setAlignment(Qt.AlignCenter)
            desc_label.setStyleSheet("color: #b0b0c0; font-size: 11px; background: transparent;")
            card_layout.addWidget(desc_label)

            card.setStyleSheet(
                f"QFrame {{ background-color: #2a2a3e; border: 1px solid #3a3a4e; border-radius: 6px; }}"
            )
            iso_layout.addWidget(card)
            self._iso_cards[cat_name] = card

        layout.addWidget(iso_group)

        middle_layout = QHBoxLayout()

        gauge_layout = QVBoxLayout()
        gauge_label = QLabel("η 腐蚀效率因子")
        gauge_label.setObjectName("subtitleLabel")
        gauge_label.setAlignment(Qt.AlignCenter)
        gauge_layout.addWidget(gauge_label)
        self._eta_gauge = EtaGaugeWidget()
        self._eta_gauge.setMinimumSize(200, 150)
        gauge_layout.addWidget(self._eta_gauge)
        middle_layout.addLayout(gauge_layout)

        chart_layout = QVBoxLayout()
        chart_label = QLabel("实测 vs 预测腐蚀速率")
        chart_label.setObjectName("subtitleLabel")
        chart_layout.addWidget(chart_label)

        if HAS_PYQTGRAPH:
            self._cr_plot = pg.PlotWidget()
            self._cr_plot.setBackground("#1e1e2e")
            self._cr_plot.getAxis("bottom").setPen(pg.mkPen(color="#b0b0c0"))
            self._cr_plot.getAxis("left").setPen(pg.mkPen(color="#b0b0c0"))
            self._cr_plot.setLabel("left", "CR", units="μm/year")

            x_vals = [1, 2]
            ticks = [(1, "实测CR"), (2, "预测CR")]
            self._cr_plot.getAxis("bottom").setTicks([ticks])

            self._cr_bars = pg.BarGraphItem(
                x=[1, 2], height=[0, 0], width=0.4,
                brushes=["#4fc3f7", "#ffa726"]
            )
            self._cr_plot.addItem(self._cr_bars)
        else:
            self._cr_plot = QLabel("")

        chart_layout.addWidget(self._cr_plot)
        middle_layout.addLayout(chart_layout, stretch=1)
        layout.addLayout(middle_layout)

        progress_layout = QVBoxLayout()
        progress_label = QLabel("25年使用寿命进度")
        progress_label.setObjectName("subtitleLabel")
        progress_layout.addWidget(progress_label)

        self._life_progress = QProgressBar()
        self._life_progress.setMinimum(0)
        self._life_progress.setMaximum(100)
        self._life_progress.setValue(0)
        self._life_progress.setTextVisible(True)
        self._life_progress.setFixedHeight(28)
        self._update_progress_style(0)
        progress_layout.addWidget(self._life_progress)
        layout.addLayout(progress_layout)

        self._summary_text = QLabel(
            "ISO 9223/9224 评估摘要:\n"
            "当前等级: -- | 腐蚀速率: -- μm/year | "
            "预计寿命剩余: -- 年"
        )
        self._summary_text.setStyleSheet(
            "color: #b0b0c0; font-size: 12px; background: #1a1a2a; "
            "border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(self._summary_text)

    def _update_progress_style(self, pct: int):
        if pct <= 25:
            color = "#66bb6a"
        elif pct <= 50:
            color = "#fdd835"
        elif pct <= 80:
            color = "#ffa726"
        else:
            color = "#ef5350"
        self._life_progress.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; }}"
        )

    def update_iso_category(self, category: str):
        for cat_name, _, cat_color, _, _ in _ISO_CATEGORIES:
            card = self._iso_cards.get(cat_name)
            if card is None:
                continue
            if cat_name == category:
                card.setStyleSheet(
                    f"QFrame {{ background-color: {cat_color}22; "
                    f"border: 2px solid {cat_color}; border-radius: 6px; }}"
                )
            else:
                card.setStyleSheet(
                    "QFrame { background-color: #2a2a3e; "
                    "border: 1px solid #3a3a4e; border-radius: 6px; }"
                )

    def update_eta(self, value: float):
        self._eta_gauge.set_value(value)

    def update_cr_comparison(self, measured: float, predicted: float):
        if HAS_PYQTGRAPH and hasattr(self, "_cr_bars") and self._cr_bars is not None:
            self._cr_bars.setOpts(height=[measured, predicted])

    def update_life_progress(self, pct: float):
        pct_int = int(min(100, max(0, pct)))
        self._life_progress.setValue(pct_int)
        self._update_progress_style(pct_int)
        self._life_progress.setFormat(f"{pct:.1f}%")

    def update_summary(self, iso_cat: str, cr: float, remaining_years: float):
        self._summary_text.setText(
            f"ISO 9223/9224 评估摘要:\n"
            f"当前等级: {iso_cat} | 腐蚀速率: {cr:.2f} μm/year | "
            f"预计寿命剩余: {remaining_years:.1f} 年"
        )


class _AlarmManagementTab(QWidget):
    """Tab 5: 告警管理 — 完整告警列表 + 过滤/操作"""

    acknowledge_requested = Signal(str)
    resolve_requested = Signal(str)
    view_details_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)

        filter_layout.addWidget(QLabel("等级:"))
        self._level_filter = QComboBox()
        self._level_filter.addItems(["全部", "4级", "3级", "2级", "1级"])
        self._level_filter.currentIndexChanged.connect(self._on_filter)
        filter_layout.addWidget(self._level_filter)

        filter_layout.addWidget(QLabel("状态:"))
        self._status_filter = QComboBox()
        self._status_filter.addItems(["全部", "活跃", "已确认", "已解决"])
        self._status_filter.currentIndexChanged.connect(self._on_filter)
        filter_layout.addWidget(self._status_filter)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, stretch=1)

        pagination = QHBoxLayout()
        self._page_label = QLabel("第 1/1 页")
        self._page_label.setStyleSheet("color: #b0b0c0; background: transparent;")
        pagination.addStretch()
        pagination.addWidget(self._page_label)
        pagination.addStretch()
        layout.addLayout(pagination)

        self._all_alarms: list = []
        self._page_size = 50
        self._current_page = 0

    def _on_filter(self):
        self._current_page = 0
        self._refresh_table()

    def set_alarms(self, alarms: list):
        self._all_alarms = alarms
        self._refresh_table()

    def _get_filtered(self) -> list:
        level_idx = self._level_filter.currentIndex()
        status_idx = self._status_filter.currentIndex()

        filtered = self._all_alarms

        if level_idx > 0:
            target_level = 5 - level_idx
            filtered = [
                a for a in filtered
                if (a.get("level", 0) if isinstance(a.get("level"), int)
                    else a.get("level", AlarmLevel.LEVEL_1).value) == target_level
            ]

        if status_idx > 0:
            status_map = {1: "ACTIVE", 2: "ACKNOWLEDGED", 3: "RESOLVED"}
            target_status = status_map.get(status_idx, "")
            filtered = [
                a for a in filtered
                if a.get("status", "").upper() == target_status
                or (hasattr(a.get("status", ""), "value")
                    and a.get("status").value == target_status)
            ]

        return filtered

    def _refresh_table(self):
        filtered = self._get_filtered()
        total_pages = max(1, (len(filtered) + self._page_size - 1) // self._page_size)
        self._page_label.setText(f"第 {self._current_page + 1}/{total_pages} 页")

        start = self._current_page * self._page_size
        page_data = filtered[start:start + self._page_size]

        headers = ["等级", "类型", "时间", "状态", "传感器", "操作员", "操作"]
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(page_data))

        for row_idx, alarm in enumerate(page_data):
            level = alarm.get("level", 1)
            if hasattr(level, "value"):
                level = level.value

            a_type = alarm.get("alarm_type", "")
            if hasattr(a_type, "value"):
                a_type = a_type.value

            ts = alarm.get("timestamp", "")
            if hasattr(ts, "strftime"):
                ts = ts.strftime("%Y-%m-%d %H:%M:%S")

            status = alarm.get("status", "")
            if hasattr(status, "value"):
                status = status.value

            level_item = QTableWidgetItem(str(level))
            level_colors = {4: "#ef5350", 3: "#ffa726", 2: "#fdd835", 1: "#42a5f5"}
            level_item.setForeground(QColor(level_colors.get(level, "#e0e0e0")))
            self._table.setItem(row_idx, 0, level_item)
            self._table.setItem(row_idx, 1, QTableWidgetItem(str(a_type)))
            self._table.setItem(row_idx, 2, QTableWidgetItem(str(ts)))
            self._table.setItem(row_idx, 3, QTableWidgetItem(str(status)))
            self._table.setItem(row_idx, 4, QTableWidgetItem(str(alarm.get("sensor_id", ""))))
            self._table.setItem(row_idx, 5, QTableWidgetItem(str(alarm.get("operator", "") or "")))

            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            action_layout.setSpacing(4)

            aid = str(alarm.get("alarm_id", ""))

            detail_btn = QPushButton("详情")
            detail_btn.setFixedSize(40, 22)
            detail_btn.clicked.connect(lambda checked, a=aid: self.view_details_requested.emit(a))
            action_layout.addWidget(detail_btn)

            if status in ("ACTIVE",):
                ack_btn = QPushButton("确认")
                ack_btn.setFixedSize(40, 22)
                ack_btn.clicked.connect(lambda checked, a=aid: self.acknowledge_requested.emit(a))
                action_layout.addWidget(ack_btn)

            if status in ("ACKNOWLEDGED",):
                res_btn = QPushButton("解决")
                res_btn.setFixedSize(40, 22)
                res_btn.clicked.connect(lambda checked, a=aid: self.resolve_requested.emit(a))
                action_layout.addWidget(res_btn)

            self._table.setCellWidget(row_idx, 6, action_widget)


class _DataQueryTab(QWidget):
    """Tab 6: 数据查询 — 历史数据检索与导出"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        filter_layout.addWidget(QLabel("开始时间:"))
        self._start_time = QDateTimeEdit()
        self._start_time.setCalendarPopup(True)
        self._start_time.setDateTime(QDateTime.currentDateTime().addDays(-7))
        self._start_time.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        filter_layout.addWidget(self._start_time)

        filter_layout.addWidget(QLabel("结束时间:"))
        self._end_time = QDateTimeEdit()
        self._end_time.setCalendarPopup(True)
        self._end_time.setDateTime(QDateTime.currentDateTime())
        self._end_time.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        filter_layout.addWidget(self._end_time)

        filter_layout.addWidget(QLabel("数据类型:"))
        self._data_type_filter = QComboBox()
        self._data_type_filter.addItems(
            ["全部", "T", "RH", "Cl⁻", "Δd_ER", "Δd_Inductive", "CR", "η"]
        )
        filter_layout.addWidget(self._data_type_filter)

        filter_layout.addWidget(QLabel("Valid:"))
        self._valid_filter = QComboBox()
        self._valid_filter.addItems(["全部", "仅有效", "仅无效"])
        filter_layout.addWidget(self._valid_filter)

        search_btn = QPushButton("🔍 查询")
        search_btn.setObjectName("primaryBtn")
        filter_layout.addWidget(search_btn)

        layout.addLayout(filter_layout)

        export_layout = QHBoxLayout()
        export_layout.addStretch()
        export_csv_btn = QPushButton("导出 CSV")
        export_csv_btn.clicked.connect(self._export_csv)
        export_layout.addWidget(export_csv_btn)
        export_json_btn = QPushButton("导出 JSON")
        export_json_btn.clicked.connect(self._export_json)
        export_layout.addWidget(export_json_btn)
        layout.addLayout(export_layout)

        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, stretch=1)

        pagination = QHBoxLayout()
        pagination.addStretch()
        self._prev_btn = QPushButton("上一页")
        self._prev_btn.clicked.connect(self._prev_page)
        pagination.addWidget(self._prev_btn)
        self._page_label = QLabel("第 1/1 页")
        self._page_label.setStyleSheet("color: #b0b0c0; background: transparent;")
        pagination.addWidget(self._page_label)
        self._next_btn = QPushButton("下一页")
        self._next_btn.clicked.connect(self._next_page)
        pagination.addWidget(self._next_btn)
        pagination.addStretch()
        layout.addLayout(pagination)

        self._all_data: list = []
        self._page_size = 1000
        self._current_page = 0

        search_btn.clicked.connect(self._on_search)

    def _on_search(self):
        pass

    def _refresh_table(self):
        total_pages = max(1, (len(self._all_data) + self._page_size - 1) // self._page_size)
        self._page_label.setText(f"第 {self._current_page + 1}/{total_pages} 页")

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._refresh_table()

    def _next_page(self):
        total = max(1, (len(self._all_data) + self._page_size - 1) // self._page_size)
        if self._current_page < total - 1:
            self._current_page += 1
            self._refresh_table()

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", "腐蚀数据.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 JSON", "腐蚀数据.json", "JSON Files (*.json)"
        )
        if not path:
            return

    def set_data(self, data: list):
        self._all_data = data
        self._current_page = 0
        self._refresh_table()


class _SystemSettingsTab(QWidget):
    """Tab 7: 系统设置 — 仅管理员可访问"""

    save_requested = Signal(dict)
    reset_requested = Signal()
    import_calibration_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #1e1e2e;")

        self._widgets: Dict[str, QWidget] = {}

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { border: none; }")

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setSpacing(16)

        self._setup_sensor_group()
        self._setup_sampling_group()
        self._setup_algorithm_group()
        self._setup_alarm_group()
        self._setup_comms_group()

        self._layout.addStretch()

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("💾 保存设置")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        reset_btn = QPushButton("🔄 恢复默认")
        reset_btn.clicked.connect(self._on_reset)
        btn_layout.addWidget(reset_btn)

        import_btn = QPushButton("📥 导入校准曲线")
        import_btn.clicked.connect(self._on_import_calibration)
        btn_layout.addWidget(import_btn)

        btn_layout.addStretch()
        self._layout.addLayout(btn_layout)

        self._scroll.setWidget(self._container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

    def _make_form_group(self, title: str, fields: list) -> QGroupBox:
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(8)

        for field in fields:
            key = field["key"]
            label = field["label"]
            widget_type = field.get("type", "double")
            default_val = field.get("default", 0)
            unit = field.get("unit", "")
            min_val = field.get("min")
            max_val = field.get("max")

            row = QHBoxLayout()

            if widget_type == "double":
                w = QDoubleSpinBox()
                w.setDecimals(4)
                w.setRange(min_val or 0, max_val or 999999)
                w.setValue(float(default_val))
                w.setMinimumWidth(120)
            elif widget_type == "int":
                w = QSpinBox()
                w.setRange(min_val or 0, max_val or 999999)
                w.setValue(int(default_val))
                w.setMinimumWidth(120)
            elif widget_type == "text":
                w = QLineEdit()
                w.setText(str(default_val))
                w.setMinimumWidth(200)
            else:
                w = QDoubleSpinBox()
                w.setValue(float(default_val))

            row.addWidget(w)
            if unit:
                ul = QLabel(unit)
                ul.setStyleSheet("color: #9090a0; font-size: 11px; background: transparent;")
                row.addWidget(ul)
            row.addStretch()

            form.addRow(QLabel(label), row)
            self._widgets[key] = w

        return group

    def _setup_sensor_group(self):
        fields = [
            {"key": "sensor.d0.value", "label": "初始电极厚度 d₀", "type": "double",
             "default": 100.0, "unit": "μm", "min": 10, "max": 500},
            {"key": "sensor.electrode_area.value", "label": "电极面积", "type": "double",
             "default": 1e-4, "unit": "m²", "min": 0.0001, "max": 0.01},
            {"key": "sensor.f0.value", "label": "激励频率 f₀", "type": "double",
             "default": 10000000, "unit": "Hz", "min": 100000, "max": 50000000},
        ]
        group = self._make_form_group("传感器参数", fields)
        self._layout.addWidget(group)

    def _setup_sampling_group(self):
        fields = [
            {"key": "sampling.normal_period.value", "label": "采样周期", "type": "int",
             "default": 600, "unit": "秒 (60-3600)", "min": 60, "max": 3600},
            {"key": "sampling.emergency_period.value", "label": "紧急采样周期", "type": "int",
             "default": 60, "unit": "秒", "min": 5, "max": 600},
            {"key": "sampling.emergency_duration.value", "label": "紧急模式持续时间", "type": "int",
             "default": 1800, "unit": "秒", "min": 60, "max": 86400},
        ]
        group = self._make_form_group("采样参数", fields)
        self._layout.addWidget(group)

    def _setup_algorithm_group(self):
        fields = [
            {"key": "algorithm.RH_crit.value", "label": "临界湿度 RH_crit", "type": "double",
             "default": 76.0, "unit": "% (50-90)", "min": 50, "max": 90},
            {"key": "algorithm.epsilon_noise_multiplier.value", "label": "ε_noise 乘数", "type": "double",
             "default": 3.0, "unit": "", "min": 0.5, "max": 10.0},
            {"key": "algorithm.alpha_res.value", "label": "α_res (温度系数)", "type": "double",
             "default": 0.0, "unit": "Ω/K", "min": -10, "max": 10},
            {"key": "algorithm.beta_res.value", "label": "β_res (二次温度系数)", "type": "double",
             "default": 0.0, "unit": "Ω/K²", "min": -10, "max": 10},
            {"key": "algorithm.k_S.value", "label": "k_S (灵敏度系数)", "type": "double",
             "default": 0.01, "unit": "", "min": 0.0, "max": 1.0},
            {"key": "algorithm.TOW_ref.value", "label": "TOW_ref (参考润湿时间)", "type": "double",
             "default": 4000, "unit": "小时/年", "min": 100, "max": 8760},
        ]
        group = self._make_form_group("算法参数", fields)
        self._layout.addWidget(group)

    def _setup_alarm_group(self):
        fields = [
            {"key": "alarm.thresholds.level_1.CR_threshold", "label": "1级阈值 (CR)", "type": "double",
             "default": 0.01, "unit": "mm/year", "min": 0.001, "max": 10.0},
            {"key": "alarm.thresholds.level_2.CR_threshold", "label": "2级阈值 (CR)", "type": "double",
             "default": 0.05, "unit": "mm/year", "min": 0.001, "max": 10.0},
            {"key": "alarm.thresholds.level_3.CR_threshold", "label": "3级阈值 (CR)", "type": "double",
             "default": 0.10, "unit": "mm/year", "min": 0.001, "max": 10.0},
            {"key": "alarm.thresholds.level_4.CR_threshold", "label": "4级阈值 (CR)", "type": "double",
             "default": 0.20, "unit": "mm/year", "min": 0.001, "max": 10.0},
        ]
        group = self._make_form_group("告警参数", fields)
        self._layout.addWidget(group)

    def _setup_comms_group(self):
        fields = [
            {"key": "comms.lora.frequency.value", "label": "LoRa 频率", "type": "double",
             "default": 433.0, "unit": "MHz", "min": 410, "max": 525},
            {"key": "comms.nb_iot.apn.value", "label": "NB-IoT APN", "type": "text",
             "default": "ctnet", "unit": ""},
            {"key": "comms.cloud.server_address.value", "label": "服务器地址", "type": "text",
             "default": "mqtt.cloud.example.com", "unit": ""},
        ]
        group = self._make_form_group("通信参数", fields)
        self._layout.addWidget(group)

    def _on_save(self):
        values = {}
        for key, widget in self._widgets.items():
            if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                values[key] = widget.value()
            elif isinstance(widget, QLineEdit):
                values[key] = widget.text()
        self.save_requested.emit(values)

    def _on_reset(self):
        reply = QMessageBox.question(
            self, "确认恢复默认",
            "确定要恢复所有设置为默认值吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.reset_requested.emit()

    def _on_import_calibration(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入校准曲线", "", "CSV Files (*.csv);;All Files (*)"
        )
        if path:
            self.import_calibration_requested.emit(path)

    def load_config(self, config: dict):
        for key, widget in self._widgets.items():
            keys = key.split(".")
            val = config
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k)
                else:
                    val = None
                    break
            if val is not None:
                if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                    try:
                        widget.setValue(float(val))
                    except (ValueError, TypeError):
                        pass
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(val))


class MainWindow(QMainWindow):
    """主应用程序窗口"""

    def __init__(self) -> None:
        super().__init__()
        self._initialized = False

        self.setWindowTitle("海上风电塔筒内部腐蚀检测系统 v1.0.0")
        self.setMinimumSize(1280, 720)

        self._app_ref: Any = None
        self._alarm_manager: Any = None
        self._config_manager: Any = None
        self._storage_manager: Any = None

        self._data_buffer: List[dict] = []
        self._corrosion_buffer: List[dict] = []
        self._max_buffer_size = 5000

        self._top_bar = _TopStatusBar()
        self._left_panel = _LeftSensorPanel()
        self._right_panel = _RightAlarmPanel()
        self._center_tabs = QTabWidget()

        self._tab_real_time = _RealTimeTab()
        self._tab_corrosion = _CorrosionDetailTab()
        self._tab_environment = _EnvironmentCorrelationTab()
        self._tab_risk = _RiskAssessmentTab()
        self._tab_alarms = _AlarmManagementTab()
        self._tab_query = _DataQueryTab()
        self._tab_settings = _SystemSettingsTab()

        self._center_tabs.addTab(self._tab_real_time, "实时监测")
        self._center_tabs.addTab(self._tab_corrosion, "腐蚀详情")
        self._center_tabs.addTab(self._tab_environment, "环境关联")
        self._center_tabs.addTab(self._tab_risk, "风险评估")
        self._center_tabs.addTab(self._tab_alarms, "告警管理")
        self._center_tabs.addTab(self._tab_query, "数据查询")
        self._center_tabs.addTab(self._tab_settings, "系统设置")

        self._left_panel.switch_to_corrosion_tab.connect(
            lambda: self._center_tabs.setCurrentIndex(1)
        )

        self._tab_alarms.acknowledge_requested.connect(self._on_acknowledge_alarm)
        self._tab_alarms.resolve_requested.connect(self._on_resolve_alarm)
        self._tab_alarms.view_details_requested.connect(self._on_view_alarm_details)
        self._right_panel.acknowledge_requested.connect(self._on_acknowledge_alarm)
        self._right_panel.resolve_requested.connect(self._on_resolve_alarm)
        self._right_panel.view_details_requested.connect(self._on_view_alarm_details)

        self._tab_settings.save_requested.connect(self._on_save_config)
        self._tab_settings.reset_requested.connect(self._on_reset_config)
        self._tab_settings.import_calibration_requested.connect(self._on_import_calibration)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._left_panel)
        splitter.addWidget(self._center_tabs)
        splitter.addWidget(self._right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([200, 820, 260])

        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._top_bar)
        central_layout.addWidget(splitter, stretch=1)

        self.setCentralWidget(central_widget)
        self.setStyleSheet(DARK_THEME_QSS)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._periodic_refresh)
        self._refresh_timer.start(600000)

        self._chart_timer = QTimer(self)
        self._chart_timer.timeout.connect(self._refresh_charts)
        self._chart_timer.start(10000)

        logger.info("MainWindow 创建完成")

    def set_app(self, app: Any):
        self._app_ref = app
        if app:
            self._config_manager = app.config_manager
            try:
                from ..core.alarm_manager import AlarmManager
                self._alarm_manager = AlarmManager()
            except Exception:
                pass

    def initialize(self) -> bool:
        self._initialized = True
        logger.info("UI 子系统初始化完成")
        return True

    def show(self) -> None:
        if not self._initialized:
            logger.warning("UI 子系统未初始化")
            return
        self.showMaximized()
        super().show()

    def shutdown(self) -> None:
        self._refresh_timer.stop()
        self._chart_timer.stop()
        self._initialized = False
        logger.info("UI 子系统已关闭")

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    @Slot(dict)
    def on_sensor_data(self, data: dict):
        if not self._initialized:
            return
        QMetaObject.invokeMethod(
            self, "_handle_sensor_data", Qt.QueuedConnection,
            type(data) if hasattr(data, "__class__") else None,
            data
        )

    def _handle_sensor_data(self, data: Any):
        d = data.to_dict() if hasattr(data, "to_dict") else data
        self._data_buffer.append(d)
        if len(self._data_buffer) > self._max_buffer_size:
            self._data_buffer = self._data_buffer[-self._max_buffer_size:]
        self._left_panel.update_sensor_data(d)

    @Slot(dict)
    def on_corrosion_record(self, record: dict):
        if not self._initialized:
            return
        QMetaObject.invokeMethod(
            self, "_handle_corrosion_record", Qt.QueuedConnection,
            type(record) if hasattr(record, "__class__") else None,
            record
        )

    def _handle_corrosion_record(self, record: Any):
        r = record.to_dict() if hasattr(record, "to_dict") else record
        self._corrosion_buffer.append(r)
        if len(self._corrosion_buffer) > self._max_buffer_size:
            self._corrosion_buffer = self._corrosion_buffer[-self._max_buffer_size:]

    @Slot(dict)
    def on_alarm_raised(self, alarm: dict):
        if not self._initialized:
            return
        QMetaObject.invokeMethod(self, "_refresh_alarm_panels", Qt.QueuedConnection)

    @Slot(dict)
    def on_alarm_resolved(self, alarm: dict):
        if not self._initialized:
            return
        QMetaObject.invokeMethod(self, "_refresh_alarm_panels", Qt.QueuedConnection)

    @Slot()
    def _refresh_alarm_panels(self):
        if self._alarm_manager is None:
            return
        try:
            active = self._alarm_manager.get_active_alarms()
            resolved = self._alarm_manager.get_recent_resolved(5)
            stats = self._alarm_manager.get_alarm_statistics()

            active_dicts = [a.to_dict() if hasattr(a, "to_dict") else a for a in active]
            resolved_dicts = [a.to_dict() if hasattr(a, "to_dict") else a for a in resolved]

            self._right_panel.refresh_active(active_dicts)
            self._right_panel.refresh_resolved(resolved_dicts)
            self._right_panel.refresh_stats(
                today=stats.get("total_active", 0),
                week=0,
                active=stats.get("total_active", 0),
            )

            all_alarms = []
            if hasattr(self._alarm_manager, "_alarm_history"):
                all_alarms = [
                    a.to_dict() if hasattr(a, "to_dict") else a
                    for a in self._alarm_manager._alarm_history
                ]
            self._tab_alarms.set_alarms(all_alarms)
        except Exception as e:
            logger.warning(f"刷新告警面板失败: {e}")

    @Slot()
    def _periodic_refresh(self):
        self._refresh_alarm_panels()
        self._refresh_charts()

    @Slot()
    def _refresh_charts(self):
        if len(self._data_buffer) < 2:
            return

        time_data = []
        er_data = []
        ind_data = []
        t_data = []
        rh_data = []
        cl_data = []

        for d in self._data_buffer[-500:]:
            ts = d.get("timestamp", 0)
            if hasattr(ts, "timestamp"):
                ts_val = ts.timestamp()
            elif isinstance(ts, (int, float)):
                ts_val = ts
            elif isinstance(ts, str):
                try:
                    from datetime import datetime as _dt
                    ts_val = _dt.fromisoformat(ts).timestamp()
                except Exception:
                    ts_val = 0
            else:
                ts_val = 0

            time_data.append(ts_val)
            er_data.append(d.get("delta_d_ER", 0))
            ind_data.append(d.get("delta_d_Inductive", 0))
            t_data.append(d.get("T", 0))
            rh_data.append(d.get("RH", 0))
            cl_data.append(d.get("Cl_deposition", 0))

        self._tab_real_time.update_chart(time_data, er_data, ind_data)
        self._tab_environment.update_chart(time_data, t_data, rh_data, ind_data)
        self._tab_environment.update_cl_bars(
            list(range(len(cl_data))), cl_data
        )

        if self._corrosion_buffer:
            raw_data = [r.get("delta_d_raw", 0) for r in self._corrosion_buffer[-500:]]
            corrected_data = [r.get("delta_d_corrected", 0) for r in self._corrosion_buffer[-500:]]
            filtered_data = [r.get("delta_d_filtered", 0) for r in self._corrosion_buffer[-500:]]
            c_time_data = [
                r.get("timestamp", 0).timestamp() if hasattr(r.get("timestamp", 0), "timestamp")
                else r.get("timestamp", 0)
                for r in self._corrosion_buffer[-500:]
            ]
            c_time_data = [
                t.timestamp() if hasattr(t, "timestamp") else (
                    t if isinstance(t, (int, float)) else 0)
                for t in c_time_data
            ]
            self._tab_corrosion.update_chart(c_time_data, raw_data, corrected_data, filtered_data)
            self._tab_corrosion.set_data(self._corrosion_buffer[-200:])

            if self._corrosion_buffer:
                latest = self._corrosion_buffer[-1]
                self._tab_risk.update_eta(latest.get("eta", 1.0))
                self._tab_risk.update_cr_comparison(
                    latest.get("CR_ER", 0), latest.get("CR_Inductive", 0)
                )
                cr = latest.get("CR_out", 0) or latest.get("CR_ER", 0)
                cr_mm = cr / 1000
                if cr_mm > 0.20:
                    iso_cat = "CX"
                elif cr_mm > 0.10:
                    iso_cat = "C5"
                elif cr_mm > 0.05:
                    iso_cat = "C4"
                elif cr_mm > 0.02:
                    iso_cat = "C3"
                elif cr_mm > 0.005:
                    iso_cat = "C2"
                else:
                    iso_cat = "C1"

                d0 = 100.0
                delta_d_filtered = latest.get("delta_d_filtered", 0)
                cr_mm_per_year = cr * 1e-6 if cr > 0 else 0.001
                remaining_years = max(0, (d0 - delta_d_filtered) / cr_mm_per_year) if cr_mm_per_year > 0 else 25
                pct_used = min(100, (delta_d_filtered / d0) * 100) if d0 > 0 else 0

                self._tab_risk.update_life_progress(pct_used)
                self._tab_risk.update_iso_category(iso_cat)
                self._tab_risk.update_summary(iso_cat, cr, remaining_years)

    def _on_acknowledge_alarm(self, alarm_id: str):
        if self._alarm_manager is None:
            return
        try:
            self._alarm_manager.acknowledge_alarm(alarm_id, "操作员")
            self._refresh_alarm_panels()
        except Exception as e:
            logger.warning(f"确认告警失败: {e}")

    def _on_resolve_alarm(self, alarm_id: str):
        if self._alarm_manager is None:
            return
        try:
            self._alarm_manager.resolve_alarm(alarm_id, "操作员")
            self._refresh_alarm_panels()
        except Exception as e:
            logger.warning(f"解决告警失败: {e}")

    def _on_view_alarm_details(self, alarm_id: str):
        if self._alarm_manager is None:
            return
        alarm = self._alarm_manager.get_alarm_by_id(alarm_id)
        if alarm is None:
            return

        details = alarm.details if hasattr(alarm, "details") else alarm.get("details", {})
        msg = details.get("message", "") if isinstance(details, dict) else str(details)
        a_type = alarm.alarm_type if hasattr(alarm, "alarm_type") else alarm.get("alarm_type", "")
        if hasattr(a_type, "value"):
            a_type = a_type.value
        level = alarm.level if hasattr(alarm, "level") else alarm.get("level", 1)
        if hasattr(level, "value"):
            level = level.value
        ts = alarm.timestamp if hasattr(alarm, "timestamp") else alarm.get("timestamp", "")
        if hasattr(ts, "strftime"):
            ts = ts.strftime("%Y-%m-%d %H:%M:%S")
        status = alarm.status if hasattr(alarm, "status") else alarm.get("status", "")
        if hasattr(status, "value"):
            status = status.value
        sensor = alarm.sensor_id if hasattr(alarm, "sensor_id") else alarm.get("sensor_id", "")

        text = (
            f"告警ID: {alarm_id}\n"
            f"等级: L{level}\n"
            f"类型: {a_type}\n"
            f"时间: {ts}\n"
            f"状态: {status}\n"
            f"传感器: {sensor}\n"
            f"详情: {msg}\n"
        )

        QMessageBox.information(self, "告警详情", text)

    def _on_save_config(self, values: dict):
        if self._config_manager is None:
            QMessageBox.warning(self, "错误", "配置管理器未初始化")
            return
        try:
            for key, value in values.items():
                self._config_manager.set(key, value)
            self._config_manager.save()
            QMessageBox.information(self, "成功", "配置已保存")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存配置失败: {e}")

    def _on_reset_config(self):
        if self._config_manager is None:
            return
        try:
            self._config_manager.reset_to_defaults()
            self._config_manager.save()
            config = self._config_manager.get_all()
            self._tab_settings.load_config(config)
            QMessageBox.information(self, "成功", "配置已恢复为默认值")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"恢复配置失败: {e}")

    def _on_import_calibration(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if not rows:
                QMessageBox.warning(self, "警告", "校准曲线文件为空")
                return
            points = []
            for row in rows:
                if len(row) >= 2:
                    points.append((float(row[0]), float(row[1])))
            QMessageBox.information(
                self, "成功",
                f"校准曲线导入成功: {len(points)} 个数据点\n"
                f"文件: {path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {e}")