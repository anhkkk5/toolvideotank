"""OcrSubtitleMixin: OCR recognition, Subtitle editing, styling, synchronization, and ASS/SRT formatting."""

try:
    from main_window_parts.common_deps import *
    from main_window_parts.common_deps import _default_asr_engine
except ImportError:
    from ui.main_window_parts.common_deps import *
    from ui.main_window_parts.common_deps import _default_asr_engine


from typing import Any, Dict, List, Optional
import os
import re
import json
import logging

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QPushButton, QSlider, QProgressBar, QLabel, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox, QTabWidget, QSplitter, QScrollArea, QFrame, QDialog,
    QApplication, QColorDialog, QFileDialog, QMessageBox, QWidget
)

logger = logging.getLogger(__name__)


class OcrSubtitleMixin:
    """Mixin containing OCR operations, Subtitle Editor, ASS generators, and SRT handling."""
    def get_selected_subtitle_preset(self) -> str:
        if getattr(self, "subtitle_preset_custom_radio", None) and self.subtitle_preset_custom_radio.isChecked():
            return "custom"
        if getattr(self, "subtitle_preset_tiktok_radio", None) and self.subtitle_preset_tiktok_radio.isChecked():
            return "tiktok"
        if getattr(self, "subtitle_preset_youtube_radio", None) and self.subtitle_preset_youtube_radio.isChecked():
            return "youtube"
        if getattr(self, "subtitle_preset_minimal_radio", None) and self.subtitle_preset_minimal_radio.isChecked():
            return "minimal"
        return "youtube"


    def get_subtitle_preset_config(self, preset_key: str | None = None) -> dict:
        preset = (preset_key or self.get_selected_subtitle_preset()).lower()
        presets = {
            "tiktok": {
                "label": "TikTok",
                "font_name": "Montserrat",
                "font_size": 30,
                "font_color": "#FFFFFF",
                "highlight_color": "#FFD400",
                "outline_color": "#000000",
                "outline_width": 7,
                "shadow_color": "#000000",
                "shadow_depth": 2,
                "shadow_alpha": 0.7,
                "background_box": False,
                "background_color": "#000000",
                "background_alpha": 0.0,
                "animation": "Word Highlight Karaoke",
                "bold": True,
                "auto_keyword_highlight": True,
                "highlight_mode": "Auto + Manual",
                "summary": "Large subtitle with karaoke-style word timing and highlighted keywords for short-form videos.",
            },
            "youtube": {
                "label": "YouTube",
                "font_name": "Roboto",
                "font_size": 30,
                "font_color": "#FFFFFF",
                "highlight_color": "#FFFFFF",
                "outline_color": "#000000",
                "outline_width": 3,
                "shadow_color": "#000000",
                "shadow_depth": 1,
                "shadow_alpha": 0.35,
                "background_box": True,
                "background_color": "#000000",
                "background_alpha": 1.0,
                "animation": "Fade In",
                "bold": False,
                "auto_keyword_highlight": False,
                "highlight_mode": "Manual",
                "summary": "Clean subtitle with a solid background box for long-form readability.",
            },
            "minimal": {
                "label": "Short",
                "font_name": "Inter",
                "font_size": 30,
                "font_color": "#FFFFFF",
                "highlight_color": "#FFFFFF",
                "outline_color": "#000000",
                "outline_width": 0,
                "shadow_color": "#000000",
                "shadow_depth": 1,
                "shadow_alpha": 0.15,
                "background_box": False,
                "background_color": "#000000",
                "background_alpha": 0.0,
                "animation": "Slide Up",
                "bold": False,
                "summary": "Light, modern caption with almost no stroke and a gentle slide/fade entrance.",
            },
            "custom": {
                "label": "Custom",
                "font_name": "Segoe UI",
                "font_size": 30,
                "font_color": "#FFFFFF",
                "highlight_color": "#FFD400",
                "outline_color": "#000000",
                "outline_width": 3,
                "shadow_color": "#000000",
                "shadow_depth": 1,
                "shadow_alpha": 0.3,
                "background_box": False,
                "background_color": "#000000",
                "background_alpha": 0.6,
                "animation": "Pop In",
                "bold": True,
                "auto_keyword_highlight": False,
                "highlight_mode": "Auto",
                "summary": "Your editable working preset. Manual style changes can switch here automatically.",
            },
        }
        return presets.get(preset, presets["tiktok"]).copy()


    def parse_srt_to_segments(self, srt_text):
        return parse_srt_to_segments(srt_text)


    def validate_srt_text(self, srt_text, expected_len=None):
        return validate_srt_text(srt_text, expected_len=expected_len)


    def extract_subtitle_text_entries(self, srt_text):
        return extract_subtitle_text_entries(srt_text)


    def format_to_srt(self, segments):
        return format_segments_to_srt(segments)


    def _uses_speaker_subtitle_colors(self) -> bool:
        checkbox = getattr(self, "subtitle_speaker_colors_cb", None)
        return bool(checkbox and checkbox.isChecked())


    def _subtitle_color_for_segment(self, segment: dict | None) -> QColor:
        speaker = str((segment or {}).get("speaker", "") or "").strip()
        if self._uses_speaker_subtitle_colors() and speaker:
            return QColor(self._speaker_color_hex(speaker))
        return QColor(self.subtitle_color_hex)


    def _apply_live_subtitle_segment_color(self, segment: dict | None) -> None:
        item = getattr(getattr(self, "video_view", None), "subtitle_item", None)
        if item is None:
            return
        color = self._subtitle_color_for_segment(segment)
        if color != getattr(item, "font_color", None):
            item.font_color = color
            item.update()


    def _refresh_speaker_subtitle_colors_if_needed(self) -> None:
        """Rebuild the ASS preview only when speaker IDs affect its colors."""
        if self._uses_speaker_subtitle_colors():
            self.update_subtitle_preview_style()


    def schedule_live_subtitle_preview_refresh(self):
        if not hasattr(self, "live_subtitle_preview_timer"):
            return
        self.live_subtitle_preview_timer.start()


    def refresh_live_subtitle_preview(self):
        self.live_preview_segments, self.live_preview_editor_name = self._resolve_live_preview_segments()
        self.sync_live_subtitle_preview()


    def is_custom_subtitle_position_mode(self) -> bool:
        if not hasattr(self, "subtitle_position_mode_combo"):
            return False
        return str(self.subtitle_position_mode_combo.currentData() or "anchor").strip().lower() == "custom"


    def on_subtitle_position_mode_changed(self, *_args):
        is_custom = self.is_custom_subtitle_position_mode()
        if hasattr(self, "subtitle_align_label"):
            self.subtitle_align_label.setVisible(not is_custom)
        if hasattr(self, "subtitle_align_combo"):
            self.subtitle_align_combo.setVisible(not is_custom)
        if hasattr(self, "subtitle_custom_x_label"):
            self.subtitle_custom_x_label.setVisible(is_custom)
        if hasattr(self, "subtitle_custom_x_spin"):
            self.subtitle_custom_x_spin.setVisible(is_custom)
        if hasattr(self, "subtitle_custom_y_label"):
            self.subtitle_custom_y_label.setVisible(is_custom)
        if hasattr(self, "subtitle_custom_y_spin"):
            self.subtitle_custom_y_spin.setVisible(is_custom)
        if hasattr(self, "subtitle_bottom_offset_label"):
            self.subtitle_bottom_offset_label.setVisible(not is_custom)
        if hasattr(self, "subtitle_bottom_offset_spin"):
            self.subtitle_bottom_offset_spin.setVisible(not is_custom)
        self.update_subtitle_preview_style()
        if getattr(self, "current_project_state", None) is not None:
            self.schedule_timeline_project_persist()


    def _set_subtitle_item_text_rendering(self, enabled: bool) -> None:
        video_view = getattr(self, "video_view", None)
        subtitle_item = getattr(video_view, "subtitle_item", None)
        setter = getattr(subtitle_item, "set_text_rendering", None)
        if callable(setter):
            try:
                setter(bool(enabled))
            except Exception:
                pass


    def on_subtitle_drag_started(self):
        """Swap to the Qt layer only while dragging for immediate feedback."""
        if self._preview_is_playing():
            return
        if getattr(self, "_preview_video_has_burned_subtitles", False):
            return
        if hasattr(self, "media_player"):
            self.media_player.clear_subtitle()
        self._set_subtitle_item_text_rendering(True)


    def on_subtitle_position_dragged(self, x_percent: int, y_percent: int):
        """Commit a drag from the live subtitle overlay to style controls."""
        if self._preview_is_playing():
            return
        x_percent = max(0, min(100, int(x_percent)))
        y_percent = max(0, min(100, int(y_percent)))
        if hasattr(self, "subtitle_position_mode_combo"):
            self.subtitle_position_mode_combo.blockSignals(True)
            index = self.subtitle_position_mode_combo.findData("custom")
            if index >= 0:
                self.subtitle_position_mode_combo.setCurrentIndex(index)
            self.subtitle_position_mode_combo.blockSignals(False)
        for widget, value in (
            (getattr(self, "subtitle_custom_x_spin", None), x_percent),
            (getattr(self, "subtitle_custom_y_spin", None), y_percent),
        ):
            if widget is not None:
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
        self.on_subtitle_position_mode_changed()


    def get_subtitle_position_config(self) -> dict:
        alignment_map = {
            "Bottom Left": 1,
            "Bottom Center": 2,
            "Bottom": 2,
            "Bottom Right": 3,
            "Center": 5,
            "Top Center": 8,
            "Top": 8,
        }
        return {
            "position_mode": "custom" if self.is_custom_subtitle_position_mode() else "anchor",
            "alignment_label": self.subtitle_align_combo.currentText().strip(),
            "alignment": alignment_map.get(self.subtitle_align_combo.currentText(), 2),
            "margin_v": int(self.subtitle_bottom_offset_spin.value()),
            "x_offset": int(self.subtitle_x_offset_spin.value()),
            "custom_position_enabled": self.is_custom_subtitle_position_mode(),
            "custom_position_x": int(self.subtitle_custom_x_spin.value()),
            "custom_position_y": int(self.subtitle_custom_y_spin.value()),
        }


    def _saved_subtitle_style_payload(self) -> dict:
        return {
            "preset": self.get_selected_subtitle_preset(),
            "font": self.subtitle_font_combo.currentText().strip(),
            "size": int(self.subtitle_font_size_spin.value()),
            "color": self.subtitle_color_hex,
            "background_color": getattr(self, "subtitle_background_color_hex", "#000000"),
            "animation": self.subtitle_animation_combo.currentText().strip(),
            "animation_time": float(self.subtitle_animation_time_spin.value()),
            "karaoke_timing_mode": str(self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"),
            "background": bool(self.subtitle_background_cb.isChecked()),
            "background_width": str(self.subtitle_background_width_combo.currentData() if hasattr(self, "subtitle_background_width_combo") else "fit_text"),
            "background_shape": str(self.subtitle_background_shape_combo.currentData() if hasattr(self, "subtitle_background_shape_combo") else "rectangle"),
            "outline": bool(getattr(self, "subtitle_outline_cb", None) and self.subtitle_outline_cb.isChecked()),
            "background_alpha": float(self.subtitle_bg_alpha_spin.value()) if hasattr(self, "subtitle_bg_alpha_spin") else 0.6,
            "background_padding": int(self.subtitle_background_padding_spin.value()) if hasattr(self, "subtitle_background_padding_spin") else 6,
            "background_radius": int(self.subtitle_background_radius_spin.value()) if hasattr(self, "subtitle_background_radius_spin") else 0,
            "bold": bool(self.subtitle_bold_cb.isChecked()),
            "speaker_colors": self._uses_speaker_subtitle_colors(),
            "auto_keyword_highlight": bool(self.subtitle_keyword_highlight_cb.isChecked()),
            "highlight_color": self.subtitle_highlight_color_combo.currentText().strip(),
            "highlight_mode": self.subtitle_highlight_mode_combo.currentText().strip(),
        }


    def _current_subtitle_style_controls_state(self) -> dict:
        return {
            "preset": self.get_selected_subtitle_preset(),
            "font": self.subtitle_font_combo.currentText().strip(),
            "size": int(self.subtitle_font_size_spin.value()),
            "color": self.subtitle_color_hex,
            "background_color": getattr(self, "subtitle_background_color_hex", "#000000"),
            "animation": self.subtitle_animation_combo.currentText().strip(),
            "animation_time": float(self.subtitle_animation_time_spin.value()),
            "karaoke_timing_mode": str(self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"),
            "background": bool(self.subtitle_background_cb.isChecked()),
            "background_width": str(self.subtitle_background_width_combo.currentData() if hasattr(self, "subtitle_background_width_combo") else "fit_text"),
            "background_shape": str(self.subtitle_background_shape_combo.currentData() if hasattr(self, "subtitle_background_shape_combo") else "rectangle"),
            "outline": bool(getattr(self, "subtitle_outline_cb", None) and self.subtitle_outline_cb.isChecked()),
            "background_alpha": float(self.subtitle_bg_alpha_spin.value()) if hasattr(self, "subtitle_bg_alpha_spin") else 0.6,
            "background_padding": int(self.subtitle_background_padding_spin.value()) if hasattr(self, "subtitle_background_padding_spin") else 6,
            "background_radius": int(self.subtitle_background_radius_spin.value()) if hasattr(self, "subtitle_background_radius_spin") else 0,
            "bold": bool(self.subtitle_bold_cb.isChecked()),
            "speaker_colors": self._uses_speaker_subtitle_colors(),
            "auto_keyword_highlight": bool(self.subtitle_keyword_highlight_cb.isChecked()),
            "highlight_color": self.subtitle_highlight_color_combo.currentText().strip(),
            "highlight_mode": self.subtitle_highlight_mode_combo.currentText().strip(),
            "single_line": bool(getattr(self, "subtitle_single_line_cb", None) and self.subtitle_single_line_cb.isChecked()),
            "position": self.get_subtitle_position_config(),
        }


    def _apply_subtitle_style_controls_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            return
        self.subtitle_font_combo.setCurrentText(str(state.get("font", self.subtitle_font_combo.currentText())))
        self.subtitle_font_size_spin.setValue(int(state.get("size", self.subtitle_font_size_spin.value())))
        self.subtitle_color_hex = str(state.get("color", self.subtitle_color_hex)).upper()
        self.subtitle_color_btn.setText(self.subtitle_color_hex)
        self.subtitle_background_color_hex = str(
            state.get("background_color", getattr(self, "subtitle_background_color_hex", "#000000"))
        ).upper()
        if hasattr(self, "subtitle_background_color_btn"):
            self.subtitle_background_color_btn.setText(self.subtitle_background_color_hex)
        self.subtitle_animation_combo.setCurrentText(str(state.get("animation", self.subtitle_animation_combo.currentText())))
        self.subtitle_animation_time_spin.setValue(float(state.get("animation_time", self.subtitle_animation_time_spin.value())))
        karaoke_mode = str(state.get("karaoke_timing_mode", self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"))
        karaoke_index = self.subtitle_karaoke_timing_combo.findData(karaoke_mode)
        if karaoke_index >= 0:
            self.subtitle_karaoke_timing_combo.setCurrentIndex(karaoke_index)
        self.subtitle_background_cb.setChecked(bool(state.get("background", self.subtitle_background_cb.isChecked())))
        if hasattr(self, "subtitle_background_width_combo"):
            index = self.subtitle_background_width_combo.findData(str(state.get("background_width", "fit_text")))
            self.subtitle_background_width_combo.setCurrentIndex(max(0, index))
            shape_index = self.subtitle_background_shape_combo.findData(str(state.get("background_shape", "rectangle")))
            self.subtitle_background_shape_combo.setCurrentIndex(max(0, shape_index))
            self.on_subtitle_background_width_changed()
            if hasattr(self, "subtitle_background_radius_spin"):
                self.subtitle_background_radius_spin.setValue(int(state.get("background_radius", 0)))
        if hasattr(self, "subtitle_outline_cb"):
            self.subtitle_outline_cb.setChecked(bool(state.get("outline", self.subtitle_outline_cb.isChecked())))
        if hasattr(self, "subtitle_bg_alpha_spin"):
            self.subtitle_bg_alpha_spin.setValue(float(state.get("background_alpha", self.subtitle_bg_alpha_spin.value())))
        if hasattr(self, "subtitle_background_padding_spin"):
            self.subtitle_background_padding_spin.setValue(
                int(state.get("background_padding", self.subtitle_background_padding_spin.value()))
            )
        self.subtitle_bold_cb.setChecked(bool(state.get("bold", self.subtitle_bold_cb.isChecked())))
        if hasattr(self, "subtitle_speaker_colors_cb"):
            self.subtitle_speaker_colors_cb.setChecked(
                bool(state.get("speaker_colors", self.subtitle_speaker_colors_cb.isChecked()))
            )
        self.subtitle_keyword_highlight_cb.setChecked(
            bool(state.get("auto_keyword_highlight", self.subtitle_keyword_highlight_cb.isChecked()))
        )
        self.subtitle_highlight_color_combo.setCurrentText(
            str(state.get("highlight_color", self.subtitle_highlight_color_combo.currentText()))
        )
        self.subtitle_highlight_mode_combo.setCurrentText(
            str(state.get("highlight_mode", self.subtitle_highlight_mode_combo.currentText()))
        )
        if hasattr(self, "subtitle_single_line_cb"):
            self.subtitle_single_line_cb.setChecked(bool(state.get("single_line", self.subtitle_single_line_cb.isChecked())))
        position = dict(state.get("position") or {})
        if position:
            mode_combo = getattr(self, "subtitle_position_mode_combo", None)
            if mode_combo is not None:
                index = mode_combo.findData(str(position.get("position_mode", "anchor")))
                if index >= 0:
                    mode_combo.setCurrentIndex(index)
            align_combo = getattr(self, "subtitle_align_combo", None)
            if align_combo is not None:
                align_combo.setCurrentText(str(position.get("alignment_label", align_combo.currentText())))
            for widget_name, value_key in (
                ("subtitle_bottom_offset_spin", "margin_v"),
                ("subtitle_x_offset_spin", "x_offset"),
                ("subtitle_custom_x_spin", "custom_position_x"),
                ("subtitle_custom_y_spin", "custom_position_y"),
            ):
                widget = getattr(self, widget_name, None)
                if widget is not None and value_key in position:
                    widget.setValue(int(position[value_key]))
            self.on_subtitle_position_mode_changed()


    def _capture_subtitle_custom_style_state(self) -> None:
        self._subtitle_custom_style_state = self._current_subtitle_style_controls_state()


    def on_subtitle_style_control_edited(self, *_args):
        if getattr(self, "_subtitle_preset_apply_in_progress", False):
            return
        self._capture_subtitle_custom_style_state()
        custom_radio = getattr(self, "subtitle_preset_custom_radio", None)
        if custom_radio is not None and not custom_radio.isChecked():
            custom_radio.blockSignals(True)
            custom_radio.setChecked(True)
            custom_radio.blockSignals(False)
            self.on_subtitle_preset_changed()
        if getattr(self, "current_project_state", None) is not None:
            self.schedule_timeline_project_persist()


    def _read_saved_subtitle_style_presets(self) -> dict:
        raw_value = self.settings.value("saved_subtitle_styles", "{}")
        try:
            parsed = json.loads(raw_value) if isinstance(raw_value, str) else dict(raw_value)
        except Exception:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}


    def refresh_saved_subtitle_style_presets(self):
        if not hasattr(self, "saved_subtitle_style_combo"):
            return
        saved = self._read_saved_subtitle_style_presets()
        self.saved_subtitle_style_combo.blockSignals(True)
        self.saved_subtitle_style_combo.clear()
        self.saved_subtitle_style_combo.addItem("My Presets", "")
        for name in sorted(saved.keys(), key=str.lower):
            self.saved_subtitle_style_combo.addItem(name, name)
        self.saved_subtitle_style_combo.setCurrentIndex(0)
        self.saved_subtitle_style_combo.blockSignals(False)


    def save_current_subtitle_style_preset(self):
        name, ok = QInputDialog.getText(self, "Save Style", "Preset name:")
        if not ok or not (name or "").strip():
            return
        preset_name = name.strip()
        saved = self._read_saved_subtitle_style_presets()
        saved[preset_name] = self._saved_subtitle_style_payload()
        self.settings.setValue("saved_subtitle_styles", json.dumps(saved, ensure_ascii=False))
        self.refresh_saved_subtitle_style_presets()
        idx = self.saved_subtitle_style_combo.findData(preset_name)
        if idx >= 0:
            self.saved_subtitle_style_combo.setCurrentIndex(idx)


    def load_selected_subtitle_style_preset(self, index: int):
        if index <= 0:
            return
        preset_name = self.saved_subtitle_style_combo.itemData(index)
        saved = self._read_saved_subtitle_style_presets()
        preset = saved.get(preset_name or "")
        if not isinstance(preset, dict):
            return

        key = str(preset.get("preset", "tiktok")).lower()
        if key == "youtube":
            self.subtitle_preset_youtube_radio.setChecked(True)
        elif key == "minimal":
            self.subtitle_preset_minimal_radio.setChecked(True)
        elif key == "custom" and getattr(self, "subtitle_preset_custom_radio", None):
            self.subtitle_preset_custom_radio.setChecked(True)
        else:
            self.subtitle_preset_tiktok_radio.setChecked(True)

        self.subtitle_font_combo.setCurrentText(str(preset.get("font", self.subtitle_font_combo.currentText())))
        self.subtitle_font_size_spin.setValue(int(preset.get("size", self.subtitle_font_size_spin.value())))
        self.subtitle_color_hex = str(preset.get("color", self.subtitle_color_hex)).upper()
        self.subtitle_color_btn.setText(self.subtitle_color_hex)
        self.subtitle_background_color_hex = str(preset.get("background_color", getattr(self, "subtitle_background_color_hex", "#000000"))).upper()
        if hasattr(self, "subtitle_background_color_btn"):
            self.subtitle_background_color_btn.setText(self.subtitle_background_color_hex)
        self.subtitle_animation_combo.setCurrentText(str(preset.get("animation", self.subtitle_animation_combo.currentText())))
        self.subtitle_animation_time_spin.setValue(float(preset.get("animation_time", self.subtitle_animation_time_spin.value())))
        karaoke_mode = str(preset.get("karaoke_timing_mode", self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"))
        karaoke_index = self.subtitle_karaoke_timing_combo.findData(karaoke_mode)
        if karaoke_index >= 0:
            self.subtitle_karaoke_timing_combo.setCurrentIndex(karaoke_index)
        self.subtitle_background_cb.setChecked(bool(preset.get("background", self.subtitle_background_cb.isChecked())))
        if hasattr(self, "subtitle_outline_cb"):
            self.subtitle_outline_cb.setChecked(bool(preset.get("outline", self.subtitle_outline_cb.isChecked())))
        if hasattr(self, "subtitle_bg_alpha_spin"):
            self.subtitle_bg_alpha_spin.setValue(float(preset.get("background_alpha", self.subtitle_bg_alpha_spin.value())))
        self.subtitle_bold_cb.setChecked(bool(preset.get("bold", self.subtitle_bold_cb.isChecked())))
        self.subtitle_keyword_highlight_cb.setChecked(bool(preset.get("auto_keyword_highlight", self.subtitle_keyword_highlight_cb.isChecked())))
        self.subtitle_highlight_color_combo.setCurrentText(str(preset.get("highlight_color", self.subtitle_highlight_color_combo.currentText())))
        self.subtitle_highlight_mode_combo.setCurrentText(str(preset.get("highlight_mode", self.subtitle_highlight_mode_combo.currentText())))
        self._capture_subtitle_custom_style_state()
        self.on_subtitle_preset_changed()


    def choose_subtitle_color(self):
        color = QColorDialog.getColor(QColor(self.subtitle_color_hex), self, "Choose Subtitle Color")
        if not color.isValid():
            return
        self.subtitle_color_hex = color.name().upper()
        self.subtitle_color_btn.setText(self.subtitle_color_hex)
        self.on_subtitle_style_control_edited()
        self.update_subtitle_preview_style()


    def choose_subtitle_background_color(self):
        current = getattr(self, "subtitle_background_color_hex", "#000000")
        color = QColorDialog.getColor(QColor(current), self, "Choose Subtitle Background Color")
        if not color.isValid():
            return
        self.subtitle_background_color_hex = color.name().upper()
        if hasattr(self, "subtitle_background_color_btn"):
            self.subtitle_background_color_btn.setText(self.subtitle_background_color_hex)
        self.on_subtitle_style_control_edited()
        self.update_subtitle_preview_style()


    def on_subtitle_background_width_changed(self, *_args):
        is_full_area = bool(
            hasattr(self, "subtitle_background_width_combo")
            and self.subtitle_background_width_combo.currentData() == "full_area"
        )
        hint = getattr(self, "subtitle_background_exact_hint", None)
        if hint is not None:
            hint.setVisible(is_full_area)
        # Shape selection was removed in favor of a consistent rounded
        # rectangle controlled by Corner radius.
        for name in ("subtitle_background_shape_label", "subtitle_background_shape_combo"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setVisible(False)
        self.update_subtitle_preview_style()


    def on_subtitle_font_scale_changed(self, _index: int = -1):
        """Translate the friendly percentage picker into the stored font size."""
        combo = getattr(self, "subtitle_font_scale_combo", None)
        spin = getattr(self, "subtitle_font_size_spin", None)
        if combo is None or spin is None:
            return
        percent = int(combo.currentData() or 100)
        spin.setValue(max(spin.minimum(), min(spin.maximum(), round(60 * percent / 100.0))))


    def sync_subtitle_font_scale_control(self, size: int | None = None):
        """Keep the visible selector honest when a preset/project sets a size."""
        combo = getattr(self, "subtitle_font_scale_combo", None)
        spin = getattr(self, "subtitle_font_size_spin", None)
        if combo is None or spin is None:
            return
        size = int(spin.value() if size is None else size)
        choices = [int(combo.itemData(index)) for index in range(combo.count())]
        if not choices:
            return
        nearest = min(choices, key=lambda percent: abs((60 * percent / 100.0) - size))
        index = combo.findData(nearest)
        if index >= 0 and index != combo.currentIndex():
            was_blocked = combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(was_blocked)


    def _subtitle_render_dimensions(self) -> tuple[int, int]:
        """Return the canvas dimensions the export ASS file is authored for."""
        source_w = max(1, int(getattr(self.video_view, "video_source_width", 0) or 1920))
        source_h = max(1, int(getattr(self.video_view, "video_source_height", 0) or 1080))
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        controller = getattr(self, "preview_controller", None)
        if controller is not None and video_path:
            try:
                target_w, target_h = controller._resolve_output_canvas_dimensions(video_path)
                if target_w and target_h:
                    return int(target_w), int(target_h)
            except Exception:
                pass
        return source_w, source_h


    def _resolved_subtitle_font_name(self, requested_font: str) -> str:
        """Use Qt's actual font fallback for both preview and ASS export.

        Preset fonts such as Montserrat are not installed on every Windows
        system. Qt and libass otherwise pick different fallbacks, causing
        identical text and widths to wrap on different words.
        """
        requested_font = str(requested_font or "Segoe UI").strip() or "Segoe UI"
        try:
            bundled_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"))
            if not getattr(self, "_bundled_subtitle_fonts_registered", False) and os.path.isdir(bundled_dir):
                for filename in os.listdir(bundled_dir):
                    if filename.lower().endswith((".ttf", ".otf")):
                        QFontDatabase.addApplicationFont(os.path.join(bundled_dir, filename))
                self._bundled_subtitle_fonts_registered = True
            resolved = QFontInfo(QFont(requested_font)).family().strip()
            return resolved or requested_font
        except Exception:
            return requested_font


    def update_subtitle_preview_style(self):
        if not hasattr(self, "video_view"):
            return
        item = self.video_view.subtitle_item
        has_video = bool(self.video_path_edit.text().strip())
        has_segments = bool(self.get_active_segments())
        if not has_video or not has_segments:
            item.set_text("")
            item.hide()
            self.sync_live_subtitle_preview()
            return
        render_w, render_h = self._subtitle_render_dimensions()
        self.video_view.set_subtitle_render_dimensions(render_w, render_h)
        source_h = max(1, render_h)
        preview_rect = self.video_view.get_preview_canvas_rect() if hasattr(self.video_view, "get_preview_canvas_rect") else self.video_view.get_video_content_rect()
        preview_h = max(1.0, preview_rect.height() or float(self.video_view.height()) or 1.0)
        preset = self.get_subtitle_preset_config()
        export_font_size = int(self.subtitle_font_size_spin.value())
        preview_scale = preview_h / source_h
        preview_text_scale = preview_scale * 0.85
        # The preview is a scaled view of the source video. Do not impose a
        # 10px floor here: it made several user-selected sizes render as the
        # same size and therefore looked as though the control had stopped
        # updating.
        # Qt's QFont and libass use different font metric engines. At the
        # small sizes used by this live preview, QFont advances the bundled
        # Montserrat glyphs about 15% wider than libass, causing earlier line
        # wraps and a visibly larger preview. Calibrate the editable layer to
        # the ASS renderer, while keeping the exported source size unchanged.
        preview_font_size = max(1, int(round(export_font_size * preview_text_scale)))
        font_name = self._resolved_subtitle_font_name(
            self.subtitle_font_combo.currentText().strip() or preset.get("font_name", "Segoe UI")
        )
        bg_alpha = float(self.subtitle_bg_alpha_spin.value()) if hasattr(self, "subtitle_bg_alpha_spin") else float(preset.get("background_alpha", 0.0))
        bg_color = QColor(getattr(self, "subtitle_background_color_hex", preset.get("background_color", "#000000")))
        bg_color.setAlpha(max(0, min(255, int(round(bg_alpha * 255.0)))))
        item.set_style(
            font_name=font_name or preset.get("font_name", "Segoe UI"),
            font_size=preview_font_size,
            font_color=self._subtitle_color_for_segment(
                (self.live_preview_segments or self.get_active_segments() or [None])[0]
            ),
            # Stroke/shadow values are authored for the source video. Scale
            # them for the smaller Qt preview too; otherwise TikTok's 7px
            # export outline overwhelms its preview-sized glyphs.
            outline_width=(
                float(preset.get("outline_width", 2)) * preview_text_scale
                if not hasattr(self, "subtitle_outline_cb") or self.subtitle_outline_cb.isChecked()
                else 0.0
            ),
            outline_color=QColor(preset.get("outline_color", "#000000")),
            background_box=bool(self.subtitle_background_cb.isChecked()),
            background_color=bg_color,
            single_line=bool(getattr(self, "subtitle_single_line_cb", None) and self.subtitle_single_line_cb.isChecked()),
            bold=bool(self.subtitle_bold_cb.isChecked()),
            shadow_color=QColor(preset.get("shadow_color", "#000000")),
            shadow_depth=float(preset.get("shadow_depth", 0)) * preview_text_scale,
        )
        position = self.get_subtitle_position_config()
        item.set_alignment(position.get("alignment_label", "Bottom"))
        item.set_positioning(
            x_offset=int(position.get("x_offset", 0)),
            bottom_offset=int(position.get("margin_v", 30)),
            custom_position_enabled=bool(position.get("custom_position_enabled", False)),
            custom_x_percent=int(position.get("custom_position_x", 50)),
            custom_y_percent=int(position.get("custom_position_y", 86)),
        )
        segments = self.live_preview_segments or self.get_active_segments()
        selected = int(getattr(self, "_selected_segment_index", -1))
        style_segment = segments[selected] if 0 <= selected < len(segments) else (segments[0] if segments else None)
        self._apply_live_subtitle_segment_color(style_segment)
        self._set_live_subtitle_effects(style_segment)
        self.video_view.reposition_subtitle()
        self.sync_live_subtitle_preview()
        self.schedule_auto_frame_preview()


    def _set_live_subtitle_effects(self, segment: dict | None, position_ms: int = 0):
        """Feed the editable preview layer the same cue effects used at export."""
        if not hasattr(self, "video_view"):
            return
        item = self.video_view.subtitle_item
        segment = segment or {}
        preset = self.get_subtitle_preset_config()
        text = str(segment.get("text", "") or "")
        mode = self.subtitle_highlight_mode_combo.currentText().strip() if hasattr(self, "subtitle_highlight_mode_combo") else "Auto"
        phrases = []
        if mode in ("Auto", "Auto + Manual"):
            phrases.extend(segment.get("auto_highlights", []) or [])
        if mode in ("Manual", "Auto + Manual"):
            phrases.extend(segment.get("manual_highlights", []) or [])
        animation = self.subtitle_animation_combo.currentText().strip().lower() if hasattr(self, "subtitle_animation_combo") else ""
        animation_duration = max(0.01, float(self.subtitle_animation_time_spin.value())) if hasattr(self, "subtitle_animation_time_spin") else 0.22
        start = float(segment.get("start", 0.0) or 0.0)
        end = max(start + 0.01, float(segment.get("end", start + 0.01) or start + 0.01))
        elapsed = max(0.0, float(position_ms) / 1000.0 - start)
        animation_progress = min(1.0, elapsed / animation_duration)
        if animation == "fade out":
            animation_progress = min(1.0, max(0.0, float(position_ms) / 1000.0 - (end - animation_duration)) / animation_duration)
        karaoke_index = -1
        if animation == "word highlight karaoke" and text:
            words = [word for word in text.split() if word]
            progress = max(0.0, min(0.999, (float(position_ms) / 1000.0 - start) / (end - start)))
            karaoke_index = min(len(words) - 1, int(progress * len(words))) if words else -1
        if hasattr(item, "set_effects"):
            item.set_effects(
                highlight_color=self._highlight_color_hex() or preset.get("highlight_color", "#FFD400"),
                highlight_phrases=phrases,
                karaoke_word_index=karaoke_index,
                auto_keyword_highlight=bool(self.subtitle_keyword_highlight_cb.isChecked()) if hasattr(self, "subtitle_keyword_highlight_cb") else False,
                animation_style=animation,
                animation_progress=animation_progress,
            )


    def _split_segments_for_single_line(self):
        from translation import TranslationOrchestrator
        source = list(self.current_translated_segments or [])
        if not source:
            return
        orchestrator = TranslationOrchestrator()
        provider_type, polisher = orchestrator._resolve_ai_provider()
        if not polisher or not polisher.is_configured():
            polisher = None
        split = orchestrator._split_segments_for_single_line(
            source, polisher=polisher, provider_type=provider_type, target_lang=self.get_target_language_code(),
            words_per_segment=int(self.subtitle_words_per_segment_spin.value()) if hasattr(self, "subtitle_words_per_segment_spin") else 4,
        )
        if split and split != source:
            self._single_line_split_cache = split


    def get_subtitle_export_style(self, segments=None):
        preset = self.get_subtitle_preset_config()
        # Export-only glyph calibration. ASS ScaleX/ScaleY enlarges glyphs
        # without changing font-size-derived line spacing or row placement.
        export_font_scale = max(0.1, float(getattr(self, "subtitle_export_font_scale", 1.0)))
        export_font_size = max(1, int(self.subtitle_font_size_spin.value()))
        style_segments = segments if segments is not None else self.get_active_segments()
        position = self.get_subtitle_position_config()
        # Preview and export both use the subtitle's centre anchor.  Do not
        # convert it to ASS's bottom anchor: that conversion includes the Qt
        # widget's font-metric padding and caused a vertical offset whenever
        # the output canvas ratio changed.
        custom_bottom_y = None
        return {
            "font_name": self._resolved_subtitle_font_name(
                self.subtitle_font_combo.currentText().strip() or preset.get("font_name", "Arial")
            ),
            "font_size": export_font_size,
            "font_scale": export_font_scale,
            "font_color": self._hex_to_ass_color(self.subtitle_color_hex),
            "speaker_colors": (
                [
                    self._hex_to_ass_color(self._speaker_color_hex(str(segment.get("speaker", "") or "")))
                    if str(segment.get("speaker", "") or "").strip() else ""
                    for segment in (style_segments or [])
                ]
                if self._uses_speaker_subtitle_colors() else []
            ),
            "highlight_color": self._hex_to_ass_color(self._highlight_color_hex()),
            "outline_color": self._hex_to_ass_color(preset.get("outline_color", "#000000")),
            "outline_width": (
                float(preset.get("outline_width", 2))
                if not hasattr(self, "subtitle_outline_cb") or self.subtitle_outline_cb.isChecked()
                else 0.0
            ),
            "shadow_color": self._hex_to_ass_color(preset.get("shadow_color", "#000000")),
            "shadow_depth": float(preset.get("shadow_depth", 1)),
            "shadow_alpha": float(preset.get("shadow_alpha", 0.0)),
            "background_color": self._hex_to_ass_color(
                getattr(self, "subtitle_background_color_hex", preset.get("background_color", "#000000"))
            ),
            "background_alpha": float(self.subtitle_bg_alpha_spin.value()) if hasattr(self, "subtitle_bg_alpha_spin") else float(preset.get("background_alpha", 0.0)),
            "background_padding": int(self.subtitle_background_padding_spin.value()) if hasattr(self, "subtitle_background_padding_spin") else 6,
            "background_radius": int(self.subtitle_background_radius_spin.value()) if hasattr(self, "subtitle_background_radius_spin") else 0,
            "background_width": str(self.subtitle_background_width_combo.currentData() if hasattr(self, "subtitle_background_width_combo") else "fit_text"),
            "background_shape": str(self.subtitle_background_shape_combo.currentData() if hasattr(self, "subtitle_background_shape_combo") else "rectangle"),
            "animation": self.subtitle_animation_combo.currentText().strip() or preset.get("animation", "Static"),
            "animation_duration": float(self.subtitle_animation_time_spin.value()),
            "karaoke_timing_mode": str(self.subtitle_karaoke_timing_combo.currentData() or "vietnamese"),
            "position_mode": str(position.get("position_mode", "anchor")),
            "alignment": int(position.get("alignment", 2)),
            "margin_v": int(position.get("margin_v", 30)),
            "custom_position_enabled": bool(position.get("custom_position_enabled", False)),
            "custom_position_x": int(position.get("custom_position_x", 50)),
            "custom_position_y": int(position.get("custom_position_y", 86)),
            "custom_position_bottom_y": custom_bottom_y,
            "background_box": bool(self.subtitle_background_cb.isChecked()),
            "bold": bool(self.subtitle_bold_cb.isChecked()),
            "preset_key": self.get_selected_subtitle_preset(),
            "auto_keyword_highlight": bool(self.subtitle_keyword_highlight_cb.isChecked())
            and self.subtitle_highlight_mode_combo.currentText().strip() in ("Auto", "Auto + Manual")
            and not any(seg.get("auto_highlights") for seg in (style_segments or [])),
            "manual_highlights": self._build_render_highlight_lists(style_segments or []),
            "word_timings": [list(seg.get("words", [])) for seg in (style_segments or [])],
            "blur_region": (
                self.video_view.get_blur_region_normalized()
                if hasattr(self, "video_view") and self._blur_effect_enabled()
                else None
            ),
            "render_subtitles": False,
        }


    def on_subtitle_preset_changed(self):
        preset = self.get_subtitle_preset_config()
        selected = self.get_selected_subtitle_preset()
        self._subtitle_preset_apply_in_progress = True
        try:
            if selected == "custom":
                if self._subtitle_custom_style_state:
                    self._apply_subtitle_style_controls_state(self._subtitle_custom_style_state)
            else:
                self.subtitle_font_combo.setCurrentText(preset.get("font_name", "Arial"))
                self.subtitle_font_size_spin.setValue(int(preset.get("font_size", self.subtitle_font_size_spin.value())))
                self.subtitle_animation_combo.setCurrentText(preset.get("animation", "Static"))
                self.subtitle_background_cb.setChecked(bool(preset.get("background_box", False)))
                self.subtitle_background_color_hex = str(
                    preset.get("background_color", getattr(self, "subtitle_background_color_hex", "#000000"))
                ).upper()
                if hasattr(self, "subtitle_background_color_btn"):
                    self.subtitle_background_color_btn.setText(self.subtitle_background_color_hex)
                if hasattr(self, "subtitle_outline_cb"):
                    self.subtitle_outline_cb.setChecked(bool(preset.get("outline_width", 0) > 0))
                if hasattr(self, "subtitle_bg_alpha_spin"):
                    self.subtitle_bg_alpha_spin.setValue(float(preset.get("background_alpha", self.subtitle_bg_alpha_spin.value())))
                self.subtitle_bold_cb.setChecked(bool(preset.get("bold", False)))
                if hasattr(self, "subtitle_keyword_highlight_cb"):
                    self.subtitle_keyword_highlight_cb.setChecked(bool(preset.get("auto_keyword_highlight", False)))
                if hasattr(self, "subtitle_highlight_color_combo"):
                    color_name = "Yellow" if preset.get("highlight_color", "").upper() == "#FFD400" else "Cyan"
                    self.subtitle_highlight_color_combo.setCurrentText(color_name)
                if hasattr(self, "subtitle_highlight_mode_combo"):
                    self.subtitle_highlight_mode_combo.setCurrentText(str(preset.get("highlight_mode", "Auto")))
        finally:
            self._subtitle_preset_apply_in_progress = False
        if hasattr(self, "style_library_card"):
            self.style_library_card.setVisible(True)
        if hasattr(self, "highlight_card"):
            self.highlight_card.setVisible(True)
        if hasattr(self, "custom_title_card"):
            self.custom_title_card.setVisible(True)
        if hasattr(self, "subtitle_preset_summary_label"):
            self.subtitle_preset_summary_label.setText(
                f"{preset.get('label', 'Preset')}: {preset.get('summary', '')}"
            )
        self._update_animation_time_visibility()
        self.on_subtitle_background_width_changed()
        if selected == "custom":
            self._capture_subtitle_custom_style_state()
        self.on_subtitle_position_mode_changed()


    def on_subtitle_animation_changed(self):
        self._update_animation_time_visibility()
        self.update_subtitle_preview_style()


    def build_subtitle_preview_srt(self, start_seconds: float, duration_seconds: float):
        return self.preview_controller.build_subtitle_preview_srt(start_seconds, duration_seconds)


    def build_full_active_subtitle_srt(self):
        return self.preview_controller.build_full_active_subtitle_srt()


    def _segment_editor_display_rows(self):
        base_segments = self.current_segments or []
        translated_segments = self.current_translated_segments or []
        source_models = self.current_segment_models or []
        # Segment lists normally remain index-aligned, but imported SRTs and
        # manual timing edits may add/remove cues on only one side.  Retain a
        # fast timing lookup so the inspector can still show the matching
        # source transcript instead of an empty "Original" field.
        base_by_time = {
            (
                round(float(segment.get("start", 0.0)), 3),
                round(float(segment.get("end", 0.0)), 3),
            ): segment
            for segment in base_segments
            if isinstance(segment, dict)
        }
        # Timeline subtitle layers retain their visible `text` separately
        # from `_seg_dict`.  Keep this as the final recovery source for a
        # cue whose in-memory dictionary was rebuilt from SRT timing data.
        timeline_text_by_index = {}
        timeline_model = getattr(getattr(self, "timeline", None), "_timeline", None)
        for track in list(getattr(timeline_model, "tracks", []) or []):
            if str(getattr(getattr(track, "type", ""), "value", getattr(track, "type", ""))).lower() not in {"subtitle", "dub_subtitle"}:
                continue
            for layer in list(getattr(track, "layers", []) or []):
                metadata = getattr(layer, "metadata", {}) or {}
                try:
                    segment_index = int(metadata.get("_seg_index", -1))
                except (TypeError, ValueError):
                    continue
                if segment_index >= 0:
                    timeline_text_by_index[segment_index] = str(
                        getattr(layer, "text", "") or getattr(layer, "dub_text", "") or ""
                    )
        row_count = max(len(base_segments), len(translated_segments))
        rows = []
        for idx in range(row_count):
            base = base_segments[idx] if idx < len(base_segments) else {}
            translated = translated_segments[idx] if idx < len(translated_segments) else {}
            if translated:
                time_key = (
                    round(float(translated.get("start", 0.0)), 3),
                    round(float(translated.get("end", 0.0)), 3),
                )
                timed_base = base_by_time.get(time_key)
                if timed_base is not None:
                    base = timed_base
            reference = translated or base
            # Imported/manual translated segments do not always retain a
            # parallel original item at the same index.  Prefer the actual
            # transcript, then the source-text metadata retained by the
            # translation workflow, so the inspector never loses the source
            # text while the preview/timeline still has a visible cue.
            model_original = ""
            if idx < len(source_models):
                model_original = str(getattr(source_models[idx], "original_text", "") or "")
            original_text = str(
                translated.get("source_text", "")
                or translated.get("original_text", "")
                or base.get("original_text", "")
                or base.get("text", "")
                or model_original
                or timeline_text_by_index.get(idx, "")
                or ""
            )
            shown_text = str(translated.get("text", "") or original_text)
            trans_meta = translated.get("metadata", {}) if isinstance(translated.get("metadata"), dict) else {}
            base_meta = base.get("metadata", {}) if isinstance(base.get("metadata"), dict) else {}
            spk = str(
                translated.get("speaker")
                or trans_meta.get("speaker")
                or base.get("speaker")
                or base_meta.get("speaker")
                or ""
            ).strip()
            v_group = str(
                translated.get("voice_group")
                or trans_meta.get("voice_group")
                or base.get("voice_group")
                or base_meta.get("voice_group")
                or ""
            ).strip()
            v_custom = str(
                translated.get("voice_custom")
                or trans_meta.get("voice_custom")
                or ""
            ).strip()
            v_name = str(
                translated.get("voice_name")
                or trans_meta.get("voice_name")
                or base.get("voice_name")
                or base_meta.get("voice_name")
                or ""
            ).strip()

            rows.append(
                {
                    "segment_index": idx,
                    "start": float(reference.get("start", 0.0)),
                    "end": float(reference.get("end", 0.0)),
                    "original": original_text,
                    # Before translation this is the original transcript,
                    # which is also the text currently shown on screen.
                    "translated": shown_text,
                    "spoken": str(translated.get("tts_text") or translated.get("dubbing_vi") or translated.get("text", "")),
                    "subtitle_vi": str(translated.get("subtitle_vi") or translated.get("text", "")),
                    "dubbing_vi": str(translated.get("dubbing_vi") or translated.get("tts_text") or translated.get("text", "")),
                    "ratio": float(translated.get("ratio", 0.0) or 0.0),
                    "attempt_count": int(translated.get("attempt_count", 0) or 0),
                    "action_taken": str(translated.get("action_taken", "")),
                    "voice_speed": float(reference.get("voice_speed", 1.0)),
                    "manual_highlights": list(translated.get("manual_highlights", [])),
                    "speaker": spk,
                    "voice_group": v_group,
                    "voice_custom": v_custom,
                    "voice_name": v_name,
                    "status": str(reference.get("status") or base.get("status") or translated.get("status") or ""),
                    "fusion_reason": str(reference.get("fusion_reason") or base.get("fusion_reason") or translated.get("fusion_reason") or ""),
                    "fusion_score": float(reference.get("fusion_score", 0.0) or base.get("fusion_score", 0.0) or 0.0),
                    "speech_coverage": float(reference.get("speech_coverage", 0.0) or base.get("speech_coverage", 0.0) or 0.0),
                    "asr_alignment": float(reference.get("asr_alignment", 0.0) or base.get("asr_alignment", 0.0) or 0.0),
                    "bbox_persistence": float(reference.get("bbox_persistence", 0.0) or base.get("bbox_persistence", 0.0) or 0.0),
                    "contextual_cue": bool(reference.get("contextual_cue", False) or base.get("contextual_cue", False)),
                    "is_noise": bool(reference.get("is_noise", False) or base.get("is_noise", False)),
                }
            )
        return rows


    def use_spoken_text_for_subtitle(self, index: int):
        if not (0 <= index < len(self.current_translated_segments or [])):
            return
        segment = self.current_translated_segments[index]
        spoken_text = " ".join(str(segment.get("tts_text") or segment.get("dubbing_vi") or "").split()).strip()
        if not spoken_text:
            QMessageBox.information(self, "Nothing To Match", "This line does not have voice text yet.")
            return
        segment["text"] = spoken_text
        segment["subtitle_vi"] = spoken_text
        segment["voice_edited"] = True
        self._voiceover_force_refresh = True
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_hidden_translated_text_from_segments()
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.sync_segment_editor_rows()
        self.refresh_ui_state()


    def _sync_segment_highlight_chip_row(self, index: int):
        row = self._find_segment_editor_row(index)
        if not row:
            return
        chip_layout = row.get("highlight_chip_layout")
        placeholder = row.get("highlight_placeholder")
        if chip_layout is None:
            return

        while chip_layout.count():
            item = chip_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        highlights = []
        if index < len(self.current_translated_segments):
            highlights = list(self.current_translated_segments[index].get("manual_highlights", []))

        if placeholder:
            placeholder.setVisible(not highlights)

        for phrase in highlights:
            chip = QPushButton(f"[ {phrase} ]")
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(
                "QPushButton { background-color: #173049; color: #9fe5ff; border: 1px solid #356081; border-radius: 999px; padding: 4px 10px; font-size: 11px; }"
                "QPushButton:hover { background-color: #214161; }"
            )
            chip.clicked.connect(lambda _=False, idx=index, value=phrase: self.remove_segment_manual_highlight(idx, value))
            chip_layout.addWidget(chip)
        chip_layout.addStretch()


    def _clear_segment_editor_rows(self):
        if not hasattr(self, "segment_editor_layout"):
            return
        while self.segment_editor_layout.count():
            item = self.segment_editor_layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif child_layout:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    child_widget = child_item.widget()
                    if child_widget:
                        child_widget.hide()
                        child_widget.setParent(None)
                        child_widget.deleteLater()


    def _show_subtitle_inspector_for_layer(self, layer_id: str):
        """Show subtitle inspector and select the matching segment."""
        self._switch_inspector("subtitle")
        if hasattr(self, "timeline") and self.timeline:
            idx = self.timeline.segment_index_for_layer_id(layer_id)
            if idx >= 0:
                self.set_selected_segment_index(idx, sync_ui=True)


    def _show_dub_subtitle_inspector_for_layer(self, layer_id: str, layer=None):
        """Show the inspector for a dub subtitle layer."""
        self._switch_inspector("subtitle")
        if hasattr(self, "timeline") and self.timeline:
            idx = self.timeline.segment_index_for_layer_id(layer_id)
            if idx >= 0:
                self.set_selected_segment_index(idx, sync_ui=True)


    def on_track_subtitle_toggled(self, track_name: str, is_shown: bool):
        """Temporarily show or hide TS1 subtitle output without deleting data."""
        self._subtitle_track_preview_visible = bool(is_shown)
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_subtitle_track_visible"):
            self.video_view.set_subtitle_track_visible(self._subtitle_track_preview_visible)
        if not is_shown:
            try:
                self.media_player.clear_subtitle()
            except Exception:
                pass
            # clear_subtitle() removes MPV's external ASS track.  Its source
            # path may still be the same on Show, so invalidate the UI-level
            # cache as well; otherwise sync_live_subtitle_preview() believes
            # the removed track is already loaded and never restores it.
            self._loaded_live_ass_path = ""
            self._loaded_live_ass_signature = None
            if hasattr(self, "video_view"):
                try:
                    self.video_view.subtitle_item.hide()
                except Exception:
                    pass
        else:
            try:
                self.sync_live_subtitle_preview()
            except Exception:
                pass
        if hasattr(self, "track_label_bar"):
            self.track_label_bar.set_subtitle_shown(track_name, bool(is_shown))
        self.log(f"[Timeline] {'Shown' if is_shown else 'Hidden'} subtitle track: {track_name}")
        self.schedule_timeline_project_persist()


    def _build_split_segment_pair(self, segment: dict, split_time: float):
        first = dict(segment or {})
        second = dict(segment or {})

        first["start"] = float(segment.get("start", 0.0))
        first["end"] = float(split_time)
        second["start"] = float(split_time)
        second["end"] = float(segment.get("end", split_time))

        words = list(segment.get("words") or [])
        orig_text = str(segment.get("text", "") or "").strip()
        first_text = ""
        second_text = ""
        first_words = []
        second_words = []

        if words and len(words) >= 2:
            for w in words:
                w_start = float(w.get("start", 0.0))
                w_end = float(w.get("end", 0.0))
                w_mid = (w_start + w_end) / 2.0
                if w_mid <= split_time:
                    first_words.append(w)
                else:
                    second_words.append(w)
            if first_words and second_words:
                from app.services.segment_regroup_service import SegmentRegroupService
                first_text = SegmentRegroupService.join_words(first_words)
                second_text = SegmentRegroupService.join_words(second_words)

        if not first_text or not second_text:
            start_t = float(segment.get("start", 0.0))
            end_t = float(segment.get("end", split_time))
            dur = max(0.001, end_t - start_t)
            ratio = max(0.05, min(0.95, (split_time - start_t) / dur))
            from app.services.segment_regroup_service import SegmentRegroupService
            sentences = SegmentRegroupService.split_text_by_punctuation(orig_text)
            if len(sentences) >= 2:
                best_k = 1
                best_diff = 999.0
                cum_len = 0
                tot_len = sum(len(s) for s in sentences)
                for k in range(1, len(sentences)):
                    cum_len += len(sentences[k - 1])
                    sent_ratio = cum_len / tot_len
                    diff = abs(sent_ratio - ratio)
                    if diff < best_diff:
                        best_diff = diff
                        best_k = k
                first_text = " ".join(sentences[:best_k]).strip()
                second_text = " ".join(sentences[best_k:]).strip()
            elif " " in orig_text:
                tokens = orig_text.split()
                if len(tokens) >= 2:
                    split_idx = max(1, min(len(tokens) - 1, round(len(tokens) * ratio)))
                    first_text = " ".join(tokens[:split_idx]).strip()
                    second_text = " ".join(tokens[split_idx:]).strip()
            elif len(orig_text) >= 2:
                char_idx = max(1, min(len(orig_text) - 1, round(len(orig_text) * ratio)))
                first_text = orig_text[:char_idx].strip()
                second_text = orig_text[char_idx:].strip()

        first["text"] = first_text if first_text else orig_text
        second["text"] = second_text if second_text else orig_text
        first["tts_text"] = first["text"]
        second["tts_text"] = second["text"]
        first["words"] = first_words
        second["words"] = second_words

        first["manual_highlights"] = list(segment.get("manual_highlights", []))
        second["manual_highlights"] = list(segment.get("manual_highlights", []))
        if "tts_group_start" in first or "tts_group_end" in first:
            first["tts_group_start"] = float(first["start"])
            first["tts_group_end"] = float(first["end"])
            second["tts_group_start"] = float(second["start"])
            second["tts_group_end"] = float(second["end"])
        return first, second


    def split_selected_segment_by_sentences(self):
        if self._preview_is_playing():
            return
        segments = list(self.get_active_segments() or [])
        if not segments:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(segments)):
            index = self._find_active_segment_index(self.media_player.position(), segments)
        if not (0 <= index < len(segments)):
            QMessageBox.information(self, "Tách câu", "Vui lòng chọn một đoạn phụ đề trên timeline trước.")
            return

        target = segments[index]
        from app.services.segment_regroup_service import SegmentRegroupService
        regroup_service = SegmentRegroupService()
        sub_segs = regroup_service.split_segment_by_sentences(target)
        if len(sub_segs) <= 1:
            QMessageBox.information(
                self,
                "Tách câu",
                "Đoạn phụ đề này chỉ có 1 câu thoại ngắn, không tìm thấy dấu câu hoặc khoảng lặng để tách thêm.",
            )
            return

        split_history_entry = {
            "type": "split_sentences",
            "index": int(index),
            "selected_before": int(index),
            "selected_after": int(index),
            "current_before": [],
            "current_after": [],
            "translated_before": [],
            "translated_after": [],
        }

        # Apply to current_segments
        if 0 <= index < len(self.current_segments or []):
            split_history_entry["current_before"] = [copy.deepcopy(self.current_segments[index])]
            orig_sub_segs = regroup_service.split_segment_by_sentences(self.current_segments[index])
            self.current_segments[index:index + 1] = orig_sub_segs
            split_history_entry["current_after"] = [copy.deepcopy(s) for s in orig_sub_segs]
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            self._sync_hidden_transcript_text_from_segments()

        # Apply to current_translated_segments
        if 0 <= index < len(self.current_translated_segments or []):
            split_history_entry["translated_before"] = [copy.deepcopy(self.current_translated_segments[index])]
            trans_target = self.current_translated_segments[index]
            trans_dur = max(0.001, float(trans_target.get("end", 0)) - float(trans_target.get("start", 0)))
            trans_sentences = regroup_service.split_text_by_punctuation(str(trans_target.get("text", "") or ""), duration=trans_dur)
            trans_sub_segs = []
            if len(trans_sentences) == len(orig_sub_segs):
                for trans_text, base_seg in zip(trans_sentences, orig_sub_segs):
                    seg_dict = dict(trans_target)
                    seg_dict["start"] = base_seg["start"]
                    seg_dict["end"] = base_seg["end"]
                    seg_dict["text"] = trans_text
                    seg_dict["tts_text"] = trans_text
                    seg_dict["words"] = []
                    trans_sub_segs.append(seg_dict)
            elif len(trans_sentences) > 1:
                trans_sub_segs = regroup_service.split_segment_by_sentences(trans_target)
            else:
                words_list = str(trans_target.get("text", "") or "").split()
                if len(words_list) >= len(orig_sub_segs):
                    chunk_sz = max(1, len(words_list) // len(orig_sub_segs))
                    for k, base_seg in enumerate(orig_sub_segs):
                        seg_dict = dict(trans_target)
                        seg_dict["start"] = base_seg["start"]
                        seg_dict["end"] = base_seg["end"]
                        w_slice = words_list[k * chunk_sz:(k + 1) * chunk_sz] if k < len(orig_sub_segs) - 1 else words_list[k * chunk_sz:]
                        seg_dict["text"] = " ".join(w_slice)
                        seg_dict["tts_text"] = seg_dict["text"]
                        seg_dict["words"] = []
                        trans_sub_segs.append(seg_dict)
                else:
                    trans_sub_segs = regroup_service.split_segment_by_sentences(trans_target)
            self.current_translated_segments[index:index + 1] = trans_sub_segs
            split_history_entry["translated_after"] = [copy.deepcopy(s) for s in trans_sub_segs]
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()

        self._timeline_timing_undo_stack.append(split_history_entry)
        self._timeline_timing_redo_stack = []
        if len(self._timeline_timing_undo_stack) > 100:
            self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
        self._refresh_timeline_history_buttons()

        self.set_selected_segment_index(index, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(index)
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()
        if hasattr(self, "status_label"):
            self.status_label.setText(f"Đã tách đoạn thành {len(sub_segs)} câu thoại riêng biệt.")


    def split_selected_timeline_segment(self):
        if self._preview_is_playing():
            return
        selection = getattr(self.timeline, "selection_range", lambda: None)() if hasattr(self, "timeline") else None
        # A selected overlay always owns Split. The selection supplies cut
        # times only; it must never redirect the command to TS1.
        if self._split_selected_overlay_layer(selection):
            return
        if selection:
            start, end = selection
            if self._split_selected_subtitle_by_range(start, end):
                return
        # Overlay layers use the same Split action as subtitle/audio blocks.
        # Copying the layer preserves its style, transform and visibility;
        # only its identity and timing are changed.
        split_time = float(getattr(getattr(self, "timeline", None), "_playhead", 0.0)) or (float(self.media_player.position()) / 1000.0)
        
        # Kiểm tra trước nếu playhead đang nằm trên một Video layer hoặc Audio layer trên timeline:
        if hasattr(self, "timeline") and getattr(self.timeline, "_timeline", None):
            from app.layers.base import LayerType
            for track in self.timeline._timeline.tracks:
                t_name = str(getattr(track, "name", "") or "")
                t_type = getattr(track, "type", None)
                if t_name.startswith("V1") or t_type == LayerType.VIDEO or t_name.startswith("A1") or t_type == LayerType.AUDIO:
                    for layer in track.layers:
                        if float(layer.start) + 0.05 < split_time < float(layer.end) - 0.05:
                            self.timeline._selected_layer_id = layer.id
                            if self._split_selected_overlay_layer(selection):
                                return

        segments = list(self.get_active_segments() or [])
        if not segments:
            QMessageBox.information(self, "Cắt đoạn", "Vui lòng di chuyển kim thời gian vào bên trong đoạn video cần cắt.")
            return

        target = segments[index]
        start = float(target.get("start", 0.0))
        end = float(target.get("end", 0.0))
        min_gap = max(0.12, getattr(self.timeline, "MIN_SEGMENT_DURATION", 0.1))
        if not (start + min_gap < split_time < end - min_gap):
            # Nếu kim playhead không nằm trong subtitle segment này nhưng nằm trong Video layer:
            if hasattr(self, "timeline") and getattr(self.timeline, "_timeline", None):
                from app.layers.base import LayerType
                for track in self.timeline._timeline.tracks:
                    t_name = str(getattr(track, "name", "") or "")
                    t_type = getattr(track, "type", None)
                    if t_name.startswith("V1") or t_type == LayerType.VIDEO:
                        for layer in track.layers:
                            if float(layer.start) < split_time < float(layer.end):
                                self.timeline._selected_layer_id = layer.id
                                if self._split_selected_overlay_layer(selection):
                                    return
            QMessageBox.information(
                self,
                "Cắt đoạn",
                "Vui lòng di chuyển kim thời gian vào bên trong đoạn để cắt.",
            )
            return

        split_history_entry = {
            "type": "split",
            "index": int(index),
            "selected_before": int(index),
            "selected_after": int(index + 1),
            "current_before": [],
            "current_after": [],
            "translated_before": [],
            "translated_after": [],
        }

        if 0 <= index < len(self.current_segments or []):
            split_history_entry["current_before"] = [copy.deepcopy(self.current_segments[index])]
            first, second = self._build_split_segment_pair(self.current_segments[index], split_time)
            self.current_segments[index:index + 1] = [first, second]
            split_history_entry["current_after"] = [copy.deepcopy(first), copy.deepcopy(second)]
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            self._sync_hidden_transcript_text_from_segments()

        if 0 <= index < len(self.current_translated_segments or []):
            split_history_entry["translated_before"] = [copy.deepcopy(self.current_translated_segments[index])]
            first, second = self._build_split_segment_pair(self.current_translated_segments[index], split_time)
            self.current_translated_segments[index:index + 1] = [first, second]
            split_history_entry["translated_after"] = [copy.deepcopy(first), copy.deepcopy(second)]
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()

        self._timeline_timing_undo_stack.append(split_history_entry)
        self._timeline_timing_redo_stack = []
        if len(self._timeline_timing_undo_stack) > 100:
            self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
        self._refresh_timeline_history_buttons()

        self.set_selected_segment_index(index + 1, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(index + 1)
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()


    def _replace_subtitle_segments_in_range(existing, replacement, start, end):
        """Replace only the selected interval, retaining cue portions outside it."""
        retained = []
        for source in list(existing or []):
            segment = dict(source)
            segment_start = float(segment.get("start", 0.0))
            segment_end = float(segment.get("end", 0.0))
            overlaps = segment_end > start and segment_start < end
            if not overlaps:
                retained.append(segment)
                continue
            # A cue can cross either selection boundary. Keep the unaffected
            # temporal portion instead of deleting the entire cue.
            if segment_start < start:
                before = dict(segment)
                before["end"] = float(start)
                if float(before["end"]) > float(before["start"]):
                    retained.append(before)
            if segment_end > end:
                after = dict(segment)
                after["start"] = float(end)
                if float(after["end"]) > float(after["start"]):
                    retained.append(after)
        return sorted(retained + [dict(item) for item in list(replacement or [])], key=lambda seg: float(seg.get("start", 0.0)))


    def _split_selected_subtitle_by_range(self, range_start: float, range_end: float) -> bool:
        """Split only the selected TS1 cue at the selection boundaries."""
        selected_id = str(getattr(getattr(self, "timeline", None), "_selected_layer_id", "") or "")
        if selected_id:
            for track in self.timeline._timeline.tracks:
                if any(layer.id == selected_id for layer in track.layers) and bool(getattr(track, "locked", False)):
                    QMessageBox.information(self, "Layer Locked", "Unlock this timeline layer before splitting it.")
                    return True
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(self.get_active_segments() or [])):
            QMessageBox.information(self, "Split by Selection", "Select a subtitle segment before splitting it.")
            return True
        boundaries = (float(range_start), float(range_end))
        history = {"type": "range_split", "current_before": copy.deepcopy(self.current_segments), "translated_before": copy.deepcopy(self.current_translated_segments)}
        changed = False
        for attr, translated in (("current_segments", False), ("current_translated_segments", True)):
            source = list(getattr(self, attr, []) or [])
            if not (0 <= index < len(source)):
                continue
            rebuilt = list(source)
            pieces = [source[index]]
            for boundary in boundaries:
                next_pieces = []
                for piece in pieces:
                    start = float(piece.get("start", 0.0)); end = float(piece.get("end", 0.0))
                    if start + 0.01 < boundary < end - 0.01:
                        first, second = self._build_split_segment_pair(piece, boundary)
                        next_pieces.extend((first, second)); changed = True
                    else:
                        next_pieces.append(piece)
                pieces = next_pieces
            if changed:
                rebuilt[index:index + 1] = pieces
                setattr(self, attr, rebuilt)
                if translated:
                    self.current_translated_segment_models = self._dict_segments_to_models(rebuilt, translated=True)
                    self._sync_hidden_translated_text_from_segments()
                else:
                    self.current_segment_models = self._dict_segments_to_models(rebuilt, translated=False)
                    self._sync_hidden_transcript_text_from_segments()
        if not changed:
            QMessageBox.information(self, "Split by Selection", "No subtitle segment crosses the selection boundaries.")
            return False
        history["current_after"] = copy.deepcopy(self.current_segments)
        history["translated_after"] = copy.deepcopy(self.current_translated_segments)
        self._timeline_timing_undo_stack.append(history)
        self._timeline_timing_redo_stack = []
        self._refresh_timeline_history_buttons()
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()
        self.log(f"[Timeline] Split subtitle segments at selection {range_start:.3f}s–{range_end:.3f}s.")
        return True


    def _split_selected_overlay_layer(self, selection=None) -> bool:
        """Split a selected Video, Audio, Blur, Logo, Mask, or Text layer at the playhead."""
        timeline = getattr(self, "timeline", None)
        if timeline is None or not getattr(timeline, "_timeline", None):
            return False
        selected_id = str(getattr(timeline, "_selected_layer_id", "") or "")
        if not selected_id:
            return False
        selected_track = selected_layer = None
        for track in timeline._timeline.tracks:
            for layer in track.layers:
                if layer.id == selected_id:
                    selected_track, selected_layer = track, layer
                    break
            if selected_layer is not None:
                break
        if selected_layer is None:
            return False
        if bool(getattr(selected_track, "locked", False)):
            QMessageBox.information(self, "Lớp bị khóa", "Vui lòng mở khóa lớp này trước khi tách.")
            return True
        if bool(getattr(selected_layer, "locked", False)):
            QMessageBox.information(self, "Lớp bị khóa", "Vui lòng mở khóa đối tượng này trước khi tách.")
            return True
        layer_type = str(getattr(getattr(selected_layer, "type", ""), "value", getattr(selected_layer, "type", ""))).lower()
        track_name = str(getattr(selected_track, "name", "") or "")
        is_logo = layer_type == "image" and track_name == "L1 Logo"
        is_video = layer_type == "video" or track_name.startswith("V1")
        is_audio = layer_type == "audio" or track_name.startswith("A1")

        # TS1 DubSubtitleLayer do nhánh tách phụ đề chuyên dụng xử lý
        if layer_type in {"subtitle", "dub_subtitle"} or track_name.startswith("TS1"):
            return False

        if layer_type not in {"blur", "mask", "text", "video", "audio"} and not is_logo and not is_video and not is_audio:
            return False

        split_times = list(selection or (float(getattr(getattr(self, "timeline", None), "_playhead", 0.0)) or (float(self.media_player.position()) / 1000.0),))
        start, end = float(selected_layer.start), float(selected_layer.end)
        min_duration = max(0.1, float(getattr(timeline, "MIN_DUR", 0.1)))
        split_times = sorted({float(t) for t in split_times if start + min_duration < float(t) < end - min_duration})
        if not split_times:
            item_name = "clip video" if is_video else ("đoạn âm thanh" if is_audio else "đối tượng")
            QMessageBox.information(
                self,
                "Tách đoạn",
                f"Vui lòng di chuyển kim thời gian vào bên trong {item_name} đang chọn để tách.",
            )
            return True
        index = selected_track.layers.index(selected_layer)
        before_layers = copy.deepcopy(selected_track.layers)
        pieces = []
        piece_start = start
        orig_source_start = float(getattr(selected_layer, "source_start", 0.0) or 0.0)
        for part_index, split_time in enumerate(split_times + [end]):
            piece = copy.deepcopy(selected_layer)
            piece.id = selected_layer.id if part_index == 0 else uuid4().hex[:12]
            base_name = str(getattr(selected_layer, "name", "Layer") or "Layer")
            piece.name = base_name if part_index == 0 else f"{base_name} {part_index + 1}"
            piece.start, piece.end = piece_start, split_time
            if is_video or is_audio:
                piece.source_start = orig_source_start + max(0.0, piece_start - start)
            piece_start = split_time
            pieces.append(piece)
        selected_track.layers[index:index + 1] = pieces
        new_layer = pieces[-1]
        timeline._selected_layer_id = new_layer.id
        self._timeline_timing_undo_stack.append({
            "type": "overlay_split",
            "track_id": selected_track.id,
            "before_layers": before_layers,
            "after_layers": copy.deepcopy(selected_track.layers)
        })
        self._timeline_timing_redo_stack = []
        self._refresh_timeline_history_buttons()
        timeline._redraw()
        self.persist_current_timeline_project_data()
        self.on_timeline_layer_selected(new_layer.id)
        self.refresh_ui_state()
        if hasattr(self, "status_label"):
            item_label = "clip video" if is_video else ("âm thanh" if is_audio else "đối tượng")
            self.status_label.setText(f"Đã tách {item_label} tại {split_times[0]:.2f}s.")
        return True


    def _apply_overlay_split_history(self, entry, *, use_after: bool):
        timeline = getattr(self, "timeline", None)
        if timeline is None or not timeline._timeline:
            return
        track_id = str(entry.get("track_id", ""))
        for track in timeline._timeline.tracks:
            if track.id == track_id:
                track.layers = copy.deepcopy(entry.get("after_layers" if use_after else "before_layers", []))
                timeline._selected_layer_id = track.layers[-1].id if track.layers else ""
                timeline._redraw()
                self.persist_current_timeline_project_data()
                self.refresh_ui_state()
                return


    def _apply_range_split_history(self, entry, *, use_after: bool):
        suffix = "after" if use_after else "before"
        self.current_segments = copy.deepcopy(entry.get(f"current_{suffix}", []))
        self.current_translated_segments = copy.deepcopy(entry.get(f"translated_{suffix}", []))
        self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_hidden_transcript_text_from_segments()
        self._sync_hidden_translated_text_from_segments()
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()


    def _find_segment_editor_row(self, segment_index: int):
        for row in getattr(self, "_segment_editor_rows", []):
            if int(row.get("segment_index", -1)) == int(segment_index):
                return row
        return None


    def _is_subtitle_inspector_details_visible(self) -> bool:
        stack = getattr(self, "inspector_stack", None)
        if not stack or stack.currentIndex() != 0:
            return False
        card = getattr(self, "subtitle_inspector_card", None)
        return bool(card and card.isVisible())


    def is_subtitle_inspector_anchored(self) -> bool:
        # Backwards-compatible alias - the anchor now applies to the
        # entire track inspector (subtitle, audio, blur, default).
        return self.is_inspector_anchored()


    def _sync_subtitle_inspector_shell_width(self, visible: bool = None):
        """Width of the inspector shell.

        The shell hosts a QStackedWidget that can show a subtitle, audio or
        default card. Width is driven by the `_inspector_collapsed` state:
        - collapsed=True  -> handle only
        - collapsed=False -> wide enough for the widest card

        The `visible` parameter is ignored (kept for API compatibility).
        """
        shell = getattr(self, "subtitle_inspector_shell", None)
        if shell is None:
            return
        # The handle was removed - no extra handle width to add.
        handle_width = 0

        if bool(getattr(self, "_inspector_collapsed", False)):
            target_width = handle_width
        else:
            responsive_width = int(getattr(self, "_responsive_inspector_width", 0) or 0)
            widest = responsive_width if responsive_width > 0 else 400
            for attr in ("subtitle_inspector_card", "audio_inspector_card", "default_inspector_card"):
                card = getattr(self, attr, None)
                if card is None:
                    continue
                try:
                    raw_max = int(card.maximumWidth() or 0)
                    if raw_max > 5000 or raw_max <= 0:
                        raw_max = 0
                    raw_min = int(card.minimumWidth() or 0)
                    if raw_min > 5000 or raw_min < 0:
                        raw_min = 0
                    raw_hint = int(card.sizeHint().width() or 0)
                    candidate = raw_max or raw_hint or raw_min or widest
                    widest = max(widest, candidate)
                except Exception:
                    pass
            if responsive_width > 0:
                widest = max(responsive_width, min(widest, 440))
            else:
                widest = max(400, min(widest, 560))
            target_width = handle_width + widest
        shell.setMinimumWidth(target_width)
        shell.setMaximumWidth(target_width)
        shell.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)


    def _update_subtitle_inspector_summary(self, rows=None):
        rows = rows if rows is not None else self._segment_editor_display_rows()
        count = len(rows or [])
        translation_ready = self._translation_phase_complete()
        if not count:
            self._selected_segment_index = -1
            if hasattr(self, "subtitle_inspector_summary_label"):
                self.subtitle_inspector_summary_label.setText("Selected subtitle: none")
            if hasattr(self, "rewrite_selected_segment_btn"):
                self.rewrite_selected_segment_btn.setEnabled(False)
            return

        selected_index = self._get_effective_selected_segment_index(rows)
        if selected_index < 0 or selected_index >= count:
            selected_index = int(rows[0].get("segment_index", 0))
        self._selected_segment_index = selected_index
        if hasattr(self, "subtitle_inspector_summary_label"):
            self.subtitle_inspector_summary_label.setText(f"Selected subtitle: Block {selected_index + 1} / {count}")
        if hasattr(self, "rewrite_selected_segment_btn"):
            self.rewrite_selected_segment_btn.setEnabled(translation_ready)


    def set_subtitle_inspector_details_visible(self, visible: bool, *, sync: bool = True):
        if not visible and self.is_inspector_anchored():
            visible = True
        # The subtitle details widget (segment editor) visibility is
        # independent from the audio/default cards. The shell collapse
        # state is managed via `set_inspector_collapsed` (called from the
        # toggle button handler), not by this function.
        widget = getattr(self, "subtitle_inspector_details_widget", None)
        if widget is not None:
            widget.setVisible(bool(visible))
        toggle_btn = getattr(self, "subtitle_inspector_toggle_btn", None)
        if toggle_btn is not None:
            toggle_btn.blockSignals(True)
            toggle_btn.setChecked(bool(visible))
            if str(toggle_btn.objectName() or "") == "subtitleInspectorHandleBtn":
                toggle_btn.setText("▶" if visible else "◀")
                toggle_btn.setToolTip("Hide subtitle editor" if visible else "Show subtitle editor")
            else:
                toggle_btn.setText("Hide details" if visible else "Show details")
            toggle_btn.blockSignals(False)
        anchor_cb = getattr(self, "anchor_inspector_cb", None)
        if anchor_cb is not None:
            toggle_btn = getattr(self, "subtitle_inspector_toggle_btn", None)
            if toggle_btn is not None:
                toggle_btn.setEnabled(not self.is_inspector_anchored())
        if not visible:
            self._clear_segment_editor_rows()
            self._segment_editor_rows = []
            self._update_subtitle_inspector_summary()
        else:
            self._sync_selected_segment_to_playback_position()
            if sync:
                self.sync_segment_editor_rows()


    def show_subtitle_inspector_details(self):
        self.set_subtitle_inspector_details_visible(True, sync=True)


    def toggle_subtitle_inspector_details(self, checked: bool):
        # checked=True means "show details" (expand the inspector shell).
        # checked=False means "hide details" (collapse to handle only).
        self.set_inspector_collapsed(not bool(checked))
        # Also update the subtitle details widget visibility (so the
        # segment editor appears/disappears).
        widget = getattr(self, "subtitle_inspector_details_widget", None)
        if widget is not None:
            widget.setVisible(bool(checked))


    def sync_segment_editor_rows(self):
        if hasattr(self, "subtitle_list_view") and self.subtitle_list_view:
            try:
                self.subtitle_list_view.refresh_segments()
            except Exception:
                pass
        if not hasattr(self, "segment_editor_layout") or getattr(self, "_syncing_segment_editor", False):
            return
        if not self._is_subtitle_inspector_details_visible():
            self._update_subtitle_inspector_summary()
            return

        self._syncing_segment_editor = True
        try:
            self._clear_segment_editor_rows()
            self._segment_editor_rows = []
            rows = self._segment_editor_display_rows()
            self._update_subtitle_inspector_summary(rows)
            if not rows:
                empty_state = QFrame(self.segment_editor_container if hasattr(self, "segment_editor_container") else None)
                empty_state.setObjectName("statusCard")
                empty_state.setMinimumHeight(180)
                empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                empty_state.setStyleSheet(
                    "QFrame#statusCard { background-color: #132132; border: 1px dashed #35506f; border-radius: 16px; }"
                )
                empty_layout = QVBoxLayout(empty_state)
                empty_layout.setContentsMargins(18, 18, 18, 18)
                empty_layout.setSpacing(8)
                empty_layout.addStretch()
                empty_title = QLabel("Subtitle editor is waiting for content")
                empty_title.setObjectName("statusHeadline")
                empty_title.setAlignment(Qt.AlignCenter)
                empty_body = QLabel("Subtitle editor will appear here once transcript or translation is ready.")
                empty_body.setObjectName("helperLabel")
                empty_body.setWordWrap(True)
                empty_body.setAlignment(Qt.AlignCenter)
                empty_layout.addWidget(empty_title)
                empty_layout.addWidget(empty_body)
                empty_layout.addStretch()
                self.segment_editor_layout.addWidget(empty_state, 1)
                return

            selected_index = self._get_effective_selected_segment_index(rows)
            visible_rows = [row for row in rows if int(row.get("segment_index", -1)) == selected_index]
            if not visible_rows:
                visible_rows = [rows[0]]
                selected_index = int(visible_rows[0].get("segment_index", 0))
            self._update_subtitle_inspector_summary(rows)

            show_original = True
            for row in visible_rows:
                idx = int(row.get("segment_index", 0))
                card = QFrame(self.segment_editor_container if hasattr(self, "segment_editor_container") else None)
                # No border on the subtitle display frame - blends into
                # the inspector shell.
                card.setFrameShape(QFrame.NoFrame)
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(4, 4, 4, 4)
                card_layout.setSpacing(6)

                # Start/End timing chips
                timing_meta_layout = QHBoxLayout()
                timing_meta_layout.setContentsMargins(0, 0, 0, 0)
                timing_meta_layout.setSpacing(12)
                start_label = QLabel(f"Start  {self.format_timestamp(row['start'])}")
                start_label.setObjectName("timingChip")
                end_label = QLabel(f"End  {self.format_timestamp(row['end'])}")
                end_label.setObjectName("timingChip")
                timing_meta_layout.addWidget(start_label)
                timing_meta_layout.addWidget(end_label)

                fusion_status = str(row.get("status", "") or "").strip()
                if fusion_status:
                    fusion_badge = QLabel()
                    reason_desc = str(row.get("fusion_reason", "") or "")
                    speech_cov = float(row.get("speech_coverage", 0.0))
                    asr_align = float(row.get("asr_alignment", 0.0))
                    bbox_persist = float(row.get("bbox_persistence", 0.0))

                    if fusion_status == "confirmed_speech":
                        badge_text = "🟢 Thoại"
                        badge_style = "background: #06281e; color: #34d399; border: 1px solid #059669; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold;"
                    elif fusion_status == "review":
                        badge_text = "🟡 Cần xem"
                        badge_style = "background: #2b1d06; color: #fbbf24; border: 1px solid #d97706; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold;"
                    elif fusion_status == "static_text":
                        badge_text = "🔴 Chữ tĩnh"
                        badge_style = "background: #2b0b0e; color: #f87171; border: 1px solid #dc2626; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold;"
                    else:
                        badge_text = f"ℹ️ {fusion_status}"
                        badge_style = "background: #111e2e; color: #94a3b8; border: 1px solid #334155; border-radius: 4px; padding: 2px 8px; font-size: 11px;"

                    fusion_badge.setText(badge_text)
                    fusion_badge.setStyleSheet(badge_style)
                    fusion_badge.setToolTip(
                        f"Phân loại Multimodal Fusion:\n"
                        f"- Trạng thái: {badge_text}\n"
                        f"- Lý do: {reason_desc or 'Chưa rõ'}\n"
                        f"- Độ phủ giọng nói (VAD): {speech_cov * 100:.1f}%\n"
                        f"- Khớp ASR: {asr_align * 100:.1f}%\n"
                        f"- BBox persistence: {bbox_persist * 100:.1f}%"
                    )
                    timing_meta_layout.addWidget(fusion_badge)

                timing_meta_layout.addStretch()

                original_label = QLabel(row["original"] or "", card)
                original_label.setWordWrap(True)
                original_label.setObjectName("helperLabel")
                original_label.setVisible(show_original and bool(row["original"].strip()))

                card_layout.addLayout(timing_meta_layout)

                # Speaker assignment is intentionally local to the selected
                # cue.  It lets users correct diarization mistakes without
                # rerunning the entire audio analysis pass.
                speaker_row = QHBoxLayout()
                speaker_row.setContentsMargins(0, 0, 0, 0)
                speaker_row.setSpacing(8)
                speaker_ids = self._detected_speaker_ids()
                segment_source = self.current_translated_segments or self.current_segments or []
                selected_speaker = ""
                if 0 <= idx < len(segment_source):
                    selected_speaker = str(segment_source[idx].get("speaker", "") or "").strip()
                try:
                    speaker_position = speaker_ids.index(selected_speaker)
                except ValueError:
                    speaker_position = -1
                speaker_indicator = QLabel()
                speaker_indicator.setFixedSize(10, 10)
                speaker_indicator.setStyleSheet(
                    "background: %s; border-radius: 5px; border: 1px solid #dcecff;"
                    % (self._speaker_color_hex(selected_speaker) if selected_speaker else "#53657d")
                )
                speaker_row.addWidget(speaker_indicator)
                speaker_row.addWidget(QLabel("Speaker:"))
                speaker_combo = QComboBox()
                speaker_options = [
                    ("Mặc định", ""),
                    ("Speaker A (Người nói 1)", "SPEAKER_00"),
                    ("Speaker B (Người nói 2)", "SPEAKER_01"),
                    ("Speaker C (Người nói 3)", "SPEAKER_02"),
                    ("Speaker D (Người nói 4)", "SPEAKER_03"),
                ]
                existing_keys = {k for _, k in speaker_options}
                for position, speaker_id in enumerate(speaker_ids):
                    if speaker_id not in existing_keys:
                        speaker_options.append((self._speaker_display_name(speaker_id, position), speaker_id))
                for label, s_id in speaker_options:
                    speaker_combo.addItem(label, s_id)
                combo_index = speaker_combo.findData(selected_speaker)
                if combo_index >= 0:
                    speaker_combo.setCurrentIndex(combo_index)
                else:
                    speaker_combo.setCurrentIndex(0)
                speaker_combo.setEnabled(True)
                speaker_combo.setToolTip("Gán người nói cho đoạn phụ đề này để đọc giọng riêng.")
                speaker_combo.currentIndexChanged.connect(
                    lambda _value, segment_index=idx, combo=speaker_combo: self.on_segment_speaker_changed(
                        segment_index, str(combo.currentData() or "")
                    )
                )
                speaker_row.addWidget(speaker_combo, 1)
                speaker_row.addStretch()
                card_layout.addLayout(speaker_row)

                speed_row = QHBoxLayout()
                speed_row.setContentsMargins(0, 0, 0, 0)
                speed_row.setSpacing(8)
                speed_label = QLabel("Voice Speed:")
                speed_label.setObjectName("helperLabel")
                speed_spin = ReliableDoubleSpinBox()
                speed_spin.setRange(0.5, 3.0)
                speed_spin.setSingleStep(0.1)
                speed_spin.setDecimals(1)
                speed_spin.setValue(float(row.get("voice_speed", 1.0)))
                speed_spin.setSuffix("x")
                speed_spin.setFixedWidth(90)
                speed_spin.valueChanged.connect(
                    lambda val, idx=idx: self.on_segment_voice_speed_changed(idx, val)
                )
                speed_row.addWidget(speed_label)
                speed_row.addWidget(speed_spin)
                speed_row.addStretch()

                card_layout.addLayout(speed_row)
                card_layout.addWidget(original_label)

                # The QTabWidget wrapper (with the "Subtitle" tab label
                # and the horizontal tab bar / "hr" beneath it) has been
                # removed. The translated editor + highlight actions are
                # placed directly in the card layout.
                translated_editor = QTextEdit()
                translated_editor.setObjectName("segmentInspectorEditor")
                translated_editor.setAcceptRichText(False)
                translated_editor.setPlainText(row["translated"])
                translated_editor.setMinimumHeight(96)
                translated_editor.setMaximumHeight(96)
                translated_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                translated_editor.setPlaceholderText("Text shown on screen.")
                translated_editor.textChanged.connect(
                    lambda idx=idx, editor=translated_editor: self.on_segment_translation_edited(idx, editor)
                )
                translated_editor.selectionChanged.connect(
                    lambda idx=idx, editor=translated_editor: self._update_segment_highlight_button_state(idx, editor)
                )
                highlight_btn = QPushButton("Add highlight from selection")
                highlight_btn.setEnabled(False)
                highlight_btn.clicked.connect(
                    lambda _=False, idx=idx, editor=translated_editor: self.add_segment_manual_highlight(idx, editor)
                )

                highlight_action_layout = QHBoxLayout()
                highlight_action_layout.setContentsMargins(0, 0, 0, 0)
                highlight_action_layout.setSpacing(8)
                highlight_action_layout.addWidget(highlight_btn)
                highlight_action_layout.addStretch()

                highlight_meta_layout = QHBoxLayout()
                highlight_meta_layout.setContentsMargins(0, 0, 0, 0)
                highlight_meta_layout.setSpacing(6)
                highlight_placeholder = QLabel("")
                highlight_placeholder.setObjectName("helperLabel")
                highlight_chip_container = QWidget()
                highlight_chip_layout = QHBoxLayout(highlight_chip_container)
                highlight_chip_layout.setContentsMargins(0, 0, 0, 0)
                highlight_chip_layout.setSpacing(6)
                highlight_meta_layout.addWidget(highlight_placeholder)
                highlight_meta_layout.addWidget(highlight_chip_container, 1)

                card_layout.addWidget(translated_editor, 0)
                card_layout.addLayout(highlight_action_layout)
                card_layout.addLayout(highlight_meta_layout)

                self.segment_editor_layout.addWidget(card, 0)
                self._segment_editor_rows.append(
                    {
                        "segment_index": idx,
                        "frame": card,
                        "original_label": original_label,
                        "translated_editor": translated_editor,
                        "highlight_button": highlight_btn,
                        "highlight_placeholder": highlight_placeholder,
                        "highlight_chip_layout": highlight_chip_layout,
                    }
                )
                self._update_segment_highlight_button_state(idx, translated_editor)
                self._sync_segment_highlight_chip_row(idx)
                self._update_segment_spoken_status(idx)

            self._set_segment_editor_highlight(selected_index)
        finally:
            self._syncing_segment_editor = False


    def _sync_hidden_translated_text_from_segments(self):
        if getattr(self, "_syncing_segment_editor", False):
            return
        self._syncing_hidden_editor_text = True
        try:
            self.translated_text.setText(self.format_to_srt(self.current_translated_segments))
        finally:
            self._syncing_hidden_editor_text = False


    def _update_ocr_overlay(self):
        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is None:
            return
        is_ocr = os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine()).strip().lower() == "ocr"
        alternate_ocr_active = bool(getattr(self, "_alternate_ocr_range_pending", None))
        btn = getattr(self, "ocr_region_btn", None)
        if btn:
            btn.setVisible(is_ocr)
            btn.blockSignals(True)
            btn.setChecked(bool(getattr(self, "_ocr_overlay_visible", True)))
            btn.blockSignals(False)
        if not is_ocr and not alternate_ocr_active:
            overlay._requested_visible = False
            overlay.hide()
            overlay.set_editable(False)
        else:
            overlay._requested_visible = bool(alternate_ocr_active or getattr(self, "_ocr_overlay_visible", True))
            if bool(alternate_ocr_active or getattr(self, "_ocr_overlay_visible", True)):
                overlay.set_editable(True)
                overlay.sync_to_view()
            else:
                overlay.set_editable(False)
                overlay.hide()


    def toggle_ocr_overlay_visibility(self, checked: bool):
        self._ocr_overlay_visible = bool(checked)
        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is not None:
            overlay._requested_visible = bool(checked)
            overlay.set_editable(bool(checked))
            if checked:
                overlay.sync_to_view()
                overlay.raise_()
                QTimer.singleShot(0, overlay.sync_to_view)
            else:
                overlay.hide()
        self._update_ocr_overlay()


    def toggle_ocr_region_editing(self, checked: bool):
        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is None:
            return
        engine = os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine())
        if not checked or engine != "ocr":
            overlay.hide()
            overlay.set_editable(False)
            self.ocr_region_btn.setStyleSheet("QPushButton { color: #6ee7d6; font-weight: bold; font-size: 10px; padding: 0; }")
            self._sync_blur_controls()
            return
        if self._blur_effect_enabled() and hasattr(self, "video_view") and hasattr(self.video_view, "set_blur_edit_enabled"):
            self.video_view.set_blur_edit_enabled(False)
        overlay.set_editable(True)
        overlay.sync_to_view()
        self.apply_preview_blur_region()
        self.log("[OCR Region] drag inside the video preview to move or resize the OCR crop.")


    def toggle_ocr_translator(self, checked: bool):
        """Show the independent, on-demand OCR Translator selection."""
        overlay = getattr(self, "ocr_translator_overlay", None)
        self._ocr_translator_active = bool(checked)
        if overlay is None:
            return
        if not self._ocr_translator_active:
            overlay.hide()
            return
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        if not video_path or not os.path.isfile(video_path):
            self._ocr_translator_active = False
            button = getattr(self, "ocr_translator_btn", None)
            if button is not None:
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
            QMessageBox.warning(self, "OCR Translator", "Please load a video before capturing visual text.")
            return
        overlay.set_normalized_rect(getattr(self, "_ocr_translator_rect", (0.2, 0.2, 0.6, 0.25)))
        overlay.sync_to_view()
        # The preview's native mpv surface can finish its layout after the
        # toolbar signal. Re-sync on the next event-loop pass so the tool
        # always receives the final visible video geometry.
        QTimer.singleShot(0, overlay.sync_to_view)
        self.log("[OCR Translator] Selection active. Drag or resize it, then click Capture.")


    def _on_ocr_translator_rect_changed(self, rect):
        self._ocr_translator_rect = tuple(rect)


    def capture_ocr_translator_region(self):
        if getattr(self, "_ocr_translator_capture_worker", None) is not None:
            return
        video_path = self.video_path_edit.text().strip()
        overlay = getattr(self, "ocr_translator_overlay", None)
        if not video_path or overlay is None:
            return
        position_ms = int(self.media_player.position()) if hasattr(self, "media_player") else 0
        self._ocr_translator_rect = overlay.normalized_rect()
        overlay.set_capturing(True)
        worker = OcrTranslatorCaptureWorker(video_path, position_ms / 1000.0, self._ocr_translator_rect)
        self._ocr_translator_capture_worker = worker
        worker.finished.connect(self._on_ocr_translator_capture_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self.log(f"[OCR Translator] Capturing visual text at {position_ms / 1000.0:.2f}s.")


    def _on_ocr_translator_capture_finished(self, text, error):
        self._ocr_translator_capture_worker = None
        overlay = getattr(self, "ocr_translator_overlay", None)
        if overlay is not None:
            overlay.set_capturing(False)
        if error:
            QMessageBox.warning(self, "OCR Translator", f"Could not capture text.\n\n{error}")
            return
        if not str(text or "").strip():
            QMessageBox.information(self, "OCR Translator", "No text was detected in the selected region.")
            return
        self.log("[OCR Translator] Capture complete.")
        self._show_ocr_translator_dialog(str(text).strip())


    def _show_ocr_translator_dialog(self, original_text):
        overlay = getattr(self, "ocr_translator_overlay", None)
        if overlay is not None:
            overlay.hide()
        dialog = QDialog(self)
        dialog.setWindowTitle("Dịch OCR")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumSize(520, 390)
        dialog.setStyleSheet(
            "QDialog { background: #101826; color: #e6eef9; }"
            "QLabel { color: #b9c8dc; font-weight: 700; }"
            "QTextEdit { background: #0b1220; color: #edf4ff; border: 1px solid #2b3b52; border-radius: 7px; padding: 7px; }"
            "QPushButton { background: #24364f; color: #ffffff; border: 1px solid #355271; border-radius: 7px; padding: 7px 12px; font-weight: 700; }"
            "QPushButton:hover { background: #315070; } QPushButton:disabled { color: #718198; background: #182334; }"
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Văn bản OCR gốc"))
        original_edit = QTextEdit(); original_edit.setPlainText(original_text); original_edit.setReadOnly(True)
        layout.addWidget(original_edit, 1)
        layout.addWidget(QLabel("Văn bản đã dịch"))
        translated_edit = QTextEdit(); translated_edit.setReadOnly(True); translated_edit.setPlaceholderText("Nhấn Dịch để dịch văn bản đã chụp.")
        layout.addWidget(translated_edit, 1)
        actions = QHBoxLayout()
        translate_btn = QPushButton("Dịch")
        copy_original_btn = QPushButton("Sao chép gốc")
        copy_translation_btn = QPushButton("Sao chép bản dịch")
        close_btn = QPushButton("Đóng")
        actions.addWidget(translate_btn); actions.addWidget(copy_original_btn); actions.addWidget(copy_translation_btn); actions.addStretch(1); actions.addWidget(close_btn)
        layout.addLayout(actions)

        def copy_text(edit):
            QApplication.clipboard().setText(edit.toPlainText())

        def translate():
            if getattr(self, "_ocr_translator_translation_worker", None) is not None:
                return
            translate_btn.setEnabled(False); translate_btn.setText("Đang dịch...")
            worker = OcrTranslatorTranslationWorker(
                original_text, self.get_source_language_code(), self.get_target_language_code()
            )
            self._ocr_translator_translation_worker = worker
            def finished(translated, error):
                self._ocr_translator_translation_worker = None
                translate_btn.setEnabled(True); translate_btn.setText("Dịch")
                if error:
                    QMessageBox.warning(dialog, "Dịch OCR", f"Dịch thất bại.\n\n{error}")
                    return
                translated_edit.setPlainText(translated)
                self.log("[Dịch OCR] Đã dịch xong.")
            worker.finished.connect(finished)
            worker.finished.connect(worker.deleteLater)
            worker.start()

        translate_btn.clicked.connect(translate)
        copy_original_btn.clicked.connect(lambda: copy_text(original_edit))
        copy_translation_btn.clicked.connect(lambda: copy_text(translated_edit))
        close_btn.clicked.connect(dialog.accept)
        dialog.finished.connect(lambda _result: overlay.sync_to_view() if overlay is not None and self._ocr_translator_active else None)
        dialog.exec()


    def download_subtitle(self):
        srt_text = self.translated_text.toPlainText().strip()
        if not srt_text:
            QMessageBox.warning(self, "Missing Subtitle", "No translated subtitle is ready yet.")
            return
        target_lang = str(self.get_target_language_code() or "translated").lower()
        suggested_name = os.path.splitext(os.path.basename(self.video_path_edit.text().strip() or "subtitle"))[0] + f"_{target_lang}.srt"
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Translated Subtitle", suggested_name, "Subtitle Files (*.srt)")
        if not file_path:
            return
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(srt_text)
        QMessageBox.information(self, "Saved", f"Translated subtitle exported to:\n\n{file_path}")


    def import_original_srt(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Original Subtitle",
            self.srt_output_folder_edit.text().strip() or self.workspace_root,
            "Subtitle Files (*.srt)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8-sig") as handle:
                srt_text = handle.read().strip()
        except Exception as exc:
            self.show_error("Import Failed", "Could not read the selected subtitle file.", str(exc))
            return

        if not srt_text:
            QMessageBox.warning(self, "Import Failed", "The selected subtitle file is empty.")
            return

        imported_segments = self.parse_srt_to_segments(srt_text)
        if not imported_segments:
            QMessageBox.warning(self, "Import Failed", "The selected file could not be parsed as a valid SRT subtitle.")
            return

        self.current_segments = imported_segments
        self.transcript_text.setText(srt_text)
        self.last_original_srt_path = file_path
        self.persist_transcription_project_data(imported_segments, srt_path=file_path)
        state = self.ensure_current_project()
        if state:
            state.set_setting("transcription_signature", "")
            self.project_service.save_project(state)
        self._sync_segment_models_from_current_segments()
        if hasattr(self, "timeline"):
            self.timeline.set_segments(self.current_segments)
            self.schedule_timeline_visual_refresh(waveform=True, thumbnails=True)
        self.log(f"[Import] Original subtitle loaded: {file_path} ({len(imported_segments)} segments)")
        QMessageBox.information(self, "Import Success", f"Loaded {len(imported_segments)} segments from original subtitle.")
        self.refresh_ui_state()


    def import_translated_srt(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Translated Subtitle",
            self.srt_output_folder_edit.text().strip() or self.workspace_root,
            "Subtitle Files (*.srt)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8-sig") as handle:
                srt_text = handle.read().strip()
        except Exception as exc:
            self.show_error("Import Failed", "Could not read the selected subtitle file.", str(exc))
            return

        if not srt_text:
            QMessageBox.warning(self, "Import Failed", "The selected subtitle file is empty.")
            return

        imported_segments = self.parse_srt_to_segments(srt_text)
        if not imported_segments:
            QMessageBox.warning(self, "Import Failed", "The selected file could not be parsed as a valid SRT subtitle.")
            return

        # An SRT only stores text/timestamps. Keep diarization metadata from
        # the current translated transcript first (manual speaker corrections
        # are stored there), falling back to the original transcript. Matching
        # by overlap also works when an imported file has slightly different
        # cue boundaries or a different number of cues.
        base_segments = self.current_translated_segments or self.current_segments
        if base_segments:
            for imported in imported_segments:
                try:
                    start = float(imported.get("start", 0.0))
                    end = float(imported.get("end", start))
                except (TypeError, ValueError):
                    continue
                best = None
                best_score = -1.0
                midpoint = (start + end) / 2.0
                for base in base_segments:
                    speaker = str(base.get("speaker", "") or "").strip()
                    if not speaker:
                        continue
                    try:
                        base_start = float(base.get("start", 0.0))
                        base_end = float(base.get("end", base_start))
                    except (TypeError, ValueError):
                        continue
                    overlap = max(0.0, min(end, base_end) - max(start, base_start))
                    distance = abs(midpoint - ((base_start + base_end) / 2.0))
                    score = overlap * 1000.0 - distance
                    if score > best_score:
                        best_score = score
                        best = base
                if best is not None:
                    speaker = str(best.get("speaker", "") or "").strip()
                    if speaker:
                        imported["speaker"] = speaker
        if self.keep_timeline_cb.isChecked() and base_segments and len(base_segments) == len(imported_segments):
            merged_segments = []
            for idx, base in enumerate(base_segments):
                merged = dict(imported_segments[idx])
                merged["start"] = float(base.get("start", 0.0))
                merged["end"] = float(base.get("end", 0.0))
                merged["words"] = list(base.get("words", []))
                if base.get("speaker"):
                    merged["speaker"] = str(base.get("speaker", "") or "")
                if "manual_highlights" in imported_segments[idx]:
                    merged["manual_highlights"] = imported_segments[idx]["manual_highlights"]
                elif base.get("manual_highlights"):
                    merged["manual_highlights"] = list(base.get("manual_highlights", []))
                merged_segments.append(merged)
            imported_segments = merged_segments
            srt_text = self.format_to_srt(imported_segments)

        self.translated_text.setText(srt_text)
        self.apply_edited_translation(show_message=False, force_apply=True)
        # ``apply_edited_translation`` rebuilds dictionaries from SRT (which
        # has no speaker field). Re-apply the metadata-bearing imported list
        # after that conversion so the speaker assignments survive both the
        # editor update and the timeline rebuild.
        if imported_segments and self.current_translated_segments:
            if len(imported_segments) == len(self.current_translated_segments):
                for idx, imported in enumerate(imported_segments):
                    speaker = str(imported.get("speaker", "") or "").strip()
                    if speaker:
                        self.current_translated_segments[idx]["speaker"] = speaker
            else:
                for target in self.current_translated_segments:
                    try:
                        start = float(target.get("start", 0.0))
                        end = float(target.get("end", start))
                    except (TypeError, ValueError):
                        continue
                    best = None
                    best_score = -1.0
                    midpoint = (start + end) / 2.0
                    for imported in imported_segments:
                        speaker = str(imported.get("speaker", "") or "").strip()
                        if not speaker:
                            continue
                        try:
                            imported_start = float(imported.get("start", 0.0))
                            imported_end = float(imported.get("end", imported_start))
                        except (TypeError, ValueError):
                            continue
                        overlap = max(0.0, min(end, imported_end) - max(start, imported_start))
                        distance = abs(midpoint - ((imported_start + imported_end) / 2.0))
                        score = overlap * 1000.0 - distance
                        if score > best_score:
                            best_score = score
                            best = imported
                    if best is not None:
                        target["speaker"] = str(best.get("speaker", "") or "").strip()
            self.current_translated_segment_models = self._dict_segments_to_models(
                self.current_translated_segments,
                translated=True,
            )
            self.apply_segments_to_timeline()
        self.last_translated_srt_path = file_path
        self.processed_artifacts["srt_translated"] = file_path
        self.persist_translation_project_data(self.current_translated_segments, file_path)
        # Rebuild speaker UI/colors after replacing the translated cues.  The
        # imported SRT itself cannot contain speaker metadata, so the merge
        # above is the source of truth for these project-only fields.
        self.refresh_detected_speakers_section()
        self._refresh_speaker_subtitle_colors_if_needed()
        self.refresh_ui_state()
        QMessageBox.information(
            self,
            "Imported",
            "Translated subtitle loaded. You can now run Generate Voice / TTS.\n\n" + file_path,
        )


    def _uses_exact_full_block_subtitle_background(self) -> bool:
        """Whether the live ASS path needs exact, measured vector geometry."""
        try:
            return bool(
                getattr(self, "subtitle_background_cb", None)
                and self.subtitle_background_cb.isChecked()
                and getattr(self, "subtitle_background_width_combo", None)
                and str(self.subtitle_background_width_combo.currentData() or self.subtitle_background_width_combo.currentText()).strip().lower()
                in {"full_area", "full subtitle area", "full block"}
            )
        except Exception:
            return False


    def _build_live_subtitle_ass_snapshot(self, segments):
        """Capture all Qt-owned state before an ASS worker is started."""
        video_path = self.video_path_edit.text().strip()
        source_width = max(1, int(getattr(self.video_view, "video_source_width", 0) or 1920))
        source_height = max(1, int(getattr(self.video_view, "video_source_height", 0) or 1080))
        canvas_width, canvas_height = self._subtitle_render_dimensions()
        subtitle_style = copy.deepcopy(self.get_subtitle_export_style(segments=segments))
        if subtitle_style.get("custom_position_enabled") and (canvas_width != source_width or canvas_height != source_height):
            try:
                scale_mode = self.get_output_scale_mode_key()
                focus_x, focus_y = self.get_output_fill_focus()
                scale = max(canvas_width / source_width, canvas_height / source_height) if scale_mode == "fill" else min(canvas_width / source_width, canvas_height / source_height)
                displayed_w, displayed_h = source_width * scale, source_height * scale
                offset_x = (canvas_width - displayed_w) * (focus_x if scale_mode == "fill" else 0.5)
                offset_y = (canvas_height - displayed_h) * (focus_y if scale_mode == "fill" else 0.5)
                x_canvas = float(subtitle_style.get("custom_position_x", 50.0)) * canvas_width / 100.0
                y_canvas = float(subtitle_style.get("custom_position_y", 86.0)) * canvas_height / 100.0
                subtitle_style["custom_position_x"] = max(0.0, min(100.0, (x_canvas - offset_x) * 100.0 / displayed_w))
                subtitle_style["custom_position_y"] = max(0.0, min(100.0, (y_canvas - offset_y) * 100.0 / displayed_h))
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        signature = (video_path, source_width, source_height, repr(segments), repr(subtitle_style))
        return {
            "segments": copy.deepcopy(list(segments or [])),
            "video_width": source_width,
            "video_height": source_height,
            "style": subtitle_style,
            "signature": signature,
            "preview_dir": self.get_project_temp_dir("preview"),
        }


    def _write_subtitle_ass_from_snapshot(snapshot: dict, srt_path: str) -> str:
        """Worker-safe ASS generation.  It intentionally touches no Qt state."""
        from subtitle_builder import generate_srt
        generate_srt(snapshot["segments"], srt_path)
        style = snapshot["style"]
        return srt_to_ass(
            srt_path,
            video_width=snapshot["video_width"], video_height=snapshot["video_height"],
            alignment=style.get("alignment", 2), margin_v=style.get("margin_v", 30),
            font_name=style.get("font_name", "Arial"), font_size=style.get("font_size", 18),
            font_color=style.get("font_color", "&H00FFFFFF"), background_box=style.get("background_box", False),
            animation_style=style.get("animation", "Static"), highlight_color=style.get("highlight_color", "&H00FFFFFF"),
            outline_color=style.get("outline_color", "&H00000000"), outline_width=style.get("outline_width", 2.0),
            shadow_color=style.get("shadow_color", "&H80000000"), shadow_depth=style.get("shadow_depth", 1.0),
            background_color=style.get("background_color", "&H80000000"), background_alpha=style.get("background_alpha", 0.5),
            background_width=style.get("background_width", "fit_text"), background_shape=style.get("background_shape", "rectangle"),
            background_padding=style.get("background_padding", 6), background_radius=style.get("background_radius", 0),
            bold=style.get("bold", False), preset_key=style.get("preset_key", ""),
            auto_keyword_highlight=style.get("auto_keyword_highlight", False), animation_duration=style.get("animation_duration", 0.22),
            manual_highlights=style.get("manual_highlights", []), word_timings=style.get("word_timings", []),
            speaker_colors=style.get("speaker_colors", []), custom_position_enabled=style.get("custom_position_enabled", False),
            custom_position_x=style.get("custom_position_x", 50), custom_position_y=style.get("custom_position_y", 86),
            custom_position_bottom_y=style.get("custom_position_bottom_y"), single_line=style.get("single_line", False),
            font_scale=style.get("font_scale", 1.0), log_generation=False,
        )


    def _schedule_deferred_subtitle_ass_build(self, segments) -> bool:
        """Queue exact libass measurement after editing settles; never block UI."""
        if not self._uses_exact_full_block_subtitle_background() or not segments:
            return False
        snapshot = self._build_live_subtitle_ass_snapshot(segments)
        if snapshot["signature"] == getattr(self, "_live_preview_signature", None):
            return True
        self._subtitle_ass_request_token = int(getattr(self, "_subtitle_ass_request_token", 0)) + 1
        snapshot["token"] = self._subtitle_ass_request_token
        self._subtitle_ass_pending_snapshot = snapshot
        timer = getattr(self, "subtitle_ass_debounce_timer", None)
        if timer:
            timer.start()
        else:
            self._start_deferred_subtitle_ass_build()
        return True


    def _start_deferred_subtitle_ass_build(self):
        snapshot = getattr(self, "_subtitle_ass_pending_snapshot", None)
        if not snapshot:
            return
        self._subtitle_ass_pending_snapshot = None
        token = int(snapshot["token"])
        preview_dir = snapshot["preview_dir"]
        os.makedirs(preview_dir, exist_ok=True)
        srt_path = os.path.join(preview_dir, f"live_preview_subtitle_{token}.srt")

        def _worker():
            try:
                ass_path = self._write_subtitle_ass_from_snapshot(snapshot, srt_path)
                self.subtitle_ass_ready.emit(token, srt_path, ass_path, snapshot["signature"])
            except Exception as exc:
                self.runtime_log_received.emit(f"[Subtitle Background] Exact libass layout failed: {exc}")
                self.subtitle_ass_ready.emit(token, "", "", snapshot["signature"])

        worker = threading.Thread(target=_worker, name=f"subtitle-ass-{token}", daemon=True)
        self._subtitle_ass_worker_threads = [thread for thread in getattr(self, "_subtitle_ass_worker_threads", []) if thread.is_alive()]
        self._subtitle_ass_worker_threads.append(worker)
        worker.start()


    def _on_async_subtitle_ass_ready(self, token: int, srt_path: str, ass_path: str, signature):
        """Apply only the newest completed exact layout on the Qt thread."""
        if int(token) != int(getattr(self, "_subtitle_ass_request_token", 0)):
            return
        if not ass_path or not os.path.exists(ass_path):
            return
        self.live_preview_subtitle_path = srt_path
        self.live_preview_ass_path = ass_path
        self._live_preview_signature = signature
        self.processed_artifacts["subtitle_preview_srt"] = srt_path
        self.processed_artifacts["subtitle_preview_ass"] = ass_path
        try:
            self.media_player.set_subtitle_file(ass_path)
            self._loaded_live_ass_path = ass_path
            self._loaded_live_ass_signature = signature
            self._set_subtitle_item_text_rendering(False)
            self.update_playback_subtitle_highlight(int(self.media_player.position() or 0))
        except Exception as exc:
            self.runtime_log_received.emit(f"[Subtitle Background] Could not apply exact layout: {exc}")


    def _resolve_live_preview_subtitle_path(self):
        segments, editor_name = self._resolve_live_preview_segments()
        self.live_preview_segments = segments
        self.live_preview_editor_name = editor_name
        return self._write_live_preview_assets(segments)


    def update_playback_subtitle_highlight(self, position_ms: int):
        try:
            if not bool(getattr(self, "_subtitle_track_preview_visible", True)):
                self.timeline.set_active_segment_index(-1)
                if hasattr(self, "video_view"):
                    self.video_view.subtitle_item.hide()
                return
            segments = self.live_preview_segments or self.get_active_segments()
            active_index = self._find_active_segment_index(position_ms, segments)
            self.timeline.set_active_segment_index(active_index)
            inspector_visible = self._is_subtitle_inspector_details_visible()
            # Playback may update its last position even while paused.  Do
            # not let that stale position overwrite a subtitle the user has
            # just selected on TS1 (which commonly reset the inspector to
            # segment 1 at position 0).  Follow playback only while it is
            # actually running.
            is_playing = self._preview_is_playing()
            if is_playing and hasattr(self.timeline, "_timeline") and self.timeline._timeline:
                # Review Mode follows the active subtitle track so the
                # Subtitle Inspector can refresh with the cue under the
                # playhead. This intentionally overrides a paused edit
                # selection only while playback is running.
                subtitle_layer_id = ""
                if active_index >= 0:
                    for layer_id, segment_index in getattr(self.timeline, "_segment_indices", {}).items():
                        if int(segment_index) == int(active_index):
                            subtitle_layer_id = str(layer_id)
                            break
                if not subtitle_layer_id:
                    for track in self.timeline._timeline.tracks:
                        track_type = str(getattr(getattr(track, "type", ""), "value", getattr(track, "type", ""))).lower()
                        if track_type not in {"subtitle", "dub_subtitle"} and str(getattr(track, "name", "")) != "TS1":
                            continue
                        if track.layers:
                            subtitle_layer_id = str(getattr(track.layers[0], "id", "") or "")
                            break
                if subtitle_layer_id and str(getattr(self.timeline, "_selected_layer_id", "") or "") != subtitle_layer_id:
                    self.timeline._selected_layer_id = subtitle_layer_id
                    self.on_timeline_layer_selected(subtitle_layer_id)
            # Keep the selected TS1 cue synchronized with the playhead during
            # review playback even when the inspector was previously focused
            # on another panel.  set_selected_segment_index() updates the
            # inspector when it is visible and remains harmless otherwise.
            if is_playing and active_index >= 0 and active_index != getattr(self, "_selected_segment_index", -1):
                self.set_selected_segment_index(active_index, sync_ui=True)

            if inspector_visible:
                target_editor = None
                if self.live_preview_editor_name == "translated":
                    target_editor = self.translated_text
                elif self.live_preview_editor_name == "transcript":
                    target_editor = self.transcript_text
                elif self.current_translated_segments:
                    target_editor = self.translated_text
                elif self.current_segments:
                    target_editor = self.transcript_text

                self._set_segment_editor_highlight(active_index)
                self._set_editor_highlight(self.translated_text, active_index if target_editor is self.translated_text else -1)
                self._set_editor_highlight(self.transcript_text, active_index if target_editor is self.transcript_text else -1)

            # Update live overlay text for faster feedback
            if hasattr(self, "video_view"):
                if getattr(self, "_preview_video_has_burned_subtitles", False):
                    self.video_view.subtitle_item.set_text("")
                    if self.video_view.subtitle_item.isVisible():
                        self.video_view.subtitle_item.hide()
                else:
                    active_indices = self._find_active_segment_indices(position_ms, segments)
                    if active_indices:
                        active_lines = [segments[i].get("text", "") for i in active_indices]
                        if len(active_lines) == 1:
                            self.video_view.subtitle_item.set_text(active_lines[0])
                        else:
                            self.video_view.subtitle_item.set_lines(active_lines)
                        self._apply_live_subtitle_segment_color(segments[active_indices[0]])
                        self._set_live_subtitle_effects(segments[active_indices[0]], position_ms)
                        if not self.video_view.subtitle_item.isVisible():
                            self.video_view.subtitle_item.show()
                    else:
                        # Keep a real subtitle visible while paused so it
                        # remains a draggable editing layer after subtitle
                        # generation, even if the playhead is between cues.
                        if not self.media_player.is_playing():
                            self._show_subtitle_drag_layer(segments)
                        else:
                             self.video_view.subtitle_item.set_text("")
                             if self.video_view.subtitle_item.isVisible():
                                 self.video_view.subtitle_item.hide()
                self.video_view.reposition_subtitle()
        except Exception as exc:
            self.log(f"[Preview] subtitle highlight skipped: {exc}")


    def _show_subtitle_drag_layer(self, segments=None):
        """Show a representative live subtitle as the paused drag target."""
        if not hasattr(self, "video_view") or getattr(self, "_preview_video_has_burned_subtitles", False):
            return
        items = list(segments or self.live_preview_segments or self.get_active_segments() or [])
        if not items:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(items)):
            index = 0
        text = str(items[index].get("text", "") or "").strip()
        if not text:
            return
        self.video_view.subtitle_item.set_text(text)
        self._apply_live_subtitle_segment_color(items[index])
        self._set_live_subtitle_effects(items[index])
        self.video_view.subtitle_item.show()
        self.video_view.reposition_subtitle()


    def sync_live_subtitle_preview(self):
        """Synchronize the live subtitle renderer and draggable Qt target."""
        if not hasattr(self, "media_player"):
            return
        if not bool(getattr(self, "_subtitle_track_preview_visible", True)):
            self.media_player.clear_subtitle()
            if hasattr(self, "video_view"):
                self.video_view.subtitle_item.set_text("")
                self.video_view.subtitle_item.hide()
            return
        if getattr(self, "_preview_video_has_burned_subtitles", False):
            self.media_player.clear_subtitle()
            if hasattr(self, "video_view"):
                self.video_view.subtitle_item.set_text("")
                self.video_view.subtitle_item.hide()
            return
        can_render_libass = bool(
            getattr(self, "_use_libass_live_preview", False)
            and hasattr(self.media_player, "set_subtitle_file")
            and hasattr(self.media_player, "_sub_track_id")
        )
        if can_render_libass:
            segments, editor_name = self._resolve_live_preview_segments()
            if segments:
                self.live_preview_segments = list(segments)
                self.live_preview_editor_name = editor_name
                _srt_path, ass_path = self._write_live_preview_assets(segments)
                if ass_path and os.path.exists(ass_path):
                    # Re-adding an unchanged MPV subtitle track can briefly
                    # stall playback.  Only reload it once the final ASS path
                    # actually changes.
                    live_track_id = getattr(self.media_player, "_sub_track_id", -1)
                    has_live_mpv_track = isinstance(live_track_id, int) and live_track_id >= 0
                    if (
                        ass_path != getattr(self, "_loaded_live_ass_path", "")
                        or getattr(self, "_loaded_live_ass_signature", None) != getattr(self, "_live_preview_signature", None)
                        or not has_live_mpv_track
                    ):
                        self.media_player.set_subtitle_file(ass_path)
                        self._loaded_live_ass_path = ass_path
                        self._loaded_live_ass_signature = getattr(self, "_live_preview_signature", None)
                    self._set_subtitle_item_text_rendering(False)
                    position = int(self.media_player.position() or 0)
                    self.update_playback_subtitle_highlight(position)
                    return
            self.media_player.clear_subtitle()
            if hasattr(self, "video_view"):
                self.video_view.subtitle_item.set_text("")
                self.video_view.subtitle_item.hide()
            return
        self.media_player.clear_subtitle()
        self._set_subtitle_item_text_rendering(True)
        position = 0
        try:
            position = int(self.media_player.position())
        except Exception:
            pass
        self.update_playback_subtitle_highlight(position)


    def open_subtitle_editor(self):
        """Open the staged, bulk translated-subtitle editor.

        Unlike the small inspector editor this does not alter the project on
        every keystroke.  It makes text-only changes explicit via Update.
        """
        if not self._translation_phase_complete():
            QMessageBox.information(self, "Subtitle Editor", "Complete the Translation phase before editing translated subtitles.")
            return
        segments = list(self.current_translated_segments or [])
        if not segments:
            QMessageBox.information(
                self,
                "Subtitle Editor",
                "Translated subtitles are not available yet. Run Translate or import a translated SRT first.",
            )
            return
        editor_segments = copy.deepcopy(segments)
        # Translation artifacts can intentionally omit source_text.  The
        # source transcript remains index/timing aligned, so enrich only the
        # editor copy for display without changing project metadata.
        source_segments = list(self.current_segments or [])
        source_by_time = {
            (round(float(item.get("start", 0.0) or 0.0), 3), round(float(item.get("end", 0.0) or 0.0), 3)): item
            for item in source_segments
            if isinstance(item, dict)
        }
        for index, segment in enumerate(editor_segments):
            if not str(segment.get("source_text") or segment.get("original_text") or "").strip():
                key = (
                    round(float(segment.get("start", 0.0) or 0.0), 3),
                    round(float(segment.get("end", 0.0) or 0.0), 3),
                )
                source = source_by_time.get(key) or (source_segments[index] if index < len(source_segments) else {})
                source_text = str(source.get("text", "") or "").strip()
                if source_text:
                    segment["source_text"] = source_text
        dialog = SubtitleEditorDialog(
            self,
            editor_segments,
            self._apply_subtitle_editor_changes,
            self.run_rewrite_translation,
        )
        self._subtitle_editor_dialog = dialog
        try:
            dialog.exec()
        finally:
            if getattr(self, "_subtitle_editor_dialog", None) is dialog:
                self._subtitle_editor_dialog = None


    def _invalidate_dubbed_output_after_subtitle_edit(self):
        """Stop old TTS/mix output from being used after subtitle edits.

        Per-cue cache files deliberately remain: VoiceWorkflow keys those
        files by text, voice and speed, so unchanged cues are cache hits on
        the next TTS run.  The old assembled voice/mix is invalid because it
        still contains deleted or changed cues and must never be exported.
        """
        state = self.ensure_current_project()
        had_dubbed_output = bool(
            getattr(self, "last_voice_vi_path", "")
            or getattr(self, "last_mixed_vi_path", "")
            or self.processed_artifacts.get("voice_vi")
            or self.processed_artifacts.get("mixed_vi")
        )
        for key in ("voice_vi", "mixed_vi", "voice_segments"):
            self.processed_artifacts.pop(key, None)
            if state is not None:
                state.artifacts.pop(key, None)
        # The TS1 layer objects may still contain paths to the old assembled
        # voice track.  Clear them too so neither preview nor export can use
        # a deleted/obsolete cue before the next TTS run.
        timeline_model = getattr(getattr(self, "timeline", None), "_timeline", None)
        for track in list(getattr(timeline_model, "tracks", []) or []):
            track_type = str(getattr(getattr(track, "type", ""), "value", getattr(track, "type", ""))).lower()
            if track_type not in {"dub_subtitle", "subtitle"}:
                continue
            for layer in list(getattr(track, "layers", []) or []):
                if hasattr(layer, "audio_path"):
                    layer.audio_path = ""
                if hasattr(layer, "tts_settings"):
                    layer.tts_settings = {}
                metadata = getattr(layer, "metadata", None)
                if isinstance(metadata, dict):
                    metadata.pop("_audio_end", None)
        self.last_voice_vi_path = ""
        self.last_mixed_vi_path = ""
        if state is not None:
            state.set_step_status("generate_tts", "pending")
            state.set_step_status("mix_audio", "pending")
            state.settings.pop("voice_signature", None)
            self.project_service.save_project(state)
        if had_dubbed_output:
            self.log("[Subtitle Editor] Existing dubbed output invalidated; unchanged cues remain in the TTS cache.")
            self.sync_preview_audio_track_to_output(apply_to_player=True, force=True)


    def _apply_subtitle_editor_changes(self, rows) -> bool:
        """Apply staged content/deletion changes without rewriting cue metadata."""
        source = list(self.current_translated_segments or [])
        if len(rows or []) != len(source):
            QMessageBox.warning(self, "Subtitle Editor", "The subtitle list changed while the editor was open. Reopen it and try again.")
            return False

        updated = []
        changed_count = 0
        deleted_count = 0
        for row, original in zip(rows, source):
            if bool(row.get("deleted")):
                deleted_count += 1
                continue
            text = str(row.get("text", "") or "").strip()
            if not text:
                QMessageBox.warning(self, "Subtitle Editor", "Use Delete for an unnecessary segment instead of leaving translated text empty.")
                return False
            segment = copy.deepcopy(original)
            old_text = str(segment.get("text", "") or "").strip()
            if text != old_text:
                changed_count += 1
                segment["text"] = text
                segment["subtitle_vi"] = text
                # A changed subtitle must speak the changed text.  Do not
                # retain a manual voice override from the old sentence.
                segment["tts_text"] = ""
                segment["dubbing_vi"] = ""
                segment["voice_edited"] = False
                self._reconcile_manual_highlights(segment)
            updated.append(segment)

        if not changed_count and not deleted_count:
            return True

        self.current_translated_segments = updated
        self.current_translated_segment_models = self._dict_segments_to_models(updated, translated=True)
        self._single_line_split_cache = None
        self._voiceover_force_refresh = bool(changed_count or deleted_count)
        self._sync_hidden_translated_text_from_segments()
        self.refresh_auto_keyword_highlights(force=True)
        self.apply_segments_to_timeline()
        self._invalidate_dubbed_output_after_subtitle_edit()
        self.persist_current_timeline_project_data()
        # Keep the project-facing translated SRT in sync as well as the
        # JSON/timeline state. Export can then use the edited result without
        # relying on a later preview refresh to rewrite it incidentally.
        self._regenerate_translated_srt_from_segments()
        if not updated:
            # persist_current_timeline_project_data intentionally skips an
            # empty list. Persist an explicit empty translation artifact so
            # a project reopened after "Delete All" cannot resurrect its
            # former subtitles from translation_final.json.
            self.persist_translation_project_data([], self.last_translated_srt_path)
        self.schedule_live_subtitle_preview_refresh()
        self.schedule_auto_frame_preview()
        self.sync_segment_editor_rows()
        self.refresh_ui_state()
        self.log(
            f"[Subtitle Editor] Updated translated subtitles: changed={changed_count}, deleted={deleted_count}, unchanged={len(updated) - changed_count}."
        )
        QMessageBox.information(
            self,
            "Subtitle Editor Updated",
            f"Updated {changed_count} subtitle segment(s); deleted {deleted_count}.\n"
            "Timeline timing, speaker assignments, and styles were preserved.\n"
            "Run TTS again only if you need dubbed audio; unchanged lines reuse their cache.",
        )
        return True


    def _regenerate_translated_srt_from_segments(self):
        """Regenerate the project SRT from current_translated_segments.
        Called after the voice workflow extends a segment's end time to
        match the actual TTS audio duration, so the burned-in subtitle and
        the rendered audio stay in sync.
        """
        out_path = str(getattr(self, "last_translated_srt_path", "") or "").strip()
        if not out_path:
            return
        try:
            from subtitle_builder import generate_srt
            generate_srt(self.current_translated_segments, out_path)
        except Exception as exc:
            print(f"[Voice] SRT regen failed: {exc}")
            return
        self.processed_artifacts["srt_translated"] = out_path
        self.persist_translation_project_data(self.current_translated_segments, out_path)


    def open_subtitle_alignment_dialog(self):
        from widgets.subtitle_alignment_dialog import SubtitleAlignmentDialog
        dialog = SubtitleAlignmentDialog(
            parent=self,
            project_state=self.current_project_state,
            project_service=self.project_service,
        )
        dialog.exec()


