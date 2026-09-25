"""VideoCreatorWorker: QThread adapter orchestrating VideoCreatorService.

Strictly adheres to Contract Step 9.1 v1.1 (LOCKED):
- UI presentation and signal dispatch isolation from Step 8 pure Python engine.
- Thread-safe cooperative cancellation using threading.Event.
- Translates Python callbacks into Qt Signals without modifying Step 8.
- Safe execution in background thread without QThread.terminate().
"""

from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QThread, Signal

from app.models.subtitle_segment import SubtitleSegment
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
)


class VideoCreatorWorker(QThread):
    """Adapter Worker executing VideoCreatorService on a background QThread."""

    # Qt Signals for Main GUI Thread communication
    progress_updated = Signal(float, str)
    stage_changed = Signal(str, str)
    log_emitted = Signal(str)
    pipeline_finished = Signal(object)  # VideoCreatorResult

    def __init__(
        self,
        *,
        original_video_path: str,
        segments: list[SubtitleSegment],
        output_video_path: str,
        workspace_dir: str = "",
        config: VideoCreatorConfig | None = None,
        service: VideoCreatorService | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.original_video_path = original_video_path
        self.segments = segments
        self.output_video_path = output_video_path
        self.workspace_dir = workspace_dir
        self.config = config or VideoCreatorConfig()
        self._service = service

        # Thread-safe cancellation event
        self._cancel_event = threading.Event()
        self._current_stage = ""

    def request_cancel(self) -> None:
        """Called by Main GUI Thread when user clicks 'Hủy'."""
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        """Cooperative hook passed into VideoCreatorRequest."""
        return self._cancel_event.is_set()

    def _on_service_progress(self, percent: float, message: str) -> None:
        """Pure Python callback executed by VideoCreatorService."""
        self.progress_updated.emit(percent, message)
        self.log_emitted.emit(f"[{percent:5.1f}%] {message}")

        stage_key, stage_name = self._resolve_stage(percent)
        if stage_key != self._current_stage:
            self._current_stage = stage_key
            self.stage_changed.emit(stage_key, stage_name)

    @staticmethod
    def _resolve_stage(percent: float) -> tuple[str, str]:
        """Maps progress percent to UI stage indicators without affecting business logic."""
        if percent < 5.0:
            return "preflight", "Kiểm tra hệ thống"
        elif percent < 5.1:
            return "mapping", "Phân vai giọng đọc"
        elif percent < 55.0:
            return "tts", "Lồng tiếng AI & Khớp thời lượng"
        elif percent < 75.0:
            return "mixing", "Hòa âm & Ducking âm thanh"
        elif percent < 95.0:
            return "export", "Xuất video & Gắn phụ đề"
        elif percent < 100.0:
            return "verification", "Hậu kiểm toàn vẹn"
        else:
            return "completed", "Hoàn tất tạo video"

    def run(self) -> None:
        """Executes VideoCreatorService on background thread."""
        try:
            service = self._service if self._service is not None else VideoCreatorService()
            request = VideoCreatorRequest(
                original_video_path=self.original_video_path,
                segments=self.segments,
                output_video_path=self.output_video_path,
                workspace_dir=self.workspace_dir,
                config=self.config,
                progress_callback=self._on_service_progress,
                is_cancelled_func=self.is_cancelled,
            )

            result = service.run(request)
            self.pipeline_finished.emit(result)

        except Exception as exc:
            # Shield GUI from unhandled background exceptions
            failed_res = VideoCreatorResult(
                output_video_path="",
                status="failed",
                error=f"Worker exception: {exc}",
            )
            self.pipeline_finished.emit(failed_res)
