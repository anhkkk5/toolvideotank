"""
QueueController — Quản lý hàng đợi xử lý tuần tự từng video (1 luồng / sequential).

Nguyên tắc hoạt động:
1. Chạy đúng 1 video tại một thời điểm (Sequential Concurrency = 1).
2. Tái sử dụng trực tiếp Fast 1-Voice Pipeline (SingleVoicePipelineWorker):
   - Quét OCR phụ đề (hoặc tái sử dụng phụ đề đã quét)
   - Dịch theo ngữ cảnh bằng DeepSeek AI API
   - Lồng tiếng 1 giọng Neural (Adam, VieNeu VIP, v.v.)
   - Render nhanh với VideoCreatorService: Che mờ chữ Trung + Đè phụ đề tiếng Việt + Hòa âm ducking.
   -> Tối ưu tốc độ tối đa, không cần chạy remote_api_server, không làm chậm máy!
3. Tự động áp dụng cài đặt OCR riêng của từng video nếu người dùng đã đặt.
4. Tự động chuyển sang video tiếp theo khi video trước hoàn thành.
5. Hỗ trợ Dừng an toàn (Stop Queue) bất kỳ lúc nào.
"""

from __future__ import annotations

import os
import time
from typing import Optional, List, Dict, Any
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from utils.media_utils import browse_video


