"""Acceptance Test Suite for Step 8.3.7 — Verification & Postflight Check (16 Tests).

Validates all 8 Criteria and Core Invariants of Contract 8.3.7 v1.1:
[1] Happy path -> MP4 chuẩn, H.264 + AAC 44.1k stereo, duration khớp -> status='success', progress 100%
[2] Missing output file -> status='failed', lỗi missing
[3] Empty output file (0 bytes) -> status='failed', lỗi empty
[4] Corrupted MP4 container (duration <= 0.0s) -> status='failed'
[5] Missing audio stream -> status='failed'
[6] Missing video stream -> status='failed'
[7] Duration mismatch > 0.5s -> status='failed'
[8] Duration tolerance acceptance (<= 0.5s) -> status='success'
[9] Subtitle count mismatch (rendered + skipped != total) -> status='failed'
[10] Pre-verification cancellation -> status='cancelled', cancelled_stage='verification', Level 3 KEEP, no cleanup, no 100% progress
[11] Cleanup intermediate audio = True -> Level 2 removed (raw_tts, fitted_tts, extracted_audio)
[12] Cleanup intermediate audio = False (Default) -> Level 2 preserved
[13] Level 3 preservation -> final_audio.wav và output_video.mp4 luôn được bảo tồn
[14] Progress monotonic (95% -> 100%) -> Kết thúc trọn vẹn 100%
[15] Codec / spec integrity -> Fail khi video codec != h264, audio != aac, ch != 2, sr != 44100
[16] Intermediate cleanup failure handling -> Cleanup lỗi (PermissionError) -> status='failed', Level 3 KEEP
"""

import copy
import os
import shutil
import sys
import tempfile
import wave
from typing import Any
from unittest.mock import MagicMock

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.models.subtitle_segment import SubtitleSegment
from app.services.video_export_service import VideoExportResult
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
)


