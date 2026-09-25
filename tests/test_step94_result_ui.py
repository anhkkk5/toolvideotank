"""Acceptance Test Suite for Step 9.4: Result / Error / Warning UI.

Verifies all 7 scenarios (R-01 -> R-07) defined in Contract Step 9.4:
- R-01: Success metrics + output paths + folder button visible
- R-02: Warning presentation with yellow header, maintains success state
- R-03: Cancellation post-export preserves and displays video artifact
- R-04: Cancellation mid-TTS without video artifact hides folder button
- R-05: Failed terminal displays red status, logs error, triggers QMessageBox.critical
- R-06: Cross-platform folder explorer helper execution
- R-07: Defensive handling for unknown terminal status without crashing
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.models.subtitle_segment import SubtitleSegment
from app.services.video_creator_service import VideoCreatorResult
from ui.dialogs.pipeline_b_progress_dialog import PipelineBProgressDialog


@pytest.fixture(scope="session")
def qapp():
    """Ensure a QApplication exists for GUI testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _create_sample_segments() -> list[SubtitleSegment]:
    return [
        SubtitleSegment(id=1, start=0.0, end=2.0, text="Câu 1", final_gender="female"),
        SubtitleSegment(id=2, start=2.0, end=4.0, text="Câu 2", final_gender="male"),
    ]


class DummyService:
    def run(self, request):
        return VideoCreatorResult(status="success")


# =============================================================================
# R-01: Success Metrics + Output Paths
# =============================================================================
def test_r01_success_metrics_and_output(qapp, tmp_path):
    out_video = tmp_path / "movie_final.mp4"
    out_video.write_bytes(b"\x00" * 32)
    out_audio = tmp_path / "movie_mix.wav"
    out_audio.write_bytes(b"\x00" * 32)

    result = VideoCreatorResult(
        output_video_path=str(out_video),
        output_audio_path=str(out_audio),
        status="success",
        final_video_duration=15.50,
        audio_duration=15.50,
        total_segments=10,
        tts_generated_count=8,
        tts_skipped_count=2,
        subtitles_rendered_count=10,
        subtitles_skipped_count=0,
    )

    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(out_video),
        service=DummyService(),
    )
    dialog._on_pipeline_finished(result)
    dialog.show()

    log_text = dialog.log_box.toPlainText()

    # Verify metrics convention
    assert "Thời lượng video thành phẩm: 15.50s" in log_text
    assert "Thời lượng audio thành phẩm: 15.50s" in log_text
    assert "Tổng số câu: 10" in log_text
    assert "Đã lồng tiếng AI: 8" in log_text
    assert "Không lồng tiếng AI: 2" in log_text
    assert "Hiển thị phụ đề: 10" in log_text
    assert "Không hiển thị phụ đề: 0" in log_text

    # Verify artifacts
    assert str(out_video) in log_text
    assert str(out_audio) in log_text
    assert dialog.btn_open_folder.isVisible() is True
    assert dialog.progress_bar.value() == 100

    dialog._worker.wait(1000)
    dialog.close()
    qapp.processEvents()


# =============================================================================
# R-02: Warning Presentation (Preserves Success Status)
# =============================================================================
def test_r02_warning_presentation(qapp, tmp_path):
    out_video = tmp_path / "warn_final.mp4"
    out_video.write_bytes(b"\x00" * 32)

    result = VideoCreatorResult(
        output_video_path=str(out_video),
        status="success",
        final_video_duration=5.0,
        audio_duration=5.2,
        total_segments=2,
        warnings=[
            "Audio duration (5.20s) exceeds video duration (5.00s). Applied '-shortest' policy.",
            "Segment #002 speed adjusted by 1.15x to fit slot.",
        ],
    )

    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(out_video),
        service=DummyService(),
    )
    dialog._on_pipeline_finished(result)
    dialog.show()

    log_text = dialog.log_box.toPlainText()

    # Must contain warning section
    assert "CẢNH BÁO HẬU KỲ (THÀNH PHẨM VẪN HỢP LỆ)" in log_text
    assert "Applied '-shortest' policy" in log_text
    assert "Segment #002 speed adjusted by 1.15x" in log_text

    # Must remain SUCCESS
    assert "THÀNH CÔNG" in dialog.lbl_status.text()
    assert dialog._ui_state == "TERMINAL"
    assert dialog.output_mp4 == str(out_video)

    dialog._worker.wait(1000)
    dialog.close()
    qapp.processEvents()


