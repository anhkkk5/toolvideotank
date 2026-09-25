"""TTS Pipeline Service - Complete End-to-End TTS & Duration Fitting Orchestration.

Implements Step 5.5:
Connects Master Data SubtitleSegments sequentially through:
1. VoiceMappingService (final_gender -> voice_id)
2. VoiceoverService (raw audio synthesis in raw_tts/)
3. DurationFittingService (speed fitting in fitted_tts/)
Produces structured TTSPipelineResult per segment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

from app.models.subtitle_segment import SubtitleSegment
from app.services.voice_mapping_service import VoiceMappingService
from app.services.voiceover_service import VoiceoverService
from app.services.duration_fitting_service import DurationFittingService, FittedAudioResult
from app.services.tts_backend import TTSBackend, TTSResult


@dataclass
class TTSPipelineSegmentResult:
    """Kết quả hoàn chỉnh của một câu thoại sau khi đi qua toàn bộ pipeline TTS."""
    segment_id: int
    voice_id: str = ""
    voice_name: str = ""
    raw_audio_path: str = ""
    raw_duration: float = 0.0
    fitted_audio_path: str = ""
    fitted_duration: float = 0.0
    applied_speed: float = 1.0
    status: Literal["success", "skipped", "failed"] = "success"
    warning: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TTSPipelineService:
    """Orchestrator kết nối khép kín chuỗi:
    SubtitleSegment (final_gender) -> VoiceMapping -> Voiceover -> DurationFitting.
    
    Đảm bảo:
    - Quản lý danh sách nhiều segment liên tiếp.
    - Không segment nào ghi đè file của segment khác (phân tách theo segment_id).
    - Bảo toàn tính bất biến của Raw WAV (raw_tts/ không bị sửa đổi).
    - Giữ nguyên vẹn voice_id xuyên suốt pipeline.
    """

    def __init__(
        self,
        voice_mapping_service: VoiceMappingService | None = None,
        voiceover_service: VoiceoverService | None = None,
        duration_fitting_service: DurationFittingService | None = None,
        raw_output_dir: str = "raw_tts",
        fitted_output_dir: str = "fitted_tts",
    ):
        self.voice_mapper = voice_mapping_service or VoiceMappingService()
        self.voiceover = voiceover_service or VoiceoverService(raw_output_dir=raw_output_dir)
        self.fitting = duration_fitting_service or DurationFittingService(fitted_output_dir=fitted_output_dir)
        self.raw_output_dir = raw_output_dir
        self.fitted_output_dir = fitted_output_dir

    def process_segment(self, segment: SubtitleSegment) -> TTSPipelineSegmentResult:
        """Xử lý đơn lẻ một segment qua toàn bộ pipeline."""
        # 1. Voice Mapping: Ánh xạ final_gender -> segment.voice_id & segment.voice_name
        self.voice_mapper.resolve_voice_for_segment(segment)
        v_id = getattr(segment, "voice_id", "")
        v_name = getattr(segment, "voice_name", "")

        # 2. Voiceover: Sinh Raw TTS Audio (Kiểm tra skip tại cửa ngõ)
        out_raw = os.path.join(self.raw_output_dir, f"segment_{segment.id:04d}.wav")
        tts_res: TTSResult = self.voiceover.generate_for_segment(segment, output_path=out_raw)

        # Xử lý trường hợp bị Skip
        if tts_res.status == "skipped":
            return TTSPipelineSegmentResult(
                segment_id=segment.id,
                voice_id=v_id,
                voice_name=v_name,
                raw_audio_path="",
                raw_duration=0.0,
                fitted_audio_path="",
                fitted_duration=0.0,
                applied_speed=1.0,
                status="skipped",
                warning="",
                error="",
            )

        # Xử lý trường hợp TTS thất bại
        if tts_res.status == "failed":
            return TTSPipelineSegmentResult(
                segment_id=segment.id,
                voice_id=v_id,
                voice_name=v_name,
                raw_audio_path="",
                raw_duration=0.0,
                fitted_audio_path="",
                fitted_duration=0.0,
                applied_speed=1.0,
                status="failed",
                warning="",
                error=tts_res.error,
            )

        # 3. Duration Fitting: Điều chỉnh thời lượng theo slot phụ đề
        slot_dur = max(0.1, round(segment.end - segment.start, 3))
        out_fitted = os.path.join(self.fitted_output_dir, f"segment_{segment.id:04d}_fit.wav")
        fit_res: FittedAudioResult = self.fitting.fit_segment(
            segment_id=segment.id,
            raw_audio_path=tts_res.audio_path,
            slot_duration=slot_dur,
            output_path=out_fitted,
        )

        if fit_res.status == "failed":
            return TTSPipelineSegmentResult(
                segment_id=segment.id,
                voice_id=v_id,
                voice_name=v_name,
                raw_audio_path=tts_res.audio_path,
                raw_duration=tts_res.duration,
                fitted_audio_path="",
                fitted_duration=0.0,
                applied_speed=1.0,
                status="failed",
                warning="",
                error=fit_res.error,
            )

        return TTSPipelineSegmentResult(
            segment_id=segment.id,
            voice_id=v_id,
            voice_name=v_name,
            raw_audio_path=fit_res.raw_audio_path,
            raw_duration=fit_res.raw_duration,
            fitted_audio_path=fit_res.fitted_audio_path,
            fitted_duration=fit_res.fitted_duration,
            applied_speed=fit_res.applied_speed,
            status="success",
            warning=fit_res.warning,
            error="",
        )

    def process_segments(self, segments: list[SubtitleSegment]) -> list[TTSPipelineSegmentResult]:
        """Xử lý danh sách các segment liên tiếp qua toàn bộ pipeline."""
        results: list[TTSPipelineSegmentResult] = []
        for seg in segments:
            res = self.process_segment(seg)
            results.append(res)
        return results
