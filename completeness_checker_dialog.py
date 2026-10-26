# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph
# GeoFASU_Ori - Completeness Checker Module

import os
import re
from datetime import datetime
from pathlib import Path

from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.PyQt.QtCore import Qt, QCoreApplication, QVariant
from qgis.gui import QgsFileWidget
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsVectorFileWriter,
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
    os.path.join(os.path.dirname(__file__), "completeness_checker_dialog.ui")
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
    """Converts a value to int if possible (handles int, float strings like '6.0')."""
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


def is_selected_ssu_1(val):
    """
    Checks if a Selected_SSU value represents 1
    (handles int 1, float 1.0, string '1', '1 - Sample SSU', etc.).
    """
    if is_null_or_empty(val):
        return False
    v_int = to_int_or_none(val)
    if v_int == 1:
        return True
    s = str(val).strip()
    if s == "1":
        return True
    if s.startswith("1") and len(s) > 1 and not s[1].isdigit():
        return True
    return False


def apply_error_symbology(layer):
    """Applies a distinct red styling to the error temporary layer."""
    if not layer or not layer.isSpatial():
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


class CompletenessCheckerDialog(QDialog, FORM_CLASS):
    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setupUi(self)
        apply_modern_style(self)

        self.progressBar.setValue(0)
        self.updateButton.setEnabled(False)
        self.current_status = "READY"
        self.statusLabel = None
        self.set_status("READY", log_message=False)

        # Gatekeeping: Run Checker is only enabled once Quality Checker passes
        self.quality_check_passed = False
        self.passed_layer_id = None
        self.runButton.setEnabled(False)
        self.runButton.setToolTip("Please run Quality Checker first. Completeness Check is enabled once Quality Checker passes.")

        # Default Output Directory
        default_dir = r"C:\PSA-GIS\GeoFASU\Kalinga\Project files"
        if hasattr(self, "outputDirWidget"):
            self.outputDirWidget.setStorageMode(QgsFileWidget.GetDirectory)
            self.outputDirWidget.setFilePath(default_dir)

        # Initial layer population
        self.populate_layers()

        # Connect project layer events
        QgsProject.instance().layersAdded.connect(self.populate_layers)
        QgsProject.instance().layersRemoved.connect(self.populate_layers)

        # UI Signals
        self.runButton.clicked.connect(self.run_checker)
        self.updateButton.clicked.connect(self.update_ssu_list)
        self.comboxSample.currentIndexChanged.connect(self.on_layer_selection_changed)
        self.comboxRef.currentIndexChanged.connect(self.on_layer_selection_changed)

    def set_quality_check_state(self, passed: bool, layer_id: str = None):
        """Updates the gatekeeper state linked to Quality Checker."""
        self.quality_check_passed = passed
        self.passed_layer_id = layer_id if passed else None

        if passed:
            if layer_id:
                # If layer exists in Sample dropdown, select it
                idx = self.comboxSample.findData(layer_id)
                if idx != -1 and self.comboxSample.currentIndex() != idx:
                    self.comboxSample.setCurrentIndex(idx)
            is_match = (
                self.passed_layer_id is None
                or self.comboxSample.currentData() == self.passed_layer_id
            )
            self.runButton.setEnabled(is_match)
            if is_match:
                self.runButton.setToolTip("Quality Check PASSED. Click to run Completeness Check.")
                lyr = QgsProject.instance().mapLayer(layer_id) if layer_id else None
                lyr_name = lyr.name() if lyr else "Selected Layer"
                self.log(
                    f"Quality Checker PASSED for '{lyr_name}'. Completeness Check is now unlocked. ✓",
                    "SUCCESS",
                )
            else:
                self.runButton.setToolTip("Selected Sample Layer has not passed Quality Checker yet.")
        else:
            self.runButton.setEnabled(False)
            self.runButton.setToolTip(
                "Please run Quality Checker first. Completeness Check is enabled once Quality Checker passes."
            )

    def showEvent(self, event):
        self.populate_layers()
        super().showEvent(event)

    def set_status(self, status: str, log_message: bool = True):
        """Updates internal status and logs it into the execution logs console."""
        self.current_status = status
        if log_message:
            if status == "PASSED":
                self.log("STATUS: PASSED ✓", "SUCCESS")
            elif status == "FAILED":
                self.log("STATUS: FAILED ✗", "ERROR")
            elif status == "RUNNING":
                self.log("STATUS: RUNNING...", "INFO")
            elif status == "READY":
                self.log("STATUS: READY", "INFO")

    def log(self, message: str, level: str = "INFO"):
        """Appends a line of text to the logs widget with level indicator."""
        prefix = {
            "INFO": "",
            "SUCCESS": "✓ ",
            "WARNING": "⚠ ",
            "ERROR": "✗ ",
        }.get(level.upper(), "")
        self.logsTextEdit.appendPlainText(f"{prefix}{message}")
        self.logsTextEdit.verticalScrollBar().setValue(
            self.logsTextEdit.verticalScrollBar().maximum()
        )

    def populate_layers(self, reset_selection=False):
        """Populates Sample SSU and Reference SSU dropdowns from vector layers in QGIS."""
        self.comboxSample.blockSignals(True)
        self.comboxRef.blockSignals(True)

        prev_sample_id = None if reset_selection else self.comboxSample.currentData()
        prev_ref_id = None if reset_selection else self.comboxRef.currentData()

        self.comboxSample.clear()
        self.comboxRef.clear()

        vector_layers = [
            lyr
            for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsVectorLayer) and lyr.isValid()
        ]

        if not vector_layers:
            self.comboxSample.setPlaceholderText("-- No Vector Layers in Project --")
            self.comboxRef.setPlaceholderText("-- No Vector Layers in Project --")
            self.comboxSample.blockSignals(False)
            self.comboxRef.blockSignals(False)
            return

        self.comboxSample.setPlaceholderText("-- Select Sample SSU Layer --")
        self.comboxRef.setPlaceholderText("-- Select Reference SSU Layer --")

        sample_priority = -1
        sample_match_idx = -1
        ref_match_idx = -1

        for idx, lyr in enumerate(vector_layers):
            self.comboxSample.addItem(lyr.name(), lyr.id())
            self.comboxRef.addItem(lyr.name(), lyr.id())

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

            # Auto-detection for Reference SSU
            if ref_match_idx == -1:
                if "ref" in lyr_name_lower:
                    ref_match_idx = idx

        if reset_selection:
            self.comboxSample.setCurrentIndex(-1)
            self.comboxRef.setCurrentIndex(-1)
        else:
            # Restore previous selection or use auto-detected
            if prev_sample_id:
                idx = self.comboxSample.findData(prev_sample_id)
                if idx != -1:
                    self.comboxSample.setCurrentIndex(idx)
                elif sample_match_idx != -1:
                    self.comboxSample.setCurrentIndex(sample_match_idx)
            elif sample_match_idx != -1:
                self.comboxSample.setCurrentIndex(sample_match_idx)

            if prev_ref_id:
                idx = self.comboxRef.findData(prev_ref_id)
                if idx != -1:
                    self.comboxRef.setCurrentIndex(idx)
                elif ref_match_idx != -1:
                    self.comboxRef.setCurrentIndex(ref_match_idx)
            elif ref_match_idx != -1:
                self.comboxRef.setCurrentIndex(ref_match_idx)

        self.comboxSample.blockSignals(False)
        self.comboxRef.blockSignals(False)
        self.on_layer_selection_changed()

    def on_layer_selection_changed(self):
        """Automatically filters Reference Layer when dropdown selections change."""
        self.set_status("READY")
        is_passed = self.quality_check_passed and (
            self.passed_layer_id is None
            or self.comboxSample.currentData() == self.passed_layer_id
        )
        self.runButton.setEnabled(is_passed)
        if not self.quality_check_passed:
            self.runButton.setToolTip(
                "Please run Quality Checker first. Completeness Check is enabled once Quality Checker passes."
            )
        elif not is_passed:
            self.runButton.setToolTip("Selected Sample Layer has not passed Quality Checker yet.")
        else:
            self.runButton.setToolTip("Quality Check PASSED. Click to run Completeness Check.")

        self.updateButton.setEnabled(False)
        sample_id = self.comboxSample.currentData()
        ref_id = self.comboxRef.currentData()
        if sample_id and ref_id:
            sample_layer = QgsProject.instance().mapLayer(sample_id)
            ref_layer = QgsProject.instance().mapLayer(ref_id)
            if sample_layer and ref_layer and sample_layer.id() != ref_layer.id():
                self.filter_reference_layer(sample_layer, ref_layer, log_to_widget=False)

    def filter_reference_layer(self, sample_layer, ref_layer, log_to_widget=True):
        """
        Filters Selected SSU Ref based on the Selected SSU Replicate Number Layer
        (replicate number and PSU if applicable) to match the data.
        """
        if not sample_layer or not sample_layer.isValid() or not ref_layer or not ref_layer.isValid():
            return None

        # 1. Determine Replicate Number from sample_layer
        reps = set()
        f_rep = find_field_name(
            sample_layer,
            "Replicate_Number",
            ["Replicate", "Rep_No", "rep_no", "REP", "rep", "Replicate Number", "replicate_number"],
        )
        if f_rep:
            for feat in sample_layer.getFeatures():
                v = feat[f_rep]
                if not is_null_or_empty(v):
                    reps.add(str(v).strip())

        # Fallback to layer name if not found from features
        if not reps:
            m_rep = re.search(r"Selected\s*SSU[_\s]+(R\d+|\d+)", sample_layer.name(), re.IGNORECASE)
            if m_rep:
                reps.add(m_rep.group(1).strip())

        # Fallback to source path
        if not reps:
            m_src = re.search(r"[/\\](R\d+)[/\\]", sample_layer.source(), re.IGNORECASE)
            if m_src:
                reps.add(m_src.group(1).strip())

        # Build target values for replicate (e.g., '16', 'R16')
        target_rep_values = set()
        for r in reps:
            target_rep_values.add(r)
            digits = re.sub(r"\D", "", r)
            if digits:
                target_rep_values.add(digits)
                target_rep_values.add(f"R{digits}")

        # 2. Determine PSU Name(s) from sample_layer (if specific PSU)
        psus = set()
        f_psu = find_field_name(
            sample_layer,
            "PSU_Name",
            ["psu_name", "PSU", "psu", "PSU Name", "PSU_name"],
        )
        if f_psu:
            for feat in sample_layer.getFeatures():
                v = feat[f_psu]
                if not is_null_or_empty(v):
                    psus.add(str(v).strip())

        # Check if PSU name is in the layer name e.g. ..._Selected SSU_R16_Bulanao...
        if not psus:
            m_psu = re.search(r"Selected\s*SSU[_\s]+(?:R\d+|\d+)[_\s]+(.+)$", sample_layer.name(), re.IGNORECASE)
            if m_psu:
                psus.add(m_psu.group(1).strip())

        # 3. Resolve fields in ref_layer
        r_rep = find_field_name(
            ref_layer,
            "Replicate_Number",
            ["Replicate", "Rep_No", "rep_no", "REP", "rep", "Replicate Number", "replicate_number"],
        )
        r_psu = find_field_name(
            ref_layer,
            "PSU_Name",
            ["psu_name", "PSU", "psu", "PSU Name", "PSU_name"],
        )

        filter_clauses = []
        if r_rep and target_rep_values:
            rep_escaped = ["'" + v.replace("'", "''") + "'" for v in sorted(target_rep_values)]
            filter_clauses.append(f'"{r_rep}" IN ({",".join(rep_escaped)})')

        if r_psu and psus:
            psu_escaped = ["'" + p.replace("'", "''") + "'" for p in sorted(psus)]
            filter_clauses.append(f'"{r_psu}" IN ({",".join(psu_escaped)})')

        if filter_clauses:
            full_filter = " AND ".join(filter_clauses)
            ref_layer.setSubsetString(full_filter)
            ref_layer.updateExtents()
            if self.iface and hasattr(self.iface, "mapCanvas") and self.iface.mapCanvas():
                self.iface.mapCanvas().refresh()
            if log_to_widget:
                rep_info = f"Replicate: {', '.join(sorted(reps))}" if reps else ""
                psu_info = f", PSU: {', '.join(sorted(psus))}" if psus else ""
                self.log(f"• Filtered Reference Layer '{ref_layer.name()}' ({rep_info}{psu_info})")
                self.log(f"  └─ Filter expression: {full_filter}")
                self.log(f"  └─ Filtered features in Reference: {ref_layer.featureCount()}")
            return full_filter
        else:
            return None

    def run_checker(self):
        """Executes completeness validation between Sample SSU and Reference SSU."""
        if not self.quality_check_passed:
            self.log("Quality Checker must PASS before Completeness Check can be run.", "WARNING")
            self.runButton.setEnabled(False)
            self.runButton.setToolTip(
                "Please run Quality Checker first. Completeness Check is enabled once Quality Checker passes."
            )
            return

        self.logsTextEdit.clear()
        self.progressBar.setValue(0)
        self.updateButton.setEnabled(False)
        self.set_status("RUNNING")

        sample_id = self.comboxSample.currentData()
        ref_id = self.comboxRef.currentData()

        sample_layer = QgsProject.instance().mapLayer(sample_id) if sample_id else None
        ref_layer = QgsProject.instance().mapLayer(ref_id) if ref_id else None

        if not sample_layer or not sample_layer.isValid():
            self.log("Please select a valid Sample SSU layer.", "WARNING")
            self.progressBar.setValue(0)
            return

        if not ref_layer or not ref_layer.isValid():
            self.log("Please select a valid Reference SSU layer.", "WARNING")
            self.progressBar.setValue(0)
            return

        if sample_layer.id() == ref_layer.id():
            self.log("Sample SSU and Reference SSU must be different layers.", "WARNING")
            self.progressBar.setValue(0)
            return

        self.runButton.setEnabled(False)
        self.progressBar.setValue(10)
        QCoreApplication.processEvents()

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log(f"[{now_str}] Starting Completeness Check...")
        self.log(f"• Sample SSU Layer: '{sample_layer.name()}'")
        self.log(f"• Reference SSU Layer: '{ref_layer.name()}'")
        out_dir = (
            self.outputDirWidget.filePath().strip()
            if hasattr(self, "outputDirWidget")
            else ""
        )
        if out_dir:
            self.log(f"• Output Folder: '{out_dir}'")
        self.log("-" * 55)

        try:
            # 0. Filter Reference SSU layer based on Sample SSU layer to match the data
            self.filter_reference_layer(sample_layer, ref_layer, log_to_widget=True)
            self.log("-" * 55)

            # 1. Resolve Sample SSU fields
            f_uc = find_field_name(
                sample_layer,
                "Update Codes",
                ["Update_Codes", "update codes", "update_code", "Update Code", "UC"],
            )
            f_uc6 = find_field_name(
                sample_layer,
                "uc_6_ind",
                ["uc6ind", "uc_6_indicator", "UC_6_IND", "uc_6"],
            )

            if not f_uc:
                self.log("ERROR: 'Update Codes' column not found in Sample SSU layer.", "ERROR")
                self.set_status("FAILED")
                self.progressBar.setValue(0)
                return

            if not f_uc6:
                self.log("WARNING: 'uc_6_ind' column not found in Sample SSU layer.", "WARNING")

            # 2. Resolve Reference SSU fields
            f_sel = find_field_name(
                ref_layer,
                "Selected_SSU",
                ["Selected SSU", "selected_ssu", "selected ssu", "SelectedSSU"],
            )

            if not f_sel:
                self.log("ERROR: 'Selected_SSU' column not found in Reference SSU layer.", "ERROR")
                self.set_status("FAILED")
                self.progressBar.setValue(0)
                return

            # 3. Count Sample SSU
            self.progressBar.setValue(25)
            QCoreApplication.processEvents()

            sample_valid_count = 0
            code_counts = {c: 0 for c in range(7)}
            code_6_skipped = 0

            for feat in sample_layer.getFeatures():
                raw_uc = feat[f_uc]
                uc_int = to_int_or_none(raw_uc)
                if uc_int is not None and 0 <= uc_int <= 6:
                    if uc_int == 6:
                        # uc_6_ind must equal 1
                        raw_uc6 = feat[f_uc6] if f_uc6 else None
                        uc6_int = to_int_or_none(raw_uc6)
                        if uc6_int == 1:
                            sample_valid_count += 1
                            code_counts[6] += 1
                        else:
                            code_6_skipped += 1
                    else:
                        sample_valid_count += 1
                        code_counts[uc_int] += 1

            self.progressBar.setValue(60)
            QCoreApplication.processEvents()

            # 4. Count Reference SSU
            ref_selected_count = 0
            for feat in ref_layer.getFeatures():
                raw_sel = feat[f_sel]
                sel_int = to_int_or_none(raw_sel)
                if sel_int == 1:
                    ref_selected_count += 1

            self.progressBar.setValue(85)
            QCoreApplication.processEvents()

            # Log counting details
            self.log(f"Sample SSU Total Valid Count: {sample_valid_count}")
            self.log(
                f"  └─ Breakdown: Code 0={code_counts[0]}, 1={code_counts[1]}, "
                f"2={code_counts[2]}, 3={code_counts[3]}, 4={code_counts[4]}, "
                f"5={code_counts[5]}, 6={code_counts[6]}"
            )
            if code_6_skipped > 0:
                self.log(f"  └─ Note: {code_6_skipped} record(s) with Update Code 6 had uc_6_ind != 1 (excluded).")

            self.log(f"Reference SSU Total Count (Selected_SSU = 1): {ref_selected_count}")
            self.log("-" * 55)

            # 5. Comparison
            self.progressBar.setValue(100)
            QCoreApplication.processEvents()

            if sample_valid_count == ref_selected_count:
                self.set_status("PASSED")
                self.runButton.setEnabled(False)
                self.updateButton.setEnabled(True)
                self.log(f"Check PASSED! Sample SSU Count: {sample_valid_count} | Reference SSU Count: {ref_selected_count}", "SUCCESS")
                self.log("Sample SSU count matches Reference SSU count perfectly.", "INFO")
                self.log("The 'Update SSU List' button is now enabled. You can now click 'Update SSU List' to merge missing reference records if needed.", "INFO")
                self.progressBar.setValue(0)
            else:
                self.set_status("FAILED")
                self.runButton.setEnabled(True)
                self.updateButton.setEnabled(False)
                diff = sample_valid_count - ref_selected_count
                diff_desc = f"{abs(diff)} more in Sample" if diff > 0 else f"{abs(diff)} more in Reference"
                self.log(f"Check FAILED! Sample SSU Count: {sample_valid_count} | Reference SSU Count: {ref_selected_count} | Difference: {abs(diff)} ({diff_desc}).", "ERROR")
                self.log("Counts must be equal to enable updating the SSU list. Please review your surveyed records and reference layer.", "WARNING")
                self.progressBar.setValue(0)

        except Exception as e:
            self.log(f"An unexpected error occurred during check: {e}", "ERROR")
            self.set_status("FAILED")
            self.runButton.setEnabled(True)
            self.progressBar.setValue(0)
        finally:
            if self.current_status != "PASSED":
                is_passed = self.quality_check_passed and (
                    self.passed_layer_id is None
                    or self.comboxSample.currentData() == self.passed_layer_id
                )
                self.runButton.setEnabled(is_passed)
                if not self.quality_check_passed:
                    self.runButton.setToolTip(
                        "Please run Quality Checker first. Completeness Check is enabled once Quality Checker passes."
                    )
                elif not is_passed:
                    self.runButton.setToolTip(
                        "Selected Sample Layer has not passed Quality Checker yet."
                    )
                else:
                    self.runButton.setToolTip(
                        "Quality Check PASSED. Click to run Completeness Check."
                    )
            else:
                self.runButton.setEnabled(False)
            self.progressBar.setValue(0)

    def resolve_survey_and_mun(self, sample_layer, ref_layer=None, base_out_dir=None):
        """
        Resolves the Name of Survey and City/Mun Name from:
        1. Layer source paths of Sample SSU and Reference SSU
        2. Feature attributes (Mun_name, Round, Year, Survey)
        3. Layer names (f"{nos}_{mun}_Selected SSU_{rep}")
        4. Existing directories in base_out_dir
        """
        nos = None
        mun = None

        # 1. Check feature attributes for Municipality
        f_mun = find_field_name(
            sample_layer,
            "Mun_name",
            ["mun_name", "MUN_NAME", "City_Mun", "Municipality", "MUN", "mun"],
        )
        if f_mun:
            for feat in sample_layer.getFeatures():
                v = feat[f_mun]
                if not is_null_or_empty(v):
                    mun = str(v).strip()
                    break

        if not mun and ref_layer:
            f_ref_mun = find_field_name(
                ref_layer,
                "Mun_name",
                ["mun_name", "MUN_NAME", "City_Mun", "Municipality", "MUN", "mun"],
            )
            if f_ref_mun:
                for feat in ref_layer.getFeatures():
                    v = feat[f_ref_mun]
                    if not is_null_or_empty(v):
                        mun = str(v).strip()
                        break

        # 2. Check source paths of sample_layer and ref_layer
        sources = []
        if sample_layer:
            sources.append(sample_layer.source().split("|")[0])
        if ref_layer:
            sources.append(ref_layer.source().split("|")[0])

        markers = [
            "Projects",
            "Validation Output",
            "Validation Ouput",
            "From Tablet",
            "Samples",
            "Excel",
            "Filepinas",
        ]
        for src in sources:
            if not src:
                continue
            norm_src = os.path.normpath(src)
            parts = [p for p in norm_src.split(os.sep) if p]
            for marker in markers:
                if marker in parts:
                    idx = parts.index(marker)
                    if not nos and idx + 1 < len(parts):
                        cand_nos = parts[idx + 1]
                        if not cand_nos.lower().endswith(".gpkg"):
                            nos = cand_nos
                    if not mun and idx + 2 < len(parts):
                        cand_mun = parts[idx + 2]
                        if not cand_mun.lower().endswith(".gpkg"):
                            mun = cand_mun
                    break
            if nos and mun:
                break

        # 3. Check layer name parsing: {nos}_{mun}_Selected SSU_{rep}
        names_to_check = []
        if sample_layer:
            names_to_check.append(sample_layer.name())
        if ref_layer:
            names_to_check.append(ref_layer.name())

        for lyr_name in names_to_check:
            m_ssu = re.search(
                r"^(.*?)_(?:Selected SSU|Selected_SSU|SelectedSSU)",
                lyr_name,
                re.IGNORECASE,
            )
            if m_ssu:
                prefix = m_ssu.group(1).strip()
                if mun and prefix.lower().endswith(mun.lower()):
                    cand_nos = prefix[: -len(mun)].rstrip(" _-")
                    if cand_nos and not nos:
                        nos = cand_nos
                elif not nos and not mun:
                    if "_" in prefix:
                        p_parts = prefix.rsplit("_", 1)
                        if not nos:
                            nos = p_parts[0]
                        if not mun:
                            mun = p_parts[1]
            if nos and mun:
                break

        # 4. Check existing directories in base_out_dir
        if base_out_dir and (not nos or not mun):
            for sub in ["Validation Output", "Validation Ouput", "Projects"]:
                check_dir = os.path.join(base_out_dir, sub)
                if os.path.isdir(check_dir):
                    existing_surveys = [
                        d
                        for d in os.listdir(check_dir)
                        if os.path.isdir(os.path.join(check_dir, d))
                    ]
                    if not nos:
                        for s_dir in existing_surveys:
                            for chk in [
                                sample_layer.name() if sample_layer else "",
                                sources[0] if sources else "",
                            ]:
                                if s_dir.lower() in chk.lower():
                                    nos = s_dir
                                    break
                            if nos:
                                break
                    if nos:
                        survey_dir = os.path.join(check_dir, nos)
                        if os.path.isdir(survey_dir):
                            existing_muns = [
                                d
                                for d in os.listdir(survey_dir)
                                if os.path.isdir(os.path.join(survey_dir, d))
                            ]
                            if not mun:
                                for m_dir in existing_muns:
                                    for chk in [
                                        sample_layer.name() if sample_layer else "",
                                        sources[0] if sources else "",
                                    ]:
                                        if m_dir.lower() in chk.lower():
                                            mun = m_dir
                                            break
                                    if mun:
                                        break

        # 5. Fallback defaults if still unresolved
        if not nos:
            if sample_layer:
                m = re.search(
                    r"^(.*?)_(?:Selected SSU|Selected_SSU|SelectedSSU)",
                    sample_layer.name(),
                    re.IGNORECASE,
                )
                if m:
                    nos = m.group(1).strip()
            if not nos:
                nos = "Survey"
        if not mun:
            mun = "Municipality"

        return nos, mun

    def update_ssu_list(self):
        """
        Merges missing records from Reference SSU into Sample SSU using (BSN, HUSN, HSN),
        validates that all records with Selected_SSU == 1 have valid Update Codes,
        generates an error layer if any errors exist, or saves the merged layer to
        <Output Folder>/Validation Output/<Name of Survey>/<City/Mun Name>/<filename>.gpkg.
        """
        sample_id = self.comboxSample.currentData()
        ref_id = self.comboxRef.currentData()

        sample_layer = QgsProject.instance().mapLayer(sample_id) if sample_id else None
        ref_layer = QgsProject.instance().mapLayer(ref_id) if ref_id else None

        if not sample_layer or not sample_layer.isValid() or not ref_layer or not ref_layer.isValid():
            self.log("Please ensure both Sample SSU and Reference SSU layers are valid.", "WARNING")
            self.progressBar.setValue(0)
            return

        # Resolve BSN, HUSN, HSN in both layers
        s_bsn = find_field_name(sample_layer, "BSN", ["bsn", "BS_No"])
        s_husn = find_field_name(sample_layer, "HUSN", ["husn", "HU_SN"])
        s_hsn = find_field_name(sample_layer, "HSN", ["hsn"])

        r_bsn = find_field_name(ref_layer, "BSN", ["bsn", "BS_No"])
        r_husn = find_field_name(ref_layer, "HUSN", ["husn", "HU_SN"])
        r_hsn = find_field_name(ref_layer, "HSN", ["hsn"])

        if not all([s_bsn, s_husn, s_hsn]):
            missing = [c for c, f in [("BSN", s_bsn), ("HUSN", s_husn), ("HSN", s_hsn)] if not f]
            self.log(f"Sample SSU layer is missing key column(s): {', '.join(missing)}", "ERROR")
            self.progressBar.setValue(0)
            return

        if not all([r_bsn, r_husn, r_hsn]):
            missing = [c for c, f in [("BSN", r_bsn), ("HUSN", r_husn), ("HSN", r_hsn)] if not f]
            self.log(f"Reference SSU layer is missing key column(s): {', '.join(missing)}", "ERROR")
            self.progressBar.setValue(0)
            return

        self.log(f"Starting Update SSU List: merging missing records from '{ref_layer.name()}' into '{sample_layer.name()}'...", "INFO")

        self.updateButton.setEnabled(False)
        self.progressBar.setValue(10)
        QCoreApplication.processEvents()

        try:
            # 0. Ensure Reference SSU layer is filtered based on Sample SSU layer to match the data
            self.filter_reference_layer(sample_layer, ref_layer, log_to_widget=False)

            # 1. Collect all keys currently present in Sample SSU
            sample_keys = set()
            for feat in sample_layer.getFeatures():
                b = str(feat[s_bsn]).strip() if not is_null_or_empty(feat[s_bsn]) else ""
                hu = str(feat[s_husn]).strip() if not is_null_or_empty(feat[s_husn]) else ""
                h = str(feat[s_hsn]).strip() if not is_null_or_empty(feat[s_hsn]) else ""
                if b or hu or h:
                    sample_keys.add((b, hu, h))

            self.progressBar.setValue(30)
            QCoreApplication.processEvents()

            # 2. Identify missing features from Reference SSU
            features_to_add = []
            sample_fields = sample_layer.fields()

            # Map sample field name -> ref field name
            field_map = {}
            for sf in sample_fields:
                rf = find_field_name(ref_layer, sf.name())
                if rf:
                    field_map[sf.name()] = rf

            missing_records_log = []

            for r_feat in ref_layer.getFeatures():
                b = str(r_feat[r_bsn]).strip() if not is_null_or_empty(r_feat[r_bsn]) else ""
                hu = str(r_feat[r_husn]).strip() if not is_null_or_empty(r_feat[r_husn]) else ""
                h = str(r_feat[r_hsn]).strip() if not is_null_or_empty(r_feat[r_hsn]) else ""
                key = (b, hu, h)

                if key not in sample_keys:
                    new_feat = QgsFeature(sample_fields)
                    if r_feat.hasGeometry():
                        new_feat.setGeometry(r_feat.geometry())

                    for s_col, r_col in field_map.items():
                        new_feat[s_col] = r_feat[r_col]

                    features_to_add.append(new_feat)
                    missing_records_log.append(f"BSN={b}, HUSN={hu}, HSN={h}")
                    sample_keys.add(key)  # prevent duplicate additions if ref has dupes

            self.progressBar.setValue(50)
            QCoreApplication.processEvents()

            # 3. Add missing features into sample layer if any
            if features_to_add:
                success = sample_layer.dataProvider().addFeatures(features_to_add)
                if not success:
                    self.log("ERROR: Failed to insert features into Sample SSU layer (dataProvider returned False).", "ERROR")
                    self.progressBar.setValue(0)
                    return

                sample_layer.updateExtents()
                sample_layer.triggerRepaint()
                if self.iface and hasattr(self.iface, "mapCanvas") and self.iface.mapCanvas():
                    self.iface.mapCanvas().refresh()

                self.log(
                    f"Successfully copied {len(features_to_add)} missing record(s) into '{sample_layer.name()}':",
                    "INFO"
                )
                for item in missing_records_log[:10]:
                    self.log(f"  + Added: {item}")
                if len(missing_records_log) > 10:
                    self.log(f"  + ... and {len(missing_records_log) - 10} more records.")
            else:
                self.log(
                    "Update SSU List: All records from Reference SSU are already present in Sample SSU (0 new records to add).",
                    "INFO"
                )

            # 4. PRE-SAVE VALIDATION on merged layer
            self.progressBar.setValue(70)
            QCoreApplication.processEvents()

            self.log("-" * 55)
            self.log("Running Pre-Save Validation on merged layer...", "INFO")

            f_sel = find_field_name(
                sample_layer,
                "Selected_SSU",
                ["Selected SSU", "selected_ssu", "SelectedSSU"],
            )
            f_uc = find_field_name(
                sample_layer,
                "Update Codes",
                [
                    "Updates_Codes",
                    "Update_Codes",
                    "Updates Codes",
                    "Update Codes",
                    "update codes",
                    "updates codes",
                    "update_code",
                    "UC",
                ],
            )

            if not f_sel:
                self.log("ERROR: 'Selected_SSU' column not found in merged Sample SSU layer.", "ERROR")
                self.progressBar.setValue(0)
                return

            if not f_uc:
                self.log("ERROR: 'Update Codes' column not found in merged Sample SSU layer.", "ERROR")
                self.progressBar.setValue(0)
                return

            layer_errors = []
            selected_1_count = 0

            for feat in sample_layer.getFeatures():
                raw_sel = feat[f_sel]
                if is_selected_ssu_1(raw_sel):
                    selected_1_count += 1
                    raw_uc = feat[f_uc]
                    if is_null_or_empty(raw_uc):
                        layer_errors.append(
                            (feat, "Selected_SSU is 1 but Update Codes is missing/null")
                        )

            # 5. Handle Errors vs Success
            if layer_errors:
                # Create temporary error layer
                temp_name = f"Errors_{sample_layer.name()}"
                crs_auth = sample_layer.crs().authid()
                if sample_layer.isSpatial():
                    wkb_type_str = QgsWkbTypes.displayString(sample_layer.wkbType())
                    uri = f"{wkb_type_str}?crs={crs_auth}"
                else:
                    uri = "none"

                # Remove existing layer with same name if any
                for old_id, old_lyr in list(QgsProject.instance().mapLayers().items()):
                    if old_lyr.name() == temp_name:
                        QgsProject.instance().removeMapLayer(old_id)

                temp_layer = QgsVectorLayer(uri, temp_name, "memory")
                t_pr = temp_layer.dataProvider()
                t_pr.addAttributes(sample_layer.fields())

                try:
                    from qgis.PyQt.QtCore import QMetaType
                    err_field = QgsField("Validation_Errors", QMetaType.Type.QString)
                except Exception:
                    err_field = QgsField("Validation_Errors", QVariant.String)

                t_pr.addAttributes([err_field])
                temp_layer.updateFields()

                new_err_feats = []
                for e_feat, e_reason in layer_errors:
                    nf = QgsFeature(temp_layer.fields())
                    if sample_layer.isSpatial() and e_feat.hasGeometry():
                        nf.setGeometry(e_feat.geometry())
                    attrs = e_feat.attributes()
                    attrs.append(e_reason)
                    nf.setAttributes(attrs)
                    new_err_feats.append(nf)

                t_pr.addFeatures(new_err_feats)
                temp_layer.updateExtents()

                apply_error_symbology(temp_layer)
                QgsProject.instance().addMapLayer(temp_layer)

                if hasattr(self, "iface") and self.iface:
                    self.iface.setActiveLayer(temp_layer)
                    if (
                        temp_layer.isSpatial()
                        and temp_layer.featureCount() > 0
                        and self.iface.mapCanvas()
                    ):
                        self.iface.mapCanvas().setExtent(temp_layer.extent())
                        self.iface.mapCanvas().refresh()

                self.log(
                    f"VALIDATION ERROR: Found {len(layer_errors)} record(s) where Selected_SSU = 1 "
                    f"but Update Codes is missing/null!"
                )
                self.log(f"Temporary error layer created: '{temp_name}'")
                self.log("Error Records List:")
                for idx, (e_feat, e_reason) in enumerate(layer_errors, 1):
                    b = str(e_feat[s_bsn]).strip() if s_bsn and not is_null_or_empty(e_feat[s_bsn]) else "-"
                    hu = str(e_feat[s_husn]).strip() if s_husn and not is_null_or_empty(e_feat[s_husn]) else "-"
                    h = str(e_feat[s_hsn]).strip() if s_hsn and not is_null_or_empty(e_feat[s_hsn]) else "-"
                    self.log(f"  [{idx}] BSN={b}, HUSN={hu}, HSN={h} (FID={e_feat.id()}) → {e_reason}")
                self.log("-" * 55)
                self.log("Pre-save Validation FAILED! The .gpkg file was NOT saved.", "ERROR")
                self.log(f"Found {len(layer_errors)} record(s) where Selected_SSU = 1 but Update Codes is missing.", "ERROR")
                self.log(f"A temporary layer '{temp_name}' has been created in QGIS with the error records.", "WARNING")
                self.log("Please resolve the missing Update Codes in the error layer before saving.", "WARNING")
                self.progressBar.setValue(0)
                return

            # No errors - Save to Validation Output/Name of Survey/City/Mun Name
            self.progressBar.setValue(85)
            QCoreApplication.processEvents()

            self.log(
                f"PRE-SAVE VALIDATION PASSED ✓ (All {selected_1_count} records with Selected_SSU = 1 "
                f"have valid Update Codes)."
            )

            base_out_dir = (
                self.outputDirWidget.filePath().strip()
                if hasattr(self, "outputDirWidget")
                else ""
            )
            if not base_out_dir:
                base_out_dir = r"C:\PSA-GIS\GeoFASU\Kalinga\Project files"

            nos, mun = self.resolve_survey_and_mun(sample_layer, ref_layer, base_out_dir)

            val_folder_name = "Validation Output"
            if os.path.isdir(os.path.join(base_out_dir, "Validation Ouput")) and not os.path.isdir(
                os.path.join(base_out_dir, "Validation Output")
            ):
                val_folder_name = "Validation Ouput"

            target_folder = os.path.join(base_out_dir, val_folder_name, nos, mun)
            os.makedirs(target_folder, exist_ok=True)

            layer_name = sample_layer.name()
            out_file_name = (
                f"{layer_name}.gpkg"
                if not layer_name.lower().endswith(".gpkg")
                else layer_name
            )
            out_gpkg_path = os.path.join(target_folder, out_file_name)
            source_path = sample_layer.source().split("|")[0]

            if os.path.exists(source_path) and os.path.abspath(source_path) == os.path.abspath(out_gpkg_path):
                self.log(f"GeoPackage updated in-place at:\n  {out_gpkg_path}")
            else:
                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.fileEncoding = "UTF-8"
                if hasattr(QgsVectorFileWriter, "CreateOrOverwriteFile"):
                    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
                write_res = QgsVectorFileWriter.writeAsVectorFormatV3(
                    sample_layer,
                    out_gpkg_path,
                    QgsProject.instance().transformContext(),
                    options,
                )
                res = write_res[0] if isinstance(write_res, tuple) else write_res
                err_str = (
                    write_res[3]
                    if (isinstance(write_res, tuple) and len(write_res) > 3)
                    else (
                        write_res[1]
                        if (isinstance(write_res, tuple) and len(write_res) > 1)
                        else ""
                    )
                )
                if res == QgsVectorFileWriter.NoError or res == 0:
                    self.log(f"Exported merged GeoPackage to Validation Output:\n  {out_gpkg_path}", "SUCCESS")
                else:
                    self.log(f"ERROR: Failed to write GeoPackage file to {out_gpkg_path}: {err_str}", "ERROR")
                    self.progressBar.setValue(0)
                    return

            self.progressBar.setValue(100)
            self.log("Update SSU List completed successfully! ✓", "SUCCESS")
            self.log(f"• Pre-save Validation: PASSED ({selected_1_count} records validated)", "INFO")
            if len(features_to_add) > 0:
                self.log(f"• Missing Records Copied: {len(features_to_add)}", "INFO")
            else:
                self.log("• Missing Records Copied: 0 (All reference records were already present)", "INFO")
            self.log(f"• Saved to: {out_gpkg_path}", "SUCCESS")
            self.progressBar.setValue(0)

        except Exception as e:
            self.log(f"EXCEPTION during update: {e}", "ERROR")
            self.progressBar.setValue(0)
        finally:
            self.updateButton.setEnabled(False)
            self.progressBar.setValue(0)

    def clear_logs(self):
        """Clears the execution logs and resets progress bar."""
        if hasattr(self, 'logsTextEdit') and self.logsTextEdit:
            self.logsTextEdit.clear()
        if hasattr(self, 'progressBar') and self.progressBar:
            self.progressBar.setValue(0)

    def reset_fields(self, preserve_quality_state=False):
        """Resets all input fields, logs, status, and progress bar to default values."""
        default_dir = r"C:\PSA-GIS\GeoFASU\Kalinga\Project files"
        if hasattr(self, "outputDirWidget"):
            self.outputDirWidget.setFilePath(default_dir)
        if not preserve_quality_state:
            self.quality_check_passed = False
            self.passed_layer_id = None
        self.populate_layers(reset_selection=not preserve_quality_state)
        self.clear_logs()
        self.set_status("READY")
        is_passed = self.quality_check_passed and (
            self.passed_layer_id is None
            or self.comboxSample.currentData() == self.passed_layer_id
        )
        self.runButton.setEnabled(is_passed)
        if not self.quality_check_passed:
            self.runButton.setToolTip(
                "Please run Quality Checker first. Completeness Check is enabled once Quality Checker passes."
            )
        elif not is_passed:
            self.runButton.setToolTip("Selected Sample Layer has not passed Quality Checker yet.")
        else:
            self.runButton.setToolTip("Quality Check PASSED. Click to run Completeness Check.")
        self.updateButton.setEnabled(False)
        self.progressBar.setValue(0)

    def closeEvent(self, event):
        """Clean close event, resets progress bar and all fields."""
        self.reset_fields()
        event.accept()

    def reject(self):
        """Clean reject event, resets progress bar and all fields."""
        self.reset_fields()
        super().reject()
