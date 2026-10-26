# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph
# Refactored for robustness, modern UI and responsive progress.

import os
import shutil
import pandas as pd

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.PyQt.QtCore import Qt, QVariant, QCoreApplication, pyqtSignal
from qgis.PyQt.QtGui import QPixmap
from qgis.core import (
    QgsVectorLayer,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFields,
    QgsVectorFileWriter,
    QgsField,
    QgsGeometry,
)
from qgis.gui import QgsFileWidget
try:
    from .style import apply_modern_style, setup_dialog_logo
except (ImportError, ValueError):
    from style import apply_modern_style, setup_dialog_logo

# Load the UI class from the .ui file
FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "GeoFASU_dialog_base.ui")
)

class GeoFASUDialog(QDialog, FORM_CLASS):
    process_completed = pyqtSignal(str, str)
    def __init__(self, parent=None):
        """Initializes the dialog."""
        super().__init__(parent)
        self.setupUi(self)
        apply_modern_style(self)
        setup_dialog_logo(self)
        self.progressBar.setValue(0)
        self.runButton.clicked.connect(self.run_process)
        self.csvFileWidget.setStorageMode(QgsFileWidget.GetFile)
        self.csvFileWidget.setFilter("Excel Files (*.xlsx)")
        self.outputDirWidget.setStorageMode(QgsFileWidget.GetDirectory)
        default_dir = r"C:\PSA-GIS\GeoFASU\Kalinga\Project files"
        self.outputDirWidget.setFilePath(default_dir)
        self.typeofS.setFocus()

    def log(self, message: str, level: str = "INFO"):
        """Appends a line of text to the logs widget with level indicator."""
        prefix = {
            "INFO": "",
            "SUCCESS": "✓ ",
            "WARNING": "⚠ ",
            "ERROR": "✗ ",
        }.get(level.upper(), "")
        if hasattr(self, 'logsTextEdit') and self.logsTextEdit:
            self.logsTextEdit.appendPlainText(f"{prefix}{message}")
            self.logsTextEdit.verticalScrollBar().setValue(
                self.logsTextEdit.verticalScrollBar().maximum()
            )

    def run_process(self):
        """Main function to execute the entire process when the 'Run' button is clicked."""
        self.logsTextEdit.clear()
        self.log("STATUS: RUNNING...", "INFO")
        csv_path = self.csvFileWidget.filePath().strip()
        out_dir = self.outputDirWidget.filePath().strip()
        folder_name = self.typeofS.text().strip()

        # --- 1. Input Validation ---
        if not all([csv_path, out_dir, folder_name]):
            self.log("STATUS: FAILED ✗", "ERROR")
            self.log("Please provide all inputs: Excel file, output directory, and survey name.", "WARNING")
            return

        if not csv_path.lower().endswith(('.xlsx', '.xls')):
            self.log("STATUS: FAILED ✗", "ERROR")
            self.log("Invalid File Type: Please select an Excel file (.xlsx).", "WARNING")
            return

        self.runButton.setEnabled(False)
        self.progressBar.setValue(0)
        self.log(f"Starting conversion for survey '{folder_name}'...", "INFO")
        QCoreApplication.processEvents()

        try:
            # --- 2. Read and Prepare Data ---
            df = self._read_and_combine_sheets(csv_path)

            if df is None or df.empty:
                self.log("STATUS: FAILED ✗", "ERROR")
                return

            # --- 3. Create Output Directories ---
            project_folder = os.path.join(out_dir, 'Projects', folder_name)
            qfield_folder = os.path.join(out_dir, 'Package for Qfield', folder_name)
            validation_folder = os.path.join(out_dir, 'Validation Output', folder_name)
            filepinas_folder = os.path.join(out_dir, 'Filepinas', folder_name)
            excel_folder = os.path.join(out_dir, 'Excel', folder_name)
            from_tablet_folder = os.path.join(out_dir, 'From Tablet', folder_name)
            os.makedirs(project_folder, exist_ok=True)
            os.makedirs(qfield_folder, exist_ok=True)
            os.makedirs(validation_folder, exist_ok=True)
            os.makedirs(filepinas_folder, exist_ok=True)
            os.makedirs(excel_folder, exist_ok=True)
            os.makedirs(from_tablet_folder, exist_ok=True)

            self.progressBar.setValue(10)
            QCoreApplication.processEvents()

            # --- 4. Process and Export Data ---
            self._export_to_geopackages(df, folder_name, project_folder, filepinas_folder, validation_folder, from_tablet_folder)

            self.progressBar.setValue(100)
            QCoreApplication.processEvents()
            self.log("STATUS: COMPLETED ✓", "SUCCESS")
            self.log(f"GeoPackages created successfully for survey '{folder_name}'! ✓", "SUCCESS")
            self.log(f"Saved to: {project_folder}", "INFO")
            self.process_completed.emit(folder_name, out_dir)

        except Exception as e:
            self.log("STATUS: FAILED ✗", "ERROR")
            self.log(f"An unexpected error occurred: {e}", "ERROR")
        finally:
            self.runButton.setEnabled(True)

    def _read_and_combine_sheets(self, csv_path):
        """
        Reads 'Sample SSU' (required) and 'Replacement SSU' (optional) sheets.
        Returns a combined and cleaned DataFrame, or None if the required sheet is missing.
        """
        df_sample = None
        df_replacement = None

        # --- 1. Read the REQUIRED 'Sample SSU' sheet ---
        try:
            df_sample = pd.read_excel(csv_path, sheet_name='Sample SSU', dtype=str)
            if df_sample is not None and not df_sample.empty:
                df_sample['_sheet_source'] = 'Sample SSU'
        except (ValueError, KeyError):
            self.log("The required sheet 'Sample SSU' was not found in the Excel file. The process cannot continue.", "ERROR")
            return None

        # --- 2. Read the OPTIONAL 'Replacement SSU' sheet ---
        try:
            df_replacement = pd.read_excel(csv_path, sheet_name='Replacement SSU', dtype=str)
            if df_replacement is not None and not df_replacement.empty:
                df_replacement['_sheet_source'] = 'Replacement SSU'
        except (ValueError, KeyError):
            pass

        # --- 3. Combine the dataframes ---
        valid_dfs = [df for df in [df_sample, df_replacement] if df is not None]
        df = pd.concat(valid_dfs, ignore_index=True)

        # --- 4. Data Cleaning and Validation ---
        if 'WKT' not in df.columns:
            self.log("A 'WKT' column is required in the Excel file but was not found.", "ERROR")
            return None
            
        df = df.dropna(subset=['WKT'])
        if df.empty:
            self.log("No rows with valid WKT geometry were found after cleaning.", "WARNING")
            return None

        df = df.fillna("")
        return df

    def _export_to_geopackages(self, df, folder_name, project_folder, filepinas_folder, validation_folder, from_tablet_folder):
        """
        Copies template selected.gpkg and populates sample points directly into it.
        """
        template_path = os.path.join(os.path.dirname(__file__), "selected.gpkg")
        if not os.path.exists(template_path):
            self.log(f"Template GeoPackage 'selected.gpkg' not found: {template_path}", "ERROR")
            raise FileNotFoundError(f"Template GeoPackage 'selected.gpkg' not found: {template_path}")

        # Check for required grouping columns
        required_cols = ['Mun_name', 'Replicate_Number']
        if not all(col in df.columns for col in required_cols):
            missing = ", ".join([col for col in required_cols if col not in df.columns])
            raise KeyError(f"Missing required column(s) for grouping: {missing}")

        municipalities = df['Mun_name'].unique()
        total_mun = len(municipalities)
        count = 0

        for mun_name, group_mun in df.groupby('Mun_name'):
            mun_project_path = os.path.join(project_folder, str(mun_name))
            mun_filepinas_path = os.path.join(filepinas_folder, str(mun_name))
            mun_validation_path = os.path.join(validation_folder, str(mun_name))
            mun_from_tablet_path = os.path.join(from_tablet_folder, str(mun_name))
            os.makedirs(mun_project_path, exist_ok=True)
            os.makedirs(mun_filepinas_path, exist_ok=True)
            os.makedirs(mun_validation_path, exist_ok=True)
            os.makedirs(mun_from_tablet_path, exist_ok=True)

            reps = group_mun.groupby('Replicate_Number')
            total_reps = len(reps)
            rep_idx = 0

            for rep_num, group_rep in reps:
                rep_str = str(rep_num).strip()
                if not rep_str.upper().startswith("R"):
                    rep_str = f"R{rep_str}"

                rep_folder_path = os.path.join(mun_project_path, rep_str)
                if os.path.exists(rep_folder_path):
                    shutil.rmtree(rep_folder_path)
                os.makedirs(rep_folder_path, exist_ok=True)

                out_filename = f"{folder_name}_{mun_name}_Selected SSU_{rep_str}.gpkg"
                out_path = os.path.join(rep_folder_path, out_filename)

                # Copy template selected.gpkg
                shutil.copyfile(template_path, out_path)

                # Open destination layer and populate features directly into it
                dest_layer = QgsVectorLayer(out_path, f"{mun_name}_{rep_str}", "ogr")
                if not dest_layer.isValid():
                    self.log(f"Failed to open destination GeoPackage: {out_path}", "ERROR")
                    continue

                layer_fields = dest_layer.fields()
                field_map = {}
                for f in layer_fields:
                    fname = f.name()
                    field_map[fname.lower()] = fname
                    field_map[fname.lower().replace(" ", "_").replace("-", "_")] = fname

                features = []
                for _, row in group_rep.iterrows():
                    wkt_val = row.get("WKT", None)
                    if not wkt_val or pd.isna(wkt_val):
                        continue
                    geom = QgsGeometry.fromWkt(str(wkt_val).strip())
                    if not geom or not geom.isGeosValid():
                        continue

                    feat = QgsFeature(layer_fields)
                    feat.setGeometry(geom)

                    for col in group_rep.columns:
                        if col in ("WKT", "_sheet_source"):
                            continue
                        col_clean = str(col).strip()
                        col_lower = col_clean.lower()
                        col_norm = col_lower.replace(" ", "_").replace("-", "_")
                        target_field = field_map.get(col_lower) or field_map.get(col_norm)
                        if target_field:
                            val = row[col]
                            if pd.notna(val) and str(val).strip() != "":
                                if target_field.lower().replace(" ", "_") == "selected_ssu":
                                    s_val = str(val).strip()
                                    if s_val in ("1", "1.0") or "sample" in s_val.lower():
                                        val = "1"
                                    elif s_val in ("2", "2.0") or "replacement" in s_val.lower():
                                        val = "2"
                                    elif s_val in ("3", "3.0") or "additional" in s_val.lower():
                                        val = "3"
                                    else:
                                        try:
                                            val = str(int(float(s_val)))
                                        except (ValueError, TypeError):
                                            val = "1"
                                feat.setAttribute(target_field, val)

                    # Ensure Selected_SSU is set (must have value of only 1 for Sample SSU, 2 for Replacement)
                    target_ssu = field_map.get("selected_ssu")
                    if target_ssu:
                        curr_ssu = feat.attribute(target_ssu)
                        if curr_ssu is None or str(curr_ssu).strip() in ("", "NULL", "None"):
                            sheet_src = row.get("_sheet_source", "Sample SSU")
                            if sheet_src == "Replacement SSU":
                                feat.setAttribute(target_ssu, "2")
                            else:
                                feat.setAttribute(target_ssu, "1")

                    # Ensure inCentroid is set (default 2 for valid WKT)
                    target_inc = field_map.get("incentroid")
                    if target_inc:
                        curr_inc = feat.attribute(target_inc)
                        if curr_inc is None or str(curr_inc).strip() in ("", "NULL", "None"):
                            feat.setAttribute(target_inc, "2")

                    # Ensure orig_wkt is set
                    target_orig = field_map.get("orig_wkt")
                    if target_orig:
                        curr_orig = feat.attribute(target_orig)
                        if curr_orig is None or str(curr_orig).strip() in ("", "NULL", "None"):
                            feat.setAttribute(target_orig, str(wkt_val).strip())

                    features.append(feat)

                provider = dest_layer.dataProvider()
                provider.addFeatures(features)
                dest_layer.updateExtents()
                del dest_layer

                rep_idx += 1
                # Responsive granular progress calculation
                step_prog = int(10 + (((count + (rep_idx / total_reps)) / total_mun) * 85))
                self.progressBar.setValue(min(step_prog, 95))
                QCoreApplication.processEvents()

            count += 1

    def clear_logs(self):
        """Clears the execution logs and resets progress bar."""
        if hasattr(self, 'logsTextEdit') and self.logsTextEdit:
            self.logsTextEdit.clear()
        if hasattr(self, 'progressBar') and self.progressBar:
            self.progressBar.setValue(0)

    def reset_fields(self):
        """Resets all input fields and the progress bar to their default state."""
        self.csvFileWidget.setFilePath("")
        default_dir = r"C:\PSA-GIS\GeoFASU\Kalinga\Project files"
        self.outputDirWidget.setFilePath(default_dir)
        self.typeofS.clear()
        self.progressBar.setValue(0)
        self.runButton.setEnabled(True)
        self.clear_logs()

    def closeEvent(self, event):
        """Ensures fields are reset when the dialog is closed."""
        self.reset_fields()
        event.accept()

    def reject(self):
        """Ensures fields are reset when the dialog is dismissed."""
        self.reset_fields()
        super().reject()