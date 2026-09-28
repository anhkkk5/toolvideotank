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

from app.version import APP_VERSION, GITHUB_REPO, UPDATE_CONFIG_URL


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

    def check_for_updates(self, timeout: float = 12) -> dict[str, Any]:
        """Kiểm tra bản cập nhật mới nhất từ cấu hình phát hành (Gist / Server)."""
        url = f"{UPDATE_CONFIG_URL}?t={int(time.time())}" if UPDATE_CONFIG_URL else f"https://api.github.com/repos/{self.repo}/releases/latest"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "TankVideo-AutoUpdater",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return {"has_update": False, "error": f"HTTP {resp.status}"}
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return {"has_update": False, "error": str(exc)}

        latest_version = str(data.get("version") or data.get("tag_name") or "").strip()
        latest_ver_clean = latest_version.lstrip("vV")
        current_ver_clean = self.current_version.lstrip("vV")

        has_update = parse_version_tuple(latest_ver_clean) > parse_version_tuple(current_ver_clean)

        patch_url = str(data.get("patch_url") or "").strip()
        download_url = str(data.get("download_url") or "").strip()
        if not download_url:
            assets = list(data.get("assets") or [])
            for asset in assets:
                if str(asset.get("name", "")).lower().endswith(".zip"):
                    download_url = asset.get("browser_download_url", "")
                    break
            if not download_url:
                download_url = data.get("html_url", "")

        # Ưu tiên patch_url cho chế độ 1-Click Auto Update
        target_download = patch_url or download_url
        is_direct = bool(
            patch_url
            or target_download.endswith(".zip")
            or "drive.google.com" in target_download
            or "drive.usercontent.google.com" in target_download
        )

        size_mb = float(data.get("size_mb", 0) or 0)
        title = data.get("name") or data.get("title") or f"Bản cập nhật v{latest_version}"
        body = data.get("notes") or data.get("body") or "Bản cập nhật tối ưu hiệu năng và tính năng mới."

        return {
            "has_update": has_update,
            "current_version": self.current_version,
            "latest_version": latest_version or latest_ver_clean,
            "title": title,
            "body": body,
            "download_url": target_download,
            "patch_url": patch_url,
            "is_direct_zip": is_direct,
            "size_mb": size_mb,
            "release_url": download_url,
        }

    def _open_download_stream(self, url: str):
        """Mở luồng tải dữ liệu hỗ trợ cả link trực tiếp và link Google Drive tự động."""
        target_url = str(url or "").strip()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        if "drive.google.com" in target_url or "drive.usercontent.google.com" in target_url:
            m = re.search(r"/d/([a-zA-Z0-9_-]+)", target_url) or re.search(r"id=([a-zA-Z0-9_-]+)", target_url)
            if m:
                file_id = m.group(1)
                init_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                req = urllib.request.Request(init_url, headers=headers)
                resp = urllib.request.urlopen(req, timeout=30)
                content_type = str(resp.headers.get("content-type", "")).lower()

                # Nếu Google trả về trang cảnh báo virus file lớn, bóc tách form để tải trực tiếp
                if "text/html" in content_type:
                    html = resp.read().decode("utf-8", errors="ignore")
                    uuid_match = re.search(r'name="uuid"\s+value="([^"]+)"', html)
                    confirm_match = re.search(r'name="confirm"\s+value="([^"]+)"', html)
                    uuid_val = uuid_match.group(1) if uuid_match else ""
                    confirm_val = confirm_match.group(1) if confirm_match else "t"
                    if uuid_val:
                        dl_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm={confirm_val}&uuid={uuid_val}"
                        req2 = urllib.request.Request(dl_url, headers=headers)
                        return urllib.request.urlopen(req2, timeout=60)
                return resp

        req = urllib.request.Request(target_url, headers=headers)
        return urllib.request.urlopen(req, timeout=30)

    def download_and_install_patch(
        self,
        download_url: str,
        progress_cb: Callable[[int, str], None] | None = None,
    ) -> tuple[bool, str]:
        """Tải bản vá zip và thay thế exe trực tiếp (không cần bat script phức tạp)."""
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

        try:
            with self._open_download_stream(download_url) as resp:
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
                            pct = min(88, int((downloaded / total_size) * 84) + 5)
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
            progress_cb(90, "Đang giải nén và áp dụng bản cập nhật...")

        # === PHƯƠNG PHÁP MỚI: Giải nén + đổi tên TRỰC TIẾP bằng Python ===
        # Windows cho phép RENAME file exe đang chạy (nhưng không cho xóa/ghi đè).
        # Quy trình: rename exe cũ → .old, giải nén exe mới, chạy bat đơn giản chỉ để restart.
        target_exe = os.path.join(self.workspace_root, "TankVideo.exe")
        target_old = os.path.join(self.workspace_root, "TankVideo.exe.old")
        target_new = os.path.join(self.workspace_root, "TankVideo_new.exe")
        update_log = os.path.join(self.workspace_root, "update.log")

        log_lines = []
        def _log(msg: str):
            log_lines.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

        _log("Bat dau cap nhat...")

        # Bước 1: Giải nén TankVideo.exe + _internal/ từ zip
        try:
            with zipfile.ZipFile(temp_zip, "r") as zf:
                all_names = zf.namelist()

                # 1a. Giải nén TankVideo.exe ra file tạm TankVideo_new.exe
                exe_names = [n for n in all_names if n.lower().endswith("tankvideo.exe")]
                if not exe_names:
                    _log("LOI: Khong tim thay TankVideo.exe trong file zip!")
                    return False, "Không tìm thấy TankVideo.exe trong bản cập nhật."

                exe_in_zip = exe_names[0]
                _log(f"Giai nen {exe_in_zip} tu zip...")

                # Đọc dữ liệu và ghi ra file mới
                data = zf.read(exe_in_zip)
                with open(target_new, "wb") as f:
                    f.write(data)
                _log(f"Da giai nen thanh cong: {len(data)} bytes")

                # 1b. Giải nén tất cả file _internal/ (Playwright driver, greenlet, v.v.)
                internal_entries = [n for n in all_names if n.startswith("_internal/") and not n.endswith("/")]
                if internal_entries:
                    _log(f"Giai nen {len(internal_entries)} file _internal/ bo sung...")
                    for entry in internal_entries:
                        dest_path = os.path.join(self.workspace_root, entry)
                        dest_dir = os.path.dirname(dest_path)
                        os.makedirs(dest_dir, exist_ok=True)
                        entry_data = zf.read(entry)
                        with open(dest_path, "wb") as f:
                            f.write(entry_data)
                    _log(f"Da giai nen {len(internal_entries)} file _internal/ thanh cong")
        except Exception as exc:
            _log(f"LOI giai nen: {exc}")
            self._write_log(update_log, log_lines)
            return False, f"Lỗi khi giải nén bản cập nhật: {exc}"

        # Bước 2: Rename exe đang chạy → .old (Windows cho phép!)
        try:
            if os.path.exists(target_old):
                try:
                    os.remove(target_old)
                except OSError:
                    pass

            if os.path.exists(target_exe):
                os.rename(target_exe, target_old)
                _log("Da doi ten TankVideo.exe -> TankVideo.exe.old")
        except Exception as exc:
            _log(f"LOI doi ten exe cu: {exc}")
            self._write_log(update_log, log_lines)
            # Dọn file mới
            try:
                os.remove(target_new)
            except OSError:
                pass
            return False, f"Không thể đổi tên file cũ: {exc}"

        # Bước 3: Rename file mới → TankVideo.exe
        try:
            os.rename(target_new, target_exe)
            _log("Da doi ten TankVideo_new.exe -> TankVideo.exe")
        except Exception as exc:
            _log(f"LOI doi ten exe moi: {exc}")
            # Khôi phục file cũ
            try:
                if os.path.exists(target_old):
                    os.rename(target_old, target_exe)
            except OSError:
                pass
            self._write_log(update_log, log_lines)
            return False, f"Không thể áp dụng file mới: {exc}"

        # Bước 4: Dọn dẹp
        try:
            os.remove(temp_zip)
        except OSError:
            pass
        try:
            if os.path.exists(target_old):
                os.remove(target_old)
        except OSError:
            pass  # File cũ đang chạy, sẽ bị xóa sau restart

        if progress_cb:
            progress_cb(98, "Cập nhật thành công! Đang khởi động lại...")

        _log("Cap nhat hoan tat! Dang khoi dong lai...")
        self._write_log(update_log, log_lines)

        # Bước 5: Tạo bat script ĐƠN GIẢN chỉ để restart app (không extract gì cả)
        bat_path = os.path.join(self.workspace_root, "apply_update.bat")
        bat_script = f"""@echo off
chcp 65001 > nul
ping 127.0.0.1 -n 3 > nul
if exist "{target_old}" del /f /q "{target_old}" >nul 2>&1
start /d "{self.workspace_root}" "" "{target_exe}"
(goto) 2>nul & del "%~f0" >nul 2>&1
exit
"""
        try:
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_script)
            kwargs: dict[str, Any] = {"cwd": self.workspace_root, "close_fds": True}
            if sys.platform == "win32":
                kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(["cmd.exe", "/c", bat_path], **kwargs)
        except Exception as exc:
            _log(f"LOI khoi dong lai: {exc}")
            self._write_log(update_log, log_lines)
            return True, f"Cập nhật xong! Vui lòng mở lại ứng dụng thủ công."

        return True, "Cập nhật thành công! Đang khởi động lại ứng dụng..."

    @staticmethod
    def _write_log(log_path: str, lines: list[str]):
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass

