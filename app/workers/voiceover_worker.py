"""VoiceOverWorker QThread for generating TTS audio per segment in a RenderJob."""

from __future__ import annotations

import os
import time
import wave
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QThread, Signal

from app.models.render_job import RenderJob, TTSSegmentResult
from app.models.subtitle_segment import SubtitleSegment


def _get_wav_duration(wav_path: str) -> float:
    """Đo thời lượng file WAV chính xác dựa trên frame count và sample rate."""
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


class VoiceOverWorker(QThread):
    """QThread worker chuyên trách sinh âm thanh TTS cho từng câu thoại trong RenderJob.

    - Hoạt động độc lập trên thread riêng, không làm đơ giao diện.
    - Cập nhật tiến độ realtime qua Qt signals.
    - Lưu trạng thái RenderJob sau mỗi câu (bảo toàn cache khi dừng/sự cố).
    - Hỗ trợ ngắt dừng an toàn qua requestInterruption().
    """

    # Signals
    # (current_index, total_count, status_message)
    progress = Signal(int, int, str)
    # (segment_id, TTSSegmentResult)
    segment_completed = Signal(int, object)
    # (segment_id, error_message)
    segment_failed = Signal(int, str)
    # (RenderJob) khi tất cả hoàn tất
    all_completed = Signal(object)
    # (error_message) khi có lỗi dừng cả luồng
    worker_failed = Signal(str)

    def __init__(
        self,
        job: RenderJob,
        *,
        max_retries: int = 2,
        tts_synthesizer: Callable[..., str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.job = job
        self.max_retries = max_retries
        self._custom_synthesizer = tts_synthesizer
        self._is_cancelled = False

    def cancel(self):
        """Yêu cầu hủy tiến trình an toàn."""
        self._is_cancelled = True
        self.requestInterruption()

    def _synthesize(self, text: str, wav_path: str, voice_id: str, speed: float = 1.0) -> str:
        """Thực hiện sinh TTS (sử dụng custom synthesizer nếu inject hoặc synthesize_text_to_wav_16k_mono chuẩn)."""
        if self._custom_synthesizer is not None:
            return self._custom_synthesizer(
                text=text,
                wav_path=wav_path,
                voice=voice_id,
                speed=speed,
            )

        from app.tts_processor import synthesize_text_to_wav_16k_mono
        return synthesize_text_to_wav_16k_mono(
            text=text,
            wav_path=wav_path,
            voice=voice_id,
            speed=speed,
        )

    def run(self):
        try:
            os.makedirs(self.job.job_dir, exist_ok=True)
            audio_dir = os.path.join(self.job.job_dir, "tts_audio")
            os.makedirs(audio_dir, exist_ok=True)

            pending_segments = self.job.get_pending_or_failed_tts_segments()
            total_pending = len(pending_segments)

            if total_pending == 0:
                self.job.status = "tts_completed"
                self.job.current_step_description = "Không có câu thoại nào cần lồng tiếng TTS"
                self.job.save_to_disk()
                self.progress.emit(0, 0, "Không có câu cần TTS")
                self.all_completed.emit(self.job)
                return

            self.job.status = "tts_running"
            self.job.save_to_disk()

            for idx, seg in enumerate(pending_segments, start=1):
                if self.isInterruptionRequested() or self._is_cancelled:
                    self.job.current_step_description = "Tiến trình TTS đã bị người dùng tạm dừng"
                    self.job.save_to_disk()
                    self.worker_failed.emit("Tiến trình đã bị dừng bởi người dùng.")
                    return

                res = self.job.tts_results.get(seg.id)
                if not res or res.status == "skipped":
                    continue

                voice_id = res.voice_id
                text = seg.translated_text.strip()
                slot_dur = max(0.1, round(seg.end - seg.start, 3))
                wav_path = os.path.join(audio_dir, f"seg_{seg.id:04d}_{seg.gender}.wav")

                self.progress.emit(
                    idx,
                    total_pending,
                    f"Đang tạo giọng đọc câu #{seg.id} ({res.voice_name}): '{text[:30]}...'",
                )

                # Sinh TTS kèm retry cơ chế
                last_error = ""
                success = False
                actual_duration = 0.0

                for attempt in range(1, self.max_retries + 2):
                    if self.isInterruptionRequested() or self._is_cancelled:
                        break
                    try:
                        self._synthesize(
                            text=text,
                            wav_path=wav_path,
                            voice_id=voice_id,
                            speed=1.0,
                        )
                        if os.path.isfile(wav_path) and os.path.getsize(wav_path) > 100:
                            actual_duration = _get_wav_duration(wav_path)
                            if actual_duration > 0.05:
                                success = True
                                break
                    except Exception as exc:
                        last_error = str(exc)
                        time.sleep(0.5)

                if success:
                    res.status = "completed"
                    res.audio_file = wav_path
                    res.raw_duration = actual_duration
                    res.slot_duration = slot_dur
                    res.fitted_duration = actual_duration
                    res.fitted_speed = 1.0
                    res.error = ""
                    res.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
                    self.job.update_tts_result(res)
                    self.job.save_to_disk()
                    self.segment_completed.emit(seg.id, res)
                else:
                    res.status = "failed"
                    res.error = last_error or "Không tạo được file âm thanh hợp lệ"
                    res.retry_count += 1
                    res.updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
                    self.job.update_tts_result(res)
                    self.job.save_to_disk()
                    self.segment_failed.emit(seg.id, res.error)

            # Kết thúc vòng lặp
            if self.job.is_tts_fully_completed():
                self.job.status = "tts_completed"
                self.job.current_step_description = "Hoàn thành toàn bộ giọng đọc TTS"
                self.job.save_to_disk()
                self.progress.emit(total_pending, total_pending, "Đã hoàn thành toàn bộ giọng đọc TTS!")
                self.all_completed.emit(self.job)
            else:
                failed_count = sum(1 for r in self.job.tts_results.values() if r.status == "failed")
                self.job.status = "failed"
                self.job.error_message = f"Có {failed_count} câu TTS bị lỗi cần thử lại"
                self.job.save_to_disk()
                self.worker_failed.emit(self.job.error_message)

        except Exception as general_exc:
            self.job.status = "failed"
            self.job.error_message = str(general_exc)
            self.job.save_to_disk()
            self.worker_failed.emit(str(general_exc))
