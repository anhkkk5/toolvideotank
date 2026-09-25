"""Bộ Test Acceptance 16 Trường Hợp: Bước 8.3.8 — Cancellation & Progress Finalization.

Tuân thủ nghiêm ngặt Contract Step 8.3.8 v1.1 LOCKED:
- Ma trận 6 Checkpoint Cancellation (Preflight, Mapping, TTS, Mixing, Export, Verification)
- Công thức TTS Progress chuẩn hóa: p = 5.0 + 50.0 * (k / N)
- Monotonic Progress (0% -> 100%) và bất biến mốc 100%
- Ngữ nghĩa trạng thái kết thúc (Terminal States) và error="" trên cancelled
- Ngữ nghĩa đường dẫn artifact (chỉ trả path khi file thực sự tồn tại/bảo tồn)
- Quy chuẩn bảo tồn Level 1, Level 2, Level 3
- Miễn nhiễm ngoại lệ Callback
"""

import os
import shutil
import struct
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
from app.services.audio_mixing_service import AudioMixingService, MixedAudioResult, TTSAudioBlock
from app.services.duration_fitting_service import FittedAudioResult, DurationFittingService
from app.services.original_audio_extractor import OriginalAudioExtractor
from app.services.tts_backend import TTSResult
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
)
from app.services.video_export_service import (
    VideoExportRequest,
    VideoExportResult,
    VideoExportService,
)
from app.services.voiceover_service import VoiceoverService


