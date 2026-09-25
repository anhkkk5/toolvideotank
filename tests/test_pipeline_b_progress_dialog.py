"""Acceptance Test Suite for PipelineBProgressDialog (Step 9.3).

Verifies all 9 scenarios (D-01 -> D-09) defined in Contract Step 9.1 v1.1 & Step 9.3:
- D-01: Dialog initialization (Worker attached, initial state RUNNING, buttons state)
- D-02: Progress + log update (progress_updated & log_emitted reflected in UI widgets)
- D-03: Stage badges update (step indicators update correctly across stages)
- D-04: Cancel click (request_cancel called, state -> CANCELLING, button disabled)
- D-05: Close safety (closeEvent ignores event when running, non-blocking)
- D-06: Cancel double-click guard (state CANCELLING prevents duplicate cancels)
- D-07: Terminal success (100%, success message, open folder visible, close enabled)
- D-08: Terminal cancelled & failed (proper messages, buttons state updated)
- D-09: Worker lifetime (strong reference maintained, cleaned up on finish)
"""

import os
import sys
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QCloseEvent
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
    """Ensure a QApplication exists for GUI widget testing."""
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
            text="Câu một",
            translated_text="Câu một",
            final_gender="female",
        ),
        SubtitleSegment(
            id=2,
            start=3.0,
            end=5.0,
            text="Câu hai",
            translated_text="Câu hai",
            final_gender="male",
        ),
    ]


class ControlledMockService:
    """Service allowing controllable pauses to inspect running/cancelling UI states."""

    def __init__(self, result: VideoCreatorResult | None = None):
        self.result = result or VideoCreatorResult(
            status="success",
            output_video_path="output/test_video.mp4",
        )
        self.pause_event = threading.Event()
        self.was_cancelled_during_run = False

    def run(self, request: VideoCreatorRequest) -> VideoCreatorResult:
        if request.progress_callback:
            request.progress_callback(10.0, "Starting...")
        # Wait if pause event is set
        if self.pause_event.is_set():
            time_left = 3.0
            while time_left > 0:
                if request.is_cancelled_func and request.is_cancelled_func():
                    self.was_cancelled_during_run = True
                    return VideoCreatorResult(status="cancelled", cancelled_stage="tts")
                threading.Event().wait(0.05)
                time_left -= 0.05

        if request.is_cancelled_func and request.is_cancelled_func():
            self.was_cancelled_during_run = True
            return VideoCreatorResult(status="cancelled", cancelled_stage="tts")

        return self.result


# =============================================================================
# D-01: Dialog Initialization
# =============================================================================
def test_d01_dialog_initialization(qapp):
    mock_service = ControlledMockService()
    dialog = PipelineBProgressDialog(
        original_video_path="videos/sample.mp4",
        segments=_create_sample_segments(),
        output_video_path="out/sample_vi.mp4",
        service=mock_service,
    )

    assert dialog._worker is not None
    assert dialog._ui_state == "RUNNING"
    assert dialog.btn_cancel.isEnabled() is True
    assert dialog.btn_cancel.text() == "Hủy tiến trình"
    assert dialog.btn_close.isEnabled() is False
    assert dialog.btn_open_folder.isVisible() is False
    assert "sample.mp4" in dialog.windowTitle() or "Pipeline B" in dialog.windowTitle()

    # Clean up worker thread
    dialog._worker.wait(2000)
    qapp.processEvents()


# =============================================================================
# D-02: Progress and Log Update
# =============================================================================
def test_d02_progress_and_log_update(qapp):
    dialog = PipelineBProgressDialog(
        original_video_path="sample.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=ControlledMockService(),
    )

    dialog._on_progress_updated(45.0, "Đang lồng tiếng câu 2/5 (45.0%)")
    assert dialog.progress_bar.value() == 45
    assert dialog.lbl_status.text() == "Đang lồng tiếng câu 2/5 (45.0%)"

    dialog._on_log_emitted("Test log line 123")
    assert "Test log line 123" in dialog.log_box.toPlainText()

    dialog._worker.wait(2000)
    qapp.processEvents()


# =============================================================================
# D-03: Stage Badges Update
# =============================================================================
def test_d03_stage_badges_update(qapp):
    dialog = PipelineBProgressDialog(
        original_video_path="sample.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=ControlledMockService(),
    )

    # 1. Preflight / Mapping
    dialog._on_stage_changed("mapping", "Phân vai giọng đọc")
    assert "Phân vai" in dialog.lbl_step2.text()
    assert "Chờ xử lý" in dialog.lbl_step3.text()

    # 2. TTS
    dialog._on_stage_changed("tts", "Lồng tiếng AI & Khớp thời lượng")
    assert "Đang thực hiện" in dialog.lbl_step2.text()
    assert "Chờ xử lý" in dialog.lbl_step3.text()

    # 3. Mixing / Export
    dialog._on_stage_changed("mixing", "Hòa âm & Ducking âm thanh")
    assert "Đã xong" in dialog.lbl_step2.text()
    assert "Hòa âm" in dialog.lbl_step3.text()

    # 4. Completed
    dialog._on_stage_changed("completed", "Hoàn tất tạo video")
    assert "Đã xong" in dialog.lbl_step2.text()
    assert "Đã xong" in dialog.lbl_step3.text()

    dialog._worker.wait(2000)
    qapp.processEvents()