class SequentialQueueController(QObject):
    """Bộ điều khiển hàng đợi tuần tự 1 luồng."""

    status_changed = Signal(str, str)   # (norm_path, status: "idle" | "waiting" | "running" | "done" | "error")
    queue_progress = Signal(int, int)   # (current_index, total_count)
    queue_finished = Signal(bool, str)  # (all_success, summary_message)

    def __init__(self, gui):
        super().__init__(gui if isinstance(gui, QObject) else None)
        self.gui = gui
        self.queue: List[Dict[str, Any]] = []
        self.current_index = -1
        self.is_running = False
        self.stop_requested = False
        self.is_single_voice_pipeline = True
        self._setup_config: Dict[str, Any] = {}
        self._active_worker = None
        self.queue_start_time = 0.0
        self.item_start_times: Dict[str, float] = {}
        self.item_durations: Dict[str, float] = {}

        # Hook callback từ pipeline_controller (dành cho legacy fallback nếu có)
        self.gui.on_pipeline_finished_callback = self._on_pipeline_finished

    def start_single_voice_queue(
        self, selected_items: List[Dict[str, Any]], setup_config: Dict[str, Any]
    ) -> bool:
        """Khởi động hàng đợi với quy trình 1 giọng nhanh (SingleVoicePipelineWorker)."""
        if not selected_items:
            QMessageBox.warning(self.gui, "Hàng đợi", "Vui lòng tích chọn ít nhất 1 video để chạy hàng đợi.")
            return False

        if self.is_running:
            return False

        self.queue = list(selected_items)
        self._setup_config = dict(setup_config or {})
        self.is_single_voice_pipeline = True
        self.current_index = 0
        self.is_running = True
        self.stop_requested = False
        self.gui._queue_running = True
        self.queue_start_time = time.time()
        self.item_start_times = {}
        self.item_durations = {}
        if not hasattr(self.gui, "_video_durations"):
            self.gui._video_durations = {}

        if not hasattr(self.gui, "_video_queue_status"):
            self.gui._video_queue_status = {}
        if not hasattr(self.gui, "_video_queue_percent"):
            self.gui._video_queue_percent = {}

        # Đánh dấu trạng thái ban đầu cho các video
        for idx, it in enumerate(self.queue):
            p = os.path.normpath(it.get("path", ""))
            if p:
                status = "running" if idx == 0 else "waiting"
                self.gui._video_queue_status[p] = status
                self.gui._video_queue_percent[p] = 0
                self.status_changed.emit(p, status)

        voice_info = self._setup_config.get("selected_voice", {})
        v_name = voice_info.get("name", "1 Giọng")
        self.gui.log(
            f"[Hàng đợi] Bắt đầu xử lý {len(self.queue)} video tuần tự (1 giọng: {v_name})..."
        )
        self.queue_progress.emit(1, len(self.queue))
        self._refresh_ui()

        # Bắt đầu xử lý video đầu tiên
        QTimer.singleShot(150, self._process_current_item)
        return True

    def start_queue(self, selected_items: List[Dict[str, Any]]) -> bool:
        """Fallback: Nếu gọi start_queue mà không truyền setup_config, lấy config mặc định và chạy."""
        if not selected_items:
            QMessageBox.warning(self.gui, "Hàng đợi", "Vui lòng tích chọn ít nhất 1 video để chạy hàng đợi.")
            return False

        default_cfg = {
            "selected_voice": {"id": "adam1", "name": "Adam", "provider": "piper"},
            "audio_mix": {"original_volume": 0.50, "tts_volume": 1.00, "duck_volume": 0.20},
            "enable_blur": True,
            "default_blur_rect": None,
            "burn_subs": True,
            "sub_cfg": None,
            "brand_logo": None,
            "watermark": None,
        }
        return self.start_single_voice_queue(selected_items, default_cfg)

    def stop_queue(self):
        """Dừng hàng đợi an toàn."""
        if not self.is_running and not getattr(self.gui, "_queue_running", False):
            return

        self.stop_requested = True
        self.is_running = False
        self.gui._queue_running = False

        # Dừng worker đang chạy nếu có
        if self._active_worker is not None:
            try:
                if hasattr(self._active_worker, "request_cancel"):
                    self._active_worker.request_cancel()
            except Exception:
                pass

        # Dừng legacy controller nếu đang chạy
        ctrl = getattr(self.gui, "pipeline_controller", None)
        if ctrl and hasattr(ctrl, "stop_pipeline_immediately"):
            try:
                ctrl.stop_pipeline_immediately()
            except Exception:
                pass

        # Đánh dấu các video còn lại là idle
        for it in self.queue:
            p = os.path.normpath(it.get("path", ""))
            if p and self.gui._video_queue_status.get(p) in ("waiting", "running"):
                self.gui._video_queue_status[p] = "idle"
                self.status_changed.emit(p, "idle")

        self.gui.log("[Hàng đợi] Đã dừng hàng đợi theo yêu cầu người dùng.")
        self.queue_finished.emit(False, "Hàng đợi đã dừng.")
        self._refresh_ui()

    def _process_current_item(self):
        """Xử lý video tại current_index."""
        if not self.is_running or self.stop_requested:
            self._finish_queue(stopped=True)
            return

        if self.current_index >= len(self.queue):
            self._finish_queue(stopped=False)
            return

        item = self.queue[self.current_index]
        video_path = item.get("path", "")
        norm_p = os.path.normpath(video_path) if video_path else ""

        if not video_path or not os.path.isfile(video_path):
            self.gui.log(f"[Hàng đợi] Không tìm thấy tệp video: {video_path}")
            if norm_p:
                self.gui._video_queue_status[norm_p] = "error"
                self.status_changed.emit(norm_p, "error")
            self.current_index += 1
            QTimer.singleShot(400, self._process_current_item)
            return

        # Cập nhật trạng thái hiển thị
        self.item_start_times[norm_p] = time.time()
        self.gui._video_queue_status[norm_p] = "running"
        self.status_changed.emit(norm_p, "running")
        self.queue_progress.emit(self.current_index + 1, len(self.queue))
        self._refresh_ui()

        self.gui.log(
            f"[Hàng đợi] ({self.current_index + 1}/{len(self.queue)}) Đang xử lý: {os.path.basename(video_path)}"
        )

        # Kiểm tra xem video này có phải là video 2 giọng (chưa duyệt kịch bản) hay không
        v_cfg = getattr(self.gui, "_video_voice_configs", {}).get(norm_p, {})
        is_dual = (v_cfg.get("voice_mode") == "dual")
        approved_cues = v_cfg.get("approved_cues")

        if is_dual and not approved_cues:
            # Video 2 giọng chưa kiểm tra duyệt kịch bản -> Chạy Phân vai AI chuẩn và mở Bảng Lịch sử
            self._run_dual_voice_check(video_path, norm_p)
            return

        if self.is_single_voice_pipeline:
            self._run_fast_single_voice_pipeline(video_path, norm_p)
        else:
            self._run_legacy_pipeline(video_path, norm_p)

    def _run_dual_voice_check(self, video_path: str, norm_p: str):
        """Chạy Phân vai AI chuẩn (ASR + VAD + OCR + Multimodal Fusion) tương đương nút '🎙️ Phân vai AI'."""
        ocr_rect = (
            getattr(self.gui, "_video_ocr_rects", {}).get(norm_p)
            or self._setup_config.get("default_blur_rect")
        )
        if ocr_rect and len(ocr_rect) == 4:
            os.environ["OCR_SUBTITLE_RECT"] = f"{ocr_rect[0]},{ocr_rect[1]},{ocr_rect[2]},{ocr_rect[3]}"

        self.gui.log(
            f"[Hàng đợi {self.current_index + 1}/{len(self.queue)}] Bắt đầu Phân vai AI chuẩn (ASR + VAD + Multimodal Fusion) cho: {os.path.basename(video_path)}..."
        )

        from ui.worker_adapters.processing_workers import VoiceGenderCheckWorker

        worker = VoiceGenderCheckWorker(video_path, existing_cues=None, ocr_rect=ocr_rect)
        self._active_worker = worker

        def _on_check_progress(msg: str):
            short = str(msg or "").strip()
            self.gui.log(f"[Phân vai AI - {os.path.basename(video_path)}] {short}")
            if not hasattr(self.gui, "_video_queue_percent"):
                self.gui._video_queue_percent = {}
            self.gui._video_queue_percent[norm_p] = 50
            self._refresh_ui()

        def _on_check_completed(result, error):
            self._active_worker = None
            if error:
                self.gui.log(f"[Hàng đợi] Lỗi phân vai AI video '{os.path.basename(video_path)}': {error}")
                self.gui._video_queue_status[norm_p] = "error"
                self.status_changed.emit(norm_p, "error")
                self._refresh_ui()
                self.current_index += 1
                if self.stop_requested or self.current_index >= len(self.queue):
                    self._finish_queue(stopped=self.stop_requested)
                else:
                    QTimer.singleShot(400, self._process_current_item)
                return

            import copy
            res = copy.deepcopy(dict(result or {}))
            res["video_path"] = video_path

            hist_id = ""
            try:
                hist_id = self.gui._save_voice_gender_history(res)
            except Exception as e:
                self.gui.log(f"[Hàng đợi] Lỗi lưu lịch sử: {e}")

            if not hasattr(self.gui, "_video_voice_configs"):
                self.gui._video_voice_configs = {}
            if norm_p not in self.gui._video_voice_configs:
                self.gui._video_voice_configs[norm_p] = {}
            self.gui._video_voice_configs[norm_p]["pending_result"] = res
            self.gui._video_voice_configs[norm_p]["history_entry_id"] = hist_id

            # Lưu danh sách phụ đề đã dịch & gán vai vào cache
            rows_list = res.get("rows") or []
            if not hasattr(self.gui, "_video_translated_cues"):
                self.gui._video_translated_cues = {}
            if rows_list:
                self.gui._video_translated_cues[norm_p] = rows_list
                # Nếu video này đang được chọn hiển thị, đồng bộ ngay lên timeline
                cur_p = getattr(self.gui, "_current_video_path", "")
                if cur_p and os.path.normpath(cur_p) == norm_p:
                    self._sync_cues_to_gui(rows_list)

            # Đổi trạng thái hiển thị thành "review" (📋 Chờ duyệt vai)
            self.gui._video_queue_status[norm_p] = "review"
            self.gui._video_queue_percent[norm_p] = 100
            self.status_changed.emit(norm_p, "review")
            self.gui.log(
                f"[Hàng đợi] ✓ Video '{os.path.basename(video_path)}' đã phân vai AI xong! Vui lòng kiểm tra và duyệt phân vai trong Bảng Lịch sử."
            )

            # Mở ngay Bảng Lịch sử / Kết quả kiểm tra giọng nói
            try:
                self.gui._on_voice_gender_check_completed(res, "", save_history=False, history_entry_id=hist_id)
            except Exception as exc:
                self.gui.log(f"[Hàng đợi] Không thể mở bảng kết quả: {exc}")

            self._refresh_ui()

            # Tiếp tục xử lý video tiếp theo trong hàng đợi (hàng đợi không bị tắc)
            self.current_index += 1
            if self.stop_requested or self.current_index >= len(self.queue):
                self._finish_queue(stopped=self.stop_requested)
            else:
                self.gui.log(
                    f"[Hàng đợi] Tiếp tục chuyển sang video tiếp theo trong khi chờ bạn duyệt kịch bản video '{os.path.basename(video_path)}'..."
                )
                QTimer.singleShot(400, self._process_current_item)

        worker.progress.connect(_on_check_progress)
        worker.completed.connect(_on_check_completed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def enqueue_approved_video(self, norm_p: str):
        """Xử lý khi người dùng duyệt xong phân vai của một video từ Bảng Lịch sử."""
        norm_p = os.path.normpath(norm_p)
        video_name = os.path.basename(norm_p)

        is_busy = self.is_running and (self._active_worker is not None and self._active_worker.isRunning())

        if is_busy:
            self.gui._video_queue_status[norm_p] = "waiting"
            self.gui._video_queue_percent[norm_p] = 0
            self.status_changed.emit(norm_p, "waiting")

            found = False
            for item in self.queue:
                if os.path.normpath(item.get("path", "")) == norm_p:
                    found = True
                    break
            if not found:
                self.queue.append({"path": norm_p, "name": video_name})

            self.gui.log(
                f"[Hàng đợi] Video '{video_name}' đã được duyệt vai! Đang có video khác đang xử lý nên video này được xếp vào hàng chờ."
            )
            self._refresh_ui()
        else:
            self.gui._video_queue_status[norm_p] = "running"
            self.gui._video_queue_percent[norm_p] = 0
            self.status_changed.emit(norm_p, "running")
            self.gui.log(
                f"[Hàng đợi] Video '{video_name}' đã được duyệt vai! Bắt đầu tạo video ngay."
            )
            item = {"path": norm_p, "name": video_name}
            self.queue = [item]
            self.current_index = 0
            self.is_running = True
            self.stop_requested = False
            self.gui._queue_running = True
            self.item_start_times[norm_p] = time.time()
            self._refresh_ui()
            self._run_fast_single_voice_pipeline(norm_p, norm_p)

    def _run_fast_single_voice_pipeline(self, video_path: str, norm_p: str):
        """Thực thi pipeline 1 giọng nhanh thông qua SingleVoicePipelineWorker."""
        # 1. Xác định khung OCR cho video này (ưu tiên khung riêng biệt đã lưu của video)
        ocr_rect = (
            getattr(self.gui, "_video_ocr_rects", {}).get(norm_p)
            or self._setup_config.get("default_blur_rect")
        )
        if ocr_rect and len(ocr_rect) == 4:
            os.environ["OCR_SUBTITLE_RECT"] = f"{ocr_rect[0]},{ocr_rect[1]},{ocr_rect[2]},{ocr_rect[3]}"

        # 2. Xác định đường dẫn file video hoàn chỉnh
        output_folder = (
            self.gui.final_output_folder_edit.text().strip()
            if hasattr(self.gui, "final_output_folder_edit") and self.gui.final_output_folder_edit.text().strip()
            else os.path.join(str(getattr(self.gui, "workspace_root", os.getcwd())), "output")
        )
        os.makedirs(output_folder, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(video_path))[0]
        output_video_path = os.path.join(output_folder, f"{base_name}_final_vi.mp4")

        # 3. Kiểm tra xem video này có phụ đề đã quét trước đó trên giao diện không
        existing_cues = None
        cur_p = getattr(self.gui, "_current_video_path", "")
        if cur_p and os.path.normpath(cur_p) == norm_p:
            raw_segs = getattr(self.gui, "current_segments", None) or getattr(
                self.gui, "current_translated_segments", None
            )
            if raw_segs and isinstance(raw_segs, list) and any(
                s.get("text") for s in raw_segs if isinstance(s, dict)
            ):
                existing_cues = [dict(s) for s in raw_segs if isinstance(s, dict) and s.get("text")]

        # 4. Khởi tạo SingleVoicePipelineWorker
        from ui.dialogs.single_voice_progress_dialog import SingleVoicePipelineWorker

        # Kiểm tra xem video này được cấu hình 2 giọng (Phân vai) hay 1 giọng
        v_cfg = getattr(self.gui, "_video_voice_configs", {}).get(norm_p, {})
        is_dual = (v_cfg.get("voice_mode") == "dual")
        dual_cfg = None

        if is_dual:
            dual_cfg = v_cfg
            sel_voice = {"id": "dual", "name": v_cfg.get("label", "2 Giọng")}
            self.gui.log(
                f"[Hàng đợi {self.current_index + 1}/{len(self.queue)}] Áp dụng chế độ: PHÂN VAI 2 GIỌNG ({v_cfg.get('label')})"
            )
        else:
            # Xác định giọng đọc cho video này (tôn trọng giọng riêng của từng video)
            use_individual = self._setup_config.get("use_individual_voices", False) or (
                self._setup_config.get("selected_voice", {}).get("id") == "keep_individual"
            )
            sel_voice = None
            if use_individual:
                v_id = v_cfg.get("voice_name")
                v_lbl = v_cfg.get("label") or ""
                if v_id:
                    sel_voice = self._resolve_voice_dict(v_id, v_lbl)

            if not sel_voice:
                sel_voice = self._setup_config.get("selected_voice", {"id": "adam1", "name": "Adam", "provider": "piper"})
                if sel_voice.get("id") == "keep_individual":
                    v_id = v_cfg.get("voice_name")
                    v_lbl = v_cfg.get("label") or ""
                    if v_id:
                        sel_voice = self._resolve_voice_dict(v_id, v_lbl)
                    else:
                        sel_voice = {"id": "adam1", "name": "Adam", "provider": "piper"}

            self.gui.log(
                f"[Hàng đợi {self.current_index + 1}/{len(self.queue)}] Áp dụng giọng đọc: {sel_voice.get('name')} (ID: {sel_voice.get('id')})"
            )

        mix_settings = self._setup_config.get("audio_mix", {"original_volume": 0.50, "tts_volume": 1.00, "duck_volume": 0.20})
        enable_blur = bool(self._setup_config.get("enable_blur", True))
        sub_cfg = self._setup_config.get("sub_cfg")
        mask_mode = str(self._setup_config.get("mask_mode") or getattr(sub_cfg, "mask_mode", "box") or "box").strip().lower()
        burn_subs = bool(self._setup_config.get("burn_subs", True))
        brand_logo = self._setup_config.get("brand_logo")
        watermark = self._setup_config.get("watermark")
        delogo_settings = self._setup_config.get("delogo_settings")

        approved_cues = v_cfg.get("approved_cues") if is_dual else None

        worker = SingleVoicePipelineWorker(
            workspace_root=str(getattr(self.gui, "workspace_root", os.getcwd())),
            video_path=video_path,
            selected_voice=sel_voice,
            audio_mix_settings=mix_settings,
            enable_blur_mask=enable_blur,
            mask_mode=mask_mode,
            blur_rect=ocr_rect,
            burn_subtitles=burn_subs,
            existing_cues=existing_cues,
            output_video_path=output_video_path,
            subtitle_config=sub_cfg,
            brand_logo_settings=brand_logo,
            watermark_settings=watermark,
            delogo_settings=delogo_settings,
            dual_voice_config=dual_cfg,
            approved_cues=approved_cues,
        )
        self._active_worker = worker

        def _on_worker_progress(pct: float, msg: str):
            if not hasattr(self.gui, "_video_queue_percent"):
                self.gui._video_queue_percent = {}
            int_pct = int(pct)
            self.gui._video_queue_percent[norm_p] = int_pct
            self.gui.log(f"[Hàng đợi {self.current_index + 1}/{len(self.queue)}] {int_pct}% - {msg}")
            self._refresh_ui()

        def _on_worker_finished(result, translated_cues):
            self._active_worker = None
            t_start = self.item_start_times.get(norm_p, time.time())
            item_elapsed = max(0.1, time.time() - t_start)
            self.item_durations[norm_p] = item_elapsed
            if not hasattr(self.gui, "_video_durations"):
                self.gui._video_durations = {}
            self.gui._video_durations[norm_p] = item_elapsed

            if not hasattr(self.gui, "_video_output_paths"):
                self.gui._video_output_paths = {}
            self.gui._video_output_paths[norm_p] = output_video_path

            if not hasattr(self.gui, "_video_translated_cues"):
                self.gui._video_translated_cues = {}
            if translated_cues:
                self.gui._video_translated_cues[norm_p] = translated_cues
                try:
                    from app.translation.srt_utils import to_srt
                    srt_out_path = os.path.splitext(output_video_path)[0] + ".srt"
                    with open(srt_out_path, "w", encoding="utf-8") as sf:
                        sf.write(to_srt(translated_cues, prefer_translated=True))
                except Exception as srt_err:
                    self.gui.log(f"[Hàng đợi] Không thể ghi file phụ đề SRT: {srt_err}")

            # Nếu video vừa hoàn tất đang hiển thị trên player, đồng bộ ngay phụ đề lên timeline và cột phụ đề
            cur_p = getattr(self.gui, "_current_video_path", "")
            if cur_p and os.path.normpath(cur_p) == norm_p and translated_cues:
                self._sync_cues_to_gui(translated_cues)

            # Tự động tắt khung OCR sau khi hoàn thành tạo video
            if hasattr(self.gui, "toggle_ocr_overlay_visibility"):
                self.gui.toggle_ocr_overlay_visibility(False)

            self._on_item_completed(norm_p, True, f"Xuất video hoàn thành: {output_video_path}")

        def _on_worker_error(err_msg: str):
            self._active_worker = None
            t_start = self.item_start_times.get(norm_p, time.time())
            item_elapsed = max(0.1, time.time() - t_start)
            self.item_durations[norm_p] = item_elapsed
            if not hasattr(self.gui, "_video_durations"):
                self.gui._video_durations = {}
            self.gui._video_durations[norm_p] = item_elapsed
            self._on_item_completed(norm_p, False, err_msg)

        worker.progress_updated.connect(_on_worker_progress)
        worker.log_emitted.connect(self.gui.log)
        worker.pipeline_finished.connect(_on_worker_finished)
        worker.pipeline_error.connect(_on_worker_error)
        worker.start()

    def _run_legacy_pipeline(self, video_path: str, norm_p: str):
        """Chạy pipeline legacy (dùng cho trường hợp fallback)."""
        ctrl = getattr(self.gui, "pipeline_controller", None)
        if ctrl and hasattr(ctrl, "run_all_pipeline"):
            ctrl.run_all_pipeline(video_path=video_path)
        else:
            self._on_item_completed(norm_p, False, "Không tìm thấy pipeline_controller.")

    def _on_pipeline_finished(self, success: bool, message: str):
        """Callback dành cho legacy pipeline_controller."""
        if not self.is_running or self.is_single_voice_pipeline:
            return
        if 0 <= self.current_index < len(self.queue):
            item = self.queue[self.current_index]
            norm_p = os.path.normpath(item.get("path", ""))
            t_start = self.item_start_times.get(norm_p, time.time())
            item_elapsed = max(0.1, time.time() - t_start)
            self.item_durations[norm_p] = item_elapsed
            if not hasattr(self.gui, "_video_durations"):
                self.gui._video_durations = {}
            self.gui._video_durations[norm_p] = item_elapsed
            self._on_item_completed(norm_p, success, message)

    def _on_item_completed(self, norm_p: str, success: bool, message: str):
        """Xử lý khi một video trong hàng đợi chạy xong."""
        if not self.is_running:
            return

        if not hasattr(self.gui, "_video_queue_percent"):
            self.gui._video_queue_percent = {}

        d = self.item_durations.get(norm_p)
        dur_msg = f" (Thời gian: {self._format_duration(d)})" if d else ""

        if success:
            self.gui._video_queue_status[norm_p] = "done"
            self.gui._video_queue_percent[norm_p] = 100
            self.status_changed.emit(norm_p, "done")
            self.gui.log(
                f"[Hàng đợi] ({self.current_index + 1}/{len(self.queue)}) ✓ ĐÃ XONG{dur_msg}: {os.path.basename(norm_p)}"
            )
        else:
            self.gui._video_queue_status[norm_p] = "error"
            self.gui._video_queue_percent[norm_p] = 0
            self.status_changed.emit(norm_p, "error")
            self.gui.log(
                f"[Hàng đợi] ({self.current_index + 1}/{len(self.queue)}) ✕ LỖI ({message}): {os.path.basename(norm_p)}"
            )

        self._refresh_ui()

        # Chuyển sang video tiếp theo
        self.current_index += 1
        if self.stop_requested or self.current_index >= len(self.queue):
            self._finish_queue(stopped=self.stop_requested)
        else:
            self.gui.log(
                f"[Hàng đợi] Chuẩn bị chuyển sang video tiếp theo ({self.current_index + 1}/{len(self.queue)})..."
            )
            QTimer.singleShot(400, self._process_current_item)

    def _sync_cues_to_gui(self, cues: list):
        """Đồng bộ danh sách phụ đề lên Timeline và Panel danh sách phụ đề."""
        try:
            trans_segs = []
            base_segs = []
            for idx, c in enumerate(cues):
                if not isinstance(c, dict):
                    continue
                s_s = float(c.get("start", 0.0))
                e_s = float(c.get("end", 0.0))
                t_txt = str(c.get("translated_text", "") or c.get("translated", "")).strip()
                o_txt = str(c.get("source_text", "") or c.get("original", "") or c.get("original_text", "") or c.get("text", "")).strip()
                raw_txt = str(c.get("text", "")).strip()
                if not t_txt and raw_txt:
                    t_txt = raw_txt
                speaker = str(c.get("speaker", "") or c.get("speaker_label", "") or "").strip()
                gender = str(c.get("gender", "") or c.get("final_gender", "") or "").strip()

                d_trans = {
                    "id": c.get("id", idx + 1),
                    "start": s_s,
                    "end": e_s,
                    "text": t_txt or o_txt,
                    "translated": t_txt,
                    "translated_text": t_txt,
                    "original": o_txt,
                    "source_text": o_txt,
                }
                if speaker:
                    d_trans["speaker"] = speaker
                if gender:
                    d_trans["gender"] = gender
                trans_segs.append(d_trans)

                d_base = {
                    "id": c.get("id", idx + 1),
                    "start": s_s,
                    "end": e_s,
                    "text": o_txt or raw_txt,
                    "original": o_txt or raw_txt,
                    "source_text": o_txt or raw_txt,
                }
                if speaker:
                    d_base["speaker"] = speaker
                if gender:
                    d_base["gender"] = gender
                base_segs.append(d_base)

            self.gui.current_translated_segments = trans_segs
            if base_segs:
                self.gui.current_segments = base_segs
            if hasattr(self.gui, "timeline") and hasattr(self.gui.timeline, "set_segments"):
                self.gui.timeline.set_segments(trans_segs)
            if hasattr(self.gui, "subtitle_list_view") and hasattr(self.gui.subtitle_list_view, "refresh_segments"):
                self.gui.subtitle_list_view.refresh_segments()
        except Exception as e:
            self.gui.log(f"[Hàng đợi] Lỗi khi đồng bộ phụ đề lên giao diện: {e}")

    def _resolve_voice_dict(self, voice_id: str, label: str = "") -> dict[str, str]:
        """Phục hồi dict cấu hình giọng {id, name, provider} từ voice_id."""
        if not voice_id:
            return {"id": "adam1", "name": "Adam", "provider": "piper"}

        if "vieneu" in voice_id:
            return {
                "id": voice_id,
                "name": label or ("Thanh niên tự tin" if "thanhnien" in voice_id else "Cô gái hoạt ngôn"),
                "provider": "vieneu",
            }

        try:
            from ui.dialogs.select_master_dialog import _load_available_voices
            fems, males = _load_available_voices()
            for v in males + fems:
                if v.get("id") == voice_id:
                    return dict(v)
        except Exception:
            pass

        provider = "edge" if "Neural" in voice_id else "piper"
        return {
            "id": voice_id,
            "name": label or voice_id,
            "provider": provider,
        }

    @staticmethod
    def _format_duration(seconds: float | None) -> str:
        if seconds is None or seconds < 0:
            return "0s"
        s = int(round(seconds))
        if s < 60:
            return f"{s}s"
        mins = s // 60
        rem = s % 60
        if rem == 0:
            return f"{mins} phút"
        return f"{mins} phút {rem:02d}s"

    def _finish_queue(self, stopped: bool = False):
        """Kết thúc toàn bộ hàng đợi."""
        self.is_running = False
        self.gui._queue_running = False
        self._active_worker = None
        if hasattr(self.gui, "toggle_ocr_overlay_visibility"):
            self.gui.toggle_ocr_overlay_visibility(False)

        total = len(self.queue)
        done_count = sum(
            1 for it in self.queue
            if self.gui._video_queue_status.get(os.path.normpath(it.get("path", ""))) == "done"
        )

        total_elapsed = max(0.1, time.time() - getattr(self, "queue_start_time", time.time()))
        tot_str = self._format_duration(total_elapsed)
        avg_str = self._format_duration(total_elapsed / max(1, done_count))

        self._refresh_ui()

        if stopped:
            summary = f"Hàng đợi đã dừng (Đã xong {done_count}/{total} video trong {tot_str})."
            self.gui.log(f"[Hàng đợi] {summary}")
            self.queue_finished.emit(False, summary)
        else:
            summary = f"Đã hoàn thành toàn bộ hàng đợi ({done_count}/{total} video thành công)!"
            self.gui.log(f"[Hàng đợi] {summary} ⏱️ Tổng thời gian: {tot_str} (Trung bình {avg_str}/video)")
            self.queue_finished.emit(True, summary)

            output_folder = (
                self.gui.final_output_folder_edit.text().strip()
                if hasattr(self.gui, "final_output_folder_edit") and self.gui.final_output_folder_edit.text().strip()
                else os.path.join(str(getattr(self.gui, "workspace_root", os.getcwd())), "output")
            )
            os.makedirs(output_folder, exist_ok=True)

            msg_box = QMessageBox(self.gui)
            msg_box.setWindowTitle("Hàng đợi hoàn tất")
            msg_box.setIcon(QMessageBox.Information)

            msg_text = (
                f"🎉 {summary}\n\n"
                f"⏱️ Tổng thời gian: {tot_str}\n"
            )
            if done_count > 1:
                msg_text += f"⚡ Tốc độ trung bình: {avg_str} / video\n"
            msg_text += f"\n📁 Thư mục lưu video:\n{output_folder}"
            msg_box.setText(msg_text)

            detail_lines = [
                f"⏱️ TỔNG THỜI GIAN: {tot_str}",
                f"📊 KẾT QUẢ: {done_count}/{total} video thành công",
            ]
            if done_count > 1:
                detail_lines.append(f"⚡ TRUNG BÌNH: {avg_str} / video")
            detail_lines.append("\nCHI TIẾT THỜI GIAN TỪNG VIDEO:")
            for idx, it in enumerate(self.queue, 1):
                p = os.path.normpath(it.get("path", ""))
                d = self.item_durations.get(p)
                d_str = self._format_duration(d) if d else "N/A"
                detail_lines.append(f" {idx}. {os.path.basename(p)}: {d_str}")
            msg_box.setDetailedText("\n".join(detail_lines))

            btn_open = msg_box.addButton("📂 Mở thư mục video", QMessageBox.ActionRole)
            btn_close = msg_box.addButton("Đóng", QMessageBox.RejectRole)
            msg_box.setDefaultButton(btn_open)
            msg_box.exec()

            if msg_box.clickedButton() == btn_open:
                if hasattr(self.gui, "open_folder") and callable(self.gui.open_folder):
                    self.gui.open_folder(output_folder)
                else:
                    try:
                        os.startfile(output_folder)
                    except Exception:
                        import subprocess
                        subprocess.Popen(["explorer", output_folder])

    def _refresh_ui(self):
        if hasattr(self.gui, "_refresh_media_pool_ui") and callable(self.gui._refresh_media_pool_ui):
            self.gui._refresh_media_pool_ui()
