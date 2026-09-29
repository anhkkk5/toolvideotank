import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox
from worker_adapters import PrepareWorkflowWorker
from runtime_paths import subprocess_hidden_kwargs

# Robust import for the progress widget
try:
    from widgets.progress_dialog import BackgroundableProgressDialog, PipelineProgressDialog
except ImportError:
    # Fallback for different execution contexts
    sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
    from widgets.progress_dialog import BackgroundableProgressDialog, PipelineProgressDialog

class PipelineController:
    """
    Orchestrates the multi-stage video translation pipeline.
    Connects background workers to the UI and progress tracking widgets.
    """
    def __init__(self, gui):
        self.gui = gui
        self.progress_dialog = None
        self.whisper_download_dialog = None
        self.local_worker_process = None
        self.local_worker_api_url = ""
        self.local_worker_api_token = ""
        self.prepare_run_id = 0
        self.prepare_status_timer = None
        self.prepare_status_phase = ""
        self.active_processing_device = "cpu"

    def _app_root(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    def _find_free_local_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _wait_for_local_worker_server(self, api_url, timeout_s=60.0):
        deadline = time.monotonic() + timeout_s
        health_url = f"{api_url.rstrip('/')}/health"
        while time.monotonic() < deadline:
            process = self.local_worker_process
            if process is not None and process.poll() is not None:
                raise RuntimeError(f"Local worker process exited early with code {process.returncode}.")
            try:
                with urllib.request.urlopen(health_url, timeout=1.0) as response:
                    if response.status == 200:
                        return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("Local worker process did not become ready.")

    def _kill_process_tree(self, process):
        if process is None:
            return
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    **subprocess_hidden_kwargs(),
                )
            else:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _stop_local_worker_server(self):
        process = self.local_worker_process
        self.local_worker_process = None
        self.local_worker_api_url = ""
        self.local_worker_api_token = ""
        self._kill_process_tree(process)

    def _start_prepare_status_polling(self):
        self._stop_prepare_status_polling()
        self.prepare_status_phase = ""
        timer = QTimer(self.gui)
        timer.setInterval(10000)
        timer.timeout.connect(self._poll_prepare_status)
        self.prepare_status_timer = timer
        timer.start()

    def _stop_prepare_status_polling(self):
        timer = self.prepare_status_timer
        self.prepare_status_timer = None
        if timer is not None:
            try:
                timer.stop()
                timer.deleteLater()
            except Exception:
                pass

    def _poll_prepare_status(self):
        api_url = self.local_worker_api_url
        token = self.local_worker_api_token
        if not api_url:
            return
        try:
            request = urllib.request.Request(f"{api_url.rstrip('/')}/v1/status")
            if token:
                request.add_header("X-CapCap-Token", token)
            with urllib.request.urlopen(request, timeout=0.35) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
            phase = str(data.get("phase", "") or "").strip()
            message = str(data.get("message", "") or "").strip()
            if phase and phase != self.prepare_status_phase:
                self.prepare_status_phase = phase
                self._on_prepare_step_started(phase, message)
        except Exception:
            pass

    def _start_local_worker_server(self, processing_device: str = ""):
        self._stop_local_worker_server()
        app_root = self._app_root()
        server_script = os.path.join(app_root, "app", "remote_api_server.py")
        port = self._find_free_local_port()
        token = secrets.token_urlsafe(24)
        env = os.environ.copy()
        env["CAPCAP_RUNTIME_PROFILE"] = "local"
        env["CAPCAP_REMOTE_API_HOST"] = "127.0.0.1"
        env["CAPCAP_REMOTE_API_PORT"] = str(port)
        env["CAPCAP_REMOTE_API_TOKEN"] = token
        env["CAPCAP_REMOTE_PRELOAD_MODELS"] = "0"
        env["CAPCAP_RUN_REMOTE_API_SERVER"] = "1" if getattr(sys, "frozen", False) else "0"
        # The worker is a separate frozen Python process.  Force UTF-8 before
        # it starts so any third-party code that still relies on Python's
        # default text encoding cannot inherit a locale-specific ANSI codec.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["CAPCAP_DEVICE"] = (
            "cuda" if str(processing_device or os.getenv("CAPCAP_DEVICE", "cpu")).strip().lower() == "cuda"
            else "cpu"
        )

        process_kwargs = subprocess_hidden_kwargs()
        if os.name == "nt":
            process_kwargs["creationflags"] = int(process_kwargs.get("creationflags", 0)) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )

        # A frozen GUI executable must be launched in an explicit worker mode.
        # Starting it with no arguments would open a second launcher window;
        # the worker entrypoint then runs the HTTP server without importing the
        # GUI or creating a QApplication.
        worker_command = ([sys.executable, "--worker-server"]
                          if getattr(sys, "frozen", False)
                          else [sys.executable, server_script])
        self.local_worker_process = subprocess.Popen(
            worker_command,
            cwd=app_root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            close_fds=False,
            **process_kwargs,
        )
        self.local_worker_api_url = f"http://127.0.0.1:{port}"
        self.local_worker_api_token = token
        try:
            self._wait_for_local_worker_server(self.local_worker_api_url)
        except Exception:
            self._stop_local_worker_server()
            raise

    def _mark_running_project_steps_stopped(self):
        state = getattr(self.gui, "current_project_state", None)
        steps = getattr(state, "steps", {}) or {}
        for step_name, status in list(steps.items()):
            if status != "running":
                continue
            try:
                self.gui.update_project_step(step_name, "failed")
            except Exception:
                try:
                    steps[step_name] = "failed"
                except Exception:
                    pass

    def _on_pipeline_stop(self):
        if self.progress_dialog:
            reply = QMessageBox.question(
                self.progress_dialog,
                "Stop Pipeline?",
                "Stop the current pipeline run? The worker process for this run will be killed.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                self.progress_dialog.cancel_stop_request()
                return

        self.gui._pipeline_active = False
        self.gui._pipeline_step = ""
        self.prepare_run_id += 1
        self._stop_prepare_status_polling()
        self._mark_running_project_steps_stopped()
        self._stop_local_worker_server()
        if self.progress_dialog:
            self.progress_dialog.fail_step("ai_process")
            self.progress_dialog.footer.setText("Quy trình đã dừng.")
            self.progress_dialog.footer.setStyleSheet("color: #FFB86B; font-weight: bold; font-size: 14px; margin-top: 15px;")
            self.progress_dialog.stop_btn.setEnabled(False)
            self.progress_dialog.stop_btn.setText("Đã dừng")
        if hasattr(self.gui, "run_all_btn"):
            self.gui.run_all_btn.setEnabled(True)
            self.gui.run_all_btn.setText("Tạo")
        self.gui.progress_bar.setRange(0, 100)
        self.gui.progress_bar.setValue(0)
        self.gui.refresh_ui_state()
        self.gui.log("[Pipeline] Stop requested. Local worker process killed.")
        cb = getattr(self.gui, "on_pipeline_finished_callback", None)
        if callable(cb):
            cb(False, "User stopped")

    def stop_pipeline_immediately(self):
        """Immediately stop the running pipeline without asking confirmation (used by queue controller)."""
        self.gui._pipeline_active = False
        self.gui._pipeline_step = ""
        self.prepare_run_id += 1
        self._stop_prepare_status_polling()
        self._mark_running_project_steps_stopped()
        self._stop_local_worker_server()
        if self.progress_dialog:
            try:
                self.progress_dialog.fail_step("ai_process")
                self.progress_dialog.hide()
            except Exception:
                pass
        if hasattr(self.gui, "run_all_btn"):
            self.gui.run_all_btn.setEnabled(True)
            self.gui.run_all_btn.setText("Tạo")
        self.gui.progress_bar.setRange(0, 100)
        self.gui.progress_bar.setValue(0)
        self.gui.refresh_ui_state()
        self.gui.log("[Pipeline] Pipeline stopped immediately.")
        cb = getattr(self.gui, "on_pipeline_finished_callback", None)
        if callable(cb):
            cb(False, "Stopped immediately")

    
    def _whisper_model_cached(self, model_name: str) -> bool:
        try:
            name = str(model_name or "").strip().lower()
            if not name:
                return True
            cache_root = os.path.join(self.gui.workspace_root, "models", "faster_whisper")
            if not os.path.isdir(cache_root):
                return False
            for entry in os.listdir(cache_root):
                low = entry.lower()
                if low.startswith("models--") and name in low:
                    return True
            return False
        except Exception:
            return True

    def _hide_whisper_download_dialog(self):
        try:
            if self.whisper_download_dialog is not None:
                self.whisper_download_dialog.hide()
                self.whisper_download_dialog.deleteLater()
                self.whisper_download_dialog = None
        except Exception:
            self.whisper_download_dialog = None

    def _show_whisper_download_dialog(self):
        try:
            if self.whisper_download_dialog is not None:
                return
            model_name = getattr(self.gui, "get_whisper_model_name", lambda: "medium")()
            dlg = BackgroundableProgressDialog(f"Đang tải mô hình Whisper: {model_name} ...", "Ẩn", 0, 0, self.gui)
            dlg.setWindowTitle("Đang tải mô hình")
            dlg.setWindowModality(Qt.NonModal)
            dlg.setMinimumDuration(0)
            dlg.setAutoReset(False)
            dlg.setAutoClose(False)
            try:
                dlg.canceled.connect(dlg.hide)
            except Exception:
                pass
            self.whisper_download_dialog = dlg
            if hasattr(self.gui, "_register_progress_dialog"):
                self.gui._register_progress_dialog(dlg)
            dlg.show()
        except Exception:
            self.whisper_download_dialog = None
    def _setup_progress_dialog(self, includes_separation=True):
        """Creates and initializes the progress tracking dialog."""
        if self.progress_dialog:
            try:
                self.progress_dialog.stop_requested.disconnect(self._on_pipeline_stop)
            except (RuntimeError, TypeError):
                pass
            self.progress_dialog.hide()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
        self.progress_dialog = PipelineProgressDialog(self.gui)
        self.progress_dialog.stop_requested.connect(self._on_pipeline_stop)
        if hasattr(self.gui, "_register_progress_dialog"):
            self.gui._register_progress_dialog(self.progress_dialog)
        from runtime_profile import is_remote_profile
        if is_remote_profile():
            # Backend runs separate + transcribe + translate in one batch.
            # Cleaner voice (separation) is handled inside the batch silently.
            self.progress_dialog.add_step("ai_process", "Xử lý phụ đề (AI)")
        else:
            self.progress_dialog.add_step("ai_process", "Xử lý phụ đề (AI)")
        self.progress_dialog.add_step("voiceover", "Tạo giọng đọc AI (TTS)")
        self.progress_dialog.add_step("preview", "Chuẩn bị xem trước Video")
        self.progress_dialog.show()

    def run_all_pipeline(self, video_path=None, requires_separation=None, target_stage="full"):
        """Entry point for the full generation process (backward-compatible).

        This method reads settings from the GUI and delegates to
        run_pipeline_from_context which is fully headless.
        """
        from models.pipeline_context import PipelineContext

        ctx = PipelineContext.from_gui(self.gui)
        if video_path:
            ctx.video_path = video_path
        if target_stage:
            ctx.target_stage = str(target_stage or "full").strip().lower()

        if not ctx.video_path or not os.path.exists(ctx.video_path):
            QMessageBox.warning(self.gui, "Lỗi", "Vui lòng chọn một tệp video trước.")
            return

        if requires_separation is not None:
            pass  # caller explicitly controls separation
        else:
            requires_separation = (ctx.audio_handling_mode == "clean")

        self.run_pipeline_from_context(ctx, requires_separation=requires_separation)

    def run_pipeline_from_context(self, ctx, requires_separation=None):
        """Run the pipeline from a PipelineContext — fully headless, no GUI reads.

        All settings come from ``ctx``. The GUI is only used for:
        - UI feedback (progress dialog, button states, log)
        - Receiving results (project state reload)

        This is the entry point that BatchPipelineController will use.
        """
        if requires_separation is None:
            requires_separation = (ctx.audio_handling_mode == "clean")

        # Initialize state
        self.prepare_run_id += 1
        prepare_run_id = self.prepare_run_id
        self.gui._pipeline_active = True
        self.gui._pipeline_step = "prepare"
        self.target_stage = ctx.target_stage
        self._pipeline_start_time = time.time()
        # Store context for later phases (voiceover, preview) to read from
        self._active_context = ctx

        # UI Feedback
        if hasattr(self.gui, "run_all_btn"):
            self.gui.run_all_btn.setEnabled(False)
            self.gui.run_all_btn.setText("Đang xử lý...")

        self._setup_progress_dialog(includes_separation=requires_separation)
        self.progress_dialog.start_step("ai_process")

        # Start the background worker
        self.gui.log(f"[Pipeline] Starting prepare workflow for: {ctx.video_path}")
        try:
            self.active_processing_device = (
                "cuda" if os.getenv("CAPCAP_DEVICE", "cpu").strip().lower() == "cuda" else "cpu"
            )
            self._start_local_worker_server(self.active_processing_device)
            self.gui.log(
                f"[Pipeline] Local worker process started at {self.local_worker_api_url} "
                f"(device={self.active_processing_device})"
            )
        except Exception as exc:
            self.pipeline_fail(f"Could not start local worker process: {exc}")
            return
        self._start_prepare_status_polling()

        # All settings come from ctx, NOT from self.gui.get_xxx()
        skip_translation = ctx.skip_translation or ctx.target_stage == "transcript"
        prefetch_tts = ctx.target_stage == "full" and ctx.output_mode in ("voice", "both")

        self.gui.prepare_workflow_thread = PrepareWorkflowWorker(
            ctx.workspace_root,
            ctx.video_path,
            ctx.output_mode,
            ctx.audio_handling_mode,
            ctx.source_language,
            ctx.target_language,
            ctx.ai_polish_enabled,
            False,
            ctx.ai_style_instruction,
            ctx.whisper_model_name,
            transcription_engine=ctx.transcription_engine,
            speaker_diarization=ctx.speaker_diarization,
            speaker_diarization_num_speakers=ctx.speaker_diarization_num_speakers,
            skip_translation=skip_translation,
            prefetch_voice_name=ctx.voice_name if prefetch_tts else "",
            prefetch_voice_speed=ctx.voice_speed if prefetch_tts else 1.0,
            remote_api_url=self.local_worker_api_url,
            remote_api_token=self.local_worker_api_token,
            force_remote_api=True,
        )

        # Connect signals
        self.gui.prepare_workflow_thread.step_started.connect(self._on_prepare_step_started)
        self.gui.prepare_workflow_thread.finished.connect(
            lambda project_state_path, error, run_id=prepare_run_id: self.on_prepare_workflow_finished(
                project_state_path,
                error,
                run_id,
            )
        )
        self.gui.prepare_workflow_thread.start()

    def _on_prepare_step_started(self, step_id, message=""):
        # The Prepare workflow runs in a separate local process, so mirror
        # its active phase into the GUI's in-memory project state.  This lets
        # Stop mark the correct phase failed instead of leaving a stale
        # completed artifact to drive the sidebar badge.
        if step_id == "translation":
            try:
                self.gui.update_project_step("translate_raw", "running")
            except Exception:
                pass
        if not self.progress_dialog:
            return
        labels = {
            "prepare": "Chuẩn bị dự án",
            "extract_audio": "Trích xuất âm thanh",
            "extraction": "Trích xuất âm thanh",
            "separation": "Tách lời thoại / nhạc nền",
            "diarization": "Nhận diện người nói",
            "transcription": "Chép lời âm thanh",
            "translation": "Dịch phụ đề",
            "done": "Chuẩn bị hoàn tất",
            "error": "Chuẩn bị thất bại",
        }
        label = str(message or labels.get(str(step_id or ""), step_id or "Đang xử lý")).strip()
        if label and self.progress_dialog:
            self.progress_dialog.footer.setText(f"Chuẩn bị: {label}")
            self.progress_dialog.footer.setStyleSheet("color: #9fb7d5; font-size: 13px; margin-top: 15px;")
        if step_id == "transcription":
            self._hide_whisper_download_dialog()

    def on_prepare_workflow_finished(self, project_state_path, error, run_id=None):
        """Callback when the background PrepareWorkflow finishes completely."""
        self._hide_whisper_download_dialog()
        if run_id is not None and run_id != self.prepare_run_id:
            self.gui.log("[Pipeline] Ignoring stale prepare result from a stopped run.")
            return
        self._stop_prepare_status_polling()
        self._stop_local_worker_server()
        if not getattr(self.gui, "_pipeline_active", False):
            return

        if error or not project_state_path:
            self.pipeline_fail(f"Quy trình chuẩn bị thất bại: {error}")
            self.gui.show_error("Chuẩn bị thất bại", "Không thể hoàn thành việc chuẩn bị dự án.", str(error))
            return

        if self.progress_dialog:
            self.progress_dialog.finish_step("ai_process")

        try:
            state = self.gui.project_service.load_project(project_state_path)
            self.gui.current_project_state = state
            self.gui.load_project_context(state)
            self.gui.refresh_ui_state()
            self._notify_speaker_analysis_result(state)
            # The OCR crop is an editing aid. Once its transcript is ready,
            # return the preview to its normal unobstructed state. The crop
            # geometry remains available through the OCR button for later
            # adjustment, and this does not affect OCR Translator overlays.
            _ctx_engine = getattr(self, "_active_context", None)
            if (_ctx_engine and _ctx_engine.transcription_engine == "ocr") or (not _ctx_engine and self.gui.get_transcription_engine() == "ocr"):
                self.gui.toggle_ocr_overlay_visibility(False)
                self.gui.log("[OCR Region] Hidden after OCR transcription completed.")
            self._notify_translation_fallback_if_used()
        except Exception as e:
            self.gui.log(f"[Pipeline] Error reloading state: {e}")

        _ctx = getattr(self, "_active_context", None)
        mode = _ctx.output_mode if _ctx else self.gui.get_output_mode_key()
        if self.target_stage in {"transcript", "translate"} or mode == "subtitle":
            self.pipeline_done()
            if self.progress_dialog:
                if self.target_stage == "transcript":
                    self.progress_dialog.skip_step("voiceover")
                elif self.target_stage == "translate":
                    self.progress_dialog.skip_step("voiceover")
                self.progress_dialog.set_completed()
            self.gui.log(f"[Pipeline] Reached requested stage: {self.target_stage}.")
        else:
            self.pipeline_advance("translation")

    def _notify_translation_fallback_if_used(self):
        """Show a UI notice when an AI translation request used Google fallback."""
        selected_provider = str(os.getenv("OPENAI_PROVIDER") or "google").strip().lower()
        if selected_provider == "google" or not self.gui.is_ai_polish_enabled():
            return
        models = list(getattr(self.gui, "current_translated_segment_models", []) or [])
        providers = {
            str(getattr(model, "metadata", {}).get("translation_provider", "") or "").strip().lower()
            for model in models
        }
        if "google-web" not in providers:
            return
        signature = f"{getattr(self, 'prepare_run_id', 0)}:{selected_provider}"
        if getattr(self, "_fallback_notification_signature", "") == signature:
            return
        self._fallback_notification_signature = signature
        notice = "Nhà cung cấp AI không khả dụng. Đã chuyển sang dùng Google Translate thay thế."
        self.gui.log(f"[Dịch thuật] {notice}")

    def _notify_speaker_analysis_result(self, state):
        summary = dict(getattr(state, "settings", {}).get("speaker_analysis_summary") or {})
        characters = dict(getattr(state, "settings", {}).get("character_analysis_summary") or {})
        if not summary:
            return
        signature = str(getattr(state, "settings", {}).get("openai_speaker_analysis_signature", "") or "")
        if characters:
            signature += (
                f":char-v{characters.get('version', 0)}:"
                f"{characters.get('character_count', 0)}:"
                f"{characters.get('unknown_turn_count', 0)}:"
                f"{characters.get('voice_resolved_turn_count', 0)}:"
                f"{characters.get('split_turn_count', 0)}:"
                f"{characters.get('manual_correction_count', 0)}"
            )
        if signature and getattr(self, "_speaker_analysis_notice_signature", "") == signature:
            return
        self._speaker_analysis_notice_signature = signature
        effective = characters or summary
        count_key = "character_count" if characters else "speaker_count"
        label = "nhân vật có thoại" if characters else "cụm giọng"
        message = (
            f"Đã phát hiện {int(effective.get(count_key, 0) or 0)} {label}: "
            f"{int(effective.get('male_count', 0) or 0)} nam, "
            f"{int(effective.get('female_count', 0) or 0)} nữ"
        )
        unknown = int(
            effective.get("unknown_character_count", effective.get("unknown_turn_count", 0))
            if characters else effective.get("unknown_count", 0)
            or 0
        )
        if unknown:
            message += f", {unknown} giọng chưa đủ chắc chắn"
        if characters and int(characters.get("voice_resolved_turn_count", 0) or 0):
            message += (
                f". Phase 2 đã nhận lại "
                f"{int(characters.get('voice_resolved_turn_count', 0) or 0)} lượt thoại khuất mặt bằng dấu vân tay giọng"
            )
        if characters and int(characters.get("split_turn_count", 0) or 0):
            message += (
                f". Phase 3 đã tách "
                f"{int(characters.get('split_turn_count', 0) or 0)} lượt có nhiều nhân vật nói nối tiếp"
            )
        if characters and int(characters.get("manual_correction_count", 0) or 0):
            message += (
                f". Phase 4 đã áp dụng "
                f"{int(characters.get('manual_correction_count', 0) or 0)} correction của người dùng"
            )
        message += ".\n\n"
        if not characters:
            message += "Đây là số giọng khác nhau trong âm thanh, không phải số người xuất hiện trên hình. "
        message += "Kết quả này đã được dùng để phân vai tự động."
        self.gui.log(f"[OpenAI Speaker Analysis] {message.replace(chr(10), ' ')}")
        if not getattr(self.gui, "_queue_running", False):
            QMessageBox.information(self.gui, "Phân tích người nói", message)

    def pipeline_advance(self, completed_step: str):
        """Manages transitions between major pipeline segments."""
        if not self.gui._pipeline_active:
            return
            
        if self.progress_dialog:
            self.progress_dialog.finish_step(completed_step)

        _ctx = getattr(self, "_active_context", None)
        mode = _ctx.output_mode if _ctx else self.gui.get_output_mode_key()
        
        # State transitions
        if completed_step == "translation":
            if mode == "subtitle":
                self.pipeline_done()
                if self.progress_dialog:
                    self.progress_dialog.skip_step("voiceover")
                    self.progress_dialog.skip_step("preview")
                    self.progress_dialog.set_completed()
                return
            # Start voiceover
            self.gui._pipeline_step = "voiceover"
            if self.progress_dialog and self.progress_dialog.isVisible():
                self.progress_dialog.start_step("voiceover")
            self.gui.run_voiceover()
            
        elif completed_step == "voiceover":
            if getattr(self, "target_stage", "full") == "tts":
                self.pipeline_done()
                if self.progress_dialog:
                    self.progress_dialog.skip_step("preview")
                    self.progress_dialog.set_completed()
                return
            self.gui._pipeline_step = "preview"
            if self.progress_dialog and self.progress_dialog.isVisible():
                self.progress_dialog.start_step("preview")
            try:
                self.gui.log("[Pipeline] Voiceover complete. Preparing video preview.")
                self.gui.preview_video()
            except Exception as exc:
                self.pipeline_fail(f"Preview start failed: {exc}")
            
        elif completed_step == "preview":
            # Success!
            self.pipeline_done()
            if self.progress_dialog: 
                self.progress_dialog.set_completed()

    def pipeline_fail(self, reason: str):
        """Safely stops the pipeline and restores UI state on failure."""
        self.gui._pipeline_active = False
        self._stop_prepare_status_polling()
        self._stop_local_worker_server()
        
        if self.progress_dialog:
            current_step = getattr(self.gui, "_pipeline_step", "prepare")
            self.progress_dialog.fail_step(current_step)
            # Show the error reason in the footer
            self.progress_dialog.footer.setText(f"THẤT BẠI: {reason}")
            self.progress_dialog.footer.setStyleSheet("color: #FF4444; font-weight: bold;")

        # Restore UI
        if hasattr(self.gui, "run_all_btn"):
            self.gui.run_all_btn.setEnabled(True)
            self.gui.run_all_btn.setText("Tạo")
        
        self.gui.progress_bar.setRange(0, 100)
        self.gui.progress_bar.setValue(0)
        self.gui.refresh_ui_state()
        cb = getattr(self.gui, "on_pipeline_finished_callback", None)
        if callable(cb):
            cb(False, str(reason))

    def pipeline_review_required(self, reason: str):
        """Stop an automatic run cleanly when human review is required."""
        self.gui._pipeline_active = False
        self.gui._pipeline_step = ""
        self._stop_prepare_status_polling()
        self._stop_local_worker_server()
        if self.progress_dialog:
            self.progress_dialog.fail_step("voiceover")
            self.progress_dialog.footer.setText(f"CẦN KIỂM TRA: {reason}")
            self.progress_dialog.footer.setStyleSheet(
                "color: #FFB84D; font-weight: bold;"
            )
            self.progress_dialog.stop_btn.setEnabled(False)
        if hasattr(self.gui, "run_all_btn"):
            self.gui.run_all_btn.setEnabled(True)
            self.gui.run_all_btn.setText("Tạo")
        self.gui.progress_bar.setRange(0, 100)
        self.gui.progress_bar.setValue(0)
        self.gui.refresh_ui_state()
        cb = getattr(self.gui, "on_pipeline_finished_callback", None)
        if callable(cb):
            cb(False, str(reason))

    def pipeline_done(self):
        """Marks the entire pipeline as successfully finished."""
        self.gui._pipeline_active = False
        self.gui._pipeline_step = ""
        self._stop_prepare_status_polling()
        self._stop_local_worker_server()
        
        elapsed = max(0.1, time.time() - getattr(self, "_pipeline_start_time", time.time()))
        s_int = int(round(elapsed))
        if s_int < 60:
            dur_str = f"{s_int}s"
            full_str = f"{s_int} giây"
        else:
            m = s_int // 60
            rem = s_int % 60
            dur_str = f"{m}m {rem:02d}s"
            full_str = f"{m} phút {rem} giây"

        cur_p = getattr(self.gui, "_current_video_path", "")
        if cur_p:
            if not hasattr(self.gui, "_video_durations"):
                self.gui._video_durations = {}
            self.gui._video_durations[os.path.normpath(cur_p)] = elapsed

        self.gui.log(f"[Pipeline] 🎉 Toàn bộ quy trình hoàn tất trong {full_str} ({elapsed:.1f}s)!")
        if self.progress_dialog and hasattr(self.progress_dialog, "footer"):
            self.progress_dialog.footer.setText(f"🎉 Hoàn thành trong {dur_str}!")
            self.progress_dialog.footer.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 14px; margin-top: 15px;")

        if hasattr(self.gui, "run_all_btn"):
            self.gui.run_all_btn.setEnabled(True)
            self.gui.run_all_btn.setText("Tạo")
            
        self.gui.progress_bar.setRange(0, 100)
        self.gui.progress_bar.setValue(100)
        self.gui.refresh_ui_state()
        cb = getattr(self.gui, "on_pipeline_finished_callback", None)
        if callable(cb):
            cb(True, "")
