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

from .style import apply_modern_style, setup_dialog_logo

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
        self.runButton.clicked.connect(self.run_process)
        
        self.comboxNOS.setPlaceholderText("-- Select Type of Survey --")
        self.comboxMun.setPlaceholderText("-- Select City/Municipality --")

        # Signals for dropdowns
        self.fileWidget.fileChanged.connect(self.populate_nos_list)
        self.comboxNOS.currentIndexChanged.connect(self.update_mun_list)

    def populate_nos_list(self):
        self.comboxNOS.blockSignals(True)
        self.comboxMun.blockSignals(True)

        self.comboxNOS.clear()
        self.comboxMun.clear()
        self.progressBar.setValue(0)

        base_path = os.path.join(self.fileWidget.filePath(), 'Validation Output')
        if os.path.isdir(base_path):
            dir_list = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]
            self.comboxNOS.addItems(dir_list)
            self.comboxNOS.setCurrentIndex(-1)

        self.comboxNOS.blockSignals(False)
        self.comboxMun.blockSignals(False)

    def update_mun_list(self):
        self.comboxMun.blockSignals(True)
        self.comboxMun.clear()
        nos = self.comboxNOS.currentText().strip()
        if nos:
            base_path = os.path.join(self.fileWidget.filePath(), 'Validation Output', nos)
            if os.path.isdir(base_path):
                dirs = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]
                self.comboxMun.addItems(dirs)
                self.comboxMun.setCurrentIndex(-1)

        self.comboxMun.blockSignals(False)

    def run_process(self):
        base_dir = self.fileWidget.filePath().strip()
        nos = self.comboxNOS.currentText().strip()
        mun = self.comboxMun.currentText().strip()

        if not all([base_dir, nos, mun]):
            QMessageBox.warning(
                self,
                "Missing Input",
                "Please ensure all fields are selected (Directory, Survey, and Municipality).",
            )
            return

        mun_dir = os.path.join(base_dir, 'Validation Output', nos, mun)
        if not os.path.isdir(mun_dir):
            QMessageBox.warning(self, "Directory Not Found", f"The directory does not exist:\n{mun_dir}")
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
            QMessageBox.warning(self, "No GeoPackage Found", f"No matching .gpkg files (with Replicate Number in filename/path) were found in:\n{mun_dir}")
            return

        filepinas_dir = os.path.join(base_dir, 'Filepinas', nos, mun)
        excel_dir = os.path.join(base_dir, 'Excel', nos, mun)
        os.makedirs(filepinas_dir, exist_ok=True)
        os.makedirs(excel_dir, exist_ok=True)
        
        # Pre-flight check: ensure output files are not locked, and ask for overwrite if any exist
        existing_files = []
        locked_files = []
        
        for rep_no in rep_gpkgs.keys():
            merged_gpkg_name = f"{nos}_{mun}_Selected SSU_{rep_no}.gpkg"
            merged_gpkg_path = os.path.join(filepinas_dir, merged_gpkg_name)
            excel_name = f"{nos}_{mun}_Selected SSU_{rep_no}.xlsx"
            excel_path = os.path.join(excel_dir, excel_name)
            
            for path in [merged_gpkg_path, excel_path]:
                if os.path.exists(path):
                    existing_files.append(path)
                    try:
                        with open(path, 'a'):
                            pass
                    except IOError:
                        locked_files.append(path)
                        
        if locked_files:
            locked_msg = "\n".join([os.path.basename(f) for f in locked_files])
            QMessageBox.critical(self, "Files In Use", f"The following files are currently open or locked by another program (like Excel or QGIS).\n\nPlease close them and try again:\n\n{locked_msg}")
            return
            
        if existing_files:
            reply = QMessageBox.question(self, "Overwrite Files?", "Some output files already exist. Do you want to overwrite them?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return
            for f in existing_files:
                try:
                    os.remove(f)
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to delete existing file before overwriting:\n{f}\nError: {e}")
                    return

        self.runButton.setEnabled(False)
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
                
                self.progressBar.setValue(base_prog + int(40 / total_reps))
                QCoreApplication.processEvents()

                # Delete 'layer' and 'path' columns and save to final GPKG
                params_del = {
                    'INPUT': temp_merged,
                    'COLUMN': ['layer', 'path'],
                    'OUTPUT': merged_gpkg_path
                }
                processing.run("native:deletecolumn", params_del)
                
                self.progressBar.setValue(base_prog + int(65 / total_reps))
                QCoreApplication.processEvents()
                
                # Convert the merged layer to excel
                excel_name = f"{nos}_{mun}_Selected SSU_{rep_no}.xlsx"
                excel_path = os.path.join(excel_dir, excel_name)
                
                merged_layer = None
                sublayers = QgsProviderRegistry.instance().providerMetadata('ogr').querySublayers(merged_gpkg_path)
                for sub in sublayers:
                    if sub.name().lower() not in ['layer_styles', 'sqlite_sequence']:
                        merged_layer = QgsVectorLayer(sub.uri(), sub.name(), "ogr")
                        break
                
                if merged_layer and merged_layer.isValid():
                    field_names = [field.name() for field in merged_layer.fields()]
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
                    
                    df = pd.DataFrame(data)
                    df = df.fillna("")
                    df.to_excel(excel_path, index=False)
                
                current_rep += 1
                self.progressBar.setValue(int((current_rep / total_reps) * 100))
                QCoreApplication.processEvents()
                
            self.progressBar.setValue(100)
            QCoreApplication.processEvents()
            QMessageBox.information(self, "Success", "Data successfully merged and exported to Filepinas and Excel folders.")
            self.comboxMun.setCurrentIndex(-1)
            self.progressBar.setValue(0)

        except Exception as e:
            QMessageBox.critical(self, "An Unexpected Error Occurred", f"Error: {e}")
        finally:
            self.runButton.setEnabled(True)

    def reset_fields(self):
        self.fileWidget.setFilePath("")
        self.comboxNOS.clear()
        self.comboxMun.clear()
        self.progressBar.setValue(0)

    def closeEvent(self, event):
        self.reset_fields()
        event.accept()
