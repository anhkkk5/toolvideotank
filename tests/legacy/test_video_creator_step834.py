"""Test Acceptance cho Bước 8.3.4 — TTS Orchestration (18 Tests).

Kiểm tra 18 kịch bản nghiêm ngặt:
[1] Male eligible -> Raw + fitted thành công
[2] Female eligible -> Raw + fitted thành công
[3] Unknown -> Bypass toàn bộ (0 raw, 0 fitted, 0 block)
[4] None -> Bypass toàn bộ (0 raw, 0 fitted, 0 block)
[5] Noise -> Bypass toàn bộ (0 raw, 0 fitted, 0 block)
[6] Empty translation -> Bypass toàn bộ (0 raw, 0 fitted, 0 block)
[7] Voice ID preservation -> Assignment ID không thay đổi, cấm gọi VoiceMappingService
[8] Master Data immutability -> segments không mutate
[9] Raw/fitted isolation -> Raw không bị overwrite bởi atempo
[10] TTS failure -> Fail-fast
[11] Fitting failure -> Fail-fast
[12] Cancellation before segment -> Cancelled, không gọi segment đó
[13] Cancellation after completed segment -> Không chạy segment tiếp theo
[14] max_speedup_ratio > 1.20 -> Reject trước TTS
[15] Assignment/segment ID mismatch -> Failed
[16] fitted_audio_path được handoff đúng sang TTSAudioBlock
[17] Skipped segment không tạo TTSAudioBlock
[18] Progress monotonic + final TTS progress = 55%
"""

import copy
import os
import shutil
import sys
import tempfile
from typing import Any
from unittest.mock import MagicMock

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.models.subtitle_segment import SubtitleSegment
from app.services.audio_mixing_service import TTSAudioBlock
from app.services.duration_fitting_service import DurationFittingService, FittedAudioResult
from app.services.tts_backend import TTSResult
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
    VoiceAssignment,
)
from app.services.voiceover_service import VoiceoverService


def create_mock_voiceover(raw_dir: str, fail_seg_id: int | None = None) -> MagicMock:
    mock = MagicMock(spec=VoiceoverService)
    def fake_generate(segment_id, translated_text, start=0.0, end=0.0, voice_id="", is_noise=False, skip_tts=False, output_path=None):
        if fail_seg_id is not None and segment_id == fail_seg_id:
            return TTSResult(segment_id=segment_id, voice_id=voice_id, audio_path="", duration=0.0, status="failed", error="Mock backend synthesis error")
        p = output_path or os.path.join(raw_dir, f"segment_{segment_id:04d}.wav")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"RIFF_FAKE_RAW_WAV_BYTES_FOR_TEST")
        return TTSResult(segment_id=segment_id, voice_id=voice_id, audio_path=p, duration=2.5, status="success", error="")
    mock.generate.side_effect = fake_generate
    return mock


def create_mock_fitting(fitted_dir: str, fail_seg_id: int | None = None, warn_seg_id: int | None = None) -> MagicMock:
    mock = MagicMock(spec=DurationFittingService)
    def fake_fit(segment_id, raw_audio_path, slot_duration, output_path=None):
        if fail_seg_id is not None and segment_id == fail_seg_id:
            return FittedAudioResult(segment_id=segment_id, raw_audio_path=raw_audio_path, raw_duration=2.5, status="failed", error="Mock atempo filter failed")
        p = output_path or os.path.join(fitted_dir, f"segment_{segment_id:04d}_fit.wav")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"RIFF_FAKE_FITTED_WAV_BYTES_FOR_TEST")
        warning = "Audio overflowed slot" if warn_seg_id == segment_id else ""
        return FittedAudioResult(
            segment_id=segment_id,
            raw_audio_path=raw_audio_path,
            raw_duration=2.5,
            fitted_audio_path=p,
            fitted_duration=2.08,
            applied_speed=1.20,
            status="success",
            warning=warning,
            error="",
        )
    mock.fit_segment.side_effect = fake_fit
    return mock


