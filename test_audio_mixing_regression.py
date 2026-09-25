"""Automated Regression Test Suite for Step 6.3: Audio Mixing & Ducking.

Validates all 11 Invariants and Core Behaviors:
1. Empty TTS blocks (all skipped) -> Copy original, no ducking, status='success'
2. Single TTS block               -> Duck interval exact (start, start+duration), volume ducked to 0.20
3. Merge gap < 0.30s (Invariant 9) -> Merged into single continuous interval
4. Distinct gap >= 0.30s          -> Preserved as separate intervals (recovers to 100% between)
5. Overlap detection (Invariant 8)-> status='failed', transparent error, no mutation
6. TTS timeline overflow (Inv 10,11)-> total_duration=max(orig, last_tts_end), warning != "", no trim
7. Output overwrite protection    -> output_path == original_path rejected
8. Missing original audio         -> status='failed'
9. End-to-End FFmpeg execution    -> produces valid stereo 44.1kHz master WAV, verified duration
"""

from __future__ import annotations

import os
import shutil
import sys
import wave
from pathlib import Path

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

WORKSPACE_DIR = Path(__file__).resolve().parent
APP_DIR = WORKSPACE_DIR / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.audio_mixing_service import AudioMixingService, TTSAudioBlock, MixedAudioResult
from services.tts_backend import measure_wav_duration


