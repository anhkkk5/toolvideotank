"""Test Acceptance cho Bước 8.3.3 — VoiceAssignment & Eligibility Gate.

Kiểm tra toàn diện 13 trường hợp:
[1] male -> vieneu_thanhnientutin
[2] female -> vieneu_cogaihoatbat
[3] unknown -> no TTS
[4] none -> no TTS
[5] noise -> no TTS
[6] empty translated_text -> no TTS
[7] Master Data unchanged (deepcopy comparison)
[8] raw_gender cannot override final_gender
[9] VoiceMappingService failure -> pipeline failed
[10] correct VoiceAssignment list/order
[11] final_gender="male", gender="female" -> Male voice (gender alias cannot override final_gender)
[12] final_gender="male", speaker_label mapped to female voice -> Male voice (speaker_label/character_voices cannot override final_gender)
[13] final_gender=None/missing, gender="female" -> No TTS (cannot fallback to gender)
"""

import copy
import os
import sys
import tempfile
from typing import Any
from unittest.mock import MagicMock

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.models.subtitle_segment import SubtitleSegment
from app.services.voice_mapping_service import (
    DEFAULT_FEMALE_VOICE,
    VoiceMappingConfig,
    VoiceMappingService,
)
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
    VoiceAssignment,
)


def run_acceptance_833() -> int:
    print("=" * 80)
    print("KIỂM THỬ ACCEPTANCE: BƯỚC 8.3.3 — VOICEASSIGNMENT & ELIGIBILITY GATE (13 TESTS)")
    print("=" * 80)

    work_dir = os.path.join(tempfile.gettempdir(), "test_creator_step833")
    os.makedirs(work_dir, exist_ok=True)

    valid_vid = os.path.join(work_dir, "sample_in.mp4")
    with open(valid_vid, "wb") as f:
        f.write(b"SAMPLE_VIDEO_HEADER")

    valid_out = os.path.join(work_dir, "sample_out.mp4")

    service = VideoCreatorService()
    tests_passed = 0
    total_tests = 13

    # -------------------------------------------------------------------------
    # [1] male -> vieneu_thanhnientutin
    # -------------------------------------------------------------------------
    seg_male = SubtitleSegment(
        id=1,
        start=0.0,
        end=2.0,
        text="Hello boy",
        translated_text="Chào chàng trai",
        raw_gender="male",
        final_gender="male",
    )
    assign_male = service._resolve_voice_assignments([seg_male])
    pass1 = (
        len(assign_male) == 1
        and assign_male[0].segment_id == 1
        and assign_male[0].voice_id == "vieneu_thanhnientutin"
        and assign_male[0].is_tts_eligible is True
        and "male" in assign_male[0].reason
    )
    print(f"[1] male -> vieneu_thanhnientutin: {'PASS' if pass1 else 'FAIL'} ({assign_male[0]})")
    if pass1: tests_passed += 1

    # -------------------------------------------------------------------------
    # [2] female -> vieneu_cogaihoatbat
    # -------------------------------------------------------------------------
    seg_female = SubtitleSegment(
        id=2,
        start=2.5,
        end=4.5,
        text="Hello girl",
        translated_text="Chào cô gái",
        raw_gender="female",
        final_gender="female",
    )
    assign_female = service._resolve_voice_assignments([seg_female])
    pass2 = (
        len(assign_female) == 1
        and assign_female[0].segment_id == 2
        and assign_female[0].voice_id == "vieneu_cogaihoatbat"
        and assign_female[0].is_tts_eligible is True
        and "female" in assign_female[0].reason
    )
    print(f"[2] female -> vieneu_cogaihoatbat: {'PASS' if pass2 else 'FAIL'} ({assign_female[0]})")
    if pass2: tests_passed += 1

    # -------------------------------------------------------------------------
    # [3] unknown -> no TTS
    # -------------------------------------------------------------------------
    seg_unk = SubtitleSegment(
        id=3,
        start=5.0,
        end=6.5,
        text="Mysterious voice",
        translated_text="Giọng bí ẩn",
        raw_gender="unknown",
        final_gender="unknown",
    )
    assign_unk = service._resolve_voice_assignments([seg_unk])
    pass3 = (
        len(assign_unk) == 1
        and assign_unk[0].segment_id == 3
        and assign_unk[0].voice_id is None
        and assign_unk[0].is_tts_eligible is False
        and assign_unk[0].reason == "unknown_gender"
    )
    print(f"[3] unknown -> no TTS: {'PASS' if pass3 else 'FAIL'} ({assign_unk[0]})")
    if pass3: tests_passed += 1

    # -------------------------------------------------------------------------
    # [4] none -> no TTS
    # -------------------------------------------------------------------------
    seg_none = SubtitleSegment(
        id=4,
        start=7.0,
        end=8.0,
        text="Silence or ambience",
        translated_text="Âm thanh không người",
        raw_gender="none",
        final_gender="none",
    )
    assign_none = service._resolve_voice_assignments([seg_none])
    pass4 = (
        len(assign_none) == 1
        and assign_none[0].segment_id == 4
        and assign_none[0].voice_id is None
        and assign_none[0].is_tts_eligible is False
        and assign_none[0].reason == "unknown_gender"
    )
    print(f"[4] none -> no TTS: {'PASS' if pass4 else 'FAIL'} ({assign_none[0]})")
    if pass4: tests_passed += 1

    # -------------------------------------------------------------------------
    # [5] noise -> no TTS
    # -------------------------------------------------------------------------
    seg_noise = SubtitleSegment(
        id=5,
        start=8.5,
        end=9.5,
        text="Background noise",
        translated_text="Tiếng ồn",
        final_gender="male",
        is_noise=True,
    )
    assign_noise = service._resolve_voice_assignments([seg_noise])
    pass5 = (
        len(assign_noise) == 1
        and assign_noise[0].segment_id == 5
        and assign_noise[0].voice_id is None
        and assign_noise[0].is_tts_eligible is False
        and assign_noise[0].reason == "noise_skip"
    )
    print(f"[5] noise -> no TTS: {'PASS' if pass5 else 'FAIL'} ({assign_noise[0]})")
    if pass5: tests_passed += 1

    # -------------------------------------------------------------------------
    # [6] empty translated_text -> no TTS
    # -------------------------------------------------------------------------
    seg_empty1 = SubtitleSegment(id=6, start=10.0, end=11.0, text="No translation", translated_text="", final_gender="female")
    seg_empty2 = SubtitleSegment(id=7, start=11.5, end=12.5, text="Whitespace only", translated_text="   \t\n ", final_gender="male")
    assign_empty = service._resolve_voice_assignments([seg_empty1, seg_empty2])
    pass6 = (
        len(assign_empty) == 2
        and assign_empty[0].is_tts_eligible is False and assign_empty[0].reason == "empty_translation"
        and assign_empty[1].is_tts_eligible is False and assign_empty[1].reason == "empty_translation"
    )
    print(f"[6] empty translated_text -> no TTS: {'PASS' if pass6 else 'FAIL'} ({assign_empty})")
    if pass6: tests_passed += 1

    # -------------------------------------------------------------------------
    # [7] Master Data unchanged (deepcopy comparison)
    # -------------------------------------------------------------------------
    test_segments = [
        copy.deepcopy(seg_male),
        copy.deepcopy(seg_female),
        copy.deepcopy(seg_unk),
        copy.deepcopy(seg_noise),
        copy.deepcopy(seg_empty1),
    ]
    segments_before = copy.deepcopy(test_segments)

    # Chạy run() thực tế
    req7 = VideoCreatorRequest(
        original_video_path=valid_vid,
        segments=test_segments,
        output_video_path=valid_out,
    )
    res7 = service.run(req7)

    # Kiểm tra tính bất biến tuyệt đối
    pass7 = (
        test_segments == segments_before
        and all(getattr(s, "voice_id", "") == "" for s in test_segments)
        and res7.status == "success"
    )
    print(f"[7] Master Data unchanged: {'PASS' if pass7 else 'FAIL'} (segments mutated: {test_segments != segments_before})")
    if pass7: tests_passed += 1

    # -------------------------------------------------------------------------
    # [8] raw_gender cannot override final_gender
    # -------------------------------------------------------------------------
    # Câu độc thoại của nam bị model raw nhận nhầm là nữ
    seg_smoothed = SubtitleSegment(
        id=8,
        start=13.0,
        end=14.5,
        text="Monologue segment",
        translated_text="Tôi tự hỏi bản thân",
        raw_gender="female",          # Model âm thanh gốc đoán nhầm Nữ
        final_gender="male",          # Đã được Temporal Smoothing phục hồi Nam!
    )
    assign_smoothed = service._resolve_voice_assignments([seg_smoothed])
    pass8 = (
        len(assign_smoothed) == 1
        and assign_smoothed[0].voice_id == "vieneu_thanhnientutin"
        and assign_smoothed[0].is_tts_eligible is True
        and "male" in assign_smoothed[0].reason
    )
    print(f"[8] raw_gender cannot override final_gender: {'PASS' if pass8 else 'FAIL'} (assigned={assign_smoothed[0].voice_id})")
    if pass8: tests_passed += 1

    # -------------------------------------------------------------------------
    # [9] VoiceMappingService failure -> pipeline failed
    # -------------------------------------------------------------------------
    failing_mapping = MagicMock()
    failing_mapping.resolve_by_gender.side_effect = RuntimeError("Voice mapping model database corrupt!")
    service_failing = VideoCreatorService(voice_mapping_service=failing_mapping)

    req9 = VideoCreatorRequest(
        original_video_path=valid_vid,
        segments=[seg_male],
        output_video_path=valid_out,
    )
    res9 = service_failing.run(req9)
    pass9 = (
        res9.status == "failed"
        and "Voice mapping failed" in res9.error
        and "Voice mapping model database corrupt" in res9.error
    )
    print(f"[9] VoiceMappingService failure: {'PASS' if pass9 else 'FAIL'} (error='{res9.error}')")
    if pass9: tests_passed += 1

    # -------------------------------------------------------------------------
    # [10] correct VoiceAssignment list/order
    # -------------------------------------------------------------------------
    mixed_list = [seg_male, seg_female, seg_unk, seg_none, seg_noise, seg_empty1]
    assign_all = service._resolve_voice_assignments(mixed_list)
    ids_in = [s.id for s in mixed_list]
    ids_out = [a.segment_id for a in assign_all]
    eligible_flags = [a.is_tts_eligible for a in assign_all]

    pass10 = (
        len(assign_all) == len(mixed_list)
        and ids_in == ids_out
        and eligible_flags == [True, True, False, False, False, False]
    )
    print(f"[10] correct VoiceAssignment list/order: {'PASS' if pass10 else 'FAIL'} (ids={ids_out}, eligible={eligible_flags})")
    if pass10: tests_passed += 1

    # -------------------------------------------------------------------------
    # [11] final_gender="male", gender="female" -> Male voice
    # -------------------------------------------------------------------------
    seg_conflict_alias = SubtitleSegment(
        id=11,
        start=15.0,
        end=16.5,
        text="Conflict alias",
        translated_text="Lời nói thử thách alias",
        final_gender="male",
        gender="female",             # Trường alias cũ không được phép override
    )
    assign_conflict_alias = service._resolve_voice_assignments([seg_conflict_alias])
    pass11 = (
        len(assign_conflict_alias) == 1
        and assign_conflict_alias[0].voice_id == "vieneu_thanhnientutin"
        and assign_conflict_alias[0].is_tts_eligible is True
        and "male" in assign_conflict_alias[0].reason
    )
    print(f"[11] final_gender='male', gender='female' -> Male voice: {'PASS' if pass11 else 'FAIL'} (voice_id={assign_conflict_alias[0].voice_id})")
    if pass11: tests_passed += 1

    # -------------------------------------------------------------------------
    # [12] final_gender="male", speaker_label mapped to female voice -> Male voice
    # -------------------------------------------------------------------------
    # Tạo VoiceMappingService có cấu hình character_voices đặc biệt map "CoGai" sang female voice
    custom_cfg = VoiceMappingConfig(character_voices={"CoGai": DEFAULT_FEMALE_VOICE})
    svc_with_char_map = VideoCreatorService(voice_mapping_service=VoiceMappingService(config=custom_cfg))

    seg_speaker_conflict = SubtitleSegment(
        id=12,
        start=17.0,
        end=18.5,
        text="Speaker label conflict",
        translated_text="Nhân vật nhãn gái nhưng giọng nam",
        final_gender="male",
        speaker_label="CoGai",       # Nhãn nhân vật không được phép override final_gender!
    )
    assign_speaker_conflict = svc_with_char_map._resolve_voice_assignments([seg_speaker_conflict])
    pass12 = (
        len(assign_speaker_conflict) == 1
        and assign_speaker_conflict[0].voice_id == "vieneu_thanhnientutin"
        and assign_speaker_conflict[0].is_tts_eligible is True
        and "male" in assign_speaker_conflict[0].reason
    )
    print(f"[12] final_gender='male' + speaker CoGai -> Male voice: {'PASS' if pass12 else 'FAIL'} (voice_id={assign_speaker_conflict[0].voice_id})")
    if pass12: tests_passed += 1

    # -------------------------------------------------------------------------
    # [13] final_gender=None/missing, gender="female" -> No TTS
    # -------------------------------------------------------------------------
    seg_missing_final = SubtitleSegment(
        id=13,
        start=19.0,
        end=20.0,
        text="Missing final gender",
        translated_text="Thiếu final gender",
        final_gender="",             # final_gender rỗng/không xác định
        gender="female",             # Tuyệt đối không fallback sang gender để gán bừa
    )
    assign_missing_final = service._resolve_voice_assignments([seg_missing_final])
    pass13 = (
        len(assign_missing_final) == 1
        and assign_missing_final[0].voice_id is None
        and assign_missing_final[0].is_tts_eligible is False
        and assign_missing_final[0].reason == "unknown_gender"
    )
    print(f"[13] final_gender missing, gender='female' -> No TTS: {'PASS' if pass13 else 'FAIL'} (is_eligible={assign_missing_final[0].is_tts_eligible})")
    if pass13: tests_passed += 1

    print("=" * 80)
    print(f"KẾT QUẢ ACCEPTANCE 8.3.3: {tests_passed}/{total_tests} TESTS PASS")
    print("=" * 80)

    return 0 if tests_passed == total_tests else 1


if __name__ == "__main__":
    sys.exit(run_acceptance_833())
