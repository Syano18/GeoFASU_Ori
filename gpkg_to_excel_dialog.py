# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph

import os
import re
import pandas as pd
from collections import defaultdict

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import QgsVectorLayer, QgsProviderRegistry
import processing

try:
    from .style import apply_modern_style, setup_dialog_logo
except (ImportError, ValueError):
    from style import apply_modern_style, setup_dialog_logo

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "gpkg_to_excel_dialog.ui")
)

class GpkgToExcelDialog(QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        apply_modern_style(self)
        setup_dialog_logo(self)
        self.progressBar.setValue(0)
        self.mergeBtn.clicked.connect(self.run_merge)
        self.exportBtn.clicked.connect(self.run_export_excel)
        
        self.comboxNOS.setPlaceholderText("-- Select Type of Survey --")
        self.comboxMun.setPlaceholderText("-- Select City/Municipality --")

        # Signals for dropdowns
        self.fileWidget.fileChanged.connect(self.populate_nos_list)
        self.comboxNOS.currentIndexChanged.connect(self.update_mun_list)
        self.comboxMun.currentIndexChanged.connect(self.check_buttons_state)

        # Default Reference Directory
        default_ref = r"C:\PSA-GIS\GeoFASU\Kalinga\Project files"
        self.fileWidget.setFilePath(default_ref)
        if os.path.isdir(default_ref):
            self.populate_nos_list()
        self.check_buttons_state()

    def showEvent(self, event):
        super().showEvent(event)
        self.check_buttons_state()

    def check_buttons_state(self):
        """Updates the enabled states and tooltips for both Merge and Export to Excel buttons."""
        self.check_merge_state()
        self.check_export_state()

    def check_merge_state(self):
        """Enables the Merge button only if there is at least one .gpkg file inside the city/mun folder in Validation Output."""
        base_dir = self.fileWidget.filePath().strip() if hasattr(self, 'fileWidget') else ""
        nos = self.comboxNOS.currentText().strip() if hasattr(self, 'comboxNOS') else ""
        mun = self.comboxMun.currentText().strip() if hasattr(self, 'comboxMun') else ""

        has_gpkg = False
        if base_dir and nos and mun:
            mun_dir = os.path.join(base_dir, 'Validation Output', nos, mun)
            if os.path.isdir(mun_dir):
                for root, _, files in os.walk(mun_dir):
                    if any(f.lower().endswith('.gpkg') for f in files):
                        has_gpkg = True
                        break

        self.mergeBtn.setEnabled(has_gpkg)
        if has_gpkg:
            self.mergeBtn.setToolTip("Click to merge GeoPackage files for the selected City/Municipality into Filepinas.")
        elif not mun:
            self.mergeBtn.setToolTip("Please select a City/Municipality with at least one .gpkg file in Validation Output to enable Merge.")
        else:
            self.mergeBtn.setToolTip(f"No .gpkg files found in 'Validation Output/{nos}/{mun}'.")

    def check_export_state(self):
        """Enables the Export to Excel button if there is at least one merged .gpkg file inside the Filepinas survey folder."""
        base_dir = self.fileWidget.filePath().strip() if hasattr(self, 'fileWidget') else ""
        nos = self.comboxNOS.currentText().strip() if hasattr(self, 'comboxNOS') else ""

        has_gpkg = False
        if base_dir and nos:
            filepinas_survey_dir = os.path.join(base_dir, 'Filepinas', nos)
            if os.path.isdir(filepinas_survey_dir):
                for root, _, files in os.walk(filepinas_survey_dir):
                    if any(f.lower().endswith('.gpkg') for f in files):
                        has_gpkg = True
                        break

        self.exportBtn.setEnabled(has_gpkg)
        if has_gpkg:
            self.exportBtn.setToolTip("Click to export all merged GeoPackage files in Filepinas to 032_GEOMS_Excel_Upload.xlsx.")
        else:
            self.exportBtn.setToolTip("Please merge all Sample SSU files across all cities/municipalities first.")

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

    def populate_nos_list(self):
        self.comboxNOS.blockSignals(True)
        self.comboxMun.blockSignals(True)

        self.comboxNOS.clear()
        self.comboxMun.clear()
        self.progressBar.setValue(0)

        nos_set = set()
        val_path = os.path.join(self.fileWidget.filePath(), 'Validation Output')
        if os.path.isdir(val_path):
            nos_set.update([d for d in os.listdir(val_path) if os.path.isdir(os.path.join(val_path, d))])
        filepinas_path = os.path.join(self.fileWidget.filePath(), 'Filepinas')
        if os.path.isdir(filepinas_path):
            nos_set.update([d for d in os.listdir(filepinas_path) if os.path.isdir(os.path.join(filepinas_path, d))])

        if nos_set:
            self.comboxNOS.addItems(sorted(list(nos_set)))
            self.comboxNOS.setCurrentIndex(-1)

        self.comboxNOS.blockSignals(False)
        self.comboxMun.blockSignals(False)
        self.check_buttons_state()

    def update_mun_list(self):
        self.comboxMun.blockSignals(True)
        self.comboxMun.clear()
        nos = self.comboxNOS.currentText().strip()
        if nos:
            mun_set = set()
            val_path = os.path.join(self.fileWidget.filePath(), 'Validation Output', nos)
            if os.path.isdir(val_path):
                mun_set.update([d for d in os.listdir(val_path) if os.path.isdir(os.path.join(val_path, d))])
            filepinas_path = os.path.join(self.fileWidget.filePath(), 'Filepinas', nos)
            if os.path.isdir(filepinas_path):
                mun_set.update([d for d in os.listdir(filepinas_path) if os.path.isdir(os.path.join(filepinas_path, d))])

            if mun_set:
                self.comboxMun.addItems(sorted(list(mun_set)))
                self.comboxMun.setCurrentIndex(-1)

        self.comboxMun.blockSignals(False)
        self.check_buttons_state()

    def run_merge(self):
        self.logsTextEdit.clear()
        self.log("STATUS: MERGING...", "INFO")
        base_dir = self.fileWidget.filePath().strip()
        nos = self.comboxNOS.currentText().strip()
        mun = self.comboxMun.currentText().strip()

        if not all([base_dir, nos, mun]):
            self.log("STATUS: FAILED ✗", "ERROR")
            self.log("Please ensure all fields are selected (Directory, Survey, and Municipality).", "WARNING")
            self.progressBar.setValue(0)
            return

        mun_dir = os.path.join(base_dir, 'Validation Output', nos, mun)
        if not os.path.isdir(mun_dir):
            self.log(f"The directory does not exist: {mun_dir}", "WARNING")
            self.progressBar.setValue(0)
            return
        
        # Group GPKG paths by replicate number
        rep_gpkgs = defaultdict(list)
        
        for root, dirs, files in os.walk(mun_dir):
            for file in files:
                if file.endswith('.gpkg'):
                    gpkg_path = os.path.join(root, file)
                    match = re.search(r'_Selected SSU_(R\d+)', gpkg_path)
                    if match:
                        rep_no = match.group(1)
                        rep_gpkgs[rep_no].append(gpkg_path)
                        
        if not rep_gpkgs:
            self.log(
                f"No matching .gpkg files (with Replicate Number in filename/path) were found in: {mun_dir}",
                "WARNING"
            )
            self.progressBar.setValue(0)
            return

        filepinas_dir = os.path.join(base_dir, 'Filepinas', nos, mun)
        os.makedirs(filepinas_dir, exist_ok=True)
        
        # Pre-flight check: ensure output files are not locked
        existing_files = []
        locked_files = []
        
        for rep_no in rep_gpkgs.keys():
            merged_gpkg_name = f"{nos}_{mun}_Selected SSU_{rep_no}.gpkg"
            merged_gpkg_path = os.path.join(filepinas_dir, merged_gpkg_name)
            
            if os.path.exists(merged_gpkg_path):
                existing_files.append(merged_gpkg_path)
                try:
                    with open(merged_gpkg_path, 'a'):
                        pass
                except IOError:
                    locked_files.append(merged_gpkg_path)
                        
        if locked_files:
            locked_msg = ", ".join([os.path.basename(f) for f in locked_files])
            self.log(f"The following GeoPackage files are currently open or locked: {locked_msg}. Please close them and try again.", "ERROR")
            self.progressBar.setValue(0)
            return
            
        if existing_files:
            self.log(f"Existing merged GeoPackage files detected in Filepinas ({len(existing_files)} file(s)). Overwriting...", "INFO")
            for f in existing_files:
                try:
                    os.remove(f)
                except Exception as e:
                    self.log(f"Failed to delete existing file before overwriting: {f} (Error: {e})", "ERROR")
                    self.progressBar.setValue(0)
                    return

        self.mergeBtn.setEnabled(False)
        self.exportBtn.setEnabled(False)
        self.progressBar.setValue(0)
        QCoreApplication.processEvents()

        try:
            total_reps = len(rep_gpkgs)
            current_rep = 0
            
            for rep_no, gpkg_list in rep_gpkgs.items():
                base_prog = int((current_rep / total_reps) * 100)
                self.progressBar.setValue(base_prog + 5)
                QCoreApplication.processEvents()
                
                merged_gpkg_name = f"{nos}_{mun}_Selected SSU_{rep_no}.gpkg"
                merged_gpkg_path = os.path.join(filepinas_dir, merged_gpkg_name)
                
                layers_to_merge = []
                for g in gpkg_list:
                    sublayers = QgsProviderRegistry.instance().providerMetadata('ogr').querySublayers(g)
                    valid_layer = None
                    for sub in sublayers:
                        if sub.name().lower() not in ['layer_styles', 'sqlite_sequence']:
                            l = QgsVectorLayer(sub.uri(), sub.name(), "ogr")
                            if l.isValid() and l.featureCount() > 0:
                                valid_layer = l
                                break
                            elif l.isValid() and valid_layer is None:
                                valid_layer = l
                    if valid_layer:
                        layers_to_merge.append(valid_layer)
                
                if not layers_to_merge:
                    current_rep += 1
                    continue
                    
                # Merge vector layers to memory first
                params = {
                    'LAYERS': layers_to_merge,
                    'CRS': layers_to_merge[0].crs(),
                    'OUTPUT': 'memory:merged_temp'
                }
                temp_merged = processing.run("native:mergevectorlayers", params)['OUTPUT']
                
                self.progressBar.setValue(base_prog + int(50 / total_reps))
                QCoreApplication.processEvents()

                # Delete 'layer', 'path', and 'fid' columns if present to avoid fid UNIQUE constraint violations
                cols_to_del = [c for c in ['layer', 'path', 'fid'] if temp_merged.fields().indexOf(c) != -1]
                if cols_to_del:
                    params_del = {
                        'INPUT': temp_merged,
                        'COLUMN': cols_to_del,
                        'OUTPUT': merged_gpkg_path
                    }
                    processing.run("native:deletecolumn", params_del)
                else:
                    params_save = {
                        'INPUT': temp_merged,
                        'OUTPUT': merged_gpkg_path
                    }
                    processing.run("native:savefeatures", params_save)
                
                current_rep += 1
                self.progressBar.setValue(int((current_rep / total_reps) * 100))
                QCoreApplication.processEvents()
                
            self.progressBar.setValue(100)
            QCoreApplication.processEvents()
            self.log("STATUS: COMPLETED ✓", "SUCCESS")
            self.log(f"Data successfully merged and exported to Filepinas folder: {filepinas_dir} ✓", "SUCCESS")
            self.progressBar.setValue(0)

        except Exception as e:
            self.log("STATUS: FAILED ✗", "ERROR")
            self.log(f"An unexpected error occurred during merge: {e}", "ERROR")
            self.progressBar.setValue(0)
        finally:
            self.check_buttons_state()
            self.progressBar.setValue(0)

    def run_export_excel(self):
        self.logsTextEdit.clear()
        self.log("STATUS: EXPORTING...", "INFO")
        base_dir = self.fileWidget.filePath().strip()
        nos = self.comboxNOS.currentText().strip()

        if not all([base_dir, nos]):
            self.log("STATUS: FAILED ✗", "ERROR")
            self.log("Please ensure Reference Directory and Type of Survey are selected.", "WARNING")
            self.progressBar.setValue(0)
            return

        filepinas_survey_dir = os.path.join(base_dir, 'Filepinas', nos)
        excel_dir = os.path.join(base_dir, 'Excel', nos)

        # Collect all merged GPKG files under the survey in Filepinas
        gpkg_files = []
        if os.path.isdir(filepinas_survey_dir):
            for root, dirs, files in os.walk(filepinas_survey_dir):
                for file in files:
                    if file.lower().endswith('.gpkg'):
                        gpkg_files.append(os.path.join(root, file))

        if not gpkg_files:
            val_survey_dir = os.path.join(base_dir, 'Validation Output', nos)
            val_has_files = os.path.isdir(val_survey_dir) and any(
                f.lower().endswith('.gpkg') for _, _, files in os.walk(val_survey_dir) for f in files
            )
            if val_has_files:
                self.log(
                    "Please merge all Sample SSU files across all cities/municipalities first before exporting to Excel.",
                    "WARNING"
                )
            else:
                self.log(f"No GeoPackage files found in: {filepinas_survey_dir}", "WARNING")
            self.progressBar.setValue(0)
            return

        gpkg_files.sort()
        os.makedirs(excel_dir, exist_ok=True)

        excel_name = "032_GEOMS_Excel_Upload.xlsx"
        excel_path = os.path.join(excel_dir, excel_name)

        # Pre-flight check: ensure excel output file is not locked
        if os.path.exists(excel_path):
            try:
                with open(excel_path, 'a'):
                    pass
            except IOError:
                self.log(f"The Excel file '{excel_name}' is currently open or locked by another program. Please close it and try again.", "ERROR")
                self.progressBar.setValue(0)
                return

            self.log(f"Target Excel file '{excel_name}' already exists. Overwriting...", "INFO")
            try:
                os.remove(excel_path)
            except Exception as e:
                self.log(f"Failed to delete existing file before overwriting: {excel_path} (Error: {e})", "ERROR")
                self.progressBar.setValue(0)
                return

        self.mergeBtn.setEnabled(False)
        self.exportBtn.setEnabled(False)
        self.progressBar.setValue(0)
        QCoreApplication.processEvents()

        try:
            total_files = len(gpkg_files)
            df_list = []
            processed_muns = set()

            for idx, gpkg_path in enumerate(gpkg_files):
                base_prog = int((idx / total_files) * 85)
                self.progressBar.setValue(base_prog + 5)
                QCoreApplication.processEvents()

                rel = os.path.relpath(gpkg_path, filepinas_survey_dir)
                parts = rel.split(os.sep)
                if len(parts) > 1:
                    processed_muns.add(parts[0])

                merged_layer = None
                sublayers = QgsProviderRegistry.instance().providerMetadata('ogr').querySublayers(gpkg_path)
                for sub in sublayers:
                    if sub.name().lower() not in ['layer_styles', 'sqlite_sequence']:
                        merged_layer = QgsVectorLayer(sub.uri(), sub.name(), "ogr")
                        break

                if merged_layer and merged_layer.isValid():
                    field_names = [field.name() for field in merged_layer.fields() if field.name().lower() not in ['layer', 'path']]
                    data = []
                    features = merged_layer.getFeatures()

                    for feat in features:
                        row = {}
                        for name in field_names:
                            val = feat[name]
                            if val is None or (hasattr(val, 'isNull') and val.isNull()) or type(val).__name__ == 'QPyNullVariant' or str(val) == 'NULL':
                                val = ""
                            elif 'ID' in name.upper():
                                val = str(val)
                            row[name] = val

                        geom = feat.geometry()
                        if geom and not geom.isNull():
                            row['WKT'] = geom.asWkt()
                        else:
                            row['WKT'] = ""
                        data.append(row)

                    if data:
                        df_temp = pd.DataFrame(data)
                        df_list.append(df_temp)

            self.progressBar.setValue(90)
            QCoreApplication.processEvents()

            if df_list:
                final_df = pd.concat(df_list, ignore_index=True)
                final_df = final_df.fillna("")

                # Remove fid column from exported Excel
                cols_to_drop = [c for c in ['fid', 'FID'] if c in final_df.columns]
                if cols_to_drop:
                    final_df = final_df.drop(columns=cols_to_drop)

                final_df.to_excel(excel_path, index=False)
                total_records = len(final_df)
            else:
                final_df = pd.DataFrame()
                final_df.to_excel(excel_path, index=False)
                total_records = 0

            self.progressBar.setValue(100)
            QCoreApplication.processEvents()

            mun_info = f" across {len(processed_muns)} municipality(ies)" if processed_muns else ""
            self.log("STATUS: COMPLETED ✓", "SUCCESS")
            self.log(
                f"Successfully exported {total_records} records from {total_files} merged file(s){mun_info} to province Excel file:\n  {excel_path} ✓",
                "SUCCESS"
            )
            self.progressBar.setValue(0)

        except Exception as e:
            self.log("STATUS: FAILED ✗", "ERROR")
            self.log(f"An unexpected error occurred during export: {e}", "ERROR")
            self.progressBar.setValue(0)
        finally:
            self.check_buttons_state()
            self.progressBar.setValue(0)

    def clear_logs(self):
        """Clears the execution logs and resets progress bar."""
        if hasattr(self, 'logsTextEdit') and self.logsTextEdit:
            self.logsTextEdit.clear()
        if hasattr(self, 'progressBar') and self.progressBar:
            self.progressBar.setValue(0)

    def reset_fields(self):
        """Resets all fields to their default state."""
        default_ref = r"C:\PSA-GIS\GeoFASU\Kalinga\Project files"
        self.fileWidget.setFilePath(default_ref)
        self.comboxNOS.blockSignals(True)
        self.comboxMun.blockSignals(True)
        self.comboxNOS.clear()
        self.comboxMun.clear()
        if os.path.isdir(default_ref):
            self.populate_nos_list()
        self.comboxNOS.setCurrentIndex(-1)
        self.comboxMun.setCurrentIndex(-1)
        self.comboxNOS.blockSignals(False)
        self.comboxMun.blockSignals(False)
        self.clear_logs()
        self.check_buttons_state()

    def closeEvent(self, event):
        """Clean close event, resets fields to default."""
        self.reset_fields()
        event.accept()

    def reject(self):
        """Clean reject event, resets fields to default."""
        self.reset_fields()
        super().reject()
