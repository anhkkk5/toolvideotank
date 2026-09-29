"""
PipelineContext & VideoWorkspace — Core data models cho batch pipeline.

PipelineContext: chứa toàn bộ cấu hình cần thiết để chạy 1 pipeline mà KHÔNG
phụ thuộc vào GUI state. Thay vì pipeline đọc gui.get_xxx(), ta snapshot tất cả
settings vào PipelineContext trước khi chạy.

VideoWorkspace: đại diện cho 1 video trong batch, bao gồm cấu hình riêng,
trạng thái xử lý, progress, output.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PipelineContext:
    """Snapshot toàn bộ settings cần thiết để chạy 1 pipeline, tách khỏi GUI.

    Thay vì pipeline_controller.run_all_pipeline đọc:
        gui.get_audio_handling_mode()
        gui.get_transcription_engine()
        gui.get_source_language_code()
        ...
    thì mọi thứ được thu thập 1 lần vào PipelineContext.
    """

    # === Bắt buộc ===
    workspace_root: str = ""
    video_path: str = ""

    # === Engine / Ngôn ngữ ===
    transcription_engine: str = "ocr"       # "ocr" | "whisper" | "sensevoice"
    source_language: str = "zh"
    target_language: str = "vi"
    whisper_model_name: str = "medium"

    # === Xử lý âm thanh ===
    audio_handling_mode: str = "fast"       # "fast" | "clean"

    # === Dịch thuật ===
    ai_polish_enabled: bool = True
    skip_translation: bool = False
    ai_style_instruction: str = ""

    # === Nhận diện người nói ===
    speaker_diarization: bool = False
    speaker_diarization_num_speakers: int = -1

    # === Giọng đọc AI ===
    output_mode: str = "both"               # "voice" | "subtitle" | "both"
    voice_name: str = ""
    voice_speed: float = 1.0

    # === Pipeline target ===
    target_stage: str = "full"              # "full" | "transcript" | "translate" | "tts"

    # === Blur/OCR region ===
    blur_rect: Optional[tuple] = None       # (x, y, w, h) normalized
    ocr_rect: Optional[tuple] = None        # (x, y, w, h) normalized

    @classmethod
    def from_gui(cls, gui) -> "PipelineContext":
        """Snapshot toàn bộ settings từ GUI vào PipelineContext.

        Đây là điểm duy nhất đọc GUI state. Sau khi tạo xong PipelineContext,
        pipeline chạy hoàn toàn độc lập với GUI.
        """
        video_path = ""
        if hasattr(gui, "video_path_edit"):
            video_path = gui.video_path_edit.text().strip()
        if hasattr(gui, "_normalize_local_file_path"):
            video_path = gui._normalize_local_file_path(video_path)

        # Blur rect from OCR region
        blur_rect = None
        if hasattr(gui, "video_view") and hasattr(gui.video_view, "get_blur_region_normalized"):
            try:
                norm_blur = gui.video_view.get_blur_region_normalized()
                if isinstance(norm_blur, dict):
                    blur_rect = (
                        float(norm_blur.get("x", 0.0)),
                        float(norm_blur.get("y", 0.0)),
                        float(norm_blur.get("width", 0.0)),
                        float(norm_blur.get("height", 0.0)),
                    )
                elif isinstance(norm_blur, list) and norm_blur and isinstance(norm_blur[0], dict):
                    first = norm_blur[0]
                    blur_rect = (
                        float(first.get("x", 0.0)),
                        float(first.get("y", 0.0)),
                        float(first.get("width", 0.0)),
                        float(first.get("height", 0.0)),
                    )
            except Exception:
                blur_rect = None

        if not blur_rect:
            rect_env = os.getenv("OCR_SUBTITLE_RECT", "").strip()
            if rect_env:
                try:
                    parts = [float(p) for p in rect_env.split(",")]
                    if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
                        blur_rect = (parts[0], parts[1], parts[2], parts[3])
                except Exception:
                    pass

        return cls(
            workspace_root=getattr(gui, "workspace_root", ""),
            video_path=video_path,
            transcription_engine=(
                gui.get_transcription_engine()
                if hasattr(gui, "get_transcription_engine") else "ocr"
            ),
            source_language=(
                gui.get_source_language_code()
                if hasattr(gui, "get_source_language_code") else "zh"
            ),
            target_language=(
                gui.get_target_language_code()
                if hasattr(gui, "get_target_language_code") else "vi"
            ),
            whisper_model_name=(
                gui.get_whisper_model_name()
                if hasattr(gui, "get_whisper_model_name") else "medium"
            ),
            audio_handling_mode=(
                gui.get_audio_handling_mode()
                if hasattr(gui, "get_audio_handling_mode") else "fast"
            ),
            ai_polish_enabled=(
                gui.is_ai_polish_enabled()
                if hasattr(gui, "is_ai_polish_enabled") else True
            ),
            skip_translation=(
                gui.is_skip_translation()
                if hasattr(gui, "is_skip_translation") else False
            ),
            ai_style_instruction=(
                gui.get_ai_style_instruction()
                if hasattr(gui, "get_ai_style_instruction") else ""
            ),
            speaker_diarization=(
                gui.is_speaker_diarization_enabled()
                if hasattr(gui, "is_speaker_diarization_enabled") else False
            ),
            speaker_diarization_num_speakers=(
                gui.get_speaker_diarization_num_speakers()
                if hasattr(gui, "get_speaker_diarization_num_speakers") else -1
            ),
            output_mode=(
                gui.get_output_mode_key()
                if hasattr(gui, "get_output_mode_key") else "both"
            ),
            voice_name=(
                gui.get_active_voice_name()
                if hasattr(gui, "get_active_voice_name") else ""
            ),
            voice_speed=(
                gui._parse_voice_speed_value()
                if hasattr(gui, "_parse_voice_speed_value") else 1.0
            ),
            blur_rect=blur_rect,
            ocr_rect=blur_rect,
        )

    @classmethod
    def from_workspace(cls, workspace: "VideoWorkspace", defaults: Optional["PipelineContext"] = None) -> "PipelineContext":
        """Tạo PipelineContext từ VideoWorkspace.

        Nếu workspace có override cấu hình riêng, dùng nó.
        Nếu không, dùng defaults (thường là PipelineContext.from_gui).
        """
        base = defaults or cls()
        # Cấu hình OCR rect riêng của workspace:
        # 1. Nếu workspace có ocr_rect riêng -> dùng nó.
        # 2. Nếu base thuộc cùng video_path đang mở -> kế thừa từ base.
        # 3. Nếu là video khác -> để None để worker tự tính default theo kích thước video đó.
        ws_ocr = getattr(workspace, "ocr_rect", None) or getattr(workspace, "blur_rect", None)
        if not ws_ocr and base.video_path and os.path.normpath(base.video_path) == os.path.normpath(workspace.video_path):
            ws_ocr = getattr(base, "ocr_rect", None) or base.blur_rect

        return cls(
            workspace_root=base.workspace_root,
            video_path=workspace.video_path,
            transcription_engine=workspace.transcription_engine or base.transcription_engine,
            source_language=workspace.source_language or base.source_language,
            target_language=workspace.target_language or base.target_language,
            whisper_model_name=workspace.whisper_model_name or base.whisper_model_name,
            audio_handling_mode=workspace.audio_handling_mode or base.audio_handling_mode,
            ai_polish_enabled=base.ai_polish_enabled,
            skip_translation=base.skip_translation,
            ai_style_instruction=base.ai_style_instruction,
            speaker_diarization=base.speaker_diarization,
            speaker_diarization_num_speakers=base.speaker_diarization_num_speakers,
            output_mode=workspace.output_mode or base.output_mode,
            voice_name=workspace.voice_name or base.voice_name,
            voice_speed=workspace.voice_speed if workspace.voice_speed != 1.0 else base.voice_speed,
            target_stage=base.target_stage,
            blur_rect=ws_ocr,
            ocr_rect=ws_ocr,
        )

    def validate(self) -> str:
        """Trả về chuỗi lỗi nếu config không hợp lệ, hoặc chuỗi rỗng nếu OK."""
        if not self.video_path or not os.path.isfile(self.video_path):
            return f"Video không tồn tại: {self.video_path}"
        if not self.workspace_root:
            return "workspace_root chưa được cấu hình"
        return ""


@dataclass
class VideoWorkspace:
    """Đại diện cho 1 dự án video độc lập trong batch.

    Mỗi video có workspace riêng: cấu hình, trạng thái, progress, output, error.
    """

    # === Nhận diện ===
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    video_path: str = ""
    video_name: str = ""
    thumb_path: str = ""
    duration_s: float = 0.0

    # === Override cấu hình (rỗng = dùng defaults chung) ===
    transcription_engine: str = ""          # "" = dùng default
    source_language: str = ""
    target_language: str = ""
    whisper_model_name: str = ""
    audio_handling_mode: str = ""
    output_mode: str = ""
    voice_name: str = ""
    voice_speed: float = 1.0
    blur_rect: Optional[tuple] = None
    ocr_rect: Optional[tuple] = None        # (x, y, w, h) normalized riêng từng video

    # === Trạng thái xử lý ===
    status: str = "pending"                 # pending | queued | running | done | error | cancelled
    progress: float = 0.0                   # 0.0 → 1.0
    current_step: str = ""                  # "" | "extract_audio" | "transcription" | "translation" | "voiceover" | "preview"
    error_message: str = ""
    output_path: str = ""                   # Video kết quả
    project_state_path: str = ""            # Đường dẫn project state JSON

    # === Retry ===
    retry_count: int = 0
    max_retries: int = 2

    # === Thời gian ===
    queued_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0

    @classmethod
    def from_video_path(cls, video_path: str, thumb_dir: str = "") -> "VideoWorkspace":
        """Tạo VideoWorkspace từ đường dẫn video.

        Tự động probe duration và tạo thumbnail nếu có thumb_dir.
        """
        video_path = os.path.abspath(video_path)
        video_name = os.path.basename(video_path)
        dur_s = 0.0
        thumb = ""

        if thumb_dir:
            try:
                from utils.media_utils import probe_video_duration_and_thumb
                dur_s, thumb = probe_video_duration_and_thumb(video_path, thumb_dir)
            except Exception:
                pass

        # Thử đọc ocr_rect từ project state đã lưu nếu có
        ocr_rect = None
        try:
            import hashlib, json, re
            from runtime_paths import workspace_root
            proj_root = os.path.join(workspace_root(), "projects")
            video_stem = os.path.splitext(video_name)[0] or "project"
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", video_stem).strip("_").lower() or "project"
            digest = hashlib.sha1(os.path.abspath(video_path).encode("utf-8")).hexdigest()[:8]
            state_file = os.path.join(proj_root, f"{slug}_{digest}", "project.json")
            if os.path.isfile(state_file):
                with open(state_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                    s_rect = s_data.get("settings", {}).get("ocr_subtitle_rect", "")
                    if s_rect:
                        parts = [float(x) for x in s_rect.split(",")]
                        if len(parts) == 4:
                            ocr_rect = tuple(parts)
        except Exception:
            pass

        return cls(
            video_path=video_path,
            video_name=video_name,
            thumb_path=thumb,
            duration_s=dur_s,
            ocr_rect=ocr_rect,
            blur_rect=ocr_rect,
        )

    def mark_queued(self):
        self.status = "queued"
        self.queued_at = time.time()
        self.error_message = ""

    def mark_running(self, step: str = ""):
        self.status = "running"
        self.started_at = time.time()
        self.current_step = step

    def mark_done(self, output_path: str = ""):
        self.status = "done"
        self.finished_at = time.time()
        self.progress = 1.0
        self.current_step = ""
        self.output_path = output_path

    def mark_error(self, message: str):
        self.status = "error"
        self.finished_at = time.time()
        self.current_step = ""
        self.error_message = message

    def mark_cancelled(self):
        self.status = "cancelled"
        self.finished_at = time.time()
        self.current_step = ""

    def can_retry(self) -> bool:
        return self.status == "error" and self.retry_count < self.max_retries

    def prepare_retry(self):
        if not self.can_retry():
            return False
        self.retry_count += 1
        self.status = "pending"
        self.progress = 0.0
        self.current_step = ""
        self.error_message = ""
        return True

    def to_dict(self) -> dict:
        """Serialize cho JSON save/load."""
        return {
            "id": self.id,
            "video_path": self.video_path,
            "video_name": self.video_name,
            "thumb_path": self.thumb_path,
            "duration_s": self.duration_s,
            "transcription_engine": self.transcription_engine,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "whisper_model_name": self.whisper_model_name,
            "audio_handling_mode": self.audio_handling_mode,
            "output_mode": self.output_mode,
            "voice_name": self.voice_name,
            "voice_speed": self.voice_speed,
            "blur_rect": self.blur_rect,
            "ocr_rect": self.ocr_rect,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "error_message": self.error_message,
            "output_path": self.output_path,
            "project_state_path": self.project_state_path,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VideoWorkspace":
        """Deserialize từ dict."""
        ws = cls()
        for key, val in data.items():
            if hasattr(ws, key):
                try:
                    setattr(ws, key, val)
                except Exception:
                    pass
        return ws
