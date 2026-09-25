"""Phase 2 character resolution using local voice embeddings.

Visual character assignments from Phase 1 provide trusted anchors.  This
service builds one voice prototype per Character ID and resolves turns where
the character is off-screen or Phase 1 returned UNKNOWN.  Ambiguous matches
remain UNKNOWN instead of being force-assigned to a dubbing voice.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from .speaker_diarization_service import SpeakerDiarizationService
from .speaker_embedding_clusterer import SpeakerEmbeddingClusterer
from .speaker_gender import detect_speaker_gender_aggregated
from .post_ocr_character_resolver import PostOCRCharacterResolver


class CharacterVoiceResolver:
    VERSION = 2

    def __init__(self, *, similarity_threshold: float | None = None, margin_threshold: float | None = None):
        self.similarity_threshold = self._env_float(
            "CHARACTER_VOICE_SIMILARITY_THRESHOLD", 0.72
        ) if similarity_threshold is None else float(similarity_threshold)
        self.margin_threshold = self._env_float(
            "CHARACTER_VOICE_MARGIN_THRESHOLD", 0.08
        ) if margin_threshold is None else float(margin_threshold)
        self.anchor_confidence = self._env_float("CHARACTER_VOICE_ANCHOR_CONFIDENCE", 0.75)
        self.clusterer = SpeakerEmbeddingClusterer()

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, str(default)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalized(value: Any) -> np.ndarray | None:
        vector = np.asarray(value, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        return vector / norm if vector.size and norm > 1e-6 else None

    def _turn_embedding(self, extractor, audio: np.ndarray, sample_rate: int, turn: dict) -> np.ndarray | None:
        start = max(0.0, float(turn.get("start", 0.0) or 0.0))
        end = max(start, float(turn.get("end", start) or start))
        begin = max(0, int(start * sample_rate))
        finish = min(len(audio), int(end * sample_rate))
        chunk = np.ascontiguousarray(audio[begin:finish], dtype=np.float32)
        if chunk.size < max(800, int(sample_rate * 0.35)):
            return None
        try:
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate, chunk)
            stream.input_finished()
            if not extractor.is_ready(stream):
                return None
            return self._normalized(extractor.compute(stream))
        except Exception as exc:
            print(f"[Character Voice Resolver] Could not embed a turn: {exc}")
            return None

    def resolve_from_embeddings(
        self,
        result: dict[str, Any],
        embeddings: dict[int, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Pure resolution core, exposed separately for deterministic tests."""
        output = dict(result or {})
        turns = [dict(item) for item in list(output.get("turns") or [])]
        registry_by_id = {
            str(item.get("character_id", "") or ""): dict(item)
            for item in list(output.get("characters") or [])
            if str(item.get("character_id", "") or "").startswith("CHAR_")
        }

        samples: dict[str, list[tuple[np.ndarray, float]]] = {}
        for index, turn in enumerate(turns):
            character_id = str(turn.get("character_id", "UNKNOWN") or "UNKNOWN").upper()
            confidence = float(turn.get("character_confidence", 0.0) or 0.0)
            source = str(turn.get("character_source", "") or "").lower()
            embedding = self._normalized(embeddings.get(index)) if index in embeddings else None
            # Never let a prior Phase 2 prediction train itself on the next
            # run. Only Phase 1 visual anchors (or legacy anchors with no
            # source field) are allowed into a prototype.
            trusted_anchor = source in {"", "visual", "visual_active_speaker", "manual_correction"}
            if character_id.startswith("CHAR_") and trusted_anchor and confidence >= self.anchor_confidence and embedding is not None:
                duration = max(0.1, float(turn.get("end", 0.0) or 0.0) - float(turn.get("start", 0.0) or 0.0))
                samples.setdefault(character_id, []).append((embedding, duration))
                turn.setdefault("character_source", "visual")

        prototypes: dict[str, np.ndarray] = {}
        prototype_meta: list[dict[str, Any]] = []
        for character_id, values in sorted(samples.items()):
            weights = np.asarray([weight for _, weight in values], dtype=np.float32)
            matrix = np.asarray([vector for vector, _ in values], dtype=np.float32)
            centroid = self._normalized(np.average(matrix, axis=0, weights=weights))
            if centroid is None:
                continue
            prototypes[character_id] = centroid
            prototype_meta.append({
                "character_id": character_id,
                "sample_count": len(values),
                "sample_duration": round(float(np.sum(weights)), 3),
                "embedding": centroid.tolist(),
            })

        resolved_count = 0
        for index, turn in enumerate(turns):
            current = str(turn.get("character_id", "UNKNOWN") or "UNKNOWN").upper()
            source = str(turn.get("character_source", "") or "").lower()
            if current.startswith("CHAR_") and source != "voice_embedding":
                continue
            if source == "voice_embedding":
                turn["character_id"] = "UNKNOWN"
                turn["character_gender"] = "unknown"
                turn["character_confidence"] = 0.0
                turn["character_source"] = "unresolved"
            embedding = self._normalized(embeddings.get(index)) if index in embeddings else None
            if embedding is None or not prototypes:
                continue
            scores = sorted(
                ((character_id, float(np.dot(embedding, prototype))) for character_id, prototype in prototypes.items()),
                key=lambda item: item[1], reverse=True,
            )
            best_id, best_score = scores[0]
            second_score = scores[1][1] if len(scores) > 1 else -1.0
            margin = best_score - second_score
            turn["character_voice_similarity"] = round(best_score, 4)
            turn["character_voice_margin"] = round(margin, 4)
            if best_score < self.similarity_threshold or margin < self.margin_threshold:
                continue
            character = registry_by_id.get(best_id, {})
            turn["character_id"] = best_id
            turn["character_gender"] = str(character.get("gender", "unknown") or "unknown")
            turn["character_confidence"] = round(min(0.96, max(0.65, best_score)), 4)
            turn["character_source"] = "voice_embedding"
            resolved_count += 1

        # Rebuild registry turn membership after voice-based assignments.
        for character_id, character in registry_by_id.items():
            character["turn_indices"] = [
                index for index, turn in enumerate(turns)
                if str(turn.get("character_id", "") or "") == character_id
            ]
            meta = next((item for item in prototype_meta if item["character_id"] == character_id), None)
            if meta:
                character["voice_prototype_sample_count"] = meta["sample_count"]
                character["voice_prototype_duration"] = meta["sample_duration"]

        characters = [registry_by_id[key] for key in sorted(registry_by_id)]
        prior_summary = dict(output.get("character_summary") or {})
        summary = {
            **prior_summary,
            "character_count": len(characters),
            "male_count": sum(1 for item in characters if item.get("gender") == "male"),
            "female_count": sum(1 for item in characters if item.get("gender") == "female"),
            "unknown_turn_count": sum(1 for turn in turns if not str(turn.get("character_id", "UNKNOWN") or "UNKNOWN").startswith("CHAR_")),
            "voice_resolved_turn_count": resolved_count,
            "voice_prototype_count": len(prototypes),
            "voice_resolution_version": self.VERSION,
            "version": max(int(prior_summary.get("version", 0) or 0), self.VERSION),
        }
        output["turns"] = turns
        output["characters"] = characters
        output["character_summary"] = summary
        artifact = {
            "version": self.VERSION,
            "model_path": self.clusterer.model_path,
            "similarity_threshold": self.similarity_threshold,
            "margin_threshold": self.margin_threshold,
            "anchor_confidence": self.anchor_confidence,
            "prototypes": prototype_meta,
        }
        return output, artifact

    def resolve(self, audio_path: str, result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        turns = list((result or {}).get("turns") or [])
        if not audio_path or not os.path.isfile(audio_path) or not turns:
            return result, {"version": self.VERSION, "prototypes": [], "skipped": "missing audio or turns"}
        extractor = self.clusterer._get_extractor()
        if extractor is None:
            print("[Character Voice Resolver] Embedding model unavailable; Phase 2 was skipped.")
            return result, {"version": self.VERSION, "prototypes": [], "skipped": "embedding model unavailable"}
        audio, sample_rate = SpeakerDiarizationService._load_audio(audio_path)
        if sample_rate != 16000:
            audio = SpeakerDiarizationService._resample(audio, sample_rate, 16000)
            sample_rate = 16000
        embeddings = {
            index: embedding
            for index, turn in enumerate(turns)
            if (embedding := self._turn_embedding(extractor, audio, sample_rate, turn)) is not None
        }
        resolved, artifact = self.resolve_from_embeddings(result, embeddings)
        resolved["turns"], continuity_count = PostOCRCharacterResolver.apply_temporal_continuity(
            list(resolved.get("turns") or [])
        )

        # A visual resolver can confidently identify CHAR_x while being unsure
        # about its voice category.  Estimate gender once from all speech owned
        # by that character, then propagate it; never decide independently per
        # subtitle.
        characters = [dict(item) for item in list(resolved.get("characters") or [])]
        gender_resolved_count = 0
        for character in characters:
            character_id = str(character.get("character_id", "") or "")
            if not character_id.startswith("CHAR_"):
                continue
            current_gender = str(character.get("gender", "unknown") or "unknown").lower()
            if current_gender in {"male", "female"}:
                continue
            matching_turns = [
                turn for turn in resolved["turns"]
                if str(turn.get("character_id", "") or "") == character_id
            ]
            estimate = detect_speaker_gender_aggregated(audio_path, matching_turns)
            gender = str(estimate.get("gender", "unknown") or "unknown").lower()
            confidence = float(estimate.get("confidence", 0.0) or 0.0)
            if gender not in {"male", "female"} or confidence < 0.60:
                continue
            character["gender"] = gender
            character["gender_source"] = "character_audio_aggregate"
            character["gender_confidence"] = confidence
            for turn in matching_turns:
                turn["character_gender"] = gender
                turn["character_gender_source"] = "character_audio_aggregate"
            gender_resolved_count += 1
        resolved["characters"] = characters
        summary = dict(resolved.get("character_summary") or {})
        summary["male_count"] = sum(1 for item in characters if item.get("gender") == "male")
        summary["female_count"] = sum(1 for item in characters if item.get("gender") == "female")
        summary["continuity_resolved_turn_count"] = continuity_count
        summary["gender_resolved_character_count"] = gender_resolved_count
        resolved["character_summary"] = summary
        artifact["continuity_resolved_turn_count"] = continuity_count
        artifact["gender_resolved_character_count"] = gender_resolved_count
        count = int((resolved.get("character_summary") or {}).get("voice_resolved_turn_count", 0) or 0)
        print(f"[Character Voice Resolver] Phase 2 resolved {count} off-screen/UNKNOWN turn(s).")
        return resolved, artifact
