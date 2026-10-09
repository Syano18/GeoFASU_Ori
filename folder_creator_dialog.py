# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph

import os
from pathlib import Path

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.gui import QgsFileWidget

from .style import apply_modern_style, setup_dialog_logo

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "folder_creator_dialog.ui")
)

STANDARD_FOLDERS = [
    "Base Layers",
    "Basemap",
    "Excel",
    "Filepinas",
    "From Tablet",
    "Package for Qfield",
    "Projects",
    "Samples",
    "Template",
    "Validation Output"
]

class FolderCreatorDialog(QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        apply_modern_style(self)
        setup_dialog_logo(self)
        
        self.openBtn.setProperty("secondary", True)
        self.openBtn.setEnabled(False)
        self.progressBar.setValue(0)
        
        # Default suggested values
        default_base = r"C:\PSA-GIS\GeoFASU"
        self.baseDirWidget.setFilePath(default_base)
        self.provinceEdit.setText("Kalinga")
        self.projectFolderEdit.setText("Project files")
        
        self.update_preview()
        
        # Signals
        self.baseDirWidget.fileChanged.connect(self.update_preview)
        self.provinceEdit.textChanged.connect(self.update_preview)
        self.projectFolderEdit.textChanged.connect(self.update_preview)
        self.createBtn.clicked.connect(self.create_folders)
        self.openBtn.clicked.connect(self.open_in_explorer)

    def get_target_path(self):
        base = self.baseDirWidget.filePath().strip()
        prov = self.provinceEdit.text().strip()
        proj = self.projectFolderEdit.text().strip()
        
        parts = [p for p in [base, prov, proj] if p]
        if parts:
            return os.path.normpath(os.path.join(*parts))
        return ""

    def are_folders_present(self, target_dir):
        """Checks if all standard subfolders already exist inside target_dir."""
        if not target_dir or not os.path.isdir(target_dir):
            return False
        return all(os.path.isdir(os.path.join(target_dir, f)) for f in STANDARD_FOLDERS)

    def update_preview(self):
        target = self.get_target_path()
        self.previewEdit.setText(target)
        
        folders_exist = self.are_folders_present(target)
        if folders_exist:
            self.createBtn.setEnabled(False)
            self.createBtn.setText("Folders Already Present")
            self.createBtn.setToolTip("All standard project folders are already present in this directory.")
            self.openBtn.setEnabled(True)
        else:
            self.createBtn.setEnabled(bool(target))
            self.createBtn.setText("Create Folders")
            self.createBtn.setToolTip("")
            self.openBtn.setEnabled(os.path.isdir(target))

    def create_folders(self):
        base = self.baseDirWidget.filePath().strip()
        prov = self.provinceEdit.text().strip()
        proj = self.projectFolderEdit.text().strip()
        
        if not base:
            QMessageBox.warning(self, "Missing Directory", "Please specify a Base Directory.")
            return

        target_dir = self.get_target_path()
        if not target_dir:
            QMessageBox.warning(self, "Invalid Path", "Please enter a valid directory structure.")
            return

        if self.are_folders_present(target_dir):
            QMessageBox.information(
                self,
                "Folders Already Present",
                f"The standard GeoFASU folder structure already exists at:\n\n{target_dir}"
            )
            self.update_preview()
            return

        self.createBtn.setEnabled(False)
        self.progressBar.setValue(0)
        QCoreApplication.processEvents()

        try:
            os.makedirs(target_dir, exist_ok=True)
            self.progressBar.setValue(10)
            QCoreApplication.processEvents()

            total = len(STANDARD_FOLDERS)
            for idx, folder_name in enumerate(STANDARD_FOLDERS):
                folder_path = os.path.join(target_dir, folder_name)
                os.makedirs(folder_path, exist_ok=True)
                
                step_val = int(10 + (((idx + 1) / total) * 90))
                self.progressBar.setValue(step_val)
                QCoreApplication.processEvents()

            self.progressBar.setValue(100)
            self.openBtn.setEnabled(True)
            QCoreApplication.processEvents()

            folders_str = "\n".join([f" • {f}" for f in STANDARD_FOLDERS])
            QMessageBox.information(
                self,
                "Folders Created",
                f"Successfully created standard GeoFASU folder structure at:\n\n{target_dir}\n\nFolders:\n{folders_str}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Creation Failed", f"Failed to create folders:\n{str(e)}")
        finally:
            self.update_preview()

    def open_in_explorer(self):
        target_dir = self.get_target_path()
        if os.path.isdir(target_dir):
            if hasattr(os, 'startfile'):
                os.startfile(target_dir)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(target_dir))
        else:
            QMessageBox.warning(self, "Not Found", f"Directory does not exist yet:\n{target_dir}")
