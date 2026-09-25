"""Unit Tests for VideoCreatorWorker Adapter (Step 9.2 Acceptance Suite).

Verifies all 10 scenarios (W-01 -> W-10) defined in Contract Step 9.1 v1.1:
- W-01: Worker initialization with SubtitleSegment and config
- W-02: request_cancel() sets threading.Event
- W-03: is_cancelled() reflects event state
- W-04: Progress callback translates to progress_updated & log_emitted
- W-05: Stage transition emits stage_changed with correct mappings
- W-06: Service success emits pipeline_finished with success result
- W-07: Service failure emits pipeline_finished with failed result
- W-08: Service unexpected exception does not crash GUI/thread, emits failure
- W-09: QThread execution runs service.run() on background thread, not GUI thread
- W-10: Cancellation propagation: is_cancelled_func reflects cancellation in real-time
"""

import sys
import threading
import time
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication

from app.models.subtitle_segment import SubtitleSegment
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
)
from ui.worker_adapters.video_creator_adapter import VideoCreatorWorker


@pytest.fixture(scope="session")
def qapp():
    """Ensure a QApplication exists for Qt Signals and QThread testing."""
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
            text="Xin chào các bạn",
            translated_text="Xin chào các bạn",
            final_gender="female",
            voice_id="vieneu_cogaihoatngon",
        ),
        SubtitleSegment(
            id=2,
            start=3.0,
            end=5.0,
            text="Hôm nay trời đẹp quá",
            translated_text="Hôm nay trời đẹp quá",
            final_gender="male",
            voice_id="vieneu_thanhnientutin",
        ),
    ]


class MockVideoCreatorService:
    """Mock service allowing flexible simulation of VideoCreatorService.run()."""

    def __init__(
        self,
        result_to_return: VideoCreatorResult | None = None,
        exception_to_raise: Exception | None = None,
        simulate_progress: bool = False,
        capture_thread: bool = False,
    ):
        self.result_to_return = result_to_return or VideoCreatorResult(
            status="success",
            output_video_path="output/final.mp4",
            output_audio_path="session/final_audio.wav",
        )
        self.exception_to_raise = exception_to_raise
        self.simulate_progress = simulate_progress
        self.capture_thread = capture_thread

        self.last_request: VideoCreatorRequest | None = None
        self.executed_thread_id: int | None = None

    def run(self, request: VideoCreatorRequest) -> VideoCreatorResult:
        self.last_request = request
        if self.capture_thread:
            self.executed_thread_id = threading.get_ident()

        if self.simulate_progress and request.progress_callback:
            request.progress_callback(0.0, "Preflight check...")
            request.progress_callback(5.0, "Voice mapping done")
            request.progress_callback(30.0, "TTS in progress...")
            request.progress_callback(60.0, "Mixing in progress...")
            request.progress_callback(80.0, "Exporting video...")
            request.progress_callback(96.0, "Verifying video...")
            request.progress_callback(100.0, "Done!")

        if self.exception_to_raise is not None:
            raise self.exception_to_raise

        return self.result_to_return


# =============================================================================
# W-01: Worker Initialization
# =============================================================================
def test_w01_worker_initialization(qapp):
    segments = _create_sample_segments()
    config = VideoCreatorConfig(duck_volume=0.15)

    worker = VideoCreatorWorker(
        original_video_path="input.mp4",
        segments=segments,
        output_video_path="out.mp4",
        workspace_dir="ws",
        config=config,
    )

    assert worker.original_video_path == "input.mp4"
    assert worker.segments == segments
    assert worker.output_video_path == "out.mp4"
    assert worker.workspace_dir == "ws"
    assert worker.config.duck_volume == 0.15
    assert not worker._cancel_event.is_set()
    assert worker.is_cancelled() is False


# =============================================================================
# W-02: request_cancel() sets threading.Event
# =============================================================================
def test_w02_request_cancel_sets_event(qapp):
    worker = VideoCreatorWorker(
        original_video_path="in.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
    )

    assert not worker._cancel_event.is_set()
    worker.request_cancel()
    assert worker._cancel_event.is_set()


# =============================================================================
# W-03: is_cancelled() reflects event state
# =============================================================================
def test_w03_is_cancelled_reflects_event(qapp):
    worker = VideoCreatorWorker(
        original_video_path="in.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
    )

    assert worker.is_cancelled() is False
    worker._cancel_event.set()
    assert worker.is_cancelled() is True


# =============================================================================
# W-04: Progress Callback Translates to progress_updated & log_emitted
# =============================================================================
def test_w04_progress_callback_signals(qapp):
    worker = VideoCreatorWorker(
        original_video_path="in.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
    )

    received_progress: list[tuple[float, str]] = []
    received_logs: list[str] = []

    worker.progress_updated.connect(lambda pct, msg: received_progress.append((pct, msg)))
    worker.log_emitted.connect(lambda log: received_logs.append(log))

    worker._on_service_progress(25.0, "Đang lồng tiếng câu 1")

    assert len(received_progress) == 1
    assert received_progress[0] == (25.0, "Đang lồng tiếng câu 1")
    assert len(received_logs) == 1
    assert "[ 25.0%] Đang lồng tiếng câu 1" in received_logs[0]


