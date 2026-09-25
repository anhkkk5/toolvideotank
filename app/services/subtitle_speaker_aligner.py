"""Subtitle-Speaker Temporal Aligner.

Aligns OCR or Whisper subtitle cues to audio diarized speaker turns
using Maximum Temporal Overlap. Handles overlapping speech and assigns
speaker confidence metrics.
"""

from __future__ import annotations

from typing import Any


def calculate_overlap(s1: float, e1: float, s2: float, e2: float) -> float:
    """Calculate the overlap duration in seconds between two intervals [s1, e1] and [s2, e2]."""
    return max(0.0, min(e1, e2) - max(s1, s2))


def align_subtitles_to_speakers(
    subtitles: list[dict[str, Any]],
    diarization_segments: list[dict[str, Any]],
    *,
    min_confidence_threshold: float = 0.25,
    default_speaker: str = "SPEAKER_00",
) -> list[dict[str, Any]]:
    """Assign a speaker_id and confidence to each subtitle segment.

    Args:
        subtitles: List of dicts with 'start', 'end', and 'text'.
        diarization_segments: List of dicts with 'start', 'end', and 'speaker'.
        min_confidence_threshold: Minimum overlap ratio to accept a turn.
        default_speaker: Fallback speaker if no turn overlaps.

    Returns:
        New list of subtitle dicts with 'speaker' and 'speaker_confidence' populated.
    """
    if not subtitles:
        return []

    if not diarization_segments:
        # Fallback: keep existing speaker or assign default
        aligned = []
        for s in subtitles:
            item = dict(s)
            item.setdefault("speaker", default_speaker)
            item.setdefault("speaker_confidence", 0.0)
            aligned.append(item)
        return aligned

    aligned_subtitles: list[dict[str, Any]] = []
    last_known_speaker = default_speaker

    for sub in subtitles:
        item = dict(sub)
        sub_start = float(item.get("start", 0.0) or 0.0)
        sub_end = float(item.get("end", sub_start + 1.0) or (sub_start + 1.0))
        sub_dur = max(0.05, sub_end - sub_start)

        best_speaker = ""
        best_turn: dict[str, Any] | None = None
        max_overlap = 0.0

        # Find diarization segment with maximum overlap duration
        for diar in diarization_segments:
            d_start = float(diar.get("start", 0.0) or 0.0)
            d_end = float(diar.get("end", d_start + 1.0) or (d_start + 1.0))
            spk = str(diar.get("speaker", "") or "").strip()

            if not spk:
                continue

            ov = calculate_overlap(sub_start, sub_end, d_start, d_end)
            if ov > max_overlap:
                max_overlap = ov
                best_speaker = spk
                best_turn = diar

        # Confidence is ratio of overlap to subtitle duration
        confidence = min(1.0, max_overlap / sub_dur) if sub_dur > 0 else 0.0

        if best_speaker and confidence >= min_confidence_threshold:
            item["speaker"] = best_speaker
            item["speaker_confidence"] = round(confidence, 2)
            last_known_speaker = best_speaker
        else:
            # Fallback 1: Find nearest diarization turn within 1.5s
            nearest_spk = ""
            nearest_turn: dict[str, Any] | None = None
            min_dist = float("inf")
            for diar in diarization_segments:
                d_start = float(diar.get("start", 0.0) or 0.0)
                d_end = float(diar.get("end", d_start + 1.0) or (d_start + 1.0))
                spk = str(diar.get("speaker", "") or "").strip()
                if not spk:
                    continue
                dist = min(abs(sub_start - d_end), abs(d_start - sub_end))
                if dist < min_dist:
                    min_dist = dist
                    nearest_spk = spk
                    nearest_turn = diar

            if nearest_spk and min_dist <= 1.5:
                item["speaker"] = nearest_spk
                item["speaker_confidence"] = round(max(0.2, 1.0 - (min_dist / 1.5)), 2)
                last_known_speaker = nearest_spk
                best_turn = nearest_turn
            else:
                # Fallback 2: Last known speaker
                item["speaker"] = last_known_speaker
                item["speaker_confidence"] = round(confidence, 2)

        if best_turn:
            character_id = str(best_turn.get("character_id", "") or "").strip()
            character_confidence = float(best_turn.get("character_confidence", 0.0) or 0.0)
            if character_id.startswith("CHAR_") and character_confidence >= 0.65:
                item["audio_speaker"] = item.get("speaker", "")
                item["speaker"] = character_id
                item["character_id"] = character_id
                item["character_gender"] = str(best_turn.get("character_gender", "unknown") or "unknown")
                item["character_confidence"] = round(character_confidence, 2)
                item["character_source"] = str(
                    best_turn.get("character_source", "temporal_alignment") or "temporal_alignment"
                )

        sub["speaker"] = item["speaker"]
        sub["speaker_confidence"] = item["speaker_confidence"]
        aligned_subtitles.append(item)

    return aligned_subtitles
