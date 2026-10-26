# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph
# GeoFASU_Ori - Checker Module

import os
import re
from pathlib import Path
from collections import Counter

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.PyQt.QtCore import Qt, QCoreApplication, QVariant, pyqtSignal
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsWkbTypes,
    QgsMarkerSymbol,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsSingleSymbolRenderer,
)

try:
    from .style import apply_modern_style, setup_dialog_logo
except (ImportError, ValueError):
    from style import apply_modern_style, setup_dialog_logo

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "checker_dialog.ui")
)


def is_null_or_empty(val):
    """Determines whether an attribute value is Null, empty, or a null-equivalent string."""
    if val is None:
        return True
    if hasattr(val, "isNull") and val.isNull():
        return True
    if type(val).__name__ == "QPyNullVariant":
        return True
    s = str(val).strip()
    return s == "" or s.upper() in ["NULL", "NONE", "NAN"]


def to_int_or_none(val):
    """Converts a value to int if possible (handles int, float strings like '6.0', '1', etc.)."""
    if is_null_or_empty(val):
        return None
    s = str(val).strip()
    try:
        f = float(s)
        if f.is_integer():
            return int(f)
    except (ValueError, TypeError):
        pass
    return None


def find_field_name(layer, target_name, alternatives=None):
    """
    Finds field in layer matching target_name or alternatives,
    case-insensitively and ignoring underscores/spaces.
    """
    if not layer or not hasattr(layer, "fields"):
        return None
    field_names = [f.name() for f in layer.fields()]
    if target_name in field_names:
        return target_name

    candidates = [target_name] + (alternatives or [])
    for cand in candidates:
        for f in field_names:
            if f.lower() == cand.lower():
                return f

    def normalize(s):
        return re.sub(r"[\s_]+", "", s).lower()

    for cand in candidates:
        norm_cand = normalize(cand)
        for f in field_names:
            if normalize(f) == norm_cand:
                return f

    return None


def apply_error_symbology(layer):
    """Applies a distinct red styling to the error temporary layer."""
    if not layer.isSpatial():
        return
    geom_type = layer.geometryType()
    if geom_type == QgsWkbTypes.PointGeometry:
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": "#EF4444",
                "color_border": "#7F1D1D",
                "size": "4.0",
                "outline_width": "0.8",
            }
        )
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    elif geom_type == QgsWkbTypes.PolygonGeometry:
        symbol = QgsFillSymbol.createSimple(
            {
                "color": "239,68,68,80",
                "color_border": "#DC2626",
                "outline_width": "0.8",
                "outline_style": "solid",
            }
        )
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    elif geom_type == QgsWkbTypes.LineGeometry:
        symbol = QgsLineSymbol.createSimple(
            {
                "color": "#DC2626",
                "width": "1.0",
            }
        )
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))


