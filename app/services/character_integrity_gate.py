"""Quality gate between character resolution and automatic voice casting."""

from __future__ import annotations

from typing import Any


class CharacterIntegrityGate:
    VERSION = 1

    @classmethod
    def inspect(
        cls,
        segments: list[dict[str, Any]],
        *,
        minimum_confidence: float = 0.65,
    ) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        voice_by_character: dict[str, str] = {}
        for index, segment in enumerate(segments or []):
            character_id = str(
                segment.get("character_id", segment.get("speaker", "UNKNOWN")) or "UNKNOWN"
            ).strip().upper()
            gender = str(segment.get("character_gender", "unknown") or "unknown").strip().lower()
            confidence = float(segment.get("character_confidence", 0.0) or 0.0)
            voice = str(segment.get("voice_name", "") or "").strip()
            reasons: list[str] = []
            if not character_id.startswith("CHAR_"):
                reasons.append("unresolved_character")
            if gender not in {"male", "female"}:
                reasons.append("unknown_gender")
            if confidence < minimum_confidence:
                reasons.append("low_confidence")
            if character_id.startswith("CHAR_") and voice:
                previous_voice = voice_by_character.setdefault(character_id, voice)
                if previous_voice != voice:
                    reasons.append("character_voice_conflict")
            if reasons:
                issues.append({
                    "segment_index": index,
                    "start": float(segment.get("start", 0.0) or 0.0),
                    "end": float(segment.get("end", 0.0) or 0.0),
                    "text": str(segment.get("text", "") or ""),
                    "character_id": character_id,
                    "gender": gender,
                    "confidence": confidence,
                    "reasons": reasons,
                })
        return {
            "version": cls.VERSION,
            "passed": not issues,
            "segment_count": len(segments or []),
            "issue_count": len(issues),
            "minimum_confidence": minimum_confidence,
            "issues": issues,
        }

