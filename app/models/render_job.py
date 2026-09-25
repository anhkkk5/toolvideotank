"""RenderJob architecture for managing the lifecycle of Pipeline B video creation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Literal

from app.models.master_dataset import MasterDataset
from app.models.subtitle_segment import SubtitleSegment
from app.services.voice_mapping_service import (
    VoiceAssignment,
    VoiceMappingConfig,
    VoiceMappingService,
)

TTSSegmentStatus = Literal["pending", "generating", "completed", "failed", "skipped"]
JobStatus = Literal[
    "created",
    "tts_running",
    "tts_completed",
    "mixing",
    "exporting",
    "completed",
    "failed",
]


@dataclass
class TTSSegmentResult:
    """Kết quả sinh giọng TTS của một câu phụ đề cụ thể."""
    segment_id: int
    status: TTSSegmentStatus = "pending"
    voice_id: str = ""
    voice_name: str = ""
    provider: str = ""
    audio_file: str = ""
    raw_duration: float = 0.0
    slot_duration: float = 0.0
    fitted_speed: float = 1.0
    fitted_duration: float = 0.0
    warning: str = ""
    error: str = ""
    retry_count: int = 0
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TTSSegmentResult:
        return cls(
            segment_id=int(data.get("segment_id", 0)),
            status=str(data.get("status", "pending")),
            voice_id=str(data.get("voice_id", "") or ""),
            voice_name=str(data.get("voice_name", "") or ""),
            provider=str(data.get("provider", "") or ""),
            audio_file=str(data.get("audio_file", "") or ""),
            raw_duration=float(data.get("raw_duration", 0.0) or 0.0),
            slot_duration=float(data.get("slot_duration", 0.0) or 0.0),
            fitted_speed=float(data.get("fitted_speed", 1.0) or 1.0),
            fitted_duration=float(data.get("fitted_duration", 0.0) or 0.0),
            warning=str(data.get("warning", "") or ""),
            error=str(data.get("error", "") or ""),
            retry_count=int(data.get("retry_count", 0) or 0),
            updated_at=str(data.get("updated_at", "") or ""),
        )


@dataclass
class AudioTimelineBlock:
    """Đoạn âm thanh TTS thực tế được xếp vào timeline video.

    Tuân thủ Nguyên tắc 4: audio ducking chỉ áp dụng cho các block này.
    """
    segment_id: int
    start_time: float
    end_time: float
    audio_file: str
    volume: float = 1.0
    is_duck_trigger: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioTimelineBlock:
        return cls(
            segment_id=int(data.get("segment_id", 0)),
            start_time=float(data.get("start_time", 0.0) or 0.0),
            end_time=float(data.get("end_time", 0.0) or 0.0),
            audio_file=str(data.get("audio_file", "") or ""),
            volume=float(data.get("volume", 1.0) or 1.0),
            is_duck_trigger=bool(data.get("is_duck_trigger", True)),
        )


@dataclass
class RenderJob:
    """Quản lý toàn bộ vòng đời và dữ liệu của một tiến trình tạo video (Pipeline B).

    Hỗ trợ resume, retry từng câu lỗi mà không phải render lại từ đầu.
    """
    id: str
    job_dir: str
    master_dataset: MasterDataset
    voice_config: VoiceMappingConfig
    created_at: str = ""
    updated_at: str = ""
    status: JobStatus = "created"
    progress_percent: float = 0.0
    current_step_description: str = ""
    tts_results: dict[int, TTSSegmentResult] = field(default_factory=dict)
    audio_timeline: list[AudioTimelineBlock] = field(default_factory=list)
    subtitle_file: str = ""
    output_video_file: str = ""
    error_message: str = ""

    def __post_init__(self):
        now_str = datetime.now().astimezone().isoformat(timespec="seconds")
        if not self.created_at:
            self.created_at = now_str
        if not self.updated_at:
            self.updated_at = now_str
        os.makedirs(self.job_dir, exist_ok=True)

    @classmethod
    def create(
        cls,
        master_dataset: MasterDataset,
        workspace_root: str,
        voice_config: VoiceMappingConfig | None = None,
        job_id: str = "",
    ) -> RenderJob:
        """Khởi tạo một RenderJob mới từ MasterDataset và ánh xạ giọng đọc."""
        from uuid import uuid4

        actual_id = job_id or uuid4().hex[:12]
        job_dir = os.path.join(workspace_root, "render_jobs", actual_id)
        os.makedirs(job_dir, exist_ok=True)

        cfg = voice_config or VoiceMappingConfig()
        voice_mapper = VoiceMappingService(cfg)
        voice_assignments = voice_mapper.map_dataset(master_dataset)

        tts_results: dict[int, TTSSegmentResult] = {}
        for seg in master_dataset.segments:
            slot_dur = max(0.1, round(seg.end - seg.start, 3))
            voice = voice_assignments.get(seg.id)
            if voice is not None:
                # Câu cần lồng tiếng TTS
                tts_results[seg.id] = TTSSegmentResult(
                    segment_id=seg.id,
                    status="pending",
                    voice_id=voice.voice_id,
                    voice_name=voice.name,
                    provider=voice.provider,
                    slot_duration=slot_dur,
                )
            else:
                # Câu bỏ qua TTS (unknown, none, noise, untranslated) -> Tuân thủ nguyên tắc 2
                tts_results[seg.id] = TTSSegmentResult(
                    segment_id=seg.id,
                    status="skipped",
                    slot_duration=slot_dur,
                    warning="Bỏ qua TTS (unknown/none/không thoại/chưa dịch)",
                )

        job = cls(
            id=actual_id,
            job_dir=job_dir,
            master_dataset=master_dataset,
            voice_config=cfg,
            tts_results=tts_results,
            status="created",
            current_step_description="Khởi tạo RenderJob thành công",
        )
        job.save_to_disk()
        return job

    def get_pending_or_failed_tts_segments(self) -> list[SubtitleSegment]:
        """Lấy danh sách các câu cần sinh âm thanh TTS (đang pending hoặc bị lỗi cần retry)."""
        needed: list[SubtitleSegment] = []
        for seg in self.master_dataset.segments:
            res = self.tts_results.get(seg.id)
            if res and res.status in ("pending", "failed"):
                needed.append(seg)
        return needed

    def update_tts_result(self, result: TTSSegmentResult):
        """Cập nhật trạng thái và kết quả sinh âm thanh của một câu."""
        result.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.tts_results[result.segment_id] = result
        self.updated_at = result.updated_at

        # Tính toán lại % tiến độ tổng quát của giai đoạn TTS
        total_tts = sum(1 for r in self.tts_results.values() if r.status != "skipped")
        if total_tts > 0:
            done_tts = sum(1 for r in self.tts_results.values() if r.status == "completed")
            self.progress_percent = round((done_tts / total_tts) * 60.0, 1)  # 0% - 60% cho TTS

    def is_tts_fully_completed(self) -> bool:
        """Kiểm tra xem toàn bộ các câu cần TTS đã hoàn thành thành công hay chưa."""
        for r in self.tts_results.values():
            if r.status in ("pending", "failed", "generating"):
                return False
        return True

    def get_active_tts_timeline_blocks(self) -> list[AudioTimelineBlock]:
        """Tổng hợp danh sách các block audio TTS thực tế phục vụ Ducking & Mixing.

        Tuân thủ Nguyên tắc 4: Chỉ những câu completed và có audio_file thực tế mới có block.
        """
        blocks: list[AudioTimelineBlock] = []
        for seg in self.master_dataset.segments:
            res = self.tts_results.get(seg.id)
            if res and res.status == "completed" and res.audio_file and os.path.isfile(res.audio_file):
                actual_dur = res.fitted_duration or res.raw_duration or res.slot_duration
                block = AudioTimelineBlock(
                    segment_id=seg.id,
                    start_time=seg.start,
                    end_time=round(seg.start + actual_dur, 3),
                    audio_file=res.audio_file,
                    is_duck_trigger=True,
                )
                blocks.append(block)
        return blocks

    def save_to_disk(self) -> str:
        """Lưu trạng thái của job ra tệp render_job.json."""
        self.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        file_path = os.path.join(self.job_dir, "render_job.json")
        temp_file = file_path + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(temp_file, file_path)
        return file_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_dir": self.job_dir,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "current_step_description": self.current_step_description,
            "subtitle_file": self.subtitle_file,
            "output_video_file": self.output_video_file,
            "error_message": self.error_message,
            "master_dataset": self.master_dataset.to_dict(),
            "voice_config": self.voice_config.to_dict(),
            "tts_results": {str(k): v.to_dict() for k, v in self.tts_results.items()},
            "audio_timeline": [b.to_dict() for b in self.audio_timeline],
        }

    @classmethod
    def load_from_disk(cls, job_dir: str) -> RenderJob:
        file_path = os.path.join(job_dir, "render_job.json")
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Không tìm thấy file RenderJob tại {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        master_data = data.get("master_dataset") or {}
        master_dataset = MasterDataset.from_entry(master_data)

        voice_config = VoiceMappingConfig.from_dict(data.get("voice_config") or {})

        raw_tts = data.get("tts_results") or {}
        tts_results = {
            int(k): TTSSegmentResult.from_dict(v) for k, v in raw_tts.items()
        }

        raw_timeline = data.get("audio_timeline") or []
        audio_timeline = [AudioTimelineBlock.from_dict(b) for b in raw_timeline]

        return cls(
            id=str(data.get("id")),
            job_dir=job_dir,
            master_dataset=master_dataset,
            voice_config=voice_config,
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            status=str(data.get("status", "created")),
            progress_percent=float(data.get("progress_percent", 0.0) or 0.0),
            current_step_description=str(data.get("current_step_description", "") or ""),
            tts_results=tts_results,
            audio_timeline=audio_timeline,
            subtitle_file=str(data.get("subtitle_file", "") or ""),
            output_video_file=str(data.get("output_video_file", "") or ""),
            error_message=str(data.get("error_message", "") or ""),
        )
