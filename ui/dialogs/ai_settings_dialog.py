from __future__ import annotations

import os
import sys
import threading
from PySide6.QtCore import Qt, QUrl, Signal, QObject
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QGroupBox,
    QFrame,
    QMessageBox,
    QWidget,
)


def _get_env_path(workspace_root: str) -> str:
    candidates = [
        os.path.join(workspace_root, ".env"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), ".env") if getattr(sys, "frozen", False) else "",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return os.path.join(workspace_root, ".env") if workspace_root else ".env"


def update_env_keys(workspace_root: str, updates: dict[str, str]) -> None:
    """Cập nhật các biến môi trường vào file .env và os.environ."""
    env_path = _get_env_path(workspace_root)
    lines: list[str] = []
    existing_keys: set[str] = set()

    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            lines = []

    updated_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _ = stripped.split("=", 1)
            key = key.strip()
            if key in updates:
                updated_lines.append(f"{key}={updates[key]}\n")
                existing_keys.add(key)
                continue
        updated_lines.append(line)

    # Thêm các key mới chưa có trong file .env
    for key, val in updates.items():
        if key not in existing_keys:
            updated_lines.append(f"{key}={val}\n")
        os.environ[key] = str(val)

    try:
        os.makedirs(os.path.dirname(os.path.abspath(env_path)), exist_ok=True)
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)
    except Exception as exc:
        print(f"[EnvUpdate] Error writing .env: {exc}")


class _ConnectionTesterSignals(QObject):
    finished = Signal(bool, str)


