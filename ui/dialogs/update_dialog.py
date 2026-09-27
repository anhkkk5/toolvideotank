"""TankVideo Auto-Update Dialog (Giao diện Kiểm tra & Cập nhật tự động)."""

from __future__ import annotations

import os
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from app.services.update_service import UpdateService
from app.version import APP_VERSION


class CheckUpdateWorker(QThread):
    finished = Signal(dict)

    def __init__(self, workspace_root: str):
        super().__init__()
        self.workspace_root = workspace_root

    def run(self):
        service = UpdateService(self.workspace_root)
        info = service.check_for_updates()
        self.finished.emit(info)


class DownloadUpdateWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(self, workspace_root: str, download_url: str):
        super().__init__()
        self.workspace_root = workspace_root
        self.download_url = download_url

    def run(self):
        service = UpdateService(self.workspace_root)
        success, msg = service.download_and_install_patch(
            self.download_url,
            progress_cb=self.progress.emit,
        )
        self.finished.emit(success, msg)


class UpdateDialog(QDialog):
    def __init__(
        self,
        parent=None,
        workspace_root: str = "",
        auto_check: bool = False,
        mandatory: bool = False,
        preloaded_info: dict | None = None,
    ):
        super().__init__(parent)
        self.workspace_root = workspace_root or os.getcwd()
        self.auto_check = auto_check
        self.mandatory = mandatory
        self.preloaded_info = preloaded_info
        self.update_info = preloaded_info or {}

        if self.mandatory:
            self.setWindowTitle("🚨 BẮT BUỘC CẬP NHẬT PHIÊN BẢN MỚI - TankVideo Studio")
        else:
            self.setWindowTitle("Cập nhật phần mềm - TankVideo Studio")
        self.setFixedSize(560, 460)
        self.setStyleSheet("""
            QDialog {
                background-color: #0b1120;
                color: #e2e8f0;
            }
            QLabel {
                color: #e2e8f0;
            }
            QTextEdit {
                background-color: #050811;
                border: 1px solid #1e293b;
                border-radius: 8px;
                color: #cbd5e1;
                font-size: 12px;
                padding: 8px;
            }
            QProgressBar {
                background-color: #1e293b;
                border: none;
                border-radius: 6px;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
                height: 14px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7b1a, stop:1 #e04800);
                border-radius: 6px;
            }
        """)

        self._build_ui()
        if self.preloaded_info:
            self._on_check_finished(self.preloaded_info)
        else:
            self._start_check()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Cảnh báo bắt buộc cập nhật (nếu bật chế độ mandatory)
        if self.mandatory:
            self.alert_banner = QLabel("⚠️ BẮT BUỘC CẬP NHẬT: Phiên bản hiện tại đã hết hạn sử dụng.\nBạn phải cập nhật lên bản mới nhất thì mới có thể sử dụng tool!")
            self.alert_banner.setStyleSheet("""
                background-color: #2e0808;
                color: #fca5a5;
                border: 1px solid #dc2626;
                border-radius: 8px;
                padding: 10px 14px;
                font-weight: bold;
                font-size: 12px;
            """)
            self.alert_banner.setWordWrap(True)
            layout.addWidget(self.alert_banner)

        # Header Title
        self.title_lbl = QLabel("🔍 Đang kiểm tra bản cập nhật...")
        self.title_lbl.setStyleSheet("font-size: 17px; font-weight: 800; color: #f8fafc;")
        layout.addWidget(self.title_lbl)

        # Subtitle / Version info
        self.version_lbl = QLabel(f"Phiên bản hiện tại: v{APP_VERSION}")
        self.version_lbl.setStyleSheet("font-size: 12px; color: #94a3b8; font-weight: 600;")
        layout.addWidget(self.version_lbl)

        # Release Notes / Description Text Box
        self.notes_box = QTextEdit()
        self.notes_box.setReadOnly(True)
        self.notes_box.setPlaceholderText("Đang kiểm tra thông tin bản cập nhật mới nhất...")
        layout.addWidget(self.notes_box, 1)

        # Progress bar (Hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_msg = QLabel("")
        self.status_msg.setStyleSheet("font-size: 11px; color: #ff9d42; font-weight: 600;")
        self.status_msg.hide()
        layout.addWidget(self.status_msg)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Đóng" if not self.mandatory else "❌ Thoát ứng dụng")
        self.cancel_btn.setMinimumWidth(110)
        self.cancel_btn.setMinimumHeight(38)
        if self.mandatory:
            self.cancel_btn.setStyleSheet("""
                QPushButton {
                    background: #2d0e0e; color: #fca5a5; border: 1px solid #7f1d1d;
                    border-radius: 8px; padding: 6px 16px; font-weight: 700; font-size: 12px;
                }
                QPushButton:hover { background: #451414; color: #ffffff; border-color: #ef4444; }
            """)
        else:
            self.cancel_btn.setStyleSheet("""
                QPushButton {
                    background: #1e293b; color: #94a3b8; border: 1px solid #334155;
                    border-radius: 8px; padding: 6px 18px; font-weight: 700; font-size: 12px;
                }
                QPushButton:hover { background: #334155; color: #f8fafc; }
            """)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.update_btn = QPushButton("🚀 Cập nhật ngay")
        self.update_btn.setMinimumWidth(160)
        self.update_btn.setMinimumHeight(38)
        self.update_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7b1a, stop:1 #e04800);
                color: #ffffff; border: 1px solid #ff9d42;
                border-radius: 8px; padding: 6px 20px; font-weight: 800; font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff8c33, stop:1 #f05400);
            }
            QPushButton:disabled { background: #334155; color: #64748b; border: none; }
        """)
        self.update_btn.setEnabled(False)
        self.update_btn.clicked.connect(self._on_update_clicked)
        btn_row.addWidget(self.update_btn)

        layout.addLayout(btn_row)

    def _start_check(self):
        self.worker = CheckUpdateWorker(self.workspace_root)
        self.worker.finished.connect(self._on_check_finished)
        self.worker.start()

    def _on_check_finished(self, info: dict):
        self.update_info = info
        if info.get("error"):
            if self.mandatory:
                # Nếu mất kết nối mạng ở chế độ bắt buộc, tạm thời cho phép vào app
                self.accept()
                return
            self.title_lbl.setText("⚠️ Không thể kiểm tra cập nhật")
            self.notes_box.setText(f"Không thể kết nối máy chủ cập nhật:\n{info['error']}\n\nVui lòng kiểm tra lại kết nối mạng Internet.")
            self.update_btn.setEnabled(False)
            return

        if not info.get("has_update"):
            if self.mandatory:
                # Đang ở bản mới nhất, tự động đóng để mở app
                self.accept()
                return
            self.title_lbl.setText("✅ Bạn đang dùng phiên bản mới nhất!")
            self.version_lbl.setText(f"Phiên bản hiện tại: v{APP_VERSION} (Mới nhất)")
            self.notes_box.setText("Phần mềm của bạn đã được cập nhật tất cả tính năng, giọng đọc và sửa lỗi mới nhất.\n\nKhông có bản cập nhật mới nào tại thời điểm này.")
            self.update_btn.hide()
            self.cancel_btn.setText("Đồng ý")
            return

        # Có bản cập nhật mới!
        latest = info.get("latest_version", "")
        if self.mandatory:
            self.title_lbl.setText(f"🚨 YÊU CẦU CẬP NHẬT PHIÊN BẢN {latest}!")
            self.title_lbl.setStyleSheet("font-size: 17px; font-weight: 800; color: #f87171;")
            self.version_lbl.setText(f"Hiện tại: v{APP_VERSION} ➔ Bắt buộc cập nhật lên: {latest}")
            self.version_lbl.setStyleSheet("font-size: 12px; color: #fbbf24; font-weight: bold;")
        else:
            self.title_lbl.setText(f"🎉 Đã có bản cập nhật mới {latest}!")
            self.version_lbl.setText(f"Hiện tại: v{APP_VERSION} ➔ Mới nhất: {latest}")

        body = info.get("body", "").strip() or "Bản cập nhật cải thiện tính năng và tối ưu hiệu suất."
        size_mb = info.get("size_mb", 0)
        size_text = f"Dung lượng bản vá: ~{size_mb} MB (Cập nhật 1-Click tự động trong 5 giây)\n\n" if size_mb else ""
        self.notes_box.setText(f"{size_text}Nội dung cập nhật mới:\n{body}")

        self.update_btn.setEnabled(True)
        target_url = info.get("download_url", "") or info.get("patch_url", "")
        if info.get("is_direct_zip"):
            self.update_btn.setText("🚀 CẬP NHẬT NGAY (1-CLICK)")
        elif "drive.google.com" in target_url:
            self.update_btn.setText("🌐 Tải từ Google Drive")
        else:
            self.update_btn.setText("🌐 Mở trang tải về")

    def reject(self):
        if self.mandatory and self.update_info.get("has_update"):
            ret = QMessageBox.question(
                self,
                "Bắt buộc cập nhật",
                f"Đã có phiên bản mới ({self.update_info.get('latest_version', '')}).\n\n"
                "Bạn bắt buộc phải cập nhật lên phiên bản mới nhất thì mới có thể sử dụng TankVideo Studio.\n\n"
                "Bạn có chắc chắn muốn thoát ứng dụng không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ret == QMessageBox.Yes:
                super().reject()
                import sys
                sys.exit(0)
            return
        super().reject()

    def closeEvent(self, event):
        if self.mandatory and self.update_info.get("has_update"):
            ret = QMessageBox.question(
                self,
                "Bắt buộc cập nhật",
                f"Đã có phiên bản mới ({self.update_info.get('latest_version', '')}).\n\n"
                "Bạn bắt buộc phải cập nhật lên phiên bản mới nhất thì mới có thể sử dụng TankVideo Studio.\n\n"
                "Bạn có chắc chắn muốn thoát ứng dụng không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ret == QMessageBox.Yes:
                event.accept()
                import sys
                sys.exit(0)
            else:
                event.ignore()
                return
        super().closeEvent(event)

    def _on_update_clicked(self):
        download_url = self.update_info.get("download_url", "")
        is_direct = self.update_info.get("is_direct_zip", False)

        if not is_direct:
            # Mở link trình duyệt (GitHub Release hoặc Google Drive)
            url_to_open = download_url or self.update_info.get("release_url", "")
            QDesktopServices.openUrl(QUrl(url_to_open))
            if self.mandatory:
                QMessageBox.information(
                    self,
                    "Tải bản cập nhật",
                    "Trình duyệt web đã được mở để bạn tải bản cập nhật mới.\n\n"
                    "Vui lòng tải về và cài đặt bản mới trước khi mở lại phần mềm.",
                )
                import sys
                sys.exit(0)
            self.accept()
            return

        # Tải bản vá tự động
        self.update_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_msg.show()
        self.status_msg.setText("Đang bắt đầu tải bản cập nhật...")

        self.dl_worker = DownloadUpdateWorker(self.workspace_root, download_url)
        self.dl_worker.progress.connect(self._on_download_progress)
        self.dl_worker.finished.connect(self._on_download_finished)
        self.dl_worker.start()

    def _on_download_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(max(0, min(100, pct)))
        self.status_msg.setText(msg)

    def _on_download_finished(self, success: bool, msg: str):
        self.cancel_btn.setEnabled(True)
        if not success:
            self.status_msg.setText(f"❌ {msg}")
            self.update_btn.setEnabled(True)
            QMessageBox.warning(self, "Lỗi cập nhật", f"Không thể hoàn tất cập nhật:\n\n{msg}")
            return

        self.status_msg.setText("✅ " + msg)
        # Tự động thoát ngay lập tức để script apply_update.bat ghi đè file và mở lại app
        import os
        import time
        time.sleep(0.5)
        os._exit(0)


def check_mandatory_update_gate(parent=None, workspace_root: str = "") -> bool:
    """Kiểm tra bản cập nhật bắt buộc tại cửa ngõ khởi động ứng dụng.

    - Nếu có bản cập nhật mới: Hiển thị hộp thoại bắt buộc cập nhật.
      Người dùng chỉ có thể chọn Cập nhật ngay hoặc Thoát ứng dụng.
      Nếu không cập nhật -> Trả về False (đóng ứng dụng).
    - Nếu không có bản cập nhật mới (hoặc mất mạng): Trả về True (cho phép vào app).
    """
    try:
        from app.services.update_service import UpdateService
        svc = UpdateService(workspace_root)
        info = svc.check_for_updates(timeout=4.0)
        if info.get("has_update"):
            dlg = UpdateDialog(parent, workspace_root=workspace_root, mandatory=True, preloaded_info=info)
            res = dlg.exec()
            # Nếu tải thành công thì _on_download_finished đã tự restart app.
            # Nếu dialog đóng mà chưa update -> return False để thoát
            return False
    except Exception:
        pass
    return True

