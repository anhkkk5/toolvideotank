"""TtsVoiceoverMixin: Voiceover workflow, TTS engines, Voice Preview and Audio Mixing."""
from __future__ import annotations


try:
    from main_window_parts.common_deps import *
except ImportError:
    from ui.main_window_parts.common_deps import *



import os
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QMessageBox


class TtsVoiceoverMixin:
    """Mixin class for managing voice catalogs, TTS preview, VoiceOver execution

    and audio mixing controls.
    """
    def _configure_local_voice_mode_ui(self):
        if hasattr(self, "use_free_voice_radio"):
            try:
                self.use_free_voice_radio.setChecked(True)
                self.use_free_voice_radio.setVisible(False)
                self.use_free_voice_radio.setEnabled(False)
            except Exception:
                pass
        if hasattr(self, "use_premium_voice_radio"):
            try:
                self.use_premium_voice_radio.setChecked(False)
                self.use_premium_voice_radio.setVisible(False)
                self.use_premium_voice_radio.setEnabled(False)
            except Exception:
                pass
        if hasattr(self, "premium_voice_combo"):
            try:
                self.premium_voice_combo.clear()
                self.premium_voice_combo.setVisible(False)
                self.premium_voice_combo.setEnabled(False)
            except Exception:
                pass
        if hasattr(self, "preview_voice_btn"):
            try:
                self.preview_voice_btn.setText("Nghe thử giọng đọc")
            except Exception:
                pass
        if hasattr(self, "voice_preview_meta_label"):
            try:
                self.voice_preview_meta_label.setText("Tạo một đoạn âm thanh ngắn nghe thử với giọng đọc đã chọn.")
            except Exception:
                pass
    def setup_audio_preview_player(self):
        if getattr(self, "_preview_audio_signals_bound", False):
            return
        self._preview_audio_signals_bound = True
        self.audio_preview_player = QMediaPlayer(self)
        self.audio_preview_output = QAudioOutput(self)
        self.audio_preview_player.setAudioOutput(self.audio_preview_output)
        self.voice_preview_library_player = QMediaPlayer(self)
        self.voice_preview_library_output = QAudioOutput(self)
        self.voice_preview_library_player.setAudioOutput(self.voice_preview_library_output)
        self.voice_preview_dialog = None
        self._voice_preview_row_buttons = {}
    def _voice_catalog_data_value(self, entry: dict) -> str:
        provider = str(entry.get("provider", "")).strip().lower()
        provider_voice = str(entry.get("provider_voice", "")).strip()
        entry_id = str(entry.get("id", "")).strip()
        if provider == "piper":
            return entry_id
        if provider == "edge":
            return f"edge:{provider_voice or 'vi-VN-HoaiMyNeural'}"
        if provider == "capcut":
            return entry_id
        return ""
    def _voice_provider_label(self, provider: str) -> str:
        provider_key = str(provider or "").strip().lower()
        if provider_key == "piper":
            return "Local"
        if provider_key == "edge":
            return "Edge"
        if provider_key == "capcut":
            return "CapCut"
        return str(provider or "Other").strip().title() or "Other"
    def _current_voice_tier(self) -> str:
        return "free"
    def _selected_voice_gender(self) -> str:
        if not hasattr(self, "voice_gender_combo"):
            return "any"
        data = self.voice_gender_combo.currentData()
        if data:
            val = self._normalize_gender_value(data)
            if val:
                return val
        return self._normalize_gender_value(self.voice_gender_combo.currentText())
    def set_voice_combo_value(self, combo, value):
        target = str(value or "").strip()
        if not combo or not target:
            return
        for index in range(combo.count()):
            item_value = str(combo.itemData(index) or "").strip()
            item_entry_id = str(combo.itemData(index, self.VOICE_ENTRY_ID_ROLE) or "").strip()
            if item_value == target or item_entry_id == target:
                combo.setCurrentIndex(index)
                return
    def _get_previewable_voice_catalog_entry(self):
        return None
    def _update_voice_preview_meta(self):
        if not hasattr(self, "voice_preview_meta_label"):
            return
        total_entries = len(self.voice_catalog_entries or [])
        if hasattr(self, "preview_voice_btn"):
            self.preview_voice_btn.setVisible(True)
            self.preview_voice_btn.setEnabled(total_entries > 0)
        if total_entries <= 0:
            self.voice_preview_meta_label.setText("Chưa có giọng đọc nào khả dụng.")
            return
        self.voice_preview_meta_label.setText(
            f"Giọng đọc khả dụng: {total_entries}. Bấm “Nghe thử giọng đọc” để nghe đoạn đọc mẫu."
        )
    def _current_voice_engine_key(self) -> str:
        combo = getattr(self, "voice_engine_combo", None)
        if combo is None:
            return "fast"
        return str(combo.currentData() or "fast").strip().lower() or "fast"
    def _resolve_active_voice_name(self, *, persist_new_clone: bool = False) -> str:
        free_value = str(self.free_voice_combo.currentData() or "").strip() if hasattr(self, "free_voice_combo") else ""
        if free_value and free_value.startswith("edge:"):
            return free_value
        if free_value and free_value in getattr(self, "voice_catalog_map", {}):
            return free_value
        # A gender filter can legitimately leave the selector empty. Do not
        # silently fall back to a voice outside the user's selected filter.
        combo_has_items = bool(hasattr(self, "free_voice_combo") and self.free_voice_combo.count())
        target_language = self.get_target_language_code()
        if (
            combo_has_items
            and target_language == "vi"
            and "ngochuyen" in getattr(self, "voice_catalog_map", {})
            and self.free_voice_combo.findData("ngochuyen") >= 0
        ):
            return "ngochuyen"
        if (
            combo_has_items
            and target_language == "vi"
            and "vi_VN-vais1000-medium" in getattr(self, "voice_catalog_map", {})
            and self.free_voice_combo.findData("vi_VN-vais1000-medium") >= 0
        ):
            return "vi_VN-vais1000-medium"
        if hasattr(self, "free_voice_combo") and self.free_voice_combo.count() > 0:
            fallback_value = str(self.free_voice_combo.itemData(0) or "").strip()
            if fallback_value:
                return fallback_value
            fallback_entry_id = str(self.free_voice_combo.itemData(0, self.VOICE_ENTRY_ID_ROLE) or "").strip()
            if fallback_entry_id:
                return fallback_entry_id
        return ""
    def on_voice_engine_changed(self):
        self._voiceover_force_refresh = True
    def load_voice_preview_catalog(self):
        self._auto_sync_piper_voices_to_catalog()
        self.voice_catalog_entries_all = self.voice_catalog_service.load_catalog()
        # A packaged build keeps its catalog under _internal (read-only), so
        # newly downloaded piper-new voices may not be persisted there. Merge
        # the local manifest in memory as well, ensuring their names/genders
        # are immediately available to the selector and gender filter.
        self._merge_piper_manifest_voices()
        self._apply_piper_voice_meta_overrides()
        if self.voice_preview_dialog is not None:
            self.voice_preview_dialog.close()
            self.voice_preview_dialog = None
        self.refresh_voice_catalog_combos()
    def _load_piper_voice_meta(self) -> dict:
        meta_path = models_path("piper", "voices_meta.json")
        if not os.path.exists(meta_path):
            return {}
        try:
            with open(meta_path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return {}
            voices = payload.get("voices", {})
            return voices if isinstance(voices, dict) else {}
        except Exception:
            return {}
    def _load_piper_voice_manifest(self) -> dict[str, dict]:
        """Load piper-new's shared voice metadata keyed by model stem."""
        manifest_path = models_path("piper", "voices.json")
        if not os.path.isfile(manifest_path):
            return {}
        try:
            with open(manifest_path, "r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except Exception:
            return {}
        entries: dict[str, dict] = {}
        if not isinstance(payload, list):
            return entries
        for item in payload:
            if not isinstance(item, dict):
                continue
            audio_path = str(item.get("audio_path", "") or "").replace("\\", "/").strip()
            voice_id = os.path.splitext(os.path.basename(audio_path))[0]
            if voice_id:
                entries[voice_id] = dict(item)
        return entries
    def _voice_gender_sort_rank(self, value: str) -> int:
        normalized = self._normalize_gender_value(value)
        if normalized == "female":
            return 0
        if normalized == "male":
            return 1
        return 2
    def _voice_entry_sort_key(self, entry: dict) -> tuple:
        provider = str(entry.get("provider", "")).strip().lower()
        name = str(entry.get("name", entry.get("id", ""))).strip().lower()
        return (
            self._voice_gender_sort_rank(str(entry.get("gender", ""))),
            0 if provider == "edge" else 1,
            name,
        )
    def _apply_piper_voice_meta_overrides(self):
        voices_meta = self._load_piper_voice_meta()
        if not voices_meta:
            return
        for entry in self.voice_catalog_entries_all or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("provider", "")).strip().lower() != "piper":
                continue
            voice_id = str(entry.get("id", "")).strip()
            if not voice_id:
                continue
            meta = voices_meta.get(voice_id, {})
            if not isinstance(meta, dict):
                continue
            if "gender" in meta:
                entry["gender"] = self._normalize_gender_value(meta.get("gender", ""))
    def refresh_voice_catalog_combos(self):
        self.voice_catalog_entries = []
        target_language = self.get_target_language_code()
        for entry in (self.voice_catalog_entries_all or []):
            if not entry or not isinstance(entry, dict):
                continue
            if not entry.get("enabled", True):
                continue
            provider = str(entry.get("provider", "")).strip().lower()
            if provider not in {"piper", "edge", "capcut", "vieneu"}:
                continue
            entry_language = str(entry.get("language", "")).strip().lower().split("-", 1)[0]
            if entry_language and entry_language != target_language:
                continue
            self.voice_catalog_entries.append(entry)
        self.voice_catalog_entries.sort(key=self._voice_entry_sort_key)
        self.voice_catalog_map = {entry.get("id", ""): entry for entry in self.voice_catalog_entries if entry.get("id")}
        if not hasattr(self, "free_voice_combo"):
            return

        selected_gender = self._selected_voice_gender()
        previous_free = str(self.free_voice_combo.currentData() or "")
        previous_entry_id = str(self.free_voice_combo.currentData(self.VOICE_ENTRY_ID_ROLE) or "")

        self.free_voice_combo.blockSignals(True)
        self.free_voice_combo.clear()
        for entry in self.voice_catalog_entries:
            entry_gender = self._normalize_gender_value(entry.get("gender", ""))
            if selected_gender in ("male", "female") and entry_gender != selected_gender:
                continue
            self.free_voice_combo.addItem(
                str(entry.get("name", entry.get("id", "Voice"))),
                self._voice_catalog_data_value(entry),
            )
            index = self.free_voice_combo.count() - 1
            self.free_voice_combo.setItemData(index, entry.get("id", ""), self.VOICE_ENTRY_ID_ROLE)

        if self.free_voice_combo.count() > 0:
            self.free_voice_combo.setCurrentIndex(0)
        target_to_restore = previous_entry_id or previous_free
        if target_to_restore:
            self.set_voice_combo_value(self.free_voice_combo, target_to_restore)
        elif selected_gender != "male" and target_language == "vi" and "ngochuyen" in self.voice_catalog_map:
            self.set_voice_combo_value(self.free_voice_combo, "ngochuyen")
        elif selected_gender == "male" and target_language == "vi" and "vietthao3886" in self.voice_catalog_map:
            self.set_voice_combo_value(self.free_voice_combo, "vietthao3886")
        elif selected_gender == "male" and target_language == "vi" and "tranthanh3870" in self.voice_catalog_map:
            self.set_voice_combo_value(self.free_voice_combo, "tranthanh3870")
        self.free_voice_combo.blockSignals(False)

        if not self._voice_signals_bound:
            self._voice_signals_bound = True
        self.on_voice_tier_changed()
        self._update_voice_preview_meta()
        self.refresh_detected_speakers_section()
    def on_voice_gender_changed(self, *_args):
        self.refresh_voice_catalog_combos()
        self.on_selected_voice_changed()
    def on_selected_voice_changed(self):
        self._update_voice_preview_meta()
        self._preload_active_voice_if_needed()
    def _preload_active_voice_if_needed(self):
        voice_name = self.get_active_voice_name()
        if not voice_name:
            return
        if str(voice_name).startswith("f5:"):
            return
        entry_id = str(self.free_voice_combo.currentData(self.VOICE_ENTRY_ID_ROLE) or '').strip() if hasattr(self, 'free_voice_combo') else ''
        entry = self.voice_catalog_map.get(entry_id) if hasattr(self, 'voice_catalog_map') else None
        provider = str((entry or {}).get('provider', '')).strip().lower()
        if provider != 'piper':
            return
        current_token = voice_name.strip()
        if getattr(self, '_voice_preload_inflight', '') == current_token or getattr(self, '_voice_preloaded_name', '') == current_token:
            return

        self._voice_preload_inflight = current_token

        def _worker(expected_voice: str):
            try:
                self._preload_tts_voice_impl(expected_voice)
                def _mark_ready():
                    if getattr(self, '_voice_preload_inflight', '') == expected_voice:
                        self._voice_preload_inflight = ''
                        self._voice_preloaded_name = expected_voice
                        self.log(f"[Voice] Piper voice preloaded: {expected_voice}")
                QTimer.singleShot(0, _mark_ready)
            except Exception as exc:
                def _mark_failed():
                    if getattr(self, '_voice_preload_inflight', '') == expected_voice:
                        self._voice_preload_inflight = ''
                        self.log(f"[Voice] Piper preload skipped: {exc}")
                QTimer.singleShot(0, _mark_failed)

        threading.Thread(target=_worker, args=(current_token,), daemon=True).start()
    def get_selected_premium_voice_catalog_entry(self):
        if not hasattr(self, "premium_voice_combo"):
            return None
        if not hasattr(self, "voice_catalog_entries"):
            return None
        entry_id = self.premium_voice_combo.currentData(self.VOICE_ENTRY_ID_ROLE)
        if entry_id and entry_id in self.voice_catalog_map:
            return self.voice_catalog_map[entry_id]
        current_value = str(self.premium_voice_combo.currentData() or "")
        for entry in self.voice_catalog_entries:
            if self._voice_catalog_data_value(entry) == current_value:
                return entry
        return None
    def get_active_voice_name(self) -> str:
        return self._resolve_active_voice_name(persist_new_clone=False)
    def _speaker_voice_assignments(self) -> dict:
        state = getattr(self, "current_project_state", None)
        raw = state.settings.get("speaker_voice_assignments", {}) if state is not None else {}
        return dict(raw) if isinstance(raw, dict) else {}
    def _save_speaker_voice_assignment(
        self,
        speaker: str,
        *,
        name: str | None = None,
        voice: str | None = None,
        voice_gender_filter: str | None = None,
    ) -> None:
        state = getattr(self, "current_project_state", None)
        speaker = str(speaker or "").strip()
        if state is None or not speaker:
            return
        assignments = self._speaker_voice_assignments()
        entry = dict(assignments.get(speaker, {}) or {})
        if name is not None:
            entry["name"] = str(name or "").strip()
        if voice is not None:
            entry["voice"] = str(voice or "").strip()
        if voice_gender_filter is not None:
            entry["voice_gender_filter"] = str(voice_gender_filter or "Any").strip() or "Any"
        assignments[speaker] = entry
        state.set_setting("speaker_voice_assignments", assignments)
        self.project_service.save_project(state)
        self._voiceover_force_refresh = True
    def _voice_display_entries(
        self,
        *,
        gender: str = "any",
        include_voice: str = "",
    ) -> list[tuple[str, str]]:
        """Return gender-filtered voices for a speaker row independently.

        ``free_voice_combo`` intentionally represents only Voice Setup.  A
        speaker's filter/search must never depend on that combo's contents.
        Keep an already assigned voice visible while filtering so changing a
        filter cannot silently replace the speaker's mapping.
        """
        wanted_gender = self._normalize_gender_value(gender)
        assigned = str(include_voice or "").strip()
        entries: list[tuple[str, str]] = []
        for entry in sorted(list(getattr(self, "voice_catalog_entries", []) or []), key=self._voice_entry_sort_key):
            value = self._voice_catalog_data_value(entry)
            if not value:
                continue
            entry_gender = self._normalize_gender_value(str(entry.get("gender", "")))
            gender_tag = " (Nam)" if entry_gender == "male" else (" (Nữ)" if entry_gender == "female" else "")
            raw_name = str(entry.get("name", entry.get("id", "Voice")) or "Voice")
            label = f"{raw_name}{gender_tag}" if gender_tag and not raw_name.endswith(gender_tag) else raw_name
            gender_match = wanted_gender not in {"male", "female"} or entry_gender in {wanted_gender, "", "any"}
            if gender_match or value == assigned:
                entries.append((label, value))
        return entries
    def _apply_speaker_voice_assignments(self, segments: list[dict]) -> list[dict]:
        assignments = self._speaker_voice_assignments()
        if not assignments:
            # Auto-run smart cast if assignments not yet populated
            state = getattr(self, "current_project_state", None)
            audio_path = (
                getattr(self, "last_extracted_audio", "")
                or (state.artifacts.get("extracted_audio") if state else "")
                or ""
            )
            from services.smart_cast import auto_cast_speakers, apply_smart_cast_to_subtitles
            speaker_voice_map, _ = auto_cast_speakers(
                segments,
                audio_path,
                expected_speakers=self.get_speaker_diarization_num_speakers(),
            )
            if speaker_voice_map:
                for spk, v in speaker_voice_map.items():
                    self._save_speaker_voice_assignment(spk, voice=v)
                return apply_smart_cast_to_subtitles(segments, speaker_voice_map)
            return [dict(segment) for segment in segments or []]

        resolved = []
        for segment in segments or []:
            item = dict(segment)
            speaker = str(item.get("speaker", "") or "").strip()
            voice = str((assignments.get(speaker, {}) or {}).get("voice", "") or "").strip()
            if voice:
                item["voice_name"] = voice
            resolved.append(item)
        return resolved
    def on_voice_tier_changed(self):
        mode = self.get_output_mode_key() if hasattr(self, "output_mode_combo") else "both"
        if hasattr(self, "free_voice_combo"):
            self.free_voice_combo.setEnabled(True)
        if hasattr(self, "preview_voice_btn"):
            # Preview Voice belongs to Voice Setup and should remain available
            # whenever the Voice panel is open, independent of output-mode
            # compatibility state.
            self.preview_voice_btn.setVisible(True)
        self._update_voice_preview_meta()
    def _parse_voice_speed_value(self) -> float:
        raw = str(getattr(self, "voice_speed_spin", None).currentText() if getattr(self, "voice_speed_spin", None) else "1.0x").strip().lower()
        raw = raw.replace("x", "")
        try:
            return float(raw or "1.0")
        except ValueError:
            return 1.0
    def _resolve_voice_preview_source(self, entry: dict) -> QUrl:
        preview_path = str(entry.get("preview_video_path", "")).strip()
        preview_url = str(entry.get("preview_video_url", "")).strip()
        preview_audio_path = str(entry.get("preview_audio_path", "")).strip()
        preview_audio_url = str(entry.get("preview_audio_url", "")).strip()

        if preview_path:
            if not os.path.isabs(preview_path):
                preview_path = os.path.join(self.workspace_root, preview_path)
            if not os.path.exists(preview_path):
                raise FileNotFoundError("The configured preview video file was not found.")
            return QUrl.fromLocalFile(preview_path)
        if preview_url:
            return QUrl(preview_url)
        if preview_audio_path:
            if not os.path.isabs(preview_audio_path):
                preview_audio_path = os.path.join(self.workspace_root, preview_audio_path)
            if not os.path.exists(preview_audio_path):
                raise FileNotFoundError("The configured preview audio file was not found.")
            return QUrl.fromLocalFile(preview_audio_path)
        if preview_audio_url:
            return QUrl(preview_audio_url)
        raise RuntimeError("This voice does not have preview media configured yet.")
    def run_vocal_separation(self):
        audio_src = self.audio_source_edit.text()
        if not audio_src or not os.path.exists(audio_src):
            QMessageBox.warning(self, "Error", "Please extract audio or select a source first!")
            return
        
        target_dir = self.audio_folder_edit.text()
        self.progress_bar.setValue(35)
        self.vocal_sep_btn.setEnabled(False)
        self.vocal_sep_btn.setText("Separating... (AI Processing)")
        self.update_project_step("separate_audio", "running")
        
        self.vocal_thread = VocalSeparationWorker(audio_src, target_dir)
        self.vocal_thread.finished.connect(self.on_vocal_separation_finished)
        self.vocal_thread.start()
    def on_vocal_separation_finished(self, vocal, music, error):
        self.vocal_sep_btn.setEnabled(True)
        self.vocal_sep_btn.setText("Separate Voice and Background")
        self.progress_bar.setValue(50)
        
        if error:
            self.update_project_step("separate_audio", "failed")
            err_lower = error.lower()
            missing_demucs = (
                "no module named" in err_lower and "demucs" in err_lower
            ) or (
                "demucs is not installed" in err_lower
            ) or (
                "requires the 'demucs' library" in err_lower
            )
            if missing_demucs:
                QMessageBox.warning(
                    self,
                    "Dependency Missing",
                    "Vocal Separation requires the 'demucs' library.\n\n"
                    "Please run (using the same Python you run this app with):\n"
                    "python -m pip install demucs\n\n"
                    f"Details:\n{error}",
                )
            else:
                QMessageBox.critical(self, "Error", f"Separation failed:\n\n{error}")
            self.log(error)
            self.refresh_ui_state()
            return
        
        if vocal and os.path.exists(vocal):
            self.audio_source_edit.setText(vocal)
            self.last_extracted_audio = vocal
            self.last_vocals_path = vocal
            self.last_music_path = music
            self.processed_artifacts["vocals"] = vocal
            self.update_project_artifact("vocals", vocal)
            if music:
                self.processed_artifacts["music"] = music
                self.update_project_artifact("music", music)
            self.update_project_step("separate_audio", "done")
            QMessageBox.information(self, "Success", 
                f"Audio stems separated!\n\nVocals: {os.path.basename(vocal)}\nBackground: {os.path.basename(music)}\n\nVocals are now selected for transcription.")
            self._pipeline_advance("separation")
        else:
            self.update_project_step("separate_audio", "failed")
            self._pipeline_fail("Separation did not produce output.")
        self.refresh_ui_state()
    def _music_audio_tracks(self) -> list[dict]:
        """Return active Music Layer entries in the timeline.

        Music is intentionally modeled separately from the source video's A1
        audio and the generated TS1 voice.  The returned dictionaries are the
        common input format used by preview and export mixing.
        """
        timeline = getattr(self, "timeline", None)
        model = getattr(timeline, "_timeline", None) if timeline is not None else None
        if model is None:
            return []
        tracks = []
        for track in getattr(model, "tracks", []) or []:
            metadata = getattr(track, "metadata", {}) or {}
            name = str(getattr(track, "name", "") or "")
            role = str(metadata.get("_audio_role", "") or "").strip().lower()
            if role != "music" and name.lower() not in {"a2 music", "music"}:
                continue
            try:
                track_volume = float(metadata.get("_volume", 30.0))
            except (TypeError, ValueError):
                track_volume = 30.0
            track_muted = bool(
                getattr(track, "muted", False)
                or metadata.get("_muted", False)
                or self._is_audio_track_muted(name)
            )
            track_visible = bool(getattr(track, "visible", True))
            track_solo = bool(getattr(track, "solo", False) or metadata.get("_solo", False))
            for layer in getattr(track, "layers", []) or []:
                source = self._normalize_local_file_path(str(getattr(layer, "source", "") or ""))
                if not source or not os.path.exists(source):
                    continue
                start = max(0.0, float(getattr(layer, "start", 0.0) or 0.0))
                end = max(start, float(getattr(layer, "end", 0.0) or 0.0))
                tracks.append({
                    "path": source,
                    "start": start,
                    "end": end,
                    "source_start": float(getattr(layer, "source_start", 0.0) or 0.0),
                    "volume": track_volume,
                    "muted": (
                        track_muted
                        or not track_visible
                        or not bool(getattr(layer, "visible", True))
                        or bool(getattr(layer, "muted", False))
                    ),
                    "solo": track_solo,
                    "loop": True,
                    "track_name": name or "A2 Music",
                    "legacy": False,
                })
        # Projects created before Music Layer became a first-class timeline
        # track may still persist the selected background stem as the
        # project-level ``music`` artifact.  Keep that audio usable instead
        # of silently falling back to A1 Original only.  A real A2 Music
        # track always wins, so this cannot duplicate a current layer.
        if not tracks:
            legacy_path = self._normalize_local_file_path(
                str(getattr(self, "last_music_path", "") or "")
            )
            if legacy_path and os.path.exists(legacy_path):
                try:
                    legacy_volume = float(
                        self.audio_music_volume_slider.value()
                        if hasattr(self, "audio_music_volume_slider")
                        else 30.0
                    )
                except (TypeError, ValueError):
                    legacy_volume = 30.0
                tracks.append({
                    "path": legacy_path,
                    "start": 0.0,
                    "end": max(0.0, float(getattr(model, "duration", 0.0) or 0.0)),
                    "source_start": 0.0,
                    "volume": legacy_volume,
                    "muted": False,
                    "solo": False,
                    "loop": True,
                    "track_name": "A2 Music",
                    "legacy": True,
                })
        return tracks
    def _apply_audio_track_settings(self, track_name: str):
        """Apply per-track volume/gain/mute to the underlying media player.

        Maps the timeline track name to the media player:
          "A1 Audio" -> QMediaPlayer #1 (original sidecar)
          "A2 Dub" / "TS1" -> QMediaPlayer #2 (dubbed sidecar)
        """
        if not hasattr(self, "media_player") or self.media_player is None:
            return
        try:
            if track_name == "A1 Audio":
                vol = self._compute_audio_track_volume(track_name, base=100.0)
                gain_db = self._get_audio_track_gain_db(track_name)
                effective = vol * (10 ** (gain_db / 20.0))
                effective = max(0.0, min(200.0, effective))
                if hasattr(self.media_player, "set_original_volume"):
                    self.media_player.set_original_volume(effective)
                muted = self._is_audio_track_muted(track_name)
                if hasattr(self.media_player, "set_mute_original"):
                    self.media_player.set_mute_original(muted)
            elif track_name in ("A2 Dub", "TS1"):
                # When Music is present the dubbed sidecar is a composed
                # TTS+Music render.  TTS volume/mute must be baked into that
                # render; applying the TS1 volume to the whole sidecar would
                # incorrectly attenuate the music as well.
                # Presence of a Music Layer is enough to choose the composed
                # sidecar path; avoid resolving/building that mix
                # synchronously from a slider callback.
                if bool(self._music_audio_tracks()):
                    if hasattr(self.media_player, "set_dubbed_volume"):
                        self.media_player.set_dubbed_volume(100.0)
                    if hasattr(self.media_player, "set_mute_dubbed"):
                        self.media_player.set_mute_dubbed(False)
                    self._schedule_preview_audio_refresh()
                else:
                    vol = self._compute_audio_track_volume(track_name, base=100.0)
                    gain_db = self._get_audio_track_gain_db(track_name)
                    effective = vol * (10 ** (gain_db / 20.0))
                    effective = max(0.0, min(200.0, effective))
                    if hasattr(self.media_player, "set_dubbed_volume"):
                        self.media_player.set_dubbed_volume(effective)
                    muted = self._is_audio_track_muted(track_name)
                    if hasattr(self.media_player, "set_mute_dubbed"):
                        self.media_player.set_mute_dubbed(muted)
            elif track_name == "A2 Music":
                # Music is composed into the dubbed sidecar alongside TS1;
                # rebuild that lightweight cached mix after a volume change.
                self._schedule_preview_audio_refresh()
        except Exception:
            pass
    def _sync_audio_mix_controls_from_tracks(self):
        """Load timeline track volumes into the Audio tab controls."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        values = {
            "A1 Audio": 50,
            "TS1": 100,
            "A2 Dub": 100,
            "A2 Music": 30,
        }
        for track in self.timeline._timeline.tracks:
            if track.name not in values:
                continue
            meta = getattr(track, "metadata", {}) or {}
            try:
                values[track.name] = int(round(float(meta.get("_volume", values[track.name]))))
            except (TypeError, ValueError):
                pass
        if hasattr(self, "audio_a1_volume_slider"):
            self.audio_a1_volume_slider.blockSignals(True)
            self.audio_a1_volume_slider.setValue(max(0, min(200, values["A1 Audio"])))
            self.audio_a1_volume_slider.blockSignals(False)
            if hasattr(self, "audio_a1_volume_label"):
                self.audio_a1_volume_label.setText(f"{values['A1 Audio']}%")
        tts_value = values["TS1"] if any(t.name == "TS1" for t in self.timeline._timeline.tracks) else values["A2 Dub"]
        if hasattr(self, "audio_a2_volume_slider"):
            self.audio_a2_volume_slider.blockSignals(True)
            self.audio_a2_volume_slider.setValue(max(0, min(200, tts_value)))
            self.audio_a2_volume_slider.blockSignals(False)
            if hasattr(self, "audio_a2_volume_label"):
                self.audio_a2_volume_label.setText(f"{tts_value}%")
        if hasattr(self, "audio_music_volume_slider"):
            self.audio_music_volume_slider.blockSignals(True)
            self.audio_music_volume_slider.setValue(max(0, min(200, values["A2 Music"])))
            self.audio_music_volume_slider.blockSignals(False)
            if hasattr(self, "audio_music_volume_label"):
                self.audio_music_volume_label.setText(f"{values['A2 Music']}%")
        self._refresh_music_layer_summary()
    def _sync_timeline_mute_to_gui(self):
        """Pull the current timeline track mute state into the GUI and backend."""
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        a1_muted = False
        a2_muted = False
        music_muted = False
        for t in self.timeline._timeline.tracks:
            metadata = getattr(t, "metadata", {}) or {}
            muted = bool(getattr(t, "muted", False) or metadata.get("_muted", False))
            if t.name == "A1 Audio" or t.name.startswith("A1") or t.name == "A1 Âm thanh":
                a1_muted = muted
            elif t.name in ("A2 Dub", "TS1") or t.name.startswith("TS1") or t.name.startswith("A2 Dub"):
                a2_muted = muted
            elif t.name == "A2 Music" or t.name.startswith("A2 Music") or t.name.startswith("A2 Nhạc"):
                music_muted = muted
        self._mute_original = a1_muted
        self._mute_dubbed = a2_muted
        if hasattr(self, "media_player"):
            try:
                self.media_player.set_mute_original(a1_muted)
            except Exception:
                pass
            try:
                # The dubbed sidecar may contain an independent Music Layer.
                # A muted TTS track must not mute that whole sidecar; the
                # compositor removes TTS while keeping Music audible.
                self.media_player.set_mute_dubbed(
                    False if self._music_audio_tracks() else a2_muted
                )
            except Exception:
                pass
        if hasattr(self, "track_label_bar"):
            self.track_label_bar.set_muted("A1 Audio", a1_muted)
            self.track_label_bar.set_muted("TS1", a2_muted)
            self.track_label_bar.set_muted("A2 Music", music_muted)
    def run_voiceover_with_progress(self, target_stage="full"):
        existing = getattr(self, "voice_thread", None)
        if existing and existing.isRunning():
            return
        self._pipeline_active = True
        self._pipeline_step = "voiceover"
        self.pipeline_controller.target_stage = str(target_stage or "full")
        if hasattr(self, "run_all_btn"):
            self.run_all_btn.setEnabled(False)
            self.run_all_btn.setText("Đang xử lý...")
        self.pipeline_controller._setup_progress_dialog(includes_separation=False)
        self.pipeline_controller.progress_dialog.skip_step("ai_process")
        self.pipeline_controller.progress_dialog.start_step("voiceover")
        self._voiceover_force_refresh = True
        self.run_voiceover()
    def on_voiceover_finished(self, voice_track, mixed, voice_segments, error):
        if hasattr(self, "voiceover_btn"):
            self.voiceover_btn.setEnabled(True)
            self.voiceover_btn.setText("Generate Voice / Mix")
        self.progress_bar.setValue(100)

        if error:
            self._voiceover_force_refresh = False
            self._pending_voice_signature = ""
            self.update_project_step("generate_tts", "failed")
            if self.bg_music_edit.text().strip():
                self.update_project_step("mix_audio", "failed")
            QMessageBox.critical(self, "Error", f"Voiceover failed:\n\n{error}")
            self._pipeline_fail("Voiceover failed.")
            self.refresh_ui_state()
            return

        if hasattr(self, "audio_tab_btn"):
            self.audio_tab_btn.setEnabled(True)

        if voice_track and os.path.exists(voice_track):
            self.last_voice_vi_path = voice_track
            self.processed_artifacts["voice_vi"] = voice_track
            self.update_project_artifact("voice_vi", voice_track)
            self.update_project_step("generate_tts", "done")
        if mixed and os.path.exists(mixed):
            self.last_mixed_vi_path = mixed
            self.processed_artifacts["mixed_vi"] = mixed
            self.update_project_artifact("mixed_vi", mixed)
            self.update_project_step("mix_audio", "done")
        elif self._music_audio_tracks():
            self.update_project_step("mix_audio", "skipped")
        if self._apply_generated_tts_texts(voice_segments):
            self._single_line_split_cache = None
            self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
            self._sync_hidden_translated_text_from_segments()
            self.apply_segments_to_timeline()
            if hasattr(self, "timeline") and voice_track:
                self.timeline.sync_tts_track(
                    voice_track,
                    segments=self.current_translated_segments or self.current_segments,
                )
                if hasattr(self, "voice_timing_sync_combo"):
                    self.timeline.set_voice_sync_mode(self.voice_timing_sync_combo.currentText())
            self._sync_timeline_mute_to_gui()
            self._sync_audio_mix_controls_from_tracks()
            self.persist_current_timeline_project_data()
            # Regenerate the project SRT from the updated segments so it
            # reflects the actual TTS audio duration (e.g. when a segment
            # was extended in voice_workflow._extend_segment_ends_to_audio).
            self._regenerate_translated_srt_from_segments()
            self.schedule_live_subtitle_preview_refresh()
            self.sync_segment_editor_rows()
        if self.current_project_state:
            voice_signature = self.build_current_voice_signature(
                segments=self._get_voiceover_segments(),
                background_path=self.resolve_background_audio_path(),
            )
            if voice_signature:
                self.current_project_state.set_setting("voice_signature", voice_signature)
                self.project_service.save_project(self.current_project_state)
        self._voiceover_force_refresh = False
        self._pending_voice_signature = ""

        try:
            self._pipeline_advance("voiceover")
        except Exception as exc:
            self.log(f"[Voiceover] pipeline_advance failed: {exc}")
            self.refresh_ui_state()

        if mixed:
            self.log(f"[Voiceover] Generated Vietnamese voice and mixed audio: Voice={voice_track}, Mixed={mixed}")
        else:
            self.log(f"[Voiceover] Generated Vietnamese voice track: {voice_track} (No background mix created.)")

        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
        self.refresh_ui_state()
        self._activate_dubbed_audio_without_original_voice()
        self.sync_preview_audio_track_to_output()
