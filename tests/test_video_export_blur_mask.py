import os
import sys
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("app"))

try:
    from app.models.subtitle_segment import SubtitleSegment
    from app.services.video_export_service import (
        VideoExportService,
        VideoExportRequest,
        SubtitleRenderConfig,
        make_rounded_rect_ass,
        generate_ass_script,
    )
except ImportError:
    from models.subtitle_segment import SubtitleSegment
    from services.video_export_service import (
        VideoExportService,
        VideoExportRequest,
        SubtitleRenderConfig,
        make_rounded_rect_ass,
        generate_ass_script,
    )


def test_make_rounded_rect_ass():
    path = make_rounded_rect_ass(600, 100, 20, 540, 1440)
    assert path.startswith("m ")
    assert " b " in path
    assert " l " in path


def test_generate_ass_script_creates_rounded_badge():
    segments = [
        SubtitleSegment(id=1, start=1.5, end=3.5, text="你好", translated_text="Xin chào bạn"),
    ]
    cfg = SubtitleRenderConfig(enable_blur_mask=True)
    ass_content, cnt = generate_ass_script(segments, 1080, 1920, cfg, target_cy=1440)
    assert cnt == 1
    assert "BgBadge" in ass_content
    assert "SubText" in ass_content
    assert "Xin chào bạn" in ass_content
    # Kiểm tra vẽ hộp bo góc vector
    assert r"\p1" in ass_content
    assert r"\p0" in ass_content


def test_video_export_builds_ass_badge_filter(tmp_path):
    orig_vid = tmp_path / "test_orig.mp4"
    orig_vid.write_bytes(b"dummy_video")
    final_aud = tmp_path / "test_audio.wav"
    final_aud.write_bytes(b"dummy_audio")
    out_vid = tmp_path / "test_out.mp4"

    segments = [
        SubtitleSegment(id=1, start=0.5, end=2.0, text="测试", translated_text="Kiểm tra mặt nạ"),
    ]

    req = VideoExportRequest(
        original_video_path=str(orig_vid),
        final_audio_path=str(final_aud),
        segments=segments,
        output_video_path=str(out_vid),
        enable_blur_mask=True,
    )

    svc = VideoExportService(temp_dir=str(tmp_path / "temp"))
    captured_filter_script = []

    def mock_run(cmd, **kwargs):
        if "-filter_complex_script" in cmd:
            idx = cmd.index("-filter_complex_script")
            script_path = cmd[idx + 1]
            if os.path.isfile(script_path):
                with open(script_path, "r", encoding="utf-8") as f:
                    captured_filter_script.append(f.read())
        out_vid.write_bytes(b"final_video_output")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        return mock_proc

    with (
        patch("app.services.video_export_service.measure_media_duration", return_value=5.0),
        patch("app.services.video_export_service.probe_video_dimensions", return_value=(1080, 1920)),
        patch("subprocess.run", side_effect=mock_run),
    ):
        res = svc.export_video(req)

    assert res.status == "success"
    assert len(captured_filter_script) == 1
    script = captured_filter_script[0]

    # Kiểm tra filter áp dụng ASS subtitle với mặt nạ hộp nền bo góc
    assert "subtitles=" in script
    assert ".ass" in script


def test_color_conversion_helpers():
    from app.services.video_export_service import hex_to_ass_color, ass_color_to_hex
    assert hex_to_ass_color("#FFE5DD") == "&H00DDE5FF&"
    assert hex_to_ass_color("#000000") == "&H00000000&"
    assert hex_to_ass_color("#FFFFFF") == "&H00FFFFFF&"
    assert hex_to_ass_color("#FFD400") == "&H0000D4FF&"

    assert ass_color_to_hex("&H00DDE5FF&") == "#FFE5DD"
    assert ass_color_to_hex("&H00000000&") == "#000000"
    assert ass_color_to_hex("&H00FFFFFF&") == "#FFFFFF"


def test_generate_ass_script_without_box():
    segments = [
        SubtitleSegment(id=1, start=1.0, end=3.0, text="测试", translated_text="Chữ không nền"),
    ]
    cfg = SubtitleRenderConfig(background_box=False, badge_text_color="&H0000D4FF&")
    ass_content, cnt = generate_ass_script(segments, 1080, 1920, cfg, target_cy=1440)
    assert cnt == 1
    assert "BgBadge" not in [line.split(",")[3] for line in ass_content.splitlines() if line.startswith("Dialogue:")]
    assert "SubText" in ass_content
    assert "&H0000D4FF&" in ass_content


def test_generate_ass_script_snug_box_dimensions():
    segments = [
        SubtitleSegment(id=1, start=1.0, end=3.0, text="测试", translated_text="Tôn Hiểu Hiểu, khách cần thìa sao không lấy?"),
    ]
    cfg = SubtitleRenderConfig(background_box=True, font_size=34)
    ass_content, cnt = generate_ass_script(segments, 1080, 1920, cfg, target_cy=1440)
    assert cnt == 1
    # Kiểm tra có vẽ BgBadge và SubText
    assert r"\p1" in ass_content
    assert "BgBadge" in ass_content
    assert "SubText" in ass_content

