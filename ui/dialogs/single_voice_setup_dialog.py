"""Single Voice Setup Dialog for 1-Voice Full Pipeline Automation.

Allows users to configure 1 voice narrator, audio mixing levels (original volume vs TTS volume),
blur mask for Chinese subtitles, subtitle burning, and DeepSeek contextual translation.
"""

from __future__ import annotations

import os
import re
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.select_master_dialog import (
    AVAILABLE_FEMALE_VOICES,
    AVAILABLE_MALE_VOICES,
)


class SingleVoiceSetupDialog(QDialog):
    """Hộp thoại Cài đặt Lồng tiếng 1 giọng & Tạo video tự động."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        video_path: str = "",
        initial_orig_volume: int = 50,
        initial_tts_volume: int = 100,
        blur_rect: tuple[float, float, float, float] | None = None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.initial_orig_volume = max(0, min(100, int(initial_orig_volume)))
        self.initial_tts_volume = max(0, min(200, int(initial_tts_volume)))
        self.blur_rect = blur_rect

        self.setWindowTitle("Cài đặt lồng tiếng (1 giọng) & Tạo video tự động")
        self.resize(620, 520)
        self.setMinimumSize(540, 460)

        self._setup_ui()
        self._apply_dark_style()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        # Header Title
        title_label = QLabel("🎬 CÀI ĐẶT LỒNG TIẾNG (1 GIỌNG) & TẠO VIDEO")
        t_font = QFont()
        t_font.setPointSize(12)
        t_font.setBold(True)
        title_label.setFont(t_font)
        title_label.setStyleSheet("color: #ff7b1a;")
        layout.addWidget(title_label)

        desc_label = QLabel(
            "Quy trình tự động: Quét OCR phụ đề Trung ➔ Dịch chuẩn ngữ cảnh bằng DeepSeek AI ➔ "
            "Lồng tiếng 1 nhân vật ➔ Che mờ chữ Trung gốc và đè phụ đề tiếng Việt lên video."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #9fb3ca; font-size: 12px; line-height: 1.4;")
        layout.addWidget(desc_label)

        # --- 1. KHUNG CHỌN 1 GIỌNG LỒNG TIẾNG ---
        voice_box = QGroupBox("1. Chọn giọng đọc nhân vật lồng tiếng")
        voice_layout = QVBoxLayout(voice_box)
        voice_layout.setSpacing(8)
        voice_layout.setContentsMargins(12, 14, 12, 12)

        v_row = QHBoxLayout()
        v_lbl = QLabel("🎙️ Giọng thuyết minh / lồng tiếng:")
        v_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #f8fbff;")
        v_row.addWidget(v_lbl)

        self.combo_voice = QComboBox()
        self.combo_voice.setMinimumHeight(34)

        # Tổng hợp danh sách giọng đọc
        all_voices = []
        # VieNeu VIP
        all_voices.append({"id": "vieneu_thanhnientutin", "name": "👑 Thanh niên tự tin (VieNeu Neural VIP)", "provider": "vieneu"})
        all_voices.append({"id": "vieneu_cogaihoatbat", "name": "👑 Cô gái hoạt ngôn (VieNeu Neural VIP)", "provider": "vieneu"})
        # Piper & Edge
        seen = {"vieneu_thanhnientutin", "vieneu_cogaihoatbat"}
        for v in AVAILABLE_MALE_VOICES:
            if v["id"] not in seen:
                seen.add(v["id"])
                prefix = "👨 " if "vieneu" not in v["id"] else ""
                all_voices.append({**v, "name": f"{prefix}{v['name']}"})
        for v in AVAILABLE_FEMALE_VOICES:
            if v["id"] not in seen:
                seen.add(v["id"])
                prefix = "👩 " if "vieneu" not in v["id"] else ""
                all_voices.append({**v, "name": f"{prefix}{v['name']}"})

        def_voice_idx = 0
        for idx, item in enumerate(all_voices):
            self.combo_voice.addItem(item["name"], item)
            # Mặc định chọn Adam hoặc Thanh niên tự tin
            if item["id"] in ("adam1", "adam"):
                def_voice_idx = idx

        self.combo_voice.setCurrentIndex(def_voice_idx)
        v_row.addWidget(self.combo_voice, 1)
        voice_layout.addLayout(v_row)

        voice_hint = QLabel("Giọng này sẽ được dùng để lồng tiếng cho toàn bộ các câu thoại trong video.")
        voice_hint.setStyleSheet("color: #8ea3bb; font-size: 11px;")
        voice_layout.addWidget(voice_hint)

        layout.addWidget(voice_box)

        # --- 2. KHUNG HÒA TRỘN ÂM THANH (AUDIO MIXING) ---
        audio_box = QGroupBox("2. Điều chỉnh âm lượng & Hòa âm")
        audio_layout = QVBoxLayout(audio_box)
        audio_layout.setSpacing(10)
        audio_layout.setContentsMargins(12, 14, 12, 12)

        # Slider Âm lượng gốc
        row_orig = QHBoxLayout()
        lbl_orig = QLabel("Âm lượng âm thanh gốc / Nhạc nền:")
        lbl_orig.setMinimumWidth(210)
        lbl_orig.setStyleSheet("color: #d7e3f4; font-size: 12px;")
        self.slider_orig = QSlider(Qt.Horizontal)
        self.slider_orig.setRange(0, 100)
        self.slider_orig.setValue(self.initial_orig_volume)
        self.lbl_orig_val = QLabel(f"{self.initial_orig_volume}%")
        self.lbl_orig_val.setMinimumWidth(45)
        self.lbl_orig_val.setStyleSheet("color: #8ad7ff; font-weight: bold;")
        self.slider_orig.valueChanged.connect(lambda v: self.lbl_orig_val.setText(f"{v}%"))
        row_orig.addWidget(lbl_orig)
        row_orig.addWidget(self.slider_orig, 1)
        row_orig.addWidget(self.lbl_orig_val)
        audio_layout.addLayout(row_orig)

        # Slider Âm lượng lồng tiếng
        row_tts = QHBoxLayout()
        lbl_tts = QLabel("Âm lượng giọng đọc AI (TTS):")
        lbl_tts.setMinimumWidth(210)
        lbl_tts.setStyleSheet("color: #d7e3f4; font-size: 12px;")
        self.slider_tts = QSlider(Qt.Horizontal)
        self.slider_tts.setRange(0, 150)
        self.slider_tts.setValue(self.initial_tts_volume)
        self.lbl_tts_val = QLabel(f"{self.initial_tts_volume}%")
        self.lbl_tts_val.setMinimumWidth(45)
        self.lbl_tts_val.setStyleSheet("color: #3ddc97; font-weight: bold;")
        self.slider_tts.valueChanged.connect(lambda v: self.lbl_tts_val.setText(f"{v}%"))
        row_tts.addWidget(lbl_tts)
        row_tts.addWidget(self.slider_tts, 1)
        row_tts.addWidget(self.lbl_tts_val)
        audio_layout.addLayout(row_tts)

        audio_hint = QLabel("💡 Tự động kích hoạt Audio Ducking: Nhạc nền sẽ tự giảm nhỏ khi có giọng đọc AI phát ra.")
        audio_hint.setStyleSheet("color: #79c0ff; font-size: 11px;")
        audio_layout.addWidget(audio_hint)

        layout.addWidget(audio_box)

        # --- 3. KHUNG CHE CHỮ TRUNG & ĐÈ PHỤ ĐỀ ---
        visual_box = QGroupBox("3. Xử lý che chữ Trung & Phụ đề Tiếng Việt")
        visual_layout = QVBoxLayout(visual_box)
        visual_layout.setSpacing(8)
        visual_layout.setContentsMargins(12, 14, 12, 12)

        self.chk_blur_mask = QCheckBox("Tự động che mờ (Blur Mask) chữ Trung gốc theo vùng OCR đã chọn")
        self.chk_blur_mask.setChecked(True)
        self.chk_blur_mask.setStyleSheet("color: #f8fbff; font-weight: bold; font-size: 12px;")
        visual_layout.addWidget(self.chk_blur_mask)

        # Hiển thị thông tin toạ độ khung che chữ Trung
        rect_desc = "Tự động phát hiện theo vùng OCR chân trang"
        if self.blur_rect and len(self.blur_rect) == 4:
            x, y, w, h = self.blur_rect
            rect_desc = f"Tọa độ vùng che: x={x:.2f}, y={y:.2f}, w={w:.2f}, h={h:.2f} (Khớp khung OCR đã vẽ)"
        self.lbl_blur_info = QLabel(f"📐 {rect_desc}")
        self.lbl_blur_info.setStyleSheet("color: #8ea3bb; font-size: 11px; margin-left: 20px;")
        visual_layout.addWidget(self.lbl_blur_info)

        self.chk_burn_subtitles = QCheckBox("Đè phụ đề Tiếng Việt dịch bởi DeepSeek AI lên video")
        self.chk_burn_subtitles.setChecked(True)
        self.chk_burn_subtitles.setStyleSheet("color: #f8fbff; font-weight: bold; font-size: 12px;")
        visual_layout.addWidget(self.chk_burn_subtitles)

        # Trạng thái & Cài đặt DeepSeek API
        ds_row = QHBoxLayout()
        ds_row.setContentsMargins(20, 4, 0, 4)
        ds_row.setSpacing(10)

        self.lbl_ds = QLabel()
        self.btn_config_ai = QPushButton("⚙️ Cài đặt / Đổi Key AI")
        self.btn_config_ai.setStyleSheet("""
            QPushButton {
                background-color: #1e293b; color: #38bdf8;
                border: 1px solid #334155; border-radius: 6px; padding: 4px 10px; font-size: 11px; font-weight: 600;
            }
            QPushButton:hover { background-color: #334155; color: #fff; }
        """)
        self.btn_config_ai.clicked.connect(self._open_ai_settings)

        self._refresh_deepseek_status()
        ds_row.addWidget(self.lbl_ds, 1)
        ds_row.addWidget(self.btn_config_ai, 0)
        visual_layout.addLayout(ds_row)

        layout.addWidget(visual_box)

        layout.addStretch()

        # --- NÚT HÀNH ĐỘNG ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Hủy")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.start_btn = QPushButton("🚀 Bắt đầu tạo video")
        self.start_btn.setObjectName("primaryActionBtn")
        self.start_btn.setMinimumHeight(38)
        self.start_btn.setMinimumWidth(160)
        self.start_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6a00, stop:1 #e04800); "
            "color: #ffffff; font-weight: 800; font-size: 13px; border: 1px solid #ff8833; border-radius: 8px; padding: 6px 18px; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7d1a, stop:1 #f05400); border-color: #ffa352; }"
        )
        self.start_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.start_btn)

        layout.addLayout(btn_layout)

    def _apply_dark_style(self):
        self.setStyleSheet("""
            QDialog { background-color: #0f1724; }
            QLabel { color: #d7e3f4; background-color: transparent; }
            QGroupBox {
                color: #f8fbff; font-weight: 700; font-size: 13px;
                border: 1px solid #253347; border-radius: 10px; margin-top: 10px; padding-top: 12px;
                background-color: #131c2a;
            }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left; left: 14px;
                padding: 0 4px; color: #ff7b1a; font-weight: bold;
            }
            QComboBox {
                background-color: #1a2738; color: #f8fbff; border: 1px solid #344862;
                border-radius: 6px; padding: 4px 10px; font-weight: 600; font-size: 12px;
            }
            QComboBox:hover { border-color: #ff7b1a; }
            QComboBox QAbstractItemView {
                background-color: #131c2a; color: #f8fbff; selection-background-color: #ff6a00;
                selection-color: #ffffff; border: 1px solid #344862;
            }
            QSlider::groove:horizontal {
                height: 6px; background: #223246; border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #ff6a00; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #f8fbff; border: 2px solid #ff7b1a; width: 14px; margin-top: -5px;
                margin-bottom: -5px; border-radius: 7px;
            }
            QCheckBox {
                color: #d7e3f4; spacing: 8px; font-size: 12px;
            }
            QCheckBox::indicator {
                width: 16px; height: 16px; border-radius: 4px; border: 1px solid #344862; background: #1a2738;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6a00; border-color: #ff8833;
            }
            QPushButton {
                background-color: #22344d; color: #f8fbff; border: 1px solid #34506f;
                border-radius: 8px; padding: 6px 14px; font-weight: 600;
            }
            QPushButton:hover { background-color: #29405d; }
        """)

    def get_selected_voice(self) -> dict[str, str]:
        """Trả về dict chứa thông tin giọng đã chọn {id, name, provider}."""
        data = self.combo_voice.currentData()
        if isinstance(data, dict):
            return data
        return {"id": "adam1", "name": "Adam", "provider": "piper"}

    def get_audio_mix_settings(self) -> dict[str, float]:
        """Trả về cài đặt hòa âm tỷ lệ float [0.0, 1.0]."""
        orig_vol = float(self.slider_orig.value()) / 100.0
        tts_vol = float(self.slider_tts.value()) / 100.0
        return {
            "original_volume": orig_vol,
            "tts_volume": tts_vol,
            "duck_volume": min(orig_vol, max(0.05, orig_vol * 0.40)) if orig_vol > 0.001 else 0.0,
        }

    def is_blur_mask_enabled(self) -> bool:
        return self.chk_blur_mask.isChecked()

    def is_burn_subtitles_enabled(self) -> bool:
        return self.chk_burn_subtitles.isChecked()

    def _refresh_deepseek_status(self):
        provider = str(os.getenv("OPENAI_PROVIDER") or os.getenv("AI_POLISHER_PROVIDER") or "deepseek").strip().lower()
        deepseek_key = str(os.getenv("DEEPSEEK_API_KEY", "")).strip()
        if provider == "google":
            self.lbl_ds.setText("🟢 Dịch thuật: Google Dịch (Miễn phí, không cần API Key)")
            self.lbl_ds.setStyleSheet("color: #4ade80; font-size: 11px; font-weight: 600;")
        elif deepseek_key:
            masked = deepseek_key[:7] + "..." + deepseek_key[-4:] if len(deepseek_key) > 12 else "Đã thiết lập"
            self.lbl_ds.setText(f"🟢 DeepSeek AI: Đã kết nối API ({masked})")
            self.lbl_ds.setStyleSheet("color: #3ddc97; font-size: 11px; font-weight: 600;")
        else:
            self.lbl_ds.setText("🟡 Chưa có DeepSeek API Key (Bấm nút bên cạnh để nhập)")
            self.lbl_ds.setStyleSheet("color: #f0b347; font-size: 11px; font-weight: 600;")

    def _open_ai_settings(self):
        from ui.dialogs.ai_settings_dialog import AiSettingsDialog
        dlg = AiSettingsDialog(self, workspace_root=self.workspace_root)
        if dlg.exec() == QDialog.Accepted:
            self._refresh_deepseek_status()
