"""Video Creator Pipeline Orchestration Service.

Implements Step 8: End-to-End Video Creator Pipeline Orchestrator Contract v1.1:
- Master Data Read-Only: Segments are strictly immutable; voice assignments are decoupled in VoiceAssignment.
- Preflight Gate: Fail-fast validation before any downstream processing.
- Config Propagation: Injects bounded parameters directly into specialized child services.
- Cooperative Cancellation: Regular cancellation checkpoints across stages and individual TTS units.
- 3-Tier Workspace Lifecycle: Ephemeral SRT cleanup, optional intermediate audio cleanup, persistent final artifacts.
- Standardized Monotonic Progress Weighting (0% -> 100%).
- Full downstream error propagation without crashing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Literal, Any

from app.models.subtitle_segment import SubtitleSegment
from app.services.audio_mixing_service import AudioMixingService, MixedAudioResult, TTSAudioBlock
from app.services.duration_fitting_service import DurationFittingService
from app.services.original_audio_extractor import OriginalAudioExtractor
from app.services.video_export_service import (
    OverflowPolicy,
    SubtitleRenderConfig,
    VideoExportRequest,
    VideoExportResult,
    VideoExportService,
    _resolve_ffprobe,
    measure_media_duration,
)
from app.services.voiceover_service import VoiceoverService

ProgressCallback = Callable[[float, str], None]
CancelledFunc = Callable[[], bool]


def probe_media_streams(file_path: str, ffprobe_bin: str | None = None) -> tuple[bool, list[dict[str, Any]], str]:
    """Trích xuất danh sách streams từ file media bằng ffprobe."""
    if not file_path or not os.path.isfile(file_path):
        return False, [], f"File not found: '{file_path}'"

    probe = ffprobe_bin or _resolve_ffprobe()
    cmd = [
        probe,
        "-v", "error",
        "-show_streams",
        "-of", "json",
        file_path,
    ]
    kwargs: dict[str, Any] = {"capture_output": True, "text": True, "timeout": 15, "encoding": "utf-8", "errors": "ignore"}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        res = subprocess.run(cmd, **kwargs)
        if res.returncode != 0:
            return False, [], f"FFprobe failed (code {res.returncode}): {res.stderr.strip()}"
        data = json.loads(res.stdout or "{}")
        streams = data.get("streams", [])
        return True, streams, ""
    except Exception as exc:
        return False, [], f"FFprobe execution exception: {exc}"


@dataclass(frozen=True)
class VoiceAssignment:
    """Bản ghi gán giọng độc lập, bảo vệ tuyệt đối tính bất biến của Master Data."""
    segment_id: int
    voice_id: str | None = None
    is_tts_eligible: bool = False
    reason: str = ""


@dataclass
class VideoCreatorConfig:
    """Cấu hình vận hành Orchestrator (chuyển tiếp tới các service thành phần đã khóa)."""
    overflow_policy: OverflowPolicy = "shortest"
    duck_volume: float = 0.20
    original_volume: float = 0.50
    tts_volume: float = 1.00
    voice_config: Any = None
    max_speedup_ratio: float = 1.20
    subtitle_config: SubtitleRenderConfig = field(default_factory=SubtitleRenderConfig)
    cleanup_intermediate_audio: bool = False
    enable_blur_mask: bool = True
    mask_mode: str = "box"                # Kiểu mặt nạ: "blur" (Ảnh 1), "box" (Ảnh 2), "none"
    blur_rect: tuple[float, float, float, float] | None = None
    # Brand logo settings
    enable_brand_logo: bool = False
    brand_logo_path: str = ""
    brand_logo_position: str = "top_left"
    brand_logo_size_percent: int = 15
    brand_logo_opacity: float = 1.0
    # Text watermark settings
    enable_watermark: bool = False
    watermark_text: str = ""
    watermark_position: str = "center"
    watermark_font_size: int = 36
    watermark_opacity: float = 0.35
    watermark_color: str = "#FFFFFF"
    # Xóa / Tẩy Logo & Watermark video gốc (Bilibili, Douyin, Bản quyền mờ)
    delogo_bilibili: bool = False
    delogo_watermark: bool = False
    delogo_watermark_rect: tuple[float, float, float, float] | None = None
    delogo_watermark_mode: str = "delogo"
    delogo_custom_rect: tuple[float, float, float, float] | None = None
    delogo_custom_mode: Literal["delogo", "boxblur", "inpaint"] = "inpaint"


@dataclass
class VideoCreatorRequest:
    """Đầu vào kích hoạt toàn bộ Pipeline xuất bản video E2E."""
    original_video_path: str
    segments: list[SubtitleSegment]
    output_video_path: str
    workspace_dir: str = ""
    config: VideoCreatorConfig = field(default_factory=VideoCreatorConfig)
    progress_callback: ProgressCallback | None = None
    is_cancelled_func: CancelledFunc | None = None


@dataclass
class VideoCreatorResult:
    """Đầu ra báo cáo kết quả toàn diện của Pipeline xuất bản video."""
    output_video_path: str = ""
    output_audio_path: str = ""
    session_dir: str = ""

    video_duration: float = 0.0
    audio_duration: float = 0.0
    final_video_duration: float = 0.0

    total_segments: int = 0
    tts_generated_count: int = 0
    tts_skipped_count: int = 0

    subtitles_rendered_count: int = 0
    subtitles_skipped_count: int = 0

    status: Literal["success", "failed", "cancelled"] = "success"
    cancelled_stage: str = ""

    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi kết quả thành dictionary an toàn cho serialize/UI."""
        return asdict(self)


