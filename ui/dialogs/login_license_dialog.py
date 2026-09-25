"""TankVideo Login & License Activation Dialog.

Allows users to view their Machine ID, log in with Email & Password,
and activate their monthly subscription license key.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.license_service import LicenseService, get_hardware_machine_id


class LoginLicenseDialog(QDialog):
    """Hộp thoại Đăng nhập & Kích hoạt bản quyền TankVideo."""

    def __init__(self, parent: QWidget | None = None, workspace_root: str | None = None):
        super().__init__(parent)
        self.workspace_root = workspace_root or os.getcwd()
        self.license_service = LicenseService(self.workspace_root)
        self.machine_id = self.license_service.machine_id

        self.setWindowTitle("TankVideo - Đăng nhập & Kích hoạt bản quyền")
        self.setFixedSize(540, 680)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._apply_dark_theme()
        self._init_ui()
        self._refresh_status()

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #0f1318;
                color: #e6edf3;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            }
            QFrame#cardFrame {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 12px;
            }
            QLabel {
                color: #e6edf3;
            }
            QLineEdit {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 10px 14px;
                color: #f0f6fc;
                font-size: 13px;
                selection-background-color: #ff6600;
            }
            QLineEdit:focus {
                border: 1px solid #ff7b1a;
                background-color: #11161d;
            }
            QPushButton#primaryActionBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6600, stop:1 #e04400);
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid #ff8833;
                border-radius: 8px;
                padding: 12px;
            }
            QPushButton#primaryActionBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff771a, stop:1 #f05000);
                border-color: #ffa352;
            }
            QPushButton#secondaryBtn {
                background-color: #21262d;
                color: #c9d1d9;
                border: 1px solid #363b42;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #30363d;
                color: #ffffff;
                border-color: #8b949e;
            }
        """)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # 1. Header (Logo + Brand)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        logo_label = QLabel()
        logo_label.setFixedSize(40, 40)
        logo_label.setAlignment(Qt.AlignCenter)
        tank_logo_path = os.path.join(self.workspace_root, "assets", "tankvideo.png")
        if os.path.exists(tank_logo_path):
            logo_pix = QPixmap(tank_logo_path)
            if not logo_pix.isNull():
                logo_label.setPixmap(logo_pix.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header_layout.addWidget(logo_label)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)
        brand_lbl = QLabel("<span style='color:#f1f5f9; font-size:20px; font-weight:900;'>TANK</span><span style='color:#ff7b1a; font-size:20px; font-weight:900;'>VIDEO</span> <span style='color:#8b949e; font-size:13px;'>SAAS LICENSE</span>")
        brand_lbl.setTextFormat(Qt.RichText)
        sub_lbl = QLabel("Hệ thống bản quyền & Đăng nhập người dùng")
        sub_lbl.setStyleSheet("color: #8b949e; font-size: 12px;")
        title_vbox.addWidget(brand_lbl)
        title_vbox.addWidget(sub_lbl)
        header_layout.addLayout(title_vbox, 1)

        main_layout.addLayout(header_layout)

        # 2. Khung trạng thái bản quyền hiện tại
        self.status_card = QFrame()
        self.status_card.setObjectName("cardFrame")
        status_card_layout = QVBoxLayout(self.status_card)
        status_card_layout.setContentsMargins(16, 14, 16, 14)
        status_card_layout.setSpacing(6)

        self.lbl_status_badge = QLabel("Chưa kích hoạt bản quyền")
        self.lbl_status_badge.setStyleSheet("font-size: 14px; font-weight: bold; color: #f85149;")
        status_card_layout.addWidget(self.lbl_status_badge)

        self.lbl_status_desc = QLabel("Vui lòng nhập Email, Mật khẩu và License Key để kích hoạt phần mềm.")
        self.lbl_status_desc.setStyleSheet("color: #8b949e; font-size: 12px;")
        self.lbl_status_desc.setWordWrap(True)
        status_card_layout.addWidget(self.lbl_status_desc)

        main_layout.addWidget(self.status_card)

        # 3. Khung Mã máy (Machine ID)
        mid_card = QFrame()
        mid_card.setObjectName("cardFrame")
        mid_layout = QVBoxLayout(mid_card)
        mid_layout.setContentsMargins(16, 12, 16, 12)
        mid_layout.setSpacing(8)

        mid_header = QHBoxLayout()
        lbl_mid_title = QLabel("💻 Mã máy của bạn (Machine ID):")
        lbl_mid_title.setStyleSheet("font-weight: bold; font-size: 12px; color: #79c0ff;")
        mid_header.addWidget(lbl_mid_title, 1)

        btn_copy_mid = QPushButton("📋 Sao chép")
        btn_copy_mid.setObjectName("secondaryBtn")
        btn_copy_mid.setToolTip("Sao chép mã máy để gửi cho Admin cấp Key")
        btn_copy_mid.clicked.connect(self._copy_machine_id)
        mid_header.addWidget(btn_copy_mid)
        mid_layout.addLayout(mid_header)

        self.txt_machine_id = QLineEdit(self.machine_id)
        self.txt_machine_id.setReadOnly(True)
        self.txt_machine_id.setStyleSheet("background-color: #0d1117; color: #58a6ff; font-family: monospace; font-weight: bold;")
        mid_layout.addWidget(self.txt_machine_id)

        lbl_mid_hint = QLabel("Gửi mã máy này cho Admin khi mua gói tháng để khóa bản quyền an toàn.")
        lbl_mid_hint.setStyleSheet("color: #8b949e; font-size: 11px;")
        mid_layout.addWidget(lbl_mid_hint)

        main_layout.addWidget(mid_card)

        # 4. Form Đăng nhập & Kích hoạt
        form_card = QFrame()
        form_card.setObjectName("cardFrame")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(16, 14, 16, 14)
        form_layout.setSpacing(10)

        # Email
        lbl_email = QLabel("📧 Địa chỉ Gmail của bạn:")
        lbl_email.setStyleSheet("font-weight: 600; font-size: 12px; color: #c9d1d9;")
        form_layout.addWidget(lbl_email)
        self.input_email = QLineEdit()
        self.input_email.setPlaceholderText("vi-du: khachhang@gmail.com")
        form_layout.addWidget(self.input_email)

        # Password
        lbl_pass = QLabel("🔒 Mật khẩu tài khoản:")
        lbl_pass.setStyleSheet("font-weight: 600; font-size: 12px; color: #c9d1d9;")
        form_layout.addWidget(lbl_pass)
        self.input_password = QLineEdit()
        self.input_password.setEchoMode(QLineEdit.Password)
        self.input_password.setPlaceholderText("Nhập mật khẩu của bạn")
        form_layout.addWidget(self.input_password)

        # License Key (Tùy chọn cho ai dùng key offline)
        lbl_key = QLabel("🔑 Mã kích hoạt (Chỉ cần nếu dùng Key Offline):")
        lbl_key.setStyleSheet("font-weight: 600; font-size: 11px; color: #8b949e;")
        form_layout.addWidget(lbl_key)
        self.input_key = QLineEdit()
        self.input_key.setPlaceholderText("Bỏ trống để đăng nhập trực tuyến bằng Email & Mật khẩu")
        form_layout.addWidget(self.input_key)

        main_layout.addWidget(form_card)

        # 5. Nút Đăng nhập
        self.btn_activate = QPushButton("🚀 ĐĂNG NHẬP VÀO HỆ THỐNG")
        self.btn_activate.setObjectName("primaryActionBtn")
        self.btn_activate.setCursor(Qt.PointingHandCursor)
        self.btn_activate.clicked.connect(self._on_activate_clicked)
        main_layout.addWidget(self.btn_activate)

        # 6. Footer (Đăng xuất & Đóng)
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        self.btn_logout = QPushButton("🚪 Đăng xuất / Xóa thiết bị")
        self.btn_logout.setObjectName("secondaryBtn")
        self.btn_logout.clicked.connect(self._on_logout_clicked)
        footer_layout.addWidget(self.btn_logout)

        footer_layout.addStretch(1)

        self.btn_close = QPushButton("Đóng")
        self.btn_close.setObjectName("secondaryBtn")
        self.btn_close.clicked.connect(self.reject)
        footer_layout.addWidget(self.btn_close)

        main_layout.addLayout(footer_layout)

    def _copy_machine_id(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.machine_id)
        QMessageBox.information(
            self,
            "Đã sao chép",
            f"Đã sao chép mã máy:\n\n{self.machine_id}\n\nHãy gửi mã này cho Admin nếu cần reset thiết bị!",
        )

    def _refresh_status(self):
        status = self.license_service.get_license_status()
        if status["licensed"]:
            self.lbl_status_badge.setText(f"👑 BẢN QUYỀN VIP: {status['plan']}")
            self.lbl_status_badge.setStyleSheet("font-size: 14px; font-weight: bold; color: #3fb950;")
            
            desc = (
                f"Tài khoản: <b>{status['email']}</b><br>"
                f"Thời hạn còn lại: <b style='color:#ff7b1a;'>{status['days_left']} ngày</b> "
                f"(Hết hạn: {status['expires_at']})<br>"
                f"Trạng thái: Thiết bị hợp lệ ({status.get('message', '')})."
            )
            self.lbl_status_desc.setText(desc)
            self.lbl_status_desc.setTextFormat(Qt.RichText)
            self.input_email.setText(status["email"])
            self.btn_activate.setText("🔄 ĐĂNG NHẬP LẠI / GIA HẠN")
            self.btn_logout.setVisible(True)
        else:
            self.lbl_status_badge.setText("⚠️ CHƯA ĐĂNG NHẬP HOẶC HẾT HẠN")
            self.lbl_status_badge.setStyleSheet("font-size: 14px; font-weight: bold; color: #f85149;")
            self.lbl_status_desc.setText(status.get("message", "Nhập Email và Mật khẩu của bạn rồi bấm Đăng nhập."))
            self.btn_activate.setText("🚀 ĐĂNG NHẬP VÀO HỆ THỐNG")
            self.btn_logout.setVisible(False)

    def _on_activate_clicked(self):
        email = self.input_email.text().strip()
        pwd = self.input_password.text().strip()
        key = self.input_key.text().strip()

        if not email or "@" not in email:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập địa chỉ Email của bạn.")
            return

        if not pwd:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập mật khẩu tài khoản.")
            return

        self.btn_activate.setEnabled(False)
        self.btn_activate.setText("⏳ Đang kết nối Supabase Cloud...")
        QApplication.processEvents()

        try:
            if key:
                # Kích hoạt Offline bằng mã Key
                ok, msg = self.license_service.activate(email, pwd, key)
            else:
                # Đăng nhập trực tuyến qua Supabase Cloud
                ok, msg = self.license_service.login_supabase(email, pwd)

            if ok:
                QMessageBox.information(self, "Thành công", msg)
                self._refresh_status()
                self.input_key.clear()
                self.accept()
            else:
                QMessageBox.critical(self, "Đăng nhập thất bại", msg)
        finally:
            self.btn_activate.setEnabled(True)
            self._refresh_status()

    def _on_logout_clicked(self):
        reply = QMessageBox.question(
            self,
            "Xác nhận",
            "Bạn có chắc muốn đăng xuất và xóa bản quyền trên máy tính này không?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.license_service.logout()
            self._refresh_status()
            QMessageBox.information(self, "Đã đăng xuất", "Đã xóa bản quyền khỏi máy.")
