"""Full E2E UI Integration Regression Suite (Step 9.5).

Verifies the complete UI Integration Matrix (UI-01 -> UI-09) strictly adhering to:
- Contract Step 9.1 v1.1 (LOCKED)
- Contract Step 9.3 & Step 9.4 (LOCKED)
- Step 8 Isolation Principle: Mocks at the boundary between Worker and Service.
- Trust in VideoCreatorResult artifact paths without filesystem guessing.
"""

import os
import sys
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.models.subtitle_segment import SubtitleSegment
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
)
from ui.dialogs.pipeline_b_progress_dialog import PipelineBProgressDialog
from ui.worker_adapters.video_creator_adapter import VideoCreatorWorker


@pytest.fixture(scope="session")
def qapp():
    """Ensure a QApplication exists for GUI testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _create_sample_segments() -> list[SubtitleSegment]:
    return [
        SubtitleSegment(
            id=1,
            start=0.5,
            end=2.5,
            text="Chào buổi sáng",
            translated_text="Chào buổi sáng",
            final_gender="female",
            voice_id="vieneu_cogaihoatngon",
        ),
        SubtitleSegment(
            id=2,
            start=3.0,
            end=5.5,
            text="Hôm nay thời tiết rất đẹp",
            translated_text="Hôm nay thời tiết rất đẹp",
            final_gender="male",
            voice_id="vieneu_thanhnientutin",
        ),
    ]


class ScenarioMockService:
    """Mock service simulating the exact behavior of VideoCreatorService across 9 scenarios."""

    def __init__(
        self,
        scenario_key: str,
        artifacts_dir: str = "",
        extra_warnings: list[str] | None = None,
    ):
        self.scenario_key = scenario_key
        self.artifacts_dir = artifacts_dir
        self.extra_warnings = extra_warnings or []
        self.cancel_detected_at = ""

    def run(self, request: VideoCreatorRequest) -> VideoCreatorResult:
        # Preflight
        if request.progress_callback:
            request.progress_callback(0.0, "Đang kiểm tra môi trường và file đầu vào...")

        # UI-04: Preflight Fail-Fast
        if self.scenario_key == "preflight_fail":
            return VideoCreatorResult(
                status="failed",
                error="Preflight validation failed: Video file does not exist",
            )

        # Mapping
        if request.progress_callback:
            request.progress_callback(5.0, "Đã phân vai giọng đọc nhân vật...")

        # UI-02: Mid-TTS Cancellation
        if self.scenario_key == "cancel_mid_tts":
            if request.progress_callback:
                request.progress_callback(25.0, "Đang lồng tiếng AI câu 1/2...")
            # Simulate cancel from user
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                status="cancelled",
                cancelled_stage="tts",
                session_dir=os.path.join(self.artifacts_dir, "session_tts_cancel"),
            )

        # TTS Completion
        if request.progress_callback:
            request.progress_callback(55.0, "Hoàn tất lồng tiếng AI...")

        # Mixing
        if request.progress_callback:
            request.progress_callback(65.0, "Đang hạ âm lượng gốc và hòa âm...")
            request.progress_callback(75.0, "Hòa âm hoàn tất...")

        # Audio artifact created
        audio_art = os.path.join(self.artifacts_dir, "final_audio.wav")
        if self.artifacts_dir:
            with open(audio_art, "wb") as f:
                f.write(b"RIFF" + b"\x00" * 32)

        # UI-03: Mid-Export Cancellation
        if self.scenario_key == "cancel_mid_export":
            if request.progress_callback:
                request.progress_callback(80.0, "Đang đóng gói video MP4...")
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path=audio_art,
                status="cancelled",
                cancelled_stage="export",
                session_dir=os.path.join(self.artifacts_dir, "session_export_cancel"),
            )

        # UI-07: Exception Simulation
        if self.scenario_key == "unexpected_exception":
            raise RuntimeError("Fatal hardware I/O interrupt")

        # Export completed
        video_art = os.path.join(self.artifacts_dir, "output_video.mp4")
        if self.artifacts_dir:
            with open(video_art, "wb") as f:
                f.write(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)

        if request.progress_callback:
            request.progress_callback(95.0, "Đóng gói MP4 thành công, kiểm tra hậu kiểm...")

        # UI-08: Post-Export Cancellation (MP4 exists, Verification skipped)
        if self.scenario_key == "cancel_post_export":
            return VideoCreatorResult(
                output_video_path=video_art,
                output_audio_path=audio_art,
                status="cancelled",
                cancelled_stage="export",
                session_dir=os.path.join(self.artifacts_dir, "session_post_export"),
            )

        # Verification & Success
        if request.progress_callback:
            request.progress_callback(100.0, "Hoàn tất toàn bộ pipeline!")

        # UI-05: Zero-TTS
        if self.scenario_key == "zero_tts":
            return VideoCreatorResult(
                output_video_path=video_art,
                output_audio_path=audio_art,
                status="success",
                final_video_duration=5.0,
                audio_duration=5.0,
                total_segments=len(request.segments),
                tts_generated_count=0,
                tts_skipped_count=len(request.segments),
                subtitles_rendered_count=len(request.segments),
                subtitles_skipped_count=0,
                warnings=self.extra_warnings,
            )

        # UI-01 & UI-06: Happy Path & Warnings
        return VideoCreatorResult(
            output_video_path=video_art,
            output_audio_path=audio_art,
            status="success",
            final_video_duration=10.0,
            audio_duration=10.0,
            total_segments=len(request.segments),
            tts_generated_count=2,
            tts_skipped_count=0,
            subtitles_rendered_count=2,
            subtitles_skipped_count=0,
            warnings=self.extra_warnings,
        )


# =============================================================================
# UI-01: Full E2E Success Flow
# =============================================================================
def test_ui01_e2e_success_flow(qapp, tmp_path):
    mock_svc = ScenarioMockService(scenario_key="success", artifacts_dir=str(tmp_path))
    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(tmp_path / "final.mp4"),
        service=mock_svc,
    )

    # Wait for completion
    dialog._worker.wait(5000)
    qapp.processEvents()
    dialog.show()

    assert dialog._ui_state == "TERMINAL"
    assert dialog.progress_bar.value() == 100
    assert "THÀNH CÔNG" in dialog.lbl_status.text()
    assert dialog.btn_open_folder.isVisible() is True
    assert dialog.btn_close.isEnabled() is True
    assert dialog.btn_cancel.isVisible() is False

    # Check metrics presentation
    log_text = dialog.log_box.toPlainText()
    assert "Thời lượng video thành phẩm: 10.00s" in log_text
    assert "Đã lồng tiếng AI: 2" in log_text
    assert "Hiển thị phụ đề: 2" in log_text
    assert str(tmp_path / "output_video.mp4") in log_text

    dialog.close()
    qapp.processEvents()


# =============================================================================
# UI-02: Cooperative Cancellation (Mid-TTS)
# =============================================================================
def test_ui02_cooperative_cancel_mid_tts(qapp, tmp_path):
    mock_svc = ScenarioMockService(scenario_key="cancel_mid_tts", artifacts_dir=str(tmp_path))
    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(tmp_path / "final.mp4"),
        service=mock_svc,
    )

    dialog._worker.wait(5000)
    qapp.processEvents()
    dialog.show()

    assert dialog._ui_state == "TERMINAL"
    assert "ĐÃ ĐƯỢC HỦY" in dialog.lbl_status.text()
    assert "TTS" in dialog.lbl_status.text()
    assert dialog.btn_open_folder.isVisible() is False
    assert dialog.btn_close.isEnabled() is True

    log_text = dialog.log_box.toPlainText()
    assert "Giai đoạn dừng: tts" in log_text
    assert "session_tts_cancel" in log_text

    dialog.close()
    qapp.processEvents()


# =============================================================================
# UI-03: Cooperative Cancellation (Mid-Export)
# =============================================================================
def test_ui03_cooperative_cancel_mid_export(qapp, tmp_path):
    mock_svc = ScenarioMockService(scenario_key="cancel_mid_export", artifacts_dir=str(tmp_path))
    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(tmp_path / "final.mp4"),
        service=mock_svc,
    )

    dialog._worker.wait(5000)
    qapp.processEvents()
    dialog.show()

    assert dialog._ui_state == "TERMINAL"
    assert "ĐÃ ĐƯỢC HỦY" in dialog.lbl_status.text()
    assert "EXPORT" in dialog.lbl_status.text()
    # Output video was not finalized -> folder button hidden
    assert dialog.btn_open_folder.isVisible() is False

    log_text = dialog.log_box.toPlainText()
    assert "Giai đoạn dừng: export" in log_text
    assert "session_export_cancel" in log_text

    dialog.close()
    qapp.processEvents()


# =============================================================================
# UI-04: Preflight Fail-Fast
# =============================================================================
def test_ui04_preflight_fail_fast(qapp, tmp_path):
    mock_svc = ScenarioMockService(scenario_key="preflight_fail", artifacts_dir=str(tmp_path))

    with patch.object(QMessageBox, "critical") as mock_box:
        dialog = PipelineBProgressDialog(
            original_video_path="non_existent_input.mp4",
            segments=_create_sample_segments(),
            output_video_path=str(tmp_path / "final.mp4"),
            service=mock_svc,
        )

        dialog._worker.wait(5000)
        qapp.processEvents()
        dialog.show()

        mock_box.assert_called_once()
        assert "Preflight validation failed" in mock_box.call_args[0][2]

    assert dialog._ui_state == "TERMINAL"
    assert "THẤT BẠI" in dialog.lbl_status.text()
    assert dialog.btn_open_folder.isVisible() is False
    assert dialog.btn_close.isEnabled() is True

    dialog.close()
    qapp.processEvents()


# =============================================================================
# UI-05: Zero-TTS Flow
# =============================================================================
def test_ui05_zero_tts_flow(qapp, tmp_path):
    mock_svc = ScenarioMockService(scenario_key="zero_tts", artifacts_dir=str(tmp_path))
    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(tmp_path / "final.mp4"),
        service=mock_svc,
    )

    dialog._worker.wait(5000)
    qapp.processEvents()
    dialog.show()

    assert dialog._ui_state == "TERMINAL"
    assert dialog.progress_bar.value() == 100
    assert "THÀNH CÔNG" in dialog.lbl_status.text()
    assert dialog.btn_open_folder.isVisible() is True

    log_text = dialog.log_box.toPlainText()
    assert "Đã lồng tiếng AI: 0" in log_text
    assert "Không lồng tiếng AI: 2" in log_text
    assert "Hiển thị phụ đề: 2" in log_text

    dialog.close()
    qapp.processEvents()


# =============================================================================
# UI-06: Warning Display Integrity
# =============================================================================
def test_ui06_warning_display_integrity(qapp, tmp_path):
    warnings = [
        "Audio duration exceeds video. Applied '-shortest' policy.",
        "Segment #001 speedup ratio reached maximum 1.20x.",
    ]
    mock_svc = ScenarioMockService(
        scenario_key="success",
        artifacts_dir=str(tmp_path),
        extra_warnings=warnings,
    )
    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(tmp_path / "final.mp4"),
        service=mock_svc,
    )

    dialog._worker.wait(5000)
    qapp.processEvents()
    dialog.show()

    # Crucial assertion: warning must NOT change state to failed
    assert dialog._ui_state == "TERMINAL"
    assert "THÀNH CÔNG" in dialog.lbl_status.text()
    assert dialog.btn_open_folder.isVisible() is True

    log_text = dialog.log_box.toPlainText()
    assert "CẢNH BÁO HẬU KỲ (THÀNH PHẨM VẪN HỢP LỆ)" in log_text
    assert "Applied '-shortest' policy" in log_text
    assert "maximum 1.20x" in log_text

    dialog.close()
    qapp.processEvents()


# =============================================================================
# UI-07: Thread Safety & Exception Resilience
# =============================================================================
def test_ui07_thread_safety_and_exception_resilience(qapp, tmp_path):
    mock_svc = ScenarioMockService(scenario_key="unexpected_exception", artifacts_dir=str(tmp_path))

    with patch.object(QMessageBox, "critical") as mock_box:
        dialog = PipelineBProgressDialog(
            original_video_path="orig.mp4",
            segments=_create_sample_segments(),
            output_video_path=str(tmp_path / "final.mp4"),
            service=mock_svc,
        )

        dialog._worker.wait(5000)
        qapp.processEvents()
        dialog.show()

        mock_box.assert_called_once()
        assert "Fatal hardware I/O interrupt" in mock_box.call_args[0][2]

    # Worker shielded GUI from crash
    assert dialog._ui_state == "TERMINAL"
    assert "THẤT BẠI" in dialog.lbl_status.text()
    assert dialog.btn_close.isEnabled() is True

    dialog.close()
    qapp.processEvents()


# =============================================================================
# UI-08: Post-Export Cancellation (MP4 Preserved)
# =============================================================================
def test_ui08_post_export_cancellation_preserves_artifact(qapp, tmp_path):
    mock_svc = ScenarioMockService(scenario_key="cancel_post_export", artifacts_dir=str(tmp_path))
    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(tmp_path / "final.mp4"),
        service=mock_svc,
    )

    dialog._worker.wait(5000)
    qapp.processEvents()
    dialog.show()

    # State is CANCELLED
    assert dialog._ui_state == "TERMINAL"
    assert "ĐÃ ĐƯỢC HỦY" in dialog.lbl_status.text()
    assert "EXPORT" in dialog.lbl_status.text()

    # But MP4 artifact was generated before cancel, so button is VISIBLE
    assert dialog.btn_open_folder.isVisible() is True
    log_text = dialog.log_box.toPlainText()
    assert "Video hoàn thành trước khi hủy" in log_text
    assert str(tmp_path / "output_video.mp4") in log_text

    dialog.close()
    qapp.processEvents()


# =============================================================================
# UI-09: Artifact Display Semantics Matrix
# =============================================================================
def test_ui09_artifact_display_semantics_matrix(qapp, tmp_path):
    test_cases = [
        # (status, output_audio, output_video, expect_open_btn, expect_video_in_log)
        ("cancelled", "", "", False, False),
        ("cancelled", "audio.wav", "", False, False),
        ("cancelled", "audio.wav", "video.mp4", True, True),
        ("failed", "audio.wav", "", False, False),
        ("success", "audio.wav", "video.mp4", True, True),
    ]

    for idx, (stat, aud, vid, exp_btn, exp_vid_log) in enumerate(test_cases):
        sub_dir = tmp_path / f"case_{idx}"
        sub_dir.mkdir(exist_ok=True)

        aud_path = str(sub_dir / aud) if aud else ""
        if aud_path:
            with open(aud_path, "wb") as f:
                f.write(b"\x00" * 16)

        vid_path = str(sub_dir / vid) if vid else ""
        if vid_path:
            with open(vid_path, "wb") as f:
                f.write(b"\x00" * 16)

        res = VideoCreatorResult(
            output_video_path=vid_path,
            output_audio_path=aud_path,
            status=stat,
            cancelled_stage="export" if stat == "cancelled" else "",
            error="Simulated error" if stat == "failed" else "",
        )

        class MockFixedResultService:
            def __init__(self, r):
                self.r = r
            def run(self, req):
                return self.r

        with patch.object(QMessageBox, "critical"):
            dialog = PipelineBProgressDialog(
                original_video_path="orig.mp4",
                segments=_create_sample_segments(),
                output_video_path="final.mp4",
                service=MockFixedResultService(res),
            )
            dialog._worker.wait(3000)
            qapp.processEvents()
            dialog.show()

            assert dialog.btn_open_folder.isVisible() is exp_btn
            if exp_vid_log:
                assert vid_path in dialog.log_box.toPlainText()
            else:
                assert vid_path == ""

            dialog.close()
            qapp.processEvents()