class VideoCreatorService:
    """Orchestrator điều phối tuần tự chuỗi xử lý tạo video hoàn chỉnh."""

    def __init__(
        self,
        *,
        voice_mapping_service: Any = None,
        tts_pipeline_service: Any = None,
        voiceover_service: Any = None,
        duration_fitting_service: Any = None,
        original_audio_extractor: Any = None,
        audio_mixing_service: Any = None,
        video_export_service: Any = None,
        stream_prober: Any = None,
    ):
        # Service dependencies được inject hoặc khởi tạo lười (lazy)
        # Tuyệt đối không gọi TTS hay FFmpeg khi import hoặc khởi tạo service
        self.voice_mapping_service = voice_mapping_service
        self.tts_pipeline_service = tts_pipeline_service
        self.voiceover_service = voiceover_service
        self.duration_fitting_service = duration_fitting_service
        self.original_audio_extractor = original_audio_extractor
        self.audio_mixing_service = audio_mixing_service
        self.video_export_service = video_export_service
        self.stream_prober = stream_prober

    def _validate_preflight(self, request: VideoCreatorRequest) -> VideoCreatorResult | None:
        """Thực thi Preflight Gate xác thực fail-fast và kiểm tra cancellation sớm.
        
        Returns:
            VideoCreatorResult nếu phát hiện lỗi hoặc bị hủy sớm (dừng pipeline).
            None nếu Preflight hoàn toàn hợp lệ (cho phép tiếp tục).
        """
        # 1. Check cancellation ngay đầu Preflight
        if request.is_cancelled_func and request.is_cancelled_func():
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                total_segments=len(request.segments),
                status="cancelled",
                cancelled_stage="preflight",
                error="",
            )

        # 2. Validate original_video_path tồn tại
        if not request.original_video_path or not os.path.isfile(request.original_video_path):
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                total_segments=len(request.segments),
                status="failed",
                error=f"Original video file not found: '{request.original_video_path}'",
            )

        # 3. Validate output_video_path đuôi .mp4
        if not str(request.output_video_path or "").lower().endswith(".mp4"):
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                total_segments=len(request.segments),
                status="failed",
                error=f"output_video_path must use .mp4 extension (got '{request.output_video_path}')",
            )

        # 4. Validate output collision với input video
        orig_vid_abs = os.path.abspath(request.original_video_path)
        out_vid_abs = os.path.abspath(request.output_video_path)
        if orig_vid_abs == out_vid_abs:
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                total_segments=len(request.segments),
                status="failed",
                error="output_video_path cannot overwrite original_video_path",
            )

        # 5. Validate toàn bộ segments (start >= 0 và end > start)
        for seg in request.segments:
            if seg.start < 0 or seg.end <= seg.start:
                return VideoCreatorResult(
                    output_video_path="",
                    output_audio_path="",
                    total_segments=len(request.segments),
                    status="failed",
                    error=f"Invalid segment timing: id={seg.id}, start={seg.start}, end={seg.end}",
                )

        # 6. Check cancellation cuối Preflight
        if request.is_cancelled_func and request.is_cancelled_func():
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                total_segments=len(request.segments),
                status="cancelled",
                cancelled_stage="preflight",
                error="",
            )

        return None

    def _resolve_voice_assignments(
        self, segments: list[SubtitleSegment], request: VideoCreatorRequest | None = None
    ) -> list[VoiceAssignment]:
        """Thực thi Stage 1: Voice Mapping & Eligibility Gate."""
        # Khởi tạo lười VoiceMappingService nếu chưa được inject
        mapping_svc = self.voice_mapping_service
        if mapping_svc is None:
            from app.services.voice_mapping_service import VoiceMappingService
            v_cfg = getattr(request.config, "voice_config", None) if request and hasattr(request, "config") else None
            mapping_svc = VoiceMappingService(config=v_cfg)

        assignments: list[VoiceAssignment] = []

        for seg in segments:
            seg_id = seg.id

            # 1. Đoạn nhiễu hoặc chủ động đánh dấu bỏ qua TTS
            if getattr(seg, "is_noise", False) or getattr(seg, "skip_tts", False):
                assignments.append(
                    VoiceAssignment(
                        segment_id=seg_id,
                        voice_id=None,
                        is_tts_eligible=False,
                        reason="noise_skip",
                    )
                )
                continue

            # 2. Không có nội dung bản dịch tiếng Việt để đọc
            trans_text = str(getattr(seg, "translated_text", "") or "").strip()
            if not trans_text:
                assignments.append(
                    VoiceAssignment(
                        segment_id=seg_id,
                        voice_id=None,
                        is_tts_eligible=False,
                        reason="empty_translation",
                    )
                )
                continue

            # 3. Đọc final_gender (nếu rỗng hoặc unknown thì fallback sang gender đã duyệt, TUYỆT ĐỐI KHÔNG đọc raw_gender)
            raw_final = str(getattr(seg, "final_gender", "") or "").lower().strip()
            if not raw_final or raw_final == "unknown":
                raw_final = str(getattr(seg, "gender", "unknown") or "unknown").lower().strip()

            if raw_final in ("female", "nữ", "nu"):
                final_g = "female"
            elif raw_final in ("male", "nam"):
                final_g = "male"
            else:
                final_g = raw_final

            # 4. unknown và none TUYỆT ĐỐI KHÔNG TTS
            if final_g in ("unknown", "none"):
                assignments.append(
                    VoiceAssignment(
                        segment_id=seg_id,
                        voice_id=None,
                        is_tts_eligible=False,
                        reason="unknown_gender",
                    )
                )
                continue

            # 5. Ánh xạ thuần túy theo final_gender qua mapping_svc.resolve_by_gender (không mutate segment)
            gender_res = mapping_svc.resolve_by_gender(final_g)
            if gender_res is not None:
                v_id = getattr(gender_res, "voice_id", str(gender_res))
                assignments.append(
                    VoiceAssignment(
                        segment_id=seg_id,
                        voice_id=v_id,
                        is_tts_eligible=True,
                        reason=f"{final_g}_mapping",
                    )
                )
            else:
                assignments.append(
                    VoiceAssignment(
                        segment_id=seg_id,
                        voice_id=None,
                        is_tts_eligible=False,
                        reason="no_voice_mapped",
                    )
                )

        return assignments

    def _orchestrate_tts(
        self,
        request: VideoCreatorRequest,
        assignments: list[VoiceAssignment],
        session_dir: str,
    ) -> tuple[list[TTSAudioBlock] | None, list[str], VideoCreatorResult | None]:
        """Thực thi Stage 2: TTS Orchestration (Contract 8.3.4 v1.1).
        
        Tuân thủ nghiêm ngặt 8 invariants:
        1. segments giữ nguyên trạng 100% (Read-Only).
        2. VoiceAssignment.voice_id được bảo toàn, CẤM gọi VoiceMappingService.
        3. Ineligible bypass toàn bộ chuỗi TTS (không Voiceover, không VieNeu, không Fitting, không block).
        4. Bắt buộc config.max_speedup_ratio <= 1.20 (vượt trần -> REJECT).
        5. Tách bạch 2 tầng: session_dir/raw_tts/ và session_dir/fitted_tts/ độc lập.
        6. Dual cancellation: check trước mỗi segment và ngay sau khi hoàn thành segment.
        7. Fail-fast: bất kỳ segment nào lỗi -> dừng toàn bộ pipeline TTS.
        8. Xuất ra list[TTSAudioBlock] canonical của Step 6.
        """
        # =====================================================================
        # 1. PRECONDITIONS & CONFIG CEILING VALIDATION
        # =====================================================================
        if request.config.max_speedup_ratio > 1.20:
            return None, [], VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=len(request.segments),
                status="failed",
                error=f"max_speedup_ratio ({request.config.max_speedup_ratio:.2f}) exceeds hard ceiling 1.20",
            )

        if len(request.segments) != len(assignments):
            return None, [], VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=len(request.segments),
                status="failed",
                error=f"Mismatch length between segments ({len(request.segments)}) and assignments ({len(assignments)})",
            )

        for seg, assign in zip(request.segments, assignments):
            if seg.id != assign.segment_id:
                return None, [], VideoCreatorResult(
                    output_video_path="",
                    output_audio_path="",
                    session_dir=session_dir,
                    total_segments=len(request.segments),
                    status="failed",
                    error=f"Assignment ID mismatch: segment_id={seg.id} != assignment_id={assign.segment_id}",
                )

        # =====================================================================
        # 2. KHỞI TẠO 2 TẦNG THƯ MỤC AUDIO & SERVICES CHUYÊN TRÁCH
        # =====================================================================
        raw_output_dir = os.path.join(session_dir, "raw_tts")
        fitted_output_dir = os.path.join(session_dir, "fitted_tts")
        os.makedirs(raw_output_dir, exist_ok=True)
        os.makedirs(fitted_output_dir, exist_ok=True)

        voiceover_svc = self.voiceover_service
        if voiceover_svc is None:
            voiceover_svc = VoiceoverService(raw_output_dir=raw_output_dir)

        fitting_svc = self.duration_fitting_service
        if fitting_svc is None:
            fitting_svc = DurationFittingService(
                fitted_output_dir=fitted_output_dir,
                max_speed=request.config.max_speedup_ratio,
            )

        tts_blocks: list[TTSAudioBlock] = []
        warnings: list[str] = []
        tts_generated_cnt = 0
        tts_skipped_cnt = 0
        total = len(request.segments)

        # =====================================================================
        # 3. VÒNG LẶP ĐIỀU PHỐI TỪNG SEGMENT
        # =====================================================================
        for i, (seg, assign) in enumerate(zip(request.segments, assignments), start=1):
            # 3.1. Checkpoint Cancellation (Pre-segment)
            if request.is_cancelled_func and request.is_cancelled_func():
                return None, warnings, VideoCreatorResult(
                    output_video_path="",
                    output_audio_path="",
                    session_dir=session_dir,
                    total_segments=total,
                    tts_generated_count=tts_generated_cnt,
                    tts_skipped_count=tts_skipped_cnt,
                    status="cancelled",
                    cancelled_stage="tts",
                    error="",
                )

            # 3.2. Check Eligibility (Ineligible bypass 100%)
            if not assign.is_tts_eligible:
                tts_skipped_cnt += 1
            else:
                # 3.3. Sinh Raw TTS WAV (qua VoiceoverService)
                raw_path = os.path.join(raw_output_dir, f"segment_{seg.id:04d}.wav")
                tts_res = voiceover_svc.generate(
                    segment_id=seg.id,
                    translated_text=seg.translated_text,
                    start=seg.start,
                    end=seg.end,
                    voice_id=assign.voice_id or "",
                    is_noise=getattr(seg, "is_noise", False),
                    skip_tts=getattr(seg, "skip_tts", False),
                    output_path=raw_path,
                )

                if tts_res.status == "failed":
                    return None, warnings, VideoCreatorResult(
                        output_video_path="",
                        output_audio_path="",
                        session_dir=session_dir,
                        total_segments=total,
                        tts_generated_count=tts_generated_cnt,
                        tts_skipped_count=tts_skipped_cnt,
                        status="failed",
                        error=f"TTS generation failed for segment {seg.id}: {tts_res.error}",
                    )

                # 3.4. Khớp thời lượng Duration Fitting (qua DurationFittingService)
                # Tự động chống đè giọng nói & Chống sụp đổ dây chuyền (Anti-domino Drift Guard):
                orig_start = round(float(seg.start), 3)
                orig_end = round(float(seg.end), 3)
                orig_dur = max(0.2, round(orig_end - orig_start, 3))

                # Cố định mốc bắt đầu tuyệt đối tại orig_start để lồng tiếng LUÔN khớp 100% với phụ đề hiển thị
                # Tuyệt đối không cho phép tích lũy độ trôi (Zero Cumulative Drift)
                actual_start = orig_start
                if tts_blocks:
                    prev_end = round(tts_blocks[-1].start_time + tts_blocks[-1].duration, 3)
                    # Nếu câu trước dài quá đè vào thời điểm bắt đầu của câu này:
                    if prev_end > orig_start:
                        # Cắt nhẹ đuôi và fade-out khối trước 20ms trước khi câu mới bắt đầu
                        target_prev_dur = max(0.1, round(orig_start - 0.02 - tts_blocks[-1].start_time, 3))
                        if target_prev_dur < tts_blocks[-1].duration:
                            try:
                                import subprocess
                                from runtime_paths import subprocess_hidden_kwargs
                                trimmed_prev = os.path.splitext(tts_blocks[-1].audio_path)[0] + "_trim.wav"
                                cmd = [
                                    fitting_svc.ffmpeg_bin, "-y",
                                    "-i", tts_blocks[-1].audio_path,
                                    "-t", f"{target_prev_dur:.3f}",
                                    "-af", f"afade=t=out:st={max(0.0, target_prev_dur - 0.05):.3f}:d=0.05",
                                    trimmed_prev,
                                ]
                                subprocess.run(cmd, check=True, capture_output=True, **subprocess_hidden_kwargs())
                                if os.path.isfile(trimmed_prev):
                                    tts_blocks[-1].audio_path = trimmed_prev
                            except Exception as exc:
                                print(f"[VideoCreator] Trimming previous audio notice: {exc}")
                            # Luôn đồng bộ duration để bảo đảm không bao giờ overlap
                            tts_blocks[-1].duration = target_prev_dur
                        # Câu mới LUÔN xuất phát chính xác tại orig_start
                        actual_start = orig_start

                # Xác định slot_dur cho câu hiện tại: Không bao giờ bị bóp nhỏ hơn orig_dur
                next_tts_start = None
                for future_seg, future_assign in zip(request.segments[i:], assignments[i:]):
                    if future_assign.is_tts_eligible:
                        next_tts_start = round(float(future_seg.start), 3)
                        break

                if next_tts_start is not None and next_tts_start > actual_start:
                    available_gap = round(next_tts_start - actual_start, 3)
                    slot_dur = max(orig_dur, min(available_gap, round(orig_dur * 1.25, 3)))
                else:
                    slot_dur = orig_dur

                fitted_path = os.path.join(fitted_output_dir, f"segment_{seg.id:04d}_fit.wav")
                fit_res = fitting_svc.fit_segment(
                    segment_id=seg.id,
                    raw_audio_path=tts_res.audio_path,
                    slot_duration=slot_dur,
                    output_path=fitted_path,
                )

                if fit_res.status == "failed":
                    return None, warnings, VideoCreatorResult(
                        output_video_path="",
                        output_audio_path="",
                        session_dir=session_dir,
                        total_segments=total,
                        tts_generated_count=tts_generated_cnt,
                        tts_skipped_count=tts_skipped_cnt,
                        status="failed",
                        error=f"Duration fitting failed for segment {seg.id}: {fit_res.error}",
                    )

                # Thu thập warning từ DurationFittingService nếu có
                if fit_res.warning:
                    warnings.append(f"Segment {seg.id}: {fit_res.warning}")

                # 3.5. Đóng gói Canonical TTSAudioBlock (Step 6 model)
                block = TTSAudioBlock(
                    segment_id=seg.id,
                    start_time=actual_start,
                    duration=fit_res.fitted_duration,
                    audio_path=fit_res.fitted_audio_path,
                    volume=1.0,
                )
                tts_blocks.append(block)
                tts_generated_cnt += 1

            # 3.6. Checkpoint Cancellation (Post-segment)
            if request.is_cancelled_func and request.is_cancelled_func():
                return None, warnings, VideoCreatorResult(
                    output_video_path="",
                    output_audio_path="",
                    session_dir=session_dir,
                    total_segments=total,
                    tts_generated_count=tts_generated_cnt,
                    tts_skipped_count=tts_skipped_cnt,
                    status="cancelled",
                    cancelled_stage="tts",
                    error="",
                )

            # 3.7. Cập nhật tiến độ đơn điệu từ 5% -> 55% theo i / total
            if request.progress_callback and total > 0:
                pct = 5.0 + 50.0 * (i / total)
                try:
                    request.progress_callback(
                        pct,
                        f"Xử lý thoại {i}/{total} ({tts_generated_cnt} hoàn tất, {tts_skipped_cnt} bỏ qua)",
                    )
                except Exception:
                    pass

        return tts_blocks, warnings, None

    def _orchestrate_mixing(
        self,
        request: VideoCreatorRequest,
        session_dir: str,
        tts_blocks: list[TTSAudioBlock],
    ) -> tuple[MixedAudioResult | None, list[str], VideoCreatorResult | None]:
        """Điều phối Stage 3: Hòa âm và ducking âm thanh (55% -> 75%).

        Tuân thủ nghiêm ngặt 11 Invariants của Contract 8.3.5 v1.1:
        - Invariant 1: Không tự chạy FFmpeg; ủy quyền trích xuất cho OriginalAudioExtractor, hòa âm cho AudioMixingService.
        - Invariant 2: request.config.duck_volume là nguồn chân lý duy nhất (đồng bộ instance).
        - Invariant 3: Chuyển tiếp canonical tts_blocks nguyên vẹn từ 8.3.4.
        - Invariant 4: Output cố định session_dir/extracted_original_audio.wav & session_dir/final_audio.wav.
        - Invariant 5: Zero-TTS (tts_blocks rỗng) vẫn gọi AudioMixingService.mix() copy 100% volume.
        - Invariant 6: Ba checkpoint cancellation (A: pre-prep, B: post-prep/pre-mix, C: post-mix).
        - Invariant 7: Fail-fast downstream; cấm xuất video khi mixing thất bại.
        - Invariant 8: Overlap detection do Step 6 xử lý fail-fast, Orchestrator propagate trung thực.
        - Invariant 9: Warning aggregation & metrics recording.
        - Invariant 10: Master Data request.segments bất biến.
        - Invariant 11: Progress đơn điệu từ 55.0% -> 75.0%.

        Returns:
            (mixed_result, warnings, error_or_cancelled_result)
        """
        warnings: list[str] = []
        total = len(request.segments)
        tts_gen_cnt = len(tts_blocks)
        tts_skip_cnt = total - tts_gen_cnt

        # ---------------------------------------------------------------------
        # 1. CANCELLATION CHECKPOINT A (Pre-preparation)
        # ---------------------------------------------------------------------
        if request.is_cancelled_func and request.is_cancelled_func():
            return None, warnings, VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=total,
                tts_generated_count=tts_gen_cnt,
                tts_skipped_count=tts_skip_cnt,
                status="cancelled",
                cancelled_stage="mixing",
                error="",
            )

        # ---------------------------------------------------------------------
        # 2. TIẾN ĐỘ 55%: Bắt đầu chuẩn bị âm thanh gốc
        # ---------------------------------------------------------------------
        if request.progress_callback:
            try:
                request.progress_callback(55.0, "Đang chuẩn bị âm thanh gốc từ video...")
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # 3. TRÍCH XUẤT VÀ CHUẨN HÓA ORIGINAL AUDIO (Level 2 Intermediate Artifact)
        # ---------------------------------------------------------------------
        extractor = self.original_audio_extractor or OriginalAudioExtractor()
        extracted_audio_path = os.path.join(session_dir, "extracted_original_audio.wav")

        try:
            ok, extract_err = extractor.extract(request.original_video_path, extracted_audio_path)
        except Exception as exc:
            ok, extract_err = False, str(exc)

        if not ok or not os.path.isfile(extracted_audio_path):
            return None, warnings, VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=total,
                tts_generated_count=tts_gen_cnt,
                tts_skipped_count=tts_skip_cnt,
                status="failed",
                error=f"Original audio extraction failed: {extract_err}",
            )

        # ---------------------------------------------------------------------
        # 4. CANCELLATION CHECKPOINT B (Post-preparation / Pre-mixing)
        # ---------------------------------------------------------------------
        if request.is_cancelled_func and request.is_cancelled_func():
            return None, warnings, VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=total,
                tts_generated_count=tts_gen_cnt,
                tts_skipped_count=tts_skip_cnt,
                status="cancelled",
                cancelled_stage="mixing",
                error="",
            )

        # ---------------------------------------------------------------------
        # 5. TIẾN ĐỘ 60%: Khởi tạo AudioMixingService & Đồng bộ config
        # ---------------------------------------------------------------------
        if request.progress_callback:
            try:
                request.progress_callback(60.0, "Đang tiến hành hòa âm và xử lý ducking âm thanh...")
            except Exception:
                pass

        orig_vol = float(getattr(request.config, "original_volume", 0.50))
        tts_vol = float(getattr(request.config, "tts_volume", 1.00))
        duck_vol = float(getattr(request.config, "duck_volume", 0.20))
        if orig_vol <= 0.001:
            duck_vol = 0.0

        mixing_svc = self.audio_mixing_service or AudioMixingService(
            duck_volume=duck_vol,
            normal_volume=orig_vol,
            tts_volume=tts_vol,
        )
        # Khóa Source of Truth cho duck_volume, normal_volume, tts_volume trong từng run
        if hasattr(mixing_svc, "duck_volume"):
            try:
                mixing_svc.duck_volume = duck_vol
            except Exception:
                pass
        if hasattr(mixing_svc, "normal_volume"):
            try:
                mixing_svc.normal_volume = orig_vol
            except Exception:
                pass
        if hasattr(mixing_svc, "tts_volume"):
            try:
                mixing_svc.tts_volume = tts_vol
            except Exception:
                pass

        # Artifact cố định (Level 3 Canonical Output)
        final_audio_path = os.path.join(session_dir, "final_audio.wav")

        # ---------------------------------------------------------------------
        # 6. THỰC THI HÒA ÂM (Step 6 Delegation)
        # ---------------------------------------------------------------------
        try:
            mixed_res = mixing_svc.mix(
                original_audio_path=extracted_audio_path,
                tts_blocks=tts_blocks,
                output_path=final_audio_path,
            )
        except Exception as exc:
            return None, warnings, VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=total,
                tts_generated_count=tts_gen_cnt,
                tts_skipped_count=tts_skip_cnt,
                status="failed",
                error=f"Audio mixing failed with exception: {exc}",
            )

        if mixed_res.status == "failed":
            return None, warnings, VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=total,
                tts_generated_count=tts_gen_cnt,
                tts_skipped_count=tts_skip_cnt,
                status="failed",
                error=f"Audio mixing failed: {mixed_res.error}",
            )

        # Thu thập warning từ AudioMixingService (ví dụ timeline overflow)
        if mixed_res.warning:
            warnings.append(mixed_res.warning)

        # ---------------------------------------------------------------------
        # 7. CANCELLATION CHECKPOINT C (Post-mixing)
        # ---------------------------------------------------------------------
        if request.is_cancelled_func and request.is_cancelled_func():
            aud_path = mixed_res.final_audio_path if (mixed_res.final_audio_path and os.path.isfile(mixed_res.final_audio_path)) else ""
            return None, warnings, VideoCreatorResult(
                output_video_path="",
                output_audio_path=aud_path,
                audio_duration=mixed_res.total_duration,
                session_dir=session_dir,
                total_segments=total,
                tts_generated_count=tts_gen_cnt,
                tts_skipped_count=tts_skip_cnt,
                warnings=warnings,
                status="cancelled",
                cancelled_stage="mixing",
                error="",
            )

        # ---------------------------------------------------------------------
        # 8. TIẾN ĐỘ 75%: Hoàn tất Stage 3 Audio Mixing & Ducking
        # ---------------------------------------------------------------------
        if request.progress_callback:
            try:
                request.progress_callback(
                    75.0,
                    f"Hòa âm hoàn tất: thời lượng audio {mixed_res.total_duration:.2f}s",
                )
            except Exception:
                pass

        return mixed_res, warnings, None

    def _orchestrate_export(
        self,
        request: VideoCreatorRequest,
        session_dir: str,
        final_audio_path: str,
    ) -> tuple[VideoExportResult | None, list[str], VideoCreatorResult | None]:
        """Điều phối Stage 4: Xuất bản video hoàn chỉnh và gắn phụ đề Hardsub (75% -> 95%).

        Tuân thủ nghiêm ngặt 10 Invariants của Contract 8.3.6 v1.1:
        - Invariant 1: Không tự can thiệp FFmpeg hay tạo SRT; ủy quyền duy nhất cho VideoExportService.
        - Invariant 2: Config propagation trực tiếp (overflow_policy, subtitle_config).
        - Invariant 3: Nhận input artifact continuity từ Stage 3 (session_dir/final_audio.wav).
        - Invariant 4: Master Data request.segments hoàn toàn READ-ONLY.
        - Invariant 5: Zero-subtitles pass-through (không lỗi khi không có sub).
        - Invariant 6: Hai checkpoints cancellation (A: pre-export, B: post-export giữ nguyên output artifact).
        - Invariant 7: Deterministic error & exception handling; dừng ngay nếu thất bại, không sang Stage 5.
        - Invariant 8: Warning aggregation lên VideoCreatorResult.
        - Invariant 9: Ghi nhận 3 thời lượng độc lập và subtitle metrics.
        - Invariant 10: Progress đơn điệu từ 75.0% -> 95.0%.

        Returns:
            (export_result, warnings, error_or_cancelled_result)
        """
        warnings: list[str] = []
        total = len(request.segments)

        # ---------------------------------------------------------------------
        # 1. CANCELLATION CHECKPOINT A (Pre-export)
        # ---------------------------------------------------------------------
        if request.is_cancelled_func and request.is_cancelled_func():
            aud_path = final_audio_path if (final_audio_path and os.path.isfile(final_audio_path)) else ""
            return None, warnings, VideoCreatorResult(
                output_video_path="",
                output_audio_path=aud_path,
                session_dir=session_dir,
                total_segments=total,
                status="cancelled",
                cancelled_stage="export",
                error="",
            )

        # ---------------------------------------------------------------------
        # 2. TIẾN ĐỘ 75%: Bắt đầu xuất bản video
        # ---------------------------------------------------------------------
        if request.progress_callback:
            try:
                request.progress_callback(75.0, "Bắt đầu xuất bản video và gắn phụ đề...")
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # 3. KHỞI TẠO EXPORT SERVICE (KHÔNG ÉP THAM SỐ TEMP_DIR)
        # ---------------------------------------------------------------------
        export_svc = (
            self.video_export_service
            if self.video_export_service is not None
            else VideoExportService()
        )

        export_req = VideoExportRequest(
            original_video_path=request.original_video_path,
            final_audio_path=final_audio_path,
            segments=request.segments,
            output_video_path=request.output_video_path,
            overflow_policy=request.config.overflow_policy,
            subtitle_config=request.config.subtitle_config,
            enable_blur_mask=getattr(request.config, "enable_blur_mask", True),
            mask_mode=getattr(request.config, "mask_mode", "box"),
            blur_rect=getattr(request.config, "blur_rect", None),
            enable_brand_logo=getattr(request.config, "enable_brand_logo", False),
            brand_logo_path=getattr(request.config, "brand_logo_path", ""),
            brand_logo_position=getattr(request.config, "brand_logo_position", "top_left"),
            brand_logo_size_percent=getattr(request.config, "brand_logo_size_percent", 15),
            brand_logo_opacity=getattr(request.config, "brand_logo_opacity", 1.0),
            enable_watermark=getattr(request.config, "enable_watermark", False),
            watermark_text=getattr(request.config, "watermark_text", ""),
            watermark_position=getattr(request.config, "watermark_position", "center"),
            watermark_font_size=getattr(request.config, "watermark_font_size", 36),
            watermark_opacity=getattr(request.config, "watermark_opacity", 0.35),
            watermark_color=getattr(request.config, "watermark_color", "#FFFFFF"),
            delogo_bilibili=getattr(request.config, "delogo_bilibili", False),
            delogo_watermark=getattr(request.config, "delogo_watermark", False),
            delogo_watermark_rect=getattr(request.config, "delogo_watermark_rect", None),
            delogo_watermark_mode=getattr(request.config, "delogo_watermark_mode", "delogo"),
            delogo_custom_rect=getattr(request.config, "delogo_custom_rect", None),
            delogo_custom_mode=getattr(request.config, "delogo_custom_mode", "delogo"),
        )

        # ---------------------------------------------------------------------
        # 4. GỌI EXPORT_VIDEO VỚI EXCEPTION HANDLING TẤT ĐỊNH
        # ---------------------------------------------------------------------
        aud_path = final_audio_path if (final_audio_path and os.path.isfile(final_audio_path)) else ""
        try:
            export_res = export_svc.export_video(export_req)
        except Exception as exc:
            return None, warnings, VideoCreatorResult(
                output_video_path="",
                output_audio_path=aud_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Video export failed with exception: {exc}",
            )

        if export_res.status == "cancelled":
            return None, warnings, VideoCreatorResult(
                output_video_path="",
                output_audio_path=aud_path,
                session_dir=session_dir,
                total_segments=total,
                status="cancelled",
                cancelled_stage="export",
                error="",
            )

        if export_res.status == "failed":
            vid_path = export_res.output_video_path if (export_res.output_video_path and os.path.isfile(export_res.output_video_path)) else ""
            return None, warnings, VideoCreatorResult(
                output_video_path=vid_path,
                output_audio_path=aud_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Video export failed: {export_res.error}",
            )

        # Thu thập cảnh báo từ VideoExportService (ví dụ freeze_end warning)
        if export_res.warning:
            warnings.append(export_res.warning)

        # ---------------------------------------------------------------------
        # 5. CANCELLATION CHECKPOINT B (Post-export)
        # ---------------------------------------------------------------------
        # Bảo toàn output_video_path đã tạo trên đĩa, trả về cancelled và không sang Stage 5
        if request.is_cancelled_func and request.is_cancelled_func():
            out_vid = export_res.output_video_path or request.output_video_path
            vid_path = out_vid if (out_vid and os.path.isfile(out_vid)) else ""
            return None, warnings, VideoCreatorResult(
                output_video_path=vid_path,
                output_audio_path=aud_path,
                video_duration=export_res.video_duration,
                audio_duration=export_res.audio_duration,
                final_video_duration=export_res.final_video_duration,
                subtitles_rendered_count=export_res.rendered_subtitles_count,
                subtitles_skipped_count=export_res.skipped_subtitles_count,
                session_dir=session_dir,
                total_segments=total,
                warnings=warnings,
                status="cancelled",
                cancelled_stage="export",
                error="",
            )

        # ---------------------------------------------------------------------
        # 6. TIẾN ĐỘ 95%: Hoàn tất Stage 4 Video Export
        # ---------------------------------------------------------------------
        if request.progress_callback:
            try:
                request.progress_callback(
                    95.0,
                    f"Xuất video hoàn tất: thời lượng {export_res.final_video_duration:.2f}s",
                )
            except Exception:
                pass

        return export_res, warnings, None

    def _orchestrate_verification(
        self,
        request: VideoCreatorRequest,
        session_dir: str,
        final_audio_path: str,
        export_res: VideoExportResult,
    ) -> tuple[float, VideoCreatorResult | None]:
        """Điều phối Stage 5: Kiểm định hậu xuất xưởng và hoàn thiện vòng đời workspace (95% -> 100%).

        Tuân thủ nghiêm ngặt 8 Tiêu chí và các Invariant của Contract 8.3.7 v1.1:
        1. Cancellation Checkpoint (Pre-verification): Bảo toàn Level 3 artifact.
        2. Tiêu chí 1: File Existence & Non-Zero Size.
        3. Tiêu chí 2: MP4 Container Parseability (actual duration > 0.0s).
        4. Tiêu chí 3: Final Stream & Codec Integrity (H.264 video + AAC stereo 44.1kHz audio).
        5. Tiêu chí 4: Duration Consistency (|actual - export_final| <= 0.5s).
        6. Tiêu chí 5: Bảng quy chuẩn Overflow Duration Policy (4 trường hợp).
        7. Tiêu chí 6: Subtitle Count (rendered + skipped == total).
        8. Tiêu chí 7: Master Data Immutability.
        9. Level 2 Intermediate Cleanup (chỉ khi 8 tiêu chí trên đã PASS; nếu lỗi: status='failed' nhưng giữ Level 3).
        10. Progress 100% & Final Result.

        Returns:
            (actual_final_duration, error_or_cancelled_result)
        """
        total = len(request.segments)
        out_vid = request.output_video_path

        # ---------------------------------------------------------------------
        # 1. CANCELLATION CHECKPOINT (Pre-verification)
        # ---------------------------------------------------------------------
        # Bảo toàn output_video.mp4 và final_audio.wav, KHÔNG chạy cleanup, KHÔNG báo progress 100%
        if request.is_cancelled_func and request.is_cancelled_func():
            vid_path = out_vid if (out_vid and os.path.isfile(out_vid)) else ""
            aud_path = final_audio_path if (final_audio_path and os.path.isfile(final_audio_path)) else ""
            return 0.0, VideoCreatorResult(
                output_video_path=vid_path,
                output_audio_path=aud_path,
                session_dir=session_dir,
                video_duration=export_res.video_duration,
                audio_duration=export_res.audio_duration,
                final_video_duration=export_res.final_video_duration,
                total_segments=total,
                subtitles_rendered_count=export_res.rendered_subtitles_count,
                subtitles_skipped_count=export_res.skipped_subtitles_count,
                status="cancelled",
                cancelled_stage="verification",
                error="",
            )

        # ---------------------------------------------------------------------
        # 2. PROGRESS 95%: Bắt đầu kiểm định chất lượng video
        # ---------------------------------------------------------------------
        if request.progress_callback:
            try:
                request.progress_callback(95.0, "Đang kiểm định chất lượng video xuất xưởng...")
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # 3. TIÊU CHÍ 1: FILE EXISTENCE & SIZE > 0
        # ---------------------------------------------------------------------
        if not os.path.isfile(out_vid):
            aud_path = final_audio_path if (final_audio_path and os.path.isfile(final_audio_path)) else ""
            return 0.0, VideoCreatorResult(
                output_video_path="",
                output_audio_path=aud_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Output video file is missing: '{out_vid}'",
            )

        file_size = os.path.getsize(out_vid)
        if file_size <= 0:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Output video file is empty (0 bytes): '{out_vid}'",
            )

        # ---------------------------------------------------------------------
        # 4. TIÊU CHÍ 2: MP4 CONTAINER PARSEABILITY (ACTUAL DURATION > 0.0s)
        # ---------------------------------------------------------------------
        actual_dur = measure_media_duration(out_vid)
        if actual_dur <= 0.0:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Output video is corrupted or unreadable (duration {actual_dur}s): '{out_vid}'",
            )

        # ---------------------------------------------------------------------
        # 5. TIÊU CHÍ 3: FINAL STREAM & CODEC INTEGRITY (H.264 + AAC 44.1kHz Stereo)
        # ---------------------------------------------------------------------
        if self.stream_prober is not None:
            ok, streams, probe_err = self.stream_prober(out_vid)
        else:
            ok, streams, probe_err = probe_media_streams(out_vid)

        if not ok:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Failed to probe output video streams: {probe_err}",
            )

        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        if not video_streams:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error="Output media stream integrity check failed: missing video stream",
            )

        v_codec = str(video_streams[0].get("codec_name", "")).lower()
        if v_codec != "h264":
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Output video stream codec mismatch: expected 'h264', got '{v_codec}'",
            )

        if not audio_streams:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error="Output media stream integrity check failed: missing audio stream",
            )

        a_codec = str(audio_streams[0].get("codec_name", "")).lower()
        if a_codec != "aac":
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Output audio stream codec mismatch: expected 'aac', got '{a_codec}'",
            )

        try:
            a_channels = int(audio_streams[0].get("channels", 0))
        except (ValueError, TypeError):
            a_channels = 0

        if a_channels != 2:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Output audio stream channels mismatch: expected 2 (stereo), got {a_channels}",
            )

        try:
            a_rate = int(audio_streams[0].get("sample_rate", 0))
        except (ValueError, TypeError):
            a_rate = 0

        if a_rate != 44100:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=f"Output audio stream sample_rate mismatch: expected 44100, got {a_rate}",
            )

        # ---------------------------------------------------------------------
        # 6. TIÊU CHÍ 4: DURATION CONSISTENCY (|actual - export_reported| <= 0.5s)
        # ---------------------------------------------------------------------
        if abs(actual_dur - export_res.final_video_duration) > 0.5:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=(
                    f"Duration consistency check failed: measured duration ({actual_dur:.2f}s) "
                    f"deviates from exported duration ({export_res.final_video_duration:.2f}s) by > 0.5s"
                ),
            )

        # ---------------------------------------------------------------------
        # 7. TIÊU CHÍ 5: BẢNG QUY CHUẨN OVERFLOW DURATION POLICY (4 TRƯỜNG HỢP)
        # ---------------------------------------------------------------------
        t_vid = export_res.video_duration
        t_aud = export_res.audio_duration
        policy = request.config.overflow_policy

        if policy == "freeze_end" and t_aud > t_vid:
            expected_policy_dur = t_aud
        else:
            expected_policy_dur = t_vid

        if expected_policy_dur > 0 and abs(actual_dur - expected_policy_dur) > 0.5:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=(
                    f"Overflow duration policy check failed: measured duration ({actual_dur:.2f}s) "
                    f"does not match expected policy duration ({expected_policy_dur:.2f}s, policy='{policy}')"
                ),
            )

        # ---------------------------------------------------------------------
        # 8. TIÊU CHÍ 6: SUBTITLE COUNTS COMPLETENESS
        # ---------------------------------------------------------------------
        sub_total = export_res.rendered_subtitles_count + export_res.skipped_subtitles_count
        if sub_total != total:
            return 0.0, VideoCreatorResult(
                output_video_path=out_vid,
                output_audio_path=final_audio_path,
                session_dir=session_dir,
                total_segments=total,
                status="failed",
                error=(
                    f"Subtitle count completeness check failed: rendered ({export_res.rendered_subtitles_count}) "
                    f"+ skipped ({export_res.skipped_subtitles_count}) = {sub_total} != total segments ({total})"
                ),
            )

        # ---------------------------------------------------------------------
        # 9. LEVEL 2 INTERMEDIATE CLEANUP (Chỉ chạy khi toàn bộ kiểm định đã PASS)
        # ---------------------------------------------------------------------
        if request.config.cleanup_intermediate_audio:
            raw_dir = os.path.join(session_dir, "raw_tts")
            fitted_dir = os.path.join(session_dir, "fitted_tts")
            ext_audio = os.path.join(session_dir, "extracted_original_audio.wav")
            try:
                if os.path.isdir(raw_dir):
                    shutil.rmtree(raw_dir)
                if os.path.isdir(fitted_dir):
                    shutil.rmtree(fitted_dir)
                if os.path.isfile(ext_audio):
                    os.remove(ext_audio)
            except Exception as cleanup_exc:
                # Cleanup failure -> status='failed', nhưng Level 3 (final_audio & output_video) BẢO TỒN NGUYÊN VẸN!
                return 0.0, VideoCreatorResult(
                    output_video_path=out_vid,
                    output_audio_path=final_audio_path,
                    session_dir=session_dir,
                    video_duration=export_res.video_duration,
                    audio_duration=export_res.audio_duration,
                    final_video_duration=actual_dur,
                    total_segments=total,
                    subtitles_rendered_count=export_res.rendered_subtitles_count,
                    subtitles_skipped_count=export_res.skipped_subtitles_count,
                    status="failed",
                    error=f"Workspace intermediate cleanup failed: {cleanup_exc}",
                )

        # ---------------------------------------------------------------------
        # 10. TIẾN ĐỘ 100%: Hoàn tất pipeline thành công
        # ---------------------------------------------------------------------
        if request.progress_callback:
            try:
                request.progress_callback(100.0, "Xuất bản video thành công!")
            except Exception:
                pass

        return actual_dur, None

    def run(self, request: VideoCreatorRequest) -> VideoCreatorResult:
        """Thực thi pipeline E2E (Preflight -> Mapping -> TTS -> Mixing -> Export -> Verification)."""
        # =====================================================================
        # PREFLIGHT GATE (Fail-fast validation)
        # =====================================================================
        preflight_error_result = self._validate_preflight(request)
        if preflight_error_result is not None:
            return preflight_error_result

        # =====================================================================
        # KHỞI TẠO SESSION WORKSPACE
        # =====================================================================
        if request.workspace_dir:
            session_dir = request.workspace_dir
        else:
            out_dir = os.path.dirname(os.path.abspath(request.output_video_path)) or "."
            session_dir = os.path.join(out_dir, f"session_{int(time.time() * 1000)}")
        os.makedirs(session_dir, exist_ok=True)

        all_warnings: list[str] = []

        # =====================================================================
        # STAGE 1: VOICE MAPPING & ELIGIBILITY GATE (0% -> 5%)
        # =====================================================================
        # 1.1. Checkpoint Cancellation (Pre-mapping)
        if request.is_cancelled_func and request.is_cancelled_func():
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=len(request.segments),
                status="cancelled",
                cancelled_stage="mapping",
                error="",
            )

        try:
            assignments = self._resolve_voice_assignments(request.segments, request=request)
        except Exception as exc:
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=len(request.segments),
                status="failed",
                error=f"Voice mapping failed: {exc}",
            )

        # 1.2. Checkpoint Cancellation (Post-mapping)
        if request.is_cancelled_func and request.is_cancelled_func():
            return VideoCreatorResult(
                output_video_path="",
                output_audio_path="",
                session_dir=session_dir,
                total_segments=len(request.segments),
                status="cancelled",
                cancelled_stage="mapping",
                error="",
            )

        tts_eligible_cnt = sum(1 for a in assignments if a.is_tts_eligible)
        tts_skipped_cnt = len(assignments) - tts_eligible_cnt

        if request.progress_callback:
            try:
                request.progress_callback(5.0, f"Phân vai hoàn tất: {tts_eligible_cnt} câu lồng tiếng, {tts_skipped_cnt} câu bỏ qua")
            except Exception:
                pass

        # =====================================================================
        # STAGE 2: TTS ORCHESTRATION & FITTING (5% -> 55%)
        # =====================================================================
        tts_blocks, tts_warnings, tts_error_result = self._orchestrate_tts(
            request, assignments, session_dir
        )
        if tts_warnings:
            all_warnings.extend(tts_warnings)

        if tts_error_result is not None:
            tts_error_result.warnings = list(all_warnings)
            return tts_error_result

        # =====================================================================
        # STAGE 3: AUDIO MIXING & DUCKING ORCHESTRATION (55% -> 75%)
        # =====================================================================
        mixed_res, mix_warnings, mix_error_result = self._orchestrate_mixing(
            request, session_dir, tts_blocks or []
        )
        if mix_warnings:
            all_warnings.extend(mix_warnings)

        if mix_error_result is not None:
            mix_error_result.warnings = list(all_warnings)
            return mix_error_result

        # =====================================================================
        # STAGE 4: VIDEO EXPORT ORCHESTRATION (75% -> 95%)
        # =====================================================================
        final_audio_path = mixed_res.final_audio_path if mixed_res else ""
        export_res, export_warnings, export_error_result = self._orchestrate_export(
            request, session_dir, final_audio_path
        )
        if export_warnings:
            all_warnings.extend(export_warnings)

        if export_error_result is not None:
            export_error_result.warnings = list(all_warnings)
            return export_error_result

        # =====================================================================
        # STAGE 5: VERIFICATION & POSTFLIGHT CHECK (95% -> 100%)
        # =====================================================================
        actual_final_dur, verify_error_result = self._orchestrate_verification(
            request, session_dir, final_audio_path, export_res
        )
        if verify_error_result is not None:
            verify_error_result.warnings = list(all_warnings)
            return verify_error_result

        # Thành công toàn diện toàn bộ Pipeline E2E
        # =====================================================================
        # CLEANUP: Xóa thư mục session tạm (audio/TTS trung gian) để tiết kiệm ổ đĩa
        # Chỉ giữ lại file video cuối cùng trong output
        # =====================================================================
        try:
            if session_dir and os.path.isdir(session_dir):
                shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass  # Không để lỗi cleanup ảnh hưởng kết quả

        return VideoCreatorResult(
            output_video_path=export_res.output_video_path if export_res else request.output_video_path,
            output_audio_path=final_audio_path,
            session_dir="",  # Đã dọn dẹp
            video_duration=export_res.video_duration if export_res else 0.0,
            audio_duration=export_res.audio_duration if export_res else 0.0,
            final_video_duration=actual_final_dur,
            total_segments=len(request.segments),
            tts_generated_count=len(tts_blocks) if tts_blocks else 0,
            tts_skipped_count=len(request.segments) - (len(tts_blocks) if tts_blocks else 0),
            subtitles_rendered_count=export_res.rendered_subtitles_count if export_res else 0,
            subtitles_skipped_count=export_res.skipped_subtitles_count if export_res else 0,
            warnings=all_warnings,
            status="success",
        )

    execute = run