def main() -> int:
    print("=" * 80)
    print("KIỂM THỬ ACCEPTANCE: BƯỚC 8.3.4 — TTS ORCHESTRATION (18 TESTS)")
    print("=" * 80)

    work_dir = os.path.join(tempfile.gettempdir(), "test_creator_step834")
    shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)

    valid_vid = os.path.join(work_dir, "sample_in.mp4")
    with open(valid_vid, "wb") as f:
        f.write(b"SAMPLE_VIDEO_HEADER")

    valid_out = os.path.join(work_dir, "sample_out.mp4")

    tests_passed = 0
    total_tests = 18

    # -------------------------------------------------------------------------
    # [1] Male eligible -> Raw + fitted thành công
    # -------------------------------------------------------------------------
    seg1 = SubtitleSegment(id=1, start=0.0, end=2.0, text="Male text", translated_text="Chào bạn nam", final_gender="male")
    assign1 = VoiceAssignment(segment_id=1, voice_id="vieneu_thanhnientutin", is_tts_eligible=True, reason="male_mapping")
    session1 = os.path.join(work_dir, "s1")

    vo1 = create_mock_voiceover(os.path.join(session1, "raw_tts"))
    fit1 = create_mock_fitting(os.path.join(session1, "fitted_tts"))
    svc1 = VideoCreatorService(voiceover_service=vo1, duration_fitting_service=fit1)

    req1 = VideoCreatorRequest(original_video_path=valid_vid, segments=[seg1], output_video_path=valid_out, workspace_dir=session1)
    res1 = svc1.run(req1)

    pass1 = (
        res1.status == "success"
        and res1.tts_generated_count == 1
        and res1.tts_skipped_count == 0
        and os.path.isfile(os.path.join(session1, "raw_tts", "segment_0001.wav"))
        and os.path.isfile(os.path.join(session1, "fitted_tts", "segment_0001_fit.wav"))
    )
    print(f"[1] Male eligible: {'PASS' if pass1 else 'FAIL'} (gen={res1.tts_generated_count}, status={res1.status})")
    if pass1: tests_passed += 1

    # -------------------------------------------------------------------------
    # [2] Female eligible -> Raw + fitted thành công
    # -------------------------------------------------------------------------
    seg2 = SubtitleSegment(id=2, start=2.5, end=4.0, text="Female text", translated_text="Chào bạn nữ", final_gender="female")
    assign2 = VoiceAssignment(segment_id=2, voice_id="vieneu_cogaihoatbat", is_tts_eligible=True, reason="female_mapping")
    session2 = os.path.join(work_dir, "s2")

    vo2 = create_mock_voiceover(os.path.join(session2, "raw_tts"))
    fit2 = create_mock_fitting(os.path.join(session2, "fitted_tts"))
    svc2 = VideoCreatorService(voiceover_service=vo2, duration_fitting_service=fit2)

    req2 = VideoCreatorRequest(original_video_path=valid_vid, segments=[seg2], output_video_path=valid_out, workspace_dir=session2)
    res2 = svc2.run(req2)

    pass2 = (
        res2.status == "success"
        and res2.tts_generated_count == 1
        and os.path.isfile(os.path.join(session2, "raw_tts", "segment_0002.wav"))
        and os.path.isfile(os.path.join(session2, "fitted_tts", "segment_0002_fit.wav"))
    )
    print(f"[2] Female eligible: {'PASS' if pass2 else 'FAIL'} (gen={res2.tts_generated_count})")
    if pass2: tests_passed += 1

    # -------------------------------------------------------------------------
    # [3], [4], [5], [6] Unknown, None, Noise, Empty translation -> Bypass 100%
    # -------------------------------------------------------------------------
    seg_unk = SubtitleSegment(id=3, start=4.5, end=5.5, text="Unknown", translated_text="Chưa rõ", final_gender="unknown")
    seg_none = SubtitleSegment(id=4, start=6.0, end=7.0, text="None", translated_text="Không người", final_gender="none")
    seg_noise = SubtitleSegment(id=5, start=7.5, end=8.5, text="Noise", translated_text="Tạp âm", final_gender="male", is_noise=True)
    seg_empty = SubtitleSegment(id=6, start=9.0, end=10.0, text="Empty", translated_text="   \t", final_gender="female")

    session3_6 = os.path.join(work_dir, "s3_6")
    vo3_6 = create_mock_voiceover(os.path.join(session3_6, "raw_tts"))
    fit3_6 = create_mock_fitting(os.path.join(session3_6, "fitted_tts"))
    svc3_6 = VideoCreatorService(voiceover_service=vo3_6, duration_fitting_service=fit3_6)

    # Test [3]
    res3 = svc3_6.run(VideoCreatorRequest(valid_vid, [seg_unk], valid_out, session3_6))
    pass3 = (res3.status == "success" and res3.tts_generated_count == 0 and res3.tts_skipped_count == 1 and vo3_6.generate.call_count == 0)
    print(f"[3] Unknown -> Bypass: {'PASS' if pass3 else 'FAIL'} (vo_calls={vo3_6.generate.call_count})")
    if pass3: tests_passed += 1

    # Test [4]
    vo3_6.generate.reset_mock()
    res4 = svc3_6.run(VideoCreatorRequest(valid_vid, [seg_none], valid_out, session3_6))
    pass4 = (res4.status == "success" and res4.tts_generated_count == 0 and res4.tts_skipped_count == 1 and vo3_6.generate.call_count == 0)
    print(f"[4] None -> Bypass: {'PASS' if pass4 else 'FAIL'} (vo_calls={vo3_6.generate.call_count})")
    if pass4: tests_passed += 1

    # Test [5]
    vo3_6.generate.reset_mock()
    res5 = svc3_6.run(VideoCreatorRequest(valid_vid, [seg_noise], valid_out, session3_6))
    pass5 = (res5.status == "success" and res5.tts_generated_count == 0 and res5.tts_skipped_count == 1 and vo3_6.generate.call_count == 0)
    print(f"[5] Noise -> Bypass: {'PASS' if pass5 else 'FAIL'} (vo_calls={vo3_6.generate.call_count})")
    if pass5: tests_passed += 1

    # Test [6]
    vo3_6.generate.reset_mock()
    res6 = svc3_6.run(VideoCreatorRequest(valid_vid, [seg_empty], valid_out, session3_6))
    pass6 = (res6.status == "success" and res6.tts_generated_count == 0 and res6.tts_skipped_count == 1 and vo3_6.generate.call_count == 0)
    print(f"[6] Empty translation -> Bypass: {'PASS' if pass6 else 'FAIL'} (vo_calls={vo3_6.generate.call_count})")
    if pass6: tests_passed += 1

    # -------------------------------------------------------------------------
    # [7] Voice ID preservation & Cấm gọi VoiceMappingService trong 8.3.4
    # -------------------------------------------------------------------------
    session7 = os.path.join(work_dir, "s7")
    vo7 = create_mock_voiceover(os.path.join(session7, "raw_tts"))
    fit7 = create_mock_fitting(os.path.join(session7, "fitted_tts"))
    mock_mapper = MagicMock()
    # Mock mapper được gọi ở Stage 1 (8.3.3) nhưng TUYỆT ĐỐI không được gọi trong 8.3.4 (_orchestrate_tts)
    svc7 = VideoCreatorService(voice_mapping_service=mock_mapper, voiceover_service=vo7, duration_fitting_service=fit7)

    # Chạy trực tiếp _orchestrate_tts
    blocks7, _, err7 = svc7._orchestrate_tts(
        VideoCreatorRequest(valid_vid, [seg1], valid_out, session7),
        [assign1],
        session7,
    )
    # Xác nhận voice_id truyền vào vo7.generate là đúng vieneu_thanhnientutin
    called_voice = vo7.generate.call_args[1]["voice_id"]
    # Xác nhận mapper không bị gọi thêm lần nào trong _orchestrate_tts
    pass7 = (err7 is None and called_voice == "vieneu_thanhnientutin" and mock_mapper.call_count == 0)
    print(f"[7] Voice ID preservation: {'PASS' if pass7 else 'FAIL'} (called_voice='{called_voice}')")
    if pass7: tests_passed += 1

    # -------------------------------------------------------------------------
    # [8] Master Data immutability (segments không mutate)
    # -------------------------------------------------------------------------
    segments8 = [copy.deepcopy(seg1), copy.deepcopy(seg2), copy.deepcopy(seg_unk)]
    segments8_before = copy.deepcopy(segments8)
    session8 = os.path.join(work_dir, "s8")
    vo8 = create_mock_voiceover(os.path.join(session8, "raw_tts"))
    fit8 = create_mock_fitting(os.path.join(session8, "fitted_tts"))
    svc8 = VideoCreatorService(voiceover_service=vo8, duration_fitting_service=fit8)

    res8 = svc8.run(VideoCreatorRequest(valid_vid, segments8, valid_out, session8))
    pass8 = (segments8 == segments8_before and all(getattr(s, "voice_id", "") == "" for s in segments8))
    print(f"[8] Master Data immutability: {'PASS' if pass8 else 'FAIL'} (mutated: {segments8 != segments8_before})")
    if pass8: tests_passed += 1

    # -------------------------------------------------------------------------
    # [9] Raw/fitted isolation (Raw không bị overwrite)
    # -------------------------------------------------------------------------
    raw_f = os.path.join(session1, "raw_tts", "segment_0001.wav")
    fit_f = os.path.join(session1, "fitted_tts", "segment_0001_fit.wav")
    with open(raw_f, "rb") as rf, open(fit_f, "rb") as ff:
        c_raw = rf.read()
        c_fit = ff.read()
    pass9 = (c_raw == b"RIFF_FAKE_RAW_WAV_BYTES_FOR_TEST" and c_fit == b"RIFF_FAKE_FITTED_WAV_BYTES_FOR_TEST" and c_raw != c_fit)
    print(f"[9] Raw/fitted isolation: {'PASS' if pass9 else 'FAIL'} (raw_size={len(c_raw)}, fit_size={len(c_fit)})")
    if pass9: tests_passed += 1

    # -------------------------------------------------------------------------
    # [10] TTS failure -> Fail-fast
    # -------------------------------------------------------------------------
    # 3 segments, segment thứ 2 bị lỗi TTS
    seg10a = SubtitleSegment(id=1, start=0.0, end=2.0, text="T1", translated_text="D1", final_gender="male")
    seg10b = SubtitleSegment(id=2, start=2.5, end=4.5, text="T2", translated_text="D2", final_gender="female")
    seg10c = SubtitleSegment(id=3, start=5.0, end=7.0, text="T3", translated_text="D3", final_gender="male")
    session10 = os.path.join(work_dir, "s10")

    vo10 = create_mock_voiceover(os.path.join(session10, "raw_tts"), fail_seg_id=2)
    fit10 = create_mock_fitting(os.path.join(session10, "fitted_tts"))
    svc10 = VideoCreatorService(voiceover_service=vo10, duration_fitting_service=fit10)

    res10 = svc10.run(VideoCreatorRequest(valid_vid, [seg10a, seg10b, seg10c], valid_out, session10))
    # Segment 3 tuyệt đối không được gọi (vo10 chỉ được gọi 2 lần)
    pass10 = (res10.status == "failed" and "segment 2" in res10.error and vo10.generate.call_count == 2)
    print(f"[10] TTS failure fail-fast: {'PASS' if pass10 else 'FAIL'} (calls={vo10.generate.call_count}, error='{res10.error}')")
    if pass10: tests_passed += 1

    # -------------------------------------------------------------------------
    # [11] Fitting failure -> Fail-fast
    # -------------------------------------------------------------------------
    session11 = os.path.join(work_dir, "s11")
    vo11 = create_mock_voiceover(os.path.join(session11, "raw_tts"))
    fit11 = create_mock_fitting(os.path.join(session11, "fitted_tts"), fail_seg_id=2)
    svc11 = VideoCreatorService(voiceover_service=vo11, duration_fitting_service=fit11)

    res11 = svc11.run(VideoCreatorRequest(valid_vid, [seg10a, seg10b, seg10c], valid_out, session11))
    pass11 = (res11.status == "failed" and "segment 2" in res11.error and vo11.generate.call_count == 2)
    print(f"[11] Fitting failure fail-fast: {'PASS' if pass11 else 'FAIL'} (calls={vo11.generate.call_count}, error='{res11.error}')")
    if pass11: tests_passed += 1

    # -------------------------------------------------------------------------
    # [12] Cancellation before segment
    # -------------------------------------------------------------------------
    session12 = os.path.join(work_dir, "s12")
    vo12 = create_mock_voiceover(os.path.join(session12, "raw_tts"))
    fit12 = create_mock_fitting(os.path.join(session12, "fitted_tts"))
    svc12 = VideoCreatorService(voiceover_service=vo12, duration_fitting_service=fit12)

    cancel_counter = 0
    def cancel_before_seg2():
        nonlocal cancel_counter
        cancel_counter += 1
        # Preflight gọi 2 lần, Pre-segment 1 là lần 3, Post-segment 1 là lần 4
        # Lần 5 chính là Pre-segment của segment 2
        return cancel_counter >= 5

    res12 = svc12.run(VideoCreatorRequest(
        valid_vid, [seg10a, seg10b, seg10c], valid_out, session12, is_cancelled_func=cancel_before_seg2
    ))
    pass12 = (
        res12.status == "cancelled"
        and res12.cancelled_stage == "tts"
        and "pre-segment" in res12.error
        and vo12.generate.call_count == 1
    )
    print(f"[12] Cancellation before segment (pre-segment 2): {'PASS' if pass12 else 'FAIL'} (status={res12.status}, vo_calls={vo12.generate.call_count})")
    if pass12: tests_passed += 1

    # -------------------------------------------------------------------------
    # [13] Cancellation after completed segment
    # -------------------------------------------------------------------------
    session13 = os.path.join(work_dir, "s13")
    vo13 = create_mock_voiceover(os.path.join(session13, "raw_tts"))
    fit13 = create_mock_fitting(os.path.join(session13, "fitted_tts"))
    svc13 = VideoCreatorService(voiceover_service=vo13, duration_fitting_service=fit13)

    # Cancel kích hoạt ngay khi câu 1 vừa hoàn tất (post-segment check)
    def cancel_after_seg1():
        # Kiểm tra nếu câu 1 đã sinh file fitted thì cancel
        return os.path.isfile(os.path.join(session13, "fitted_tts", "segment_0001_fit.wav"))

    res13 = svc13.run(VideoCreatorRequest(
        valid_vid, [seg10a, seg10b, seg10c], valid_out, session13, is_cancelled_func=cancel_after_seg1
    ))
    pass13 = (res13.status == "cancelled" and res13.cancelled_stage == "tts" and vo13.generate.call_count == 1)
    print(f"[13] Cancellation after completed segment: {'PASS' if pass13 else 'FAIL'} (status={res13.status}, vo_calls={vo13.generate.call_count})")
    if pass13: tests_passed += 1

    # -------------------------------------------------------------------------
    # [14] max_speedup_ratio > 1.20 -> Reject trước TTS
    # -------------------------------------------------------------------------
    session14 = os.path.join(work_dir, "s14")
    vo14 = create_mock_voiceover(os.path.join(session14, "raw_tts"))
    fit14 = create_mock_fitting(os.path.join(session14, "fitted_tts"))
    svc14 = VideoCreatorService(voiceover_service=vo14, duration_fitting_service=fit14)

    bad_cfg = VideoCreatorConfig(max_speedup_ratio=1.30)
    res14 = svc14.run(VideoCreatorRequest(valid_vid, [seg1], valid_out, session14, config=bad_cfg))
    pass14 = (res14.status == "failed" and "exceeds hard ceiling 1.20" in res14.error and vo14.generate.call_count == 0)
    print(f"[14] max_speedup_ratio > 1.20: {'PASS' if pass14 else 'FAIL'} (error='{res14.error}')")
    if pass14: tests_passed += 1

    # -------------------------------------------------------------------------
    # [15] Assignment/segment ID mismatch -> Failed
    # -------------------------------------------------------------------------
    session15 = os.path.join(work_dir, "s15")
    mismatched_assign = [VoiceAssignment(segment_id=999, voice_id="vieneu_thanhnientutin", is_tts_eligible=True)]
    blocks15, _, err15 = svc1._orchestrate_tts(
        VideoCreatorRequest(valid_vid, [seg1], valid_out, session15),
        mismatched_assign,
        session15,
    )
    pass15 = (err15 is not None and err15.status == "failed" and "Assignment ID mismatch" in err15.error)
    print(f"[15] Assignment/segment ID mismatch: {'PASS' if pass15 else 'FAIL'} (error='{err15.error if err15 else ''}')")
    if pass15: tests_passed += 1

    # -------------------------------------------------------------------------
    # [16] fitted_audio_path được handoff đúng sang TTSAudioBlock (Step 6 model)
    # -------------------------------------------------------------------------
    session16 = os.path.join(work_dir, "s16")
    vo16 = create_mock_voiceover(os.path.join(session16, "raw_tts"))
    fit16 = create_mock_fitting(os.path.join(session16, "fitted_tts"))
    svc16 = VideoCreatorService(voiceover_service=vo16, duration_fitting_service=fit16)

    blocks16, _, err16 = svc16._orchestrate_tts(
        VideoCreatorRequest(valid_vid, [seg1], valid_out, session16),
        [assign1],
        session16,
    )
    b0 = blocks16[0]
    expected_fit_path = os.path.join(session16, "fitted_tts", "segment_0001_fit.wav")
    pass16 = (
        isinstance(b0, TTSAudioBlock)
        and b0.segment_id == 1
        and b0.start_time == 0.0
        and b0.duration == 2.08
        and b0.audio_path == expected_fit_path
        and b0.volume == 1.0
    )
    print(f"[16] fitted_audio_path handoff to TTSAudioBlock: {'PASS' if pass16 else 'FAIL'} (dur={b0.duration}, path='{b0.audio_path}')")
    if pass16: tests_passed += 1

    # -------------------------------------------------------------------------
    # [17] Skipped segment không tạo TTSAudioBlock
    # -------------------------------------------------------------------------
    session17 = os.path.join(work_dir, "s17")
    vo17 = create_mock_voiceover(os.path.join(session17, "raw_tts"))
    fit17 = create_mock_fitting(os.path.join(session17, "fitted_tts"))
    svc17 = VideoCreatorService(voiceover_service=vo17, duration_fitting_service=fit17)

    # 1 eligible, 1 unknown
    mixed_segs = [seg1, seg_unk]
    mixed_assigns = [assign1, VoiceAssignment(segment_id=3, voice_id=None, is_tts_eligible=False)]
    blocks17, _, _ = svc17._orchestrate_tts(
        VideoCreatorRequest(valid_vid, mixed_segs, valid_out, session17),
        mixed_assigns,
        session17,
    )
    pass17 = (len(blocks17) == 1 and blocks17[0].segment_id == 1)
    print(f"[17] Skipped segment omission in blocks: {'PASS' if pass17 else 'FAIL'} (blocks_count={len(blocks17)})")
    if pass17: tests_passed += 1

    # -------------------------------------------------------------------------
    # [18] Progress monotonic + final TTS progress = 55%
    # -------------------------------------------------------------------------
    progress_history: list[float] = []
    def record_progress(pct, msg):
        progress_history.append(pct)

    session18 = os.path.join(work_dir, "s18")
    vo18 = create_mock_voiceover(os.path.join(session18, "raw_tts"))
    fit18 = create_mock_fitting(os.path.join(session18, "fitted_tts"))
    svc18 = VideoCreatorService(voiceover_service=vo18, duration_fitting_service=fit18)

    # 3 segments
    svc18.run(VideoCreatorRequest(
        valid_vid, [seg10a, seg10b, seg10c], valid_out, session18, progress_callback=record_progress
    ))

    is_monotonic = all(x <= y for x, y in zip(progress_history, progress_history[1:]))
    pass18 = (
        len(progress_history) >= 4  # 1 từ mapping (5%), 3 từ tts
        and is_monotonic
        and progress_history[0] == 5.0
        and abs(progress_history[-1] - 55.0) < 0.01
    )
    print(f"[18] Progress monotonic & ends at 55%: {'PASS' if pass18 else 'FAIL'} (history={[round(p, 1) for p in progress_history]})")
    if pass18: tests_passed += 1

    print("=" * 80)
    print(f"KẾT QUẢ ACCEPTANCE 8.3.4: {tests_passed}/{total_tests} TESTS PASS")
    print("=" * 80)

    return 0 if tests_passed == total_tests else 1


if __name__ == "__main__":
    sys.exit(main())
