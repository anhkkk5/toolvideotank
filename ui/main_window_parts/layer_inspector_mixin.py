"""LayerInspectorMixin: Layer Inspector panels, Blur, Mask, Logo, Text, Video, Audio controls."""

try:
    from main_window_parts.common_deps import *
except ImportError:
    from ui.main_window_parts.common_deps import *


from typing import Any, Dict, List, Optional
import os
import json
import logging

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QPushButton, QSlider, QProgressBar, QLabel, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox, QTabWidget, QSplitter, QScrollArea, QFrame, QDialog,
    QApplication, QFileDialog, QMessageBox, QWidget, QMenu
)

logger = logging.getLogger(__name__)


class LayerInspectorMixin:
    """Mixin containing layer inspector panels (Blur, Mask, Logo, Text, Audio, Video) and overlay wiring."""
    def _on_text_layer_selected_from_preview(self, layer_id):
        if hasattr(self, "timeline"):
            self.timeline._selected_layer_id = str(layer_id)
            self.timeline._redraw()
        self.on_timeline_layer_selected(str(layer_id))


    def _on_text_layer_moved(self, layer_id, x, y):
        if self._preview_is_playing():
            return
        layer = next((item for item in self._text_layers() if item.id == layer_id), None)
        if layer is None:
            return
        layer.transform.x, layer.transform.y = float(x), float(y)
        self.schedule_timeline_project_persist()


    def _refresh_music_layer_summary(self):
        label = getattr(self, "music_layers_summary_label", None)
        entries = self._music_audio_tracks()
        # The optional volume row is shown only for a real timeline Music
        # Layer.  Legacy project-level music artifacts remain usable for
        # playback/export but should not make the optional control appear as
        # if a new layer had been added.
        volume_row = getattr(self, "audio_music_volume_row", None)
        if volume_row is not None:
            volume_row.setVisible(any(not bool(item.get("legacy", False)) for item in entries))
        if label is None:
            return
        if not entries:
            label.setText("No music layer added.")
            return
        names = []
        for entry in entries:
            names.append(os.path.basename(str(entry.get("path", ""))) or "Music")
        label.setText(f"{len(names)} music layer(s): " + ", ".join(names))


    def add_music_layer(self):
        """Choose an audio file and add it as an independent timeline track."""
        if self._preview_is_playing():
            return
        video_path = str(getattr(self, "video_path_edit", None).text() if hasattr(self, "video_path_edit") else "").strip()
        if not video_path or not os.path.exists(video_path):
            QMessageBox.information(self, "Add Music Layer", "Select a video before adding music.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Music",
            "",
            "Audio Files (*.wav *.mp3 *.flac *.m4a *.aac *.ogg);;All Files (*)",
        )
        if not path:
            return
        normalized = self._normalize_local_file_path(path)
        if not normalized or not os.path.exists(normalized):
            return
        timeline = getattr(self, "timeline", None)
        model = getattr(timeline, "_timeline", None) if timeline is not None else None
        if model is None:
            return
        from app.layers.audio import AudioLayer
        from app.layers.base import LayerType
        from app.layers.sync_bridge import find_or_create_track

        duration = max(0.1, float(getattr(model, "duration", 0.0) or 0.0))
        track = find_or_create_track(model, "A2 Music", LayerType.AUDIO, 80)
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_audio_role"] = "music"
        track.metadata.setdefault("_volume", 30.0)
        track.metadata.setdefault("_muted", False)
        layer = AudioLayer(
            name=f"Music {len(track.layers) + 1}",
            source=normalized,
            start=0.0,
            end=duration,
            volume=float(track.metadata.get("_volume", 30.0)) / 100.0,
        )
        layer.metadata["_audio_role"] = "music"
        track.layers.append(layer)
        if hasattr(timeline, "_track_heights"):
            timeline._track_heights[track.id] = int(track.height or 80)
        try:
            self.bg_music_edit.setText(normalized)
        except Exception:
            pass
        self.last_music_path = normalized
        self.processed_artifacts["music"] = normalized
        if hasattr(self, "update_project_artifact"):
            self.update_project_artifact("music", normalized)
        timeline._redraw()
        self._sync_audio_mix_controls_from_tracks()
        self._refresh_music_layer_summary()
        try:
            timeline.select_layer(layer.id)
            self.on_timeline_layer_selected(layer.id)
        except Exception:
            pass
        self.persist_current_timeline_project_data()
        self._schedule_preview_audio_refresh(force=True)


    def _set_layer_timing_controls(self, prefix: str, layer) -> None:
        """Populate an overlay inspector's Start/End controls without edits."""
        for suffix, value in (("start", float(layer.start)), ("end", float(layer.end))):
            control = getattr(self, f"{prefix}_inspector_{suffix}_spin", None)
            if control is None:
                continue
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)


    def _deferred_effect_layer_id_for(self, layer_type: str) -> str:
        """Return the one effect clip temporarily hidden during an edit."""
        if self._preview_is_playing():
            return ""
        if str(getattr(self, "_deferred_effect_edit_type", "") or "") != str(layer_type):
            return ""
        return str(getattr(self, "_deferred_effect_edit_layer_id", "") or "")


    def _wire_layer_timing_controls(self, prefix: str) -> None:
        """Wire one inspector's common Start/End controls once."""
        wired_name = f"_{prefix}_layer_timing_wired"
        if getattr(self, wired_name, False):
            return
        setattr(self, wired_name, True)
        start_control = getattr(self, f"{prefix}_inspector_start_spin", None)
        end_control = getattr(self, f"{prefix}_inspector_end_spin", None)
        if start_control is None or end_control is None:
            return

        def _selected_layer():
            selected_id = str(getattr(self.timeline, "_selected_layer_id", "") or "")
            for track in getattr(getattr(self.timeline, "_timeline", None), "tracks", []):
                for layer in track.layers:
                    if layer.id == selected_id:
                        return track, layer
            return None, None

        def _apply_timing(_value=None):
            track, layer = _selected_layer()
            if layer is None:
                return
            start = max(0.0, float(start_control.value()))
            end = max(start + float(getattr(self.timeline, "MIN_DUR", 0.1)), float(end_control.value()))
            duration = float(getattr(self.timeline, "_duration", 0.0) or 0.0)
            if duration > 0:
                start = min(start, max(0.0, duration - float(getattr(self.timeline, "MIN_DUR", 0.1))))
                end = min(end, duration)
                end = max(end, start + float(getattr(self.timeline, "MIN_DUR", 0.1)))
            layer.start, layer.end = start, end
            self._set_layer_timing_controls(prefix, layer)
            self.timeline._redraw()
            self.persist_current_timeline_project_data()
            self._timed_layer_preview_signature = None
            self.refresh_timed_layer_preview()
            if prefix == "mask":
                self._apply_mask_to_preview(
                    regions=self._current_mask_regions_payload(include_inactive=True)
                )

        start_control.valueChanged.connect(_apply_timing)
        end_control.valueChanged.connect(_apply_timing)


    def _show_logo_overlay(self, track, layer, *, editable=True):
        """Show the draggable logo overlay for the selected logo layer."""
        if not hasattr(self, "video_view"):
            return
        # This method is also called by selection/project-restoration paths,
        # so guard it here as well as in the timed playback refresh.
        if not bool(getattr(self, "_logo_track_preview_visible", True)):
            if hasattr(self.video_view, "clear_logo"):
                self.video_view.clear_logo()
            return
        path = str(getattr(layer, "source", "") or "")
        if not path:
            return
        try:
            from app.layers.transform import Transform
            transform = getattr(layer, "transform", None) or Transform()
        except Exception:
            transform = None
        # Get position/size from the layer (use transform or defaults)
        if transform is not None and hasattr(transform, "x"):
            x = float(getattr(transform, "x", 0.1)) / 100.0
            y = float(getattr(transform, "y", 0.1)) / 100.0
            scale_x = float(getattr(transform, "scale_x", 1.0))
            scale_y = float(getattr(transform, "scale_y", 1.0))
            w = 0.2 * scale_x
            h = 0.2 * scale_y
        else:
            x, y, w, h = 0.1, 0.1, 0.2, 0.2

        # Store the handler lambdas as attributes so we can disconnect
        # them by reference. This avoids the libpyside RuntimeWarning
        # that occurs when calling disconnect() with no args or with
        # a lambda that was never connected.
        prev_moved = getattr(self, "_logo_moved_handler", None)
        if prev_moved is not None:
            try:
                self.video_view.logoMoved.disconnect(prev_moved)
            except (RuntimeError, TypeError, Exception):
                pass
        prev_deleted = getattr(self, "_logo_deleted_handler", None)
        if prev_deleted is not None:
            try:
                self.video_view.logoDeleted.disconnect(prev_deleted)
            except (RuntimeError, TypeError, Exception):
                pass

        self._logo_overlay_layer = layer

        def _moved_handler(nx, ny, nw, nh, l=layer):
            self._on_logo_moved(l, nx, ny, nw, nh)

        def _deleted_handler(l=layer):
            self._delete_logo_layer(l)

        self._logo_moved_handler = _moved_handler
        self._logo_deleted_handler = _deleted_handler

        self.video_view.logoMoved.connect(_moved_handler)
        self.video_view.logoDeleted.connect(_deleted_handler)

        logos = []
        active_index = 0
        for index, candidate in enumerate(track.layers):
            if not self._layer_is_active_at_preview_time(candidate):
                continue
            source = str(getattr(candidate, "source", "") or "")
            candidate_transform = getattr(candidate, "transform", None)
            if candidate_transform is not None and hasattr(candidate_transform, "x"):
                logo_x = float(getattr(candidate_transform, "x", 0.1)) / 100.0
                logo_y = float(getattr(candidate_transform, "y", 0.1)) / 100.0
                logo_w = 0.2 * float(getattr(candidate_transform, "scale_x", 1.0))
                logo_h = 0.2 * float(getattr(candidate_transform, "scale_y", 1.0))
                logo_rotation = float(getattr(candidate_transform, "rotation", 0.0) or 0.0)
            else:
                logo_x, logo_y, logo_w, logo_h, logo_rotation = 0.1, 0.1, 0.2, 0.2, 0.0
            logos.append({
                "source": source, "x": logo_x, "y": logo_y,
                "width": logo_w, "height": logo_h,
                "opacity": float(getattr(candidate, "opacity", 1.0) or 1.0),
                "rotation": logo_rotation,
            })
            if candidate is layer:
                active_index = len(logos) - 1
        if not logos:
            if hasattr(self.video_view, "clear_logo"):
                self.video_view.clear_logo()
            return
        self.video_view.set_logos(
            logos,
            active_index=active_index,
            editable=bool(editable and not self._preview_is_playing()
                          and str(getattr(layer, "id", "") or "") == str(getattr(self, "_preview_edit_layer_id", "") or "")),
        )

        # Push opacity + rotation from the layer to the overlay. We
        # default to fully opaque + 0° for a freshly created logo.
        opacity = float(getattr(layer, "opacity", 1.0) or 1.0)
        rotation = 0.0
        if transform is not None and hasattr(transform, "rotation"):
            try:
                rotation = float(getattr(transform, "rotation", 0.0) or 0.0)
            except (TypeError, ValueError):
                rotation = 0.0
        self.video_view.set_logo_opacity(opacity)
        self.video_view.set_logo_rotation(rotation)


    def _delete_logo_layer(self, layer):
        """Remove the logo layer from the L1 track and clean up."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        remaining_track = None
        remaining_layer = None
        for track in self.timeline._timeline.tracks:
            if layer in track.layers:
                track.layers.remove(layer)
                if not track.layers:
                    try:
                        self.timeline._timeline.tracks.remove(track)
                    except ValueError:
                        pass
                    if hasattr(self.timeline, "_track_heights") and track.id in self.timeline._track_heights:
                        del self.timeline._track_heights[track.id]
                else:
                    remaining_track = track
                    remaining_layer = track.layers[0]
                break
        try:
            self.timeline._selected_layer_id = remaining_layer.id if remaining_layer else ""
        except Exception:
            pass
        if hasattr(self.timeline, "_redraw"):
            self.timeline._redraw()
        if hasattr(self.timeline, "viewport"):
            self.timeline.viewport().update()
        if remaining_layer is not None:
            self._show_logo_overlay(remaining_track, remaining_layer)
        elif hasattr(self, "video_view") and hasattr(self.video_view, "clear_logo"):
            self.video_view.clear_logo()
        try:
            self.persist_current_timeline_project_data()
        except Exception:
            pass
        if hasattr(self, "_show_default_inspector"):
            self._show_default_inspector()


    def _on_logo_moved(self, layer, x, y, w, h):
        """Update the ImageLayer's transform from the logo overlay drag."""
        if self._preview_is_playing():
            return
        try:
            from app.layers.transform import Transform
            transform = Transform(
                x=float(x) * 100.0,
                y=float(y) * 100.0,
                scale_x=float(w) / 0.2 if 0.2 > 0 else 1.0,
                scale_y=float(h) / 0.2 if 0.2 > 0 else 1.0,
            )
            layer.transform = transform
        except Exception:
            pass
        # Coalesce the disk write while the overlay emits drag events.
        self.schedule_timeline_project_persist()


    def _show_mask_overlay(self, track, layer):
        """Show the draggable mask overlay for the selected mask layer."""
        if not hasattr(self, "video_view"):
            return
        if not bool(getattr(self, "_mask_track_preview_visible", True)):
            # Hide/Show controls both the visual effect and its edit chrome.
            # A later focus/selection event must not resurrect either one.
            if hasattr(self.video_view, "clear_mask_region"):
                self.video_view.clear_mask_region()
            return
        # Disconnect any previous handlers to avoid the libpyside
        # RuntimeWarning that occurs when calling disconnect() with no
        # args or a lambda that was never connected.
        prev_moved = getattr(self, "_mask_moved_handler", None)
        if prev_moved is not None:
            try:
                self.video_view.maskMoved.disconnect(prev_moved)
            except (RuntimeError, TypeError, Exception):
                pass
        prev_changed = getattr(self, "_mask_region_changed_handler", None)
        if prev_changed is not None:
            try:
                self.video_view.maskRegionChanged.disconnect(prev_changed)
            except (RuntimeError, TypeError, Exception):
                pass
        prev_deleted = getattr(self, "_mask_deleted_handler", None)
        if prev_deleted is not None:
            try:
                self.video_view.maskDeleted.disconnect(prev_deleted)
            except (RuntimeError, TypeError, Exception):
                pass

        self._mask_overlay_layer = layer

        def _moved_handler(nx, ny, nw, nh, l=layer):
            self._on_mask_moved(l, nx, ny, nw, nh)

        def _region_changed_handler(t=track, l=layer):
            # Fired continuously while the user drags the overlay. Push
            # the new region back to the layer + mpv filter so the
            # green mask follows the overlay in real time.
            self._on_mask_overlay_changed(t, l)

        def _deleted_handler(l=layer):
            self._delete_mask_layer(l)

        self._mask_moved_handler = _moved_handler
        self._mask_region_changed_handler = _region_changed_handler
        self._mask_deleted_handler = _deleted_handler

        self.video_view.maskMoved.connect(_moved_handler)
        self.video_view.maskRegionChanged.connect(_region_changed_handler)
        self.video_view.maskDeleted.connect(_deleted_handler)

        visible_layers = [candidate for candidate in track.layers
                          if self._layer_is_active_at_preview_time(candidate)]
        regions = self._current_mask_regions_payload()
        try:
            active_index = visible_layers.index(layer)
        except ValueError:
            active_index = 0
        # The overlay is always shown so the user can move / resize
        # the region regardless of the M1 track toggle. The toggle
        # only controls whether the mpv filter is applied (see
        # on_track_mask_toggled). Without this, the overlay would
        # only appear after the user clicked the mask layer track
        # to re-select it, even though the layer already exists.
        is_playing = False
        try:
            is_playing = bool(self.media_player.is_playing())
        except Exception:
            is_playing = False
        if hasattr(self, "track_label_bar"):
            self.track_label_bar.set_controls_enabled(not is_playing)
        self.video_view.set_mask_regions(
            regions, active_index=active_index, editable=not is_playing,
        )
        # Re-apply the complete active M1 payload after rebinding the
        # editable overlay. set_mask_regions only updates editor chrome; it
        # must never leave the other mask effects cleared when selection
        # changes between multiple layers.
        try:
            self._apply_mask_to_preview(
                regions=self._current_mask_regions_payload(
                    exclude_layer_id=self._deferred_effect_layer_id_for("mask")
                )
            )
        except Exception:
            pass


    def _on_mask_moved(self, layer, x, y, w, h):
        """Update Mask geometry without rebuilding its MPV effect per move."""
        if self._preview_is_playing():
            return
        try:
            layer.position_x = float(x)
            layer.position_y = float(y)
            layer.width = float(w)
            layer.height = float(h)
        except Exception:
            return
        # Persist coalesced geometry only. The selected M1 effect has already
        # been removed from the filter graph for this paused edit session.
        self.schedule_timeline_project_persist(mask_state=True)
        try:
            if (hasattr(self, "mask_inspector_x_spin")
                    and self.timeline._selected_layer_id == layer.id):
                for control, value in (
                    (self.mask_inspector_x_spin, x),
                    (self.mask_inspector_y_spin, y),
                    (self.mask_inspector_w_spin, w),
                    (self.mask_inspector_h_spin, h),
                ):
                    control.blockSignals(True)
                    control.setValue(float(value))
                    control.blockSignals(False)
        except Exception:
            pass


    def _resync_visual_layers_after_state(self):
        """Finalize overlay effects/handles after a playback state change."""
        try:
            self._timed_layer_preview_signature = None
            self.refresh_timed_layer_preview()
            self._apply_mask_to_preview()
            self._sync_blur_controls()
        except Exception:
            pass
        # Both project settings and timeline JSON are disk-backed.  Defer
        # those writes during the drag while keeping all preview state live.
        self.schedule_timeline_project_persist(mask_state=True)


    def _on_mask_overlay_changed(self, track, layer):
        """Read the current overlay region and update the layer
        position. The mpv filter is NOT re-applied here — it is
        only applied while the video is playing, to avoid lag
        during the drag. When the user presses play, the latest
        layer position is pushed to mpv via `_apply_mask_to_preview`
        (called from `toggle_play` and the stateChanged handler).
        """
        if self._preview_is_playing() or not hasattr(self, "video_view"):
            return
        overlay = getattr(self.video_view, "mask_overlay", None)
        if overlay is None or not overlay._regions:
            return
        try:
            active_index = int(getattr(overlay, "_active_index", -1))
            rect = overlay._regions[active_index]
            x = float(rect.x())
            y = float(rect.y())
            w = float(rect.width())
            h = float(rect.height())
        except Exception:
            return
        try:
            layer.position_x = x
            layer.position_y = y
            layer.width = w
            layer.height = h
        except Exception:
            return
        self.schedule_timeline_project_persist(mask_state=True)


    def _delete_mask_layer(self, layer):
        """Remove the mask layer from the M1 track and clean up."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        for track in self.timeline._timeline.tracks:
            if layer in track.layers:
                track.layers.remove(layer)
                if not track.layers:
                    try:
                        self.timeline._timeline.tracks.remove(track)
                    except ValueError:
                        pass
                    if hasattr(self.timeline, "_track_heights") and track.id in self.timeline._track_heights:
                        del self.timeline._track_heights[track.id]
                break
        if hasattr(self.timeline, "_redraw"):
            self.timeline._redraw()
        if hasattr(self.timeline, "viewport"):
            self.timeline.viewport().update()
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
        # The mask-specific delete path returns before the shared Delete
        # handler can persist the serialized timeline.  Write timeline.json
        # here as well so a deleted M1 layer cannot reappear on reopen.
        try:
            self.persist_current_timeline_project_data()
        except Exception:
            pass
        if hasattr(self, "_show_default_inspector"):
            self._show_default_inspector()
        self._clear_effect_selection_after_delete()


    def _show_audio_inspector_for_track(self, track, layer=None):
        """Show audio inspector populated with the selected track's settings."""
        self._switch_inspector("audio")
        # The Dub Voice section is only for A2 Dub/TS1. Hide it for
        # A1 Audio (or any other audio track).
        track_name = str(getattr(track, "name", "") or "")
        dub_section = getattr(self, "audio_inspector_dub_section", None)
        if dub_section is not None:
            dub_section.setVisible(track_name in ("A2 Dub", "TS1"))
        if track is None:
            return
        track_name = str(getattr(track, "name", "Audio"))
        if hasattr(self, "audio_inspector_track_name_label"):
            self.audio_inspector_track_name_label.setText(track_name)
        if hasattr(self, "audio_inspector_layer_count_label"):
            count = len(list(getattr(track, "layers", [])))
            if layer is not None:
                layer_label = f"Selected: {layer.name}"
            else:
                layer_label = "No layer selected"
            self.audio_inspector_layer_count_label.setText(
                f"{layer_label}    •    {count} layer(s) in track"
            )
        if hasattr(self, "audio_inspector_summary_label"):
            self.audio_inspector_summary_label.setText(
                f"Audio settings for {track_name}. Adjust volume, gain, "
                "speed or mute the track for preview."
            )
        # Load current track metadata into the controls
        meta = getattr(track, "metadata", None) or {}
        try:
            volume = float(meta.get("_volume", 100.0))
        except (TypeError, ValueError):
            volume = 100.0
        try:
            gain = float(meta.get("_gain_db", 0.0))
        except (TypeError, ValueError):
            gain = 0.0
        try:
            speed = float(meta.get("_speed", 1.0))
        except (TypeError, ValueError):
            speed = 1.0
        muted = bool(meta.get("_muted", False))
        solo = bool(meta.get("_solo", False))
        try:
            fade_in = float(meta.get("_fade_in", 0.0))
        except (TypeError, ValueError):
            fade_in = 0.0
        try:
            fade_out = float(meta.get("_fade_out", 0.0))
        except (TypeError, ValueError):
            fade_out = 0.0
        if hasattr(self, "audio_inspector_gain_spin"):
            self.audio_inspector_gain_spin.blockSignals(True)
            self.audio_inspector_gain_spin.setValue(gain)
            self.audio_inspector_gain_spin.blockSignals(False)
        if hasattr(self, "audio_inspector_speed_spin"):
            self.audio_inspector_speed_spin.blockSignals(True)
            self.audio_inspector_speed_spin.setValue(speed)
            self.audio_inspector_speed_spin.blockSignals(False)
        if hasattr(self, "audio_inspector_mute_btn"):
            self.audio_inspector_mute_btn.blockSignals(True)
            self.audio_inspector_mute_btn.setChecked(muted)
            self.audio_inspector_mute_btn.setText("Unmute Track" if muted else "Mute Track")
            self.audio_inspector_mute_btn.blockSignals(False)
        if hasattr(self, "audio_inspector_solo_btn"):
            self.audio_inspector_solo_btn.blockSignals(True)
            self.audio_inspector_solo_btn.setChecked(solo)
            self.audio_inspector_solo_btn.blockSignals(False)
        if hasattr(self, "audio_inspector_fade_in_spin"):
            self.audio_inspector_fade_in_spin.blockSignals(True)
            self.audio_inspector_fade_in_spin.setValue(fade_in)
            self.audio_inspector_fade_in_spin.blockSignals(False)
        if hasattr(self, "audio_inspector_fade_out_spin"):
            self.audio_inspector_fade_out_spin.blockSignals(True)
            self.audio_inspector_fade_out_spin.setValue(fade_out)
            self.audio_inspector_fade_out_spin.blockSignals(False)
        if hasattr(self, "_refresh_audio_inspector_dub_voice_buttons"):
            try:
                self._refresh_audio_inspector_dub_voice_buttons()
            except Exception:
                pass
        if track_name not in ("A2 Dub", "TS1"):
            for attr in ("audio_inspector_use_voice_btn", "audio_inspector_regenerate_voice_btn"):
                button = getattr(self, attr, None)
                if button is not None:
                    button.setVisible(False)
                    button.setEnabled(False)


    def _show_default_inspector_for_layer(self, track, layer):
        self._switch_inspector("default")
        if hasattr(self, "default_inspector_summary_label"):
            tname = getattr(track, "name", "Track") if track else "Track"
            lname = getattr(layer, "name", "Layer") if layer else "Layer"
            ltype = str(getattr(layer.type, "value", layer.type)) if layer else "?"
            self.default_inspector_summary_label.setText(
                f"Selected: {tname} → {lname} ({ltype}).\n"
                "No per-layer settings available for this track type yet."
            )


    def _show_blur_inspector_for_track(self, track, layer=None):
        """Show the Blur Track Inspector populated with the selected track."""
        self._switch_inspector("blur")
        self._wire_blur_inspector_controls()
        self._wire_layer_timing_controls("blur")
        if track is None:
            return
        # B1 mirrors M1 interaction: all regions remain visible in the
        # preview, but only the layer selected in the timeline is editable.
        if layer is not None:
            self._set_layer_timing_controls("blur", layer)
            try:
                visible_layers = [candidate for candidate in track.layers
                                  if self._layer_is_active_at_preview_time(candidate)]
                active_index = visible_layers.index(layer) if layer in visible_layers else 0
                self.video_view.set_blur_active_index(active_index)
            except (AttributeError, ValueError):
                pass
        track_name = str(getattr(track, "name", "Blur"))
        if hasattr(self, "blur_inspector_track_name_label"):
            self.blur_inspector_track_name_label.setText(track_name)
        if hasattr(self, "blur_inspector_layer_count_label"):
            count = len(list(getattr(track, "layers", [])))
            if layer is not None:
                self.blur_inspector_layer_count_label.setText(
                    f"Selected: {layer.name}    •    {count} blur region(s) in track"
                )
            else:
                self.blur_inspector_layer_count_label.setText(
                    f"{count} blur region(s) in track"
                )
        # Load radius / opacity / pixelate from the selected layer
        # (fall back to defaults when no layer is selected).
        if layer is not None:
            try:
                strength = int(round(float(getattr(layer, "blur_strength", 20.0))))
            except (TypeError, ValueError):
                strength = 20
            strength = max(1, min(20, strength))
            try:
                opacity = float(getattr(layer, "blur_opacity", 1.0))
            except (TypeError, ValueError):
                opacity = 1.0
            opacity = max(0.0, min(1.0, opacity))
            pixelate = bool(getattr(layer, "pixelate", False))
            try:
                pixel_size = int(getattr(layer, "pixelate_size", 12))
            except (TypeError, ValueError):
                pixel_size = 12
            pixel_size = max(2, min(60, pixel_size))
        else:
            strength, opacity, pixelate, pixel_size = 20, 1.0, False, 12

        if hasattr(self, "blur_inspector_radius_slider"):
            self.blur_inspector_radius_slider.blockSignals(True)
            self.blur_inspector_radius_slider.setValue(strength)
            self.blur_inspector_radius_slider.blockSignals(False)
        if hasattr(self, "blur_inspector_radius_value_label"):
            self.blur_inspector_radius_value_label.setText(str(strength))
        if hasattr(self, "blur_inspector_opacity_slider"):
            self.blur_inspector_opacity_slider.blockSignals(True)
            self.blur_inspector_opacity_slider.setValue(int(round(opacity * 100)))
            self.blur_inspector_opacity_slider.blockSignals(False)
        if hasattr(self, "blur_inspector_opacity_value_label"):
            self.blur_inspector_opacity_value_label.setText(
                f"{int(round(opacity * 100))}%"
            )
        if hasattr(self, "blur_inspector_pixelate_cb"):
            self.blur_inspector_pixelate_cb.blockSignals(True)
            self.blur_inspector_pixelate_cb.setChecked(pixelate)
            self.blur_inspector_pixelate_cb.blockSignals(False)
        if hasattr(self, "blur_inspector_pixel_size_slider"):
            self.blur_inspector_pixel_size_slider.blockSignals(True)
            self.blur_inspector_pixel_size_slider.setValue(pixel_size)
            self.blur_inspector_pixel_size_slider.blockSignals(False)
        if hasattr(self, "blur_inspector_pixel_size_value_label"):
            self.blur_inspector_pixel_size_value_label.setText(str(pixel_size))

        if hasattr(self, "blur_inspector_summary_label"):
            self.blur_inspector_summary_label.setText(
                f"Blur regions in '{track_name}'. Use the B1 layer "
                "visibility control in the timeline to show or hide it."
            )


    def _wire_blur_inspector_controls(self):
        """One-time wiring of the Blur Inspector's per-region controls."""
        if getattr(self, "_blur_inspector_wired", False):
            return
        self._blur_inspector_wired = True

        def _selected_blur_layer():
            """Return the currently selected BlurLayer (or None)."""
            if not hasattr(self, "timeline") or not self.timeline._timeline:
                return None, None
            sid = getattr(self.timeline, "_selected_layer_id", "") or ""
            for tr in self.timeline._timeline.tracks:
                for l in tr.layers:
                    if l.id == sid:
                        return l, tr
            return None, None

        def _on_radius_changed(value):
            layer, _ = _selected_blur_layer()
            if layer is None:
                return
            try:
                layer.blur_strength = int(value)
            except Exception:
                return
            if hasattr(self, "blur_inspector_radius_value_label"):
                self.blur_inspector_radius_value_label.setText(str(int(value)))
            self._sync_blur_layer_to_preview(layer)

        def _on_opacity_changed(value):
            layer, _ = _selected_blur_layer()
            if layer is None:
                return
            opacity = max(0.0, min(1.0, float(value) / 100.0))
            try:
                layer.blur_opacity = opacity
            except Exception:
                return
            if hasattr(self, "blur_inspector_opacity_value_label"):
                self.blur_inspector_opacity_value_label.setText(f"{int(value)}%")
            self._sync_blur_layer_to_preview(layer)

        def _on_pixelate_toggled(checked):
            layer, _ = _selected_blur_layer()
            if layer is None:
                return
            try:
                layer.pixelate = bool(checked)
            except Exception:
                return
            self._sync_blur_layer_to_preview(layer)

        def _on_pixel_size_changed(value):
            layer, _ = _selected_blur_layer()
            if layer is None:
                return
            try:
                layer.pixelate_size = int(value)
            except Exception:
                return
            if hasattr(self, "blur_inspector_pixel_size_value_label"):
                self.blur_inspector_pixel_size_value_label.setText(str(int(value)))
            self._sync_blur_layer_to_preview(layer)

        self._blur_radius_handler = _on_radius_changed
        self._blur_opacity_handler = _on_opacity_changed
        self._blur_pixelate_handler = _on_pixelate_toggled
        self._blur_pixel_size_handler = _on_pixel_size_changed

        if hasattr(self, "blur_inspector_radius_slider"):
            self.blur_inspector_radius_slider.valueChanged.connect(_on_radius_changed)
        if hasattr(self, "blur_inspector_opacity_slider"):
            self.blur_inspector_opacity_slider.valueChanged.connect(_on_opacity_changed)
        if hasattr(self, "blur_inspector_pixelate_cb"):
            self.blur_inspector_pixelate_cb.toggled.connect(_on_pixelate_toggled)
        if hasattr(self, "blur_inspector_pixel_size_slider"):
            self.blur_inspector_pixel_size_slider.valueChanged.connect(_on_pixel_size_changed)


    def _sync_blur_layer_to_preview(self, layer):
        """Push a BlurLayer's per-region style back to the video preview
        + persisted state + B1 timeline regions (so the export matches).
        """
        if not hasattr(self, "video_view") or not hasattr(self.video_view, "blur_overlay"):
            return
        try:
            from app.layers.blur import BlurLayer
            regions = self.video_view.blur_overlay._regions or []
        except Exception:
            return
        # Find the index of this layer in the B1 track to map it to
        # the corresponding region in the video overlay.
        idx = -1
        if hasattr(self, "timeline") and self.timeline._timeline:
            for tr in self.timeline._timeline.tracks:
                if tr.id == layer.id or layer in tr.layers:
                    try:
                        idx = list(tr.layers).index(layer)
                    except ValueError:
                        idx = -1
                    break
        if idx < 0 or idx >= len(regions):
            return
        rect = regions[idx]
        try:
            x = float(rect.x())
            y = float(rect.y())
            w = float(rect.width())
            h = float(rect.height())
        except Exception:
            return
        # Build a single-region payload using this layer's style and
        # write it through the normal persist + preview path.
        payload = [{
            "x": x, "y": y, "width": w, "height": h,
            "blur_strength": int(getattr(layer, "blur_strength", 20)),
            "blur_opacity": float(getattr(layer, "blur_opacity", 1.0)),
            "pixelate": bool(getattr(layer, "pixelate", False)),
            "pixelate_size": int(getattr(layer, "pixelate_size", 12)),
        }]
        try:
            if hasattr(self.video_view, "set_blur_regions_normalized"):
                self.video_view.set_blur_regions_normalized(payload)
        except Exception:
            pass
        # Persist and re-apply the filter (so the export matches).
        if hasattr(self, "persist_project_blur_state"):
            try:
                self.persist_project_blur_state(regions=payload)
            except Exception:
                pass
        if hasattr(self, "apply_preview_blur_region"):
            try:
                self.apply_preview_blur_region(regions=payload, force=True)
            except Exception:
                pass
        # Push the new style onto the B1 track layers (one payload
        # entry per BlurLayer).
        if hasattr(self, "timeline") and self.timeline._timeline:
            from app.layers.blur import BlurLayer as _BL
            for tr in self.timeline._timeline.tracks:
                if tr.name == "B1":
                    for i, l in enumerate(tr.layers):
                        if i < len(payload):
                            l.blur_strength = int(payload[i].get("blur_strength", 20))
                            l.blur_opacity = float(payload[i].get("blur_opacity", 1.0))
                            l.pixelate = bool(payload[i].get("pixelate", False))
                            l.pixelate_size = int(payload[i].get("pixelate_size", 12))


    def _show_default_inspector(self):
        self._switch_inspector("default")


    def _text_layers(self):
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return []
        return [layer for track in self.timeline._timeline.tracks for layer in track.layers
                if str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower() == "text"]


    def _refresh_text_layer_preview(self, active_id=""):
        if not hasattr(self, "video_view") or not hasattr(self.video_view, "set_text_layers"):
            return
        from app.layers.text import TEXT_LAYER_EXPORT_SCALE
        # Use the same source-to-preview calibration as the editable
        # subtitle overlay. TextLayer.font_size is authored at source-video
        # scale (60 px at 100%), while QFont draws in preview pixels.
        render_h = max(1, int(getattr(self.video_view, "subtitle_render_height", 0) or 0))
        if render_h <= 1:
            _render_w, render_h = self._subtitle_render_dimensions()
        preview_rect = self.video_view.get_preview_canvas_rect()
        # Preview canvases can be smaller than the output canvas on laptops
        # or after moving the Preview/Timeline splitter. Preserve the real
        # source-to-preview scale in both directions; the old 1.0 floor kept
        # Text at export size instead of matching the visible canvas.
        preview_scale = max(
            0.01,
            float(preview_rect.height() or self.video_view.height() or 1.0) / max(1, render_h),
        )
        preview_text_scale = preview_scale * TEXT_LAYER_EXPORT_SCALE
        items = []
        is_editable = (
            not self._preview_is_playing()
            and str(active_id or "")
            and str(active_id or "") == str(getattr(self, "_preview_edit_layer_id", "") or "")
        )
        effective_active_id = str(active_id or "") if is_editable else ""
        if not bool(getattr(self, "_text_track_preview_visible", True)):
            self.video_view.set_text_layers([], active_id or getattr(self.timeline, "_selected_layer_id", ""))
            return
        for layer in self._text_layers():
            if not self._layer_is_active_at_preview_time(layer):
                continue
            transform = getattr(layer, "transform", None)
            items.append({
                "id": layer.id, "text": getattr(layer, "text", ""),
                "font_name": getattr(layer, "font_name", "Arial"),
                "font_size": max(1, int(round(float(getattr(layer, "font_size", 60)) * preview_text_scale))),
                "font_color": getattr(layer, "font_color", "#FFFFFF"),
                "background_color": getattr(layer, "background_color", ""),
                "background_opacity": max(0.0, min(1.0, float(getattr(layer, "background_opacity", 0.5) or 0.0))),
                "font_bold": getattr(layer, "font_bold", False),
                "font_italic": getattr(layer, "font_italic", False),
                "font_underline": getattr(layer, "font_underline", False),
                # The shared Qt renderer scales its source-space padding with
                # the preview canvas just like glyph size, so export and the
                # editor use the same physical box geometry.
                "padding_scale": preview_scale,
                "x": getattr(transform, "x", .5) if transform else .5,
                "y": getattr(transform, "y", .5) if transform else .5,
            })
        self.video_view.set_text_layers(items, effective_active_id)
        if getattr(self.video_view, "text_overlay", None) is not None:
            self.video_view.text_overlay.set_editable(bool(is_editable))


    def _show_text_inspector_for_track(self, track, layer):
        self._switch_inspector("text")
        self._wire_text_inspector_controls()
        self._wire_layer_timing_controls("text")
        self._set_layer_timing_controls("text", layer)
        self.text_inspector_content.blockSignals(True)
        self.text_inspector_content.setPlainText(str(getattr(layer, "text", "")))
        self.text_inspector_content.blockSignals(False)
        self.text_inspector_font_combo.blockSignals(True)
        font_name = str(getattr(layer, "font_name", "Arial"))
        if self.text_inspector_font_combo.findText(font_name) < 0:
            self.text_inspector_font_combo.addItem(font_name)
        self.text_inspector_font_combo.setCurrentText(font_name)
        self.text_inspector_font_combo.blockSignals(False)
        size = int(getattr(layer, "font_size", 60))
        choices = [int(self.text_inspector_size_combo.itemData(i)) for i in range(self.text_inspector_size_combo.count())]
        nearest = min(choices, key=lambda percent: abs(60 * percent / 100.0 - size))
        self.text_inspector_size_combo.blockSignals(True)
        self.text_inspector_size_combo.setCurrentIndex(self.text_inspector_size_combo.findData(nearest))
        self.text_inspector_size_combo.blockSignals(False)
        color = str(getattr(layer, "font_color", "#FFFFFF"))
        self.text_inspector_color_btn.setText(color)
        self.text_inspector_color_btn.setStyleSheet(f"background-color: {color}; color: #fff;")
        bg = str(getattr(layer, "background_color", "") or "")
        self.text_inspector_background_btn.setText(bg or "None")
        self.text_inspector_background_btn.setStyleSheet(f"background-color: {bg or '#26364a'}; color: #fff;")
        opacity = max(0, min(100, int(round(float(getattr(layer, "background_opacity", 0.5) or 0.0) * 100))))
        self.text_inspector_background_opacity_slider.blockSignals(True)
        self.text_inspector_background_opacity_slider.setValue(opacity)
        self.text_inspector_background_opacity_slider.blockSignals(False)
        self.text_inspector_background_opacity_value.setText(f"{opacity}%")
        self.text_inspector_summary_label.setText(f"Selected: {getattr(track, 'name', 'T1 Text')} → {getattr(layer, 'name', 'Text')}. Drag it on the preview to move it.")


    def _wire_text_inspector_controls(self):
        if getattr(self, "_text_inspector_wired", False):
            return
        self._text_inspector_wired = True
        def selected():
            sid = getattr(self.timeline, "_selected_layer_id", "")
            return next((layer for layer in self._text_layers() if layer.id == sid), None)
        def changed():
            layer = selected()
            if layer:
                self._refresh_text_layer_preview(layer.id)
                self.schedule_timeline_project_persist()
        def content_changed():
            layer = selected()
            if layer:
                text = self.text_inspector_content.toPlainText()
                if not text.strip():
                    text = "Text"
                    self.text_inspector_content.blockSignals(True)
                    self.text_inspector_content.setPlainText(text)
                    self.text_inspector_content.blockSignals(False)
                layer.text = text
                first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Text")
                layer.name = first_line[:24] or "Text"
                self.timeline._redraw(); changed()
        def size_changed(_index):
            layer = selected()
            if layer:
                percent = int(self.text_inspector_size_combo.currentData() or 100)
                layer.font_size = int(round(60 * percent / 100.0)); changed()
        def font_changed(value):
            layer = selected()
            if layer: layer.font_name = str(value); changed()
        def color_changed():
            from PySide6.QtWidgets import QColorDialog
            from PySide6.QtGui import QAction, QColor
            layer = selected()
            chosen = QColorDialog.getColor(QColor(getattr(layer, "font_color", "#FFFFFF")), self, "Pick text color")
            if layer and chosen.isValid():
                layer.font_color = chosen.name(); self.text_inspector_color_btn.setText(layer.font_color)
                self.text_inspector_color_btn.setStyleSheet(f"background-color: {layer.font_color}; color: #fff;"); changed()
        def background_changed():
            layer = selected()
            if layer is None: return
            current = QColor(str(getattr(layer, "background_color", "") or "#000000"))
            chosen = QColorDialog.getColor(current, self, "Choose Text Background Color")
            if chosen.isValid():
                layer.background_color = chosen.name()
                self.text_inspector_background_btn.setText(layer.background_color)
                self.text_inspector_background_btn.setStyleSheet(f"background-color: {layer.background_color}; color: #fff;"); changed()
        def background_opacity_changed(value):
            layer = selected()
            if layer is not None:
                value = max(0, min(100, int(value)))
                layer.background_opacity = value / 100.0
                self.text_inspector_background_opacity_value.setText(f"{value}%")
                changed()
        self.text_inspector_content.textChanged.connect(content_changed)
        self.text_inspector_size_combo.currentIndexChanged.connect(size_changed)
        self.text_inspector_font_combo.currentTextChanged.connect(font_changed)
        self.text_inspector_color_btn.clicked.connect(color_changed)
        self.text_inspector_background_btn.clicked.connect(background_changed)
        self.text_inspector_background_opacity_slider.valueChanged.connect(background_opacity_changed)


    def _show_logo_inspector_for_track(self, track, layer=None):
        """Show the Logo Track Inspector populated with the selected L1 layer."""
        self._switch_inspector("logo")
        self._wire_logo_inspector_controls()
        self._wire_layer_timing_controls("logo")
        if layer is None:
            return
        self._set_layer_timing_controls("logo", layer)
        # Read current opacity/rotation from the layer and apply to the
        # inspector controls.
        opacity = float(getattr(layer, "opacity", 1.0) or 1.0)
        rotation = 0.0
        try:
            transform = getattr(layer, "transform", None)
            if transform is not None and hasattr(transform, "rotation"):
                rotation = float(getattr(transform, "rotation", 0.0) or 0.0)
        except Exception:
            rotation = 0.0
        if hasattr(self, "logo_inspector_opacity_slider"):
            self.logo_inspector_opacity_slider.blockSignals(True)
            self.logo_inspector_opacity_slider.setValue(int(round(opacity * 100)))
            self.logo_inspector_opacity_slider.blockSignals(False)
        if hasattr(self, "logo_inspector_opacity_value_label"):
            self.logo_inspector_opacity_value_label.setText(f"{int(round(opacity * 100))}%")
        if hasattr(self, "logo_inspector_rotation_slider"):
            self.logo_inspector_rotation_slider.blockSignals(True)
            self.logo_inspector_rotation_slider.setValue(int(round(rotation)))
            self.logo_inspector_rotation_slider.blockSignals(False)
        if hasattr(self, "logo_inspector_rotation_value_label"):
            self.logo_inspector_rotation_value_label.setText(f"{int(round(rotation))}°")
        if hasattr(self, "logo_inspector_summary_label"):
            tname = getattr(track, "name", "L1 Logo")
            lname = getattr(layer, "name", "Logo")
            self.logo_inspector_summary_label.setText(
                f"Selected: {tname} → {lname}. "
                "Adjust opacity and rotation below; drag the logo on the "
                "preview to reposition."
            )


    def _wire_logo_inspector_controls(self):
        """One-time wiring of the Logo Inspector's opacity/rotation controls."""
        if getattr(self, "_logo_inspector_wired", False):
            return
        self._logo_inspector_wired = True

        def _on_opacity_changed(value, l=None):
            if l is None:
                l = getattr(self, "_logo_overlay_layer", None)
            if l is None:
                return
            opacity = max(0.0, min(1.0, float(value) / 100.0))
            try:
                l.opacity = opacity
            except Exception:
                pass
            if hasattr(self, "logo_inspector_opacity_value_label"):
                self.logo_inspector_opacity_value_label.setText(f"{int(value)}%")
            if hasattr(self, "video_view") and hasattr(self.video_view, "set_logo_opacity"):
                self.video_view.set_logo_opacity(opacity)

        def _on_rotation_changed(value, l=None):
            if l is None:
                l = getattr(self, "_logo_overlay_layer", None)
            if l is None:
                return
            rotation = float(value)
            try:
                from app.layers.transform import Transform
                transform = getattr(l, "transform", None) or Transform()
                transform.rotation = rotation
                l.transform = transform
            except Exception:
                pass
            if hasattr(self, "logo_inspector_rotation_value_label"):
                self.logo_inspector_rotation_value_label.setText(f"{int(value)}°")
            if hasattr(self, "video_view") and hasattr(self.video_view, "set_logo_rotation"):
                self.video_view.set_logo_rotation(rotation)

        # Store handlers so we can disconnect on re-wire.
        self._logo_opacity_handler = _on_opacity_changed
        self._logo_rotation_handler = _on_rotation_changed

        if hasattr(self, "logo_inspector_opacity_slider"):
            self.logo_inspector_opacity_slider.valueChanged.connect(_on_opacity_changed)
        if hasattr(self, "logo_inspector_rotation_slider"):
            self.logo_inspector_rotation_slider.valueChanged.connect(_on_rotation_changed)


    def _show_video_inspector_for_track(self, track, layer=None):
        """Show the Video Track Inspector (V1 Video)."""
        if not self._video_filter_inspector_available():
            self._switch_inspector("default")
            if hasattr(self, "default_inspector_summary_label"):
                self.default_inspector_summary_label.setText(
                    "Video Filter Inspector requires the gpu-next preview backend."
                )
            return
        self._switch_inspector("video")
        if track is None:
            return
        if hasattr(self, "video_inspector_summary_label"):
            self.video_inspector_summary_label.setText(
                "Adjust the preset, intensity and fine-tune each channel below."
            )
        # Populate the inline filter controls
        self._wire_video_inspector_controls()
        self._refresh_video_inspector_status()


    def _wire_video_inspector_controls(self):
        """One-time wiring of the inline video filter controls."""
        if getattr(self, "_video_inspector_wired", False):
            return
        # Preset combo
        if hasattr(self, "video_inspector_preset_combo"):
            preset_keys = (
                list(self._video_filter_presets().keys())
                if hasattr(self, "_video_filter_presets")
                else ["original", "bright", "warm", "vivid", "cool", "soft"]
            )
            preset_labels = {
                "original": "Original",
                "bright": "Bright",
                "warm": "Warm",
                "vivid": "Vivid",
                "cool": "Cool",
                "soft": "Soft",
            }
            for key in preset_keys:
                label = preset_labels.get(str(key), str(key).title())
                self.video_inspector_preset_combo.addItem(label, str(key))
            self.video_inspector_preset_combo.currentIndexChanged.connect(
                self._on_video_inspector_preset_changed
            )
        # Intensity
        if hasattr(self, "video_inspector_intensity_slider"):
            self.video_inspector_intensity_slider.valueChanged.connect(
                self._on_video_inspector_intensity_changed
            )
            self.video_inspector_intensity_slider.sliderReleased.connect(
                self._on_video_inspector_intensity_released
            )
        # Adjust sliders
        if hasattr(self, "video_inspector_adjust_sliders"):
            for field_key, (slider, value_lbl) in self.video_inspector_adjust_sliders.items():
                slider.valueChanged.connect(
                    lambda v, lbl=value_lbl, fk=field_key: self._on_video_inspector_adjust_changed(fk, v, lbl)
                )
                slider.sliderReleased.connect(
                    lambda fk=field_key: self._on_video_inspector_adjust_released(fk)
                )
        # Reset
        if hasattr(self, "video_inspector_reset_btn"):
            self.video_inspector_reset_btn.clicked.connect(self._on_video_inspector_reset)
        self._video_inspector_wired = True
        # Initial UI sync
        self._sync_video_inspector_ui()


    def _sync_video_inspector_ui(self):
        if hasattr(self, "video_inspector_preset_combo"):
            try:
                key = self._normalize_video_filter_preset_key(
                    getattr(self, "_video_filter_preset_key", "original")
                )
                for i in range(self.video_inspector_preset_combo.count()):
                    if self.video_inspector_preset_combo.itemData(i) == key:
                        self.video_inspector_preset_combo.blockSignals(True)
                        self.video_inspector_preset_combo.setCurrentIndex(i)
                        self.video_inspector_preset_combo.blockSignals(False)
                        break
            except Exception:
                pass
        if hasattr(self, "video_inspector_intensity_slider"):
            try:
                self.video_inspector_intensity_slider.blockSignals(True)
                self.video_inspector_intensity_slider.setValue(int(self._video_filter_intensity))
                self.video_inspector_intensity_slider.blockSignals(False)
            except Exception:
                pass
        if hasattr(self, "video_inspector_intensity_value_label"):
            try:
                self.video_inspector_intensity_value_label.setText(str(int(self._video_filter_intensity)))
            except Exception:
                pass
        if hasattr(self, "video_inspector_adjust_sliders"):
            overrides = getattr(self, "_video_filter_adjust_overrides", {}) or {}
            for field_key, (slider, value_lbl) in self.video_inspector_adjust_sliders.items():
                try:
                    val = int(overrides.get(field_key, 0))
                except Exception:
                    val = 0
                try:
                    slider.blockSignals(True)
                    slider.setValue(val)
                    slider.blockSignals(False)
                except Exception:
                    pass
                value_lbl.setText(str(val))


    def _refresh_video_inspector_status(self):
        try:
            if not hasattr(self, "video_inspector_status_label"):
                return
            try:
                active = bool(self.has_active_video_filters())
            except Exception:
                active = False
            realtime = self._is_realtime_color_filter_state()
            
            if active and realtime:
                self.video_inspector_status_label.setText("✓ Realtime preview")
                self.video_inspector_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            elif active:
                self.video_inspector_status_label.setText("✓ Filter applied")
                self.video_inspector_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.video_inspector_status_label.setText("No filter applied")
                self.video_inspector_status_label.setStyleSheet("color: #888; font-weight: normal;")
            if hasattr(self, "video_inspector_reset_btn"):
                self.video_inspector_reset_btn.setEnabled(self._video_filter_inspector_available())
        except Exception as e:
            if hasattr(self, "log"):
                self.log(f"[Filter] Status refresh error: {e}")


    def _on_video_inspector_intensity_changed(self, value: int):
        if hasattr(self, "video_inspector_intensity_value_label"):
            self.video_inspector_intensity_value_label.setText(str(int(value)))
        try:
            self.on_video_filter_intensity_changed(int(value))
        except Exception:
            pass
        self._refresh_video_inspector_status()


    def _on_video_inspector_intensity_released(self):
        if hasattr(self, "on_video_filter_slider_released"):
            try:
                self.on_video_filter_slider_released()
            except Exception:
                pass
        self._refresh_video_inspector_status()


    def _on_video_inspector_adjust_changed(self, field_key: str, value: int, value_lbl):
        value_lbl.setText(str(int(value)))
        self.on_video_filter_adjust_changed(field_key, int(value))
        self._refresh_video_inspector_status()


    def _on_video_inspector_adjust_released(self, field_key: str):
        if hasattr(self, "on_video_filter_slider_released"):
            try:
                self.on_video_filter_slider_released()
            except Exception:
                pass
        self._refresh_video_inspector_status()


    def _on_video_inspector_reset(self):
        self.reset_video_filters()
        self._refresh_video_inspector_status()
        if hasattr(self, "refresh_ui_state"):
            self.refresh_ui_state()


    def _current_blur_track_for_inspector(self):
        """Return the Blur Track currently displayed in the Blur inspector."""
        if not hasattr(self, "blur_inspector_track_name_label"):
            return None, None
        target = self.blur_inspector_track_name_label.text().strip()
        if not target or target == "-":
            return None, None
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return None, None
        for t in self.timeline._timeline.tracks:
            if t.name == target:
                return t, target
        return None, None


    def on_blur_inspector_show_toggled(self, checked: bool):
        """Toggle whether the blur is rendered on the video preview.

        The blur layers remain in the timeline; only the visual mpv vf
        filter is toggled on/off via the media player's blur region.
        """
        track, _track_name = self._current_blur_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_show_on_preview"] = bool(checked)
        if hasattr(self, "media_player") and self.media_player is not None:
            if checked:
                # Re-apply the blur region to the media player.
                if hasattr(self, "apply_preview_blur_region"):
                    try:
                        self.apply_preview_blur_region(force=True)
                    except Exception:
                        pass
            else:
                # Clear the blur vf filter but keep the layer data.
                try:
                    self.media_player.clear_blur_region()
                except Exception:
                    pass
        if hasattr(self, "blur_inspector_summary_label"):
            state = "shown" if checked else "hidden"
            self.blur_inspector_summary_label.setText(
                f"The visual blur is currently {state} on the video preview."
            )


    def _switch_inspector(self, kind: str):
        if not hasattr(self, "inspector_stack"):
            return
        idx_map = {
            "subtitle": 0,
            "audio": 1,
            "blur": 2,
            "video": 3,
            "default": 4,
            "logo": 5,
            "mask": 6,
            "text": 7,
        }
        target = idx_map.get(kind, 4)
        if self.inspector_stack.currentIndex() != target:
            self.inspector_stack.setCurrentIndex(target)
        # The handle/toggle button is always visible so the user can
        # The handle/toggle UI was removed - the track inspector is
        # always expanded. No need to show/hide a handle.
        # Clicking a track layer opens the inspector (auto-expand shell).
        if kind in ("subtitle", "audio", "blur", "video", "logo", "mask", "text"):
            self.set_inspector_collapsed(False)


    def _current_audio_track_for_inspector(self):
        """Return the Track object currently displayed in the audio inspector."""
        if not hasattr(self, "audio_inspector_card") or not hasattr(self, "timeline"):
            return None, None
        if not self.timeline._timeline:
            return None, None
        if not hasattr(self, "audio_inspector_track_name_label"):
            return None, None
        target = self.audio_inspector_track_name_label.text().strip()
        if not target or target == "-":
            return None, None
        for t in self.timeline._timeline.tracks:
            if t.name == target:
                return t, target
        return None, None


    def on_audio_inspector_gain_changed(self, value: float):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_gain_db"] = float(value)
        self._apply_audio_track_settings(track_name)


    def on_audio_inspector_speed_changed(self, value: float):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_speed"] = float(value)
        self._apply_audio_track_settings(track_name)


    def on_audio_inspector_fade_in_changed(self, value: float):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_fade_in"] = float(value)
        self._apply_audio_track_settings(track_name)


    def on_audio_inspector_fade_out_changed(self, value: float):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_fade_out"] = float(value)
        self._apply_audio_track_settings(track_name)


    def on_audio_inspector_mute_toggled(self, checked: bool):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_muted"] = bool(checked)
        track.muted = bool(checked)
        if hasattr(self, "audio_inspector_mute_btn"):
            self.audio_inspector_mute_btn.setText(
                "Unmute Track" if checked else "Mute Track"
            )
        self._apply_audio_track_settings(track_name)


    def on_audio_inspector_solo_toggled(self, checked: bool):
        track, track_name = self._current_audio_track_for_inspector()
        if track is None:
            return
        if not isinstance(track.metadata, dict):
            track.metadata = {}
        track.metadata["_solo"] = bool(checked)
        self._apply_audio_track_settings(track_name)
        # Solo changes affect every other audio track.  Re-apply the two
        # preview sidecars (and rebuild the composed Music/TTS sidecar when
        # present) so preview follows the same routing used by export.
        if track_name != "A1 Audio":
            self._apply_audio_track_settings("A1 Audio")
        if track_name not in ("A2 Dub", "TS1"):
            self._apply_audio_track_settings("TS1")
        if self._music_audio_tracks():
            self._schedule_preview_audio_refresh(force=True)


    def _refresh_audio_inspector_dub_voice_buttons(self):
        """Enable/disable Dub Voice buttons and populate shared/tabs."""
        idx = int(getattr(self, "_selected_segment_index", -1))
        segments = self.get_active_segments() or []
        valid = 0 <= idx < len(segments)
        seg = segments[idx] if valid and isinstance(segments[idx], dict) else {}
        translation_ready = self._translation_phase_complete()
        for attr in (
            "audio_inspector_use_voice_btn",
            "audio_inspector_regenerate_voice_btn",
        ):
            btn = getattr(self, attr, None)
            if btn is not None:
                # These actions only make sense once translated subtitle
                # data exists.  Keep them out of the inspector until the
                # Translation phase has completed successfully.
                btn.setVisible(translation_ready)
                btn.setEnabled(valid and translation_ready)
        # Shared section: Original text
        orig_lbl = getattr(self, "inspector_original_text_label", None)
        orig_widget = getattr(self, "inspector_shared_original_label", None)
        if orig_lbl is not None:
            orig_text = ""
            if valid:
                row = self._find_segment_editor_row(idx)
                if row is not None:
                    orig_text = str(row.get("original", "") or "")
                if not orig_text:
                    orig_text = str(
                        seg.get("source_text", "")
                        or seg.get("original_text", "")
                        or seg.get("text", "")
                        or ""
                    )
            orig_lbl.setText(orig_text if orig_text else "")
            if orig_widget is not None:
                orig_widget.setVisible(bool(orig_text))


    def on_audio_inspector_regenerate_voice_clicked(self):
        if not self._translation_phase_complete():
            QMessageBox.information(self, "Voice Unavailable", "Complete the Translation phase before generating subtitle voice audio.")
            return
        idx = int(getattr(self, "_selected_segment_index", -1))
        segments = self.get_active_segments() or []
        if not (0 <= idx < len(segments)):
            return
        self.preview_segment_audio(idx)


    def on_track_blur_toggled(self, track_name: str, is_on: bool):
        """Handle B1 track label click - toggle blur effect."""
        if not hasattr(self, "blur_area_btn"):
            return
        self.blur_area_btn.blockSignals(True)
        self.blur_area_btn.setChecked(bool(is_on))
        self.blur_area_btn.blockSignals(False)
        try:
            self.toggle_blur_effect_enabled(bool(is_on))
        except Exception:
            pass
        self.schedule_timeline_project_persist(blur_state=True)


    def on_track_logo_toggled(self, track_name: str, is_shown: bool):
        """Handle L1 track label click - hide or show the logo overlay."""
        self._logo_track_preview_visible = bool(is_shown)
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_logo_track_visible"):
            self.video_view.set_logo_track_visible(self._logo_track_preview_visible)
        # Force the next timed refresh to respect the new track state even if
        # the playhead remains at the same timestamp.
        self._timed_layer_preview_signature = None
        self.schedule_timeline_project_persist()
        if not hasattr(self, "video_view"):
            return
        if is_shown:
            # Restore only logos active at the current playhead.  This keeps
            # Hide/Show consistent with timed logo segments.
            self.refresh_timed_layer_preview()
        else:
            # Hide the logo overlay
            if hasattr(self.video_view, "clear_logo"):
                self.video_view.clear_logo()


    def on_track_mask_toggled(self, track_name: str, is_shown: bool):
        """Handle M1 track label click - show or hide the mask filter."""
        self._mask_track_preview_visible = bool(is_shown)
        self.schedule_timeline_project_persist(mask_state=True)
        if not hasattr(self, "media_player"):
            return
        if is_shown:
            # Re-apply the M1 mask filter from the timeline.
            try:
                self._apply_mask_to_preview()
            except Exception:
                pass
            # Re-show the mask overlay. A label click should restore M1 even
            # when another layer is selected (or the selection was cleared).
            try:
                if hasattr(self, "timeline") and self.timeline._timeline:
                    sid = getattr(self.timeline, "_selected_layer_id", "")
                    for tr in self.timeline._timeline.tracks:
                        if tr.name != "M1" or not tr.layers:
                            continue
                        layer = next((item for item in tr.layers if item.id == sid), tr.layers[0])
                        self._show_mask_overlay(tr, layer)
                        return
            except Exception:
                pass
        else:
            try:
                self.media_player.clear_mask_region()
            except Exception:
                pass
            if hasattr(self, "video_view") and hasattr(self.video_view, "clear_mask_region"):
                try:
                    self.video_view.clear_mask_region()
                except Exception:
                    pass


    def is_inspector_anchored(self) -> bool:
        checkbox = getattr(self, "anchor_inspector_cb", None)
        return bool(checkbox and checkbox.isChecked())


    def set_inspector_collapsed(self, collapsed: bool):
        """Collapse or expand the inspector shell. The track layer
        inspector is always expanded - collapse is disabled.
        """
        collapsed = False
        self._inspector_collapsed = False
        # Sync shell width
        try:
            self._sync_subtitle_inspector_shell_width(visible=not bool(collapsed))
        except Exception:
            pass
        # Hide the entire stack so no card content is visible when collapsed
        stack = getattr(self, "inspector_stack", None)
        if stack is not None:
            stack.setVisible(not bool(collapsed))
        # Sync subtitle details widget visibility to match
        widget = getattr(self, "subtitle_inspector_details_widget", None)
        if widget is not None:
            widget.setVisible(not bool(collapsed))
        # Sync toggle button
        toggle_btn = getattr(self, "subtitle_inspector_toggle_btn", None)
        if toggle_btn is not None:
            toggle_btn.blockSignals(True)
            toggle_btn.setChecked(not bool(collapsed))
            toggle_btn.setText("▶" if collapsed else "◀")
            toggle_btn.setToolTip(
                "Show track inspector" if collapsed else "Hide track inspector"
            )
            toggle_btn.blockSignals(False)


    def on_anchor_inspector_toggled(self, checked: bool):
        if checked:
            # Anchor means: keep the track inspector shell expanded
            # (whichever card is currently shown: subtitle, audio, blur
            # or default).
            self.set_inspector_collapsed(False)
        toggle_btn = getattr(self, "subtitle_inspector_toggle_btn", None)
        if toggle_btn is not None:
            toggle_btn.setEnabled(not checked)
        self.save_user_settings()


    def _blur_effect_enabled(self) -> bool:
        return bool(hasattr(self, "blur_area_btn") and self.blur_area_btn.isChecked())


    def _sync_blur_controls(self):
        video_view = getattr(self, "video_view", None)
        blur_btn = getattr(self, "blur_area_btn", None)
        blur_add_btn = getattr(self, "blur_add_btn", None)
        if video_view is None or blur_btn is None:
            return
        has_video = bool(self.video_path_edit.text().strip()) and os.path.exists(self.video_path_edit.text().strip())
        blur_enabled = self._blur_effect_enabled()
        is_playing = False
        media_player = getattr(self, "media_player", None)
        if media_player is not None:
            try:
                is_playing = bool(media_player.is_playing())
            except Exception:
                is_playing = False
        # The blur overlay (the draggable rectangle) is only shown
        # when the blur effect is ON. Turning the effect OFF hides
        # the rectangle; turning it ON shows it again for drag.
        has_regions = bool(self._current_blur_regions_payload())
        selected_id = str(getattr(getattr(self, "timeline", None), "_selected_layer_id", "") or "")
        selected_blur = False
        timeline_model = getattr(getattr(self, "timeline", None), "_timeline", None)
        for track in getattr(timeline_model, "tracks", []):
            if str(getattr(track, "name", "")) != "B1":
                continue
            selected_blur = any(str(getattr(layer, "id", "")) == selected_id for layer in getattr(track, "layers", []))
            break
        editing_allowed = (
            blur_enabled
            and has_video
            and has_regions
            and selected_blur
            and not is_playing
            and not bool(getattr(self, "_filter_thumbnail_visible", False))
        )
        if hasattr(video_view, "set_blur_edit_enabled"):
            video_view.set_blur_edit_enabled(editing_allowed)
        if blur_add_btn is not None:
            # The "+" button must be clickable even when the blur effect
            # toggle is OFF: pressing it should both enable the effect
            # AND add a region. Requiring the user to toggle first is
            # unnecessary friction.
            blur_add_btn.setEnabled(
                bool(getattr(self, "_optional_layer_controls_ready", False))
                and has_video
                and not is_playing
                and not bool(getattr(self, "_filter_thumbnail_visible", False))
            )


    def toggle_blur_effect_enabled(self, checked: bool):
        if not hasattr(self, "video_view") or not hasattr(self, "blur_area_btn"):
            return
        has_video = bool(self.video_path_edit.text().strip()) and os.path.exists(self.video_path_edit.text().strip())
        if checked and not has_video:
            self.blur_area_btn.blockSignals(True)
            self.blur_area_btn.setChecked(False)
            self.blur_area_btn.blockSignals(False)
            QMessageBox.warning(self, "Blur Area", "Please load a video before adding a blur area.")
            return
        # The B1 header visibility control is the single visibility source.
        # Update the managed MPV effect immediately, including while paused.
        self._sync_blur_controls()
        if hasattr(self, "media_player"):
            if checked:
                self.apply_preview_blur_region(force=True)
            else:
                self.media_player.clear_blur_region()
        self.persist_project_blur_state()
        # Sync the B1 track label so the ON/OFF indicator matches
        if hasattr(self, "track_label_bar"):
            try:
                self.track_label_bar.set_blur_on("B1", bool(checked))
            except Exception:
                pass
        if checked:
            self.log("[Blur Area] blur effect enabled.")


    def add_blur_region(self):
        if not hasattr(self, "video_view"):
            return
        has_video = bool(self.video_path_edit.text().strip()) and os.path.exists(self.video_path_edit.text().strip())
        if not has_video:
            QMessageBox.warning(self, "Blur Area", "Please load a video before adding a blur area.")
            return
        if hasattr(self, "blur_area_btn") and not self.blur_area_btn.isChecked():
            self.blur_area_btn.blockSignals(True)
            self.blur_area_btn.setChecked(True)
            self.blur_area_btn.blockSignals(False)
        if hasattr(self.video_view, "add_blur_region"):
            self.video_view.add_blur_region()
        # Do NOT call on_add_timeline_layer("blur") here. The
        # blurRegionChanged signal emitted by add_blur_region() will
        # trigger on_preview_blur_region_changed() which (with the
        # recent fix) syncs the B1 track from the overlay regions
        # even when the blur effect is on. Adding a BlurLayer here too
        # would create a duplicate.
        self._sync_blur_controls()
        self._blur_region_preview_dirty = True
        if hasattr(self, "media_player"):
            self.media_player.clear_blur_region()
        self.persist_project_blur_state()


    def on_blur_edit_finished(self):
        if getattr(self, "_blur_edit_finish_syncing", False):
            return
        if not self._blur_effect_enabled():
            return
        self._blur_region_preview_dirty = True
        self.schedule_timeline_project_persist(blur_state=True)


    def on_preview_blur_region_changed(self):
        if self._preview_is_playing():
            return
        if self._blur_effect_enabled():
            self._blur_region_preview_dirty = True
            # Even when the blur effect is on, the B1 track in the
            # timeline must stay in sync with the overlay regions. Without
            # this, deleting a region from the overlay leaves a stale
            # BlurLayer behind in the timeline. The actual mpv blur
            # effect is only updated when the video plays, to keep
            # editing fast.
            if hasattr(self, "timeline"):
                try:
                    regions = self._current_blur_regions_payload() if hasattr(self, "_current_blur_regions_payload") else []
                    self.timeline.sync_blur_regions(regions)
                    self.schedule_timeline_project_persist(blur_state=True)
                except Exception:
                    pass
            return
        self.apply_preview_blur_region()
        self.schedule_timeline_project_persist(blur_state=True)
        if hasattr(self, "timeline"):
            regions = self._current_blur_regions_payload() if hasattr(self, "_current_blur_regions_payload") else []
            self.timeline.sync_blur_regions(regions)


    def apply_preview_blur_region(self, *, regions=None, force: bool = False):
        if not hasattr(self, "media_player") or not hasattr(self, "video_view"):
            return
        self._blur_region_preview_dirty = False
        blur_enabled = self._blur_effect_enabled()
        if regions is not None:
            blur_region = regions
        else:
            blur_region = self._current_blur_regions_payload()
            suppressed_id = self._deferred_effect_layer_id_for("blur")
            if suppressed_id and isinstance(blur_region, list):
                blur_layers = []
                timeline_model = getattr(getattr(self, "timeline", None), "_timeline", None)
                for track in list(getattr(timeline_model, "tracks", []) or []):
                    if str(getattr(track, "name", "") or "") == "B1":
                        blur_layers = list(getattr(track, "layers", []) or [])
                        break
                if len(blur_layers) == len(blur_region):
                    blur_region = [
                        region for region, layer in zip(blur_region, blur_layers)
                        if str(getattr(layer, "id", "") or "") != suppressed_id
                    ]
        # Always apply the blur when enabled and regions exist, even
        # when the video is paused, so the user can see the cached
        # blur effect on the video preview.
        if blur_enabled and blur_region:
            self.media_player.set_blur_region(blur_region)
        else:
            self.media_player.clear_blur_region()


    def _current_blur_regions_payload(self):
        if not hasattr(self, "video_view") or not hasattr(self.video_view, "get_blur_region_normalized"):
            return []
        raw_regions = self.video_view.get_blur_region_normalized()
        if isinstance(raw_regions, dict):
            raw_regions = [raw_regions]
        if not isinstance(raw_regions, list):
            return []
        regions = []
        for region in raw_regions:
            if not isinstance(region, dict):
                continue
            try:
                x = max(0.0, min(1.0, float(region.get("x", 0.0))))
                y = max(0.0, min(1.0, float(region.get("y", 0.0))))
                width = max(0.0, min(1.0 - x, float(region.get("width", 0.0))))
                height = max(0.0, min(1.0 - y, float(region.get("height", 0.0))))
            except (TypeError, ValueError):
                continue
            if width <= 0.0 or height <= 0.0:
                continue
            entry = {
                "x": round(x, 6),
                "y": round(y, 6),
                "width": round(width, 6),
                "height": round(height, 6),
            }
            # Per-region style (radius, opacity, pixelate). Defaults
            # are chosen so an existing region without these keys
            # behaves the same as before the inspector was added.
            try:
                strength = region.get("blur_strength", region.get("strength"))
                if strength is not None:
                    entry["blur_strength"] = int(round(float(strength)))
            except (TypeError, ValueError):
                pass
            try:
                opacity = region.get("blur_opacity", region.get("opacity"))
                if opacity is not None:
                    entry["blur_opacity"] = round(float(opacity), 4)
            except (TypeError, ValueError):
                pass
            if bool(region.get("pixelate", False)):
                entry["pixelate"] = True
                try:
                    entry["pixelate_size"] = int(region.get("pixelate_size", 12))
                except (TypeError, ValueError):
                    entry["pixelate_size"] = 12
            regions.append(entry)
        # Preview rectangles store geometry only. Preserve timing and per-layer
        # style from B1 whenever its layers correspond one-to-one with those
        # rectangles. This is essential after splitting: a blur piece remains
        # an independent timed layer instead of being rebuilt as a full-video
        # region by the preview-to-timeline sync.
        blur_layers = []
        timeline_model = getattr(getattr(self, "timeline", None), "_timeline", None)
        for track in list(getattr(timeline_model, "tracks", []) or []):
            if str(getattr(track, "name", "") or "") == "B1":
                blur_layers = list(getattr(track, "layers", []) or [])
                break
        if blur_layers and len(blur_layers) != len(regions):
            # A split layer can produce several timeline clips that share
            # one original preview rectangle. In that case the timeline is
            # authoritative: expand its independent clips back into payload
            # entries rather than collapsing them to the single rectangle.
            regions = []
            for layer in blur_layers:
                try:
                    regions.append({
                        "x": round(float(getattr(layer, "position_x", 0.0) or 0.0), 6),
                        "y": round(float(getattr(layer, "position_y", 0.0) or 0.0), 6),
                        "width": round(float(getattr(layer, "width", 0.0) or 0.0), 6),
                        "height": round(float(getattr(layer, "height", 0.0) or 0.0), 6),
                        "start": float(getattr(layer, "start", 0.0) or 0.0),
                        "end": float(getattr(layer, "end", 0.0) or 0.0),
                        "blur_strength": float(getattr(layer, "blur_strength", 20.0) or 20.0),
                        "blur_opacity": float(getattr(layer, "blur_opacity", 1.0) or 1.0),
                        "pixelate": bool(getattr(layer, "pixelate", False)),
                        "pixelate_size": int(getattr(layer, "pixelate_size", 12) or 12),
                    })
                except (TypeError, ValueError):
                    continue
        elif len(blur_layers) == len(regions):
            for entry, layer in zip(regions, blur_layers):
                try:
                    entry["start"] = float(getattr(layer, "start", 0.0) or 0.0)
                    entry["end"] = float(getattr(layer, "end", 0.0) or 0.0)
                    entry["blur_strength"] = float(getattr(layer, "blur_strength", entry.get("blur_strength", 20)) or 20)
                    entry["blur_opacity"] = float(getattr(layer, "blur_opacity", entry.get("blur_opacity", 1.0)) or 1.0)
                    entry["pixelate"] = bool(getattr(layer, "pixelate", entry.get("pixelate", False)))
                    entry["pixelate_size"] = int(getattr(layer, "pixelate_size", entry.get("pixelate_size", 12)) or 12)
                except (TypeError, ValueError):
                    continue
        return regions


    def persist_project_blur_state(self, *, regions=None, enabled=None):
        state = getattr(self, "current_project_state", None)
        if not state:
            return
        if regions is None:
            regions = self._current_blur_regions_payload()
        if enabled is None:
            enabled = self._blur_effect_enabled()
        blur_state = {
            "enabled": bool(enabled),
            "regions": list(regions or []),
        }
        if state.settings.get("blur_state") == blur_state:
            return
        state.set_setting("blur_state", blur_state)
        self.project_service.save_project(state)


    def _restore_project_blur_state(self, state):
        blur_state = dict(getattr(state, "settings", {}).get("blur_state") or {})
        regions = blur_state.get("regions", [])
        # A serialized timeline is authoritative for optional layers.  The
        # legacy blur_state setting can be stale after deleting the last B1
        # layer, so never use it to recreate a deleted layer on reopen.
        if getattr(self, "_saved_timeline_model_restored", False):
            timeline_model = getattr(getattr(self, "timeline", None), "_timeline", None)
            timeline_layers = []
            for track in getattr(timeline_model, "tracks", []) or []:
                if str(getattr(track, "name", "") or "") == "B1":
                    timeline_layers = list(getattr(track, "layers", []) or [])
                    break
            regions = []
            for layer in timeline_layers:
                try:
                    regions.append({
                        "x": float(getattr(layer, "position_x", 0.0) or 0.0),
                        "y": float(getattr(layer, "position_y", 0.0) or 0.0),
                        "width": float(getattr(layer, "width", 0.0) or 0.0),
                        "height": float(getattr(layer, "height", 0.0) or 0.0),
                        "start": float(getattr(layer, "start", 0.0) or 0.0),
                        "end": float(getattr(layer, "end", 0.0) or 0.0),
                        "blur_strength": float(getattr(layer, "blur_strength", 20.0) or 20.0),
                        "blur_opacity": float(getattr(layer, "blur_opacity", 1.0) or 1.0),
                        "pixelate": bool(getattr(layer, "pixelate", False)),
                        "pixelate_size": int(getattr(layer, "pixelate_size", 12) or 12),
                    })
                except (TypeError, ValueError):
                    continue
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_blur_regions_normalized"):
            self.video_view.set_blur_regions_normalized(regions)
        # Restore the B1 track visibility instead of forcing Blur back on.
        # Older projects did not save this value and therefore default to ON.
        blur_enabled = bool(blur_state.get("enabled", True))
        if hasattr(self, "blur_area_btn"):
            self.blur_area_btn.blockSignals(True)
            self.blur_area_btn.setChecked(blur_enabled)
            self.blur_area_btn.blockSignals(False)
        self._sync_blur_controls()
        if hasattr(self, "track_label_bar"):
            try:
                self.track_label_bar.set_blur_on("B1", blur_enabled)
            except Exception:
                pass
        if hasattr(self, "timeline") and not getattr(self, "_saved_timeline_model_restored", False):
            self.timeline.sync_blur_regions(regions)
        if hasattr(self, "media_player"):
            try:
                if blur_enabled:
                    self.apply_preview_blur_region(force=True)
                else:
                    self.media_player.clear_blur_region()
            except Exception:
                self.media_player.clear_blur_region()


    def _current_mask_regions_payload(self, *, time_seconds=None, include_inactive=False,
                                      exclude_layer_id: str = ""):
        """Build the mask payload from the M1 track's MaskLayers.

        Visibility is NOT checked here — the play-state gate in
        _apply_mask_to_preview is the single source of truth for
        whether the mask is shown on the video. The payload always
        includes every M1 layer so the mask is ready the moment the
        user presses play.
        """
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return []
        items: list[dict] = []
        for tr in self.timeline._timeline.tracks:
            if tr.name != "M1":
                continue
            for layer in tr.layers:
                if exclude_layer_id and str(getattr(layer, "id", "") or "") == str(exclude_layer_id):
                    continue
                if not include_inactive and not self._layer_is_active_at_preview_time(layer, time_seconds):
                    continue
                try:
                    items.append({
                        "x": float(getattr(layer, "position_x", 0.3)),
                        "y": float(getattr(layer, "position_y", 0.4)),
                        "width": float(getattr(layer, "width", 0.4)),
                        "height": float(getattr(layer, "height", 0.2)),
                        "color": str(getattr(layer, "color", "#000000")),
                        "mode": str(getattr(layer, "mode", "solid")),
                        "opacity": float(getattr(layer, "opacity", 1.0)),
                        "pixelate_size": int(getattr(layer, "pixelate_size", 12)),
                        "blur_strength": int(getattr(layer, "blur_strength", 20)),
                        "start": float(getattr(layer, "start", 0.0) or 0.0),
                        "end": float(getattr(layer, "end", 0.0) or 0.0),
                    })
                except (TypeError, ValueError):
                    continue
        return items


    def _apply_mask_to_preview(self, *, regions=None, force: bool = False):
        """Push the M1 mask track into the mpv filter chain.

        The mask effect is independent of timeline selection and playback
        state.  Pausing or selecting another layer must not remove it from
        the preview; only the dedicated M1 visibility control (or an empty
        mask track) may clear the effect.  The editable outline/handles are
        managed separately by the timeline selection.

        `force=True` bypasses the play-state gate (used by direct
        calls from `toggle_play` so the mask is applied/cleared in
        the same code path as the play/pause).
        """
        if not hasattr(self, "media_player"):
            return
        # M1 Hide/Show must survive play/pause, project restoration, and
        # native-window focus changes.  Never rebuild a hidden mask graph.
        if not bool(getattr(self, "_mask_track_preview_visible", True)):
            self.media_player.clear_mask_region()
            return
        if regions is None:
            regions = self._current_mask_regions_payload(
                include_inactive=True,
                exclude_layer_id=self._deferred_effect_layer_id_for("mask"),
            )
        if force:
            if regions:
                self.media_player.set_mask_region(regions)
            else:
                if hasattr(self.media_player, "clear_mask_region"):
                    self.media_player.clear_mask_region()
            return
        if regions:
            if hasattr(self.media_player, "set_mask_region"):
                self.media_player.set_mask_region(regions)
        else:
            if hasattr(self.media_player, "clear_mask_region"):
                self.media_player.clear_mask_region()


    def persist_project_mask_state(self, *, regions=None):
        state = getattr(self, "current_project_state", None)
        if not state:
            return
        if regions is None:
            regions = self._current_mask_regions_payload()
        mask_state = {
            "enabled": bool(getattr(self, "_mask_track_preview_visible", True)),
            "regions": list(regions or []),
        }
        if state.settings.get("mask_state") == mask_state:
            return
        state.set_setting("mask_state", mask_state)
        self.project_service.save_project(state)


    def _restore_project_mask_state(self, state):
        mask_state = dict(getattr(state, "settings", {}).get("mask_state") or {})
        regions = mask_state.get("regions", [])
        timeline_model_restored = bool(getattr(self, "_saved_timeline_model_restored", False))
        if timeline_model_restored:
            # The saved M1 track is authoritative.  In particular, an empty
            # M1 track means the user deleted the final mask and must not be
            # reconstructed from the legacy mask_state setting.
            regions = self._current_mask_regions_payload(include_inactive=True)
        if hasattr(self, "media_player"):
            self._apply_mask_to_preview(regions=regions, force=True)
        if hasattr(self, "track_label_bar"):
            try:
                self.track_label_bar.set_mask_shown(
                    "M1", bool(getattr(self, "_mask_track_preview_visible", True))
                )
            except Exception:
                pass
        # Sync the M1 track from legacy settings only when no serialized
        # timeline was available.  Otherwise this method must not recreate
        # deleted layers or overwrite their timing/style properties.
        if hasattr(self, "timeline") and regions and not timeline_model_restored:
            try:
                from app.layers.mask import MaskLayer
                from app.layers.sync_bridge import find_or_create_track
                from app.layers.base import LayerType
                tl = self.timeline._timeline
                track = find_or_create_track(tl, "M1", LayerType.MASK, 60)
                track.layers.clear()
                # Mask layers span the full video duration (like the
                # audio track) so the M1 row matches the video length
                # rather than collapsing to a zero-width clip (Bug 1).
                mask_end = tl.duration if tl.duration > 0 else (
                    self.timeline._duration if hasattr(self.timeline, "_duration") else 0.0
                )
                if mask_end <= 0:
                    mask_end = 5.0
                for i, r in enumerate(regions):
                    layer = MaskLayer(
                        name=f"Mask {i + 1}",
                        position_x=float(r.get("x", 0.3)),
                        position_y=float(r.get("y", 0.4)),
                        width=float(r.get("width", 0.4)),
                        height=float(r.get("height", 0.2)),
                        color=str(r.get("color", "#000000")),
                        mode=str(r.get("mode", "solid")),
                        pixelate_size=int(r.get("pixelate_size", 12)),
                        blur_strength=int(r.get("blur_strength", 20)),
                        start=0.0,
                        end=float(mask_end),
                    )
                    layer.z_index = i
                    track.layers.append(layer)
                if hasattr(self.timeline, "_track_heights"):
                    self.timeline._track_heights[track.id] = 60
                self.timeline._redraw()
                # Keep the restored mask available for preview/editing. The
                # caller selects V1 after all tracks are restored, so this
                # does not steal the default project focus.
                if track.layers:
                    try:
                        first_layer = track.layers[0]
                        self.timeline._selected_layer_id = first_layer.id
                        self._show_mask_overlay(track, first_layer)
                    except Exception:
                        pass
            except Exception:
                pass


    def _show_mask_inspector_for_track(self, track, layer=None):
        """Show the Mask Track Inspector populated with the selected M1 layer.

        The inspector only exposes the mask's colour + opacity. Position,
        size and mode are not configurable here — the user positions /
        resizes the region via the draggable overlay on the video. The
        mask is only applied to the video while the player is playing.
        """
        self._switch_inspector("mask")
        self._wire_mask_inspector_controls()
        self._wire_layer_timing_controls("mask")
        if layer is None:
            return
        self._set_layer_timing_controls("mask", layer)
        color = str(getattr(layer, "color", "#000000"))
        if hasattr(self, "mask_inspector_color_btn"):
            self.mask_inspector_color_btn.blockSignals(True)
            self.mask_inspector_color_btn.setText(color)
            self.mask_inspector_color_btn.setStyleSheet(
                f"background-color: {color}; color: #fff;"
            )
            self.mask_inspector_color_btn.blockSignals(False)
        try:
            opacity = float(getattr(layer, "opacity", 1.0))
        except (TypeError, ValueError):
            opacity = 1.0
        opacity = max(0.0, min(1.0, opacity))
        if hasattr(self, "mask_inspector_opacity_slider"):
            self.mask_inspector_opacity_slider.blockSignals(True)
            self.mask_inspector_opacity_slider.setValue(int(round(opacity * 100)))
            self.mask_inspector_opacity_slider.blockSignals(False)
        if hasattr(self, "mask_inspector_opacity_value_label"):
            self.mask_inspector_opacity_value_label.setText(f"{int(round(opacity * 100))}%")
        if hasattr(self, "mask_inspector_summary_label"):
            tname = getattr(track, "name", "M1")
            lname = getattr(layer, "name", "Mask")
            self.mask_inspector_summary_label.setText(
                f"Selected: {tname} → {lname}. Drag the mask on the video "
                "to move it. Drag a corner to resize. The X button deletes "
                "the mask. The mask is applied while the video is playing."
            )


    def _wire_mask_inspector_controls(self):
        """One-time wiring of the Mask Inspector controls.

        Only colour + opacity are wired here. Position / size / mode
        are not configurable in the inspector; the user positions and
        resizes the mask via the draggable overlay on the video.
        """
        if getattr(self, "_mask_inspector_wired", False):
            return
        self._mask_inspector_wired = True

        def _selected_mask_layer():
            if not hasattr(self, "timeline") or not self.timeline._timeline:
                return None, None
            sid = getattr(self.timeline, "_selected_layer_id", "") or ""
            for tr in self.timeline._timeline.tracks:
                for l in tr.layers:
                    if l.id == sid:
                        return l, tr
            return None, None

        def _sync_preview(l):
            try:
                self._apply_mask_to_preview()
            except Exception:
                pass
            try:
                if hasattr(self, "persist_project_mask_state"):
                    self.persist_project_mask_state()
            except Exception:
                pass

        def _on_opacity_changed(v):
            layer, _ = _selected_mask_layer()
            if layer is None:
                return
            opacity = max(0.0, min(1.0, float(v) / 100.0))
            try:
                layer.opacity = opacity
            except Exception:
                pass
            if hasattr(self, "mask_inspector_opacity_value_label"):
                self.mask_inspector_opacity_value_label.setText(f"{int(v)}%")
            _sync_preview(layer)

        self._mask_opacity_handler = _on_opacity_changed
        if hasattr(self, "mask_inspector_opacity_slider"):
            self.mask_inspector_opacity_slider.valueChanged.connect(_on_opacity_changed)

        # Color picker
        from PySide6.QtWidgets import QColorDialog
        def _on_color_clicked():
            from PySide6.QtGui import QAction, QColor
            layer, _ = _selected_mask_layer()
            current = QColor(str(getattr(layer, "color", "#000000")))
            chosen = QColorDialog.getColor(current, self, "Pick mask colour")
            if not chosen.isValid():
                return
            hex_str = chosen.name()
            if hasattr(self, "mask_inspector_color_btn"):
                self.mask_inspector_color_btn.setText(hex_str)
                self.mask_inspector_color_btn.setStyleSheet(
                    f"background-color: {hex_str}; color: #fff;"
                )
            if layer is not None:
                try:
                    layer.color = hex_str
                except Exception:
                    pass
                _sync_preview(layer)

        self._mask_color_handler = _on_color_clicked
        if hasattr(self, "mask_inspector_color_btn"):
            self.mask_inspector_color_btn.clicked.connect(_on_color_clicked)


