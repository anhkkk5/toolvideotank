"""Phase 4 persistence and application of user character corrections."""

from __future__ import annotations

from typing import Any


class CharacterCorrectionService:
    VERSION = 4

    @staticmethod
    def build_review_queue(segments: list[dict[str, Any]], threshold: float = 0.80) -> list[dict[str, Any]]:
        queue = []
        for index, segment in enumerate(segments or []):
            character_id = str(segment.get("character_id", segment.get("speaker", "UNKNOWN")) or "UNKNOWN")
            confidence = float(segment.get("character_confidence", segment.get("speaker_confidence", 0.0)) or 0.0)
            source = str(segment.get("character_source", "") or "")
            reasons = []
            if not character_id.startswith("CHAR_"):
                reasons.append("unresolved_character")
            if confidence < threshold:
                reasons.append("low_confidence")
            if reasons and source != "manual_correction":
                queue.append({
                    "segment_index": index,
                    "start": float(segment.get("start", 0.0) or 0.0),
                    "end": float(segment.get("end", 0.0) or 0.0),
                    "text": str(segment.get("text", "") or ""),
                    "character_id": character_id,
                    "confidence": confidence,
                    "source": source,
                    "reasons": reasons,
                })
        return queue

    @staticmethod
    def upsert(corrections: list[dict[str, Any]], correction: dict[str, Any]) -> list[dict[str, Any]]:
        item = dict(correction or {})
        start = round(float(item.get("start", 0.0) or 0.0), 3)
        end = round(max(start, float(item.get("end", start) or start)), 3)
        character_id = str(item.get("character_id", "UNKNOWN") or "UNKNOWN").strip().upper()
        item.update({"start": start, "end": end, "character_id": character_id, "version": 1})
        kept = [
            dict(existing) for existing in list(corrections or [])
            if abs(float(existing.get("start", -99.0) or -99.0) - start) > 0.04
            or abs(float(existing.get("end", -99.0) or -99.0) - end) > 0.04
        ]
        kept.append(item)
        return sorted(kept, key=lambda value: (float(value.get("start", 0.0)), float(value.get("end", 0.0))))

    @classmethod
    def apply(cls, result: dict[str, Any], corrections: list[dict[str, Any]]) -> dict[str, Any]:
        output = dict(result or {})
        turns = [dict(turn) for turn in list(output.get("turns") or [])]
        registry = {
            str(item.get("character_id", "") or ""): dict(item)
            for item in list(output.get("characters") or [])
            if str(item.get("character_id", "") or "").startswith("CHAR_")
        }
        applied = 0
        for turn in turns:
            ts = float(turn.get("start", 0.0) or 0.0)
            te = max(ts, float(turn.get("end", ts) or ts))
            best = None
            best_overlap = 0.0
            for correction in corrections or []:
                cs = float(correction.get("start", 0.0) or 0.0)
                ce = max(cs, float(correction.get("end", cs) or cs))
                overlap = max(0.0, min(te, ce) - max(ts, cs))
                if overlap > best_overlap:
                    best, best_overlap = correction, overlap
            if not best or best_overlap < min(0.20, max(0.05, (te - ts) * 0.25)):
                continue
            character_id = str(best.get("character_id", "UNKNOWN") or "UNKNOWN").strip().upper()
            gender = str(best.get("character_gender", "unknown") or "unknown").strip().lower()
            turn.update({
                "character_id": character_id,
                "character_gender": gender if gender in {"male", "female"} else "unknown",
                "character_confidence": 1.0,
                "character_source": "manual_correction",
            })
            if character_id.startswith("CHAR_"):
                registry.setdefault(character_id, {
                    "character_id": character_id,
                    "gender": turn["character_gender"],
                    "audio_speakers": [],
                    "turn_indices": [],
                })
            applied += 1

        for character_id, character in registry.items():
            matching = [
                (index, turn) for index, turn in enumerate(turns)
                if str(turn.get("character_id", "") or "") == character_id
            ]
            character["turn_indices"] = [index for index, _ in matching]
            character["audio_speakers"] = sorted({
                str(turn.get("speaker", "") or "") for _, turn in matching
                if str(turn.get("speaker", "") or "")
            })
            manual_genders = [
                str(turn.get("character_gender", "unknown") or "unknown") for _, turn in matching
                if str(turn.get("character_source", "") or "") == "manual_correction"
                and str(turn.get("character_gender", "unknown") or "unknown") in {"male", "female"}
            ]
            if manual_genders:
                character["gender"] = max({"male", "female"}, key=manual_genders.count)

        characters = [registry[key] for key in sorted(registry)]
        summary = dict(output.get("character_summary") or {})
        summary.update({
            "version": max(cls.VERSION, int(summary.get("version", 0) or 0)),
            "manual_correction_count": applied,
            "character_count": len(characters),
            "male_count": sum(1 for item in characters if item.get("gender") == "male"),
            "female_count": sum(1 for item in characters if item.get("gender") == "female"),
        })
        output.update({"turns": turns, "characters": characters, "character_summary": summary})
        return output
