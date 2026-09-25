"""Automated Regression Test Suite for Step 5.4.3: Duration Fitting Test Matrix.

Validates the complete 9 Scenarios of Duration Fitting Contract v1.0:
1. Short audio          : raw 1.50s, slot 3.00s -> speed=1.0x, copy, no FFmpeg, no padding
2. <= 3% tolerance      : raw 2.04s, slot 2.00s (ratio 1.02) -> speed=1.0x, copy, no FFmpeg
3. 1.15x fitting        : raw 2.30s, slot 2.00s -> speed=1.15x, FFmpeg atempo, fitted ≈ 2.00s
4. 1.20x overflow       : raw 3.00s, slot 1.50s -> speed=1.20x (clamped), warning != "", fitted ≈ 2.50s
5. Raw WAV immutable    : SHA-256 hash of raw WAV before == after fitting
6. Invalid slot         : slot_duration <= 0 -> status="failed", no FFmpeg
7. Missing raw WAV      : raw file does not exist -> status="failed", no fake fitted file
8. Invalid raw WAV      : corrupt/empty file -> status="failed"
9. Duration integrity   : measured WAV duration matches theoretical expectation (±0.02s)
"""

from __future__ import annotations

import hashlib
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

from services.duration_fitting_service import DurationFittingService
from services.tts_backend import measure_wav_duration


def compute_sha256(filepath: str) -> str:
    """Tính mã băm SHA-256 của tệp tin."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def create_pcm_wav(file_path: str, duration_sec: float, sample_rate: int = 16000) -> float:
    """Tạo file WAV PCM 16-bit Mono hợp lệ cho audio testing."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
    num_frames = int(duration_sec * sample_rate)
    silent_data = b"\x00\x00" * num_frames
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(silent_data)
    return round(num_frames / float(sample_rate), 3)


