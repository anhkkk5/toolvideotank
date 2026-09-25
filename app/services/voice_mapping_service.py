"""Centralized Voice Mapping Service for assigning TTS voices to Master Data segments."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

from app.models.subtitle_segment import SubtitleSegment
from app.models.master_dataset import MasterDataset


@dataclass
class VoiceAssignment:
    """Đại diện cho một cấu hình giọng TTS được gán cho câu thoại."""
    voice_id: str
    name: str
    provider: str = "vieneu"  # "vieneu" | "capcut" | "piper" | "edge"
    gender: Literal["male", "female"] = "male"
    speed: float = 1.0
    pitch: float = 0.0
    volume: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceAssignment:
        gender_raw = str(data.get("gender", "male")).lower().strip()
        gender = "female" if gender_raw == "female" else "male"
        return cls(
            voice_id=str(data.get("voice_id", "") or "default"),
            name=str(data.get("name", "") or "Giọng mặc định"),
            provider=str(data.get("provider", "vieneu") or "vieneu"),
            gender=gender,
            speed=float(data.get("speed", 1.0) or 1.0),
            pitch=float(data.get("pitch", 0.0) or 0.0),
            volume=float(data.get("volume", 1.0) or 1.0),
        )


# Cấu hình giọng mặc định chuẩn theo yêu cầu dự án:
# - Nam: "Thanh niên tự tin" (vieneu_thanhnientutin)
# - Nữ: "Cô gái hoạt ngôn" (vieneu_cogaihoatbat)
DEFAULT_MALE_VOICE = VoiceAssignment(
    voice_id="vieneu_thanhnientutin",
    name="Thanh niên tự tin",
    provider="vieneu",
    gender="male",
    speed=1.0,
)

DEFAULT_FEMALE_VOICE = VoiceAssignment(
    voice_id="vieneu_cogaihoatbat",
    name="Cô gái hoạt ngôn",
    provider="vieneu",
    gender="female",
    speed=1.0,
)


@dataclass
class VoiceMappingConfig:
    """Toàn bộ cấu hình phân vai và ánh xạ giọng đọc kịch bản."""
    default_male_voice: VoiceAssignment = field(default_factory=lambda: DEFAULT_MALE_VOICE)
    default_female_voice: VoiceAssignment = field(default_factory=lambda: DEFAULT_FEMALE_VOICE)
    character_voices: dict[str, VoiceAssignment] = field(default_factory=dict)
    fallback_voice: VoiceAssignment | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_male_voice": self.default_male_voice.to_dict(),
            "default_female_voice": self.default_female_voice.to_dict(),
            "character_voices": {
                name: voice.to_dict() for name, voice in self.character_voices.items()
            },
            "fallback_voice": self.fallback_voice.to_dict() if self.fallback_voice else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceMappingConfig:
        male_data = data.get("default_male_voice") or {}
        female_data = data.get("default_female_voice") or {}
        char_data = data.get("character_voices") or {}
        fallback_data = data.get("fallback_voice")

        return cls(
            default_male_voice=VoiceAssignment.from_dict(male_data) if male_data else DEFAULT_MALE_VOICE,
            default_female_voice=VoiceAssignment.from_dict(female_data) if female_data else DEFAULT_FEMALE_VOICE,
            character_voices={
                name: VoiceAssignment.from_dict(v) for name, v in char_data.items() if isinstance(v, dict)
            },
            fallback_voice=VoiceAssignment.from_dict(fallback_data) if isinstance(fallback_data, dict) else None,
        )


class VoiceMappingService:
    """Service trung tâm quyết định giọng đọc TTS cho từng câu thoại trong Master Data.

    Tuân thủ nghiêm ngặt 5 nguyên tắc kiến trúc:
    - male -> giọng nam
    - female -> giọng nữ
    - speaker_label khớp nhân vật -> giọng riêng của nhân vật
    - unknown & none -> TUYỆT ĐỐI KHÔNG GÁN GIỌNG (trả về None)
    """

    def __init__(self, config: VoiceMappingConfig | None = None):
        self.config = config or VoiceMappingConfig()

    def resolve_by_gender(self, final_gender: str) -> VoiceAssignment | None:
        """Thuần túy ánh xạ từ final_gender sang VoiceAssignment.
        
        Contract bất biến:
        - 'male'   -> default_male_voice ("Thanh niên tự tin" / vieneu_thanhnientutin)
        - 'female' -> default_female_voice ("Cô gái hoạt bát" / vieneu_cogaihoatbat)
        - 'unknown' -> None
        - 'none'    -> None
        """
        g = str(final_gender or "").lower().strip()
        if g in ("male", "nam"):
            return self.config.default_male_voice
        elif g in ("female", "nữ", "nu"):
            return self.config.default_female_voice
        return None

    def resolve_voice_for_segment(self, segment: SubtitleSegment) -> VoiceAssignment | None:
        """Xác định giọng đọc cho một câu thoại cụ thể.

        Tuân thủ hợp đồng:
        - CHỈ ĐỌC final_gender (hoặc gender alias). TUYỆT ĐỐI KHÔNG đọc raw_gender.
        - Trả về VoiceAssignment nếu câu cần lồng tiếng TTS, hoặc None nếu bỏ qua.
        """
        # 1. Đoạn nhiễu hoặc chủ động đánh dấu bỏ qua TTS
        if getattr(segment, "is_noise", False) or getattr(segment, "skip_tts", False):
            segment.voice_id = ""
            segment.voice_name = ""
            return None

        # 2. Không có nội dung bản dịch tiếng Việt để đọc
        trans_text = str(getattr(segment, "translated_text", "") or "").strip()
        if not trans_text:
            segment.voice_id = ""
            segment.voice_name = ""
            return None

        # 3. Đọc final_gender (nếu rỗng hoặc unknown thì fallback sang gender)
        raw_final = str(getattr(segment, "final_gender", "") or "").lower().strip()
        if not raw_final or raw_final == "unknown":
            raw_final = str(getattr(segment, "gender", "unknown") or "unknown").lower().strip()

        if raw_final in ("female", "nữ", "nu"):
            final_g = "female"
        elif raw_final in ("male", "nam"):
            final_g = "male"
        else:
            final_g = raw_final

        # 4. unknown và none TUYỆT ĐỐI KHÔNG TTS
        if final_g in ("unknown", "none"):
            segment.voice_id = ""
            segment.voice_name = ""
            return None

        # 5. Ưu tiên gán giọng theo nhân vật cụ thể nếu có cấu hình riêng
        speaker = str(getattr(segment, "speaker_label", "") or "").strip()
        if speaker and speaker in self.config.character_voices:
            assignment = self.config.character_voices[speaker]
            segment.voice_id = assignment.voice_id
            segment.voice_name = assignment.name
            return assignment

        # 6. Ánh xạ theo final_gender
        assignment = self.resolve_by_gender(final_g) or self.config.fallback_voice
        if assignment is not None:
            segment.voice_id = assignment.voice_id
            segment.voice_name = assignment.name
        else:
            segment.voice_id = ""
            segment.voice_name = ""
        return assignment

    def map_dataset(self, dataset: MasterDataset) -> dict[int, VoiceAssignment | None]:
        """Ánh xạ toàn bộ các câu trong MasterDataset sang giọng TTS tương ứng.

        Trả về dictionary dạng {segment_id: VoiceAssignment | None}.
        """
        mapping: dict[int, VoiceAssignment | None] = {}
        for seg in dataset.segments:
            mapping[seg.id] = self.resolve_voice_for_segment(seg)
        return mapping

    def get_summary_mapping(self, dataset: MasterDataset) -> dict[str, Any]:
        """Tóm tắt phân bổ giọng đọc kịch bản để hiển thị trên giao diện xác nhận (Dialog/UI)."""
        assigned = self.map_dataset(dataset)
        voice_counts: dict[str, int] = {}
        skipped_unknown = 0
        skipped_none = 0
        skipped_noise = 0
        skipped_untranslated = 0
        total_tts_sentences = 0

        for seg in dataset.segments:
            v = assigned.get(seg.id)
            if v is not None:
                total_tts_sentences += 1
                key = f"{v.name} ({v.provider})"
                voice_counts[key] = voice_counts.get(key, 0) + 1
            else:
                if seg.is_noise:
                    skipped_noise += 1
                elif seg.gender == "unknown":
                    skipped_unknown += 1
                elif seg.gender == "none":
                    skipped_none += 1
                elif not seg.translated_text.strip():
                    skipped_untranslated += 1

        return {
            "total_segments": len(dataset.segments),
            "total_tts_sentences": total_tts_sentences,
            "voice_distribution": voice_counts,
            "skipped": {
                "unknown": skipped_unknown,
                "none": skipped_none,
                "noise": skipped_noise,
                "untranslated": skipped_untranslated,
            },
        }
