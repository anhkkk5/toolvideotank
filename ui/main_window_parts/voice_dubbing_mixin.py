"""VoiceDubbingMixin: Voice dubbing execution, Piper sync, Speaker management, and TTS generation."""

try:
    from main_window_parts.common_deps import *
except ImportError:
    from ui.main_window_parts.common_deps import *


from typing import Any, Dict, List, Optional
import os
import json
import logging

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QTimer
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QPushButton, QSlider, QProgressBar, QLabel, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox, QTabWidget, QSplitter, QScrollArea, QFrame, QDialog,
    QApplication, QFileDialog, QMessageBox, QWidget, QMenu
)

logger = logging.getLogger(__name__)


class VoiceDubbingMixin:
    """Mixin containing voiceover pipelines, speaker assignments, Piper catalogs, and normalizer dict."""
    def _merge_piper_manifest_voices(self) -> None:
        """Merge local piper-new models/metadata into the in-memory catalog."""
        manifest = self._load_piper_voice_manifest()
        if not manifest:
            return
        existing = {
            str(entry.get("id", "")).strip(): entry
            for entry in (self.voice_catalog_entries_all or [])
            if isinstance(entry, dict) and str(entry.get("id", "")).strip()
        }
        for voice_id, meta in manifest.items():
            model_path = models_path("piper", f"{voice_id}.onnx")
            if not os.path.isfile(model_path) or os.path.getsize(model_path) <= 0:
                continue
            name = str(meta.get("name", "") or "").strip() or voice_id
            gender = self._normalize_gender_value(str(meta.get("gender", "") or ""))
            entry = existing.get(voice_id)
            if entry is None:
                entry = {
                    "id": voice_id,
                    "name": name,
                    "provider": "piper",
                    "provider_voice": f"models/piper/{voice_id}.onnx",
                    "language": "vi",
                    "gender": gender,
                    "tier": "free",
                    "preview_video_url": "",
                    "preview_video_path": "",
                    "preview_audio_url": "",
                    "preview_audio_path": "",
                    "enabled": True,
                    "tags": ["local", "piper"],
                }
                if str(meta.get("description", "") or "").strip():
                    entry["description"] = str(meta.get("description")).strip()
                self.voice_catalog_entries_all.append(entry)
                existing[voice_id] = entry
                continue
            # Manifest metadata is authoritative for piper-new display data,
            # but keep project/catalog-specific fields such as preview media.
            if name and str(entry.get("name", "")).strip() != name:
                entry["name"] = name
            if gender and self._normalize_gender_value(str(entry.get("gender", ""))) != gender:
                entry["gender"] = gender
            if str(meta.get("description", "") or "").strip():
                entry["description"] = str(meta.get("description")).strip()


    def _normalize_gender_value(self, value: str) -> str:
        raw = str(value or "").strip().lower()
        if not raw:
            return ""
        if raw in {"m", "male", "nam"}:
            return "male"
        if raw in {"f", "female", "nu", "nữ", "ná»¯"}:
            return "female"
        if raw in {"any", "all", "tất cả", "tat ca", "unknown", "none"}:
            return "any"
        return raw


    def _auto_sync_piper_voices_to_catalog(self):
        # Include both writable and bundled roots.  In a packaged build the
        # writable models/piper directory can exist as an empty download
        # target, and must not hide voices shipped under _internal/models.
        model_directories = []
        seen_directories = set()
        for root in (self.workspace_root, bundle_root()):
            for folder, relative_dir in (("piper", "models/piper"), ("piper-en", "models/piper-en")):
                directory = os.path.join(root, "models", folder)
                if directory in seen_directories:
                    continue
                seen_directories.add(directory)
                model_directories.append((directory, relative_dir))
        model_directories = tuple(model_directories)
        if not any(os.path.isdir(path) for path, _relative_path in model_directories):
            return
        catalog_path = app_path("voice_preview_catalog.json")
        os.makedirs(os.path.dirname(catalog_path), exist_ok=True)

        def titleize(voice_id: str) -> str:
            stem = str(voice_id or "").strip()
            if not stem:
                return "Voice"
            if re.match(r"^[a-z]{2}_[A-Z]{2}-", stem):
                return stem
            text = re.sub(r"[_-]+", " ", stem, flags=re.UNICODE).strip()
            text = re.sub(r"\s+", " ", text, flags=re.UNICODE)
            parts = [p for p in text.split(" ") if p]
            out = []
            for part in parts:
                if any(ch.isdigit() for ch in part):
                    out.append(part)
                else:
                    out.append(part[:1].upper() + part[1:].lower())
            return " ".join(out) if out else stem

        def language_from_piper_config(model_path: str) -> str:
            # Legacy packs have one config beside each model.  The current
            # piper-new Vietnamese pack shares models/piper/config.json, so
            # fall back to the containing directory when the per-model file
            # is absent.
            folder_name = os.path.basename(os.path.dirname(model_path))
            shared_config = os.path.join(os.path.dirname(model_path), "config.json")
            candidates = (
                [shared_config, f"{model_path}.json"]
                if folder_name.lower() == "piper"
                else [f"{model_path}.json", shared_config]
            )
            if folder_name:
                candidates.append(models_path(folder_name, "config.json"))
            head = ""
            for cfg_path in candidates:
                if not os.path.isfile(cfg_path):
                    continue
                try:
                    with open(cfg_path, "r", encoding="utf-8", errors="ignore") as handle:
                        head = handle.read(16384)
                    if head:
                        break
                except Exception:
                    continue
            if not head:
                return ""
            match = re.search(
                r"\"espeak\"\\s*:\\s*{[^}]*\"voice\"\\s*:\\s*\"([^\"]+)\"",
                head,
                flags=re.IGNORECASE | re.DOTALL,
            )
            voice = (match.group(1).strip() if match else "").lower()
            if not voice:
                return ""
            return re.split(r"[-_]", voice, 1)[0].strip().lower()

        def provider_voice_for_model(model_path: str, relative_dir: str) -> str:
            return f"{relative_dir}/{os.path.basename(model_path)}"

        try:
            if os.path.exists(catalog_path):
                with open(catalog_path, "r", encoding="utf-8-sig") as handle:
                    payload = json.load(handle) or {}
            else:
                payload = {}
        except Exception:
            payload = {}

        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("schema_version", 2)
        payload.setdefault("voices", [])
        voices = list(payload.get("voices", []) or [])

        by_id = {}
        for entry in voices:
            if isinstance(entry, dict) and entry.get("id"):
                by_id[str(entry.get("id")).strip()] = entry

        model_paths = []
        for models_dir, relative_dir in model_directories:
            if not os.path.isdir(models_dir):
                continue
            model_paths.extend(
                (os.path.join(models_dir, name), relative_dir)
                for name in os.listdir(models_dir)
                if name.lower().endswith(".onnx")
            )
        model_paths.sort(key=lambda item: (item[1], os.path.basename(item[0]).lower()))
        changed = False
        model_ids = set()
        if not model_paths:
            # No models => remove all Piper voices from catalog (keep non-piper voices like Edge).
            new_voices = []
            for entry in voices:
                if not isinstance(entry, dict):
                    continue
                provider = str(entry.get("provider", "")).strip().lower()
                if provider == "piper":
                    changed = True
                    continue
                new_voices.append(entry)
            if not changed:
                return
            payload["voices"] = new_voices
            try:
                with open(catalog_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
            except Exception as exc:
                try:
                    self.log(f"[Voice Catalog] Auto-sync Piper failed: {exc}")
                except Exception:
                    pass
            return

        for model_path, relative_dir in model_paths:
            voice_id = os.path.splitext(os.path.basename(model_path))[0]
            model_ids.add(voice_id)
            pv = provider_voice_for_model(model_path, relative_dir)
            lang = language_from_piper_config(model_path) or "vi"

            existing = by_id.get(voice_id)
            if isinstance(existing, dict) and str(existing.get("provider", "")).strip().lower() == "piper":
                if str(existing.get("provider_voice", "")).strip() != pv:
                    existing["provider_voice"] = pv
                    changed = True
                if not str(existing.get("language", "")).strip():
                    existing["language"] = lang
                    changed = True
                for key in ("preview_audio_url", "preview_audio_path", "preview_video_url", "preview_video_path"):
                    if key not in existing:
                        existing[key] = ""
                        changed = True
                if "tier" not in existing:
                    existing["tier"] = "free"
                    changed = True
                if "enabled" not in existing:
                    existing["enabled"] = True
                    changed = True
                if "tags" not in existing:
                    existing["tags"] = ["local", "piper"]
                    changed = True
                continue

            if voice_id == "vi_VN-vais1000-medium":
                name = "Vais1000 Medium (Local)"
            else:
                name = f"{titleize(voice_id)} (Local)"
            voices.append(
                {
                    "id": voice_id,
                    "name": name,
                    "provider": "piper",
                    "provider_voice": pv,
                    "language": lang,
                    "gender": "",
                    "tier": "free",
                    "preview_video_url": "",
                    "preview_video_path": "",
                    "preview_audio_url": "",
                    "preview_audio_path": "",
                    "enabled": True,
                    "tags": ["local", "piper"],
                }
            )
            changed = True

        # Remove Piper entries whose models were deleted.
        new_voices = []
        for entry in voices:
            if not isinstance(entry, dict):
                continue
            provider = str(entry.get("provider", "")).strip().lower()
            if provider == "piper":
                entry_id = str(entry.get("id", "")).strip()
                if not entry_id or entry_id not in model_ids:
                    changed = True
                    continue
            new_voices.append(entry)
        voices = new_voices

        if not changed:
            return

        payload["voices"] = voices
        try:
            with open(catalog_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except Exception as exc:
            try:
                self.log(f"[Voice Catalog] Auto-sync Piper failed: {exc}")
            except Exception:
                pass


    def _preload_tts_voice_impl(voice_name: str):
        from tts_processor import preload_tts_voice

        return preload_tts_voice(voice_name)


    def _speaker_sort_key(speaker: str) -> tuple[int, str]:
        value = str(speaker or "").strip()
        try:
            return (int(value.rsplit("_", 1)[-1]), value)
        except (TypeError, ValueError):
            return (9999, value)


    def _speaker_color_hex(speaker: str) -> str:
        value = str(speaker or "").strip()
        try:
            index = int(value.rsplit("_", 1)[-1])
        except (TypeError, ValueError):
            index = sum(ord(char) for char in value)
        return QColor.fromHsv((index * 137 + 20) % 360, 155, 205).name()


    def _detected_speaker_ids(self) -> list[str]:
        segments = list(
            getattr(self, "current_translated_segments", None)
            or getattr(self, "current_segments", None)
            or []
        )
        return sorted(
            {
                str(segment.get("speaker", "") or "").strip()
                for segment in segments
                if str(segment.get("speaker", "") or "").strip()
            },
            key=self._speaker_sort_key,
        )


    def _speaker_display_name(speaker: str, position: int) -> str:
        """Use stable automatic labels; diarization IDs remain internal."""
        if 0 <= position < 26:
            return f"Speaker {chr(ord('A') + position)}"
        return f"Speaker {position + 1}"


    def refresh_detected_speakers_section(self) -> None:
        card = getattr(self, "detected_speakers_card", None)
        layout = getattr(self, "detected_speakers_list_layout", None)
        if card is None or layout is None:
            return

        btn = getattr(self, "auto_assign_gender_voices_btn", None)
        if btn is not None and not getattr(self, "_auto_assign_btn_connected", False):
            self._auto_assign_btn_connected = True
            btn.clicked.connect(self.auto_assign_voices_by_audio_gender)

        # Voice catalog initialization happens during UI construction, before
        # a project (and therefore the segment lists) necessarily exists.
        segments = list(
            getattr(self, "current_translated_segments", None)
            or getattr(self, "current_segments", None)
            or []
        )
        speakers = self._detected_speaker_ids()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        card.setVisible(bool(speakers))
        if not speakers:
            if hasattr(self, "timeline"):
                self.timeline.set_highlighted_speaker("")
            return
        assignments = self._speaker_voice_assignments()
        for position, speaker in enumerate(speakers):
            entry = dict(assignments.get(speaker, {}) or {})
            display_name = self._speaker_display_name(speaker, position)
            segment_count = sum(
                1 for segment in segments
                if str(segment.get("speaker", "") or "").strip() == speaker
            )
            row = QFrame()
            row.setObjectName("statusCard")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(9, 8, 9, 8)
            row_layout.setSpacing(6)
            header = QHBoxLayout()
            indicator = QLabel()
            indicator.setFixedSize(12, 12)
            indicator.setStyleSheet(
                f"background: {self._speaker_color_hex(speaker)}; border-radius: 6px; border: 1px solid #dcecff;"
            )
            header.addWidget(indicator)
            speaker_label = QLabel(f"{display_name}  ·  {segment_count} segment{'s' if segment_count != 1 else ''}")
            speaker_label.setToolTip(f"Timeline ID: {speaker}")
            header.addWidget(speaker_label, 1)
            row_layout.addLayout(header)

            assigned_voice = str(entry.get("voice", "") or "")
            saved_gender = self._normalize_gender_value(str(entry.get("voice_gender_filter", "any") or "any"))

            # Tự động nhận diện âm thanh gốc nếu người nói này chưa từng được gán giọng
            if not assigned_voice and saved_gender in ("", "any"):
                det_g = self._detect_speaker_gender_auto(speaker, segments)
                if det_g == "male":
                    saved_gender = "male"
                    assigned_voice = "vieneu_thanhnientutin"
                else:
                    saved_gender = "female"
                    assigned_voice = "vieneu_cogaihoatbat"
                self._save_speaker_voice_assignment(speaker, voice=assigned_voice, voice_gender_filter=saved_gender)

            row_layout.addWidget(QLabel("Loại giọng"))
            gender_combo = QComboBox()
            gender_combo.addItem("Tất cả", "any")
            gender_combo.addItem("Nam", "male")
            gender_combo.addItem("Nữ", "female")
            saved_idx = gender_combo.findData(saved_gender)
            if saved_idx >= 0:
                gender_combo.setCurrentIndex(saved_idx)
            row_layout.addWidget(gender_combo)
            row_layout.addWidget(QLabel("Giọng đọc"))
            voice_combo = QComboBox()
            row_layout.addWidget(voice_combo)

            def _refresh_speaker_voice_combo(
                *,
                combo=voice_combo,
                filter_combo=gender_combo,
                assigned=assigned_voice,
            ):
                # ``"Use default voice"`` intentionally has an empty value;
                # do not fall back to the original assignment in that case.
                current_assigned = (
                    str(combo.currentData() or "")
                    if combo.count()
                    else str(assigned or "")
                )
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("Dùng giọng mặc định ở trên", "")
                chosen_gender = str(filter_combo.currentData() or filter_combo.currentText() or "any")
                for label, value in self._voice_display_entries(
                    gender=chosen_gender,
                    include_voice=current_assigned,
                ):
                    combo.addItem(label, value)
                voice_index = combo.findData(current_assigned)
                combo.setCurrentIndex(voice_index if voice_index >= 0 else 0)
                combo.blockSignals(False)

            _refresh_speaker_voice_combo()
            voice_combo.currentIndexChanged.connect(
                lambda _index, sp=speaker, combo=voice_combo: self._save_speaker_voice_assignment(
                    sp, voice=str(combo.currentData() or "")
                )
            )

            def _on_speaker_gender_changed(
                sp=speaker,
                filter_combo=gender_combo,
                refresh=_refresh_speaker_voice_combo,
            ):
                chosen_g = str(filter_combo.currentData() or "any")
                auto_v = None
                if chosen_g == "female":
                    auto_v = "vieneu_cogaihoatbat"
                elif chosen_g == "male":
                    auto_v = "vieneu_thanhnientutin"
                self._save_speaker_voice_assignment(sp, voice_gender_filter=chosen_g, voice=auto_v)
                refresh(assigned=auto_v or "")

            gender_combo.currentIndexChanged.connect(
                lambda _index, fn=_on_speaker_gender_changed: fn()
            )
            voice_combo.activated.connect(
                lambda _index, sp=speaker: self.highlight_timeline_speaker(sp)
            )
            reassign_row = QHBoxLayout()
            reassign_row.setContentsMargins(0, 0, 0, 0)
            reassign_row.setSpacing(6)
            reassign_row.addWidget(QLabel("Move all to"))
            reassign_combo = QComboBox()
            for target_position, target_speaker in enumerate(speakers):
                if target_speaker != speaker:
                    reassign_combo.addItem(
                        self._speaker_display_name(target_speaker, target_position),
                        target_speaker,
                    )
            reassign_button = QPushButton("Apply")
            reassign_button.setToolTip(
                f"Reassign every {display_name} subtitle segment to the selected speaker."
            )
            has_target = reassign_combo.count() > 0
            reassign_combo.setEnabled(has_target)
            reassign_button.setEnabled(has_target)
            reassign_button.clicked.connect(
                lambda _checked=False, source=speaker, combo=reassign_combo: self.reassign_all_speaker_segments(
                    source, str(combo.currentData() or "")
                )
            )
            reassign_row.addWidget(reassign_combo, 1)
            reassign_row.addWidget(reassign_button)
            row_layout.addLayout(reassign_row)
            row.mousePressEvent = lambda event, sp=speaker, original=row.mousePressEvent: (
                self.toggle_timeline_speaker_highlight(sp), original(event)
            )[-1]
            layout.addWidget(row)
        layout.addStretch()


    def _detect_speaker_gender_auto(self, speaker: str, segments: list[dict]) -> str:
        state = getattr(self, "current_project_state", None)
        audio_path = (
            getattr(self, "last_extracted_audio", "")
            or (state.artifacts.get("extracted_audio") if state else "")
            or (state.artifacts.get("audio_extracted") if state else "")
            or ""
        )
        if not audio_path or not os.path.isfile(audio_path):
            return "female"
        from services.capcut_bridge import detect_speaker_gender_from_audio
        spk_segs = [s for s in (segments or []) if str(s.get("speaker", "") or "").strip() == speaker]
        return detect_speaker_gender_from_audio(audio_path, spk_segs)


    def auto_assign_voices_by_audio_gender(self) -> None:
        """Execute Smart Multi-Speaker Auto-Cast:
        1. Diarize & align speakers if subtitles lack speaker tags.
        2. Multi-segment acoustic spectral gender detection.
        3. Rank Lead & Support roles via RoleScore (Duration, Utterances, Scenes).
        4. Map Lead Male -> Anh Dũng, Support Male -> Minh Quang, Lead Female -> Cô Gái Hoạt Ngôn, Support Female -> Ngọc Huyền.
        5. Save immutable speaker voice map and apply to all segments.
        """
        segments = list(
            getattr(self, "current_translated_segments", None)
            or getattr(self, "current_segments", None)
            or []
        )
        if not segments:
            QMessageBox.warning(self, "Chưa có phụ đề", "Vui lòng quét hoặc dịch phụ đề trước khi phân vai.")
            return

        state = getattr(self, "current_project_state", None)
        audio_path = (
            getattr(self, "last_extracted_audio", "")
            or (state.artifacts.get("extracted_audio") if state else "")
            or (state.artifacts.get("audio_extracted") if state else "")
            or ""
        )

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            QApplication.processEvents()
            # 1. If segments lack speaker IDs, run diarization & alignment
            has_speakers = any(str(s.get("speaker", "")).strip() for s in segments)
            if not has_speakers and audio_path and os.path.isfile(audio_path):
                try:
                    from services.speaker_diarization_service import SpeakerDiarizationService
                    from services.subtitle_speaker_aligner import align_subtitles_to_speakers
                    diar_service = SpeakerDiarizationService()
                    diar_turns = diar_service.diarize(
                        audio_path,
                        num_speakers=self.get_speaker_diarization_num_speakers(),
                    )
                    QApplication.processEvents()
                    if diar_turns:
                        segments = align_subtitles_to_speakers(segments, diar_turns)
                except Exception as e:
                    print(f"[Smart Cast] Diarization alignment fallback: {e}")

            # If still no speaker IDs, perform acoustic clustering into distinct turns
            has_speakers = any(str(s.get("speaker", "")).strip() for s in segments)
            if not has_speakers and audio_path and os.path.isfile(audio_path):
                from services.speaker_gender import detect_speaker_gender_aggregated
                for idx, s in enumerate(segments):
                    res = detect_speaker_gender_aggregated(audio_path, [s])
                    g = res.get("gender", "unknown")
                    s["speaker"] = f"SPEAKER_{g.upper()}_{idx % 2:02d}"
                QApplication.processEvents()

            # 2. Run Smart Auto-Cast Engine
            from services.smart_cast import auto_cast_speakers, apply_smart_cast_to_subtitles
            speaker_voice_map, profiles = auto_cast_speakers(
                segments,
                audio_path,
                expected_speakers=self.get_speaker_diarization_num_speakers(),
            )
            QApplication.processEvents()

            if not speaker_voice_map:
                QMessageBox.warning(self, "Không thể phân vai", "Không tìm thấy người nói hợp lệ để phân vai.")
                return

            # 3. Save voice assignments to project
            assigned_summary = []
            for spk, prof in profiles.items():
                assigned_voice = speaker_voice_map.get(spk, "")
                gender = prof.get("gender", "female")
                role_label = prof.get("role_label", "Nhân vật")
                dur = prof.get("speech_duration", 0.0)
                utts = prof.get("utterance_count", 0)
                self._save_speaker_voice_assignment(spk, voice=assigned_voice, voice_gender_filter=gender)
                assigned_summary.append(f"• {spk}: {role_label} ({dur}s, {utts} câu) ➔ {assigned_voice}")

            # 4. Apply to segments
            updated_segments = apply_smart_cast_to_subtitles(segments, speaker_voice_map, profiles=profiles)
            if getattr(self, "current_translated_segments", None):
                self.current_translated_segments = updated_segments
            if getattr(self, "current_segments", None):
                self.current_segments = updated_segments

            # 5. Refresh UI
            if hasattr(self, "subtitle_list_view"):
                self.subtitle_list_view.refresh_segments()
            if hasattr(self, "detected_speakers_card"):
                self.detected_speakers_card.show()
            self.refresh_detected_speakers_section()
            if hasattr(self, "timeline"):
                self.timeline.update()

            QMessageBox.information(
                self,
                "Phân vai tự động thông minh hoàn tất",
                "Đã phân tích âm thanh & kịch bản và tự động gán giọng thành công:\n\n" + "\n".join(assigned_summary),
            )
        finally:
            QApplication.restoreOverrideCursor()


    def highlight_timeline_speaker(self, speaker: str) -> None:
        if hasattr(self, "timeline"):
            self.timeline.set_highlighted_speaker(speaker)


    def toggle_timeline_speaker_highlight(self, speaker: str) -> None:
        """Toggle the presentation-only speaker highlight from its card."""
        timeline = getattr(self, "timeline", None)
        if timeline is None:
            return
        selected = str(speaker or "").strip()
        current = str(getattr(timeline, "_highlighted_speaker", "") or "").strip()
        timeline.set_highlighted_speaker("" if selected and selected == current else selected)


    def on_segment_speaker_changed(self, index: int, speaker: str) -> None:
        """Apply and persist a Phase 4 Character ID correction."""
        if getattr(self, "_syncing_segment_editor", False):
            return
        speaker = str(speaker or "").strip()
        active = list(self.get_active_segments() or [])
        selected = dict(active[index]) if 0 <= index < len(active) else {}
        old_speaker = str(selected.get("speaker", "") or "").strip()
        gender = "unknown"
        state = getattr(self, "current_project_state", None)
        registry = []
        if state is not None:
            registry = self.project_service.load_json_artifact(
                state, "character_registry", default=[]
            ) or []
        profile = next(
            (item for item in registry if str(item.get("character_id", "") or "") == speaker),
            {},
        )
        gender = str(profile.get("gender", selected.get("character_gender", "unknown")) or "unknown")
        updated = False
        for segments_list in (
            getattr(self, "current_segments", None),
            getattr(self, "current_translated_segments", None),
        ):
            if segments_list and 0 <= index < len(segments_list):
                if speaker:
                    segments_list[index]["speaker"] = speaker
                    if speaker.startswith("CHAR_"):
                        segments_list[index]["character_id"] = speaker
                        segments_list[index]["character_gender"] = gender
                        segments_list[index]["character_confidence"] = 1.0
                        segments_list[index]["character_source"] = "manual_correction"
                else:
                    segments_list[index].pop("speaker", None)
                updated = True
        if not updated:
            return
        if state is not None and speaker.startswith("CHAR_"):
            from services import CharacterCorrectionService
            corrections = self.project_service.load_json_artifact(
                state, "character_corrections", default=[]
            ) or []
            corrections = CharacterCorrectionService.upsert(corrections, {
                "start": float(selected.get("start", 0.0) or 0.0),
                "end": float(selected.get("end", 0.0) or 0.0),
                "character_id": speaker,
                "character_gender": gender,
                "previous_character_id": old_speaker,
            })
            self.project_service.save_json_artifact(
                state,
                "character_corrections",
                os.path.join("analysis", "character_corrections.json"),
                corrections,
            )
            self.log(
                f"[Character Correction] Câu #{index + 1}: {old_speaker or 'UNKNOWN'} -> {speaker}. "
                "Correction đã được lưu để cập nhật prototype ở lần chạy tiếp theo."
            )
        self._sync_segment_models_from_current_segments()
        self._voiceover_force_refresh = True
        # Speaker identity changes the TS1 color and future voice selection,
        # not subtitle text, timing, or visual style.  Avoid the full
        # apply_segments_to_timeline() path here because it refreshes the
        # live subtitle preview assets and rewrites its SRT unnecessarily.
        if hasattr(self, "timeline"):
            self.timeline.set_segments(self.get_active_segments())
            self.timeline.set_active_segment_index(index)
        self._refresh_speaker_subtitle_colors_if_needed()
        self.refresh_detected_speakers_section()
        self.persist_current_timeline_project_data()


    def reassign_all_speaker_segments(self, source_speaker: str, target_speaker: str) -> None:
        """Move every cue from one diarized speaker to another."""
        source_speaker = str(source_speaker or "").strip()
        target_speaker = str(target_speaker or "").strip()
        if not source_speaker or not target_speaker or source_speaker == target_speaker:
            return
        changed_indexes: set[int] = set()
        for segments_list in (
            getattr(self, "current_segments", None),
            getattr(self, "current_translated_segments", None),
        ):
            if not segments_list:
                continue
            for index, segment in enumerate(segments_list):
                if str(segment.get("speaker", "") or "").strip() == source_speaker:
                    segment["speaker"] = target_speaker
                    changed_indexes.add(index)
        if not changed_indexes:
            return
        self._sync_segment_models_from_current_segments()
        self._voiceover_force_refresh = True
        if hasattr(self, "timeline"):
            self.timeline.set_segments(self.get_active_segments())
            self.timeline.set_highlighted_speaker(target_speaker)
        self._refresh_speaker_subtitle_colors_if_needed()
        self.refresh_detected_speakers_section()
        self.persist_current_timeline_project_data()
        self.log(
            f"[Diarization] Reassigned {len(changed_indexes)} segment(s) "
            f"from {source_speaker} to {target_speaker}."
        )


    def open_normalizer_dict_dialog(self):
        """Edit the pronunciation dictionary stored in this project.

        This is deliberately project state rather than a global CSV resource:
        the same word may need different pronunciation in different videos.
        The dictionary is passed to Piper only; subtitle text is untouched.
        """
        if not str(self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""):
            QMessageBox.information(self, "Từ điển phát âm", "Vui lòng mở một dự án trước khi chỉnh sửa từ điển phát âm.")
            return
        state = self.ensure_current_project()
        if state is None:
            QMessageBox.information(self, "Từ điển phát âm", "Vui lòng mở một dự án trước khi chỉnh sửa từ điển phát âm.")
            return
        if not self._translation_phase_complete():
            QMessageBox.information(self, "Từ điển phát âm", "Vui lòng hoàn thành bước Dịch thuật trước khi chỉnh sửa từ điển dự án.")
            return

        DICT_DEFS = [
            {"label": "Từ viết tắt", "key": "acronyms", "col_a": "acronym", "col_b": "transliteration", "header_a": "Từ viết tắt", "header_b": "Cách đọc"},
            {"label": "Từ nước ngoài", "key": "non_vietnamese_words", "col_a": "original", "col_b": "transliteration", "header_a": "Từ gốc", "header_b": "Cách đọc"},
        ]

        dialog = QDialog(self)
        dialog.setWindowTitle("Từ điển phát âm")
        dialog.setModal(True)
        dialog.resize(700, 520)
        dialog.setStyleSheet("""
            QDialog { background-color: #0f1724; }
            QLabel { color: #d7e3f4; background-color: transparent; }
            QTableWidget { background-color: #132033; color: #d7e3f4; gridline-color: #2f4868;
                border: 1px solid #2f4868; border-radius: 8px; font-size: 13px; }
            QTableWidget::item:selected { background-color: #29405d; color: #f8fbff; }
            QHeaderView::section { background-color: #1a2c44; color: #8ad7ff; border: none;
                padding: 6px 8px; font-weight: 700; font-size: 12px; }
            QPushButton { background-color: #22344d; color: #f8fbff; border: 1px solid #34506f;
                border-radius: 8px; padding: 6px 16px; font-weight: 600; }
            QPushButton:hover { background-color: #29405d; }
            QPushButton#dangerBtn { background-color: #5a1a1a; border-color: #8b2a2a; }
            QPushButton#dangerBtn:hover { background-color: #7a2828; }
            QPushButton#primaryBtn { background-color: #1a4a5a; border-color: #2a6a8b; }
            QPushButton#primaryBtn:hover { background-color: #1e5a6e; }
            QTabWidget::pane { border: 1px solid #2f4868; background-color: #0f1724; border-radius: 8px; }
            QTabBar::tab { background-color: #1a2c44; color: #9fb3ca; padding: 8px 20px; border: 1px solid #2f4868;
                border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }
            QTabBar::tab:selected { background-color: #132033; color: #8ad7ff; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Quản lý từ điển phát âm", dialog)
        title.setStyleSheet("color: #f8fbff; font-size: 16px; font-weight: 700;")
        layout.addWidget(title)

        project_name = str(getattr(state, "project_id", "") or "dự án hiện tại")
        hint = QLabel(
            f"Dự án: {project_name}\n"
            "Các mục chỉ ảnh hưởng đến cách đọc của Piper; văn bản phụ đề dịch sẽ không bị thay đổi.",
            dialog,
        )
        hint.setStyleSheet("color: #9fb3ca; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        from PySide6.QtWidgets import QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView
        tabs = QTabWidget(dialog)
        layout.addWidget(tabs, 1)

        tables = {}

        for defn in DICT_DEFS:
            tab = QWidget(dialog)
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(8, 8, 8, 8)
            tab_layout.setSpacing(8)

            table = QTableWidget(0, 2, dialog)
            table.setHorizontalHeaderLabels([defn.get("header_a", defn["col_a"].title()), defn.get("header_b", defn["col_b"].title())])
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.verticalHeader().setVisible(False)
            tab_layout.addWidget(table, 1)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(8)
            add_btn = QPushButton("+ Thêm dòng", dialog)
            remove_btn = QPushButton("Xóa dòng chọn", dialog)
            remove_btn.setObjectName("dangerBtn")
            btn_row.addWidget(add_btn)
            btn_row.addWidget(remove_btn)
            btn_row.addStretch()
            tab_layout.addLayout(btn_row)

            add_btn.clicked.connect(lambda _checked=False, t=table: self._vietdict_add_row(t))
            remove_btn.clicked.connect(lambda _checked=False, t=table: self._vietdict_remove_row(t))

            tables[defn["key"]] = {"table": table, "defn": defn}
            tabs.addTab(tab, defn["label"])

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addStretch()

        save_btn = QPushButton("Lưu tất cả", dialog)
        save_btn.setObjectName("primaryBtn")
        close_btn = QPushButton("Đóng", dialog)
        close_btn.clicked.connect(dialog.accept)
        bottom_row.addWidget(save_btn)
        bottom_row.addWidget(close_btn)
        layout.addLayout(bottom_row)

        def _load_all():
            settings = getattr(state, "settings", {}) or {}
            dictionary = settings.get("normalizer_dictionary", {}) or {}
            for key, meta in tables.items():
                rows = dictionary.get(key, []) if isinstance(dictionary, dict) else []
                table = meta["table"]
                table.setRowCount(0)
                if isinstance(rows, dict):
                    rows = [rows]
                for row in rows if isinstance(rows, (list, tuple)) else []:
                    if not isinstance(row, dict):
                        continue
                    a = str(row.get(meta["defn"]["col_a"], row.get("key", "")) or "").strip()
                    b = str(row.get(meta["defn"]["col_b"], row.get("value", "")) or "").strip()
                    if a or b:
                        r = table.rowCount()
                        table.insertRow(r)
                        table.setItem(r, 0, QTableWidgetItem(a))
                        table.setItem(r, 1, QTableWidgetItem(b))

        def _save_all():
            dictionary = {}
            for key, meta in tables.items():
                table = meta["table"]
                rows = []
                for r in range(table.rowCount()):
                    a = (table.item(r, 0).text() if table.item(r, 0) else "").strip()
                    b = (table.item(r, 1).text() if table.item(r, 1) else "").strip()
                    if a or b:
                        rows.append({meta["defn"]["col_a"]: a, meta["defn"]["col_b"]: b})
                dictionary[key] = rows
            try:
                state.set_setting("normalizer_dictionary", dictionary)
                self.current_project_state = state
                self.project_service.save_project(state)
                try:
                    from tts_processor import reset_vietnamese_normalizer_cache
                    reset_vietnamese_normalizer_cache()
                except Exception as exc:
                    self.log(f"[VietDict] Cache refresh warning: {exc}")
                self._voiceover_force_refresh = True
                self._pending_voice_signature = ""
                self.log(f"[VietDict] Saved project pronunciation dictionary ({project_name}).")
                self.refresh_ui_state()
                QMessageBox.information(dialog, "Normalizer Dictionary", "Project dictionary saved. New Preview Voice, Regenerate Voice, and TTS runs will use it immediately.")
            except Exception as exc:
                self.log(f"[VietDict] Save failed: {exc}")
                QMessageBox.critical(dialog, "Normalizer Dictionary", "Could not save the project dictionary. No pronunciation changes were applied.\n\n" + str(exc))

        save_btn.clicked.connect(_save_all)

        _load_all()
        dialog.exec()


    def _tts_audio_track_state(self) -> dict:
        """Return the generated voice track's timeline volume/mute state."""
        timeline = getattr(self, "timeline", None)
        model = getattr(timeline, "_timeline", None) if timeline is not None else None
        state = {"volume": 100.0, "muted": False, "solo": False, "track_name": "TS1"}
        for track in getattr(model, "tracks", []) or [] if model is not None else []:
            name = str(getattr(track, "name", "") or "")
            if name not in ("TS1", "A2 Dub"):
                continue
            metadata = getattr(track, "metadata", {}) or {}
            try:
                state["volume"] = float(metadata.get("_volume", 100.0))
            except (TypeError, ValueError):
                state["volume"] = 100.0
            state["muted"] = bool(
                getattr(track, "muted", False)
                or metadata.get("_muted", False)
                or self._is_audio_track_muted(name)
            )
            state["solo"] = bool(getattr(track, "solo", False) or metadata.get("_solo", False))
            state["track_name"] = name
            break
        return state


    def _resolve_preview_voice_only_audio_path(self) -> str:
        if self.using_existing_audio_source():
            return ""
        candidates = [
            self.processed_artifacts.get("voice_vi"),
            self.last_voice_vi_path,
        ]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return normalized
        # Older projects may have persisted the generated WAV only on the
        # TS1 DubSubtitle layers, without a top-level voice_vi artifact.  Use
        # that canonical layer reference as a recovery path after reopening.
        timeline = getattr(self, "timeline", None)
        model = getattr(timeline, "_timeline", None) if timeline is not None else None
        for track in getattr(model, "tracks", []) or [] if model is not None else []:
            if str(getattr(track, "name", "")) not in ("TS1", "A2 Dub"):
                continue
            for layer in getattr(track, "layers", []) or []:
                metadata = getattr(layer, "metadata", {}) or {}
                for candidate in (
                    getattr(layer, "audio_path", ""),
                    metadata.get("audio_path", ""),
                    metadata.get("_audio_path", ""),
                ):
                    normalized = self._normalize_local_file_path(candidate)
                    if normalized and os.path.exists(normalized):
                        return normalized
        # Legacy releases sometimes stored only mixed_vi.  It is still a
        # valid dubbed sidecar when there is no separate Music Layer.
        if not self._music_audio_tracks():
            for candidate in (
                self.processed_artifacts.get("mixed_vi"),
                self.last_mixed_vi_path,
            ):
                normalized = self._normalize_local_file_path(candidate)
                if normalized and os.path.exists(normalized):
                    return normalized
        return ""


    def _resolve_preview_dubbed_audio_path(self) -> str:
        mixed_audio = self._resolve_preview_mixed_audio_path()
        if mixed_audio:
            return mixed_audio
        return self._resolve_preview_voice_only_audio_path()


    def _has_preview_dubbed_audio_source(self) -> bool:
        if self.using_existing_audio_source():
            audio_path = self._normalize_local_file_path(self.mixed_audio_edit.text().strip())
            return bool(audio_path and os.path.exists(audio_path))
        return bool(self._resolve_preview_voice_only_audio_path() or self._music_audio_tracks())


    def build_current_voice_signature(self, segments=None, background_path=""):
        voice_segments = list(segments or [])
        if not voice_segments:
            voice_segments = self._get_voiceover_segments()
        if not voice_segments:
            return ""
        normalizer_signature = ""
        try:
            from tts_processor import normalizer_dictionary_fingerprint
            settings = getattr(self.current_project_state, "settings", {}) or {}
            normalizer_signature = normalizer_dictionary_fingerprint(
                settings.get("normalizer_dictionary", {})
            )
        except Exception:
            # Signature generation must not prevent a project from opening;
            # the TTS cache still remains usable when the optional normalizer
            # package is unavailable.
            normalizer_signature = ""
        return self.project_service.build_voice_signature(
            voice_segments,
            audio_handling_mode=self.get_audio_handling_mode(),
            voice_name=self.get_active_voice_name(),
            voice_speed=self._parse_voice_speed_value(),
            timing_sync_mode=str(self.voice_timing_sync_combo.currentText()).strip(),
            background_path=background_path,
            original_volume=int(self.audio_a1_volume_slider.value()) if hasattr(self, "audio_a1_volume_slider") else 50,
            dub_volume=int(self.audio_a2_volume_slider.value()) if hasattr(self, "audio_a2_volume_slider") else 100,
            normalizer_signature=normalizer_signature,
        )


    def has_reusable_voice_inputs(self) -> bool:
        state = self.ensure_current_project()
        if state and not self.translated_text.toPlainText().strip():
            self.load_project_context(state)
        translated_srt = self.translated_text.toPlainText().strip()
        if not translated_srt:
            return False
        return bool(self.parse_srt_to_segments(translated_srt))


    def is_speaker_diarization_enabled(self) -> bool:
        return bool(
            hasattr(self, "speaker_diarization_cb")
            and self.speaker_diarization_cb.isChecked()
        )


    def get_speaker_diarization_num_speakers(self) -> int:
        combo = getattr(self, "speaker_diarization_speakers_combo", None)
        if combo is None:
            return -1
        try:
            value = int(combo.currentData())
            return value if value >= 2 else -1
        except (TypeError, ValueError):
            return -1


    def refresh_speaker_analysis_summary(self) -> None:
        hint = getattr(self, "speaker_diarization_hint_label", None)
        if hint is None:
            return
        state = getattr(self, "current_project_state", None)
        summary = dict(getattr(state, "settings", {}).get("speaker_analysis_summary") or {}) if state else {}
        characters = dict(getattr(state, "settings", {}).get("character_analysis_summary") or {}) if state else {}
        analysis_error = str(getattr(state, "settings", {}).get("speaker_analysis_error", "") or "") if state else ""
        if analysis_error:
            hint.setText(
                "Lỗi Character Resolver — TTS đã bị chặn để tránh gán sai giọng: "
                + analysis_error
            )
            hint.setStyleSheet("color: #f87171; font-weight: 600;")
            return
        hint.setStyleSheet("")
        if characters:
            hint.setText(
                "Kết quả Character Resolver: "
                f"{int(characters.get('character_count', 0) or 0)} nhân vật có thoại — "
                f"{int(characters.get('male_count', 0) or 0)} nam, "
                f"{int(characters.get('female_count', 0) or 0)} nữ; "
                f"{int(characters.get('unknown_turn_count', 0) or 0)} lượt chưa chắc chắn; "
                f"Phase 3 tách {int(characters.get('split_turn_count', 0) or 0)} lượt đổi người nói; "
                f"Phase 2 nhận lại {int(characters.get('voice_resolved_turn_count', 0) or 0)} lượt qua dấu vân tay giọng; "
                f"Phase 4 áp dụng {int(characters.get('manual_correction_count', 0) or 0)} sửa tay."
            )
            return
        if not summary:
            hint.setText(
                "Khi có khóa OpenAI, TankVideo sẽ tự phân tích số người nói trước bước chép lời; "
                "nếu không, chương trình dùng Sherpa-ONNX cục bộ."
            )
            return
        hint.setText(
            "Kết quả âm thanh trước chép lời: "
            f"{int(summary.get('speaker_count', 0) or 0)} cụm giọng — "
            f"{int(summary.get('male_count', 0) or 0)} nam, "
            f"{int(summary.get('female_count', 0) or 0)} nữ, "
            f"{int(summary.get('unknown_count', 0) or 0)} chưa chắc chắn."
        )


    def update_speaker_diarization_availability(self) -> None:
        checkbox = getattr(self, "speaker_diarization_cb", None)
        hint = getattr(self, "speaker_diarization_hint_label", None)
        card = getattr(self, "speaker_diarization_card", None)
        speakers_combo = getattr(self, "speaker_diarization_speakers_combo", None)
        if checkbox is None:
            return
        # Cho phép diarization cả khi dùng OCR (Chế độ Hybrid thông minh)
        available = True
        checkbox.setEnabled(available)
        checkbox.setVisible(available)
        if card is not None:
            card.setVisible(available)
        if speakers_combo is not None:
            speakers_combo.setEnabled(available)
        if hint is not None:
            hint.setVisible(available)
        checkbox.setToolTip(
            "Nhận diện người nói offline bằng Sherpa-ONNX để tự động phân vai giọng đọc thông minh."
        )


    def is_ai_dubbing_rewrite_enabled(self):
        return bool(getattr(self, "ai_dubbing_rewrite_cb", None) and self.ai_dubbing_rewrite_cb.isChecked())


    def get_ai_dubbing_style_instruction(self):
        if hasattr(self, "translator_style_edit"):
            return " ".join(self.translator_style_edit.text().split()).strip()
        return ""


    def _resolve_segment_voice_text(self, segment: dict) -> str:
        current = dict(segment or {})
        subtitle_text = " ".join(str(current.get("text", "") or "").split()).strip()
        if bool(current.get("voice_edited")):
            edited_text = " ".join(str(current.get("tts_text") or current.get("dubbing_vi") or "").split()).strip()
            if edited_text:
                return edited_text
        return subtitle_text


    def on_segment_voice_speed_changed(self, index: int, value: float):
        if getattr(self, "_syncing_segment_editor", False):
            return
        for segments_list in (self.current_translated_segments, self.current_segments):
            if segments_list and 0 <= index < len(segments_list):
                segments_list[index]["voice_speed"] = round(float(value), 1)
                self._voiceover_force_refresh = True
        self.persist_current_timeline_project_data()


    def _stop_voice_library_preview(self):
        try:
            self.voice_preview_library_player.stop()
            self.voice_preview_library_player.setSource(QUrl())
        except Exception:
            pass
        for button in self._voice_preview_row_buttons.values():
            button.setText("Preview")


    def _build_voice_preview_popup(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Thư viện nghe thử giọng đọc")
        dialog.setModal(False)
        dialog.resize(720, 560)
        dialog.setStyleSheet(
            """
            QDialog {
                background-color: #0f1724;
            }
            QWidget {
                background-color: #0f1724;
                color: #dbe5f3;
            }
            QScrollArea {
                border: none;
                background-color: #0f1724;
            }
            QLabel#statusHeadline {
                color: #f8fbff;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#sectionTitle {
                color: #8ad7ff;
                font-weight: 700;
            }
            QLabel#helperLabel {
                color: #9fb3ca;
            }
            QFrame#statusCard {
                background-color: #132033;
                border: 1px solid #2f4868;
                border-radius: 12px;
            }
            QPushButton {
                background-color: #22344d;
                color: #f8fbff;
                border: 1px solid #34506f;
                border-radius: 10px;
                padding: 8px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #29405d;
            }
            QPushButton:disabled {
                background-color: #172435;
                color: #7f92a9;
                border-color: #24384f;
            }
            """
        )

        root_layout = QVBoxLayout(dialog)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        title = QLabel("Thư viện nghe thử giọng đọc", dialog)
        title.setObjectName("statusHeadline")
        root_layout.addWidget(title)

        hint = QLabel(
            "Nghe thử các mẫu giọng đọc đã cấu hình tại đây. Cửa sổ này sử dụng trình phát riêng và không ảnh hưởng đến timeline video chính.",
            dialog,
        )
        hint.setObjectName("helperLabel")
        hint.setWordWrap(True)
        root_layout.addWidget(hint)

        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget(scroll)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        current_provider = None
        self._voice_preview_row_buttons = {}
        entries = sorted(
            list(self.voice_catalog_entries_all or []),
            key=lambda item: (
                str(item.get("tier", "")),
                self._voice_provider_label(str(item.get("provider", ""))),
                str(item.get("name", "")),
            ),
        )
        for entry in entries:
            provider = self._voice_provider_label(str(entry.get("provider", "")).strip())
            if provider != current_provider:
                current_provider = provider
                header = QLabel(provider, container)
                header.setObjectName("sectionTitle")
                layout.addWidget(header)

            row = QFrame(container)
            row.setObjectName("statusCard")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(10)

            label = QLabel(str(entry.get("name", entry.get("id", "Voice"))), row)
            label.setWordWrap(True)
            meta = QLabel(str(entry.get("tier", "voice")).strip().title(), row)
            meta.setObjectName("helperLabel")
            preview_btn = QPushButton("Nghe thử", row)
            preview_btn.setEnabled(self._entry_has_preview_media(entry))
            preview_btn.clicked.connect(lambda _checked=False, item=entry, btn=preview_btn: self._play_voice_preview_entry(item, btn))

            row_layout.addWidget(label, 1)
            row_layout.addWidget(meta)
            row_layout.addWidget(preview_btn)
            layout.addWidget(row)
            self._voice_preview_row_buttons[str(entry.get("id", ""))] = preview_btn

        layout.addStretch()
        scroll.setWidget(container)
        root_layout.addWidget(scroll, 1)

        close_btn = QPushButton("Đóng", dialog)
        close_btn.clicked.connect(dialog.close)
        root_layout.addWidget(close_btn, 0, Qt.AlignRight)

        dialog.finished.connect(lambda _result: self._stop_voice_library_preview())
        self.voice_preview_dialog = dialog
        return dialog


    def preview_selected_voice_sample(self):
        if not (self.voice_catalog_entries or []):
            QMessageBox.information(self, "Nghe thử giọng", "Chưa có giọng đọc nội bộ nào khả dụng. Vui lòng thêm mô hình Piper vào thư mục models/piper trước.")
            return

        voice_name = self.get_active_voice_name()
        if not voice_name:
            QMessageBox.warning(self, "Preview voice", "Choose a voice first.")
            return

        voice_entry = (getattr(self, "voice_catalog_map", {}) or {}).get(voice_name, {})
        if isinstance(voice_entry, dict) and voice_entry.get("provider") in ("capcut", "vieneu"):
            preview_rel = voice_entry.get("preview_audio_path", "")
            preview_path = os.path.join(self.workspace_root, preview_rel) if preview_rel else ""
            if preview_path and os.path.isfile(preview_path):
                try:
                    self.play_audio_preview_file(preview_path)
                    self.log(f"[Voice Preview] playing sample: {preview_path}")
                    return
                except Exception as exc:
                    self.show_error("Voice Preview Failed", "Could not play preview audio.", str(exc))
                    return

        if not self.ensure_required_resources("Voice preview", include_voice=True):
            return
        voice_speed = self._parse_voice_speed_value()
        text = "Chào bạn, đây là bản xem trước giọng nói của mẫu được chọn."  # "Hello, this is a preview of the selected voice sample." in Vietnamese

        if hasattr(self, "preview_voice_btn"):
            self.preview_voice_btn.setEnabled(False)
            self.preview_voice_btn.setText("...")

        project_state = getattr(self, "current_project_state", None) or self.ensure_current_project()
        project_settings = getattr(project_state, "settings", {}) or {}
        normalizer_dictionary = dict(project_settings.get("normalizer_dictionary", {}) or {})
        worker = VoiceSamplePreviewWorker(
            self.workspace_root,
            text,
            voice_name,
            voice_speed,
            temp_dir=self.get_project_temp_dir("voice_sample_preview"),
            normalizer_dictionary=normalizer_dictionary,
        )
        worker.progress.connect(self.log)
        worker.finished.connect(self.on_voice_sample_preview_ready)
        self._voice_sample_preview_thread = worker
        worker.start()


    def on_voice_sample_preview_ready(self, audio_path: str, error: str):
        if hasattr(self, "preview_voice_btn"):
            self.preview_voice_btn.setEnabled(True)
            self.preview_voice_btn.setText("Nghe thử giọng đọc")
        self._voice_sample_preview_thread = None

        if error:
            self.show_error("Voice Preview Failed", "Could not generate the preview audio.", error)
            return
        if not audio_path:
            self.show_error("Voice Preview Failed", "Preview audio path is missing.", "")
            return

        try:
            self.play_audio_preview_file(audio_path)
            self.log(f"[Voice Preview] playing generated sample: {audio_path}")
        except Exception as exc:
            self.show_error("Voice Preview Failed", "Could not play the generated preview audio.", str(exc))


    def run_tts_for_segment(
        self,
        index: int,
        voice_name: str = "",
        text: str = "",
        play_immediately: bool = True,
        callback: callable = None,
    ):
        source_segments = self.current_translated_segments or self.current_segments
        if not source_segments or index < 0 or index >= len(source_segments):
            if callback:
                callback(False, "")
            return

        seg = source_segments[index]
        if not text:
            text = str(seg.get("tts_text") or seg.get("translated") or seg.get("text", "")).strip()
        if not text:
            if callback:
                callback(False, "")
            return

        if not voice_name:
            voice_name = str(seg.get("voice_custom") or "").strip()
            if not voice_name and hasattr(self, "subtitle_list_view") and hasattr(self.subtitle_list_view, "get_group_voice_id"):
                grp = str(seg.get("voice_group", "") or "")
                if grp:
                    voice_name = self.subtitle_list_view.get_group_voice_id(grp)
            if not voice_name:
                voice_name = self.get_active_voice_name() or "ngochuyen"

        voice_speed = self._parse_voice_speed_value() if hasattr(self, "_parse_voice_speed_value") else 1.0
        project_state = getattr(self, "current_project_state", None) or self.ensure_current_project()
        project_settings = getattr(project_state, "settings", {}) or {}
        normalizer_dictionary = dict(project_settings.get("normalizer_dictionary", {}) or {})

        existing = self._segment_preview_threads.get(index)
        if existing and existing.isRunning():
            try:
                existing.quit()
                existing.wait(500)
            except Exception:
                pass

        worker = SegmentAudioPreviewWorker(
            self.workspace_root,
            index,
            text,
            voice_name,
            voice_speed,
            temp_dir=self.get_project_temp_dir("segment_audio_preview"),
            cache_temp_dir=self.get_project_temp_dir("tts"),
            normalizer_dictionary=normalizer_dictionary,
        )

        def _on_done(idx, audio_path, error):
            self._segment_preview_threads.pop(idx, None)
            if error or not audio_path or not os.path.exists(audio_path):
                if callback:
                    callback(False, "")
                return
            if play_immediately:
                try:
                    self.play_audio_preview_file(audio_path)
                except Exception as exc:
                    print(f"[run_tts_for_segment] Audio play error: {exc}")
            if callback:
                callback(True, audio_path)

        worker.finished.connect(_on_done)
        self._segment_preview_threads[index] = worker
        worker.start()


    def _get_voiceover_segments(self):
        source_segments = list(self.current_translated_segments or [])
        if not source_segments:
            translated_srt = self.translated_text.toPlainText().strip()
            return self._apply_speaker_voice_assignments(self.parse_srt_to_segments(translated_srt)) if translated_srt else []

        grouped_segments = []
        idx = 0
        while idx < len(source_segments):
            segment = dict(source_segments[idx])
            group_id = str(segment.get('tts_group_id', '') or '').strip()
            tts_text = self._resolve_segment_voice_text(segment)
            if not group_id:
                segment['text'] = tts_text
                segment['tts_text'] = str(segment.get('tts_text') or '').strip() if bool(segment.get('voice_edited')) else ''
                grouped_segments.append(segment)
                idx += 1
                continue

            group_items = [segment]
            cursor = idx + 1
            while cursor < len(source_segments):
                candidate = source_segments[cursor]
                if str(candidate.get('tts_group_id', '') or '').strip() != group_id:
                    break
                group_items.append(dict(candidate))
                cursor += 1

            voice_text = ""
            voice_edited = False
            for item in group_items:
                if bool(item.get('voice_edited')):
                    candidate_text = " ".join(str(item.get('tts_text') or item.get('dubbing_vi') or '').split()).strip()
                    if candidate_text:
                        voice_text = candidate_text
                        voice_edited = True
                        break
            if not voice_text:
                voice_text = ' '.join(
                    ' '.join(str(item.get('text') or '').split()).strip()
                    for item in group_items
                ).strip()

            grouped_segments.append({
                'start': float(group_items[0].get('tts_group_start', group_items[0].get('start', 0.0)) or group_items[0].get('start', 0.0)),
                'end': float(group_items[-1].get('tts_group_end', group_items[-1].get('end', 0.0)) or group_items[-1].get('end', 0.0)),
                'text': voice_text,
                'tts_text': voice_text if voice_edited else '',
                'tts_group_id': group_id,
                'voice_edited': voice_edited,
                'source_text': ' '.join(
                    ' '.join(str(item.get('source_text') or item.get('text') or '').split()).strip()
                    for item in group_items
                ).strip(),
                'speaker': str(group_items[0].get('speaker', '') or ''),
            })
            idx = cursor
        return self._apply_speaker_voice_assignments(grouped_segments)


    def run_voiceover(self, force_refresh: bool | None = None):
        if not self.ensure_required_resources("Voice generation", include_voice=True):
            return
        state = self.ensure_current_project()
        if state and not self.translated_text.toPlainText().strip():
            self.load_project_context(state)

        translated_srt = self.translated_text.toPlainText().strip()
        if not translated_srt:
            QMessageBox.warning(self, "Error", "No translated SRT available. Please run translation first (STEP 3).")
            return

        segments = self._get_voiceover_segments()
        if not segments:
            QMessageBox.warning(self, "Error", "Translated SRT could not be parsed to segments.")
            return

        # Some GUI refresh paths retain only the flattened CHAR_x label. The
        # authoritative diarization artifact still has gender/confidence and
        # source, so rehydrate immediately before the integrity gate instead
        # of reporting every otherwise-resolved cue as AI 0%.
        if state is not None:
            diarization_path = str(state.artifacts.get("speaker_diarization", "") or "")
            if diarization_path and os.path.exists(diarization_path):
                speaker_turns = self.project_service.load_json_artifact(
                    state, "speaker_diarization", default=[]
                ) or []
                if speaker_turns:
                    # Final Assignment must run at the actual TTS boundary as
                    # well as during Prepare.  OCR can be regrouped differently
                    # on a later GUI refresh; never gate stale UNKNOWN metadata.
                    from services import PostOCRCharacterResolver
                    speaker_turns, repaired_count = (
                        PostOCRCharacterResolver.apply_temporal_continuity(speaker_turns)
                    )
                    if repaired_count:
                        self.project_service.save_json_artifact(
                            state,
                            "speaker_diarization",
                            os.path.join("analysis", "speaker_diarization.json"),
                            speaker_turns,
                        )
                        self.log(
                            "[Final Character Assignment] Repaired "
                            f"{repaired_count} contiguous OCR cue(s) before TTS."
                        )
                    from services.subtitle_speaker_aligner import align_subtitles_to_speakers
                    segments = align_subtitles_to_speakers(segments, speaker_turns)

        # Never turn missing/ambiguous character metadata into a confidently
        # wrong voice. Manual corrections carry confidence=1 and pass here.
        character_pipeline_enabled = bool(
            state and state.settings.get("speaker_diarization_enabled", False)
        )
        if character_pipeline_enabled or any(
            str(item.get("character_id", "") or "").strip() for item in segments
        ):
            from services import CharacterIntegrityGate
            integrity = CharacterIntegrityGate.inspect(segments)
            if not integrity["passed"]:
                examples = integrity["issues"][:5]
                details = "\n".join(
                    f"- #{item['segment_index'] + 1} {item['start']:.2f}s: "
                    f"{', '.join(item['reasons'])}"
                    for item in examples
                )
                self.log(
                    "[Character Integrity Gate] TTS blocked: "
                    f"{integrity['issue_count']} unresolved/ambiguous cue(s)."
                )
                if getattr(self, "_pipeline_active", False):
                    self.pipeline_controller.pipeline_review_required(
                        f"{integrity['issue_count']} câu chưa xác định chắc chắn nhân vật; TTS chưa được tạo."
                    )
                QMessageBox.warning(
                    self,
                    "Cần kiểm tra nhân vật trước khi tạo giọng",
                    f"Còn {integrity['issue_count']} câu chưa đủ chắc chắn để gán voice.\n"
                    "Hãy mở bộ lọc 'Cần kiểm tra' và xác nhận nhân vật.\n\n"
                    f"{details}",
                )
                return

        out_dir = self.voice_output_folder_edit.text().strip() or os.path.join(self.workspace_root, "output")
        bg_path = self.resolve_background_audio_path()
        audio_handling_mode = self.get_audio_handling_mode()
        voice_name = self._resolve_active_voice_name(persist_new_clone=True)
        if not voice_name:
            QMessageBox.warning(self, "Missing Voice", "Choose a voice first.")
            return
        if state is not None and state.settings.get("tts_skipped", False):
            # Starting TTS explicitly re-enables the generated voice path.
            state.set_setting("tts_skipped", False)
            self.project_service.save_project(state)
        voice_speed = self._parse_voice_speed_value()
        timing_sync_mode = str(self.voice_timing_sync_combo.currentText()).strip()
        original_volume = int(self.audio_a1_volume_slider.value()) if hasattr(self, "audio_a1_volume_slider") else 50
        dub_volume = int(self.audio_a2_volume_slider.value()) if hasattr(self, "audio_a2_volume_slider") else 100
        voice_signature = self.build_current_voice_signature(segments=segments, background_path=bg_path)
        if state and voice_signature:
            force_refresh = (
                bool(getattr(self, "_voiceover_force_refresh", False))
                if force_refresh is None else bool(force_refresh)
            )
            cached_voice_signature = str(state.settings.get("voice_signature", "") or "").strip()
            cached_voice_track = self._normalize_local_file_path(state.artifacts.get("voice_vi", "") or self.last_voice_vi_path)
            cached_mixed_track = self._normalize_local_file_path(state.artifacts.get("mixed_vi", "") or self.last_mixed_vi_path)
            # TTS generation caches the standalone voice track.  Music and
            # volume are composed later for preview/export, so a Music Layer
            # must not force a second TTS synthesis just because no legacy
            # mixed_vi artifact exists.
            required_output = cached_voice_track
            self.log(
                f"[Voiceover] Cache check: force={force_refresh}, "
                f"cached_sig={'<empty>' if not cached_voice_signature else cached_voice_signature[:16]+'...'}, "
                f"new_sig={'<empty>' if not voice_signature else voice_signature[:16]+'...'}, "
                f"match={cached_voice_signature == voice_signature}, "
                f"required_output={required_output}, exists={os.path.exists(required_output) if required_output else False}"
            )
            if not force_refresh and cached_voice_signature == voice_signature and required_output and os.path.exists(required_output):
                self.last_voice_vi_path = cached_voice_track if cached_voice_track and os.path.exists(cached_voice_track) else self.last_voice_vi_path
                self.last_mixed_vi_path = cached_mixed_track if cached_mixed_track and os.path.exists(cached_mixed_track) else ""
                if self.last_voice_vi_path:
                    self.processed_artifacts["voice_vi"] = self.last_voice_vi_path
                    self.update_project_artifact("voice_vi", self.last_voice_vi_path)
                    self.update_project_step("generate_tts", "done")
                if bg_path:
                    self.update_project_step("mix_audio", "skipped")
                self.log("[Voiceover] Reusing existing generated audio. Generate did not call TTS again.")
                self._activate_dubbed_audio_without_original_voice()
                self.progress_bar.setValue(100)
                self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
                self.refresh_ui_state()
                self._pipeline_advance("voiceover")
                return

        combo_text = self.free_voice_combo.currentText() if hasattr(self, "free_voice_combo") else ""
        combo_data = self.free_voice_combo.currentData() if hasattr(self, "free_voice_combo") else ""
        combo_id = self.free_voice_combo.currentData(self.VOICE_ENTRY_ID_ROLE) if hasattr(self, "free_voice_combo") else ""
        self.log(f"[Voiceover] Selected voice: text='{combo_text}', data='{combo_data}', id='{combo_id}'")
        
        self.log(
            "[Voiceover] Starting with "
            f"audio_mode={audio_handling_mode}, "
            f"voice={voice_name}, "
            f"speed={voice_speed:.2f}, "
            f"segments={len(segments)}, "
            f"translated_chars={len(translated_srt)}, "
            f"background={bg_path or '<none>'}"
        )
        if state:
            self.log(
                "[Voiceover] State snapshot: "
                f"project={state.project_root}, "
                f"steps={dict(state.steps)}, "
                f"artifacts={dict(state.artifacts)}"
            )

        try:
            self.media_player.pause()
            self.timeline.set_playing(False)
        except Exception:
            pass

        if hasattr(self, "voiceover_btn"):
            self.voiceover_btn.setEnabled(False)
            self.voiceover_btn.setText("Generating... (TTS)")
        self.progress_bar.setValue(85)
        self.update_project_step("generate_tts", "running")
        if bg_path:
            self.update_project_step("mix_audio", "running")
        self.refresh_ui_state()
        try:
            QApplication.processEvents()
        except Exception:
            pass
        self._pending_voice_signature = voice_signature

        project_state_path = self.project_service.project_file(self.current_project_state.project_root) if self.current_project_state else ""
        self.voice_thread = VoiceOverWorker(
            self.workspace_root,
            segments,
            out_dir,
            bg_path,
            audio_handling_mode,
            voice_name,
            voice_speed,
            timing_sync_mode,
            original_volume,
            dub_volume,
            project_state_path,
            self.get_project_temp_dir("tts"),
            self.is_ai_dubbing_rewrite_enabled() and self.get_output_mode_key() in ("voice", "both"),
            self.get_ai_dubbing_style_instruction(),
            self.get_source_language_code(),
        )
        self.voice_thread.progress.connect(self.log)
        self.voice_thread.finished.connect(self.on_voiceover_finished)
        self.voice_thread.start()


    def _apply_generated_tts_texts(self, voice_segments):
        source_segments = self.current_translated_segments
        if not source_segments or not voice_segments:
            return False

        updated = False
        grouped_updates = {}
        positional_updates = []
        for seg in list(voice_segments or []):
            tts_text = ' '.join(str((seg or {}).get("tts_text") or (seg or {}).get("text") or "").split()).strip()
            if not tts_text:
                continue
            subtitle_vi = ' '.join(str((seg or {}).get("subtitle_vi") or (seg or {}).get("text") or "").split()).strip()
            dubbing_vi = ' '.join(str((seg or {}).get("dubbing_vi") or tts_text).split()).strip()
            action_taken = str((seg or {}).get("action_taken") or "").strip().lower()
            ratio = float((seg or {}).get("ratio") or 0.0)
            group_id = str((seg or {}).get("tts_group_id") or "").strip()
            try:
                new_start = float((seg or {}).get("start", 0.0))
                new_end = float((seg or {}).get("end", 0.0))
            except (TypeError, ValueError):
                new_start = new_end = None
            try:
                new_original_end = float((seg or {}).get("_original_end")) if (seg or {}).get("_original_end") is not None else None
            except (TypeError, ValueError):
                new_original_end = None
            try:
                new_audio_end = float((seg or {}).get("_audio_end")) if (seg or {}).get("_audio_end") is not None else None
            except (TypeError, ValueError):
                new_audio_end = None
            payload = {
                "tts_text": tts_text,
                "subtitle_vi": subtitle_vi,
                "dubbing_vi": dubbing_vi,
                "action_taken": action_taken,
                "ratio": ratio,
                "attempt_count": int((seg or {}).get("attempt_count") or 1),
                "start": new_start,
                "end": new_end,
                "_original_end": new_original_end,
                "_audio_end": new_audio_end,
            }
            if group_id:
                grouped_updates[group_id] = payload
            else:
                positional_updates.append(payload)

        positional_index = 0
        for seg in source_segments:
            group_id = str((seg or {}).get("tts_group_id") or "").strip()
            if group_id and group_id in grouped_updates:
                next_payload = grouped_updates[group_id]
            elif positional_index < len(positional_updates):
                next_payload = positional_updates[positional_index]
                positional_index += 1
            else:
                continue

            next_tts_text = next_payload["tts_text"]
            current_tts_text = ' '.join(str(seg.get("tts_text") or "").split()).strip()
            if current_tts_text != next_tts_text:
                seg["tts_text"] = next_tts_text
                updated = True
            seg["subtitle_vi"] = next_payload["subtitle_vi"]
            seg["dubbing_vi"] = next_payload["dubbing_vi"]
            seg["action_taken"] = next_payload["action_taken"]
            seg["ratio"] = next_payload["ratio"]
            seg["attempt_count"] = next_payload["attempt_count"]
            # Sync start/end from the voice workflow so the SRT reflects the
            # actual TTS audio duration (see _extend_segment_ends_to_audio).
            new_start = next_payload.get("start")
            new_end = next_payload.get("end")
            if new_start is not None and new_end is not None and new_end > new_start:
                try:
                    old_start = float(seg.get("start", 0.0))
                    old_end = float(seg.get("end", 0.0))
                except (TypeError, ValueError):
                    old_start = old_end = None
                if old_start is not None and old_end is not None:
                    if abs(new_start - old_start) > 0.01 or abs(new_end - old_end) > 0.01:
                        seg["start"] = new_start
                        seg["end"] = new_end
                        updated = True
            new_original_end = next_payload.get("_original_end")
            if new_original_end is not None:
                seg["_original_end"] = new_original_end
            new_audio_end = next_payload.get("_audio_end")
            if new_audio_end is not None:
                seg["_audio_end"] = new_audio_end
            else:
                seg.pop("_audio_end", None)
        return updated


    def _activate_dubbed_audio_without_original_voice(self) -> None:
        """Prevent the source dialogue and generated dub from playing together."""
        mode = str(self.get_output_mode_key() or "subtitle").strip().lower()
        if mode not in {"voice", "both"}:
            return
        self.on_track_mute_toggled("A1 Audio", True)
        self.on_track_mute_toggled("TS1", False)
        self._sync_timeline_mute_to_gui()
        self.log(
            "[Voiceover] Dub preview selected: original A1 dialogue muted to prevent doubled voices."
        )


    def skip_tts_stage(self):
        """Explicitly finish the optional TTS phase after translation."""
        has_translation = bool(self.current_translated_segments or self.translated_text.toPlainText().strip())
        if not has_translation:
            QMessageBox.information(self, "Skip TTS", "Complete Translate before skipping Generate Voice / TTS.")
            return
        state = self.ensure_current_project()
        if state is not None:
            state.set_setting("tts_skipped", True)
            state.set_step_status("generate_tts", "skipped")
            state.set_step_status("mix_audio", "skipped")
            self.project_service.save_project(state)
        self._voiceover_force_refresh = True
        self.log("[Pipeline] Generate Voice / TTS skipped. The translated subtitle video is ready to export.")
        self.refresh_ui_state()


