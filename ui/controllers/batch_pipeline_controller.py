"""
BatchPipelineController — Quản lý xử lý hàng loạt nhiều video.

Kiến trúc:
    BatchPipelineController
        │
        ├── Queue (deque[VideoWorkspace])
        │
        ├── Active Workers (dict[ws_id → QThread])
        │   ├── PipelineWorker #1 → PipelineContext → PrepareWorkflow
        │   ├── PipelineWorker #2 → PipelineContext → PrepareWorkflow
        │   └── ...
        │
        └── Completed / Failed results

Nguyên tắc:
- Không đọc GUI state. Mọi settings đến từ PipelineContext.
- GUI chỉ nhận signals (status, progress) để hiển thị.
- max_concurrent cấu hình được, mặc định = 1 (an toàn CPU).
- Retry tự động cho video lỗi (tùy cấu hình).
"""

from __future__ import annotations

import os
import time
import traceback
from collections import deque
from typing import Optional, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot, QTimer

from models.pipeline_context import PipelineContext, VideoWorkspace


class PipelineWorker(QThread):
    """Worker thread chạy 1 pipeline cho 1 VideoWorkspace.

    Hoàn toàn headless — không đọc GUI, không tạo widget.
    Giao tiếp qua signals.
    """

    # Signals
    step_changed = Signal(str, str)         # (workspace_id, step_name)
    progress_changed = Signal(str, float)   # (workspace_id, progress 0-1)
    finished = Signal(str, str, str)        # (workspace_id, output_path, error)

    def __init__(self, workspace: VideoWorkspace, ctx: PipelineContext,
                 log_fn: Optional[Callable] = None):
        super().__init__()
        self.workspace = workspace
        self.ctx = ctx
        self._log_fn = log_fn or (lambda msg: None)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        ws = self.workspace
        ws_id = ws.id
        ws.mark_running("prepare")
        self.step_changed.emit(ws_id, "prepare")

        try:
            self._log_fn(f"[Batch] [{ws.video_name}] Bắt đầu pipeline...")

            # Import workflow
            from workflows.prepare_workflow import PrepareWorkflow
            from services import ProjectService

            project_service = ProjectService(self.ctx.workspace_root)

            # Step 1: Prepare project
            self.step_changed.emit(ws_id, "extract_audio")
            self.progress_changed.emit(ws_id, 0.1)

            if self._cancelled:
                ws.mark_cancelled()
                self.finished.emit(ws_id, "", "Đã hủy")
                return

            workflow = PrepareWorkflow(self.ctx.workspace_root)

            # Build prepare params matching what PrepareWorkflowWorker does
            skip_translation = self.ctx.skip_translation or self.ctx.target_stage == "transcript"
            prefetch_tts = (
                self.ctx.target_stage == "full"
                and self.ctx.output_mode in ("voice", "both")
            )

            project_state = workflow.run(
                video_path=self.ctx.video_path,
                source_language=self.ctx.source_language,
                target_language=self.ctx.target_language,
                mode=self.ctx.output_mode,
                audio_handling_mode=self.ctx.audio_handling_mode,
                whisper_model_name=self.ctx.whisper_model_name,
                translator_ai=self.ctx.ai_polish_enabled,
                optimize_subtitles=False,
                translator_style=self.ctx.ai_style_instruction,
                transcription_engine=self.ctx.transcription_engine,
                speaker_diarization=self.ctx.speaker_diarization,
                speaker_diarization_num_speakers=self.ctx.speaker_diarization_num_speakers,
                skip_translation=skip_translation,
                prefetch_voice_name=self.ctx.voice_name if prefetch_tts else "",
                prefetch_voice_speed=self.ctx.voice_speed if prefetch_tts else 1.0,
                step_callback=lambda step: self._on_step(ws_id, step),
            )

            if self._cancelled:
                ws.mark_cancelled()
                self.finished.emit(ws_id, "", "Đã hủy")
                return

            self.step_changed.emit(ws_id, "done")
            self.progress_changed.emit(ws_id, 1.0)

            # Save project state path
            state_path = ""
            if hasattr(project_state, "project_file"):
                state_path = str(project_state.project_file or "")
            elif isinstance(project_state, str):
                state_path = project_state

            ws.project_state_path = state_path
            ws.mark_done(output_path=state_path)
            self._log_fn(f"[Batch] [{ws.video_name}] Hoàn thành!")
            self.finished.emit(ws_id, state_path, "")

        except Exception as exc:
            error_msg = f"{exc}\n{traceback.format_exc()}"
            ws.mark_error(str(exc))
            self._log_fn(f"[Batch] [{ws.video_name}] LỖI: {exc}")
            self.finished.emit(ws_id, "", error_msg)

    def _on_step(self, ws_id: str, step_name: str):
        """Callback from PrepareWorkflow khi chuyển bước."""
        self.workspace.current_step = step_name
        self.step_changed.emit(ws_id, step_name)

        # Ước lượng progress dựa trên step
        step_progress = {
            "prepare": 0.05,
            "extract_audio": 0.10,
            "extraction": 0.10,
            "separation": 0.20,
            "diarization": 0.30,
            "transcription": 0.40,
            "translation": 0.60,
            "voiceover": 0.75,
            "preview": 0.90,
            "done": 1.0,
        }
        progress = step_progress.get(step_name, 0.5)
        self.workspace.progress = progress
        self.progress_changed.emit(ws_id, progress)


