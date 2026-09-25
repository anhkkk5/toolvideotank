"""Build character-analysis turns for subtitle cues missed by diarization.

Audio diarization and burned-in subtitle OCR are independent observations.  A
valid OCR cue must not inherit the nearest speaker merely because the audio
provider omitted a short turn.  This service converts those uncovered cues to
synthetic turns so the existing visual/voice Character Resolver can inspect
their exact time range.
"""

from __future__ import annotations

from typing import Any


class PostOCRCharacterResolver:
    VERSION = 1

    @classmethod
    def apply_temporal_continuity(
        cls,
        turns: list[dict[str, Any]],
        *,
        maximum_gap: float = 0.75,
    ) -> tuple[list[dict[str, Any]], int]:
        """Resolve a short UNKNOWN turn bracketed by the same character.

        This is deliberately conservative: both neighbours must independently
        agree on a resolved Character ID and gender.  It handles short OCR
        cues that diarization missed without guessing from only one side.
        """
        ordered = sorted(
            [dict(turn) for turn in turns or []],
            key=lambda item: (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0)),
        )
        repaired = 0
        for index in range(1, len(ordered) - 1):
            turn = ordered[index]
            current = str(turn.get("character_id", "UNKNOWN") or "UNKNOWN").upper()
            if current.startswith("CHAR_"):
                continue
            previous, following = ordered[index - 1], ordered[index + 1]
            previous_id = str(previous.get("character_id", "") or "").upper()
            following_id = str(following.get("character_id", "") or "").upper()
            previous_gender = str(previous.get("character_gender", "unknown") or "unknown").lower()
            following_gender = str(following.get("character_gender", "unknown") or "unknown").lower()
            left_gap = float(turn.get("start", 0.0) or 0.0) - float(previous.get("end", 0.0) or 0.0)
            right_gap = float(following.get("start", 0.0) or 0.0) - float(turn.get("end", 0.0) or 0.0)
            if not previous_id.startswith("CHAR_") or previous_id != following_id:
                continue
            if previous_gender not in {"male", "female"} or previous_gender != following_gender:
                continue
            if left_gap > maximum_gap or right_gap > maximum_gap:
                continue
            confidence = min(
                float(previous.get("character_confidence", 0.0) or 0.0),
                float(following.get("character_confidence", 0.0) or 0.0),
            )
            if confidence < 0.70:
                continue
            turn["character_id"] = previous_id
            turn["character_gender"] = previous_gender
            turn["character_confidence"] = round(max(0.70, confidence * 0.9), 4)
            turn["character_source"] = "temporal_continuity"
            repaired += 1
        # A short lead-in immediately attached to the following resolved line
        # is normally one utterance split by OCR punctuation (for example a
        # greeting followed by an introduction).
        # Walk backwards so a resolved anchor can propagate through several
        # contiguous OCR pieces belonging to the same sentence/monologue.
        for index in range(len(ordered) - 2, -1, -1):
            turn, following = ordered[index], ordered[index + 1]
            current = str(turn.get("character_id", "UNKNOWN") or "UNKNOWN").upper()
            if current.startswith("CHAR_"):
                continue
            source = str(turn.get("character_source", "") or "").lower()
            if source not in {"visual_active_speaker", "unresolved", "post_ocr_pending"}:
                continue
            duration = float(turn.get("end", 0.0) or 0.0) - float(turn.get("start", 0.0) or 0.0)
            right_gap = float(following.get("start", 0.0) or 0.0) - float(turn.get("end", 0.0) or 0.0)
            following_id = str(following.get("character_id", "") or "").upper()
            following_gender = str(following.get("character_gender", "unknown") or "unknown").lower()
            following_confidence = float(following.get("character_confidence", 0.0) or 0.0)
            if duration > 3.5 or right_gap > 0.15 or not following_id.startswith("CHAR_"):
                continue
            if following_gender not in {"male", "female"} or following_confidence < 0.70:
                continue
            turn["character_id"] = following_id
            turn["character_gender"] = following_gender
            turn["character_confidence"] = round(max(0.70, following_confidence * 0.85), 4)
            turn["character_source"] = "ocr_continuation"
            repaired += 1
        return ordered, repaired

    @staticmethod
    def _overlap(start: float, end: float, other_start: float, other_end: float) -> float:
        return max(0.0, min(end, other_end) - max(start, other_start))

    @classmethod
    def find_uncovered_cues(
        cls,
        cues: list[dict[str, Any]],
        turns: list[dict[str, Any]],
        *,
        minimum_coverage: float = 0.25,
    ) -> list[dict[str, Any]]:
        uncovered: list[dict[str, Any]] = []
        for cue_index, cue in enumerate(cues or []):
            start = max(0.0, float(cue.get("start", 0.0) or 0.0))
            end = max(start + 0.05, float(cue.get("end", start + 0.05) or (start + 0.05)))
            duration = max(0.05, end - start)
            best_overlap = max(
                (
                    cls._overlap(
                        start,
                        end,
                        float(turn.get("start", 0.0) or 0.0),
                        float(turn.get("end", 0.0) or 0.0),
                    )
                    for turn in turns or []
                ),
                default=0.0,
            )
            if best_overlap / duration < minimum_coverage:
                item = dict(cue)
                item["cue_index"] = cue_index
                item["coverage"] = round(best_overlap / duration, 4)
                uncovered.append(item)
        return uncovered

    @classmethod
    def augment_turns(
        cls,
        cues: list[dict[str, Any]],
        turns: list[dict[str, Any]],
        *,
        minimum_coverage: float = 0.25,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        base_turns = [dict(turn) for turn in turns or []]
        gaps = cls.find_uncovered_cues(
            cues, base_turns, minimum_coverage=minimum_coverage
        )
        synthetic: list[dict[str, Any]] = []
        for gap in gaps:
            cue_index = int(gap.get("cue_index", len(synthetic)) or 0)
            start = max(0.0, float(gap.get("start", 0.0) or 0.0))
            end = max(start + 0.05, float(gap.get("end", start + 0.05) or (start + 0.05)))
            synthetic.append({
                "start": round(start, 3),
                "end": round(end, 3),
                "speaker": f"OCR_GAP_{cue_index:04d}",
                "text": str(gap.get("text", gap.get("original_text", "")) or ""),
                "ocr_cue_index": cue_index,
                "turn_origin": "post_ocr_gap",
                "character_id": "UNKNOWN",
                "character_gender": "unknown",
                "character_confidence": 0.0,
                "character_source": "post_ocr_pending",
            })
        combined = sorted(
            [*base_turns, *synthetic],
            key=lambda item: (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0)),
        )
        return combined, {
            "version": cls.VERSION,
            "cue_count": len(cues or []),
            "original_turn_count": len(base_turns),
            "gap_count": len(synthetic),
            "minimum_coverage": minimum_coverage,
            "gaps": [
                {
                    "cue_index": item["ocr_cue_index"],
                    "start": item["start"],
                    "end": item["end"],
                    "text": item["text"],
                }
                for item in synthetic
            ],
        }
