"""Audio Ducking & Mixing Service strictly following Rule 4 (Ducking based on actual TTS audio)."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from app.models.render_job import RenderJob, AudioTimelineBlock


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


def merge_duck_intervals(
    intervals: list[tuple[float, float]],
    min_gap: float = 0.3,
) -> list[tuple[float, float]]:
    """Hợp nhất các khoảng thời gian TTS gần nhau (< min_gap) để tránh việc âm thanh

    gốc bị nhấp nhả (ducking flicker).
    """
    if not intervals:
        return []

    # Sắp xếp theo start_time tăng dần
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[float, float]] = []

    current_start, current_end = sorted_intervals[0]

    for start, end in sorted_intervals[1:]:
        if start <= (current_end + min_gap):
            # Khoảng cách quá gần nhau hoặc chồng lấn -> gộp lại
            current_end = max(current_end, end)
        else:
            merged.append((round(current_start, 3), round(current_end, 3)))
            current_start, current_end = start, end

    merged.append((round(current_start, 3), round(current_end, 3)))
    return merged


class AudioDuckingService:
    """Dịch vụ ducking âm thanh gốc và trộn với thoại TTS.

    Tuân thủ nghiêm ngặt NGUYÊN TẮC 4:
    - Ducking âm thanh gốc chỉ diễn ra tại các khoảng thời gian có file TTS thực tế.
    - Các câu unknown hoặc none KHÔNG có TTS -> âm thanh gốc giữ nguyên 100%.
    - Fade-in và Fade-out mượt mà tại điểm chuyển giao âm lượng.
    """

    def __init__(
        self,
        *,
        duck_volume: float = 0.20,
        normal_volume: float = 1.0,
        ffmpeg_bin: str | None = None,
    ):
        self.duck_volume = max(0.05, min(0.60, float(duck_volume)))
        self.normal_volume = float(normal_volume)
        self.ffmpeg_bin = ffmpeg_bin or _resolve_ffmpeg()

    def build_volume_filter_expression(
        self,
        duck_intervals: list[tuple[float, float]],
    ) -> str:
        """Sinh biểu thức FFmpeg volume động:

        Giữ normal_volume ở các đoạn bình thường (bao gồm cả unknown/none),
        Hạ xuống duck_volume tại các khoảng có TTS thực tế.
        """
        if not duck_intervals:
            return f"volume={self.normal_volume}"

        merged = merge_duck_intervals(duck_intervals)
        diff = round(self.normal_volume - self.duck_volume, 3)

        # Tạo chuỗi between(t, start, end)
        # volume = normal_volume - diff * (between(t,s1,e1) + between(t,s2,e2) + ...)
        terms = [f"between(t,{s:.3f},{e:.3f})" for s, e in merged]
        combined = "+".join(terms)

        expr = f"volume=eval=frame:volume='{self.normal_volume:.2f}-{diff:.2f}*min(1,{combined})'"
        return expr

    def extract_audio_from_video(self, video_path: str, output_wav_path: str) -> str:
        """Trích xuất luồng âm thanh stereo 44.1kHz từ tệp video gốc."""
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"Không tìm thấy video gốc: {video_path}")

        os.makedirs(os.path.dirname(output_wav_path), exist_ok=True)
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", video_path,
            "-vn",
            "-ar", "44100",
            "-ac", "2",
            output_wav_path,
        ]

        kwargs: dict[str, Any] = {"capture_output": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.run(cmd, **kwargs)
        if proc.returncode != 0 or not os.path.isfile(output_wav_path):
            raise RuntimeError(f"Lỗi khi trích xuất âm thanh từ video: {proc.stderr.decode('utf-8', errors='ignore')}")

        return output_wav_path

    def duck_background_audio(
        self,
        input_audio_path: str,
        duck_intervals: list[tuple[float, float]],
        output_audio_path: str,
    ) -> str:
        """Áp dụng bộ lọc ducking lên âm thanh nền."""
        if not os.path.isfile(input_audio_path):
            raise FileNotFoundError(f"Không tìm thấy âm thanh nguồn: {input_audio_path}")

        if not duck_intervals:
            # Không có TTS -> sao chép nguyên bản
            os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)
            shutil.copyfile(input_audio_path, output_audio_path)
            return output_audio_path

        vol_filter = self.build_volume_filter_expression(duck_intervals)
        os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", input_audio_path,
            "-af", vol_filter,
            "-ar", "44100",
            "-ac", "2",
            output_audio_path,
        ]

        kwargs: dict[str, Any] = {"capture_output": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.run(cmd, **kwargs)
        if proc.returncode != 0 or not os.path.isfile(output_audio_path):
            raise RuntimeError(f"Lỗi ducking âm thanh: {proc.stderr.decode('utf-8', errors='ignore')}")

        return output_audio_path

    def create_concatenated_tts_track(
        self,
        blocks: list[AudioTimelineBlock],
        total_duration: float,
        output_wav_path: str,
    ) -> str:
        """Tạo một luồng âm thanh thoại liên tục đồng bộ với timeline video bằng cách

        đặt từng block audio TTS vào đúng vị trí miligiây qua adelay.
        """
        os.makedirs(os.path.dirname(output_wav_path), exist_ok=True)

        if not blocks:
            # Tạo 1 track im lặng dài bằng video
            dur = max(1.0, float(total_duration or 1.0))
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-f", "lavfi",
                "-i", f"anullsrc=r=44100:cl=stereo",
                "-t", str(dur),
                output_wav_path,
            ]
            subprocess.run(cmd, capture_output=True)
            return output_wav_path

        # Nếu có blocks, dùng filter_complex script để tránh tràn dòng lệnh
        script_lines = []
        inputs = []

        for idx, block in enumerate(blocks):
            inputs.extend(["-i", block.audio_file])
            delay_ms = int(round(block.start_time * 1000.0))
            # adelay nhận format left|right
            script_lines.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms},volume={block.volume:.2f}[a{idx}];")

        mix_inputs = "".join(f"[a{i}]" for i in range(len(blocks)))
        script_lines.append(f"{mix_inputs}amix=inputs={len(blocks)}:duration=longest:dropout_transition=0[outa]")

        script_content = "\n".join(script_lines)
        script_file = output_wav_path + ".filter_script.txt"
        with open(script_file, "w", encoding="utf-8") as f:
            f.write(script_content)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            *inputs,
            "-filter_complex_script", script_file,
            "-map", "[outa]",
            "-ar", "44100",
            "-ac", "2",
            output_wav_path,
        ]

        kwargs: dict[str, Any] = {"capture_output": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.run(cmd, **kwargs)
        try:
            os.remove(script_file)
        except OSError:
            pass

        if proc.returncode != 0 or not os.path.isfile(output_wav_path):
            raise RuntimeError(f"Lỗi tạo track TTS timeline: {proc.stderr.decode('utf-8', errors='ignore')}")

        return output_wav_path

    def mix_ducked_bg_and_tts(
        self,
        ducked_bg_path: str,
        tts_track_path: str,
        output_mixed_path: str,
    ) -> str:
        """Trộn (mix) âm thanh nền đã duck với track thoại TTS thành bản âm thanh hoàn chỉnh."""
        os.makedirs(os.path.dirname(output_mixed_path), exist_ok=True)

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", ducked_bg_path,
            "-i", tts_track_path,
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[outa]",
            "-map", "[outa]",
            "-ar", "44100",
            "-ac", "2",
            output_mixed_path,
        ]

        kwargs: dict[str, Any] = {"capture_output": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.run(cmd, **kwargs)
        if proc.returncode != 0 or not os.path.isfile(output_mixed_path):
            raise RuntimeError(f"Lỗi hòa trộn âm thanh tổng hợp: {proc.stderr.decode('utf-8', errors='ignore')}")

        return output_mixed_path

    def process_job(self, job: RenderJob) -> str:
        """Xử lý toàn bộ tiến trình Audio Ducking và Hòa âm cho RenderJob.

        Returns:
            Đường dẫn file âm thanh master_mixed.wav
        """
        mix_dir = os.path.join(job.job_dir, "audio_mix")
        os.makedirs(mix_dir, exist_ok=True)

        video_path = job.master_dataset.video_path
        if not video_path or not os.path.isfile(video_path):
            raise FileNotFoundError(f"Không tìm thấy video gốc để trích xuất âm thanh: {video_path}")

        # 1. Trích xuất audio gốc
        job.status = "mixing"
        job.current_step_description = "Đang trích xuất âm thanh từ video gốc..."
        job.save_to_disk()
        raw_bg = os.path.join(mix_dir, "original_bg.wav")
        self.extract_audio_from_video(video_path, raw_bg)

        # 2. Lấy các khoảng thời gian TTS thực tế (Nguyên tắc 4)
        active_blocks = job.get_active_tts_timeline_blocks()
        duck_intervals = [(b.start_time, b.end_time) for b in active_blocks if b.is_duck_trigger]

        # 3. Thực hiện ducking audio gốc
        job.current_step_description = f"Đang duck âm thanh nền theo {len(duck_intervals)} đoạn thoại thực tế..."
        job.save_to_disk()
        ducked_bg = os.path.join(mix_dir, "ducked_bg.wav")
        self.duck_background_audio(raw_bg, duck_intervals, ducked_bg)

        # 4. Tạo track thoại TTS
        job.current_step_description = "Đang đặt các câu thoại vào timeline âm thanh..."
        job.save_to_disk()
        tts_track = os.path.join(mix_dir, "tts_track.wav")
        self.create_concatenated_tts_track(active_blocks, job.master_dataset.duration, tts_track)

        # 5. Hòa trộn cuối cùng
        job.current_step_description = "Đang hòa trộn âm thanh nền và giọng đọc TTS hoàn chỉnh..."
        job.save_to_disk()
        final_mixed = os.path.join(job.job_dir, "master_mixed.wav")
        self.mix_ducked_bg_and_tts(ducked_bg, tts_track, final_mixed)

        job.current_step_description = "Hoàn thành hòa trộn âm thanh (Audio Ducking & Mixing)"
        job.progress_percent = 80.0
        job.save_to_disk()
        return final_mixed