class AiSettingsDialog(QDialog):
    """Hộp thoại cấu hình Dịch thuật AI & Khóa API trực quan, hiện đại."""

    def __init__(self, parent: QWidget | None = None, workspace_root: str = ""):
        super().__init__(parent)
        self.workspace_root = workspace_root or os.getcwd()
        self.setWindowTitle("⚙️ Cài đặt Dịch thuật AI & Khóa API")
        self.resize(580, 520)
        self.setMinimumSize(540, 480)

        self._signals = _ConnectionTesterSignals()
        self._signals.finished.connect(self._on_test_finished)

        self._setup_ui()
        self._load_current_values()

    def _setup_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
            }
            QLabel {
                color: #e2e8f0;
                font-size: 13px;
            }
            QGroupBox {
                color: #38bdf8;
                font-weight: 700;
                font-size: 13px;
                border: 1px solid #1e293b;
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 14px;
                background-color: #131d33;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 14px;
                padding: 0 6px;
                color: #38bdf8;
            }
            QComboBox {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 13px;
                font-weight: 600;
            }
            QComboBox:hover {
                border-color: #38bdf8;
            }
            QLineEdit {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #38bdf8;
                background-color: #0f172a;
            }
            QPushButton {
                font-size: 13px;
                font-weight: 600;
                border-radius: 8px;
                padding: 8px 16px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header Title
        title_box = QHBoxLayout()
        icon_lbl = QLabel("🤖")
        icon_lbl.setStyleSheet("font-size: 24px;")
        title_box.addWidget(icon_lbl)

        title_text_layout = QVBoxLayout()
        title = QLabel("Cấu hình Dịch thuật AI & Khóa API")
        title.setStyleSheet("color: #f8fafc; font-size: 16px; font-weight: 800;")
        sub_title = QLabel("Thiết lập mô hình AI dùng để dịch kịch bản & phân vai lồng tiếng.")
        sub_title.setStyleSheet("color: #94a3b8; font-size: 12px;")
        title_text_layout.addWidget(title)
        title_text_layout.addWidget(sub_title)
        title_box.addLayout(title_text_layout)
        title_box.addStretch()
        layout.addLayout(title_box)

        # Provider Selector Box
        prov_box = QGroupBox("1. Chọn nhà cung cấp dịch thuật")
        prov_layout = QVBoxLayout(prov_box)
        prov_layout.setContentsMargins(14, 14, 14, 14)
        prov_layout.setSpacing(10)

        self.combo_provider = QComboBox()
        self.combo_provider.addItem("👑 DeepSeek AI (Khuyên dùng nhất cho phim Trung)", "deepseek")
        self.combo_provider.addItem("🟢 Google Dịch (Miễn phí 100%, không cần API Key)", "google")
        self.combo_provider.addItem("🔵 Google AI Studio (Gemini Flash)", "google_ai_studio")
        self.combo_provider.addItem("🟣 OpenAI (ChatGPT - GPT-4o-mini)", "openai")
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        prov_layout.addWidget(self.combo_provider)

        layout.addWidget(prov_box)

        # Details Box (Key, Model, Guide)
        self.details_box = QGroupBox("2. Thông tin Khóa API (API Key)")
        details_layout = QVBoxLayout(self.details_box)
        details_layout.setContentsMargins(14, 14, 14, 14)
        details_layout.setSpacing(10)

        # API Key input
        self.lbl_key = QLabel("Khóa API (API Key):")
        details_layout.addWidget(self.lbl_key)

        key_row = QHBoxLayout()
        self.edit_key = QLineEdit()
        self.edit_key.setEchoMode(QLineEdit.Password)
        self.edit_key.setPlaceholderText("Dán khóa API bắt đầu bằng sk-... vào đây")
        key_row.addWidget(self.edit_key, 1)

        self.btn_toggle_eye = QPushButton("👁️")
        self.btn_toggle_eye.setToolTip("Hiện / Ẩn khóa API")
        self.btn_toggle_eye.setStyleSheet("background-color: #334155; color: #f8fafc; padding: 6px 10px;")
        self.btn_toggle_eye.clicked.connect(self._toggle_key_visibility)
        key_row.addWidget(self.btn_toggle_eye)
        details_layout.addLayout(key_row)

        # Model Input (optional / editable)
        self.lbl_model = QLabel("Mô hình AI (Model):")
        self.edit_model = QLineEdit()
        details_layout.addWidget(self.lbl_model)
        details_layout.addWidget(self.edit_model)

        # Guide Link
        self.lbl_guide = QLabel()
        self.lbl_guide.setWordWrap(True)
        self.lbl_guide.setStyleSheet("color: #38bdf8; font-size: 11px; padding: 4px 0;")
        self.lbl_guide.setOpenExternalLinks(True)
        details_layout.addWidget(self.lbl_guide)

        # Test Connection button & status
        test_row = QHBoxLayout()
        self.btn_test = QPushButton("🔍 Kiểm tra kết nối")
        self.btn_test.setStyleSheet("""
            QPushButton {
                background-color: #1e3a8a; color: #93c5fd; border: 1px solid #2563eb;
            }
            QPushButton:hover { background-color: #1d4ed8; color: #fff; }
        """)
        self.btn_test.clicked.connect(self._test_connection)
        test_row.addWidget(self.btn_test)

        self.lbl_test_status = QLabel("")
        self.lbl_test_status.setStyleSheet("font-size: 11px; font-weight: 600;")
        test_row.addWidget(self.lbl_test_status, 1)
        details_layout.addLayout(test_row)

        layout.addWidget(self.details_box)

        layout.addStretch()

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton("Hủy bỏ")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #334155; color: #cbd5e1; border: 1px solid #475569;
            }
            QPushButton:hover { background-color: #475569; color: #fff; }
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("💾 Lưu cấu hình")
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1);
                color: #ffffff; border: 1px solid #38bdf8; padding: 8px 24px; font-weight: 700;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5e9, stop:1 #0284c7);
            }
        """)
        self.btn_save.clicked.connect(self._save_and_close)
        btn_row.addWidget(self.btn_save)

        layout.addLayout(btn_row)

    def _toggle_key_visibility(self):
        if self.edit_key.echoMode() == QLineEdit.Password:
            self.edit_key.setEchoMode(QLineEdit.Normal)
            self.btn_toggle_eye.setText("🔒")
        else:
            self.edit_key.setEchoMode(QLineEdit.Password)
            self.btn_toggle_eye.setText("👁️")

    def _on_provider_changed(self):
        provider = self.combo_provider.currentData()
        self.lbl_test_status.setText("")

        if provider == "google":
            self.lbl_key.hide()
            self.edit_key.hide()
            self.btn_toggle_eye.hide()
            self.lbl_model.hide()
            self.edit_model.hide()
            self.btn_test.hide()
            self.lbl_guide.setText(
                "🟢 <b>Google Dịch miễn phí:</b> Không yêu cầu khóa API. "
                "Hệ thống sẽ dịch tự động qua web Google Translate tốc độ cao."
            )
            self.lbl_guide.setStyleSheet("color: #4ade80; font-size: 12px;")
        elif provider == "deepseek":
            self.lbl_key.show()
            self.edit_key.show()
            self.btn_toggle_eye.show()
            self.lbl_model.show()
            self.edit_model.show()
            self.btn_test.show()
            self.edit_key.setText(str(os.getenv("DEEPSEEK_API_KEY", "")).strip())
            self.edit_model.setText(str(os.getenv("DEEPSEEK_MODEL", "deepseek-chat")).strip() or "deepseek-chat")
            self.lbl_guide.setText(
                "👑 <b>DeepSeek AI (Khuyên dùng):</b> Dịch văn phong kiếm hiệp, hiện đại cực mượt.<br>"
                "👉 Lấy khóa API tại: <a href='https://platform.deepseek.com/api_keys' style='color: #38bdf8;'>https://platform.deepseek.com/api_keys</a>"
            )
            self.lbl_guide.setStyleSheet("color: #38bdf8; font-size: 12px;")
        elif provider == "google_ai_studio":
            self.lbl_key.show()
            self.edit_key.show()
            self.btn_toggle_eye.show()
            self.lbl_model.show()
            self.edit_model.show()
            self.btn_test.show()
            self.edit_key.setText(str(os.getenv("GOOGLE_AI_STUDIO_API_KEY", "")).strip())
            self.edit_model.setText(str(os.getenv("GOOGLE_AI_STUDIO_MODEL", "gemini-1.5-flash")).strip() or "gemini-1.5-flash")
            self.lbl_guide.setText(
                "🔵 <b>Google AI Studio (Gemini):</b> Miễn phí hạn mức hàng ngày từ Google.<br>"
                "👉 Lấy khóa API miễn phí tại: <a href='https://aistudio.google.com/apikey' style='color: #38bdf8;'>https://aistudio.google.com/apikey</a>"
            )
            self.lbl_guide.setStyleSheet("color: #38bdf8; font-size: 12px;")
        elif provider == "openai":
            self.lbl_key.show()
            self.edit_key.show()
            self.btn_toggle_eye.show()
            self.lbl_model.show()
            self.edit_model.show()
            self.btn_test.show()
            self.edit_key.setText(str(os.getenv("OPENAI_API_KEY", "")).strip())
            self.edit_model.setText(str(os.getenv("OPENAI_MODEL", "gpt-4o-mini")).strip() or "gpt-4o-mini")
            self.lbl_guide.setText(
                "🟣 <b>OpenAI (ChatGPT):</b> Dùng GPT-4o-mini hoặc GPT-4o.<br>"
                "👉 Lấy khóa API tại: <a href='https://platform.openai.com/api-keys' style='color: #38bdf8;'>https://platform.openai.com/api-keys</a>"
            )
            self.lbl_guide.setStyleSheet("color: #38bdf8; font-size: 12px;")

    def _load_current_values(self):
        provider = str(os.getenv("OPENAI_PROVIDER") or os.getenv("AI_POLISHER_PROVIDER") or "deepseek").strip().lower()
        if provider == "gemini":
            provider = "google_ai_studio"
        idx = self.combo_provider.findData(provider)
        if idx >= 0:
            self.combo_provider.setCurrentIndex(idx)
        else:
            self.combo_provider.setCurrentIndex(0)
        self._on_provider_changed()

    def _test_connection(self):
        provider = self.combo_provider.currentData()
        key = self.edit_key.text().strip()
        model = self.edit_model.text().strip()

        if not key:
            self.lbl_test_status.setText("⚠️ Vui lòng nhập khóa API trước khi kiểm tra.")
            self.lbl_test_status.setStyleSheet("color: #fbbf24; font-size: 11px;")
            return

        self.btn_test.setEnabled(False)
        self.lbl_test_status.setText("⏳ Đang gửi yêu cầu kiểm tra...")
        self.lbl_test_status.setStyleSheet("color: #94a3b8; font-size: 11px;")

        def _worker():
            try:
                from openai import OpenAI
                if provider == "deepseek":
                    base_url = "https://api.deepseek.com"
                    client = OpenAI(api_key=key, base_url=base_url, timeout=12.0)
                    client.chat.completions.create(
                        model=model or "deepseek-chat",
                        messages=[{"role": "user", "content": "hi"}],
                        max_tokens=5,
                    )
                elif provider == "google_ai_studio":
                    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
                    client = OpenAI(api_key=key, base_url=base_url, timeout=12.0)
                    client.chat.completions.create(
                        model=model or "gemini-1.5-flash",
                        messages=[{"role": "user", "content": "hi"}],
                        max_tokens=5,
                    )
                elif provider == "openai":
                    client = OpenAI(api_key=key, timeout=12.0)
                    client.chat.completions.create(
                        model=model or "gpt-4o-mini",
                        messages=[{"role": "user", "content": "hi"}],
                        max_tokens=5,
                    )
                self._signals.finished.emit(True, "🟢 Kết nối thành công! Khóa API hợp lệ.")
            except Exception as e:
                err_msg = str(e)
                if "401" in err_msg or "Authentication" in err_msg:
                    err_msg = "Khóa API không chính xác hoặc đã bị thu hồi."
                elif "insufficient_quota" in err_msg or "429" in err_msg:
                    err_msg = "Tài khoản hết hạn mức hoặc chưa nạp tiền."
                self._signals.finished.emit(False, f"🔴 Lỗi: {err_msg}")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_test_finished(self, success: bool, message: str):
        self.btn_test.setEnabled(True)
        self.lbl_test_status.setText(message)
        self.lbl_test_status.setStyleSheet(f"color: {'#4ade80' if success else '#f87171'}; font-size: 11px;")

    def _save_and_close(self):
        provider = self.combo_provider.currentData()
        key = self.edit_key.text().strip()
        model = self.edit_model.text().strip()

        updates = {
            "OPENAI_PROVIDER": provider,
            "AI_POLISHER_PROVIDER": provider,
        }

        if provider == "deepseek":
            updates["DEEPSEEK_API_KEY"] = key
            updates["DEEPSEEK_MODEL"] = model or "deepseek-chat"
            updates["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
        elif provider == "google_ai_studio":
            updates["GOOGLE_AI_STUDIO_API_KEY"] = key
            updates["GOOGLE_AI_STUDIO_MODEL"] = model or "gemini-1.5-flash"
            updates["GOOGLE_AI_STUDIO_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
        elif provider == "openai":
            updates["OPENAI_API_KEY"] = key
            updates["OPENAI_MODEL"] = model or "gpt-4o-mini"
            updates["OPENAI_BASE_URL"] = "https://api.openai.com/v1"

        update_env_keys(self.workspace_root, updates)

        QMessageBox.information(
            self,
            "Đã lưu cấu hình",
            f"Đã lưu thành công cấu hình dịch thuật ({self.combo_provider.currentText().split('(')[0].strip()})!\n\n"
            "Các dự án tạo mới sẽ tự động sử dụng cấu hình này.",
        )
        self.accept()
