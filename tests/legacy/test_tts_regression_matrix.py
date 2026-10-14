"""Automated Regression Test Suite for Step 5.3: TTS Regression Test Matrix.

Validates the full End-to-End pipeline:
SubtitleSegment -> VoiceMappingService -> VoiceoverService -> TTSBackend -> Raw WAV -> TTSResult

Matrix of 8 Scenarios:
1. Male Anchor     : final_gender=male   -> vieneu_thanhnientutin + success
2. Female Anchor   : final_gender=female -> vieneu_cogaihoatbat + success
3. Monologue BGM   : raw=female, final=male -> vieneu_thanhnientutin + success (Contract Isolation)
4. Rapid Switch    : Seg 18 (Female) -> Seg 19 (Male) rapid boundary protection
5. OCR Noise       : is_noise=True       -> skipped + 0 backend calls
6. Non-speech      : skip_tts=True       -> skipped + 0 backend calls
7. Unknown         : final_gender=unknown -> skipped + 0 backend calls
8. Raw Duration    : exact WAV header duration matches TTSResult.duration (±0.01s tolerance)
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

from models.subtitle_segment import SubtitleSegment
from services.voice_mapping_service import VoiceMappingService
from services.voiceover_service import VoiceoverService
from services.tts_backend import TTSBackend, measure_wav_duration


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


class MatrixTrackingBackend(TTSBackend):
    """Backend kiểm thử ma trận: Sinh file WAV thật và đếm chính xác số lần gọi."""

    SUPPORTED_VOICES = {"vieneu_thanhnientutin", "vieneu_cogaihoatbat"}

    def __init__(self):
        self.call_history: list[tuple[str, str, str]] = []
        # Độ dài audio giả lập cho từng câu để kiểm tra duration độc lập
        self.duration_table: dict[str, float] = {
            "vieneu_thanhnientutin": 1.850,
            "vieneu_cogaihoatbat": 1.620,
        }

    def synthesize(self, text: str, voice_id: str, output_path: str) -> float:
        self.call_history.append((text, voice_id, output_path))
        if voice_id not in self.SUPPORTED_VOICES:
            raise ValueError(f"Invalid or unsupported VieNeu voice_id: '{voice_id}'")

        dur = self.duration_table.get(voice_id, 1.500)
        create_pcm_wav(output_path, dur)
        return measure_wav_duration(output_path)


def run_matrix_tests() -> bool:
    print("=" * 70)
    print("           CAPCAP STEP 5.3: TTS REGRESSION TEST MATRIX")
    print("=" * 70)

    raw_dir = os.path.join(str(WORKSPACE_DIR), "raw_tts")
    os.makedirs(raw_dir, exist_ok=True)

    backend = MatrixTrackingBackend()
    voice_mapper = VoiceMappingService()
    service = VoiceoverService(backend=backend, raw_output_dir=raw_dir)

    test_results: list[tuple[int, str, bool, list[str]]] = []

    # =========================================================================
    # 1. Male Anchor
    # =========================================================================
    t1_errs = []
    seg_1 = SubtitleSegment(
        id=1,
        start=1.0,
        end=4.0,
        text="我是一个自信的青年",
        translated_text="Tôi là một chàng trai tự tin.",
        raw_gender="male",
        final_gender="male",
        final_decision_confidence=0.985,
    )
    res_1 = service.process_segment(seg_1, voice_mapping_service=voice_mapper)
    if res_1.status != "success":
        t1_errs.append(f"Expected status 'success', got '{res_1.status}'")
    if res_1.voice_id != "vieneu_thanhnientutin":
        t1_errs.append(f"Expected voice 'vieneu_thanhnientutin', got '{res_1.voice_id}'")
    if not os.path.isfile(res_1.audio_path):
        t1_errs.append(f"Audio file missing at {res_1.audio_path}")
    if res_1.duration <= 0:
        t1_errs.append(f"Invalid duration: {res_1.duration}")
    test_results.append((1, "Male Anchor -> vienue_thanhnientutin + success", len(t1_errs) == 0, t1_errs))

    # =========================================================================
    # 2. Female Anchor
    # =========================================================================
    t2_errs = []
    seg_2 = SubtitleSegment(
        id=2,
        start=5.0,
        end=7.5,
        text="你好啊，很高兴见到你",
        translated_text="Chào bạn, rất vui được gặp bạn.",
        raw_gender="female",
        final_gender="female",
        final_decision_confidence=0.970,
    )
    res_2 = service.process_segment(seg_2, voice_mapping_service=voice_mapper)
    if res_2.status != "success":
        t2_errs.append(f"Expected status 'success', got '{res_2.status}'")
    if res_2.voice_id != "vieneu_cogaihoatbat":
        t2_errs.append(f"Expected voice 'vieneu_cogaihoatbat', got '{res_2.voice_id}'")
    if not os.path.isfile(res_2.audio_path):
        t2_errs.append(f"Audio file missing at {res_2.audio_path}")
    if res_2.duration <= 0:
        t2_errs.append(f"Invalid duration: {res_2.duration}")
    test_results.append((2, "Female Anchor -> vieneu_cogaihoatbat + success", len(t2_errs) == 0, t2_errs))

    # =========================================================================
    # 3. Monologue BGM (Câu 27: raw female 99.2%, final male 90.6%)
    # =========================================================================
    t3_errs = []
    seg_3 = SubtitleSegment(
        id=27,
        start=81.5,
        end=83.5,
        text="直到",
        translated_text="Cho đến khi tôi hiểu ra mọi chuyện.",
        raw_gender="female",
        raw_gender_confidence=0.992,
        final_gender="male",
        final_decision_confidence=0.906,
        decision_mode="contextual_smoothing",
    )
    res_3 = service.process_segment(seg_3, voice_mapping_service=voice_mapper)
    if res_3.status != "success":
        t3_errs.append(f"Expected status 'success', got '{res_3.status}'")
    if res_3.voice_id != "vieneu_thanhnientutin":
        t3_errs.append(f"Isolation broken! Expected 'vieneu_thanhnientutin', got '{res_3.voice_id}'")
    if backend.call_history[-1][1] != "vieneu_thanhnientutin":
        t3_errs.append(f"Backend received wrong voice: '{backend.call_history[-1][1]}'")
    test_results.append((3, "Monologue BGM (raw female -> final male) -> vieneu_thanhnientutin", len(t3_errs) == 0, t3_errs))

    # =========================================================================
    # 4. Rapid Switch (Câu 18 Female -> Câu 19 Male, gap 0.0s)
    # =========================================================================
    t4_errs = []
    seg_18 = SubtitleSegment(
        id=18,
        start=45.0,
        end=46.5,
        text="快点离开这里！",
        translated_text="Mau rời khỏi đây đi!",
        raw_gender="female",
        final_gender="female",
        final_decision_confidence=0.999,
    )
    seg_19 = SubtitleSegment(
        id=19,
        start=46.5,
        end=48.0,
        text="我知道了！",
        translated_text="Tôi biết rồi!",
        raw_gender="male",
        final_gender="male",
        final_decision_confidence=0.999,
    )
    res_18 = service.process_segment(seg_18, voice_mapping_service=voice_mapper)
    res_19 = service.process_segment(seg_19, voice_mapping_service=voice_mapper)

    if res_18.voice_id != "vieneu_cogaihoatbat":
        t4_errs.append(f"Seg 18 must be female, got {res_18.voice_id}")
    if res_19.voice_id != "vieneu_thanhnientutin":
        t4_errs.append(f"Seg 19 must be male, got {res_19.voice_id}")
    if res_18.status != "success" or res_19.status != "success":
        t4_errs.append(f"Rapid switch segments failed: 18={res_18.status}, 19={res_19.status}")
    test_results.append((4, "Rapid Switch (Female 18 -> Male 19) -> Separate distinct voices", len(t4_errs) == 0, t4_errs))

    # =========================================================================
    # 5. OCR Noise (is_noise=True) -> status=skipped + 0 backend calls
    # =========================================================================
    t5_errs = []
    calls_before_5 = len(backend.call_history)
    seg_5 = SubtitleSegment(
        id=5,
        start=0.0,
        end=2.0,
        text="本故事纯属虚构",
        translated_text="Kịch bản chỉ là hư cấu",
        is_noise=True,
        final_gender="male",
    )
    res_5 = service.process_segment(seg_5, voice_mapping_service=voice_mapper)
    calls_delta_5 = len(backend.call_history) - calls_before_5
    if res_5.status != "skipped":
        t5_errs.append(f"Expected status 'skipped', got '{res_5.status}'")
    if calls_delta_5 != 0:
        t5_errs.append(f"Backend was invoked {calls_delta_5} times for noise segment!")
    test_results.append((5, "OCR Noise (is_noise=True) -> skipped + 0 backend calls", len(t5_errs) == 0, t5_errs))

    # =========================================================================
    # 6. Non-speech (skip_tts=True) -> status=skipped + 0 backend calls
    # =========================================================================
    t6_errs = []
    calls_before_6 = len(backend.call_history)
    seg_6 = SubtitleSegment(
        id=6,
        start=10.0,
        end=14.0,
        text="♪ 背景音乐 ♪",
        translated_text="[Nhạc nền du dương]",
        skip_tts=True,
        final_gender="female",
    )
    res_6 = service.process_segment(seg_6, voice_mapping_service=voice_mapper)
    calls_delta_6 = len(backend.call_history) - calls_before_6
    if res_6.status != "skipped":
        t6_errs.append(f"Expected status 'skipped', got '{res_6.status}'")
    if calls_delta_6 != 0:
        t6_errs.append(f"Backend was invoked {calls_delta_6} times for non-speech segment!")
    test_results.append((6, "Non-speech (skip_tts=True) -> skipped + 0 backend calls", len(t6_errs) == 0, t6_errs))

    # =========================================================================
    # 7. Unknown (final_gender=unknown) -> skipped + 0 backend calls
    # =========================================================================
    t7_errs = []
    calls_before_7 = len(backend.call_history)
    seg_7 = SubtitleSegment(
        id=7,
        start=20.0,
        end=22.0,
        text="有人在那里吗？",
        translated_text="Có ai ở đó không?",
        raw_gender="unknown",
        final_gender="unknown",
    )
    res_7 = service.process_segment(seg_7, voice_mapping_service=voice_mapper)
    calls_delta_7 = len(backend.call_history) - calls_before_7
    if res_7.status != "skipped":
        t7_errs.append(f"Expected status 'skipped', got '{res_7.status}'")
    if calls_delta_7 != 0:
        t7_errs.append(f"Backend was invoked {calls_delta_7} times for unknown gender segment!")
    test_results.append((7, "Unknown (final_gender=unknown) -> skipped + 0 backend calls", len(t7_errs) == 0, t7_errs))

    # =========================================================================
    # 8. Raw Duration Integrity (tolerance ±0.01s, no fitting, no atempo)
    # =========================================================================
    t8_errs = []
    tolerance = 0.01

    # Kiểm tra trên seg_1 (Slot = 3.0s, Audio thực = 1.850s)
    with wave.open(res_1.audio_path, "rb") as wf:
        actual_wav_dur_1 = wf.getnframes() / float(wf.getframerate())

    diff_1 = abs(res_1.duration - actual_wav_dur_1)
    if diff_1 > tolerance:
        t8_errs.append(f"Seg 1 duration mismatch: reported={res_1.duration:.4f}s, wav={actual_wav_dur_1:.4f}s")
    if abs(res_1.duration - 3.0) < 0.05:
        t8_errs.append(f"Seg 1 duration was falsely clamped to subtitle slot duration (3.0s)!")

    # Kiểm tra cả file VieNeu thật đã sinh ở 5.2.2.5 (câu 27) nếu có
    real_wav_27 = os.path.join(raw_dir, "segment_0027.wav")
    if os.path.isfile(real_wav_27):
        with wave.open(real_wav_27, "rb") as wf:
            real_header_dur = wf.getnframes() / float(wf.getframerate())
        measured_dur = measure_wav_duration(real_wav_27)
        if abs(measured_dur - real_header_dur) > tolerance:
            t8_errs.append(f"Real VieNeu file duration mismatch: measured={measured_dur:.4f}s, header={real_header_dur:.4f}s")

    test_results.append((8, "Raw Duration Integrity (WAV header match, zero fitting/atempo)", len(t8_errs) == 0, t8_errs))

    # =========================================================================
    # BÁO CÁO KẾT QUẢ TỔNG HỢP MA TRẬN 8/8
    # =========================================================================
    print("-" * 70)
    print(f"{'#':<3} | {'Scenario':<45} | {'Result':<8}")
    print("-" * 70)
    all_passed = True
    passed_count = 0

    for idx, name, ok, errs in test_results:
        tag = "✅ PASS" if ok else "❌ FAIL"
        print(f"{idx:<3} | {name:<45} | {tag:<8}")
        if ok:
            passed_count += 1
        else:
            all_passed = False
            for e in errs:
                print(f"      -> {e}")

    print("=" * 70)
    print(f"TTS REGRESSION MATRIX RESULT: {passed_count}/{len(test_results)} PASS")
    print("=" * 70)
    return all_passed


if __name__ == "__main__":
    success = run_matrix_tests()
    if not success:
        sys.exit(1)
