"""ProjectSettingsMixin: Project lifecycle, user settings, model config dialog and file browsing."""
from __future__ import annotations


try:
    from main_window_parts.common_deps import *
    from main_window_parts.common_deps import _default_asr_engine
except ImportError:
    from ui.main_window_parts.common_deps import *
    from ui.main_window_parts.common_deps import _default_asr_engine



import os
import shutil
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QPushButton, QSlider, QProgressBar, QLabel, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox, QTabWidget, QSplitter, QScrollArea, QFrame, QDialog,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class ProjectSettingsMixin:
    """Mixin class for managing project state, settings persistence,

    model settings dialog and file browser dialogs.
    """
    def save_user_settings(self):
        save_user_settings_impl(self)
        try:
            self.settings.setValue("premium_voice_name", "")
            self.settings.setValue("premium_voice_value", "")
            self.settings.setValue("voice_tier", "free")
        except Exception:
            pass
    def load_user_settings(self):
        load_user_settings_impl(self)
        if hasattr(self, "use_premium_voice_radio"):
            try:
                self.use_premium_voice_radio.setChecked(False)
            except Exception:
                pass
        if hasattr(self, "use_free_voice_radio"):
            try:
                self.use_free_voice_radio.setChecked(True)
            except Exception:
                pass
    def open_model_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Cài đặt")
        dialog.setModal(True)
        dialog.setMinimumWidth(450)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: #0f1724;
            }
            QLabel {
                color: #d7e3f4;
                background: transparent;
            }
            QLabel#statusHeadline {
                color: #f8fbff;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#helperLabel {
                color: #9fb3ca;
                font-size: 12px;
            }
            QComboBox, QLineEdit {
                background-color: #132033;
                color: #f8fbff;
                border: 1px solid #2f4868;
                border-radius: 10px;
                padding: 8px 10px;
                min-height: 18px;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QComboBox QAbstractItemView {
                background-color: #132033;
                color: #f8fbff;
                border: 1px solid #2f4868;
                selection-background-color: #24486c;
                selection-color: #ffffff;
            }
            QPushButton {
                background-color: #22344d;
                color: #f8fbff;
                border: 1px solid #34506f;
                border-radius: 10px;
                padding: 8px 16px;
                font-weight: 600;
                min-width: 84px;
            }
            QPushButton:hover {
                background-color: #29405d;
            }
            QPushButton:pressed {
                background-color: #1d2d42;
            }
            """
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.setSizeConstraint(QLayout.SetFixedSize)

        remote_mode = is_remote_profile()
        # Transcription Engine Section
        engine_title = QLabel("Nguồn tạo phụ đề")
        engine_title.setObjectName("statusHeadline")
        layout.addWidget(engine_title)

        engine_combo = QComboBox(dialog)
        engine_combo.addItem("Âm thanh (SenseVoice) - Nhanh", "sensevoice")
        engine_combo.addItem("Âm thanh (Whisper) - Chất lượng", "whisper")
        engine_combo.addItem("Video (OCR hình ảnh)", "ocr")
        current_engine = self.get_transcription_engine()
        idx = engine_combo.findData(current_engine)
        if idx >= 0:
            engine_combo.setCurrentIndex(idx)
        layout.addWidget(engine_combo)

        # OCR Region combo (only visible when OCR selected)
        region_label = QLabel("Vị trí phụ đề OCR:")
        region_label.setVisible(current_engine == "ocr")
        region_combo = QComboBox(dialog)
        region_combo.addItem("Phía dưới (mặc định)", "bottom")
        region_combo.addItem("Phía trên", "top")
        region_combo.addItem("Toàn khung hình", "full")
        current_region = (os.getenv("OCR_SUBTITLE_REGION") or "bottom").strip().lower()
        idx = region_combo.findData(current_region)
        if idx >= 0:
            region_combo.setCurrentIndex(idx)
        region_combo.setVisible(current_engine == "ocr")
        layout.addWidget(region_label)
        layout.addWidget(region_combo)

        sampling_label = QLabel("Tốc độ lấy mẫu OCR:")
        sampling_label.setToolTip("Tốc độ cao hơn bắt được các phụ đề lướt nhanh nhưng xử lý nhiều khung hình hơn.")
        sampling_label.setVisible(current_engine == "ocr")
        sampling_combo = QComboBox(dialog)
        sampling_combo.addItem("Tự động (khuyên dùng)", "auto")
        sampling_combo.addItem("1 FPS (nhẹ máy)", "1")
        sampling_combo.addItem("1.5 FPS", "1.5")
        sampling_combo.addItem("2 FPS", "2")
        sampling_combo.addItem("3 FPS", "3")
        sampling_combo.addItem("4 FPS (chữ xuất hiện nhanh)", "4")
        current_sampling_fps = str(os.getenv("OCR_SAMPLING_FPS") or "auto").strip().lower()
        idx = sampling_combo.findData(current_sampling_fps)
        sampling_combo.setCurrentIndex(idx if idx >= 0 else 0)
        sampling_combo.setVisible(current_engine == "ocr")
        layout.addWidget(sampling_label)
        layout.addWidget(sampling_combo)

        # Whisper Section
        is_whisper = current_engine == "whisper"
        whisper_title = QLabel("Mô hình Whisper")
        whisper_title.setObjectName("statusHeadline")
        whisper_title.setVisible(is_whisper)
        layout.addWidget(whisper_title)
        
        whisper_combo = QComboBox(dialog)
        whisper_combo.addItem("Base (Nhẹ)", "base")
        whisper_combo.addItem("Small (Nhanh)", "small")
        if os.environ.get("CAPCAP_DEVICE", "cuda").strip().lower() == "cuda":
            whisper_combo.addItem("Medium (Chất lượng)", "medium")
        current_whisper = str(getattr(self, "selected_whisper_model_name", "auto") or "auto").strip().lower()
        if current_whisper == "auto":
            current_whisper = self.get_whisper_model_name()
        whisper_index = whisper_combo.findData(current_whisper)
        whisper_combo.setCurrentIndex(whisper_index if whisper_index >= 0 else 0)
        whisper_combo.setVisible(is_whisper)
        layout.addWidget(whisper_combo)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #2f4868;")
        layout.addWidget(divider)

        remote_title = QLabel("API máy chủ từ xa")
        remote_title.setObjectName("statusHeadline")
        remote_title.setVisible(remote_mode)
        layout.addWidget(remote_title)

        remote_url_layout = QVBoxLayout()
        remote_url_label = QLabel("Địa chỉ URL API PC:")
        remote_url_edit = QLineEdit(dialog)
        remote_url_edit.setText(os.getenv("CAPCAP_REMOTE_API_URL", "http://127.0.0.1:8765"))
        remote_url_layout.addWidget(remote_url_label)
        remote_url_layout.addWidget(remote_url_edit)
        remote_url_label.setVisible(remote_mode)
        remote_url_edit.setVisible(remote_mode)
        layout.addLayout(remote_url_layout)

        remote_token_layout = QVBoxLayout()
        remote_token_label = QLabel("API Token (tùy chọn):")
        remote_token_edit = QLineEdit(dialog)
        remote_token_edit.setEchoMode(QLineEdit.Password)
        remote_token_edit.setText(os.getenv("CAPCAP_REMOTE_API_TOKEN", ""))
        remote_token_layout.addWidget(remote_token_label)
        remote_token_layout.addWidget(remote_token_edit)
        remote_token_label.setVisible(remote_mode)
        remote_token_edit.setVisible(remote_mode)
        layout.addLayout(remote_token_layout)

        remote_actions_layout = QHBoxLayout()
        test_remote_btn = QPushButton("Kiểm tra kết nối", dialog)
        test_remote_btn.setVisible(remote_mode)
        remote_actions_layout.addWidget(test_remote_btn)
        remote_actions_layout.addStretch()
        layout.addLayout(remote_actions_layout)

        remote_hint_label = QLabel(
            "Chế độ máy chủ từ xa giữ Whisper và AI dịch thuật trên máy PC của bạn. "
            "Bản laptop chỉ gửi âm thanh và phụ đề qua HTTP."
        )
        remote_hint_label.setObjectName("helperLabel")
        remote_hint_label.setWordWrap(True)
        remote_hint_label.setVisible(remote_mode)
        layout.addWidget(remote_hint_label)

        remote_divider = QFrame()
        remote_divider.setFrameShape(QFrame.HLine)
        remote_divider.setStyleSheet("color: #2f4868;")
        remote_divider.setVisible(remote_mode)
        layout.addWidget(remote_divider)

        # AI Translation Section
        ai_title = QLabel("Dịch thuật AI")
        ai_title.setObjectName("statusHeadline")
        ai_title.setVisible(not remote_mode)
        layout.addWidget(ai_title)

        provider_layout = QHBoxLayout()
        provider_label = QLabel("Nhà cung cấp dịch thuật:")
        provider_label.setVisible(not remote_mode)
        provider_layout.addWidget(provider_label)
        provider_combo = QComboBox(dialog)
        provider_combo.addItem("Google Dịch (miễn phí, không cần key)", "google")
        provider_combo.addItem("Google AI Studio (Gemini)", "google_ai_studio")
        provider_combo.addItem("DeepSeek (Khuyên dùng cho phim Trung)", "deepseek")
        provider_combo.addItem("OpenAI", "openai")
        provider_combo.addItem("Ollama (Nội bộ)", "ollama")
        current_provider = (os.getenv("OPENAI_PROVIDER") or "google").strip().lower()
        if current_provider == "gemini":
            current_provider = "google_ai_studio"
        if current_provider not in {"google", "google_ai_studio", "deepseek", "openai", "ollama"}:
            current_provider = "google"
        idx = provider_combo.findData(current_provider)
        if idx >= 0:
            provider_combo.setCurrentIndex(idx)
        provider_combo.setVisible(not remote_mode)
        provider_layout.addWidget(provider_combo, 1)
        layout.addLayout(provider_layout)

        def _provider_values(provider):
            if provider == "google_ai_studio":
                legacy = str(os.getenv("OPENAI_PROVIDER") or "").strip().lower() == "gemini"
                return (
                    os.getenv("GOOGLE_AI_STUDIO_API_KEY", "") or (os.getenv("OPENAI_API_KEY", "") if legacy else ""),
                    os.getenv("GOOGLE_AI_STUDIO_MODEL", "") or (os.getenv("OPENAI_MODEL", "") if legacy else ""),
                    os.getenv("GOOGLE_AI_STUDIO_BASE_URL", "") or (os.getenv("OPENAI_BASE_URL", "") if legacy else ""),
                )
            if provider == "deepseek":
                return (
                    os.getenv("DEEPSEEK_API_KEY", ""),
                    os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
                    os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                )
            return (os.getenv("OPENAI_API_KEY", ""), os.getenv("OPENAI_MODEL", ""), os.getenv("OPENAI_BASE_URL", ""))

        initial_key, initial_model, initial_base_url = _provider_values(current_provider)

        key_section_widget = QWidget(dialog)
        key_layout = QVBoxLayout(key_section_widget)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_label = QLabel("Khóa API (API Key):")
        key_edit = QLineEdit(dialog)
        key_edit.setEchoMode(QLineEdit.Password)
        key_edit.setText(initial_key)
        key_layout.addWidget(key_label)
        key_layout.addWidget(key_edit)
        key_section_widget.setVisible(not remote_mode)
        layout.addWidget(key_section_widget)

        model_layout = QVBoxLayout()
        model_label = QLabel("Mô hình AI:")
        model_edit = QLineEdit(dialog)
        model_edit.setText(initial_model)
        model_layout.addWidget(model_label)
        model_layout.addWidget(model_edit)
        model_label.setVisible(not remote_mode)
        model_edit.setVisible(not remote_mode)
        layout.addLayout(model_layout)

        base_url_layout = QVBoxLayout()
        base_url_label = QLabel("Địa chỉ URL API:")
        base_url_edit = QLineEdit(dialog)
        base_url_edit.setText(initial_base_url)
        base_url_layout.addWidget(base_url_label)
        base_url_layout.addWidget(base_url_edit)
        base_url_label.setVisible(not remote_mode)
        base_url_edit.setVisible(not remote_mode)
        layout.addLayout(base_url_layout)

        provider_hint = QLabel("Lấy khóa API tại https://aistudio.google.com/apikey")
        provider_hint.setObjectName("helperLabel")
        provider_hint.setWordWrap(True)
        provider_hint.setVisible(not remote_mode)
        layout.addWidget(provider_hint)

        def _toggle_visible(widget, visible):
            widget.setVisible(visible)

        def update_provider_fields():
            p = provider_combo.currentData()
            model_edit.setPlaceholderText("")
            is_ai = p != "google"
            is_google_ai_studio = p == "google_ai_studio"
            is_deepseek = p == "deepseek"
            is_openai = p == "openai"
            is_ollama = p == "ollama"
            is_google = p == "google"
            _toggle_visible(key_section_widget, is_google_ai_studio or is_deepseek or is_openai)
            _toggle_visible(base_url_label, not remote_mode and is_ai)
            _toggle_visible(base_url_edit, not remote_mode and is_ai)
            _toggle_visible(test_btn, not remote_mode and is_ai)
            _toggle_visible(test_status, not remote_mode and is_ai)
            _toggle_visible(model_label, not remote_mode and is_ai)
            _toggle_visible(model_edit, not remote_mode and is_ai)
            if is_google:
                provider_hint.setText("Google Dịch web miễn phí, không cần khóa API. Bản dịch cơ bản.")
                key_edit.clear()
                model_edit.clear()
                base_url_edit.clear()
            elif is_google_ai_studio:
                model_label.setText("Mô hình AI:")
                key, model, base_url = _provider_values(p)
                key_edit.setText(key)
                model_edit.setText(model)
                base_url_edit.setText(base_url or "https://generativelanguage.googleapis.com/v1beta/openai/")
                if not model_edit.text().strip():
                    model_edit.setText("gemini-2.5-flash")
                provider_hint.setText("Sử dụng khóa API Google AI Studio Gemini: https://aistudio.google.com/apikey")
            elif is_deepseek:
                model_label.setText("Mô hình AI:")
                key, model, base_url = _provider_values(p)
                key_edit.setText(key)
                model_edit.setText(model or "deepseek-v4-flash")
                base_url_edit.setText(base_url or "https://api.deepseek.com")
                if not model_edit.text().strip():
                    model_edit.setText("deepseek-v4-flash")
                provider_hint.setText("Lấy khóa API DeepSeek tại https://platform.deepseek.com/api_keys (Model: deepseek-v4-flash, tắt thinking)")
            elif is_openai:
                model_label.setText("Mô hình AI:")
                key, model, base_url = _provider_values(p)
                key_edit.setText(key)
                model_edit.setText(model)
                base_url_edit.setText(base_url or "https://api.openai.com/v1/")
                if not model_edit.text().strip():
                    model_edit.setText("gpt-4o-mini")
                provider_hint.setText("Lấy khóa API OpenAI tại https://platform.openai.com/api-keys")
            elif p == "ollama":
                model_label.setText("Mô hình AI:")
                base_url_edit.setText("http://localhost:11434/v1")
                key_edit.clear()
                model_edit.setText("gemma4:31b-cloud")
                provider_hint.setText("Yêu cầu máy chủ Ollama đang chạy. Mô hình mặc định: gemma4:31b-cloud")
            model_edit.setReadOnly(False)
            dialog.layout().invalidate()
            dialog.adjustSize()

        test_btn = QPushButton("Kiểm tra kết nối", dialog)
        test_btn.setVisible(not remote_mode)
        test_status = QLabel("")
        test_status.setObjectName("helperLabel")
        test_status.setVisible(not remote_mode)
        test_row = QHBoxLayout()
        test_row.addWidget(test_btn)
        test_row.addWidget(test_status, 1)
        layout.addLayout(test_row)

        def test_ai_connection():
            url = base_url_edit.text().strip()
            provider = provider_combo.currentData()
            key = key_edit.text().strip() or ("ollama" if provider == "ollama" else "")
            model = model_edit.text().strip()
            if not url:
                test_status.setText("Vui lòng nhập URL máy chủ trước.")
                return
            if not key:
                test_status.setText("Vui lòng nhập khóa API trước.")
                return
            if not model:
                test_status.setText("Vui lòng nhập tên mô hình trước.")
                return
            test_status.setText("Đang kiểm tra...")
            test_status.repaint()
            try:
                from openai import OpenAI
                client = OpenAI(api_key=key, base_url=url, timeout=15.0)
                # A tiny completion validates the endpoint, credential, and the
                # selected model.  Some compatible APIs do not expose /models.
                test_kwargs = {
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 8,
                }
                if provider == "deepseek":
                    test_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
                client.chat.completions.create(**test_kwargs)
                test_status.setText(f"Đã kết nối: {model}")
            except Exception as e:
                if provider == "ollama":
                    self.log(f"[Ollama] Kiểm tra kết nối thất bại: {e}")
                    test_status.setText("Không thể kết nối đến Ollama. Vui lòng kiểm tra lại cấu hình.")
                else:
                    test_status.setText(f"Thất bại: {e}")

        test_btn.clicked.connect(test_ai_connection)

        provider_combo.currentIndexChanged.connect(update_provider_fields)
        update_provider_fields()

        def update_engine_fields():
            engine_val = engine_combo.currentData()
            is_ocr = engine_val == "ocr"
            is_whisper = engine_val == "whisper"
            _toggle_visible(whisper_title, is_whisper)
            _toggle_visible(whisper_combo, is_whisper)
            _toggle_visible(region_label, is_ocr)
            _toggle_visible(region_combo, is_ocr)
            _toggle_visible(sampling_label, is_ocr)
            _toggle_visible(sampling_combo, is_ocr)
            dialog.layout().invalidate()
            dialog.adjustSize()

        engine_combo.currentIndexChanged.connect(update_engine_fields)

        local_download_layout = QHBoxLayout()
        manage_resources_btn = QPushButton("Quản lý tài nguyên", dialog)
        open_voices_folder_btn = QPushButton("Mở thư mục giọng đọc", dialog)
        local_download_layout.addWidget(manage_resources_btn)
        local_download_layout.addWidget(open_voices_folder_btn)
        manage_resources_btn.setVisible(not remote_mode)
        open_voices_folder_btn.setVisible(not remote_mode)
        layout.addLayout(local_download_layout)

        def _piper_models_dir() -> str:
            return models_path("piper")

        def open_voices_folder():
            voices_dir = _piper_models_dir()
            os.makedirs(voices_dir, exist_ok=True)
            open_folder_impl(self, voices_dir)

        open_voices_folder_btn.clicked.connect(open_voices_folder)
        manage_resources_btn.clicked.connect(self.open_resource_manager_dialog)
        def _test_remote_connection():
            try:
                payload = self._test_remote_api_connection(
                    remote_url_edit.text().strip(),
                    remote_token_edit.text().strip(),
                )
                service_name = str(payload.get("service", "capcap-remote-api") or "capcap-remote-api")
                profile_name = str(payload.get("profile", "local") or "local")
                QMessageBox.information(
                    dialog,
                    "API từ xa",
                    f"Kết nối thành công.\n\nDịch vụ: {service_name}\nHồ sơ: {profile_name}",
                )
            except Exception as exc:
                QMessageBox.warning(
                    dialog,
                    "API từ xa",
                    f"Không thể kết nối đến máy chủ PC.\n\n{exc}",
                )

        test_remote_btn.clicked.connect(_test_remote_connection)

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch()
        cancel_btn = QPushButton("Hủy", dialog)
        save_btn = QPushButton("Lưu", dialog)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)

        cancel_btn.clicked.connect(dialog.reject)
        save_btn.clicked.connect(dialog.accept)

        # The subtitle is a top-level overlay above MPV's native surface.
        # Hide it for this modal dialog so it cannot paint over Settings.
        subtitle_item = getattr(getattr(self, "video_view", None), "subtitle_item", None)
        text_overlay = getattr(getattr(self, "video_view", None), "text_overlay", None)
        subtitle_was_visible = bool(subtitle_item is not None and subtitle_item.isVisible())
        if subtitle_item is not None:
            subtitle_item.set_suppressed(True)
        if text_overlay is not None:
            text_overlay.set_suppressed(True)
        dialog_result = dialog.exec()
        if dialog_result != QDialog.Accepted:
            if subtitle_item is not None:
                subtitle_item.set_suppressed(False)
            if text_overlay is not None:
                text_overlay.set_suppressed(False)
            if subtitle_was_visible and not getattr(self, "_preview_video_has_burned_subtitles", False):
                QTimer.singleShot(0, self.sync_live_subtitle_preview)
            return

        # Save Logic
        new_whisper = str(whisper_combo.currentData() or "small").strip().lower()
        new_engine = str(engine_combo.currentData() or "sensevoice").strip().lower()
        new_ocr_region = str(region_combo.currentData() or "bottom").strip().lower()
        new_ocr_sampling_fps = str(sampling_combo.currentData() or "auto").strip().lower()
        new_key = key_edit.text().strip()
        new_model = model_edit.text().strip()
        new_provider = str(provider_combo.currentData()).strip()
        new_base_url = base_url_edit.text().strip()

        self.selected_whisper_model_name = new_whisper
        
        # Transcription engine settings (apply to all modes)
        # The subtitle source is project-local.  Do not write it into .env,
        # otherwise opening another project can inherit a stale OCR/Audio
        # choice from an earlier session.
        _engine_updates = {
            "OCR_SUBTITLE_REGION": new_ocr_region,
            "OCR_SAMPLING_FPS": new_ocr_sampling_fps,
        }
        
        # Write back to .env
        env_lines = []
        if os.path.exists(".env"):
            with open(".env", "r", encoding="utf-8") as f:
                env_lines = f.readlines()
        
        if remote_mode:
            updates = {
                "CAPCAP_REMOTE_API_URL": remote_url_edit.text().strip() or "http://127.0.0.1:8765",
                "CAPCAP_REMOTE_API_TOKEN": remote_token_edit.text().strip(),
            }
        else:
            if new_provider == "google":
                updates = {
                    "AI_POLISHER_PROVIDER": "google",
                    "OPENAI_PROVIDER": "google",
                }
            elif new_provider == "google_ai_studio":
                updates = {
                    "AI_POLISHER_PROVIDER": "google_ai_studio",
                    "OPENAI_PROVIDER": "google_ai_studio",
                    "GOOGLE_AI_STUDIO_API_KEY": new_key,
                    "GOOGLE_AI_STUDIO_MODEL": new_model or "gemini-2.5-flash",
                    "GOOGLE_AI_STUDIO_BASE_URL": new_base_url or "https://generativelanguage.googleapis.com/v1beta/openai/",
                }
            elif new_provider == "deepseek":
                updates = {
                    "AI_POLISHER_PROVIDER": "deepseek",
                    "OPENAI_PROVIDER": "deepseek",
                    "DEEPSEEK_API_KEY": new_key,
                    "DEEPSEEK_MODEL": new_model or "deepseek-v4-flash",
                    "DEEPSEEK_BASE_URL": new_base_url or "https://api.deepseek.com",
                }
            elif new_provider == "ollama":
                updates = {
                    "AI_POLISHER_PROVIDER": "ollama",
                    "OPENAI_PROVIDER": "ollama",
                    "OPENAI_API_KEY": "ollama",
                    "OPENAI_MODEL": new_model,
                    "OPENAI_BASE_URL": new_base_url or "http://localhost:11434/v1",
                }
            else:
                updates = {
                    "AI_POLISHER_PROVIDER": "openai",
                    "OPENAI_PROVIDER": "openai",
                    "OPENAI_API_KEY": new_key,
                    "OPENAI_MODEL": new_model or "gpt-4o-mini",
                    "OPENAI_BASE_URL": new_base_url or "https://api.openai.com/v1/",
                }
        
        updates.update(_engine_updates)

        new_env_lines = []
        handled_keys = set()
        for line in env_lines:
            match = re.match(r"^([^=]+)=.*", line)
            if match:
                k = match.group(1).strip()
                if k == "TRANSCRIPTION_ENGINE":
                    # Legacy global cache: source selection now belongs to
                    # the active project and must not survive here.
                    continue
                if k in updates:
                    new_env_lines.append(f"{k}={updates[k]}\n")
                    handled_keys.add(k)
                    continue
            new_env_lines.append(line)
        
        for k, v in updates.items():
            if k not in handled_keys:
                new_env_lines.append(f"{k}={v}\n")
        
        with open(".env", "w", encoding="utf-8") as f:
            f.writelines(new_env_lines)
            
        # Update os.environ so it takes effect immediately in this session
        for k, v in updates.items():
            os.environ[k] = v

        self.set_project_transcription_engine(new_engine)
        self.save_user_settings()
        self._update_ocr_overlay()
        QMessageBox.information(self, "Success", "Settings saved and updated!")
        if subtitle_item is not None:
            subtitle_item.set_suppressed(False)
        if text_overlay is not None:
            text_overlay.set_suppressed(False)
        if subtitle_was_visible and not getattr(self, "_preview_video_has_burned_subtitles", False):
            QTimer.singleShot(0, self.sync_live_subtitle_preview)
    def ensure_current_project(self):
        video_path = self.video_path_edit.text().strip()
        state = self.project_bridge.ensure_project(
            video_path=video_path,
            mode=self.get_output_mode_key(),
            translator_ai=self.is_ai_polish_enabled(),
            input_language=self.get_source_language_code(),
            target_language=self.get_target_language_code(),
        )
        if not state:
            return None
        audio_handling_mode = self.get_audio_handling_mode()
        if str(state.settings.get("audio_handling_mode", "fast")).strip().lower() != audio_handling_mode:
            state.set_setting("audio_handling_mode", audio_handling_mode)
            self.project_service.save_project(state)
        self.current_project_state = state
        self.processed_artifacts.update(state.artifacts)
        return state
    def update_project_step(self, step_name: str, status: str):
        state = self.ensure_current_project()
        if not state:
            return
        self.project_bridge.update_step(state, step_name, status)
    def update_project_artifact(self, artifact_name: str, path: str):
        state = self.ensure_current_project()
        if not state or not path:
            return
        normalized_path = self._normalize_local_file_path(path)
        self.processed_artifacts[artifact_name] = normalized_path
        self.project_bridge.update_artifact(state, artifact_name, normalized_path)
    def persist_transcription_project_data(self, raw_segments, srt_path=""):
        state = self.ensure_current_project()
        if not state:
            return
        self.current_segment_models = self.project_bridge.persist_transcription(state, raw_segments, srt_path)
    def persist_translation_project_data(self, translated_segments, srt_path=""):
        state = self.ensure_current_project()
        if not state:
            return
        self.current_translated_segment_models = self.project_bridge.persist_translation(
            state,
            self.current_segment_models,
            translated_segments,
            srt_path,
        )
        signature = self.build_current_translation_signature()
        if signature:
            state.set_setting("translation_signature", signature)
            self.project_service.save_project(state)
    def load_project_context(self, state):
        if not state:
            return
        self._allow_post_pipeline_preview_assets = False
        # Subtitle Source is stored only with this project.  Old projects
        # without a value start from the normal default instead of inheriting
        # the last global .env selection.
        project_engine = str(getattr(state, "settings", {}).get("transcription_engine", "") or "").strip().lower()
        os.environ["TRANSCRIPTION_ENGINE"] = project_engine if project_engine in {"whisper", "sensevoice", "ocr"} else _default_asr_engine()
        audio_handling_mode = str(getattr(state, "settings", {}).get("audio_handling_mode", "") or "").strip().lower()
        if audio_handling_mode and hasattr(self, "audio_handling_combo"):
            combo_index = self.audio_handling_combo.findData(audio_handling_mode)
            if combo_index >= 0:
                self.audio_handling_combo.setCurrentIndex(combo_index)
        context = self.project_bridge.load_context(state)
        self.processed_artifacts = {}
        # Restore project-scoped visibility. Old projects remain visible by
        # default because they have no saved value yet.
        preview_visibility = dict(getattr(state, "settings", {}).get("preview_track_visibility") or {})
        self._subtitle_track_preview_visible = bool(preview_visibility.get("TS1", True))
        self._text_track_preview_visible = bool(preview_visibility.get("T1 Text", True))
        self._logo_track_preview_visible = bool(preview_visibility.get("L1 Logo", True))
        self._mask_track_preview_visible = bool(preview_visibility.get("M1", True))
        saved_subtitle_style = dict(getattr(state, "settings", {}).get("subtitle_style_controls") or {})
        if saved_subtitle_style:
            self._apply_subtitle_style_controls_state(saved_subtitle_style)
            self._subtitle_custom_style_state = dict(saved_subtitle_style)
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_subtitle_track_visible"):
            self.video_view.set_subtitle_track_visible(self._subtitle_track_preview_visible)
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_logo_track_visible"):
            self.video_view.set_logo_track_visible(self._logo_track_preview_visible)
        self.last_original_srt_path = ""
        self.last_translated_srt_path = ""
        self.last_extracted_audio = ""
        self.last_vocals_path = ""
        # Sync timeline track mute -> GUI per-track mute state
        self._sync_timeline_mute_to_gui()
        self._sync_audio_mix_controls_from_tracks()
        self.last_music_path = ""
        self.last_voice_vi_path = ""
        self.last_mixed_vi_path = ""
        self.current_segment_models = []
        self.current_translated_segment_models = []
        self.current_segments = []
        self.current_translated_segments = []
        if hasattr(self, "audio_source_edit"):
            self.audio_source_edit.clear()
        if hasattr(self, "transcript_text"):
            self.transcript_text.clear()
        if hasattr(self, "translated_text"):
            self.translated_text.clear()
        self._saved_timeline_model_restored = False
        if hasattr(self, "timeline"):
            self.timeline.set_segments([])
            self.timeline.set_video_thumbnails([])
            self.timeline.set_playing(False)
            # Restore optional tracks before apply_segments_to_timeline().
            # That method refreshes TS1, while preserving the restored Text,
            # Logo, Blur, and Mask tracks.
            self._saved_timeline_model_restored = bool(
                self._restore_saved_timeline_model(state)
            )
        self._timeline_video_thumb_cache_key = None
        self._timeline_video_thumbnails = []
        self.processed_artifacts.update(context["artifacts"])
        self.last_original_srt_path = self._normalize_local_file_path(context["last_original_srt_path"] or self.last_original_srt_path)
        self.last_translated_srt_path = self._normalize_local_file_path(context["last_translated_srt_path"] or self.last_translated_srt_path)
        self.last_extracted_audio = self._normalize_local_file_path(context["last_extracted_audio"] or self.last_extracted_audio)
        self.last_vocals_path = self._normalize_local_file_path(context["last_vocals_path"] or self.last_vocals_path)
        self.last_music_path = self._normalize_local_file_path(context["last_music_path"] or self.last_music_path)
        self.last_voice_vi_path = self._normalize_local_file_path(context["last_voice_vi_path"] or self.last_voice_vi_path)
        self.last_mixed_vi_path = self._normalize_local_file_path(context["last_mixed_vi_path"] or self.last_mixed_vi_path)
        self.current_segment_models = context["current_segment_models"]
        self.current_translated_segment_models = context["current_translated_segment_models"]
        self.current_segments = context["current_segments"]
        self.current_translated_segments = context["current_translated_segments"]
        self.refresh_detected_speakers_section()
        self.refresh_speaker_analysis_summary()
        if self.current_translated_segments:
            self.refresh_auto_keyword_highlights(force=True)
        if self.get_audio_handling_mode() == "clean" and self.last_vocals_path and os.path.exists(self.last_vocals_path):
            self.audio_source_edit.setText(self.last_vocals_path)
        elif self.last_extracted_audio and os.path.exists(self.last_extracted_audio):
            self.audio_source_edit.setText(self.last_extracted_audio)
        elif self.last_vocals_path and os.path.exists(self.last_vocals_path):
            self.audio_source_edit.setText(self.last_vocals_path)
        if self.current_segments:
            self.transcript_text.setText(self.format_to_srt(self.current_segments))
        if self.current_translated_segments:
            self.translated_text.setText(self.format_to_srt(self.current_translated_segments))
        if self.current_translated_segments or self.current_segments:
            self._enable_post_pipeline_preview_assets(refresh=True)
            self.apply_segments_to_timeline()
            self.set_selected_segment_index(0, sync_ui=True)
        # Restore A2 Dub track if TTS was generated
        voice_path = context.get("artifacts", {}).get("voice_vi", "")
        if voice_path and os.path.exists(voice_path) and hasattr(self, "timeline"):
            self.timeline.sync_tts_track(voice_path, segments=self.current_translated_segments or self.current_segments)
            # Enable Audio tab since voice generation was completed
            if hasattr(self, "audio_tab_btn"):
                self.audio_tab_btn.setEnabled(True)
        self._sync_timeline_mute_to_gui()
        self._sync_audio_mix_controls_from_tracks()
        # OCR geometry is project-scoped.  For a reopened OCR project that has
        # not produced a transcript yet, keep the crop editor visible so the
        # user can configure the region before running Transcript.  Completed
        # projects return to an unobstructed preview until OCR is explicitly
        # reopened with the toolbar button.
        has_transcript = bool(
            self.current_segments
            or self.current_segment_models
            or (hasattr(self, "transcript_text") and self.transcript_text.toPlainText().strip())
        )
        if not bool(getattr(self, "_alternate_ocr_range_pending", None)):
            self._ocr_overlay_visible = False
        self._update_ocr_overlay()
        # Clear any stale layer selection from the previous project so
        # the inspector does not stay pinned to a track that no longer
        # exists (e.g. a BlurLayer from a previous project that was
        # removed by _restore_project_blur_state).
        if hasattr(self, "timeline"):
            try:
                self.timeline.select_layer("")
            except Exception:
                pass
        self._show_default_inspector()
        self._restore_project_blur_state(state)
        if hasattr(self, "_restore_project_mask_state"):
            try:
                self._restore_project_mask_state(state)
            except Exception:
                pass
        # Always start a reopened project focused on the source video layer,
        # never on an optional overlay that happened to be restored first.
        try:
            video_layer = None
            for track in self.timeline._timeline.tracks:
                if str(getattr(track, "name", "")) == "V1 Video" and track.layers:
                    video_layer = track.layers[0]
                    break
            if video_layer is not None:
                self.timeline.select_layer(video_layer.id)
                self.on_timeline_layer_selected(video_layer.id)
        except Exception:
            pass
        # Reconnect optional timeline layers to their preview overlays after
        # restoring the serialized model.  Timeline restoration alone is not
        # enough because these overlays are maintained by the video view.
        try:
            self._refresh_text_layer_preview(getattr(self.timeline, "_selected_layer_id", ""))
        except Exception:
            pass
        try:
            logo_track = next(
                (
                    track for track in self.timeline._timeline.tracks
                    if str(getattr(track, "name", "")) == "L1 Logo"
                    and getattr(track, "layers", None)
                ),
                None,
            )
            if logo_track is not None:
                logo_layer = next(
                    (candidate for candidate in logo_track.layers
                     if self._layer_is_active_at_preview_time(candidate)),
                    logo_track.layers[0],
                )
                self._show_logo_overlay(logo_track, logo_layer)
        except Exception:
            pass
        # Force the dual-track sidecar player to re-initialize for this
        # project. Without this, reopening a project would leave the
        # original/dubbed QMediaPlayer sidecars pointing at the previous
        # project's audio files (or empty), so the user hears nothing
        # until they press Generate.
        try:
            if hasattr(self, "sync_preview_audio_track_to_output"):
                self.sync_preview_audio_track_to_output(apply_to_player=True, force=True)
        except Exception:
            pass
        # Stop any active playback so the user re-presses Play after
        # reopening. Otherwise mpv / QMediaPlayer may keep playing the
        # previous source.
        try:
            if hasattr(self, "media_player") and self.media_player is not None:
                self.media_player.pause()
        except Exception:
            pass
    def update_project_header(self):
        video_path = self.video_path_edit.text().strip()
        if video_path:
            video_name = os.path.basename(video_path)
            self.project_title_label.setText(f"Project: {video_name}")
            if hasattr(self, "upload_status_label"):
                self.upload_status_label.setText(f"[OK] {video_name} uploaded")
        else:
            self.project_title_label.setText("Project: No video selected")
            if hasattr(self, "upload_status_label"):
                self.upload_status_label.setText("No video uploaded yet")
    def get_current_project_temp_key(self) -> str:
        state = getattr(self, "current_project_state", None)
        project_id = str(getattr(state, "project_id", "") or "").strip()
        if project_id:
            return project_id
        project_root = str(getattr(state, "project_root", "") or "").strip()
        if project_root:
            return os.path.basename(os.path.normpath(project_root))
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        if video_path:
            video_name = os.path.splitext(os.path.basename(video_path))[0] or "project"
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", video_name).strip("_").lower() or "project"
            digest = hashlib.sha1(os.path.abspath(video_path).encode("utf-8")).hexdigest()[:8]
            return f"{slug}_{digest}"
        return "global"
    def get_project_temp_root(self, create: bool = False) -> str:
        root = os.path.normpath(
            os.path.join(
                self.get_workspace_temp_root(create=create),
                "projects",
                self.get_current_project_temp_key(),
            )
        )
        if create:
            os.makedirs(root, exist_ok=True)
        return root
    def get_project_temp_path(self, *parts: str, create_parent: bool = False) -> str:
        path = os.path.normpath(os.path.join(self.get_project_temp_root(create=create_parent), *parts))
        if create_parent:
            parent = os.path.dirname(path) if os.path.splitext(path)[1] else path
            if parent:
                os.makedirs(parent, exist_ok=True)
        return path
    def get_project_temp_dir(self, *parts: str) -> str:
        path = self.get_project_temp_path(*parts, create_parent=True)
        os.makedirs(path, exist_ok=True)
        return path
    def _reset_project_runtime_state(self) -> None:
        self.current_project_state = None
        self.current_segment_models = []
        self.current_translated_segment_models = []
        self.current_segments = []
        self.current_translated_segments = []
        self.processed_artifacts = {}
        self.last_extracted_audio = ""
        self.last_vocals_path = ""
        self.last_music_path = ""
        self.last_original_srt_path = ""
        self.last_translated_srt_path = ""
        self.last_voice_vi_path = ""
        self.last_mixed_vi_path = ""
        self.last_preview_video_path = ""
        self.last_styled_preview_path = ""
        self.last_styled_preview_signature = ""
        self.last_exported_video_path = ""
        self.last_exact_preview_5s_path = ""
        self.last_exact_preview_frame_path = ""
        self.live_preview_subtitle_path = ""
        self.live_preview_ass_path = ""
        self.live_preview_segments = []
        self.live_preview_editor_name = ""
        self._live_preview_signature = None
        self._timeline_waveform_cache_key = None
        self._timeline_waveform_samples = []
        self._timeline_waveform_duration_s = 0.0
        self._desired_timeline_waveform_request = None
        self._timeline_video_thumb_cache_key = None
        self._timeline_video_thumbnails = []
        self._desired_timeline_thumbnail_request = None
        self._allow_post_pipeline_preview_assets = False
        self._pending_timeline_waveform_refresh = False
        self._pending_timeline_thumbnail_refresh = False
        if hasattr(self, "transcript_text"):
            self.transcript_text.clear()
        if hasattr(self, "translated_text"):
            self.translated_text.clear()
        if hasattr(self, "audio_source_edit"):
            self.audio_source_edit.clear()
        if hasattr(self, "bg_music_edit"):
            self.bg_music_edit.clear()
        if hasattr(self, "mixed_audio_edit"):
            self.mixed_audio_edit.clear()
        if hasattr(self, "video_path_edit"):
            self.video_path_edit.clear()
        if hasattr(self, "timeline"):
            self.timeline.set_segments([])
            self.timeline.set_duration(0)
            self.timeline.set_waveform_data([], 0.0)
            self.timeline.set_video_thumbnails([])
            self.timeline.set_playing(False)
        if hasattr(self, "media_player"):
            try:
                self.media_player.clear_subtitle()
                self.media_player.stop()
                from PySide6.QtCore import QUrl
                self.media_player.setSource(QUrl())
            except Exception:
                pass
        if hasattr(self, "video_view"):
            try:
                self.video_view.clear_blur_region()
            except Exception:
                pass
        if hasattr(self, "progress_bar"):
            self.progress_bar.setValue(0)
        # Force-clear segment editor directly
        self._clear_segment_editor_rows()
        self._segment_editor_rows = []
        self._selected_segment_index = -1
        self.sync_segment_editor_rows()
        self.update_progress_checklist()
        self.refresh_ui_state()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
    def _has_cleanable_project_data(self) -> bool:
        project_root = str(getattr(getattr(self, "current_project_state", None), "project_root", "") or "").strip()
        candidates = [
            getattr(self, "last_extracted_audio", None),
            getattr(self, "last_vocals_path", None),
            getattr(self, "last_music_path", None),
            getattr(self, "last_voice_vi_path", None),
            getattr(self, "last_mixed_vi_path", None),
            getattr(self, "live_preview_subtitle_path", None),
            getattr(self, "live_preview_ass_path", None),
            getattr(self, "last_preview_video_path", None),
            getattr(self, "last_styled_preview_path", None),
            getattr(self, "last_exact_preview_5s_path", None),
            getattr(self, "last_exact_preview_frame_path", None),
            self.get_project_temp_path("tts"),
            self.get_project_temp_path("segment_audio_preview"),
            self.get_project_temp_path("voice_sample_preview"),
            self.get_project_temp_path("htdemucs"),
            self.get_project_temp_path("timeline_video_thumbs"),
            self.get_project_temp_root(),
            project_root,
        ]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return True
        return False
    def exit_to_launcher(self):
        self._return_to_launcher(project_removed_from_recent=False)
    def clean_current_project(self):
        project_state = getattr(self, "current_project_state", None)
        if not self._has_cleanable_project_data():
            QMessageBox.information(self, "Clean Project", "There is no generated project data to clean right now.")
            return

        confirmation = QMessageBox.question(
            self,
            "Clean Project",
            "This will remove intermediate project files, temp previews, separated audio, cached TTS files, and this video's timeline media cache.\n\n"
            "It will keep your source video, imported assets, and final exported video.\n\n"
            "Do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return

        removed_paths = []
        removed_groups = {
            "Project folder": [],
            "Generated voice files": [],
            "Separated audio": [],
            "Preview temp files": [],
            "TTS cache": [],
            "Temp folders": [],
            "Timeline media cache": [],
            "Launcher media cache": [],
        }
        project_temp_root = self.get_project_temp_root()
        output_root = os.path.join(self.workspace_root, "output")
        project_root = str(getattr(project_state, "project_root", "") or "").strip()
        project_id = str(getattr(project_state, "project_id", "") or "").strip()
        if not project_id and project_root:
            project_id = os.path.basename(os.path.normpath(project_root))
        project_state_path = self.project_service.project_file(project_root) if project_root else ""
        allowed_roots = [root for root in [project_temp_root, output_root, project_root] if root]

        # Stop active workers and pending persistence before deleting files.
        # Otherwise a late worker/timer can recreate the selected project's
        # cache or timeline after it has just been removed.
        self._terminate_workers()
        # Release MPV/QMediaPlayer handles before deleting extracted audio or
        # project files. Windows keeps a stopped sidecar source locked until
        # it is explicitly unloaded, which previously made the first cleanup
        # attempt report WinError 32.
        media_player = getattr(self, "media_player", None)
        if media_player is not None:
            try:
                media_player.clear_audio()
            except Exception:
                pass
            try:
                media_player._clear_original_audio()
            except Exception:
                pass
            try:
                from PySide6.QtCore import QUrl
                media_player.setSource(QUrl())
            except Exception:
                pass
            try:
                QApplication.processEvents()
            except Exception:
                pass
        persist_timer = getattr(self, "_timeline_persist_timer", None)
        if persist_timer is not None:
            persist_timer.stop()
        self._pending_timeline_persist = False
        self._pending_mask_state_persist = False
        self._pending_blur_state_persist = False

        self.cleanup_temp_preview_files()

        file_candidates = [
            ("Separated audio", self.last_extracted_audio),
            ("Separated audio", self.last_vocals_path),
            ("Separated audio", self.last_music_path),
            ("Generated voice files", self.last_voice_vi_path),
            ("Generated voice files", self.last_mixed_vi_path),
            ("Preview temp files", self.live_preview_subtitle_path),
            ("Preview temp files", self.live_preview_ass_path),
            ("Preview temp files", self.last_styled_preview_path),
            ("Project folder", project_state_path),
        ]
        for group_name, candidate in file_candidates:
            before_count = len(removed_paths)
            self._remove_path_if_safe(candidate, allowed_roots=allowed_roots, removed=removed_paths)
            if len(removed_paths) > before_count:
                removed_groups[group_name].append(removed_paths[-1])

        dir_candidates = [
            ("Project folder", project_root),
            ("TTS cache", self.get_project_temp_path("tts")),
            ("Temp folders", self.get_project_temp_path("segment_audio_preview")),
            ("Temp folders", self.get_project_temp_path("voice_sample_preview")),
            ("Temp folders", self.get_project_temp_path("htdemucs")),
            ("Temp folders", self.get_project_temp_path("timeline_video_thumbs")),
            ("Temp folders", project_temp_root),
        ]
        for group_name, candidate in dir_candidates:
            before_count = len(removed_paths)
            self._remove_path_if_safe(candidate, allowed_roots=allowed_roots, removed=removed_paths)
            if len(removed_paths) > before_count:
                removed_groups[group_name].append(removed_paths[-1])

        # Older builds stored a few per-project temporary files directly in
        # temp/<project_id>.  Remove that exact legacy directory only; never
        # remove the shared temp root or another project's folder.
        if project_id:
            legacy_project_temp = os.path.join(self.get_workspace_temp_root(), project_id)
            before_count = len(removed_paths)
            self._remove_path_if_safe(
                legacy_project_temp,
                allowed_roots=[self.get_workspace_temp_root()],
                removed=removed_paths,
            )
            if len(removed_paths) > before_count:
                removed_groups["Temp folders"].append(removed_paths[-1])

        # V1/A1 visual assets live in the shared temp root because they are
        # prepared in the launcher before a project context exists. Remove
        # only files whose digest belongs to this source video; caches for
        # other projects remain untouched.
        source_video = self._normalize_local_file_path(
            self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        )
        if source_video:
            source = os.path.abspath(source_video)
            # Some older code paths keyed cache files by the user-provided
            # path while newer ones use the normalized absolute path. Remove
            # both keys for this one selected source video.
            digest_sources = {source, source_video}
            digests = {
                hashlib.md5(cache_source.encode("utf-8")).hexdigest()[:12]
                for cache_source in digest_sources
            }
            full_digests = {
                hashlib.md5(cache_source.encode("utf-8")).hexdigest()
                for cache_source in digest_sources
            }
            temp_root = self.get_workspace_temp_root()
            timeline_cache_paths = []
            for digest in digests:
                timeline_cache_paths.extend([
                    os.path.join(temp_root, f"waveform_{digest}.wav"),
                    os.path.join(temp_root, "timeline_visuals", f"{digest}.json"),
                ])
            thumb_dir = os.path.join(temp_root, "timeline_thumbnails")
            if os.path.isdir(thumb_dir):
                for digest in digests:
                    timeline_cache_paths.extend(
                        glob.glob(os.path.join(thumb_dir, f"launcher_{digest}_*.jpg"))
                    )
            for candidate in timeline_cache_paths:
                before_count = len(removed_paths)
                self._remove_path_if_safe(candidate, allowed_roots=[temp_root], removed=removed_paths)
                if len(removed_paths) > before_count:
                    removed_groups["Timeline media cache"].append(removed_paths[-1])

            # The launcher card thumbnail has its own full-MD5 filename.
            # It belongs solely to this source video, so cleaning this project
            # can safely remove it without touching other recent projects.
            launcher_thumb_root = os.path.join(temp_root, "launcher_thumbs")
            for digest in full_digests:
                before_count = len(removed_paths)
                self._remove_path_if_safe(
                    os.path.join(launcher_thumb_root, f"{digest}.jpg"),
                    allowed_roots=[temp_root],
                    removed=removed_paths,
                )
                if len(removed_paths) > before_count:
                    removed_groups["Launcher media cache"].append(removed_paths[-1])

        self._reset_project_runtime_state()

        if removed_paths:
            self.log(f"[Clean Project] Removed {len(removed_paths)} intermediate paths.")
            detail_lines = ["Cleaned these groups:"]
            for group_name, paths in removed_groups.items():
                if paths:
                    detail_lines.append(f"- {group_name}: {len(paths)} item(s)")
            QMessageBox.information(
                self,
                "Clean Project",
                f"Removed {len(removed_paths)} intermediate paths for the current project.\n\n" + "\n".join(detail_lines),
            )
        else:
            QMessageBox.information(
                self,
                "Clean Project",
                "No removable intermediate files were found for the current project.",
            )
        # The project directory above has intentionally been deleted. Do not
        # persist the in-memory timeline while returning to the launcher,
        # because that would recreate projects/<project_id>/timeline.json.
        self._return_to_launcher(
            project_removed_from_recent=True,
            persist_project_data=False,
        )
    def browse_video(self):
        browse_video_impl(self)
    def browse_audio_folder(self):
        browse_audio_folder_impl(self)
    def browse_srt_output_folder(self):
        browse_srt_output_folder_impl(self)
    def browse_audio_source(self):
        browse_audio_source_impl(self)
    def browse_background_audio(self):
        browse_background_audio_impl(self)
    def browse_existing_mixed_audio(self):
        browse_existing_mixed_audio_impl(self)
    def browse_voice_output_folder(self):
        browse_voice_output_folder_impl(self)