class BatchPipelineController(QObject):
    """Quản lý batch xử lý nhiều video.

    Kiến trúc:
    - Queue chứa VideoWorkspace chờ xử lý
    - Active workers dict chứa PipelineWorker đang chạy
    - max_concurrent kiểm soát số pipeline chạy đồng thời
    - Signals thông báo UI về trạng thái từng video
    """

    # Signals cho UI
    workspace_added = Signal(str)                   # workspace_id
    workspace_removed = Signal(str)                 # workspace_id
    workspace_status_changed = Signal(str, str)     # (workspace_id, new_status)
    workspace_progress_changed = Signal(str, float) # (workspace_id, progress 0-1)
    workspace_step_changed = Signal(str, str)       # (workspace_id, step_name)
    batch_started = Signal()
    batch_completed = Signal(int, int)              # (success_count, fail_count)
    log_message = Signal(str)                       # log text

    def __init__(self, workspace_root: str = "", max_concurrent: int = 1,
                 log_fn: Optional[Callable] = None, parent=None):
        super().__init__(parent)
        self.workspace_root = workspace_root
        self.max_concurrent = max(1, max_concurrent)
        self._log_fn = log_fn or (lambda msg: None)

        # Data
        self.workspaces: list[VideoWorkspace] = []
        self._queue: deque[str] = deque()           # workspace IDs chờ xử lý
        self._active_workers: dict[str, PipelineWorker] = {}  # đang chạy
        self._defaults: Optional[PipelineContext] = None      # cấu hình chung
        self._is_running = False

        # Stats
        self._success_count = 0
        self._fail_count = 0

    # ─── Workspace Management ─────────────────────────────────────────

    def add_workspace(self, video_path: str, thumb_dir: str = "") -> VideoWorkspace:
        """Thêm 1 video vào batch."""
        ws = VideoWorkspace.from_video_path(video_path, thumb_dir)
        self.workspaces.append(ws)
        self.workspace_added.emit(ws.id)
        self._log(f"[Batch] Đã thêm: {ws.video_name}")
        return ws

    def add_workspaces(self, video_paths: list[str], thumb_dir: str = "") -> list[VideoWorkspace]:
        """Thêm nhiều video vào batch."""
        return [self.add_workspace(p, thumb_dir) for p in video_paths]

    def remove_workspace(self, ws_id: str):
        """Xóa 1 video khỏi batch (chỉ nếu chưa đang chạy)."""
        ws = self._find_workspace(ws_id)
        if not ws:
            return
        if ws.status == "running":
            self._log(f"[Batch] Không thể xóa {ws.video_name} — đang chạy")
            return
        self.workspaces = [w for w in self.workspaces if w.id != ws_id]
        if ws_id in self._queue:
            self._queue = deque(wid for wid in self._queue if wid != ws_id)
        self.workspace_removed.emit(ws_id)

    def get_workspace(self, ws_id: str) -> Optional[VideoWorkspace]:
        return self._find_workspace(ws_id)

    def clear_all(self):
        """Xóa tất cả workspace (chỉ nếu không đang chạy)."""
        if self._is_running:
            self._log("[Batch] Không thể xóa — đang chạy batch")
            return
        ids = [ws.id for ws in self.workspaces]
        self.workspaces.clear()
        self._queue.clear()
        for wid in ids:
            self.workspace_removed.emit(wid)

    # ─── Configuration ────────────────────────────────────────────────

    def set_defaults(self, ctx: PipelineContext):
        """Đặt cấu hình mặc định chung cho batch.

        Các workspace không có override riêng sẽ dùng settings này.
        """
        self._defaults = ctx

    def set_defaults_from_gui(self, gui):
        """Snapshot cấu hình mặc định từ GUI hiện tại."""
        self._defaults = PipelineContext.from_gui(gui)
        self._defaults.workspace_root = self.workspace_root or self._defaults.workspace_root
        self.workspace_root = self._defaults.workspace_root

    def set_max_concurrent(self, n: int):
        """Thay đổi số pipeline chạy đồng thời."""
        self.max_concurrent = max(1, n)
        # Nếu đang chạy và có slot trống, bắt thêm worker
        if self._is_running:
            self._dispatch_next()

    # ─── Execution ────────────────────────────────────────────────────

    def start_all(self):
        """Đưa tất cả workspace pending vào queue và bắt đầu xử lý."""
        if self._is_running:
            self._log("[Batch] Đang chạy batch, bỏ qua start_all")
            return

        pending = [ws for ws in self.workspaces if ws.status in ("pending",)]
        if not pending:
            self._log("[Batch] Không có video nào cần xử lý")
            return

        self._is_running = True
        self._success_count = 0
        self._fail_count = 0

        for ws in pending:
            ws.mark_queued()
            self._queue.append(ws.id)
            self.workspace_status_changed.emit(ws.id, "queued")

        self.batch_started.emit()
        self._log(f"[Batch] Bắt đầu xử lý {len(pending)} video (đồng thời: {self.max_concurrent})")
        self._dispatch_next()

    def stop_all(self):
        """Hủy tất cả — cả đang chạy lẫn đang chờ."""
        self._queue.clear()

        for ws_id, worker in list(self._active_workers.items()):
            worker.cancel()
            ws = self._find_workspace(ws_id)
            if ws:
                ws.mark_cancelled()
                self.workspace_status_changed.emit(ws_id, "cancelled")

        self._is_running = False
        self._log("[Batch] Đã dừng tất cả pipeline")

    def retry_failed(self):
        """Đưa tất cả video lỗi vào lại queue (nếu còn retry)."""
        retried = []
        for ws in self.workspaces:
            if ws.can_retry():
                ws.prepare_retry()
                retried.append(ws)

        if not retried:
            self._log("[Batch] Không có video lỗi nào có thể retry")
            return

        if not self._is_running:
            self._is_running = True
            self._success_count = 0
            self._fail_count = 0

        for ws in retried:
            ws.mark_queued()
            self._queue.append(ws.id)
            self.workspace_status_changed.emit(ws.id, "queued")

        self._log(f"[Batch] Retry {len(retried)} video lỗi")
        self._dispatch_next()

    def retry_single(self, ws_id: str):
        """Retry 1 video cụ thể."""
        ws = self._find_workspace(ws_id)
        if not ws or not ws.can_retry():
            return

        ws.prepare_retry()
        ws.mark_queued()
        self._queue.append(ws.id)
        self.workspace_status_changed.emit(ws_id, "queued")

        if not self._is_running:
            self._is_running = True
        self._dispatch_next()

    # ─── Internal ─────────────────────────────────────────────────────

    def _dispatch_next(self):
        """Bắt đầu worker mới nếu còn slot trống và còn video trong queue."""
        while len(self._active_workers) < self.max_concurrent and self._queue:
            ws_id = self._queue.popleft()
            ws = self._find_workspace(ws_id)
            if not ws or ws.status == "cancelled":
                continue

            # Tạo PipelineContext cho workspace này
            ctx = PipelineContext.from_workspace(ws, self._defaults)
            if not ctx.workspace_root:
                ctx.workspace_root = self.workspace_root

            # Validate
            error = ctx.validate()
            if error:
                ws.mark_error(error)
                self.workspace_status_changed.emit(ws_id, "error")
                self._fail_count += 1
                continue

            # Tạo và chạy worker
            worker = PipelineWorker(ws, ctx, log_fn=self._log)
            worker.step_changed.connect(self._on_worker_step)
            worker.progress_changed.connect(self._on_worker_progress)
            worker.finished.connect(self._on_worker_finished)

            self._active_workers[ws_id] = worker
            self.workspace_status_changed.emit(ws_id, "running")
            worker.start()

    @Slot(str, str)
    def _on_worker_step(self, ws_id: str, step: str):
        self.workspace_step_changed.emit(ws_id, step)

    @Slot(str, float)
    def _on_worker_progress(self, ws_id: str, progress: float):
        self.workspace_progress_changed.emit(ws_id, progress)

    @Slot(str, str, str)
    def _on_worker_finished(self, ws_id: str, output_path: str, error: str):
        # Cleanup worker
        worker = self._active_workers.pop(ws_id, None)
        if worker:
            worker.deleteLater()

        ws = self._find_workspace(ws_id)
        if ws:
            if error:
                self._fail_count += 1
                self.workspace_status_changed.emit(ws_id, "error")

                # Auto-retry nếu có thể
                if ws.can_retry():
                    self._log(f"[Batch] [{ws.video_name}] Tự động retry (lần {ws.retry_count + 1}/{ws.max_retries})")
                    ws.prepare_retry()
                    ws.mark_queued()
                    self._queue.append(ws_id)
                    self.workspace_status_changed.emit(ws_id, "queued")
                    self._fail_count -= 1  # Chưa tính thất bại thật sự
            else:
                self._success_count += 1
                self.workspace_status_changed.emit(ws_id, "done")

        # Xử lý video tiếp theo
        if self._queue:
            self._dispatch_next()
        elif not self._active_workers:
            # Batch hoàn tất
            self._is_running = False
            self._log(
                f"[Batch] Hoàn tất! Thành công: {self._success_count}, "
                f"Thất bại: {self._fail_count}"
            )
            self.batch_completed.emit(self._success_count, self._fail_count)

    def _find_workspace(self, ws_id: str) -> Optional[VideoWorkspace]:
        for ws in self.workspaces:
            if ws.id == ws_id:
                return ws
        return None

    def _log(self, msg: str):
        self._log_fn(msg)
        self.log_message.emit(msg)

    # ─── Status Queries ───────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def total_count(self) -> int:
        return len(self.workspaces)

    @property
    def pending_count(self) -> int:
        return sum(1 for ws in self.workspaces if ws.status in ("pending", "queued"))

    @property
    def running_count(self) -> int:
        return len(self._active_workers)

    @property
    def done_count(self) -> int:
        return sum(1 for ws in self.workspaces if ws.status == "done")

    @property
    def error_count(self) -> int:
        return sum(1 for ws in self.workspaces if ws.status == "error")

    def get_summary(self) -> dict:
        """Trả về tóm tắt batch."""
        return {
            "total": self.total_count,
            "pending": self.pending_count,
            "running": self.running_count,
            "done": self.done_count,
            "error": self.error_count,
            "is_running": self.is_running,
            "max_concurrent": self.max_concurrent,
        }
