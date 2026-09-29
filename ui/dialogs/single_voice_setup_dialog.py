"""Single Voice Setup Dialog for 1-Voice Full Pipeline Automation.

Allows users to configure 1 voice narrator, audio mixing levels (original volume vs TTS volume),
blur mask for Chinese subtitles, subtitle burning, and DeepSeek contextual translation.
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
    _load_available_voices,
)
from ui.widgets.subtitle_style_group import SubtitleStyleGroupBox


class SingleVoiceSetupDialog(QDialog):
    """Hộp thoại Cài đặt Lồng tiếng 1 giọng & Tạo video tự động."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        video_path: str = "",
        video_paths: list[str] | None = None,
        initial_orig_volume: int = 50,
        initial_tts_volume: int = 100,
        blur_rect: tuple[float, float, float, float] | None = None,
        workspace_root: str = "",
        initial_voice_id: str = "",
        individual_voices: dict[str, dict[str, str]] | None = None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.video_paths = [os.path.normpath(p) for p in (video_paths or []) if p]
        if not self.video_path and self.video_paths:
            self.video_path = self.video_paths[0]
        self.workspace_root = workspace_root or os.getcwd()
        self.initial_orig_volume = max(0, min(100, int(initial_orig_volume)))
        self.initial_tts_volume = max(0, min(200, int(initial_tts_volume)))
        self.blur_rect = blur_rect
        self.initial_voice_id = initial_voice_id
        self.individual_voices = individual_voices
        self.start_now = False

        self.setWindowTitle("Cài đặt lồng tiếng (1 giọng) & Tạo video tự động")
        # Tự động tính toán kích thước rộng rãi, vừa vặn độ phân giải màn hình
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            target_w = max(900, min(1020, int(geo.width() * 0.75)))
            target_h = max(780, min(900, int(geo.height() * 0.90)))
            self.resize(target_w, target_h)
        else:
            self.resize(940, 840)
        self.setMinimumSize(850, 600)

        # Cho phép click bên ngoài dialog để đóng (dismiss/cancel)
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
        layout.setSpacing(14)

        # Header Title
        count = len(self.video_paths)
        title_text = f"🎬 CÀI ĐẶT LỒNG TIẾNG (1 GIỌNG) CHO {count} VIDEO ĐÃ CHỌN" if count > 1 else "🎬 CÀI ĐẶT LỒNG TIẾNG (1 GIỌNG) & TẠO VIDEO"
        title_label = QLabel(title_text)
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

        if count > 1:
            names = [os.path.basename(p) for p in self.video_paths]
            disp = ", ".join(names[:3]) + (f" ...và {len(names) - 3} video khác" if len(names) > 3 else "")
            v_box = QLabel(f"🎬 Video áp dụng: {disp}")
            v_box.setStyleSheet("color: #38BDF8; font-size: 11px; font-weight: 600; background: #162032; padding: 4px 8px; border-radius: 4px;")
            layout.addWidget(v_box)

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

        # Nạp động danh sách giọng đọc mới nhất
        try:
            cur_females, cur_males = _load_available_voices()
        except Exception:
            cur_females, cur_males = AVAILABLE_FEMALE_VOICES, AVAILABLE_MALE_VOICES

        # Tổng hợp danh sách giọng đọc
        all_voices = []
        # VieNeu VIP
        all_voices.append({"id": "vieneu_thanhnientutin", "name": "👑 Thanh niên tự tin (VieNeu Neural VIP)", "provider": "vieneu"})
        all_voices.append({"id": "vieneu_cogaihoatbat", "name": "👑 Cô gái hoạt ngôn (VieNeu Neural VIP)", "provider": "vieneu"})
        # Piper & Edge
        seen = {"vieneu_thanhnientutin", "vieneu_cogaihoatbat"}
        for v in cur_males:
            if v["id"] not in seen:
                seen.add(v["id"])
                prefix = "👨 " if "vieneu" not in v["id"] else ""
                all_voices.append({**v, "name": f"{prefix}{v['name']}"})
        for v in cur_females:
            if v["id"] not in seen:
                seen.add(v["id"])
                prefix = "👩 " if "vieneu" not in v["id"] else ""
                all_voices.append({**v, "name": f"{prefix}{v['name']}"})

        # Kiểm tra xem các video đã chọn có cài giọng riêng từ trước không
        has_individual = False
        indiv_map = getattr(self, "individual_voices", None)
        if indiv_map is None and self.parent() and hasattr(self.parent(), "_video_voice_configs"):
            indiv_map = {}
            for p in self.video_paths:
                cfg = getattr(self.parent(), "_video_voice_configs", {}).get(os.path.normpath(p), {})
                if cfg.get("voice_name") and cfg.get("label"):
                    indiv_map[os.path.normpath(p)] = cfg

        if len(self.video_paths) > 1 and indiv_map and len(indiv_map) > 0:
            summaries = []
            for p in self.video_paths:
                c = indiv_map.get(os.path.normpath(p), {})
                v_l = c.get("label", "")
                base = os.path.basename(p)
                short_b = base if len(base) <= 12 else base[:10] + "…"
                if v_l:
                    summaries.append(f"{short_b}: {v_l}")
                else:
                    summaries.append(f"{short_b}: Mặc định")
            summ_txt = ", ".join(summaries[:2]) + ("..." if len(summaries) > 2 else "")
            keep_item = {
                "id": "keep_individual",
                "name": f"🎯 Giữ nguyên giọng riêng từng video ({summ_txt})",
                "provider": "individual",
            }
            all_voices.insert(0, keep_item)
            has_individual = True

        def_voice_idx = 0
        if not has_individual:
            target_v = getattr(self, "initial_voice_id", "").strip()
            for idx, item in enumerate(all_voices):
                if target_v and (item["id"] == target_v or target_v in item["id"]):
                    def_voice_idx = idx
                    break
                elif not target_v and item["id"] in ("adam1", "adam"):
                    def_voice_idx = idx

        for idx, item in enumerate(all_voices):
            self.combo_voice.addItem(item["name"], item)

        self.combo_voice.setCurrentIndex(def_voice_idx)
        v_row.addWidget(self.combo_voice, 1)
        voice_layout.addLayout(v_row)

        self.voice_hint = QLabel("Giọng này sẽ được dùng để lồng tiếng cho toàn bộ các câu thoại trong video.")
        self.voice_hint.setStyleSheet("color: #8ea3bb; font-size: 11px;")
        voice_layout.addWidget(self.voice_hint)

        def _update_voice_hint():
            cur = self.combo_voice.currentData()
            if isinstance(cur, dict) and cur.get("id") == "keep_individual":
                self.voice_hint.setText("💡 Mỗi video trong hàng đợi sẽ được tạo đúng theo giọng đọc bạn đã chọn trên từng thẻ video.")
                self.voice_hint.setStyleSheet("color: #34D399; font-size: 11px; font-weight: bold;")
            elif len(self.video_paths) > 1:
                self.voice_hint.setText("⚠️ Áp dụng giọng này để thay thế cho toàn bộ các video trong hàng đợi.")
                self.voice_hint.setStyleSheet("color: #FBBF24; font-size: 11px;")
            else:
                self.voice_hint.setText("Giọng này sẽ được dùng để lồng tiếng cho toàn bộ các câu thoại trong video.")
                self.voice_hint.setStyleSheet("color: #8ea3bb; font-size: 11px;")

        self.combo_voice.currentIndexChanged.connect(_update_voice_hint)
        _update_voice_hint()

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

        # --- 4. KHUNG KIỂU DÁNG PHỤ ĐỀ & HỘP NỀN CHE VIDEO ---
        self.sub_style_group = SubtitleStyleGroupBox(self, parent_window=self.parent())
        self.chk_burn_subtitles.toggled.connect(self.sub_style_group.setEnabled)
        layout.addWidget(self.sub_style_group)

        # --- 5. KHUNG LOGO THƯƠNG HIỆU & HÌNH MỜ (WATERMARK) ---
        branding_box = QGroupBox("5. Logo Thương hiệu & Hình mờ Bản quyền (Watermark)")
        branding_layout = QVBoxLayout(branding_box)
        branding_layout.setSpacing(12)
        branding_layout.setContentsMargins(12, 14, 12, 12)

        # === PHẦN A: LOGO THƯƠNG HIỆU (BRAND LOGO) ===
        self.chk_enable_logo = QCheckBox("Bật hiển thị Logo thương hiệu xuyên suốt video")
        self.chk_enable_logo.setStyleSheet("color: #ff9d42; font-weight: bold; font-size: 12px;")
        branding_layout.addWidget(self.chk_enable_logo)

        self.logo_container = QWidget()
        logo_c_layout = QVBoxLayout(self.logo_container)
        logo_c_layout.setContentsMargins(18, 0, 0, 4)
        logo_c_layout.setSpacing(8)

        # Hàng 1: Chọn file ảnh logo & thumbnail xem trước
        logo_file_row = QHBoxLayout()
        logo_file_row.setSpacing(8)
        lbl_l_file = QLabel("Ảnh Logo:")
        lbl_l_file.setStyleSheet("color: #d7e3f4; font-size: 12px; font-weight: 600;")
        lbl_l_file.setMinimumWidth(70)
        logo_file_row.addWidget(lbl_l_file)

        self.txt_logo_path = QLineEdit()
        self.txt_logo_path.setPlaceholderText("Chọn file ảnh logo (.png, .jpg, .webp)...")
        self.txt_logo_path.setStyleSheet("background-color: #1a2738; color: #f8fbff; border: 1px solid #344862; border-radius: 6px; padding: 5px 8px; font-size: 11px;")
        logo_file_row.addWidget(self.txt_logo_path, 1)

        self.btn_browse_logo = QPushButton("📁 Chọn ảnh...")
        self.btn_browse_logo.setStyleSheet("""
            QPushButton {
                background-color: #1e293b; color: #38bdf8;
                border: 1px solid #334155; border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 600;
            }
            QPushButton:hover { background-color: #334155; color: #fff; }
        """)
        self.btn_browse_logo.clicked.connect(self._browse_logo_file)
        logo_file_row.addWidget(self.btn_browse_logo)

        # Thumbnail preview nhỏ
        self.lbl_logo_preview = QLabel()
        self.lbl_logo_preview.setFixedSize(40, 40)
        self.lbl_logo_preview.setAlignment(Qt.AlignCenter)
        self.lbl_logo_preview.setStyleSheet("border: 1px dashed #344862; border-radius: 6px; background-color: #16202e; color: #64748b; font-size: 9px;")
        self.lbl_logo_preview.setText("Logo")
        logo_file_row.addWidget(self.lbl_logo_preview)
        logo_c_layout.addLayout(logo_file_row)

        # Hàng 2: Vị trí logo & Kích thước & Độ mờ
        logo_opt_row = QHBoxLayout()
        logo_opt_row.setSpacing(12)

        lbl_l_pos = QLabel("Vị trí:")
        lbl_l_pos.setStyleSheet("color: #d7e3f4; font-size: 11px;")
        logo_opt_row.addWidget(lbl_l_pos)

        self.combo_logo_pos = QComboBox()
        self.combo_logo_pos.addItem("Góc trên trái (Top-Left) ★ Khuyên dùng", "top_left")
        self.combo_logo_pos.addItem("Góc trên phải (Top-Right)", "top_right")
        self.combo_logo_pos.addItem("Góc dưới trái (Bottom-Left)", "bottom_left")
        self.combo_logo_pos.addItem("Góc dưới phải (Bottom-Right)", "bottom_right")
        self.combo_logo_pos.addItem("Chính giữa (Center)", "center")
        self.combo_logo_pos.addItem("Góc trên giữa (Top-Center)", "top_center")
        logo_opt_row.addWidget(self.combo_logo_pos, 1)

        lbl_l_size = QLabel("Kích thước:")
        lbl_l_size.setStyleSheet("color: #d7e3f4; font-size: 11px;")
        logo_opt_row.addWidget(lbl_l_size)

        self.slider_logo_size = QSlider(Qt.Horizontal)
        self.slider_logo_size.setRange(5, 35)
        self.slider_logo_size.setValue(15)
        self.lbl_logo_size_val = QLabel("15%")
        self.lbl_logo_size_val.setMinimumWidth(32)
        self.lbl_logo_size_val.setStyleSheet("color: #ff9d42; font-weight: bold; font-size: 11px;")
        self.slider_logo_size.valueChanged.connect(lambda v: self.lbl_logo_size_val.setText(f"{v}%"))
        logo_opt_row.addWidget(self.slider_logo_size)
        logo_opt_row.addWidget(self.lbl_logo_size_val)

        lbl_l_op = QLabel("Độ mờ:")
        lbl_l_op.setStyleSheet("color: #d7e3f4; font-size: 11px;")
        logo_opt_row.addWidget(lbl_l_op)

        self.slider_logo_opacity = QSlider(Qt.Horizontal)
        self.slider_logo_opacity.setRange(10, 100)
        self.slider_logo_opacity.setValue(100)
        self.lbl_logo_opacity_val = QLabel("100%")
        self.lbl_logo_opacity_val.setMinimumWidth(36)
        self.lbl_logo_opacity_val.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px;")
        self.slider_logo_opacity.valueChanged.connect(lambda v: self.lbl_logo_opacity_val.setText(f"{v}%"))
        logo_opt_row.addWidget(self.slider_logo_opacity)
        logo_opt_row.addWidget(self.lbl_logo_opacity_val)

        logo_c_layout.addLayout(logo_opt_row)
        branding_layout.addWidget(self.logo_container)

        self.chk_enable_logo.toggled.connect(self.logo_container.setEnabled)
        self.txt_logo_path.textChanged.connect(self._update_logo_preview)

        # Phân cách mỏng giữa Logo và Watermark
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #1e293b; margin: 4px 0;")
        branding_layout.addWidget(sep)

        # === PHẦN B: HÌNH MỜ CHỮ (TEXT WATERMARK) ===
        self.chk_enable_watermark = QCheckBox("Bật hình mờ chữ (Watermark chống reup) xuyên suốt video")
        self.chk_enable_watermark.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 12px;")
        branding_layout.addWidget(self.chk_enable_watermark)

        self.wm_container = QWidget()
        wm_c_layout = QVBoxLayout(self.wm_container)
        wm_c_layout.setContentsMargins(18, 0, 0, 0)
        wm_c_layout.setSpacing(8)

        # Hàng 1: Nhập chữ watermark & Vị trí
        wm_row1 = QHBoxLayout()
        wm_row1.setSpacing(8)

        lbl_wm_text = QLabel("Chữ Watermark:")
        lbl_wm_text.setStyleSheet("color: #d7e3f4; font-size: 12px; font-weight: 600;")
        lbl_wm_text.setMinimumWidth(95)
        wm_row1.addWidget(lbl_wm_text)

        self.txt_watermark = QLineEdit()
        self.txt_watermark.setPlaceholderText("Ví dụ: Nhím Review, Tên Kênh...")
        self.txt_watermark.setStyleSheet("background-color: #1a2738; color: #f8fbff; border: 1px solid #344862; border-radius: 6px; padding: 5px 8px; font-size: 11px;")
        wm_row1.addWidget(self.txt_watermark, 1)

        lbl_wm_pos = QLabel("Vị trí:")
        lbl_wm_pos.setStyleSheet("color: #d7e3f4; font-size: 11px;")
        wm_row1.addWidget(lbl_wm_pos)

        self.combo_watermark_pos = QComboBox()
        self.combo_watermark_pos.addItem("Chính giữa video (Center) ★ Khuyên dùng", "center")
        self.combo_watermark_pos.addItem("Gần giữa dưới (trên phụ đề)", "center_bottom")
        self.combo_watermark_pos.addItem("Góc trên trái (Top-Left)", "top_left")
        self.combo_watermark_pos.addItem("Góc trên phải (Top-Right)", "top_right")
        self.combo_watermark_pos.addItem("Góc dưới trái (Bottom-Left)", "bottom_left")
        self.combo_watermark_pos.addItem("Góc dưới phải (Bottom-Right)", "bottom_right")
        wm_row1.addWidget(self.combo_watermark_pos, 1)
        wm_c_layout.addLayout(wm_row1)

        # Hàng 2: Độ to & Độ mờ
        wm_row2 = QHBoxLayout()
        wm_row2.setSpacing(12)

        lbl_wm_size = QLabel("Độ to (Cỡ chữ):")
        lbl_wm_size.setStyleSheet("color: #d7e3f4; font-size: 11px;")
        wm_row2.addWidget(lbl_wm_size)

        self.slider_watermark_size = QSlider(Qt.Horizontal)
        self.slider_watermark_size.setRange(18, 80)
        self.slider_watermark_size.setValue(36)
        self.lbl_watermark_size_val = QLabel("36px")
        self.lbl_watermark_size_val.setMinimumWidth(38)
        self.lbl_watermark_size_val.setStyleSheet("color: #ff9d42; font-weight: bold; font-size: 11px;")
        self.slider_watermark_size.valueChanged.connect(lambda v: self.lbl_watermark_size_val.setText(f"{v}px"))
        wm_row2.addWidget(self.slider_watermark_size, 1)
        wm_row2.addWidget(self.lbl_watermark_size_val)

        lbl_wm_op = QLabel("Độ mờ (Độ trong suốt):")
        lbl_wm_op.setStyleSheet("color: #d7e3f4; font-size: 11px;")
        wm_row2.addWidget(lbl_wm_op)

        self.slider_watermark_opacity = QSlider(Qt.Horizontal)
        self.slider_watermark_opacity.setRange(10, 100)
        self.slider_watermark_opacity.setValue(35)
        self.lbl_watermark_opacity_val = QLabel("35%")
        self.lbl_watermark_opacity_val.setMinimumWidth(36)
        self.lbl_watermark_opacity_val.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px;")
        self.slider_watermark_opacity.valueChanged.connect(lambda v: self.lbl_watermark_opacity_val.setText(f"{v}%"))
        wm_row2.addWidget(self.slider_watermark_opacity, 1)
        wm_row2.addWidget(self.lbl_watermark_opacity_val)

        wm_c_layout.addLayout(wm_row2)
        branding_layout.addWidget(self.wm_container)

        self.chk_enable_watermark.toggled.connect(self.wm_container.setEnabled)
        layout.addWidget(branding_box)

        # Nạp cài đặt đã lưu trước đó
        self._load_branding_settings()

        scroll.setWidget(content_widget)
        root_layout.addWidget(scroll, 1)

        # --- NÚT HÀNH ĐỘNG ---
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Hủy")
        self.cancel_btn.setMinimumHeight(38)
        self.cancel_btn.setMinimumWidth(100)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        count = len(self.video_paths)
        btn_txt = f"🚀 Bắt đầu tạo video ({count} video)" if count > 1 else "🚀 Bắt đầu tạo video"
        self.start_btn = QPushButton(btn_txt)
        self.start_btn.setObjectName("primaryActionBtn")
        self.start_btn.setMinimumHeight(38)
        self.start_btn.setMinimumWidth(180)
        self.start_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6a00, stop:1 #e04800); "
            "color: #ffffff; font-weight: 800; font-size: 13px; border: 1px solid #ff8833; border-radius: 8px; padding: 6px 20px; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7d1a, stop:1 #f05400); border-color: #ffa352; }"
        )
        def _on_start_btn_clicked():
            self.start_now = True
            self.accept()
        self.start_btn.clicked.connect(_on_start_btn_clicked)
        btn_layout.addWidget(self.start_btn)

        root_layout.addLayout(btn_layout)

    def get_subtitle_config(self) -> SubtitleRenderConfig:
        """Trả về SubtitleRenderConfig được người dùng chọn."""
        return self.sub_style_group.get_subtitle_render_config()

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

    def get_voice_config(self) -> dict[str, Any]:
        """Trả về cấu hình giọng đọc chuẩn hóa."""
        v = self.get_selected_voice()
        mix = self.get_audio_mix_settings()
        return {
            "mode": "single",
            "voice": v,
            "voice_id": v.get("id", ""),
            "voice_name": v.get("name", ""),
            "provider": v.get("provider", "piper"),
            "orig_volume": int(mix.get("original_volume", 0.5) * 100),
            "tts_volume": int(mix.get("tts_volume", 1.0) * 100),
            "duck_volume": mix.get("duck_volume", 0.2),
            "blur_mask": self.is_blur_mask_enabled(),
            "burn_subtitles": self.is_burn_subtitles_enabled(),
            "start_now": getattr(self, "start_now", False),
        }

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

    def _browse_logo_file(self):
        """Mở hộp thoại chọn file ảnh logo thương hiệu."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file ảnh Logo Thương hiệu",
            os.path.dirname(self.txt_logo_path.text().strip()) if self.txt_logo_path.text().strip() else "",
            "File hình ảnh (*.png *.jpg *.jpeg *.webp *.bmp);;Tất cả file (*.*)",
        )
        if path:
            self.txt_logo_path.setText(os.path.normpath(path))
            self.chk_enable_logo.setChecked(True)
            self._update_logo_preview(path)

    def _update_logo_preview(self, path: str = ""):
        """Cập nhật ảnh thumbnail xem trước của Logo."""
        img_path = (path or self.txt_logo_path.text()).strip()
        if img_path and os.path.isfile(img_path):
            pix = QPixmap(img_path)
            if not pix.isNull():
                scaled = pix.scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_logo_preview.setPixmap(scaled)
                self.lbl_logo_preview.setText("")
                self.lbl_logo_preview.setToolTip(f"Logo: {os.path.basename(img_path)}")
                return
        self.lbl_logo_preview.clear()
        self.lbl_logo_preview.setText("Logo")
        self.lbl_logo_preview.setToolTip("Chưa chọn file ảnh")

    def _load_branding_settings(self):
        """Khôi phục các cài đặt Logo & Watermark đã lưu từ trước."""
        settings = QSettings("TankVideo", "TankVideoStudio")
        # Brand Logo
        enable_logo = settings.value("branding/enable_logo", False, type=bool)
        logo_path = settings.value("branding/logo_path", "", type=str)
        logo_pos = settings.value("branding/logo_pos", "top_left", type=str)
        logo_size = settings.value("branding/logo_size", 15, type=int)
        logo_op = settings.value("branding/logo_opacity", 100, type=int)

        self.chk_enable_logo.setChecked(enable_logo)
        self.logo_container.setEnabled(enable_logo)
        if logo_path:
            self.txt_logo_path.setText(logo_path)
            self._update_logo_preview(logo_path)

        pos_idx = self.combo_logo_pos.findData(logo_pos)
        if pos_idx >= 0:
            self.combo_logo_pos.setCurrentIndex(pos_idx)

        self.slider_logo_size.setValue(max(5, min(35, logo_size)))
        self.slider_logo_opacity.setValue(max(10, min(100, logo_op)))

        # Watermark
        enable_wm = settings.value("branding/enable_watermark", False, type=bool)
        wm_text = settings.value("branding/watermark_text", "", type=str)
        wm_pos = settings.value("branding/watermark_pos", "center", type=str)
        wm_size = settings.value("branding/watermark_size", 36, type=int)
        wm_op = settings.value("branding/watermark_opacity", 35, type=int)

        self.chk_enable_watermark.setChecked(enable_wm)
        self.wm_container.setEnabled(enable_wm)
        if wm_text:
            self.txt_watermark.setText(wm_text)

        wm_pos_idx = self.combo_watermark_pos.findData(wm_pos)
        if wm_pos_idx >= 0:
            self.combo_watermark_pos.setCurrentIndex(wm_pos_idx)

        self.slider_watermark_size.setValue(max(18, min(80, wm_size)))
        self.slider_watermark_opacity.setValue(max(10, min(100, wm_op)))

    def _save_branding_settings(self):
        """Lưu lại cài đặt Logo & Watermark để tiện dùng cho những lần sau."""
        settings = QSettings("TankVideo", "TankVideoStudio")
        # Brand Logo
        settings.setValue("branding/enable_logo", self.chk_enable_logo.isChecked())
        settings.setValue("branding/logo_path", self.txt_logo_path.text().strip())
        settings.setValue("branding/logo_pos", self.combo_logo_pos.currentData() or "top_left")
        settings.setValue("branding/logo_size", self.slider_logo_size.value())
        settings.setValue("branding/logo_opacity", self.slider_logo_opacity.value())

        # Watermark
        settings.setValue("branding/enable_watermark", self.chk_enable_watermark.isChecked())
        settings.setValue("branding/watermark_text", self.txt_watermark.text().strip())
        settings.setValue("branding/watermark_pos", self.combo_watermark_pos.currentData() or "center")
        settings.setValue("branding/watermark_size", self.slider_watermark_size.value())
        settings.setValue("branding/watermark_opacity", self.slider_watermark_opacity.value())

    def get_brand_logo_settings(self) -> dict[str, Any]:
        """Trả về cấu hình Logo thương hiệu được thiết lập."""
        return {
            "enable": self.chk_enable_logo.isChecked() and bool(self.txt_logo_path.text().strip()),
            "path": self.txt_logo_path.text().strip(),
            "position": str(self.combo_logo_pos.currentData() or "top_left"),
            "size_percent": int(self.slider_logo_size.value()),
            "opacity": float(self.slider_logo_opacity.value()) / 100.0,
        }

    def get_watermark_settings(self) -> dict[str, Any]:
        """Trả về cấu hình Hình mờ chữ (Watermark) được thiết lập."""
        return {
            "enable": self.chk_enable_watermark.isChecked() and bool(self.txt_watermark.text().strip()),
            "text": self.txt_watermark.text().strip(),
            "position": str(self.combo_watermark_pos.currentData() or "center"),
            "font_size": int(self.slider_watermark_size.value()),
            "opacity": float(self.slider_watermark_opacity.value()) / 100.0,
            "color": "#FFFFFF",
        }

    def accept(self):
        """Lưu lại cài đặt thương hiệu trước khi chấp nhận."""
        self._save_branding_settings()
        super().accept()
