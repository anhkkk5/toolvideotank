"""Smart Role Ranking and Voice Cast Engine.

Determines Lead and Supporting roles for each gender based on RoleScore,
and produces an immutable speaker-to-voice mapping from SMART_CAST_VOICES.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from config.smart_cast_voices import get_smart_cast_voice, SMART_CAST_VOICES
except ImportError:
    try:
        from app.config.smart_cast_voices import get_smart_cast_voice, SMART_CAST_VOICES
    except ImportError:
        from ..config.smart_cast_voices import get_smart_cast_voice, SMART_CAST_VOICES

try:
    from services.speaker_gender import detect_speaker_gender_aggregated
    from services.speaker_profile import build_speaker_profiles
except ImportError:
    try:
        from app.services.speaker_gender import detect_speaker_gender_aggregated
        from app.services.speaker_profile import build_speaker_profiles
    except ImportError:
        from .speaker_gender import detect_speaker_gender_aggregated
        from .speaker_profile import build_speaker_profiles


def auto_cast_speakers(
    subtitles: list[dict[str, Any]],
    audio_path: str = "",
    *,
    gender_overrides: dict[str, str] | None = None,
    expected_speakers: int = -1,
    speaker_turns: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Execute complete Smart Auto-Cast pipeline.

    Args:
        subtitles: List of subtitle dicts with 'start', 'end', and 'speaker'.
        audio_path: Optional path to extracted video audio for acoustic analysis.
        gender_overrides: Optional manual map of speaker_id -> 'male'|'female'.

    Returns:
        tuple (speaker_voice_map, detailed_speaker_profiles)
        where speaker_voice_map is an immutable dict: speaker_id -> voice_name
    """
    if not subtitles:
        return {}, {}

    # Ensure speaker turns exist on subtitles by aligning with audio diarization if needed
    distinct_speakers = set(str(s.get("speaker", "")).strip() for s in subtitles if str(s.get("speaker", "")).strip())
    needs_alignment = (len(distinct_speakers) <= 1 or len(distinct_speakers) > 5)
    if needs_alignment and audio_path and os.path.isfile(audio_path):
        try:
            from services.speaker_diarization_service import SpeakerDiarizationService
            from services.subtitle_speaker_aligner import align_subtitles_to_speakers
            diar_service = SpeakerDiarizationService()
            diar_turns = diar_service.diarize(audio_path, num_speakers=expected_speakers)
            if diar_turns:
                subtitles = align_subtitles_to_speakers(subtitles, diar_turns)
        except Exception as exc:
            print(f"[Smart Cast] Diarization alignment error: {exc}")

    gender_overrides = gender_overrides or {}
    # Do not create a character voice from labels that were only inherited
    # from the nearest/previous diarization turn. They remain editable in the
    # timeline but use the global fallback voice until confirmed.
    reliable_subtitles = [
        s for s in subtitles
        if float(s.get("speaker_confidence", 1.0) or 0.0) >= 0.55
    ]
    profiles = build_speaker_profiles(reliable_subtitles)

    # 1. Determine gender for each speaker using multi-segment acoustic analysis
    for spk, prof in profiles.items():
        if spk in gender_overrides:
            prof["gender"] = gender_overrides[spk].lower()
            prof["gender_confidence"] = 1.0
        elif audio_path:
            # Prefer diarization turns: OCR cue windows often include silence
            # or the next character and can turn a clear male/female cluster
            # into an incorrect/unknown result.
            gender_segments = speaker_turns if speaker_turns else subtitles
            spk_segs = [
                s for s in gender_segments
                if str(s.get("speaker", "")).strip() == spk
            ]
            res = detect_speaker_gender_aggregated(audio_path, spk_segs)
            gender_confidence = float(res.get("confidence", 0.0) or 0.0)
            prof["gender"] = res.get("gender", "unknown") if gender_confidence >= 0.65 else "unknown"
            prof["gender_confidence"] = gender_confidence
            prof["spectral_centroid"] = res.get("mean_centroid", 0.0)
            prof["median_pitch"] = res.get("median_pitch", 0.0)
        else:
            prof["gender"] = "unknown"
            prof["gender_confidence"] = 0.0

    # 2. Group speakers by gender and sort by RoleScore descending
    males = [p for p in profiles.values() if p.get("gender") == "male"]
    females = [p for p in profiles.values() if p.get("gender") == "female"]
    unknowns = [p for p in profiles.values() if p.get("gender") not in ("male", "female")]

    males.sort(key=lambda x: x.get("role_score", 0.0), reverse=True)
    females.sort(key=lambda x: x.get("role_score", 0.0), reverse=True)

    # Unknown acoustic gender must not be guessed by alternating male/female;
    # that made a low-confidence diarization error become a confidently wrong
    # character voice. Leave it for manual selection/global fallback.

    males.sort(key=lambda x: x.get("role_score", 0.0), reverse=True)
    females.sort(key=lambda x: x.get("role_score", 0.0), reverse=True)

    # 3. Assign Role and Voice based on Rank
    speaker_voice_map: dict[str, str] = {}

    # Rank Males
    for rank, prof in enumerate(males, 1):
        spk_id = prof["speaker_id"]
        role_label = "Nam chính" if rank == 1 else f"Nam phụ {rank - 1}"
        # Gender-only casting: every male character shares the configured
        # primary male voice while speaker IDs remain separate.
        voice_name = get_smart_cast_voice("male", 1)

        prof["role_rank"] = rank
        prof["role_label"] = role_label
        prof["voice_name"] = voice_name
        speaker_voice_map[spk_id] = voice_name

    # Rank Females
    for rank, prof in enumerate(females, 1):
        spk_id = prof["speaker_id"]
        role_label = "Nữ chính" if rank == 1 else f"Nữ phụ {rank - 1}"
        # Gender-only casting: every female character shares the configured
        # primary female voice while speaker IDs remain separate.
        voice_name = get_smart_cast_voice("female", 1)

        prof["role_rank"] = rank
        prof["role_label"] = role_label
        prof["voice_name"] = voice_name
        speaker_voice_map[spk_id] = voice_name

    return speaker_voice_map, profiles


def apply_smart_cast_to_subtitles(
    subtitles: list[dict[str, Any]],
    speaker_voice_map: dict[str, str],
    default_fallback_voice: str = "vieneu_cogaihoatbat",
    profiles: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Apply the immutable speaker-to-voice mapping onto all subtitle cues."""
    updated: list[dict[str, Any]] = []
    profiles = profiles or {}
    for sub in subtitles or []:
        item = dict(sub)
        spk = str(item.get("speaker", "") or "").strip()
        assigned_voice = speaker_voice_map.get(spk)
        if assigned_voice:
            item["voice_name"] = assigned_voice
        else:
            item.pop("voice_name", None)
        if profiles and spk in profiles:
            prof = profiles[spk]
            gender = prof.get("gender", "female")
            rank = prof.get("role_rank", 1)
            if gender == "female":
                item["voice_group"] = "circle" if rank <= 1 else "diamond"
            else:
                item["voice_group"] = "square" if rank <= 1 else "triangle"
        updated.append(item)
    return updated