# =============================================================================
# D-04: Cancel Click
# =============================================================================
def test_d04_cancel_click(qapp):
    mock_service = ControlledMockService()
    mock_service.pause_event.set()  # Pause to simulate running state

    dialog = PipelineBProgressDialog(
        original_video_path="sample.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=mock_service,
    )

    assert dialog._ui_state == "RUNNING"
    dialog._on_cancel_clicked()

    assert dialog._ui_state == "CANCELLING"
    assert dialog.btn_cancel.isEnabled() is False
    assert dialog.btn_cancel.text() == "Đang hủy..."
    assert dialog._worker.is_cancelled() is True

    dialog._worker.wait(2000)
    qapp.processEvents()


# =============================================================================
# D-05: Close Safety (Non-blocking GUI)
# =============================================================================
def test_d05_close_safety_non_blocking(qapp):
    mock_service = ControlledMockService()
    mock_service.pause_event.set()

    dialog = PipelineBProgressDialog(
        original_video_path="sample.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=mock_service,
    )

    event = QCloseEvent()
    dialog.closeEvent(event)

    # Event must be ignored while worker is running
    assert not event.isAccepted()
    assert dialog._close_requested is True
    assert dialog._ui_state == "CANCELLING"
    assert dialog._worker.is_cancelled() is True

    dialog._worker.wait(2000)
    qapp.processEvents()


# =============================================================================
# D-06: Cancel Double-Click Guard
# =============================================================================
def test_d06_cancel_double_click_guard(qapp):
    mock_service = ControlledMockService()
    mock_service.pause_event.set()

    dialog = PipelineBProgressDialog(
        original_video_path="sample.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=mock_service,
    )

    # First cancel click
    dialog._on_cancel_clicked()
    assert dialog._ui_state == "CANCELLING"

    # Second cancel click while CANCELLING
    dialog._on_cancel_clicked()
    assert dialog._ui_state == "CANCELLING"
    assert dialog.btn_cancel.isEnabled() is False
    assert dialog.btn_cancel.text() == "Đang hủy..."

    dialog._worker.wait(2000)
    qapp.processEvents()


# =============================================================================
# D-07: Terminal Success
# =============================================================================
def test_d07_terminal_success(qapp, tmp_path):
    out_video = tmp_path / "final_success.mp4"
    out_video.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    success_result = VideoCreatorResult(
        output_video_path=str(out_video),
        status="success",
        total_segments=2,
    )

    dialog = PipelineBProgressDialog(
        original_video_path="sample.mp4",
        segments=_create_sample_segments(),
        output_video_path=str(out_video),
        service=ControlledMockService(result=success_result),
    )

    dialog._on_pipeline_finished(success_result)

    dialog.show()
    assert dialog._ui_state == "TERMINAL"
    assert dialog.progress_bar.value() == 100
    assert "THÀNH CÔNG" in dialog.lbl_status.text()
    assert dialog.btn_close.isEnabled() is True
    assert dialog.btn_cancel.isVisible() is False
    assert dialog.btn_open_folder.isVisible() is True

    dialog._worker.wait(2000)
    dialog.close()
    qapp.processEvents()


# =============================================================================
# D-08: Terminal Cancelled and Failed
# =============================================================================
def test_d08_terminal_cancelled_and_failed(qapp):
    dialog = PipelineBProgressDialog(
        original_video_path="sample.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=ControlledMockService(),
    )

    # 1. Test cancelled handling
    cancelled_result = VideoCreatorResult(
        status="cancelled",
        cancelled_stage="mixing",
        session_dir="session/temp_dir",
    )
    dialog._on_pipeline_finished(cancelled_result)

    assert dialog._ui_state == "TERMINAL"
    assert "ĐÃ ĐƯỢC HỦY" in dialog.lbl_status.text()
    assert "MIXING" in dialog.lbl_status.text()
    assert dialog.btn_close.isEnabled() is True
    assert dialog.btn_cancel.isVisible() is False

    # 2. Test failed handling
    failed_result = VideoCreatorResult(
        status="failed",
        error="Audio mixing sample rate mismatch",
    )
    with patch.object(QMessageBox, "critical") as mock_crit:
        dialog._on_pipeline_finished(failed_result)
        mock_crit.assert_called_once()
        assert "Audio mixing sample rate mismatch" in dialog.log_box.toPlainText()
        assert "THẤT BẠI" in dialog.lbl_status.text()

    dialog._worker.wait(2000)
    qapp.processEvents()


# =============================================================================
# D-09: Worker Lifetime and Strong Reference
# =============================================================================
def test_d09_worker_lifetime_and_cleanup(qapp):
    mock_service = ControlledMockService()
    dialog = PipelineBProgressDialog(
        original_video_path="sample.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
        service=mock_service,
    )

    # During running, strong reference exists
    worker_ref = dialog._worker
    assert worker_ref is not None
    assert worker_ref.isRunning() or worker_ref.isFinished()

    # Wait for thread finish
    worker_ref.wait(2000)
    qapp.processEvents()

    # Trigger cleanup slot
    dialog._on_worker_thread_finished()
    assert dialog._worker is None
