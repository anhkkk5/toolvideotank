"""Single Voice Pipeline Progress Dialog and Background Worker.

Executes the full 1-voice automated workflow:
1. Video OCR Subtitle Extraction.
2. DeepSeek AI Contextual Translation.
3. 1-Voice Neural TTS Synthesis with Duration Fitting.
4. Video Rendering with Chinese Blur Mask + Vietnamese Subtitles + Audio Ducking.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
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

from app.models.subtitle_segment import SubtitleSegment
from app.services.video_creator_service import (
    VideoCreatorConfig,
    VideoCreatorRequest,
    VideoCreatorResult,
    VideoCreatorService,
)
from app.services.video_export_service import SubtitleRenderConfig
from app.services.voice_mapping_service import VoiceMappingConfig


class SingleVoicePipelineWorker(QThread):
    """QThread worker chạy toàn bộ quy trình 1 giọng không làm đơ giao diện."""

    progress_updated = Signal(float, str)
    stage_changed = Signal(str, str)
    log_emitted = Signal(str)
    pipeline_finished = Signal(object, list)  # (VideoCreatorResult, translated_cues)
    pipeline_error = Signal(str)

    def __init__(
        self,
        *,
        workspace_root: str,
        video_path: str,
        selected_voice: dict[str, str],
        audio_mix_settings: dict[str, float],
        enable_blur_mask: bool,
        blur_rect: tuple[float, float, float, float] | None,
        burn_subtitles: bool,
        existing_cues: list[dict[str, Any]] | None,
        output_video_path: str,
        subtitle_config: SubtitleRenderConfig | None = None,
        brand_logo_settings: dict[str, Any] | None = None,
        watermark_settings: dict[str, Any] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.workspace_root = workspace_root
        self.video_path = video_path
        self.selected_voice = selected_voice
        self.audio_mix_settings = audio_mix_settings
        self.enable_blur_mask = enable_blur_mask
        self.blur_rect = blur_rect
        self.burn_subtitles = burn_subtitles
        self.existing_cues = existing_cues
        self.output_video_path = output_video_path
        self.subtitle_config = subtitle_config or SubtitleRenderConfig()
        self.brand_logo_settings = brand_logo_settings or {}
        self.watermark_settings = watermark_settings or {}

        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self):
        try:
            self._execute_pipeline()
        except Exception as exc:
            trace_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
            print(f"[SingleVoicePipelineWorker] Error:\n{trace_str}")
            self.pipeline_error.emit(str(exc))

    def _execute_pipeline(self):
        # --- BƯỚC 1: QUÉT OCR PHỤ ĐỀ (0% -> 25%) ---
        self.stage_changed.emit("ocr", "Đang quét phụ đề video (OCR)...")
        self.progress_updated.emit(5.0, "Đang quét phụ đề video...")

        cues: list[dict[str, Any]] = []
        if self.existing_cues and len(self.existing_cues) > 0 and any(str(c.get("text", "")).strip() for c in self.existing_cues):
            cues = [dict(c) for c in self.existing_cues if str(c.get("text", "")).strip()]
            self.log_emitted.emit(f"[OCR] Tái sử dụng {len(cues)} câu phụ đề đã nhận diện trên giao diện.")
        else:
            self.log_emitted.emit(f"[OCR] Bắt đầu quét OCR từ video: {os.path.basename(self.video_path)}")
            from services.engine_runtime import EngineRuntime
            from services.subtitle_merge_service import SubtitleMergeService

            engine = EngineRuntime()
            region = str(os.getenv("OCR_SUBTITLE_REGION", "bottom") or "bottom")
            raw_cues = list(engine.transcribe_video_ocr(self.video_path, region=region) or [])
            self.log_emitted.emit(f"[OCR] Quét thô hoàn tất, tìm thấy {len(raw_cues)} đoạn text.")
            cues = SubtitleMergeService.merge_cues([dict(c) for c in raw_cues if str(c.get("text", "")).strip()])

        if self._cancel_event.is_set():
            return

        if not cues:
            raise RuntimeError(
                "Không đọc được phụ đề từ video. Vui lòng kiểm tra lại khung OCR trên màn hình xem video."
            )

        self.log_emitted.emit(f"[OCR] Đã chuẩn hóa {len(cues)} câu thoại hợp lệ.")
        self.progress_updated.emit(25.0, f"Đã quét xong {len(cues)} câu phụ đề.")

        # --- BƯỚC 2: DỊCH PHỤ ĐỀ BẰNG DEEPSEEK AI (25% -> 45%) ---
        self.stage_changed.emit("translate", "Đang dịch kịch bản chuẩn ngữ cảnh (DeepSeek AI)...")
        deepseek_key = str(os.getenv("DEEPSEEK_API_KEY", "")).strip()
        from services.subtitle_translation_service import SubtitleTranslationService

        # Đánh số ID cho các câu
        indexed_cues = [
            {**cue, "id": cue.get("id", idx)}
            for idx, cue in enumerate(cues, start=1)
        ]

        translated_cues: list[dict[str, Any]] = []
        if deepseek_key:
            try:
                from services.deepseek_service import DeepSeekService
                ds_svc = DeepSeekService(api_key=deepseek_key)
                sub_trans_svc = SubtitleTranslationService(ds_svc)
                self.log_emitted.emit("[Dịch thuật] Đang kết nối DeepSeek AI API để dịch theo văn cảnh...")

                def _on_ds_progress(msg, cur, tot):
                    if tot > 0:
                        pct = 25.0 + (cur / tot) * 20.0
                        self.progress_updated.emit(pct, f"DeepSeek AI đang dịch ({cur}/{tot})...")
                    self.log_emitted.emit(f"[DeepSeek] {msg}")

                translated_cues, _ = sub_trans_svc.translate_with_deepseek(
                    indexed_cues,
                    overwrite_manual=True,
                    progress=_on_ds_progress,
                )
                self.log_emitted.emit(f"[Dịch thuật] DeepSeek AI đã dịch thành công {len(translated_cues)} câu.")
            except Exception as ds_err:
                self.log_emitted.emit(f"[Dịch thuật] DeepSeek AI thông báo: {ds_err}. Chuyển sang bộ dịch dự phòng...")
                translated_cues = []

        if self._cancel_event.is_set():
            return

        if not translated_cues:
            self.log_emitted.emit("[Dịch thuật] Đang dịch bằng bộ dịch dự phòng...")
            translated_cues = SubtitleTranslationService().translate_cues(
                indexed_cues,
                target_lang="vi",
                progress=lambda msg: self.log_emitted.emit(f"[Dịch thuật] {msg}"),
            )

        self.progress_updated.emit(45.0, "Dịch thuật kịch bản hoàn tất.")

        # --- BƯỚC 3 & 4: TẠO GIỌNG ĐỌC AI & XUẤT VIDEO (45% -> 100%) ---
        self.stage_changed.emit("render", "Đang lồng tiếng AI, che chữ Trung và xuất video MP4...")
        voice_id = str(self.selected_voice.get("id", "adam1")).strip()
        voice_name = str(self.selected_voice.get("name", voice_id)).strip()
        self.log_emitted.emit(f"[Lồng tiếng] Áp dụng giọng thuyết minh: {voice_name} (ID: {voice_id})")

        segments: list[SubtitleSegment] = []
        for idx, cue in enumerate(translated_cues, start=1):
            start_s = float(cue.get("start", 0.0) or 0.0)
            end_s = float(cue.get("end", 0.0) or 0.0)
            txt = str(cue.get("translated_text", "") or cue.get("text", "")).strip()
            if not txt:
                continue

            seg = SubtitleSegment(
                id=idx,
                start=start_s,
                end=end_s,
                text=str(cue.get("text", "") or txt),
                translated_text=txt,
                voice_id=voice_id,
                voice_name=voice_name,
                gender="male",
                final_gender="male",
            )
            segments.append(seg)

        creator_config = VideoCreatorConfig()
        creator_config.enable_blur_mask = self.enable_blur_mask
        creator_config.blur_rect = self.blur_rect
        creator_config.burn_subtitles = self.burn_subtitles
        creator_config.subtitle_config = self.subtitle_config
        creator_config.original_volume = float(self.audio_mix_settings.get("original_volume", 0.50))
        creator_config.tts_volume = float(self.audio_mix_settings.get("tts_volume", 1.00))
        creator_config.duck_volume = float(self.audio_mix_settings.get("duck_volume", 0.20))

        # Cấu hình Logo Thương hiệu
        if self.brand_logo_settings and isinstance(self.brand_logo_settings, dict):
            creator_config.enable_brand_logo = bool(self.brand_logo_settings.get("enable", False))
            creator_config.brand_logo_path = str(self.brand_logo_settings.get("path", "")).strip()
            creator_config.brand_logo_position = str(self.brand_logo_settings.get("position", "top_left"))
            creator_config.brand_logo_size_percent = int(self.brand_logo_settings.get("size_percent", 15))
            creator_config.brand_logo_opacity = float(self.brand_logo_settings.get("opacity", 1.0))

        # Cấu hình Hình mờ chữ Watermark
        if self.watermark_settings and isinstance(self.watermark_settings, dict):
            creator_config.enable_watermark = bool(self.watermark_settings.get("enable", False))
            creator_config.watermark_text = str(self.watermark_settings.get("text", "")).strip()
            creator_config.watermark_position = str(self.watermark_settings.get("position", "center"))
            creator_config.watermark_font_size = int(self.watermark_settings.get("font_size", 36))
            creator_config.watermark_opacity = float(self.watermark_settings.get("opacity", 0.35))
            creator_config.watermark_color = str(self.watermark_settings.get("color", "#FFFFFF"))

        # Khóa cứng toàn bộ các vai về đúng 1 giọng đã chọn
        from app.services.voice_mapping_service import VoiceAssignment, VoiceMappingConfig
        single_va = VoiceAssignment(
            voice_id=voice_id,
            name=voice_name,
            provider=str(self.selected_voice.get("provider", "piper")),
            gender="male",
            speed=1.0,
        )
        vm_config = VoiceMappingConfig(
            default_male_voice=single_va,
            default_female_voice=single_va,
            fallback_voice=single_va,
        )
        creator_config.voice_config = vm_config


        def _on_creator_progress(raw_pct: float, message: str):
            scaled = 45.0 + (raw_pct * 0.55)
            self.progress_updated.emit(scaled, message)
            self.log_emitted.emit(f"[Tạo video] {message}")

        request = VideoCreatorRequest(
            original_video_path=self.video_path,
            segments=segments,
            output_video_path=self.output_video_path,
            config=creator_config,
            progress_callback=_on_creator_progress,
            is_cancelled_func=lambda: self._cancel_event.is_set(),
        )

        service = VideoCreatorService()
        result = service.run(request)

        if getattr(result, "status", "") == "failed":
            raise RuntimeError(getattr(result, "error", "") or "Quá trình xuất video thất bại.")

        if self._cancel_event.is_set():
            return

        self.progress_updated.emit(100.0, "Hoàn tất tạo video thành công!")
        self.pipeline_finished.emit(result, translated_cues)


class SingleVoiceProgressDialog(QDialog):
    """Hộp thoại trực quan hiển thị toàn bộ 4 bước tạo video 1 giọng."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        workspace_root: str = "",
        video_path: str = "",
        selected_voice: dict[str, str],
        audio_mix_settings: dict[str, float],
        enable_blur_mask: bool = True,
        blur_rect: tuple[float, float, float, float] | None = None,
        burn_subtitles: bool = True,
        existing_cues: list[dict[str, Any]] | None = None,
        output_video_path: str = "",
        subtitle_config: SubtitleRenderConfig | None = None,
        brand_logo_settings: dict[str, Any] | None = None,
        watermark_settings: dict[str, Any] | None = None,
    ):
        super().__init__(parent)
        self.workspace_root = workspace_root
        self.video_path = video_path
        self.selected_voice = selected_voice
        self.audio_mix_settings = audio_mix_settings
        self.enable_blur_mask = enable_blur_mask
        self.blur_rect = blur_rect
        self.burn_subtitles = burn_subtitles
        self.existing_cues = existing_cues
        self.output_video_path = output_video_path
        self.subtitle_config = subtitle_config or SubtitleRenderConfig()
        self.brand_logo_settings = brand_logo_settings or {}
        self.watermark_settings = watermark_settings or {}

        self._worker: SingleVoicePipelineWorker | None = None
        self._last_result: VideoCreatorResult | None = None
        self._translated_cues: list[dict[str, Any]] = []

        self.setWindowTitle("Tiến trình tạo video (1 giọng) - Toàn bộ quy trình")
        self.resize(750, 520)
        self.setMinimumSize(650, 450)

        self._setup_ui()
        self._apply_dark_style()
        self._start_worker()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)

        # Header Title
        header_title = QLabel("⚡ TIẾN TRÌNH TẠO VIDEO (1 GIỌNG) - TANKVIDEO")
        h_font = QFont()
        h_font.setPointSize(12)
        h_font.setBold(True)
        header_title.setFont(h_font)
        header_title.setStyleSheet("color: #ff7b1a;")
        root_layout.addWidget(header_title)

        video_name = os.path.basename(self.video_path) if self.video_path else "Video"
        v_name = self.selected_voice.get("name", "Mặc định")
        lbl_info = QLabel(f"🎥 Video: {video_name} | 🎙️ Giọng thuyết minh: {v_name}")
        lbl_info.setStyleSheet("color: #8b949e; font-size: 11px;")
        root_layout.addWidget(lbl_info)

        # 3 Step Visual Indicators
        steps_frame = QFrame()
        steps_frame.setStyleSheet("background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 6px;")
        steps_layout = QHBoxLayout(steps_frame)
        steps_layout.setContentsMargins(10, 8, 10, 8)

        self.lbl_step1 = QLabel("1. 📄 Quét OCR & DeepSeek\n[Đang chạy...]")
        self.lbl_step1.setStyleSheet("color: #ff7b1a; font-weight: bold; font-size: 11px;")
        self.lbl_step1.setAlignment(Qt.AlignCenter)

        self.lbl_step2 = QLabel("2. 🎙️ Lồng tiếng AI (1 giọng)\n[Chờ xử lý]")
        self.lbl_step2.setStyleSheet("color: #8b949e; font-weight: bold; font-size: 11px;")
        self.lbl_step2.setAlignment(Qt.AlignCenter)

        self.lbl_step3 = QLabel("3. 🎞️ Che chữ & Xuất MP4\n[Chờ xử lý]")
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
            QDialog { background-color: #121316; color: #e6edf3; }
            QLabel { background-color: transparent; }
            QPushButton {
                background-color: #21262d; color: #e6edf3; border: 1px solid #30363d;
                border-radius: 6px; padding: 6px 14px; font-weight: 600;
            }
            QPushButton:hover { background-color: #30363d; }
            QPushButton#primaryBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6a00, stop:1 #e04800);
                color: #ffffff; border: 1px solid #ff8833;
            }
        """)

    def _start_worker(self):
        self._worker = SingleVoicePipelineWorker(
            workspace_root=self.workspace_root,
            video_path=self.video_path,
            selected_voice=self.selected_voice,
            audio_mix_settings=self.audio_mix_settings,
            enable_blur_mask=self.enable_blur_mask,
            blur_rect=self.blur_rect,
            burn_subtitles=self.burn_subtitles,
            existing_cues=self.existing_cues,
            output_video_path=self.output_video_path,
            subtitle_config=self.subtitle_config,
            brand_logo_settings=self.brand_logo_settings,
            watermark_settings=self.watermark_settings,
            parent=self,
        )

        self._worker.progress_updated.connect(self._on_progress_updated)
        self._worker.stage_changed.connect(self._on_stage_changed)
        self._worker.log_emitted.connect(self._on_log_emitted)
        self._worker.pipeline_finished.connect(self._on_pipeline_finished)
        self._worker.pipeline_error.connect(self._on_pipeline_error)

        self._worker.start()

    def _on_progress_updated(self, pct: float, message: str):
        val = max(0, min(100, int(round(pct))))
        self.progress_bar.setValue(val)
        self.lbl_status.setText(f"{message} ({val}%)")

    def _on_stage_changed(self, stage: str, message: str):
        if stage == "ocr":
            self.lbl_step1.setText("1. 📄 Quét phụ đề OCR\n[🔄 Đang chạy]")
            self.lbl_step1.setStyleSheet("color: #ff7b1a; font-weight: bold; font-size: 11px;")
        elif stage == "translate":
            self.lbl_step1.setText("1. 📄 Dịch DeepSeek AI\n[🔄 Đang dịch]")
            self.lbl_step1.setStyleSheet("color: #ff7b1a; font-weight: bold; font-size: 11px;")
        elif stage == "render":
            self.lbl_step1.setText("1. 📄 OCR & DeepSeek\n[✅ Đã xong]")
            self.lbl_step1.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 11px;")
            self.lbl_step2.setText("2. 🎙️ Lồng tiếng AI (1 giọng)\n[🔄 Đang tạo]")
            self.lbl_step2.setStyleSheet("color: #ff7b1a; font-weight: bold; font-size: 11px;")
            self.lbl_step3.setText("3. 🎞️ Che chữ & Xuất MP4\n[🔄 Đang xử lý]")
            self.lbl_step3.setStyleSheet("color: #ff7b1a; font-weight: bold; font-size: 11px;")

    def _on_log_emitted(self, msg: str):
        self.log_box.append(msg)

    def _on_pipeline_finished(self, result: VideoCreatorResult, translated_cues: list):
        self._last_result = result
        self._translated_cues = translated_cues

        self.lbl_step1.setText("1. 📄 OCR & DeepSeek\n[✅ Xong]")
        self.lbl_step1.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 11px;")
        self.lbl_step2.setText("2. 🎙️ Lồng tiếng AI (1 giọng)\n[✅ Xong]")
        self.lbl_step2.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 11px;")
        self.lbl_step3.setText("3. 🎞️ Che chữ & Xuất MP4\n[✅ Hoàn thành]")
        self.lbl_step3.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 11px;")

        self.progress_bar.setValue(100)
        self.lbl_status.setText("🎉 Đã tạo video thành công!")
        self.lbl_status.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 13px;")

        self.btn_cancel.setVisible(False)
        self.btn_open_folder.setVisible(True)
        self.btn_close.setEnabled(True)

    def _on_pipeline_error(self, err_msg: str):
        self.lbl_status.setText(f"❌ Thất bại: {err_msg}")
        self.lbl_status.setStyleSheet("color: #f85149; font-weight: bold; font-size: 12px;")
        self.btn_cancel.setVisible(False)
        self.btn_close.setEnabled(True)
        QMessageBox.critical(self, "Lỗi tạo video", f"Không thể hoàn thành quy trình tạo video:\n\n{err_msg}")

    def _on_cancel_clicked(self):
        if self._worker and self._worker.isRunning():
            ans = QMessageBox.question(
                self,
                "Hủy tiến trình",
                "Bạn có chắc muốn hủy tiến trình tạo video này không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ans == QMessageBox.Yes:
                self.lbl_status.setText("Đang yêu cầu hủy...")
                self._worker.request_cancel()
                self._worker.wait(2000)
                self.reject()

    def _on_open_folder_clicked(self):
        out_path = self.output_video_path
        if self._last_result and getattr(self._last_result, "output_video_path", ""):
            out_path = self._last_result.output_video_path

        target_dir = os.path.dirname(os.path.abspath(out_path)) if out_path else os.getcwd()
        try:
            if os.name == "nt":
                if os.path.isfile(out_path):
                    subprocess.run(["explorer", "/select,", os.path.abspath(out_path)])
                else:
                    os.startfile(target_dir)
        except Exception as exc:
            QMessageBox.warning(self, "Lỗi mở thư mục", str(exc))
