"""MediaPlaybackMixin: Media player controls, Timeline manipulation, Audio waveform, Thumbnails and Frame preview."""

try:
    from main_window_parts.common_deps import *
except ImportError:
    from ui.main_window_parts.common_deps import *


from typing import Any, Dict, List, Optional
import os
import json
import logging

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QPushButton, QSlider, QProgressBar, QLabel, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox, QTabWidget, QSplitter, QScrollArea, QFrame, QDialog,
    QApplication, QFileDialog, QMessageBox, QWidget, QMenu
)

logger = logging.getLogger(__name__)


class MediaPlaybackMixin:
    """Mixin containing media playback, playhead sync, timeline segment/layer actions, and waveforms."""
    def format_timestamp(self, seconds):
        return format_timestamp(seconds)


    def _format_compact_editor_timestamp(self, seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        minutes, sec = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{sec:02d}"
        return f"{minutes:02d}:{sec:02d}"


    def _nudge_playhead(self, delta_s: float):
        focus = QApplication.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return
        current_t = float(getattr(getattr(self, "timeline", None), "_playhead", 0.0))
        new_t = max(0.0, current_t + delta_s)
        if hasattr(self, "timeline"):
            self.timeline.set_playhead(new_t)
        if hasattr(self, "set_position"):
            self.set_position(int(new_t * 1000))


    def setup_media_player(self):
        if getattr(self, "_media_backend_ready", False):
            return
        previous_speed = getattr(self, "_preview_speed", 1.0)
        setup_media_player_impl(self)
        self._preview_speed = previous_speed
        self._media_backend_ready = True
        if hasattr(self, "media_player"):
            try:
                self.media_player.set_playback_rate(previous_speed)
            except Exception:
                pass


    def toggle_play(self):
        toggle_play_impl(self)


    def position_changed(self, position):
        position_changed_impl(self, position)


    def set_position(self, position):
        set_position_impl(self, position)


    def refresh_play_button_icon(self):
        """Update the play button icon + tooltip to reflect the current
        media player state (playing vs paused). Called from
        position_changed when playback ends naturally so the button
        switches from the pause icon back to the play icon."""
        if not hasattr(self, "play_btn"):
            return
        playing = False
        try:
            playing = bool(self.media_player.is_playing())
        except Exception:
            playing = False
        play_icon = "pause.svg" if playing else "play.svg"
        play_tip = "Pause preview" if playing else "Play preview"
        try:
            self.play_btn.setIcon(load_icon(asset_path("icons", play_icon), 18))
            self.play_btn.setToolTip(play_tip)
        except Exception:
            pass
        if hasattr(self, "blur_area_btn"):
            blur_active = bool(self.blur_area_btn.isChecked())
            self.blur_area_btn.setToolTip("Blur effect on" if blur_active else "Turn blur effect on or off")
        if hasattr(self, "preview_speed_combo"):
            target = float(getattr(self, "_preview_speed", 1.0))
            index = self.preview_speed_combo.findData(target)
            if index >= 0 and self.preview_speed_combo.currentIndex() != index:
                self.preview_speed_combo.blockSignals(True)
                self.preview_speed_combo.setCurrentIndex(index)
                self.preview_speed_combo.blockSignals(False)
        if hasattr(self, "preview_audio_track_combo"):
            combo = self.preview_audio_track_combo
            entries = self._preview_audio_track_choices()
            current_mode = str(getattr(self, "_preview_audio_track_mode", "both") or "both").strip().lower()
            if current_mode == "dubbed" and not any(value == "dubbed" for _label, value in entries):
                current_mode = "both"
                self._preview_audio_track_mode = "both"
            existing = [(combo.itemText(i), str(combo.itemData(i) or "")) for i in range(combo.count())]
            if existing != entries:
                combo.blockSignals(True)
                combo.clear()
                for label, value in entries:
                    combo.addItem(label, value)
                combo.blockSignals(False)
            target_index = combo.findData(current_mode)
            if target_index < 0:
                target_index = 0
            if combo.currentIndex() != target_index:
                combo.blockSignals(True)
                combo.setCurrentIndex(target_index)
                combo.blockSignals(False)
            combo.setEnabled(combo.count() > 1 and getattr(self, "media_player", None) is not None and getattr(self.media_player, "backend_name", "") == "libmpv")


    def _preview_is_playing(self) -> bool:
        # The timeline keeps an explicit review/edit state synchronized from
        # the media-state callback. Prefer it here: native backends can report
        # a transient PlayingState while a pause/seek event is still being
        # delivered, which used to disable range actions immediately after a
        # range was created.
        timeline = getattr(self, "timeline", None)
        if timeline is not None and hasattr(timeline, "_playing"):
            return bool(getattr(timeline, "_playing", False))
        try:
            return bool(self.media_player.is_playing())
        except Exception:
            return False


    def _sync_preview_framing_to_player(self):
        """Keep native MPV crop framing consistent with the preview canvas."""
        view = getattr(self, "video_view", None)
        player = getattr(self, "media_player", None)
        if view is None or player is None or not hasattr(player, "set_preview_framing"):
            return
        try:
            source_w = float(getattr(view, "video_source_width", 0) or 0)
            source_h = float(getattr(view, "video_source_height", 0) or 0)
            canvas = view.get_preview_canvas_rect()
            source_ratio = source_w / source_h if source_w > 0 and source_h > 0 else 0.0
            canvas_ratio = canvas.width() / canvas.height() if canvas.height() > 0 else source_ratio
            focus_x, focus_y = self.get_output_fill_focus()
            player.set_preview_framing(
                source_ratio,
                canvas_ratio,
                self.get_output_scale_mode_key(),
                focus_x,
                focus_y,
            )
        except Exception as exc:
            self.log(f"[Preview] Could not sync canvas framing: {exc}")


    def schedule_auto_frame_preview(self):
        if not bool(getattr(self, "_allow_post_pipeline_preview_assets", False)):
            return
        if not hasattr(self, "auto_preview_frame_cb") or not self.auto_preview_frame_cb.isChecked():
            return
        if self.auto_preview_frame_cb.isHidden():
            return
        if getattr(self, "_pipeline_active", False):
            return
        if not self.video_path_edit.text().strip() or not self.get_active_segments():
            return
        self.frame_preview_status_label.setText("Refreshing exact frame preview...")
        self.auto_frame_preview_timer.start()


    def trigger_auto_frame_preview(self):
        self.start_exact_frame_preview(show_dialog=False)


    def schedule_seek_frame_preview(self):
        if not bool(getattr(self, "_allow_post_pipeline_preview_assets", False)):
            return
        if not hasattr(self, "auto_preview_frame_cb") or not self.auto_preview_frame_cb.isChecked():
            return
        if self.auto_preview_frame_cb.isHidden():
            return
        if getattr(self, "_pipeline_active", False):
            return
        if self.media_player.is_playing():
            return
        if not self.video_path_edit.text().strip() or not self.get_active_segments():
            return
        self.frame_preview_status_label.setText("Updating exact frame preview for the selected timeline position...")
        self.seek_frame_preview_timer.start()


    def trigger_seek_frame_preview(self):
        if self.media_player.is_playing():
            return
        self.start_exact_frame_preview(show_dialog=False)


    def update_frame_preview_thumbnail(self, image_path: str):
        widget = getattr(self, "frame_preview_image_label", None)
        if widget is not None and hasattr(widget, "set_frame_image"):
            if hasattr(self, "video_view") and self.video_view is not None:
                widget.set_video_dimensions(
                    int(getattr(self.video_view, "video_source_width", 0) or 0),
                    int(getattr(self.video_view, "video_source_height", 0) or 0),
                )
                widget.set_preview_aspect_ratio(getattr(self.video_view, "preview_aspect_key", "source"))
                widget.set_preview_scale_mode(getattr(self.video_view, "preview_scale_mode", "fit"))
                focus_x, focus_y = self.get_output_fill_focus()
                widget.set_preview_fill_focus(focus_x, focus_y)
            widget.set_frame_image(image_path)
            return
        update_frame_preview_thumbnail_impl(self, image_path, QPixmap, Qt)


    def _position_frame_preview_badge(self):
        badge = getattr(self, "frame_preview_badge_label", None)
        if badge is None:
            return
        host = None
        if getattr(self, "_filter_thumbnail_visible", False):
            host = getattr(self, "frame_preview_image_label", None)
        if host is None or not host.isVisible():
            host = getattr(self, "video_view", None)
        if host is None:
            return
        badge.adjustSize()
        content_rect = None
        if hasattr(host, "get_video_content_rect"):
            try:
                content_rect = host.get_video_content_rect()
            except Exception:
                content_rect = None
        if content_rect is not None and content_rect.width() > 0 and content_rect.height() > 0:
            x = host.x() + content_rect.right() - badge.width() - 14
            y = host.y() + content_rect.top() + 14
        else:
            x = host.x() + max(12, host.width() - badge.width() - 14)
            y = host.y() + 14
        badge.move(int(x), int(y))
        badge.raise_()


    def preview_exact_frame(self):
        self.preview_controller.start_exact_frame_preview(show_dialog=True)


    def on_exact_frame_ready(self, output_path, error):
        self.preview_controller.on_exact_frame_ready(output_path, error)


    def show_frame_preview_dialog(self, image_path: str):
        show_frame_preview_dialog_impl(self, image_path, QPixmap, Qt)


    def resolve_timeline_audio_visualization_path(self) -> str:
        preview_mode = str(getattr(self, "_preview_audio_track_mode", "original") or "original").strip().lower()
        if preview_mode == "original":
            candidates = [
                self.audio_source_edit.text().strip() if hasattr(self, "audio_source_edit") else "",
                self.processed_artifacts.get("vocals"),
                self.processed_artifacts.get("audio_extracted"),
                self.last_vocals_path,
                self.last_extracted_audio,
            ]
            for candidate in candidates:
                normalized = self._normalize_local_file_path(candidate)
                if normalized and os.path.exists(normalized):
                    return normalized

        dubbed_audio_kind, dubbed_audio = self._resolve_preview_dubbed_playback_source()
        if dubbed_audio_kind in ("mixed", "voice") and dubbed_audio and os.path.exists(dubbed_audio):
            return dubbed_audio

        candidates = [
            self.audio_source_edit.text().strip() if hasattr(self, "audio_source_edit") else "",
            self.processed_artifacts.get("vocals"),
            self.processed_artifacts.get("audio_extracted"),
            self.last_vocals_path,
            self.last_extracted_audio,
        ]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return normalized
        return ""


    def _waveform_temp_path(self) -> str:
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        if not video_path:
            return ""
        video_hash = hashlib.md5(video_path.encode("utf-8")).hexdigest()[:12]
        return os.path.join(self.get_workspace_temp_root(create=True), f"waveform_{video_hash}.wav")


    def _timeline_waveform_request_signature(self):
        # A1 represents the source video's original audio. It must remain
        # stable as Transcript/Translate/TTS change project artifacts.
        video_path = self._normalize_local_file_path(self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else "")
        if video_path and os.path.exists(video_path):
            try:
                stat = os.stat(video_path)
                return (
                    "v4-source-video-envelope",
                    os.path.abspath(video_path),
                    int(stat.st_size),
                    int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
                )
            except Exception:
                return ("v4-source-video-envelope", os.path.abspath(video_path), 0, 0)
        return None


    def _timeline_thumbnail_request_signature(self):
        video_path = self._normalize_local_file_path(self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else "")
        duration_s = max(0.0, float(getattr(self.timeline, "duration", 0) or 0) / 1000.0) if hasattr(self, "timeline") else 0.0
        if not video_path or not os.path.exists(video_path) or duration_s <= 0.0:
            return None
        try:
            stat = os.stat(video_path)
            return (
                "v5-timeline-thumbnails",
                os.path.abspath(video_path),
                int(stat.st_size),
                int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
                int(round(duration_s)),
            )
        except Exception:
            return ("v5-timeline-thumbnails", os.path.abspath(video_path), 0, 0, int(round(duration_s)))


    def _load_launcher_timeline_visual_cache(self):
        """Return static V1/A1 data prepared by the launcher, if valid."""
        video_path = self._normalize_local_file_path(
            self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        )
        if not video_path or not os.path.exists(video_path):
            return None
        try:
            stat = os.stat(video_path)
            source_abs = os.path.abspath(video_path)
            cache_dir = os.path.join(self.get_workspace_temp_root(create=True), "timeline_visuals")
            digest = hashlib.md5(source_abs.encode("utf-8")).hexdigest()[:12]
            manifest_path = os.path.join(cache_dir, f"{digest}.json")
            candidates = [manifest_path]
            # A packaged build can be launched with a copied video (for
            # example, the same file moved from media/ to Downloads).  The
            # launcher cache is still reusable in that case, but its
            # path-based digest no longer matches.  Fall back to a manifest
            # with the same filename and byte size, while retaining the
            # normal exact path/mtime validation as the first choice.
            if os.path.isdir(cache_dir):
                candidates.extend(
                    path for path in glob.glob(os.path.join(cache_dir, "*.json"))
                    if path != manifest_path
                )
            for candidate in candidates:
                try:
                    with open(candidate, "r", encoding="utf-8") as handle:
                        data = json.load(handle)
                except (OSError, ValueError, TypeError):
                    continue
                exact = (
                    data.get("source") == source_abs
                    and int(data.get("size", -1)) == int(stat.st_size)
                    and int(data.get("mtime_ns", -1)) == int(getattr(stat, "st_mtime_ns", 0))
                )
                compatible_copy = (
                    os.path.basename(str(data.get("source", ""))).lower()
                    == os.path.basename(source_abs).lower()
                    and int(data.get("size", -1)) == int(stat.st_size)
                )
                if exact or compatible_copy:
                    return data
            return None
        except (OSError, ValueError, TypeError):
            return None


    def refresh_timeline_waveform(self):
        if not hasattr(self, "timeline"):
            return
        request_signature = self._timeline_waveform_request_signature()
        if not request_signature:
            self._desired_timeline_waveform_request = None
            self._timeline_waveform_cache_key = None
            self._timeline_waveform_samples = []
            self._timeline_waveform_duration_s = 0.0
            self.timeline.set_waveform_data([], 0.0)
            return

        if not hasattr(self, "_timeline_waveform_dict_cache"):
            self._timeline_waveform_dict_cache = {}
        if request_signature in self._timeline_waveform_dict_cache:
            samples, dur_s = self._timeline_waveform_dict_cache[request_signature]
            self._desired_timeline_waveform_request = request_signature
            self._timeline_waveform_cache_key = request_signature
            self._timeline_waveform_samples = samples
            self._timeline_waveform_duration_s = dur_s
            self.timeline.set_waveform_data(samples, dur_s)
            return

        launcher_cache = self._load_launcher_timeline_visual_cache()
        if launcher_cache and launcher_cache.get("waveform"):
            self._desired_timeline_waveform_request = request_signature
            self._timeline_waveform_cache_key = request_signature
            self._timeline_waveform_samples = list(launcher_cache.get("waveform") or [])
            self._timeline_waveform_duration_s = max(0.0, float(launcher_cache.get("duration_s") or 0.0))
            self._timeline_waveform_dict_cache[request_signature] = (self._timeline_waveform_samples, self._timeline_waveform_duration_s)
            self.timeline.set_waveform_data(
                self._timeline_waveform_samples, self._timeline_waveform_duration_s
            )
            return
        self._desired_timeline_waveform_request = request_signature
        if self._timeline_waveform_cache_key == request_signature:
            self.timeline.set_waveform_data(
                self._timeline_waveform_samples, self._timeline_waveform_duration_s
            )
            return
        worker = self._timeline_waveform_worker
        if worker is not None and worker.isRunning():
            if getattr(worker, "request_signature", None) == request_signature:
                return
            try:
                worker.cancel()
            except Exception:
                pass
            self._timeline_waveform_worker = None
        video_path = self._normalize_local_file_path(
            self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        )
        worker = TimelineWaveformWorker(
            request_signature, video_path, "", self._waveform_temp_path()
        )
        worker.finished.connect(self._on_timeline_waveform_ready)
        self._timeline_waveform_worker = worker
        worker.start()


    def _on_timeline_waveform_ready(self, request_signature, waveform, duration_s, error):
        self._timeline_waveform_worker = None
        if request_signature != self._desired_timeline_waveform_request:
            self.refresh_timeline_waveform()
            return
        if not hasattr(self, "_timeline_waveform_dict_cache"):
            self._timeline_waveform_dict_cache = {}
        if error:
            print(f"[Timeline] waveform generation failed: {error}")
            self._timeline_waveform_cache_key = request_signature
            self._timeline_waveform_samples = []
            self._timeline_waveform_duration_s = 0.0
        else:
            self._timeline_waveform_cache_key = request_signature
            self._timeline_waveform_samples = list(waveform or [])
            self._timeline_waveform_duration_s = max(0.0, float(duration_s or 0.0))
            self._timeline_waveform_dict_cache[request_signature] = (
                self._timeline_waveform_samples,
                self._timeline_waveform_duration_s,
            )
            print(
                f"[Timeline] waveform generated: samples={len(self._timeline_waveform_samples)} "
                f"duration={self._timeline_waveform_duration_s:.1f}s"
            )
        if hasattr(self, "timeline"):
            self.timeline.set_waveform_data(self._timeline_waveform_samples, self._timeline_waveform_duration_s)


    def schedule_timeline_visual_refresh(self, *, waveform: bool = True, thumbnails: bool = True, delay_ms: int = 250):
        # V1/A1 visuals are tied only to the source media, not to a pipeline
        # stage. They are static cached assets and may be prepared as soon as
        # a video is opened.
        if waveform:
            self._pending_timeline_waveform_refresh = True
        if thumbnails:
            self._pending_timeline_thumbnail_refresh = True
        timer = getattr(self, "_timeline_visual_refresh_timer", None)
        if timer is None:
            self._run_pending_timeline_visual_refresh()
            return
        timer.start(max(0, int(delay_ms)))


    def _run_pending_timeline_visual_refresh(self):
        refresh_waveform = bool(getattr(self, "_pending_timeline_waveform_refresh", False))
        refresh_thumbnails = bool(getattr(self, "_pending_timeline_thumbnail_refresh", False))
        self._pending_timeline_waveform_refresh = False
        self._pending_timeline_thumbnail_refresh = False
        if refresh_waveform:
            self.refresh_timeline_waveform()
        if refresh_thumbnails:
            self.refresh_timeline_video_thumbnails()


    def refresh_timeline_video_thumbnails(self):
        if not hasattr(self, "timeline"):
            return
        request_signature = self._timeline_thumbnail_request_signature()
        if not request_signature:
            self._timeline_video_thumb_cache_key = None
            self._timeline_video_thumbnails = []
            self._desired_timeline_thumbnail_request = None
            self.timeline.set_video_thumbnails([])
            return

        if not hasattr(self, "_timeline_thumbnail_dict_cache"):
            self._timeline_thumbnail_dict_cache = {}
        if request_signature in self._timeline_thumbnail_dict_cache:
            pixmaps = self._timeline_thumbnail_dict_cache[request_signature]
            self._desired_timeline_thumbnail_request = request_signature
            self._timeline_video_thumb_cache_key = request_signature
            self._timeline_video_thumbnails = pixmaps
            self.timeline.set_video_thumbnails(pixmaps)
            return

        launcher_cache = self._load_launcher_timeline_visual_cache()
        if launcher_cache and launcher_cache.get("thumbnails"):
            pixmaps = []
            for timestamp_s, output_path in launcher_cache.get("thumbnails"):
                pixmap = QPixmap(str(output_path or ""))
                if not pixmap.isNull():
                    pixmaps.append((float(timestamp_s), pixmap))
            if pixmaps:
                self._desired_timeline_thumbnail_request = request_signature
                self._timeline_video_thumb_cache_key = request_signature
                self._timeline_video_thumbnails = pixmaps
                self._timeline_thumbnail_dict_cache[request_signature] = pixmaps
                self.timeline.set_video_thumbnails(pixmaps)
                return
        self._desired_timeline_thumbnail_request = request_signature
        if self._timeline_video_thumb_cache_key == request_signature:
            self.timeline.set_video_thumbnails(self._timeline_video_thumbnails)
            return
        worker = self._timeline_thumbnail_worker
        if worker is not None and worker.isRunning():
            if getattr(worker, "request_signature", None) == request_signature:
                return
            try:
                worker.cancel()
            except Exception:
                pass
            self._timeline_thumbnail_worker = None
        video_path = self._normalize_local_file_path(self.video_path_edit.text().strip())
        duration_s = max(0.0, float(self.timeline.duration or 0) / 1000.0)
        thumb_dir = os.path.join(self.get_workspace_temp_root(create=True), "timeline_thumbnails")
        worker = TimelineThumbnailWorker(request_signature, video_path, duration_s, thumb_dir)
        worker.finished.connect(self._on_timeline_video_thumbnails_ready)
        self._timeline_thumbnail_worker = worker
        worker.start()


    def _on_timeline_video_thumbnails_ready(self, request_signature, thumbnails, error):
        self._timeline_thumbnail_worker = None
        if request_signature != self._desired_timeline_thumbnail_request:
            self.refresh_timeline_video_thumbnails()
            return
        if not hasattr(self, "_timeline_thumbnail_dict_cache"):
            self._timeline_thumbnail_dict_cache = {}
        if error:
            print(f"[Timeline] thumbnail generation failed: {error}")
            self._timeline_video_thumb_cache_key = request_signature
            self._timeline_video_thumbnails = []
        else:
            pixmaps = []
            for timestamp_s, output_path in list(thumbnails or []):
                pixmap = QPixmap(str(output_path or ""))
                if not pixmap.isNull():
                    pixmaps.append((float(timestamp_s), pixmap))
            self._timeline_video_thumb_cache_key = request_signature
            self._timeline_video_thumbnails = pixmaps
            self._timeline_thumbnail_dict_cache[request_signature] = pixmaps
        if hasattr(self, "timeline"):
            self.timeline.set_video_thumbnails(self._timeline_video_thumbnails)


    def persist_current_timeline_project_data(self):
        state = self.ensure_current_project()
        if not state:
            return
        if self.current_segments:
            self.current_segment_models = self.project_bridge.persist_transcription(
                state,
                self.current_segments,
                self.last_original_srt_path,
            )
        if self.current_translated_segments:
            self.current_translated_segment_models = self.project_bridge.persist_translation(
                state,
                self.current_segment_models,
                self.current_translated_segments,
                self.last_translated_srt_path,
            )
            signature = self.build_current_translation_signature()
            if signature:
                state.set_setting("translation_signature", signature)
        if self.current_project_state:
            voice_signature = self.build_current_voice_signature(
                segments=self._get_voiceover_segments(),
                background_path=self.resolve_background_audio_path(),
            )
            if voice_signature:
                state.set_setting("voice_signature", voice_signature)

        # These states belong to the project editor view.  The track-label
        # widget itself is rebuilt on startup, so it cannot be their source
        # of truth.
        state.set_setting("preview_track_visibility", {
            "TS1": bool(getattr(self, "_subtitle_track_preview_visible", True)),
            "T1 Text": bool(getattr(self, "_text_track_preview_visible", True)),
            "L1 Logo": bool(getattr(self, "_logo_track_preview_visible", True)),
            "M1": bool(getattr(self, "_mask_track_preview_visible", True)),
            "B1": bool(self._blur_effect_enabled()),
        })
        state.set_setting("subtitle_style_controls", self._current_subtitle_style_controls_state())
        
        # Save timeline data (includes mask and logo layers)
        if hasattr(self, "timeline") and self.timeline._timeline:
            import json
            timeline_data = self.timeline._timeline.to_dict()
            # Save timeline to a file in the project directory
            timeline_path = os.path.join(state.project_root, "timeline", "timeline.json")
            os.makedirs(os.path.dirname(timeline_path), exist_ok=True)
            with open(timeline_path, "w", encoding="utf-8") as f:
                json.dump(timeline_data, f, ensure_ascii=False, indent=2)
            state.set_artifact("timeline", timeline_path)
            # Selection Range is an ephemeral editing aid. Never restore it
            # when reopening a project, where an old range can be confusing.
            state.settings.pop("timeline_selection_range", None)
        
        self.project_service.save_project(state)


    def schedule_timeline_project_persist(self, *, mask_state=False, blur_state=False):
        """Coalesce persistence requested by high-frequency editor events.

        Preview geometry is updated by the callers immediately.  Only the
        disk-backed project/timeline write is delayed, which prevents drag
        operations and text typing from blocking the Qt event loop.
        """
        self._pending_timeline_persist = True
        self._pending_mask_state_persist = self._pending_mask_state_persist or bool(mask_state)
        self._pending_blur_state_persist = self._pending_blur_state_persist or bool(blur_state)
        timer = getattr(self, "_timeline_persist_timer", None)
        if timer is not None:
            timer.start()
        else:
            self._flush_pending_timeline_persist()


    def _flush_pending_timeline_persist(self):
        """Write coalesced editor changes once after an edit burst ends."""
        if not getattr(self, "_pending_timeline_persist", False):
            return
        save_mask = self._pending_mask_state_persist
        save_blur = self._pending_blur_state_persist
        self._pending_timeline_persist = False
        self._pending_mask_state_persist = False
        self._pending_blur_state_persist = False
        try:
            if save_mask:
                self.persist_project_mask_state()
            if save_blur:
                self.persist_project_blur_state()
            self.persist_current_timeline_project_data()
        except Exception:
            # Preserve existing best-effort persistence behavior: a save
            # failure must not interrupt editing or leave the timer running.
            pass


    def _cache_core_timeline_tracks_only(self):
        """Keep only V1, A1, and TS1 when a video session is closed.

        Optional editing tracks remain fully usable (and exportable) during
        the active session. They are deliberately not retained in the
        reopen cache, preventing Blur/Logo/Mask/Text tracks from following
        a video into its next editing session.
        """
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        # Music is a first-class project audio track, so retain it alongside
        # the source and generated-voice tracks when the editor session is
        # cached/reopened.
        core_track_names = {"V1 Video", "A1 Audio", "TS1", "A2 Music"}
        timeline = self.timeline._timeline
        removed = [track for track in timeline.tracks if track.name not in core_track_names]
        if removed:
            timeline.tracks = [track for track in timeline.tracks if track.name in core_track_names]
            for track in removed:
                self.timeline._track_heights.pop(track.id, None)
            selected_id = str(getattr(self.timeline, "_selected_layer_id", "") or "")
            retained_ids = {layer.id for track in timeline.tracks for layer in track.layers}
            if selected_id not in retained_ids:
                self.timeline._selected_layer_id = ""
            self.timeline._redraw()
            self.persist_current_timeline_project_data()
        state = getattr(self, "current_project_state", None)
        if state is not None:
            # Blur and mask also have legacy settings fallbacks. Clear those
            # cache entries so they cannot recreate optional tracks on load.
            state.set_setting("blur_state", {"enabled": False, "regions": []})
            state.set_setting("mask_state", {"enabled": False, "regions": []})
            self.project_service.save_project(state)
        if removed:
            self.log(f"[Timeline Cache] Retained core tracks only; discarded {len(removed)} optional track(s).")


    def _restore_saved_timeline_model(self, state) -> bool:
        """Restore the complete editor timeline, including optional layers.

        The project bridge restores transcript artifacts, but those artifacts
        only describe the core subtitle data.  Text/Logo/Blur/Mask tracks are
        persisted separately in ``timeline/timeline.json`` and must be loaded
        before the subtitle sync rebuilds TS1; otherwise reopening a project
        silently drops the optional tracks from the in-memory model.
        """
        timeline = getattr(self, "timeline", None)
        if timeline is None:
            return False
        artifacts = getattr(state, "artifacts", {}) or {}
        timeline_path = str(artifacts.get("timeline", "") or "").strip()
        if not timeline_path:
            timeline_path = os.path.join(state.project_root, "timeline", "timeline.json")
        timeline_path = self._normalize_local_file_path(timeline_path)
        if not timeline_path or not os.path.isfile(timeline_path):
            return False
        try:
            import json
            from app.layers.timeline import Timeline

            with open(timeline_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            loaded = Timeline.from_dict(saved)
            if not loaded.tracks:
                return False

            timeline._timeline = loaded
            # Track visibility toggles are an editor-view concern, not part
            # of the serialized project model.  Do not let hidden IDs from a
            # previous project affect the restored tracks.
            timeline._timeline_hidden_track_ids.clear()
            # The source/video duration is refreshed later by set_video_source;
            # retain the saved duration until then so optional layer geometry
            # can be drawn immediately during project restoration.
            timeline._duration = max(
                float(getattr(timeline, "_duration", 0.0) or 0.0),
                float(getattr(loaded, "duration", 0.0) or 0.0),
            )
            timeline._track_heights = {
                str(track.id): int(getattr(track, "height", timeline.TRACK_DEFAULT_H))
                for track in loaded.tracks
            }
            timeline._segment_indices.clear()
            timeline._overlap_layout_cache.clear()
            timeline._overlap_row_assignments.clear()
            timeline._redraw()
            self.log(
                f"[Timeline] Restored {len(loaded.tracks)} saved track(s) "
                f"from {timeline_path}"
            )
            return True
        except Exception as exc:
            self.log(f"[Timeline] Could not restore saved timeline: {exc}")
            return False


    def ripple_delete_selected_timeline_segment(self):
        focus = QApplication.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return
        if self._preview_is_playing():
            return
        segments = list(self.get_active_segments() or [])
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(segments)):
            self.delete_selected_timeline_segment()
            return
        target = segments[index]
        dur = max(0.0, float(target.get("end", 0.0)) - float(target.get("start", 0.0)))
        # Xóa segment hiện tại
        self.delete_selected_timeline_segment()
        # Co các segment phía sau lại
        if dur > 0.01:
            for s_list in (getattr(self, "current_segments", None), getattr(self, "current_translated_segments", None)):
                if s_list and 0 <= index < len(s_list):
                    for seg in s_list[index:]:
                        seg["start"] = max(0.0, float(seg.get("start", 0.0)) - dur)
                        seg["end"] = max(seg["start"] + 0.1, float(seg.get("end", 0.0)) - dur)
            if hasattr(self, "apply_segments_to_timeline"):
                self.apply_segments_to_timeline()
            if hasattr(self, "persist_current_timeline_project_data"):
                self.persist_current_timeline_project_data()


    def on_timeline_segment_timing_edit_started(self, index: int, start: float, end: float):
        if self._suspend_timeline_undo:
            return
        last_entry = self._timeline_timing_undo_stack[-1] if self._timeline_timing_undo_stack else None
        if last_entry and str(last_entry.get("type", "timing")) == "timing" and int(last_entry.get("index", -1)) == int(index):
            if abs(float(last_entry.get("start", 0.0)) - float(start)) < 0.0001 and abs(float(last_entry.get("end", 0.0)) - float(end)) < 0.0001:
                return
        self._timeline_timing_undo_stack.append(
            {
                "type": "timing",
                "index": int(index),
                "start": float(start),
                "end": float(end),
            }
        )
        self._timeline_timing_redo_stack = []
        if len(self._timeline_timing_undo_stack) > 100:
            self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
        self._refresh_timeline_history_buttons()


    def on_timeline_segment_selected(self, index: int):
        self.set_selected_segment_index(index, sync_ui=False)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(index)


    def _layer_is_active_at_preview_time(self, layer, time_seconds=None) -> bool:
        """Return whether a layer should be visible at the current playhead."""
        if not bool(getattr(layer, "visible", True)):
            return False
        if time_seconds is None:
            try:
                time_seconds = float(self.media_player.position()) / 1000.0
            except Exception:
                time_seconds = 0.0
        start = max(0.0, float(getattr(layer, "start", 0.0) or 0.0))
        end = float(getattr(layer, "end", 0.0) or 0.0)
        # Legacy layers without a valid duration continue to be visible.
        return end <= start or (start <= float(time_seconds) < end)


    def refresh_timed_layer_preview(self, position_ms=None) -> None:
        """Show only overlay layers whose timeline interval contains the playhead."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        time_seconds = float(position_ms if position_ms is not None else self.media_player.position()) / 1000.0
        tracked = []
        for track in self.timeline._timeline.tracks:
            for layer in track.layers:
                layer_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower()
                is_logo = layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo"
                if layer_type in {"blur", "mask", "text"} or is_logo:
                    tracked.append((layer.id, self._layer_is_active_at_preview_time(layer, time_seconds)))
        signature = tuple(tracked)
        if signature == getattr(self, "_timed_layer_preview_signature", None):
            return
        self._timed_layer_preview_signature = signature
        selected_id = str(getattr(self.timeline, "_selected_layer_id", "") or "")

        # Text layers are rendered independently, so filtering their payload
        # makes them disappear/reappear without changing their saved state.
        self._refresh_text_layer_preview(selected_id)

        for track in self.timeline._timeline.tracks:
            if str(getattr(track, "name", "")) == "L1 Logo":
                # The L1 header Hide/Show state is independent from playback
                # and timing.  Do not let a timed refresh recreate a hidden
                # logo when playback advances or resumes.
                if not bool(getattr(self, "_logo_track_preview_visible", True)):
                    if hasattr(self.video_view, "clear_logo"):
                        self.video_view.clear_logo()
                    continue
                active = [l for l in track.layers if self._layer_is_active_at_preview_time(l, time_seconds)]
                if active:
                    is_selected_logo = (
                        selected_id in {l.id for l in active}
                        and selected_id == str(getattr(self, "_preview_edit_layer_id", "") or "")
                        and not self._preview_is_playing()
                    )
                    target = next((l for l in active if l.id == selected_id), active[0])
                    self._show_logo_overlay(track, target, editable=is_selected_logo)
                elif hasattr(self.video_view, "clear_logo"):
                    self.video_view.clear_logo()
            elif str(getattr(track, "name", "")) == "M1":
                active_layers = [l for l in track.layers if self._layer_is_active_at_preview_time(l, time_seconds)]
                # Keep the selected region in the editor overlay, but remove
                # only that one layer from the expensive rendered effect
                # while it is being edited on a paused frame.
                overlay_regions = self._current_mask_regions_payload(time_seconds=time_seconds)
                suppressed_id = self._deferred_effect_layer_id_for("mask")
                effect_regions = self._current_mask_regions_payload(
                    time_seconds=time_seconds, exclude_layer_id=suppressed_id,
                )
                if hasattr(self.video_view, "set_mask_regions"):
                    active_index = next((i for i, l in enumerate(active_layers) if l.id == selected_id), 0)
                    self.video_view.set_mask_regions(
                        overlay_regions,
                        active_index=active_index,
                        editable=bool(
                            active_layers
                            and selected_id in {l.id for l in active_layers}
                            and selected_id == str(getattr(self, "_preview_edit_layer_id", "") or "")
                            and self._deferred_effect_layer_id_for("mask") == selected_id
                            and not self._preview_is_playing()
                        ),
                    )
                # The mask effect is independent of selection/edit handles.
                # Keep it applied when the preview is paused as well.
                self._apply_mask_to_preview(regions=effect_regions)
            elif str(getattr(track, "name", "")) == "B1":
                overlay_regions = []
                active_layers = [l for l in track.layers if self._layer_is_active_at_preview_time(l, time_seconds)]
                for layer in active_layers:
                    overlay_regions.append({
                        "x": float(getattr(layer, "position_x", 0.0)), "y": float(getattr(layer, "position_y", 0.0)),
                        "width": float(getattr(layer, "width", 0.0)), "height": float(getattr(layer, "height", 0.0)),
                        "blur_strength": float(getattr(layer, "blur_strength", 20.0)),
                        "blur_opacity": float(getattr(layer, "blur_opacity", 1.0)),
                        "pixelate": bool(getattr(layer, "pixelate", False)),
                        "pixelate_size": int(getattr(layer, "pixelate_size", 12)),
                    })
                if hasattr(self.video_view, "set_blur_regions_normalized"):
                    self.video_view.set_blur_regions_normalized(overlay_regions)
                if hasattr(self.video_view, "set_blur_edit_enabled"):
                    # B1's effect remains rendered, but its border/handles
                    # are shown only while a B1 layer is selected and the
                    # preview is paused.
                    is_selected_blur = selected_id in {l.id for l in active_layers}
                    try:
                        is_playing = bool(self.media_player.is_playing())
                    except Exception:
                        is_playing = False
                    self.video_view.set_blur_edit_enabled(bool(
                        is_selected_blur
                        and selected_id == str(getattr(self, "_preview_edit_layer_id", "") or "")
                        and self._deferred_effect_layer_id_for("blur") == selected_id
                        and not is_playing
                        and self._blur_effect_enabled()
                    ))
                # Blur has a separate MPV filter in addition to its editable
                # outline. Update that filter with the same time-filtered
                # regions; otherwise a filter applied at playback start
                # continues blurring after the outline has disappeared.
                suppressed_id = self._deferred_effect_layer_id_for("blur")
                effect_regions = [
                    region for region, layer in zip(overlay_regions, active_layers)
                    if str(getattr(layer, "id", "")) != suppressed_id
                ]
                self.apply_preview_blur_region(regions=effect_regions)

        # Rebuild both managed effect payloads once from the complete active
        # timeline after all overlay bookkeeping. This is the authoritative
        # multi-layer path: one selected layer may be suppressed, but every
        # other active Blur/Mask layer is always included.
        suppressed_mask_id = self._deferred_effect_layer_id_for("mask")
        self._apply_mask_to_preview(
            regions=self._current_mask_regions_payload(
                time_seconds=time_seconds,
                exclude_layer_id=suppressed_mask_id,
            )
        )
        blur_effect_regions = []
        suppressed_blur_id = self._deferred_effect_layer_id_for("blur")
        for track in self.timeline._timeline.tracks:
            if str(getattr(track, "name", "")) != "B1":
                continue
            for layer in track.layers:
                if not self._layer_is_active_at_preview_time(layer, time_seconds):
                    continue
                if str(getattr(layer, "id", "") or "") == suppressed_blur_id:
                    continue
                blur_effect_regions.append({
                    "x": float(getattr(layer, "position_x", 0.0)),
                    "y": float(getattr(layer, "position_y", 0.0)),
                    "width": float(getattr(layer, "width", 0.0)),
                    "height": float(getattr(layer, "height", 0.0)),
                    "blur_strength": float(getattr(layer, "blur_strength", 20.0)),
                    "blur_opacity": float(getattr(layer, "blur_opacity", 1.0)),
                    "pixelate": bool(getattr(layer, "pixelate", False)),
                    "pixelate_size": int(getattr(layer, "pixelate_size", 12)),
                })
        self.apply_preview_blur_region(regions=blur_effect_regions)


    def on_timeline_layer_timing_changed(self, layer_id: str, start: float, end: float):
        """Persist timeline-handle duration edits for all non-subtitle layers."""
        if self._preview_is_playing():
            return
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        for track in self.timeline._timeline.tracks:
            for layer in track.layers:
                if layer.id != layer_id:
                    continue
                if bool(getattr(layer, "locked", False)):
                    return
                layer_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower()
                is_logo = layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo"
                if layer_type not in {"blur", "mask", "text"} and not is_logo:
                    return
                layer.start = max(0.0, float(start))
                layer.end = max(layer.start + float(getattr(self.timeline, "MIN_DUR", 0.1)), float(end))
                self.persist_current_timeline_project_data()
                self._timed_layer_preview_signature = None
                self.refresh_timed_layer_preview()
                if layer_type == "mask":
                    self._apply_mask_to_preview(
                        regions=self._current_mask_regions_payload(include_inactive=True)
                    )
                # Refresh the visible inspector values while keeping its
                # layer-specific visual controls and preview selection intact.
                self.on_timeline_layer_selected(layer_id)
                return


    def on_timeline_layer_selected(self, layer_id: str):
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        track = None
        layer = None
        for t in self.timeline._timeline.tracks:
            for l in t.layers:
                if l.id == layer_id:
                    layer = l
                    track = t
                    break
            if layer:
                break
        # The subtitle overlay should only capture the mouse when a concrete
        # subtitle segment (TS1/S1) is selected in the timeline.  Otherwise
        # it stays click-through, preventing accidental moves while editing
        # other video layers.
        is_review_mode = self._preview_is_playing()
        if hasattr(self, "video_view") and hasattr(self.video_view, "subtitle_item"):
            layer_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower() if layer else ""
            self.video_view.subtitle_item.set_editable(
                not is_review_mode and layer_type in {"subtitle", "dub_subtitle"}
            )
        # During review mode a layer may still be inspected/focused, but it
        # must never acquire preview drag handles. A real paused selection is
        # the only entry point into preview editing.
        self._preview_edit_layer_id = "" if is_review_mode else str(layer_id or "")
        # Selection changes are the commit boundary for deferred Blur/Mask
        # geometry. Selecting a Blur/Mask while paused starts a new light-
        # weight edit session; selecting anything else restores the old one.
        self._set_deferred_effect_edit_target(track, layer)
        if not layer:
            self._show_default_inspector()
            # Deselecting a layer only removes edit chrome. Effects and
            # rendered layer content remain visible in the preview.
            self._timed_layer_preview_signature = None
            self.refresh_timed_layer_preview()
            return
        # A selection must respect timing immediately, including before the
        # next playback positionChanged signal is emitted.
        self._timed_layer_preview_signature = None
        self.refresh_timed_layer_preview()
        layer_type = str(getattr(layer.type, "value", layer.type)).lower()
        can_modify_layer = not bool(getattr(track, "locked", False)) and not bool(getattr(layer, "locked", False))
        if hasattr(self, "timeline_split_btn"):
            self.timeline_split_btn.setEnabled(
                not is_review_mode and can_modify_layer and (layer_type in {"subtitle", "dub_subtitle", "blur", "mask", "text"}
                or (layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo")
                )
            )
        if hasattr(self, "timeline_split_sentences_btn"):
            self.timeline_split_sentences_btn.setEnabled(
                not is_review_mode and can_modify_layer and (layer_type in {"subtitle", "dub_subtitle"})
            )
        if hasattr(self, "timeline_delete_btn"):
            self.timeline_delete_btn.setEnabled(not is_review_mode and can_modify_layer)
        if layer_type == "subtitle":
            self._show_subtitle_inspector_for_layer(layer_id)
        elif layer_type == "dub_subtitle":
            self._show_dub_subtitle_inspector_for_layer(layer_id, layer)
        elif layer_type == "audio":
            if str(getattr(track, "name", "")) != "A1 Audio":
                self._show_audio_inspector_for_track(track, layer)
        elif layer_type == "blur":
            self._show_blur_inspector_for_track(track, layer)
        elif layer_type == "video":
            self._show_video_inspector_for_track(track, layer)
        elif layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo":
            self._show_logo_overlay(track, layer)
            self._show_logo_inspector_for_track(track, layer)
        elif layer_type == "mask" or str(getattr(track, "name", "")) == "M1":
            self._show_mask_overlay(track, layer)
            self._show_mask_inspector_for_track(track, layer)
        elif layer_type == "text":
            self._show_text_inspector_for_track(track, layer)
            self._refresh_text_layer_preview(layer.id)
        else:
            # Image, sticker: show default with info
            self._show_default_inspector_for_layer(track, layer)
            # Do not clear unrelated visual layers when changing inspector
            # panels. Their effects are independent of selection.
            self._timed_layer_preview_signature = None
            self.refresh_timed_layer_preview()


    def on_add_timeline_layer(self, layer_type: str = "subtitle"):
        if not hasattr(self, "timeline"):
            return
        if self._preview_is_playing():
            return

        if layer_type in {"blur", "logo", "mask", "text", "image", "sticker"} and not bool(
            getattr(self, "_optional_layer_controls_ready", False)
        ):
            QMessageBox.information(
                self,
                "Generate Video First",
                "Complete video generation before adding Blur, Logo, Mask, Text, or other overlay layers.",
            )
            return

        tl = self.timeline._timeline
        if not tl:
            return

        from app.layers.base import LayerType
        from app.layers.sync_bridge import find_or_create_track

        if layer_type == "subtitle":
            # TS1 is driven from the segment lists, not the legacy Subtitle
            # track. Insert at the playhead so the normal timeline, preview,
            # editor, export and project persistence paths all stay aligned.
            try:
                start = max(0.0, float(self.media_player.position()) / 1000.0)
            except Exception:
                start = 0.0
            duration = max(0.0, float(getattr(tl, "duration", 0.0) or 0.0))
            end = start + 2.0
            if duration > 0.0:
                end = min(end, duration)
                if end - start < 0.20:
                    start = max(0.0, end - 2.0)
            if end - start < 0.05:
                end = start + 2.0

            translated_exists = bool(getattr(self, "current_translated_segments", None))
            if not hasattr(self, "current_segments") or self.current_segments is None:
                self.current_segments = []
            if not hasattr(self, "current_translated_segments") or self.current_translated_segments is None:
                self.current_translated_segments = []

            active_segments = self.current_translated_segments if translated_exists else self.current_segments
            index = next(
                (idx for idx, segment in enumerate(active_segments)
                 if float(segment.get("start", 0.0) or 0.0) > start),
                len(active_segments),
            )
            source_segment = {"start": start, "end": end, "text": "New subtitle", "words": []}
            translated_segment = {
                "start": start,
                "end": end,
                "text": "New subtitle",
                "source_text": "New subtitle",
                "tts_text": "New subtitle",
                "provider": "manual",
            }
            history_entry = {
                "type": "insert",
                "index": int(index),
                "selected_before": int(getattr(self, "_selected_segment_index", -1)),
                "selected_after": int(index),
                "current_before": [],
                "current_after": [copy.deepcopy(source_segment)],
                "translated_before": [],
                "translated_after": [copy.deepcopy(translated_segment)] if translated_exists else [],
            }
            self.current_segments.insert(min(index, len(self.current_segments)), source_segment)
            if translated_exists:
                self.current_translated_segments.insert(min(index, len(self.current_translated_segments)), translated_segment)
            # Segment insertion changes the source index mapping used by the
            # optional one-line display cache, so always rebuild it from the
            # current project data.
            self._single_line_split_cache = None
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            if translated_exists:
                self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
                self._sync_hidden_translated_text_from_segments()
            self._sync_hidden_transcript_text_from_segments()
            self._timeline_timing_undo_stack.append(history_entry)
            self._timeline_timing_redo_stack = []
            if len(self._timeline_timing_undo_stack) > 100:
                self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
            self._refresh_timeline_history_buttons()
            self.set_selected_segment_index(index, sync_ui=True)
            self.timeline.set_active_segment_index(index)
            self.apply_segments_to_timeline()
            self.persist_current_timeline_project_data()
            self.schedule_live_subtitle_preview_refresh()
            self.refresh_ui_state()
            self.show_subtitle_inspector_details()
            self.log(f"[Subtitle] Added manual TS1 segment at {start:.2f}s.")
            return

        elif layer_type == "text":
            from app.layers.text import TextLayer
            text_track = find_or_create_track(tl, "T1 Text", LayerType.TEXT, 80)
            idx = len(text_track.layers)
            layer = TextLayer(
                name=f"Text {idx + 1}",
                text="New text layer",
                start=0.0,
                end=tl.duration if tl.duration > 0 else 10.0,
            )
            layer.font_size = 60
            # Match the subtitle defaults so identical Text/Subtitles size
            # values use the same family and weight out of the box.
            layer.font_name = "Segoe UI"
            layer.font_bold = True
            layer.transform.x = 0.5
            layer.transform.y = 0.5
            layer.z_index = idx
            text_track.layers.append(layer)
            if hasattr(self.timeline, "_track_heights"):
                self.timeline._track_heights[text_track.id] = text_track.height or 80
            self.timeline._redraw()
            self.timeline._selected_layer_id = layer.id
            self._show_text_inspector_for_track(text_track, layer)
            self._refresh_text_layer_preview(layer.id)

        elif layer_type == "image":
            from app.layers.image import ImageLayer
            img_track = find_or_create_track(tl, "I1 Image", LayerType.IMAGE, 80)
            idx = len(img_track.layers)
            layer = ImageLayer(
                name=f"Image {idx + 1}",
                source="",
                start=0.0,
                end=min(tl.duration, 10.0) if tl.duration > 0 else 10.0,
            )
            layer.z_index = idx
            img_track.layers.append(layer)
            self.timeline._redraw()

        elif layer_type == "logo":
            from app.layers.image import ImageLayer
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Logo / Watermark Image", "",
                "Images (*.png *.jpg *.jpeg *.bmp *.gif *.svg);;All Files (*)"
            )
            if not path:
                return
            img_track = find_or_create_track(tl, "L1 Logo", LayerType.IMAGE, 80)
            # L1 supports multiple independent logo layers.  Keep existing
            # layers intact; selecting a timeline layer determines which
            # logo is currently editable in the preview overlay.
            idx = len(img_track.layers)
            dur = tl.duration if tl.duration > 0 else 10.0
            layer = ImageLayer(
                name=f"Logo {idx + 1}",
                source=path,
                start=0.0,
                end=dur,
            )
            layer.z_index = idx
            # Mark as watermark so the preview positions it correctly
            layer.metadata["_is_watermark"] = True
            img_track.layers.append(layer)
            # Register the new track's height in the timeline so it gets
            # a real draw slot.
            if hasattr(self.timeline, "_track_heights"):
                self.timeline._track_heights[img_track.id] = (
                    img_track.height or 80
                )
            self.timeline._redraw()
            # Show the logo overlay immediately (no need to click the
            # layer first) and persist the logo state.
            try:
                self._show_logo_overlay(img_track, layer)
            except Exception:
                pass

        elif layer_type == "blur":
            from app.layers.blur import BlurLayer
            blur_track = find_or_create_track(tl, "B1", LayerType.BLUR, 60)
            # Register the new track's height in the timeline so it gets a
            # real draw slot (otherwise the track silently uses the default
            # height and may not be visible).
            if hasattr(self.timeline, "_track_heights"):
                self.timeline._track_heights[blur_track.id] = (
                    blur_track.height or 60
                )
            idx = len(blur_track.layers)
            # Stagger each new blur layer slightly so all layers are
            # visible in the timeline (otherwise overlapping layers at
            # the same position hide each other).
            stagger = idx % 4
            base_y = 0.75 - stagger * 0.06
            base_x = 0.30 + (stagger % 2) * 0.08
            # New Blur layers are global by default.  Their geometry can be
            # narrowed later in the inspector/timeline, but creating one must
            # not unexpectedly limit it to a five-second window at the
            # current playhead.
            blur_start = 0.0
            blur_end = float(tl.duration) if float(getattr(tl, "duration", 0.0) or 0.0) > 0.0 else 10.0
            layer = BlurLayer(
                name=f"Blur {idx + 1}",
                position_x=float(base_x),
                position_y=float(base_y),
                width=0.4,
                height=0.1,
                blur_strength=20.0,
                start=blur_start,
                end=blur_end,
            )
            layer.z_index = idx
            blur_track.layers.append(layer)
            # Force a redraw so the new track + layer are visible.
            self.timeline._redraw()
            # Auto-scroll the timeline vertically so the new B1
            # track is in view (it sits below V1 + A1 by default).
            try:
                if hasattr(self.timeline, "verticalScrollBar"):
                    y_offset = 0
                    if hasattr(self.timeline, "RULER_HEIGHT"):
                        y_offset = int(self.timeline.RULER_HEIGHT)
                    for tr in tl.tracks:
                        if tr.id == blur_track.id:
                            break
                        y_offset += int(
                            self.timeline._track_heights.get(
                                tr.id, self.timeline.TRACK_DEFAULT_H
                            )
                        )
                    bar = self.timeline.verticalScrollBar()
                    # Make sure the scroll bar range reflects the new scene
                    # size (it is normally auto-sized by the QGraphicsView,
                    # but the range can lag on first update).
                    viewport_h = int(self.timeline.viewport().height())
                    scene_h = int(self.timeline._scene.height())
                    bar.setRange(0, max(0, scene_h - viewport_h))
                    # Center the B1 track in the viewport
                    target = max(0, y_offset - max(0, (viewport_h - 80) // 2))
                    bar.setValue(target)
                    # Make sure the new layer is fully visible too.
                    self.timeline.ensureVisible(
                        0,
                        y_offset,
                        1,
                        int(self.timeline._track_heights.get(
                            blur_track.id, 60
                        )),
                    )
            except Exception:
                pass
            # Auto-enable the blur effect so the visual blur shows on the
            # video preview the moment the layer is added.
            if hasattr(self, "blur_area_btn"):
                self.blur_area_btn.blockSignals(True)
                self.blur_area_btn.setChecked(True)
                self.blur_area_btn.blockSignals(False)
            # Push the new region's normalized data into the video view
            # and force the mpv vf filter to be applied immediately.
            try:
                regions = []
                for ll in blur_track.layers:
                    if not getattr(ll, "visible", True):
                        continue
                    regions.append({
                        "x": float(getattr(ll, "position_x", 0.3)),
                        "y": float(getattr(ll, "position_y", 0.8)),
                        "width": float(getattr(ll, "width", 0.4)),
                        "height": float(getattr(ll, "height", 0.1)),
                        "blur_strength": float(getattr(ll, "blur_strength", 20.0)),
                    })
                if hasattr(self.video_view, "set_blur_regions_normalized"):
                    self.video_view.set_blur_regions_normalized(regions)
                # The Add Layer menu bypasses the legacy Blur button, so it
                # must explicitly enable the editable overlay.  Merely
                # checking blur_area_btn does not emit its toggled signal.
                if hasattr(self.video_view, "set_blur_edit_enabled"):
                    self.video_view.set_blur_edit_enabled(True)
                if hasattr(self.video_view, "set_blur_active_index"):
                    self.video_view.set_blur_active_index(idx)
                if hasattr(self, "apply_preview_blur_region"):
                    self.apply_preview_blur_region(force=True)
            except Exception:
                pass
            # Persist the new region(s) to the project state so they
            # survive a close/reopen. Without this, the blur_state is
            # only saved on the legacy blur add/edit handlers, and a
            # region added via the new "Blur" button would be lost.
            try:
                if hasattr(self, "persist_project_blur_state"):
                    self.persist_project_blur_state()
            except Exception:
                pass
            try:
                self.timeline._selected_layer_id = layer.id
                # Route newly-created layers through the same paused
                # selection path as existing B1 layers. This starts the
                # deferred edit session and removes only this layer's
                # rendered effect while its geometry is edited.
                self.on_timeline_layer_selected(layer.id)
            except Exception:
                pass

        elif layer_type == "mask":
            from app.layers.mask import MaskLayer
            mask_track = find_or_create_track(tl, "M1", LayerType.MASK, 60)
            if hasattr(self.timeline, "_track_heights"):
                self.timeline._track_heights[mask_track.id] = (
                    mask_track.height or 60
                )
            idx = len(mask_track.layers)
            # Position default mask as a slim horizontal bar near the bottom
            # perfectly suited for covering original hardcoded video subtitles (like a subtitle banner)
            stagger = idx % 4
            layer = MaskLayer(
                name=f"Mask {idx + 1}",
                position_x=0.05,
                position_y=max(0.70, 0.84 - (stagger * 0.03)),
                width=0.90,
                height=0.08,
                color="#000000",
                mode="solid",
                pixelate_size=12,
                blur_strength=20,
                start=0.0,
                # Span the full timeline so the mask track is visible
                # across the whole video (like the audio track layers),
                # not a short 5-second segment.
                end=tl.duration if tl.duration > 0 else 5.0,
            )
            layer.z_index = idx
            # Visibility is gated by the play state in
            # _apply_mask_to_preview: the mask filter is only pushed
            # to mpv while the video is playing, so a freshly added
            # mask does not draw on the paused preview.
            mask_track.layers.append(layer)
            self.timeline._redraw()
            # Push the new mask into the mpv filter chain and persist
            # it so the export matches the preview.
            try:
                self._apply_mask_to_preview()
            except Exception:
                pass
            try:
                if hasattr(self, "persist_project_mask_state"):
                    self.persist_project_mask_state()
            except Exception:
                pass
            # Select the new mask layer so the inspector opens with
            # the right settings loaded.
            try:
                self.timeline._selected_layer_id = layer.id
                self.timeline._redraw()
                # Use the normal paused-layer selection path so the new M1
                # layer gets the same deferred effect/edit-handle behavior
                # as a layer selected after reopening a project.
                self.on_timeline_layer_selected(layer.id)
            except Exception:
                pass
        
        # Save timeline data (includes mask and logo layers)
        try:
            self.persist_current_timeline_project_data()
        except Exception:
            pass


    def _timeline_neighbor_bounds(self, index: int):
        active_segments = list(self.get_active_segments() or [])
        prev_end = 0.0
        next_start = max(0.0, float(getattr(self.timeline, "duration", 0)) / 1000.0)
        if index > 0 and index - 1 < len(active_segments):
            prev_end = float(active_segments[index - 1].get("end", 0.0))
        if index + 1 < len(active_segments):
            next_start = float(active_segments[index + 1].get("start", next_start))
        return prev_end, next_start


    def nudge_selected_timeline_segment(self, delta_seconds: float):
        segments = list(self.get_active_segments() or [])
        if not segments:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(segments)):
            index = self._find_active_segment_index(self.media_player.position(), segments)
        if not (0 <= index < len(segments)):
            return

        target = segments[index]
        start = float(target.get("start", 0.0))
        end = float(target.get("end", 0.0))
        duration = max(0.0, end - start)
        gap = float(getattr(self.timeline, "SEGMENT_GAP", 0.03))
        prev_end, next_start = self._timeline_neighbor_bounds(index)
        max_timeline = max(0.0, float(getattr(self.timeline, "duration", 0)) / 1000.0)
        min_start = max(0.0, prev_end + gap)
        if index + 1 < len(segments):
            max_start = max(min_start, next_start - gap - duration)
        else:
            max_start = max(0.0, max_timeline - duration)
        new_start = min(max(start + float(delta_seconds), min_start), max_start)
        if abs(new_start - start) < 0.0001:
            return
        new_end = new_start + duration
        self.on_timeline_segment_timing_edit_started(index, start, end)
        self.on_timeline_segment_timing_changed(index, new_start, new_end)


    def ripple_nudge_selected_timeline_segment(self, delta_seconds: float):
        segments = list(self.get_active_segments() or [])
        if not segments:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        if not (0 <= index < len(segments)):
            index = self._find_active_segment_index(self.media_player.position(), segments)
        if not (0 <= index < len(segments)):
            return

        gap = float(getattr(self.timeline, "SEGMENT_GAP", 0.0))
        max_timeline = max(0.0, float(getattr(self.timeline, "duration", 0)) / 1000.0)
        prev_end, _next_start = self._timeline_neighbor_bounds(index)
        first_start = float(segments[index].get("start", 0.0))
        last_end = float(segments[-1].get("end", 0.0))
        min_delta = max(0.0, prev_end + gap) - first_start
        max_delta = max_timeline - last_end
        actual_delta = min(max(float(delta_seconds), min_delta), max_delta)
        if abs(actual_delta) < 0.0001:
            return

        history_entry = {
            "type": "batch_timing",
            "index": int(index),
            "selected_before": int(index),
            "selected_after": int(index),
            "current_before": [],
            "current_after": [],
            "translated_before": [],
            "translated_after": [],
        }

        if 0 <= index < len(self.current_segments or []):
            history_entry["current_before"] = [copy.deepcopy(seg) for seg in self.current_segments[index:]]
            for seg in self.current_segments[index:]:
                self._apply_segment_timing(
                    seg,
                    float(seg.get("start", 0.0)) + actual_delta,
                    float(seg.get("end", 0.0)) + actual_delta,
                )
            history_entry["current_after"] = [copy.deepcopy(seg) for seg in self.current_segments[index:]]
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            self._sync_hidden_transcript_text_from_segments()

        if 0 <= index < len(self.current_translated_segments or []):
            history_entry["translated_before"] = [copy.deepcopy(seg) for seg in self.current_translated_segments[index:]]
            for seg in self.current_translated_segments[index:]:
                self._apply_segment_timing(
                    seg,
                    float(seg.get("start", 0.0)) + actual_delta,
                    float(seg.get("end", 0.0)) + actual_delta,
                )
            history_entry["translated_after"] = [copy.deepcopy(seg) for seg in self.current_translated_segments[index:]]
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()

        # A derived single-line cache is indexed against the pre-edit
        # subtitle list.  Reusing it after a delete can redraw a segment
        # which has just been removed, especially when a new segment is
        # inserted at the same point in the timeline.
        self._single_line_split_cache = None

        self._timeline_timing_undo_stack.append(history_entry)
        self._timeline_timing_redo_stack = []
        if len(self._timeline_timing_undo_stack) > 100:
            self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
        self._refresh_timeline_history_buttons()

        self.set_selected_segment_index(index, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(index)
        self.apply_segments_to_timeline()
        # Write the edited lists even if a deletion leaves one of them
        # empty.  The generic persistence method deliberately avoids empty
        # lists during initial project setup, so explicitly replace the
        # existing segment artifacts here to prevent a deleted segment from
        # being restored from disk or project cache later in this session.
        state = getattr(self, "current_project_state", None)
        if state is not None:
            try:
                self.current_segment_models = self.project_bridge.persist_transcription(
                    state, self.current_segments or [], self.last_original_srt_path
                )
                if self.current_translated_segments is not None:
                    self.current_translated_segment_models = self.project_bridge.persist_translation(
                        state,
                        self.current_segment_models,
                        self.current_translated_segments or [],
                        self.last_translated_srt_path,
                    )
            except Exception as exc:
                self.log(f"[Subtitle] Could not update deleted segment cache: {exc}")
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()


    def _apply_timeline_structure_history_entry(self, entry: dict, *, use_after: bool):
        index = int(entry.get("index", -1))
        current_before = [copy.deepcopy(seg) for seg in list(entry.get("current_before", []) or [])]
        current_after = [copy.deepcopy(seg) for seg in list(entry.get("current_after", []) or [])]
        translated_before = [copy.deepcopy(seg) for seg in list(entry.get("translated_before", []) or [])]
        translated_after = [copy.deepcopy(seg) for seg in list(entry.get("translated_after", []) or [])]

        if self.current_segments is not None:
            replace_with = current_after if use_after else current_before
            replace_count = len(current_before if use_after else current_after)
            if current_before or current_after:
                self.current_segments[index:index + replace_count] = replace_with
                self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
                self._sync_hidden_transcript_text_from_segments()

        if self.current_translated_segments is not None:
            replace_with = translated_after if use_after else translated_before
            replace_count = len(translated_before if use_after else translated_after)
            if translated_before or translated_after:
                self.current_translated_segments[index:index + replace_count] = replace_with
                self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
                self._sync_hidden_translated_text_from_segments()

        target_index = int(entry.get("selected_after" if use_after else "selected_before", index))
        self.set_selected_segment_index(target_index, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(target_index)
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()


    def populate_timeline_layers_menu(self):
        """Build the Layers menu without touching project/preview visibility."""
        menu = getattr(self, "timeline_layers_menu", None)
        timeline = getattr(self, "timeline", None)
        if menu is None:
            return
        menu.clear()
        if timeline is None or not timeline._timeline:
            empty = menu.addAction("No layers")
            empty.setEnabled(False)
            return
        has_tracks = False
        for track in timeline._timeline.tracks:
            # Do not show empty/default tracks. The menu reflects only
            # tracks that currently contain project layers.
            if not track.layers:
                continue
            has_tracks = True
            action = menu.addAction(str(track.name or "Layer Track"))
            action.setCheckable(True)
            action.setChecked(timeline.is_track_shown_on_timeline(track))
            action.setToolTip("Only changes whether this entire track is displayed on the timeline.")
            action.toggled.connect(
                lambda shown, track_id=track.id: timeline.set_track_shown_on_timeline(track_id, shown)
            )
        if not has_tracks:
            empty = menu.addAction("No layer tracks")
            empty.setEnabled(False)


    def on_timeline_track_lock_toggled(self, track_name: str, locked: bool):
        timeline = getattr(self, "timeline", None)
        if timeline is None or not timeline._timeline:
            return
        for track in timeline._timeline.tracks:
            if track.name == track_name:
                track.locked = bool(locked)
                timeline._redraw()
                self.persist_current_timeline_project_data()
                self.refresh_ui_state()
                self.log(f"[Timeline] {'Locked' if locked else 'Unlocked'} track: {track.name}")
                return


    def toggle_selected_timeline_layer_lock(self, layer_id: str = ""):
        timeline = getattr(self, "timeline", None)
        selected_id = str(layer_id or getattr(timeline, "_selected_layer_id", "") or "") if timeline else ""
        if not timeline or not timeline._timeline or not selected_id:
            return
        for track in timeline._timeline.tracks:
            for layer in track.layers:
                if layer.id == selected_id:
                    layer.locked = not bool(getattr(layer, "locked", False))
                    timeline._redraw()
                    self.persist_current_timeline_project_data()
                    self.log(f"[Timeline] {'Locked' if layer.locked else 'Unlocked'} layer: {layer.name or layer.id}")
                    return


    def delete_selected_timeline_segment(self):
        if self._preview_is_playing():
            return
        # If a layer is currently selected in the timeline, remove it
        # from its track. Handles blur (with overlay sync), image/logo,
        # text, and any other layer type.
        if hasattr(self, "timeline") and self.timeline._timeline:
            selected_id = str(getattr(self.timeline, "_selected_layer_id", "") or "")
            if selected_id:
                for track in self.timeline._timeline.tracks:
                    layer = None
                    layer_idx = -1
                    for li, l in enumerate(track.layers):
                        if l.id == selected_id:
                            layer = l
                            layer_idx = li
                            break
                    if layer is None:
                        continue
                    track_name = str(getattr(track, "name", ""))
                    if track_name in ("V1 Video", "A1 Audio"):
                        QMessageBox.information(self, "Không thể xóa", "Không thể xóa luồng âm thanh hoặc video gốc của dự án. Nếu muốn tắt tiếng, bạn có thể nhấn biểu tượng Tắt tiếng (Mute) trên track.")
                        return
                    if bool(getattr(track, "locked", False)):
                        QMessageBox.information(self, "Lớp bị khóa", "Vui lòng mở khóa lớp này trước khi xóa.")
                        return
                    if bool(getattr(layer, "locked", False)):
                        QMessageBox.information(self, "Lớp bị khóa", "Vui lòng mở khóa lớp này trước khi xóa.")
                        return
                    layer_type = str(
                        getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))
                    ).lower()
                    # TS1 is a projection of the canonical subtitle lists.
                    # Removing only its visual DubSubtitleLayer leaves the
                    # source segment intact; a later resize calls
                    # apply_segments_to_timeline() and recreates that "deleted"
                    # cue. Route it through the canonical segment deletion
                    # branch below instead.
                    is_subtitle_layer = (
                        layer_type == "dub_subtitle"
                        or str(getattr(getattr(track, "type", ""), "value", getattr(track, "type", ""))).lower() == "dub_subtitle"
                    )
                    if is_subtitle_layer:
                        if bool(getattr(track, "locked", False)) or bool(getattr(layer, "locked", False)):
                            QMessageBox.information(self, "Layer Locked", "Unlock this timeline layer before deleting it.")
                            return
                        segment_index = int(getattr(self.timeline, "_segment_indices", {}).get(layer.id, -1))
                        if segment_index < 0 and isinstance(getattr(layer, "metadata", None), dict):
                            try:
                                segment_index = int(layer.metadata.get("_seg_index", -1))
                            except (TypeError, ValueError):
                                segment_index = -1
                        if segment_index < 0:
                            QMessageBox.warning(self, "Delete Segment", "Could not identify the selected subtitle segment.")
                            return
                        # Carry the selected layer's timing/text into the
                        # canonical deletion path.  Segment indices can be
                        # renumbered after an insertion/deletion, so relying
                        # on a stale index can remove the adjacent cue.
                        self._pending_delete_segment_key = (
                            round(float(getattr(layer, "start", 0.0) or 0.0), 6),
                            round(float(getattr(layer, "end", 0.0) or 0.0), 6),
                            str(getattr(layer, "text", "") or ""),
                        )
                        self.timeline._selected_layer_id = ""
                        self._selected_segment_index = segment_index
                        return self.delete_selected_timeline_segment()
                    # Use the layer-specific removal paths where they own
                    # preview state.  The Delete timeline button therefore
                    # removes the selected layer rather than merely deleting
                    # a timeline bar and leaving a stale overlay behind.
                    if layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo":
                        self._delete_logo_layer(layer)
                        return
                    if layer_type == "mask" or str(getattr(track, "name", "")) == "M1":
                        self._delete_mask_layer(layer)
                        return
                    # Blur: pop the corresponding overlay region first
                    if layer_type == "blur":
                        try:
                            overlay = getattr(self.video_view, "blur_overlay", None)
                            # A split BlurLayer can share one preview region
                            # with its sibling pieces. Only remove by index
                            # when preview regions and timeline layers are
                            # still one-to-one; otherwise deleting one split
                            # piece would remove the surviving blur region.
                            if (
                                overlay is not None
                                and len(overlay._regions) == len(track.layers)
                                and 0 <= layer_idx < len(overlay._regions)
                            ):
                                overlay._regions.pop(layer_idx)
                                overlay._active_index = min(
                                    layer_idx, len(overlay._regions) - 1
                                )
                                overlay.update()
                                if hasattr(overlay, "sync_to_view"):
                                    overlay.sync_to_view()
                        except Exception:
                            pass
                    # Remove the layer from the track
                    try:
                        if layer in track.layers:
                            track.layers.remove(layer)
                    except ValueError:
                        pass
                    # If the track is now empty, remove it (B1, L1, etc.)
                    if not track.layers:
                        try:
                            self.timeline._timeline.tracks.remove(track)
                        except ValueError:
                            pass
                        if hasattr(self.timeline, "_track_heights") and track.id in self.timeline._track_heights:
                            del self.timeline._track_heights[track.id]
                    # Sync blur overlay if needed
                    if layer_type == "blur":
                        try:
                            regions = self._current_blur_regions_payload() if hasattr(self, "_current_blur_regions_payload") else []
                            if hasattr(self.video_view, "set_blur_regions_normalized"):
                                self.video_view.set_blur_regions_normalized(regions)
                            if hasattr(self.timeline, "sync_blur_regions"):
                                self.timeline.sync_blur_regions(regions)
                            if hasattr(self, "apply_preview_blur_region"):
                                self.apply_preview_blur_region(force=True)
                            if hasattr(self, "persist_project_blur_state"):
                                self.persist_project_blur_state()
                        except Exception:
                            pass
                    # Clear selection and redraw
                    try:
                        self.timeline._selected_layer_id = ""
                    except Exception:
                        pass
                    if hasattr(self.timeline, "_redraw"):
                        self.timeline._redraw()
                    if hasattr(self.timeline, "viewport"):
                        self.timeline.viewport().update()
                    # Show default inspector
                    if hasattr(self, "_show_default_inspector"):
                        self._show_default_inspector()
                    # Keep remaining Logo / Mask layers visible. Clearing
                    # the whole overlay here used to hide every surviving
                    # layer until the user clicked one in the timeline.
                    if str(getattr(track, "name", "")) == "L1 Logo":
                        if track.layers:
                            next_layer = track.layers[min(layer_idx, len(track.layers) - 1)]
                            self.timeline._selected_layer_id = next_layer.id
                            self._show_logo_overlay(track, next_layer)
                        elif hasattr(self, "video_view") and hasattr(self.video_view, "clear_logo"):
                            self.video_view.clear_logo()
                    if str(getattr(track, "name", "")) == "M1":
                        if not track.layers and hasattr(self, "video_view") and hasattr(self.video_view, "clear_mask_region"):
                            self.video_view.clear_mask_region()
                        try:
                            if hasattr(self, "_apply_mask_to_preview"):
                                self._apply_mask_to_preview()
                        except Exception:
                            pass
                        try:
                            if hasattr(self, "persist_project_mask_state"):
                                self.persist_project_mask_state()
                        except Exception:
                            pass
                    if layer_type == "blur":
                        # Do not auto-select a surviving B1 layer. Leave the
                        # editor focused on V1 so the remaining effect is
                        # visible but not implicitly put into edit mode.
                        self._clear_effect_selection_after_delete()
                    if layer_type == "text":
                        # The preview overlay owns a list of all text layers;
                        # refresh it after deletion so only the selected
                        # layer is removed and surviving text stays visible.
                        self._refresh_text_layer_preview("")
                    if layer_type == "audio" and str(getattr(track, "name", "")) == "A2 Music":
                        # Removing a Music Layer must also remove it from the
                        # composed preview sidecar.  Do not leave the hidden
                        # legacy path/artifact as a fallback after the last
                        # music layer has been deleted.
                        if not track.layers:
                            try:
                                self.bg_music_edit.clear()
                            except Exception:
                                pass
                            self.last_music_path = ""
                            self.processed_artifacts.pop("music", None)
                            state = getattr(self, "current_project_state", None)
                            if state is not None:
                                state.artifacts.pop("music", None)
                                self.project_service.save_project(state)
                        self._refresh_music_layer_summary()
                        self._schedule_preview_audio_refresh(force=True)
                    try:
                        self.persist_current_timeline_project_data()
                    except Exception:
                        pass
                    return
        segments = list(self.get_active_segments() or [])
        if not segments:
            return
        index = int(getattr(self, "_selected_segment_index", -1))
        pending_key = getattr(self, "_pending_delete_segment_key", None)
        if pending_key:
            target_start, target_end, target_text = pending_key
            matching = [
                idx for idx, segment in enumerate(segments)
                if abs(float(segment.get("start", 0.0) or 0.0) - target_start) < 0.01
                and abs(float(segment.get("end", 0.0) or 0.0) - target_end) < 0.01
                and (not target_text or str(segment.get("text", "") or "") == target_text)
            ]
            if not matching:
                matching = [
                    idx for idx, segment in enumerate(segments)
                    if abs(float(segment.get("start", 0.0) or 0.0) - target_start) < 0.01
                    and abs(float(segment.get("end", 0.0) or 0.0) - target_end) < 0.01
                ]
            if matching:
                index = matching[0]
        if not (0 <= index < len(segments)):
            index = self._find_active_segment_index(self.media_player.position(), segments)
        if not (0 <= index < len(segments)):
            QMessageBox.information(self, "Delete Segment", "Please select an audio/subtitle block first.")
            return

        remaining_count = max(0, len(segments) - 1)
        target_selection = min(index, max(0, remaining_count - 1)) if remaining_count else -1
        delete_history_entry = {
            "type": "delete",
            "index": int(index),
            "selected_before": int(index),
            "selected_after": int(target_selection),
            "current_before": [],
            "current_after": [],
            "translated_before": [],
            "translated_after": [],
        }

        def _matching_index(items):
            if not pending_key:
                return index if 0 <= index < len(items) else -1
            target_start, target_end, target_text = pending_key
            for item_index, segment in enumerate(items):
                if abs(float(segment.get("start", 0.0) or 0.0) - target_start) < 0.01 \
                        and abs(float(segment.get("end", 0.0) or 0.0) - target_end) < 0.01 \
                        and (not target_text or str(segment.get("text", "") or "") == target_text):
                    return item_index
            for item_index, segment in enumerate(items):
                if abs(float(segment.get("start", 0.0) or 0.0) - target_start) < 0.01 \
                        and abs(float(segment.get("end", 0.0) or 0.0) - target_end) < 0.01:
                    return item_index
            return index if 0 <= index < len(items) else -1

        current_index = _matching_index(self.current_segments or [])
        if 0 <= current_index < len(self.current_segments or []):
            delete_history_entry["current_before"] = [copy.deepcopy(self.current_segments[current_index])]
            self.current_segments[current_index:current_index + 1] = []
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            self._sync_hidden_transcript_text_from_segments()

        translated_index = _matching_index(self.current_translated_segments or [])
        if 0 <= translated_index < len(self.current_translated_segments or []):
            delete_history_entry["translated_before"] = [copy.deepcopy(self.current_translated_segments[translated_index])]
            self.current_translated_segments[translated_index:translated_index + 1] = []
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()

        # The optional one-line display cache is indexed against the old
        # subtitle list. It must never survive a deletion, otherwise a later
        # timing edit can redraw a stale cue from that cache.
        self._single_line_split_cache = None
        self._pending_delete_segment_key = None

        self._timeline_timing_undo_stack.append(delete_history_entry)
        self._timeline_timing_redo_stack = []
        if len(self._timeline_timing_undo_stack) > 100:
            self._timeline_timing_undo_stack = self._timeline_timing_undo_stack[-100:]
        self._refresh_timeline_history_buttons()

        self.set_selected_segment_index(target_selection, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(target_selection)
        self.apply_segments_to_timeline()
        # `persist_current_timeline_project_data()` intentionally skips empty
        # lists during project initialization. A user deletion is different:
        # write the exact post-delete lists, including [] so a removed final
        # cue can never be restored from the project artifacts.
        state = getattr(self, "current_project_state", None)
        if state is not None:
            try:
                self.current_segment_models = self.project_bridge.persist_transcription(
                    state, self.current_segments or [], self.last_original_srt_path,
                )
                if self.current_translated_segments is not None:
                    self.current_translated_segment_models = self.project_bridge.persist_translation(
                        state,
                        self.current_segment_models,
                        self.current_translated_segments or [],
                        self.last_translated_srt_path,
                    )
            except Exception as exc:
                self.log(f"[Subtitle] Could not update deleted segment cache: {exc}")
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()


    def on_timeline_segment_timing_changed(self, index: int, start: float, end: float):
        updated = False
        if 0 <= index < len(self.current_segments or []):
            self._apply_segment_timing(self.current_segments[index], start, end)
            self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
            self._sync_hidden_transcript_text_from_segments()
            updated = True
        if 0 <= index < len(self.current_translated_segments or []):
            self._apply_segment_timing(self.current_translated_segments[index], start, end)
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()
            updated = True
        if not updated:
            return
        # Timing changes invalidate the optional derived one-line display
        # list. Otherwise it can retain deleted cues and overwrite the fresh
        # canonical subtitle state on the next redraw.
        self._single_line_split_cache = None
        self.apply_segments_to_timeline()
        # Rebuilding TS1 rehydrates its layers and can briefly select the
        # first cue while the preview refreshes. Restore the cue that was
        # actually edited only after the rebuild has completed.
        self.set_selected_segment_index(index, sync_ui=True)
        if hasattr(self, "timeline"):
            self.timeline.set_active_segment_index(index)
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()


    def _refresh_timeline_history_buttons(self):
        if hasattr(self, "timeline_undo_btn"):
            self.timeline_undo_btn.setEnabled(bool(self._timeline_timing_undo_stack))
        if hasattr(self, "timeline_redo_btn"):
            self.timeline_redo_btn.setEnabled(bool(self._timeline_timing_redo_stack))


    def undo_last_timeline_timing_edit(self):
        if self._preview_is_playing():
            return False
        if not self._timeline_timing_undo_stack:
            return False
        entry = self._timeline_timing_undo_stack.pop()
        if str(entry.get("type", "")) == "range_split":
            self._apply_range_split_history(entry, use_after=False)
            self._timeline_timing_redo_stack.append(entry)
            self._refresh_timeline_history_buttons()
            return True
        if str(entry.get("type", "")) == "overlay_split":
            self._apply_overlay_split_history(entry, use_after=False)
            self._timeline_timing_redo_stack.append(entry)
            self._refresh_timeline_history_buttons()
            return True
        if str(entry.get("type", "timing")) in {"insert", "split", "delete", "batch_timing", "split_sentences"}:
            self._apply_timeline_structure_history_entry(entry, use_after=False)
            self._timeline_timing_redo_stack.append(entry)
            self._refresh_timeline_history_buttons()
            return True
        current_entry = None
        active_segments = self.get_active_segments()
        index = int(entry.get("index", -1))
        if 0 <= index < len(active_segments):
            current_entry = {
                "index": index,
                "start": float(active_segments[index].get("start", 0.0)),
                "end": float(active_segments[index].get("end", 0.0)),
            }
        self._suspend_timeline_undo = True
        try:
            self.on_timeline_segment_timing_changed(
                index,
                float(entry.get("start", 0.0)),
                float(entry.get("end", 0.0)),
            )
        finally:
            self._suspend_timeline_undo = False
        if current_entry:
            self._timeline_timing_redo_stack.append(current_entry)
        self._refresh_timeline_history_buttons()
        return True


    def redo_last_timeline_timing_edit(self):
        if self._preview_is_playing():
            return False
        if not self._timeline_timing_redo_stack:
            return False
        entry = self._timeline_timing_redo_stack.pop()
        if str(entry.get("type", "")) == "range_split":
            self._apply_range_split_history(entry, use_after=True)
            self._timeline_timing_undo_stack.append(entry)
            self._refresh_timeline_history_buttons()
            return True
        if str(entry.get("type", "")) == "overlay_split":
            self._apply_overlay_split_history(entry, use_after=True)
            self._timeline_timing_undo_stack.append(entry)
            self._refresh_timeline_history_buttons()
            return True
        if str(entry.get("type", "timing")) in {"insert", "split", "delete", "batch_timing", "split_sentences"}:
            self._apply_timeline_structure_history_entry(entry, use_after=True)
            self._timeline_timing_undo_stack.append(entry)
            self._refresh_timeline_history_buttons()
            return True
        current_entry = None
        active_segments = self.get_active_segments()
        index = int(entry.get("index", -1))
        if 0 <= index < len(active_segments):
            current_entry = {
                "index": index,
                "start": float(active_segments[index].get("start", 0.0)),
                "end": float(active_segments[index].get("end", 0.0)),
            }
        self._suspend_timeline_undo = True
        try:
            self.on_timeline_segment_timing_changed(
                index,
                float(entry.get("start", 0.0)),
                float(entry.get("end", 0.0)),
            )
        finally:
            self._suspend_timeline_undo = False
        if current_entry:
            self._timeline_timing_undo_stack.append(current_entry)
        self._refresh_timeline_history_buttons()
        return True


    def _sync_selected_segment_to_playback_position(self):
        if not hasattr(self, "media_player"):
            return
        segments = self.live_preview_segments or self.get_active_segments()
        if not segments:
            return
        try:
            position_ms = int(self.media_player.position())
        except Exception:
            return
        if hasattr(self, "subtitle_list_view") and self.subtitle_list_view:
            try:
                self.subtitle_list_view.sync_playback_position(position_ms)
            except Exception:
                pass
        active_index = self._find_active_segment_index(position_ms, segments)
        if active_index >= 0:
            self.set_selected_segment_index(active_index, sync_ui=False)


    def apply_segments_to_timeline(self):
        segs = self.get_active_segments()
        if segs:
            try:
                from workflows.voice_workflow import predict_speed_ratios
                settings = getattr(self.current_project_state, "settings", {}) or {}
                predict_speed_ratios(
                    segs,
                    normalizer_dictionary=dict(settings.get("normalizer_dictionary", {}) or {}),
                )
            except Exception:
                pass
        self.timeline.set_segments(segs if segs else [])
        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=True)
        # Configure the Qt subtitle overlay before showing its drag target.
        # Otherwise it can briefly use the default size until the first drag.
        self.update_subtitle_preview_style()
        self._show_subtitle_drag_layer()
        self.sync_live_subtitle_preview()


    def _timeline_audio_track_mutes(self) -> tuple[bool, bool] | None:
        if not hasattr(self, "timeline") or not getattr(self.timeline, "_timeline", None):
            return None
        a1_muted = None
        a2_muted = None
        for track in self.timeline._timeline.tracks:
            metadata = getattr(track, "metadata", {}) or {}
            muted = bool(getattr(track, "muted", False) or metadata.get("_muted", False))
            if track.name == "A1 Audio":
                a1_muted = muted
            elif track.name in ("A2 Dub", "TS1"):
                a2_muted = muted
        if a1_muted is None and a2_muted is None:
            return None
        return bool(a1_muted), bool(a2_muted)


    def _resolve_preview_dubbed_playback_source(self) -> tuple[str, str]:
        """Resolve which audio file represents the dubbed track in preview.

        With a Music Layer, preview uses the cached TTS+music render so its
        track volumes match export. Without one, it falls back to pure TTS.

        Returns ("voice", path) | ("mixed", path) | ("original", "").
        """
        track_mutes = self._timeline_audio_track_mutes()
        voice_only = self._resolve_preview_voice_only_audio_path()
        mixed_audio = self._resolve_preview_mixed_audio_path()

        if not track_mutes:
            if mixed_audio:
                return "mixed", mixed_audio
            if voice_only:
                return "voice", voice_only
            return "original", ""

        a1_muted, a2_muted = track_mutes
        # A muted TS1 track does not imply the Music Layer is muted.  When a
        # composed sidecar exists, it is rebuilt without TTS and returned so
        # music remains audible independently.
        if mixed_audio:
            return "mixed", mixed_audio
        if a2_muted:
            return "original", ""
        # With no Music Layer the generated voice can be played directly.
        if voice_only:
            return "voice", voice_only
        return "original", ""


    def _is_active_timeline_audio_track_muted(self) -> bool:
        track_mutes = self._timeline_audio_track_mutes()
        if not track_mutes:
            return False
        a1_muted, a2_muted = track_mutes
        mode = str(getattr(self, "_preview_audio_track_mode", "original") or "original").strip().lower()
        if mode != "dubbed":
            return a1_muted
        dubbed_audio_kind, _dubbed_path = self._resolve_preview_dubbed_playback_source()
        if dubbed_audio_kind == "voice":
            return a2_muted
        if dubbed_audio_kind == "mixed":
            # The mixed sidecar contains TTS + Music. A1 is loaded as its
            # own sidecar, so only the TTS-side mute controls this stream.
            return a2_muted
        return a1_muted


    def play_audio_preview_file(self, audio_path: str):
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError("Audio preview file was not found.")
        if os.path.getsize(audio_path) <= 44:
            raise RuntimeError("Audio preview file is empty or invalid.")
        if hasattr(self, "media_player") and self.media_player.is_playing():
            self.media_player.pause()
            if hasattr(self, "timeline"):
                self.timeline.set_playing(False)
        self.audio_preview_player.stop()
        self.audio_preview_player.setSource(QUrl.fromLocalFile(audio_path))
        self.audio_preview_player.play()
        self._last_audio_preview_path = audio_path


    def _play_voice_preview_entry(self, entry: dict, button: QPushButton | None = None):
        try:
            source = self._resolve_voice_preview_source(entry)
            self._stop_voice_library_preview()
            self.voice_preview_library_player.setSource(source)
            self.voice_preview_library_player.play()
            if button is not None:
                button.setText("Playing...")
            self.log(f"[Voice Preview] playing clip for {entry.get('name', 'voice')}")
        except Exception as exc:
            self.show_error("Nghe thử giọng thất bại", "Không thể phát đoạn mẫu giọng đọc đã chọn.", str(exc))


    def on_segment_audio_preview_ready(self, index: int, audio_path: str, error: str):
        btn = getattr(self, "audio_inspector_regenerate_voice_btn", None)

        self._segment_preview_threads.pop(index, None)

        if error:
            if btn is not None:
                btn.setEnabled(True)
                btn.setText("Regenerate voice")
            self.show_error("Audio Preview Failed", "Could not generate preview audio for this subtitle.", error)
            return

        self._voiceover_force_refresh = True
        if btn is not None:
            btn.setEnabled(True)
            btn.setText("Regenerate voice")

        if getattr(self, "last_voice_vi_path", "") and os.path.exists(self.last_voice_vi_path):
            self.run_voiceover()
        else:
            self._apply_segment_audio_end_to_timeline(index=index, audio_path=audio_path)
            try:
                self.play_audio_preview_file(audio_path)
            except Exception as exc:
                self.show_error("Audio Preview Failed", "Could not play the generated preview audio.", str(exc))


    def _apply_segment_audio_end_to_timeline(self, *, index: int, audio_path: str) -> None:
        if not audio_path or not os.path.exists(audio_path):
            return
        actual_d = ffprobe_wav_duration(audio_path)
        if actual_d <= 0.0:
            return
        segs = self.current_translated_segments or self.current_segments
        if not segs or index < 0 or index >= len(segs):
            return
        seg = segs[index]
        try:
            start_s = float(seg.get("start", 0.0))
        except (TypeError, ValueError):
            return
        audio_end = start_s + actual_d
        try:
            cur_end = float(seg.get("end", audio_end))
        except (TypeError, ValueError):
            cur_end = audio_end
        if audio_end > cur_end + 0.01:
            seg["_audio_end"] = audio_end
        else:
            seg.pop("_audio_end", None)
        timeline = getattr(self, "timeline", None)
        if timeline is None:
            return
        timeline_model = getattr(timeline, "_timeline", None)
        if timeline_model is None:
            return
        from app.layers.sync_bridge import DUB_SUBTITLE_TRACK_NAME
        target_track = None
        for t in timeline_model.tracks:
            if t.name == DUB_SUBTITLE_TRACK_NAME:
                target_track = t
                break
        if target_track is None:
            return
        for layer in target_track.layers:
            meta = getattr(layer, "metadata", None) or {}
            if not isinstance(meta, dict):
                continue
            try:
                if int(meta.get("_seg_index", -1)) == index:
                    if audio_end > cur_end + 0.01:
                        meta["_audio_end"] = audio_end
                    else:
                        meta.pop("_audio_end", None)
            except (TypeError, ValueError):
                continue
        timeline._redraw()


