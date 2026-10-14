"""Step 7.4 — Subtitle Rendering & Video Export Regression Test Matrix.

Kiểm tra 10 Scenarios độc lập theo Contract 7.1 & API Design 7.2:
1. Normal export — video > audio
2. Audio > video + shortest
3. Audio > video + freeze_end
4. is_noise=True -> không render subtitle
5. translated_text="" -> không render subtitle
6. unknown/none -> subtitle vẫn render
7. Invalid segment timing -> fail-fast
8. Output collision với input -> reject
9. Non-.mp4 / invalid policy -> reject
10. FFmpeg failure -> status="failed" + SRT cleanup + không uncaught exception

Đồng thời kiểm tra các thông số thực tế của file MP4 (FFprobe stream inspection):
- video duration
- audio duration
- final MP4 duration
- audio stream (AAC, 44100Hz, 2 channels)
- subtitle burn-in (hardsub, no soft subtitles)
- cleanup SRT trong thư mục temp
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.models.subtitle_segment import SubtitleSegment
from app.services.video_export_service import (
    VideoExportRequest,
    VideoExportResult,
    VideoExportService,
    SubtitleRenderConfig,
    _resolve_ffmpeg,
    _resolve_ffprobe,
    measure_media_duration,
)


def run_cmd(cmd: list[str]) -> subprocess.CompletedProcess:
    kwargs: dict[str, Any] = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "ignore"}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(cmd, **kwargs)


def create_synthetic_video(path: str, duration: float, width: int = 320, height: int = 240, fps: int = 25) -> None:
    """Tạo video test MP4 bằng FFmpeg lavfi testsrc."""
    ffmpeg = _resolve_ffmpeg()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size={width}x{height}:rate={fps}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        path,
    ]
    res = run_cmd(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to create synthetic video: {res.stderr}")


def create_synthetic_audio(path: str, duration: float, freq: int = 440, sr: int = 44100) -> None:
    """Tạo audio test WAV bằng FFmpeg lavfi sine."""
    ffmpeg = _resolve_ffmpeg()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={duration}",
        "-ar", str(sr),
        "-ac", "2",
        "-c:a", "pcm_s16le",
        path,
    ]
    res = run_cmd(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to create synthetic audio: {res.stderr}")


def inspect_media_file(path: str) -> dict[str, Any]:
    """Kiểm tra chi tiết stream thực tế trong container MP4 bằng ffprobe."""
    ffprobe = _resolve_ffprobe()
    cmd = [
        ffprobe,
        "-v", "error",
        "-show_entries", "stream=codec_name,codec_type,sample_rate,channels:format=duration",
        "-of", "json",
        path,
    ]
    res = run_cmd(cmd)
    if res.returncode != 0:
        return {"error": res.stderr}

    data = json.loads(res.stdout)
    format_dur = float(data.get("format", {}).get("duration", 0.0))
    streams = data.get("streams", [])

    video_codec = None
    audio_codec = None
    sample_rate = None
    channels = None
    has_sub_stream = False

    for s in streams:
        c_type = s.get("codec_type")
        if c_type == "video" and not video_codec:
            video_codec = s.get("codec_name")
        elif c_type == "audio" and not audio_codec:
            audio_codec = s.get("codec_name")
            sample_rate = s.get("sample_rate")
            channels = s.get("channels")
        elif c_type == "subtitle":
            has_sub_stream = True

    return {
        "format_duration": format_dur,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "sample_rate": sample_rate,
        "channels": channels,
        "has_sub_stream": has_sub_stream,
        "streams_count": len(streams),
    }


def count_temp_srt_files(temp_dir: str) -> int:
    """Đếm số file .srt tạm còn sót trong temp_dir."""
    if not os.path.isdir(temp_dir):
        return 0
    return len([f for f in os.listdir(temp_dir) if f.startswith("export_sub_") and f.endswith(".srt")])


def main() -> int:
    print("=" * 80)
    print("BƯỚC 7.4: REGRESSION TEST MATRIX — SUBTITLE RENDERING & VIDEO EXPORT")
    print("=" * 80)

    work_dir = os.path.join(tempfile.gettempdir(), "capcap_regression_step74")
    shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)

    temp_srt_dir = os.path.join(work_dir, "temp_srt")
    os.makedirs(temp_srt_dir, exist_ok=True)

    service = VideoExportService(temp_dir=temp_srt_dir)
    scenarios_passed = 0
    total_scenarios = 10
    results_summary: list[dict[str, Any]] = []

    try:
        # =====================================================================
        # SCENARIO 1: Normal export — video > audio
        # =====================================================================
        print("\n--- [Scenario 1] Normal export (video > audio, hardsub Vietnamese) ---")
        vid1 = os.path.join(work_dir, "sc1_in.mp4")
        aud1 = os.path.join(work_dir, "sc1_in.wav")
        out1 = os.path.join(work_dir, "sc1_out.mp4")
        create_synthetic_video(vid1, duration=5.0)
        create_synthetic_audio(aud1, duration=3.0)

        seg1 = SubtitleSegment(
            id=1,
            start=0.5,
            end=2.5,
            text="Hello Vietnam",
            raw_gender="male",
            final_gender="male",
            translated_text="Xin chào Việt Nam, đây là phụ đề tiếng Việt!",
        )

        res1 = service.export_video(
            VideoExportRequest(
                original_video_path=vid1,
                final_audio_path=aud1,
                segments=[seg1],
                output_video_path=out1,
                overflow_policy="shortest",
            )
        )

        probe1 = inspect_media_file(out1) if os.path.isfile(out1) else {}
        srt_left1 = count_temp_srt_files(temp_srt_dir)

        pass1 = (
            res1.status == "success"
            and abs(res1.video_duration - 5.0) <= 0.1
            and abs(res1.audio_duration - 3.0) <= 0.1
            and abs(res1.final_video_duration - 5.0) <= 0.2
            and res1.rendered_subtitles_count == 1
            and res1.skipped_subtitles_count == 0
            and probe1.get("video_codec") == "h264"
            and probe1.get("audio_codec") == "aac"
            and str(probe1.get("sample_rate")) == "44100"
            and probe1.get("channels") == 2
            and probe1.get("has_sub_stream") is False  # Hardsub burned, no soft sub track
            and srt_left1 == 0
        )

        print(f"Result 1: status={res1.status}, final_dur={res1.final_video_duration:.2f}s, rendered={res1.rendered_subtitles_count}")
        print(f"Probe 1: codec={probe1.get('video_codec')}/{probe1.get('audio_codec')}, rate={probe1.get('sample_rate')}, ch={probe1.get('channels')}, soft_sub={probe1.get('has_sub_stream')}, srt_remained={srt_left1}")
        status_str = "PASS" if pass1 else "FAIL"
        print(f"--> SCENARIO 1: {status_str}")
        if pass1:
            scenarios_passed += 1
        results_summary.append({"id": 1, "name": "Normal export (video > audio)", "status": status_str, "detail": f"dur={res1.final_video_duration:.2f}s, aac/h264 verified, srt_left={srt_left1}"})

        # =====================================================================
        # SCENARIO 2: Audio > video + shortest
        # =====================================================================
        print("\n--- [Scenario 2] Audio > video + shortest policy ---")
        vid2 = os.path.join(work_dir, "sc2_in.mp4")
        aud2 = os.path.join(work_dir, "sc2_in.wav")
        out2 = os.path.join(work_dir, "sc2_out.mp4")
        create_synthetic_video(vid2, duration=3.0)
        create_synthetic_audio(aud2, duration=5.0)

        seg2 = SubtitleSegment(
            id=2,
            start=0.5,
            end=2.0,
            text="Audio is longer than video",
            raw_gender="female",
            final_gender="female",
            translated_text="Âm thanh dài hơn video!",
        )

        res2 = service.export_video(
            VideoExportRequest(
                original_video_path=vid2,
                final_audio_path=aud2,
                segments=[seg2],
                output_video_path=out2,
                overflow_policy="shortest",
            )
        )

        probe2 = inspect_media_file(out2) if os.path.isfile(out2) else {}
        srt_left2 = count_temp_srt_files(temp_srt_dir)

        pass2 = (
            res2.status == "success"
            and abs(res2.video_duration - 3.0) <= 0.1
            and abs(res2.audio_duration - 5.0) <= 0.1
            and abs(res2.final_video_duration - 3.0) <= 0.2  # Bị cắt đúng theo video 3.0s
            and "shortest" in res2.warning.lower()
            and probe2.get("video_codec") == "h264"
            and probe2.get("audio_codec") == "aac"
            and srt_left2 == 0
        )

        print(f"Result 2: status={res2.status}, final_dur={res2.final_video_duration:.2f}s, warning='{res2.warning}'")
        print(f"Probe 2: format_dur={probe2.get('format_duration'):.2f}s, srt_remained={srt_left2}")
        status_str = "PASS" if pass2 else "FAIL"
        print(f"--> SCENARIO 2: {status_str}")
        if pass2:
            scenarios_passed += 1
        results_summary.append({"id": 2, "name": "Audio > video + shortest", "status": status_str, "detail": f"final_dur={res2.final_video_duration:.2f}s (cut to video)"})

        # =====================================================================
        # SCENARIO 3: Audio > video + freeze_end
        # =====================================================================
        print("\n--- [Scenario 3] Audio > video + freeze_end policy ---")
        vid3 = os.path.join(work_dir, "sc3_in.mp4")
        aud3 = os.path.join(work_dir, "sc3_in.wav")
        out3 = os.path.join(work_dir, "sc3_out.mp4")
        create_synthetic_video(vid3, duration=3.0)
        create_synthetic_audio(aud3, duration=5.0)

        seg3 = SubtitleSegment(
            id=3,
            start=0.5,
            end=2.0,
            text="Freeze frame to audio end",
            raw_gender="female",
            final_gender="female",
            translated_text="Kéo dài khung hình kết thúc!",
        )

        res3 = service.export_video(
            VideoExportRequest(
                original_video_path=vid3,
                final_audio_path=aud3,
                segments=[seg3],
                output_video_path=out3,
                overflow_policy="freeze_end",
            )
        )

        probe3 = inspect_media_file(out3) if os.path.isfile(out3) else {}
        srt_left3 = count_temp_srt_files(temp_srt_dir)

        pass3 = (
            res3.status == "success"
            and abs(res3.video_duration - 3.0) <= 0.1
            and abs(res3.audio_duration - 5.0) <= 0.1
            and abs(res3.final_video_duration - 5.0) <= 0.2  # Kéo dài frame cuối tới 5.0s
            and "freeze frame" in res3.warning.lower()
            and probe3.get("video_codec") == "h264"
            and probe3.get("audio_codec") == "aac"
            and srt_left3 == 0
        )

        print(f"Result 3: status={res3.status}, final_dur={res3.final_video_duration:.2f}s, warning='{res3.warning}'")
        print(f"Probe 3: format_dur={probe3.get('format_duration'):.2f}s, srt_remained={srt_left3}")
        status_str = "PASS" if pass3 else "FAIL"
        print(f"--> SCENARIO 3: {status_str}")
        if pass3:
            scenarios_passed += 1
        results_summary.append({"id": 3, "name": "Audio > video + freeze_end", "status": status_str, "detail": f"final_dur={res3.final_video_duration:.2f}s (freeze extended to audio)"})

        # =====================================================================
        # SCENARIO 4: is_noise=True -> không render subtitle
        # =====================================================================
        print("\n--- [Scenario 4] is_noise=True -> skip subtitle ---")
        vid4 = os.path.join(work_dir, "sc4_in.mp4")
        aud4 = os.path.join(work_dir, "sc4_in.wav")
        out4 = os.path.join(work_dir, "sc4_out.mp4")
        create_synthetic_video(vid4, duration=3.0)
        create_synthetic_audio(aud4, duration=2.0)

        seg4 = SubtitleSegment(
            id=4,
            start=0.5,
            end=1.5,
            text="Unwanted noise",
            raw_gender="unknown",
            final_gender="unknown",
            translated_text="Tiếng ồn nền không mong muốn",
            is_noise=True,
        )

        res4 = service.export_video(
            VideoExportRequest(
                original_video_path=vid4,
                final_audio_path=aud4,
                segments=[seg4],
                output_video_path=out4,
            )
        )

        srt_left4 = count_temp_srt_files(temp_srt_dir)
        pass4 = (
            res4.status == "success"
            and res4.rendered_subtitles_count == 0
            and res4.skipped_subtitles_count == 1
            and os.path.isfile(out4)
            and srt_left4 == 0
        )

        print(f"Result 4: status={res4.status}, rendered={res4.rendered_subtitles_count}, skipped={res4.skipped_subtitles_count}")
        status_str = "PASS" if pass4 else "FAIL"
        print(f"--> SCENARIO 4: {status_str}")
        if pass4:
            scenarios_passed += 1
        results_summary.append({"id": 4, "name": "is_noise=True skipped", "status": status_str, "detail": "rendered=0, skipped=1"})

        # =====================================================================
        # SCENARIO 5: translated_text="" -> không render subtitle
        # =====================================================================
        print("\n--- [Scenario 5] translated_text='' -> skip subtitle ---")
        vid5 = os.path.join(work_dir, "sc5_in.mp4")
        aud5 = os.path.join(work_dir, "sc5_in.wav")
        out5 = os.path.join(work_dir, "sc5_out.mp4")
        create_synthetic_video(vid5, duration=3.0)
        create_synthetic_audio(aud5, duration=2.0)

        seg5a = SubtitleSegment(id=5, start=0.2, end=1.0, text="Empty translation", translated_text="")
        seg5b = SubtitleSegment(id=6, start=1.2, end=2.0, text="Whitespace translation", translated_text="   \t\n  ")

        res5 = service.export_video(
            VideoExportRequest(
                original_video_path=vid5,
                final_audio_path=aud5,
                segments=[seg5a, seg5b],
                output_video_path=out5,
            )
        )

        srt_left5 = count_temp_srt_files(temp_srt_dir)
        pass5 = (
            res5.status == "success"
            and res5.rendered_subtitles_count == 0
            and res5.skipped_subtitles_count == 2
            and os.path.isfile(out5)
            and srt_left5 == 0
        )

        print(f"Result 5: status={res5.status}, rendered={res5.rendered_subtitles_count}, skipped={res5.skipped_subtitles_count}")
        status_str = "PASS" if pass5 else "FAIL"
        print(f"--> SCENARIO 5: {status_str}")
        if pass5:
            scenarios_passed += 1
        results_summary.append({"id": 5, "name": "translated_text='' skipped", "status": status_str, "detail": "rendered=0, skipped=2"})

        # =====================================================================
        # SCENARIO 6: unknown/none -> subtitle vẫn render
        # =====================================================================
        print("\n--- [Scenario 6] unknown/none -> subtitle still renders ---")
        vid6 = os.path.join(work_dir, "sc6_in.mp4")
        aud6 = os.path.join(work_dir, "sc6_in.wav")
        out6 = os.path.join(work_dir, "sc6_out.mp4")
        create_synthetic_video(vid6, duration=4.0)
        create_synthetic_audio(aud6, duration=3.0)

        seg6a = SubtitleSegment(
            id=7,
            start=0.5,
            end=1.5,
            text="Unknown speaker speaks",
            raw_gender="unknown",
            final_gender="unknown",
            translated_text="Nhân vật bí ẩn phát biểu",
        )
        seg6b = SubtitleSegment(
            id=8,
            start=1.8,
            end=2.8,
            text="None speaker speaks",
            raw_gender="none",
            final_gender="none",
            translated_text="Âm thanh người không rõ danh tính",
        )

        res6 = service.export_video(
            VideoExportRequest(
                original_video_path=vid6,
                final_audio_path=aud6,
                segments=[seg6a, seg6b],
                output_video_path=out6,
            )
        )

        srt_left6 = count_temp_srt_files(temp_srt_dir)
        pass6 = (
            res6.status == "success"
            and res6.rendered_subtitles_count == 2
            and res6.skipped_subtitles_count == 0
            and os.path.isfile(out6)
            and srt_left6 == 0
        )

        print(f"Result 6: status={res6.status}, rendered={res6.rendered_subtitles_count}, skipped={res6.skipped_subtitles_count}")
        status_str = "PASS" if pass6 else "FAIL"
        print(f"--> SCENARIO 6: {status_str}")
        if pass6:
            scenarios_passed += 1
        results_summary.append({"id": 6, "name": "unknown/none rendered properly", "status": status_str, "detail": "rendered=2, skipped=0"})

        # =====================================================================
        # SCENARIO 7: Invalid segment timing -> fail-fast
        # =====================================================================
        print("\n--- [Scenario 7] Invalid segment timing -> fail-fast ---")
        vid7 = os.path.join(work_dir, "sc7_in.mp4")
        aud7 = os.path.join(work_dir, "sc7_in.wav")
        out7a = os.path.join(work_dir, "sc7a_out.mp4")
        out7b = os.path.join(work_dir, "sc7b_out.mp4")
        create_synthetic_video(vid7, duration=3.0)
        create_synthetic_audio(aud7, duration=2.0)

        # Case 7a: start < 0
        seg7a = SubtitleSegment(id=9, start=-1.0, end=1.5, text="Negative start", translated_text="Lỗi thời gian âm")
        res7a = service.export_video(
            VideoExportRequest(
                original_video_path=vid7,
                final_audio_path=aud7,
                segments=[seg7a],
                output_video_path=out7a,
            )
        )

        # Case 7b: end <= start
        seg7b = SubtitleSegment(id=10, start=2.0, end=1.5, text="End before start", translated_text="Lỗi kết thúc trước bắt đầu")
        res7b = service.export_video(
            VideoExportRequest(
                original_video_path=vid7,
                final_audio_path=aud7,
                segments=[seg7b],
                output_video_path=out7b,
            )
        )

        srt_left7 = count_temp_srt_files(temp_srt_dir)
        pass7 = (
            res7a.status == "failed"
            and "Invalid segment timing" in res7a.error
            and not os.path.isfile(out7a)
            and res7b.status == "failed"
            and "Invalid segment timing" in res7b.error
            and not os.path.isfile(out7b)
            and srt_left7 == 0
        )

        print(f"Result 7a (start<0): status={res7a.status}, error='{res7a.error}'")
        print(f"Result 7b (end<=start): status={res7b.status}, error='{res7b.error}'")
        status_str = "PASS" if pass7 else "FAIL"
        print(f"--> SCENARIO 7: {status_str}")
        if pass7:
            scenarios_passed += 1
        results_summary.append({"id": 7, "name": "Invalid segment timing fail-fast", "status": status_str, "detail": "Rejected start<0 and end<=start"})

        # =====================================================================
        # SCENARIO 8: Output collision với input -> reject
        # =====================================================================
        print("\n--- [Scenario 8] Output collision with input -> reject ---")
        vid8 = os.path.join(work_dir, "sc8_in.mp4")
        aud8 = os.path.join(work_dir, "sc8_in.wav")
        create_synthetic_video(vid8, duration=3.0)
        create_synthetic_audio(aud8, duration=2.0)

        # Case 8a: out == original_video
        res8a = service.export_video(
            VideoExportRequest(
                original_video_path=vid8,
                final_audio_path=aud8,
                segments=[],
                output_video_path=vid8,
            )
        )

        # Case 8b: out == final_audio
        fake_aud_mp4 = os.path.join(work_dir, "sc8_audio.mp4")
        shutil.copyfile(aud8, fake_aud_mp4)
        res8b = service.export_video(
            VideoExportRequest(
                original_video_path=vid8,
                final_audio_path=fake_aud_mp4,
                segments=[],
                output_video_path=fake_aud_mp4,
            )
        )

        pass8 = (
            res8a.status == "failed"
            and "cannot overwrite original_video_path" in res8a.error
            and res8b.status == "failed"
            and "cannot overwrite final_audio_path" in res8b.error
        )

        print(f"Result 8a: status={res8a.status}, error='{res8a.error}'")
        print(f"Result 8b: status={res8b.status}, error='{res8b.error}'")
        status_str = "PASS" if pass8 else "FAIL"
        print(f"--> SCENARIO 8: {status_str}")
        if pass8:
            scenarios_passed += 1
        results_summary.append({"id": 8, "name": "Output collision rejection", "status": status_str, "detail": "Protected video and audio inputs"})

        # =====================================================================
        # SCENARIO 9: Non-.mp4 / invalid policy -> reject
        # =====================================================================
        print("\n--- [Scenario 9] Non-.mp4 / invalid policy -> reject ---")
        vid9 = os.path.join(work_dir, "sc9_in.mp4")
        aud9 = os.path.join(work_dir, "sc9_in.wav")
        out9_mkv = os.path.join(work_dir, "sc9_out.mkv")
        out9_valid = os.path.join(work_dir, "sc9_out.mp4")
        create_synthetic_video(vid9, duration=3.0)
        create_synthetic_audio(aud9, duration=2.0)

        # Case 9a: non-.mp4
        res9a = service.export_video(
            VideoExportRequest(
                original_video_path=vid9,
                final_audio_path=aud9,
                segments=[],
                output_video_path=out9_mkv,
            )
        )

        # Case 9b: invalid policy
        res9b = service.export_video(
            VideoExportRequest(
                original_video_path=vid9,
                final_audio_path=aud9,
                segments=[],
                output_video_path=out9_valid,
                overflow_policy="invalid_stretch",  # type: ignore
            )
        )

        pass9 = (
            res9a.status == "failed"
            and "must use .mp4 extension" in res9a.error
            and res9b.status == "failed"
            and "Invalid overflow_policy" in res9b.error
        )

        print(f"Result 9a: status={res9a.status}, error='{res9a.error}'")
        print(f"Result 9b: status={res9b.status}, error='{res9b.error}'")
        status_str = "PASS" if pass9 else "FAIL"
        print(f"--> SCENARIO 9: {status_str}")
        if pass9:
            scenarios_passed += 1
        results_summary.append({"id": 9, "name": "Non-.mp4 & invalid policy reject", "status": status_str, "detail": "Validation prevented execution"})

        # =====================================================================
        # SCENARIO 10: FFmpeg failure -> status="failed" + SRT cleanup
        # =====================================================================
        print("\n--- [Scenario 10] FFmpeg failure -> failed status + SRT cleanup ---")
        vid10 = os.path.join(work_dir, "sc10_in.mp4")
        aud10 = os.path.join(work_dir, "sc10_in.wav")
        out10 = os.path.join(work_dir, "sc10_out.mp4")
        create_synthetic_video(vid10, duration=3.0)
        create_synthetic_audio(aud10, duration=2.0)

        seg10 = SubtitleSegment(
            id=11,
            start=0.5,
            end=1.5,
            text="Testing SRT cleanup on failure",
            translated_text="Thử nghiệm dọn dẹp SRT khi lỗi",
        )

        # Tạo script ffmpeg giả lập thất bại
        mock_failing_ffmpeg = os.path.join(work_dir, "mock_failing_ffmpeg.bat")
        with open(mock_failing_ffmpeg, "w") as f:
            f.write("@echo Mock FFmpeg execution error occurred! 1>&2\n@exit /b 1\n")

        failing_service = VideoExportService(
            ffmpeg_bin=mock_failing_ffmpeg,
            temp_dir=temp_srt_dir,
        )

        res10 = failing_service.export_video(
            VideoExportRequest(
                original_video_path=vid10,
                final_audio_path=aud10,
                segments=[seg10],
                output_video_path=out10,
            )
        )

        srt_left10 = count_temp_srt_files(temp_srt_dir)
        pass10 = (
            res10.status == "failed"
            and "FFmpeg video export failed" in res10.error
            and "Mock FFmpeg execution error" in res10.error
            and not os.path.isfile(out10)
            and srt_left10 == 0
        )

        print(f"Result 10: status={res10.status}, error='{res10.error[:80]}...', srt_remained={srt_left10}")
        status_str = "PASS" if pass10 else "FAIL"
        print(f"--> SCENARIO 10: {status_str}")
        if pass10:
            scenarios_passed += 1
        results_summary.append({"id": 10, "name": "FFmpeg failure handling & SRT cleanup", "status": status_str, "detail": f"Handled gracefully, srt_left={srt_left10}"})

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    print("\n" + "=" * 80)
    print("BẢNG TỔNG HỢP 10 KỊCH BẢN REGRESSION BƯỚC 7.4")
    print("=" * 80)
    print(f"{'#':<3} | {'Scenario':<42} | {'Trạng thái':<10} | {'Chi tiết'}")
    print("-" * 80)
    for r in results_summary:
        print(f"{r['id']:<3} | {r['name']:<42} | {r['status']:<10} | {r['detail']}")
    print("=" * 80)
    print(f"KẾT QUẢ CUỐI CÙNG: {scenarios_passed}/{total_scenarios} SCENARIOS PASS")
    print("=" * 80)

    return 0 if scenarios_passed == total_scenarios else 1


if __name__ == "__main__":
    sys.exit(main())
