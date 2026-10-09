# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph

import os
import sys
import re
import shutil
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QCoreApplication

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsSnappingConfig,
    QgsTolerance,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
    Qgis,
)
from qgis.PyQt.QtWidgets import (
    QDialog, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QHBoxLayout, QLabel, QAbstractItemView, 
    QMessageBox, QInputDialog
)

from qgis.utils import iface

from .style import apply_modern_style, setup_dialog_logo

# QFieldSync (supports embedded and external plugin installation)
plugin_dir = os.path.dirname(__file__)
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

try:
    from qfieldsync.core.cloud_converter import CloudConverter
    from qfieldsync.core.preferences import Preferences
    HAS_QFIELDSYNC = True
except Exception:
    try:
        from .qfieldsync.core.cloud_converter import CloudConverter
        from .qfieldsync.core.preferences import Preferences
        HAS_QFIELDSYNC = True
    except Exception:
        HAS_QFIELDSYNC = False


FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'loader_dialog.ui'))


class LoaderDialog(QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setupUi(self)
        apply_modern_style(self)
        setup_dialog_logo(self)
        self.plugin_dir = os.path.dirname(__file__)
        self.load_successful = False

        self.aplqml.setEnabled(False)
        self.genrate.setEnabled(False)
        self.progbar.setValue(0)

        self.comboxNOS.setPlaceholderText("-- Select Type of Survey --")
        self.comboxMun.setPlaceholderText("-- Select City/Municipality --")
        self.comboxRep.setPlaceholderText("-- Select Replicate Number --")

        # Signals
        self.fileWidget.fileChanged.connect(self.populate_nos_list)
        self.comboxNOS.currentIndexChanged.connect(self.update_mun_list)
        self.comboxMun.currentIndexChanged.connect(self.update_rep_list)
        self.comboxRep.currentIndexChanged.connect(self.on_rep_change)
        self.loadbtn.clicked.connect(self.load_layers)
        self.aplqml.clicked.connect(self.apply_styles)
        self.genrate.clicked.connect(self.export_qfield_project)

    # ---------- Utilities ----------
    def _clean(self, s: str) -> str:
        """Windows-safe filename cleaner."""
        s = (s or "").strip()
        s = re.sub(r'[<>:"/\\|?*]+', "_", s)
        return s.rstrip(" .")

    def show_error(self, message: str):
        self.load_successful = False
        self.progbar.setValue(0)
        self.remove_all_layers()
        self.loadbtn.setEnabled(True)
        self.aplqml.setEnabled(False)
        self.genrate.setEnabled(False)
        QCoreApplication.processEvents()
        QMessageBox.critical(self, "Error", message)

    def remove_all_layers(self):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        for group_name in ['Tracklog', 'Samples', 'Reference Layer', 'Base Layer', 'Basemap']:
            group = root.findGroup(group_name)
            if group:
                for child in list(group.findLayers()):
                    lyr = child.layer()
                    if lyr:
                        project.removeMapLayer(lyr.id())
                root.removeChildNode(group)

        # Clean up any lingering GeoFASU-related layers from project
        known_keywords = ["Selected SSU", "Additional SSU", "Replacement PSU", "tracklog", "Bgy Bdry."]
        for layer_id, layer in list(project.mapLayers().items()):
            if layer and (any(kw in layer.name() for kw in known_keywords) or layer.name().endswith("_img")):
                project.removeMapLayer(layer_id)

        if hasattr(self, 'iface') and self.iface and self.iface.mapCanvas():
            self.iface.mapCanvas().refresh()

    def reset_all(self):
        """Reset UI and, if load failed, remove added groups."""
        if not self.load_successful:
            self.remove_all_layers()

        for w in (self.fileWidget, self.comboxNOS, self.comboxMun, self.comboxRep,
                  self.loadbtn, self.aplqml, self.genrate):
            w.setEnabled(True)

        self.fileWidget.setFilePath("")
        self.comboxNOS.clear()
        self.comboxMun.clear()
        self.comboxRep.clear()
        self.progbar.setValue(0)
        self.aplqml.setEnabled(False)
        self.genrate.setEnabled(False)
        self.load_successful = False

    def closeEvent(self, event):
        self.reset_all()
        event.accept()

    def get_sample_layer(self, layer_name: str = ""):
        root = QgsProject.instance().layerTreeRoot()
        samples_group = root.findGroup("Samples")
        if samples_group:
            for child in samples_group.children():
                if isinstance(child, QgsLayerTreeLayer) and child.layer():
                    if layer_name and child.name() == layer_name:
                        return child.layer()
                    if not layer_name and "_Selected SSU" in child.name():
                        return child.layer()
        for lyr in QgsProject.instance().mapLayers().values():
            if layer_name and lyr.name() == layer_name:
                return lyr
            if not layer_name and "_Selected SSU" in lyr.name():
                return lyr
        return None

    # ---------- Combos ----------
    def populate_nos_list(self):
        self.comboxNOS.blockSignals(True)
        self.comboxMun.blockSignals(True)
        self.comboxRep.blockSignals(True)

        self.comboxNOS.clear()
        self.comboxMun.clear()
        self.comboxRep.clear()
        self.aplqml.setEnabled(False)
        self.progbar.setValue(0)

        base_path = os.path.join(self.fileWidget.filePath(), 'Projects')
        if os.path.isdir(base_path):
            dir_list = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]
            self.comboxNOS.addItems(dir_list)
            self.comboxNOS.setCurrentIndex(-1)

        self.comboxNOS.blockSignals(False)
        self.comboxMun.blockSignals(False)
        self.comboxRep.blockSignals(False)

    def update_mun_list(self):
        self.comboxMun.blockSignals(True)
        self.comboxRep.blockSignals(True)

        self.comboxMun.clear()
        self.comboxRep.clear()
        nos = self.comboxNOS.currentText().strip()
        if nos:
            base_path = os.path.join(self.fileWidget.filePath(), 'Projects', nos)
            if os.path.isdir(base_path):
                dirs = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]
                self.comboxMun.addItems(dirs)
                self.comboxMun.setCurrentIndex(-1)

        self.comboxMun.blockSignals(False)
        self.comboxRep.blockSignals(False)

    def update_rep_list(self):
        self.comboxRep.blockSignals(True)
        self.comboxRep.clear()
        nos = self.comboxNOS.currentText().strip()
        mun = self.comboxMun.currentText().strip()
        if nos and mun:
            base_path = os.path.join(
                self.fileWidget.filePath(), 'Projects',
                nos, mun
            )
            if os.path.isdir(base_path):
                dirs = [d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))]
                self.comboxRep.addItems(dirs)
                self.comboxRep.setCurrentIndex(-1)

        self.comboxRep.blockSignals(False)

    def on_rep_change(self):
        if self.comboxRep.currentText().strip():
            self.aplqml.setEnabled(False)

    # ---------- Load ----------
    def load_layers(self):
        self.loadbtn.setEnabled(False)
        self.progbar.setValue(5)
        QCoreApplication.processEvents()

        try:
            working_dir = os.path.join(self.fileWidget.filePath().strip(), 'Projects')
            nos = self.comboxNOS.currentText().strip()
            mun = self.comboxMun.currentText().strip()
            rep = self.comboxRep.currentText().strip()
            if not all([working_dir, nos, mun, rep]):
                self.show_error("All inputs must be selected.")
                return

            self.progbar.setValue(10)
            QCoreApplication.processEvents()
            self.remove_all_layers()
            self.progbar.setValue(20)
            QCoreApplication.processEvents()

            root = QgsProject.instance().layerTreeRoot()
            groups = {name: root.addGroup(name) for name in
                      ['Tracklog', 'Samples', 'Base Layer', 'Basemap']}

            # Basemap (offline image)
            basemap_candidates = [
                os.path.join(self.fileWidget.filePath().strip(), 'Basemap', f"{mun}_img.gpkg"),
                os.path.join(self.fileWidget.filePath().strip(), 'Basemap', f"{mun}_img.mbtiles"),
                os.path.join(self.fileWidget.filePath().strip(), 'Basemap', f"{mun}_img.tif"),
                os.path.join(self.fileWidget.filePath().strip(), 'Basemap', f"{mun}.gpkg"),
                os.path.join(self.fileWidget.filePath().strip(), 'Basemap', f"{mun}.mbtiles"),
                os.path.join(self.fileWidget.filePath().strip(), 'Basemap', f"{mun}.tif"),
            ]
            basemap_path = next((p for p in basemap_candidates if os.path.exists(p)), None)
            if not basemap_path:
                self.show_error(f"Offline image file not found in Basemap folder for: {mun}")
                return

            basemap_layer = QgsRasterLayer(basemap_path, f"{mun}_img", "gdal")
            if not basemap_layer.isValid():
                self.show_error(f"Invalid offline image layer: {basemap_path}")
                return

            QgsProject.instance().addMapLayer(basemap_layer, False)
            groups['Basemap'].addLayer(basemap_layer)

            # Collapse basemap children
            for child in groups['Basemap'].children():
                if isinstance(child, QgsLayerTreeLayer):
                    child.setExpanded(False)

            self.progbar.setValue(35)
            QCoreApplication.processEvents()

            # Base Layer
            base_layer_path = os.path.join(self.fileWidget.filePath().strip(), 'Base Layers', f"{mun}.gpkg")
            base_layer = QgsVectorLayer(base_layer_path, "Bgy Bdry.", "ogr")
            if not base_layer.isValid():
                self.show_error(f"Invalid base layer: {base_layer_path}")
                return

            QgsProject.instance().addMapLayer(base_layer, False)
            groups['Base Layer'].addLayer(base_layer)

            self.progbar.setValue(50)
            QCoreApplication.processEvents()

            # Load existing Selected SSU layer from rep folder (created by Convert Excel to GPKG)
            rep_dir = os.path.join(working_dir, nos, mun, rep)
            sample_layer_name = f"{nos}_{mun}_Selected SSU_{rep}"
            selected_ssu_path = os.path.join(rep_dir, f"{sample_layer_name}.gpkg")

            if not os.path.exists(selected_ssu_path):
                self.show_error(f"Missing Selected SSU layer:\n{selected_ssu_path}\n\nPlease run 'Convert Excel to GPKG' first.")
                return

            selected_lyr = QgsVectorLayer(selected_ssu_path, sample_layer_name, "ogr")
            if not selected_lyr.isValid():
                self.show_error(f"Invalid Selected SSU layer:\n{selected_ssu_path}")
                return

            QgsProject.instance().addMapLayer(selected_lyr, False)
            groups['Samples'].addLayer(selected_lyr)

            self.progbar.setValue(65)
            QCoreApplication.processEvents()

            # Copy & load additional files to Samples/Tracklog (only Additional and Tracklog)
            file_ops = [
                ("additional.gpkg", f"{nos}_{mun}_Additional SSU or Replacement PSU sample.gpkg", "Samples",
                 f"{nos}_{mun}_Additional SSU or Replacement PSU sample"),
                ("tracklog.gpkg",   "tracklog.gpkg", "Tracklog", "tracklog"),
            ]

            step_inc = 30 / len(file_ops)
            for idx, (src_name, dest_name, group_name, layer_name) in enumerate(file_ops):
                src_path = os.path.join(self.plugin_dir, src_name)
                dest_path = os.path.join(rep_dir, dest_name)
                if not os.path.exists(src_path):
                    self.show_error(f"Missing source file: {src_path}")
                    return
                shutil.copyfile(src_path, dest_path)
                lyr = QgsVectorLayer(dest_path, layer_name, "ogr")
                if not lyr.isValid():
                    self.show_error(f"Invalid layer copied to: {dest_path}")
                    return
                QgsProject.instance().addMapLayer(lyr, False)
                groups[group_name].addLayer(lyr)
                self.progbar.setValue(int(65 + (idx + 1) * step_inc))
                QCoreApplication.processEvents()

            self.aplqml.setEnabled(True)
            self.progbar.setValue(100)
            self.genrate.setEnabled(False)
            self.load_successful = True
            QCoreApplication.processEvents()
            QMessageBox.information(self, "Success", "Layers successfully loaded.")

            # Zoom to first valid layer in Basemap
            for child in groups['Basemap'].children():
                if isinstance(child, QgsLayerTreeLayer):
                    lyr = child.layer()
                    if lyr and lyr.isValid():
                        self.iface.mapCanvas().setExtent(lyr.extent())
                        self.iface.mapCanvas().refresh()
                        break

        except Exception as e:
            self.show_error(f"Unexpected error: {str(e)}")
        finally:
            if not self.load_successful:
                self.progbar.setValue(0)
                self.loadbtn.setEnabled(True)
                self.aplqml.setEnabled(False)
                self.genrate.setEnabled(False)

    # ---------- Styles ----------
    def apply_styles(self):
        self.loadbtn.setEnabled(False)
        self.progbar.setValue(10)
        QCoreApplication.processEvents()

        try:
            root = QgsProject.instance().layerTreeRoot()
            style_dir = os.path.join(self.plugin_dir, "QML")

            required_groups = ["Basemap", "Samples", "Tracklog", "Base Layer"]
            # verify each group has at least one valid layer
            for gname in required_groups:
                group = root.findGroup(gname)
                if not group or not any(
                    isinstance(c, QgsLayerTreeLayer) and c.layer() and c.layer().isValid()
                    for c in group.children()
                ):
                    self.show_error("No/Missing Groups/Layer Loaded")
                    return

            def apply_qml(group_name: str, keyword: str, qml_file: str):
                group = root.findGroup(group_name)
                if not group:
                    return
                qml_path = os.path.join(style_dir, qml_file)
                if not os.path.exists(qml_path):
                    return
                for child in group.children():
                    if isinstance(child, QgsLayerTreeLayer):
                        lyr = child.layer()
                        if lyr and (keyword in lyr.name()):
                            lyr.loadNamedStyle(qml_path)
                            lyr.triggerRepaint()

            self.progbar.setValue(25)
            QCoreApplication.processEvents()
            apply_qml("Base Layer", "", "Barangay.qml")
            self.progbar.setValue(50)
            QCoreApplication.processEvents()
            apply_qml("Samples", "_Selected SSU", "Sample.qml")
            apply_qml("Samples", "_Additional", "Additional.qml")
            self.progbar.setValue(75)
            QCoreApplication.processEvents()
            apply_qml("Tracklog", "", "Tracklog.qml")

            # collapse layers in Samples
            samples_group = root.findGroup("Samples")
            if samples_group:
                for child in samples_group.children():
                    if isinstance(child, QgsLayerTreeLayer):
                        child.setExpanded(False)

            self.progbar.setValue(100)
            QCoreApplication.processEvents()
            QMessageBox.information(self, "Style Applied", "QML styles successfully applied.")

            self.aplqml.setEnabled(False)
            self.genrate.setEnabled(True)
            self.fileWidget.setEnabled(False)
            self.comboxNOS.setEnabled(False)
            self.comboxMun.setEnabled(False)
            self.comboxRep.setEnabled(False)

        except Exception as e:
            self.show_error(f"Failed to apply styles: {str(e)}")

    # ---------- Export ----------
    def export_qfield_project(self):
        if not HAS_QFIELDSYNC:
            QMessageBox.critical(self, "Error", "QFieldSync plugin is not installed or enabled. Please install QFieldSync to use this export feature.")
            return

        project = QgsProject.instance()

        base_dir = self.fileWidget.filePath()
        if not base_dir:
            QMessageBox.critical(self, "Error", "Please select an output folder.")
            return
        base_path = Path(base_dir)

        nos = self._clean(self.comboxNOS.currentText())
        mun = self._clean(self.comboxMun.currentText())
        rep = self._clean(self.comboxRep.currentText())
        if not all([nos, mun, rep]):
            QMessageBox.critical(self, "Error", "NOS, MUN, and REP must be selected.")
            return

        # ---------- Detect PSU count before asking ----------
        sample_layer_name = f"{nos}_{mun}_Selected SSU_{rep}"
        layer = self.get_sample_layer(sample_layer_name) or self.get_sample_layer()
        single_psu_only = False
        single_psu_name = None
        if layer:
            idx = layer.fields().lookupField("PSU_Name")
            if idx != -1:
                psu_names = sorted({self._clean(str(f[idx])) for f in layer.getFeatures() if f[idx] not in (None, "")})
                if len(psu_names) == 1:
                    single_psu_only = True
                    single_psu_name = psu_names[0]

        # ---------- Ask only if more than one PSU ----------
        if single_psu_only:
            reply = QMessageBox.Yes
        else:
            reply = QMessageBox.question(
                self, "Export by PSU?",
                "Do you want to export separately by PSU name?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )

        # Remember last directory
        try:
            Preferences().set_value("exportDirectory", str(base_path))
        except Exception:
            pass

        def run_convert(inner_folder_name, psu_filter=None, progress_callback=None):
            def set_prog(val):
                if progress_callback:
                    progress_callback(val)
                QCoreApplication.processEvents()

            set_prog(5)
            target_root = base_path / "Package for Qfield" / nos
            target_dir = target_root / inner_folder_name
            target_dir.mkdir(parents=True, exist_ok=True)

            val_root = base_path / "Validation Output" / nos / mun
            val_root.mkdir(parents=True, exist_ok=True)

            import time
            import tempfile
            import qgis.utils
            from qgis.core import QgsProject, QgsLayerTreeLayer
            import gc

            temp_proj_path = str(base_path / "geofasu_temp_export.qgz")
            project.write(temp_proj_path)
            
            temp_project = QgsProject()
            temp_project.read(temp_proj_path)
            temp_project.setFileName(str(target_dir / f"{inner_folder_name}.qgz"))

            sample_extent = None
            sample_layer_obj = None
            if psu_filter:
                root = temp_project.layerTreeRoot()
                # Filter Sample Layer
                sample_group = root.findGroup("Samples")
                if sample_group:
                    for child in sample_group.children():
                        if child.name() == sample_layer_name and child.layer():
                            sample_lyr = child.layer()
                            sample_lyr.setSubsetString(f"\"PSU_Name\" = '{psu_filter}'")
                            sample_lyr.updateExtents()
                            sample_extent = sample_lyr.extent()
                            sample_layer_obj = sample_lyr
                            
                            try:
                                from qgis.core import QgsRectangle, QgsReferencedRectangle
                                ext_copy = QgsRectangle(sample_extent)
                                ext_copy.scale(1.2)
                                sample_rect = QgsReferencedRectangle(ext_copy, sample_lyr.crs())
                                temp_project.viewSettings().setDefaultViewExtent(sample_rect)
                                temp_project.viewSettings().setPresetExtent(sample_rect)
                            except Exception as e:
                                print(f"Set view extent error: {e}")
                            break
                # Filter Base Layer to exact barangay boundary
                import re
                base_group = root.findGroup("Base Layer")
                base_layer_for_mask = None
                matching_features = []
                
                if base_group:
                    for child in base_group.children():
                        if isinstance(child, QgsLayerTreeLayer) and child.layer():
                            base_layer_for_mask = child.layer()
                            break

                if base_layer_for_mask and base_layer_for_mask.isValid():
                    from qgis.core import (
                        QgsCoordinateTransform,
                        QgsGeometry
                    )
                    
                    # 1. Collect sample geometries for spatial intersection
                    sample_geoms = []
                    if sample_layer_obj and sample_layer_obj.isValid():
                        xform = None
                        if sample_layer_obj.crs() != base_layer_for_mask.crs() and sample_layer_obj.crs().isValid() and base_layer_for_mask.crs().isValid():
                            xform = QgsCoordinateTransform(sample_layer_obj.crs(), base_layer_for_mask.crs(), temp_project.transformContext())
                        for f in sample_layer_obj.getFeatures():
                            g = f.geometry()
                            if g and not g.isEmpty():
                                g_copy = QgsGeometry(g)
                                if xform:
                                    g_copy.transform(xform)
                                sample_geoms.append(g_copy)

                    # Check spatial intersection
                    if sample_geoms:
                        combined_sample = QgsGeometry.unaryUnion(sample_geoms) if len(sample_geoms) > 1 else sample_geoms[0]
                        for feat in base_layer_for_mask.getFeatures():
                            geom = feat.geometry()
                            if geom and not geom.isEmpty() and geom.intersects(combined_sample):
                                matching_features.append(feat)

                    # 2. Fallback to robust name matching if spatial matching found nothing
                    if not matching_features:
                        field_names = [f.name() for f in base_layer_for_mask.fields()]
                        target_field = "name"
                        for cand in ["name", "NAME", "Bgy_Name", "bgy_name", "BARANGAY", "Barangay", "BGY_NAME", "BRGY_NAME", "brgy_name", "BG_NAME"]:
                            if cand in field_names:
                                target_field = cand
                                break

                        base_filter = re.split(r'\s*-\s*EA\b', psu_filter, flags=re.IGNORECASE)[0].strip()
                        base_filter_clean = re.sub(r'^\s*(\d+|PSU\s*\d*)\s*[-_:]\s*', '', base_filter, flags=re.IGNORECASE).strip()
                        
                        parts = re.split(r'\s*\+\s*|\s*/\s*|\s*&\s*|\s+and\s+', base_filter_clean, flags=re.IGNORECASE)
                        parts = [p.strip().upper() for p in parts if p.strip()]

                        for feat in base_layer_for_mask.getFeatures():
                            val = feat[target_field]
                            if val:
                                val_norm = str(val).strip().upper()
                                for p in parts:
                                    if p == val_norm or p in val_norm or val_norm in p:
                                        matching_features.append(feat)
                                        break

                    # Apply subset filter on Base Layer
                    if matching_features:
                        field_names = [f.name() for f in base_layer_for_mask.fields()]
                        target_field = "name"
                        for cand in ["name", "NAME", "Bgy_Name", "bgy_name", "BARANGAY", "Barangay", "BGY_NAME", "BRGY_NAME", "brgy_name", "BG_NAME"]:
                            if cand in field_names:
                                target_field = cand
                                break
                        
                        if "fid" in field_names:
                            fid_list = [str(f.id()) for f in matching_features]
                            base_layer_for_mask.setSubsetString(f"\"fid\" IN ({', '.join(fid_list)})")
                        else:
                            name_vals = [f"'{str(f[target_field]).replace('\'', '\'\'')}'" for f in matching_features if f[target_field]]
                            if name_vals:
                                base_layer_for_mask.setSubsetString(f"\"{target_field}\" IN ({', '.join(set(name_vals))})")

                # Clip Basemap to exact Barangay boundary container
                basemap_group = root.findGroup("Basemap")
                if basemap_group and matching_features:
                    for child in basemap_group.children():
                        if isinstance(child, QgsLayerTreeLayer) and child.layer():
                            set_prog(20)
                            raster_layer = child.layer()
                            import processing
                            import tempfile
                            import uuid
                            from osgeo import gdal
                            from qgis.core import (
                                QgsVectorLayer,
                                QgsFeature,
                                QgsGeometry,
                                QgsRasterLayer,
                                QgsCoordinateTransform,
                                QgsVectorFileWriter
                            )
                            
                            raster_crs = raster_layer.crs()
                            base_crs = base_layer_for_mask.crs()
                            xform = None
                            if raster_crs.isValid() and base_crs.isValid() and raster_crs != base_crs:
                                xform = QgsCoordinateTransform(base_crs, raster_crs, temp_project.transformContext())

                            crs_auth = raster_crs.authid() if raster_crs.isValid() else base_crs.authid()
                            mask_memory_layer = QgsVectorLayer(f"MultiPolygon?crs={crs_auth}", "barangay_mask", "memory")
                            dp = mask_memory_layer.dataProvider()
                            
                            mask_feats = []
                            for feat in matching_features:
                                geom = feat.geometry()
                                if geom and not geom.isEmpty():
                                    g_copy = QgsGeometry(geom)
                                    if xform:
                                        g_copy.transform(xform)
                                    f_new = QgsFeature()
                                    f_new.setGeometry(g_copy)
                                    mask_feats.append(f_new)
                            
                            if mask_feats:
                                dp.addFeatures(mask_feats)
                                mask_memory_layer.updateExtents()

                                temp_mask_path = os.path.join(
                                    tempfile.gettempdir(),
                                    f"mask_{inner_folder_name}_{uuid.uuid4().hex[:6]}.gpkg"
                                )
                                QgsVectorFileWriter.writeAsVectorFormat(
                                    mask_memory_layer, temp_mask_path, "UTF-8", raster_crs, "GPKG"
                                )

                                # Calculate exact bounding box to avoid scanning entire municipality raster
                                extent = mask_memory_layer.extent()
                                if mask_memory_layer.crs() != raster_crs and mask_memory_layer.crs().isValid() and raster_crs.isValid():
                                    xform_box = QgsCoordinateTransform(mask_memory_layer.crs(), raster_crs, temp_project.transformContext())
                                    extent = xform_box.transformBoundingBox(extent)
                                bounds = [extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()]

                                temp_tif_path = os.path.join(
                                    tempfile.gettempdir(),
                                    f"{raster_layer.name()}_{inner_folder_name}_{uuid.uuid4().hex[:6]}.tif"
                                )

                                try:
                                    gdal.SetCacheMax(512 * 1024 * 1024)
                                    gdal.Warp(
                                        temp_tif_path,
                                        raster_layer.source(),
                                        format='GTiff',
                                        outputBounds=bounds,
                                        cutlineDSName=temp_mask_path,
                                        cropToCutline=True,
                                        dstSRS=raster_crs.authid() if raster_crs.isValid() else None,
                                        warpOptions=['NUM_THREADS=ALL_CPUS'],
                                        creationOptions=['COMPRESS=JPEG', 'JPEG_QUALITY=80', 'TILED=YES', 'NUM_THREADS=ALL_CPUS']
                                    )

                                    if os.path.exists(temp_tif_path):
                                        ds = gdal.Open(temp_tif_path, gdal.GA_Update)
                                        if ds:
                                            ds.BuildOverviews("NEAREST", [2, 4, 8, 16])
                                            ds = None

                                        new_raster = QgsRasterLayer(temp_tif_path, raster_layer.name(), "gdal")
                                        if new_raster.isValid():
                                            temp_project.addMapLayer(new_raster, False)
                                            basemap_group.insertLayer(0, new_raster)
                                            temp_project.removeMapLayer(raster_layer.id())

                                    try:
                                        if os.path.exists(temp_mask_path):
                                            os.remove(temp_mask_path)
                                    except Exception:
                                        pass
                                except Exception as e:
                                    print(f"Fast clip failed: {e}")
                            break

            try:
                root = temp_project.layerTreeRoot()
                sample_group = root.findGroup("Samples")
                sample_layers = set()
                if sample_group:
                    for child in sample_group.children():
                        if isinstance(child, QgsLayerTreeLayer) and child.layer():
                            sample_layers.add(child.layer().id())

                for layer in temp_project.mapLayers().values():
                    if layer.id() not in sample_layers:
                        try:
                            layer.setCustomProperty("identify/disabled", True)
                            layer.setReadOnly(True)
                        except Exception:
                            pass

                set_prog(50)
                original_addProject = qgis.utils.iface.addProject
                qgis.utils.iface.addProject = lambda p: None
                try:
                    conv = CloudConverter(temp_project, str(target_dir))
                    conv.convert()
                finally:
                    qgis.utils.iface.addProject = original_addProject
                    del conv
                    temp_project.clear()
                    del temp_project
                    gc.collect()

                # Rename attachments to 'attachments.zip'
                attachments = sorted(
                    target_dir.glob("*_attachments.zip"),
                    key=lambda p: p.stat().st_mtime, reverse=True
                )
                if attachments:
                    dest = target_dir / "attachments.zip"
                    try:
                        if dest.exists():
                            dest.unlink()
                        newest = attachments[0]
                        newest.replace(dest)
                        for p in attachments[1:]:
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass

                set_prog(80)
                # Package newest .qgs -> .qgz (then delete .qgs)
                qgs_candidates = sorted(
                    target_dir.glob("*.qgs"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                if not qgs_candidates:
                    listing = "\n".join(sorted(p.name for p in target_dir.glob("*")))
                    raise FileNotFoundError("No .qgs produced by converter.\n" + f"Folder contents:\n{listing}")

                produced_qgs = qgs_candidates[0]

                if psu_filter:
                    old_gpkg_name = f"{nos}_{mun}_Selected SSU_{rep}.gpkg"
                    new_gpkg_name = f"{nos}_{mun}_Selected SSU_{rep}_{psu_filter}.gpkg"
                    old_gpkg_path = target_dir / old_gpkg_name
                    if old_gpkg_path.exists():
                        for _ in range(10):
                            try:
                                old_gpkg_path.rename(target_dir / new_gpkg_name)
                                break
                            except PermissionError:
                                time.sleep(0.2)
                                
                        qgs_content = produced_qgs.read_text(encoding="utf-8")
                        qgs_content = qgs_content.replace(old_gpkg_name, new_gpkg_name)
                        produced_qgs.write_text(qgs_content, encoding="utf-8")

                    if sample_extent:
                        import xml.etree.ElementTree as ET
                        try:
                            tree = ET.parse(produced_qgs)
                            root_xml = tree.getroot()
                            mapcanvas = root_xml.find("mapcanvas")
                            if mapcanvas is not None:
                                extent_xml = mapcanvas.find("extent")
                                if extent_xml is None:
                                    extent_xml = ET.SubElement(mapcanvas, "extent")
                                
                                ext = sample_extent
                                ext.scale(1.2)
                                
                                for tag, val in [("xmin", ext.xMinimum()), ("ymin", ext.yMinimum()), ("xmax", ext.xMaximum()), ("ymax", ext.yMaximum())]:
                                    elem = extent_xml.find(tag)
                                    if elem is None:
                                        elem = ET.SubElement(extent_xml, tag)
                                    elem.text = str(val)
                                    
                            tree.write(produced_qgs, encoding="utf-8", xml_declaration=True)
                        except Exception as e:
                            print(f"Failed to patch extent in QGS: {e}")

                qgz_path = target_dir / f"{inner_folder_name}.qgz"
                if qgz_path.exists():
                    qgz_path.unlink()

                with ZipFile(qgz_path, "w", compression=ZIP_DEFLATED) as zf:
                    zf.write(str(produced_qgs), arcname="project.qgs")

                produced_qgs.unlink(missing_ok=True)
                backup = target_dir / (produced_qgs.name + "~")
                backup.unlink(missing_ok=True)

                return qgz_path

            finally:
                pass

        # ---------- If not exporting per PSU ----------
        if reply == QMessageBox.No:
            self.genrate.setEnabled(False)
            self.progbar.setValue(0)
            QCoreApplication.processEvents()
            inner_folder = f"{nos}_{mun}_Selected SSU_{rep}"
            try:
                filter_val = single_psu_name if single_psu_only else None
                qgz_path = run_convert(inner_folder, psu_filter=filter_val, progress_callback=self.progbar.setValue)
                self.progbar.setValue(100)
                QCoreApplication.processEvents()
                QMessageBox.information(self, "Export Successful",
                                        f"Folder:\n{qgz_path.parent}\n\nProject (.qgz only):\n{qgz_path}")
                # Reset UI
                self.fileWidget.setEnabled(True)
                self.comboxNOS.setEnabled(True)
                self.comboxMun.setEnabled(True)
                self.comboxRep.setEnabled(True)
                self.comboxMun.setCurrentIndex(0)
                self.comboxRep.setCurrentIndex(0)
                self.progbar.setValue(0)
                self.aplqml.setEnabled(False)
                self.genrate.setEnabled(False)
                self.loadbtn.setEnabled(True)
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))
            return

        # ---------- Export per PSU ----------
        if not layer:
            layer = self.get_sample_layer(f"{nos}_{mun}_Selected SSU_{rep}") or self.get_sample_layer()
        if not layer:
            QMessageBox.critical(self, "Error", f"Sample layer '{nos}_{mun}_Selected SSU_{rep}' not found.")
            return
        idx = layer.fields().lookupField("PSU_Name")
        if idx == -1:
            QMessageBox.critical(self, "Error", f"Field 'PSU_Name' not found in layer '{layer.name()}'.")
            return

        psu_names = sorted({self._clean(str(f[idx])) for f in layer.getFeatures() if f[idx] not in (None, "")})
        if not psu_names:
            QMessageBox.critical(self, "Error", "No PSU_Name values found.")
            return

        if single_psu_only:
            selected_psus = [single_psu_name]
        else:
            selected_psus = self.choose_psus(psu_names)
            if not selected_psus:
                return  # user cancelled

        self.genrate.setEnabled(False)
        self.progbar.setValue(0)
        QCoreApplication.processEvents()

        success, fail = 0, 0
        errors = []
        total = len(selected_psus)
        for i, psu in enumerate(selected_psus):
            self.progbar.setValue(int((i / total) * 100))
            QCoreApplication.processEvents()
            
            def make_cb(index):
                def cb(p):
                    self.progbar.setValue(int(((index + (p / 100)) / total) * 100))
                return cb
                
            inner_folder = f"{nos}_{mun}_Selected SSU_{rep}_{psu}"
            try:
                _ = run_convert(inner_folder, psu_filter=psu, progress_callback=make_cb(i))
                success += 1
            except Exception as e:
                fail += 1
                errors.append(f"{psu}: {e}")

        self.progbar.setValue(100)
        QCoreApplication.processEvents()
        summary = f"Generated {success} Qfield Projects"

        # Reset UI
        self.fileWidget.setEnabled(True)
        self.comboxNOS.setEnabled(True)
        self.comboxMun.setEnabled(True)
        self.comboxRep.setEnabled(True)
        self.comboxMun.setCurrentIndex(0)
        self.comboxRep.setCurrentIndex(0)
        self.progbar.setValue(0)
        self.aplqml.setEnabled(False)
        self.genrate.setEnabled(False)
        self.loadbtn.setEnabled(True)

        if fail:
            summary += f"\nFailed: {fail}\n" + "\n".join(errors[:10])

        QMessageBox.information(self, "Batch Export Finished", summary)
            
    def choose_psus(self, psu_names):
        """Modal dialog to choose multiple PSU names. Returns a list of selected names."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Choose PSU Name(s)")
        apply_modern_style(dlg)

        label = QLabel("Select one or more PSU Name:")
        listw = QListWidget()
        listw.addItems(psu_names)
        listw.setSelectionMode(QAbstractItemView.MultiSelection)
        listw.setMinimumWidth(440)
        listw.setMinimumHeight(320)

        btn_ok = QPushButton("Export")
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setProperty("secondary", True)
        btn_all = QPushButton("Select All")
        btn_all.setProperty("secondary", True)
        btn_clear = QPushButton("Clear")
        btn_clear.setProperty("secondary", True)

        def _select_all():
            listw.selectAll()

        def _clear():
            listw.clearSelection()

        def _accept():
            if not listw.selectedItems():
                QMessageBox.information(self, "Nothing selected", "Please select at least one PSU Name.")
                return
            dlg.accept()

        btn_all.clicked.connect(_select_all)
        btn_clear.clicked.connect(_clear)
        btn_ok.clicked.connect(_accept)
        btn_cancel.clicked.connect(dlg.reject)

        # layout
        btns_left = QHBoxLayout()
        btns_left.addWidget(btn_all)
        btns_left.addWidget(btn_clear)
        btns_left.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(label)
        layout.addWidget(listw)
        layout.addLayout(btns_left)
        layout.addLayout(btns)

        if dlg.exec_() == QDialog.Accepted:
            return [it.text() for it in listw.selectedItems()]
        return []