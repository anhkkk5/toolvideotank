"""Phase 3: split one audio-diarization turn at visual speaker changes."""

from __future__ import annotations

from typing import Any


class CharacterSegmentSplitter:
    VERSION = 3
    MIN_SPAN_SECONDS = 0.18

    @classmethod
    def split_turns(
        cls,
        turns: list[dict[str, Any]],
        assignments: dict[int, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        output: list[dict[str, Any]] = []
        split_turn_count = 0
        created_span_count = 0

        for index, original in enumerate(turns):
            turn = dict(original)
            start = float(turn.get("start", 0.0) or 0.0)
            end = max(start, float(turn.get("end", start) or start))
            assignment = dict(assignments.get(index) or {})
            raw_spans = list(assignment.get("spans") or assignment.get("segments") or [])
            candidates: list[dict[str, Any]] = []
            for raw in raw_spans:
                try:
                    span_start = max(start, float(raw.get("start", start) or start))
                    span_end = min(end, float(raw.get("end", end) or end))
                    confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0) or 0.0)))
                except (TypeError, ValueError):
                    continue
                character_id = str(raw.get("character_id", "UNKNOWN") or "UNKNOWN").strip().upper()
                gender = str(raw.get("voice_category", raw.get("character_gender", "unknown")) or "unknown").strip().lower()
                if not character_id.startswith("CHAR_") or confidence < 0.65:
                    character_id, gender = "UNKNOWN", "unknown"
                if span_end - span_start < cls.MIN_SPAN_SECONDS:
                    continue
                candidates.append({
                    "start": span_start,
                    "end": span_end,
                    "character_id": character_id,
                    "character_gender": gender if gender in {"male", "female"} else "unknown",
                    "character_confidence": confidence,
                })

            if not candidates:
                output.append(turn)
                continue

            # Convert possibly overlapping model spans to a complete,
            # non-overlapping interval sequence. At every interval the most
            # confident covering observation wins.
            points = sorted({start, end, *[x["start"] for x in candidates], *[x["end"] for x in candidates]})
            pieces: list[dict[str, Any]] = []
            for left, right in zip(points, points[1:]):
                if right - left < cls.MIN_SPAN_SECONDS:
                    continue
                midpoint = (left + right) / 2.0
                covering = [x for x in candidates if x["start"] <= midpoint <= x["end"]]
                selected = max(covering, key=lambda x: x["character_confidence"]) if covering else None
                piece = dict(turn)
                piece["start"], piece["end"] = round(left, 3), round(right, 3)
                piece["phase3_segment"] = True
                if selected:
                    piece.update({
                        "character_id": selected["character_id"],
                        "character_gender": selected["character_gender"],
                        "character_confidence": selected["character_confidence"],
                        "character_source": "visual_active_speaker",
                    })
                else:
                    piece.update({
                        "character_id": "UNKNOWN",
                        "character_gender": "unknown",
                        "character_confidence": 0.0,
                        "character_source": "unresolved",
                    })
                pieces.append(piece)

            merged: list[dict[str, Any]] = []
            for piece in pieces:
                if (
                    merged
                    and merged[-1].get("character_id") == piece.get("character_id")
                    and abs(float(merged[-1]["end"]) - float(piece["start"])) <= 0.02
                ):
                    merged[-1]["end"] = piece["end"]
                    merged[-1]["character_confidence"] = max(
                        float(merged[-1].get("character_confidence", 0.0) or 0.0),
                        float(piece.get("character_confidence", 0.0) or 0.0),
                    )
                else:
                    merged.append(piece)

            if not merged:
                output.append(turn)
                continue
            distinct = {piece.get("character_id") for piece in merged if piece.get("character_id") != "UNKNOWN"}
            if len(merged) > 1 and len(distinct) > 1:
                split_turn_count += 1
                created_span_count += len(merged)
            output.extend(merged)

        output.sort(key=lambda item: (float(item.get("start", 0.0)), float(item.get("end", 0.0))))
        return output, {
            "split_turn_count": split_turn_count,
            "created_span_count": created_span_count,
        }
