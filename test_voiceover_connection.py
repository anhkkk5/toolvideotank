"""Test Suite for Step 5.2.2.4: VoiceMapping -> VoiceoverService Connection.

Validates the full pipeline contract:
SubtitleSegment
      ↓
VoiceMapping (final_gender -> voice_id)
      ↓
VoiceoverService (skip checks & orchestration)
      ↓
TTSBackend (receive exact voice_id)
      ↓
TTSResult
"""

from __future__ import annotations

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
from services.tts_backend import TTSBackend, TTSResult


class TrackingMockBackend(TTSBackend):
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    def synthesize(self, text: str, voice_id: str, output_path: str) -> float:
        self.calls.append((text, voice_id, output_path))
        return 2.15


def run_tests():
    print("=" * 65)
    print("    TEST 5.2.2.4: VOICE MAPPING -> VOICEOVER SERVICE")
    print("=" * 65)

    backend = TrackingMockBackend()
    voice_mapper = VoiceMappingService()
    service = VoiceoverService(backend=backend)

    # -------------------------------------------------------------------------
    # TEST 1: Male Segment -> vieneu_thanhnientutin
    # -------------------------------------------------------------------------
    seg_male = SubtitleSegment(
        id=1,
        start=0.0,
        end=3.0,
        text="我看着她",
        translated_text="Tôi nhìn bóng lưng cô ấy",
        raw_gender="male",
        final_gender="male",
    )
    r1 = service.process_segment(seg_male, voice_mapping_service=voice_mapper)
    assert r1.status == "success", f"Expected success, got {r1.status}"
    assert r1.voice_id == "vieneu_thanhnientutin", f"Expected vieneu_thanhnientutin, got {r1.voice_id}"
    assert backend.calls[-1][1] == "vieneu_thanhnientutin", "Backend must receive vieneu_thanhnientutin"
    print("[PASS] Test 1: Male -> vieneu_thanhnientutin -> Backend success")

    # -------------------------------------------------------------------------
    # TEST 2: Female Segment -> vieneu_cogaihoatbat
    # -------------------------------------------------------------------------
    seg_female = SubtitleSegment(
        id=2,
        start=3.5,
        end=6.0,
        text="你好",
        translated_text="Xin chào bạn",
        raw_gender="female",
        final_gender="female",
    )
    r2 = service.process_segment(seg_female, voice_mapping_service=voice_mapper)
    assert r2.status == "success", f"Expected success, got {r2.status}"
    assert r2.voice_id == "vieneu_cogaihoatbat", f"Expected vieneu_cogaihoatbat, got {r2.voice_id}"
    assert backend.calls[-1][1] == "vieneu_cogaihoatbat", "Backend must receive vieneu_cogaihoatbat"
    print("[PASS] Test 2: Female -> vieneu_cogaihoatbat -> Backend success")

    # -------------------------------------------------------------------------
    # TEST 3: Unknown / None Segment -> SKIP (Backend must NOT be called)
    # -------------------------------------------------------------------------
    call_count_before = len(backend.calls)
    seg_unk = SubtitleSegment(
        id=3,
        start=6.5,
        end=8.0,
        text="...",
        translated_text="Không rõ người nói",
        raw_gender="unknown",
        final_gender="unknown",
    )
    r3 = service.process_segment(seg_unk, voice_mapping_service=voice_mapper)
    assert r3.status == "skipped", f"Expected skipped for unknown, got {r3.status}"
    assert len(backend.calls) == call_count_before, "Backend MUST NOT be called for unknown/none"
    print("[PASS] Test 3: Unknown/None -> voice_id='' -> VoiceoverService SKIPPED without calling backend")

    # -------------------------------------------------------------------------
    # TEST 4: Contract Isolation (Câu 27: raw female + final male -> Male Voice)
    # -------------------------------------------------------------------------
    seg_27 = SubtitleSegment(
        id=27,
        start=81.5,
        end=83.5,
        text="直到",
        translated_text="Cho đến khi",
        raw_gender="female",
        raw_gender_confidence=0.999,
        final_gender="male",
        final_decision_confidence=0.906,
    )
    r4 = service.process_segment(seg_27, voice_mapping_service=voice_mapper)
    assert r4.status == "success", f"Expected success, got {r4.status}"
    assert r4.voice_id == "vieneu_thanhnientutin", f"Expected male voice, got {r4.voice_id}"
    assert backend.calls[-1][1] == "vieneu_thanhnientutin", "Backend must receive male voice even though raw is female"
    print("[PASS] Test 4: Contract Isolation (raw female + final male -> Male Voice) verified")

    print("-" * 65)
    print("RESULT: 4/4 TESTS PASSED! CONNECTION VERIFIED.")
    print("=" * 65)


if __name__ == "__main__":
    run_tests()
