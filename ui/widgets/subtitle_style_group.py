"""Subtitle Style Group Widget for Video Creation Dialogs.

Provides a unified, intuitive, and modern UI component for configuring:
- Subtitle Presets (Pastel Box, YouTube Box, TikTok, Elegant White, Custom)
- Font family and proportional font sizing (28px - 46px)
- Text color and Background box color with interactive color pickers
- Snug background box toggle & corner radius (for covering underlying video text)
- Entrance animations (Pop In, Fade In, Slide Up, Static)
- Live preview banner showing real-time appearance
- Two-way synchronization with main window left sidebar styling
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.video_export_service import (
    SubtitleRenderConfig,
    ass_color_to_hex,
    hex_to_ass_color,
)

PRESETS_DATA = {
    "blur_mask": {
        "name": "🌫️ Mặt nạ làm mờ ngang (Ảnh 1 - Khuyên dùng)",
        "font_name": "Arial",
        "font_size": 36,
        "text_color": "#FFFFFF",
        "bg_color": "#000000",
        "has_box": False,
        "bold": True,
        "animation": "Bật lên (Pop In)",
        "hint": "Dải làm mờ ngang che sạch chữ gốc video, chữ trắng viền đen dày nổi bật như Ảnh 1.",
        "mask_mode": "blur",
    },
    "pastel_box": {
        "name": "🌸 Hộp hồng Pastel (Bám sát chữ - Che video gốc)",
        "font_name": "Arial",
        "font_size": 34,
        "text_color": "#111111",
        "bg_color": "#FFE5DD",
        "has_box": True,
        "bold": True,
        "animation": "Bật lên (Pop In)",
        "hint": "Khung hồng pastel ôm sát chữ, che sạch chữ gốc, phong cách hiện đại khuyên dùng.",
    },
    "youtube_box": {
        "name": "🖤 Hộp đen YouTube (Phụ đề chuẩn nét - Ảnh 2)",
        "font_name": "Roboto",
        "font_size": 34,
        "text_color": "#FFFFFF",
        "bg_color": "#000000",
        "has_box": True,
        "bold": False,
        "animation": "Mờ dần vào (Fade In)",
        "hint": "Khung đen chữ trắng tương phản cao, rõ ràng trên mọi cảnh quay.",
    },
    "tiktok": {
        "name": "✨ TikTok Xu hướng (Chữ vàng viền đen)",
        "font_name": "Montserrat",
        "font_size": 36,
        "text_color": "#FFD400",
        "bg_color": "#000000",
        "has_box": False,
        "bold": True,
        "animation": "Bật lên (Pop In)",
        "hint": "Chữ vàng viền đen nổi bật, không hộp nền, chuẩn xu hướng video ngắn.",
    },
    "white_box": {
        "name": "🤍 Hộp trắng sữa thanh lịch",
        "font_name": "Inter",
        "font_size": 34,
        "text_color": "#111111",
        "bg_color": "#F5F5F7",
        "has_box": True,
        "bold": True,
        "animation": "Bật lên (Pop In)",
        "hint": "Khung trắng sữa trang nhã, viền bo tinh tế, phong cách phim điện ảnh.",
    },
    "custom": {
        "name": "⚙️ Tùy chỉnh (Kiểu của bạn)",
        "font_name": "Arial",
        "font_size": 34,
        "text_color": "#FFFFFF",
        "bg_color": "#1A2738",
        "has_box": True,
        "bold": True,
        "animation": "Bật lên (Pop In)",
        "hint": "Tự do phối màu, chỉnh cỡ chữ, nền hộp và hiệu ứng theo sở thích.",
    },
}


class SubtitleStyleGroupBox(QGroupBox):
    """Khung điều khiển cấu hình kiểu dáng phụ đề & hộp nền che video trực quan."""

    style_changed = Signal(object)  # Emits SubtitleRenderConfig

    def __init__(self, parent: QWidget | None = None, *, parent_window: QWidget | None = None):
        super().__init__("4. Kiểu dáng phụ đề & Hộp nền che video", parent)
        self.parent_window = parent_window

        # Current style states
        self.current_text_color = "#111111"
        self.current_bg_color = "#FFE5DD"
        self._is_updating = False

        self._setup_ui()
        self._apply_preset("pastel_box")

        # Đồng bộ từ cột trái nếu có
        if self.parent_window is not None:
            self.sync_from_main_window(self.parent_window)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. HÀNG MẪU ĐỊNH SẴN (PRESETS)
        row_preset = QHBoxLayout()
        row_preset.setSpacing(8)
        lbl_preset = QLabel("🎨 Phong cách:")
        lbl_preset.setStyleSheet("font-size: 12px; font-weight: bold; color: #ff7b1a;")
        lbl_preset.setMinimumWidth(85)
        row_preset.addWidget(lbl_preset)

        self.combo_preset = QComboBox()
        for key, p in PRESETS_DATA.items():
            self.combo_preset.addItem(p["name"], key)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        row_preset.addWidget(self.combo_preset, 1)

        self.btn_sync_left = QPushButton("🔄 Lấy từ cột trái")
        self.btn_sync_left.setToolTip("Sao chép nhanh các thiết lập phụ đề đang chọn ở cột bên trái màn hình chính")
        self.btn_sync_left.setStyleSheet("""
            QPushButton {
                background-color: #1e293b; color: #38bdf8;
                border: 1px solid #334155; border-radius: 6px; padding: 4px 10px; font-size: 11px; font-weight: 600;
            }
            QPushButton:hover { background-color: #334155; color: #fff; }
        """)
        self.btn_sync_left.clicked.connect(self._on_manual_sync_clicked)
        row_preset.addWidget(self.btn_sync_left)
        layout.addLayout(row_preset)

        # 2. HÀNG PHÔNG CHỮ & KÍCH CỠ CHỮ
        row_font = QHBoxLayout()
        row_font.setSpacing(8)

        lbl_font = QLabel("Phông chữ:")
        lbl_font.setStyleSheet("color: #d7e3f4; font-size: 12px;")
        lbl_font.setMinimumWidth(75)
        row_font.addWidget(lbl_font)

        self.combo_font = QComboBox()
        self.combo_font.addItems(["Arial", "Montserrat", "Roboto", "Inter", "Segoe UI", "Tahoma", "Poppins"])
        self.combo_font.setCurrentText("Arial")
        self.combo_font.currentIndexChanged.connect(self._on_control_changed)
        row_font.addWidget(self.combo_font, 1)

        lbl_size = QLabel("Kích cỡ:")
        lbl_size.setStyleSheet("color: #d7e3f4; font-size: 12px; margin-left: 8px;")
        row_font.addWidget(lbl_size)

        self.combo_size = QComboBox()
        self.combo_size.addItem("Vừa / Chuẩn (34px - Khuyên dùng)", 34)
        self.combo_size.addItem("Nhỏ gọn (28px)", 28)
        self.combo_size.addItem("Lớn nổi bật (40px)", 40)
        self.combo_size.addItem("Rất lớn (46px)", 46)
        self.combo_size.setCurrentIndex(0)
        self.combo_size.currentIndexChanged.connect(self._on_control_changed)
        row_font.addWidget(self.combo_size, 1)
        layout.addLayout(row_font)

        # 3. HÀNG MÀU CHỮ, HỘP NỀN & IN ĐẬM
        row_colors = QHBoxLayout()
        row_colors.setSpacing(10)

        # Nút chọn màu chữ
        lbl_text_col = QLabel("Màu chữ:")
        lbl_text_col.setStyleSheet("color: #d7e3f4; font-size: 12px;")
        row_colors.addWidget(lbl_text_col)

        self.btn_text_color = QPushButton(self.current_text_color)
        self.btn_text_color.setMinimumWidth(80)
        self.btn_text_color.clicked.connect(self._pick_text_color)
        row_colors.addWidget(self.btn_text_color)

        # Checkbox bật hộp nền
        self.chk_box = QCheckBox("Hộp nền che video")
        self.chk_box.setChecked(True)
        self.chk_box.setToolTip("Tự động tạo hộp nền ôm sát chữ để che kín hoàn toàn chữ tiếng Trung gốc phía sau")
        self.chk_box.setStyleSheet("color: #f8fbff; font-weight: bold; font-size: 12px; margin-left: 6px;")
        self.chk_box.toggled.connect(self._on_box_toggled)
        row_colors.addWidget(self.chk_box)

        # Nút chọn màu hộp nền
        self.btn_bg_color = QPushButton(self.current_bg_color)
        self.btn_bg_color.setMinimumWidth(80)
        self.btn_bg_color.clicked.connect(self._pick_bg_color)
        row_colors.addWidget(self.btn_bg_color)

        # Checkbox in đậm
        self.chk_bold = QCheckBox("In đậm (Bold)")
        self.chk_bold.setChecked(True)
        self.chk_bold.setStyleSheet("color: #d7e3f4; font-size: 12px; margin-left: 6px;")
        self.chk_bold.toggled.connect(self._on_control_changed)
        row_colors.addWidget(self.chk_bold)

        layout.addLayout(row_colors)

        # 4. HÀNG HIỆU ỨNG XUẤT HIỆN
        row_anim = QHBoxLayout()
        row_anim.setSpacing(8)

        lbl_anim = QLabel("Hiệu ứng:")
        lbl_anim.setStyleSheet("color: #d7e3f4; font-size: 12px;")
        lbl_anim.setMinimumWidth(75)
        row_anim.addWidget(lbl_anim)

        self.combo_anim = QComboBox()
        self.combo_anim.addItems(["Bật lên (Pop In)", "Mờ dần vào (Fade In)", "Trượt lên (Slide Up)", "Tĩnh (Static)"])
        self.combo_anim.setCurrentText("Bật lên (Pop In)")
        self.combo_anim.currentIndexChanged.connect(self._on_control_changed)
        row_anim.addWidget(self.combo_anim, 1)

        self.lbl_hint = QLabel("💡 Khung hồng pastel bám sát chữ, vừa vặn che sạch video gốc.")
        self.lbl_hint.setStyleSheet("color: #79c0ff; font-size: 11px;")
        row_anim.addWidget(self.lbl_hint, 2)
        layout.addLayout(row_anim)

        # 5. LIVE PREVIEW BANNER
        preview_container = QFrame()
        preview_container.setStyleSheet("background-color: #0b111a; border: 1px dashed #24354c; border-radius: 8px; padding: 6px;")
        prev_layout = QVBoxLayout(preview_container)
        prev_layout.setContentsMargins(6, 6, 6, 6)
        prev_layout.setAlignment(Qt.AlignCenter)

        self.lbl_preview_badge = QLabel("Tôn Hiểu Hiểu, khách cần thìa sao không lấy?")
        self.lbl_preview_badge.setAlignment(Qt.AlignCenter)
        prev_layout.addWidget(self.lbl_preview_badge)

        layout.addWidget(preview_container)

        self._update_color_buttons()
        self._update_live_preview()

    def _update_color_buttons(self):
        # Nút màu chữ
        t_color = self.current_text_color
        is_light = QColor(t_color).lightness() > 128
        btn_fg = "#000000" if is_light else "#FFFFFF"
        self.btn_text_color.setText(t_color)
        self.btn_text_color.setStyleSheet(
            f"QPushButton {{ background-color: {t_color}; color: {btn_fg}; font-weight: bold; border: 1px solid #556677; border-radius: 5px; padding: 3px 8px; }}"
        )

        # Nút màu nền
        bg_col = self.current_bg_color
        is_bg_light = QColor(bg_col).lightness() > 128
        bg_btn_fg = "#000000" if is_bg_light else "#FFFFFF"
        self.btn_bg_color.setText(bg_col)
        self.btn_bg_color.setStyleSheet(
            f"QPushButton {{ background-color: {bg_col}; color: {bg_btn_fg}; font-weight: bold; border: 1px solid #556677; border-radius: 5px; padding: 3px 8px; }}"
        )
        self.btn_bg_color.setEnabled(self.chk_box.isChecked())

    def _update_live_preview(self):
        font_family = self.combo_font.currentText().strip() or "Arial"
        font_weight = "bold" if self.chk_bold.isChecked() else "normal"
        text_color = self.current_text_color
        has_box = self.chk_box.isChecked()
        p_key = self.combo_preset.currentData() or "custom"

        if p_key == "blur_mask":
            bg_color = "rgba(255, 255, 255, 0.18)"
            border_css = "border: 1px dashed rgba(255, 255, 255, 0.45);"
        else:
            bg_color = self.current_bg_color if has_box else "transparent"
            border_css = "border: none;" if has_box else "border: 1px solid #334455;"

        # Render preview pill with snug padding
        self.lbl_preview_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: {text_color};
                font-family: '{font_family}', sans-serif;
                font-size: 13px;
                font-weight: {font_weight};
                border-radius: 7px;
                padding: 5px 14px;
                {border_css}
            }}
        """)

    def _on_preset_changed(self, index: int):
        if self._is_updating:
            return
        key = self.combo_preset.currentData()
        if key in PRESETS_DATA and key != "custom":
            self._apply_preset(key)

    def _apply_preset(self, key: str):
        data = PRESETS_DATA.get(key)
        if not data:
            return
        self._is_updating = True
        try:
            self.current_text_color = data["text_color"]
            self.current_bg_color = data["bg_color"]
            self.chk_box.setChecked(data["has_box"])
            self.chk_bold.setChecked(data["bold"])
            self.combo_font.setCurrentText(data["font_name"])
            self.combo_anim.setCurrentText(data["animation"])
            self.lbl_hint.setText(f"💡 {data['hint']}")

            # Chọn size tương ứng
            s_val = data["font_size"]
            for i in range(self.combo_size.count()):
                if self.combo_size.itemData(i) == s_val:
                    self.combo_size.setCurrentIndex(i)
                    break

            self._update_color_buttons()
            self._update_live_preview()
        finally:
            self._is_updating = False
        self._notify_change()

    def _on_box_toggled(self, checked: bool):
        self.btn_bg_color.setEnabled(checked)
        self._on_control_changed()

    def _on_control_changed(self, *_args):
        if self._is_updating:
            return
        self._update_color_buttons()
        self._update_live_preview()
        self._notify_change()

    def _pick_text_color(self):
        col = QColorDialog.getColor(QColor(self.current_text_color), self, "Chọn màu chữ phụ đề")
        if col.isValid():
            self.current_text_color = col.name().upper()
            self._set_custom_preset_active()
            self._update_color_buttons()
            self._update_live_preview()
            self._notify_change()

    def _pick_bg_color(self):
        col = QColorDialog.getColor(QColor(self.current_bg_color), self, "Chọn màu hộp nền phụ đề")
        if col.isValid():
            self.current_bg_color = col.name().upper()
            self._set_custom_preset_active()
            self._update_color_buttons()
            self._update_live_preview()
            self._notify_change()

    def _set_custom_preset_active(self):
        """Khi người dùng tự chỉnh màu, chuyển preset sang 'Tùy chỉnh'."""
        self._is_updating = True
        try:
            idx = self.combo_preset.findData("custom")
            if idx >= 0:
                self.combo_preset.setCurrentIndex(idx)
        finally:
            self._is_updating = False

    def _on_manual_sync_clicked(self):
        win = self.parent_window or self.parent()
        if win:
            self.sync_from_main_window(win)

    def sync_from_main_window(self, win: Any):
        """Sao chép cấu hình kiểu dáng từ cột bên trái của màn hình chính."""
        if not win:
            return
        self._is_updating = True
        try:
            # Màu chữ
            text_hex = getattr(win, "subtitle_color_hex", None)
            if text_hex and text_hex.startswith("#"):
                self.current_text_color = text_hex.upper()

            # Màu hộp nền
            bg_hex = getattr(win, "subtitle_background_color_hex", None)
            if bg_hex and bg_hex.startswith("#"):
                self.current_bg_color = bg_hex.upper()

            # Bật/tắt hộp nền
            if hasattr(win, "subtitle_background_cb"):
                self.chk_box.setChecked(win.subtitle_background_cb.isChecked())

            # Phông chữ
            if hasattr(win, "subtitle_font_combo"):
                f_name = win.subtitle_font_combo.currentText().strip()
                if f_name:
                    self.combo_font.setCurrentText(f_name)

            # In đậm
            if hasattr(win, "subtitle_bold_cb"):
                self.chk_bold.setChecked(win.subtitle_bold_cb.isChecked())

            # Hiệu ứng
            if hasattr(win, "subtitle_animation_combo"):
                anim = win.subtitle_animation_combo.currentText().strip()
                if anim:
                    self.combo_anim.setCurrentText(anim)

            self._set_custom_preset_active()
            self._update_color_buttons()
            self._update_live_preview()
        finally:
            self._is_updating = False
        self._notify_change()

    def get_subtitle_render_config(self) -> SubtitleRenderConfig:
        """Xuất SubtitleRenderConfig chuẩn để đưa vào VideoCreatorConfig."""
        font_name = self.combo_font.currentText().strip() or "Arial"
        font_size = int(self.combo_size.currentData() or 34)
        has_box = self.chk_box.isChecked()
        is_bold = self.chk_bold.isChecked()
        anim = self.combo_anim.currentText().strip()
        p_key = self.combo_preset.currentData() or "custom"

        # Chuyển Hex sang ASS
        text_ass = hex_to_ass_color(self.current_text_color, alpha=1.0)
        bg_ass = hex_to_ass_color(self.current_bg_color, alpha=1.0)

        # Xác định mask_mode
        mask_mode = "blur" if p_key == "blur_mask" else ("box" if has_box else "none")

        cfg = SubtitleRenderConfig(
            font_name=font_name,
            font_size=font_size,
            primary_color=text_ass,
            outline_color="&H00000000&",
            outline_width=4 if not has_box else 0,
            bold=is_bold,
            enable_blur_mask=True,
            mask_mode=mask_mode,
            background_box=has_box,
            badge_bg_color=bg_ass,
            badge_text_color=text_ass,
            box_alpha=1.0,
            box_radius=14,
            animation=anim,
            preset_name=p_key,
        )
        return cfg

    def set_subtitle_render_config(self, cfg: SubtitleRenderConfig):
        """Nạp SubtitleRenderConfig vào giao diện."""
        if not cfg:
            return
        self._is_updating = True
        try:
            self.combo_font.setCurrentText(getattr(cfg, "font_name", "Arial") or "Arial")
            s_val = int(getattr(cfg, "font_size", 34) or 34)
            for i in range(self.combo_size.count()):
                if self.combo_size.itemData(i) == s_val:
                    self.combo_size.setCurrentIndex(i)
                    break

            self.chk_box.setChecked(bool(getattr(cfg, "background_box", True)))
            self.chk_bold.setChecked(bool(getattr(cfg, "bold", True)))
            self.current_text_color = ass_color_to_hex(getattr(cfg, "badge_text_color", "&H00111111&"))
            self.current_bg_color = ass_color_to_hex(getattr(cfg, "badge_bg_color", "&H00DDE5FF&"))
            self.combo_anim.setCurrentText(getattr(cfg, "animation", "Bật lên (Pop In)"))

            p_key = getattr(cfg, "preset_name", "custom")
            idx = self.combo_preset.findData(p_key)
            if idx >= 0:
                self.combo_preset.setCurrentIndex(idx)

            self._update_color_buttons()
            self._update_live_preview()
        finally:
            self._is_updating = False

    def _notify_change(self):
        cfg = self.get_subtitle_render_config()
        self.style_changed.emit(cfg)