class CheckerDialog(QDialog, FORM_CLASS):
    quality_check_passed = pyqtSignal(str)
    quality_check_failed = pyqtSignal()

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setupUi(self)
        apply_modern_style(self)
        setup_dialog_logo(self)

        self.closeButton.setProperty("secondary", True)
        if hasattr(self, 'openFolderButton'):
            self.openFolderButton.setProperty("secondary", True)
            self.openFolderButton.clicked.connect(self.open_default_folder)
        self.progressBar.setValue(0)
        self.comboxSample.setPlaceholderText("-- Select Sample SSU Layer --")

        # Initial population of project layers
        self.populate_layers()

        # Keep dropdowns in sync if project layers change
        QgsProject.instance().layersAdded.connect(self.populate_layers)
        QgsProject.instance().layersRemoved.connect(self.populate_layers)

        # Signal connections
        self.runButton.clicked.connect(self.run_checker)
        self.closeButton.clicked.connect(self.close)
        self.comboxSample.currentIndexChanged.connect(self.on_sample_changed)

    def open_default_folder(self):
        """Opens the default project folder in Windows File Explorer."""
        default_dir = r"C:\PSA-GIS\GeoFASU\Kalinga\Project files"
        os.makedirs(default_dir, exist_ok=True)
        try:
            os.startfile(default_dir)
        except Exception:
            from qgis.PyQt.QtGui import QDesktopServices
            from qgis.PyQt.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(default_dir))

    def on_sample_changed(self):
        self.quality_check_failed.emit()

    def showEvent(self, event):
        """Refreshes layer list when dialog is shown."""
        self.populate_layers()
        super().showEvent(event)

    def populate_layers(self, reset_selection=False):
        """Populates Sample SSU dropdown from vector layers in QGIS."""
        self.comboxSample.blockSignals(True)

        prev_sample_id = None if reset_selection else self.comboxSample.currentData()
        self.comboxSample.clear()

        # Get all valid vector layers in project
        vector_layers = [
            lyr
            for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsVectorLayer) and lyr.isValid()
        ]

        if not vector_layers:
            self.comboxSample.setPlaceholderText("-- No Vector Layers in Project --")
            self.comboxSample.blockSignals(False)
            return

        self.comboxSample.setPlaceholderText("-- Select Sample SSU Layer --")

        sample_priority = -1
        sample_match_idx = -1

        for idx, lyr in enumerate(vector_layers):
            self.comboxSample.addItem(lyr.name(), lyr.id())

            lyr_name_lower = lyr.name().lower()

            # Auto-detection for Sample SSU:
            # Priority 3: Primary "Selected SSU" layer (excluding ref, additional, replacement)
            # Priority 2: Any "Selected SSU" layer (excluding ref)
            # Priority 1: Fallback to any layer with "sample" (excluding ref)
            if "ref" not in lyr_name_lower:
                if (
                    "selected ssu" in lyr_name_lower
                    and "additional" not in lyr_name_lower
                    and "replacement" not in lyr_name_lower
                ):
                    if sample_priority < 3:
                        sample_match_idx = idx
                        sample_priority = 3
                elif "selected ssu" in lyr_name_lower:
                    if sample_priority < 2:
                        sample_match_idx = idx
                        sample_priority = 2
                elif "sample" in lyr_name_lower:
                    if sample_priority < 1:
                        sample_match_idx = idx
                        sample_priority = 1

        if reset_selection:
            self.comboxSample.setCurrentIndex(-1)
        elif prev_sample_id:
            idx = self.comboxSample.findData(prev_sample_id)
            if idx != -1:
                self.comboxSample.setCurrentIndex(idx)
            elif sample_match_idx != -1:
                self.comboxSample.setCurrentIndex(sample_match_idx)
        elif sample_match_idx != -1:
            self.comboxSample.setCurrentIndex(sample_match_idx)

        self.comboxSample.blockSignals(False)

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

    def run_checker(self):
        """Executes validation on Sample SSU."""
        self.logsTextEdit.clear()
        self.log("STATUS: RUNNING...", "INFO")
        sample_layer_id = self.comboxSample.currentData()
        sample_layer = QgsProject.instance().mapLayer(sample_layer_id) if sample_layer_id else None

        if not sample_layer or not sample_layer.isValid():
            self.log("STATUS: FAILED ✗", "ERROR")
            self.log("Please select a valid Sample SSU layer from the dropdown list.", "WARNING")
            self.progressBar.setValue(0)
            return

        self.runButton.setEnabled(False)
        self.progressBar.setValue(5)
        QCoreApplication.processEvents()

        try:
            feature_count = sample_layer.featureCount()

            # Resolve column names in Sample SSU
            f_bsn = find_field_name(sample_layer, "BSN", ["bsn", "BS_No"])
            f_husn = find_field_name(sample_layer, "HUSN", ["husn", "HU_SN"])
            f_hsn = find_field_name(sample_layer, "HSN", ["hsn"])
            f_uc = find_field_name(
                sample_layer,
                "Update Codes",
                ["Update_Codes", "update codes", "update_code", "Update Code", "UC"],
            )
            f_nhhhead = find_field_name(
                sample_layer, "n_hhhead", ["n_hh_head", "nhhhead", "n_head", "new_hhhead"]
            )
            f_uc2ind = find_field_name(
                sample_layer, "UC_2_ind", ["uc_2_ind", "uc2ind", "UC_2_IND", "uc_2_indicator", "UC2_ind"]
            )
            f_nhsn = find_field_name(sample_layer, "n_hsn", ["nhsn", "new_hsn"])
            f_mucind = find_field_name(
                sample_layer, "m_uc_ind", ["mucind", "m_uc_indicator", "muc_ind", "UC_m_ind"]
            )
            f_naddress = find_field_name(
                sample_layer, "n_address", ["naddress", "new_address", "n_addr"]
            )
            f_uc6ind = find_field_name(
                sample_layer, "uc_6_ind", ["uc6ind", "uc_6_indicator", "UC_6_IND", "uc_6"]
            )
            f_muc = find_field_name(sample_layer, "m_uc", ["muc", "M_UC", "m_uc_code"])

            # Check if required core columns are present
            missing_core = []
            if not f_bsn:
                missing_core.append("BSN")
            if not f_husn:
                missing_core.append("HUSN")
            if not f_hsn:
                missing_core.append("HSN")
            if not f_uc:
                missing_core.append("Update Codes")

            if missing_core:
                self.log(
                    f"Sample SSU layer '{sample_layer.name()}' is missing required column(s): {', '.join(missing_core)}.",
                    "ERROR"
                )
                self.progressBar.setValue(0)
                return

            self.progressBar.setValue(15)
            QCoreApplication.processEvents()

            # Pass 1: Build frequency map for (BSN, HUSN, HSN) to detect duplicate entries
            bsn_husn_hsn_counts = Counter()
            for feat in sample_layer.getFeatures():
                bsn_val = feat[f_bsn]
                husn_val = feat[f_husn]
                hsn_val = feat[f_hsn]
                if (
                    not is_null_or_empty(bsn_val)
                    and not is_null_or_empty(husn_val)
                    and not is_null_or_empty(hsn_val)
                ):
                    key = (str(bsn_val).strip(), str(husn_val).strip(), str(hsn_val).strip())
                    bsn_husn_hsn_counts[key] += 1

            self.progressBar.setValue(30)
            QCoreApplication.processEvents()

            # Pass 2: Feature-level validation
            layer_errors = []
            processed_count = 0

            for feat in sample_layer.getFeatures():
                reasons = []

                # 1. BSN, HUSN, HSN must not be null
                if is_null_or_empty(feat[f_bsn]):
                    reasons.append("BSN is Null")
                if is_null_or_empty(feat[f_husn]):
                    reasons.append("HUSN is Null")
                if is_null_or_empty(feat[f_hsn]):
                    reasons.append("HSN is Null")

                # 2. Check for duplicate entries based on (BSN, HUSN, HSN)
                if (
                    not is_null_or_empty(feat[f_bsn])
                    and not is_null_or_empty(feat[f_husn])
                    and not is_null_or_empty(feat[f_hsn])
                ):
                    key = (str(feat[f_bsn]).strip(), str(feat[f_husn]).strip(), str(feat[f_hsn]).strip())
                    dup_count = bsn_husn_hsn_counts.get(key, 0)
                    if dup_count > 1:
                        reasons.append(
                            f"Duplicate entry: BSN={key[0]}, HUSN={key[1]}, HSN={key[2]} (appears {dup_count} times)"
                        )

                # 3. Update Codes validation & 11 criteria
                if is_null_or_empty(feat[f_uc]):
                    reasons.append("Update Codes is Null")
                else:
                    uc = to_int_or_none(feat[f_uc])
                    if uc is None:
                        reasons.append(f"Update Codes '{feat[f_uc]}' is invalid")
                    else:
                        uc2 = to_int_or_none(feat[f_uc2ind]) if f_uc2ind else None
                        mucind = to_int_or_none(feat[f_mucind]) if f_mucind else None
                        uc6 = to_int_or_none(feat[f_uc6ind]) if f_uc6ind else None
                        muc = to_int_or_none(feat[f_muc]) if f_muc else None

                        def check_field_not_null(field_id, col_display_name, context_desc):
                            if not field_id:
                                reasons.append(f"{context_desc}: column '{col_display_name}' not found")
                            elif is_null_or_empty(feat[field_id]):
                                reasons.append(f"{context_desc}: {col_display_name} is Null")

                        # 1. 1,3,5 - n_hhhead column not null
                        if uc in [1, 3, 5]:
                            check_field_not_null(f_nhhhead, "n_hhhead", f"Update Code {uc}")

                        # 2. 2 - UC_2_ind column not null
                        if uc == 2:
                            check_field_not_null(f_uc2ind, "UC_2_ind", "Update Code 2")

                        # 3. 2 and UC_2_ind column is equal to 1 or 3 - n_hhhead column not null
                        if uc == 2 and uc2 in [1, 3]:
                            check_field_not_null(f_nhhhead, "n_hhhead", f"Update Code 2 (UC_2_ind={uc2})")

                        # 4. 3,5 - n_hsn column not null
                        if uc in [3, 5]:
                            check_field_not_null(f_nhsn, "n_hsn", f"Update Code {uc}")

                        # 5. 1,5 - m_uc_ind column not null
                        if uc in [1, 5]:
                            check_field_not_null(f_mucind, "m_uc_ind", f"Update Code {uc}")

                        # 6. 1,5 and m_uc_ind column is equal to 2 - n_address column not null
                        if uc in [1, 5] and mucind == 2:
                            check_field_not_null(f_naddress, "n_address", f"Update Code {uc} (m_uc_ind=2)")

                        # 7. 2 and UC_2_ind column = 2 or 3 - n_address column not null
                        if uc == 2 and uc2 in [2, 3]:
                            check_field_not_null(f_naddress, "n_address", f"Update Code 2 (UC_2_ind={uc2})")

                        # 8. 6 - uc_6_ind column not null
                        if uc == 6:
                            check_field_not_null(f_uc6ind, "uc_6_ind", "Update Code 6")

                        # 9. 6 and uc_6_ind column = 1 - n_hhhead column not null
                        if uc == 6 and uc6 == 1:
                            check_field_not_null(f_nhhhead, "n_hhhead", "Update Code 6 (uc_6_ind=1)")

                        # 10. 2 and UC_2_ind column = 2 - m_uc column not null
                        if uc == 2 and uc2 == 2:
                            check_field_not_null(f_muc, "m_uc", "Update Code 2 (UC_2_ind=2)")

                        # 11. 2 and UC_2_ind column = 2 and m_uc = 2 - n_hhhead column not null
                        if uc == 2 and uc2 == 2 and muc == 2:
                            check_field_not_null(f_nhhhead, "n_hhhead", "Update Code 2 (UC_2_ind=2, m_uc=2)")

                if reasons:
                    layer_errors.append((feat, "; ".join(reasons)))

                processed_count += 1
                if feature_count > 0 and processed_count % max(1, (feature_count // 20)) == 0:
                    prog = 30 + int((processed_count / feature_count) * 60)
                    self.progressBar.setValue(min(prog, 90))
                    QCoreApplication.processEvents()

            err_count = len(layer_errors)
            created_temp_layer = None

            if err_count > 0:
                # Create temporary memory layer for errors
                temp_name = f"Errors_{sample_layer.name()}"
                crs_auth = sample_layer.crs().authid()
                if sample_layer.isSpatial():
                    wkb_type_str = QgsWkbTypes.displayString(sample_layer.wkbType())
                    uri = f"{wkb_type_str}?crs={crs_auth}"
                else:
                    uri = "none"

                temp_layer = QgsVectorLayer(uri, temp_name, "memory")
                t_pr = temp_layer.dataProvider()

                # Copy original fields and add Validation_Errors field
                t_pr.addAttributes(sample_layer.fields())
                try:
                    from qgis.PyQt.QtCore import QMetaType
                    err_field = QgsField("Validation_Errors", QMetaType.Type.QString)
                except Exception:
                    err_field = QgsField("Validation_Errors", QVariant.String)

                t_pr.addAttributes([err_field])
                temp_layer.updateFields()

                new_features = []
                for e_feat, e_reason in layer_errors:
                    nf = QgsFeature(temp_layer.fields())
                    if sample_layer.isSpatial() and e_feat.hasGeometry():
                        nf.setGeometry(e_feat.geometry())
                    attrs = e_feat.attributes()
                    attrs.append(e_reason)
                    nf.setAttributes(attrs)
                    new_features.append(nf)

                t_pr.addFeatures(new_features)
                temp_layer.updateExtents()

                # Apply prominent red symbology
                apply_error_symbology(temp_layer)

                # Add to QGIS Project
                QgsProject.instance().addMapLayer(temp_layer)
                created_temp_layer = temp_layer

            self.progressBar.setValue(100)
            QCoreApplication.processEvents()

            # Set active layer and zoom canvas if errors exist
            if created_temp_layer and hasattr(self, "iface") and self.iface:
                self.iface.setActiveLayer(created_temp_layer)
                if (
                    created_temp_layer.isSpatial()
                    and created_temp_layer.featureCount() > 0
                    and self.iface.mapCanvas()
                ):
                    self.iface.mapCanvas().setExtent(created_temp_layer.extent())
                    self.iface.mapCanvas().refresh()

            if err_count == 0:
                self.log("STATUS: PASSED ✓", "SUCCESS")
                self.log(
                    f"Checker completed successfully! All {feature_count} records in '{sample_layer.name()}' passed validation. ✓",
                    "SUCCESS"
                )
                self.progressBar.setValue(0)
                self.quality_check_passed.emit(sample_layer.id())
            else:
                self.log(f"STATUS: FAILED ✗ ({err_count} errors found)", "ERROR")
                self.log(
                    f"Validation Errors Found: Found {err_count} error feature(s) out of {feature_count} in '{sample_layer.name()}'.",
                    "WARNING"
                )
                self.log(
                    f"A new temporary layer '{created_temp_layer.name()}' has been created in QGIS with the error records.",
                    "INFO"
                )
                self.progressBar.setValue(0)
                self.quality_check_failed.emit()

        except Exception as e:
            self.log("STATUS: FAILED ✗", "ERROR")
            self.log(f"An error occurred during checking: {e}", "ERROR")
            self.quality_check_failed.emit()
            self.progressBar.setValue(0)
        finally:
            self.runButton.setEnabled(True)
            self.progressBar.setValue(0)

    def clear_logs(self):
        """Clears the execution logs and resets progress bar."""
        if hasattr(self, 'logsTextEdit') and self.logsTextEdit:
            self.logsTextEdit.clear()
        if hasattr(self, 'progressBar') and self.progressBar:
            self.progressBar.setValue(0)

    def reset_fields(self):
        """Resets the input fields and progress bar to default values."""
        self.progressBar.setValue(0)
        self.runButton.setEnabled(True)
        self.populate_layers(reset_selection=True)
        self.clear_logs()
        self.quality_check_failed.emit()

    def closeEvent(self, event):
        """Clean close event, resets fields to default."""
        self.reset_fields()
        event.accept()

    def reject(self):
        """Clean reject event, resets fields to default."""
        self.reset_fields()
        super().reject()
