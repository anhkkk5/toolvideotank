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
        max_count: int = 200,
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
                        for i, e in enumerate(entries):
                            if self._is_cancelled:
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

    def __init__(self, selected_items: List[tuple], output_dir: str, parent=None):
        """selected_items: list of (row_idx, video_dict)"""
        super().__init__(parent)
        self.selected_items = selected_items
        self.output_dir = output_dir
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

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
                    res = svc.download_single(v.get("url"), self.output_dir)
                    if res.get("success"):
                        downloaded = True
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
                success += 1
                self.sig_row_status.emit(row_idx, "✅ Hoàn thành")
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

        # State
        self._selected_platform = "douyin"
        self._raw_videos: List[Dict[str, Any]] = []
        self._filtered_indices: List[int] = []

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
        ]
        for i, (p_id, p_name) in enumerate(platform_list):
            btn = QPushButton(p_name)
            btn.setCheckable(True)
            btn.setChecked(p_id == "douyin")
            btn.setStyleSheet(self._platform_btn_style(p_id == "douyin"))
            btn.clicked.connect(lambda checked, pid=p_id: self._on_platform_selected(pid))
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
        right_layout.addWidget(toolbar_card)

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

        right_layout.addWidget(self.table, 1)

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

        right_layout.addLayout(footer_row)
        splitter.addWidget(right_widget)

        # Splitter proportion (Left 350px, Right rest)
        splitter.setSizes([350, 930])
        root.addWidget(splitter, 1)

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
            t_lbl.setText(f"CẤU HÌNH QUÉT VIDEO ({p_name})")

        # Update input placeholder
        if platform_id == "douyin":
            self.url_input.setPlaceholderText("Dán link kênh Douyin (https://www.douyin.com/user/...)...")
        elif platform_id == "tiktok":
            self.url_input.setPlaceholderText("Dán link kênh TikTok (@username hoặc link profile)...")
        elif platform_id == "youtube":
            self.url_input.setPlaceholderText("Dán link kênh hoặc playlist YouTube...")
        elif platform_id == "bilibili":
            self.url_input.setPlaceholderText("Dán link kênh Bilibili (https://space.bilibili.com/...)...")
        elif platform_id in ("facebook", "reels"):
            self.url_input.setPlaceholderText("Dán link trang/kênh Facebook, Reels tab (https://www.facebook.com/...) hoặc link video...")
        else:
            self.url_input.setPlaceholderText(f"Dán link video hoặc trang {p_name}...")

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

        # Start worker thread with selected browser & profile
        mode = "channel" if "Kênh" in self.mode_combo.currentText() else "single"
        self._scan_worker = ScanWorker(
            platform=self._selected_platform,
            url=url,
            mode=mode,
            browser_id=getattr(self, "_selected_browser_id", "chrome"),
            profile_id=getattr(self, "_selected_profile_id", "Default"),
            browser_exe=getattr(self, "_selected_browser_exe", ""),
            parent=self,
        )
        self._scan_worker.sig_progress.connect(self._on_scan_progress)
        self._scan_worker.sig_video_found.connect(self._on_video_found)
        self._scan_worker.sig_finished.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_stop_scan(self):
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
        self.scan_status_lbl.setText(f"Bắt đầu tải {len(selected_items)} video...")
        self.header_status_badge.setText(f"📥 Đang tải 0/{len(selected_items)}...")

        self._download_worker = DownloadWorker(selected_items, out_dir, parent=self)
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

