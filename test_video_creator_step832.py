"""Test Acceptance cho Bước 8.3.2 — Pre-Flight Gate.

Kiểm tra 10 trường hợp:
[1] Valid input -> PASS
[2] Missing original video -> PASS
[3] Invalid output extension -> PASS
[4] Output == input -> PASS
[5] Negative segment.start -> PASS
[6] segment.end <= segment.start -> PASS
[7] Late segment timing error (segment #50 lỗi) -> PASS
[8] Preflight cancellation -> PASS
[9] No TTS on Preflight failure -> PASS
[10] No FFmpeg on Preflight failure -> PASS
"""

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
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
)


def run_acceptance_832() -> int:
    print("=" * 80)
    print("KIỂM THỬ ACCEPTANCE: BƯỚC 8.3.2 — PRE-FLIGHT GATE")
    print("=" * 80)

    work_dir = os.path.join(tempfile.gettempdir(), "test_creator_step832")
    os.makedirs(work_dir, exist_ok=True)

    # Tạo 1 file video giả định để test tồn tại
    valid_vid = os.path.join(work_dir, "sample_in.mp4")
    with open(valid_vid, "wb") as f:
        f.write(b"SAMPLE_VIDEO_HEADER_FOR_PREFLIGHT_TEST")

    valid_out = os.path.join(work_dir, "sample_out.mp4")

    # Mocks để đảm bảo không gọi downstream khi preflight fail
    mock_tts = MagicMock()
    mock_mixing = MagicMock()
    mock_export = MagicMock()

    service = VideoCreatorService(
        tts_pipeline_service=mock_tts,
        audio_mixing_service=mock_mixing,
        video_export_service=mock_export,
    )

    tests_passed = 0
    total_tests = 10

    # -------------------------------------------------------------------------
    # [1] Valid input -> PASS
    # -------------------------------------------------------------------------
    seg_valid = SubtitleSegment(id=1, start=0.5, end=2.5, text="Hello", translated_text="Xin chào")
    req1 = VideoCreatorRequest(
        original_video_path=valid_vid,
        segments=[seg_valid],
        output_video_path=valid_out,
    )
    res1 = service.run(req1)
    pass1 = (res1.status == "success" and res1.total_segments == 1 and res1.error == "")
    print(f"[1] Valid input: {'PASS' if pass1 else 'FAIL'} (status={res1.status})")
    if pass1: tests_passed += 1

    # -------------------------------------------------------------------------
    # [2] Missing original video -> PASS
    # -------------------------------------------------------------------------
    req2 = VideoCreatorRequest(
        original_video_path=os.path.join(work_dir, "non_existent_video.mp4"),
        segments=[seg_valid],
        output_video_path=valid_out,
    )
    res2 = service.run(req2)
    pass2 = (res2.status == "failed" and "not found" in res2.error.lower())
    print(f"[2] Missing original video: {'PASS' if pass2 else 'FAIL'} (error='{res2.error}')")
    if pass2: tests_passed += 1

    # -------------------------------------------------------------------------
    # [3] Invalid output extension -> PASS
    # -------------------------------------------------------------------------
    req3 = VideoCreatorRequest(
        original_video_path=valid_vid,
        segments=[seg_valid],
        output_video_path=os.path.join(work_dir, "output.mkv"),
    )
    res3 = service.run(req3)
    pass3 = (res3.status == "failed" and ".mp4" in res3.error)
    print(f"[3] Invalid output extension: {'PASS' if pass3 else 'FAIL'} (error='{res3.error}')")
    if pass3: tests_passed += 1

    # -------------------------------------------------------------------------
    # [4] Output == input -> PASS
    # -------------------------------------------------------------------------
    req4 = VideoCreatorRequest(
        original_video_path=valid_vid,
        segments=[seg_valid],
        output_video_path=valid_vid,
    )
    res4 = service.run(req4)
    pass4 = (res4.status == "failed" and "cannot overwrite" in res4.error)
    print(f"[4] Output == input: {'PASS' if pass4 else 'FAIL'} (error='{res4.error}')")
    if pass4: tests_passed += 1

    # -------------------------------------------------------------------------
    # [5] Negative segment.start -> PASS
    # -------------------------------------------------------------------------
    seg_neg = SubtitleSegment(id=5, start=-0.5, end=2.0, text="Bad start", translated_text="Lỗi âm")
    req5 = VideoCreatorRequest(
        original_video_path=valid_vid,
        segments=[seg_neg],
        output_video_path=valid_out,
    )
    res5 = service.run(req5)
    pass5 = (res5.status == "failed" and "Invalid segment timing" in res5.error and "start=-0.5" in res5.error)
    print(f"[5] Negative segment.start: {'PASS' if pass5 else 'FAIL'} (error='{res5.error}')")
    if pass5: tests_passed += 1

    # -------------------------------------------------------------------------
    # [6] segment.end <= segment.start -> PASS
    # -------------------------------------------------------------------------
    seg_inverted = SubtitleSegment(id=6, start=3.0, end=2.0, text="Bad end", translated_text="Lỗi đảo ngược")
    req6 = VideoCreatorRequest(
        original_video_path=valid_vid,
        segments=[seg_inverted],
        output_video_path=valid_out,
    )
    res6 = service.run(req6)
    pass6 = (res6.status == "failed" and "Invalid segment timing" in res6.error and "id=6" in res6.error)
    print(f"[6] segment.end <= segment.start: {'PASS' if pass6 else 'FAIL'} (error='{res6.error}')")
    if pass6: tests_passed += 1

    # -------------------------------------------------------------------------
    # [7] Late segment timing error (segment 50 lỗi) -> PASS
    # -------------------------------------------------------------------------
    many_segs: list[SubtitleSegment] = []
    for i in range(1, 50):
        many_segs.append(SubtitleSegment(id=i, start=float(i * 2), end=float(i * 2 + 1), text=f"Text {i}", translated_text=f"Dịch {i}"))
    # Segment thứ 50 lỗi
    many_segs.append(SubtitleSegment(id=50, start=100.0, end=90.0, text="Text 50", translated_text="Dịch 50"))
    
    req7 = VideoCreatorRequest(
        original_video_path=valid_vid,
        segments=many_segs,
        output_video_path=valid_out,
    )
    res7 = service.run(req7)
    pass7 = (res7.status == "failed" and "id=50" in res7.error)
    print(f"[7] Late segment timing error (segment 50): {'PASS' if pass7 else 'FAIL'} (error='{res7.error}')")
    if pass7: tests_passed += 1

    # -------------------------------------------------------------------------
    # [8] Preflight cancellation -> PASS
    # -------------------------------------------------------------------------
    req8 = VideoCreatorRequest(
        original_video_path=valid_vid,
        segments=[seg_valid],
        output_video_path=valid_out,
        is_cancelled_func=lambda: True,
    )
    res8 = service.run(req8)
    pass8 = (res8.status == "cancelled" and res8.cancelled_stage == "preflight")
    print(f"[8] Preflight cancellation: {'PASS' if pass8 else 'FAIL'} (status={res8.status}, stage={res8.cancelled_stage})")
    if pass8: tests_passed += 1

    # -------------------------------------------------------------------------
    # [9] No TTS on Preflight failure -> PASS
    # -------------------------------------------------------------------------
    # Đã chạy qua các case lỗi [2], [3], [4], [5], [6], [7], [8].
    # Kiểm tra mock_tts chưa bao giờ được gọi
    pass9 = (mock_tts.call_count == 0)
    print(f"[9] No TTS on Preflight failure: {'PASS' if pass9 else 'FAIL'} (tts_call_count={mock_tts.call_count})")
    if pass9: tests_passed += 1

    # -------------------------------------------------------------------------
    # [10] No FFmpeg/Export on Preflight failure -> PASS
    # -------------------------------------------------------------------------
    pass10 = (mock_export.call_count == 0 and mock_mixing.call_count == 0)
    print(f"[10] No FFmpeg/Export on Preflight fail: {'PASS' if pass10 else 'FAIL'} (export_call_count={mock_export.call_count})")
    if pass10: tests_passed += 1

    print("=" * 80)
    print(f"KẾT QUẢ ACCEPTANCE 8.3.2: {tests_passed}/{total_tests} TESTS PASS")
    print("=" * 80)

    return 0 if tests_passed == total_tests else 1


if __name__ == "__main__":
    sys.exit(run_acceptance_832())
