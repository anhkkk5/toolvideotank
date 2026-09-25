"""TTS Backend Interface and Result Contract for Voiceover Pipeline.

Standardized contract according to Step 5.1 & Step 5.2.1:
- TTSResult: Output contract representing the exact state of TTS synthesis per segment.
- TTSBackend: Abstract Base Class that every TTS Engine (VieNeu, Piper, Cloud) must implement.
- measure_wav_duration: Utility to extract exact raw audio duration from WAV header.
"""

from __future__ import annotations

import os
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Any, Literal

TTSStatus = Literal["pending", "generating", "success", "failed", "skipped"]


def measure_wav_duration(wav_path: str) -> float:
    """Đo thời lượng file WAV chính xác (giây) dựa trên frame count và sample rate.
    
    Chỉ đo trực tiếp từ file âm thanh thô (Raw Audio), không giả định hay can thiệp tốc độ.
    """
    if not os.path.isfile(wav_path):
        return 0.0
    try:
        with wave.open(wav_path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0:
                return round(frames / float(rate), 3)
    except Exception:
        pass
    return 0.0


@dataclass
class TTSResult:
    """Output Contract chuẩn hóa của một câu thoại sau khi qua TTS Generator.
    
    Fields:
    - segment_id: Định danh câu thoại
    - voice_id: Giọng đọc do Voice Mapping quyết định (bất biến)
    - audio_path: Đường dẫn file WAV thô được sinh
    - duration: Thời lượng thực tế đo được từ Raw Audio (giây)
    - status: Trạng thái ("pending" | "generating" | "success" | "failed" | "skipped")
    - error: Mô tả lỗi nếu thất bại (không chứa API key/token)
    """
    segment_id: int
    voice_id: str = ""
    audio_path: str = ""
    duration: float = 0.0
    status: TTSStatus = "pending"
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TTSBackend(ABC):
    """Abstract Interface cho mọi engine tạo giọng đọc trong hệ thống.
    
    Mỗi backend chỉ thực hiện đúng một nhiệm vụ:
    Nhận (text, voice_id, output_path) -> sinh file WAV thô và trả về duration thực tế.
    
    Nguyên tắc bắt buộc:
    - Không đọc raw_gender / final_gender
    - Không tự đổi voice_id khi lỗi hoặc không tìm thấy
    - Ném Exception (ví dụ ValueError) khi voice_id không hợp lệ để tầng Service ghi nhận status='failed'
    """

    @abstractmethod
    def synthesize(self, text: str, voice_id: str, output_path: str) -> float:
        """Sinh âm thanh thô ra output_path và trả về thời lượng thực tế (giây).
        
        Args:
            text: Nội dung câu thoại tiếng Việt cần đọc.
            voice_id: Mã giọng do Voice Mapping chỉ định (ví dụ: 'vieneu_thanhnientutin').
            output_path: Đường dẫn file WAV thô cần ghi ra.
            
        Returns:
            float: Thời lượng thực tế của file âm thanh thô (giây).
            
        Raises:
            ValueError: Khi voice_id không tồn tại hoặc không được backend hỗ trợ.
            RuntimeError: Khi quá trình tổng hợp âm thanh thất bại.
        """
        pass
