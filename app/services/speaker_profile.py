"""Speaker Profile Aggregator.

Builds a comprehensive profile for each speaker including total speech duration,
utterance count, temporal span, and scene presence to compute a deterministic RoleScore.
"""

from __future__ import annotations

from typing import Any


def build_speaker_profiles(
    subtitles: list[dict[str, Any]],
    *,
    scene_interval_seconds: float = 15.0,
) -> dict[str, dict[str, Any]]:
    """Aggregate statistics for every speaker in the subtitles.

    Returns:
        dict mapping speaker_id -> {
            "speaker_id": str,
            "speech_duration": float,
            "utterance_count": int,
            "first_seen": float,
            "last_seen": float,
            "scene_count": int,
            "role_score": float,
        }
    """
    profiles: dict[str, dict[str, Any]] = {}
    scenes_seen: dict[str, set[int]] = {}

    for sub in subtitles or []:
        spk = str(sub.get("speaker", "") or "SPEAKER_00").strip()
        start = float(sub.get("start", 0.0) or 0.0)
        end = float(sub.get("end", start + 1.0) or (start + 1.0))
        dur = max(0.1, end - start)

        if spk not in profiles:
            profiles[spk] = {
                "speaker_id": spk,
                "speech_duration": 0.0,
                "utterance_count": 0,
                "first_seen": start,
                "last_seen": end,
                "scene_count": 0,
                "role_score": 0.0,
            }
            scenes_seen[spk] = set()

        prof = profiles[spk]
        prof["speech_duration"] += dur
        prof["utterance_count"] += 1
        prof["first_seen"] = min(prof["first_seen"], start)
        prof["last_seen"] = max(prof["last_seen"], end)

        # Estimate scene presence by bucketing timestamps into scene intervals
        scene_idx = int(start // scene_interval_seconds)
        scenes_seen[spk].add(scene_idx)

    # Compute scene count
    for spk, prof in profiles.items():
        prof["scene_count"] = len(scenes_seen.get(spk, set()))
        prof["speech_duration"] = round(prof["speech_duration"], 2)

    # Normalize metrics and compute RoleScore:
    # RoleScore = 0.60 * duration_norm + 0.25 * utterance_norm + 0.15 * scene_norm
    max_dur = max((p["speech_duration"] for p in profiles.values()), default=1.0) or 1.0
    max_utt = max((p["utterance_count"] for p in profiles.values()), default=1) or 1
    max_scenes = max((p["scene_count"] for p in profiles.values()), default=1) or 1

    for prof in profiles.values():
        dur_norm = prof["speech_duration"] / max_dur
        utt_norm = prof["utterance_count"] / max_utt
        scene_norm = prof["scene_count"] / max_scenes

        score = (0.60 * dur_norm) + (0.25 * utt_norm) + (0.15 * scene_norm)
        prof["role_score"] = round(score, 4)

    return profiles
