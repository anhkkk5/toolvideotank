"""SubtitleSegment dataclass and typing definitions."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

TranslationStatus = Literal["none", "pending", "translated", "manual", "noise", "failed"]
GenderType = Literal["male", "female", "none", "unknown"]


@dataclass
class SubtitleSegment:
    id: int
    start: float
    end: float
    text: str
    translated_text: str = ""
    speaker_label: str = ""                # Tên nhân vật hoặc nhãn hiển thị (ví dụ: "Tiểu Đình", "Lâm Hạo")
    gender: GenderType = "unknown"         # "male" | "female" | "none" | "unknown" (final_gender alias)
    confidence: float = 0.0                # final_decision_confidence alias
    raw_gender: GenderType = "unknown"     # Kết quả gốc nguyên bản từ mô hình âm thanh
    raw_gender_confidence: float = 0.0     # Độ tin cậy gốc từ mô hình âm thanh
    final_gender: GenderType = "unknown"   # Kết quả sau khi kết hợp đa tầng
    final_decision_confidence: float = 0.0 # Độ tin cậy quyết định cuối cùng
    decision_mode: str = "raw_audio"       # "raw_audio" | "contextual_smoothing" | "manual"
    audio_quality: str = "clean"           # "clean" | "low"
    speech_duration: float = 0.0           # Thời lượng speech thực tế (VAD)
    speech_ratio: float = 0.0              # Tỷ lệ speech_duration / subtitle_duration
    music_score: float = 0.0               # Điểm nhạc nền từ AST
    gender_reason: list[str] = field(default_factory=list) # Danh sách lý do giải trình
    translation_source: str = "none"       # "deepseek" | "manual" | "none"
    translation_edited: bool = False       # True nếu người dùng sửa tay trên UI
    translation_status: TranslationStatus = "none" # "none" | "pending" | "translated" | "manual" | "noise" | "failed"
    is_noise: bool = False                 # True nếu là disclaimer kịch bản hoặc rác OCR
    skip_tts: bool = False
    voice_id: str = ""                     # TTS Voice ID được gán (ví dụ: "vieneu_thanhnientutin")
    voice_name: str = ""                   # Tên hiển thị của voice (ví dụ: "Thanh niên tự tin")
    status: str = "ok"
    fusion_reason: str = ""                # Lý do giải trình từ Multimodal Fusion
    bbox: list[float] = field(default_factory=list) # Tọa độ chuẩn hóa của phụ đề [x1, y1, x2, y2]
    cluster_id: str = ""                   # Cụm giọng nói (SPEAKER_00, SPEAKER_01...)
    acoustic_hint: str = ""                # Gợi ý âm học kèm mức tin cậy (vd: male 52.8% (0.8s, LOW trust))
    cluster_female_ratio: float = 0.5      # Tỉ lệ nữ trong cluster
    cluster_male_ratio: float = 0.5        # Tỉ lệ nam trong cluster

    def to_dict(self) -> dict[str, Any]:
        """Convert segment to serializable dictionary."""
        data = asdict(self)
        data["original_text"] = self.text
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_id: int = 1) -> SubtitleSegment:
        """Create SubtitleSegment from dictionary."""
        raw_id = data.get("id", default_id)
        try:
            seg_id = int(str(raw_id).split(":", 1)[0])
        except (ValueError, TypeError):
            seg_id = default_id

        text = str(data.get("text", "") or data.get("original_text", "") or "").strip()
        trans = str(data.get("translated_text", "") or "").strip()
        
        gender = str(data.get("gender", "unknown") or "unknown").lower().strip()
        if gender not in {"male", "female", "none"}:
            gender = "unknown"

        trans_source = str(data.get("translation_source", "none") or "none")
        trans_edited = bool(data.get("translation_edited", False))
        
        status = str(data.get("translation_status", "") or "").strip()
        if not status or status not in {"none", "pending", "translated", "manual", "noise", "failed"}:
            status = "manual" if trans_edited else ("translated" if trans else "none")

        raw_final = str(data.get("final_gender", "") or "").lower().strip()
        if raw_final in {"nữ", "nu", "female"}:
            final_gender = "female"
        elif raw_final in {"nam", "male"}:
            final_gender = "male"
        elif raw_final == "none":
            final_gender = "none"
        else:
            final_gender = gender

        raw_g = str(data.get("raw_gender", "") or "").lower().strip()
        if raw_g in {"nữ", "nu", "female"}:
            raw_gender = "female"
        elif raw_g in {"nam", "male"}:
            raw_gender = "male"
        elif raw_g == "none":
            raw_gender = "none"
        else:
            raw_gender = "unknown"

        return cls(
            id=seg_id,
            start=round(float(data.get("start", 0.0) or 0.0), 3),
            end=round(float(data.get("end", 0.0) or 0.0), 3),
            text=text,
            translated_text=trans,
            speaker_label=str(data.get("speaker_label", "") or data.get("speaker", "") or "").strip(),
            gender=gender,
            confidence=float(data.get("confidence", 0.0) or 0.0),
            raw_gender=raw_gender,
            raw_gender_confidence=float(data.get("raw_gender_confidence", 0.0) or 0.0),
            final_gender=final_gender,
            final_decision_confidence=float(data.get("final_decision_confidence", 0.0) or data.get("confidence", 0.0) or 0.0),
            decision_mode=str(data.get("decision_mode", "raw_audio") or "raw_audio"),
            audio_quality=str(data.get("audio_quality", "clean") or "clean"),
            speech_duration=float(data.get("speech_duration", 0.0) or 0.0),
            speech_ratio=float(data.get("speech_ratio", 0.0) or 0.0),
            music_score=float(data.get("music_score", 0.0) or 0.0),
            gender_reason=list(data.get("gender_reason", []) or []),
            translation_source=trans_source,
            translation_edited=trans_edited,
            translation_status=status,
            is_noise=bool(data.get("is_noise", False)),
            skip_tts=bool(data.get("skip_tts", False)),
            status=str(data.get("status", "ok") or "ok"),
            fusion_reason=str(data.get("fusion_reason", "") or ""),
            bbox=list(data.get("bbox") or []),
            cluster_id=str(data.get("cluster_id", "") or data.get("voice_cluster", "") or "").strip(),
            acoustic_hint=str(data.get("acoustic_hint", "") or "").strip(),
            cluster_female_ratio=float(data.get("cluster_female_ratio", 0.5) or 0.5),
            cluster_male_ratio=float(data.get("cluster_male_ratio", 0.5) or 0.5),
        )
