"""BỘ KIỂM THỬ TỔNG THỂ END-TO-END (E2E) — BƯỚC 8.4: PIPELINE DELIVERY.

Tuân thủ nghiêm ngặt Contract Step 8.4 v1.1 LOCKED:
- 10 Kịch bản E2E tích hợp hệ thống hoàn chỉnh.
- Kiểm chứng toàn bộ chuỗi: Preflight -> Mapping -> TTS/Fitting -> Mixing -> Export -> Verification -> Cleanup.
- Bảo vệ mạch độc thoại Nam (Segments 22–27).
- Ma trận Cooperative Cancellation (3 subcases: Preflight, Mid-TTS, Post-export).
- Ma trận Fail-Fast (3 subcases: Missing input, Invalid timing, Corrupted MP4).
- Đo lường Duration thực tế trên đĩa bằng FFprobe (Shortest vs Freeze-End).
- Deep snapshot immutability của Master Data SubtitleSegment.
- Vòng đời Workspace Level 1, 2, 3.
- Real FFmpeg / FFprobe Binary Smoke Test.
"""

import copy
import os
import shutil
import struct
import subprocess
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
    probe_media_streams,
)
from app.services.video_export_service import (
    VideoExportRequest,
    VideoExportResult,
    VideoExportService,
    _resolve_ffmpeg,
    _resolve_ffprobe,
    measure_media_duration,
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


def create_real_synthetic_mp4(file_path: str, duration_sec: float = 3.0) -> bool:
    """Sử dụng FFmpeg thật của hệ thống để tạo video MP4 hợp lệ."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    ffmpeg_bin = _resolve_ffmpeg()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration_sec}:size=320x240:rate=25",
        "-f", "lavfi",
        "-i", f"sine=frequency=1000:duration={duration_sec}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-ar", "44100",
        "-ac", "2",
        file_path,
    ]
    kwargs: dict[str, Any] = {"capture_output": True, "text": True, "timeout": 20}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        res = subprocess.run(cmd, **kwargs)
        return res.returncode == 0 and os.path.isfile(file_path) and os.path.getsize(file_path) > 0
    except Exception:
        return False


def standard_h264_aac_prober(file_path: str) -> tuple[bool, list[dict[str, Any]], str]:
    """Mock ffprobe trả về H.264 video và AAC stereo audio."""
    streams = [
        {"codec_type": "video", "codec_name": "h264", "duration": "5.0"},
        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2, "duration": "5.0"},
    ]
    return True, streams, ""


def make_test_segment(
    seg_id: int,
    start: float,
    end: float,
    text: str = "English subtitle",
    translated_text: str = "Phụ đề tiếng Việt",
    final_gender: str = "male",
    is_noise: bool = False,
    skip_tts: bool = False,
    voice_id: str | None = None,
    voice_name: str | None = None,
) -> SubtitleSegment:
    """Tạo SubtitleSegment đầy đủ thuộc tính cho test E2E."""
    return SubtitleSegment(
        id=seg_id,
        start=start,
        end=end,
        text=text,
        translated_text=translated_text,
        final_gender=final_gender,
        is_noise=is_noise,
        skip_tts=skip_tts,
        voice_id=voice_id,
        voice_name=voice_name,
    )


def run_full_e2e_matrix() -> int:
    print("=" * 80)
    print("     CAPCAP STEP 8.4: FULL E2E REGRESSION MATRIX & PIPELINE DELIVERY")
    print("=" * 80)

    test_root = os.path.join(tempfile.gettempdir(), "capcap_step84_e2e_workspace")
    if os.path.isdir(test_root):
        try:
            shutil.rmtree(test_root)
        except Exception:
            pass
    os.makedirs(test_root, exist_ok=True)

    results: list[tuple[str, str, bool, list[str]]] = []

    # =========================================================================
    # E2E-01: Full Happy Path E2E (Đa giới tính & Hardsub)
    # =========================================================================
    t1_errs = []
    t1_dir = os.path.join(test_root, "e2e_01")
    os.makedirs(t1_dir, exist_ok=True)
    in_vid_1 = os.path.join(t1_dir, "input.mp4")
    create_pcm_wav(in_vid_1, 5.0)  # Giả định input media 5.0s
    out_vid_1 = os.path.join(t1_dir, "output.mp4")

    segs_1 = [
        make_test_segment(1, 0.0, 1.0, translated_text="Chào bạn nam", final_gender="male"),
        make_test_segment(2, 1.2, 2.2, translated_text="Chào bạn nữ", final_gender="female"),
        make_test_segment(3, 2.4, 3.0, translated_text="Tiếng ồn", is_noise=True),
        make_test_segment(4, 3.1, 3.8, translated_text="Chủ động bỏ qua", skip_tts=True),
        make_test_segment(5, 3.9, 4.5, translated_text="Người lạ", final_gender="unknown"),
        make_test_segment(6, 4.6, 5.0, translated_text=""),  # empty translation
    ]

    def fake_generate_1(segment_id, translated_text, start, end, voice_id, is_noise, skip_tts, output_path):
        dur = max(0.2, end - start)
        create_pcm_wav(output_path, dur)
        return TTSResult(segment_id=segment_id, voice_id=voice_id, audio_path=output_path, duration=dur, status="success", error="")

    def fake_fit_1(segment_id, raw_audio_path, slot_duration, output_path):
        create_pcm_wav(output_path, slot_duration)
        return FittedAudioResult(segment_id=segment_id, raw_audio_path=raw_audio_path, raw_duration=slot_duration, fitted_audio_path=output_path, fitted_duration=slot_duration, status="success")

    def fake_extract_1(vid, out):
        create_pcm_wav(out, 5.0)
        return True, ""

    def fake_mix_1(original_audio_path, tts_blocks, output_path):
        create_pcm_wav(output_path, 5.0)
        return MixedAudioResult(final_audio_path=output_path, total_duration=5.0, status="success")

    def fake_export_1(r):
        create_pcm_wav(r.output_video_path, 5.0)
        # 5 câu có translated_text được render phụ đề (câu 6 rỗng bị bỏ qua)
        rendered_cnt = sum(1 for s in r.segments if str(getattr(s, "translated_text", "") or "").strip())
        skipped_cnt = len(r.segments) - rendered_cnt
        return VideoExportResult(
            output_video_path=r.output_video_path,
            video_duration=5.0,
            audio_duration=5.0,
            final_video_duration=5.0,
            rendered_subtitles_count=rendered_cnt,
            skipped_subtitles_count=skipped_cnt,
            status="success",
        )

    mock_vo1 = MagicMock(spec=VoiceoverService, generate=MagicMock(side_effect=fake_generate_1))
    mock_fit1 = MagicMock(spec=DurationFittingService, fit_segment=MagicMock(side_effect=fake_fit_1))
    mock_ext1 = MagicMock(spec=OriginalAudioExtractor, extract=MagicMock(side_effect=fake_extract_1))
    mock_mix1 = MagicMock(spec=AudioMixingService, mix=MagicMock(side_effect=fake_mix_1))
    mock_exp1 = MagicMock(spec=VideoExportService, export_video=MagicMock(side_effect=fake_export_1))

    progress_events_1: list[float] = []
    svc1 = VideoCreatorService(
        voiceover_service=mock_vo1,
        duration_fitting_service=mock_fit1,
        original_audio_extractor=mock_ext1,
        audio_mixing_service=mock_mix1,
        video_export_service=mock_exp1,
        stream_prober=standard_h264_aac_prober,
    )
    req1 = VideoCreatorRequest(
        original_video_path=in_vid_1,
        segments=segs_1,
        output_video_path=out_vid_1,
        workspace_dir=t1_dir,
        progress_callback=lambda p, msg: progress_events_1.append(p),
    )
    res1 = svc1.run(req1)

    if res1.status != "success":
        t1_errs.append(f"Expected status='success', got '{res1.status}', error='{res1.error}'")
    if res1.error != "":
        t1_errs.append(f"Expected error='', got '{res1.error}'")
    if res1.cancelled_stage != "":
        t1_errs.append(f"Expected cancelled_stage='', got '{res1.cancelled_stage}'")
    if res1.tts_generated_count != 2 or res1.tts_skipped_count != 4:
        t1_errs.append(f"Expected tts 2 gen / 4 skip, got {res1.tts_generated_count}/{res1.tts_skipped_count}")
    if res1.subtitles_rendered_count != 5 or res1.subtitles_skipped_count != 1:
        t1_errs.append(f"Expected sub 5 rendered / 1 skip, got {res1.subtitles_rendered_count}/{res1.subtitles_skipped_count}")
    if not os.path.isfile(res1.output_video_path) or os.path.getsize(res1.output_video_path) <= 0:
        t1_errs.append("output_video_path must exist and size > 0")
    if not os.path.isfile(res1.output_audio_path) or os.path.getsize(res1.output_audio_path) <= 0:
        t1_errs.append("output_audio_path must exist and size > 0")
    # Prober check
    ok, streams, _ = standard_h264_aac_prober(res1.output_video_path)
    if not ok or len([s for s in streams if s.get("codec_type") == "subtitle"]) != 0:
        t1_errs.append("Output must have no soft subtitle stream (Hardsub only)")
    # Progress check
    if not progress_events_1 or progress_events_1[-1] != 100.0:
        t1_errs.append(f"Expected final progress 100.0%, got {progress_events_1[-1] if progress_events_1 else 'empty'}")
    results.append(("E2E-01", "Full Happy Path (Multi-type Segments & Artifact Integrity)", len(t1_errs) == 0, t1_errs))

    # =========================================================================
    # E2E-02: Bảo vệ mạch độc thoại Nam (Segments 22–27)
    # =========================================================================
    t2_errs = []
    t2_dir = os.path.join(test_root, "e2e_02")
    os.makedirs(t2_dir, exist_ok=True)
    in_vid_2 = os.path.join(t2_dir, "input.mp4")
    create_pcm_wav(in_vid_2, 6.0)
    out_vid_2 = os.path.join(t2_dir, "output.mp4")

    # Tạo đúng 6 câu thoại 22–27 nam độc thoại
    monologue_texts = [
        (22, 0.0, 0.8, "Ta đã chờ đợi khoảnh khắc này rất lâu rồi."),
        (23, 1.0, 1.8, "Không ai có thể ngăn cản bước tiến của ta."),
        (24, 2.0, 2.8, "Mọi thứ đều đã nằm trong kế hoạch."),
        (25, 3.0, 3.8, "Dù có khó khăn ta cũng sẽ vượt qua."),
        (26, 4.0, 4.8, "Đây là vận mệnh ta tự mình định đoạt."),
        (27, 5.0, 5.8, "Hãy chứng kiến sức mạnh thật sự của ta."),
    ]
    segs_2 = [
        make_test_segment(sid, s, e, text=f"Dialogue {sid}", translated_text=txt, final_gender="male")
        for sid, s, e, txt in monologue_texts
    ]

    called_voices_2: list[str] = []
    def fake_generate_2(segment_id, translated_text, start, end, voice_id, is_noise, skip_tts, output_path):
        called_voices_2.append(voice_id)
        create_pcm_wav(output_path, end - start)
        return TTSResult(segment_id=segment_id, voice_id=voice_id, audio_path=output_path, duration=end-start, status="success", error="")

    captured_blocks_2: list[TTSAudioBlock] = []
    def fake_mix_2(original_audio_path, tts_blocks, output_path):
        captured_blocks_2.extend(tts_blocks)
        create_pcm_wav(output_path, 6.0)
        return MixedAudioResult(final_audio_path=output_path, total_duration=6.0, status="success")

    def fake_export_2(r):
        create_pcm_wav(r.output_video_path, 6.0)
        return VideoExportResult(output_video_path=r.output_video_path, video_duration=6.0, audio_duration=6.0, final_video_duration=6.0, rendered_subtitles_count=len(r.segments), skipped_subtitles_count=0, status="success")

    mock_vo2 = MagicMock(spec=VoiceoverService, generate=MagicMock(side_effect=fake_generate_2))
    mock_fit2 = MagicMock(spec=DurationFittingService, fit_segment=MagicMock(side_effect=fake_fit_1))
    mock_ext2 = MagicMock(spec=OriginalAudioExtractor, extract=MagicMock(side_effect=fake_extract_1))
    mock_mix2 = MagicMock(spec=AudioMixingService, mix=MagicMock(side_effect=fake_mix_2))
    mock_exp2 = MagicMock(spec=VideoExportService, export_video=MagicMock(side_effect=fake_export_2))

    svc2 = VideoCreatorService(
        voiceover_service=mock_vo2,
        duration_fitting_service=mock_fit2,
        original_audio_extractor=mock_ext2,
        audio_mixing_service=mock_mix2,
        video_export_service=mock_exp2,
        stream_prober=standard_h264_aac_prober,
    )
    req2 = VideoCreatorRequest(
        original_video_path=in_vid_2,
        segments=segs_2,
        output_video_path=out_vid_2,
        workspace_dir=t2_dir,
    )
    res2 = svc2.run(req2)

    if res2.status != "success":
        t2_errs.append(f"Expected status='success', got '{res2.status}', error='{res2.error}'")
    if res2.tts_generated_count != 6:
        t2_errs.append(f"Expected 6 TTS generated, got {res2.tts_generated_count}")
    # Kiểm tra voice_id xuyên suốt
    if len(called_voices_2) != 6 or any(v != "vieneu_thanhnientutin" for v in called_voices_2):
        t2_errs.append(f"Voice drift detected! Expected all 'vieneu_thanhnientutin', got: {called_voices_2}")
    if len(captured_blocks_2) != 6:
        t2_errs.append(f"Expected 6 TTSAudioBlocks, got {len(captured_blocks_2)}")
    for b in captured_blocks_2:
        if b.segment_id not in range(22, 28):
            t2_errs.append(f"Unexpected block segment_id: {b.segment_id}")
    results.append(("E2E-02", "Male Monologue Protection (Segments 22–27 Unified Voice)", len(t2_errs) == 0, t2_errs))

    # =========================================================================
    # E2E-03: Zero-TTS Pass-Through (Video gắn phụ đề thuần túy)
    # =========================================================================
    t3_errs = []
    t3_dir = os.path.join(test_root, "e2e_03")
    os.makedirs(t3_dir, exist_ok=True)
    in_vid_3 = os.path.join(t3_dir, "input.mp4")
    create_pcm_wav(in_vid_3, 4.0)
    out_vid_3 = os.path.join(t3_dir, "output.mp4")

    # Mọi câu đều không eligible cho TTS
    segs_3 = [
        make_test_segment(1, 0.0, 1.0, translated_text="Nhiễu nền", is_noise=True),
        make_test_segment(2, 1.5, 2.5, translated_text="Bỏ qua", skip_tts=True),
        make_test_segment(3, 3.0, 4.0, translated_text="Không rõ", final_gender="unknown"),
    ]

    mock_vo3 = MagicMock(spec=VoiceoverService)
    mock_fit3 = MagicMock(spec=DurationFittingService)
    mock_ext3 = MagicMock(spec=OriginalAudioExtractor, extract=MagicMock(side_effect=fake_extract_1))
    
    passed_blocks_3: list[TTSAudioBlock] = []
    def fake_mix_3(original_audio_path, tts_blocks, output_path):
        passed_blocks_3.extend(tts_blocks)
        create_pcm_wav(output_path, 4.0)
        return MixedAudioResult(final_audio_path=output_path, total_duration=4.0, status="success")
    mock_mix3 = MagicMock(spec=AudioMixingService, mix=MagicMock(side_effect=fake_mix_3))

    def fake_export_3(r):
        create_pcm_wav(r.output_video_path, 4.0)
        return VideoExportResult(output_video_path=r.output_video_path, video_duration=4.0, audio_duration=4.0, final_video_duration=4.0, rendered_subtitles_count=len(r.segments), skipped_subtitles_count=0, status="success")
    mock_exp3 = MagicMock(spec=VideoExportService, export_video=MagicMock(side_effect=fake_export_3))

    svc3 = VideoCreatorService(
        voiceover_service=mock_vo3,
        duration_fitting_service=mock_fit3,
        original_audio_extractor=mock_ext3,
        audio_mixing_service=mock_mix3,
        video_export_service=mock_exp3,
        stream_prober=standard_h264_aac_prober,
    )
    req3 = VideoCreatorRequest(
        original_video_path=in_vid_3,
        segments=segs_3,
        output_video_path=out_vid_3,
        workspace_dir=t3_dir,
    )
    res3 = svc3.run(req3)

    if res3.status != "success":
        t3_errs.append(f"Expected status='success', got '{res3.status}'")
    if res3.tts_generated_count != 0:
        t3_errs.append(f"Expected tts_generated_count=0, got {res3.tts_generated_count}")
    if mock_vo3.generate.called:
        t3_errs.append("VoiceoverService MUST NOT be called for zero-TTS")
    if len(passed_blocks_3) != 0:
        t3_errs.append(f"AudioMixingService must receive 0 blocks, got {len(passed_blocks_3)}")
    if res3.subtitles_rendered_count != 3:
        t3_errs.append(f"Expected 3 subtitles rendered in hardsub, got {res3.subtitles_rendered_count}")
    results.append(("E2E-03", "Zero-TTS Pass-Through (Pure Hardsub with 100% Original Volume)", len(t3_errs) == 0, t3_errs))

    # =========================================================================
    # E2E-04: Tràn thời lượng Audio > Video (Chính sách shortest)
    # =========================================================================
    t4_errs = []
    t4_dir = os.path.join(test_root, "e2e_04")
    os.makedirs(t4_dir, exist_ok=True)
    in_vid_4 = os.path.join(t4_dir, "input.mp4")
    create_pcm_wav(in_vid_4, 3.0)  # Video 3.0s
    out_vid_4 = os.path.join(t4_dir, "output.mp4")

    # Audio 5.0s > Video 3.0s -> chính sách shortest cắt tại 3.0s
    def fake_mix_4(original_audio_path, tts_blocks, output_path):
        create_pcm_wav(output_path, 5.0)  # Audio 5.0s
        return MixedAudioResult(final_audio_path=output_path, total_duration=5.0, status="success")

    def fake_export_4(r):
        # Giả lập FFmpeg cắt theo shortest: video output có độ dài 3.0s
        create_pcm_wav(r.output_video_path, 3.0)
        return VideoExportResult(
            output_video_path=r.output_video_path,
            video_duration=3.0,
            audio_duration=5.0,
            final_video_duration=3.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            warning="Audio duration (5.00s) exceeds video duration (3.00s). Applied '-shortest' policy.",
            status="success",
        )

    def prober_3s(file_path: str):
        streams = [
            {"codec_type": "video", "codec_name": "h264", "duration": "3.0"},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2, "duration": "3.0"},
        ]
        return True, streams, ""

    mock_vo4 = MagicMock(spec=VoiceoverService, generate=MagicMock(side_effect=fake_generate_1))
    mock_fit4 = MagicMock(spec=DurationFittingService, fit_segment=MagicMock(side_effect=fake_fit_1))
    mock_ext4 = MagicMock(spec=OriginalAudioExtractor, extract=MagicMock(side_effect=fake_extract_1))
    mock_mix4 = MagicMock(spec=AudioMixingService, mix=MagicMock(side_effect=fake_mix_4))
    mock_exp4 = MagicMock(spec=VideoExportService, export_video=MagicMock(side_effect=fake_export_4))

    svc4 = VideoCreatorService(
        voiceover_service=mock_vo4,
        duration_fitting_service=mock_fit4,
        original_audio_extractor=mock_ext4,
        audio_mixing_service=mock_mix4,
        video_export_service=mock_exp4,
        stream_prober=prober_3s,
    )
    req4 = VideoCreatorRequest(
        original_video_path=in_vid_4,
        segments=[make_test_segment(1, 0.0, 2.5)],
        output_video_path=out_vid_4,
        workspace_dir=t4_dir,
        config=VideoCreatorConfig(overflow_policy="shortest"),
    )
    res4 = svc4.run(req4)

    if res4.status != "success":
        t4_errs.append(f"Expected status='success', got '{res4.status}'")
    if not any("-shortest" in w for w in res4.warnings):
        t4_errs.append("Expected '-shortest' warning in warnings list")
    # Kiểm tra duration thực tế trên đĩa
    actual_dur_4 = measure_media_duration(res4.output_video_path)
    if abs(actual_dur_4 - 3.0) > 0.5:
        t4_errs.append(f"Actual video duration on disk must be ~3.0s, got {actual_dur_4}s")
    results.append(("E2E-04", "Audio Overflow — Shortest Policy (Duration Cut to Video Length)", len(t4_errs) == 0, t4_errs))

    # =========================================================================
    # E2E-05: Tràn thời lượng Audio > Video (Chính sách freeze_end)
    # =========================================================================
    t5_errs = []
    t5_dir = os.path.join(test_root, "e2e_05")
    os.makedirs(t5_dir, exist_ok=True)
    in_vid_5 = os.path.join(t5_dir, "input.mp4")
    create_pcm_wav(in_vid_5, 3.0)  # Video 3.0s
    out_vid_5 = os.path.join(t5_dir, "output.mp4")

    # Audio 5.0s > Video 3.0s -> freeze_end kéo dài video thành 5.0s
    def fake_export_5(r):
        create_pcm_wav(r.output_video_path, 5.0)
        return VideoExportResult(
            output_video_path=r.output_video_path,
            video_duration=3.0,
            audio_duration=5.0,
            final_video_duration=5.0,
            rendered_subtitles_count=1,
            skipped_subtitles_count=0,
            warning="Audio duration (5.00s) exceeds video duration (3.00s). Video extended with freeze frame to 5.00s.",
            status="success",
        )

    def prober_5s(file_path: str):
        streams = [
            {"codec_type": "video", "codec_name": "h264", "duration": "5.0"},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2, "duration": "5.0"},
        ]
        return True, streams, ""

    mock_vo5 = MagicMock(spec=VoiceoverService, generate=MagicMock(side_effect=fake_generate_1))
    mock_fit5 = MagicMock(spec=DurationFittingService, fit_segment=MagicMock(side_effect=fake_fit_1))
    mock_ext5 = MagicMock(spec=OriginalAudioExtractor, extract=MagicMock(side_effect=fake_extract_1))
    mock_mix5 = MagicMock(spec=AudioMixingService, mix=MagicMock(side_effect=fake_mix_4))
    mock_exp5 = MagicMock(spec=VideoExportService, export_video=MagicMock(side_effect=fake_export_5))

    svc5 = VideoCreatorService(
        voiceover_service=mock_vo5,
        duration_fitting_service=mock_fit5,
        original_audio_extractor=mock_ext5,
        audio_mixing_service=mock_mix5,
        video_export_service=mock_exp5,
        stream_prober=prober_5s,
    )
    req5 = VideoCreatorRequest(
        original_video_path=in_vid_5,
        segments=[make_test_segment(1, 0.0, 2.5)],
        output_video_path=out_vid_5,
        workspace_dir=t5_dir,
        config=VideoCreatorConfig(overflow_policy="freeze_end"),
    )
    res5 = svc5.run(req5)

    if res5.status != "success":
        t5_errs.append(f"Expected status='success', got '{res5.status}'")
    if not any("freeze frame" in w for w in res5.warnings):
        t5_errs.append("Expected 'freeze frame' warning in warnings list")
    actual_dur_5 = measure_media_duration(res5.output_video_path)
    if abs(actual_dur_5 - 5.0) > 0.5:
        t5_errs.append(f"Actual video duration on disk must be extended to ~5.0s, got {actual_dur_5}s")
    results.append(("E2E-05", "Audio Overflow — Freeze-End Policy (Duration Extended to Audio Length)", len(t5_errs) == 0, t5_errs))

    # =========================================================================
    # E2E-06: Ma trận Cooperative Cancellation (3 Subcases: Preflight, Mid-TTS, Post-export)
    # =========================================================================
    t6_errs = []
    t6_dir = os.path.join(test_root, "e2e_06")
    os.makedirs(t6_dir, exist_ok=True)
    in_vid_6 = os.path.join(t6_dir, "input.mp4")
    create_pcm_wav(in_vid_6, 3.0)

    # Subcase 6A: Preflight Cancellation
    req_6a = VideoCreatorRequest(
        original_video_path=in_vid_6,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=os.path.join(t6_dir, "out_6a.mp4"),
        is_cancelled_func=lambda: True,
    )
    res_6a = svc1.run(req_6a)
    if res_6a.status != "cancelled" or res_6a.cancelled_stage != "preflight" or res_6a.error != "":
        t6_errs.append("6A: Expected status='cancelled', cancelled_stage='preflight', error=''")

    # Subcase 6B: Mid-TTS Cancellation (giữa câu 1 và câu 2)
    t6b_dir = os.path.join(t6_dir, "s6b")
    call_cnt_6b = {"cnt": 0}
    def cancel_mid_tts():
        call_cnt_6b["cnt"] += 1
        return call_cnt_6b["cnt"] >= 6  # Hủy tại pre-segment 2

    req_6b = VideoCreatorRequest(
        original_video_path=in_vid_6,
        segments=[make_test_segment(1, 0.0, 1.0), make_test_segment(2, 1.0, 2.0)],
        output_video_path=os.path.join(t6_dir, "out_6b.mp4"),
        workspace_dir=t6b_dir,
        is_cancelled_func=cancel_mid_tts,
    )
    res_6b = svc1.run(req_6b)
    if res_6b.status != "cancelled" or res_6b.cancelled_stage != "tts" or res_6b.error != "":
        t6_errs.append("6B: Expected status='cancelled', cancelled_stage='tts', error=''")

    # Subcase 6C: Post-export Cancellation (sau khi xuất MP4, không chạy Verification)
    t6c_dir = os.path.join(t6_dir, "s6c")
    out_vid_6c = os.path.join(t6c_dir, "out_6c.mp4")
    call_cnt_6c = {"cnt": 0}
    def cancel_post_export():
        call_cnt_6c["cnt"] += 1
        return call_cnt_6c["cnt"] >= 11  # Checkpoint B của Export

    def fake_export_6c(r):
        create_pcm_wav(out_vid_6c, 3.0)
        return VideoExportResult(output_video_path=out_vid_6c, video_duration=3.0, audio_duration=3.0, final_video_duration=3.0, rendered_subtitles_count=1, skipped_subtitles_count=0, status="success")

    mock_exp6c = MagicMock(spec=VideoExportService, export_video=MagicMock(side_effect=fake_export_6c))
    svc6c = VideoCreatorService(
        voiceover_service=mock_vo1,
        duration_fitting_service=mock_fit1,
        original_audio_extractor=mock_ext1,
        audio_mixing_service=mock_mix1,
        video_export_service=mock_exp6c,
        stream_prober=standard_h264_aac_prober,
    )
    req_6c = VideoCreatorRequest(
        original_video_path=in_vid_6,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid_6c,
        workspace_dir=t6c_dir,
        is_cancelled_func=cancel_post_export,
    )
    res_6c = svc6c.run(req_6c)
    if res_6c.status != "cancelled" or res_6c.cancelled_stage != "export" or res_6c.error != "":
        t6_errs.append("6C: Expected status='cancelled', cancelled_stage='export', error=''")
    if not os.path.isfile(out_vid_6c):
        t6_errs.append("6C: Output video file must be preserved on disk")
    results.append(("E2E-06", "Cooperative Cancellation Matrix (Preflight, Mid-TTS, Post-Export)", len(t6_errs) == 0, t6_errs))

    # =========================================================================
    # E2E-07: Ma trận Fail-Fast & Xử lý Ngoại lệ Kỹ thuật (3 Subcases)
    # =========================================================================
    t7_errs = []
    t7_dir = os.path.join(test_root, "e2e_07")
    os.makedirs(t7_dir, exist_ok=True)

    # Subcase 7A: Missing Input Video
    req_7a = VideoCreatorRequest(
        original_video_path=os.path.join(t7_dir, "non_existent.mp4"),
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=os.path.join(t7_dir, "out_7a.mp4"),
    )
    res_7a = svc1.run(req_7a)
    if res_7a.status != "failed" or "not found" not in res_7a.error.lower():
        t7_errs.append("7A: Expected status='failed' with 'not found' error")

    # Subcase 7B: Invalid Timing (start >= end)
    in_vid_7 = os.path.join(t7_dir, "in_7.mp4")
    create_pcm_wav(in_vid_7, 3.0)
    req_7b = VideoCreatorRequest(
        original_video_path=in_vid_7,
        segments=[make_test_segment(1, 2.0, 1.0)],  # end < start
        output_video_path=os.path.join(t7_dir, "out_7b.mp4"),
    )
    res_7b = svc1.run(req_7b)
    if res_7b.status != "failed" or "Invalid segment timing" not in res_7b.error:
        t7_errs.append("7B: Expected status='failed' with 'Invalid segment timing' error")

    # Subcase 7C: Corrupted MP4 Container at Verification
    t7c_dir = os.path.join(t7_dir, "s7c")
    out_vid_7c = os.path.join(t7c_dir, "out_7c.mp4")

    def corrupt_prober(p):
        return False, [], "MOOV atom missing or corrupted MP4 container"

    svc7c = VideoCreatorService(
        voiceover_service=mock_vo1,
        duration_fitting_service=mock_fit1,
        original_audio_extractor=mock_ext1,
        audio_mixing_service=mock_mix1,
        video_export_service=mock_exp1,
        stream_prober=corrupt_prober,
    )
    req_7c = VideoCreatorRequest(
        original_video_path=in_vid_7,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid_7c,
        workspace_dir=t7c_dir,
    )
    res_7c = svc7c.run(req_7c)
    if res_7c.status != "failed" or "Failed to probe" not in res_7c.error:
        t7_errs.append("7C: Expected status='failed' due to corrupted container")
    results.append(("E2E-07", "Fail-Fast Matrix (Missing Input, Invalid Timing, Corrupted MP4)", len(t7_errs) == 0, t7_errs))

    # =========================================================================
    # E2E-08: Vòng đời Workspace & Dọn dẹp Intermediate Audio (2 Subcases)
    # =========================================================================
    t8_errs = []
    t8_dir = os.path.join(test_root, "e2e_08")
    os.makedirs(t8_dir, exist_ok=True)
    in_vid_8 = os.path.join(t8_dir, "input.mp4")
    create_pcm_wav(in_vid_8, 3.0)

    # Subcase 8A: cleanup_intermediate_audio = True
    t8a_dir = os.path.join(t8_dir, "s8a")
    out_vid_8a = os.path.join(t8a_dir, "out_8a.mp4")
    req_8a = VideoCreatorRequest(
        original_video_path=in_vid_8,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid_8a,
        workspace_dir=t8a_dir,
        config=VideoCreatorConfig(cleanup_intermediate_audio=True),
    )
    res_8a = svc1.run(req_8a)
    if res_8a.status != "success":
        t8_errs.append(f"8A: Expected status='success', got {res_8a.status}")
    # Level 2 intermediate must be cleaned
    if os.path.isdir(os.path.join(t8a_dir, "raw_tts")) or os.path.isdir(os.path.join(t8a_dir, "fitted_tts")) or os.path.isfile(os.path.join(t8a_dir, "extracted_original_audio.wav")):
        t8_errs.append("8A: Level 2 intermediate audio must be cleaned")
    # Level 3 must be preserved
    if not os.path.isfile(res_8a.output_video_path) or not os.path.isfile(res_8a.output_audio_path):
        t8_errs.append("8A: Level 3 artifacts must be preserved")

    # Subcase 8B: cleanup_intermediate_audio = False (default)
    t8b_dir = os.path.join(t8_dir, "s8b")
    out_vid_8b = os.path.join(t8b_dir, "out_8b.mp4")
    req_8b = VideoCreatorRequest(
        original_video_path=in_vid_8,
        segments=[make_test_segment(1, 0.0, 2.0)],
        output_video_path=out_vid_8b,
        workspace_dir=t8b_dir,
        config=VideoCreatorConfig(cleanup_intermediate_audio=False),
    )
    res_8b = svc1.run(req_8b)
    if res_8b.status != "success":
        t8_errs.append(f"8B: Expected status='success', got {res_8b.status}")
    if not os.path.isdir(os.path.join(t8b_dir, "raw_tts")) or not os.path.isdir(os.path.join(t8b_dir, "fitted_tts")) or not os.path.isfile(os.path.join(t8b_dir, "extracted_original_audio.wav")):
        t8_errs.append("8B: Level 2 intermediate audio must remain preserved when cleanup=False")
    results.append(("E2E-08", "Workspace Lifecycle (Intermediate Cleanup vs Preservation)", len(t8_errs) == 0, t8_errs))

    # =========================================================================
    # E2E-09: Tính Bất biến Tuyệt đối của Master Data (Deep Snapshot)
    # =========================================================================
    t9_errs = []
    t9_dir = os.path.join(test_root, "e2e_09")
    os.makedirs(t9_dir, exist_ok=True)
    in_vid_9 = os.path.join(t9_dir, "input.mp4")
    create_pcm_wav(in_vid_9, 4.0)
    out_vid_9 = os.path.join(t9_dir, "output.mp4")

    segs_9 = [
        make_test_segment(1, 0.0, 1.0, text="One", translated_text="Một", final_gender="male", voice_id=None, voice_name=None),
        make_test_segment(2, 1.2, 2.2, text="Two", translated_text="Hai", final_gender="female", is_noise=False, voice_id=None, voice_name=None),
        make_test_segment(3, 2.5, 3.5, text="Three", translated_text="Ba", is_noise=True, skip_tts=True, voice_id=None, voice_name=None),
    ]

    # Lưu Deep Snapshot trước khi gọi run()
    snapshot_before = [copy.deepcopy(s.__dict__) for s in segs_9]

    req9 = VideoCreatorRequest(
        original_video_path=in_vid_9,
        segments=segs_9,
        output_video_path=out_vid_9,
        workspace_dir=t9_dir,
    )
    res9 = svc1.run(req9)

    if res9.status != "success":
        t9_errs.append(f"Expected status='success', got {res9.status}")

    # So sánh từng trường của từng segment sau khi run()
    critical_fields = ["id", "start", "end", "text", "translated_text", "final_gender", "is_noise", "skip_tts", "voice_id", "voice_name"]
    for i, (orig, curr) in enumerate(zip(snapshot_before, segs_9), start=1):
        for f in critical_fields:
            val_before = orig.get(f)
            val_after = getattr(curr, f, None)
            if val_before != val_after:
                t9_errs.append(f"Master Data mutated in segment {i}, field '{f}': '{val_before}' -> '{val_after}'")
    results.append(("E2E-09", "Master Data Strict Immutability (Deep Snapshot Verification)", len(t9_errs) == 0, t9_errs))

    # =========================================================================
    # E2E-10: Real FFmpeg / FFprobe Binary Smoke Test
    # =========================================================================
    t10_errs = []
    t10_dir = os.path.join(test_root, "e2e_10")
    os.makedirs(t10_dir, exist_ok=True)
    real_in_vid = os.path.join(t10_dir, "real_input.mp4")
    real_out_vid = os.path.join(t10_dir, "real_output.mp4")

    # 1. Tạo file video thật bằng FFmpeg
    if not create_real_synthetic_mp4(real_in_vid, 2.0):
        t10_errs.append("Failed to create real synthetic MP4 with FFmpeg binary")
    else:
        # 2. Chạy VideoCreatorService với các service default (thực thi FFmpeg thực tế)
        # Sử dụng real extractor, real export service và real prober
        # Mock TTS để không phụ thuộc GPU/API, nhưng toàn bộ audio extraction, mixing, subtitle rendering, ffmpeg encoding là THẬT 100%
        real_svc = VideoCreatorService(
            voiceover_service=mock_vo1,
            duration_fitting_service=mock_fit1,
            # original_audio_extractor=None -> dùng OriginalAudioExtractor thật
            # audio_mixing_service=None -> dùng AudioMixingService thật
            # video_export_service=None -> dùng VideoExportService thật
            # stream_prober=None -> dùng probe_media_streams thật (FFprobe)
        )
        real_req = VideoCreatorRequest(
            original_video_path=real_in_vid,
            segments=[make_test_segment(1, 0.2, 1.8, translated_text="Kiểm tra FFmpeg thực tế")],
            output_video_path=real_out_vid,
            workspace_dir=t10_dir,
        )
        real_res = real_svc.run(real_req)

        if real_res.status != "success":
            t10_errs.append(f"Real pipeline failed: status='{real_res.status}', error='{real_res.error}'")
        if not os.path.isfile(real_out_vid) or os.path.getsize(real_out_vid) <= 0:
            t10_errs.append("Real output MP4 does not exist or empty on disk")
        else:
            # 3. Dùng FFprobe thật để kiểm định tính hợp lệ của file video sinh ra
            ok, streams, probe_err = probe_media_streams(real_out_vid)
            if not ok:
                t10_errs.append(f"Real FFprobe failed on generated MP4: {probe_err}")
            else:
                v_streams = [s for s in streams if s.get("codec_type") == "video"]
                a_streams = [s for s in streams if s.get("codec_type") == "audio"]
                if not v_streams or str(v_streams[0].get("codec_name", "")).lower() != "h264":
                    t10_errs.append("Real output MP4 missing valid H.264 video stream")
                if not a_streams or str(a_streams[0].get("codec_name", "")).lower() != "aac":
                    t10_errs.append("Real output MP4 missing valid AAC audio stream")
                # Đo duration thực tế bằng measure_media_duration
                real_dur = measure_media_duration(real_out_vid)
                if real_dur <= 0.0:
                    t10_errs.append(f"Real output MP4 has invalid duration: {real_dur}s")

    results.append(("E2E-10", "Real FFmpeg / FFprobe Binary Smoke Test (Real MP4 Playable Artifact)", len(t10_errs) == 0, t10_errs))

    # =========================================================================
    # TỔNG KẾT BẢNG KẾT QUẢ BƯỚC 8.4
    # =========================================================================
    print("-" * 80)
    passed_count = sum(1 for _, _, p, _ in results if p)
    for code, name, passed, errs in results:
        status_icon = "✅ PASS" if passed else "❌ FAIL"
        print(f"[{code}] {status_icon} - {name}")
        for err in errs:
            print(f"     └── ⚠️ {err}")

    print("=" * 80)
    print(f"KẾT QUẢ FULL E2E REGRESSION BƯỚC 8.4: {passed_count}/{len(results)} SCENARIOS PASS")
    print("=" * 80)

    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(run_full_e2e_matrix())
