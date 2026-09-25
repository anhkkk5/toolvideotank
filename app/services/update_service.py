"""TankVideo In-App Auto-Update Service.

Checks GitHub Releases for updates, downloads patch archives,
and seamlessly updates the application via a lightweight Windows helper script.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from typing import Any, Callable

from app.version import APP_VERSION, GITHUB_REPO


def parse_version_tuple(ver_str: str) -> tuple[int, ...]:
    clean = re.sub(r"[^\d.]", "", str(ver_str or "").strip())
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts or [0])


class UpdateService:
    def __init__(self, workspace_root: str | None = None):
        self.workspace_root = workspace_root or os.getcwd()
        self.current_version = APP_VERSION
        self.repo = GITHUB_REPO

    def check_for_updates(self) -> dict[str, Any]:
        """Kiểm tra bản cập nhật mới nhất từ GitHub Releases API."""
        url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "TankVideo-AutoUpdater",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status != 200:
                    return {"has_update": False, "error": f"HTTP {resp.status}"}
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return {"has_update": False, "error": str(exc)}

        tag_name = str(data.get("tag_name", "") or "").strip()
        latest_ver_clean = tag_name.lstrip("vV")
        current_ver_clean = self.current_version.lstrip("vV")

        has_update = parse_version_tuple(latest_ver_clean) > parse_version_tuple(current_ver_clean)

        assets = list(data.get("assets") or [])
        patch_asset = None
        # Ưu tiên tìm file patch nhỏ (dưới 100MB)
        for asset in assets:
            name = str(asset.get("name", "")).lower()
            if name.endswith(".zip") and ("patch" in name or "update" in name or "tankvideo" in name):
                patch_asset = asset
                break
        if not patch_asset and assets:
            for asset in assets:
                if str(asset.get("name", "")).lower().endswith(".zip"):
                    patch_asset = asset
                    break

        download_url = ""
        size_mb = 0.0
        if patch_asset:
            download_url = patch_asset.get("browser_download_url", "")
            size_mb = round(float(patch_asset.get("size", 0)) / (1024 * 1024), 1)
        else:
            download_url = data.get("html_url", f"https://github.com/{self.repo}/releases/latest")

        return {
            "has_update": has_update,
            "current_version": self.current_version,
            "latest_version": tag_name or latest_ver_clean,
            "title": data.get("name", f"Bản cập nhật {tag_name}"),
            "body": data.get("body", "Bản cập nhật cải tiến hiệu năng và tính năng mới."),
            "published_at": data.get("published_at", ""),
            "download_url": download_url,
            "is_direct_zip": bool(patch_asset and download_url.endswith(".zip")),
            "size_mb": size_mb,
            "release_url": data.get("html_url", ""),
        }

    def download_and_install_patch(
        self,
        download_url: str,
        progress_cb: Callable[[int, str], None] | None = None,
    ) -> tuple[bool, str]:
        """Tải bản vá zip và kích hoạt helper script tự động nâng cấp ứng dụng."""
        if not download_url:
            return False, "Không có đường link tải bản cập nhật."

        temp_zip = os.path.join(self.workspace_root, "temp_update.zip")
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except OSError:
                pass

        if progress_cb:
            progress_cb(5, "Đang kết nối tới máy chủ cập nhật...")

        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "TankVideo-AutoUpdater"},
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get("content-length", 0) or 0)
                downloaded = 0
                chunk_size = 1024 * 256  # 256 KB

                with open(temp_zip, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = min(92, int((downloaded / total_size) * 88) + 5)
                            mb = downloaded / (1024 * 1024)
                            total_mb = total_size / (1024 * 1024)
                            if progress_cb:
                                progress_cb(pct, f"Đang tải bản cập nhật: {mb:.1f} / {total_mb:.1f} MB ({pct}%)")
                        else:
                            mb = downloaded / (1024 * 1024)
                            if progress_cb:
                                progress_cb(50, f"Đang tải bản cập nhật: {mb:.1f} MB...")
        except Exception as exc:
            if os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except OSError:
                    pass
            return False, f"Lỗi khi tải bản cập nhật: {exc}"

        if not os.path.exists(temp_zip) or os.path.getsize(temp_zip) < 1024:
            return False, "Tệp cập nhật tải về bị lỗi hoặc không đầy đủ."

        if not zipfile.is_zipfile(temp_zip):
            return False, "Tệp tải về không phải định dạng ZIP hợp lệ."

        if progress_cb:
            progress_cb(96, "Chuẩn bị khởi động lại và áp dụng bản cập nhật...")

        # Tạo helper script bat để ghi đè file sau khi TankVideo.exe đóng
        bat_path = os.path.join(self.workspace_root, "apply_update.bat")
        bat_script = f"""@echo off
chcp 65001 > nul
echo Dang cap nhat TankVideo Studio...
timeout /t 1 /nobreak > nul

:waitloop
tasklist /fi "imagename eq TankVideo.exe" 2>nul | find /i "TankVideo.exe" > nul
if not errorlevel 1 (
    timeout /t 1 /nobreak > nul
    goto waitloop
)

echo Dang giai nen ban cap nhat vao thu muc...
tar -xf "{temp_zip}" -C "{self.workspace_root}"
del "{temp_zip}" 2>nul

echo Khoi dong lai TankVideo Studio...
start "" "{os.path.join(self.workspace_root, 'TankVideo.exe')}"
del "%~f0" 2>nul
exit
"""
        try:
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_script)
        except Exception as exc:
            return False, f"Không thể tạo tệp cài đặt cập nhật: {exc}"

        # Chạy file .bat độc lập và thoát app hiện tại
        try:
            from runtime_paths import subprocess_hidden_kwargs
            subprocess.Popen(
                ["cmd.exe", "/c", bat_path],
                cwd=self.workspace_root,
                creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0,
                close_fds=True,
            )
        except Exception as exc:
            return False, f"Không thể kích hoạt trình cập nhật: {exc}"

        return True, "Cập nhật thành công! Đang khởi động lại ứng dụng..."
