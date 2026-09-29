"""Dual Voice (Male & Female) Setup Dialog for Role-Based Automation.

Allows users to configure multi-voice role assignments (Male Lead + Female Lead),
speech speed, audio ducking, subtitle burning, and blur masking for selected batch videos.
"""

from __future__ import annotations

import os
import re
from typing import Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.services.video_export_service import SubtitleRenderConfig
from ui.dialogs.select_master_dialog import (
    AVAILABLE_FEMALE_VOICES,
    AVAILABLE_MALE_VOICES,
)


class DualVoiceSetupDialog(QDialog):
    """Hộp thoại Cài đặt Phân vai Nam & Nữ cho một hoặc nhiều video."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        video_paths: list[str] | None = None,
        workspace_root: str = "",
        initial_orig_volume: int = 50,
        initial_tts_volume: int = 100,
    ):
        super().__init__(parent)
        self.video_paths = [os.path.normpath(p) for p in (video_paths or []) if p]
        self.workspace_root = workspace_root or os.getcwd()
        self.initial_orig_volume = max(0, min(100, int(initial_orig_volume)))
        self.initial_tts_volume = max(0, min(200, int(initial_tts_volume)))
        self.start_now = False

        count = len(self.video_paths)
        if count > 1:
            self.setWindowTitle(f"Cài đặt Phân vai Nam/Nữ ({count} video đã chọn) - TankVideo")
        else:
            self.setWindowTitle("Cài đặt Phân vai Nam/Nữ & Lồng tiếng AI - TankVideo")

        self.resize(880, 720)
        self.setMinimumSize(800, 580)
        self.setWindowFlags(self.windowFlags() | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)

        self._setup_ui()
        self._apply_dark_style()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(8, 6, 14, 6)
        layout.setSpacing(12)

        # ── Header Title ──
        count = len(self.video_paths)
        title_text = f"👥 CÀI ĐẶT PHÂN VAI (NAM & NỮ) CHO {count} VIDEO ĐÃ CHỌN" if count > 1 else "👥 CÀI ĐẶT PHÂN VAI (NAM & NỮ) LỒNG TIẾNG AI"
        title_label = QLabel(title_text)
        t_font = QFont()
        t_font.setPointSize(12)
        t_font.setBold(True)
        title_label.setFont(t_font)
        title_label.setStyleSheet("color: #C084FC;")
        layout.addWidget(title_label)

        desc_label = QLabel(
            "Hệ thống tự động phân tách nhân vật bằng AI ➔ Nhân vật Nam lồng giọng Nam, nhân vật Nữ lồng giọng Nữ.\n"
            "Mỗi video sẽ lưu giữ cấu hình phân vai này để khi tạo video sẽ lồng tiếng chính xác theo từng vai."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #94A3B8; font-size: 11px; line-height: 1.4;")
        layout.addWidget(desc_label)

        if self.video_paths:
            names = [os.path.basename(p) for p in self.video_paths]
            disp = ", ".join(names[:3]) + (f" ...và {len(names) - 3} video khác" if len(names) > 3 else "")
            v_box = QLabel(f"🎬 Video áp dụng: {disp}")
            v_box.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: 600; background: #162032; padding: 4px 8px; border-radius: 4px;")
            layout.addWidget(v_box)

        # ── 1. KHUNG CHỌN GIỌNG NAM & GIỌNG NỮ ──
        role_box = QGroupBox("1. Chọn giọng đọc theo vai (Nam & Nữ)")
        role_layout = QVBoxLayout(role_box)
        role_layout.setSpacing(10)
        role_layout.setContentsMargins(12, 14, 12, 12)

        # Giọng Nam
        male_row = QHBoxLayout()
        male_row.setSpacing(8)
        lbl_m = QLabel("👨 Giọng Nam:")
        lbl_m.setFixedWidth(110)
        lbl_m.setStyleSheet("font-weight: 700; color: #60A5FA; font-size: 12px;")
        male_row.addWidget(lbl_m)

        self.combo_male = QComboBox()
        self.combo_male.setFixedHeight(32)
        for v in AVAILABLE_MALE_VOICES:
            p = v.get("provider", "").upper()
            self.combo_male.addItem(f"{v['name']} ({p})", v)
        male_row.addWidget(self.combo_male, 1)

        self.btn_preview_male = QPushButton("🔊 Nghe thử")
        self.btn_preview_male.setFixedHeight(30)
        self.btn_preview_male.setStyleSheet(
            "QPushButton { background: #1E293B; color: #60A5FA; font-weight: 700; font-size: 11px; padding: 0 10px; border: 1px solid #2563EB; border-radius: 4px; } "
            "QPushButton:hover { background: #2563EB; color: #fff; }"
        )
        self.btn_preview_male.clicked.connect(self._preview_male_voice)
        male_row.addWidget(self.btn_preview_male)
        role_layout.addLayout(male_row)

        # Giọng Nữ
        female_row = QHBoxLayout()
        female_row.setSpacing(8)
        lbl_f = QLabel("👩 Giọng Nữ:")
        lbl_f.setFixedWidth(110)
        lbl_f.setStyleSheet("font-weight: 700; color: #F472B6; font-size: 12px;")
        female_row.addWidget(lbl_f)

        self.combo_female = QComboBox()
        self.combo_female.setFixedHeight(32)
        for v in AVAILABLE_FEMALE_VOICES:
            p = v.get("provider", "").upper()
            self.combo_female.addItem(f"{v['name']} ({p})", v)
        female_row.addWidget(self.combo_female, 1)

        self.btn_preview_female = QPushButton("🔊 Nghe thử")
        self.btn_preview_female.setFixedHeight(30)
        self.btn_preview_female.setStyleSheet(
            "QPushButton { background: #1E293B; color: #F472B6; font-weight: 700; font-size: 11px; padding: 0 10px; border: 1px solid #DB2777; border-radius: 4px; } "
            "QPushButton:hover { background: #DB2777; color: #fff; }"
        )
        self.btn_preview_female.clicked.connect(self._preview_female_voice)
        female_row.addWidget(self.btn_preview_female)
        role_layout.addLayout(female_row)

        # Tốc độ đọc
        spd_row = QHBoxLayout()
        spd_row.setSpacing(8)
        lbl_spd = QLabel("⚡ Tốc độ đọc:")
        lbl_spd.setFixedWidth(110)
        lbl_spd.setStyleSheet("font-weight: 600; color: #E2E8F0; font-size: 11px;")
        spd_row.addWidget(lbl_spd)

        self.slider_speed = QSlider(Qt.Horizontal)
        self.slider_speed.setRange(80, 150)
        self.slider_speed.setValue(100)
        self.lbl_speed_val = QLabel("1.00x")
        self.lbl_speed_val.setFixedWidth(45)
        self.lbl_speed_val.setStyleSheet("color: #FF8A00; font-weight: 700;")
        self.slider_speed.valueChanged.connect(lambda v: self.lbl_speed_val.setText(f"{v / 100:.2f}x"))
        spd_row.addWidget(self.slider_speed, 1)
        spd_row.addWidget(self.lbl_speed_val)
        role_layout.addLayout(spd_row)

        layout.addWidget(role_box)

        # ── 2. KHUNG ÂM LƯỢNG & HẠ NHẠC NỀN ──
        vol_box = QGroupBox("2. Cài đặt âm lượng & Trộn âm thanh")
        vol_layout = QVBoxLayout(vol_box)
        vol_layout.setSpacing(10)
        vol_layout.setContentsMargins(12, 14, 12, 12)

        # Âm lượng gốc
        a1_row = QHBoxLayout()
        lbl_a1 = QLabel("🎵 Âm thanh gốc (A1):")
        lbl_a1.setFixedWidth(140)
        lbl_a1.setStyleSheet("color: #E2E8F0; font-size: 11px;")
        a1_row.addWidget(lbl_a1)

        self.slider_a1 = QSlider(Qt.Horizontal)
        self.slider_a1.setRange(0, 100)
        self.slider_a1.setValue(self.initial_orig_volume)
        self.lbl_a1_val = QLabel(f"{self.initial_orig_volume}%")
        self.lbl_a1_val.setFixedWidth(40)
        self.lbl_a1_val.setStyleSheet("color: #38BDF8; font-weight: 700;")
        self.slider_a1.valueChanged.connect(lambda v: self.lbl_a1_val.setText(f"{v}%"))
        a1_row.addWidget(self.slider_a1, 1)
        a1_row.addWidget(self.lbl_a1_val)
        vol_layout.addLayout(a1_row)

        # Âm lượng giọng lồng tiếng
        a2_row = QHBoxLayout()
        lbl_a2 = QLabel("🗣️ Giọng đọc AI (A2):")
        lbl_a2.setFixedWidth(140)
        lbl_a2.setStyleSheet("color: #E2E8F0; font-size: 11px;")
        a2_row.addWidget(lbl_a2)

        self.slider_a2 = QSlider(Qt.Horizontal)
        self.slider_a2.setRange(0, 200)
        self.slider_a2.setValue(self.initial_tts_volume)
        self.lbl_a2_val = QLabel(f"{self.initial_tts_volume}%")
        self.lbl_a2_val.setFixedWidth(40)
        self.lbl_a2_val.setStyleSheet("color: #4ADE80; font-weight: 700;")
        self.slider_a2.valueChanged.connect(lambda v: self.lbl_a2_val.setText(f"{v}%"))
        a2_row.addWidget(self.slider_a2, 1)
        a2_row.addWidget(self.lbl_a2_val)
        vol_layout.addLayout(a2_row)

        self.chk_ducking = QCheckBox("Tự động hạ nhỏ âm thanh gốc (Ducking) khi nhân vật nói")
        self.chk_ducking.setChecked(True)
        self.chk_ducking.setStyleSheet("color: #94A3B8; font-size: 11px;")
        vol_layout.addWidget(self.chk_ducking)

        layout.addWidget(vol_box)

        # ── 3. KHUNG CHE MỜ & ĐÈ PHỤ ĐỀ ──
        sub_box = QGroupBox("3. Tùy chọn Phụ đề & Che mờ")
        sub_layout = QVBoxLayout(sub_box)
        sub_layout.setSpacing(8)
        sub_layout.setContentsMargins(12, 14, 12, 12)

        self.chk_blur_mask = QCheckBox("Che mờ chữ phụ đề gốc (Sử dụng khung OCR đã lưu của từng video)")
        self.chk_blur_mask.setChecked(True)
        self.chk_blur_mask.setStyleSheet("color: #E2E8F0; font-weight: 600; font-size: 11px;")
        sub_layout.addWidget(self.chk_blur_mask)

        self.chk_burn_subs = QCheckBox("Đè phụ đề dịch tiếng Việt lên video kết quả")
        self.chk_burn_subs.setChecked(True)
        self.chk_burn_subs.setStyleSheet("color: #E2E8F0; font-weight: 600; font-size: 11px;")
        sub_layout.addWidget(self.chk_burn_subs)

        layout.addWidget(sub_box)

        scroll.setWidget(content_widget)
        root_layout.addWidget(scroll, 1)

        # ── NÚT BẤM DƯỚI CÙNG ──
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Hủy")
        self.cancel_btn.setMinimumHeight(36)
        self.cancel_btn.setMinimumWidth(80)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        save_txt = f"💾 Lưu cấu hình phân vai ({count} video)" if count > 1 else "💾 Lưu cấu hình phân vai"
        self.save_btn = QPushButton(save_txt)
        self.save_btn.setMinimumHeight(36)
        self.save_btn.setStyleSheet(
            "QPushButton { background: #4C1D95; color: #EDE9FE; font-weight: 700; font-size: 12px; "
            "border: 1px solid #7C3AED; border-radius: 6px; padding: 0 16px; } "
            "QPushButton:hover { background: #6D28D9; color: #fff; }"
        )
        self.save_btn.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(self.save_btn)

        create_txt = f"⚡ Áp dụng & Tạo ngay ({count} video)" if count > 1 else "⚡ Áp dụng & Tạo ngay"
        self.create_now_btn = QPushButton(create_txt)
        self.create_now_btn.setMinimumHeight(36)
        self.create_now_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF6B00, stop:1 #FF9500); "
            "color: #ffffff; font-weight: 800; font-size: 12px; border: 1px solid #FF8A00; border-radius: 6px; padding: 0 16px; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF8A00, stop:1 #FFB347); }"
        )
        self.create_now_btn.clicked.connect(self._on_create_now_clicked)
        btn_layout.addWidget(self.create_now_btn)

        root_layout.addLayout(btn_layout)

    def _preview_male_voice(self):
        v_data = self.combo_male.currentData()
        if v_data:
            self._play_sample_audio(v_data)

    def _preview_female_voice(self):
        v_data = self.combo_female.currentData()
        if v_data:
            self._play_sample_audio(v_data)

    def _play_sample_audio(self, voice_data: dict):
        try:
            from services.tts_service import TTSService
            v_id = voice_data.get("id", "")
            svc = TTSService(self.workspace_root)
            if hasattr(svc, "play_preview"):
                svc.play_preview(v_id)
        except Exception:
            pass

    def _on_save_clicked(self):
        self.start_now = False
        self.accept()

    def _on_create_now_clicked(self):
        self.start_now = True
        self.accept()

    def get_voice_config(self) -> dict[str, Any]:
        """Trả về cấu hình phân vai đã được người dùng thiết lập."""
        male_data = self.combo_male.currentData() or {}
        female_data = self.combo_female.currentData() or {}
        speed = self.slider_speed.value() / 100.0
        return {
            "mode": "multi",
            "male_voice": male_data,
            "female_voice": female_data,
            "speed": speed,
            "orig_volume": self.slider_a1.value(),
            "tts_volume": self.slider_a2.value(),
            "ducking": self.chk_ducking.isChecked(),
            "blur_mask": self.chk_blur_mask.isChecked(),
            "burn_subtitles": self.chk_burn_subs.isChecked(),
            "start_now": self.start_now,
        }

    def _apply_dark_style(self):
        self.setStyleSheet("""
            QDialog { background-color: #0F172A; }
            QLabel { color: #E2E8F0; background-color: transparent; }
            QGroupBox {
                color: #F8FAFC; font-weight: 700; font-size: 12px;
                border: 1px solid #1E293B; border-radius: 8px; margin-top: 10px; padding-top: 14px;
                background-color: #141E33;
            }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left; left: 12px;
                padding: 0 4px; color: #C084FC; font-weight: bold;
            }
            QComboBox {
                background-color: #1E293B; color: #F8FAFC; border: 1px solid #334155;
                border-radius: 5px; padding: 4px 8px; font-weight: 600; font-size: 11px;
            }
            QComboBox:hover { border-color: #A855F7; }
            QComboBox QAbstractItemView {
                background-color: #141E33; color: #F8FAFC; selection-background-color: #7C3AED;
                selection-color: #ffffff; border: 1px solid #334155;
            }
            QSlider::groove:horizontal {
                height: 5px; background: #1E293B; border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #A855F7; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #C084FC; width: 14px; margin-top: -5px; margin-bottom: -5px; border-radius: 7px;
            }
        """)
