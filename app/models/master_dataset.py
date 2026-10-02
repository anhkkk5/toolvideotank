"""MasterDataset dataclass representing an approved, single-source-of-truth dataset."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.subtitle_segment import SubtitleSegment


@dataclass
class MasterDataset:
    """Đại diện cho một bản Master Data duy nhất (Single Source of Truth)

    đã được người dùng kiểm duyệt hoàn tất từ Pipeline A.
    Pipeline B chỉ đọc dữ liệu từ đối tượng này.
    """
    id: str
    video_path: str
    created_at: str = ""
    updated_at: str = ""
    title: str = ""
    segments: list[SubtitleSegment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        if not self.title:
            if self.video_path:
                import os
                self.title = os.path.basename(self.video_path)
            else:
                self.title = f"Master_{self.id[:8]}"

    @property
    def counts(self) -> dict[str, int]:
        """Thống kê chi tiết các loại phân vai trong dataset."""
        counts = {
            "total": len(self.segments),
            "male": 0,
            "female": 0,
            "unknown": 0,
            "none": 0,
            "noise": 0,
            "translated": 0,
            "untranslated": 0,
        }
        for seg in self.segments:
            if seg.is_noise:
                counts["noise"] += 1
                continue
            if getattr(seg, "manual_override", False) or str(getattr(seg, "decision_mode", "")).lower() == "manual":
                g = str(getattr(seg, "gender", "") or getattr(seg, "final_gender", "") or "unknown").lower().strip()
            else:
                g = str(getattr(seg, "final_gender", "") or getattr(seg, "gender", "") or "unknown").lower().strip()
            if g in ("female", "nữ", "nu"):
                g = "female"
            elif g in ("male", "nam"):
                g = "male"

            if g in counts:
                counts[g] += 1
            else:
                counts["unknown"] += 1

            if seg.translated_text.strip():
                counts["translated"] += 1
            else:
                counts["untranslated"] += 1
        return counts

    @property
    def duration(self) -> float:
        """Tổng thời lượng kịch bản từ 0 đến mốc kết thúc của câu cuối cùng."""
        if not self.segments:
            return 0.0
        return max(seg.end for seg in self.segments)

    def get_tts_eligible_segments(self) -> list[SubtitleSegment]:
        """Lọc danh sách các câu cần và đủ điều kiện để tạo giọng đọc TTS:

        - Giới tính là male hoặc female (unknown và none KHÔNG tạo TTS)
        - Không phải là noise hoặc bị đánh dấu skip_tts
        - Có nội dung bản dịch tiếng Việt (translated_text không rỗng)
        """
        eligible = []
        for seg in self.segments:
            if seg.is_noise or seg.skip_tts:
                continue
            if getattr(seg, "manual_override", False) or str(getattr(seg, "decision_mode", "")).lower() == "manual":
                g = str(getattr(seg, "gender", "") or getattr(seg, "final_gender", "") or "unknown").lower().strip()
            else:
                g = str(getattr(seg, "final_gender", "") or getattr(seg, "gender", "") or "unknown").lower().strip()
            if g in ("female", "nữ", "nu"):
                g = "female"
            elif g in ("male", "nam"):
                g = "male"
            if g in ("male", "female") and seg.translated_text.strip():
                eligible.append(seg)
        return eligible

    def get_subtitle_display_segments(self) -> list[SubtitleSegment]:
        """Lọc danh sách các câu cần hiển thị phụ đề trên video:

        - Bao gồm cả male, female và unknown (nếu có bản dịch tiếng Việt)
        - none và noise sẽ không hiển thị phụ đề rác
        """
        sub_segs = []
        for seg in self.segments:
            if seg.is_noise or seg.gender == "none":
                continue
            text_to_show = seg.translated_text.strip() or seg.text.strip()
            if text_to_show:
                sub_segs.append(seg)
        return sub_segs

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi thành dictionary có thể serialize ra JSON lưu trữ."""
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "video_path": self.video_path,
            "metadata": self.metadata,
            "result": {
                "video_path": self.video_path,
                "counts": self.counts,
                "rows": [seg.to_dict() for seg in self.segments],
            },
        }

    @classmethod
    def from_entry(cls, entry_dict: dict[str, Any]) -> MasterDataset:
        """Khởi tạo MasterDataset từ một entry trong file lịch sử voice_gender_checks.json."""
        entry_id = str(entry_dict.get("id") or "")
        created_at = str(entry_dict.get("created_at") or "")
        updated_at = str(entry_dict.get("updated_at") or "")
        video_path = str(entry_dict.get("video_path") or "")
        metadata = dict(entry_dict.get("metadata") or {})

        result = dict(entry_dict.get("result") or {})
        if not video_path:
            video_path = str(result.get("video_path") or "")

        raw_rows = list(result.get("rows") or result.get("segments") or [])
        segments: list[SubtitleSegment] = []
        for idx, row in enumerate(raw_rows, start=1):
            if isinstance(row, dict):
                segments.append(SubtitleSegment.from_dict(row, default_id=idx))

        return cls(
            id=entry_id,
            video_path=video_path,
            created_at=created_at,
            updated_at=updated_at,
            title=str(entry_dict.get("title") or ""),
            segments=segments,
            metadata=metadata,
        )
