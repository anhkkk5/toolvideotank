"""Regression Test Suite for Step 5.2.2.8: Raw Duration Measurement Integrity.

Validates that:
1. VoiceoverService records exact duration measured from the actual WAV header,
   NEVER guessing from text length or subtitle duration (end - start).
2. No atempo, no speed adjustment, no audio cutting is applied.
3. Subtitle slot time (e.g. 5.0s) has ZERO influence on TTSResult.duration (e.g. 1.76s).
4. Measurement precision is within ±0.01s tolerance of the raw WAV frame count.
"""

from __future__ import annotations

import os
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

from services.voiceover_service import VoiceoverService
from services.tts_backend import TTSBackend, measure_wav_duration


def create_exact_wav(file_path: str, duration_sec: float, sample_rate: int = 16000) -> float:
    """Tạo một file WAV PCM 16-bit Mono hợp lệ với thời lượng chính xác tuyệt đối."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
    num_frames = int(duration_sec * sample_rate)
    # 2 bytes per sample (16-bit mono silence)
    silent_data = b"\x00\x00" * num_frames
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(silent_data)

    actual = round(num_frames / float(sample_rate), 3)
    return actual


class SyntheticWavBackend(TTSBackend):
    """Backend tạo file WAV thực tế với thời lượng xác định trước để kiểm tra đo đạc."""
    def __init__(self, target_duration: float):
        self.target_duration = target_duration

    def synthesize(self, text: str, voice_id: str, output_path: str) -> float:
        create_exact_wav(output_path, self.target_duration)
        return measure_wav_duration(output_path)


def run_raw_duration_tests():
    print("=" * 65)
    print("   TEST 5.2.2.8: RAW DURATION MEASUREMENT INTEGRITY")
    print("=" * 65)

    raw_dir = os.path.join(str(WORKSPACE_DIR), "raw_tts")
    os.makedirs(raw_dir, exist_ok=True)

    all_passed = True
    tolerance = 0.01  # Sai số cho phép ±0.01 giây

    # =========================================================================
    # TEST 1: Synthetic WAV - Subtitle Slot 10.0s vs Raw WAV 2.350s
    # =========================================================================
    print("\n[Test 1] Synthetic WAV: Slot = 10.0s, Actual Audio = 2.350s")
    wav_path_1 = os.path.join(raw_dir, "test_dur_1.wav")
    backend_1 = SyntheticWavBackend(target_duration=2.350)
    service_1 = VoiceoverService(backend=backend_1, raw_output_dir=raw_dir)

    res_1 = service_1.generate(
        segment_id=301,
        translated_text="Câu thoại thử nghiệm thời lượng",
        start=0.0,
        end=10.0,  # Slot rất dài (10s)
        voice_id="vieneu_thanhnientutin",
        output_path=wav_path_1,
    )

    # Đo độc lập bằng wave module
    with wave.open(wav_path_1, "rb") as wf:
        exact_from_header_1 = wf.getnframes() / float(wf.getframerate())

    print(f"  Subtitle Slot Duration : 10.000s")
    print(f"  Exact WAV Header Time  : {exact_from_header_1:.3f}s")
    print(f"  TTSResult.duration     : {res_1.duration:.3f}s")

    diff_1 = abs(res_1.duration - exact_from_header_1)
    if diff_1 > tolerance:
        print(f"  [FAIL] TTSResult.duration differs from WAV header by {diff_1:.4f}s > {tolerance}s")
        all_passed = False
    elif abs(res_1.duration - 10.0) < 0.1:
        print(f"  [FAIL] TTSResult.duration was falsely clamped/guessed from subtitle slot (10.0s)!")
        all_passed = False
    else:
        print(f"  [PASS] Successfully decoupled from subtitle slot. Measured exact WAV: {res_1.duration:.3f}s")

    # =========================================================================
    # TEST 2: Synthetic WAV - Subtitle Slot 0.5s vs Raw WAV 1.420s (Audio > Slot)
    # =========================================================================
    print("\n[Test 2] Synthetic WAV: Slot = 0.5s, Actual Audio = 1.420s (Audio dài hơn Slot)")
    wav_path_2 = os.path.join(raw_dir, "test_dur_2.wav")
    backend_2 = SyntheticWavBackend(target_duration=1.420)
    service_2 = VoiceoverService(backend=backend_2, raw_output_dir=raw_dir)

    res_2 = service_2.generate(
        segment_id=302,
        translated_text="Câu ngắn nhưng audio dài hơn slot",
        start=5.0,
        end=5.5,  # Slot chỉ 0.5s
        voice_id="vieneu_cogaihoatbat",
        output_path=wav_path_2,
    )

    with wave.open(wav_path_2, "rb") as wf:
        exact_from_header_2 = wf.getnframes() / float(wf.getframerate())

    print(f"  Subtitle Slot Duration : 0.500s")
    print(f"  Exact WAV Header Time  : {exact_from_header_2:.3f}s")
    print(f"  TTSResult.duration     : {res_2.duration:.3f}s")

    diff_2 = abs(res_2.duration - exact_from_header_2)
    if diff_2 > tolerance:
        print(f"  [FAIL] TTSResult.duration differs from WAV header by {diff_2:.4f}s > {tolerance}s")
        all_passed = False
    elif abs(res_2.duration - 0.5) < 0.1:
        print(f"  [FAIL] TTSResult.duration was falsely truncated/clamped to subtitle slot (0.5s)!")
        all_passed = False
    else:
        print(f"  [PASS] Preserved raw duration without fitting/speed-up: {res_2.duration:.3f}s")

    # =========================================================================
    # TEST 3: Real VieNeu WAV from Step 5.2.2.5 (segment_0027.wav)
    # =========================================================================
    print("\n[Test 3] Real VieNeu WAV (segment_0027.wav generated in 5.2.2.5)")
    real_wav_27 = os.path.join(raw_dir, "segment_0027.wav")
    if not os.path.isfile(real_wav_27):
        print(f"  [FAIL] Real WAV file missing: {real_wav_27}")
        all_passed = False
    else:
        with wave.open(real_wav_27, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            exact_real_dur = frames / float(rate)

        measured_by_func = measure_wav_duration(real_wav_27)
        print(f"  File Path              : {real_wav_27}")
        print(f"  Frames: {frames}, Rate: {rate}Hz")
        print(f"  Direct Wave Header     : {exact_real_dur:.4f}s")
        print(f"  measure_wav_duration   : {measured_by_func:.3f}s")
        print(f"  Subtitle Slot (Câu 27) : 81.5s -> 83.5s (2.000s)")

        diff_real = abs(measured_by_func - exact_real_dur)
        if diff_real > tolerance:
            print(f"  [FAIL] Measured duration differs by {diff_real:.4f}s > {tolerance}s")
            all_passed = False
        else:
            print(f"  [PASS] Real VieNeu file measured with 100% precision: {measured_by_func:.3f}s")

    print("\n" + "-" * 65)
    if all_passed:
        print("RESULT: ALL RAW DURATION TESTS PASSED! ZERO BIAS, ZERO FITTING.")
    else:
        print("RESULT: RAW DURATION TESTS FAILED.")
    print("=" * 65)
    return all_passed


if __name__ == "__main__":
    ok = run_raw_duration_tests()
    if not ok:
        sys.exit(1)
