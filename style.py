# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph
# Modern UI stylesheet and theme utility for GeoFASU_Ori

import os
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import QComboBox, QListView

MODERN_STYLE = """
/* Global Dialog */
QDialog {
    background-color: #F8FAFC;
    color: #1E293B;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Roboto', 'Helvetica Neue', Arial, sans-serif;
    font-size: 13px;
}

/* Labels */
QLabel {
    color: #334155;
    font-size: 12px;
    font-weight: 600;
}

/* Inputs & Combos */
QLineEdit, QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    color: #0F172A;
    min-height: 22px;
}

QComboBox {
    combobox-popup: 0;
}

QLineEdit:hover, QComboBox:hover {
    border-color: #94A3B8;
}

QLineEdit:focus, QComboBox:focus {
    border: 1.5px solid #2563EB;
    background-color: #FFFFFF;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #E2E8F0;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background-color: #F8FAFC;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #64748B;
    width: 0;
    height: 0;
}

/* Dropdown Popup List */
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 4px;
    outline: none;
    selection-background-color: #EFF6FF;
    selection-color: #1D4ED8;
    color: #1E293B;
}

QComboBox QAbstractItemView::item {
    min-height: 28px;
    padding: 6px 10px;
    border-radius: 4px;
    margin: 1px 0px;
    color: #1E293B;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #F1F5F9;
    color: #0F172A;
}

QComboBox QAbstractItemView::item:selected {
    background-color: #EFF6FF;
    color: #1D4ED8;
    font-weight: 600;
}

/* Primary PushButtons */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3B82F6, stop:1 #2563EB);
    color: #FFFFFF;
    border: 1px solid #1D4ED8;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
    min-height: 24px;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #60A5FA, stop:1 #3B82F6);
    border-color: #2563EB;
}

QPushButton:pressed {
    background: #1D4ED8;
    border-color: #1E40AF;
}

QPushButton:disabled {
    background: #E2E8F0;
    color: #94A3B8;
    border: 1px solid #CBD5E1;
}

/* Secondary / Dialog Buttons */
QPushButton[secondary="true"], QPushButton#btn_cancel, QPushButton#btn_clear, QPushButton#btn_all {
    background: #FFFFFF;
    color: #475569;
    border: 1px solid #CBD5E1;
}

QPushButton[secondary="true"]:hover, QPushButton#btn_cancel:hover, QPushButton#btn_clear:hover, QPushButton#btn_all:hover {
    background: #F1F5F9;
    color: #1E293B;
    border-color: #94A3B8;
}

/* Modern Responsive Progress Bar */
QProgressBar {
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    background-color: #E2E8F0;
    text-align: center;
    color: #1E293B;
    font-weight: 600;
    font-size: 11px;
    min-height: 20px;
    max-height: 22px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3B82F6, stop:0.5 #2563EB, stop:1 #1D4ED8);
    border-radius: 5px;
}

/* QgsFileWidget Tool Button */
QToolButton {
    background-color: #F1F5F9;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 20px;
}

QToolButton:hover {
    background-color: #E2E8F0;
    border-color: #94A3B8;
}

/* List Widget */
QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 4px;
}

QListWidget::item {
    padding: 6px 10px;
    border-radius: 4px;
    color: #1E293B;
}

QListWidget::item:hover {
    background-color: #F1F5F9;
}

QLabel#iconLabel {
    margin: 0px;
    padding: 0px;
    background: transparent;
}

QListWidget::item:selected {
    background-color: #EFF6FF;
    color: #1D4ED8;
    font-weight: 600;
}
"""

def apply_modern_style(widget):
    """Applies modern styling to the given Qt widget/dialog."""
    widget.setStyleSheet(MODERN_STYLE)
    for cb in widget.findChildren(QComboBox):
        cb.setView(QListView())


def setup_dialog_logo(dialog, max_width=250, max_height=130):
    """Safely loads and smoothly scales logo.png preserving aspect ratio."""
    if hasattr(dialog, 'iconLabel'):
        logo_path = os.path.join(os.path.dirname(__file__), 'icons', 'logo.png')
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    max_width, max_height,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                dialog.iconLabel.setPixmap(scaled)
                dialog.iconLabel.setAlignment(Qt.AlignCenter)
                # Ensure label height precisely wraps the scaled image plus buffer
                target_height = scaled.height() + 12
                dialog.iconLabel.setMinimumHeight(target_height)
                dialog.iconLabel.setMaximumHeight(target_height)
                dialog.iconLabel.setFixedHeight(target_height)


