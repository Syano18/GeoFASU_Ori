# Developer: TechCraft by Chano
# email: c.dacpano@psa.gov.ph

import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt, QCoreApplication

# Set your GitHub repository here ("owner/repository")
GITHUB_REPO = "Syano18/GeoFASU_Ori"


def get_metadata_info():
    metadata_path = Path(__file__).parent / "metadata.txt"
    info = {"name": "GeoFASU_Ori", "version": "0.0.0", "repository": GITHUB_REPO}
    if not metadata_path.exists():
        return info

    with open(metadata_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("name="):
                info["name"] = line.split("=", 1)[1].strip()
            elif line.startswith("version="):
                info["version"] = line.split("=", 1)[1].strip()
            elif line.startswith("repository="):
                info["repository"] = line.split("=", 1)[1].strip().replace("https://github.com/", "").rstrip("/")
    return info


def parse_version_tuple(v_str):
    clean_v = v_str.lstrip("vV").strip()
    try:
        return tuple(map(int, clean_v.split(".")))
    except ValueError:
        return (0, 0, 0)


def check_for_updates(parent=None, silent_if_latest=False):
    meta = get_metadata_info()
    plugin_name = meta.get("name", "GeoFASU_Ori")
    local_version = meta.get("version", "0.0.0")
    repo = meta.get("repository", GITHUB_REPO)

    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "QGIS-Plugin-Updater",
            "Accept": "application/vnd.github.v3+json"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            release_data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        if not silent_if_latest:
            QMessageBox.warning(
                parent,
                "Update Check Failed",
                f"Could not check for updates on repository '{repo}':\n\n{str(e)}"
            )
        return

    latest_tag = release_data.get("tag_name", "")
    zip_url = release_data.get("zipball_url")

    if parse_version_tuple(latest_tag) > parse_version_tuple(local_version):
        msg_text = (
            f"A new version of {plugin_name} is available!\n\n"
            f"• Current version: {local_version}\n"
            f"• Latest version: {latest_tag}\n\n"
            "Do you want to download and install the update now?"
        )
        reply = QMessageBox.question(
            parent,
            "Update Available",
            msg_text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes and zip_url:
            _apply_update(parent, zip_url, latest_tag)
    else:
        if not silent_if_latest:
            QMessageBox.information(
                parent,
                "Up to Date",
                f"You are already using the latest version (v{local_version})."
            )


def _apply_update(parent, zip_url, new_tag):
    plugin_dir = Path(__file__).parent
    temp_zip = Path(tempfile.gettempdir()) / f"geofasu_update_{new_tag}.zip"
    extract_dir = Path(tempfile.gettempdir()) / f"geofasu_extracted_{new_tag}"

    progress = QProgressDialog("Downloading update...", "Cancel", 0, 100, parent)
    progress.setWindowTitle("Updating Plugin")
    progress.setWindowModality(Qt.WindowModal)
    progress.show()
    QCoreApplication.processEvents()

    try:
        req = urllib.request.Request(zip_url, headers={"User-Agent": "QGIS-Plugin-Updater"})
        with urllib.request.urlopen(req, timeout=30) as response, open(temp_zip, "wb") as out_file:
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            block_size = 8192
            while True:
                if progress.wasCanceled():
                    return
                chunk = response.read(block_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    percent = min(int((downloaded / total_size) * 85), 85)
                    progress.setValue(percent)
                QCoreApplication.processEvents()

        progress.setLabelText("Installing files...")
        progress.setValue(90)
        QCoreApplication.processEvents()

        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # GitHub ZIPs wrap content inside a root subfolder (e.g. owner-repo-hash)
        subfolders = [f for f in extract_dir.iterdir() if f.is_dir()]
        source_dir = subfolders[0] if subfolders else extract_dir

        for item in source_dir.iterdir():
            dest = plugin_dir / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        progress.setValue(100)
        QMessageBox.information(
            parent,
            "Update Complete",
            f"Successfully updated to {new_tag}!\n\nPlease restart QGIS or reload the plugin to apply the changes."
        )
    except Exception as e:
        QMessageBox.critical(parent, "Update Error", f"Failed to apply update:\n{str(e)}")
    finally:
        progress.close()
        if temp_zip.exists():
            try:
                temp_zip.unlink()
            except Exception:
                pass
        if extract_dir.exists():
            try:
                shutil.rmtree(extract_dir)
            except Exception:
                pass
