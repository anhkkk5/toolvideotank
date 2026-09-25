"""Speaker Gender Detection Service based on multi-segment acoustic spectral centroid analysis.

Analyzes multiple clean speech samples belonging to the same speaker identity
to reliably determine acoustic gender (male/female/unknown) with confidence scores.
"""

from __future__ import annotations

import os
import wave
from typing import Any
import numpy as np


def detect_speaker_gender_aggregated(
    audio_path: str,
    speaker_segments: list[dict[str, Any]],
    *,
    min_segment_duration: float = 0.6,
    max_samples: int = 15,
) -> dict[str, Any]:
    """Aggregate spectral centroid across multiple segments of a single speaker.

    Returns:
        {
            "gender": "male" | "female" | "unknown",
            "confidence": float (0.0 to 1.0),
            "mean_centroid": float,
            "sample_count": int,
        }
    """
    if not audio_path or not os.path.isfile(audio_path) or not speaker_segments:
        return {
            "gender": "unknown",
            "confidence": 0.0,
            "mean_centroid": 0.0,
            "sample_count": 0,
        }

    try:
        with wave.open(audio_path, "rb") as wf:
            sr = wf.getframerate()
            n_ch = wf.getnchannels()
            total_frames = wf.getnframes()

            centroids: list[float] = []
            pitches: list[float] = []

            # Sort segments by duration descending to pick the cleanest/longest speech first
            valid_segments = []
            for seg in speaker_segments:
                s = float(seg.get("start", 0.0) or 0.0)
                e = float(seg.get("end", s + 1.0) or (s + 1.0))
                dur = e - s
                if dur >= min_segment_duration:
                    valid_segments.append((s, min(dur, 3.0)))

            valid_segments.sort(key=lambda x: x[1], reverse=True)

            for s_time, dur_time in valid_segments[:max_samples]:
                start_f = int(s_time * sr)
                dur_f = int(dur_time * sr)

                if start_f < 0 or start_f + dur_f > total_frames or dur_f <= 0:
                    continue

                wf.setpos(start_f)
                raw = wf.readframes(dur_f)
                if not raw:
                    continue

                data = np.frombuffer(raw, dtype=np.int16)
                if n_ch == 2:
                    data = data[::2]

                # FFT analysis in speech frequency range [85Hz, 3000Hz]
                fft = np.abs(np.fft.rfft(data))
                freqs = np.fft.rfftfreq(len(data), 1.0 / sr)
                mask = (freqs >= 85) & (freqs <= 3000)

                sum_mag = float(np.sum(fft[mask]))
                if sum_mag > 1e-4:
                    sc = float(np.sum(freqs[mask] * fft[mask]) / sum_mag)
                    centroids.append(sc)

                # Spectral centroid is strongly affected by music, microphone
                # EQ and sibilance. Estimate F0 on short voiced frames and use
                # it as the primary cue instead of treating brightness as sex.
                frame_size = max(256, int(sr * 0.04))
                hop = max(128, frame_size // 2)
                min_lag = max(1, int(sr / 320.0))
                max_lag = min(frame_size - 2, int(sr / 70.0))
                normalized = data.astype(np.float32)
                normalized -= float(np.mean(normalized))
                peak = float(np.max(np.abs(normalized))) if len(normalized) else 0.0
                if peak > 1.0:
                    normalized /= peak
                for offset in range(0, max(0, len(normalized) - frame_size + 1), hop):
                    frame = normalized[offset:offset + frame_size]
                    if float(np.sqrt(np.mean(frame * frame))) < 0.015:
                        continue
                    frame = frame * np.hanning(frame_size)
                    corr = np.correlate(frame, frame, mode="full")[frame_size - 1:]
                    if corr[0] <= 1e-6 or max_lag <= min_lag:
                        continue
                    lag = min_lag + int(np.argmax(corr[min_lag:max_lag + 1]))
                    periodicity = float(corr[lag] / corr[0])
                    if periodicity >= 0.32:
                        pitches.append(float(sr / lag))

            if not centroids:
                return {
                    "gender": "unknown",
                    "confidence": 0.0,
                    "mean_centroid": 0.0,
                    "sample_count": 0,
                }

            mean_sc = float(np.median(centroids))
            sample_count = len(centroids)

            median_pitch = float(np.median(pitches)) if pitches else 0.0
            pitch_q25 = float(np.percentile(pitches, 25)) if pitches else 0.0
            pitch_q75 = float(np.percentile(pitches, 75)) if pitches else 0.0
            # Autocorrelation often locks onto the second harmonic of a male
            # voice, producing a misleading 200-240 Hz median.  Combine the
            # lower pitch quartile with spectral balance instead of trusting
            # one median value. This is especially important for short-drama
            # dialogue recorded through phone compression and background music.
            if len(pitches) < 5:
                gender, conf = "unknown", 0.0
            elif pitch_q25 <= 155.0 or (pitch_q25 < 205.0 and mean_sc < 970.0):
                gender = "male"
                conf = min(0.93, 0.68 + max(0.0, 205.0 - pitch_q25) / 180.0)
            elif median_pitch >= 235.0 or pitch_q25 >= 205.0 or (median_pitch >= 210.0 and mean_sc >= 1050.0):
                gender = "female"
                conf = min(0.95, 0.68 + max(0.0, pitch_q25 - 185.0) / 180.0)
            else:
                gender, conf = "unknown", 0.0

            # If sample count is small (< 3), penalize confidence
            if sample_count < 3:
                conf *= 0.85

            return {
                "gender": gender if conf >= 0.60 else "unknown",
                "confidence": round(float(conf), 2),
                "mean_centroid": round(mean_sc, 1),
                "median_pitch": round(median_pitch, 1),
                "pitch_q25": round(pitch_q25, 1),
                "pitch_q75": round(pitch_q75, 1),
                "sample_count": sample_count,
            }

    except Exception as exc:
        print(f"[Speaker Gender] Aggregation error: {exc}")
        return {
            "gender": "unknown",
            "confidence": 0.0,
            "mean_centroid": 0.0,
            "sample_count": 0,
        }
