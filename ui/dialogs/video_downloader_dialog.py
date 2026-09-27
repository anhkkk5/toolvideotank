"""Video Downloader Dialog – Giao diện tải video từ mạng xã hội.

Hỗ trợ: YouTube, TikTok, Douyin, Bilibili, Xiaohongshu (RED)
Hai chế độ:
  1. Tải từng video (nhập link video)
  2. Tải toàn bộ kênh (nhập link kênh/trang cá nhân)
"""

import os
import threading
import time

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


# ---- Rounded separator helper ----
def _sep_line(parent=None):
    line = QFrame(parent)
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet("background: #1e293b; max-height: 1px; margin: 6px 0;")
    return line


class VideoDownloaderDialog(QDialog):
    """Full-featured video downloader dialog."""

    # Qt signals for thread-safe UI updates
    _sig_progress = Signal(dict)
    _sig_log = Signal(str)
    _sig_done = Signal(dict)

    # ------------------------------------------------------------------ #
    #  Colours / Stylesheet tokens                                        #
    # ------------------------------------------------------------------ #
    _BG = "#080c14"
    _CARD = "#0f172a"
    _BORDER = "#1e293b"
    _ACCENT = "#38bdf8"
    _ORANGE = "#ff7b1a"
    _GREEN = "#34d399"
    _RED = "#f87171"
    _TEXT = "#e2e8f0"
    _MUTED = "#94a3b8"

    def __init__(self, parent=None, workspace_root: str = ""):
        super().__init__(parent)
        self._workspace_root = workspace_root
        self._download_thread = None
        self._service = None
        self._is_downloading = False

        self.setWindowTitle("📥 TankVideo – Tải Video Từ Mạng Xã Hội")
        self.setMinimumSize(780, 620)
        self.resize(850, 680)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {self._BG};
                color: {self._TEXT};
            }}
            QWidget {{
                color: {self._TEXT};
            }}
        """)

        self._sig_progress.connect(self._on_progress_update)
        self._sig_log.connect(self._on_log_message)
        self._sig_done.connect(self._on_download_done)

        self._build_ui()

    # ================================================================== #
    #  UI Construction                                                    #
    # ================================================================== #
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        # ---- Header ----
        header = QHBoxLayout()
        header.setSpacing(12)

        icon_lbl = QLabel("📥")
        icon_lbl.setFixedSize(48, 48)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {self._ORANGE}, stop:1 #e04800);
            border-radius: 24px; font-size: 24px;
        """)
        header.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_lbl = QLabel("TẢI VIDEO TỪ MẠNG XÃ HỘI")
        title_lbl.setStyleSheet(f"font-size: 18px; font-weight: 900; color: {self._TEXT}; letter-spacing: 1px;")
        title_col.addWidget(title_lbl)

        sub_lbl = QLabel("Không logo • Không watermark • HD/Full HD • Tải siêu nhanh")
        sub_lbl.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {self._ORANGE};")
        title_col.addWidget(sub_lbl)
        header.addLayout(title_col, 1)
        root.addLayout(header)

        # ---- Platform badges ----
        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        platforms = [
            ("🎬 YouTube", "#ff0000", "#3b0000", "#7f1d1d"),
            ("🎵 TikTok", "#00f2ea", "#002b2a", "#065f5e"),
            ("📱 Douyin", "#161823", "#94a3b8", "#334155"),
            ("📺 Bilibili", "#00a1d6", "#002940", "#0e4a6e"),
            ("📕 Xiaohongshu", "#ff2442", "#3b0008", "#7f1d2d"),
        ]
        for label, text_color, bg, border in platforms:
            badge = QLabel(label)
            badge.setStyleSheet(
                f"color: {text_color}; background: {bg}; border: 1px solid {border}; "
                f"border-radius: 6px; padding: 4px 10px; font-size: 11px; font-weight: 700;"
            )
            badge_row.addWidget(badge)
        badge_row.addStretch()
        root.addLayout(badge_row)

        root.addWidget(_sep_line(self))

        # ---- Mode selection ----
        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        mode_label = QLabel("Chế độ tải:")
        mode_label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {self._TEXT};")
        mode_row.addWidget(mode_label)

        self.radio_single = QRadioButton("📹 Tải từng video")
        self.radio_single.setChecked(True)
        self.radio_single.setStyleSheet(self._radio_style())
        mode_row.addWidget(self.radio_single)

        self.radio_channel = QRadioButton("📺 Tải toàn bộ kênh")
        self.radio_channel.setStyleSheet(self._radio_style())
        mode_row.addWidget(self.radio_channel)
        mode_row.addStretch()
        root.addLayout(mode_row)

        # ---- URL input ----
        url_card = QFrame(self)
        url_card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD}; border: 1px solid {self._BORDER};
                border-radius: 12px;
            }}
        """)
        url_layout = QVBoxLayout(url_card)
        url_layout.setContentsMargins(16, 14, 16, 14)
        url_layout.setSpacing(10)

        url_label = QLabel("🔗 Nhập link video hoặc link kênh")
        url_label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {self._ACCENT};")
        url_layout.addWidget(url_label)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Dán link vào đây... (VD: https://www.tiktok.com/@username)")
        self.url_input.setMinimumHeight(42)
        self.url_input.setStyleSheet(f"""
            QLineEdit {{
                background: #060911; color: {self._TEXT}; border: 1px solid {self._BORDER};
                border-radius: 8px; padding: 8px 14px; font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {self._ACCENT};
            }}
        """)
        input_row.addWidget(self.url_input, 1)

        self.btn_paste = QPushButton("📋 Dán")
        self.btn_paste.setMinimumHeight(42)
        self.btn_paste.setCursor(Qt.PointingHandCursor)
        self.btn_paste.setStyleSheet(f"""
            QPushButton {{
                background: #1e293b; color: {self._MUTED}; font-weight: 700; font-size: 12px;
                border-radius: 8px; border: 1px solid {self._BORDER}; padding: 6px 14px;
            }}
            QPushButton:hover {{ background: #334155; color: {self._TEXT}; }}
        """)
        self.btn_paste.clicked.connect(self._on_paste)
        input_row.addWidget(self.btn_paste)
        url_layout.addLayout(input_row)

        # Settings row 1: Quality + Browser selection
        settings_row_1 = QHBoxLayout()
        settings_row_1.setSpacing(12)

        # Quality
        q_label = QLabel("Chất lượng:")
        q_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {self._MUTED};")
        settings_row_1.addWidget(q_label)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["Cao nhất (Best)", "Full HD (1080p)", "HD (720p)", "SD (480p)"])
        self.quality_combo.setMinimumHeight(36)
        self.quality_combo.setStyleSheet(f"""
            QComboBox {{
                background: #060911; color: {self._TEXT}; border: 1px solid {self._BORDER};
                border-radius: 6px; padding: 4px 12px; font-size: 12px; min-width: 140px;
            }}
            QComboBox:hover {{ border-color: {self._ACCENT}; }}
            QComboBox::drop-down {{
                border: none; width: 28px;
            }}
            QComboBox QAbstractItemView {{
                background: #0f172a; color: {self._TEXT}; border: 1px solid {self._BORDER};
                selection-background-color: #1e3a5f;
            }}
        """)
        settings_row_1.addWidget(self.quality_combo)

        settings_row_1.addSpacing(16)

        # Browser
        b_label = QLabel("Trình duyệt:")
        b_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {self._MUTED};")
        settings_row_1.addWidget(b_label)

        self.browser_combo = QComboBox()
        self.browser_combo.setMinimumHeight(36)
        self.browser_combo.setStyleSheet(f"""
            QComboBox {{
                background: #060911; color: {self._TEXT}; border: 1px solid {self._BORDER};
                border-radius: 6px; padding: 4px 12px; font-size: 12px; min-width: 220px;
            }}
            QComboBox:hover {{ border-color: {self._ACCENT}; }}
            QComboBox::drop-down {{
                border: none; width: 28px;
            }}
            QComboBox QAbstractItemView {{
                background: #0f172a; color: {self._TEXT}; border: 1px solid {self._BORDER};
                selection-background-color: #1e3a5f;
            }}
        """)
        self._populate_browsers()
        settings_row_1.addWidget(self.browser_combo, 1)

        url_layout.addLayout(settings_row_1)

        # Settings row 2: Output dir
        settings_row_2 = QHBoxLayout()
        settings_row_2.setSpacing(12)

        dir_label = QLabel("Thư mục lưu:")
        dir_label.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {self._MUTED};")
        settings_row_2.addWidget(dir_label)

        self.dir_input = QLineEdit()
        default_dir = os.path.join(self._workspace_root or os.path.expanduser("~"), "downloads_video")
        self.dir_input.setText(default_dir)
        self.dir_input.setMinimumHeight(36)
        self.dir_input.setStyleSheet(f"""
            QLineEdit {{
                background: #060911; color: {self._TEXT}; border: 1px solid {self._BORDER};
                border-radius: 6px; padding: 4px 10px; font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {self._ACCENT}; }}
        """)
        settings_row_2.addWidget(self.dir_input, 1)

        self.btn_browse = QPushButton("📁")
        self.btn_browse.setFixedSize(36, 36)
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.setStyleSheet(f"""
            QPushButton {{
                background: #1e293b; color: {self._MUTED}; font-size: 16px;
                border-radius: 6px; border: 1px solid {self._BORDER};
            }}
            QPushButton:hover {{ background: #334155; }}
        """)
        self.btn_browse.clicked.connect(self._on_browse)
        settings_row_2.addWidget(self.btn_browse)

        url_layout.addLayout(settings_row_2)
        root.addWidget(url_card)

        # ---- Action buttons ----
        action_row = QHBoxLayout()
        action_row.setSpacing(12)

        self.btn_download = QPushButton("⚡ BẮT ĐẦU TẢI")
        self.btn_download.setMinimumHeight(48)
        self.btn_download.setCursor(Qt.PointingHandCursor)
        self.btn_download.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {self._ORANGE}, stop:1 #e04800);
                color: #ffffff; font-weight: 900; font-size: 15px;
                border: 1px solid #ff9d42; border-radius: 10px; padding: 8px 32px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #ff8c33, stop:1 #f05400);
                border-color: #ffb366;
            }}
            QPushButton:disabled {{
                background: #1e293b; color: #475569; border-color: {self._BORDER};
            }}
        """)
        self.btn_download.clicked.connect(self._on_start_download)
        action_row.addWidget(self.btn_download, 1)

        self.btn_cancel = QPushButton("✕ Hủy tải")
        self.btn_cancel.setMinimumHeight(48)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: #251419; color: {self._RED}; font-weight: 700; font-size: 13px;
                border: 1px solid #7f1d1d; border-radius: 10px; padding: 8px 24px;
            }}
            QPushButton:hover {{ background: #3b141e; color: #fca5a5; }}
            QPushButton:disabled {{ background: #1e293b; color: #475569; border-color: {self._BORDER}; }}
        """)
        self.btn_cancel.clicked.connect(self._on_cancel)
        action_row.addWidget(self.btn_cancel)

        self.btn_open_folder = QPushButton("📂 Mở thư mục")
        self.btn_open_folder.setMinimumHeight(48)
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.setStyleSheet(f"""
            QPushButton {{
                background: #064e3b; color: {self._GREEN}; font-weight: 700; font-size: 13px;
                border: 1px solid #059669; border-radius: 10px; padding: 8px 24px;
            }}
            QPushButton:hover {{ background: #065f46; color: #ffffff; border-color: #10b981; }}
        """)
        self.btn_open_folder.clicked.connect(self._on_open_folder)
        action_row.addWidget(self.btn_open_folder)

        root.addLayout(action_row)

        # ---- Progress section ----
        progress_card = QFrame(self)
        progress_card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD}; border: 1px solid {self._BORDER};
                border-radius: 12px;
            }}
        """)
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(16, 12, 16, 12)
        progress_layout.setSpacing(8)

        self.status_label = QLabel("⏳ Sẵn sàng – Nhập link và bấm 'Bắt đầu tải'")
        self.status_label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {self._ACCENT};")
        progress_layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(22)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: #060911; border: 1px solid {self._BORDER};
                border-radius: 6px; text-align: center; color: {self._TEXT};
                font-size: 11px; font-weight: 700;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {self._ORANGE}, stop:1 #e04800);
                border-radius: 5px;
            }}
        """)
        progress_layout.addWidget(self.progress_bar)

        # Speed / ETA row
        info_row = QHBoxLayout()
        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet(f"font-size: 11px; color: {self._MUTED};")
        info_row.addWidget(self.speed_label)
        info_row.addStretch()
        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet(f"font-size: 11px; color: {self._MUTED};")
        info_row.addWidget(self.eta_label)
        progress_layout.addLayout(info_row)

        root.addWidget(progress_card)

        # ---- Log area ----
        log_label = QLabel("📋 Nhật ký tải")
        log_label.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {self._MUTED};")
        root.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(140)
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background: #060911; color: {self._MUTED}; border: 1px solid {self._BORDER};
                border-radius: 8px; padding: 8px; font-size: 11px; font-family: Consolas, monospace;
            }}
        """)
        root.addWidget(self.log_text)

    # ================================================================== #
    #  Helpers                                                            #
    # ================================================================== #
    def _radio_style(self):
        return f"""
            QRadioButton {{
                color: {self._TEXT}; font-size: 13px; font-weight: 600; spacing: 6px;
            }}
            QRadioButton::indicator {{
                width: 16px; height: 16px;
            }}
            QRadioButton::indicator:unchecked {{
                border: 2px solid {self._BORDER}; border-radius: 8px; background: #060911;
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {self._ORANGE}; border-radius: 8px;
                background: {self._ORANGE};
            }}
        """

    def _quality_key(self) -> str:
        idx = self.quality_combo.currentIndex()
        return ["best", "1080p", "720p", "480p"][idx]

    @staticmethod
    def _format_bytes(b: float) -> str:
        if b <= 0:
            return ""
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    @staticmethod
    def _format_speed(b: float) -> str:
        if b <= 0:
            return ""
        for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB/s"

    @staticmethod
    def _format_eta(seconds: int) -> str:
        if seconds <= 0:
            return ""
        m, s = divmod(int(seconds), 60)
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"

    # ================================================================== #
    #  Button handlers                                                    #
    # ================================================================== #
    def _on_paste(self):
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self.url_input.setText(text)

    def _on_browse(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video", self.dir_input.text())
        if d:
            self.dir_input.setText(d)

    def _on_open_folder(self):
        target = self.dir_input.text().strip()
        if target and os.path.isdir(target):
            if hasattr(os, "startfile"):
                os.startfile(target)
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _on_cancel(self):
        if self._service:
            self._service.cancel()
            self._log("⛔ Đang hủy tải...")

    def _populate_browsers(self):
        try:
            from app.services.video_downloader_service import get_available_browsers
            available = get_available_browsers()
        except Exception:
            available = []

        self.browser_combo.clear()
        names = [b["name"] for b in available]
        if names:
            auto_label = f"Tự động ({' / '.join(names)})"
        else:
            auto_label = "Tự động phát hiện"

        self.browser_combo.addItem(f"⚡ {auto_label}", "auto")
        for b in available:
            b_id = b["id"]
            b_name = b["name"]
            icon = "🟢" if b_id == "coccoc" else "🌐"
            self.browser_combo.addItem(f"{icon} {b_name}", b_id)

    def _on_start_download(self):
        raw_text = self.url_input.text().strip()
        if not raw_text:
            self.status_label.setText("⚠️ Vui lòng nhập link video hoặc link kênh!")
            self.status_label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {self._RED};")
            return

        # Auto-extract URL from share text (Douyin, TikTok, etc.)
        from app.services.video_downloader_service import extract_url_from_text
        url = extract_url_from_text(raw_text)

        output_dir = self.dir_input.text().strip()
        if not output_dir:
            output_dir = os.path.join(self._workspace_root or os.path.expanduser("~"), "downloads_video")
            self.dir_input.setText(output_dir)

        quality = self._quality_key()
        is_channel = self.radio_channel.isChecked()
        browser_id = self.browser_combo.currentData() or "auto"
        browser_text = self.browser_combo.currentText()

        # Reset UI
        self.progress_bar.setValue(0)
        self.speed_label.setText("")
        self.eta_label.setText("")
        self.log_text.clear()
        self._set_downloading(True)

        from app.services.video_downloader_service import VideoDownloaderService, detect_platform
        platform = detect_platform(url)

        # Show extracted URL if it differs from raw input
        if url != raw_text:
            self._log(f"🔗 Đã trích xuất URL: {url}")
            self.url_input.setText(url)

        self._log(f"🔍 Nền tảng: {platform.upper()}")
        self._log(f"📂 Thư mục lưu: {output_dir}")
        self._log(f"🎬 Chất lượng: {quality}")
        self._log(f"🌐 Trình duyệt: {browser_text}")
        self._log(f"📥 Chế độ: {'Toàn bộ kênh' if is_channel else 'Từng video'}")
        self._log("─" * 50)

        self._service = VideoDownloaderService(output_dir, preferred_browser=browser_id)

        def _worker():
            try:
                if is_channel:
                    result = self._service.download_channel(
                        url, output_dir, quality, self._thread_progress_callback
                    )
                else:
                    result = self._service.download_single(
                        url, output_dir, quality, self._thread_progress_callback
                    )
                self._sig_done.emit(result)
            except Exception as exc:
                self._sig_done.emit({"success": False, "error": str(exc), "files": []})

        self._download_thread = threading.Thread(target=_worker, daemon=True)
        self._download_thread.start()

    # ================================================================== #
    #  Thread-safe callbacks                                              #
    # ================================================================== #
    def _thread_progress_callback(self, progress):
        """Called from download thread – emit signal for main thread."""
        self._sig_progress.emit({
            "status": progress.status,
            "percent": progress.percent,
            "speed": progress.speed,
            "eta": progress.eta,
            "title": progress.title,
            "video_index": progress.video_index,
            "video_total": progress.video_total,
            "downloaded_bytes": progress.downloaded_bytes,
            "total_bytes": progress.total_bytes,
        })

    def _on_progress_update(self, data: dict):
        """Slot: update UI from progress data."""
        percent = int(data.get("percent", 0))
        self.progress_bar.setValue(min(100, percent))

        title = data.get("title", "")
        idx = data.get("video_index", 0)
        total = data.get("video_total", 0)
        status = data.get("status", "")

        if total > 1:
            self.status_label.setText(f"📥 [{idx}/{total}] {title}")
        elif title:
            self.status_label.setText(f"📥 {title}")
        else:
            self.status_label.setText(f"📥 Đang tải... {percent}%")
        self.status_label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {self._ACCENT};")

        speed = data.get("speed", 0)
        eta = data.get("eta", 0)
        dl_bytes = data.get("downloaded_bytes", 0)
        total_bytes = data.get("total_bytes", 0)

        speed_text = self._format_speed(speed) if speed else ""
        dl_text = self._format_bytes(dl_bytes) if dl_bytes else ""
        total_text = self._format_bytes(total_bytes) if total_bytes else ""
        if dl_text and total_text:
            self.speed_label.setText(f"🚀 {speed_text}  •  {dl_text} / {total_text}")
        elif speed_text:
            self.speed_label.setText(f"🚀 {speed_text}")

        if eta:
            self.eta_label.setText(f"⏱️ Còn ~{self._format_eta(eta)}")
        else:
            self.eta_label.setText("")

        if status == "finished" and total <= 1:
            self._log(f"✅ Hoàn tất: {title}")

    def _on_log_message(self, msg: str):
        self.log_text.append(msg)

    def _on_download_done(self, result: dict):
        """Slot: download finished."""
        self._set_downloading(False)

        success = result.get("success", False)
        files = result.get("files", [])
        error = result.get("error", "")
        channel = result.get("channel_name", "") or result.get("channel", "")
        downloaded = result.get("downloaded", len(files))
        total = result.get("total", 0)

        self._log("─" * 50)

        if success:
            self.progress_bar.setValue(100)
            if channel:
                self.status_label.setText(f"✅ Hoàn tất! Đã tải {downloaded}/{total} video từ kênh {channel}")
            else:
                self.status_label.setText(f"✅ Hoàn tất! Đã tải {len(files)} video thành công")
            self.status_label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {self._GREEN};")

            for f in files:
                self._log(f"  📄 {os.path.basename(f)}")

            if result.get("output_dir"):
                self.dir_input.setText(result["output_dir"])

            self._log(f"\n🎉 Tải thành công {downloaded} video!")
        else:
            self.status_label.setText(f"❌ Lỗi: {error[:100]}")
            self.status_label.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {self._RED};")
            self._log(f"❌ Lỗi: {error}")

    # ================================================================== #
    #  Internal helpers                                                   #
    # ================================================================== #
    def _log(self, msg: str):
        """Thread-safe log appender."""
        if threading.current_thread() is threading.main_thread():
            self.log_text.append(msg)
        else:
            self._sig_log.emit(msg)

    def _set_downloading(self, active: bool):
        self._is_downloading = active
        self.btn_download.setEnabled(not active)
        self.btn_cancel.setEnabled(active)
        self.url_input.setEnabled(not active)
        self.quality_combo.setEnabled(not active)
        self.dir_input.setEnabled(not active)
        self.radio_single.setEnabled(not active)
        self.radio_channel.setEnabled(not active)

    def closeEvent(self, event):
        if self._is_downloading and self._service:
            self._service.cancel()
        super().closeEvent(event)
