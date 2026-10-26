# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph
# GeoFASU_Ori - Preprocessing and Postprocessing Dialogs

import os
from pathlib import Path

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QDialog, QMessageBox, QWidget, QScrollArea, QFrame

try:
    from .style import apply_modern_style, setup_dialog_logo
    from .GeoFASU_dialog import GeoFASUDialog
    from .loader_dialog import LoaderDialog
    from .checker_dialog import CheckerDialog
    from .completeness_checker_dialog import CompletenessCheckerDialog
    from .gpkg_to_excel_dialog import GpkgToExcelDialog
    from .updater import check_for_updates
except (ImportError, ValueError):
    from style import apply_modern_style, setup_dialog_logo
    from GeoFASU_dialog import GeoFASUDialog
    from loader_dialog import LoaderDialog
    from checker_dialog import CheckerDialog
    from completeness_checker_dialog import CompletenessCheckerDialog
    from gpkg_to_excel_dialog import GpkgToExcelDialog
    from updater import check_for_updates

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'main_dialog.ui'))


def apply_responsive_geometry(dialog, preferred_w=920, preferred_h=640, min_w=640, min_h=400):
    """
    Dynamically sizes and centers the dialog to fit any display resolution
    (especially laptops like 1366x768, 1080p with 125%/150% scaling, or compact screens).
    Also enables window maximize/minimize/restore controls.
    """
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowMinMaxButtonsHint)

    from qgis.PyQt.QtWidgets import QApplication
    screen = QApplication.primaryScreen()
    if screen:
        avail = screen.availableGeometry()
        avail_w = avail.width()
        avail_h = avail.height()

        target_w = min(preferred_w, max(min_w, int(avail_w * 0.92)))
        target_h = min(preferred_h, max(min_h, int(avail_h * 0.88)))

        safe_min_w = min(min_w, int(avail_w * 0.75))
        safe_min_h = min(min_h, int(avail_h * 0.60))
        dialog.setMinimumSize(safe_min_w, safe_min_h)

        x = avail.x() + max(0, (avail_w - target_w) // 2)
        y = avail.y() + max(0, (avail_h - target_h) // 2)
        dialog.setGeometry(x, y, target_w, target_h)

        logo_h = 45 if avail_h < 760 else 65
        setup_dialog_logo(dialog, max_width=200, max_height=logo_h)
    else:
        dialog.resize(preferred_w, preferred_h)
        dialog.setMinimumSize(min_w, min_h)
        setup_dialog_logo(dialog, max_width=220, max_height=65)


def open_default_folder_in_explorer():
    """Opens the default project folder in Windows File Explorer."""
    default_dir = r"C:\PSA-GIS\GeoFASU\Kalinga\Project files"
    os.makedirs(default_dir, exist_ok=True)
    try:
        os.startfile(default_dir)
    except Exception:
        from qgis.PyQt.QtGui import QDesktopServices
        from qgis.PyQt.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(default_dir))


def _make_scroll(widget):
    widget.setWindowFlags(Qt.Widget)
    widget.setMinimumSize(0, 0)
    if hasattr(widget, 'iconLabel'):
        widget.iconLabel.hide()
    if hasattr(widget, 'closeButton'):
        widget.closeButton.hide()
    if hasattr(widget, 'openFolderButton'):
        widget.openFolderButton.hide()
    if hasattr(widget, 'mainHorizontalLayout') and widget.mainHorizontalLayout:
        widget.mainHorizontalLayout.setStretch(0, 1)
        widget.mainHorizontalLayout.setStretch(1, 1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setWidget(widget)
    return scroll


class PreprocessingDialog(QDialog, FORM_CLASS):
    """Preprocessing workflow dialog containing Excel to GPKG and Load/Generate QField."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setWindowTitle("GeoFASU_Ori - Preprocessing")
        apply_modern_style(self)
        apply_responsive_geometry(self, preferred_w=920, preferred_h=620, min_w=640, min_h=400)

        icons_path = Path(__file__).parent / "icons"

        self.btn_update.setProperty("secondary", True)
        self.btn_open_folder.setProperty("secondary", True)
        self.btn_close.setProperty("secondary", True)
        self.btn_update.clicked.connect(lambda: check_for_updates(self, silent_if_latest=False))
        self.btn_open_folder.clicked.connect(self.open_default_folder)
        self.btn_close.clicked.connect(self.close)

        folder_icon = icons_path / "folder.png"
        if folder_icon.exists():
            self.btn_open_folder.setIcon(QIcon(str(folder_icon)))

        # Modules
        self.tab_converter = GeoFASUDialog(parent=self)
        self.tab_loader = LoaderDialog(parent=self)
        self.tab_converter.process_completed.connect(self.on_converter_completed)

        self.tabs = [
            (self.tab_converter, "Excel to GPKG", "converter.png"),
            (self.tab_loader, "Load and Generate QField", "loader.png"),
        ]

        self.tabWidget.clear()
        for widget, title, icon_name in self.tabs:
            icon_file = icons_path / icon_name
            icon = QIcon(str(icon_file)) if icon_file.exists() else QIcon()
            self.tabWidget.addTab(_make_scroll(widget), icon, title)

        self.tabWidget.currentChanged.connect(self.on_tab_changed)

    def on_tab_changed(self, index: int):
        for widget, _, _ in self.tabs:
            if hasattr(widget, 'clear_logs'):
                widget.clear_logs()
            elif hasattr(widget, 'logsTextEdit') and widget.logsTextEdit:
                widget.logsTextEdit.clear()

    def on_converter_completed(self, survey_name: str = "", out_dir: str = ""):
        if hasattr(self, 'tab_loader'):
            if out_dir and os.path.isdir(out_dir):
                self.tab_loader.fileWidget.setFilePath(out_dir)
            self.tab_loader.populate_nos_list()
            if survey_name:
                idx = self.tab_loader.comboxNOS.findText(survey_name)
                if idx != -1:
                    self.tab_loader.comboxNOS.setCurrentIndex(idx)
                    self.tab_loader.update_mun_list()

    def open_default_folder(self):
        """Opens the default project folder in Windows File Explorer."""
        open_default_folder_in_explorer()

    def set_active_tab(self, index: int):
        if 0 <= index < self.tabWidget.count():
            self.tabWidget.setCurrentIndex(index)
            self.on_tab_changed(index)

    def showEvent(self, event):
        super().showEvent(event)
        from qgis.PyQt.QtWidgets import QApplication
        screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            new_w = min(self.width(), int(avail.width() * 0.95))
            new_h = min(self.height(), int(avail.height() * 0.90))
            if new_w != self.width() or new_h != self.height():
                self.resize(new_w, new_h)

    def reset_all_modules(self):
        """Resets all fields in all preprocessing modules to their default values."""
        for widget, _, _ in self.tabs:
            if hasattr(widget, 'reset_fields'):
                widget.reset_fields()
        if 0 < self.tabWidget.count():
            self.tabWidget.setCurrentIndex(0)

    def closeEvent(self, event):
        """Resets all fields in all modules when the dialog is closed."""
        self.reset_all_modules()
        event.accept()

    def reject(self):
        """Resets all fields in all modules when the dialog is dismissed."""
        self.reset_all_modules()
        super().reject()


class PostprocessingDialog(QDialog, FORM_CLASS):
    """Postprocessing workflow dialog containing Quality Checker and GPKG to Excel."""
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setupUi(self)
        self.setWindowTitle("GeoFASU_Ori - Postprocessing")
        apply_modern_style(self)
        apply_responsive_geometry(self, preferred_w=920, preferred_h=640, min_w=640, min_h=420)

        icons_path = Path(__file__).parent / "icons"

        self.btn_update.setProperty("secondary", True)
        self.btn_open_folder.setProperty("secondary", True)
        self.btn_close.setProperty("secondary", True)
        self.btn_update.clicked.connect(lambda: check_for_updates(self, silent_if_latest=False))
        self.btn_open_folder.clicked.connect(self.open_default_folder)
        self.btn_close.clicked.connect(self.close)

        folder_icon = icons_path / "folder.png"
        if folder_icon.exists():
            self.btn_open_folder.setIcon(QIcon(str(folder_icon)))

        # Modules
        self.tab_checker = CheckerDialog(iface=self.iface, parent=self)
        self.tab_completeness = CompletenessCheckerDialog(iface=self.iface, parent=self)
        self.tab_gpkg_excel = GpkgToExcelDialog(parent=self)

        # Gatekeeping Quality Checker -> Completeness Checker
        self.last_passed_layer_id = None
        self.tab_checker.quality_check_passed.connect(self.on_quality_check_passed)
        self.tab_checker.quality_check_failed.connect(self.on_quality_check_failed)

        self.tabs = [
            (self.tab_checker, "Quality Checker", "checker.png"),
            (self.tab_completeness, "Completeness Checker", "completeness.png"),
            (self.tab_gpkg_excel, "GPKG to Excel", "gpkg_to_excel.png"),
        ]

        self.tabWidget.clear()
        for widget, title, icon_name in self.tabs:
            icon_file = icons_path / icon_name
            icon = QIcon(str(icon_file)) if icon_file.exists() else QIcon()
            self.tabWidget.addTab(_make_scroll(widget), icon, title)

        self.tabWidget.currentChanged.connect(self.on_tab_changed)

    def on_quality_check_passed(self, layer_id: str):
        """Called when Quality Checker passes with 0 errors."""
        self.last_passed_layer_id = layer_id
        if hasattr(self, 'tab_completeness'):
            self.tab_completeness.set_quality_check_state(True, layer_id)

    def on_quality_check_failed(self):
        """Called when Quality Checker fails, has errors, or layer selection changes."""
        self.last_passed_layer_id = None
        if hasattr(self, 'tab_completeness'):
            self.tab_completeness.set_quality_check_state(False)

    def on_tab_changed(self, index: int):
        # Reset logs across tabs when tab changes
        for widget, _, _ in self.tabs:
            if hasattr(widget, 'clear_logs'):
                widget.clear_logs()
            elif hasattr(widget, 'logsTextEdit') and widget.logsTextEdit:
                widget.logsTextEdit.clear()

        if index == 1 and hasattr(self, 'tab_completeness'):
            if self.last_passed_layer_id:
                self.tab_completeness.set_quality_check_state(True, self.last_passed_layer_id)
            else:
                self.tab_completeness.set_quality_check_state(False)
        elif index == 2 and hasattr(self, 'tab_gpkg_excel'):
            self.tab_gpkg_excel.check_buttons_state()

    def open_default_folder(self):
        """Opens the default project folder in Windows File Explorer."""
        open_default_folder_in_explorer()

    def set_active_tab(self, index: int):
        if 0 <= index < self.tabWidget.count():
            self.tabWidget.setCurrentIndex(index)
            self.on_tab_changed(index)

    def showEvent(self, event):
        super().showEvent(event)
        from qgis.PyQt.QtWidgets import QApplication
        screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            new_w = min(self.width(), int(avail.width() * 0.95))
            new_h = min(self.height(), int(avail.height() * 0.90))
            if new_w != self.width() or new_h != self.height():
                self.resize(new_w, new_h)

    def reset_all_modules(self):
        """Resets all fields in all postprocessing modules to their default values."""
        self.last_passed_layer_id = None
        for widget, _, _ in self.tabs:
            if hasattr(widget, 'reset_fields'):
                widget.reset_fields()
        if 0 < self.tabWidget.count():
            self.tabWidget.setCurrentIndex(0)

    def closeEvent(self, event):
        """Resets all fields in all modules when the dialog is closed."""
        self.reset_all_modules()
        event.accept()

    def reject(self):
        """Resets all fields in all modules when the dialog is dismissed."""
        self.reset_all_modules()
        super().reject()


# Backward compatibility alias
GeoFASUMainDialog = PreprocessingDialog
