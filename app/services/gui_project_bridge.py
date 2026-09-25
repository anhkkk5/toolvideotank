from __future__ import annotations

import os

from services.segment_service import SegmentService


class GUIProjectBridge:
    def __init__(self, project_service):
        self.project_service = project_service
        self.segment_service = SegmentService()

    def ensure_project(
        self,
        *,
        video_path: str,
        mode: str,
        translator_ai: bool,
        input_language: str,
        target_language: str = "vi",
    ):
        if not video_path or not os.path.exists(video_path):
            return None
        return self.project_service.ensure_project(
            video_path,
            mode=mode,
            translator_ai=translator_ai,
            input_language=input_language,
            target_language=target_language,
        )

    def update_step(self, state, step_name: str, status: str):
        if not state:
            return None
        return self.project_service.update_step(state, step_name, status)

    def update_artifact(self, state, artifact_name: str, path: str):
        if not state or not path:
            return None
        return self.project_service.update_artifact(state, artifact_name, path)

    def dict_segments_to_models(self, segments, *, translated: bool = False):
        return self.segment_service.segment_dicts_to_models(segments, translated=translated)

    def persist_transcription(self, state, raw_segments, srt_path: str = ""):
        if not state:
            return []
        segment_models = self.segment_service.transcript_dicts_to_models(raw_segments)
        self.project_service.save_json_artifact(
            state,
            "transcript_raw",
            os.path.join("analysis", "transcript_raw.json"),
            raw_segments,
        )
        self.project_service.save_segment_artifact(
            state,
            "transcript_segments",
            os.path.join("analysis", "transcript_segments.json"),
            segment_models,
        )
        if srt_path:
            self.update_artifact(state, "subtitle_original_srt", srt_path)
        self.update_step(state, "transcribe", "done")
        return segment_models

    def persist_translation(self, state, base_models, translated_segments, srt_path: str = ""):
        if not state:
            return []
        models = self.segment_service.apply_translations(base_models, translated_segments)

        self.project_service.save_segment_artifact(
            state,
            "translation_final",
            os.path.join("translation", "translation_final.json"),
            models,
        )
        if any(model.refined_translation for model in models):
            self.project_service.save_segment_artifact(
                state,
                "translation_refined",
                os.path.join("translation", "translation_refined.json"),
                models,
            )
            self.update_step(state, "refine_translation", "done")
        else:
            self.project_service.save_segment_artifact(
                state,
                "translation_raw",
                os.path.join("translation", "translation_raw.json"),
                models,
            )
            self.update_step(state, "refine_translation", "skipped")
        if srt_path:
            self.update_artifact(state, "subtitle_translated_srt", srt_path)
        self.update_step(state, "translate_raw", "done")
        return models

    def load_context(self, state):
        context = {
            "artifacts": {},
            "last_original_srt_path": "",
            "last_translated_srt_path": "",
            "last_extracted_audio": "",
            "last_vocals_path": "",
            "last_music_path": "",
            "last_voice_vi_path": "",
            "last_mixed_vi_path": "",
            "current_segments": [],
            "current_translated_segments": [],
            "current_segment_models": [],
            "current_translated_segment_models": [],
        }
        if not state:
            return context

        context["artifacts"] = dict(state.artifacts)
        context["last_original_srt_path"] = state.artifacts.get("subtitle_original_srt") or state.artifacts.get("srt_original") or ""
        context["last_translated_srt_path"] = state.artifacts.get("subtitle_translated_srt") or state.artifacts.get("srt_translated") or ""
        context["last_extracted_audio"] = state.artifacts.get("extracted_audio") or state.artifacts.get("audio_extracted") or ""
        context["last_vocals_path"] = state.artifacts.get("vocals", "")
        context["last_music_path"] = state.artifacts.get("music", "")
        context["last_voice_vi_path"] = state.artifacts.get("voice_vi", "")
        context["last_mixed_vi_path"] = state.artifacts.get("mixed_vi", "")

        # Check if speaker diarization turns are available
        diarization_path = state.artifacts.get("speaker_diarization", "")
        speaker_turns = []
        if diarization_path and os.path.exists(diarization_path):
            speaker_turns = self.project_service.load_json_artifact(state, "speaker_diarization", default=[]) or []

        transcript_json = state.artifacts.get("transcript_segments")
        if transcript_json and os.path.exists(transcript_json):
            transcript_models = self.project_service.load_segment_artifact(state, "transcript_segments")
            repaired_transcript = False
            if speaker_turns:
                # Rehydrate the entire Character Resolver assignment, not just
                # speaker. This also repairs artifacts written by older builds
                # that contain CHAR_x but lost confidence/gender/source.
                from services.subtitle_speaker_aligner import align_subtitles_to_speakers
                transcript_rows = [segment.to_original_subtitle_dict() for segment in transcript_models]
                aligned_rows = align_subtitles_to_speakers(transcript_rows, speaker_turns)
                for model, aligned in zip(transcript_models, aligned_rows):
                    for key in (
                        "speaker", "audio_speaker", "speaker_confidence",
                        "character_id", "character_gender",
                        "character_confidence", "character_source",
                    ):
                        if key in aligned and model.metadata.get(key) != aligned.get(key):
                            model.metadata[key] = aligned.get(key)
                            repaired_transcript = True
                if repaired_transcript:
                    self.project_service.save_segment_artifact(
                        state,
                        "transcript_segments",
                        os.path.join("analysis", "transcript_segments.json"),
                        transcript_models,
                    )
            context["current_segment_models"] = transcript_models
            context["current_segments"] = [segment.to_original_subtitle_dict() for segment in transcript_models]

        translation_json = state.artifacts.get("translation_final")
        if translation_json and os.path.exists(translation_json):
            translation_models = self.project_service.load_segment_artifact(state, "translation_final")
            repaired_speakers = False
            for index, translation_model in enumerate(translation_models):
                if index < len(context["current_segment_models"]):
                    source_metadata = context["current_segment_models"][index].metadata
                    for key in (
                        "speaker", "audio_speaker", "speaker_confidence",
                        "character_id", "character_gender",
                        "character_confidence", "character_source",
                    ):
                        if key in source_metadata and translation_model.metadata.get(key) != source_metadata.get(key):
                            translation_model.metadata[key] = source_metadata.get(key)
                            repaired_speakers = True
                    continue
                source_speaker = ""
                if not source_speaker and speaker_turns:
                    source_speaker = self._match_speaker_from_turns(
                        translation_model.start, translation_model.end, speaker_turns
                    )
                if source_speaker:
                    translation_model.metadata["speaker"] = source_speaker
                    repaired_speakers = True
            if repaired_speakers:
                self.project_service.save_segment_artifact(
                    state,
                    "translation_final",
                    os.path.join("translation", "translation_final.json"),
                    translation_models,
                )
            context["current_translated_segment_models"] = translation_models
            context["current_translated_segments"] = [segment.to_subtitle_dict() for segment in translation_models]

        return context

    @staticmethod
    def _match_speaker_from_turns(start: float, end: float, turns: list[dict]) -> str:
        best_spk = ""
        best_overlap = 0.0
        for t in turns:
            try:
                ts = float(t.get("start", 0.0))
                te = float(t.get("end", 0.0))
                spk = str(t.get("speaker", "") or "").strip()
                if not spk:
                    continue
                overlap = max(0.0, min(end, te) - max(start, ts))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_spk = spk
            except (TypeError, ValueError):
                continue
        if best_spk:
            return best_spk
        # Fallback: nearest turn
        mid = (start + end) / 2.0
        min_dist = 999.0
        closest_spk = ""
        for t in turns:
            try:
                ts = float(t.get("start", 0.0))
                te = float(t.get("end", 0.0))
                spk = str(t.get("speaker", "") or "").strip()
                if not spk:
                    continue
                dist = min(abs(mid - ts), abs(mid - te))
                if dist < min_dist:
                    min_dist = dist
                    closest_spk = spk
            except (TypeError, ValueError):
                continue
        return closest_spk if min_dist < 2.0 else ""