# =============================================================================
# W-05: Stage Transitions emit stage_changed with Correct Mappings
# =============================================================================
def test_w05_stage_transitions(qapp):
    worker = VideoCreatorWorker(
        original_video_path="in.mp4",
        segments=_create_sample_segments(),
        output_video_path="out.mp4",
    )

    stages_emitted: list[tuple[str, str]] = []
    worker.stage_changed.connect(lambda k, n: stages_emitted.append((k, n)))

    # Test monotonic stage transitions
    test_percents = [0.0, 5.0, 10.0, 30.0, 55.0, 75.0, 96.0, 100.0]
    for pct in test_percents:
        worker._on_service_progress(pct, f"Progress at {pct}%")

    # Verify expected stages were emitted without duplicate identical stages
    expected_stage_keys = ["preflight", "mapping", "tts", "mixing", "export", "verification", "completed"]
    actual_stage_keys = [k for k, _ in stages_emitted]
    assert actual_stage_keys == expected_stage_keys


# =============================================================================
# W-06: Service Success emits pipeline_finished with Success Result
# =============================================================================
def test_w06_service_success(qapp):
    expected_result = VideoCreatorResult(
        output_video_path="out/final.mp4",
        output_audio_path="out/final.wav",
        status="success",
        total_segments=2,
    )
    mock_service = MockVideoCreatorService(result_to_return=expected_result)

    worker = VideoCreatorWorker(
        original_video_path="in.mp4",
        segments=_create_sample_segments(),
        output_video_path="out/final.mp4",
        service=mock_service,
    )

    finished_results: list[VideoCreatorResult] = []
    worker.pipeline_finished.connect(lambda res: finished_results.append(res))

    worker.run()

    assert len(finished_results) == 1
    res = finished_results[0]
    assert res.status == "success"
    assert res.output_video_path == "out/final.mp4"
    assert res.total_segments == 2


# =============================================================================
# W-07: Service Failure emits pipeline_finished with Failed Result
# =============================================================================
def test_w07_service_failure(qapp):
    failed_result = VideoCreatorResult(
        status="failed",
        error="FFprobe validation error",
    )
    mock_service = MockVideoCreatorService(result_to_return=failed_result)

    worker = VideoCreatorWorker(
        original_video_path="in.mp4",
        segments=_create_sample_segments(),
        output_video_path="out/final.mp4",
        service=mock_service,
    )

    finished_results: list[VideoCreatorResult] = []
    worker.pipeline_finished.connect(lambda res: finished_results.append(res))

    worker.run()

    assert len(finished_results) == 1
    res = finished_results[0]
    assert res.status == "failed"
    assert "FFprobe validation error" in res.error


# =============================================================================
# W-08: Service Unexpected Exception caught cleanly, emits failure
# =============================================================================
def test_w08_service_unexpected_exception(qapp):
    mock_service = MockVideoCreatorService(exception_to_raise=RuntimeError("Unexpected OS device error"))

    worker = VideoCreatorWorker(
        original_video_path="in.mp4",
        segments=_create_sample_segments(),
        output_video_path="out/final.mp4",
        service=mock_service,
    )

    finished_results: list[VideoCreatorResult] = []
    worker.pipeline_finished.connect(lambda res: finished_results.append(res))

    # Should not raise exception
    worker.run()

    assert len(finished_results) == 1
    res = finished_results[0]
    assert res.status == "failed"
    assert "Worker exception: Unexpected OS device error" in res.error
    assert res.output_video_path == ""


# =============================================================================
# W-09: QThread Execution runs service.run() on Background Thread
# =============================================================================
def test_w09_qthread_background_execution(qapp):
    main_gui_thread_id = threading.get_ident()

    mock_service = MockVideoCreatorService(capture_thread=True)
    worker = VideoCreatorWorker(
        original_video_path="in.mp4",
        segments=_create_sample_segments(),
        output_video_path="out/final.mp4",
        service=mock_service,
    )

    finished_results: list[VideoCreatorResult] = []
    worker.pipeline_finished.connect(lambda res: finished_results.append(res))

    # Start genuine QThread background execution
    worker.start()
    worker.wait(5000)
    qapp.processEvents()

    assert len(finished_results) == 1
    assert mock_service.executed_thread_id is not None
    # Crucial assertion: executed on a different thread than GUI thread
    assert mock_service.executed_thread_id != main_gui_thread_id


# =============================================================================
# W-10: Cancellation Propagation reflects in real-time
# =============================================================================
def test_w10_cancellation_propagation(qapp):
    cancel_checked_inside_service: list[bool] = []

    class CancellationCapturingService:
        def run(self, request: VideoCreatorRequest) -> VideoCreatorResult:
            # Check before cancel
            cancel_checked_inside_service.append(request.is_cancelled_func())
            # Trigger cancellation from GUI
            worker.request_cancel()
            # Check after cancel
            cancel_checked_inside_service.append(request.is_cancelled_func())
            return VideoCreatorResult(status="cancelled", cancelled_stage="tts")

    service = CancellationCapturingService()
    worker = VideoCreatorWorker(
        original_video_path="in.mp4",
        segments=_create_sample_segments(),
        output_video_path="out/final.mp4",
        service=service,
    )

    finished_results: list[VideoCreatorResult] = []
    worker.pipeline_finished.connect(lambda res: finished_results.append(res))

    worker.run()

    assert cancel_checked_inside_service == [False, True]
    assert len(finished_results) == 1
    assert finished_results[0].status == "cancelled"
    assert finished_results[0].cancelled_stage == "tts"