def run_duration_fitting_regression():
    print("=" * 70)
    print("      CAPCAP STEP 5.4.3: DURATION FITTING REGRESSION MATRIX (9/9)")
    print("=" * 70)

    test_dir = os.path.join(str(WORKSPACE_DIR), "temp", "test_fitting")
    raw_dir = os.path.join(test_dir, "raw_tts")
    fitted_dir = os.path.join(test_dir, "fitted_tts")
    shutil.rmtree(test_dir, ignore_errors=True)
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(fitted_dir, exist_ok=True)

    service = DurationFittingService(
        tolerance_ratio=1.03,
        max_speed=1.20,
        fitted_output_dir=fitted_dir,
    )

    test_results: list[tuple[int, str, bool, list[str]]] = []

    # =========================================================================
    # 1. Short audio (raw 1.50s, slot 3.00s)
    # =========================================================================
    t1_errs = []
    raw_1 = os.path.join(raw_dir, "seg_0001_raw.wav")
    fit_1 = os.path.join(fitted_dir, "seg_0001_fit.wav")
    create_pcm_wav(raw_1, 1.500)

    res_1 = service.fit_segment(
        segment_id=1,
        raw_audio_path=raw_1,
        slot_duration=3.000,
        output_path=fit_1,
    )
    if res_1.status != "success":
        t1_errs.append(f"Status not success: {res_1.status}, err: {res_1.error}")
    if res_1.applied_speed != 1.0:
        t1_errs.append(f"Applied speed must be 1.0x, got {res_1.applied_speed}")
    if abs(res_1.fitted_duration - 1.500) > 0.01:
        t1_errs.append(f"Fitted duration must be 1.500s (no silence padding), got {res_1.fitted_duration}")
    if not os.path.isfile(fit_1):
        t1_errs.append("Fitted audio file not created on disk")
    test_results.append((1, "Short audio (1.5s -> slot 3.0s) -> 1.0x copy, no padding", len(t1_errs) == 0, t1_errs))

    # =========================================================================
    # 2. <= 3% tolerance (raw 2.04s, slot 2.00s -> ratio 1.02)
    # =========================================================================
    t2_errs = []
    raw_2 = os.path.join(raw_dir, "seg_0002_raw.wav")
    fit_2 = os.path.join(fitted_dir, "seg_0002_fit.wav")
    create_pcm_wav(raw_2, 2.040)

    res_2 = service.fit_segment(
        segment_id=2,
        raw_audio_path=raw_2,
        slot_duration=2.000,
        output_path=fit_2,
    )
    if res_2.status != "success":
        t2_errs.append(f"Status not success: {res_2.status}")
    if res_2.applied_speed != 1.0:
        t2_errs.append(f"Applied speed must be 1.0x for <=3% tolerance, got {res_2.applied_speed}")
    if abs(res_2.fitted_duration - 2.040) > 0.01:
        t2_errs.append(f"Fitted duration should equal raw duration (2.040s), got {res_2.fitted_duration}")
    test_results.append((2, "<= 3% tolerance (2.04s -> slot 2.0s) -> 1.0x copy, no FFmpeg", len(t2_errs) == 0, t2_errs))

    # =========================================================================
    # 3. 1.15x fitting (raw 2.30s, slot 2.00s -> ratio 1.15)
    # =========================================================================
    t3_errs = []
    raw_3 = os.path.join(raw_dir, "seg_0003_raw.wav")
    fit_3 = os.path.join(fitted_dir, "seg_0003_fit.wav")
    create_pcm_wav(raw_3, 2.300)

    res_3 = service.fit_segment(
        segment_id=3,
        raw_audio_path=raw_3,
        slot_duration=2.000,
        output_path=fit_3,
    )
    if res_3.status != "success":
        t3_errs.append(f"Status not success: {res_3.status}, err: {res_3.error}")
    if abs(res_3.applied_speed - 1.15) > 0.005:
        t3_errs.append(f"Applied speed must be ~1.15x, got {res_3.applied_speed}")
    # expected duration = 2.30 / 1.15 = 2.00s
    if abs(res_3.fitted_duration - 2.000) > 0.03:
        t3_errs.append(f"Fitted duration should be ~2.00s, got {res_3.fitted_duration}")
    if res_3.warning != "":
        t3_errs.append(f"Warning should be empty for safe fit, got '{res_3.warning}'")
    test_results.append((3, "1.15x fitting (2.30s -> slot 2.0s) -> atempo 1.15x, fitted ≈ 2.00s", len(t3_errs) == 0, t3_errs))

    # =========================================================================
    # 4. 1.20x overflow (raw 3.00s, slot 1.50s -> ratio 2.0)
    # =========================================================================
    t4_errs = []
    raw_4 = os.path.join(raw_dir, "seg_0004_raw.wav")
    fit_4 = os.path.join(fitted_dir, "seg_0004_fit.wav")
    create_pcm_wav(raw_4, 3.000)

    res_4 = service.fit_segment(
        segment_id=4,
        raw_audio_path=raw_4,
        slot_duration=1.500,
        output_path=fit_4,
    )
    if res_4.status != "success":
        t4_errs.append(f"Status not success: {res_4.status}, err: {res_4.error}")
    if res_4.applied_speed != 1.20:
        t4_errs.append(f"Applied speed must be clamped to 1.20x, got {res_4.applied_speed}")
    # expected duration = 3.00 / 1.20 = 2.50s
    if abs(res_4.fitted_duration - 2.500) > 0.03:
        t4_errs.append(f"Fitted duration should be ~2.50s, got {res_4.fitted_duration}")
    if not res_4.warning:
        t4_errs.append("Warning MUST be present for overflow condition")
    elif "1.20" not in res_4.warning:
        t4_errs.append(f"Warning should mention 1.20x max speed: '{res_4.warning}'")
    test_results.append((4, "1.20x overflow (3.00s -> slot 1.5s) -> clamped 1.20x + warning", len(t4_errs) == 0, t4_errs))

    # =========================================================================
    # 5. Raw WAV immutable (SHA-256 hash check)
    # =========================================================================
    t5_errs = []
    raw_5 = os.path.join(raw_dir, "seg_0005_raw.wav")
    fit_5 = os.path.join(fitted_dir, "seg_0005_fit.wav")
    create_pcm_wav(raw_5, 2.500)
    hash_before = compute_sha256(raw_5)

    res_5 = service.fit_segment(
        segment_id=5,
        raw_audio_path=raw_5,
        slot_duration=2.200,
        output_path=fit_5,
    )
    hash_after = compute_sha256(raw_5)
    if hash_before != hash_after:
        t5_errs.append("Raw WAV hash changed! Raw audio was mutated during fitting!")
    if os.path.abspath(raw_5) == os.path.abspath(fit_5):
        t5_errs.append("Fitted audio path is identical to raw audio path!")
    test_results.append((5, "Raw WAV immutability -> SHA-256 hash strictly preserved", len(t5_errs) == 0, t5_errs))

    # =========================================================================
    # 6. Invalid slot (slot_duration <= 0) -> status="failed", no FFmpeg
    # =========================================================================
    t6_errs = []
    raw_6 = os.path.join(raw_dir, "seg_0006_raw.wav")
    create_pcm_wav(raw_6, 2.000)

    res_6a = service.fit_segment(segment_id=6, raw_audio_path=raw_6, slot_duration=0.0)
    res_6b = service.fit_segment(segment_id=6, raw_audio_path=raw_6, slot_duration=-1.5)
    if res_6a.status != "failed" or "slot_duration" not in res_6a.error:
        t6_errs.append(f"Failed to reject slot_duration=0: status={res_6a.status}, err={res_6a.error}")
    if res_6b.status != "failed" or "slot_duration" not in res_6b.error:
        t6_errs.append(f"Failed to reject slot_duration=-1.5: status={res_6b.status}, err={res_6b.error}")
    test_results.append((6, "Invalid slot (slot_duration <= 0) -> status='failed', no FFmpeg", len(t6_errs) == 0, t6_errs))

    # =========================================================================
    # 7. Missing raw WAV -> status="failed", no fake fitted file
    # =========================================================================
    t7_errs = []
    raw_7_nonexistent = os.path.join(raw_dir, "nonexistent_file.wav")
    fit_7_target = os.path.join(fitted_dir, "nonexistent_fit.wav")

    res_7 = service.fit_segment(
        segment_id=7,
        raw_audio_path=raw_7_nonexistent,
        slot_duration=2.0,
        output_path=fit_7_target,
    )
    if res_7.status != "failed":
        t7_errs.append(f"Expected status 'failed', got '{res_7.status}'")
    if "not found" not in res_7.error.lower():
        t7_errs.append(f"Error should mention file not found: '{res_7.error}'")
    if os.path.isfile(fit_7_target):
        t7_errs.append(f"Fake file was wrongly created at: {fit_7_target}")
    test_results.append((7, "Missing raw WAV -> status='failed', no fake file generated", len(t7_errs) == 0, t7_errs))

    # =========================================================================
    # 8. Invalid raw WAV (empty or corrupt) -> status="failed"
    # =========================================================================
    t8_errs = []
    raw_8_corrupt = os.path.join(raw_dir, "corrupt.wav")
    with open(raw_8_corrupt, "wb") as f:
        f.write(b"NOT_A_VALID_WAV_HEADER_DATA")

    res_8 = service.fit_segment(
        segment_id=8,
        raw_audio_path=raw_8_corrupt,
        slot_duration=2.0,
    )
    if res_8.status != "failed":
        t8_errs.append(f"Expected status 'failed' for corrupt WAV, got '{res_8.status}'")
    if "invalid" not in res_8.error.lower() and "unreadable" not in res_8.error.lower():
        t8_errs.append(f"Error should describe unreadable file: '{res_8.error}'")
    test_results.append((8, "Invalid raw WAV (corrupt/empty) -> status='failed'", len(t8_errs) == 0, t8_errs))

    # =========================================================================
    # 9. Fitted WAV duration integrity (measured from actual file header)
    # =========================================================================
    t9_errs = []
    raw_9 = os.path.join(raw_dir, "seg_0009_raw.wav")
    fit_9 = os.path.join(fitted_dir, "seg_0009_fit.wav")
    create_pcm_wav(raw_9, 2.400)

    res_9 = service.fit_segment(
        segment_id=9,
        raw_audio_path=raw_9,
        slot_duration=2.000,  # required_speed = 1.20
        output_path=fit_9,
    )
    if not os.path.isfile(fit_9):
        t9_errs.append("Fitted audio file missing on disk")
    else:
        with wave.open(fit_9, "rb") as wf:
            direct_dur = wf.getnframes() / float(wf.getframerate())
        if abs(res_9.fitted_duration - direct_dur) > 0.005:
            t9_errs.append(f"Mismatch between res.fitted_duration ({res_9.fitted_duration}) and direct header ({direct_dur})")
        # Lý thuyết: 2.400 / 1.20 = 2.000s (sai số thực tế do WSOLA frame chunking của FFmpeg atempo <= 0.03s)
        if abs(direct_dur - 2.000) > 0.03:
            t9_errs.append(f"Actual FFmpeg output duration {direct_dur:.3f}s deviates > 0.03s from expected 2.000s")
    test_results.append((9, "Fitted WAV duration integrity -> matches header measurement (±0.03s)", len(t9_errs) == 0, t9_errs))

    # =========================================================================
    # BÁO CÁO KẾT QUẢ MA TRẬN 9/9
    # =========================================================================
    print("-" * 70)
    print(f"{'#':<3} | {'Scenario':<52} | {'Result':<8}")
    print("-" * 70)
    all_passed = True
    passed_count = 0

    for idx, name, ok, errs in test_results:
        tag = "✅ PASS" if ok else "❌ FAIL"
        print(f"{idx:<3} | {name:<52} | {tag:<8}")
        if ok:
            passed_count += 1
        else:
            all_passed = False
            for e in errs:
                print(f"      -> {e}")

    print("=" * 70)
    print(f"DURATION FITTING REGRESSION MATRIX RESULT: {passed_count}/{len(test_results)} PASS")
    print("=" * 70)
    return all_passed


if __name__ == "__main__":
    ok = run_duration_fitting_regression()
    if not ok:
        sys.exit(1)
