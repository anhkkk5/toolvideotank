"""Subtitle Cards Studio - Right column bilingual subtitle manager.

Features:
- Dual-mode Voice Assignment:
  Mode 1 (Manual per-cue): Custom voice dropdown directly in each card (bottom right red-box position).
  Mode 2 (Batch Shape Groups): 4 distinct shape groups (🟢 Circle, 🟦 Square, 🔺 Triangle, 🔶 Diamond)
    with real-time count badge and group-level voice pickers.
- Bilingual Display: Chinese (Original) on top, Vietnamese (Translated) below.
- Studio aesthetic matching user's CapCut-style specifications.
"""

from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


AI_VOICES = [
    # Female voices
    {"id": "vieneu_cogaihoatbat", "name": "Cô gái hoạt bát (VieNeu)", "gender": "female", "icon": "⚡"},
    {"id": "banmai", "name": "Ban Mai (Piper)", "gender": "female", "icon": "👩"},
    {"id": "chieuthanh", "name": "Chiêu Thanh (Piper)", "gender": "female", "icon": "👩"},
    {"id": "ngochuyen", "name": "Ngọc Huyền", "gender": "female", "icon": "👩"},
    {"id": "vi-VN-HoaiMyNeural", "name": "Hoài My (Edge)", "gender": "female", "icon": "👩"},
    # Male voices
    {"id": "vieneu_thanhnientutin", "name": "Thanh niên tự tin (VieNeu)", "gender": "male", "icon": "⚡"},
    {"id": "minhquang", "name": "Minh Quang (Piper)", "gender": "male", "icon": "👨"},
    {"id": "vi-VN-NamMinhNeural", "name": "Nam Minh (Edge)", "gender": "male", "icon": "👨"},
]

SHAPE_GROUPS = {
    "circle": {"name": "Nhân vật 1", "icon": "🟢", "color": "#10b981", "default_voice": "vieneu_cogaihoatbat", "default_label": "Cô gái hoạt bát"},
    "square": {"name": "Nhân vật 2", "icon": "🟦", "color": "#3b82f6", "default_voice": "vieneu_thanhnientutin", "default_label": "Thanh niên tự tin"},
    "triangle": {"name": "Nhân vật 3", "icon": "🔺", "color": "#f59e0b", "default_voice": "minhquang", "default_label": "Minh Quang"},
    "diamond": {"name": "Nhân vật 4", "icon": "🔶", "color": "#ec4899", "default_voice": "chieuthanh", "default_label": "Chiêu Thanh"},
}


def _load_chinese_cues_from_project(gui) -> list[str]:
    """Extract true Chinese text from original.srt to ensure the top box is always Chinese."""
    state = getattr(gui, "current_project_state", None)
    project_dir = getattr(state, "project_dir", "") or getattr(gui, "current_project_dir", "") or ""

    candidates = [
        getattr(gui, "last_original_srt_path", "") or "",
        getattr(gui, "processed_artifacts", {}).get("srt_original", "") or "",
        getattr(state, "artifacts", {}).get("srt_original", "") if state else "",
        os.path.join(project_dir, "subtitle", "original.srt") if project_dir else "",
        os.path.join(project_dir, "subtitle", "subtitle.srt") if project_dir else "",
        os.path.join(project_dir, "original.srt") if project_dir else "",
    ]

    # Also search projects directory for matching project if direct paths not found
    if not any(c and os.path.exists(c) for c in candidates):
        video_text = ""
        if hasattr(gui, "video_path_edit"):
            video_text = gui.video_path_edit.text().strip()
        video_path = getattr(gui, "_current_video_path", "") or video_text
        if video_path:
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            projects_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "projects"))
            if os.path.exists(projects_root):
                for d in os.listdir(projects_root):
                    if base_name and (base_name in d or d in base_name):
                        orig_path = os.path.join(projects_root, d, "subtitle", "original.srt")
                        if os.path.exists(orig_path):
                            candidates.append(orig_path)
                            break

    for path in candidates:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                    content = f.read()
                blocks = re.split(r"\n\s*\n", content.strip())
                cues = []
                for b in blocks:
                    lines = [l.strip() for l in b.splitlines() if l.strip()]
                    if len(lines) >= 3:
                        text = " ".join(lines[2:])
                        cues.append(text)
                if cues:
                    return cues
            except Exception:
                pass
    return []


