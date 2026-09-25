"""Acceptance Test Suite for Step 8.3.5 — Audio Mixing & Ducking Orchestration (14 Tests).

Validates all 11 Invariants and Core Behaviors of Contract 8.3.5 v1.1:
[1] Normal mixing with TTS blocks -> Sinh final_audio.wav, status='success', duck intervals đúng
[2] Zero-TTS (empty blocks) -> Copy nguyên bản audio gốc 100% volume, không ducking, status='success'
[3] Config propagation (duck_volume) -> request.config.duck_volume = 0.15 -> applied_duck_volume == 0.15
[4] Fixed output path contract -> Output audio path luôn là <session_dir>/final_audio.wav
[5] Overlap detection fail-fast -> 2 block overlap timeline -> status='failed', transparent error
[6] Timeline overflow warning -> TTS dài hơn audio gốc -> Warning overflow xuất hiện trong result.warnings
[7] Missing original audio -> Đường dẫn audio/video gốc không tồn tại -> status='failed'
[8] Pre-preparation cancellation (Checkpoint A) -> Không gọi extractor, không gọi mix(), cancelled_stage='mixing'
[9] Post-mixing cancellation (Checkpoint C) -> status='cancelled', cancelled_stage='mixing'
[10] Missing TTS file error -> Block trỏ đến file WAV không tồn tại -> status='failed'
[11] Master Data immutability -> segments không bị mutate bất kỳ thuộc tính nào
[12] Progress monotonic -> Đi từ 55.0% -> 75.0% đơn điệu
[13] Audio extraction delegation -> VideoCreatorService gọi OriginalAudioExtractor, chuyển extracted WAV sang AudioMixingService
[14] Cancellation after extraction (Checkpoint B) -> AudioMixingService.mix() KHÔNG được gọi, cancelled_stage='mixing'
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
from app.services.audio_mixing_service import AudioMixingService, MixedAudioResult, TTSAudioBlock
from app.services.original_audio_extractor import OriginalAudioExtractor
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
    VoiceAssignment,
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


def make_test_segment(seg_id: int, start: float, end: float, text: str = "Thoại mẫu", final_gender: str = "male") -> SubtitleSegment:
    seg = SubtitleSegment(id=seg_id, start=start, end=end, text=f"Text {seg_id}")
    seg.translated_text = text
    seg.final_gender = final_gender
    seg.gender = "female"  # Phải bị phớt lờ
    seg.is_noise = False
    seg.skip_tts = False
    return seg


def run_all_acceptance_tests():
    print("=" * 80)
    print("     CAPCAP STEP 8.3.5 — AUDIO MIXING & DUCKING ORCHESTRATION ACCEPTANCE")
    print("=" * 80)

    test_root = tempfile.mkdtemp(prefix="capcap_test_step835_")
    results: list[tuple[int, str, bool, list[str]]] = []

    try:
        # =====================================================================
        # TEST 1: Normal mixing with valid TTS blocks
        # =====================================================================
        t1_errs = []
        t1_dir = os.path.join(test_root, "t1")
        os.makedirs(t1_dir, exist_ok=True)
        orig_video = os.path.join(t1_dir, "input.wav")
        create_pcm_wav(orig_video, 8.0)

        # 2 valid blocks (1.0 -> 3.0, 4.0 -> 6.0)
        b1_wav = os.path.join(t1_dir, "b1.wav")
        b2_wav = os.path.join(t1_dir, "b2.wav")
        create_pcm_wav(b1_wav, 2.0)
        create_pcm_wav(b2_wav, 2.0)

        tts_blocks = [
            TTSAudioBlock(segment_id=1, start_time=1.0, duration=2.0, audio_path=b1_wav),
            TTSAudioBlock(segment_id=2, start_time=4.0, duration=2.0, audio_path=b2_wav),
        ]
        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 3.0), make_test_segment(2, 4.0, 6.0)],
            output_video_path=os.path.join(t1_dir, "out.mp4"),
            workspace_dir=t1_dir,
            config=VideoCreatorConfig(duck_volume=0.20),
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t1_dir, tts_blocks)
        if err_res is not None:
            t1_errs.append(f"Unexpected error result: {err_res.error}")
        if mixed_res is None or mixed_res.status != "success":
            t1_errs.append(f"Expected success, got {mixed_res}")
        if not os.path.isfile(os.path.join(t1_dir, "final_audio.wav")):
            t1_errs.append("final_audio.wav not created")
        if mixed_res and len(mixed_res.duck_intervals) != 2:
            t1_errs.append(f"Expected 2 duck intervals, got {mixed_res.duck_intervals}")
        results.append((1, "Normal mixing with TTS blocks", len(t1_errs) == 0, t1_errs))

        # =====================================================================
        # TEST 2: Zero-TTS (empty blocks) -> Copy 100% volume
        # =====================================================================
        t2_errs = []
        t2_dir = os.path.join(test_root, "t2")
        os.makedirs(t2_dir, exist_ok=True)
        orig_video = os.path.join(t2_dir, "input.wav")
        create_pcm_wav(orig_video, 5.0)

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 3.0, final_gender="unknown")],
            output_video_path=os.path.join(t2_dir, "out.mp4"),
            workspace_dir=t2_dir,
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t2_dir, [])
        if err_res is not None:
            t2_errs.append(f"Unexpected error: {err_res.error}")
        if mixed_res is None or mixed_res.status != "success":
            t2_errs.append("Expected success for zero-TTS")
        if mixed_res and mixed_res.duck_intervals != []:
            t2_errs.append(f"Expected empty duck intervals, got {mixed_res.duck_intervals}")
        final_p = os.path.join(t2_dir, "final_audio.wav")
        if not os.path.isfile(final_p):
            t2_errs.append("final_audio.wav missing for zero-TTS")
        results.append((2, "Zero-TTS (empty blocks)", len(t2_errs) == 0, t2_errs))

        # =====================================================================
        # TEST 3: Config propagation (duck_volume = 0.15)
        # =====================================================================
        t3_errs = []
        t3_dir = os.path.join(test_root, "t3")
        os.makedirs(t3_dir, exist_ok=True)
        orig_video = os.path.join(t3_dir, "input.wav")
        create_pcm_wav(orig_video, 6.0)
        b_wav = os.path.join(t3_dir, "b.wav")
        create_pcm_wav(b_wav, 2.0)

        # Inject service with wrong default (0.30) to test source of truth override
        injected_mixing = AudioMixingService(duck_volume=0.30)
        svc = VideoCreatorService(audio_mixing_service=injected_mixing)
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 3.0)],
            output_video_path=os.path.join(t3_dir, "out.mp4"),
            workspace_dir=t3_dir,
            config=VideoCreatorConfig(duck_volume=0.15),
        )
        blocks = [TTSAudioBlock(segment_id=1, start_time=1.0, duration=2.0, audio_path=b_wav)]
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t3_dir, blocks)
        if err_res is not None:
            t3_errs.append(f"Error: {err_res.error}")
        if mixed_res and mixed_res.applied_duck_volume != 0.15:
            t3_errs.append(f"Expected applied_duck_volume=0.15, got {mixed_res.applied_duck_volume}")
        results.append((3, "Config propagation (duck_volume=0.15)", len(t3_errs) == 0, t3_errs))

        # =====================================================================
        # TEST 4: Fixed output path contract (<session_dir>/final_audio.wav)
        # =====================================================================
        t4_errs = []
        t4_dir = os.path.join(test_root, "t4")
        os.makedirs(t4_dir, exist_ok=True)
        orig_video = os.path.join(t4_dir, "input.wav")
        create_pcm_wav(orig_video, 4.0)

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 0.5, 2.0)],
            output_video_path=os.path.join(t4_dir, "out.mp4"),
            workspace_dir=t4_dir,
        )
        mixed_res, _, _ = svc._orchestrate_mixing(req, t4_dir, [])
        expected_p = os.path.join(t4_dir, "final_audio.wav")
        if mixed_res and os.path.abspath(mixed_res.final_audio_path) != os.path.abspath(expected_p):
            t4_errs.append(f"Expected final_audio_path={expected_p}, got {mixed_res.final_audio_path}")
        results.append((4, "Fixed output path contract", len(t4_errs) == 0, t4_errs))

        # =====================================================================
        # TEST 5: Overlap detection fail-fast
        # =====================================================================
        t5_errs = []
        t5_dir = os.path.join(test_root, "t5")
        os.makedirs(t5_dir, exist_ok=True)
        orig_video = os.path.join(t5_dir, "input.wav")
        create_pcm_wav(orig_video, 10.0)

        # Overlapping blocks: b1 ends at 4.0, b2 starts at 3.0
        b1_wav = os.path.join(t5_dir, "b1.wav")
        b2_wav = os.path.join(t5_dir, "b2.wav")
        create_pcm_wav(b1_wav, 3.0)
        create_pcm_wav(b2_wav, 2.0)

        tts_blocks = [
            TTSAudioBlock(segment_id=1, start_time=1.0, duration=3.0, audio_path=b1_wav),
            TTSAudioBlock(segment_id=2, start_time=3.0, duration=2.0, audio_path=b2_wav),
        ]
        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 4.0), make_test_segment(2, 3.0, 5.0)],
            output_video_path=os.path.join(t5_dir, "out.mp4"),
            workspace_dir=t5_dir,
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t5_dir, tts_blocks)
        if err_res is None or err_res.status != "failed":
            t5_errs.append("Expected pipeline failure on TTS overlap")
        elif "TTS overlap detected" not in err_res.error:
            t5_errs.append(f"Unexpected error message: {err_res.error}")
        results.append((5, "Overlap detection fail-fast", len(t5_errs) == 0, t5_errs))

        # =====================================================================
        # TEST 6: Timeline overflow warning
        # =====================================================================
        t6_errs = []
        t6_dir = os.path.join(test_root, "t6")
        os.makedirs(t6_dir, exist_ok=True)
        orig_video = os.path.join(t6_dir, "input.wav")
        create_pcm_wav(orig_video, 3.0)  # Original audio is only 3.0s

        # Block ends at 5.0s > 3.0s
        b1_wav = os.path.join(t6_dir, "b1.wav")
        create_pcm_wav(b1_wav, 4.0)

        tts_blocks = [
            TTSAudioBlock(segment_id=1, start_time=1.0, duration=4.0, audio_path=b1_wav)
        ]
        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 5.0)],
            output_video_path=os.path.join(t6_dir, "out.mp4"),
            workspace_dir=t6_dir,
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t6_dir, tts_blocks)
        if err_res is not None:
            t6_errs.append(f"Unexpected error: {err_res.error}")
        if mixed_res is None or mixed_res.status != "success":
            t6_errs.append("Expected success despite timeline overflow")
        if not any("exceeds original audio duration" in w for w in warns):
            t6_errs.append(f"Expected overflow warning in warnings, got: {warns}")
        if mixed_res and mixed_res.total_duration < 5.0:
            t6_errs.append(f"Expected extended timeline >= 5.0s, got {mixed_res.total_duration}")
        results.append((6, "Timeline overflow warning", len(t6_errs) == 0, t6_errs))

        # =====================================================================
        # TEST 7: Missing original audio
        # =====================================================================
        t7_errs = []
        t7_dir = os.path.join(test_root, "t7")
        os.makedirs(t7_dir, exist_ok=True)
        missing_video = os.path.join(t7_dir, "non_existent_input.mp4")

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=missing_video,
            segments=[make_test_segment(1, 1.0, 3.0)],
            output_video_path=os.path.join(t7_dir, "out.mp4"),
            workspace_dir=t7_dir,
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t7_dir, [])
        if err_res is None or err_res.status != "failed":
            t7_errs.append("Expected failed status on missing original audio")
        results.append((7, "Missing original audio fail-fast", len(t7_errs) == 0, t7_errs))

        # =====================================================================
        # TEST 8: Pre-preparation cancellation (Checkpoint A)
        # =====================================================================
        t8_errs = []
        t8_dir = os.path.join(test_root, "t8")
        os.makedirs(t8_dir, exist_ok=True)
        orig_video = os.path.join(t8_dir, "input.wav")
        create_pcm_wav(orig_video, 5.0)

        mock_extractor = MagicMock(spec=OriginalAudioExtractor)
        mock_mixing = MagicMock(spec=AudioMixingService)
        svc = VideoCreatorService(original_audio_extractor=mock_extractor, audio_mixing_service=mock_mixing)

        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 3.0)],
            output_video_path=os.path.join(t8_dir, "out.mp4"),
            workspace_dir=t8_dir,
            is_cancelled_func=lambda: True,  # Cancelled right at Checkpoint A
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t8_dir, [])
        if err_res is None or err_res.status != "cancelled":
            t8_errs.append("Expected status='cancelled'")
        if err_res and err_res.cancelled_stage != "mixing":
            t8_errs.append(f"Expected cancelled_stage='mixing', got {err_res.cancelled_stage}")
        if mock_extractor.extract.called:
            t8_errs.append("OriginalAudioExtractor must NOT be called after Checkpoint A cancellation")
        if mock_mixing.mix.called:
            t8_errs.append("AudioMixingService.mix must NOT be called after Checkpoint A cancellation")
        results.append((8, "Pre-preparation cancellation (Checkpoint A)", len(t8_errs) == 0, t8_errs))

        # =====================================================================
        # TEST 9: Post-mixing cancellation (Checkpoint C)
        # =====================================================================
        t9_errs = []
        t9_dir = os.path.join(test_root, "t9")
        os.makedirs(t9_dir, exist_ok=True)
        orig_video = os.path.join(t9_dir, "input.wav")
        create_pcm_wav(orig_video, 5.0)

        # Cancel condition triggers only after mixing (called 3rd time)
        call_counter = {"count": 0}
        def dynamic_cancel():
            call_counter["count"] += 1
            return call_counter["count"] >= 3  # Checkpoint C

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 3.0)],
            output_video_path=os.path.join(t9_dir, "out.mp4"),
            workspace_dir=t9_dir,
            is_cancelled_func=dynamic_cancel,
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t9_dir, [])
        if err_res is None or err_res.status != "cancelled":
            t9_errs.append("Expected status='cancelled' at Checkpoint C")
        if err_res and err_res.cancelled_stage != "mixing":
            t9_errs.append(f"Expected cancelled_stage='mixing', got {err_res.cancelled_stage}")
        # final_audio.wav was created by mix() before cancellation
        if not os.path.isfile(os.path.join(t9_dir, "final_audio.wav")):
            t9_errs.append("final_audio.wav should exist before Checkpoint C cancel")
        results.append((9, "Post-mixing cancellation (Checkpoint C)", len(t9_errs) == 0, t9_errs))

        # =====================================================================
        # TEST 10: Missing TTS file error
        # =====================================================================
        t10_errs = []
        t10_dir = os.path.join(test_root, "t10")
        os.makedirs(t10_dir, exist_ok=True)
        orig_video = os.path.join(t10_dir, "input.wav")
        create_pcm_wav(orig_video, 5.0)

        tts_blocks = [
            TTSAudioBlock(segment_id=1, start_time=1.0, duration=2.0, audio_path=os.path.join(t10_dir, "ghost.wav"))
        ]
        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 3.0)],
            output_video_path=os.path.join(t10_dir, "out.mp4"),
            workspace_dir=t10_dir,
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t10_dir, tts_blocks)
        if err_res is None or err_res.status != "failed":
            t10_errs.append("Expected status='failed' when TTS WAV is missing")
        elif "TTS audio file missing" not in err_res.error:
            t10_errs.append(f"Unexpected error: {err_res.error}")
        results.append((10, "Missing TTS file error", len(t10_errs) == 0, t10_errs))

        # =====================================================================
        # TEST 11: Master Data immutability
        # =====================================================================
        t11_errs = []
        t11_dir = os.path.join(test_root, "t11")
        os.makedirs(t11_dir, exist_ok=True)
        orig_video = os.path.join(t11_dir, "input.wav")
        create_pcm_wav(orig_video, 5.0)

        seg1 = make_test_segment(1, 1.0, 3.0)
        seg2 = make_test_segment(2, 3.0, 5.0)
        orig_segs = [copy.deepcopy(seg1), copy.deepcopy(seg2)]

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[seg1, seg2],
            output_video_path=os.path.join(t11_dir, "out.mp4"),
            workspace_dir=t11_dir,
        )
        svc._orchestrate_mixing(req, t11_dir, [])

        for s_curr, s_orig in zip([seg1, seg2], orig_segs):
            if s_curr != s_orig:
                t11_errs.append("SubtitleSegment data mutated")
            if s_curr.voice_id != "":
                t11_errs.append(f"Injected voice_id onto SubtitleSegment: '{s_curr.voice_id}'")
            if s_curr.voice_name != "":
                t11_errs.append(f"Injected voice_name onto SubtitleSegment: '{s_curr.voice_name}'")
        results.append((11, "Master Data immutability", len(t11_errs) == 0, t11_errs))

        # =====================================================================
        # TEST 12: Progress monotonic 55% -> 75%
        # =====================================================================
        t12_errs = []
        t12_dir = os.path.join(test_root, "t12")
        os.makedirs(t12_dir, exist_ok=True)
        orig_video = os.path.join(t12_dir, "input.wav")
        create_pcm_wav(orig_video, 5.0)

        recorded_progress = []
        def on_prog(pct, msg):
            recorded_progress.append((pct, msg))

        svc = VideoCreatorService()
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 3.0)],
            output_video_path=os.path.join(t12_dir, "out.mp4"),
            workspace_dir=t12_dir,
            progress_callback=on_prog,
        )
        svc._orchestrate_mixing(req, t12_dir, [])

        pcts = [p[0] for p in recorded_progress]
        if not pcts:
            t12_errs.append("No progress recorded")
        else:
            if pcts[0] != 55.0:
                t12_errs.append(f"Expected initial progress 55.0%, got {pcts[0]}")
            if pcts[-1] != 75.0:
                t12_errs.append(f"Expected final progress 75.0%, got {pcts[-1]}")
            if pcts != sorted(pcts):
                t12_errs.append(f"Progress is not monotonic: {pcts}")
        results.append((12, "Progress monotonic 55% -> 75%", len(t12_errs) == 0, t12_errs))

        # =====================================================================
        # TEST 13: Audio extraction delegation
        # =====================================================================
        t13_errs = []
        t13_dir = os.path.join(test_root, "t13")
        os.makedirs(t13_dir, exist_ok=True)
        fake_video_mp4 = os.path.join(t13_dir, "sample.mp4")
        with open(fake_video_mp4, "wb") as f:
            f.write(b"FAKE_MP4_HEADER_DATA")

        # Mock OriginalAudioExtractor to confirm it is invoked with correct args
        mock_extractor = MagicMock(spec=OriginalAudioExtractor)
        def fake_extract(in_p, out_p):
            create_pcm_wav(out_p, 4.0)
            return True, ""
        mock_extractor.extract.side_effect = fake_extract

        mock_mixing = MagicMock(spec=AudioMixingService)
        mock_mixing.mix.return_value = MixedAudioResult(
            final_audio_path=os.path.join(t13_dir, "final_audio.wav"),
            original_duration=4.0,
            total_duration=4.0,
            status="success",
        )

        svc = VideoCreatorService(original_audio_extractor=mock_extractor, audio_mixing_service=mock_mixing)
        req = VideoCreatorRequest(
            original_video_path=fake_video_mp4,
            segments=[make_test_segment(1, 1.0, 3.0)],
            output_video_path=os.path.join(t13_dir, "out.mp4"),
            workspace_dir=t13_dir,
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t13_dir, [])

        if not mock_extractor.extract.called:
            t13_errs.append("OriginalAudioExtractor was not called")
        else:
            called_in, called_out = mock_extractor.extract.call_args[0]
            if called_in != fake_video_mp4:
                t13_errs.append(f"Expected in={fake_video_mp4}, got {called_in}")
            expected_ext_out = os.path.join(t13_dir, "extracted_original_audio.wav")
            if os.path.abspath(called_out) != os.path.abspath(expected_ext_out):
                t13_errs.append(f"Expected out={expected_ext_out}, got {called_out}")

        if not mock_mixing.mix.called:
            t13_errs.append("AudioMixingService.mix was not called")
        else:
            mix_kwargs = mock_mixing.mix.call_args[1]
            if os.path.abspath(mix_kwargs.get("original_audio_path", "")) != os.path.abspath(os.path.join(t13_dir, "extracted_original_audio.wav")):
                t13_errs.append(f"Mixing service received wrong audio path: {mix_kwargs.get('original_audio_path')}")
        results.append((13, "Audio extraction delegation", len(t13_errs) == 0, t13_errs))

        # =====================================================================
        # TEST 14: Cancellation after extraction (Checkpoint B)
        # =====================================================================
        t14_errs = []
        t14_dir = os.path.join(test_root, "t14")
        os.makedirs(t14_dir, exist_ok=True)
        orig_video = os.path.join(t14_dir, "input.wav")
        create_pcm_wav(orig_video, 5.0)

        # Cancel right after extraction (Checkpoint B: called 2nd time)
        call_count_14 = {"count": 0}
        def cancel_at_checkpoint_b():
            call_count_14["count"] += 1
            return call_count_14["count"] >= 2  # False at Checkpoint A, True at Checkpoint B

        mock_mixing_14 = MagicMock(spec=AudioMixingService)
        svc = VideoCreatorService(audio_mixing_service=mock_mixing_14)
        req = VideoCreatorRequest(
            original_video_path=orig_video,
            segments=[make_test_segment(1, 1.0, 3.0)],
            output_video_path=os.path.join(t14_dir, "out.mp4"),
            workspace_dir=t14_dir,
            is_cancelled_func=cancel_at_checkpoint_b,
        )
        mixed_res, warns, err_res = svc._orchestrate_mixing(req, t14_dir, [])

        if err_res is None or err_res.status != "cancelled":
            t14_errs.append("Expected status='cancelled' at Checkpoint B")
        if err_res and err_res.cancelled_stage != "mixing":
            t14_errs.append(f"Expected cancelled_stage='mixing', got {err_res.cancelled_stage}")
        if mock_mixing_14.mix.called:
            t14_errs.append("AudioMixingService.mix() MUST NOT be called after Checkpoint B cancellation")
        # But extracted_original_audio.wav should exist because extraction succeeded before cancel
        ext_p = os.path.join(t14_dir, "extracted_original_audio.wav")
        if not os.path.isfile(ext_p):
            t14_errs.append("extracted_original_audio.wav should exist before Checkpoint B")
        results.append((14, "Cancellation after extraction (Checkpoint B)", len(t14_errs) == 0, t14_errs))

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
    print(f"KẾT QUẢ ACCEPTANCE STEP 8.3.5: {passed_count}/{len(results)} TESTS PASS")
    print("=" * 80)
    return passed_count == len(results)


if __name__ == "__main__":
    success = run_all_acceptance_tests()
    sys.exit(0 if success else 1)
