"""VideoFilterExportMixin: Video filters, MPV LUTs, Video Export and Runtime Logs."""
from __future__ import annotations


try:
    from main_window_parts.common_deps import *
    from main_window_parts.common_deps import _default_asr_engine
except ImportError:
    from ui.main_window_parts.common_deps import *
    from ui.main_window_parts.common_deps import _default_asr_engine



import os
import subprocess
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox


class VideoFilterExportMixin:
    """Mixin class providing video filter adjustments, MPV color presets

    and final video export workflow.
    """
    def _video_filter_presets(self):
        return {
            "original": {
                "brightness": 0,
                "contrast": 0,
                "saturation": 0,
                "temperature": 0,
                "highlights": 0,
                "shadows": 0,
            },
            "bright": {
                "brightness": 20,
                "contrast": 5,
                "saturation": 5,
                "temperature": 0,
                "highlights": -10,
                "shadows": 20,
            },
            "warm": {
                "brightness": 10,
                "contrast": 5,
                "saturation": 10,
                "temperature": 25,
                "highlights": -5,
                "shadows": 10,
            },
            "vivid": {
                "brightness": 10,
                "contrast": 20,
                "saturation": 25,
                "temperature": 0,
                "highlights": -5,
                "shadows": 5,
            },
            "cool": {
                "brightness": 0,
                "contrast": 15,
                "saturation": 5,
                "temperature": -20,
                "highlights": -10,
                "shadows": -5,
            },
            "soft": {
                "brightness": 10,
                "contrast": -12,
                "saturation": 5,
                "temperature": 10,
                "highlights": -15,
                "shadows": 15,
            },
        }
    def _video_filter_lut_map(self):
        return {
            "warm": asset_path("luts", "Portrait", "Portrait3.cube"),
            "vivid": asset_path("luts", "Color Boost", "Earth_Tone_Boost.cube"),
            "cool": asset_path("luts", "Cinematic", "Cinematic-2.cube"),
        }
    def _video_filter_fields(self):
        return ("brightness", "contrast", "saturation", "gamma", "hue", "temperature", "highlights", "shadows")
    def _clamp_video_filter_value(self, value):
        try:
            numeric = int(round(float(value)))
        except Exception:
            numeric = 0
        return max(-100, min(100, numeric))
    def _default_video_filter_overrides(self):
        return {field: 0 for field in self._video_filter_fields()}
    def _default_video_filter_modified_flags(self):
        return {field: False for field in self._video_filter_fields()}
    def _normalize_video_filter_preset_key(self, preset_key):
        key = str(preset_key or "original").strip().lower()
        return key if key in self._video_filter_presets() else "original"
    def _get_video_filter_base_values(self, preset_key=None):
        key = self._normalize_video_filter_preset_key(preset_key or self._video_filter_preset_key)
        return dict(self._video_filter_presets().get(key, self._video_filter_presets()["original"]))
    def _get_video_filter_scaled_values(self, preset_key=None, intensity=None):
        base_values = self._get_video_filter_base_values(preset_key)
        scale = max(0.0, min(100.0, float(intensity if intensity is not None else self._video_filter_intensity))) / 100.0
        return {
            field: self._clamp_video_filter_value(base_values.get(field, 0) * scale)
            for field in self._video_filter_fields()
        }
    def _get_video_filter_effective_values(self, preset_key=None, intensity=None, overrides=None, modified_flags=None):
        scaled_values = self._get_video_filter_scaled_values(preset_key, intensity)
        effective = {}
        active_overrides = overrides if overrides is not None else self._video_filter_adjust_overrides
        active_modified = modified_flags if modified_flags is not None else self._video_filter_user_modified
        for field in self._video_filter_fields():
            if active_modified.get(field, False):
                effective[field] = self._clamp_video_filter_value(active_overrides.get(field, 0))
            else:
                effective[field] = self._clamp_video_filter_value(scaled_values.get(field, 0))
        return effective
    def _refresh_video_filter_ui(self):
        if not hasattr(self, "video_filter_intensity_slider"):
            return
        self._video_filter_ui_sync = True
        try:
            for preset_key, button in getattr(self, "video_filter_preset_buttons", {}).items():
                button.setChecked(preset_key == self._normalize_video_filter_preset_key(self._video_filter_preset_key))

            self.video_filter_intensity_slider.setValue(int(self._video_filter_intensity))
            if hasattr(self, "video_filter_intensity_value_label"):
                self.video_filter_intensity_value_label.setText(str(int(self._video_filter_intensity)))

            for field, slider in getattr(self, "video_filter_adjust_sliders", {}).items():
                slider.setValue(int(self._video_filter_adjust_overrides.get(field, 0)))
                self._update_video_filter_slider_visual_state(field, slider)
            for field, label in getattr(self, "video_filter_adjust_value_labels", {}).items():
                label.setText(str(int(self._video_filter_adjust_overrides.get(field, 0))))
                is_modified = bool(self._video_filter_user_modified.get(field, False))
                label.setProperty("filterModified", is_modified)
                label.style().unpolish(label)
                label.style().polish(label)
        finally:
            self._video_filter_ui_sync = False
    def _update_video_filter_slider_visual_state(self, field, slider):
        if not slider:
            return
        is_modified = bool(self._video_filter_user_modified.get(field, False))
        if is_modified:
            slider.setStyleSheet(
                "QSlider::groove:horizontal {"
                "background: #223248; height: 6px; border-radius: 3px; }"
                "QSlider::sub-page:horizontal {"
                "background: #4ea6d8; border-radius: 3px; }"
                "QSlider::handle:horizontal {"
                "background: #8ad7ff; width: 14px; margin: -5px 0; border-radius: 7px; }"
            )
        else:
            slider.setStyleSheet("")
    def set_video_filter_state(self, preset_key="original", intensity=75, overrides=None, modified_flags=None):
        self._video_filter_preset_key = self._normalize_video_filter_preset_key(preset_key)
        self._video_filter_intensity = max(0, min(100, int(round(float(intensity)))))
        base_overrides = self._default_video_filter_overrides()
        base_modified_flags = self._default_video_filter_modified_flags()
        for field in self._video_filter_fields():
            if overrides and field in overrides:
                base_overrides[field] = self._clamp_video_filter_value(overrides[field])
            if modified_flags and field in modified_flags:
                base_modified_flags[field] = bool(modified_flags[field])
        self._video_filter_adjust_overrides = base_overrides
        self._video_filter_user_modified = base_modified_flags
        self._refresh_video_filter_ui()
        # Keep the inspector controls in sync as well.  The inspector has a
        # separate set of sliders from the legacy filter panel; previously a
        # Reset changed the underlying state but left those visible sliders at
        # their old values until the inspector was reopened.
        try:
            self._sync_video_inspector_ui()
        except Exception:
            pass
        if hasattr(self, "media_player") and self._is_realtime_color_filter_state():
            self._apply_realtime_color_filter_preview()
        self.refresh_ui_state()
    def on_video_filter_preset_selected(self, preset_key):
        if self._video_filter_ui_sync:
            return
        normalized_preset = self._normalize_video_filter_preset_key(preset_key)
        seeded_overrides = self._get_video_filter_scaled_values(normalized_preset, 75)
        self.set_video_filter_state(
            normalized_preset,
            75,
            seeded_overrides,
            self._default_video_filter_modified_flags(),
        )
        self._mark_video_filter_preview_dirty()
        self.schedule_live_video_filter_preview()
        self._persist_video_filter_settings()
    def on_video_filter_intensity_changed(self, value):
        if self._video_filter_ui_sync:
            return
        self._video_filter_intensity = max(0, min(100, int(value)))
        self._refresh_video_filter_ui()
        self.refresh_ui_state()
        self._mark_video_filter_preview_dirty()
        if not self._is_video_filter_slider_interacting():
            self.schedule_live_video_filter_preview()
        self._persist_video_filter_settings()
    def on_video_filter_adjust_changed(self, field_key, value):
        if self._video_filter_ui_sync:
            return
        normalized_field = str(field_key or "").strip().lower()
        if normalized_field not in self._video_filter_fields():
            return
        clamped_value = self._clamp_video_filter_value(value)
        scaled_value = self._get_video_filter_scaled_values().get(normalized_field, 0)
        self._video_filter_adjust_overrides[normalized_field] = clamped_value
        self._video_filter_user_modified[normalized_field] = int(clamped_value) != int(scaled_value)
        self._refresh_video_filter_ui()
        self.refresh_ui_state()
        self._mark_video_filter_preview_dirty()
        if not self._is_video_filter_slider_interacting():
            self.schedule_live_video_filter_preview()
        self._persist_video_filter_settings()
    def reset_video_filters(self):
        self.set_video_filter_state(
            "original",
            75,
            self._default_video_filter_overrides(),
            self._default_video_filter_modified_flags(),
        )
        if self._is_realtime_color_filter_state():
            self._apply_realtime_color_filter_preview()
        self._video_filter_preview_dirty = False
        self._video_filter_apply_requested = False
        if not self._is_realtime_color_filter_state():
            self.schedule_live_video_filter_preview()
        self._persist_video_filter_settings()
    def reset_video_filter_adjustments(self):
        seeded_overrides = self._get_video_filter_scaled_values(self._video_filter_preset_key, self._video_filter_intensity)
        self.set_video_filter_state(
            self._video_filter_preset_key,
            self._video_filter_intensity,
            seeded_overrides,
            self._default_video_filter_modified_flags(),
        )
        self._mark_video_filter_preview_dirty()
        self.schedule_live_video_filter_preview()
    def get_video_filter_state(self):
        base_values = self._get_video_filter_base_values()
        scaled_values = self._get_video_filter_scaled_values()
        effective_values = self._get_video_filter_effective_values()
        preset_key = self._normalize_video_filter_preset_key(self._video_filter_preset_key)
        lut_path = str(self._video_filter_lut_map().get(preset_key, "") or "").strip()
        if lut_path and not os.path.exists(lut_path):
            lut_path = ""
        lut_strength = 0.0
        if lut_path:
            lut_strength = max(0.0, min(1.0, float(self._video_filter_intensity) / 100.0))
        active = any(abs(int(value)) > 0 for value in effective_values.values()) or bool(
            lut_path and lut_strength > 0.001
        )
        return {
            "preset": preset_key,
            "intensity": int(self._video_filter_intensity),
            "base": base_values,
            "scaled": scaled_values,
            "overrides": dict(self._video_filter_adjust_overrides),
            "modified": dict(self._video_filter_user_modified),
            "final": effective_values,
            "lut_path": lut_path,
            "lut_strength": lut_strength,
            "active": active,
        }
    def has_active_video_filters(self):
        state = self.get_video_filter_state()
        active = bool(state.get("active"))
        return active
    def schedule_live_video_filter_preview(self):
        if self._is_realtime_color_filter_state():
            self._pending_video_filter_preview = False
            self._apply_realtime_color_filter_preview()
            return
        if not hasattr(self, "video_filter_preview_timer"):
            return
        self._pending_video_filter_preview = True
        if getattr(self, "_styled_preview_running", False):
            return
        self.video_filter_preview_timer.start()
    def _is_realtime_color_filter_state(self) -> bool:
        """Return whether the current state is safe for MPV live preview."""
        try:
            state = self.get_video_filter_state()
            # LUT preview is realtime only when the active MPV backend has
            # native gpu-next/libplacebo LUT support. The stable gpu backend
            # continues using the debounced FFmpeg preview path.
            if (
                state.get("lut_path")
                and float(state.get("lut_strength", 0) or 0) > 0.001
                and not bool(getattr(self.media_player, "supports_native_lut", False))
            ):
                return False
            return bool(getattr(self.media_player, "backend_name", "") == "libmpv") and hasattr(
                self.media_player, "set_color_filter_state"
            )
        except Exception:
            return False
    def _apply_realtime_color_filter_preview(self) -> bool:
        if not self._is_realtime_color_filter_state():
            return False
        try:
            source_path = self.video_path_edit.text().strip()
            if not source_path or not os.path.exists(source_path):
                return False
            current_source = str(getattr(self.media_player, "_source_path", "") or "")
            was_playing = bool(self.media_player.is_playing())
            position = int(self.media_player.position() or 0)
            if os.path.abspath(current_source) != os.path.abspath(source_path):
                self.media_player.setSource(QUrl.fromLocalFile(source_path))
                if position > 0:
                    self.media_player.setPosition(position)
                if was_playing:
                    self.media_player.play()
            self.media_player.set_color_filter_state(self.get_video_filter_state())
            self._video_filter_preview_dirty = False
            self._video_filter_apply_requested = False
            self._play_video_filter_preview_when_ready = False
            return True
        except Exception as exc:
            self.log(f"[Filter] MPV realtime preview failed: {exc}")
            return False
    def _is_video_filter_slider_interacting(self):
        sliders = [getattr(self, "video_filter_intensity_slider", None)]
        sliders.extend(list(getattr(self, "video_filter_adjust_sliders", {}).values()))
        for slider in sliders:
            if slider is not None and slider.isSliderDown():
                return True
        return False
    def on_video_filter_slider_released(self):
        self.schedule_live_video_filter_preview()
    def is_filter_workflow_active(self) -> bool:
        stack = getattr(self, "left_panel_stack", None)
        if stack is None:
            return False
        try:
            return int(stack.currentIndex()) == 4
        except Exception:
            return False
    def _mark_video_filter_preview_dirty(self):
        if self._is_realtime_color_filter_state():
            self._video_filter_preview_dirty = False
            self._video_filter_apply_requested = False
            self._apply_realtime_color_filter_preview()
            return
        self._video_filter_preview_dirty = self.has_active_video_filters()
        self._video_filter_apply_requested = False
        self.refresh_ui_state()
    def apply_current_video_filter(self):
        self.log(f"[Filter] apply_current_video_filter called, has_active={self.has_active_video_filters()}")
        if self._is_realtime_color_filter_state():
            self.log("[Filter] Applying Brightness/Contrast/Saturation through MPV realtime preview")
            self._apply_realtime_color_filter_preview()
            self.refresh_ui_state()
            return
        if not self.has_active_video_filters():
            self.log("[Filter] No active filters, returning early")
            self._video_filter_preview_dirty = False
            self._video_filter_apply_requested = False
            self.hide_filter_thumbnail_preview()
            self.refresh_ui_state()
            return
        self._video_filter_apply_requested = True
        self.refresh_ui_state()
        self.log("[Filter] Calling preview_controller.preview_video()")
        self.preview_controller.preview_video()
    def revert_video_filter_preview_to_source(self):
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        if not video_path or not os.path.exists(video_path):
            return
        self._play_video_filter_preview_when_ready = False
        self.hide_filter_thumbnail_preview()
        try:
            current_position = int(self.media_player.position())
        except Exception:
            current_position = 0
        try:
            self.media_player.pause()
        except Exception:
            pass
        try:
            self.media_player.setSource(QUrl.fromLocalFile(video_path))
            if current_position > 0:
                self.media_player.setPosition(current_position)
        except Exception:
            pass
        self.refresh_video_dimensions(video_path)
        self._preview_video_has_burned_subtitles = False
        self.sync_live_subtitle_preview()
        if hasattr(self, "timeline"):
            self.timeline.set_playing(False)
        self.refresh_ui_state()
    def _can_auto_render_filter_preview(self):
        video_path = self.video_path_edit.text().strip()
        if not video_path or not os.path.exists(video_path):
            return False
        if getattr(self, "_styled_preview_running", False) or getattr(self, "_pipeline_active", False):
            return False
        if self.has_active_video_filters():
            return True
        mode = self.get_output_mode_key()
        if mode == "subtitle":
            return bool(self.last_translated_srt_path and os.path.exists(self.last_translated_srt_path))
        if mode == "voice":
            audio_path = self.resolve_selected_audio_path()
            return bool(audio_path and os.path.exists(audio_path))
        if mode == "both":
            audio_path = self.resolve_selected_audio_path()
            return bool(
                audio_path
                and os.path.exists(audio_path)
                and self.last_translated_srt_path
                and os.path.exists(self.last_translated_srt_path)
            )
        return False
    def run_live_video_filter_preview(self):
        if self._is_realtime_color_filter_state():
            self._pending_video_filter_preview = False
            return
        if getattr(self, "_styled_preview_running", False) or getattr(self, "_frame_preview_running", False):
            return
        if not getattr(self, "_pending_video_filter_preview", False):
            return
        if not self.has_active_video_filters():
            self._pending_video_filter_preview = False
            self.hide_filter_thumbnail_preview()
            return
        if not self._can_auto_render_filter_preview():
            self._pending_video_filter_preview = False
            return
        self._pending_video_filter_preview = False
        try:
            self.preview_controller.start_exact_frame_preview(show_dialog=False)
        except Exception as exc:
            self.log(f"[Filter Preview] skipped: {exc}")
    def show_filter_thumbnail_preview(self, image_path: str):
        already_visible = bool(getattr(self, "_filter_thumbnail_visible", False))
        self._filter_thumbnail_visible = True
        if already_visible:
            self.update_frame_preview_thumbnail(image_path)
            if hasattr(self, "frame_preview_badge_label"):
                self._position_frame_preview_badge()
                self.frame_preview_badge_label.show()
            return
        self._suspend_preview_region_tools_for_filter()
        if hasattr(self, "preview_context_label"):
            self.preview_context_label.hide()
        if hasattr(self, "frame_preview_status_label"):
            self.frame_preview_status_label.hide()
        if hasattr(self, "frame_preview_image_label"):
            target_height = int(getattr(self, "_filter_thumbnail_target_height", 320) or 320)
            if hasattr(self, "video_view") and self.video_view is not None:
                live_height = int(self.video_view.height() or 0)
                if live_height > 0:
                    target_height = max(320, live_height)
            self._filter_thumbnail_target_height = target_height
            if hasattr(self.frame_preview_image_label, "setMinimumHeight"):
                self.frame_preview_image_label.setMinimumHeight(target_height)
            if hasattr(self.frame_preview_image_label, "setMaximumHeight"):
                self.frame_preview_image_label.setMaximumHeight(target_height)
            self.frame_preview_image_label.show()
        if hasattr(self, "video_view"):
            self.video_view.hide()
        self._force_hide_ocr_overlay_for_filter()
        self.update_frame_preview_thumbnail(image_path)
        if hasattr(self, "frame_preview_badge_label"):
            self._position_frame_preview_badge()
            self.frame_preview_badge_label.show()
        QTimer.singleShot(0, self._force_hide_ocr_overlay_for_filter)
    def hide_filter_thumbnail_preview(self):
        self._filter_thumbnail_visible = False
        if hasattr(self, "frame_preview_badge_label"):
            self.frame_preview_badge_label.hide()
        if hasattr(self, "frame_preview_image_label"):
            if hasattr(self.frame_preview_image_label, "setMinimumHeight"):
                self.frame_preview_image_label.setMinimumHeight(0)
            if hasattr(self.frame_preview_image_label, "setMaximumHeight"):
                self.frame_preview_image_label.setMaximumHeight(16777215)
            if hasattr(self.frame_preview_image_label, "clear_frame_image"):
                self.frame_preview_image_label.clear_frame_image()
            self.frame_preview_image_label.hide()
        if hasattr(self, "frame_preview_status_label"):
            self.frame_preview_status_label.hide()
        if hasattr(self, "preview_context_label"):
            self.preview_context_label.hide()
        if hasattr(self, "video_view"):
            self.video_view.show()
        self._restore_preview_region_tools_after_filter()
    def _suspend_preview_region_tools_for_filter(self):
        self._suspend_ocr_overlay = True
        self._filter_preview_blur_was_checked = bool(
            hasattr(self, "blur_area_btn") and self.blur_area_btn.isChecked()
        )
        overlay = getattr(self, "ocr_region_overlay", None)
        self._filter_preview_ocr_was_editable = bool(getattr(overlay, "_editable", False)) if overlay is not None else False

        if hasattr(self, "blur_area_btn"):
            self.blur_area_btn.setEnabled(False)
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_blur_edit_enabled"):
            self.video_view.set_blur_edit_enabled(False)
        if overlay is not None:
            overlay.set_editable(False)
            overlay.hide()
    def _force_hide_ocr_overlay_for_filter(self):
        if not bool(getattr(self, "_filter_thumbnail_visible", False)):
            return
        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is not None:
            overlay.set_editable(False)
            overlay.hide()
    def _restore_preview_region_tools_after_filter(self):
        self._suspend_ocr_overlay = False
        if hasattr(self, "blur_area_btn"):
            self.blur_area_btn.setEnabled(True)
        self._sync_blur_controls()

        overlay = getattr(self, "ocr_region_overlay", None)
        if overlay is not None:
            self._update_ocr_overlay()
            if (
                bool(getattr(self, "_filter_preview_ocr_was_editable", False))
                and os.getenv("TRANSCRIPTION_ENGINE", _default_asr_engine()).strip().lower() == "ocr"
            ):
                overlay.set_editable(True)
                overlay.sync_to_view()
    def _on_video_inspector_preset_changed(self, index: int):
        if not hasattr(self, "video_inspector_preset_combo"):
            return
        try:
            key = self.video_inspector_preset_combo.itemData(index)
            if not key:
                return
            self.on_video_filter_preset_selected(str(key))
        except Exception:
            pass
        # When the preset changes, the base values for each adjust
        # field change too. Refresh the slider UI so the user can see
        # what the new preset looks like at the current intensity.
        self._sync_video_inspector_ui()
        self._refresh_video_inspector_status()
        if hasattr(self, "refresh_ui_state"):
            self.refresh_ui_state()
    def _video_filter_inspector_available(self) -> bool:
        """Return whether the initialized preview backend supports realtime filters."""
        backend = getattr(self, "media_player", None)
        if backend is None or str(getattr(backend, "backend_name", "")) != "libmpv":
            return False
        if not bool(getattr(backend, "_gpu_next_enabled", False)):
            return False
        try:
            vo = backend._player.vo
            return any(
                str(item.get("name", "")) == "gpu-next"
                for item in (vo or [])
                if isinstance(item, dict)
            )
        except Exception:
            return False
    def _persist_video_filter_settings(self):
        """Persist realtime filter controls without requiring an Apply action."""
        try:
            self.save_user_settings()
        except Exception as exc:
            self.log(f"[Filter] Could not persist filter settings: {exc}")
    def export_final_video(self):
        self.preview_controller.export_final_video()
    def on_export_progress(self, percent: int, message: str):
        dlg = self._ensure_export_progress_dialog()
        if dlg is None:
            return
        message_text = str(message or "Exporting final video...").strip() or "Exporting final video..."
        history = list(getattr(self, "_export_progress_messages", []) or [])
        if not history or history[-1] != message_text:
            history.append(message_text)
        self._export_progress_messages = history[-4:]
        dlg.setLabelText("Exporting final video...\n\n" + "\n".join(self._export_progress_messages))
        if percent is None or int(percent) < 0:
            dlg.setRange(0, 0)
        else:
            if dlg.maximum() == 0:
                dlg.setRange(0, 100)
            value = max(0, min(100, int(percent)))
            dlg.setValue(value)
            try:
                self.progress_bar.setValue(value)
            except Exception:
                pass
        dlg.show()
    def on_export_finished(self, output_path, error):
        self.preview_controller.on_export_finished(output_path, error)
    def _ensure_export_progress_dialog(self):
        dlg = getattr(self, "export_progress_dialog", None)
        if dlg is not None:
            return dlg
        dlg = BackgroundableProgressDialog("Preparing final export...", "Hide", 0, 100, self)
        dlg.setWindowTitle("Exporting Video")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoReset(False)
        dlg.setAutoClose(False)
        dlg.setMinimumWidth(520)
        dlg.setValue(0)
        dlg.setLabelText("Exporting final video...\n\nWaiting to start...")
        dlg.setStyleSheet(
            "QProgressDialog { background-color: #101826; color: #e6eef9; }"
            "QLabel { color: #e6eef9; background: transparent; }"
            "QPushButton { background-color: #24364f; color: #ffffff; border: 1px solid #335171; border-radius: 10px; padding: 8px 14px; font-weight: 700; }"
            "QPushButton:hover { background-color: #2d4665; border-color: #4575a8; }"
            "QProgressBar { border: 1px solid #2a3a50; border-radius: 10px; text-align: center; background-color: #111927; color: white; min-height: 16px; }"
            "QProgressBar::chunk { background-color: #4ed0b3; border-radius: 10px; }"
        )
        try:
            dlg.setCancelButtonText("Run in background")
            dlg.canceled.connect(dlg.hide)
        except Exception:
            pass
        self.export_progress_dialog = dlg
        self._register_progress_dialog(dlg)
        dlg.show()
        return dlg
    def _close_export_progress_dialog(self):
        try:
            dlg = getattr(self, "export_progress_dialog", None)
            if dlg is not None:
                self._unregister_progress_dialog(dlg)
                dlg.hide()
                dlg.deleteLater()
        finally:
            self.export_progress_dialog = None
    def export_runtime_logs(self):
        default_name = f"capcap_logs_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        default_path = os.path.join(self.workspace_root, default_name)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Runtime Logs",
            default_path,
            "Text Files (*.txt);;All Files (*)",
        )
        if not file_path:
            return
        try:
            self._flush_runtime_log_entries()
            with open(file_path, "w", encoding="utf-8") as handle:
                entries = getattr(self, "_runtime_logs", [])
                handle.write("\n".join(entries))
                handle.write("\n" if entries else "")
            self.log(f"[Logs] Exported runtime logs to {file_path}")
        except OSError as exc:
            QMessageBox.warning(self, "Export Logs", f"Could not export logs:\n{exc}")