class SubtitleCard(QFrame):
    """A single subtitle cue card with Shape Group selector and manual AI voice picker."""

    def __init__(self, segment_data: dict, index: int, parent_view: SubtitleListView, orig_chinese: str = ""):
        super().__init__()
        self.parent_view = parent_view
        self.gui = parent_view.gui
        self.segment_index = index
        self.segment_data = dict(segment_data)
        self._is_active = False

        # Read or assign default group from segment data or speaker
        grp = str(self.segment_data.get("voice_group", "") or "").strip()
        spk = str(self.segment_data.get("speaker", "") or "").strip()
        if not grp:
            if spk and hasattr(self.parent_view, "get_group_for_speaker"):
                grp = self.parent_view.get_group_for_speaker(spk)
            else:
                grp = "circle"
        self.current_group = str(grp or "circle")
        self.custom_voice = str(self.segment_data.get("voice_custom", "") or self.segment_data.get("voice", "") or "")

        self.setObjectName("subtitleCard")
        self.setFrameShape(QFrame.StyledPanel)
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ---- Header Row ----
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)

        # Index label
        self.idx_label = QLabel(f"#{index + 1}")
        self.idx_label.setStyleSheet("color: #64748b; font-weight: 700; font-size: 12px;")
        header_row.addWidget(self.idx_label)

        self.shape_btns = {}

        # Timecode badge: [ 0.50 → 1.50 ]
        start_s = float(self.segment_data.get("start", 0.0))
        end_s = float(self.segment_data.get("end", 0.0))
        time_text = f"{start_s:.2f}  →  {end_s:.2f}"
        self.time_label = QLabel(time_text)
        self.time_label.setStyleSheet(
            "background: #11151f; color: #94a3b8; border: 1px solid #232b3c; border-radius: 4px; padding: 2px 7px; font-size: 11px; font-family: monospace;"
        )
        header_row.addWidget(self.time_label)

        # Play button (▶)
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(22, 22)
        self.play_btn.setToolTip("Phát thử câu này trên video")
        self.play_btn.setStyleSheet(
            "QPushButton { background: #161b26; color: #ff9d42; border: 1px solid #2b364c; border-radius: 11px; font-size: 9px; font-weight: bold; } "
            "QPushButton:hover { background: #ff7b1a; color: #ffffff; }"
        )
        self.play_btn.clicked.connect(self._on_play_clicked)
        header_row.addWidget(self.play_btn)

        header_row.addStretch()

        # TTS listen button (🔊 TTS)
        self.tts_audio_btn = QPushButton("🔊 TTS")
        self.tts_audio_btn.setFixedHeight(22)
        self.tts_audio_btn.setToolTip("Nghe thử âm thanh lồng tiếng câu này")
        self.tts_audio_btn.setStyleSheet(
            "QPushButton { background: #14231b; color: #34d399; border: 1px solid #1c4d37; border-radius: 4px; padding: 1px 7px; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #059669; color: #ffffff; }"
        )
        self.tts_audio_btn.clicked.connect(self._on_tts_audio_clicked)
        header_row.addWidget(self.tts_audio_btn)

        layout.addLayout(header_row)

        # ---- TOP: CHINESE TEXT AREA ----
        orig_text = orig_chinese or str(self.segment_data.get("original", "") or self.segment_data.get("source_text", "") or "")
        trans_text = str(self.segment_data.get("translated", "") or self.segment_data.get("text", "") or "")
        if orig_text == trans_text and orig_chinese:
            orig_text = orig_chinese

        self.orig_edit = QTextEdit()
        self.orig_edit.setAcceptRichText(False)
        self.orig_edit.setPlaceholderText("Tiếng Trung (gốc)...")
        self.orig_edit.setPlainText(orig_text)
        self.orig_edit.setFixedHeight(40)
        self.orig_edit.setStyleSheet(
            "QTextEdit { background: #090e15; color: #e2e8f0; border: 1px solid #182637; border-radius: 5px; padding: 3px 6px; font-size: 13px; } "
            "QTextEdit:focus { border-color: #38bdf8; background: #0c141e; }"
        )
        self.orig_edit.textChanged.connect(self._on_orig_edited)
        layout.addWidget(self.orig_edit)

        # ---- BOTTOM: VIETNAMESE TEXT AREA ----
        self.trans_edit = QTextEdit()
        self.trans_edit.setAcceptRichText(False)
        self.trans_edit.setPlaceholderText("Tiếng Việt (bản dịch)...")
        self.trans_edit.setPlainText(trans_text)
        self.trans_edit.setFixedHeight(42)
        self.trans_edit.setStyleSheet(
            "QTextEdit { background: #090e15; color: #ffffff; border: 1px solid #182637; border-radius: 5px; padding: 3px 6px; font-size: 13px; font-weight: 500; } "
            "QTextEdit:focus { border-color: #00d2ff; background: #0c141e; }"
        )
        self.trans_edit.textChanged.connect(self._on_trans_edited)
        layout.addWidget(self.trans_edit)

        # ---- Bottom Action & Voice Selection Row ----
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)

        # Action Buttons
        self.translate_btn = QPushButton("🌐 Dịch")
        self.translate_btn.setFixedHeight(22)
        self.translate_btn.setStyleSheet(
            "QPushButton { background: #101d2c; color: #38bdf8; border: 1px solid #1a3d5e; border-radius: 4px; padding: 1px 7px; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background: #0284c7; color: #ffffff; border-color: #38bdf8; }"
        )
        self.translate_btn.clicked.connect(self._on_retranslate_clicked)
        action_row.addWidget(self.translate_btn)

        self.polish_btn = QPushButton("✂ Tinh chỉnh")
        self.polish_btn.setFixedHeight(22)
        self.polish_btn.setStyleSheet(
            "QPushButton { background: #101d2c; color: #22d3ee; border: 1px solid #184a5a; border-radius: 4px; padding: 1px 7px; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background: #0891b2; color: #ffffff; border-color: #22d3ee; }"
        )
        self.polish_btn.clicked.connect(self._on_polish_clicked)
        action_row.addWidget(self.polish_btn)

        self.gen_tts_btn = QPushButton("✨ Tạo TTS")
        self.gen_tts_btn.setFixedHeight(22)
        self.gen_tts_btn.setStyleSheet(
            "QPushButton { background: #261e12; color: #fbbf24; border: 1px solid #573c16; border-radius: 4px; padding: 1px 7px; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background: #d97706; color: #ffffff; border-color: #fbbf24; }"
        )
        self.gen_tts_btn.clicked.connect(self._on_gen_tts_clicked)
        action_row.addWidget(self.gen_tts_btn)

        self.del_btn = QPushButton("🗑 Xóa")
        self.del_btn.setFixedHeight(22)
        self.del_btn.setStyleSheet(
            "QPushButton { background: #241316; color: #f87171; border: 1px solid #541e24; border-radius: 4px; padding: 1px 7px; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background: #dc2626; color: #ffffff; border-color: #f87171; }"
        )
        self.del_btn.clicked.connect(self._on_delete_clicked)
        action_row.addWidget(self.del_btn)

        action_row.addStretch()

        # Hidden backward-compatibility widgets
        self.character_combo = QComboBox()
        self.character_combo.hide()
        self.listen_voice_btn = QPushButton()
        self.listen_voice_btn.hide()
        self.voice_picker_btn = QPushButton()
        self.voice_picker_btn.hide()

        layout.addLayout(action_row)

    def _character_choices(self) -> list[str]:
        choices: set[str] = set()
        state = getattr(self.gui, "current_project_state", None)
        if state is not None:
            try:
                registry = self.gui.project_service.load_json_artifact(
                    state, "character_registry", default=[]
                ) or []
                choices.update(
                    str(item.get("character_id", "") or "") for item in registry
                    if str(item.get("character_id", "") or "").startswith("CHAR_")
                )
            except Exception:
                pass
        for segment_list in (
            getattr(self.gui, "current_translated_segments", None),
            getattr(self.gui, "current_segments", None),
        ):
            for segment in segment_list or []:
                value = str(segment.get("character_id", segment.get("speaker", "")) or "")
                if value.startswith("CHAR_"):
                    choices.add(value)
        return sorted(choices)

    def _on_character_changed(self, _index: int) -> None:
        character_id = str(self.character_combo.currentData() or "").strip()
        if not character_id:
            return
        self.current_group = self.parent_view.get_group_for_speaker(character_id)
        self.custom_voice = ""
        self.segment_data.update({
            "speaker": character_id,
            "character_id": character_id,
            "character_confidence": 1.0,
            "character_source": "manual_correction",
            "voice_group": self.current_group,
            "voice_custom": "",
        })
        self._update_shape_buttons()
        self._apply_style()
        self._update_voice_picker_btn_text()
        self.parent_view.update_group_counts()
        for segment_list in (
            getattr(self.gui, "current_translated_segments", None),
            getattr(self.gui, "current_segments", None),
        ):
            if segment_list and 0 <= self.segment_index < len(segment_list):
                segment_list[self.segment_index]["voice_group"] = self.current_group
                segment_list[self.segment_index]["voice_custom"] = ""
                segment_list[self.segment_index].pop("voice_name", None)
        self.confidence_label.setText("Tay 100%")
        self.confidence_label.setStyleSheet(
            "color: #34d399; border: 1px solid #34d399; border-radius: 4px; padding: 1px 5px; font-size: 10px;"
        )
        if hasattr(self.gui, "on_segment_speaker_changed"):
            self.gui.on_segment_speaker_changed(self.segment_index, character_id)
        # Recalculate the review badge/filter after the signal handler returns;
        # rebuilding synchronously would delete the combo while it is emitting.
        QTimer.singleShot(0, self.parent_view.refresh_segments)

    def _set_group(self, group_key: str):
        self.current_group = group_key
        self.custom_voice = ""  # Reset custom voice để nhận giọng của nhóm mới!
        self.segment_data["voice_group"] = group_key
        self.segment_data["voice_custom"] = ""
        self._update_shape_buttons()
        self._apply_style()
        self._update_voice_picker_btn_text()
        self.parent_view.update_group_counts()

        # Save to GUI segments
        for seg_list in (getattr(self.gui, "current_translated_segments", None), getattr(self.gui, "current_segments", None)):
            if seg_list and 0 <= self.segment_index < len(seg_list):
                seg_list[self.segment_index]["voice_group"] = group_key
                seg_list[self.segment_index]["voice_custom"] = ""
                seg_list[self.segment_index]["voice_name"] = self.get_effective_voice_id()

    def _update_shape_buttons(self):
        for sk, btn in self.shape_btns.items():
            if sk == self.current_group:
                color = SHAPE_GROUPS[sk]["color"]
                btn.setStyleSheet(
                    f"QPushButton {{ background: #172a40; border: 2px solid {color}; border-radius: 4px; font-size: 11px; font-weight: bold; }}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background: #0c141e; border: 1px solid #1a2636; border-radius: 4px; font-size: 10px; opacity: 0.6; } "
                    "QPushButton:hover { background: #152438; border-color: #38bdf8; }"
                )

    def _update_voice_picker_btn_text(self):
        if self.custom_voice:
            # Finding name
            v_name = self.custom_voice
            for v in AI_VOICES:
                if v["id"] == self.custom_voice:
                    v_name = v["name"]
                    break
            self.voice_picker_btn.setText(f"🎙️ {v_name} ⌄")
            self.voice_picker_btn.setStyleSheet(
                "QPushButton { background: #1c2718; color: #a3e635; border: 1px solid #4d7c0f; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 700; } "
                "QPushButton:hover { background: #2b3d22; border-color: #84cc16; }"
            )
        else:
            # Group voice
            grp_voice_id = self.parent_view.get_group_voice_id(self.current_group)
            grp_voice_name = self.parent_view.get_voice_display_name(grp_voice_id)
            shape_icon = SHAPE_GROUPS.get(self.current_group, {}).get("icon", "🟢")
            self.voice_picker_btn.setText(f"{shape_icon} {grp_voice_name} ⌄")
            self.voice_picker_btn.setStyleSheet(
                "QPushButton { background: #0e1724; color: #93c5fd; border: 1px solid #1e334a; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600; } "
                "QPushButton:hover { background: #16283e; color: #ffffff; border-color: #38bdf8; }"
            )

    def _open_voice_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #0d1520; color: #eff6ff; border: 1px solid #1e334a; padding: 4px; } "
            "QMenu::item:selected { background: #0284c7; color: #ffffff; border-radius: 4px; }"
        )

        # Default option: Follow Group
        shape_info = SHAPE_GROUPS.get(self.current_group, {})
        grp_name = shape_info.get("name", "")
        follow_action = menu.addAction(f"🔄 Theo nhóm {shape_info.get('icon', '')} {grp_name} (Mặc định)")

        menu.addSeparator()
        female_menu = menu.addMenu("👩 Giọng Nữ")
        male_menu = menu.addMenu("👨 Giọng Nam")

        action_map = {}
        for v in AI_VOICES:
            target_menu = female_menu if v["gender"] == "female" else male_menu
            act = target_menu.addAction(f"{v['icon']} {v['name']}")
            action_map[act] = v["id"]

        chosen = menu.exec(self.voice_picker_btn.mapToGlobal(self.voice_picker_btn.rect().bottomLeft()))
        if chosen == follow_action:
            self.custom_voice = ""
            self.segment_data["voice_custom"] = ""
            self._update_voice_picker_btn_text()
            self._save_voice_to_gui()
        elif chosen in action_map:
            self.custom_voice = action_map[chosen]
            self.segment_data["voice_custom"] = self.custom_voice
            self._update_voice_picker_btn_text()
            self._save_voice_to_gui()

    def _save_voice_to_gui(self):
        for segment_list in (getattr(self.gui, "current_translated_segments", None), getattr(self.gui, "current_segments", None)):
            if segment_list and 0 <= self.segment_index < len(segment_list):
                segment_list[self.segment_index]["voice_custom"] = self.custom_voice
                segment_list[self.segment_index]["voice_group"] = self.current_group

    def get_effective_voice_id(self) -> str:
        if self.custom_voice:
            return self.custom_voice
        return self.parent_view.get_group_voice_id(self.current_group)

    def _apply_style(self):
        if self._is_active:
            self.setStyleSheet(
                "QFrame#subtitleCard { background-color: #1a1f2c; border: 2px solid #ff7b1a; border-radius: 8px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame#subtitleCard { background-color: #121620; border: 1px solid #232b3b; border-radius: 8px; }"
            )

    def set_active(self, active: bool):
        if self._is_active == active:
            return
        self._is_active = active
        self._apply_style()

    def _find_cached_segment_audio(self) -> str:
        """Find if a valid audio file for this segment already exists in cache/project with the EXACT same voice and text."""
        tts_text = self.trans_edit.toPlainText().strip()
        if not tts_text:
            tts_text = str(self.segment_data.get("translated", "") or self.segment_data.get("text", "")).strip()
        effective_voice = self.get_effective_voice_id()
        if not effective_voice or not tts_text:
            return ""

        try:
            tts_dir = ""
            if hasattr(self.gui, "get_project_temp_dir"):
                tts_dir = self.gui.get_project_temp_dir("tts")
            elif hasattr(self.gui, "get_project_temp_path"):
                tts_dir = self.gui.get_project_temp_path("tts")

            if tts_dir and os.path.exists(tts_dir):
                # 1. Kiểm tra file riêng của đúng giọng này
                voice_specific_file = os.path.join(tts_dir, f"seg_{self.segment_index:04d}_{effective_voice}.wav")
                if os.path.exists(voice_specific_file) and os.path.getsize(voice_specific_file) > 100:
                    return voice_specific_file

                # 2. Kiểm tra manifest (BẮT BUỘC phải đúng chính xác voice_name và text)
                manifest_file = os.path.join(tts_dir, "tts_cache_manifest.json")
                if os.path.exists(manifest_file):
                    import json
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    seg_info = manifest.get("segments", {}).get(str(self.segment_index))
                    if seg_info and isinstance(seg_info, dict):
                        wav = seg_info.get("wav_path", "")
                        v_name = seg_info.get("voice_name", "")
                        cached_txt = str(seg_info.get("text", "")).strip()
                        # Nghiêm ngặt: v_name phải đúng bằng effective_voice mới được dùng!
                        if v_name == effective_voice and wav and os.path.exists(wav) and os.path.getsize(wav) > 100:
                            if not cached_txt or cached_txt == tts_text:
                                return wav
        except Exception:
            pass
        return ""

    def _on_listen_voice_clicked(self):
        self.parent_view.select_card(self.segment_index, seek=False)
        tts_text = self.trans_edit.toPlainText().strip()
        if not tts_text:
            tts_text = str(self.segment_data.get("translated", "") or self.segment_data.get("text", "")).strip()
        if not tts_text:
            return

        effective_voice = self.get_effective_voice_id()

        # 1. Phát ngay nếu file audio đã có sẵn trong cache ĐÚNG VỚI GIỌNG NÀY
        cached_wav = self._find_cached_segment_audio()
        if cached_wav and hasattr(self.gui, "play_audio_preview_file"):
            try:
                self.gui.play_audio_preview_file(cached_wav)
                return
            except Exception:
                pass

        # 2. Sinh âm thanh ngầm theo đúng nhân vật lồng tiếng và phát khi xong
        if hasattr(self.gui, "run_tts_for_segment"):
            self.listen_voice_btn.setText("⏳")
            self.listen_voice_btn.setEnabled(False)
            if hasattr(self, "tts_audio_btn"):
                self.tts_audio_btn.setText("⏳")
                self.tts_audio_btn.setEnabled(False)

            def on_done(success: bool, audio_path: str):
                self.listen_voice_btn.setText("▶ Nghe")
                self.listen_voice_btn.setEnabled(True)
                if hasattr(self, "tts_audio_btn"):
                    self.tts_audio_btn.setText("🔊 TTS")
                    self.tts_audio_btn.setEnabled(True)

            self.gui.run_tts_for_segment(
                self.segment_index,
                voice_name=effective_voice,
                text=tts_text,
                play_immediately=True,
                callback=on_done,
            )
        elif hasattr(self.gui, "preview_segment_audio"):
            self.gui.preview_segment_audio(self.segment_index)

    def _on_play_clicked(self):
        self.parent_view.select_card(self.segment_index, seek=True)

    def _on_tts_audio_clicked(self):
        self.parent_view.select_card(self.segment_index, seek=True)
        self._on_listen_voice_clicked()

    def _on_retranslate_clicked(self):
        self.parent_view.select_card(self.segment_index, seek=False)
        if hasattr(self.gui, "run_rewrite_translation"):
            try:
                self.gui.run_rewrite_translation()
            except Exception:
                pass

    def _on_polish_clicked(self):
        self.parent_view.select_card(self.segment_index, seek=False)
        if hasattr(self.gui, "run_rewrite_translation"):
            try:
                self.gui.run_rewrite_translation()
            except Exception:
                pass

    def _on_gen_tts_clicked(self):
        self._on_listen_voice_clicked()

    def _on_delete_clicked(self):
        ans = QMessageBox.question(
            self.gui,
            "Xóa câu phụ đề",
            f"Bạn có chắc muốn xóa câu #{self.segment_index + 1} này không?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            if hasattr(self.gui, "delete_selected_timeline_segment"):
                self.parent_view.select_card(self.segment_index, seek=False)
                try:
                    self.gui.delete_selected_timeline_segment()
                    self.parent_view.refresh_segments()
                except Exception:
                    pass

    def _on_orig_edited(self):
        new_text = self.orig_edit.toPlainText().strip()
        self.segment_data["original"] = new_text
        if hasattr(self.gui, "current_segments") and self.gui.current_segments:
            if self.segment_index < len(self.gui.current_segments):
                self.gui.current_segments[self.segment_index]["text"] = new_text

    def _on_trans_edited(self):
        new_text = self.trans_edit.toPlainText().strip()
        self.segment_data["translated"] = new_text
        if hasattr(self.gui, "on_segment_translation_edited"):
            try:
                self.gui.on_segment_translation_edited(self.segment_index, self.trans_edit)
            except Exception:
                pass

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.parent_view.select_card(self.segment_index, seek=True)


class SubtitleListView(QWidget):
    """Right column studio manager with Batch Shape Groups & Manual AI Voice selection."""

    def __init__(self, gui, parent=None):
        super().__init__(parent)
        self.gui = gui
        self.cards: list[SubtitleCard] = []
        self._selected_index = -1
        self._filter_untranslated_only = False
        self._filter_review_only = False
        self._search_query = ""

        # Default group voices
        self.group_voices = {
            "circle": "vieneu_cogaihoatbat",
            "square": "vieneu_thanhnientutin",
            "triangle": "minhquang",
            "diamond": "chieuthanh",
        }

        self.setObjectName("subtitleListView")
        self.setStyleSheet("QWidget#subtitleListView { background-color: #141519; border: none; border-radius: 4px; }")
        self.setMinimumWidth(260)
        self.setMaximumWidth(600)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        # ---- Top Header ----
        top_header = QHBoxLayout()
        top_header.setContentsMargins(2, 2, 2, 2)
        top_header.setSpacing(8)

        title_icon = QLabel("💬")
        title_icon.setStyleSheet("font-size: 14px; color: #ff9d42;")
        top_header.addWidget(title_icon)

        title_lbl = QLabel("Phụ đề")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: 800; color: #ffffff;")
        top_header.addWidget(title_lbl)

        self.count_badge = QLabel("0/0 câu")
        self.count_badge.setStyleSheet(
            "background: #181d28; color: #ff9d42; border: 1px solid #2d384e; border-radius: 10px; padding: 2px 8px; font-size: 10px; font-weight: 700;"
        )
        top_header.addWidget(self.count_badge)

        top_header.addStretch()

        # Hidden Phân vai button kept for backward compatibility (top navigation bar already has Phân vai AI)
        self.smart_cast_btn = QPushButton("⚡ Phân vai AI")
        self.smart_cast_btn.hide()
        self.smart_cast_btn.clicked.connect(self._on_smart_cast_clicked)

        # Split long segments button (✂️ Tách câu)
        self.split_long_btn = QPushButton("✂ Tách câu")
        self.split_long_btn.setFixedHeight(26)
        self.split_long_btn.setStyleSheet(
            "QPushButton { background: #161c28; color: #cbd5e1; border: 1px solid #283347; border-radius: 5px; padding: 2px 8px; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background: #222b3d; color: #ffffff; border-color: #ff7b1a; }"
        )
        self.split_long_btn.setToolTip("Tự động tách các câu phụ đề dài theo dấu câu")
        self.split_long_btn.clicked.connect(self._on_split_long_clicked)
        top_header.addWidget(self.split_long_btn)

        # More Actions dropdown button (⋮)
        self.more_actions_btn = QToolButton()
        self.more_actions_btn.setText("⋮")
        self.more_actions_btn.setFixedHeight(26)
        self.more_actions_btn.setFixedWidth(26)
        self.more_actions_btn.setPopupMode(QToolButton.InstantPopup)
        self.more_actions_btn.setStyleSheet(
            "QToolButton { background: #161c28; color: #cbd5e1; border: 1px solid #283347; border-radius: 5px; font-size: 14px; font-weight: bold; } "
            "QToolButton:hover { background: #222b3d; color: #ffffff; border-color: #ff7b1a; } "
            "QToolButton::menu-indicator { image: none; width: 0; }"
        )
        self.more_actions_menu = QMenu(self.more_actions_btn)
        self.more_actions_menu.setStyleSheet(
            "QMenu { background-color: #161a24; border: 1px solid #2d3548; border-radius: 6px; padding: 4px; color: #f1f5f9; font-size: 11px; } "
            "QMenu::item { padding: 6px 16px; border-radius: 4px; } "
            "QMenu::item:selected { background-color: #ff7b1a; color: #ffffff; }"
        )
        act_import = self.more_actions_menu.addAction("⤵ Nhập file SRT...")
        act_import.triggered.connect(self._on_import_clicked)
        act_export_orig = self.more_actions_menu.addAction("↓ Xuất file SRT Gốc")
        act_export_orig.triggered.connect(self._on_export_orig_clicked)
        act_export_trans = self.more_actions_menu.addAction("↓ Xuất file SRT Dịch")
        act_export_trans.triggered.connect(self._on_export_trans_clicked)
        self.more_actions_menu.addSeparator()
        act_clear = self.more_actions_menu.addAction("🗑️ Xóa tất cả phụ đề")
        act_clear.triggered.connect(self._on_clear_all_clicked)
        self.more_actions_btn.setMenu(self.more_actions_menu)
        top_header.addWidget(self.more_actions_btn)

        root.addLayout(top_header)

        # Retain hidden buttons for backwards-compatibility
        self.import_btn = QPushButton()
        self.import_btn.hide()
        self.import_btn.clicked.connect(self._on_import_clicked)
        self.export_orig_btn = QPushButton()
        self.export_orig_btn.hide()
        self.export_orig_btn.clicked.connect(self._on_export_orig_clicked)
        self.export_trans_btn = QPushButton()
        self.export_trans_btn.hide()
        self.export_trans_btn.clicked.connect(self._on_export_trans_clicked)
        self.clear_all_btn = QPushButton()
        self.clear_all_btn.hide()
        self.clear_all_btn.clicked.connect(self._on_clear_all_clicked)

        # ---- Search & Filter Toolbar Row ----
        search_filter_row = QHBoxLayout()
        search_filter_row.setContentsMargins(0, 0, 0, 0)
        search_filter_row.setSpacing(6)

        self.search_edit = QLineEdit()
        self.search_edit.setFixedHeight(28)
        self.search_edit.setPlaceholderText("🔍 Tìm nội dung phụ đề...")
        self.search_edit.setStyleSheet(
            "QLineEdit { background: #11141c; color: #f1f5f9; border: 1px solid #232b3b; border-radius: 6px; padding: 2px 8px; font-size: 11px; } "
            "QLineEdit:focus { border-color: #ff7b1a; background: #161a24; }"
        )
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        search_filter_row.addWidget(self.search_edit, 1)

        # Filter Pills: [Tất cả] [Chưa dịch] [Cần xem]
        self.filter_all_btn = QPushButton("Tất cả")
        self.filter_all_btn.setFixedHeight(28)
        self.filter_all_btn.setStyleSheet(
            "QPushButton { background: #ff7b1a; color: #ffffff; border: none; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 700; }"
        )
        self.filter_all_btn.clicked.connect(self._on_filter_all_clicked)
        search_filter_row.addWidget(self.filter_all_btn)

        self.untrans_toggle_btn = QPushButton("Chưa dịch")
        self.untrans_toggle_btn.setCheckable(True)
        self.untrans_toggle_btn.setFixedHeight(28)
        self.untrans_toggle_btn.setStyleSheet(
            "QPushButton { background: #161b26; color: #94a3b8; border: 1px solid #283246; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600; } "
            "QPushButton:checked { background: #ff7b1a; color: #ffffff; border-color: #ff7b1a; font-weight: 700; }"
        )
        self.untrans_toggle_btn.toggled.connect(self._on_untrans_filter_toggled)
        search_filter_row.addWidget(self.untrans_toggle_btn)

        self.review_toggle_btn = QPushButton("Cần xem")
        self.review_toggle_btn.setCheckable(True)
        self.review_toggle_btn.setFixedHeight(28)
        self.review_toggle_btn.setToolTip("Chỉ hiện câu chưa xác định hoặc có độ tin cậy dưới 80%")
        self.review_toggle_btn.setStyleSheet(
            "QPushButton { background: #161b26; color: #fbbf24; border: 1px solid #3d2f16; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600; } "
            "QPushButton:checked { background: #d97706; color: #ffffff; border-color: #fbbf24; font-weight: 700; }"
        )
        self.review_toggle_btn.toggled.connect(self._on_review_filter_toggled)
        search_filter_row.addWidget(self.review_toggle_btn)

        root.addLayout(search_filter_row)

        # Hidden group_bar kept for backward-compatibility with other modules
        self.group_bar = QFrame()
        self.group_bar.hide()
        self.group_count_labels = {}
        self.group_combos = {}

        # ---- Cards Scroll Area ----
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("subtitleScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(
            "QScrollArea#subtitleScrollArea { background-color: #0b0f17; border: none; } "
            "QScrollArea#subtitleScrollArea > QWidget > QWidget { background-color: #0b0f17; } "
            "QScrollBar:vertical { background: #0b0f17; width: 6px; border-radius: 3px; } "
            "QScrollBar::handle:vertical { background: #232c3d; min-height: 24px; border-radius: 3px; } "
            "QScrollBar::handle:vertical:hover { background: #ff7b1a; }"
        )
        if self.scroll_area.viewport():
            self.scroll_area.viewport().setStyleSheet("background-color: #0b0f17; border: none;")

        self.cards_container = QWidget()
        self.cards_container.setObjectName("cardsContainer")
        self.cards_container.setStyleSheet("QWidget#cardsContainer { background-color: #0b0f17; }")
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 2, 0, 2)
        self.cards_layout.setSpacing(6)

        # Empty state placeholder
        self.empty_state_frame = QFrame()
        self.empty_state_frame.setObjectName("emptyStateFrame")
        self.empty_state_frame.setStyleSheet(
            "QFrame#emptyStateFrame { background: #10141d; border: 1px dashed #273142; border-radius: 8px; padding: 24px 16px; margin: 20px 8px; }"
        )
        empty_layout = QVBoxLayout(self.empty_state_frame)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_icon = QLabel("🎬")
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_icon.setStyleSheet("font-size: 32px; background: transparent;")
        empty_title = QLabel("Chưa có phụ đề trong dự án")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #cbd5e1; background: transparent; margin-top: 6px;")
        empty_desc = QLabel("Bấm '⚡ TẠO VIDEO AI' ở trên hoặc chọn 'Chép lời'\nđể nhận diện và biên dịch phụ đề tự động.")
        empty_desc.setAlignment(Qt.AlignCenter)
        empty_desc.setStyleSheet("font-size: 11px; color: #64748b; background: transparent; margin-top: 4px;")
        empty_layout.addWidget(empty_icon)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_desc)
        self.cards_layout.addWidget(self.empty_state_frame)

        self.cards_layout.addStretch()

        self.scroll_area.setWidget(self.cards_container)
        root.addWidget(self.scroll_area, 1)

        # ---- Bottom Bar ----
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(2, 4, 2, 2)
        bottom_bar.setSpacing(8)

        # Original -> Timeline button
        self.orig_to_timeline_btn = QPushButton("cc Gốc → Timeline")
        self.orig_to_timeline_btn.setFixedHeight(30)
        self.orig_to_timeline_btn.setStyleSheet(
            "QPushButton { background: #111d2c; color: #93c5fd; border: 1px solid #1e3550; border-radius: 6px; padding: 3px 10px; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #1a2f48; color: #ffffff; border-color: #60a5fa; }"
        )
        self.orig_to_timeline_btn.clicked.connect(self._on_orig_to_timeline_clicked)
        bottom_bar.addWidget(self.orig_to_timeline_btn)

        # Translated -> Timeline button
        self.trans_to_timeline_btn = QPushButton("🌐A Dịch → Timeline")
        self.trans_to_timeline_btn.setFixedHeight(30)
        self.trans_to_timeline_btn.setStyleSheet(
            "QPushButton { background: #231c15; color: #ff9d42; border: 1px solid #4a3420; border-radius: 6px; padding: 3px 10px; font-size: 11px; font-weight: 700; } "
            "QPushButton:hover { background: #352517; color: #ffffff; border-color: #ff7b1a; }"
        )
        self.trans_to_timeline_btn.clicked.connect(self._on_trans_to_timeline_clicked)
        bottom_bar.addWidget(self.trans_to_timeline_btn, 1)

        # Sparkle Magic Action Button
        self.magic_btn = QPushButton("✨")
        self.magic_btn.setFixedSize(36, 36)
        self.magic_btn.setToolTip("Tự động dịch hoặc tạo giọng đọc toàn bộ theo phân vai nhóm")
        self.magic_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff9d42, stop:1 #e04800); color: #ffffff; border: none; border-radius: 18px; font-size: 16px; font-weight: bold; } "
            "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffb169, stop:1 #f0540a); }"
        )
        self.magic_btn.clicked.connect(self._on_magic_clicked)
        bottom_bar.addWidget(self.magic_btn)

        root.addLayout(bottom_bar)

    def _on_group_voice_changed(self, group_key: str, combo: QComboBox):
        v_id = str(combo.currentData() or "")
        self.group_voices[group_key] = v_id
        # Update all cards in this group that use group voice
        for card in self.cards:
            if card.current_group == group_key and not card.custom_voice:
                card._update_voice_picker_btn_text()

    def get_group_voice_id(self, group_key: str) -> str:
        return self.group_voices.get(group_key, SHAPE_GROUPS.get(group_key, {}).get("default_voice", "vieneu_cogaihoatbat"))

    def get_voice_display_name(self, voice_id: str) -> str:
        for v in AI_VOICES:
            if v["id"] == voice_id:
                return v["name"].split("(")[0].strip()
        return voice_id

    def _on_preview_group_voice(self, group_key: str):
        voice_id = self.group_voices.get(group_key, "")
        if not voice_id and group_key in self.group_combos:
            voice_id = str(self.group_combos[group_key].currentData() or "")
        if not voice_id:
            return

        # 1. Check catalog for preview audio sample
        if hasattr(self.gui, "voice_catalog_map"):
            entry = getattr(self.gui, "voice_catalog_map", {}).get(voice_id, {})
            preview_rel = entry.get("preview_audio_path", "")
            if preview_rel and hasattr(self.gui, "workspace_root"):
                preview_path = os.path.join(self.gui.workspace_root, preview_rel)
                if os.path.isfile(preview_path) and hasattr(self.gui, "play_audio_preview_file"):
                    self.gui.play_audio_preview_file(preview_path)
                    return

        # 2. Check if voice_name_combo has it to use gui.preview_voice()
        if hasattr(self.gui, "voice_name_combo"):
            idx = self.gui.voice_name_combo.findData(voice_id)
            if idx >= 0:
                self.gui.voice_name_combo.setCurrentIndex(idx)
                if hasattr(self.gui, "preview_voice"):
                    self.gui.preview_voice()
                    return

    def _on_filter_all_clicked(self):
        self.untrans_toggle_btn.setChecked(False)
        self.review_toggle_btn.setChecked(False)
        self._filter_untranslated_only = False
        self._filter_review_only = False
        self.filter_all_btn.setStyleSheet(
            "QPushButton { background: #ff7b1a; color: #ffffff; border: none; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 700; }"
        )
        self.refresh_segments()

    def update_group_counts(self):
        counts = {"circle": 0, "square": 0, "triangle": 0, "diamond": 0}
        for card in self.cards:
            gk = card.current_group
            if gk in counts:
                counts[gk] += 1

        for gk, lbl in self.group_count_labels.items():
            lbl.setText(f"{counts[gk]} câu")

    def refresh_segments(self):
        """Re-render cards based on current project subtitle segments."""
        if not hasattr(self.gui, "_segment_editor_display_rows"):
            return

        rows = self.gui._segment_editor_display_rows() or []
        total_count = len(rows)

        chinese_cues = _load_chinese_cues_from_project(self.gui)

        for c in list(self.cards):
            self.cards_layout.removeWidget(c)
            c.deleteLater()
        self.cards.clear()

        visible_count = 0
        review_count = 0
        search_q = self._search_query.lower().strip()

        for idx, row in enumerate(rows):
            orig_chinese = chinese_cues[idx] if idx < len(chinese_cues) else ""
            orig_text = orig_chinese or str(row.get("original", "") or "")
            trans_text = str(row.get("translated", "") or "")

            character_id = str(row.get("character_id", row.get("speaker", "UNKNOWN")) or "UNKNOWN")
            confidence = float(row.get("character_confidence", row.get("speaker_confidence", 0.0)) or 0.0)
            source = str(row.get("character_source", "") or "")
            needs_review = (
                not character_id.startswith("CHAR_")
                or confidence < 0.80
            ) and source != "manual_correction"
            if needs_review:
                review_count += 1

            if self._filter_untranslated_only and trans_text and trans_text != orig_text:
                continue

            if self._filter_review_only and not needs_review:
                continue

            if search_q and search_q not in orig_text.lower() and search_q not in trans_text.lower():
                continue

            card = SubtitleCard(row, idx, self, orig_chinese=orig_chinese)
            self.cards.append(card)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            visible_count += 1

        self.count_badge.setText(f"{visible_count}/{total_count} câu")
        self.review_toggle_btn.setText(f"Cần xem ({review_count})")
        self.update_group_counts()

        if hasattr(self, "empty_state_frame"):
            self.empty_state_frame.setVisible(visible_count == 0)

        if 0 <= self._selected_index < len(self.cards):
            self.cards[self._selected_index].set_active(True)

    def select_card(self, index: int, seek: bool = True):
        """Highlight card and optionally seek player and timeline."""
        self._selected_index = index
        target_card = None

        for card in self.cards:
            is_target = (card.segment_index == index)
            card.set_active(is_target)
            if is_target:
                target_card = card

        if target_card is not None:
            self.scroll_area.ensureWidgetVisible(target_card, 20, 20)

        if hasattr(self.gui, "set_selected_segment_index"):
            try:
                self.gui.set_selected_segment_index(index, sync_ui=False)
            except Exception:
                pass

        if seek and target_card is not None:
            start_s = float(target_card.segment_data.get("start", 0.0))
            if hasattr(self.gui, "seek_to_time"):
                try:
                    self.gui.seek_to_time(start_s)
                except Exception:
                    pass
            elif hasattr(self.gui, "media_player"):
                try:
                    self.gui.media_player.setPosition(int(start_s * 1000))
                except Exception:
                    pass

    def sync_playback_position(self, position_ms: int):
        """Auto-highlight and scroll to the card corresponding to current playback position."""
        pos_s = position_ms / 1000.0
        active_idx = -1
        for card in self.cards:
            start_s = float(card.segment_data.get("start", 0.0))
            end_s = float(card.segment_data.get("end", 0.0))
            if start_s <= pos_s <= end_s:
                active_idx = card.segment_index
                break

        if active_idx >= 0 and active_idx != self._selected_index:
            self.select_card(active_idx, seek=False)

    def _on_search_text_changed(self, text: str):
        self._search_query = text
        self.refresh_segments()

    def _on_untrans_filter_toggled(self, checked: bool):
        self._filter_untranslated_only = checked
        if checked and hasattr(self, "filter_all_btn"):
            self.filter_all_btn.setStyleSheet(
                "QPushButton { background: #161b26; color: #94a3b8; border: 1px solid #283246; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600; }"
            )
        elif not checked and not self._filter_review_only and hasattr(self, "filter_all_btn"):
            self.filter_all_btn.setStyleSheet(
                "QPushButton { background: #ff7b1a; color: #ffffff; border: none; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 700; }"
            )
        self.refresh_segments()

    def _on_review_filter_toggled(self, checked: bool):
        self._filter_review_only = checked
        if checked and hasattr(self, "filter_all_btn"):
            self.filter_all_btn.setStyleSheet(
                "QPushButton { background: #161b26; color: #94a3b8; border: 1px solid #283246; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600; }"
            )
        elif not checked and not self._filter_untranslated_only and hasattr(self, "filter_all_btn"):
            self.filter_all_btn.setStyleSheet(
                "QPushButton { background: #ff7b1a; color: #ffffff; border: none; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 700; }"
            )
        self.refresh_segments()

    def _on_smart_cast_clicked(self):
        if hasattr(self.gui, "auto_assign_voices_by_audio_gender"):
            self.gui.auto_assign_voices_by_audio_gender()
            self.refresh_segments()

    def get_group_for_speaker(self, speaker_id: str) -> str:
        """Map speaker IDs (SPEAKER_00, SPEAKER_01...) consistently to shape groups."""
        if not hasattr(self, "_speaker_to_group_map"):
            self._speaker_to_group_map = {}
        spk = str(speaker_id or "").strip()
        if not spk:
            return "circle"

        # 1. Check if Smart Cast profile exists for this speaker
        state = getattr(self.gui, "current_project_state", None)
        if state:
            project_data = getattr(state, "data", {}) or {}
            smart_cast = project_data.get("smart_cast", {}) or {}
            profiles = smart_cast.get("profiles", {}) or {}
            if spk in profiles:
                prof = profiles[spk]
                gender = prof.get("gender", "female")
                rank = prof.get("role_rank", 1)
                if gender == "female":
                    return "circle" if rank <= 1 else "diamond"
                else:
                    return "square" if rank <= 1 else "triangle"

        # 2. Consistent alternating mapping
        spk_key = spk.upper()
        if spk_key not in self._speaker_to_group_map:
            group_keys = ["circle", "square", "triangle", "diamond"]
            idx = len(self._speaker_to_group_map) % len(group_keys)
            self._speaker_to_group_map[spk_key] = group_keys[idx]
        return self._speaker_to_group_map[spk_key]

    def _on_split_long_clicked(self):
        if hasattr(self.gui, "split_long_segments"):
            try:
                self.gui.split_long_segments()
                self.refresh_segments()
            except Exception:
                pass

    def _on_import_clicked(self):
        menu = QMenu(self)
        import_trans = menu.addAction("Nhập SRT Dịch...")
        import_orig = menu.addAction("Nhập SRT Gốc...")
        action = menu.exec(self.import_btn.mapToGlobal(self.import_btn.rect().bottomLeft()))
        if action == import_trans and hasattr(self.gui, "import_translated_srt"):
            self.gui.import_translated_srt()
            self.refresh_segments()
        elif action == import_orig and hasattr(self.gui, "import_original_srt"):
            self.gui.import_original_srt()
            self.refresh_segments()

    def _on_export_orig_clicked(self):
        if hasattr(self.gui, "download_original_script"):
            self.gui.download_original_script()

    def _on_export_trans_clicked(self):
        if hasattr(self.gui, "download_subtitle"):
            self.gui.download_subtitle()

    def _on_clear_all_clicked(self):
        ans = QMessageBox.question(
            self.gui,
            "Xóa toàn bộ phụ đề",
            "Bạn có chắc muốn xóa toàn bộ phụ đề trong dự án này không?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            if hasattr(self.gui, "current_translated_segments"):
                self.gui.current_translated_segments = []
            if hasattr(self.gui, "current_segments"):
                self.gui.current_segments = []
            if hasattr(self.gui, "persist_current_timeline_project_data"):
                try:
                    self.gui.persist_current_timeline_project_data()
                except Exception:
                    pass
            self.refresh_segments()

    def _on_orig_to_timeline_clicked(self):
        if hasattr(self.gui, "on_output_mode_changed"):
            try:
                self.gui.on_output_mode_changed("Phụ đề Gốc")
            except Exception:
                pass

    def _on_trans_to_timeline_clicked(self):
        if hasattr(self.gui, "on_output_mode_changed"):
            try:
                self.gui.on_output_mode_changed("Phụ đề + Giọng đọc Tiếng Việt")
            except Exception:
                pass

    def _on_magic_clicked(self):
        if hasattr(self.gui, "run_voiceover"):
            self.gui.run_voiceover()
        elif hasattr(self.gui, "run_translation"):
            self.gui.run_translation()
