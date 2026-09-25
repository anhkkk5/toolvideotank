"""Anchor-based Temporal Smoothing service for voice gender classification."""

from __future__ import annotations

from typing import Any


class TemporalGenderSmoothingService:
    """Refine low-quality voice gender segments using strong audio anchors and context."""

    @staticmethod
    def smooth(
        cues: list[dict[str, Any]],
        continuity_groups: list[dict[str, Any]] | None = None,
        max_gap: float = 0.85,
    ) -> list[dict[str, Any]]:
        if not cues:
            return []

        same_speaker_map: dict[int, float] = {}
        if continuity_groups:
            for group in continuity_groups:
                ids = group.get("ids", [])
                likelihood = float(group.get("same_speaker_likelihood", 0.0) or 0.0)
                for iid in ids:
                    same_speaker_map[iid] = likelihood

        results: list[dict[str, Any]] = []
        for c in cues:
            item = dict(c)
            raw_g = item.get("raw_gender") or item.get("gender", "unknown")
            raw_c = float(item.get("raw_gender_confidence") or item.get("confidence", 0.0) or 0.0)
            item.setdefault("raw_gender", raw_g)
            item.setdefault("raw_gender_confidence", raw_c)
            item.setdefault("final_gender", raw_g)
            item.setdefault("final_decision_confidence", raw_c)
            item.setdefault("decision_mode", "raw_audio")
            item.setdefault("gender_reason", ["raw_audio_inference"])
            results.append(item)

        n = len(results)
        clusters: list[list[int]] = []
        current_cluster: list[int] = [0]

        for i in range(1, n):
            prev = results[i - 1]
            curr = results[i]
            gap = float(curr.get("start", 0.0)) - float(prev.get("end", 0.0))

            prev_id = prev.get("id")
            curr_id = curr.get("id")
            has_deepseek_link = (
                prev_id in same_speaker_map
                and curr_id in same_speaker_map
                and same_speaker_map[prev_id] >= 0.80
            )

            if gap <= max_gap or has_deepseek_link:
                current_cluster.append(i)
            else:
                clusters.append(current_cluster)
                current_cluster = [i]
        if current_cluster:
            clusters.append(current_cluster)

        for cluster_indices in clusters:
            male_anchors: list[tuple[int, float]] = []
            female_anchors: list[tuple[int, float]] = []

            for idx in cluster_indices:
                c = results[idx]
                raw_g = str(c.get("raw_gender", "")).lower()
                raw_c = float(c.get("raw_gender_confidence", 0.0) or 0.0)
                trust = str(c.get("raw_confidence_trust", "LOW")).upper()
                qual = str(c.get("audio_quality", "low")).lower()

                # Anchor mạnh: BẮT BUỘC phải là âm thanh sạch (clean) và trust HIGH
                is_anchor = (qual == "clean" and trust == "HIGH" and raw_c >= 0.85)
                if is_anchor:
                    if raw_g == "male":
                        male_anchors.append((idx, raw_c))
                    elif raw_g == "female":
                        female_anchors.append((idx, raw_c))

            # Dialogue Switch Evidence: Nếu trong cụm có cả Anchor Nam và Nữ -> Đối thoại đối đáp!
            if male_anchors and female_anchors:
                continue

            target_gender = None
            anchor_confs: list[float] = []
            if male_anchors and not female_anchors:
                target_gender = "male"
                anchor_confs = [c for _, c in male_anchors]
            elif female_anchors and not male_anchors:
                target_gender = "female"
                anchor_confs = [c for _, c in female_anchors]

            if not target_gender or not anchor_confs:
                continue

            avg_anchor_conf = sum(anchor_confs) / len(anchor_confs)

            for idx in cluster_indices:
                c = results[idx]
                raw_g = str(c.get("raw_gender", "")).lower()
                raw_c = float(c.get("raw_gender_confidence", 0.0) or 0.0)
                trust = str(c.get("raw_confidence_trust", "LOW")).upper()
                cid = c.get("id")

                # Bằng chứng chống smoothing: nếu câu có audio sạch và tự tin cao khác với target_gender
                if c.get("audio_quality") == "clean" and raw_g != target_gender and raw_c >= 0.85:
                    continue

                is_weak = (trust in {"LOW", "MEDIUM"} or float(c.get("speech_duration", 0.0)) < 1.1)

                if is_weak and raw_g != target_gender:
                    c["final_gender"] = target_gender
                    c["gender"] = target_gender
                    c["decision_mode"] = "contextual_smoothing"

                    ss_bonus = 0.04 if same_speaker_map.get(cid, 0.0) >= 0.80 else 0.0
                    c["final_decision_confidence"] = round(min(0.96, avg_anchor_conf * 0.91 + ss_bonus), 3)
                    c["confidence"] = c["final_decision_confidence"]

                    reasons = list(c.get("gender_reason", []))
                    reasons.append("anchor_continuity_smoothing")
                    if target_gender == "male":
                        reasons.append(f"aligned_with_{len(male_anchors)}_male_anchors")
                    else:
                        reasons.append(f"aligned_with_{len(female_anchors)}_female_anchors")
                    if same_speaker_map.get(cid, 0.0) >= 0.80:
                        reasons.append("deepseek_same_speaker_verified")
                    c["gender_reason"] = reasons

        return results
