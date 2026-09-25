"""Pre-flight Validator for MasterDataset before feeding into Pipeline B."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

from app.models.master_dataset import MasterDataset
from app.models.subtitle_segment import SubtitleSegment

ValidationSeverity = Literal["error", "warning", "info"]


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: ValidationSeverity
    segment_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class MasterValidationResult:
    is_valid: bool
    can_proceed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [iss for iss in self.issues if iss.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [iss for iss in self.issues if iss.severity == "warning"]

    @property
    def infos(self) -> list[ValidationIssue]:
        return [iss for iss in self.issues if iss.severity == "info"]

    def format_summary(self) -> str:
        """Trả về bản tóm tắt thân thiện với người dùng."""
        lines = []
        if self.is_valid:
            lines.append("✅ Dữ liệu Master Data hợp lệ, sẵn sàng tạo video.")
        else:
            lines.append(f"❌ Phát hiện {len(self.errors)} lỗi nghiêm trọng cần xử lý!")

        if self.warnings:
            lines.append(f"⚠️ Có {len(self.warnings)} cảnh báo cần lưu ý.")

        counts = self.stats.get("counts", {})
        lines.append(
            f"📊 Thống kê: Tổng {counts.get('total', 0)} câu | "
            f"Nam: {counts.get('male', 0)} | Nữ: {counts.get('female', 0)} | "
            f"Không xác định: {counts.get('unknown', 0)} | Không lời: {counts.get('none', 0)}"
        )
        lines.append(
            f"🎙️ Số câu sẽ tạo giọng đọc TTS: {self.stats.get('tts_eligible_count', 0)} câu | "
            f"Phụ đề hiển thị: {self.stats.get('subtitle_display_count', 0)} câu"
        )
        return "\n".join(lines)


def validate_master_dataset(
    dataset: MasterDataset,
    *,
    check_video_file: bool = True,
    min_slot_duration: float = 0.2,
    max_slot_duration: float = 15.0,
) -> MasterValidationResult:
    """Thực hiện tiền kiểm tra (Pre-flight check) toàn diện trên MasterDataset.

    Đảm bảo dữ liệu hoàn toàn sạch và chuẩn xác trước khi đưa vào RenderJob.
    """
    issues: list[ValidationIssue] = []

    # 1. Kiểm tra đường dẫn video gốc
    if not dataset.video_path:
        issues.append(
            ValidationIssue(
                code="MISSING_VIDEO_PATH",
                message="Master Data không chứa đường dẫn video gốc.",
                severity="error",
            )
        )
    elif check_video_file and not os.path.isfile(dataset.video_path):
        issues.append(
            ValidationIssue(
                code="VIDEO_FILE_NOT_FOUND",
                message=f"Tệp video gốc không tồn tại trên đĩa: {dataset.video_path}",
                severity="error",
                details={"video_path": dataset.video_path},
            )
        )

    # 2. Kiểm tra danh sách phân đoạn (segments)
    if not dataset.segments:
        issues.append(
            ValidationIssue(
                code="EMPTY_DATASET",
                message="Master Data không có câu phụ đề nào.",
                severity="error",
            )
        )
        return MasterValidationResult(
            is_valid=False,
            can_proceed=False,
            issues=issues,
            stats={"counts": dataset.counts, "tts_eligible_count": 0, "subtitle_display_count": 0},
        )

    # 3. Duyệt từng phân đoạn để kiểm tra tính toàn vẹn
    invalid_timing_count = 0
    missing_translation_tts_count = 0
    short_slot_count = 0
    long_slot_count = 0

    valid_genders = {"male", "female", "unknown", "none"}

    for seg in dataset.segments:
        # Thời gian
        if seg.start < 0:
            issues.append(
                ValidationIssue(
                    code="NEGATIVE_START_TIME",
                    message=f"Câu #{seg.id} có thời gian bắt đầu âm ({seg.start}s).",
                    severity="error",
                    segment_id=seg.id,
                )
            )
            invalid_timing_count += 1

        if seg.start >= seg.end:
            issues.append(
                ValidationIssue(
                    code="INVALID_TIMING_ORDER",
                    message=f"Câu #{seg.id} có thời gian bắt đầu ({seg.start}s) >= kết thúc ({seg.end}s).",
                    severity="error",
                    segment_id=seg.id,
                )
            )
            invalid_timing_count += 1
        else:
            duration = seg.end - seg.start
            if duration < min_slot_duration and not seg.is_noise and seg.gender != "none":
                issues.append(
                    ValidationIssue(
                        code="SLOT_TOO_SHORT",
                        message=f"Câu #{seg.id} có thời lượng quá ngắn ({duration:.2f}s < {min_slot_duration}s).",
                        severity="warning",
                        segment_id=seg.id,
                    )
                )
                short_slot_count += 1
            elif duration > max_slot_duration and not seg.is_noise:
                issues.append(
                    ValidationIssue(
                        code="SLOT_TOO_LONG",
                        message=f"Câu #{seg.id} có thời lượng rất dài ({duration:.2f}s > {max_slot_duration}s).",
                        severity="warning",
                        segment_id=seg.id,
                    )
                )
                long_slot_count += 1

        # Giới tính / phân vai
        if seg.gender not in valid_genders:
            issues.append(
                ValidationIssue(
                    code="INVALID_GENDER",
                    message=f"Câu #{seg.id} có giá trị giới tính không hợp lệ: '{seg.gender}'.",
                    severity="warning",
                    segment_id=seg.id,
                )
            )

        # Bản dịch tiếng Việt
        is_dialogue = seg.gender in ("male", "female") and not seg.is_noise and not seg.skip_tts
        if is_dialogue and not seg.translated_text.strip():
            issues.append(
                ValidationIssue(
                    code="MISSING_TRANSLATION_FOR_TTS",
                    message=f"Câu #{seg.id} được chỉ định đọc giọng {seg.gender} nhưng chưa có bản dịch tiếng Việt.",
                    severity="error",
                    segment_id=seg.id,
                )
            )
            missing_translation_tts_count += 1

    # 4. Kiểm tra tổng thể
    tts_segments = dataset.get_tts_eligible_segments()
    sub_segments = dataset.get_subtitle_display_segments()
    counts = dataset.counts

    if not tts_segments:
        issues.append(
            ValidationIssue(
                code="NO_TTS_ELIGIBLE_SEGMENTS",
                message="Không có câu nào đủ điều kiện để lồng tiếng (cần ít nhất 1 câu nam/nữ có bản dịch).",
                severity="warning",
            )
        )

    if counts["total"] > 0 and (counts["unknown"] / counts["total"]) > 0.5:
        issues.append(
            ValidationIssue(
                code="HIGH_UNKNOWN_RATIO",
                message=f"Tỷ lệ câu không xác định giới tính khá cao ({counts['unknown']}/{counts['total']} câu). "
                        "Các câu này sẽ chỉ hiện phụ đề mà không được lồng tiếng.",
                severity="info",
            )
        )

    has_errors = any(iss.severity == "error" for iss in issues)
    can_proceed = not has_errors and (len(tts_segments) > 0 or len(sub_segments) > 0)

    stats = {
        "counts": counts,
        "tts_eligible_count": len(tts_segments),
        "subtitle_display_count": len(sub_segments),
        "invalid_timing_count": invalid_timing_count,
        "missing_translation_tts_count": missing_translation_tts_count,
        "short_slot_count": short_slot_count,
        "long_slot_count": long_slot_count,
        "total_duration": dataset.duration,
    }

    return MasterValidationResult(
        is_valid=not has_errors,
        can_proceed=can_proceed,
        issues=issues,
        stats=stats,
    )
