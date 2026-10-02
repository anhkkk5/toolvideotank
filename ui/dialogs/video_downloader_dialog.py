"""Video Downloader Dialog – Giao diện Quét & Tải Video Đa Nền Tảng PRO NATIVE.

Thiết kế Cyber Engine UI hiện đại theo phong cách Quét Video Pro:
- Cột trái: Cấu hình quét (Chọn nền tảng, Link/User ID, Chế độ quét, Cookie ATP, Proxy, Thư mục lưu)
- Cột phải: Bảng kết quả quét (Ảnh bìa, ID, Tiêu đề, Lượt thích, Lượt xem, Tác giả, Trạng thái)
- Chức năng: Quét kênh/video trước -> Lọc / Chọn video theo ý muốn -> Bấm Tải các video đã chọn sau.
"""

import os
import sys
import threading
import time
import json
import csv
import urllib.request
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, Signal, QTimer, QThread, QObject, QByteArray, QSize, QSettings
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
)

from app.services.cookie_storage_service import (
    get_saved_douyin_cookies,
    save_douyin_cookies,
    clear_saved_douyin_cookies,
    get_douyin_cookie_summary,
    save_platform_cookies,
    get_saved_platform_cookies,
    get_platform_cookie_summary,
    clear_saved_platform_cookies,
    detect_cookie_platform,
    PLATFORM_DISPLAY_NAMES,
    PLATFORM_DOMAINS,
    _get_setting,
)
from app.services.browser_profile_service import get_installed_browsers_with_profiles
from ui.dialogs.browser_profile_dialog import BrowserProfileDialog, CookieExpiredDialog
from app.services.hongguo_downloader_service import (
    HongguoScanWorker,
    HongguoDownloadWorker,
    parse_hongguo_id,
)


def _sep_line(parent=None):
    line = QFrame(parent)
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("background: #1e293b; max-height: 1px; margin: 4px 0;")
    return line


from concurrent.futures import ThreadPoolExecutor, as_completed

_THUMBNAIL_CACHE: Dict[str, QPixmap] = {}


# ====================================================================== #
#  High-Speed Concurrent Thumbnail Loader Thread                         #
# ====================================================================== #
class ThumbnailLoader(QThread):
    thumbnail_loaded = Signal(int, QPixmap)  # row_idx, pixmap

    def __init__(self, items_to_load: List[tuple], parent=None):
        """items_to_load: list of (row_idx, image_url)"""
        super().__init__(parent)
        self.items = items_to_load
        self._is_running = True
        self._executor = None

    def _fetch_one(self, row_idx: int, img_url: str):
        if not self._is_running or not img_url:
            return None
        global _THUMBNAIL_CACHE
        if img_url in _THUMBNAIL_CACHE:
            return row_idx, _THUMBNAIL_CACHE[img_url]

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            if "hdslb.com" in img_url or "bilibili.com" in img_url:
                headers["Referer"] = "https://www.bilibili.com/"
            elif "tiktok.com" in img_url or "tiktokcdn.com" in img_url:
                headers["Referer"] = "https://www.tiktok.com/"
            elif "youtube.com" in img_url or "ytimg.com" in img_url:
                headers["Referer"] = "https://www.youtube.com/"
            elif "kuaishou" in img_url or "kwaicdn" in img_url:
                headers["Referer"] = "https://www.kuaishou.com/"
            elif "facebook.com" in img_url or "fbcdn.net" in img_url or "fna.fbcdn" in img_url:
                headers["Referer"] = "https://www.facebook.com/"
            else:
                headers["Referer"] = "https://www.douyin.com/"

            req = urllib.request.Request(img_url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                image = QImage()
                if image.loadFromData(data):
                    pixmap = QPixmap.fromImage(image).scaled(
                        72, 54, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                    )
                    cropped = pixmap.copy(
                        (pixmap.width() - 72) // 2,
                        (pixmap.height() - 54) // 2,
                        72, 54
                    )
                    _THUMBNAIL_CACHE[img_url] = cropped
                    return row_idx, cropped
        except Exception:
            pass
        return None

    def run(self):
        # 1. Immediately emit cached thumbnails
        uncached = []
        for row_idx, img_url in self.items:
            if img_url in _THUMBNAIL_CACHE:
                self.thumbnail_loaded.emit(row_idx, _THUMBNAIL_CACHE[img_url])
            else:
                uncached.append((row_idx, img_url))

        if not uncached:
            return

        # 2. Concurrently fetch remaining thumbnails with 8 workers
        with ThreadPoolExecutor(max_workers=8) as executor:
            self._executor = executor
            futures = [executor.submit(self._fetch_one, r, u) for r, u in uncached]
            for f in as_completed(futures):
                if not self._is_running:
                    break
                try:
                    res = f.result()
                    if res and self._is_running:
                        r_idx, pix = res
                        self.thumbnail_loaded.emit(r_idx, pix)
                except Exception:
                    pass

    def stop(self):
        self._is_running = False
        if self._executor:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass


# ====================================================================== #
#  Background Scanner Worker Thread                                       #
# ====================================================================== #
class ScanWorker(QThread):
    sig_progress = Signal(str, int)       # message, count
    sig_video_found = Signal(dict)        # video dict
    sig_finished = Signal(list, dict, str) # videos, channel_info, error

    def __init__(
        self,
        platform: str,
        url: str,
        mode: str,
        browser_id: str = "chrome",
        profile_id: Optional[str] = None,
        browser_exe: Optional[str] = None,
        max_count: int = 0,  # 0: Không giới hạn (quét toàn bộ kênh)
        parent=None,
    ):
        super().__init__(parent)
        self.platform = platform
        self.url = url
        self.mode = mode
        self.browser_id = browser_id
        self.profile_id = profile_id
        self.browser_exe = browser_exe
        self.max_count = max_count
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        videos = []
        channel_info = {"name": "", "total": 0}
        err = ""

        try:
            if self.platform == "douyin":
                from app.services.douyin_channel_scanner import scan_douyin_channel
                videos, channel_info = scan_douyin_channel(
                    channel_url=self.url,
                    max_videos=self.max_count,
                    browser_id=self.browser_id,
                    profile_id=self.profile_id,
                    browser_exe_path=self.browser_exe,
                    progress_cb=lambda msg, cnt: self.sig_progress.emit(msg, cnt),
                    video_found_cb=lambda item: self.sig_video_found.emit(item),
                    is_cancelled_cb=lambda: self._is_cancelled,
                )
                if channel_info.get("error_type") == "COOKIE_EXPIRED":
                    err = "COOKIE_EXPIRED"
            elif self.platform == "bilibili" or "bilibili.com" in self.url or "b23.tv" in self.url:
                from app.services.bilibili_channel_scanner import scan_bilibili
                videos, channel_info, err = scan_bilibili(
                    url=self.url,
                    max_videos=self.max_count,
                    browser_id=self.browser_id,
                    profile_id=self.profile_id,
                    browser_exe_path=self.browser_exe,
                    progress_cb=lambda msg, cnt: self.sig_progress.emit(msg, cnt),
                    video_found_cb=lambda item: self.sig_video_found.emit(item),
                    is_cancelled_cb=lambda: self._is_cancelled,
                )
            elif self.platform in ("facebook", "reels") or "facebook.com" in self.url or "fb.watch" in self.url:
                from app.services.facebook_channel_scanner import scan_facebook_channel
                mode = "reels" if self.platform == "reels" or "reels" in self.url else "videos"
                videos, channel_info, err = scan_facebook_channel(
                    url=self.url,
                    max_videos=self.max_count,
                    browser_id=self.browser_id,
                    profile_id=self.profile_id,
                    browser_exe_path=self.browser_exe,
                    progress_cb=lambda msg, cnt: self.sig_progress.emit(msg, cnt),
                    video_found_cb=lambda item: self.sig_video_found.emit(item),
                    is_cancelled_cb=lambda: self._is_cancelled,
                    mode=mode,
                )
            elif self.platform == "xiaohongshu" or "xiaohongshu.com" in self.url or "rednote.com" in self.url or "xhslink.com" in self.url:
                from app.services.rednote_channel_scanner import scan_rednote
                videos, channel_info = scan_rednote(
                    url=self.url,
                    max_videos=self.max_count,
                    browser_id=self.browser_id,
                    profile_id=self.profile_id,
                    browser_exe_path=self.browser_exe,
                    progress_cb=lambda msg, cnt: self.sig_progress.emit(msg, cnt),
                    video_found_cb=lambda item: self.sig_video_found.emit(item),
                    is_cancelled_cb=lambda: self._is_cancelled,
                )
            else:
                # Fallback via yt-dlp for YouTube, TikTok, etc.
                import yt_dlp
                self.sig_progress.emit(f"Đang phân tích liên kết {self.platform.upper()}...", 0)

                scan_url = self.url.strip()
                if self.platform == "tiktok" and not scan_url.startswith("http"):
                    # Auto format username to full TikTok channel URL
                    clean_user = scan_url.lstrip("@")
                    scan_url = f"https://www.tiktok.com/@{clean_user}"

                ydl_opts = {
                    "quiet": True,
                    "extract_flat": True,
                    "skip_download": True,
                    "no_warnings": True,
                    "extractor_args": {"tiktok": ["app_version=0"]},
                }
                if self.max_count > 0 and self.max_count < 99999:
                    ydl_opts["playlistend"] = self.max_count

                # Attach saved cookies for this platform if available
                from app.services.cookie_storage_service import get_saved_platform_cookies
                _, netscape_path, ua = get_saved_platform_cookies(self.platform)
                if netscape_path and os.path.exists(netscape_path):
                    ydl_opts["cookiefile"] = netscape_path
                if ua:
                    ydl_opts["http_headers"] = {"User-Agent": ua}

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(scan_url, download=False)
                    if not info:
                        err = "Không tìm thấy dữ liệu từ liên kết đã nhập."
                    else:
                        entries = info.get("entries") or [info]
                        ch_name = info.get("uploader") or info.get("channel") or info.get("title") or "Unknown"
                        channel_info["name"] = ch_name
                        is_unlimited = (self.max_count <= 0 or self.max_count >= 99999)
                        for i, e in enumerate(entries):
                            if self._is_cancelled:
                                break
                            if not is_unlimited and len(videos) >= self.max_count:
                                break
                            vid = str(e.get("id") or (i + 1))
                            v_url = e.get("url") or e.get("webpage_url") or scan_url

                            # Robust thumbnail extraction: check both 'thumbnail' and 'thumbnails'
                            cover = e.get("thumbnail") or ""
                            if not cover and e.get("thumbnails"):
                                for t in e["thumbnails"]:
                                    if isinstance(t, dict) and t.get("url"):
                                        cover = t["url"]
                                        if t.get("id") in ("cover", "originCover", "0"):
                                            break

                            # Clean title
                            raw_title = e.get("title") or e.get("description") or f"Video {i+1}"
                            clean_title = " ".join(str(raw_title).split())

                            v_entry = {
                                "id": vid,
                                "title": clean_title,
                                "url": v_url,
                                "direct_url": "",
                                "cover": cover,
                                "likes": e.get("like_count") or 0,
                                "views": e.get("view_count") or 0,
                                "author": e.get("uploader") or ch_name,
                                "duration": e.get("duration") or 0,
                                "status": "Chờ tải",
                            }
                            videos.append(v_entry)
                            self.sig_video_found.emit(v_entry)
                            self.sig_progress.emit(f"Đã tìm thấy {len(videos)} video...", len(videos))
                        channel_info["total"] = len(videos)
        except Exception as e:
            err = str(e)

        self.sig_finished.emit(videos, channel_info, err)


# ====================================================================== #
#  Background Batch Downloader Thread                                     #
# ====================================================================== #
class DownloadWorker(QThread):
    sig_row_status = Signal(int, str)      # row_idx, status_text
    sig_progress = Signal(int, int, str)   # current, total, message
    sig_finished = Signal(int, int, bool)  # success_count, total, was_cancelled

    def __init__(
        self,
        selected_items: List[tuple],
        output_dir: str,
        auto_delogo_bilibili: bool = False,
        auto_delogo_watermark: bool = False,
        parent=None,
    ):
        """selected_items: list of (row_idx, video_dict)"""
        super().__init__(parent)
        self.selected_items = selected_items
        self.output_dir = output_dir
        self.auto_delogo_bilibili = auto_delogo_bilibili
        self.auto_delogo_watermark = auto_delogo_watermark
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def _apply_delogo_cleanup(self, video_path: str, delogo_bili: bool = True, delogo_wm: bool = True) -> bool:
        """Khử sạch logo Bilibili và watermark bản quyền trên file video vừa tải về."""
        try:
            if not video_path or not os.path.isfile(video_path):
                return False
            if not delogo_bili and not delogo_wm:
                return False

            from app.services.video_export_service import (
                _resolve_ffmpeg,
                probe_video_dimensions,
                build_delogo_filters,
            )
            ffmpeg = _resolve_ffmpeg()
            vid_w, vid_h = probe_video_dimensions(video_path)

            filters, out_v = build_delogo_filters(
                vid_w=vid_w,
                vid_h=vid_h,
                delogo_bilibili=delogo_bili,
                delogo_watermark=delogo_wm,
                current_v="0:v",
            )
            if not filters:
                return False

            dir_name = os.path.dirname(video_path)
            base_name, ext = os.path.splitext(os.path.basename(video_path))
            temp_clean_path = os.path.join(dir_name, f"{base_name}_delogo_temp{ext}")

            cmd = [
                ffmpeg, "-y",
                "-i", video_path,
                "-filter_complex", ";\n".join(filters),
                "-map", f"[{out_v}]",
                "-map", "0:a:0?",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                temp_clean_path,
            ]
            import subprocess
            kwargs = {"capture_output": True}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            proc = subprocess.run(cmd, **kwargs)
            if proc.returncode == 0 and os.path.isfile(temp_clean_path) and os.path.getsize(temp_clean_path) > 10240:
                try:
                    os.replace(temp_clean_path, video_path)
                except Exception:
                    os.remove(video_path)
                    os.rename(temp_clean_path, video_path)
                print(f"[DownloadWorker] Delogo cleanup succeeded for: {os.path.basename(video_path)}")
                return True
            else:
                if os.path.isfile(temp_clean_path):
                    try:
                        os.remove(temp_clean_path)
                    except Exception:
                        pass
        except Exception as exc:
            print(f"[DownloadWorker] Delogo cleanup notice: {exc}")
        return False

    def run(self):
        os.makedirs(self.output_dir, exist_ok=True)
        total = len(self.selected_items)
        success = 0

        # Load Douyin cookies and user agent
        custom_cookies, _, ua = get_saved_douyin_cookies()
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in custom_cookies) if custom_cookies else ""
        user_agent = ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        for idx, (row_idx, v) in enumerate(self.selected_items):
            if self._is_cancelled:
                self.sig_row_status.emit(row_idx, "⏹️ Đã dừng")
                self.sig_progress.emit(idx, total, "Đã dừng tải video.")
                break

            title = v.get("title") or f"video_{v.get('id', idx+1)}"
            clean_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:60] or f"video_{v.get('id')}"
            out_path = os.path.join(self.output_dir, f"{clean_title}.mp4")

            self.sig_row_status.emit(row_idx, "⏳ Đang tải...")
            self.sig_progress.emit(idx + 1, total, f"Đang tải {idx+1}/{total}: {clean_title}")

            downloaded = False
            direct_url = v.get("direct_url")

            # Try direct CDN stream download first
            if direct_url:
                try:
                    req = urllib.request.Request(
                        direct_url,
                        headers={
                            "User-Agent": user_agent,
                            "Referer": "https://www.douyin.com/",
                            "Cookie": cookie_header,
                        }
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp, open(out_path, "wb") as f_out:
                        while True:
                            if self._is_cancelled:
                                break
                            chunk = resp.read(64 * 1024)
                            if not chunk:
                                break
                            f_out.write(chunk)

                    if self._is_cancelled:
                        if os.path.exists(out_path):
                            try:
                                os.remove(out_path)
                            except Exception:
                                pass
                        self.sig_row_status.emit(row_idx, "⏹️ Đã hủy")
                        break

                    if os.path.exists(out_path) and os.path.getsize(out_path) > 10240:
                        downloaded = True
                except Exception:
                    downloaded = False

            # Fallback to VideoDownloaderService if not cancelled
            if not downloaded and not self._is_cancelled:
                try:
                    from app.services.video_downloader_service import VideoDownloaderService
                    svc = VideoDownloaderService(output_root=self.output_dir)
                    res = svc.download_single(
                        v.get("url"),
                        self.output_dir,
                        auto_delogo_bilibili=False,
                        auto_delogo_watermark=False,
                    )
                    if res.get("success"):
                        downloaded = True
                        if res.get("files") and len(res.get("files")) > 0:
                            f_cand = res.get("files")[0]
                            if os.path.isfile(f_cand):
                                out_path = f_cand
                except Exception:
                    downloaded = False

            if self._is_cancelled:
                if os.path.exists(out_path):
                    try:
                        os.remove(out_path)
                    except Exception:
                        pass
                self.sig_row_status.emit(row_idx, "⏹️ Đã hủy")
                break

            if downloaded:
                actual_file = out_path if (os.path.exists(out_path) and os.path.getsize(out_path) > 10240) else None
                if not actual_file and os.path.isdir(self.output_dir):
                    for f in os.listdir(self.output_dir):
                        if f.endswith(".mp4") and clean_title[:20].lower() in f.lower():
                            fp = os.path.join(self.output_dir, f)
                            if os.path.getsize(fp) > 10240:
                                actual_file = fp
                                break

                # Khử Logo Bilibili & Watermark nếu được bật
                v_url = (v.get("url") or "") + " " + (v.get("webpage_url") or "") + " " + (v.get("id") or "")
                is_bilibili = (
                    "bilibili" in v_url.lower()
                    or "b23.tv" in v_url.lower()
                    or v.get("platform") == "bilibili"
                    or (hasattr(self, "platform") and self.platform == "bilibili")
                )

                delogo_bili = self.auto_delogo_bilibili and (is_bilibili or not v.get("platform"))
                delogo_wm = self.auto_delogo_watermark and (is_bilibili or not v.get("platform"))

                did_delogo = False
                if actual_file and (delogo_bili or delogo_wm):
                    self.sig_row_status.emit(row_idx, "🧹 Đang xóa logo...")
                    did_delogo = self._apply_delogo_cleanup(
                        actual_file,
                        delogo_bili=delogo_bili,
                        delogo_wm=delogo_wm,
                    )

                success += 1
                status_msg = "✅ Hoàn thành (Đã xóa logo)" if did_delogo else "✅ Hoàn thành"
                self.sig_row_status.emit(row_idx, status_msg)
            else:
                self.sig_row_status.emit(row_idx, "❌ Lỗi tải")

            time.sleep(0.15)

        self.sig_finished.emit(success, total, self._is_cancelled)


# ====================================================================== #
#  Checkmark Icon Path Helper                                            #
# ====================================================================== #
_CHECK_ICON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "assets", "icons", "check_white.svg")
).replace("\\", "/")

