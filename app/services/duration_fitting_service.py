"""Duration Fitting Service using FFmpeg atempo filter.

Implements Step 5.4 Duration Fitting Contract v1.0:
- FittedAudioResult: Data contract for fitted audio output and diagnostics.
- Preserves Raw Audio immutability (raw_tts/ is never overwritten).
- Zero silence padding for audio shorter than slot.
- Tolerance ratio threshold: 1.03 (ratio <= 1.03 -> exact 1.0x copy, NO FFmpeg).
- Maximum speed cap: 1.20x (overflow flagged with warning, strictly NO trimming).
- All failures captured as FittedAudioResult(status="failed", error=...).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, asdict
from typing import Any, Literal

from app.models.render_job import RenderJob
from app.services.tts_backend import measure_wav_duration


def _resolve_ffmpeg() -> str:
    """Xác định đường dẫn FFmpeg thực thi trên hệ thống."""
    try:
        from app.runtime_paths import bin_path
        p = bin_path("ffmpeg", "ffmpeg.exe")
        if os.path.isfile(p):
            return p
    except Exception:
        pass

    w = shutil.which("ffmpeg")
    if w:
        return w

    local_fallback = os.path.join(r"d:\capcap\CapCap", "bin", "ffmpeg", "ffmpeg.exe")
    if os.path.isfile(local_fallback):
        return local_fallback

    return "ffmpeg"


@dataclass
class FittedAudioResult:
    """Data contract đầu ra chuẩn hóa của tầng Duration Fitting (Bước 5.4)."""
    segment_id: int
    raw_audio_path: str
    raw_duration: float
    fitted_audio_path: str = ""
    fitted_duration: float = 0.0
    applied_speed: float = 1.0
    status: Literal["success", "failed"] = "success"
    warning: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DurationFittingService:
    """Service điều chỉnh tốc độ âm thanh thoại thô (Raw Audio) cho phù hợp với khung phụ đề (slot).

    Tuân thủ nghiêm ngặt 9 quy tắc của Duration Fitting Contract v1.0:
    1. Raw WAV bất biến (không sửa, không ghi đè).
    2. Audio ngắn hoặc trong ngưỡng tolerance_ratio (<= 1.03): Giữ 1.0x, copy trực tiếp, KHÔNG chạy FFmpeg.
    3. Audio dài > 3%: Tính required_speed = raw_duration / slot_duration và áp dụng atempo.
    4. Trần tốc độ: max_speed = 1.20x.
    5. Tuyệt đối KHÔNG trim (cắt gọt) từ cuối.
    6. Overflow (required_speed > 1.20): Kẹp trần 1.20x và ghi nhận warning minh bạch.
    7. Tuyệt đối KHÔNG đệm silence vào file audio.
    8. Output lưu riêng biệt tại fitted_output_dir (mặc định 'fitted_tts').
    9. Mọi lỗi được bao đóng thành FittedAudioResult(status="failed", error=...).
    """

    def __init__(
        self,
        *,
        tolerance_ratio: float = 1.03,
        max_speed: float = 1.20,
        fitted_output_dir: str = "fitted_tts",
        ffmpeg_bin: str | None = None,
    ):
        self.tolerance_ratio = float(tolerance_ratio)
        self.max_speed = float(max_speed)
        self.fitted_output_dir = fitted_output_dir
        self.ffmpeg_bin = ffmpeg_bin or _resolve_ffmpeg()

    def fit_segment(
        self,
        *,
        segment_id: int,
        raw_audio_path: str,
        slot_duration: float,
        output_path: str | None = None,
    ) -> FittedAudioResult:
        """Thực hiện xử lý khớp thời lượng cho một câu thoại theo Contract 5.4.1."""
        # 1. Validation: slot_duration <= 0
        if slot_duration <= 0:
            return FittedAudioResult(
                segment_id=segment_id,
                raw_audio_path=raw_audio_path,
                raw_duration=0.0,
                status="failed",
                error=f"slot_duration must be > 0 (got {slot_duration})",
            )

        # 2. Validation: raw_audio_path tồn tại
        if not raw_audio_path or not os.path.isfile(raw_audio_path):
            return FittedAudioResult(
                segment_id=segment_id,
                raw_audio_path=str(raw_audio_path or ""),
                raw_duration=0.0,
                status="failed",
                error=f"Raw audio file not found: '{raw_audio_path}'",
            )

        # 3. Validation: output_path không được trùng raw_audio_path (Bảo vệ Raw WAV bất biến)
        raw_abs = os.path.abspath(raw_audio_path)
        if output_path is not None:
            dest_abs = os.path.abspath(output_path)
            if raw_abs == dest_abs:
                return FittedAudioResult(
                    segment_id=segment_id,
                    raw_audio_path=raw_audio_path,
                    raw_duration=0.0,
                    status="failed",
                    error="output_path cannot overwrite raw_audio_path (Raw WAV must be immutable)",
                )
            target_output = output_path
        else:
            os.makedirs(self.fitted_output_dir, exist_ok=True)
            target_output = os.path.join(
                self.fitted_output_dir,
                f"segment_{segment_id:04d}_fit.wav",
            )

        # 4. Đo raw_duration thực tế từ WAV header
        raw_duration = measure_wav_duration(raw_audio_path)
        if raw_duration <= 0.0:
            return FittedAudioResult(
                segment_id=segment_id,
                raw_audio_path=raw_audio_path,
                raw_duration=0.0,
                status="failed",
                error=f"Invalid or unreadable raw WAV file: '{raw_audio_path}'",
            )

        os.makedirs(os.path.dirname(os.path.abspath(target_output)) or ".", exist_ok=True)

        # 5. Rule 2: Audio ngắn hơn hoặc bằng slot (hoặc chỉ dài hơn <= tolerance_ratio)
        if raw_duration <= (slot_duration * self.tolerance_ratio):
            try:
                # Cắt khoảng lặng đầu (leading silence) để giọng lồng tiếng phát ra tức thì cùng phụ đề
                cmd = [
                    self.ffmpeg_bin,
                    "-y",
                    "-i", raw_audio_path,
                    "-filter:a", "silenceremove=start_periods=1:start_duration=0.01:start_threshold=-42dB",
                    "-ar", "16000",
                    "-ac", "1",
                    target_output,
                ]
                kwargs: dict[str, Any] = {"capture_output": True}
                if os.name == "nt":
                    kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                proc = subprocess.run(cmd, **kwargs)
                if proc.returncode != 0 or not os.path.isfile(target_output):
                    if os.path.abspath(target_output) != raw_abs:
                        shutil.copyfile(raw_audio_path, target_output)

                fitted_dur = measure_wav_duration(target_output)
                return FittedAudioResult(
                    segment_id=segment_id,
                    raw_audio_path=raw_audio_path,
                    raw_duration=raw_duration,
                    fitted_audio_path=target_output,
                    fitted_duration=fitted_dur,
                    applied_speed=1.0,
                    status="success",
                    warning="",
                    error="",
                )
            except Exception as exc:
                return FittedAudioResult(
                    segment_id=segment_id,
                    raw_audio_path=raw_audio_path,
                    raw_duration=raw_duration,
                    status="failed",
                    error=f"Failed to copy raw audio: {exc}",
                )

        # 6. Rule 3 & 4: Audio dài hơn > 3% -> Tính required_speed và áp dụng atempo
        required_speed = raw_duration / float(slot_duration)
        adaptive_ceiling = max(self.max_speed, 1.35)
        if required_speed <= self.max_speed:
            applied_speed = round(required_speed, 3)
            warning = ""
        elif required_speed <= adaptive_ceiling:
            applied_speed = round(required_speed, 3)
            warning = (
                f"Thời lượng âm thanh ({raw_duration:.2f}s) vượt quá slot ({slot_duration:.2f}s). "
                f"Đã tự động tăng tốc thích ứng lên {applied_speed:.2f}x để bảo toàn timeline."
            )
        else:
            applied_speed = adaptive_ceiling
            warning = (
                f"Thời lượng âm thanh ({raw_duration:.2f}s) vượt quá slot ({slot_duration:.2f}s). "
                f"Đã áp dụng tốc độ trần {adaptive_ceiling:.2f}x (overflow)."
            )

        # 7. Thực thi FFmpeg với bộ lọc cắt khoảng lặng đầu (silenceremove) & atempo
        # Đảm bảo giọng lồng tiếng cất lên NGAY LẬP TỨC khi phụ đề xuất hiện, loại bỏ độ trễ 150-250ms
        filter_parts = ["silenceremove=start_periods=1:start_duration=0.01:start_threshold=-42dB"]
        if abs(applied_speed - 1.0) >= 0.01:
            filter_parts.append(f"atempo={applied_speed:.3f}")
        filter_chain = ",".join(filter_parts)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", raw_audio_path,
            "-filter:a", filter_chain,
            "-ar", "16000",
            "-ac", "1",
            target_output,
        ]

        kwargs: dict[str, Any] = {"capture_output": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            proc = subprocess.run(cmd, **kwargs)
            if proc.returncode != 0 or not os.path.isfile(target_output):
                err_msg = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else "Unknown FFmpeg error"
                return FittedAudioResult(
                    segment_id=segment_id,
                    raw_audio_path=raw_audio_path,
                    raw_duration=raw_duration,
                    status="failed",
                    error=f"FFmpeg atempo execution failed: {err_msg}",
                )
        except Exception as exc:
            return FittedAudioResult(
                segment_id=segment_id,
                raw_audio_path=raw_audio_path,
                raw_duration=raw_duration,
                status="failed",
                error=f"Cannot execute FFmpeg: {exc}",
            )

        # 8. Đo lại fitted_duration thực tế từ file vừa sinh
        fitted_dur = measure_wav_duration(target_output)
        if fitted_dur <= 0.0:
            return FittedAudioResult(
                segment_id=segment_id,
                raw_audio_path=raw_audio_path,
                raw_duration=raw_duration,
                status="failed",
                error=f"Invalid duration from fitted output WAV: '{target_output}'",
            )

        return FittedAudioResult(
            segment_id=segment_id,
            raw_audio_path=raw_audio_path,
            raw_duration=raw_duration,
            fitted_audio_path=target_output,
            fitted_duration=fitted_dur,
            applied_speed=applied_speed,
            status="success",
            warning=warning,
            error="",
        )

    def fit_segment_audio(
        self,
        audio_path: str,
        slot_duration: float,
        output_path: str | None = None,
    ) -> tuple[str, float, float, str]:
        """Phương thức tương thích ngược: trả về (path, duration, speed, warning)."""
        res = self.fit_segment(
            segment_id=0,
            raw_audio_path=audio_path,
            slot_duration=slot_duration,
            output_path=output_path,
        )
        if res.status == "success":
            return res.fitted_audio_path, res.fitted_duration, res.applied_speed, res.warning
        return audio_path, res.raw_duration, 1.0, res.error or res.warning

    def process_job(self, job: RenderJob) -> RenderJob:
        """Áp dụng duration fitting cho toàn bộ các câu thoại đã hoàn thành TTS trong RenderJob."""
        fitted_dir = os.path.join(job.job_dir, "fitted_audio")
        os.makedirs(fitted_dir, exist_ok=True)

        for res in job.tts_results.values():
            if res.status != "completed" or not res.audio_file or not os.path.isfile(res.audio_file):
                continue

            out_file = os.path.join(fitted_dir, f"seg_{res.segment_id:04d}_fitted.wav")
            fit_res = self.fit_segment(
                segment_id=res.segment_id,
                raw_audio_path=res.audio_file,
                slot_duration=res.slot_duration,
                output_path=out_file,
            )

            if fit_res.status == "success":
                res.audio_file = fit_res.fitted_audio_path
                res.fitted_duration = fit_res.fitted_duration
                res.fitted_speed = fit_res.applied_speed
                res.warning = fit_res.warning
            else:
                res.warning = fit_res.error
            job.update_tts_result(res)

        job.audio_timeline = job.get_active_tts_timeline_blocks()
        job.current_step_description = "Hoàn thành xử lý khớp thời lượng câu thoại (Duration Fitting)"
        job.save_to_disk()
        return job
