# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph

from pathlib import Path
from qgis.PyQt.QtWidgets import QAction, QMenu
from qgis.PyQt.QtGui import QIcon

try:
    from .main_dialog import PreprocessingDialog, PostprocessingDialog
    from .folder_creator_dialog import FolderCreatorDialog
    from .updater import check_for_updates
    from . import resources_rc
except (ImportError, ValueError):
    from main_dialog import PreprocessingDialog, PostprocessingDialog
    from folder_creator_dialog import FolderCreatorDialog
    from updater import check_for_updates
    import resources_rc


class GeoFASU:
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.folder_creator_dlg = None
        self.pre_dlg = None
        self.post_dlg = None
        self.menu = None
        self.main_action = None

    def initGui(self):
        icons_path = Path(__file__).parent / "icons"

        # Create custom top-level menu
        self.menu = QMenu("&GeoFASU_Ori", self.iface.mainWindow())

        # 1. Standalone Folder Creator Action
        self.folder_creator_action = QAction(
            QIcon(str(icons_path / "folder.png")),
            "Create Folder Structure",
            self.iface.mainWindow()
        )
        self.folder_creator_action.triggered.connect(self.run_folder_creator)

        # 2. Preprocessing Action (Directly opens Preprocessing dialog)
        self.preprocessing_action = QAction(
            QIcon(str(icons_path / "preprocessing.png")),
            "Preprocessing",
            self.iface.mainWindow()
        )
        self.preprocessing_action.triggered.connect(lambda: self.run_preprocessing(0))

        # 3. Postprocessing Action (Directly opens Postprocessing dialog)
        self.postprocessing_action = QAction(
            QIcon(str(icons_path / "postprocessing.png")),
            "Postprocessing",
            self.iface.mainWindow()
        )
        self.postprocessing_action.triggered.connect(lambda: self.run_postprocessing(0))

        # 4. Check for Updates Action
        self.update_action = QAction(
            QIcon(str(icons_path / "update.png")),
            "Check for Updates...",
            self.iface.mainWindow()
        )
        self.update_action.triggered.connect(
            lambda: check_for_updates(self.iface.mainWindow(), silent_if_latest=False)
        )

        # Populate top-level menu directly without nested submenus
        self.menu.addAction(self.folder_creator_action)
        self.menu.addSeparator()
        self.menu.addAction(self.preprocessing_action)
        self.menu.addAction(self.postprocessing_action)
        self.menu.addSeparator()
        self.menu.addAction(self.update_action)

        # Add toolbar icon
        if hasattr(self.iface, 'addToolBarIcon'):
            self.main_action = QAction(
                QIcon(str(icons_path / "icon.png")),
                "GeoFASU_Ori",
                self.iface.mainWindow()
            )
            self.main_action.triggered.connect(lambda: self.run_preprocessing(0))
            self.iface.addToolBarIcon(self.main_action)

        # Add custom menu directly to QGIS top-level menu bar
        menu_bar = self.iface.mainWindow().menuBar()
        help_menu = self.iface.helpMenu() if hasattr(self.iface, 'helpMenu') else None
        if help_menu:
            menu_bar.insertMenu(help_menu.menuAction(), self.menu)
        else:
            menu_bar.addMenu(self.menu)

    def unload(self):
        # Remove toolbar icon
        if hasattr(self.iface, 'removeToolBarIcon') and self.main_action:
            self.iface.removeToolBarIcon(self.main_action)

        # Remove the top-level menu from the QGIS main window menu bar
        if self.menu:
            menu_bar = self.iface.mainWindow().menuBar()
            menu_bar.removeAction(self.menu.menuAction())
            self.menu.deleteLater()
            self.menu = None

    def run_folder_creator(self):
        if not self.folder_creator_dlg:
            self.folder_creator_dlg = FolderCreatorDialog()
        self.folder_creator_dlg.show()
        self.folder_creator_dlg.raise_()
        self.folder_creator_dlg.activateWindow()

    def run_preprocessing(self, tab_index=0):
        if not self.pre_dlg:
            self.pre_dlg = PreprocessingDialog(self.iface.mainWindow())

            # Cross-dialog directory sync
            def sync_dir():
                if self.post_dlg and hasattr(self.post_dlg, 'tab_gpkg_excel'):
                    p = self.pre_dlg.tab_loader.fileWidget.filePath()
                    if p:
                        self.post_dlg.tab_gpkg_excel.fileWidget.setFilePath(p)

            self.pre_dlg.tab_loader.fileWidget.fileChanged.connect(sync_dir)

        self.pre_dlg.set_active_tab(tab_index)
        self.pre_dlg.show()
        self.pre_dlg.raise_()
        self.pre_dlg.activateWindow()

    def run_postprocessing(self, tab_index=0):
        if not self.post_dlg:
            self.post_dlg = PostprocessingDialog(self.iface, self.iface.mainWindow())

            # Cross-dialog directory sync
            if self.pre_dlg:
                p = self.pre_dlg.tab_loader.fileWidget.filePath()
                if p:
                    self.post_dlg.tab_gpkg_excel.fileWidget.setFilePath(p)

        self.post_dlg.set_active_tab(tab_index)
        self.post_dlg.show()
        self.post_dlg.raise_()
        self.post_dlg.activateWindow()

    # Backward compatibility helpers
    def run_dialog(self, target=0):
        if target in (0, 1, 'converter', 'loader'):
            self.run_preprocessing(target if isinstance(target, int) else (0 if target == 'converter' else 1))
        else:
            self.run_postprocessing(0 if target in (2, 'checker') else 1)

    def run_converter(self):
        self.run_preprocessing(0)

    def run_loader(self):
        self.run_preprocessing(1)

    def run_qfield(self):
        self.run_preprocessing(1)

    def run_checker(self):
        self.run_postprocessing(0)

    def run_gpkg_to_excel(self):
        self.run_postprocessing(1)
