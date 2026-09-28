"""
BatchPipelineController — Quản lý xử lý hàng loạt nhiều video.

Kiến trúc:
    BatchPipelineController
        │
        ├── Queue (deque[VideoWorkspace])
        │
        ├── Active Workers (dict[ws_id → PipelineWorker])
        │   ├── PipelineWorker #1 → Local Worker Server → PrepareWorkflow
        │   ├── PipelineWorker #2 → Local Worker Server → PrepareWorkflow
        │   └── ...
        │
        └── Completed / Failed results

Nguyên tắc:
- Không đọc GUI state. Mọi settings đến từ PipelineContext.
- GUI chỉ nhận signals (status, progress) để hiển thị.
- max_concurrent cấu hình được, mặc định = 1 (an toàn CPU).
- Retry tự động cho video lỗi (tùy cấu hình).
- PipelineWorker tái sử dụng PrepareWorkflowWorker (local worker server).
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from collections import deque
from typing import Optional, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot, QTimer

from models.pipeline_context import PipelineContext, VideoWorkspace
from runtime_paths import subprocess_hidden_kwargs


class PipelineWorker(QThread):
    """Worker thread chạy 1 pipeline cho 1 VideoWorkspace.

    Sử dụng cùng kiến trúc local worker server như PipelineController:
    1. Spawn local worker server (subprocess)
    2. Gửi request POST /v1/prepare qua HTTP
    3. Poll /v1/status để cập nhật progress
    4. Nhận kết quả project_state_path

    Hoàn toàn headless — không đọc GUI, không tạo widget.
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
        self._worker_process = None

    def cancel(self):
        self._cancelled = True
        self._kill_worker_process()

    def run(self):
        ws = self.workspace
        ws_id = ws.id
        ws.mark_running("prepare")
        self.step_changed.emit(ws_id, "prepare")

        try:
            self._log_fn(f"[Batch] [{ws.video_name}] Bắt đầu pipeline...")

            if self._cancelled:
                ws.mark_cancelled()
                self.finished.emit(ws_id, "", "Đã hủy")
                return

            # ── Step 1: Spawn local worker server ──
            api_url, api_token = self._start_worker_server()
            self._log_fn(f"[Batch] [{ws.video_name}] Worker server: {api_url}")

            if self._cancelled:
                self._kill_worker_process()
                ws.mark_cancelled()
                self.finished.emit(ws_id, "", "Đã hủy")
                return

            # ── Step 2: Send /v1/prepare request ──
            self.step_changed.emit(ws_id, "extract_audio")
            self.progress_changed.emit(ws_id, 0.05)

            skip_translation = self.ctx.skip_translation or self.ctx.target_stage == "transcript"
            prefetch_tts = (
                self.ctx.target_stage == "full"
                and self.ctx.output_mode in ("voice", "both")
            )

            payload = {
                "workspace_root": self.ctx.workspace_root,
                "video_path": self.ctx.video_path,
                "source_language": self.ctx.source_language,
                "target_language": self.ctx.target_language,
                "mode": self.ctx.output_mode,
                "audio_handling_mode": self.ctx.audio_handling_mode,
                "translator_ai": self.ctx.ai_polish_enabled,
                "optimize_subtitles": False,
                "translator_style": self.ctx.ai_style_instruction,
                "whisper_model_name": self.ctx.whisper_model_name,
                "transcription_engine": self.ctx.transcription_engine,
                "speaker_diarization": self.ctx.speaker_diarization,
                "speaker_diarization_num_speakers": self.ctx.speaker_diarization_num_speakers,
                "skip_translation": skip_translation,
                "prefetch_voice_name": self.ctx.voice_name if prefetch_tts else "",
                "prefetch_voice_speed": self.ctx.voice_speed if prefetch_tts else 1.0,
            }

            # Send async request (long timeout — pipeline có thể chạy rất lâu)
            result = self._post_api(api_url, api_token, "/v1/prepare", payload, timeout=7200)

            if self._cancelled:
                self._kill_worker_process()
                ws.mark_cancelled()
                self.finished.emit(ws_id, "", "Đã hủy")
                return

            # ── Step 3: Extract result ──
            state_path = str(result.get("project_state_path", "")) if result else ""

            if not state_path:
                error_msg = str(result.get("error", "Không nhận được project_state_path")) if result else "Empty response"
                ws.mark_error(error_msg)
                self._log_fn(f"[Batch] [{ws.video_name}] LỖI: {error_msg}")
                self.finished.emit(ws_id, "", error_msg)
                return

            ws.project_state_path = state_path
            ws.mark_done(output_path=state_path)

            self.step_changed.emit(ws_id, "done")
            self.progress_changed.emit(ws_id, 1.0)
            self._log_fn(f"[Batch] [{ws.video_name}] Hoàn thành!")
            self.finished.emit(ws_id, state_path, "")

        except Exception as exc:
            error_msg = f"{exc}"
            ws.mark_error(error_msg)
            self._log_fn(f"[Batch] [{ws.video_name}] LỖI: {exc}")
            self.finished.emit(ws_id, "", error_msg)
        finally:
            self._kill_worker_process()

    # ── Local Worker Server Management ──────────────────────────────

    def _start_worker_server(self) -> tuple[str, str]:
        """Spawn local worker server subprocess, trả về (api_url, api_token)."""
        app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        server_script = os.path.join(app_root, "app", "remote_api_server.py")

        port = self._find_free_port()
        token = secrets.token_urlsafe(24)

        env = os.environ.copy()
        env["CAPCAP_RUNTIME_PROFILE"] = "local"
        env["CAPCAP_REMOTE_API_HOST"] = "127.0.0.1"
        env["CAPCAP_REMOTE_API_PORT"] = str(port)
        env["CAPCAP_REMOTE_API_TOKEN"] = token
        env["CAPCAP_REMOTE_PRELOAD_MODELS"] = "0"
        env["CAPCAP_RUN_REMOTE_API_SERVER"] = "1" if getattr(sys, "frozen", False) else "0"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["CAPCAP_DEVICE"] = os.getenv("CAPCAP_DEVICE", "cpu").strip().lower()

        process_kwargs = subprocess_hidden_kwargs()
        if os.name == "nt":
            process_kwargs["creationflags"] = int(process_kwargs.get("creationflags", 0)) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )

        worker_command = (
            [sys.executable, "--worker-server"]
            if getattr(sys, "frozen", False)
            else [sys.executable, server_script]
        )

        self._worker_process = subprocess.Popen(
            worker_command,
            cwd=app_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            close_fds=False,
            **process_kwargs,
        )

        api_url = f"http://127.0.0.1:{port}"

        # Wait for server to be ready
        self._wait_for_server(api_url, timeout_s=60.0)

        return api_url, token

    def _wait_for_server(self, api_url: str, timeout_s: float = 60.0):
        deadline = time.monotonic() + timeout_s
        health_url = f"{api_url.rstrip('/')}/health"
        while time.monotonic() < deadline:
            if self._cancelled:
                raise RuntimeError("Đã hủy trong lúc chờ worker server")
            proc = self._worker_process
            if proc is not None and proc.poll() is not None:
                raise RuntimeError(f"Worker server thoát sớm (code {proc.returncode})")
            try:
                with urllib.request.urlopen(health_url, timeout=1.0) as response:
                    if response.status == 200:
                        return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("Worker server không sẵn sàng sau 60 giây")

    def _post_api(self, api_url: str, token: str, endpoint: str,
                  payload: dict, timeout: int = 7200) -> dict:
        """Gửi POST request và poll status trong khi chờ."""
        url = f"{api_url.rstrip('/')}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("X-CapCap-Token", token)

        # Start polling status in background
        self._start_status_polling(api_url, token)

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(f"API error {e.code}: {body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection error: {e.reason}")
        finally:
            self._stop_status_polling()

    def _start_status_polling(self, api_url: str, token: str):
        """Poll /v1/status mỗi 5 giây để cập nhật progress."""
        self._poll_url = f"{api_url.rstrip('/')}/v1/status"
        self._poll_token = token
        self._poll_active = True
        self._last_poll_phase = ""

        import threading
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _stop_status_polling(self):
        self._poll_active = False

    def _poll_loop(self):
        """Background thread polling status endpoint."""
        ws_id = self.workspace.id
        while self._poll_active and not self._cancelled:
            time.sleep(5.0)
            if not self._poll_active:
                break
            try:
                request = urllib.request.Request(self._poll_url)
                if self._poll_token:
                    request.add_header("X-CapCap-Token", self._poll_token)
                with urllib.request.urlopen(request, timeout=2.0) as response:
                    data = json.loads(response.read().decode("utf-8", errors="replace"))
                phase = str(data.get("phase", "") or "").strip()
                if phase and phase != self._last_poll_phase:
                    self._last_poll_phase = phase
                    self._on_step(ws_id, phase)
            except Exception:
                pass

    def _on_step(self, ws_id: str, step_name: str):
        """Callback khi detect phase change qua polling."""
        self.workspace.current_step = step_name
        self.step_changed.emit(ws_id, step_name)

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

    def _kill_worker_process(self):
        proc = self._worker_process
        self._worker_process = None
        if proc is None:
            return
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    **subprocess_hidden_kwargs(),
                )
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


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
        self._batch_start_time = 0.0

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
        """Đặt cấu hình mặc định chung cho batch."""
        self._defaults = ctx

    def set_defaults_from_gui(self, gui):
        """Snapshot cấu hình mặc định từ GUI hiện tại."""
        self._defaults = PipelineContext.from_gui(gui)
        self._defaults.workspace_root = self.workspace_root or self._defaults.workspace_root
        self.workspace_root = self._defaults.workspace_root

    def set_max_concurrent(self, n: int):
        """Thay đổi số pipeline chạy đồng thời."""
        self.max_concurrent = max(1, n)
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
        self._batch_start_time = time.time()

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
            self._batch_start_time = time.time()

        for ws in retried:
            ws.mark_queued()
            self._queue.append(ws.id)
            self.workspace_status_changed.emit(ws.id, "queued")

        self._log(f"[Batch] Retry {len(retried)} video lỗi")
        self.batch_started.emit()
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
            self._batch_start_time = time.time()
            self.batch_started.emit()
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
            if error and ws.status != "cancelled":
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
            elif not error:
                self._success_count += 1
                self.workspace_status_changed.emit(ws_id, "done")

        # Xử lý video tiếp theo
        if self._queue:
            self._dispatch_next()
        elif not self._active_workers:
            # Batch hoàn tất
            elapsed = time.time() - self._batch_start_time if self._batch_start_time else 0
            elapsed_str = self._format_elapsed(elapsed)
            self._is_running = False
            self._log(
                f"[Batch] ✅ Hoàn tất! Thành công: {self._success_count}, "
                f"Thất bại: {self._fail_count}, Thời gian: {elapsed_str}"
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

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        m, s = divmod(s, 60)
        if m < 60:
            return f"{m}m {s}s"
        h, m = divmod(m, 60)
        return f"{h}h {m}m"

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

    @property
    def elapsed_str(self) -> str:
        if not self._batch_start_time:
            return ""
        return self._format_elapsed(time.time() - self._batch_start_time)

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
            "elapsed": self.elapsed_str,
        }
