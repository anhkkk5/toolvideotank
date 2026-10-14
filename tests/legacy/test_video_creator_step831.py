"""Test Acceptance cho Bước 8.3.1 — Khởi tạo VideoCreatorService & Data Models."""

import dataclasses
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def test_step831():
    print("=" * 80)
    print("KIỂM THỬ ACCEPTANCE: BƯỚC 8.3.1 — KHỞI TẠO VIDEOCREATORSERVICE & DATA MODELS")
    print("=" * 80)

    tests_passed = 0
    total_tests = 9

    # 1. Import module
    try:
        from app.services.video_creator_service import (
            VoiceAssignment,
            VideoCreatorConfig,
            VideoCreatorRequest,
            VideoCreatorResult,
            VideoCreatorService,
        )
        from app.models.subtitle_segment import SubtitleSegment
        print("[1] Import module: PASS")
        tests_passed += 1
    except Exception as e:
        print(f"[1] Import module: FAIL ({e})")
        return 1

    # 2. Khởi tạo VoiceAssignment
    try:
        va = VoiceAssignment(segment_id=10, voice_id="vieneu_thanhnientutin", is_tts_eligible=True, reason="male_mapping")
        assert va.segment_id == 10
        assert va.voice_id == "vieneu_thanhnientutin"
        assert va.is_tts_eligible is True
        assert va.reason == "male_mapping"
        print("[2] Khởi tạo VoiceAssignment: PASS")
        tests_passed += 1
    except Exception as e:
        print(f"[2] Khởi tạo VoiceAssignment: FAIL ({e})")

    # 3. VoiceAssignment immutable
    try:
        is_frozen = False
        try:
            va.voice_id = "other_voice"  # type: ignore
        except dataclasses.FrozenInstanceError:
            is_frozen = True
        assert is_frozen, "VoiceAssignment phải là frozen dataclass"
        print("[3] VoiceAssignment immutable: PASS")
        tests_passed += 1
    except Exception as e:
        print(f"[3] VoiceAssignment immutable: FAIL ({e})")

    # 4. Khởi tạo VideoCreatorConfig
    try:
        cfg = VideoCreatorConfig(
            overflow_policy="freeze_end",
            duck_volume=0.15,
            max_speedup_ratio=1.15,
            cleanup_intermediate_audio=True,
        )
        assert cfg.overflow_policy == "freeze_end"
        assert cfg.duck_volume == 0.15
        assert cfg.max_speedup_ratio == 1.15
        assert cfg.cleanup_intermediate_audio is True
        assert cfg.subtitle_config.border_style == 1
        assert cfg.subtitle_config.outline_width == 2
        print("[4] Khởi tạo VideoCreatorConfig: PASS")
        tests_passed += 1
    except Exception as e:
        print(f"[4] Khởi tạo VideoCreatorConfig: FAIL ({e})")

    # 5. Khởi tạo VideoCreatorRequest
    try:
        dummy_seg = SubtitleSegment(id=1, start=0.0, end=2.0, text="Hello", translated_text="Xin chào")
        req = VideoCreatorRequest(
            original_video_path="test_video.mp4",
            segments=[dummy_seg],
            output_video_path="output.mp4",
            workspace_dir="workspace_temp",
            config=cfg,
        )
        assert req.original_video_path == "test_video.mp4"
        assert len(req.segments) == 1
        assert req.output_video_path == "output.mp4"
        print("[5] Khởi tạo VideoCreatorRequest: PASS")
        tests_passed += 1
    except Exception as e:
        print(f"[5] Khởi tạo VideoCreatorRequest: FAIL ({e})")

    # 6. Khởi tạo VideoCreatorResult
    try:
        res = VideoCreatorResult(
            output_video_path="output.mp4",
            output_audio_path="session/final_audio.wav",
            session_dir="session",
            video_duration=10.0,
            audio_duration=8.5,
            final_video_duration=10.0,
            total_segments=1,
            tts_generated_count=1,
            tts_skipped_count=0,
            subtitles_rendered_count=1,
            subtitles_skipped_count=0,
            status="success",
            cancelled_stage="",
            warnings=["Sample warning"],
            error="",
        )
        assert res.output_audio_path == "session/final_audio.wav"
        assert res.session_dir == "session"
        assert res.subtitles_skipped_count == 0
        assert res.cancelled_stage == ""
        assert res.status == "success"
        print("[6] Khởi tạo VideoCreatorResult: PASS")
        tests_passed += 1
    except Exception as e:
        print(f"[6] Khởi tạo VideoCreatorResult: FAIL ({e})")

    # 7. VideoCreatorService()
    try:
        service = VideoCreatorService()
        assert service is not None
        # Test skeleton run call
        dummy_result = service.run(req)
        assert dummy_result.output_video_path == "output.mp4"
        assert dummy_result.total_segments == 1
        assert dummy_result.status == "success"
        print("[7] VideoCreatorService() & run skeleton: PASS")
        tests_passed += 1
    except Exception as e:
        print(f"[7] VideoCreatorService() & run skeleton: FAIL ({e})")

    # 8. to_dict()
    try:
        d = res.to_dict()
        assert isinstance(d, dict)
        assert d["output_video_path"] == "output.mp4"
        assert d["session_dir"] == "session"
        assert d["cancelled_stage"] == ""
        assert d["status"] == "success"
        assert "warnings" in d
        print("[8] to_dict(): PASS")
        tests_passed += 1
    except Exception as e:
        print(f"[8] to_dict(): FAIL ({e})")

    # 9. Không gọi TTS/FFmpeg khi import/khởi tạo
    # Service không thực hiện subprocess hay tạo file âm thanh nào
    try:
        svc = VideoCreatorService()
        # Xác nhận các thuộc tính downstream là None hoặc injection sạch
        assert svc.voice_mapping_service is None
        assert svc.tts_pipeline_service is None
        assert svc.audio_mixing_service is None
        assert svc.video_export_service is None
        print("[9] Không gọi TTS/FFmpeg khi import/khởi tạo: PASS")
        tests_passed += 1
    except Exception as e:
        print(f"[9] Không gọi TTS/FFmpeg khi import/khởi tạo: FAIL ({e})")

    print("=" * 80)
    print(f"KẾT QUẢ ACCEPTANCE 8.3.1: {tests_passed}/{total_tests} TESTS PASS")
    print("=" * 80)

    return 0 if tests_passed == total_tests else 1


if __name__ == "__main__":
    sys.exit(test_step831())
