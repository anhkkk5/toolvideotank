"""Speaker Embedding Clusterer & Merger.

Performs secondary global speaker clustering using Sherpa-ONNX 3D-Speaker
embeddings and pairwise cosine similarity, subject to strict temporal
non-overlap and acoustic gender constraints.
"""

from __future__ import annotations

import os
from typing import Any
import numpy as np

try:
    from runtime_paths import models_path
except ImportError:
    try:
        from app.runtime_paths import models_path
    except ImportError:
        models_path = lambda *p: os.path.join(os.path.dirname(__file__), "..", "..", "models", *p)

try:
    from services.speaker_gender import detect_speaker_gender_aggregated
except ImportError:
    try:
        from app.services.speaker_gender import detect_speaker_gender_aggregated
    except ImportError:
        detect_speaker_gender_aggregated = None


class SpeakerEmbeddingClusterer:
    DEFAULT_MODEL_DIR = "pyannote"
    DEFAULT_EMBEDDING_MODEL = "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"

    def __init__(self, model_path: str | None = None, similarity_threshold: float = 0.32):
        configured = str(os.getenv("SPEAKER_DIARIZATION_EMBEDDING_MODEL", "") or "").strip()
        self.model_path = model_path or (
            os.path.abspath(configured) if configured else models_path(self.DEFAULT_MODEL_DIR, self.DEFAULT_EMBEDDING_MODEL)
        )
        try:
            self.similarity_threshold = float(os.getenv("SPEAKER_CLUSTER_MERGE_THRESHOLD", str(similarity_threshold)))
        except (TypeError, ValueError):
            self.similarity_threshold = similarity_threshold
        self._extractor = None

    def _get_extractor(self):
        if self._extractor is not None:
            return self._extractor
        if not os.path.isfile(self.model_path):
            return None
        try:
            import sherpa_onnx

            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig()
            config.model = self.model_path
            config.num_threads = 2
            config.provider = str(os.getenv("SPEAKER_DIARIZATION_PROVIDER", "cpu") or "cpu").strip().lower()
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
            return self._extractor
        except Exception as exc:
            print(f"[SpeakerClusterer] Failed to load embedding extractor: {exc}")
            return None

    def cluster_and_merge(
        self,
        audio: np.ndarray,
        sample_rate: int,
        raw_turns: list[dict[str, Any]],
        *,
        audio_path: str = "",
        max_overlap_allowed: float = 0.30,
        max_target_speakers: int = 5,
    ) -> list[dict[str, Any]]:
        """Merge over-segmented turns by audio voiceprint similarity, gender, and temporal constraints."""
        if not raw_turns or len(raw_turns) <= 1:
            return raw_turns

        extractor = self._get_extractor()
        if extractor is None:
            return raw_turns

        speaker_ids = sorted(list(set(str(t.get("speaker", "")).strip() for t in raw_turns if str(t.get("speaker", "")).strip())))
        if len(speaker_ids) <= 2:
            return raw_turns

        # Collect turns per speaker
        speaker_turns: dict[str, list[dict[str, Any]]] = {s: [] for s in speaker_ids}
        for t in raw_turns:
            spk = str(t.get("speaker", "")).strip()
            if spk in speaker_turns:
                speaker_turns[spk].append(t)

        # Detect gender per raw speaker if audio_path is given
        speaker_genders: dict[str, str] = {}
        if audio_path and os.path.isfile(audio_path) and detect_speaker_gender_aggregated:
            for s in speaker_ids:
                try:
                    res = detect_speaker_gender_aggregated(audio_path, speaker_turns[s])
                    speaker_genders[s] = res.get("gender", "unknown")
                except Exception:
                    speaker_genders[s] = "unknown"

        # Extract embeddings and durations
        speaker_embeddings: dict[str, np.ndarray] = {}
        speaker_weights: dict[str, float] = {}

        for spk in speaker_ids:
            turns = speaker_turns[spk]
            embs = []
            weights = []
            for t in turns:
                dur = float(t.get("end", 0.0)) - float(t.get("start", 0.0))
                s_idx = max(0, int(float(t.get("start", 0.0)) * sample_rate))
                e_idx = min(len(audio), int(float(t.get("end", 0.0)) * sample_rate))
                chunk = audio[s_idx:e_idx]
                if len(chunk) < 800:
                    continue

                try:
                    stream = extractor.create_stream()
                    stream.accept_waveform(sample_rate, chunk)
                    stream.input_finished()
                    if extractor.is_ready(stream):
                        emb = np.array(extractor.compute(stream), dtype=np.float32)
                        norm = np.linalg.norm(emb)
                        if norm > 1e-6:
                            embs.append(emb / norm)
                            weights.append(dur)
                except Exception:
                    continue

            total_dur = sum(float(t.get("end", 0.0)) - float(t.get("start", 0.0)) for t in turns)
            speaker_weights[spk] = total_dur

            if embs:
                w_arr = np.array(weights, dtype=np.float32)
                w_sum = np.sum(w_arr)
                if w_sum > 1e-6:
                    w_arr /= w_sum
                    centroid = np.sum(np.array(embs) * w_arr[:, None], axis=0)
                    c_norm = np.linalg.norm(centroid)
                    if c_norm > 1e-6:
                        speaker_embeddings[spk] = centroid / c_norm

        if len(speaker_embeddings) <= 2:
            return raw_turns

        # Check temporal overlap
        def has_temporal_overlap(spk1: str, spk2: str) -> bool:
            for t1 in speaker_turns[spk1]:
                s1 = float(t1.get("start", 0.0))
                e1 = float(t1.get("end", 0.0))
                for t2 in speaker_turns[spk2]:
                    s2 = float(t2.get("start", 0.0))
                    e2 = float(t2.get("end", 0.0))
                    ov = max(0.0, min(e1, e2) - max(s1, s2))
                    if ov > max_overlap_allowed:
                        return True
            return False

        active_speakers = set(speaker_embeddings.keys())
        merged_into: dict[str, str] = {s: s for s in speaker_ids}

        # Step 1: Agglomerative clustering by voiceprint similarity
        while True:
            best_pair = None
            best_sim = -1.0
            spk_list = sorted(list(active_speakers))

            for i in range(len(spk_list)):
                s1 = spk_list[i]
                e1 = speaker_embeddings[s1]
                g1 = speaker_genders.get(s1, "unknown")
                for j in range(i + 1, len(spk_list)):
                    s2 = spk_list[j]
                    e2 = speaker_embeddings[s2]
                    g2 = speaker_genders.get(s2, "unknown")

                    # Gender conflict check: male cannot merge with female
                    if g1 in ("male", "female") and g2 in ("male", "female") and g1 != g2:
                        continue
                    # Temporal overlap check
                    if has_temporal_overlap(s1, s2):
                        continue

                    sim = float(np.dot(e1, e2))
                    if sim > best_sim:
                        best_sim = sim
                        best_pair = (s1, s2)

            if best_pair and best_sim >= self.similarity_threshold:
                s1, s2 = best_pair
                w1 = speaker_weights[s1]
                w2 = speaker_weights[s2]
                new_emb = (speaker_embeddings[s1] * w1 + speaker_embeddings[s2] * w2) / max(1e-6, w1 + w2)
                norm = np.linalg.norm(new_emb)
                if norm > 1e-6:
                    speaker_embeddings[s1] = new_emb / norm
                speaker_weights[s1] = w1 + w2
                speaker_turns[s1].extend(speaker_turns[s2])
                if speaker_genders.get(s1) == "unknown" and speaker_genders.get(s2) != "unknown":
                    speaker_genders[s1] = speaker_genders[s2]

                for orig, target in list(merged_into.items()):
                    if target == s2:
                        merged_into[orig] = s1

                active_speakers.remove(s2)
            else:
                break

        # Step 2: Absorb tiny fragments (< 1.5s) into major characters
        major_clusters = [s for s in active_speakers if speaker_weights[s] >= 1.5]
        minor_clusters = [s for s in active_speakers if speaker_weights[s] < 1.5]

        for minor in minor_clusters:
            g_minor = speaker_genders.get(minor, "unknown")
            best_target = None
            best_target_sim = -1.0
            for major in major_clusters:
                g_major = speaker_genders.get(major, "unknown")
                if g_minor in ("male", "female") and g_major in ("male", "female") and g_minor != g_major:
                    continue
                if has_temporal_overlap(minor, major):
                    continue
                sim = float(np.dot(speaker_embeddings[minor], speaker_embeddings[major]))
                if sim > best_target_sim:
                    best_target_sim = sim
                    best_target = major

            if best_target:
                for orig, target in list(merged_into.items()):
                    if target == minor:
                        merged_into[orig] = best_target
                speaker_weights[best_target] += speaker_weights[minor]
                speaker_turns[best_target].extend(speaker_turns[minor])
                active_speakers.remove(minor)

        # Step 3: Canonical renaming SPEAKER_00, SPEAKER_01,... ordered by duration
        sorted_clusters = sorted(list(active_speakers), key=lambda s: -speaker_weights.get(s, 0.0))
        canonical_names = {s: f"SPEAKER_{idx:02d}" for idx, s in enumerate(sorted_clusters)}

        final_speaker_map = {}
        for orig in speaker_ids:
            target = merged_into.get(orig, orig)
            final_speaker_map[orig] = canonical_names.get(target, "SPEAKER_00")

        # Update turns with canonical speaker names
        merged_turns = []
        for t in raw_turns:
            orig = str(t.get("speaker", "")).strip()
            new_spk = final_speaker_map.get(orig, orig)
            t_copy = dict(t)
            t_copy["speaker"] = new_spk
            merged_turns.append(t_copy)

        print(f"[SpeakerClusterer] Reduced {len(speaker_ids)} raw speakers down to {len(active_speakers)} canonical characters.")
        return merged_turns