def create_pcm_wav(file_path: str, duration_sec: float, sample_rate: int = 44100, channels: int = 2) -> None:
    """Tạo file WAV PCM 16-bit stereo chuẩn hóa."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    num_samples = int(sample_rate * duration_sec)
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        raw_frame = struct.pack("<hh", 500, -500) if channels == 2 else struct.pack("<h", 500)
        wf.writeframes(raw_frame * num_samples)


def make_test_segment(
    seg_id: int,
    start: float,
    end: float,
    translated_text: str = "Xin chào các bạn",
    final_gender: str = "male",
    is_noise: bool = False,
    skip_tts: bool = False,
) -> SubtitleSegment:
    """Tạo subtitle segment cho test."""
    return SubtitleSegment(
        id=seg_id,
        start=start,
        end=end,
        text=f"Text {seg_id}",
        translated_text=translated_text,
        final_gender=final_gender,
        is_noise=is_noise,
        skip_tts=skip_tts,
    )


def standard_h264_aac_prober(file_path: str) -> tuple[bool, list[dict[str, Any]], str]:
    """Mock ffprobe trả về H.264 video và AAC stereo audio."""
    streams = [
        {"codec_type": "video", "codec_name": "h264", "duration": "5.0"},
        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2, "duration": "5.0"},
    ]
    return True, streams, ""


def run_acceptance_838() -> int:
    print("=" * 80)
    print("     CAPCAP STEP 8.3.8 — CANCELLATION & PROGRESS FINALIZATION (16 TESTS)")
    print("=" * 80)

    test_root = os.path.join(tempfile.gettempdir(), "capcap_step838_acceptance")
    if os.path.isdir(test_root):
        try:
            shutil.rmtree(test_root)
        except Exception:
            pass
    os.makedirs(test_root, exist_ok=True)

    results: list[tuple[int, str, bool, list[str]]] = []

    # =========================================================================
    # TEST 1: Cancel Preflight Early -> cancelled_stage="preflight", error="", paths=""
    # =========================================================================
    t1_errs = []
    t1_dir = os.path.join(test_root, "t1")
    os.makedirs(t1_dir, exist_ok=True)
    in_vid = os.path.join(t1_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t1_dir, "output.mp4")

    progress_events_1: list[float] = []
    svc1 = VideoCreatorService()
    req1 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        is_cancelled_func=lambda: True,  # Hủy ngay lập tức
        progress_callback=lambda p, msg: progress_events_1.append(p),
    )
    res1 = svc1.run(req1)

    if res1.status != "cancelled":
        t1_errs.append(f"Expected status='cancelled', got '{res1.status}'")
    if res1.cancelled_stage != "preflight":
        t1_errs.append(f"Expected cancelled_stage='preflight', got '{res1.cancelled_stage}'")
    if res1.error != "":
        t1_errs.append(f"Expected error='', got '{res1.error}'")
    if res1.output_video_path != "":
        t1_errs.append(f"Expected output_video_path='', got '{res1.output_video_path}'")
    if res1.output_audio_path != "":
        t1_errs.append(f"Expected output_audio_path='', got '{res1.output_audio_path}'")
    if 100.0 in progress_events_1:
        t1_errs.append("Progress 100.0% MUST NOT be emitted on cancellation")
    results.append((1, "Cancel Preflight Early", len(t1_errs) == 0, t1_errs))

    # =========================================================================
    # TEST 2: Cancel Preflight Late -> cancelled_stage="preflight", error=""
    # =========================================================================
    t2_errs = []
    t2_dir = os.path.join(test_root, "t2")
    os.makedirs(t2_dir, exist_ok=True)
    in_vid = os.path.join(t2_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t2_dir, "output.mp4")

    # Hủy ở lần gọi thứ 2 của is_cancelled_func trong preflight
    call_cnt_2 = {"cnt": 0}
    def cancel_late_preflight():
        call_cnt_2["cnt"] += 1
        return call_cnt_2["cnt"] >= 2

    progress_events_2: list[float] = []
    svc2 = VideoCreatorService()
    req2 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        is_cancelled_func=cancel_late_preflight,
        progress_callback=lambda p, msg: progress_events_2.append(p),
    )
    res2 = svc2.run(req2)

    if res2.status != "cancelled":
        t2_errs.append(f"Expected status='cancelled', got '{res2.status}'")
    if res2.cancelled_stage != "preflight":
        t2_errs.append(f"Expected cancelled_stage='preflight', got '{res2.cancelled_stage}'")
    if res2.error != "":
        t2_errs.append(f"Expected error='', got '{res2.error}'")
    if res2.output_video_path != "":
        t2_errs.append(f"Expected output_video_path='', got '{res2.output_video_path}'")
    if 100.0 in progress_events_2:
        t2_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((2, "Cancel Preflight Late", len(t2_errs) == 0, t2_errs))

    # =========================================================================
    # TEST 3: Cancel Pre-Mapping -> cancelled_stage="mapping", error=""
    # =========================================================================
    t3_errs = []
    t3_dir = os.path.join(test_root, "t3")
    os.makedirs(t3_dir, exist_ok=True)
    in_vid = os.path.join(t3_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t3_dir, "output.mp4")

    # Pass preflight (2 checks), cancel right at Pre-Mapping
    call_cnt_3 = {"cnt": 0}
    def cancel_at_pre_mapping():
        call_cnt_3["cnt"] += 1
        return call_cnt_3["cnt"] > 2

    progress_events_3: list[float] = []
    mock_tts3 = MagicMock(spec=VoiceoverService)
    svc3 = VideoCreatorService(voiceover_service=mock_tts3)
    req3 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        workspace_dir=t3_dir,
        is_cancelled_func=cancel_at_pre_mapping,
        progress_callback=lambda p, msg: progress_events_3.append(p),
    )
    res3 = svc3.run(req3)

    if res3.status != "cancelled":
        t3_errs.append(f"Expected status='cancelled', got '{res3.status}'")
    if res3.cancelled_stage != "mapping":
        t3_errs.append(f"Expected cancelled_stage='mapping', got '{res3.cancelled_stage}'")
    if res3.error != "":
        t3_errs.append(f"Expected error='', got '{res3.error}'")
    if res3.output_video_path != "":
        t3_errs.append(f"Expected output_video_path='', got '{res3.output_video_path}'")
    if mock_tts3.generate.called:
        t3_errs.append("TTS MUST NOT be called after mapping cancellation")
    if 100.0 in progress_events_3:
        t3_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((3, "Cancel Pre-Mapping", len(t3_errs) == 0, t3_errs))

    # =========================================================================
    # TEST 4: Cancel Post-Mapping -> cancelled_stage="mapping", error=""
    # =========================================================================
    t4_errs = []
    t4_dir = os.path.join(test_root, "t4")
    os.makedirs(t4_dir, exist_ok=True)
    in_vid = os.path.join(t4_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t4_dir, "output.mp4")

    # Pass preflight (2 checks) + pre-mapping (1 check), cancel at post-mapping (check 4)
    call_cnt_4 = {"cnt": 0}
    def cancel_at_post_mapping():
        call_cnt_4["cnt"] += 1
        return call_cnt_4["cnt"] >= 4

    progress_events_4: list[float] = []
    svc4 = VideoCreatorService()
    req4 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        workspace_dir=t4_dir,
        is_cancelled_func=cancel_at_post_mapping,
        progress_callback=lambda p, msg: progress_events_4.append(p),
    )
    res4 = svc4.run(req4)

    if res4.status != "cancelled":
        t4_errs.append(f"Expected status='cancelled', got '{res4.status}'")
    if res4.cancelled_stage != "mapping":
        t4_errs.append(f"Expected cancelled_stage='mapping', got '{res4.cancelled_stage}'")
    if res4.error != "":
        t4_errs.append(f"Expected error='', got '{res4.error}'")
    # Khi cancel ở post-mapping, progress 5.0% chưa được phát ra
    if 5.0 in progress_events_4:
        t4_errs.append("Progress 5.0% MUST NOT be emitted if post-mapping is cancelled")
    if 100.0 in progress_events_4:
        t4_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((4, "Cancel Post-Mapping", len(t4_errs) == 0, t4_errs))

    # =========================================================================
    # TEST 5: Cancel TTS Pre-segment -> cancelled_stage="tts", error=""
    # =========================================================================
    t5_errs = []
    t5_dir = os.path.join(test_root, "t5")
    os.makedirs(t5_dir, exist_ok=True)
    in_vid = os.path.join(t5_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t5_dir, "output.mp4")

    # 2 segments: segment 1 thành công, cancel trước segment 2
    seg1 = make_test_segment(1, 0.0, 2.0)
    seg2 = make_test_segment(2, 2.0, 4.0)

    # Fake TTS và Fitting
    def fake_generate_5(segment_id, translated_text, start, end, voice_id, is_noise, skip_tts, output_path):
        create_pcm_wav(output_path, 2.0)
        return TTSResult(segment_id=segment_id, voice_id=voice_id, audio_path=output_path, duration=2.0, status="success", error="")

    def fake_fit_5(segment_id, raw_audio_path, slot_duration, output_path):
        create_pcm_wav(output_path, slot_duration)
        return FittedAudioResult(
            segment_id=segment_id,
            raw_audio_path=raw_audio_path,
            raw_duration=slot_duration,
            fitted_audio_path=output_path,
            fitted_duration=slot_duration,
            status="success",
        )

    mock_vo5 = MagicMock(spec=VoiceoverService)
    mock_vo5.generate.side_effect = fake_generate_5
    mock_fit5 = MagicMock(spec=DurationFittingService)
    mock_fit5.fit_segment.side_effect = fake_fit_5

    cancel_call_5 = {"cnt": 0}
    def cancel_before_seg2():
        cancel_call_5["cnt"] += 1
        # Preflight (2) + Pre-mapping (1) + Post-mapping (1) + Pre-seg1 (1) + Post-seg1 (1) + Pre-seg2 (1)
        return cancel_call_5["cnt"] >= 7

    progress_events_5: list[float] = []
    svc5 = VideoCreatorService(voiceover_service=mock_vo5, duration_fitting_service=mock_fit5)
    req5 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[seg1, seg2],
        output_video_path=out_vid,
        workspace_dir=t5_dir,
        is_cancelled_func=cancel_before_seg2,
        progress_callback=lambda p, msg: progress_events_5.append(p),
    )
    res5 = svc5.run(req5)

    if res5.status != "cancelled":
        t5_errs.append(f"Expected status='cancelled', got '{res5.status}'")
    if res5.cancelled_stage != "tts":
        t5_errs.append(f"Expected cancelled_stage='tts', got '{res5.cancelled_stage}'")
    if res5.error != "":
        t5_errs.append(f"Expected error='', got '{res5.error}'")
    if res5.tts_generated_count != 1:
        t5_errs.append(f"Expected tts_generated_count=1, got {res5.tts_generated_count}")
    # File raw và fitted của seg 1 bảo tồn trên đĩa
    seg1_raw = os.path.join(t5_dir, "raw_tts", "segment_0001.wav")
    seg1_fit = os.path.join(t5_dir, "fitted_tts", "segment_0001_fit.wav")
    if not os.path.isfile(seg1_raw) or not os.path.isfile(seg1_fit):
        t5_errs.append("Audio artifacts of segment 1 must be preserved on disk")
    if 100.0 in progress_events_5:
        t5_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((5, "Cancel TTS Pre-segment", len(t5_errs) == 0, t5_errs))

    # =========================================================================
    # TEST 6: Cancel TTS Post-segment -> cancelled_stage="tts", error=""
    # =========================================================================
    t6_errs = []
    t6_dir = os.path.join(test_root, "t6")
    os.makedirs(t6_dir, exist_ok=True)
    in_vid = os.path.join(t6_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t6_dir, "output.mp4")

    mock_vo6 = MagicMock(spec=VoiceoverService)
    mock_vo6.generate.side_effect = fake_generate_5
    mock_fit6 = MagicMock(spec=DurationFittingService)
    mock_fit6.fit_segment.side_effect = fake_fit_5

    cancel_call_6 = {"cnt": 0}
    def cancel_at_post_seg1():
        cancel_call_6["cnt"] += 1
        # Hủy tại Checkpoint 3.6 (Post-segment 1): lần gọi thứ 6
        return cancel_call_6["cnt"] >= 6

    progress_events_6: list[float] = []
    svc6 = VideoCreatorService(voiceover_service=mock_vo6, duration_fitting_service=mock_fit6)
    req6 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[seg1, seg2],
        output_video_path=out_vid,
        workspace_dir=t6_dir,
        is_cancelled_func=cancel_at_post_seg1,
        progress_callback=lambda p, msg: progress_events_6.append(p),
    )
    res6 = svc6.run(req6)

    if res6.status != "cancelled":
        t6_errs.append(f"Expected status='cancelled', got '{res6.status}'")
    if res6.cancelled_stage != "tts":
        t6_errs.append(f"Expected cancelled_stage='tts', got '{res6.cancelled_stage}'")
    if res6.error != "":
        t6_errs.append(f"Expected error='', got '{res6.error}'")
    if mock_vo6.generate.call_count != 1:
        t6_errs.append(f"Expected generate() called once, got {mock_vo6.generate.call_count}")
    if 100.0 in progress_events_6:
        t6_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((6, "Cancel TTS Post-segment", len(t6_errs) == 0, t6_errs))

    # =========================================================================
    # TEST 7: TTS Progress Exact Formula (p = 5.0 + 50.0 * (k / N))
    # =========================================================================
    t7_errs = []
    t7_dir = os.path.join(test_root, "t7")
    os.makedirs(t7_dir, exist_ok=True)
    in_vid = os.path.join(t7_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t7_dir, "output.mp4")

    # 4 segments: N = 4
    segs_4 = [
        make_test_segment(1, 0.0, 1.0),
        make_test_segment(2, 1.0, 2.0),
        make_test_segment(3, 2.0, 3.0),
        make_test_segment(4, 3.0, 4.0),
    ]

    mock_vo7 = MagicMock(spec=VoiceoverService)
    mock_vo7.generate.side_effect = fake_generate_5
    mock_fit7 = MagicMock(spec=DurationFittingService)
    mock_fit7.fit_segment.side_effect = fake_fit_5

    # Mock mixing, export, verification prober to let it finish
    def fake_extract_7(vid, out):
        create_pcm_wav(out, 4.0)
        return True, ""
    mock_ext7 = MagicMock(spec=OriginalAudioExtractor)
    mock_ext7.extract.side_effect = fake_extract_7

    def fake_mix_7(original_audio_path, tts_blocks, output_path):
        create_pcm_wav(output_path, 4.0)
        return MixedAudioResult(final_audio_path=output_path, total_duration=4.0, status="success")
    mock_mix7 = MagicMock(spec=AudioMixingService)
    mock_mix7.mix.side_effect = fake_mix_7

    def fake_export_7(r):
        create_pcm_wav(r.output_video_path, 4.0)
        return VideoExportResult(
            output_video_path=r.output_video_path,
            video_duration=4.0,
            audio_duration=4.0,
            final_video_duration=4.0,
            rendered_subtitles_count=len(r.segments),
            skipped_subtitles_count=0,
            status="success",
        )
    mock_exp7 = MagicMock(spec=VideoExportService)
    mock_exp7.export_video.side_effect = fake_export_7

    progress_events_7: list[float] = []
    svc7 = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext7,
        audio_mixing_service=mock_mix7,
        video_export_service=mock_exp7,
        stream_prober=standard_h264_aac_prober,
    )
    req7 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=segs_4,
        output_video_path=out_vid,
        workspace_dir=t7_dir,
        progress_callback=lambda p, msg: progress_events_7.append(round(p, 2)),
    )
    res7 = svc7.run(req7)

    if res7.status != "success":
        t7_errs.append(f"Expected status='success', got '{res7.status}', error='{res7.error}'")

    # Kiểm tra các mốc TTS cụ thể:
    # N=4 -> k=0: 5.0%, k=1: 17.5%, k=2: 30.0%, k=3: 42.5%, k=4: 55.0%
    expected_tts_milestones = [5.0, 17.5, 30.0, 42.5, 55.0]
    for em in expected_tts_milestones:
        if em not in progress_events_7:
            t7_errs.append(f"Expected progress milestone {em}% not found in events: {progress_events_7}")

    # Khẳng định tiến độ sau segment cuối cùng phát đúng 55.0%
    if 55.0 not in progress_events_7:
        t7_errs.append(f"55.0% must be emitted after final segment, got: {progress_events_7}")
    results.append((7, "TTS Progress Exact Formula", len(t7_errs) == 0, t7_errs))

    # =========================================================================
    # TEST 8: Cancel Mixing Checkpoint A (Pre-preparation) -> cancelled_stage="mixing"
    # =========================================================================
    t8_errs = []
    t8_dir = os.path.join(test_root, "t8")
    os.makedirs(t8_dir, exist_ok=True)
    in_vid = os.path.join(t8_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t8_dir, "output.mp4")

    mock_ext8 = MagicMock(spec=OriginalAudioExtractor)
    mock_mix8 = MagicMock(spec=AudioMixingService)

    # Cancel right at Checkpoint A of mixing
    cancel_cnt_8 = {"cnt": 0}
    def cancel_at_mixing_a():
        cancel_cnt_8["cnt"] += 1
        # Preflight(2) + PreMap(1) + PostMap(1) + PreSeg(1) + PostSeg(1) + MixCheckpointA(1) = 7
        return cancel_cnt_8["cnt"] >= 7

    progress_events_8: list[float] = []
    svc8 = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext8,
        audio_mixing_service=mock_mix8,
    )
    req8 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        workspace_dir=t8_dir,
        is_cancelled_func=cancel_at_mixing_a,
        progress_callback=lambda p, msg: progress_events_8.append(p),
    )
    res8 = svc8.run(req8)

    if res8.status != "cancelled":
        t8_errs.append(f"Expected status='cancelled', got '{res8.status}'")
    if res8.cancelled_stage != "mixing":
        t8_errs.append(f"Expected cancelled_stage='mixing', got '{res8.cancelled_stage}'")
    if res8.error != "":
        t8_errs.append(f"Expected error='', got '{res8.error}'")
    if res8.output_audio_path != "":
        t8_errs.append(f"Expected output_audio_path='', got '{res8.output_audio_path}'")
    if mock_ext8.extract.called:
        t8_errs.append("Extractor MUST NOT be called after Checkpoint A cancellation")
    if mock_mix8.mix.called:
        t8_errs.append("AudioMixingService MUST NOT be called")
    if 100.0 in progress_events_8:
        t8_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((8, "Cancel Mixing Checkpoint A", len(t8_errs) == 0, t8_errs))

    # =========================================================================
    # TEST 9: Cancel Mixing Checkpoint B (Pre-mixing) -> cancelled_stage="mixing"
    # =========================================================================
    t9_errs = []
    t9_dir = os.path.join(test_root, "t9")
    os.makedirs(t9_dir, exist_ok=True)
    in_vid = os.path.join(t9_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t9_dir, "output.mp4")

    def fake_extract_9(vid, out):
        create_pcm_wav(out, 2.0)
        return True, ""
    mock_ext9 = MagicMock(spec=OriginalAudioExtractor)
    mock_ext9.extract.side_effect = fake_extract_9
    mock_mix9 = MagicMock(spec=AudioMixingService)

    cancel_cnt_9 = {"cnt": 0}
    def cancel_at_mixing_b():
        cancel_cnt_9["cnt"] += 1
        # Preflight(2) + PreMap(1) + PostMap(1) + PreSeg(1) + PostSeg(1) + MixA(1) + MixB(1) = 8
        return cancel_cnt_9["cnt"] >= 8

    progress_events_9: list[float] = []
    svc9 = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext9,
        audio_mixing_service=mock_mix9,
    )
    req9 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        workspace_dir=t9_dir,
        is_cancelled_func=cancel_at_mixing_b,
        progress_callback=lambda p, msg: progress_events_9.append(p),
    )
    res9 = svc9.run(req9)

    if res9.status != "cancelled":
        t9_errs.append(f"Expected status='cancelled', got '{res9.status}'")
    if res9.cancelled_stage != "mixing":
        t9_errs.append(f"Expected cancelled_stage='mixing', got '{res9.cancelled_stage}'")
    if res9.error != "":
        t9_errs.append(f"Expected error='', got '{res9.error}'")
    if res9.output_audio_path != "":
        t9_errs.append(f"Expected output_audio_path='', got '{res9.output_audio_path}'")
    if not mock_ext9.extract.called:
        t9_errs.append("Extractor SHOULD be called before Checkpoint B")
    if mock_mix9.mix.called:
        t9_errs.append("AudioMixingService MUST NOT be called after Checkpoint B cancellation")
    # File extracted audio được bảo tồn
    extracted_wav_path = os.path.join(t9_dir, "extracted_original_audio.wav")
    if not os.path.isfile(extracted_wav_path):
        t9_errs.append("extracted_original_audio.wav must be preserved on disk")
    if 100.0 in progress_events_9:
        t9_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((9, "Cancel Mixing Checkpoint B", len(t9_errs) == 0, t9_errs))

    # =========================================================================
    # TEST 10: Cancel Mixing Checkpoint C (Post-mixing) -> final_audio.wav preserved
    # =========================================================================
    t10_errs = []
    t10_dir = os.path.join(test_root, "t10")
    os.makedirs(t10_dir, exist_ok=True)
    in_vid = os.path.join(t10_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t10_dir, "output.mp4")

    mock_ext10 = MagicMock(spec=OriginalAudioExtractor)
    mock_ext10.extract.side_effect = fake_extract_7
    mock_mix10 = MagicMock(spec=AudioMixingService)
    mock_mix10.mix.side_effect = fake_mix_7
    mock_exp10 = MagicMock(spec=VideoExportService)

    cancel_cnt_10 = {"cnt": 0}
    def cancel_at_mixing_c():
        cancel_cnt_10["cnt"] += 1
        # Preflight(2) + PreMap(1) + PostMap(1) + PreSeg(1) + PostSeg(1) + MixA(1) + MixB(1) + MixC(1) = 9
        return cancel_cnt_10["cnt"] >= 9

    progress_events_10: list[float] = []
    svc10 = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext10,
        audio_mixing_service=mock_mix10,
        video_export_service=mock_exp10,
    )
    req10 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        workspace_dir=t10_dir,
        is_cancelled_func=cancel_at_mixing_c,
        progress_callback=lambda p, msg: progress_events_10.append(p),
    )
    res10 = svc10.run(req10)

    if res10.status != "cancelled":
        t10_errs.append(f"Expected status='cancelled', got '{res10.status}'")
    if res10.cancelled_stage != "mixing":
        t10_errs.append(f"Expected cancelled_stage='mixing', got '{res10.cancelled_stage}'")
    if res10.error != "":
        t10_errs.append(f"Expected error='', got '{res10.error}'")
    final_aud_10 = os.path.join(t10_dir, "final_audio.wav")
    if res10.output_audio_path != final_aud_10:
        t10_errs.append(f"Expected output_audio_path='{final_aud_10}', got '{res10.output_audio_path}'")
    if not os.path.isfile(final_aud_10):
        t10_errs.append("final_audio.wav must exist on disk after Checkpoint C cancellation")
    if res10.output_video_path != "":
        t10_errs.append(f"Expected output_video_path='', got '{res10.output_video_path}'")
    if mock_exp10.export_video.called:
        t10_errs.append("VideoExportService MUST NOT be called after Checkpoint C cancellation")
    if 100.0 in progress_events_10:
        t10_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((10, "Cancel Mixing Checkpoint C", len(t10_errs) == 0, t10_errs))

    # =========================================================================
    # TEST 11: Cancel Export Pre-FFmpeg (Checkpoint A) -> output_video_path=""
    # =========================================================================
    t11_errs = []
    t11_dir = os.path.join(test_root, "t11")
    os.makedirs(t11_dir, exist_ok=True)
    in_vid = os.path.join(t11_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t11_dir, "output.mp4")

    mock_ext11 = MagicMock(spec=OriginalAudioExtractor)
    mock_ext11.extract.side_effect = fake_extract_7
    mock_mix11 = MagicMock(spec=AudioMixingService)
    mock_mix11.mix.side_effect = fake_mix_7
    mock_exp11 = MagicMock(spec=VideoExportService)

    cancel_cnt_11 = {"cnt": 0}
    def cancel_at_export_a():
        cancel_cnt_11["cnt"] += 1
        # Preflight(2) + PreMap(1) + PostMap(1) + PreSeg(1) + PostSeg(1) + MixA(1) + MixB(1) + MixC(1) + ExpA(1) = 10
        return cancel_cnt_11["cnt"] >= 10

    progress_events_11: list[float] = []
    svc11 = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext11,
        audio_mixing_service=mock_mix11,
        video_export_service=mock_exp11,
    )
    req11 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        workspace_dir=t11_dir,
        is_cancelled_func=cancel_at_export_a,
        progress_callback=lambda p, msg: progress_events_11.append(p),
    )
    res11 = svc11.run(req11)

    if res11.status != "cancelled":
        t11_errs.append(f"Expected status='cancelled', got '{res11.status}'")
    if res11.cancelled_stage != "export":
        t11_errs.append(f"Expected cancelled_stage='export', got '{res11.cancelled_stage}'")
    if res11.error != "":
        t11_errs.append(f"Expected error='', got '{res11.error}'")
    if res11.output_video_path != "":
        t11_errs.append(f"Expected output_video_path='', got '{res11.output_video_path}'")
    final_aud_11 = os.path.join(t11_dir, "final_audio.wav")
    if res11.output_audio_path != final_aud_11:
        t11_errs.append(f"output_audio_path should preserve final_audio.wav, got '{res11.output_audio_path}'")
    if mock_exp11.export_video.called:
        t11_errs.append("export_video MUST NOT be called after Checkpoint A cancellation")
    if 100.0 in progress_events_11:
        t11_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((11, "Cancel Export Pre-FFmpeg", len(t11_errs) == 0, t11_errs))

    # =========================================================================
    # TEST 12: Cancel Export Post-FFmpeg (Checkpoint B) -> output_video.mp4 preserved
    # =========================================================================
    t12_errs = []
    t12_dir = os.path.join(test_root, "t12")
    os.makedirs(t12_dir, exist_ok=True)
    in_vid = os.path.join(t12_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t12_dir, "output.mp4")

    mock_ext12 = MagicMock(spec=OriginalAudioExtractor)
    mock_ext12.extract.side_effect = fake_extract_7
    mock_mix12 = MagicMock(spec=AudioMixingService)
    mock_mix12.mix.side_effect = fake_mix_7

    def fake_export_12(r):
        create_pcm_wav(out_vid, 2.0)
        return VideoExportResult(output_video_path=out_vid, video_duration=2.0, audio_duration=2.0, final_video_duration=2.0, rendered_subtitles_count=1, status="success")
    mock_exp12 = MagicMock(spec=VideoExportService)
    mock_exp12.export_video.side_effect = fake_export_12

    cancel_cnt_12 = {"cnt": 0}
    def cancel_at_export_b():
        cancel_cnt_12["cnt"] += 1
        # Checkpoint B của Export là lần gọi thứ 11
        return cancel_cnt_12["cnt"] >= 11

    progress_events_12: list[float] = []
    svc12 = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext12,
        audio_mixing_service=mock_mix12,
        video_export_service=mock_exp12,
    )
    req12 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        workspace_dir=t12_dir,
        is_cancelled_func=cancel_at_export_b,
        progress_callback=lambda p, msg: progress_events_12.append(p),
    )
    res12 = svc12.run(req12)

    if res12.status != "cancelled":
        t12_errs.append(f"Expected status='cancelled', got '{res12.status}'")
    if res12.cancelled_stage != "export":
        t12_errs.append(f"Expected cancelled_stage='export', got '{res12.cancelled_stage}'")
    if res12.error != "":
        t12_errs.append(f"Expected error='', got '{res12.error}'")
    if res12.output_video_path != out_vid:
        t12_errs.append(f"Expected output_video_path='{out_vid}', got '{res12.output_video_path}'")
    if not os.path.isfile(out_vid):
        t12_errs.append("output_video.mp4 MUST be preserved on disk")
    if 100.0 in progress_events_12:
        t12_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((12, "Cancel Export Post-FFmpeg", len(t12_errs) == 0, t12_errs))

    # =========================================================================
    # TEST 13: Cancel Verification Checkpoint -> Level 2 not cleaned, artifacts kept
    # =========================================================================
    t13_errs = []
    t13_dir = os.path.join(test_root, "t13")
    os.makedirs(t13_dir, exist_ok=True)
    in_vid = os.path.join(t13_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t13_dir, "output.mp4")

    mock_ext13 = MagicMock(spec=OriginalAudioExtractor)
    mock_ext13.extract.side_effect = fake_extract_7
    mock_mix13 = MagicMock(spec=AudioMixingService)
    mock_mix13.mix.side_effect = fake_mix_7
    mock_exp13 = MagicMock(spec=VideoExportService)
    mock_exp13.export_video.side_effect = fake_export_12

    cancel_cnt_13 = {"cnt": 0}
    def cancel_at_verification():
        cancel_cnt_13["cnt"] += 1
        # Pre-verification Checkpoint là lần gọi thứ 12
        return cancel_cnt_13["cnt"] >= 12

    progress_events_13: list[float] = []
    svc13 = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext13,
        audio_mixing_service=mock_mix13,
        video_export_service=mock_exp13,
        stream_prober=standard_h264_aac_prober,
    )
    req13 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        workspace_dir=t13_dir,
        config=VideoCreatorConfig(cleanup_intermediate_audio=True),  # Yêu cầu dọn dẹp
        is_cancelled_func=cancel_at_verification,
        progress_callback=lambda p, msg: progress_events_13.append(p),
    )
    res13 = svc13.run(req13)

    if res13.status != "cancelled":
        t13_errs.append(f"Expected status='cancelled', got '{res13.status}'")
    if res13.cancelled_stage != "verification":
        t13_errs.append(f"Expected cancelled_stage='verification', got '{res13.cancelled_stage}'")
    if res13.error != "":
        t13_errs.append(f"Expected error='', got '{res13.error}'")
    if res13.output_video_path != out_vid:
        t13_errs.append(f"Expected output_video_path='{out_vid}', got '{res13.output_video_path}'")
    # CẤM xóa Level 2 khi bị hủy
    raw_dir_13 = os.path.join(t13_dir, "raw_tts")
    fitted_dir_13 = os.path.join(t13_dir, "fitted_tts")
    ext_audio_13 = os.path.join(t13_dir, "extracted_original_audio.wav")
    if not os.path.isdir(raw_dir_13) or not os.path.isdir(fitted_dir_13) or not os.path.isfile(ext_audio_13):
        t13_errs.append("Level 2 intermediate audio MUST NOT be cleaned when cancelled at verification")
    # Level 3 artifacts preserved
    final_aud_13 = os.path.join(t13_dir, "final_audio.wav")
    if not os.path.isfile(out_vid) or not os.path.isfile(final_aud_13):
        t13_errs.append("Level 3 artifacts MUST be preserved on disk")
    if 100.0 in progress_events_13:
        t13_errs.append("Progress 100.0% MUST NOT be emitted")
    results.append((13, "Cancel Verification Checkpoint", len(t13_errs) == 0, t13_errs))

    # =========================================================================
    # TEST 14: Progress Monotonicity on Success Stream (p_k >= p_{k-1} & p_final == 100)
    # =========================================================================
    t14_errs = []
    t14_dir = os.path.join(test_root, "t14")
    os.makedirs(t14_dir, exist_ok=True)
    in_vid = os.path.join(t14_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t14_dir, "output.mp4")

    progress_events_14: list[float] = []
    svc14 = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext7,
        audio_mixing_service=mock_mix7,
        video_export_service=mock_exp7,
        stream_prober=standard_h264_aac_prober,
    )
    req14 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0), make_test_segment(2, 2.0, 4.0)],
        output_video_path=out_vid,
        workspace_dir=t14_dir,
        progress_callback=lambda p, msg: progress_events_14.append(p),
    )
    res14 = svc14.run(req14)

    if res14.status != "success":
        t14_errs.append(f"Expected status='success', got '{res14.status}', error='{res14.error}'")
    if res14.error != "":
        t14_errs.append(f"Expected error='', got '{res14.error}'")
    if res14.cancelled_stage != "":
        t14_errs.append(f"Expected cancelled_stage='', got '{res14.cancelled_stage}'")
    # Kiểm tra tính đơn điệu không giảm
    for i in range(1, len(progress_events_14)):
        if progress_events_14[i] < progress_events_14[i - 1]:
            t14_errs.append(f"Progress decreased: {progress_events_14[i-1]}% -> {progress_events_14[i]}%")
    # Mốc cuối cùng phải là 100.0%
    if not progress_events_14 or progress_events_14[-1] != 100.0:
        t14_errs.append(f"Expected final progress 100.0%, got {progress_events_14[-1] if progress_events_14 else 'empty'}")
    results.append((14, "Progress Monotonicity Success Stream", len(t14_errs) == 0, t14_errs))

    # =========================================================================
    # TEST 15: Progress Never 100% on Any Cancellation or Failure
    # =========================================================================
    t15_errs = []
    # Kịch bản 1: Failure tại Preflight (missing video)
    pe_fail_pre: list[float] = []
    req_fail_pre = VideoCreatorRequest(
        original_video_path="missing.mp4",
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path="out.mp4",
        progress_callback=lambda p, msg: pe_fail_pre.append(p),
    )
    res_fail_pre = svc14.run(req_fail_pre)
    if res_fail_pre.status != "failed" or 100.0 in pe_fail_pre:
        t15_errs.append("100% emitted on preflight failure")

    # Kịch bản 2: Failure tại TTS (TTS generate fail)
    t15_dir = os.path.join(test_root, "t15")
    os.makedirs(t15_dir, exist_ok=True)
    in_vid_15 = os.path.join(t15_dir, "input.mp4")
    with open(in_vid_15, "wb") as f: f.write(b"DATA")
    out_vid_15 = os.path.join(t15_dir, "output.mp4")

    mock_vo_fail = MagicMock(spec=VoiceoverService)
    mock_vo_fail.generate.return_value = TTSResult(segment_id=1, voice_id="v1", audio_path="", duration=0.0, status="failed", error="TTS Network Timeout")
    pe_fail_tts: list[float] = []
    svc_fail_tts = VideoCreatorService(voiceover_service=mock_vo_fail)
    req_fail_tts = VideoCreatorRequest(
        original_video_path=in_vid_15,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid_15,
        workspace_dir=t15_dir,
        progress_callback=lambda p, msg: pe_fail_tts.append(p),
    )
    res_fail_tts = svc_fail_tts.run(req_fail_tts)
    if res_fail_tts.status != "failed" or 100.0 in pe_fail_tts:
        t15_errs.append("100% emitted on TTS failure")
    if res_fail_tts.cancelled_stage != "":
        t15_errs.append("cancelled_stage must be empty on failure")
    if not res_fail_tts.error:
        t15_errs.append("error must not be empty on failure")

    # Kịch bản 3: Failure tại Verification (file container corrupt)
    t15_dir_v = os.path.join(test_root, "t15_v")
    os.makedirs(t15_dir_v, exist_ok=True)
    in_vid_15v = os.path.join(t15_dir_v, "input.mp4")
    with open(in_vid_15v, "wb") as f: f.write(b"DATA")
    out_vid_15v = os.path.join(t15_dir_v, "output.mp4")

    def corrupt_prober(file_path: str):
        return False, [], "Invalid media container header"

    pe_fail_verify: list[float] = []
    svc_fail_verify = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext7,
        audio_mixing_service=mock_mix7,
        video_export_service=mock_exp7,
        stream_prober=corrupt_prober,
    )
    req_fail_verify = VideoCreatorRequest(
        original_video_path=in_vid_15v,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid_15v,
        workspace_dir=t15_dir_v,
        progress_callback=lambda p, msg: pe_fail_verify.append(p),
    )
    res_fail_verify = svc_fail_verify.run(req_fail_verify)
    if res_fail_verify.status != "failed" or 100.0 in pe_fail_verify:
        t15_errs.append("100% emitted on verification failure")

    results.append((15, "Progress Never 100% on Cancellation / Failure", len(t15_errs) == 0, t15_errs))

    # =========================================================================
    # TEST 16: Progress Callback Exception Tolerance (Safe UI Error Handling)
    # =========================================================================
    t16_errs = []
    t16_dir = os.path.join(test_root, "t16")
    os.makedirs(t16_dir, exist_ok=True)
    in_vid = os.path.join(t16_dir, "input.mp4")
    with open(in_vid, "wb") as f: f.write(b"DATA")
    out_vid = os.path.join(t16_dir, "output.mp4")

    # Callback ném ngoại lệ Runtime Error ở mọi lần gọi
    def faulty_progress_callback(percent: float, message: str) -> None:
        raise RuntimeError(f"UI Thread Died on {percent}%: {message}")

    svc16 = VideoCreatorService(
        voiceover_service=mock_vo7,
        duration_fitting_service=mock_fit7,
        original_audio_extractor=mock_ext7,
        audio_mixing_service=mock_mix7,
        video_export_service=mock_exp7,
        stream_prober=standard_h264_aac_prober,
    )
    req16 = VideoCreatorRequest(
        original_video_path=in_vid,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid,
        workspace_dir=t16_dir,
        progress_callback=faulty_progress_callback,
    )

    try:
        res16 = svc16.run(req16)
        if res16.status != "success":
            t16_errs.append(f"Expected status='success' despite UI callback crash, got '{res16.status}'")
    except Exception as exc:
        t16_errs.append(f"Pipeline crashed due to faulty progress callback: {exc}")

    results.append((16, "Progress Callback Exception Tolerance", len(t16_errs) == 0, t16_errs))

    # =========================================================================
    # TỔNG KẾT
    # =========================================================================
    print("-" * 80)
    passed_count = sum(1 for _, _, p, _ in results if p)
    for num, name, passed, errs in results:
        status_icon = "✅ PASS" if passed else "❌ FAIL"
        print(f"[{num:02d}] {status_icon} - {name}")
        for err in errs:
            print(f"     └── ⚠️ {err}")

    print("=" * 80)
    print(f"KẾT QUẢ ACCEPTANCE STEP 8.3.8: {passed_count}/{len(results)} TESTS PASS")
    print("=" * 80)

    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(run_acceptance_838())
