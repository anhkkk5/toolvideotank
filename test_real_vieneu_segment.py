"""Real Engine Test Suite for Step 5.2.2.5: Test 1 Real Segment with VieNeu.

Executes the full pipeline with the REAL VieNeuBackend:
SubtitleSegment (final_gender='male')
      ↓
VoiceMappingService
      ↓
segment.voice_id = 'vieneu_thanhnientutin'
      ↓
VoiceoverService
      ↓
VieNeuBackend (Real Engine)
      ↓
raw_tts/segment_0027.wav
      ↓
measure duration from actual WAV header
      ↓
TTSResult(status='success')
"""

from __future__ import annotations

import os
import sys
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
from services.vieneu_backend import VieNeuBackend


def run_real_segment_test():
    print("=" * 65)
    print("   TEST 5.2.2.5: TEST 1 REAL SEGMENT WITH VIENEU ENGINE")
    print("=" * 65)

    # Đảm bảo thư mục output raw_tts tồn tại
    raw_dir = os.path.join(str(WORKSPACE_DIR), "raw_tts")
    os.makedirs(raw_dir, exist_ok=True)

    # Khởi tạo dịch vụ với VieNeuBackend thật
    real_backend = VieNeuBackend()
    voice_mapper = VoiceMappingService()
    service = VoiceoverService(backend=real_backend, raw_output_dir=raw_dir)

    # Tạo 1 segment thực tế (câu 27: Nam, "Cho đến khi tôi nhận ra...")
    test_seg = SubtitleSegment(
        id=27,
        start=81.5,
        end=83.5,
        text="直到",
        translated_text="Cho đến khi tôi nhận ra sự thật.",
        raw_gender="female",      # Cố tình đặt raw_gender là female để kiểm tra isolation
        final_gender="male",       # final_gender chuẩn Nam
        final_decision_confidence=0.906,
    )

    out_wav = os.path.join(raw_dir, f"segment_{test_seg.id:04d}.wav")
    print(f"Segment ID       : {test_seg.id}")
    print(f"Text tiếng Việt  : '{test_seg.translated_text}'")
    print(f"Raw Gender       : {test_seg.raw_gender}")
    print(f"Final Gender     : {test_seg.final_gender}")
    print(f"Target Output    : {out_wav}")
    print("-" * 65)
    print("Đang gọi VieNeu TTS thật để sinh Raw Audio...")

    # Chạy chuỗi hoàn chỉnh
    result = service.process_segment(
        segment=test_seg,
        voice_mapping_service=voice_mapper,
        output_path=out_wav,
    )

    print("-" * 65)
    print(f"Result Status    : {result.status}")
    print(f"Assigned Voice   : {result.voice_id}")
    print(f"Audio Path       : {result.audio_path}")
    print(f"Raw Duration     : {result.duration:.3f} giây")
    print(f"Error Message    : '{result.error}'")
    print("-" * 65)

    # Kiểm tra 6 tiêu chí:
    errors = []
    if result.status != "success":
        errors.append(f"Status is not 'success': {result.status}")
    if result.voice_id != "vieneu_thanhnientutin":
        errors.append(f"Voice ID is not 'vieneu_thanhnientutin': {result.voice_id}")
    if not os.path.isfile(result.audio_path):
        errors.append(f"Audio file was not created: {result.audio_path}")
    elif os.path.getsize(result.audio_path) < 1000:
        errors.append(f"Audio file size is suspiciously small: {os.path.getsize(result.audio_path)} bytes")
    if result.duration <= 0.0:
        errors.append(f"Invalid duration: {result.duration}")

    if errors:
        print("[FAIL] Test 5.2.2.5 Failed with errors:")
        for e in errors:
            print(f"  - {e}")
        return False

    file_size = os.path.getsize(result.audio_path)
    print(f"File Size        : {file_size:,} bytes")
    print("[PASS] TEST 5.2.2.5 PASSED 100%! RAW AUDIO GENERATED SUCCESSFULLY.")
    print("=" * 65)
    return True


if __name__ == "__main__":
    success = run_real_segment_test()
    if not success:
        sys.exit(1)
