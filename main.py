
import sys

from PySide6.QtWidgets import QApplication
from app.db import init_db
from app.ui import LoginDialog, MainWindow


APP_STYLE = """
QWidget {
    font-family: "Segoe UI";
    font-size: 10pt;
    color: #1F2937;
}

QMainWindow, QDialog {
    background-color: #F4F7FB;
}

QLabel {
    background: transparent;
    color: #1F2937;
}

QTabWidget::pane {
    border: 1px solid #E2E8F0;
    background-color: #FFFFFF;
    border-radius: 8px;
    top: -1px;
}

QTabBar::tab {
    background-color: #E9EEF6;
    color: #475569;
    padding: 11px 16px;
    margin-right: 3px;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}

QTabBar::tab:selected {
    background-color: #FFFFFF;
    color: #1D4ED8;
    font-weight: 600;
    border-bottom: 3px solid #2563EB;
}

QTabBar::tab:hover:!selected {
    background-color: #DCE6F5;
}

QPushButton {
    background-color: #2563EB;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 9px 15px;
    min-height: 18px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #1D4ED8;
}

QPushButton:pressed {
    background-color: #1E40AF;
}

QPushButton:disabled {
    background-color: #CBD5E1;
    color: #64748B;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 8px 10px;
    min-height: 18px;
    selection-background-color: #2563EB;
}

QLineEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #2563EB;
}

QComboBox::drop-down {
    border: none;
    width: 25px;
}

QTableWidget {
    background-color: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 7px;
    gridline-color: #E8EDF4;
    selection-background-color: #2563EB;
    selection-color: #FFFFFF;
}

QTableWidget::item:selected {
    background-color: #2563EB;
    color: #FFFFFF;
}

QTableWidget::item:selected:!active {
    background-color: #93C5FD;
    color: #172033;
}

QTableWidget::item {
    padding: 6px;
}

QHeaderView::section {
    background-color: #EAF0F8;
    color: #334155;
    padding: 10px 7px;
    border: none;
    border-bottom: 1px solid #CBD5E1;
    font-weight: 600;
}

QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: #1D4ED8;
}

QMessageBox {
    background-color: #FFFFFF;
}

QStatusBar {
    background-color: #FFFFFF;
    color: #64748B;
    border-top: 1px solid #E2E8F0;
}

QScrollBar:vertical {
    background-color: #F1F5F9;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #CBD5E1;
    min-height: 25px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background-color: #94A3B8;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
"""


def main():
    init_db()

    app = QApplication(sys.argv)
    app.setApplicationName("GST Billing System")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)

    login = LoginDialog()

    if login.exec() != LoginDialog.Accepted or not login.user:
        return 0

    window = MainWindow(login.user)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
