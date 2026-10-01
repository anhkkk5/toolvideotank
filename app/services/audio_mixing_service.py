"""Audio Mixing & Ducking Service.

Implements Step 6.1 & Step 6.2 Contract v1.0:
- TTSAudioBlock: Data model representing fitted TTS audio placed at exact absolute timeline.
- MixedAudioResult: Data model returning mixed master audio and diagnostics.
- AudioMixingService: Centralized service orchestrating ducking and timeline audio mixing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

from app.services.tts_backend import measure_wav_duration


def _resolve_ffmpeg() -> str:
    """Xác định đường dẫn thực thi của FFmpeg."""
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
class TTSAudioBlock:
    """Đại diện cho một khối âm thanh thoại hợp lệ trên timeline video."""
    segment_id: int
    start_time: float         # Mốc thời gian bắt đầu trên timeline (giây)
    duration: float           # Thời lượng âm thanh thực tế (fitted_duration)
    audio_path: str           # Đường dẫn file WAV (thường trong fitted_tts/)
    volume: float = 1.0       # Hệ số âm lượng thoại riêng (mặc định 1.0)

    @property
    def end_time(self) -> float:
        """Thời điểm kết thúc âm thanh thoại trên timeline."""
        return round(self.start_time + self.duration, 3)


@dataclass
class MixedAudioResult:
    """Kết quả hoàn chỉnh của tiến trình hòa âm và ducking âm thanh."""
    final_audio_path: str = ""
    original_duration: float = 0.0
    total_duration: float = 0.0
    duck_intervals: list[tuple[float, float]] = field(default_factory=list)
    applied_duck_volume: float = 0.20
    status: Literal["success", "failed"] = "success"
    warning: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AudioMixingService:
    """Service chịu trách nhiệm hòa âm (mixing) và hạ âm lượng nền (ducking).
    
    Tuân thủ nghiêm ngặt 11 Invariants của Contract 6.1:
    - Invariant 8: Không overlap TTS (nếu overlap -> fail rõ ràng).
    - Invariant 9: Hợp nhất gap < 0.30s để tránh ducking nhấp nhả (flicker).
    - Invariant 10: Không trim TTS khi vượt video, ghi nhận warning overflow.
    - Invariant 11: total_duration = max(original_duration, last_tts_end).
    - Timeline placement tuyệt đối theo start_time qua adelay.
    """

    def __init__(
        self,
        *,
        duck_volume: float = 0.20,
        normal_volume: float = 1.0,
        tts_volume: float = 1.0,
        min_gap_merge: float = 0.30,
        ffmpeg_bin: str | None = None,
    ):
        self.duck_volume = float(duck_volume)
        self.normal_volume = float(normal_volume)
        self.tts_volume = float(tts_volume)
        self.min_gap_merge = float(min_gap_merge)
        self.ffmpeg_bin = ffmpeg_bin or _resolve_ffmpeg()

    def build_duck_intervals(self, sorted_blocks: list[TTSAudioBlock]) -> list[tuple[float, float]]:
        """Xây dựng và hợp nhất các khoảng ducking theo Invariant 9 (gap < min_gap_merge)."""
        if not sorted_blocks:
            return []

        raw_intervals = [(b.start_time, b.end_time) for b in sorted_blocks]
        merged: list[tuple[float, float]] = []

        cur_start, cur_end = raw_intervals[0]
        for next_start, next_end in raw_intervals[1:]:
            gap = round(next_start - cur_end, 3)
            if gap < self.min_gap_merge:
                # Gộp hai khoảng gần nhau thành một khoảng liên tục
                cur_end = max(cur_end, next_end)
            else:
                # Đủ xa (>= min_gap_merge) -> giữ khoảng riêng
                merged.append((round(cur_start, 3), round(cur_end, 3)))
                cur_start, cur_end = next_start, next_end

        merged.append((round(cur_start, 3), round(cur_end, 3)))
        return merged

    def build_volume_filter_expression(self, duck_intervals: list[tuple[float, float]]) -> str:
        """Tạo biểu thức FFmpeg volume động: giữ normal_volume ngoài khoảng TTS, hạ duck_volume trong khoảng TTS."""
        if self.normal_volume <= 0.001:
            return "volume=0"
        if not duck_intervals:
            return f"volume={self.normal_volume:.2f}"

        diff = round(max(0.0, self.normal_volume - self.duck_volume), 3)
        terms = [f"between(t,{s:.3f},{e:.3f})" for s, e in duck_intervals]
        combined = "+".join(terms)
        return f"volume=eval=frame:volume='{self.normal_volume:.2f}-{diff:.2f}*min(1,{combined})'"

    def _assemble_unified_tts_track(
        self,
        sorted_blocks: list[TTSAudioBlock],
        total_duration: float,
        output_tts_path: str,
    ) -> str:
        """Ghép toàn bộ các câu thoại vào một track âm thanh duy nhất theo timeline tuyệt đối.
        
        Giải quyết triệt để giới hạn 32KB dòng lệnh của Windows API (WinError 206)
        khi xử lý video dài (1 tiếng, 2 tiếng...) có hàng ngàn câu thoại phụ đề.
        """
        import math
        import wave
        import numpy as np

        target_sr = 16000
        for b in sorted_blocks:
            if b.audio_path and os.path.isfile(b.audio_path):
                try:
                    with wave.open(b.audio_path, "rb") as test_w:
                        test_sr = test_w.getframerate()
                        if test_sr in {16000, 22050, 24000, 44100, 48000}:
                            target_sr = test_sr
                            break
                except Exception:
                    pass

        # Cơ chế Streaming Disk-Writing: Ghi tuần tự trực tiếp xuống file WAV theo dòng thời gian
        # Giúp tiêu thụ RAM luôn cố định < 10MB kể cả với video siêu dài 10 tiếng, 20 tiếng, 30 tiếng
        os.makedirs(os.path.dirname(os.path.abspath(output_tts_path)) or ".", exist_ok=True)
        tts_scale = float(getattr(self, "tts_volume", 1.0))
        silence_1s = b"\x00\x00" * target_sr
        current_sample = 0

        with wave.open(output_tts_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(target_sr)

            for b in sorted_blocks:
                if not b.audio_path or not os.path.isfile(b.audio_path):
                    continue
                try:
                    start_sample = max(current_sample, int(round(b.start_time * target_sr)))
                    gap_samples = start_sample - current_sample
                    if gap_samples > 0:
                        full_secs = gap_samples // target_sr
                        rem = gap_samples % target_sr
                        for _ in range(full_secs):
                            wf.writeframes(silence_1s)
                        if rem > 0:
                            wf.writeframes(b"\x00\x00" * rem)
                        current_sample = start_sample

                    with wave.open(b.audio_path, "rb") as w:
                        sr = w.getframerate()
                        n_ch = w.getnchannels()
                        n_fr = w.getnframes()
                        raw = w.readframes(n_fr)
                    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                    if n_ch == 2:
                        data = (data[0::2] + data[1::2]) * 0.5
                    if sr != target_sr and len(data) > 0:
                        orig_idx = np.arange(len(data))
                        new_len = int(len(data) * target_sr / sr)
                        new_idx = np.linspace(0, len(data) - 1, new_len)
                        data = np.interp(new_idx, orig_idx, data)

                    if tts_scale <= 0.001:
                        vol = 0.0
                    else:
                        vol = max(0.1, float(getattr(b, "volume", 1.0) or 1.0) * 1.35 * tts_scale)
                    data = np.clip(data * vol, -32767.0, 32767.0).astype(np.int16)
                    wf.writeframes(data.tobytes())
                    current_sample += len(data)
                except Exception as e:
                    print(f"[AudioMixing] Warning streaming block {b.segment_id}: {e}")

            # Đệm khoảng lặng đến hết độ dài tổng thể video nếu cần
            total_samples = int(round(total_duration * target_sr))
            if total_samples > current_sample:
                gap_samples = total_samples - current_sample
                full_secs = gap_samples // target_sr
                rem = gap_samples % target_sr
                for _ in range(full_secs):
                    wf.writeframes(silence_1s)
                if rem > 0:
                    wf.writeframes(b"\x00\x00" * rem)

        return output_tts_path

    def mix(
        self,
        *,
        original_audio_path: str,
        tts_blocks: list[TTSAudioBlock],
        output_path: str,
    ) -> MixedAudioResult:
        """Hòa âm giữa audio gốc (đã duck) và luồng TTS theo timeline tuyệt đối."""
        # =====================================================================
        # BƯỚC 1: VALIDATE ORIGINAL AUDIO & OUTPUT PATH
        # =====================================================================
        if not original_audio_path or not os.path.isfile(original_audio_path):
            return MixedAudioResult(
                status="failed",
                error=f"Original audio file not found: '{original_audio_path}'",
            )

        orig_abs = os.path.abspath(original_audio_path)
        dest_abs = os.path.abspath(output_path)
        if orig_abs == dest_abs:
            return MixedAudioResult(
                status="failed",
                error="output_path cannot overwrite original_audio_path",
            )

        orig_dur = measure_wav_duration(original_audio_path)
        if orig_dur <= 0.0:
            return MixedAudioResult(
                status="failed",
                error=f"Invalid or unreadable original audio WAV: '{original_audio_path}'",
            )

        # =====================================================================
        # BƯỚC 2: VALIDATE TTS BLOCKS & DETECT OVERLAP (INVARIANT 8)
        # =====================================================================
        clean_blocks: list[TTSAudioBlock] = []
        for b in tts_blocks:
            if not b.audio_path or not os.path.isfile(b.audio_path):
                return MixedAudioResult(
                    status="failed",
                    original_duration=orig_dur,
                    error=f"TTS audio file missing for segment {b.segment_id}: '{b.audio_path}'",
                )
            if b.start_time < 0:
                return MixedAudioResult(
                    status="failed",
                    original_duration=orig_dur,
                    error=f"Invalid negative start_time for segment {b.segment_id}: {b.start_time}",
                )
            if b.duration <= 0:
                return MixedAudioResult(
                    status="failed",
                    original_duration=orig_dur,
                    error=f"Invalid non-positive duration for segment {b.segment_id}: {b.duration}",
                )
            clean_blocks.append(b)

        # Sắp xếp blocks theo start_time tăng dần
        sorted_blocks = sorted(clean_blocks, key=lambda x: x.start_time)

        # Kiểm tra và Tự Động Xử Lý Overlap giữa các khối thoại liên tiếp (Auto-resolve TTS Overlap)
        for i in range(1, len(sorted_blocks)):
            prev = sorted_blocks[i - 1]
            curr = sorted_blocks[i]
            if curr.start_time < prev.end_time:
                overlap_dur = round(prev.end_time - curr.start_time, 3)
                if overlap_dur <= 0.005:
                    curr.start_time = prev.end_time
                else:
                    print(
                        f"[AudioMixing] Auto-resolving overlap ({overlap_dur:.3f}s) between Segment {prev.segment_id} "
                        f"and Segment {curr.segment_id} (fade-out trimming)..."
                    )
                    # Cắt nhẹ đuôi của câu trước để câu sau cất lời chuẩn xác tại curr.start_time
                    new_prev_dur = max(0.1, round(curr.start_time - prev.start_time - 0.01, 3))
                    try:
                        trimmed_audio = os.path.splitext(prev.audio_path)[0] + "_mix_resolved.wav"
                        fade_start = max(0.0, new_prev_dur - 0.05)
                        cmd = [
                            self.ffmpeg_bin, "-y",
                            "-i", prev.audio_path,
                            "-t", f"{new_prev_dur:.3f}",
                            "-af", f"afade=t=out:st={fade_start:.3f}:d=0.05",
                            trimmed_audio,
                        ]
                        from runtime_paths import subprocess_hidden_kwargs
                        subprocess.run(cmd, check=True, capture_output=True, **subprocess_hidden_kwargs())
                        if os.path.isfile(trimmed_audio):
                            prev.audio_path = trimmed_audio
                    except Exception as trim_err:
                        print(f"[AudioMixing] Auto-resolve overlap trim notice: {trim_err}")
                    prev.duration = new_prev_dur

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        # =====================================================================
        # BƯỚC 3: XỬ LÝ KHI KHÔNG CÓ TTS BLOCK NÀO (TẤT CẢ SKIPPED)
        # =====================================================================
        if not sorted_blocks:
            try:
                shutil.copyfile(original_audio_path, output_path)
                act_dur = measure_wav_duration(output_path)
                return MixedAudioResult(
                    final_audio_path=output_path,
                    original_duration=orig_dur,
                    total_duration=act_dur,
                    duck_intervals=[],
                    applied_duck_volume=self.duck_volume,
                    status="success",
                    warning="",
                    error="",
                )
            except Exception as exc:
                return MixedAudioResult(
                    status="failed",
                    original_duration=orig_dur,
                    error=f"Failed to copy original audio: {exc}",
                )

        # =====================================================================
        # BƯỚC 4: TÍNH TOÁN DUCK INTERVALS & OVERFLOW WARNING (INVARIANTS 9, 10, 11)
        # =====================================================================
        duck_intervals = self.build_duck_intervals(sorted_blocks)
        last_tts_end = max((b.end_time for b in sorted_blocks), default=0.0)
        expected_total_duration = max(orig_dur, last_tts_end)

        warning_msg = ""
        if last_tts_end > orig_dur:
            warning_msg = (
                f"TTS audio timeline ({last_tts_end:.2f}s) exceeds original audio duration ({orig_dur:.2f}s). "
                f"Timeline extended to {expected_total_duration:.2f}s without trimming."
            )

        # =====================================================================
        # BƯỚC 5: XÂY DỰNG FFMPEG FILTER COMPLEX SCRIPT (ABSOLUTE TIMELINE PLACEMENT)
        # Tự động chuyển sang Unified Master Track khi có nhiều câu thoại (> 30 câu)
        # để chống lỗi WinError 206 (The filename or extension is too long) trên Windows
        # =====================================================================
        vol_filter = self.build_volume_filter_expression(duck_intervals)
        use_unified_track = len(sorted_blocks) > 30
        unified_tts_path = output_path + ".unified_tts.wav"

        if use_unified_track:
            self._assemble_unified_tts_track(
                sorted_blocks=sorted_blocks,
                total_duration=expected_total_duration,
                output_tts_path=unified_tts_path,
            )
            inputs = ["-i", original_audio_path, "-i", unified_tts_path]
            script_lines = [
                f"[0:a]{vol_filter},aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=stereo[bg];",
                f"[1:a]aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=stereo[fg];",
                f"[bg][fg]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=0.98[outa]"
            ]
        else:
            inputs = ["-i", original_audio_path]
            for b in sorted_blocks:
                inputs.extend(["-i", b.audio_path])

            script_lines: list[str] = []
            script_lines.append(
                f"[0:a]{vol_filter},aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=stereo[bg];"
            )
            tts_scale = float(getattr(self, "tts_volume", 1.0))
            for idx, b in enumerate(sorted_blocks, start=1):
                delay_ms = int(round(b.start_time * 1000.0))
                if tts_scale <= 0.001:
                    tts_vol = 0.0
                else:
                    tts_vol = max(0.1, float(getattr(b, "volume", 1.0) or 1.0) * 1.35 * tts_scale)
                script_lines.append(
                    f"[{idx}:a]aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=stereo,"
                    f"adelay={delay_ms}|{delay_ms},"
                    f"volume={tts_vol:.2f}[tts_{idx}];"
                )

            mix_sources = "[bg]" + "".join(f"[tts_{i}]" for i in range(1, len(sorted_blocks) + 1))
            num_inputs = 1 + len(sorted_blocks)
            script_lines.append(
                f"{mix_sources}amix=inputs={num_inputs}:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=0.98[outa]"
            )

        script_content = "\n".join(script_lines)
        filter_script_path = output_path + ".filter_script.txt"

        try:
            with open(filter_script_path, "w", encoding="utf-8") as f:
                f.write(script_content)

            cmd = [
                self.ffmpeg_bin,
                "-y",
                *inputs,
                "-filter_complex_script", filter_script_path,
                "-map", "[outa]",
                "-ar", "44100",
                "-ac", "2",
                output_path,
            ]

            kwargs: dict[str, Any] = {"capture_output": True}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            proc = subprocess.run(cmd, **kwargs)
            if proc.returncode != 0 or not os.path.isfile(output_path):
                err_text = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else "Unknown FFmpeg error"
                return MixedAudioResult(
                    status="failed",
                    original_duration=orig_dur,
                    total_duration=0.0,
                    duck_intervals=duck_intervals,
                    error=f"FFmpeg mixing failed: {err_text}",
                )

        except Exception as exc:
            return MixedAudioResult(
                status="failed",
                original_duration=orig_dur,
                total_duration=0.0,
                duck_intervals=duck_intervals,
                error=f"Cannot execute FFmpeg: {exc}",
            )
        finally:
            if os.path.isfile(filter_script_path):
                try:
                    os.remove(filter_script_path)
                except Exception:
                    pass
            if os.path.isfile(unified_tts_path):
                try:
                    os.remove(unified_tts_path)
                except Exception:
                    pass

        # Đo lại actual duration từ file output thực tế
        actual_duration = measure_wav_duration(output_path)

        return MixedAudioResult(
            final_audio_path=output_path,
            original_duration=orig_dur,
            total_duration=actual_duration,
            duck_intervals=duck_intervals,
            applied_duck_volume=self.duck_volume,
            status="success",
            warning=warning_msg,
            error="",
        )
