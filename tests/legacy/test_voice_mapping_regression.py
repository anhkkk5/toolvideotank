"""Automated Regression Test Suite for Voice Mapping Contract.

Validates the downstream contract from Gender AI final decision:
- male   -> vieneu_thanhnientutin ("Thanh niên tự tin")
- female -> vieneu_cogaihoatbat ("Cô gái hoạt ngôn")
- unknown -> None (no voice assigned)
- none    -> None (no voice assigned)
- Contract Isolation: raw_gender is strictly ignored; only final_gender is used.

Usage:
    python test_voice_mapping_regression.py
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
from services.voice_mapping_service import (
    DEFAULT_MALE_VOICE,
    DEFAULT_FEMALE_VOICE,
    VoiceMappingService,
    VoiceAssignment,
)


def run_voice_mapping_tests() -> bool:
    service = VoiceMappingService()
    test_results: list[tuple[str, bool, list[str]]] = []

    # =========================================================================
    # TEST 1: Pure Gender Mapping - MALE
    # Assert: final_gender='male' -> vieneu_thanhnientutin
    # =========================================================================
    t1_errs = []
    v_male = service.resolve_by_gender("male")
    if v_male is None or v_male.voice_id != "vieneu_thanhnientutin":
        t1_errs.append(f"Expected vieneu_thanhnientutin, got {getattr(v_male, 'voice_id', None)}")
    if v_male is None or v_male.name != "Thanh niên tự tin":
        t1_errs.append(f"Expected 'Thanh niên tự tin', got {getattr(v_male, 'name', None)}")
    test_results.append(("TEST 1 - Pure Mapping: male -> Thanh niên tự tin", len(t1_errs) == 0, t1_errs))

    # =========================================================================
    # TEST 2: Pure Gender Mapping - FEMALE
    # Assert: final_gender='female' -> vieneu_cogaihoatbat
    # =========================================================================
    t2_errs = []
    v_female = service.resolve_by_gender("female")
    if v_female is None or v_female.voice_id != "vieneu_cogaihoatbat":
        t2_errs.append(f"Expected vieneu_cogaihoatbat, got {getattr(v_female, 'voice_id', None)}")
    if v_female is None or v_female.name != "Cô gái hoạt ngôn":
        t2_errs.append(f"Expected 'Cô gái hoạt ngôn', got {getattr(v_female, 'name', None)}")
    test_results.append(("TEST 2 - Pure Mapping: female -> Cô gái hoạt ngôn", len(t2_errs) == 0, t2_errs))

    # =========================================================================
    # TEST 3: Pure Gender Mapping - UNKNOWN & NONE
    # Assert: 'unknown' -> None, 'none' -> None
    # =========================================================================
    t3_errs = []
    v_unk = service.resolve_by_gender("unknown")
    v_none = service.resolve_by_gender("none")
    if v_unk is not None:
        t3_errs.append(f"Expected None for unknown, got {v_unk.voice_id}")
    if v_none is not None:
        t3_errs.append(f"Expected None for none, got {v_none.voice_id}")
    test_results.append(("TEST 3 - Pure Mapping: unknown/none -> None", len(t3_errs) == 0, t3_errs))

    # =========================================================================
    # TEST 4: Contract Isolation (CRITICAL)
    # Scenario: Câu 27 có raw_gender='female' (99.9%) nhưng final_gender='male' (90.6%)
    # Assert: Voice Mapping BẮT BUỘC chỉ đọc final_gender='male' -> vieneu_thanhnientutin
    # =========================================================================
    t4_errs = []
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
        decision_mode="contextual_smoothing",
    )
    v_seg_27 = service.resolve_voice_for_segment(seg_27)
    if v_seg_27 is None or v_seg_27.voice_id != "vieneu_thanhnientutin":
        t4_errs.append(
            f"Isolation contract broken! Expected male voice (vieneu_thanhnientutin), got {getattr(v_seg_27, 'voice_id', None)}"
        )
    if seg_27.voice_id != "vieneu_thanhnientutin":
        t4_errs.append(f"Segment voice_id not populated correctly: {seg_27.voice_id}")
    test_results.append(("TEST 4 - Contract Isolation: raw female + final male -> Male Voice", len(t4_errs) == 0, t4_errs))

    # =========================================================================
    # TEST 5: Noise & Untranslated Suppression
    # Assert: is_noise=True or empty translated_text -> None
    # =========================================================================
    t5_errs = []
    seg_noise = SubtitleSegment(
        id=99,
        start=0.0,
        end=2.0,
        text="剧情需要",
        translated_text="",
        is_noise=True,
        final_gender="male",
    )
    v_noise = service.resolve_voice_for_segment(seg_noise)
    if v_noise is not None:
        t5_errs.append("Expected None for noise segment, but voice was assigned.")
    test_results.append(("TEST 5 - Noise & Untranslated Suppression", len(t5_errs) == 0, t5_errs))

    # =========================================================================
    # REPORT OUTPUT
    # =========================================================================
    print("=" * 65)
    print("           CAPCAP VOICE MAPPING REGRESSION TESTS")
    print("=" * 65)
    all_passed = True
    passed_count = 0

    for name, ok, errors in test_results:
        tag = "[PASS]" if ok else "[FAIL]"
        print(f"{tag} {name}")
        if ok:
            passed_count += 1
        else:
            all_passed = False
            for err in errors:
                print(f"       -> {err}")

    print("-" * 65)
    print(f"VOICE MAPPING RESULT: {passed_count}/{len(test_results)} PASS")
    print("=" * 65)
    return all_passed


if __name__ == "__main__":
    success = run_voice_mapping_tests()
    sys.exit(0 if success else 1)