def create_pcm_wav(file_path: str, duration_sec: float, sample_rate: int = 44100, channels: int = 2) -> float:
    """Tạo file WAV PCM 16-bit stereo chuẩn hóa."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
    num_frames = int(duration_sec * sample_rate)
    silent_data = b"\x00\x00" * num_frames * channels
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(silent_data)
    return round(num_frames / float(sample_rate), 3)


def make_test_segment(seg_id: int, start: float, end: float) -> SubtitleSegment:
    seg = SubtitleSegment(id=seg_id, start=start, end=end, text="Hello")
    seg.translated_text = "Xin chào"
    seg.final_gender = "male"
    return seg


def standard_h264_aac_prober(file_path: str):
    """Prober chuẩn trả về 1 video H.264 và 1 audio AAC 44.1kHz Stereo."""
    return True, [
        {"codec_type": "video", "codec_name": "h264"},
        {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": 44100},
    ], ""


def run_all_acceptance_tests():
    print("=" * 80)
    print("     CAPCAP STEP 8.3.7 — VERIFICATION & POSTFLIGHT ACCEPTANCE (16 TESTS)")
    print("=" * 80)

    test_root = tempfile.mkdtemp(prefix="capcap_test_step837_")
    results: list[tuple[int, str, bool, list[str]]] = []

    try:
        # =====================================================================
        # TEST 1: Happy path verification
        # =====================================================================
        t1_errs = []
        t1_dir = os.path.join(test_root, "t1")
        os.makedirs(t1_dir, exist_ok=True)
        final_aud = os.path.join(t1_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 4.0)
        out_vid = os.path.join(t1_dir, "output.mp4")
        # Dùng WAV 4.0s làm mock video file đo được 4.0s
        create_pcm_wav(out_vid, 4.0)

        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=4.0,
            audio_duration=4.0,
            final_video_duration=4.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path=out_vid,
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t1_dir,
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t1_dir, final_aud, export_res)
        if err_res is not None:
            t1_errs.append(f"Unexpected error: {err_res.error}")
        if actual_dur != 4.0:
            t1_errs.append(f"Expected actual_dur=4.0, got {actual_dur}")
        results.append((1, "Happy path verification", len(t1_errs) == 0, t1_errs))

        # =====================================================================
        # TEST 2: Missing output file
        # =====================================================================
        t2_errs = []
        t2_dir = os.path.join(test_root, "t2")
        os.makedirs(t2_dir, exist_ok=True)
        missing_vid = os.path.join(t2_dir, "missing.mp4")
        final_aud = os.path.join(t2_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        export_res = VideoExportResult(output_video_path=missing_vid, final_video_duration=3.0, status="success")
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=missing_vid,
            workspace_dir=t2_dir,
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t2_dir, final_aud, export_res)
        if err_res is None or err_res.status != "failed":
            t2_errs.append("Expected status='failed' on missing output file")
        elif "Output video file is missing" not in err_res.error:
            t2_errs.append(f"Unexpected error: {err_res.error}")
        results.append((2, "Missing output file fail-fast", len(t2_errs) == 0, t2_errs))

        # =====================================================================
        # TEST 3: Empty output file (0 bytes)
        # =====================================================================
        t3_errs = []
        t3_dir = os.path.join(test_root, "t3")
        os.makedirs(t3_dir, exist_ok=True)
        empty_vid = os.path.join(t3_dir, "empty.mp4")
        with open(empty_vid, "wb") as f:
            pass  # 0 bytes
        final_aud = os.path.join(t3_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        export_res = VideoExportResult(output_video_path=empty_vid, final_video_duration=3.0, status="success")
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=empty_vid,
            workspace_dir=t3_dir,
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t3_dir, final_aud, export_res)
        if err_res is None or err_res.status != "failed":
            t3_errs.append("Expected status='failed' on empty output file")
        elif "Output video file is empty" not in err_res.error:
            t3_errs.append(f"Unexpected error: {err_res.error}")
        results.append((3, "Empty output file (0 bytes)", len(t3_errs) == 0, t3_errs))

        # =====================================================================
        # TEST 4: Corrupted MP4 container (duration <= 0.0s)
        # =====================================================================
        t4_errs = []
        t4_dir = os.path.join(test_root, "t4")
        os.makedirs(t4_dir, exist_ok=True)
        corrupt_vid = os.path.join(t4_dir, "corrupt.mp4")
        with open(corrupt_vid, "wb") as f:
            f.write(b"CORRUPTED_NON_PARSEABLE_BYTES")
        final_aud = os.path.join(t4_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        export_res = VideoExportResult(output_video_path=corrupt_vid, final_video_duration=3.0, status="success")
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=corrupt_vid,
            workspace_dir=t4_dir,
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t4_dir, final_aud, export_res)
        if err_res is None or err_res.status != "failed":
            t4_errs.append("Expected status='failed' on corrupt container")
        elif "Output video is corrupted or unreadable" not in err_res.error:
            t4_errs.append(f"Unexpected error: {err_res.error}")
        results.append((4, "Corrupted MP4 container", len(t4_errs) == 0, t4_errs))

        # =====================================================================
        # TEST 5: Missing audio stream
        # =====================================================================
        t5_errs = []
        t5_dir = os.path.join(test_root, "t5")
        os.makedirs(t5_dir, exist_ok=True)
        out_vid = os.path.join(t5_dir, "out.mp4")
        create_pcm_wav(out_vid, 3.0)
        final_aud = os.path.join(t5_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        # Prober chỉ trả về video stream, thiếu audio stream
        def only_video_prober(p):
            return True, [{"codec_type": "video", "codec_name": "h264"}], ""

        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=3.0,
            audio_duration=3.0,
            final_video_duration=3.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=only_video_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t5_dir,
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t5_dir, final_aud, export_res)
        if err_res is None or err_res.status != "failed":
            t5_errs.append("Expected status='failed' on missing audio stream")
        elif "missing audio stream" not in err_res.error:
            t5_errs.append(f"Unexpected error: {err_res.error}")
        results.append((5, "Missing audio stream fail-fast", len(t5_errs) == 0, t5_errs))

        # =====================================================================
        # TEST 6: Missing video stream
        # =====================================================================
        t6_errs = []
        t6_dir = os.path.join(test_root, "t6")
        os.makedirs(t6_dir, exist_ok=True)
        out_vid = os.path.join(t6_dir, "out.mp4")
        create_pcm_wav(out_vid, 3.0)
        final_aud = os.path.join(t6_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        # Prober chỉ trả về audio stream, thiếu video stream
        def only_audio_prober(p):
            return True, [{"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": 44100}], ""

        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=3.0,
            audio_duration=3.0,
            final_video_duration=3.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=only_audio_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t6_dir,
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t6_dir, final_aud, export_res)
        if err_res is None or err_res.status != "failed":
            t6_errs.append("Expected status='failed' on missing video stream")
        elif "missing video stream" not in err_res.error:
            t6_errs.append(f"Unexpected error: {err_res.error}")
        results.append((6, "Missing video stream fail-fast", len(t6_errs) == 0, t6_errs))

        # =====================================================================
        # TEST 7: Duration mismatch > 0.5s
        # =====================================================================
        t7_errs = []
        t7_dir = os.path.join(test_root, "t7")
        os.makedirs(t7_dir, exist_ok=True)
        out_vid = os.path.join(t7_dir, "out.mp4")
        create_pcm_wav(out_vid, 5.0)  # Measured = 5.0s
        final_aud = os.path.join(t7_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 4.0)

        # Reported = 4.0s -> Lệch 1.0s (> 0.5s)
        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=4.0,
            audio_duration=4.0,
            final_video_duration=4.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t7_dir,
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t7_dir, final_aud, export_res)
        if err_res is None or err_res.status != "failed":
            t7_errs.append("Expected status='failed' on duration mismatch > 0.5s")
        elif "Duration consistency check failed" not in err_res.error:
            t7_errs.append(f"Unexpected error: {err_res.error}")
        results.append((7, "Duration mismatch > 0.5s fail-fast", len(t7_errs) == 0, t7_errs))

        # =====================================================================
        # TEST 8: Duration tolerance acceptance (<= 0.5s)
        # =====================================================================
        t8_errs = []
        t8_dir = os.path.join(test_root, "t8")
        os.makedirs(t8_dir, exist_ok=True)
        out_vid = os.path.join(t8_dir, "out.mp4")
        create_pcm_wav(out_vid, 4.20)  # Measured = 4.20s
        final_aud = os.path.join(t8_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 4.00)

        # Reported = 4.00s -> Lệch 0.20s (<= 0.5s)
        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=4.0,
            audio_duration=4.0,
            final_video_duration=4.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t8_dir,
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t8_dir, final_aud, export_res)
        if err_res is not None:
            t8_errs.append(f"Unexpected error: {err_res.error}")
        if actual_dur != 4.20:
            t8_errs.append(f"Expected actual_dur=4.20, got {actual_dur}")
        results.append((8, "Duration tolerance acceptance (<= 0.5s)", len(t8_errs) == 0, t8_errs))

        # =====================================================================
        # TEST 9: Subtitle count mismatch
        # =====================================================================
        t9_errs = []
        t9_dir = os.path.join(test_root, "t9")
        os.makedirs(t9_dir, exist_ok=True)
        out_vid = os.path.join(t9_dir, "out.mp4")
        create_pcm_wav(out_vid, 4.0)
        final_aud = os.path.join(t9_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 4.0)

        # Total 2 segments, but rendered + skipped = 1 != 2
        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=4.0,
            audio_duration=4.0,
            final_video_duration=4.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0), make_test_segment(2, 2.0, 4.0)],
            output_video_path=out_vid,
            workspace_dir=t9_dir,
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t9_dir, final_aud, export_res)
        if err_res is None or err_res.status != "failed":
            t9_errs.append("Expected status='failed' on subtitle count mismatch")
        elif "Subtitle count completeness check failed" not in err_res.error:
            t9_errs.append(f"Unexpected error: {err_res.error}")
        results.append((9, "Subtitle count mismatch fail-fast", len(t9_errs) == 0, t9_errs))

        # =====================================================================
        # TEST 10: Pre-verification cancellation
        # =====================================================================
        t10_errs = []
        t10_dir = os.path.join(test_root, "t10")
        os.makedirs(t10_dir, exist_ok=True)
        out_vid = os.path.join(t10_dir, "output.mp4")
        create_pcm_wav(out_vid, 4.0)
        final_aud = os.path.join(t10_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 4.0)

        # Tạo Level 2 dirs
        raw_dir = os.path.join(t10_dir, "raw_tts")
        os.makedirs(raw_dir, exist_ok=True)

        prog_called = []
        export_res = VideoExportResult(output_video_path=out_vid, final_video_duration=4.0, status="success")
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t10_dir,
            is_cancelled_func=lambda: True,  # Cancelled before verification
            progress_callback=lambda pct, msg: prog_called.append(pct),
            config=VideoCreatorConfig(cleanup_intermediate_audio=True),
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t10_dir, final_aud, export_res)
        if err_res is None or err_res.status != "cancelled":
            t10_errs.append("Expected status='cancelled'")
        if err_res and err_res.cancelled_stage != "verification":
            t10_errs.append(f"Expected cancelled_stage='verification', got {err_res.cancelled_stage}")
        if not os.path.isfile(out_vid) or not os.path.isfile(final_aud):
            t10_errs.append("Level 3 artifacts must be preserved on cancellation")
        if not os.path.isdir(raw_dir):
            t10_errs.append("Level 2 intermediate must NOT be cleaned up when cancelled")
        if 100.0 in prog_called:
            t10_errs.append("Progress 100% MUST NOT be called when cancelled")
        results.append((10, "Pre-verification cancellation", len(t10_errs) == 0, t10_errs))

        # =====================================================================
        # TEST 11: Cleanup intermediate audio = True
        # =====================================================================
        t11_dir = os.path.join(test_root, "t11")
        os.makedirs(t11_dir, exist_ok=True)
        t11_errs = []
        out_vid = os.path.join(t11_dir, "output.mp4")
        create_pcm_wav(out_vid, 3.0)
        final_aud = os.path.join(t11_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        raw_dir = os.path.join(t11_dir, "raw_tts")
        fitted_dir = os.path.join(t11_dir, "fitted_tts")
        ext_audio = os.path.join(t11_dir, "extracted_original_audio.wav")
        os.makedirs(raw_dir, exist_ok=True)
        os.makedirs(fitted_dir, exist_ok=True)
        create_pcm_wav(ext_audio, 3.0)

        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=3.0,
            audio_duration=3.0,
            final_video_duration=3.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t11_dir,
            config=VideoCreatorConfig(cleanup_intermediate_audio=True),
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t11_dir, final_aud, export_res)
        if err_res is not None:
            t11_errs.append(f"Unexpected error: {err_res.error}")
        if os.path.exists(raw_dir) or os.path.exists(fitted_dir) or os.path.exists(ext_audio):
            t11_errs.append("Level 2 intermediate audio was not cleaned up")
        results.append((11, "Cleanup intermediate audio = True", len(t11_errs) == 0, t11_errs))

        # =====================================================================
        # TEST 12: Cleanup intermediate audio = False (Default)
        # =====================================================================
        t12_dir = os.path.join(test_root, "t12")
        os.makedirs(t12_dir, exist_ok=True)
        t12_errs = []
        out_vid = os.path.join(t12_dir, "output.mp4")
        create_pcm_wav(out_vid, 3.0)
        final_aud = os.path.join(t12_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        raw_dir = os.path.join(t12_dir, "raw_tts")
        os.makedirs(raw_dir, exist_ok=True)

        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=3.0,
            audio_duration=3.0,
            final_video_duration=3.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t12_dir,
            config=VideoCreatorConfig(cleanup_intermediate_audio=False),  # Default
        )
        actual_dur, err_res = svc._orchestrate_verification(req, t12_dir, final_aud, export_res)
        if err_res is not None:
            t12_errs.append(f"Unexpected error: {err_res.error}")
        if not os.path.isdir(raw_dir):
            t12_errs.append("Level 2 intermediate audio must be preserved when cleanup is False")
        results.append((12, "Cleanup intermediate audio = False (Default)", len(t12_errs) == 0, t12_errs))

        # =====================================================================
        # TEST 13: Final artifacts preservation (Level 3)
        # =====================================================================
        t13_dir = os.path.join(test_root, "t13")
        os.makedirs(t13_dir, exist_ok=True)
        t13_errs = []
        out_vid = os.path.join(t13_dir, "output.mp4")
        create_pcm_wav(out_vid, 3.0)
        final_aud = os.path.join(t13_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=3.0,
            audio_duration=3.0,
            final_video_duration=3.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t13_dir,
            config=VideoCreatorConfig(cleanup_intermediate_audio=True),  # Even with cleanup=True
        )
        svc._orchestrate_verification(req, t13_dir, final_aud, export_res)
        if not os.path.isfile(out_vid):
            t13_errs.append("output_video.mp4 must never be deleted")
        if not os.path.isfile(final_aud):
            t13_errs.append("final_audio.wav must never be deleted")
        results.append((13, "Final artifacts preservation (Level 3)", len(t13_errs) == 0, t13_errs))

        # =====================================================================
        # TEST 14: Progress monotonic (95% -> 100%)
        # =====================================================================
        t14_dir = os.path.join(test_root, "t14")
        os.makedirs(t14_dir, exist_ok=True)
        t14_errs = []
        out_vid = os.path.join(t14_dir, "output.mp4")
        create_pcm_wav(out_vid, 3.0)
        final_aud = os.path.join(t14_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        prog_history = []
        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=3.0,
            audio_duration=3.0,
            final_video_duration=3.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t14_dir,
            progress_callback=lambda pct, msg: prog_history.append((pct, msg)),
        )
        svc._orchestrate_verification(req, t14_dir, final_aud, export_res)
        pcts = [p[0] for p in prog_history]
        if not pcts:
            t14_errs.append("No progress recorded")
        else:
            if pcts[0] != 95.0:
                t14_errs.append(f"Expected start 95.0%, got {pcts[0]}")
            if pcts[-1] != 100.0:
                t14_errs.append(f"Expected end 100.0%, got {pcts[-1]}")
            if pcts != sorted(pcts):
                t14_errs.append(f"Progress not monotonic: {pcts}")
        results.append((14, "Progress monotonic (95% -> 100%)", len(t14_errs) == 0, t14_errs))

        # =====================================================================
        # TEST 15: Codec / spec integrity failure (H.264 + AAC 44.1k Stereo)
        # =====================================================================
        t15_dir = os.path.join(test_root, "t15")
        os.makedirs(t15_dir, exist_ok=True)
        t15_errs = []
        out_vid = os.path.join(t15_dir, "output.mp4")
        create_pcm_wav(out_vid, 3.0)
        final_aud = os.path.join(t15_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=3.0,
            audio_duration=3.0,
            final_video_duration=3.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )

        # 15a: Video codec != h264 (mpeg4)
        def prober_mpeg4(p):
            return True, [
                {"codec_type": "video", "codec_name": "mpeg4"},
                {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": 44100},
            ], ""
        svc_15a = VideoCreatorService(stream_prober=prober_mpeg4)
        req_15a = VideoCreatorRequest("orig.mp4", [make_test_segment(1, 0.0, 2.0)], out_vid, t15_dir)
        _, err_15a = svc_15a._orchestrate_verification(req_15a, t15_dir, final_aud, export_res)
        if err_15a is None or "expected 'h264'" not in err_15a.error:
            t15_errs.append(f"15a: Expected h264 mismatch error, got {err_15a}")

        # 15b: Audio codec != aac (mp3)
        def prober_mp3(p):
            return True, [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "mp3", "channels": 2, "sample_rate": 44100},
            ], ""
        svc_15b = VideoCreatorService(stream_prober=prober_mp3)
        _, err_15b = svc_15b._orchestrate_verification(req_15a, t15_dir, final_aud, export_res)
        if err_15b is None or "expected 'aac'" not in err_15b.error:
            t15_errs.append(f"15b: Expected aac mismatch error, got {err_15b}")

        # 15c: Audio channels != 2 (mono)
        def prober_mono(p):
            return True, [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac", "channels": 1, "sample_rate": 44100},
            ], ""
        svc_15c = VideoCreatorService(stream_prober=prober_mono)
        _, err_15c = svc_15c._orchestrate_verification(req_15a, t15_dir, final_aud, export_res)
        if err_15c is None or "expected 2 (stereo)" not in err_15c.error:
            t15_errs.append(f"15c: Expected channels 2 mismatch error, got {err_15c}")

        # 15d: Audio sample_rate != 44100 (48000)
        def prober_48k(p):
            return True, [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": 48000},
            ], ""
        svc_15d = VideoCreatorService(stream_prober=prober_48k)
        _, err_15d = svc_15d._orchestrate_verification(req_15a, t15_dir, final_aud, export_res)
        if err_15d is None or "expected 44100" not in err_15d.error:
            t15_errs.append(f"15d: Expected 44100 mismatch error, got {err_15d}")

        results.append((15, "Codec / spec integrity failure", len(t15_errs) == 0, t15_errs))

        # =====================================================================
        # TEST 16: Intermediate cleanup failure handling (Level 3 preserved)
        # =====================================================================
        t16_dir = os.path.join(test_root, "t16")
        os.makedirs(t16_dir, exist_ok=True)
        t16_errs = []
        out_vid = os.path.join(t16_dir, "output.mp4")
        create_pcm_wav(out_vid, 3.0)
        final_aud = os.path.join(t16_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        # Mock os.remove to raise PermissionError when deleting intermediate audio
        export_res = VideoExportResult(
            output_video_path=out_vid,
            video_duration=3.0,
            audio_duration=3.0,
            final_video_duration=3.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            status="success",
        )
        svc = VideoCreatorService(stream_prober=standard_h264_aac_prober)
        req = VideoCreatorRequest(
            original_video_path="orig.mp4",
            segments=[make_test_segment(1, 0.0, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t16_dir,
            config=VideoCreatorConfig(cleanup_intermediate_audio=True),
        )

        # Create dummy intermediate file
        ext_audio = os.path.join(t16_dir, "extracted_original_audio.wav")
        create_pcm_wav(ext_audio, 3.0)

        orig_rm = os.remove
        def fail_remove(path):
            if "extracted_original_audio.wav" in path:
                raise PermissionError("Access is denied: file locked by Windows process")
            return orig_rm(path)

        os.remove = fail_remove
        try:
            actual_dur, err_res = svc._orchestrate_verification(req, t16_dir, final_aud, export_res)
        finally:
            os.remove = orig_rm

        if err_res is None or err_res.status != "failed":
            t16_errs.append("Expected status='failed' when intermediate cleanup fails")
        elif "Workspace intermediate cleanup failed" not in err_res.error:
            t16_errs.append(f"Unexpected error message: {err_res.error}")

        # Invariant: Level 3 artifacts MUST be preserved despite cleanup failure!
        if not os.path.isfile(out_vid):
            t16_errs.append("output_video.mp4 must remain preserved on cleanup failure")
        if not os.path.isfile(final_aud):
            t16_errs.append("final_audio.wav must remain preserved on cleanup failure")

        results.append((16, "Intermediate cleanup failure handling (Level 3 preserved)", len(t16_errs) == 0, t16_errs))

    finally:
        shutil.rmtree(test_root, ignore_errors=True)

    # In kết quả tổng hợp
    print("-" * 80)
    passed_count = 0
    for test_id, name, passed, errs in results:
        status_str = "✅ PASS" if passed else "❌ FAIL"
        if passed:
            passed_count += 1
        print(f"[{test_id:02d}] {status_str} - {name}")
        for e in errs:
            print(f"     └── ⚠️ {e}")

    print("=" * 80)
    print(f"KẾT QUẢ ACCEPTANCE STEP 8.3.7: {passed_count}/{len(results)} TESTS PASS")
    print("=" * 80)
    return passed_count == len(results)


if __name__ == "__main__":
    success = run_all_acceptance_tests()
    sys.exit(0 if success else 1)