if not os.path.exists(_CHECK_ICON_PATH):
    try:
        os.makedirs(os.path.dirname(_CHECK_ICON_PATH), exist_ok=True)
        with open(_CHECK_ICON_PATH, "w", encoding="utf-8") as f:
            f.write(
                '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" '
                'fill="none" stroke="#ffffff" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">'
                '<polyline points="20 6 9 17 4 12"></polyline></svg>'
            )
    except Exception:
        pass


# ====================================================================== #
#  Main Video Downloader Dialog (TankVideo Pro Native Style)             #
# ====================================================================== #
class VideoDownloaderDialog(QDialog):
    """Giao diện Quét & Bóc Tách Video Đa Nền Tảng chuẩn TankVideo Pro Native."""

    sig_hg_cover_ready = Signal(bytes)

    # Colors - TankVideo Theme
    _PRIMARY = "#ff7b1a"         # Flame Orange
    _PRIMARY_HOVER = "#ff9d42"   # Bright Orange Hover
    _PRIMARY_DARK = "#ea580c"    # Deep Orange
    _PRIMARY_BG = "#2a1608"      # Orange tint bg
    _ACCENT_BLUE = "#38bdf8"     # Sky Blue accent (TankVideo secondary)
    _ACCENT_BLUE_HOVER = "#0ea5e9"
    _BG = "#080c14"              # Deep dark navy window background
    _CARD = "#0f172a"            # Slate navy card background
    _CARD_BORDER = "#1e293b"     # Slate border
    _CARD_HOVER = "#162238"      # Card hover
    _INPUT_BG = "#0a0f1d"        # Input background
    _GREEN = "#10b981"           # Success green
    _RED = "#ef4444"             # Danger red
    _TEXT = "#f8fafc"            # Primary text
    _TEXT_MUTED = "#94a3b8"      # Secondary muted text

    def __init__(self, parent=None, workspace_root: str = ""):
        super().__init__(parent)
        self._workspace_root = workspace_root
        self._scan_worker = None
        self._download_worker = None
        self._thumb_worker = None
        self.sig_hg_cover_ready.connect(self._apply_hg_cover_data)

        # State
        self._selected_platform = "douyin"
        self._raw_videos: List[Dict[str, Any]] = []
        self._filtered_indices: List[int] = []

        # Hongguo Drama State
        self._hg_scan_worker = None
        self._hg_download_worker = None
        self._hg_drama_info = None
        self._hg_ep_buttons = {}
        self._hg_selected_eps = set()
        self._hg_ep_data = {}

        # Browser & Profile Selection State
        self._settings = QSettings("TankVideo", "VideoDownloader")
        self._selected_browser_id = self._settings.value("browser_id", "chrome")
        self._selected_browser_name = self._settings.value("browser_name", "Google Chrome")
        self._selected_browser_exe = self._settings.value("browser_exe", "")
        self._selected_profile_id = self._settings.value("profile_id", "Default")
        self._selected_profile_name = self._settings.value("profile_name", "Mặc định")
        self._remember_browser = self._settings.value("remember_browser", False, type=bool)

        self.setWindowTitle("⚡ TANKVIDEO – QUÉT & TẢI VIDEO PRO NATIVE")
        self.setMinimumSize(1150, 780)
        self.resize(1280, 860)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {self._BG};
                color: {self._TEXT};
            }}
            QWidget {{
                color: {self._TEXT};
                font-family: "Segoe UI", "SF Pro Display", "Microsoft YaHei", "Arial", sans-serif;
            }}
            QScrollBar:vertical {{
                background: #0d1321; width: 8px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #1e293b; min-height: 20px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self._PRIMARY};
            }}
        """)

        self._build_ui()
        self._refresh_cookie_status()
        self._update_browser_info_label()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "_reposition_header_cb"):
            QTimer.singleShot(60, self._reposition_header_cb)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_reposition_header_cb"):
            self._reposition_header_cb()

    # ================================================================== #
    #  UI Layout Construction                                            #
    # ================================================================== #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # ---- TOP HEADER BAR ----
        header = QFrame(self)
        header.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 10px;
                padding: 4px 8px;
            }}
        """)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(14, 8, 14, 8)
        h_layout.setSpacing(12)

        logo_box = QLabel("⚡")
        logo_box.setFixedSize(38, 38)
        logo_box.setAlignment(Qt.AlignCenter)
        logo_box.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {self._PRIMARY}, stop:1 {self._PRIMARY_DARK});
            border-radius: 8px; font-size: 20px; color: white;
        """)
        h_layout.addWidget(logo_box)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        t_label = QLabel()
        t_label.setText(
            "<span style='color:#f8fafc; font-size:16px; font-weight:900; letter-spacing:0.5px;'>TANK</span>"
            f"<span style='color:{self._PRIMARY}; font-size:16px; font-weight:900; letter-spacing:0.5px;'>VIDEO</span> "
            "<span style='color:#475569; font-size:14px; font-weight:700;'>|</span> "
            "<span style='color:#cbd5e1; font-size:14px; font-weight:800; letter-spacing:0.3px;'>QUÉT VIDEO PRO NATIVE</span>"
        )
        top_row.addWidget(t_label)

        badge_vip = QLabel("VIP PRO")
        badge_vip.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._PRIMARY}, stop:1 {self._PRIMARY_DARK});
            color: white; font-size: 10px; font-weight: 800; padding: 2px 7px; border-radius: 4px;
        """)
        top_row.addWidget(badge_vip)
        top_row.addStretch()
        title_col.addLayout(top_row)

        sub_label = QLabel("Hệ Thống Quét & Bóc Tách Video Đa Nền Tảng Tự Động (Cyber Engine v2.0)")
        sub_label.setStyleSheet(f"font-size: 11px; color: {self._TEXT_MUTED};")
        title_col.addWidget(sub_label)
        h_layout.addLayout(title_col, 1)

        # Right status badge
        self.header_status_badge = QLabel("⚡ Sẵn Sàng")
        self.header_status_badge.setStyleSheet(f"""
            background: #201309; border: 1px solid {self._PRIMARY};
            color: {self._PRIMARY_HOVER}; font-size: 11px; font-weight: 700;
            padding: 6px 14px; border-radius: 6px;
        """)
        h_layout.addWidget(self.header_status_badge)
        root.addWidget(header)

        # ---- MAIN 2-COLUMN SPLITTER ----
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; width: 10px; }")

        # ============================================================== #
        #  LEFT SIDEBAR (Configuration) - Width 350px                    #
        # ============================================================== #
        left_widget = QWidget(self)
        left_widget.setFixedWidth(350)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # Scroll area for left sidebar so it never overflows on small screens
        left_scroll = QScrollArea(self)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setStyleSheet("background: transparent;")

        left_content = QWidget()
        left_content_layout = QVBoxLayout(left_content)
        left_content_layout.setContentsMargins(0, 0, 6, 0)
        left_content_layout.setSpacing(10)

        # --- Card 1: Chọn Nền Tảng ---
        card_platforms = self._create_card("CHỌN NỀN TẢNG (12 PLATFORMS)")
        plat_grid = QGridLayout()
        plat_grid.setSpacing(6)

        self.plat_btns = {}
        platform_list = [
            ("douyin", "📱 Douyin"),
            ("tiktok", "🎵 TikTok"),
            ("youtube", "🎬 YouTube"),
            ("facebook", "📘 FB Video"),
            ("reels", "📽️ FB Reels"),
            ("kuaishou", "⚡ Kuaishou"),
            ("bilibili", "📺 Bilibili"),
            ("xiaohongshu", "📕 RED/XHS"),
            ("hongguo", "🍎 Hongguo (红果)"),
        ]
        for i, (p_id, p_name) in enumerate(platform_list):
            btn = QPushButton(p_name)
            btn.setCheckable(True)
            btn.setChecked(p_id == "douyin")
            btn.setStyleSheet(self._platform_btn_style(p_id == "douyin"))
            btn.clicked.connect(lambda checked, pid=p_id: self._on_platform_selected(pid))
            if p_id == "hongguo":
                plat_grid.addWidget(btn, 4, 0, 1, 2)
            else:
                plat_grid.addWidget(btn, i // 2, i % 2)
            self.plat_btns[p_id] = btn

        card_platforms.layout().addLayout(plat_grid)
        left_content_layout.addWidget(card_platforms)

        # --- Card 2: Cấu Hình Quét Video ---
        self.card_config = self._create_card("CẤU HÌNH QUÉT VIDEO (DOUYIN)")
        c_layout = self.card_config.layout()

        lbl_input = QLabel("📌 NHẬP LINK / USER ID / HASHTAG MUỐN QUÉT:")
        lbl_input.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {self._PRIMARY};")
        c_layout.addWidget(lbl_input)

        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Dán link kênh Douyin (https://www.douyin.com/user/...)...")
        self.url_input.setStyleSheet(self._input_style())
        url_row.addWidget(self.url_input, 1)

        btn_paste_url = QPushButton("📋 Dán")
        btn_paste_url.setFixedSize(54, 34)
        btn_paste_url.setStyleSheet(self._secondary_btn_style())
        btn_paste_url.clicked.connect(self._on_paste_url)
        url_row.addWidget(btn_paste_url)
        c_layout.addLayout(url_row)

        lbl_mode = QLabel("⚙️ CHẾ ĐỘ QUÉT:")
        lbl_mode.setStyleSheet("font-size: 11px; font-weight: 700; color: #cbd5e1; margin-top: 4px;")
        c_layout.addWidget(lbl_mode)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "⚡ Quét Kênh / User Sáng Tạo (Toàn bộ)",
            "🎬 Quét Video Đơn / Nhiều Link",
        ])
        self.mode_combo.setStyleSheet(self._combo_style())
        c_layout.addWidget(self.mode_combo)

        lbl_limit = QLabel("🔢 SỐ LƯỢNG VIDEO QUÉT:")
        lbl_limit.setStyleSheet("font-size: 11px; font-weight: 700; color: #cbd5e1; margin-top: 6px;")
        c_layout.addWidget(lbl_limit)

        limit_row = QHBoxLayout()
        limit_row.setSpacing(6)

        self.limit_combo = QComboBox()
        self.limit_combo.addItem("♾️ Không giới hạn (Quét sạch toàn bộ kênh)", 0)
        self.limit_combo.addItem("50 video mới nhất", 50)
        self.limit_combo.addItem("100 video mới nhất", 100)
        self.limit_combo.addItem("200 video mới nhất", 200)
        self.limit_combo.addItem("500 video mới nhất", 500)
        self.limit_combo.addItem("1000 video mới nhất", 1000)
        self.limit_combo.addItem("⚙️ Tùy chỉnh số lượng...", -1)
        self.limit_combo.setStyleSheet(self._combo_style())
        limit_row.addWidget(self.limit_combo, 1)

        self.custom_limit_spin = QSpinBox()
        self.custom_limit_spin.setRange(1, 99999)
        self.custom_limit_spin.setValue(200)
        self.custom_limit_spin.setSuffix(" video")
        self.custom_limit_spin.setStyleSheet(self._input_style())
        self.custom_limit_spin.setVisible(False)
        limit_row.addWidget(self.custom_limit_spin)
        c_layout.addLayout(limit_row)

        self.limit_combo.currentIndexChanged.connect(
            lambda: self.custom_limit_spin.setVisible(self.limit_combo.currentData() == -1)
        )

        left_content_layout.addWidget(self.card_config)

        # --- Card 2.5: Trình Duyệt & Hồ Sơ Quét (Profiles) ---
        self.card_browser = self._create_card("🖥️ TRÌNH DUYỆT & PROFILE QUÉT")
        b_card_lay = self.card_browser.layout()

        self.lbl_browser_info = QLabel("🌐 Đang tải trình duyệt...")
        self.lbl_browser_info.setStyleSheet("font-size: 11px; color: #cbd5e1; line-height: 1.4;")
        self.lbl_browser_info.setWordWrap(True)
        b_card_lay.addWidget(self.lbl_browser_info)

        btn_change_browser = QPushButton("🔄 Đổi Trình Duyệt / Hồ Sơ")
        btn_change_browser.setStyleSheet(self._secondary_btn_style())
        btn_change_browser.clicked.connect(self._on_change_browser)
        b_card_lay.addWidget(btn_change_browser)

        lbl_browser_hint = QLabel("💡 Quét tự động bằng trình duyệt & profile đang chọn ở trên.")
        lbl_browser_hint.setStyleSheet(f"font-size: 10px; color: {self._TEXT_MUTED}; font-style: italic;")
        lbl_browser_hint.setWordWrap(True)
        b_card_lay.addWidget(lbl_browser_hint)

        left_content_layout.addWidget(self.card_browser)

        # --- Card 3: Cookie & Proxy Nâng Cao ---
        card_cookie = self._create_card("🔑 CẤU HÌNH COOKIE & PROXY (ATP COOKIE)")
        ck_layout = card_cookie.layout()

        self.lbl_cookie_title = QLabel("COOKIE (TÙY CHỌN CHO DOUYIN):")
        self.lbl_cookie_title.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {self._TEXT_MUTED};")
        ck_layout.addWidget(self.lbl_cookie_title)

        self.cookie_input = QTextEdit()
        self.cookie_input.setPlaceholderText("Dán chuỗi ATP Cookie vào đây (ví dụ: =douyin.com;...|User-Agent)...")
        self.cookie_input.setFixedHeight(55)
        self.cookie_input.setStyleSheet(f"""
            QTextEdit {{
                background: {self._INPUT_BG}; border: 1px solid {self._CARD_BORDER};
                border-radius: 6px; color: #e2e8f0; font-size: 10px; font-family: monospace;
            }}
            QTextEdit:focus {{ border-color: {self._PRIMARY}; }}
        """)
        ck_layout.addWidget(self.cookie_input)

        ck_btn_row = QHBoxLayout()
        ck_btn_row.setSpacing(6)
        btn_paste_ck = QPushButton("📋 Dán Nhanh")
        btn_paste_ck.setStyleSheet(self._secondary_btn_style())
        btn_paste_ck.clicked.connect(self._on_paste_cookie)
        ck_btn_row.addWidget(btn_paste_ck)

        btn_save_ck = QPushButton("💾 Lưu Cookie")
        btn_save_ck.setStyleSheet(self._secondary_btn_style())
        btn_save_ck.clicked.connect(self._on_save_cookie)
        ck_btn_row.addWidget(btn_save_ck)

        btn_clear_ck = QPushButton("🗑 Xóa")
        btn_clear_ck.setStyleSheet(self._danger_btn_style())
        btn_clear_ck.clicked.connect(self._on_clear_cookie)
        ck_btn_row.addWidget(btn_clear_ck)
        ck_layout.addLayout(ck_btn_row)

        self.cookie_status_lbl = QLabel("Chưa cấu hình cookie")
        self.cookie_status_lbl.setStyleSheet(f"font-size: 11px; color: {self._TEXT_MUTED};")
        ck_layout.addWidget(self.cookie_status_lbl)

        # Proxy
        lbl_proxy = QLabel("PROXY (HTTP/SOCKS - TÙY CHỌN):")
        lbl_proxy.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {self._TEXT_MUTED}; margin-top: 4px;")
        ck_layout.addWidget(lbl_proxy)

        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("http://user:pass@ip:port")
        self.proxy_input.setStyleSheet(self._input_style())
        ck_layout.addWidget(self.proxy_input)

        # Output folder
        lbl_output = QLabel("📁 THƯ MỤC LƯU VIDEO:")
        lbl_output.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {self._TEXT_MUTED}; margin-top: 4px;")
        ck_layout.addWidget(lbl_output)

        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        default_dl = os.path.join(self._workspace_root or os.getcwd(), "downloads_video")
        self.output_dir_input = QLineEdit(default_dl)
        self.output_dir_input.setStyleSheet(self._input_style())
        out_row.addWidget(self.output_dir_input, 1)

        btn_browse = QPushButton("📁")
        btn_browse.setFixedSize(36, 34)
        btn_browse.setStyleSheet(self._secondary_btn_style())
        btn_browse.clicked.connect(self._on_browse_output)
        out_row.addWidget(btn_browse)
        ck_layout.addLayout(out_row)

        left_content_layout.addWidget(card_cookie)

        # --- Card 4: Tự Động Xóa Logo & Watermark (Delogo AI) ---
        card_delogo = self._create_card("🧹 TỰ ĐỘNG XÓA LOGO & WATERMARK (DELOGO AI)")
        dl_layout = card_delogo.layout()

        self.chk_auto_delogo_bili = QCheckBox("🎯 Tự động xóa Logo Bilibili (Góc trên cùng bên phải)")
        self.chk_auto_delogo_bili.setChecked(False)
        self.chk_auto_delogo_bili.setStyleSheet("color: #ff9d42; font-weight: bold; font-size: 11px;")
        dl_layout.addWidget(self.chk_auto_delogo_bili)

        self.chk_auto_delogo_wm = QCheckBox("🌊 Tự động làm mờ dải Watermark bản quyền (ở dưới)")
        self.chk_auto_delogo_wm.setChecked(False)
        self.chk_auto_delogo_wm.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px;")
        dl_layout.addWidget(self.chk_auto_delogo_wm)

        lbl_delogo_note = QLabel(
            "💡 Chỉ bật khi video gốc thực sự có logo Bilibili hoặc dải chữ watermark cần xóa, "
            "tránh chèn dải che mờ không cần thiết lên video."
        )
        lbl_delogo_note.setWordWrap(True)
        lbl_delogo_note.setStyleSheet(f"font-size: 10px; color: {self._TEXT_MUTED}; font-style: italic;")
        dl_layout.addWidget(lbl_delogo_note)

        # QSettings persistence for downloader delogo options (mặc định False)
        dl_settings = QSettings("TankVideo", "TankVideoStudio")
        self.chk_auto_delogo_bili.setChecked(dl_settings.value("downloader/auto_delogo_bilibili", False, type=bool))
        self.chk_auto_delogo_wm.setChecked(dl_settings.value("downloader/auto_delogo_watermark", False, type=bool))
        self.chk_auto_delogo_bili.toggled.connect(lambda v: dl_settings.setValue("downloader/auto_delogo_bilibili", v))
        self.chk_auto_delogo_wm.toggled.connect(lambda v: dl_settings.setValue("downloader/auto_delogo_watermark", v))

        left_content_layout.addWidget(card_delogo)

        # --- Action Buttons: BẮT ĐẦU QUÉT & DỪNG QUÉT ---
        act_row = QHBoxLayout()
        act_row.setSpacing(8)

        self.btn_start_scan = QPushButton("⚡ BẮT ĐẦU QUÉT NGẦM")
        self.btn_start_scan.setFixedHeight(44)
        self.btn_start_scan.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._PRIMARY}, stop:1 {self._PRIMARY_DARK});
                border: none; border-radius: 8px; color: white;
                font-size: 13px; font-weight: 800; letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._PRIMARY_HOVER}, stop:1 {self._PRIMARY});
            }}
            QPushButton:disabled {{
                background: #1e293b; color: #64748b;
            }}
        """)
        self.btn_start_scan.clicked.connect(self._on_start_scan)
        act_row.addWidget(self.btn_start_scan, 2)

        self.btn_stop_scan = QPushButton("🛑 DỪNG")
        self.btn_stop_scan.setFixedHeight(44)
        self.btn_stop_scan.setEnabled(False)
        self.btn_stop_scan.setStyleSheet(f"""
            QPushButton {{
                background: #7f1d1d; border: 1px solid #991b1b;
                border-radius: 8px; color: #fecaca;
                font-size: 12px; font-weight: 700;
            }}
            QPushButton:hover {{ background: #991b1b; color: #ffffff; }}
            QPushButton:disabled {{ background: #1e293b; border-color: #334155; color: #64748b; }}
        """)
        self.btn_stop_scan.clicked.connect(self._on_stop_scan)
        act_row.addWidget(self.btn_stop_scan, 1)
        left_content_layout.addLayout(act_row)

        # Scan progress bar & status
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 0)
        self.scan_progress.setFixedHeight(6)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.setStyleSheet(f"""
            QProgressBar {{
                background: #0f172a; border-radius: 3px; border: none;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._PRIMARY}, stop:1 {self._PRIMARY_DARK});
                border-radius: 3px;
            }}
        """)
        self.scan_progress.hide()
        left_content_layout.addWidget(self.scan_progress)

        self.scan_status_lbl = QLabel("Sẵn sàng quét.")
        self.scan_status_lbl.setStyleSheet(f"font-size: 11px; color: {self._TEXT_MUTED};")
        left_content_layout.addWidget(self.scan_status_lbl)

        left_scroll.setWidget(left_content)
        left_layout.addWidget(left_scroll)
        splitter.addWidget(left_widget)
        # ============================================================== #
        #  RIGHT MAIN CONTENT (Results Table & Download Actions)         #
        # ============================================================== #
        right_widget = QWidget(self)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(10)

        # ---- TOP TABLE TOOLBAR (Spacious 2-Row Design) ----
        toolbar_card = QFrame(self)
        toolbar_card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        tb_box = QVBoxLayout(toolbar_card)
        tb_box.setContentsMargins(10, 10, 10, 10)
        tb_box.setSpacing(8)

        # ---- HÀNG 1: BỘ LỌC & TÌM KIẾM (Search & Filters) ----
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        # 1. Search box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Tìm theo tiêu đề, ID, tác giả...")
        self.search_input.setMinimumWidth(160)
        self.search_input.setMaximumWidth(250)
        self.search_input.setStyleSheet(self._input_style())
        self.search_input.textChanged.connect(self._apply_filters)
        row1.addWidget(self.search_input, 1)

        # 2. Min views/likes filter
        lbl_min = QLabel("Lọc min:")
        lbl_min.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {self._TEXT_MUTED};")
        row1.addWidget(lbl_min)

        self.spin_min_val = QSpinBox()
        self.spin_min_val.setRange(0, 100_000_000)
        self.spin_min_val.setSingleStep(1000)
        self.spin_min_val.setValue(0)
        self.spin_min_val.setFixedWidth(75)
        self.spin_min_val.setStyleSheet(self._input_style())
        row1.addWidget(self.spin_min_val)

        self.combo_filter_type = QComboBox()
        self.combo_filter_type.addItems(["Lượt thích", "Lượt xem"])
        self.combo_filter_type.setFixedWidth(90)
        self.combo_filter_type.setStyleSheet(self._combo_style())
        row1.addWidget(self.combo_filter_type)

        btn_apply_filter = QPushButton("⚡ Lọc")
        btn_apply_filter.setStyleSheet(self._primary_action_btn_style())
        btn_apply_filter.clicked.connect(self._apply_filters)
        row1.addWidget(btn_apply_filter)

        btn_reset_filter = QPushButton("🔄 Bỏ lọc")
        btn_reset_filter.setStyleSheet(self._secondary_btn_style())
        btn_reset_filter.clicked.connect(self._on_reset_filters)
        row1.addWidget(btn_reset_filter)

        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("background: #1e293b; max-width: 1px; margin: 2px 2px;")
        row1.addWidget(sep1)

        # 3. Quick range select: Từ STT X đến Y
        lbl_stt = QLabel("Từ STT:")
        lbl_stt.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {self._TEXT_MUTED};")
        row1.addWidget(lbl_stt)

        self.spin_range_from = QSpinBox()
        self.spin_range_from.setRange(1, 10000)
        self.spin_range_from.setValue(1)
        self.spin_range_from.setFixedWidth(50)
        self.spin_range_from.setStyleSheet(self._input_style())
        row1.addWidget(self.spin_range_from)

        lbl_to = QLabel("đến")
        lbl_to.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {self._TEXT_MUTED};")
        row1.addWidget(lbl_to)

        self.spin_range_to = QSpinBox()
        self.spin_range_to.setRange(1, 10000)
        self.spin_range_to.setValue(50)
        self.spin_range_to.setFixedWidth(50)
        self.spin_range_to.setStyleSheet(self._input_style())
        row1.addWidget(self.spin_range_to)

        btn_range_select = QPushButton("🎯 Chọn Nhanh")
        btn_range_select.setStyleSheet(self._secondary_btn_style())
        btn_range_select.clicked.connect(self._on_quick_range_select)
        row1.addWidget(btn_range_select)

        row1.addStretch()
        tb_box.addLayout(row1)

        # Line separator between Row 1 and Row 2
        line_tb = QFrame()
        line_tb.setFrameShape(QFrame.HLine)
        line_tb.setStyleSheet("background: #192338; max-height: 1px; margin: 2px 0;")
        tb_box.addWidget(line_tb)

        # ---- HÀNG 2: THAO TÁC CHỌN & TẢI VIDEO (Actions & Download) ----
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        # Selection shortcuts
        btn_select_all = QPushButton("☑ Chọn Tất Cả")
        btn_select_all.setStyleSheet(self._secondary_btn_style())
        btn_select_all.clicked.connect(lambda: self._set_all_rows_checked(True))
        row2.addWidget(btn_select_all)

        btn_deselect_all = QPushButton("☐ Bỏ Chọn Tất Cả")
        btn_deselect_all.setStyleSheet(self._secondary_btn_style())
        btn_deselect_all.clicked.connect(lambda: self._set_all_rows_checked(False))
        row2.addWidget(btn_deselect_all)

        row2.addStretch(1)

        # Big Download Button
        self.btn_download_selected = QPushButton("📥 TẢI VIDEO ĐÃ CHỌN (0)")
        self.btn_download_selected.setFixedHeight(36)
        self.btn_download_selected.setMinimumWidth(210)
        self.btn_download_selected.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._PRIMARY}, stop:1 {self._PRIMARY_DARK});
                border: none; border-radius: 6px; color: white;
                font-size: 12px; font-weight: 800; padding: 0 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._PRIMARY_HOVER}, stop:1 {self._PRIMARY});
            }}
            QPushButton:disabled {{
                background: #1e293b; color: #64748b;
            }}
        """)
        self.btn_download_selected.clicked.connect(self._on_download_selected)
        self.btn_download_selected.setEnabled(False)
        row2.addWidget(self.btn_download_selected)

        # Stop Download Button
        self.btn_stop_download = QPushButton("🛑 DỪNG TẢI")
        self.btn_stop_download.setFixedHeight(36)
        self.btn_stop_download.setMinimumWidth(105)
        self.btn_stop_download.setEnabled(False)
        self.btn_stop_download.setStyleSheet("""
            QPushButton {
                background: #7f1d1d; border: 1px solid #dc2626;
                border-radius: 6px; color: #fecaca;
                font-size: 11px; font-weight: 800; padding: 0 12px;
            }
            QPushButton:hover { background: #991b1b; color: #ffffff; }
            QPushButton:disabled { background: #1a2234; border-color: #24324a; color: #475569; }
        """)
        self.btn_stop_download.clicked.connect(self._on_stop_download)
        row2.addWidget(self.btn_stop_download)

        # Export CSV Button
        btn_export = QPushButton("📊 Xuất File CSV")
        btn_export.setFixedHeight(36)
        btn_export.setStyleSheet(self._secondary_btn_style())
        btn_export.clicked.connect(self._on_export_csv)
        row2.addWidget(btn_export)

        # Delete Selected Rows Button
        btn_delete_rows = QPushButton("🗑️ Xóa Đã Chọn")
        btn_delete_rows.setFixedHeight(36)
        btn_delete_rows.setStyleSheet(self._danger_btn_style())
        btn_delete_rows.clicked.connect(self._on_delete_selected_rows)
        row2.addWidget(btn_delete_rows)

        tb_box.addLayout(row2)

        # ---- RESULTS TABLE (QTableWidget) ----
        self.table = QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "", "STT", "ẢNH BÌA", "TIÊU ĐỀ / NỘI DUNG",
            "❤️ LƯỢT THÍCH", "👁️ LƯỢT XEM", "TÁC GIẢ", "TRẠNG THÁI"
        ])
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {self._CARD};
                alternate-background-color: #0b101c;
                border: 1px solid {self._CARD_BORDER};
                border-radius: 8px;
                gridline-color: #162032;
                selection-background-color: #261609;
                selection-color: #f8fafc;
            }}
            QHeaderView::section {{
                background-color: #0b101c;
                color: #cbd5e1;
                font-size: 11px;
                font-weight: 700;
                padding: 6px;
                border: none;
                border-bottom: 2px solid {self._PRIMARY};
            }}
            QTableWidget::item {{
                padding: 4px;
                border-bottom: 1px solid #141d2e;
            }}
        """)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)

        # Header column widths
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 42)
        header_view.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 46)
        header_view.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 85)
        header_view.setSectionResizeMode(3, QHeaderView.Stretch)
        header_view.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 95)
        header_view.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 95)
        header_view.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 120)
        header_view.setSectionResizeMode(7, QHeaderView.Fixed)
        self.table.setColumnWidth(7, 105)

        # REAL, CLICKABLE HEADER CHECKBOX OVER SECTION 0 (DEFAULT: UNCHECKED)
        self.header_cb = QCheckBox(self.table.horizontalHeader())
        self.header_cb.setFixedSize(22, 22)
        self.header_cb.setFocusPolicy(Qt.NoFocus)
        self.header_cb.setChecked(False)
        self.header_cb.setCursor(Qt.PointingHandCursor)
        self.header_cb.setToolTip("Chọn tất cả / Bỏ chọn tất cả video đang hiển thị")
        self.header_cb.setStyleSheet(f"""
            QCheckBox {{
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 16px; height: 16px; border-radius: 4px;
                border: 1.5px solid {self._PRIMARY}; background: #0a0f1d;
            }}
            QCheckBox::indicator:hover {{
                border-color: {self._PRIMARY_HOVER};
            }}
            QCheckBox::indicator:checked {{
                background-color: {self._PRIMARY};
                border-color: {self._PRIMARY};
                image: url("{_CHECK_ICON_PATH}");
            }}
            QCheckBox::indicator:checked:hover {{
                background-color: {self._PRIMARY_HOVER};
                border-color: {self._PRIMARY_HOVER};
            }}
        """)
        self.header_cb.stateChanged.connect(self._on_header_checkbox_changed)

        def _reposition_header_cb():
            if hasattr(self, "header_cb") and self.header_cb:
                hh = self.table.horizontalHeader()
                sec_x = hh.sectionPosition(0)
                sec_w = self.table.columnWidth(0)
                h = hh.height()
                self.header_cb.move(sec_x + (sec_w - 22) // 2, (h - 22) // 2)

        self._reposition_header_cb = _reposition_header_cb
        self.table.horizontalHeader().geometriesChanged.connect(_reposition_header_cb)
        self.table.horizontalHeader().sectionResized.connect(lambda *_: _reposition_header_cb())

        # ---- BOTTOM TABLE FOOTER ----
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(4, 2, 4, 2)

        self.table_stats_lbl = QLabel("Tổng video: 0 | Đã chọn: 0 | Tổng lượt xem: 0")
        self.table_stats_lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {self._PRIMARY};")
        footer_row.addWidget(self.table_stats_lbl)

        footer_row.addStretch()

        btn_open_folder = QPushButton("📂 Mở Thư Mục Tải Về")
        btn_open_folder.setStyleSheet(self._secondary_btn_style())
        btn_open_folder.clicked.connect(self._on_open_download_dir)
        footer_row.addWidget(btn_open_folder)

        # Main Right Stacked Widget (Page 0: Standard Table View, Page 1: Hongguo Drama Studio)
        self.right_stack = QStackedWidget(self)

        # PAGE 0: BẢNG VIDEO MẠNG XÃ HỘI THÔNG THƯỜNG
        page_table = QWidget(self)
        page_table_lay = QVBoxLayout(page_table)
        page_table_lay.setContentsMargins(0, 0, 0, 0)
        page_table_lay.setSpacing(10)
        page_table_lay.addWidget(toolbar_card)
        page_table_lay.addWidget(self.table, 1)
        page_table_lay.addLayout(footer_row)
        self.right_stack.addWidget(page_table)

        # PAGE 1: HONGGUO DRAMA STUDIO VIEW
        page_hongguo = self._build_hongguo_view()
        self.right_stack.addWidget(page_hongguo)

        right_layout.addWidget(self.right_stack, 1)
        splitter.addWidget(right_widget)

        # Splitter proportion (Left 350px, Right rest)
        splitter.setSizes([350, 930])
        root.addWidget(splitter, 1)

    # ================================================================== #
    #  Hongguo Drama Studio View (Tải Phim Ngắn Hồng Quả Pro)            #
    # ================================================================== #
    def _build_hongguo_view(self) -> QWidget:
        """Xây dựng giao diện quét và tải phim ngắn Hồng Quả chuẩn Cyber Theme CapCap."""
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)

        # 1. TOP DRAMA INFO CARD
        self.hg_info_card = QFrame(self)
        self.hg_info_card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        ic_layout = QHBoxLayout(self.hg_info_card)
        ic_layout.setContentsMargins(14, 12, 14, 12)
        ic_layout.setSpacing(16)

        # Poster cover
        self.hg_cover_lbl = QLabel()
        self.hg_cover_lbl.setFixedSize(70, 96)
        self.hg_cover_lbl.setAlignment(Qt.AlignCenter)
        self.hg_cover_lbl.setStyleSheet(f"""
            QLabel {{
                background: #0a0f1d;
                border: 1.5px solid {self._PRIMARY};
                border-radius: 6px;
                color: {self._PRIMARY_HOVER};
                font-weight: 700;
                font-size: 11px;
            }}
        """)
        self.hg_cover_lbl.setText("🎬\nHongguo")
        ic_layout.addWidget(self.hg_cover_lbl)

        # Drama details (Title, Meta, Tags)
        dt_lay = QVBoxLayout()
        dt_lay.setSpacing(4)
        dt_lay.setAlignment(Qt.AlignVCenter)

        self.hg_title_lbl = QLabel("Chưa quét phim")
        self.hg_title_lbl.setStyleSheet("font-size: 16px; font-weight: 800; color: #f8fafc;")
        dt_lay.addWidget(self.hg_title_lbl)

        self.hg_meta_lbl = QLabel("Nhập liên kết phim hoặc series_id bên trái rồi bấm 'QUÉT TẬP PHIM' để bắt đầu.")
        self.hg_meta_lbl.setStyleSheet(f"font-size: 11px; color: {self._TEXT_MUTED};")
        dt_lay.addWidget(self.hg_meta_lbl)

        self.hg_tags_lbl = QLabel("")
        self.hg_tags_lbl.setStyleSheet(f"font-size: 11px; color: {self._PRIMARY_HOVER}; font-weight: 600;")
        dt_lay.addWidget(self.hg_tags_lbl)

        ic_layout.addLayout(dt_lay, 1)

        # Right badges
        badge_box = QVBoxLayout()
        badge_box.setSpacing(6)
        badge_box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.hg_badge_free = QLabel("🎁 Miễn phí")
        self.hg_badge_free.setStyleSheet(f"""
            background: #2a1608; border: 1px solid {self._PRIMARY};
            color: {self._PRIMARY_HOVER}; font-size: 10px; font-weight: 700;
            padding: 4px 10px; border-radius: 6px;
        """)
        badge_box.addWidget(self.hg_badge_free)

        self.hg_badge_status = QLabel("★ Đầy đủ tập")
        self.hg_badge_status.setStyleSheet("""
            background: #0c233c; border: 1px solid #0284c7;
            color: #38bdf8; font-size: 10px; font-weight: 700;
            padding: 4px 10px; border-radius: 6px;
        """)
        badge_box.addWidget(self.hg_badge_status)
        ic_layout.addLayout(badge_box)

        page_layout.addWidget(self.hg_info_card)

        # 2. EPISODES GRID CARD
        ep_card = QFrame(self)
        ep_card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        ep_card_lay = QVBoxLayout(ep_card)
        ep_card_lay.setContentsMargins(14, 12, 14, 12)
        ep_card_lay.setSpacing(10)

        # Header of Episode List
        ep_head = QHBoxLayout()
        ep_head.setSpacing(8)

        lbl_ep_title = QLabel("DANH SÁCH TẬP")
        lbl_ep_title.setStyleSheet(f"font-size: 12px; font-weight: 800; color: {self._PRIMARY}; letter-spacing: 0.5px;")
        ep_head.addWidget(lbl_ep_title)

        ep_head.addStretch()

        btn_select_all = QPushButton("✓ Chọn tất cả")
        btn_select_all.setStyleSheet(self._secondary_btn_style())
        btn_select_all.clicked.connect(lambda: self._set_all_hongguo_episodes_checked(True))
        ep_head.addWidget(btn_select_all)

        btn_deselect_all = QPushButton("✗ Bỏ chọn")
        btn_deselect_all.setStyleSheet(self._secondary_btn_style())
        btn_deselect_all.clicked.connect(lambda: self._set_all_hongguo_episodes_checked(False))
        ep_head.addWidget(btn_deselect_all)

        ep_card_lay.addLayout(ep_head)

        # Scroll Area for Episode Buttons Grid
        self.hg_ep_scroll = QScrollArea(self)
        self.hg_ep_scroll.setWidgetResizable(True)
        self.hg_ep_scroll.setFrameShape(QFrame.NoFrame)
        self.hg_ep_scroll.setStyleSheet("background: transparent;")

        self.hg_ep_container = QWidget()
        self.hg_ep_grid = QGridLayout(self.hg_ep_container)
        self.hg_ep_grid.setContentsMargins(4, 4, 4, 4)
        self.hg_ep_grid.setSpacing(8)

        # Placeholder label when no episodes loaded yet
        self.hg_ep_empty_lbl = QLabel("Vui lòng dán link hoặc ID phim Hồng Quả và bấm 'QUÉT TẬP PHIM' để tải danh sách tập.")
        self.hg_ep_empty_lbl.setAlignment(Qt.AlignCenter)
        self.hg_ep_empty_lbl.setStyleSheet(f"color: {self._TEXT_MUTED}; font-size: 12px; padding: 40px;")
        self.hg_ep_grid.addWidget(self.hg_ep_empty_lbl, 0, 0, 1, 1)

        self.hg_ep_scroll.setWidget(self.hg_ep_container)
        ep_card_lay.addWidget(self.hg_ep_scroll, 1)

        page_layout.addWidget(ep_card, 1)

        # 3. CONTROL & DOWNLOAD BAR
        ctrl_card = QFrame(self)
        ctrl_card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        ctrl_lay = QVBoxLayout(ctrl_card)
        ctrl_lay.setContentsMargins(14, 10, 14, 10)
        ctrl_lay.setSpacing(8)

        # Overall progress bar
        self.hg_progress_bar = QProgressBar(self)
        self.hg_progress_bar.setRange(0, 100)
        self.hg_progress_bar.setValue(0)
        self.hg_progress_bar.setFixedHeight(6)
        self.hg_progress_bar.setTextVisible(False)
        self.hg_progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: #0a0f1d; border-radius: 3px; border: none;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._PRIMARY}, stop:1 {self._PRIMARY_DARK});
                border-radius: 3px;
            }}
        """)
        self.hg_progress_bar.hide()
        ctrl_lay.addWidget(self.hg_progress_bar)

        # Bottom action row
        b_row = QHBoxLayout()
        b_row.setSpacing(10)

        self.hg_stats_lbl = QLabel("Đã chọn 0 tập")
        self.hg_stats_lbl.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {self._PRIMARY};")
        b_row.addWidget(self.hg_stats_lbl)

        b_row.addStretch()

        lbl_th = QLabel("⚡ Luồng tải:")
        lbl_th.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {self._TEXT_MUTED};")
        b_row.addWidget(lbl_th)

        self.hg_threads_spin = QSpinBox(self)
        self.hg_threads_spin.setRange(1, 32)
        self.hg_threads_spin.setValue(16)
        self.hg_threads_spin.setFixedWidth(70)
        self.hg_threads_spin.setStyleSheet(self._input_style())
        b_row.addWidget(self.hg_threads_spin)

        self.btn_hg_download = QPushButton("📥 TẢI XUỐNG")
        self.btn_hg_download.setFixedHeight(36)
        self.btn_hg_download.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._PRIMARY}, stop:1 {self._PRIMARY_DARK});
                border: none; border-radius: 6px; color: white;
                font-size: 12px; font-weight: 800; padding: 0 18px; letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._PRIMARY_HOVER}, stop:1 {self._PRIMARY});
            }}
            QPushButton:disabled {{
                background: #1e293b; color: #64748b;
            }}
        """)
        self.btn_hg_download.clicked.connect(self._on_start_download_hongguo)
        b_row.addWidget(self.btn_hg_download)

        self.btn_hg_stop_download = QPushButton("🛑 DỪNG")
        self.btn_hg_stop_download.setFixedHeight(36)
        self.btn_hg_stop_download.setEnabled(False)
        self.btn_hg_stop_download.setStyleSheet(self._danger_btn_style())
        self.btn_hg_stop_download.clicked.connect(self._on_stop_download_hongguo)
        b_row.addWidget(self.btn_hg_stop_download)

        ctrl_lay.addLayout(b_row)
        page_layout.addWidget(ctrl_card)

        # 4. LOG WINDOW CARD
        log_card = QFrame(self)
        log_card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        lc_lay = QVBoxLayout(log_card)
        lc_lay.setContentsMargins(10, 8, 10, 8)
        lc_lay.setSpacing(4)

        log_head = QHBoxLayout()
        lbl_log = QLabel("📋 NHẬT KÝ TIẾN TRÌNH QUÉT & TẢI")
        lbl_log.setStyleSheet(f"font-size: 10px; font-weight: 700; color: {self._TEXT_MUTED};")
        log_head.addWidget(lbl_log)
        log_head.addStretch()

        btn_clear_log = QPushButton("Xóa log")
        btn_clear_log.setStyleSheet(f"font-size: 9px; color: {self._TEXT_MUTED}; background: transparent; border: none;")
        btn_clear_log.clicked.connect(lambda: self.hg_log_edit.clear())
        log_head.addWidget(btn_clear_log)
        lc_lay.addLayout(log_head)

        self.hg_log_edit = QTextEdit(self)
        self.hg_log_edit.setReadOnly(True)
        self.hg_log_edit.setFixedHeight(95)
        self.hg_log_edit.setStyleSheet(f"""
            QTextEdit {{
                background: #070b14; border: 1px solid #141d2e;
                border-radius: 4px; color: #cbd5e1; font-size: 10px;
                font-family: Consolas, monospace; line-height: 1.3;
            }}
        """)
        lc_lay.addWidget(self.hg_log_edit)
        page_layout.addWidget(log_card)

        return page

    def _create_episode_card(self, ep: dict) -> QPushButton:
        """Tạo nút tập theo dạng ô số với 2 dòng text chuẩn CapCap."""
        ep_idx = ep.get("index", 1)
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setChecked(True)
        btn.setFixedSize(68, 54)
        btn.setCursor(Qt.PointingHandCursor)
        init_status = ep.get("status_text") or ("Sẵn sàng" if ep.get("video_url") else "Khóa Web")
        self._update_episode_button_ui(btn, ep_idx, init_status, is_checked=True)
        btn.clicked.connect(lambda checked, idx=ep_idx, b=btn: self._on_episode_button_clicked(idx, b))
        return btn

    def _update_episode_button_ui(
        self,
        btn: QPushButton,
        ep_idx: int,
        status_text: str = "Sẵn sàng",
        is_checked: bool = True,
    ):
        """Cập nhật giao diện nút tập: hiển thị số tập to và trạng thái bên dưới."""
        btn.setText(f"{ep_idx:02d}\n{status_text}")
        if "Hoàn tất" in status_text or "Đã có" in status_text:
            border = "#10b981"
            bg = "#06291a"
            num_color = "#34d399"
        elif "Lỗi" in status_text:
            border = "#ef4444"
            bg = "#2d0a0e"
            num_color = "#fca5a5"
        elif "Khóa" in status_text:
            border = "#b45309"
            bg = "#1e1408"
            num_color = "#fbbf24"
        elif "Tải" in status_text or "Bóc tách" in status_text or "Đang" in status_text:
            border = "#38bdf8"
            bg = "#0c233c"
            num_color = "#7dd3fc"
        elif is_checked:
            border = self._PRIMARY
            bg = "#2a1608"
            num_color = self._PRIMARY_HOVER
        else:
            border = "#1e293b"
            bg = "#0a0f1d"
            num_color = "#94a3b8"

        btn.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                border: 1.5px solid {border};
                border-radius: 6px;
                color: {num_color};
                font-size: 13px;
                font-weight: 800;
                line-height: 1.2;
                padding-top: 4px;
            }}
            QPushButton:hover {{
                border-color: {self._PRIMARY_HOVER};
            }}
        """)

    def _render_hongguo_episodes(self, drama_info: dict):
        """Hiển thị toàn bộ danh sách tập của bộ phim lên lưới nút bấm."""
        self._hg_drama_info = drama_info
        self._hg_ep_buttons.clear()
        self._hg_selected_eps.clear()
        self._hg_ep_data.clear()

        title = drama_info.get("title", "Hongguo Drama")
        total_ep = drama_info.get("total_episodes", 0)
        s_id = drama_info.get("series_id", "")
        tags = " • ".join(drama_info.get("tags", []))
        acc_cnt = drama_info.get("accessible_episodes", 0)

        self.hg_title_lbl.setText(title)
        info_txt = f"ID: {s_id} • {total_ep} tập"
        if acc_cnt > 0 and acc_cnt < total_ep:
            info_txt += f" • Web xem thử {acc_cnt} tập đầu"
        else:
            info_txt += " • Đầy đủ tập"
        self.hg_meta_lbl.setText(info_txt)

        if tags:
            self.hg_tags_lbl.setText(f"🏷️ {tags}")
        else:
            self.hg_tags_lbl.setText("")

        cover_url = drama_info.get("cover_url", "")
        if cover_url:
            self._load_hg_cover_async(cover_url)

        # Clear grid cũ
        while self.hg_ep_grid.count():
            item = self.hg_ep_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        episodes = drama_info.get("episodes", [])
        if not episodes:
            lbl = QLabel("Không tìm thấy danh sách tập nào.")
            lbl.setStyleSheet(f"color: {self._RED}; font-size: 12px; padding: 20px;")
            self.hg_ep_grid.addWidget(lbl, 0, 0)
            return

        cols = 10
        for i, ep in enumerate(episodes):
            ep_idx = ep.get("index", i + 1)
            # Gán trạng thái ban đầu cho tập
            if not ep.get("status_text"):
                if ep.get("video_url") or (acc_cnt > 0 and ep_idx <= acc_cnt):
                    ep["status_text"] = "Sẵn sàng"
                else:
                    ep["status_text"] = "Khóa Web"

            self._hg_ep_data[ep_idx] = ep
            self._hg_selected_eps.add(ep_idx)

            btn = self._create_episode_card(ep)
            self._hg_ep_buttons[ep_idx] = btn
            row = i // cols
            col = i % cols
            self.hg_ep_grid.addWidget(btn, row, col)

        self._update_hongguo_selected_count()
        self._append_hongguo_log(
            f"[{time.strftime('%H:%M:%S')}] ✅ Đã nạp {len(episodes)} tập phim '{title}'.\n"
            f"   💡 Ghi chú: Nền tảng Web Hongguo mở xem thử các tập đầu (1-{acc_cnt or 3}). "
            f"Các tập sau ByteDance yêu cầu mở trên App Hồng Quả."
        )

    def _load_hg_cover_async(self, url: str):
        """Tải ảnh bìa phim ngầm và nạp qua PIL an toàn cho Qt thread."""
        def _fetch():
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0",
                        "Referer": "https://hongguoduanju.com/",
                    },
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw = resp.read()
                if raw:
                    self.sig_hg_cover_ready.emit(raw)
            except Exception as exc:
                print(f"[Hongguo] cover fetch error: {exc}")
        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_hg_cover_data(self, raw_bytes: bytes):
        """Áp dụng ảnh bìa poster lên QLabel trên Main GUI Thread."""
        if not hasattr(self, "hg_cover_lbl") or not self.hg_cover_lbl or not raw_bytes:
            return
        try:
            pm = QPixmap()
            ok = pm.loadFromData(raw_bytes)
            if not ok or pm.isNull():
                from PIL import Image
                import io
                pil_im = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
                data = pil_im.tobytes("raw", "RGBA")
                qimg = QImage(data, pil_im.width, pil_im.height, QImage.Format_RGBA8888)
                pm = QPixmap.fromImage(qimg)

            if not pm.isNull():
                target_w = self.hg_cover_lbl.width() or 70
                target_h = self.hg_cover_lbl.height() or 96
                scaled = pm.scaled(target_w, target_h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self.hg_cover_lbl.setPixmap(scaled)
                self.hg_cover_lbl.setScaledContents(True)
        except Exception as exc:
            print(f"[Hongguo] apply cover error: {exc}")

    def _on_episode_button_clicked(self, ep_idx: int, btn: QPushButton):
        if ep_idx in self._hg_selected_eps:
            self._hg_selected_eps.remove(ep_idx)
            is_chk = False
        else:
            self._hg_selected_eps.add(ep_idx)
            is_chk = True
        btn.setChecked(is_chk)
        txt_lines = btn.text().split("\n")
        st = txt_lines[1] if len(txt_lines) > 1 else "Sẵn sàng"
        self._update_episode_button_ui(btn, ep_idx, st, is_checked=is_chk)
        self._update_hongguo_selected_count()

    def _set_all_hongguo_episodes_checked(self, checked: bool):
        if checked:
            self._hg_selected_eps = set(self._hg_ep_buttons.keys())
        else:
            self._hg_selected_eps.clear()

        for ep_idx, btn in self._hg_ep_buttons.items():
            btn.setChecked(checked)
            txt_lines = btn.text().split("\n")
            st = txt_lines[1] if len(txt_lines) > 1 else "Sẵn sàng"
            self._update_episode_button_ui(btn, ep_idx, st, is_checked=checked)

        self._update_hongguo_selected_count()

    def _update_hongguo_selected_count(self):
        count = len(self._hg_selected_eps)
        total = len(self._hg_ep_buttons)
        if hasattr(self, "hg_stats_lbl"):
            self.hg_stats_lbl.setText(f"Đã chọn {count}/{total} tập")

    def _append_hongguo_log(self, text: str):
        if hasattr(self, "hg_log_edit") and self.hg_log_edit:
            self.hg_log_edit.append(text)
            sb = self.hg_log_edit.verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())

    # ================================================================== #
    #  Card & Widget Styling Helpers                                      #
    # ================================================================== #
    @staticmethod
    def _format_duration(seconds) -> str:
        if not seconds:
            return "--:--"
        if isinstance(seconds, str):
            if ":" in seconds:
                return seconds
            try:
                seconds = float(seconds)
            except Exception:
                return seconds
        try:
            s = int(float(seconds))
            if s <= 0:
                return "--:--"
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            if h > 0:
                return f"{h:02d}:{m:02d}:{sec:02d}"
            return f"{m:02d}:{sec:02d}"
        except Exception:
            return str(seconds)

    def _create_card(self, title: str) -> QFrame:
        card = QFrame(self)
        card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(f"font-size: 11px; font-weight: 800; color: {self._PRIMARY}; letter-spacing: 0.5px;")
        layout.addWidget(t_lbl)
        return card

    def _platform_btn_style(self, is_active: bool) -> str:
        if is_active:
            return f"""
                QPushButton {{
                    background: #2a1608; border: 1.5px solid {self._PRIMARY};
                    color: {self._PRIMARY_HOVER}; border-radius: 6px; padding: 6px 4px;
                    font-size: 11px; font-weight: 800;
                }}
            """
        return f"""
            QPushButton {{
                background: {self._INPUT_BG}; border: 1px solid {self._CARD_BORDER};
                color: {self._TEXT_MUTED}; border-radius: 6px; padding: 6px 4px;
                font-size: 11px; font-weight: 600;
            }}
            QPushButton:hover {{
                background: #141c2e; border-color: #334155; color: #f1f5f9;
            }}
        """

    def _input_style(self) -> str:
        return f"""
            QLineEdit, QSpinBox {{
                background: {self._INPUT_BG}; border: 1px solid {self._CARD_BORDER};
                border-radius: 6px; color: #f8fafc; font-size: 11px; padding: 6px 8px;
            }}
            QLineEdit:focus, QSpinBox:focus {{
                border-color: {self._PRIMARY};
            }}
        """

    def _combo_style(self) -> str:
        return f"""
            QComboBox {{
                background: {self._INPUT_BG}; border: 1px solid {self._CARD_BORDER};
                border-radius: 6px; color: #f8fafc; font-size: 11px; padding: 5px 8px;
            }}
            QComboBox:focus {{ border-color: {self._PRIMARY}; }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: #0f172a; color: white; selection-background-color: {self._PRIMARY};
            }}
        """

    def _secondary_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background: #162033; border: 1px solid #2d3c54;
                border-radius: 6px; color: #e2e8f0; font-size: 11px;
                font-weight: 700; padding: 6px 12px;
            }}
            QPushButton:hover {{ background: #22314a; border-color: {self._PRIMARY}; color: {self._PRIMARY_HOVER}; }}
            QPushButton:disabled {{ color: #475569; background: #0e1523; border-color: #1e293b; }}
        """

    def _primary_action_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background: #251408; border: 1px solid {self._PRIMARY};
                border-radius: 6px; color: {self._PRIMARY_HOVER}; font-size: 11px;
                font-weight: 700; padding: 6px 12px;
            }}
            QPushButton:hover {{
                background: {self._PRIMARY}; color: #ffffff;
            }}
            QPushButton:disabled {{
                background: #121926; border-color: #1e293b; color: #475569;
            }}
        """

    def _danger_btn_style(self) -> str:
        return """
            QPushButton {{
                background: #3b1016; border: 1px solid #7f1d1d;
                border-radius: 6px; color: #fca5a5; font-size: 11px;
                font-weight: 700; padding: 6px 12px;
            }}
            QPushButton:hover {{ background: #7f1d1d; color: #ffffff; }}
            QPushButton:disabled {{ background: #121926; border-color: #1e293b; color: #475569; }}
        """

    # ================================================================== #
    #  Platform & Mode Handlers                                           #
    # ================================================================== #
    def _on_platform_selected(self, platform_id: str):
        self._selected_platform = platform_id
        for pid, btn in self.plat_btns.items():
            btn.setChecked(pid == platform_id)
            btn.setStyleSheet(self._platform_btn_style(pid == platform_id))

        p_name = platform_id.upper()
        plat_display = PLATFORM_DISPLAY_NAMES.get(platform_id, platform_id.capitalize())
        # Update config card title
        t_lbl = self.card_config.findChild(QLabel)
        if t_lbl:
            if platform_id == "hongguo":
                t_lbl.setText("CẤU HÌNH PHIM HỒNG QUẢ (HONGGUO 短剧)")
            else:
                t_lbl.setText(f"CẤU HÌNH QUÉT VIDEO ({p_name})")

        # Switch right view stack: Hongguo Drama Studio vs Standard Table
        if hasattr(self, "right_stack"):
            if platform_id == "hongguo":
                self.right_stack.setCurrentIndex(1)
            else:
                self.right_stack.setCurrentIndex(0)

        # Update input placeholder & scan button text
        if platform_id == "hongguo":
            self.url_input.setPlaceholderText("Dán link phim hoặc series_id (VD: https://hongguoduanju.com/detail?series_id=7680028248540974142)...")
            self.btn_start_scan.setText("🎬 QUÉT TẬP PHIM")
            self.header_status_badge.setText("🍎 Hongguo 短剧")
        elif platform_id == "douyin":
            self.url_input.setPlaceholderText("Dán link kênh Douyin (https://www.douyin.com/user/...)...")
            self.btn_start_scan.setText("⚡ BẮT ĐẦU QUÉT NGẦM")
        elif platform_id == "tiktok":
            self.url_input.setPlaceholderText("Dán link kênh TikTok (@username hoặc link profile)...")
            self.btn_start_scan.setText("⚡ BẮT ĐẦU QUÉT NGẦM")
        elif platform_id == "youtube":
            self.url_input.setPlaceholderText("Dán link kênh hoặc playlist YouTube...")
            self.btn_start_scan.setText("⚡ BẮT ĐẦU QUÉT NGẦM")
        elif platform_id == "bilibili":
            self.url_input.setPlaceholderText("Dán link kênh Bilibili (https://space.bilibili.com/...)...")
            self.btn_start_scan.setText("⚡ BẮT ĐẦU QUÉT NGẦM")
        elif platform_id in ("facebook", "reels"):
            self.url_input.setPlaceholderText("Dán link trang/kênh Facebook, Reels tab (https://www.facebook.com/...) hoặc link video...")
            self.btn_start_scan.setText("⚡ BẮT ĐẦU QUÉT NGẦM")
        else:
            self.url_input.setPlaceholderText(f"Dán link video hoặc trang {p_name}...")
            self.btn_start_scan.setText("⚡ BẮT ĐẦU QUÉT NGẦM")

        # Update cookie title & placeholder & load saved cookie for current platform
        if hasattr(self, "lbl_cookie_title"):
            self.lbl_cookie_title.setText(f"COOKIE (TÙY CHỌN CHO {plat_display.upper()}):")
        if hasattr(self, "cookie_input"):
            domain = PLATFORM_DOMAINS.get(platform_id, f".{platform_id}.com")
            self.cookie_input.setPlaceholderText(f"Dán chuỗi ATP Cookie của {plat_display} (ví dụ: ={domain};...|User-Agent)...")
            cookie_key = f"{platform_id}_cookie_raw" if platform_id != "douyin" else "douyin_cookie_raw"
            self.cookie_input.setPlainText(_get_setting(cookie_key, ""))
        self._refresh_cookie_status(platform_id)

    # ================================================================== #
    #  Browser & Profile Management                                       #
    # ================================================================== #
    def _update_browser_info_label(self):
        b_id = getattr(self, "_selected_browser_id", "chrome")
        b_name = getattr(self, "_selected_browser_name", "Google Chrome") or "Google Chrome"
        p_name = getattr(self, "_selected_profile_name", "Mặc định") or "Mặc định"

        icon_str = "🌐"
        if b_id == "coccoc":
            icon_str = "🟢"
        elif b_id == "edge":
            icon_str = "🔷"

        if hasattr(self, "lbl_browser_info"):
            self.lbl_browser_info.setText(
                f"{icon_str} <b>{b_name}</b><br>👤 Hồ sơ: <b style='color:#38bdf8;'>{p_name}</b>"
            )

    def _on_change_browser(self):
        dlg = BrowserProfileDialog(parent=self, default_browser_id=self._selected_browser_id)
        if dlg.exec() == QDialog.Accepted:
            sel = dlg.get_selected()
            self._selected_browser_id = sel["browser_id"]
            self._selected_browser_name = sel["browser_name"]
            self._selected_browser_exe = sel["browser_exe"]
            self._selected_profile_id = sel["profile_id"]
            self._selected_profile_name = sel["profile_name"]
            self._remember_browser = sel["remember"]

            self._settings.setValue("browser_id", self._selected_browser_id)
            self._settings.setValue("browser_name", self._selected_browser_name)
            self._settings.setValue("browser_exe", self._selected_browser_exe)
            self._settings.setValue("profile_id", self._selected_profile_id)
            self._settings.setValue("profile_name", self._selected_profile_name)
            self._settings.setValue("remember_browser", self._remember_browser)

            self._update_browser_info_label()

    # ================================================================== #
    #  Cookie & Proxy Management                                          #
    # ================================================================== #
    def _refresh_cookie_status(self, platform: Optional[str] = None):
        plat = (platform or getattr(self, "_selected_platform", "douyin")).lower()
        summary_text, is_valid, count, plat_name = get_platform_cookie_summary(plat)
        self.cookie_status_lbl.setText(summary_text)
        if is_valid and count > 0:
            self.cookie_status_lbl.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {self._GREEN};")
        else:
            self.cookie_status_lbl.setStyleSheet(f"font-size: 11px; color: {self._TEXT_MUTED};")

    def _on_paste_url(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.url_input.setText(text)

    def _on_paste_cookie(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if not text:
            return
        self.cookie_input.setPlainText(text)
        self._save_cookie_internal(text)

    def _on_save_cookie(self):
        text = self.cookie_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Lưu Cookie", "Vui lòng dán chuỗi cookie vào ô nhập trước!")
            return
        self._save_cookie_internal(text)

    def _save_cookie_internal(self, text: str):
        curr_plat = getattr(self, "_selected_platform", "douyin")
        res = save_platform_cookies(text, platform=curr_plat)
        if not res.get("success"):
            QMessageBox.warning(self, "Lỗi Cookie", f"Không thể phân tích cookie:\n{res.get('error', 'Lỗi không xác định')}")
        else:
            detected_plat = res.get("platform", curr_plat)
            plat_name = res.get("platform_name", detected_plat.capitalize())
            count = res.get("count", 0)

            # If user pasted a cookie that belongs to another platform (e.g. pasted Bilibili cookie while on Douyin)
            if detected_plat != curr_plat and detected_plat in self.plat_btns:
                self._on_platform_selected(detected_plat)
                QMessageBox.information(
                    self,
                    "Nhận Diện Cookie",
                    f"Hệ thống tự động nhận diện đây là Cookie của {plat_name}!\n"
                    f"Đã lưu thành công {count} cookies {plat_name}.\n"
                    f"Giao diện đã chuyển sang nền tảng {plat_name}."
                )
            else:
                self._refresh_cookie_status(curr_plat)
                QMessageBox.information(
                    self,
                    "Lưu Cookie Thành Công",
                    f"Đã lưu thành công {count} cookies {plat_name}!\n"
                    f"Đã sẵn sàng quét kênh {plat_name}."
                )

    def _on_clear_cookie(self):
        curr_plat = getattr(self, "_selected_platform", "douyin")
        clear_saved_platform_cookies(curr_plat)
        self.cookie_input.clear()
        self._refresh_cookie_status(curr_plat)

    def _on_browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video", self.output_dir_input.text())
        if d:
            self.output_dir_input.setText(d)

    def _on_open_download_dir(self):
        out_dir = self.output_dir_input.text().strip()
        if os.path.exists(out_dir):
            if sys.platform == "win32":
                os.startfile(out_dir)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", out_dir])
        else:
            QMessageBox.information(self, "Thư mục tải về", "Thư mục tải về chưa được tạo hoặc chưa có video nào.")

    # ================================================================== #
    #  Scanning Logic                                                    #
    # ================================================================== #
    def _on_start_scan(self):
        # Route to Hongguo drama scan if platform is Hongguo
        if getattr(self, "_selected_platform", "") == "hongguo":
            self._on_start_scan_hongguo()
            return

        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Quét Video", "Vui lòng nhập Link kênh hoặc Link video muốn quét!")
            return

        # Auto save cookie if user typed into cookie_input
        ck_text = self.cookie_input.toPlainText().strip()
        if ck_text:
            curr_plat = getattr(self, "_selected_platform", "douyin")
            save_platform_cookies(curr_plat, ck_text)
            self._refresh_cookie_status(curr_plat)

        # Update UI state
        self.btn_start_scan.setEnabled(False)
        self.btn_stop_scan.setEnabled(True)
        self.scan_progress.show()
        b_name = getattr(self, "_selected_browser_name", "Trình duyệt") or "Trình duyệt"
        p_name = getattr(self, "_selected_profile_name", "Mặc định") or "Mặc định"
        self.scan_status_lbl.setText(f"Đang khởi tạo {b_name} ({p_name})...")
        self.header_status_badge.setText("⚡ Đang quét ngầm...")
        self.header_status_badge.setStyleSheet(f"""
            background: #2a1608; border: 1px solid {self._PRIMARY};
            color: {self._PRIMARY_HOVER}; font-size: 11px; font-weight: 700;
            padding: 6px 14px; border-radius: 6px;
        """)

        # Clear existing table
        self._raw_videos.clear()
        self._filtered_indices.clear()
        self.table.setRowCount(0)
        if hasattr(self, "header_cb") and self.header_cb:
            self.header_cb.blockSignals(True)
            self.header_cb.setChecked(False)
            self.header_cb.blockSignals(False)
        self._update_table_stats()

        # Determine scan limit (0 = Không giới hạn)
        limit_data = self.limit_combo.currentData() if hasattr(self, "limit_combo") else 0
        if limit_data == -1 and hasattr(self, "custom_limit_spin"):
            max_count = self.custom_limit_spin.value()
        else:
            max_count = int(limit_data) if limit_data is not None else 0

        # Start worker thread with selected browser & profile
        mode = "channel" if "Kênh" in self.mode_combo.currentText() else "single"
        self._scan_worker = ScanWorker(
            platform=self._selected_platform,
            url=url,
            mode=mode,
            browser_id=getattr(self, "_selected_browser_id", "chrome"),
            profile_id=getattr(self, "_selected_profile_id", "Default"),
            browser_exe=getattr(self, "_selected_browser_exe", ""),
            max_count=max_count,
            parent=self,
        )
        self._scan_worker.sig_progress.connect(self._on_scan_progress)
        self._scan_worker.sig_video_found.connect(self._on_video_found)
        self._scan_worker.sig_finished.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_stop_scan(self):
        # Route to Hongguo drama stop if platform is Hongguo
        if getattr(self, "_selected_platform", "") == "hongguo":
            self._on_stop_scan_hongguo()
            return

        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self.scan_status_lbl.setText("Đang dừng quét...")
            self.btn_stop_scan.setEnabled(False)

    def _on_scan_progress(self, msg: str, count: int):
        self.scan_status_lbl.setText(msg)
        self.header_status_badge.setText(f"⚡ Đã tìm thấy {count} video")

    def _on_video_found(self, v_entry: dict):
        # Strict validation: Ignore any dummy recommendation links without title/cover/direct_url
        if not v_entry.get("title") and not v_entry.get("cover") and not v_entry.get("direct_url") and v_entry.get("likes", 0) == 0:
            return

        row_idx = len(self._raw_videos)
        self._raw_videos.append(v_entry)
        self._filtered_indices.append(row_idx)
        self._insert_table_row(row_idx, v_entry)
        self._update_table_stats()

    def _insert_table_row(self, row_idx: int, v: dict):
        t_row = self.table.rowCount()
        self.table.insertRow(t_row)
        self.table.setRowHeight(t_row, 58)

        # Col 0: Checkbox (MẶC ĐỊNH LÀ KHÔNG TÍCH / UNCHECKED)
        cb = QCheckBox()
        cb.setFixedSize(22, 22)
        cb.setFocusPolicy(Qt.NoFocus)
        cb.setChecked(False)
        cb.setCursor(Qt.PointingHandCursor)
        cb.setStyleSheet(f"""
            QCheckBox {{
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 16px; height: 16px; border-radius: 4px;
                border: 1.5px solid #334155; background: #0a0f1d;
            }}
            QCheckBox::indicator:hover {{
                border-color: {self._PRIMARY};
            }}
            QCheckBox::indicator:checked {{
                background-color: {self._PRIMARY};
                border-color: {self._PRIMARY};
                image: url("{_CHECK_ICON_PATH}");
            }}
            QCheckBox::indicator:checked:hover {{
                background-color: {self._PRIMARY_HOVER};
                border-color: {self._PRIMARY_HOVER};
            }}
        """)
        cb.stateChanged.connect(self._update_table_stats)
        cb_container = QWidget()
        cb_container.setStyleSheet("background: transparent;")
        cb_layout = QHBoxLayout(cb_container)
        cb_layout.setContentsMargins(0, 0, 0, 0)
        cb_layout.setAlignment(Qt.AlignCenter)
        cb_layout.addWidget(cb)
        self.table.setCellWidget(t_row, 0, cb_container)

        # Col 1: STT
        stt_item = QTableWidgetItem(str(t_row + 1))
        stt_item.setTextAlignment(Qt.AlignCenter)
        stt_item.setForeground(QColor("#94a3b8"))
        self.table.setItem(t_row, 1, stt_item)

        # Col 2: ẢNH BÌA (Thumbnail placeholder / Cache check)
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(72, 54)
        thumb_lbl.setStyleSheet("background: #111827; border-radius: 4px; border: 1px solid #1e293b;")
        thumb_lbl.setAlignment(Qt.AlignCenter)
        c_url = v.get("cover", "")
        if c_url and c_url in _THUMBNAIL_CACHE:
            thumb_lbl.setPixmap(_THUMBNAIL_CACHE[c_url])

        thumb_container = QWidget()
        thumb_container.setStyleSheet("background: transparent;")
        thumb_lay = QHBoxLayout(thumb_container)
        thumb_lay.setContentsMargins(0, 0, 0, 0)
        thumb_lay.setAlignment(Qt.AlignCenter)
        thumb_lay.addWidget(thumb_lbl)
        self.table.setCellWidget(t_row, 2, thumb_container)

        # Col 3: Tiêu đề
        title_item = QTableWidgetItem(v.get("title", ""))
        title_item.setToolTip(v.get("title", ""))
        self.table.setItem(t_row, 3, title_item)

        # Col 4: Lượt thích
        likes = v.get("likes", 0)
        like_str = f"{likes:,}".replace(",", ".") if likes else "0"
        like_item = QTableWidgetItem(f"❤️ {like_str}")
        like_item.setForeground(QColor("#f43f5e"))
        like_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(t_row, 4, like_item)

        # Col 5: Lượt xem
        views = v.get("views", 0)
        view_str = f"{views:,}".replace(",", ".") if views else "0"
        view_item = QTableWidgetItem(f"👁️ {view_str}")
        view_item.setForeground(QColor(self._ACCENT_BLUE))
        view_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.setItem(t_row, 5, view_item)

        # Col 6: Tác giả
        author_item = QTableWidgetItem(v.get("author", ""))
        author_item.setForeground(QColor("#cbd5e1"))
        self.table.setItem(t_row, 6, author_item)

        # Col 7: Trạng thái
        status_item = QTableWidgetItem(v.get("status", "Chờ tải"))
        status_item.setTextAlignment(Qt.AlignCenter)
        status_item.setForeground(QColor("#f59e0b"))
        self.table.setItem(t_row, 7, status_item)

    def _on_scan_finished(self, videos: list, channel_info: dict, err: str):
        self.btn_start_scan.setEnabled(True)
        self.btn_stop_scan.setEnabled(False)
        self.scan_progress.hide()

        ch_name = channel_info.get("name") or "Kênh"
        total = len(self._raw_videos)

        # Check for expired cookie or service exception
        if (
            err in ["COOKIE_EXPIRED", "NO_VIDEOS_OR_COOKIE_EXPIRED"]
            or channel_info.get("error_type") in ["COOKIE_EXPIRED", "NO_VIDEOS_OR_COOKIE_EXPIRED"]
        ):
            self.scan_status_lbl.setText("⚠️ Cookie Douyin đã hết hạn hoặc phiên không hợp lệ!")
            self.header_status_badge.setText("⚠️ Cookie Hết Hạn")
            self.header_status_badge.setStyleSheet(f"""
                background: #3a1118; border: 1px solid #ef4444;
                color: #f87171; font-size: 11px; font-weight: 700;
                padding: 6px 14px; border-radius: 6px;
            """)

            # Pop up Cookie Expired Alert Dialog with 1-click clipboard paste
            dlg = CookieExpiredDialog(
                parent=self,
                browser_name=getattr(self, "_selected_browser_name", "Google Chrome") or "Google Chrome",
                profile_name=getattr(self, "_selected_profile_name", "Mặc định") or "Mặc định",
            )
            if dlg.exec() == QDialog.Accepted:
                if dlg.action_result == "paste_retry":
                    self._refresh_cookie_status()
                    QTimer.singleShot(400, self._on_start_scan)
                    return
                elif dlg.action_result == "goto_cookie":
                    self.cookie_input.setFocus()
                    self.cookie_input.selectAll()
            return

        if err:
            self.scan_status_lbl.setText(f"Quét kết thúc với cảnh báo: {err}")
            self.header_status_badge.setText(f"⚡ Đã quét: {total} video")
        else:
            self.scan_status_lbl.setText(f"✅ Hoàn tất! Quét được {total} video của kênh '{ch_name}'.")
            self.header_status_badge.setText(f"✅ Đã quét {total} video")

        # Load thumbnails asynchronously
        items_to_load = []
        for i, v in enumerate(self._raw_videos):
            if v.get("cover"):
                items_to_load.append((i, v["cover"]))

        if items_to_load:
            if self._thumb_worker and self._thumb_worker.isRunning():
                self._thumb_worker.stop()
            self._thumb_worker = ThumbnailLoader(items_to_load, parent=self)
            self._thumb_worker.thumbnail_loaded.connect(self._on_thumbnail_loaded)
            self._thumb_worker.start()

        # Update range selector max (default header checkbox unchecked)
        if total > 0:
            self.spin_range_from.setValue(1)
            self.spin_range_to.setValue(min(50, total))
            self.spin_range_to.setMaximum(total)
            if hasattr(self, "header_cb") and self.header_cb:
                self.header_cb.blockSignals(True)
                self.header_cb.setChecked(False)
                self.header_cb.blockSignals(False)

        self._update_table_stats()

    def _on_thumbnail_loaded(self, row_idx: int, pixmap: QPixmap):
        if row_idx < self.table.rowCount():
            cell_widget = self.table.cellWidget(row_idx, 2)
            if cell_widget:
                lbl = cell_widget.findChild(QLabel)
                if lbl:
                    lbl.setPixmap(pixmap)

    # ================================================================== #
    #  Table Filtering & Selection Logic                                  #
    # ================================================================== #
    def _on_header_checkbox_changed(self, state: int):
        checked = (state == Qt.Checked.value or state == 2)
        self._set_all_rows_checked(checked)

    def _set_all_rows_checked(self, checked: bool):
        total = self.table.rowCount()
        applied = 0
        for r in range(total):
            if self.table.isRowHidden(r):
                continue
            cb_widget = self.table.cellWidget(r, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb:
                    cb.blockSignals(True)
                    cb.setChecked(checked)
                    cb.blockSignals(False)
                    applied += 1

        self._update_table_stats()
        action_text = "Đã chọn tất cả" if checked else "Đã bỏ chọn tất cả"
        self.scan_status_lbl.setText(f"{action_text} {applied} video đang hiển thị.")

    def _on_quick_range_select(self):
        total = self.table.rowCount()
        if total == 0:
            QMessageBox.information(self, "Chọn Nhanh", "Chưa có danh sách video để chọn!")
            return

        from_idx = max(0, self.spin_range_from.value() - 1)
        to_idx = min(total - 1, self.spin_range_to.value() - 1)
        if from_idx > to_idx:
            from_idx, to_idx = to_idx, from_idx

        selected_in_range = 0
        for r in range(total):
            if self.table.isRowHidden(r):
                continue
            cb_widget = self.table.cellWidget(r, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb:
                    in_range = (from_idx <= r <= to_idx)
                    cb.blockSignals(True)
                    cb.setChecked(in_range)
                    cb.blockSignals(False)
                    if in_range:
                        selected_in_range += 1

        self._update_table_stats()
        self.scan_status_lbl.setText(
            f"🎯 Đã chọn nhanh {selected_in_range} video (khoảng STT {from_idx+1} đến {to_idx+1})."
        )

    def _apply_filters(self):
        query = self.search_input.text().strip().lower()
        min_val = self.spin_min_val.value()
        filter_type = self.combo_filter_type.currentText()  # "Lượt thích" / "Lượt xem"

        total = self.table.rowCount()
        hidden_count = 0

        for r in range(total):
            if r >= len(self._raw_videos):
                continue
            v = self._raw_videos[r]
            match_search = True
            if query:
                title = (v.get("title") or "").lower()
                author = (v.get("author") or "").lower()
                vid = str(v.get("id") or "").lower()
                match_search = (query in title) or (query in author) or (query in vid)

            match_min = True
            if min_val > 0:
                val = v.get("likes", 0) if "thích" in filter_type.lower() else v.get("views", 0)
                match_min = val >= min_val

            should_hide = not (match_search and match_min)
            self.table.setRowHidden(r, should_hide)
            if should_hide:
                hidden_count += 1

        self._update_table_stats()
        visible = total - hidden_count
        if query or min_val > 0:
            self.scan_status_lbl.setText(f"Bộ lọc: đang hiển thị {visible}/{total} video phù hợp.")

    def _on_reset_filters(self):
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self.spin_min_val.setValue(0)
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, False)
        self._update_table_stats()
        self.scan_status_lbl.setText(f"Đã bỏ bộ lọc. Hiển thị toàn bộ {self.table.rowCount()} video.")

    def _update_table_stats(self):
        total = self.table.rowCount()
        selected = 0
        visible_count = 0
        total_views = 0

        for r in range(total):
            is_hidden = self.table.isRowHidden(r)
            if not is_hidden:
                visible_count += 1
            cb_widget = self.table.cellWidget(r, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb and cb.isChecked() and not is_hidden:
                    selected += 1
            if r < len(self._raw_videos):
                total_views += self._raw_videos[r].get("views", 0)

        # Synchronize header checkbox state
        if hasattr(self, "header_cb") and self.header_cb:
            self.header_cb.blockSignals(True)
            self.header_cb.setChecked(visible_count > 0 and selected == visible_count)
            self.header_cb.blockSignals(False)

        # Update download button
        is_downloading = bool(self._download_worker and self._download_worker.isRunning())
        self.btn_download_selected.setText(f"📥 TẢI VIDEO ĐÃ CHỌN ({selected})")
        self.btn_download_selected.setEnabled(selected > 0 and not is_downloading)

        views_formatted = f"{total_views:,}".replace(",", ".")
        if visible_count < total:
            self.table_stats_lbl.setText(
                f"Hiển thị: {visible_count}/{total} video | Đã chọn: {selected} | Tổng lượt xem: {views_formatted}"
            )
        else:
            self.table_stats_lbl.setText(
                f"Tổng video: {total} | Đã chọn: {selected} | Tổng lượt xem: {views_formatted}"
            )

    def _on_delete_selected_rows(self):
        rows_to_del = []
        for r in range(self.table.rowCount()):
            cb_widget = self.table.cellWidget(r, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb and cb.isChecked() and not self.table.isRowHidden(r):
                    rows_to_del.append(r)

        if not rows_to_del:
            QMessageBox.information(self, "Xóa Video", "Chưa có video nào được chọn để xóa!")
            return

        cnt = len(rows_to_del)
        res = QMessageBox.question(
            self,
            "Xác nhận xóa",
            f"Bạn có chắc chắn muốn xóa {cnt} video đã chọn khỏi danh sách kết quả không?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if res != QMessageBox.Yes:
            return

        for r in reversed(rows_to_del):
            if r < len(self._raw_videos):
                self._raw_videos.pop(r)
            self.table.removeRow(r)

        # Re-number STT
        for r in range(self.table.rowCount()):
            stt_item = self.table.item(r, 1)
            if stt_item:
                stt_item.setText(str(r + 1))

        self._update_table_stats()
        self.scan_status_lbl.setText(f"🗑️ Đã xóa {cnt} video khỏi danh sách.")

    def _on_export_csv(self):
        if not self._raw_videos:
            QMessageBox.information(self, "Xuất Dữ Liệu", "Chưa có video nào để xuất!")
            return

        # Check if user selected specific rows, otherwise export all visible rows
        selected_indices = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            cb_widget = self.table.cellWidget(r, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    selected_indices.append(r)

        if not selected_indices:
            export_rows = [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]
            export_msg = f"Đã xuất toàn bộ {len(export_rows)} video"
        else:
            export_rows = selected_indices
            export_msg = f"Đã xuất {len(export_rows)} video đã chọn"

        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu danh sách video (Excel/CSV)", "douyin_videos.csv", "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "STT", "ID Video", "Tiêu đề", "URL Kênh/Video",
                    "Lượt thích", "Lượt xem", "Tác giả", "Link MP4 Direct"
                ])
                for out_stt, r in enumerate(export_rows):
                    if r < len(self._raw_videos):
                        v = self._raw_videos[r]
                        writer.writerow([
                            out_stt + 1,
                            v.get("id"),
                            v.get("title"),
                            v.get("url"),
                            v.get("likes"),
                            v.get("views"),
                            v.get("author"),
                            v.get("direct_url"),
                        ])
            QMessageBox.information(self, "Xuất Dữ Liệu", f"{export_msg} thành công ra file:\n{path}")
            self.scan_status_lbl.setText(f"📊 {export_msg} ra: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "Lỗi Xuất File", str(e))

    # ================================================================== #
    #  Batch Download Execution                                           #
    # ================================================================== #
    def _on_download_selected(self):
        selected_items = []
        for r in range(self.table.rowCount()):
            if self.table.isRowHidden(r):
                continue
            cb_widget = self.table.cellWidget(r, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb and cb.isChecked():
                    if r < len(self._raw_videos):
                        selected_items.append((r, self._raw_videos[r]))

        if not selected_items:
            QMessageBox.warning(self, "Tải Video", "Chưa có video nào được chọn để tải!")
            return

        out_dir = self.output_dir_input.text().strip()
        if not out_dir:
            out_dir = os.path.join(self._workspace_root or os.getcwd(), "downloads_video")
            self.output_dir_input.setText(out_dir)

        # Update button states: Enable STOP button, disable download & scan
        self.btn_download_selected.setEnabled(False)
        self.btn_stop_download.setEnabled(True)
        self.btn_start_scan.setEnabled(False)

        self.scan_progress.show()
        self.scan_progress.setRange(0, len(selected_items))
        self.scan_progress.setValue(0)
        auto_bili = self.chk_auto_delogo_bili.isChecked() if hasattr(self, "chk_auto_delogo_bili") else False
        auto_wm = self.chk_auto_delogo_wm.isChecked() if hasattr(self, "chk_auto_delogo_wm") else False
        self._download_worker = DownloadWorker(
            selected_items,
            out_dir,
            auto_delogo_bilibili=auto_bili,
            auto_delogo_watermark=auto_wm,
            parent=self,
        )
        self._download_worker.sig_row_status.connect(self._on_row_status_update)
        self._download_worker.sig_progress.connect(self._on_download_progress)
        self._download_worker.sig_finished.connect(self._on_download_finished)
        self._download_worker.start()

    def _on_stop_download(self):
        if self._download_worker and self._download_worker.isRunning():
            self.scan_status_lbl.setText("🛑 Đang dừng quá trình tải, vui lòng đợi giây lát...")
            self.btn_stop_download.setEnabled(False)
            self._download_worker.cancel()

    def _on_row_status_update(self, row_idx: int, status_text: str):
        if row_idx < self.table.rowCount():
            item = self.table.item(row_idx, 7)
            if item:
                item.setText(status_text)
                if "Hoàn thành" in status_text:
                    item.setForeground(QColor(self._GREEN))
                elif "Lỗi" in status_text:
                    item.setForeground(QColor(self._RED))
                elif "dừng" in status_text.lower() or "hủy" in status_text.lower():
                    item.setForeground(QColor("#f43f5e"))
                else:
                    item.setForeground(QColor("#f59e0b"))

    def _on_download_progress(self, current: int, total: int, msg: str):
        self.scan_progress.setValue(current)
        self.scan_status_lbl.setText(msg)
        self.header_status_badge.setText(f"📥 Đang tải {current}/{total}...")

    def _on_download_finished(self, success_count: int, total: int, was_cancelled: bool = False):
        self.btn_download_selected.setEnabled(True)
        self.btn_stop_download.setEnabled(False)
        self.btn_start_scan.setEnabled(True)
        self.scan_progress.hide()

        self._update_table_stats()

        if was_cancelled:
            self.scan_status_lbl.setText(f"🛑 Đã dừng tải: {success_count}/{total} video đã được tải thành công.")
            self.header_status_badge.setText(f"⏹️ Đã dừng ({success_count}/{total})")
            QMessageBox.information(
                self,
                "Đã Dừng Tải",
                f"Quá trình tải video đã dừng theo yêu cầu.\nSố video đã tải thành công: {success_count}/{total}.",
            )
        else:
            self.scan_status_lbl.setText(f"🎉 Tải hoàn tất: {success_count}/{total} video thành công!")
            self.header_status_badge.setText(f"✅ Đã tải xong {success_count} video")
            res = QMessageBox.information(
                self,
                "Tải Hoàn Tất",
                f"Đã tải thành công {success_count}/{total} video vào thư mục:\n{self.output_dir_input.text()}\n\nBạn có muốn mở thư mục ngay không?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if res == QMessageBox.Yes:
                self._on_open_download_dir()

    # ================================================================== #
    #  Hongguo Drama Scan & Download Handlers                             #
    # ================================================================== #
    def _get_hongguo_cookie_str(self) -> str:
        """Lấy chuỗi Cookie Hồng Quả chuẩn hóa dạng name=value;..."""
        ck_text = self.cookie_input.toPlainText().strip()
        if ck_text:
            return ck_text
        raw_ck = get_saved_platform_cookies("hongguo")
        if isinstance(raw_ck, tuple):
            ck_list = raw_ck[0]
            if isinstance(ck_list, list):
                return "; ".join([f"{c['name']}={c['value']}" for c in ck_list if isinstance(c, dict) and "name" in c])
        elif isinstance(raw_ck, str):
            return raw_ck
        return ""

    def _on_start_scan_hongguo(self):
        """Bắt đầu quét tập phim Hồng Quả."""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Quét Phim Hồng Quả", "Vui lòng dán liên kết hoặc ID phim Hồng Quả!")
            return

        series_id = parse_hongguo_id(url)
        if not series_id:
            QMessageBox.warning(self, "Quét Phim Hồng Quả", "Không tìm thấy series_id hợp lệ từ liên kết hoặc chuỗi nhập vào!")
            return

        ck_text = self.cookie_input.toPlainText().strip()
        if ck_text:
            save_platform_cookies("hongguo", ck_text)

        cookies = self._get_hongguo_cookie_str() or None

        self.btn_start_scan.setEnabled(False)
        self.btn_stop_scan.setEnabled(True)
        self.scan_progress.show()
        self.scan_status_lbl.setText(f"Đang phân tích phim ID {series_id}...")
        self.header_status_badge.setText("🍎 Đang quét Hồng Quả...")
        self._append_hongguo_log(f"[{time.strftime('%H:%M:%S')}] 🔍 Bắt đầu quét phim ID: {series_id}...")

        self._hg_scan_worker = HongguoScanWorker(url, cookies=cookies, parent=self)
        self._hg_scan_worker.sig_progress.connect(self._on_hg_scan_progress)
        self._hg_scan_worker.sig_done.connect(self._on_hg_scan_done)
        self._hg_scan_worker.sig_error.connect(self._on_hg_scan_error)
        self._hg_scan_worker.start()

    def _on_stop_scan_hongguo(self):
        """Dừng quét phim Hồng Quả."""
        if self._hg_scan_worker and self._hg_scan_worker.isRunning():
            self._hg_scan_worker.cancel()
            self.scan_status_lbl.setText("Đang dừng quét phim...")
            self.btn_stop_scan.setEnabled(False)
            self._append_hongguo_log(f"[{time.strftime('%H:%M:%S')}] 🛑 Đã gửi lệnh dừng quét.")

    def _on_hg_scan_progress(self, msg: str):
        self.scan_status_lbl.setText(msg)
        self._append_hongguo_log(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _on_hg_scan_done(self, drama_info: dict):
        self.btn_start_scan.setEnabled(True)
        self.btn_stop_scan.setEnabled(False)
        self.scan_progress.hide()
        title = drama_info.get("title", "")
        cnt = drama_info.get("total_episodes", 0)
        self.scan_status_lbl.setText(f"Quét hoàn tất: {title} ({cnt} tập)")
        self.header_status_badge.setText(f"🍎 Đã quét {cnt} tập")
        self._render_hongguo_episodes(drama_info)

    def _on_hg_scan_error(self, err_msg: str):
        self.btn_start_scan.setEnabled(True)
        self.btn_stop_scan.setEnabled(False)
        self.scan_progress.hide()
        self.scan_status_lbl.setText("Lỗi quét phim!")
        self.header_status_badge.setText("⚠️ Lỗi quét")
        self._append_hongguo_log(f"[{time.strftime('%H:%M:%S')}] ❌ Lỗi quét phim: {err_msg}")
        QMessageBox.warning(
            self,
            "Lỗi Quét Phim Hồng Quả",
            f"Không thể lấy thông tin phim:\n{err_msg}\n\n💡 Mẹo: Bạn có thể nhập Cookie Hồng Quả ở khung Cookie bên trái để truy cập đầy đủ tất cả các tập.",
        )

    def _on_start_download_hongguo(self):
        """Bắt đầu tải các tập phim Hồng Quả đã chọn với đa luồng."""
        if not self._hg_drama_info:
            QMessageBox.warning(self, "Tải Phim", "Vui lòng quét thông tin phim trước khi bấm tải!")
            return

        if not self._hg_selected_eps:
            QMessageBox.warning(self, "Tải Phim", "Bạn chưa chọn tập nào để tải! Vui lòng chọn ít nhất 1 tập.")
            return

        out_dir = self.output_dir_input.text().strip()
        if not out_dir:
            out_dir = os.path.join(self._workspace_root, "output", "Hongguo")
        os.makedirs(out_dir, exist_ok=True)

        selected_list = []
        for ep_idx in sorted(self._hg_selected_eps):
            if ep_idx in self._hg_ep_data:
                selected_list.append(self._hg_ep_data[ep_idx])

        threads = self.hg_threads_spin.value()
        cookies = self._get_hongguo_cookie_str() or None

        self.btn_hg_download.setEnabled(False)
        self.btn_hg_stop_download.setEnabled(True)
        self.hg_progress_bar.show()
        self.hg_progress_bar.setValue(0)

        self._hg_download_worker = HongguoDownloadWorker(
            drama_info=self._hg_drama_info,
            selected_episodes=selected_list,
            output_dir=out_dir,
            threads=threads,
            cookies=cookies,
            parent=self,
        )
        self._hg_download_worker.sig_ep_status.connect(self._on_hg_ep_status)
        self._hg_download_worker.sig_ep_completed.connect(self._on_hg_ep_completed)
        self._hg_download_worker.sig_ep_error.connect(self._on_hg_ep_error)
        self._hg_download_worker.sig_overall_progress.connect(self._on_hg_overall_progress)
        self._hg_download_worker.sig_log.connect(self._append_hongguo_log)
        self._hg_download_worker.sig_all_done.connect(self._on_hg_all_done)
        self._hg_download_worker.start()

    def _on_stop_download_hongguo(self):
        """Dừng tải đa luồng các tập phim Hồng Quả."""
        if self._hg_download_worker and self._hg_download_worker.isRunning():
            self._hg_download_worker.cancel()
            self._append_hongguo_log(f"[{time.strftime('%H:%M:%S')}] 🛑 Đang gửi lệnh dừng tải đa luồng...")
            self.btn_hg_stop_download.setEnabled(False)

    def _on_hg_ep_status(self, ep_idx: int, status_text: str):
        btn = self._hg_ep_buttons.get(ep_idx)
        if btn:
            is_chk = ep_idx in self._hg_selected_eps
            self._update_episode_button_ui(btn, ep_idx, status_text, is_checked=is_chk)

    def _on_hg_ep_completed(self, ep_idx: int, file_path: str):
        btn = self._hg_ep_buttons.get(ep_idx)
        if btn:
            self._update_episode_button_ui(btn, ep_idx, "Hoàn tất ✓", is_checked=True)

    def _on_hg_ep_error(self, ep_idx: int, error_msg: str):
        btn = self._hg_ep_buttons.get(ep_idx)
        if btn:
            self._update_episode_button_ui(btn, ep_idx, "Lỗi", is_checked=True)

    def _on_hg_overall_progress(self, completed: int, total: int, pct: int):
        if hasattr(self, "hg_progress_bar"):
            self.hg_progress_bar.setValue(pct)
        if hasattr(self, "hg_stats_lbl"):
            self.hg_stats_lbl.setText(f"Tiến độ: {completed}/{total} tập ({pct}%)")

    def _on_hg_all_done(self, success_count: int, fail_count: int):
        self.btn_hg_download.setEnabled(True)
        self.btn_hg_stop_download.setEnabled(False)
        self.hg_progress_bar.hide()
        total = success_count + fail_count
        self._update_hongguo_selected_count()

        if fail_count == 0 and success_count > 0:
            res = QMessageBox.information(
                self,
                "Tải Phim Hoàn Tất",
                f"🎉 Đã tải thành công {success_count}/{total} tập phim!\n\nThư mục: {self.output_dir_input.text()}\nBạn có muốn mở thư mục không?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if res == QMessageBox.Yes:
                self._on_open_download_dir()
        else:
            QMessageBox.information(
                self,
                "Kết Quả Tải Phim",
                f"Quá trình tải phim đã kết thúc:\n- Thành công: {success_count} tập\n- Thất bại / Bị dừng: {fail_count} tập.",
            )