# =============================================================================
# R-03: Post-Export Cancellation Artifact Preservation
# =============================================================================
def test_r03_post_export_cancellation_artifact_preservation(qapp, tmp_path):
    out_video = tmp_path / "post_export_cancelled.mp4"
    out_video.write_bytes(b"\x00" * 32)
    out_audio = tmp_path / "mix.wav"
    out_audio.write_bytes(b"\x00" * 32)

    result = VideoCreatorResult(
        output_video_path=str(out_video),
        output_audio_path=str(out_audio),
        status="cancelled",
        cancelled_stage="export",
        session_dir="session/export_run_01",
    )

    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(out_video),
        service=DummyService(),
    )
    dialog._on_pipeline_finished(result)
    dialog.show()

    log_text = dialog.log_box.toPlainText()

    # Must reflect cancelled status
    assert "ĐÃ ĐƯỢC HỦY" in dialog.lbl_status.text()
    assert "EXPORT" in dialog.lbl_status.text()

    # Video artifact is preserved on disk, so folder button is visible
    assert dialog.btn_open_folder.isVisible() is True
    assert "Video hoàn thành trước khi hủy" in log_text
    assert str(out_video) in log_text
    assert str(out_audio) in log_text

    dialog._worker.wait(1000)
    dialog.close()
    qapp.processEvents()


# =============================================================================
# R-04: Mid-TTS Cancellation Without Video Artifact
# =============================================================================
def test_r04_mid_tts_cancellation_no_video_artifact(qapp):
    result = VideoCreatorResult(
        output_video_path="",
        output_audio_path="",
        status="cancelled",
        cancelled_stage="tts",
        session_dir="session/tts_run_02",
    )

    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=DummyService(),
    )
    dialog._on_pipeline_finished(result)
    dialog.show()

    log_text = dialog.log_box.toPlainText()

    assert "ĐÃ ĐƯỢC HỦY" in dialog.lbl_status.text()
    assert "TTS" in dialog.lbl_status.text()
    # No video artifact -> folder button hidden
    assert dialog.btn_open_folder.isVisible() is False
    assert "session/tts_run_02" in log_text

    dialog._worker.wait(1000)
    dialog.close()
    qapp.processEvents()


# =============================================================================
# R-05: Technical Error Handling
# =============================================================================
def test_r05_technical_error_handling(qapp, tmp_path):
    out_audio = tmp_path / "mid_audio.wav"
    out_audio.write_bytes(b"\x00" * 32)

    result = VideoCreatorResult(
        output_video_path="",
        output_audio_path=str(out_audio),
        status="failed",
        error="FFmpeg exit code 1: Unable to open input video stream",
        session_dir="session/fail_01",
    )

    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=DummyService(),
    )

    with patch.object(QMessageBox, "critical") as mock_box:
        dialog._on_pipeline_finished(result)
        mock_box.assert_called_once()
        call_args = mock_box.call_args[0]
        assert "FFmpeg exit code 1" in call_args[2]

    log_text = dialog.log_box.toPlainText()
    assert "TIẾN TRÌNH THẤT BẠI" in dialog.lbl_status.text()
    assert "FFmpeg exit code 1" in log_text
    assert "Audio trung gian bảo toàn" in log_text
    assert dialog.btn_close.isEnabled() is True
    assert dialog.btn_open_folder.isVisible() is False

    dialog._worker.wait(1000)
    dialog.close()
    qapp.processEvents()


# =============================================================================
# R-06: Cross-Platform Folder Explorer
# =============================================================================
def test_r06_cross_platform_folder_explorer(qapp, tmp_path):
    out_video = tmp_path / "test_exp.mp4"
    out_video.write_bytes(b"\x00" * 32)

    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(out_video),
        service=DummyService(),
    )
    dialog.output_mp4 = str(out_video)

    # 1. Windows simulation
    with patch("sys.platform", "win32"), patch("subprocess.Popen") as mock_popen:
        dialog._on_open_folder_clicked()
        mock_popen.assert_called_once()
        assert "explorer /select" in mock_popen.call_args[0][0]

    # 2. Darwin (macOS) simulation
    with patch("sys.platform", "darwin"), patch("subprocess.Popen") as mock_popen:
        dialog._on_open_folder_clicked()
        mock_popen.assert_called_once()
        assert mock_popen.call_args[0][0] == ["open", "-R", str(out_video)]

    # 3. Linux simulation
    with patch("sys.platform", "linux"), patch("subprocess.Popen") as mock_popen:
        dialog._on_open_folder_clicked()
        mock_popen.assert_called_once()
        assert mock_popen.call_args[0][0] == ["xdg-open", str(tmp_path)]

    dialog._worker.wait(1000)
    dialog.close()
    qapp.processEvents()


# =============================================================================
# R-07: Unknown Terminal Status (Defensive Handling)
# =============================================================================
def test_r07_unknown_terminal_status(qapp):
    unexpected_result = VideoCreatorResult(
        status="aborted_by_third_party",  # Non-standard status
        error="Unknown socket disconnect",
    )

    dialog = PipelineBProgressDialog(
        original_video_path="orig.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=DummyService(),
    )

    # Must not raise unhandled exception
    dialog._on_pipeline_finished(unexpected_result)

    assert "TRẠNG THÁI TIẾN TRÌNH KHÔNG XÁC ĐỊNH" in dialog.lbl_status.text()
    assert "aborted_by_third_party" in dialog.log_box.toPlainText()
    assert dialog.btn_close.isEnabled() is True
    assert dialog._ui_state == "TERMINAL"

    dialog._worker.wait(1000)
    dialog.close()
    qapp.processEvents()
