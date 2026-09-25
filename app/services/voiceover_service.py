"""Voiceover Service - Centralized Orchestration for Raw TTS Audio Generation.

Implements Step 5.2 & Step 5.2.2.3:
- Orchestrates TTS generation from SubtitleSegment data contract.
- Validates Skip Rules IMMEDIATELY before backend execution.
- Treats voice_id as final and unchangeable (strictly NO voice fallback).
- Produces Raw TTS Audio and records exact measured duration.
- Strictly NO duration fitting, NO audio ducking, NO mixing.
"""

from __future__ import annotations

import os
from typing import Any

from app.models.subtitle_segment import SubtitleSegment
from app.services.tts_backend import TTSBackend, TTSResult
from app.services.vieneu_backend import VieNeuBackend
from app.services.unified_tts_backend import UnifiedTTSBackend


class VoiceoverService:
    """Service chịu trách nhiệm sinh Raw TTS Audio cho từng câu thoại.
    
    Tuân thủ nghiêm ngặt 4 nguyên tắc kiến trúc:
    1. Skip trước: Nếu câu rỗng/nhiễu/bỏ qua/không có voice_id -> return status="skipped" ngay.
    2. voice_id là bất biến: Truyền đúng voice_id xuống backend, không tự đổi hay fallback ngầm.
    3. Không duration fitting: Chỉ đo và trả về duration thô của file sinh ra.
    4. Không mixing/ducking: Chỉ quản lý tầng sinh file WAV thô.
    """

    def __init__(
        self,
        backend: TTSBackend | None = None,
        raw_output_dir: str = "raw_tts",
    ):
        self.backend = backend if backend is not None else UnifiedTTSBackend()
        self.raw_output_dir = raw_output_dir

    def generate(
        self,
        *,
        segment_id: int,
        translated_text: str,
        start: float = 0.0,
        end: float = 0.0,
        voice_id: str = "",
        is_noise: bool = False,
        skip_tts: bool = False,
        output_path: str | None = None,
    ) -> TTSResult:
        """Sinh âm thanh thô cho một câu thoại theo đúng input contract 5.1.
        
        Args:
            segment_id: Mã câu thoại.
            translated_text: Nội dung tiếng Việt đã dịch.
            start: Thời điểm bắt đầu slot (giây).
            end: Thời điểm kết thúc slot (giây).
            voice_id: Mã giọng đã được Voice Mapping quyết định.
            is_noise: Đánh dấu câu rác/nhiễu.
            skip_tts: Đánh dấu chủ động bỏ qua lồng tiếng.
            output_path: Đường dẫn file WAV thô (tùy chọn).
            
        Returns:
            TTSResult: Kết quả tổng hợp âm thanh thô.
        """
        clean_text = str(translated_text or "").strip()
        clean_voice = str(voice_id or "").strip()

        # =====================================================================
        # BƯỚC 1: KIỂM TRA SKIP RULES NGAY TẠI CỬA NGÕ (FAIL-EARLY)
        # Không khởi tạo backend hoặc gọi bất kỳ tiến trình nào nếu vi phạm.
        # =====================================================================
        if not clean_text or is_noise or skip_tts or not clean_voice:
            return TTSResult(
                segment_id=segment_id,
                voice_id=clean_voice,
                audio_path="",
                duration=0.0,
                status="skipped",
                error="",
            )

        # =====================================================================
        # BƯỚC 2: XÁC ĐỊNH ĐƯỜNG DẪN OUTPUT FILE THÔ
        # =====================================================================
        if not output_path:
            os.makedirs(self.raw_output_dir, exist_ok=True)
            output_path = os.path.join(
                self.raw_output_dir,
                f"segment_{segment_id:04d}.wav",
            )
        else:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        # =====================================================================
        # BƯỚC 3: THỰC THI QUA BACKEND (VOICE_ID BẤT BIẾN, BẮT LỖI MINH BẠCH)
        # =====================================================================
        try:
            raw_duration = self.backend.synthesize(
                text=clean_text,
                voice_id=clean_voice,
                output_path=output_path,
            )
            return TTSResult(
                segment_id=segment_id,
                voice_id=clean_voice,
                audio_path=output_path,
                duration=raw_duration,
                status="success",
                error="",
            )
        except Exception as exc:
            # Lỗi được ghi nhận minh bạch, tuyệt đối không tự sửa hay fallback giọng khác
            return TTSResult(
                segment_id=segment_id,
                voice_id=clean_voice,
                audio_path="",
                duration=0.0,
                status="failed",
                error=str(exc),
            )

    def generate_for_segment(
        self,
        segment: SubtitleSegment,
        output_path: str | None = None,
    ) -> TTSResult:
        """Wrapper thuận tiện nhận trực tiếp SubtitleSegment.
        
        Trích xuất đúng 5 trường dữ liệu contract từ SubtitleSegment và chuyển tiếp.
        TUYỆT ĐỐI KHÔNG đọc raw_gender hay tự suy đoán lại giới tính.
        """
        return self.generate(
            segment_id=segment.id,
            translated_text=segment.translated_text,
            start=segment.start,
            end=segment.end,
            voice_id=getattr(segment, "voice_id", ""),
            is_noise=getattr(segment, "is_noise", False),
            skip_tts=getattr(segment, "skip_tts", False),
            output_path=output_path,
        )

    def process_segment(
        self,
        segment: SubtitleSegment,
        voice_mapping_service: Any = None,
        output_path: str | None = None,
    ) -> TTSResult:
        """Thực hiện chuỗi liên kết chuẩn: VoiceMapping -> voice_id -> VoiceoverService.
        
        1. Gọi VoiceMappingService để phân giải final_gender thành voice_id trên segment.
        2. Chuyển segment đã có voice_id vào generate_for_segment().
        
        Bảo đảm nguyên tắc kiến trúc:
        - VoiceoverService KHÔNG tự đọc final_gender hay raw_gender.
        - VoiceMappingService chịu trách nhiệm duy nhất ánh xạ final_gender -> voice_id.
        - unknown/none -> voice_id="" -> VoiceoverService tự động skip.
        """
        if voice_mapping_service is not None:
            voice_mapping_service.resolve_voice_for_segment(segment)

        return self.generate_for_segment(segment, output_path=output_path)

