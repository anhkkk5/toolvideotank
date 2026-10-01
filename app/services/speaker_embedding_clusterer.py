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

    def cluster_cues(
        self,
        audio_path: str,
        cues: list[dict[str, Any]],
        *,
        similarity_threshold: float = 0.35,
    ) -> list[dict[str, Any]]:
        """Trích xuất Speaker Embeddings từ audio và gom cụm các câu thoại (cues).

        Tự động xác định số lượng nhân vật thông qua Agglomerative Voiceprint Clustering.
        Gán `cluster_id` (SPEAKER_00, SPEAKER_01...) và tính toán `cluster_gender_prior`
        cho từng câu thoại nhằm cung cấp bằng chứng cho Bayesian Evidence Fusion.
        """
        if not cues or not audio_path or not os.path.isfile(audio_path):
            return cues

        extractor = self._get_extractor()
        if extractor is None:
            return cues

        try:
            import soundfile as sf
            audio, sr = sf.read(audio_path, dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=-1)
        except Exception as exc:
            print(f"[SpeakerClusterer] Cannot read audio for clustering: {exc}")
            return cues

        # 1. Trích xuất embedding cho từng câu thoại
        cue_embeddings: dict[int, np.ndarray] = {}
        for idx, cue in enumerate(cues):
            cid = cue.get("id", idx + 1)
            st = float(cue.get("start", 0.0) or 0.0)
            en = float(cue.get("end", st + 0.1) or (st + 0.1))
            s_idx = max(0, int(st * sr))
            e_idx = min(len(audio), int(en * sr))
            chunk = audio[s_idx:e_idx]
            if len(chunk) < 800:
                continue

            try:
                stream = extractor.create_stream()
                stream.accept_waveform(sr, chunk)
                stream.input_finished()
                if extractor.is_ready(stream):
                    emb = np.array(extractor.compute(stream), dtype=np.float32)
                    norm = np.linalg.norm(emb)
                    if norm > 1e-6:
                        cue_embeddings[cid] = emb / norm
            except Exception:
                continue

        if not cue_embeddings:
            return cues

        # 2. Agglomerative Clustering gom cụm câu thoại dựa trên Cosine Similarity
        # Khởi tạo mỗi câu là 1 cụm
        clusters: dict[int, list[int]] = {cid: [cid] for cid in cue_embeddings}
        cluster_centroids: dict[int, np.ndarray] = {cid: cue_embeddings[cid].copy() for cid in cue_embeddings}

        active_cids = list(clusters.keys())
        sim_thresh = float(similarity_threshold)

        while len(active_cids) > 1:
            best_pair = None
            best_sim = -1.0

            for i in range(len(active_cids)):
                c1 = active_cids[i]
                e1 = cluster_centroids[c1]
                for j in range(i + 1, len(active_cids)):
                    c2 = active_cids[j]
                    e2 = cluster_centroids[c2]
                    sim = float(np.dot(e1, e2))
                    if sim > best_sim:
                        best_sim = sim
                        best_pair = (c1, c2)

            if best_pair and best_sim >= sim_thresh:
                c1, c2 = best_pair
                # Gộp c2 vào c1
                clusters[c1].extend(clusters[c2])
                new_cent = cluster_centroids[c1] * len(clusters[c1]) + cluster_centroids[c2] * len(clusters[c2])
                norm = np.linalg.norm(new_cent)
                if norm > 1e-6:
                    cluster_centroids[c1] = new_cent / norm
                del clusters[c2]
                del cluster_centroids[c2]
                active_cids.remove(c2)
            else:
                break

        # 2.5 Hấp thụ các câu đơn lẻ / cụm manh mún (< 1.5s) vào cụm chính có âm sắc tương đồng nhất
        id_to_cue = {c.get("id", i + 1): c for i, c in enumerate(cues)}
        cluster_durs = {
            cid: sum(float(id_to_cue.get(mid, {}).get("end", 0.0)) - float(id_to_cue.get(mid, {}).get("start", 0.0)) for mid in clusters[cid])
            for cid in list(clusters.keys())
        }
        major_c = [cid for cid in clusters if cluster_durs.get(cid, 0.0) >= 1.5]
        minor_c = [cid for cid in clusters if cluster_durs.get(cid, 0.0) < 1.5]

        if major_c and minor_c:
            for minor in minor_c:
                best_major = None
                best_sim = -1.0
                for major in major_c:
                    sim = float(np.dot(cluster_centroids[minor], cluster_centroids[major]))
                    if sim > best_sim:
                        best_sim = sim
                        best_major = major
                if best_major and best_sim >= 0.25:
                    clusters[best_major].extend(clusters[minor])
                    new_cent = cluster_centroids[best_major] * len(clusters[best_major]) + cluster_centroids[minor] * len(clusters[minor])
                    norm = np.linalg.norm(new_cent)
                    if norm > 1e-6:
                        cluster_centroids[best_major] = new_cent / norm
                    if minor in clusters:
                        del clusters[minor]
                    if minor in cluster_centroids:
                        del cluster_centroids[minor]

        # 3. Đặt tên chuẩn hóa cụm SPEAKER_00, SPEAKER_01... sắp xếp theo số lượng câu
        sorted_clusters = sorted(clusters.values(), key=lambda member_ids: -len(member_ids))
        cue_to_cluster: dict[int, str] = {}
        cluster_gender_stats: dict[str, dict[str, float]] = {}

        id_to_cue = {c.get("id", i + 1): c for i, c in enumerate(cues)}

        for cl_idx, member_ids in enumerate(sorted_clusters):
            cluster_name = f"SPEAKER_{cl_idx:02d}"
            f_score = 0.0
            m_score = 0.0

            for cid in member_ids:
                cue_to_cluster[cid] = cluster_name
                c_item = id_to_cue.get(cid, {})
                rg = str(c_item.get("raw_gender") or c_item.get("gender") or "").lower()
                rc = float(c_item.get("raw_gender_confidence") or c_item.get("confidence") or 0.5)
                if rc > 1.0:
                    rc /= 100.0
                if rg == "female":
                    f_score += rc
                elif rg == "male":
                    m_score += rc

            total_s = f_score + m_score
            if total_s > 0:
                cluster_gender_stats[cluster_name] = {
                    "female": f_score / total_s,
                    "male": m_score / total_s,
                }
            else:
                cluster_gender_stats[cluster_name] = {"female": 0.5, "male": 0.5}

        # 4. Gán thông tin cụm và Prior vào cues
        enriched_cues: list[dict[str, Any]] = []
        for idx, cue in enumerate(cues):
            c_copy = dict(cue)
            cid = c_copy.get("id", idx + 1)
            cl_name = cue_to_cluster.get(cid, "SPEAKER_00")
            c_copy["cluster_id"] = cl_name
            c_copy["voice_cluster"] = cl_name

            stats = cluster_gender_stats.get(cl_name, {"female": 0.5, "male": 0.5})
            c_copy["cluster_female_ratio"] = round(stats["female"], 3)
            c_copy["cluster_male_ratio"] = round(stats["male"], 3)
            if stats["female"] > 0.60:
                c_copy["cluster_gender_prior"] = "female"
                c_copy["cluster_prior_confidence"] = round(stats["female"], 3)
            elif stats["male"] > 0.60:
                c_copy["cluster_gender_prior"] = "male"
                c_copy["cluster_prior_confidence"] = round(stats["male"], 3)
            else:
                c_copy["cluster_gender_prior"] = "unknown"
                c_copy["cluster_prior_confidence"] = 0.5

            enriched_cues.append(c_copy)

        print(f"[SpeakerClusterer] Clustered {len(cues)} cues into {len(sorted_clusters)} voiceprint characters.")
        return enriched_cues

