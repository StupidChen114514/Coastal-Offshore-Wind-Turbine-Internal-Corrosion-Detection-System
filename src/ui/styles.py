"""QSS样式表 – 暗色工业监控主题"""

DARK_THEME_QSS = """
/* ===== 全局样式 ===== */
QWidget {
    background-color: #1e1e2e;
    color: #e0e0e0;
    font-family: "Microsoft YaHei", "SimHei", "Segoe UI", sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #1e1e2e;
}

/* ===== 菜单栏 ===== */
QMenuBar {
    background-color: #1a1a2a;
    color: #e0e0e0;
    border-bottom: 1px solid #3a3a4e;
    padding: 2px;
    font-size: 13px;
}
QMenuBar::item:selected {
    background-color: #3a3a4e;
    border-radius: 4px;
}
QMenu {
    background-color: #2a2a3e;
    color: #e0e0e0;
    border: 1px solid #3a3a4e;
    padding: 4px;
}
QMenu::item:selected {
    background-color: #4fc3f7;
    color: #1e1e2e;
    border-radius: 3px;
}

/* ===== 状态栏 ===== */
QStatusBar {
    background-color: #1a1a2a;
    color: #b0b0c0;
    border-top: 1px solid #3a3a4e;
    padding: 4px 8px;
    font-size: 12px;
}

/* ===== TabWidget ===== */
QTabWidget::pane {
    border: 1px solid #3a3a4e;
    background-color: #1e1e2e;
    border-radius: 0px;
}
QTabBar::tab {
    background-color: #252538;
    color: #b0b0c0;
    border: 1px solid #3a3a4e;
    padding: 8px 18px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: 13px;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #4fc3f7;
    border-bottom: 2px solid #4fc3f7;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background-color: #2e2e42;
    color: #d0d0e0;
}

/* ===== 分组框 ===== */
QGroupBox {
    background-color: #2a2a3e;
    border: 1px solid #3a3a4e;
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-size: 14px;
    font-weight: bold;
    color: #4fc3f7;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
}

/* ===== 按钮 ===== */
QPushButton {
    background-color: #3a3a4e;
    color: #e0e0e0;
    border: 1px solid #4a4a5e;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
    min-height: 28px;
}
QPushButton:hover {
    background-color: #4a4a5e;
    border-color: #4fc3f7;
}
QPushButton:pressed {
    background-color: #2a2a3e;
}
QPushButton:disabled {
    background-color: #2a2a3e;
    color: #606070;
    border-color: #3a3a4e;
}

QPushButton#primaryBtn {
    background-color: #4fc3f7;
    color: #1e1e2e;
    border: none;
    font-weight: bold;
}
QPushButton#primaryBtn:hover {
    background-color: #66d0f8;
}
QPushButton#primaryBtn:pressed {
    background-color: #3ab0e0;
}

QPushButton#dangerBtn {
    background-color: #ef5350;
    color: #ffffff;
    border: none;
    font-weight: bold;
}
QPushButton#dangerBtn:hover {
    background-color: #f2706d;
}
QPushButton#dangerBtn:pressed {
    background-color: #d32f2f;
}

QPushButton#successBtn {
    background-color: #66bb6a;
    color: #1e1e2e;
    border: none;
    font-weight: bold;
}
QPushButton#successBtn:hover {
    background-color: #78c97c;
}

QPushButton#timeSpanBtn {
    background-color: #2a2a3e;
    color: #b0b0c0;
    border: 1px solid #3a3a4e;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
    min-height: 24px;
}
QPushButton#timeSpanBtn:checked {
    background-color: #4fc3f7;
    color: #1e1e2e;
    border-color: #4fc3f7;
    font-weight: bold;
}

/* ===== 表格 ===== */
QTableWidget {
    background-color: #1e1e2e;
    alternate-background-color: #252538;
    color: #e0e0e0;
    gridline-color: #3a3a4e;
    border: 1px solid #3a3a4e;
    border-radius: 4px;
    selection-background-color: #3a5a7e;
    selection-color: #ffffff;
    font-size: 12px;
}
QTableWidget QHeaderView::section {
    background-color: #2a2a3e;
    color: #4fc3f7;
    border: 1px solid #3a3a4e;
    padding: 6px 8px;
    font-size: 12px;
    font-weight: bold;
}

/* ===== 输入控件 ===== */
QLineEdit, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QComboBox {
    background-color: #1a1a2a;
    color: #e0e0e0;
    border: 1px solid #3a3a4e;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 26px;
    font-size: 13px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #4fc3f7;
}
QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #2a2a3e;
    color: #e0e0e0;
    selection-background-color: #4fc3f7;
    selection-color: #1e1e2e;
}

/* ===== 滚动条 ===== */
QScrollBar:vertical {
    background-color: #1a1a2a;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background-color: #4a4a5e;
    min-height: 30px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background-color: #5a5a6e;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background-color: #1a1a2a;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background-color: #4a4a5e;
    min-width: 30px;
    border-radius: 5px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ===== 进度条 ===== */
QProgressBar {
    background-color: #1a1a2a;
    border: 1px solid #3a3a4e;
    border-radius: 6px;
    text-align: center;
    color: #e0e0e0;
    font-size: 12px;
    min-height: 20px;
}
QProgressBar::chunk {
    border-radius: 5px;
}

/* ===== 分割器 ===== */
QSplitter::handle {
    background-color: #3a3a4e;
    width: 2px;
}
QSplitter::handle:hover {
    background-color: #4fc3f7;
}

/* ===== 复选框/单选框 ===== */
QCheckBox, QRadioButton {
    color: #e0e0e0;
    spacing: 8px;
    font-size: 13px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #4a4a5e;
    border-radius: 3px;
    background-color: #1a1a2a;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #4fc3f7;
    border-color: #4fc3f7;
}

/* ===== 标签 ===== */
QLabel {
    color: #e0e0e0;
    background-color: transparent;
}

QLabel#titleLabel {
    font-size: 18px;
    font-weight: bold;
    color: #4fc3f7;
}

QLabel#subtitleLabel {
    font-size: 14px;
    color: #b0b0c0;
}

QLabel#sensorValueLabel {
    font-size: 28px;
    font-weight: bold;
    color: #ffffff;
}

QLabel#sensorUnitLabel {
    font-size: 14px;
    color: #b0b0c0;
}

QLabel#alarmLevel4Label {
    color: #ef5350;
    font-weight: bold;
    font-size: 14px;
}
QLabel#alarmLevel3Label {
    color: #ffa726;
    font-weight: bold;
    font-size: 14px;
}
QLabel#alarmLevel2Label {
    color: #fdd835;
    font-weight: bold;
    font-size: 13px;
}
QLabel#alarmLevel1Label {
    color: #42a5f5;
    font-weight: bold;
    font-size: 13px;
}

/* ===== 工具提示 ===== */
QToolTip {
    background-color: #2a2a3e;
    color: #e0e0e0;
    border: 1px solid #4fc3f7;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

/* ===== 消息框 ===== */
QMessageBox {
    background-color: #2a2a3e;
    color: #e0e0e0;
}
QMessageBox QLabel {
    color: #e0e0e0;
    font-size: 13px;
}
QMessageBox QPushButton {
    min-width: 80px;
}

/* ===== 日历弹窗 ===== */
QCalendarWidget {
    background-color: #2a2a3e;
    color: #e0e0e0;
}

/* ===== 输入框错误状态 ===== */
QLineEdit[valid="false"], QSpinBox[valid="false"], QDoubleSpinBox[valid="false"] {
    border: 2px solid #ef5350;
}
"""

COLLAPSED_THEME_QSS = """
QWidget {
    font-size: 12px;
}
"""
