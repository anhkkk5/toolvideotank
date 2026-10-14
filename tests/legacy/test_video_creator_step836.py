"""Acceptance Test Suite for Step 8.3.6 — Video Export Orchestration (15 Tests).

Validates all 10 Invariants and Core Behaviors of Contract 8.3.6 v1.1:
[1] Normal video export with hardsub -> Sinh output.mp4, status='success', đo đủ 3 durations
[2] Zero subtitles (all noise/empty) -> Xuất video không sub, rendered_count=0, status='success'
[3] Config propagation (overflow_policy) -> Verify export_req.overflow_policy == request.config.overflow_policy
[4] Config propagation (subtitle_config) -> Custom SubtitleRenderConfig truyền nguyên vẹn sang export_req
[5] Missing final_audio_path -> status='failed', lỗi rõ ràng, dừng pipeline
[6] Missing original_video_path -> status='failed', lỗi rõ ràng, dừng pipeline
[7] Output overwrite input protection -> output_video_path == original_video_path -> status='failed'
[8] Output overwrite audio protection -> output_video_path == final_audio_path -> status='failed'
[9] Pre-export cancellation (Checkpoint A) -> export_video() KHÔNG được gọi, cancelled_stage='export'
[10] Post-export cancellation (Checkpoint B) -> status='cancelled', cancelled_stage='export', output_video.mp4 vẫn tồn tại trên disk
[11] Master Data immutability -> segments không bị mutate bất kỳ thuộc tính nào
[12] Metrics recording -> Ghi nhận video_duration, audio_duration, final_video_duration, rendered_count, skipped_count
[13] Warning propagation -> Freeze frame warning xuất hiện trong result.warnings
[14] Progress monotonic (75% -> 95%) -> Đi từ 75.0% -> 95.0% đơn điệu
[15] Unexpected export exception -> export_video() raise RuntimeError -> status='failed', error chứa exception message
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
from app.services.video_export_service import (
    OverflowPolicy,
    SubtitleRenderConfig,
    VideoExportRequest,
    VideoExportResult,
    VideoExportService,
)
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


def make_test_segment(seg_id: int, start: float, end: float, text: str = "Thoại gốc", trans_text: str = "Bản dịch") -> SubtitleSegment:
    seg = SubtitleSegment(id=seg_id, start=start, end=end, text=text)
    seg.translated_text = trans_text
    seg.final_gender = "male"
    seg.is_noise = False
    seg.skip_tts = False
    return seg


def run_all_acceptance_tests():
    print("=" * 80)
    print("     CAPCAP STEP 8.3.6 — VIDEO EXPORT ORCHESTRATION ACCEPTANCE (15 TESTS)")
    print("=" * 80)

    test_root = tempfile.mkdtemp(prefix="capcap_test_step836_")
    results: list[tuple[int, str, bool, list[str]]] = []

    try:
        # =====================================================================
        # TEST 1: Normal video export with hardsub
        # =====================================================================
        t1_errs = []
        t1_dir = os.path.join(test_root, "t1")
        os.makedirs(t1_dir, exist_ok=True)
        in_vid = os.path.join(t1_dir, "input.mp4")
        with open(in_vid, "wb") as f:
            f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t1_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 4.0)
        out_vid = os.path.join(t1_dir, "output.mp4")

        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.return_value = VideoExportResult(
            output_video_path=out_vid,
            video_duration=4.0,
            audio_duration=4.0,
            final_video_duration=4.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            applied_overflow_policy="shortest",
            status="success",
        )

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.5)],
            output_video_path=out_vid,
            workspace_dir=t1_dir,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t1_dir, final_aud)
        if err_res is not None:
            t1_errs.append(f"Unexpected error: {err_res.error}")
        if export_res is None or export_res.status != "success":
            t1_errs.append(f"Expected success, got {export_res}")
        if not mock_export.export_video.called:
            t1_errs.append("VideoExportService.export_video was not called")
        results.append((1, "Normal video export with hardsub", len(t1_errs) == 0, t1_errs))

        # =====================================================================
        # TEST 2: Zero subtitles (all noise or empty translation)
        # =====================================================================
        t2_errs = []
        t2_dir = os.path.join(test_root, "t2")
        os.makedirs(t2_dir, exist_ok=True)
        in_vid = os.path.join(t2_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t2_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)
        out_vid = os.path.join(t2_dir, "output.mp4")

        seg_noise = make_test_segment(1, 0.0, 1.0, "Noise", "Rác")
        seg_noise.is_noise = True
        seg_empty = make_test_segment(2, 1.0, 2.0, "Empty", "   \t")

        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.return_value = VideoExportResult(
            output_video_path=out_vid,
            video_duration=3.0,
            audio_duration=3.0,
            final_video_duration=3.0,
            rendered_subtitles_count=0,
            skipped_subtitles_count=2,
            status="success",
        )

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[seg_noise, seg_empty],
            output_video_path=out_vid,
            workspace_dir=t2_dir,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t2_dir, final_aud)
        if err_res is not None:
            t2_errs.append(f"Unexpected error: {err_res.error}")
        if export_res and export_res.rendered_subtitles_count != 0:
            t2_errs.append(f"Expected 0 rendered subtitles, got {export_res.rendered_subtitles_count}")
        results.append((2, "Zero subtitles (all noise/empty)", len(t2_errs) == 0, t2_errs))

        # =====================================================================
        # TEST 3: Config propagation (overflow_policy='freeze_end')
        # =====================================================================
        t3_errs = []
        t3_dir = os.path.join(test_root, "t3")
        os.makedirs(t3_dir, exist_ok=True)
        in_vid = os.path.join(t3_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t3_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 5.0)
        out_vid = os.path.join(t3_dir, "output.mp4")

        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.return_value = VideoExportResult(status="success", output_video_path=out_vid)

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t3_dir,
            config=VideoCreatorConfig(overflow_policy="freeze_end"),
        )
        svc._orchestrate_export(req, t3_dir, final_aud)
        if not mock_export.export_video.called:
            t3_errs.append("export_video not called")
        else:
            called_req = mock_export.export_video.call_args[0][0]
            if called_req.overflow_policy != "freeze_end":
                t3_errs.append(f"Expected overflow_policy='freeze_end', got {called_req.overflow_policy}")
        results.append((3, "Config propagation (overflow_policy)", len(t3_errs) == 0, t3_errs))

        # =====================================================================
        # TEST 4: Config propagation (subtitle_config)
        # =====================================================================
        t4_errs = []
        t4_dir = os.path.join(test_root, "t4")
        os.makedirs(t4_dir, exist_ok=True)
        in_vid = os.path.join(t4_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t4_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)
        out_vid = os.path.join(t4_dir, "output.mp4")

        custom_sub_cfg = SubtitleRenderConfig(font_name="Roboto", font_size=24, outline_width=3, bold=False)
        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.return_value = VideoExportResult(status="success", output_video_path=out_vid)

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t4_dir,
            config=VideoCreatorConfig(subtitle_config=custom_sub_cfg),
        )
        svc._orchestrate_export(req, t4_dir, final_aud)
        if not mock_export.export_video.called:
            t4_errs.append("export_video not called")
        else:
            called_req = mock_export.export_video.call_args[0][0]
            if called_req.subtitle_config != custom_sub_cfg:
                t4_errs.append(f"Expected subtitle_config={custom_sub_cfg}, got {called_req.subtitle_config}")
        results.append((4, "Config propagation (subtitle_config)", len(t4_errs) == 0, t4_errs))

        # =====================================================================
        # TEST 5: Missing final_audio_path fail-fast
        # =====================================================================
        t5_errs = []
        t5_dir = os.path.join(test_root, "t5")
        os.makedirs(t5_dir, exist_ok=True)
        in_vid = os.path.join(t5_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        missing_aud = os.path.join(t5_dir, "non_existent_final_audio.wav")
        out_vid = os.path.join(t5_dir, "output.mp4")

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t5_dir,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t5_dir, missing_aud)
        if err_res is None or err_res.status != "failed":
            t5_errs.append("Expected status='failed' on missing final_audio")
        elif "Final audio file not found" not in err_res.error:
            t5_errs.append(f"Unexpected error: {err_res.error}")
        results.append((5, "Missing final_audio_path fail-fast", len(t5_errs) == 0, t5_errs))

        # =====================================================================
        # TEST 6: Missing original_video_path fail-fast
        # =====================================================================
        t6_errs = []
        t6_dir = os.path.join(test_root, "t6")
        os.makedirs(t6_dir, exist_ok=True)
        missing_vid = os.path.join(t6_dir, "non_existent_input.mp4")
        final_aud = os.path.join(t6_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)
        out_vid = os.path.join(t6_dir, "output.mp4")

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=missing_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t6_dir,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t6_dir, final_aud)
        if err_res is None or err_res.status != "failed":
            t6_errs.append("Expected status='failed' on missing original video")
        elif "Original video file not found" not in err_res.error:
            t6_errs.append(f"Unexpected error: {err_res.error}")
        results.append((6, "Missing original_video_path fail-fast", len(t6_errs) == 0, t6_errs))

        # =====================================================================
        # TEST 7: Output overwrite input protection (output == original_video)
        # =====================================================================
        t7_errs = []
        t7_dir = os.path.join(test_root, "t7")
        os.makedirs(t7_dir, exist_ok=True)
        in_vid = os.path.join(t7_dir, "sample.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t7_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=in_vid,  # Same as input
            workspace_dir=t7_dir,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t7_dir, final_aud)
        if err_res is None or err_res.status != "failed":
            t7_errs.append("Expected status='failed' when output overwrites input video")
        elif "cannot overwrite original_video_path" not in err_res.error:
            t7_errs.append(f"Unexpected error: {err_res.error}")
        results.append((7, "Output overwrite input protection", len(t7_errs) == 0, t7_errs))

        # =====================================================================
        # TEST 8: Output overwrite audio protection (output == final_audio)
        # =====================================================================
        t8_errs = []
        t8_dir = os.path.join(test_root, "t8")
        os.makedirs(t8_dir, exist_ok=True)
        in_vid = os.path.join(t8_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t8_dir, "final_audio.mp4")  # .mp4 naming collision
        create_pcm_wav(final_aud, 3.0)

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=final_aud,  # Same as final_audio
            workspace_dir=t8_dir,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t8_dir, final_aud)
        if err_res is None or err_res.status != "failed":
            t8_errs.append("Expected status='failed' when output overwrites final audio")
        elif "cannot overwrite final_audio_path" not in err_res.error:
            t8_errs.append(f"Unexpected error: {err_res.error}")
        results.append((8, "Output overwrite audio protection", len(t8_errs) == 0, t8_errs))

        # =====================================================================
        # TEST 9: Pre-export cancellation (Checkpoint A)
        # =====================================================================
        t9_errs = []
        t9_dir = os.path.join(test_root, "t9")
        os.makedirs(t9_dir, exist_ok=True)
        in_vid = os.path.join(t9_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t9_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)
        out_vid = os.path.join(t9_dir, "output.mp4")

        mock_export = MagicMock(spec=VideoExportService)
        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t9_dir,
            is_cancelled_func=lambda: True,  # Cancelled right at Checkpoint A
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t9_dir, final_aud)
        if err_res is None or err_res.status != "cancelled":
            t9_errs.append("Expected status='cancelled'")
        if err_res and err_res.cancelled_stage != "export":
            t9_errs.append(f"Expected cancelled_stage='export', got {err_res.cancelled_stage}")
        if mock_export.export_video.called:
            t9_errs.append("export_video() MUST NOT be called after Checkpoint A cancellation")
        results.append((9, "Pre-export cancellation (Checkpoint A)", len(t9_errs) == 0, t9_errs))

        # =====================================================================
        # TEST 10: Post-export cancellation (Checkpoint B) -> Output artifact preserved
        # =====================================================================
        t10_errs = []
        t10_dir = os.path.join(test_root, "t10")
        os.makedirs(t10_dir, exist_ok=True)
        in_vid = os.path.join(t10_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t10_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)
        out_vid = os.path.join(t10_dir, "output.mp4")

        # Fake export_video creating output.mp4 on disk
        def fake_export_video(r):
            with open(out_vid, "wb") as f:
                f.write(b"FINAL_RENDERED_MP4_BYTES")
            return VideoExportResult(
                output_video_path=out_vid,
                video_duration=3.0,
                audio_duration=3.0,
                final_video_duration=3.0,
                rendered_subtitles_count=1,
                status="success",
            )

        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.side_effect = fake_export_video

        # Triggers cancellation only after export finishes (2nd invocation of cancelled_func)
        call_count_10 = {"count": 0}
        def cancel_at_checkpoint_b():
            call_count_10["count"] += 1
            return call_count_10["count"] >= 2  # False at Checkpoint A, True at Checkpoint B

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t10_dir,
            is_cancelled_func=cancel_at_checkpoint_b,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t10_dir, final_aud)
        if err_res is None or err_res.status != "cancelled":
            t10_errs.append("Expected status='cancelled'")
        if err_res and err_res.cancelled_stage != "export":
            t10_errs.append(f"Expected cancelled_stage='export', got {err_res.cancelled_stage}")
        # Invariant 6: Output artifact must remain preserved on disk
        if not os.path.isfile(out_vid):
            t10_errs.append("Output video must be preserved on disk after Post-export cancellation")
        results.append((10, "Post-export cancellation (Checkpoint B)", len(t10_errs) == 0, t10_errs))

        # =====================================================================
        # TEST 11: Master Data immutability
        # =====================================================================
        t11_errs = []
        t11_dir = os.path.join(test_root, "t11")
        os.makedirs(t11_dir, exist_ok=True)
        in_vid = os.path.join(t11_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t11_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)
        out_vid = os.path.join(t11_dir, "output.mp4")

        seg1 = make_test_segment(1, 0.5, 2.0)
        seg2 = make_test_segment(2, 2.5, 4.0)
        orig_segs = [copy.deepcopy(seg1), copy.deepcopy(seg2)]

        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.return_value = VideoExportResult(status="success", output_video_path=out_vid)

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[seg1, seg2],
            output_video_path=out_vid,
            workspace_dir=t11_dir,
        )
        svc._orchestrate_export(req, t11_dir, final_aud)

        for s_curr, s_orig in zip([seg1, seg2], orig_segs):
            if s_curr != s_orig:
                t11_errs.append("SubtitleSegment mutated during export orchestration")
        results.append((11, "Master Data immutability", len(t11_errs) == 0, t11_errs))

        # =====================================================================
        # TEST 12: Metrics recording (3 durations + subtitle counts)
        # =====================================================================
        t12_errs = []
        t12_dir = os.path.join(test_root, "t12")
        os.makedirs(t12_dir, exist_ok=True)
        in_vid = os.path.join(t12_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t12_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 6.0)
        out_vid = os.path.join(t12_dir, "output.mp4")

        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.return_value = VideoExportResult(
            output_video_path=out_vid,
            video_duration=5.0,
            audio_duration=6.0,
            final_video_duration=6.0,
            rendered_subtitles_count=3,
            skipped_subtitles_count=1,
            status="success",
        )

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t12_dir,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t12_dir, final_aud)
        if export_res:
            if export_res.video_duration != 5.0:
                t12_errs.append(f"video_duration mismatch: {export_res.video_duration}")
            if export_res.audio_duration != 6.0:
                t12_errs.append(f"audio_duration mismatch: {export_res.audio_duration}")
            if export_res.final_video_duration != 6.0:
                t12_errs.append(f"final_video_duration mismatch: {export_res.final_video_duration}")
            if export_res.rendered_subtitles_count != 3:
                t12_errs.append(f"rendered_count mismatch: {export_res.rendered_subtitles_count}")
            if export_res.skipped_subtitles_count != 1:
                t12_errs.append(f"skipped_count mismatch: {export_res.skipped_subtitles_count}")
        results.append((12, "Metrics recording (3 durations + sub counts)", len(t12_errs) == 0, t12_errs))

        # =====================================================================
        # TEST 13: Warning propagation
        # =====================================================================
        t13_errs = []
        t13_dir = os.path.join(test_root, "t13")
        os.makedirs(t13_dir, exist_ok=True)
        in_vid = os.path.join(t13_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t13_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 7.0)
        out_vid = os.path.join(t13_dir, "output.mp4")

        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.return_value = VideoExportResult(
            output_video_path=out_vid,
            status="success",
            warning="Audio duration (7.00s) exceeds video duration (5.00s). Video extended with freeze frame.",
        )

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t13_dir,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t13_dir, final_aud)
        if not any("exceeds video duration" in w for w in warns):
            t13_errs.append(f"Expected warning in warnings, got: {warns}")
        results.append((13, "Warning propagation", len(t13_errs) == 0, t13_errs))

        # =====================================================================
        # TEST 14: Progress monotonic (75% -> 95%)
        # =====================================================================
        t14_errs = []
        t14_dir = os.path.join(test_root, "t14")
        os.makedirs(t14_dir, exist_ok=True)
        in_vid = os.path.join(t14_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t14_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)
        out_vid = os.path.join(t14_dir, "output.mp4")

        recorded_prog = []
        def on_prog(pct, msg):
            recorded_prog.append((pct, msg))

        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.return_value = VideoExportResult(
            output_video_path=out_vid,
            final_video_duration=3.0,
            status="success",
        )

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t14_dir,
            progress_callback=on_prog,
        )
        svc._orchestrate_export(req, t14_dir, final_aud)
        pcts = [p[0] for p in recorded_prog]
        if not pcts:
            t14_errs.append("No progress recorded")
        else:
            if pcts[0] != 75.0:
                t14_errs.append(f"Expected start progress 75.0%, got {pcts[0]}")
            if pcts[-1] != 95.0:
                t14_errs.append(f"Expected end progress 95.0%, got {pcts[-1]}")
            if pcts != sorted(pcts):
                t14_errs.append(f"Progress not monotonic: {pcts}")
        results.append((14, "Progress monotonic (75% -> 95%)", len(t14_errs) == 0, t14_errs))

        # =====================================================================
        # TEST 15: Unexpected export exception handling
        # =====================================================================
        t15_errs = []
        t15_dir = os.path.join(test_root, "t15")
        os.makedirs(t15_dir, exist_ok=True)
        in_vid = os.path.join(t15_dir, "input.mp4")
        with open(in_vid, "wb") as f: f.write(b"SAMPLE_VIDEO_DATA")
        final_aud = os.path.join(t15_dir, "final_audio.wav")
        create_pcm_wav(final_aud, 3.0)
        out_vid = os.path.join(t15_dir, "output.mp4")

        mock_export = MagicMock(spec=VideoExportService)
        mock_export.export_video.side_effect = RuntimeError("FFmpeg encoding crash: out of memory")

        svc = VideoCreatorService(video_export_service=mock_export)
        req = VideoCreatorRequest(
            original_video_path=in_vid,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=out_vid,
            workspace_dir=t15_dir,
        )
        export_res, warns, err_res = svc._orchestrate_export(req, t15_dir, final_aud)
        if err_res is None or err_res.status != "failed":
            t15_errs.append("Expected status='failed' when export raises exception")
        elif "Video export failed with exception: FFmpeg encoding crash" not in err_res.error:
            t15_errs.append(f"Unexpected error message: {err_res.error}")
        results.append((15, "Unexpected export exception", len(t15_errs) == 0, t15_errs))

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
    print(f"KẾT QUẢ ACCEPTANCE STEP 8.3.6: {passed_count}/{len(results)} TESTS PASS")
    print("=" * 80)
    return passed_count == len(results)


if __name__ == "__main__":
    success = run_all_acceptance_tests()
    sys.exit(0 if success else 1)
