"""Progress Dialog executing Pipeline B with VideoCreatorWorker and VideoCreatorService.

Adheres strictly to Contract Step 9.1 v1.1 (LOCKED) and Step 9.3 (APPROVED):
- Replaces legacy VoiceOverWorker + PipelineBPostProcessWorker with VideoCreatorWorker.
- UI State Machine: IDLE -> RUNNING -> CANCELLING -> TERMINAL.
- Cooperative Cancellation: request_cancel() via threading.Event, NO terminate(), NO wait() blocking GUI.
- Responsive closeEvent: non-blocking close request waiting for pipeline_finished.
- Preserves 100% of UI layout, styling, and visual indicators.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.render_job import RenderJob
from app.models.subtitle_segment import SubtitleSegment
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorResult,
    VideoCreatorService,
)
from ui.worker_adapters.video_creator_adapter import VideoCreatorWorker


class PipelineBProgressDialog(QDialog):
    """Hộp thoại hiển thị toàn bộ tiến trình tạo video tự động (Pipeline B)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        job: RenderJob | None = None,
        target_dataset: Any = None,
        original_video_path: str = "",
        segments: list[SubtitleSegment] | None = None,
        output_video_path: str = "",
        workspace_dir: str = "",
        config: VideoCreatorConfig | None = None,
        service: VideoCreatorService | None = None,
    ):
        super().__init__(parent)
        self.job = job
        self.target_dataset = target_dataset or (job.master_dataset if job else None)
        self.segments = segments or (list(self.target_dataset.segments) if self.target_dataset else [])
        self.original_video_path = (
            original_video_path
            or (getattr(self.target_dataset, "video_path", "") if self.target_dataset else "")
            or (getattr(self.job.master_dataset, "video_path", "") if (self.job and self.job.master_dataset) else "")
        )
        self.output_video_path = output_video_path or (getattr(job, "output_video_file", "") if job else "")
        self.workspace_dir = workspace_dir or (getattr(job, "job_dir", "") if job else "")
        self.config = config or VideoCreatorConfig()
        self._service = service

        # Strong reference to background worker
        self._worker: VideoCreatorWorker | None = None
        self.output_mp4: str = ""

        # UI State Machine: IDLE -> RUNNING -> CANCELLING -> TERMINAL
        self._ui_state: str = "IDLE"
        self._close_requested: bool = False

        self.setWindowTitle("TankVideo Studio - Tiến trình tạo video tự động (Pipeline B)")
        self.resize(750, 520)
        self.setMinimumSize(650, 450)

        self._setup_ui()
        self._apply_dark_style()
        self._start_pipeline()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)

        # Header Info
        header_title = QLabel("⚡ TIẾN TRÌNH TẠO VIDEO TỰ ĐỘNG (TANKVIDEO)")
        h_font = QFont()
        h_font.setPointSize(12)
        h_font.setBold(True)
        header_title.setFont(h_font)
        header_title.setStyleSheet("color: #ff7b1a;")
        root_layout.addWidget(header_title)

        # Extract counts
        if self.target_dataset and hasattr(self.target_dataset, "counts") and self.target_dataset.counts:
            meta_counts = self.target_dataset.counts
        else:
            male_cnt = sum(1 for s in self.segments if getattr(s, "final_gender", "") == "male")
            female_cnt = sum(1 for s in self.segments if getattr(s, "final_gender", "") == "female")
            unknown_cnt = sum(1 for s in self.segments if getattr(s, "final_gender", "") not in ("male", "female"))
            meta_counts = {
                "total": len(self.segments),
                "male": male_cnt,
                "female": female_cnt,
                "unknown": unknown_cnt,
                "none": 0,
            }

        video_name = (
            os.path.basename(self.original_video_path)
            if self.original_video_path
            else (getattr(self.target_dataset, "title", "Video") if self.target_dataset else "Video")
        )
        non_tts_cnt = meta_counts.get("unknown", 0) + meta_counts.get("none", 0)
        lbl_info = QLabel(
            f"🎥 Video: {video_name} | "
            f"📊 Kịch bản: {meta_counts['total']} câu (Nam: {meta_counts['male']}, "
            f"Nữ: {meta_counts['female']}, Không TTS: {non_tts_cnt})"
        )
        lbl_info.setStyleSheet("color: #8b949e; font-size: 11px;")
        root_layout.addWidget(lbl_info)

        # 3 Step Visual Indicators
        steps_frame = QFrame()
        steps_frame.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 6px;")
        steps_layout = QHBoxLayout(steps_frame)
        steps_layout.setContentsMargins(10, 8, 10, 8)

        self.lbl_step1 = QLabel("1. 📄 Master Data\n[✅ Đã duyệt]")
        self.lbl_step1.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 11px;")
        self.lbl_step1.setAlignment(Qt.AlignCenter)

        self.lbl_step2 = QLabel("2. 🎙️ Lồng tiếng AI\n[Chờ xử lý]")
        self.lbl_step2.setStyleSheet("color: #8b949e; font-weight: bold; font-size: 11px;")
        self.lbl_step2.setAlignment(Qt.AlignCenter)

        self.lbl_step3 = QLabel("3. 🎞️ Hòa âm & Xuất MP4\n[Chờ xử lý]")
        self.lbl_step3.setStyleSheet("color: #8b949e; font-weight: bold; font-size: 11px;")
        self.lbl_step3.setAlignment(Qt.AlignCenter)

        steps_layout.addWidget(self.lbl_step1, 1)
        steps_layout.addWidget(self.lbl_step2, 1)
        steps_layout.addWidget(self.lbl_step3, 1)
        root_layout.addWidget(steps_frame)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #21262d;
                color: #ffffff;
                border: 1px solid #30363d;
                border-radius: 6px;
                text-align: center;
                height: 22px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1f6feb, stop:1 #238636);
                border-radius: 5px;
            }
        """)
        root_layout.addWidget(self.progress_bar)

        # Status Label
        self.lbl_status = QLabel("Khởi tạo tiến trình...")
        self.lbl_status.setStyleSheet("color: #e6edf3; font-weight: bold; font-size: 12px;")
        root_layout.addWidget(self.lbl_status)

        # Realtime Log Box
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("""
            QTextEdit {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                color: #c9d1d9;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        root_layout.addWidget(self.log_box)

        # Button Controls
        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("Hủy tiến trình")
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_layout.addWidget(self.btn_cancel)

        btn_layout.addStretch()

        self.btn_open_folder = QPushButton("📂 Mở thư mục video")
        self.btn_open_folder.setVisible(False)
        self.btn_open_folder.clicked.connect(self._on_open_folder_clicked)
        btn_layout.addWidget(self.btn_open_folder)

        self.btn_close = QPushButton("Đóng")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setEnabled(False)
        btn_layout.addWidget(self.btn_close)

        root_layout.addLayout(btn_layout)

    def _apply_dark_style(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #121316;
                color: #e2e8f0;
            }
            QProgressBar {
                border: 1px solid #2d323c;
                border-radius: 6px;
                text-align: center;
                background-color: #181a20;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7b1a, stop:1 #e04800);
                border-radius: 6px;
            }
            QTextEdit {
                background-color: #16181d;
                border: 1px solid #2d323c;
                border-radius: 6px;
                color: #cbd5e1;
                font-family: Consolas, 'Segoe UI', monospace;
            }
            QPushButton {
                background-color: #20242c;
                border: 1px solid #333946;
                border-radius: 6px;
                color: #e2e8f0;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #292e39;
                border-color: #ff7b1a;
                color: #ffffff;
            }
        """)

    def _append_log(self, text: str):
        self.log_box.append(text)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def _start_pipeline(self):
        """Bắt đầu chạy pipeline thông qua VideoCreatorWorker."""
        self._ui_state = "RUNNING"
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText("Hủy tiến trình")
        self.btn_close.setEnabled(False)
        self.btn_open_folder.setVisible(False)

        self._append_log("🚀 Bắt đầu TankVideo Studio Pipeline: Đọc dữ liệu từ Master Data...")
        self.lbl_status.setText("Đang chuẩn bị tiến trình tạo video tự động...")

        self._worker = VideoCreatorWorker(
            original_video_path=self.original_video_path,
            segments=self.segments,
            output_video_path=self.output_video_path,
            workspace_dir=self.workspace_dir,
            config=self.config,
            service=self._service,
            parent=self,
        )
        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.stage_changed.connect(self._on_stage_changed)
        self._worker.log_emitted.connect(self._on_log_emitted)
        self._worker.pipeline_finished.connect(self._on_pipeline_finished)
        self._worker.finished.connect(self._on_worker_thread_finished)
        self._worker.start()

    def _on_progress_updated(self, percent: float, message: str):
        self.lbl_status.setText(message)
        self.progress_bar.setValue(int(round(percent)))

    def _on_stage_changed(self, stage_key: str, stage_name: str):
        """Cập nhật các badge chỉ báo giai đoạn trên giao diện."""
        if stage_key in ("preflight", "mapping"):
            self.lbl_step2.setText(f"2. 🎙️ Lồng tiếng AI\n[{stage_name}]")
            self.lbl_step2.setStyleSheet("color: #ff7b1a; font-weight: bold; font-size: 11px;")
            self.lbl_step3.setText("3. 🎞️ Hòa âm & Xuất MP4\n[Chờ xử lý]")
            self.lbl_step3.setStyleSheet("color: #8b949e; font-weight: bold; font-size: 11px;")
        elif stage_key == "tts":
            self.lbl_step2.setText("2. 🎙️ Lồng tiếng AI\n[Đang thực hiện]")
            self.lbl_step2.setStyleSheet("color: #ff7b1a; font-weight: bold; font-size: 11px;")
            self.lbl_step3.setText("3. 🎞️ Hòa âm & Xuất MP4\n[Chờ xử lý]")
            self.lbl_step3.setStyleSheet("color: #8b949e; font-weight: bold; font-size: 11px;")
        elif stage_key in ("mixing", "export", "verification"):
            self.lbl_step2.setText("2. 🎙️ Lồng tiếng AI\n[✅ Đã xong]")
            self.lbl_step2.setStyleSheet("color: #22c55e; font-weight: bold; font-size: 11px;")
            self.lbl_step3.setText(f"3. 🎞️ Hòa âm & Xuất MP4\n[{stage_name}]")
            self.lbl_step3.setStyleSheet("color: #ff7b1a; font-weight: bold; font-size: 11px;")
        elif stage_key == "completed":
            self.lbl_step2.setText("2. 🎙️ Lồng tiếng AI\n[✅ Đã xong]")
            self.lbl_step2.setStyleSheet("color: #22c55e; font-weight: bold; font-size: 11px;")
            self.lbl_step3.setText("3. 🎞️ Hòa âm & Xuất MP4\n[✅ Đã xong]")
            self.lbl_step3.setStyleSheet("color: #22c55e; font-weight: bold; font-size: 11px;")

    def _on_log_emitted(self, log_line: str):
        self._append_log(log_line)

    def _on_pipeline_finished(self, result: VideoCreatorResult):
        """Xử lý trạng thái kết thúc terminal của pipeline (Step 9.4)."""
        self._ui_state = "TERMINAL"
        self._last_result = result
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setVisible(False)
        self.btn_close.setEnabled(True)

        if result.status == "success":
            self.output_mp4 = result.output_video_path
            self.progress_bar.setValue(100)
            self.lbl_status.setText("🎉 ĐÃ TẠO VIDEO THÀNH CÔNG!")
            self.lbl_status.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 13px;")

            self.lbl_step2.setText("2. 🎙️ Lồng tiếng AI\n[✅ Đã xong]")
            self.lbl_step2.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 11px;")
            self.lbl_step3.setText("3. 🎞️ Hòa âm & Xuất MP4\n[✅ Đã xong]")
            self.lbl_step3.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 11px;")

            self._append_log("\n" + "=" * 55)
            self._append_log("🎉 XUẤT BẢN VIDEO THÀNH CÔNG!")
            self._append_log(f"🎬 Video thành phẩm: {result.output_video_path}")
            if result.output_audio_path:
                self._append_log(f"🎵 Audio thành phẩm: {result.output_audio_path}")
            self._append_log("-" * 55)
            self._append_log("📊 BÁO CÁO THỐNG KÊ:")
            self._append_log(f"   • Thời lượng video thành phẩm: {result.final_video_duration:.2f}s")
            self._append_log(f"   • Thời lượng audio thành phẩm: {result.audio_duration:.2f}s")
            self._append_log(f"   • Tổng số câu: {result.total_segments}")
            self._append_log(f"   • Đã lồng tiếng AI: {result.tts_generated_count}")
            self._append_log(f"   • Không lồng tiếng AI: {result.tts_skipped_count}")
            self._append_log(f"   • Hiển thị phụ đề: {result.subtitles_rendered_count}")
            self._append_log(f"   • Không hiển thị phụ đề: {result.subtitles_skipped_count}")
            self._append_log("=" * 55)

            if result.warnings:
                self._append_log("\n⚠️ CẢNH BÁO HẬU KỲ (THÀNH PHẨM VẪN HỢP LỆ):")
                for w in result.warnings:
                    self._append_log(f"   • {w}")

            if result.output_video_path and os.path.isfile(result.output_video_path):
                self.btn_open_folder.setVisible(True)

        elif result.status == "cancelled":
            stage_info = f" ({result.cancelled_stage})" if result.cancelled_stage else ""
            self.lbl_status.setText(f"⏹️ TIẾN TRÌNH ĐÃ ĐƯỢC HỦY{stage_info.upper()}")
            self.lbl_status.setStyleSheet("color: #d29922; font-weight: bold; font-size: 12px;")
            self._append_log("\n" + "=" * 55)
            self._append_log("⏹️ TIẾN TRÌNH ĐÃ ĐƯỢC DỪNG AN TOÀN")
            if result.cancelled_stage:
                self._append_log(f"   • Giai đoạn dừng: {result.cancelled_stage}")
            if result.output_video_path and os.path.isfile(result.output_video_path):
                self.output_mp4 = result.output_video_path
                self.btn_open_folder.setVisible(True)
                self._append_log(f"   • Video hoàn thành trước khi hủy: {result.output_video_path}")
            if result.output_audio_path and os.path.isfile(result.output_audio_path):
                self._append_log(f"   • Audio hoàn thành trước khi hủy: {result.output_audio_path}")
            if result.session_dir:
                self._append_log(f"   • Thư mục session lưu giữ: {result.session_dir}")
            self._append_log("=" * 55)

        elif result.status == "failed":
            self.lbl_status.setText("❌ TIẾN TRÌNH THẤT BẠI")
            self.lbl_status.setStyleSheet("color: #f85149; font-weight: bold; font-size: 12px;")
            self._append_log("\n" + "=" * 55)
            self._append_log("❌ TIẾN TRÌNH THẤT BẠI")
            self._append_log(f"   • Chi tiết lỗi: {result.error}")
            if result.output_audio_path and os.path.isfile(result.output_audio_path):
                self._append_log(f"   • Audio trung gian bảo toàn: {result.output_audio_path}")
            if result.session_dir:
                self._append_log(f"   • Thư mục session lưu giữ: {result.session_dir}")
            self._append_log("=" * 55)
            QMessageBox.critical(self, "Lỗi tạo video", f"Tiến trình tạo video thất bại:\n\n{result.error}")

        else:
            # Xử lý phòng thủ trạng thái không xác định (R-07)
            self.lbl_status.setText("⚠️ TRẠNG THÁI TIẾN TRÌNH KHÔNG XÁC ĐỊNH")
            self.lbl_status.setStyleSheet("color: #d29922; font-weight: bold; font-size: 12px;")
            self._append_log(f"\n⚠️ Cảnh báo: Nhận kết quả với trạng thái không xác định: '{result.status}'")
            if result.error:
                self._append_log(f"   • Thông tin lỗi: {result.error}")

        # Non-blocking close check
        if self._close_requested:
            self.accept()

    def _on_worker_thread_finished(self):
        """Dọn dẹp tài nguyên worker khi luồng QThread kết thúc."""
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

    def _on_cancel_clicked(self):
        """Xử lý khi người dùng nhấn nút 'Hủy tiến trình' (Double-click guard)."""
        if self._ui_state == "CANCELLING":
            return

        if self._ui_state == "RUNNING":
            self._ui_state = "CANCELLING"
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Đang hủy...")
            self.lbl_status.setText("Đang yêu cầu dừng tiến trình tại checkpoint an toàn...")
            self._append_log("⏹️ Người dùng yêu cầu hủy tiến trình (đang chờ dừng tại checkpoint an toàn)...")

            if self._worker and self._worker.isRunning():
                self._worker.request_cancel()

    def closeEvent(self, event):
        """Xử lý sự kiện đóng cửa sổ an toàn, không block GUI thread."""
        if self._ui_state in ("RUNNING", "CANCELLING"):
            event.ignore()
            self._close_requested = True
            if self._ui_state == "RUNNING":
                self._on_cancel_clicked()
        else:
            event.accept()
            super().closeEvent(event)

    def _on_open_folder_clicked(self):
        if self.output_mp4 and os.path.isfile(self.output_mp4):
            folder = os.path.dirname(self.output_mp4)
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{os.path.normpath(self.output_mp4)}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", self.output_mp4])
            else:
                subprocess.Popen(["xdg-open", folder])