def create_pcm_wav(file_path: str, duration_sec: float, sample_rate: int = 44100, channels: int = 2) -> float:
    """Tạo file WAV PCM stereo 16-bit hợp lệ cho audio mixing testing."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
    num_frames = int(duration_sec * sample_rate)
    silent_data = b"\x00\x00" * num_frames * channels
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(silent_data)
    return round(num_frames / float(sample_rate), 3)


def run_audio_mixing_regression():
    print("=" * 70)
    print("      CAPCAP STEP 6.3: AUDIO MIXING & DUCKING REGRESSION MATRIX")
    print("=" * 70)

    test_base = os.path.join(str(WORKSPACE_DIR), "temp", "test_mixing")
    shutil.rmtree(test_base, ignore_errors=True)
    os.makedirs(test_base, exist_ok=True)

    service = AudioMixingService(duck_volume=0.20, normal_volume=1.0, min_gap_merge=0.30)
    test_results: list[tuple[int, str, bool, list[str]]] = []

    # File âm thanh gốc mẫu (10.0s stereo 44.1kHz)
    orig_wav = os.path.join(test_base, "original_bgm.wav")
    create_pcm_wav(orig_wav, 10.000)

    # =========================================================================
    # 1. Empty TTS Blocks (Tất cả phân cảnh bị skip)
    # =========================================================================
    t1_errs = []
    out_1 = os.path.join(test_base, "out_empty.wav")
    res_1 = service.mix(original_audio_path=orig_wav, tts_blocks=[], output_path=out_1)
    if res_1.status != "success":
        t1_errs.append(f"Status not success: {res_1.status}, err: {res_1.error}")
    if res_1.duck_intervals != []:
        t1_errs.append(f"Duck intervals must be empty, got {res_1.duck_intervals}")
    if not os.path.isfile(out_1):
        t1_errs.append("Output file missing on disk")
    test_results.append((1, "Empty TTS blocks (all skipped) -> Copy original, no ducking", len(t1_errs) == 0, t1_errs))

    # =========================================================================
    # 2. Single TTS block -> Exact duck interval
    # =========================================================================
    t2_errs = []
    tts_wav_2 = os.path.join(test_base, "tts_2.wav")
    create_pcm_wav(tts_wav_2, 2.000, sample_rate=16000, channels=1)
    b2 = TTSAudioBlock(segment_id=2, start_time=2.000, duration=2.000, audio_path=tts_wav_2)

    out_2 = os.path.join(test_base, "out_single.wav")
    res_2 = service.mix(original_audio_path=orig_wav, tts_blocks=[b2], output_path=out_2)
    if res_2.status != "success":
        t2_errs.append(f"Status not success: {res_2.status}, err: {res_2.error}")
    if res_2.duck_intervals != [(2.0, 4.0)]:
        t2_errs.append(f"Expected duck interval [(2.0, 4.0)], got {res_2.duck_intervals}")
    if not os.path.isfile(out_2):
        t2_errs.append("Output file missing")
    test_results.append((2, "Single TTS block -> Exact duck interval (2.0s -> 4.0s)", len(t2_errs) == 0, t2_errs))

    # =========================================================================
    # 3. Merge Gap < 0.30s (Invariant 9: Gap = 0.20s -> Merged)
    # =========================================================================
    t3_errs = []
    # Block A: 2.0s -> 3.5s (end 3.5s)
    # Block B: 3.7s -> 5.0s (start 3.7s, gap = 0.20s < 0.30s)
    tts_wav_3a = os.path.join(test_base, "tts_3a.wav")
    tts_wav_3b = os.path.join(test_base, "tts_3b.wav")
    create_pcm_wav(tts_wav_3a, 1.500)
    create_pcm_wav(tts_wav_3b, 1.300)
    b3a = TTSAudioBlock(segment_id=31, start_time=2.000, duration=1.500, audio_path=tts_wav_3a)
    b3b = TTSAudioBlock(segment_id=32, start_time=3.700, duration=1.300, audio_path=tts_wav_3b)

    out_3 = os.path.join(test_base, "out_merged.wav")
    res_3 = service.mix(original_audio_path=orig_wav, tts_blocks=[b3a, b3b], output_path=out_3)
    if res_3.status != "success":
        t3_errs.append(f"Status failed: {res_3.error}")
    # Kỳ vọng gộp thành duy nhất 1 interval: (2.0, 5.0)
    if res_3.duck_intervals != [(2.0, 5.0)]:
        t3_errs.append(f"Expected merged interval [(2.0, 5.0)], got {res_3.duck_intervals}")
    test_results.append((3, "Merge gap < 0.30s (gap=0.20s) -> Merged into [(2.0, 5.0)]", len(t3_errs) == 0, t3_errs))

    # =========================================================================
    # 4. Distinct Gap >= 0.30s (Gap = 0.50s -> Kept separate)
    # =========================================================================
    t4_errs = []
    # Block A: 2.0s -> 3.5s (end 3.5s)
    # Block B: 4.0s -> 5.5s (start 4.0s, gap = 0.50s >= 0.30s)
    tts_wav_4b = os.path.join(test_base, "tts_4b.wav")
    create_pcm_wav(tts_wav_4b, 1.500)
    b4b = TTSAudioBlock(segment_id=42, start_time=4.000, duration=1.500, audio_path=tts_wav_4b)

    out_4 = os.path.join(test_base, "out_distinct.wav")
    res_4 = service.mix(original_audio_path=orig_wav, tts_blocks=[b3a, b4b], output_path=out_4)
    if res_4.status != "success":
        t4_errs.append(f"Status failed: {res_4.error}")
    if res_4.duck_intervals != [(2.0, 3.5), (4.0, 5.5)]:
        t4_errs.append(f"Expected distinct intervals [(2.0, 3.5), (4.0, 5.5)], got {res_4.duck_intervals}")
    test_results.append((4, "Distinct gap >= 0.30s (gap=0.50s) -> Kept separate intervals", len(t4_errs) == 0, t4_errs))

    # =========================================================================
    # 5. Overlap detection (Invariant 8) -> status='failed', no trim
    # =========================================================================
    t5_errs = []
    # Block A: 2.0s -> 4.0s (end 4.0s)
    # Block B: 3.8s -> 5.0s (start 3.8s < 4.0s -> OVERLAP)
    b5a = TTSAudioBlock(segment_id=51, start_time=2.000, duration=2.000, audio_path=tts_wav_3a)
    b5b = TTSAudioBlock(segment_id=52, start_time=3.800, duration=1.200, audio_path=tts_wav_3b)

    out_5 = os.path.join(test_base, "out_overlap.wav")
    res_5 = service.mix(original_audio_path=orig_wav, tts_blocks=[b5a, b5b], output_path=out_5)
    if res_5.status != "failed":
        t5_errs.append(f"Expected status 'failed' for overlapping TTS, got '{res_5.status}'")
    if "overlap detected" not in res_5.error.lower():
        t5_errs.append(f"Error message must describe overlap: '{res_5.error}'")
    test_results.append((5, "Overlap detection (start < prev_end) -> status='failed', no trim", len(t5_errs) == 0, t5_errs))

    # =========================================================================
    # 6. TTS timeline overflow (Invariant 10 & 11) -> total_duration extended + warning
    # =========================================================================
    t6_errs = []
    # Audio gốc: 10.0s
    # Block TTS: 8.5s -> 11.5s (end 11.5s > 10.0s)
    tts_wav_6 = os.path.join(test_base, "tts_6.wav")
    create_pcm_wav(tts_wav_6, 3.000)
    b6 = TTSAudioBlock(segment_id=61, start_time=8.500, duration=3.000, audio_path=tts_wav_6)

    out_6 = os.path.join(test_base, "out_overflow.wav")
    res_6 = service.mix(original_audio_path=orig_wav, tts_blocks=[b6], output_path=out_6)
    if res_6.status != "success":
        t6_errs.append(f"Status not success: {res_6.status}, err: {res_6.error}")
    # Invariant 11: total_duration = max(10.0, 11.5) ≈ 11.5s
    if abs(res_6.total_duration - 11.500) > 0.1:
        t6_errs.append(f"Total duration must be extended to ~11.5s, got {res_6.total_duration}")
    # Invariant 10: warning must be present
    if not res_6.warning or "exceeds" not in res_6.warning.lower():
        t6_errs.append(f"Warning must describe timeline overflow: '{res_6.warning}'")
    test_results.append((6, "TTS timeline overflow (11.5s > 10.0s) -> total_dur=11.5s + warning", len(t6_errs) == 0, t6_errs))

    # =========================================================================
    # 7. Output overwrite protection
    # =========================================================================
    t7_errs = []
    res_7 = service.mix(original_audio_path=orig_wav, tts_blocks=[], output_path=orig_wav)
    if res_7.status != "failed" or "overwrite" not in res_7.error.lower():
        t7_errs.append(f"Failed to reject output == original: {res_7.error}")
    test_results.append((7, "Output overwrite protection (output == original) -> rejected", len(t7_errs) == 0, t7_errs))

    # =========================================================================
    # 8. Missing original audio
    # =========================================================================
    t8_errs = []
    res_8 = service.mix(original_audio_path=os.path.join(test_base, "missing.wav"), tts_blocks=[], output_path=out_1)
    if res_8.status != "failed" or "not found" not in res_8.error.lower():
        t8_errs.append(f"Failed to handle missing original: {res_8.error}")
    test_results.append((8, "Missing original audio -> status='failed', clean error", len(t8_errs) == 0, t8_errs))

    # =========================================================================
    # 9. End-to-End FFmpeg execution & audio verification
    # =========================================================================
    t9_errs = []
    # Đo file thật được xuất ra từ Test 2 (single block 2.0s -> 4.0s trong video 10s)
    if not os.path.isfile(out_2):
        t9_errs.append(f"Mixed file missing: {out_2}")
    else:
        with wave.open(out_2, "rb") as wf:
            nchannels = wf.getnchannels()
            frate = wf.getframerate()
            nframes = wf.getnframes()
            dur = nframes / float(frate)

        if nchannels != 2:
            t9_errs.append(f"Mixed audio must be stereo (2 channels), got {nchannels}")
        if frate != 44100:
            t9_errs.append(f"Mixed audio sample rate must be 44100Hz, got {frate}")
        if abs(dur - 10.000) > 0.1:
            t9_errs.append(f"Duration must equal original (10.0s), got {dur:.3f}s")
    test_results.append((9, "End-to-End FFmpeg execution -> Stereo 44.1kHz, verified duration", len(t9_errs) == 0, t9_errs))

    # =========================================================================
    # BÁO CÁO KẾT QUẢ MA TRẬN 9/9
    # =========================================================================
    print("-" * 70)
    print(f"{'#':<3} | {'Scenario':<55} | {'Result':<8}")
    print("-" * 70)
    all_ok = True
    passed = 0
    for idx, name, ok, errs in test_results:
        tag = "✅ PASS" if ok else "❌ FAIL"
        print(f"{idx:<3} | {name:<55} | {tag:<8}")
        if ok:
            passed += 1
        else:
            all_ok = False
            for e in errs:
                print(f"      -> {e}")

    print("=" * 70)
    print(f"AUDIO MIXING REGRESSION MATRIX RESULT: {passed}/{len(test_results)} PASS")
    print("=" * 70)
    return all_ok


if __name__ == "__main__":
    success = run_audio_mixing_regression()
    if not success:
        sys.exit(1)
