"""Video Export & Subtitle Rendering Service.

Implements Step 7: Subtitle Rendering & Video Export Contract v1.0:
- SubtitleMode: HARD_SUB_ONLY (burn-in directly into video stream).
- BorderStyle=1, Outline=2 (crisp black outline, white text, no opaque box).
- 3 Independent durations: video_duration, audio_duration, final_video_duration (measured from file).
- Ephemeral SRT in temp/ encoded with UTF-8 BOM (utf-8-sig) and always cleaned up in finally.
- Strict timing validation on segments (start >= 0, end > start).
- Complete original audio replacement with AAC 192k stereo.
- Overflow policies: 'shortest' (default) vs 'freeze_end' (tpad clone).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

from app.models.subtitle_segment import SubtitleSegment

OverflowPolicy = Literal["shortest", "freeze_end"]
SubtitleMode = Literal["hard_sub"]


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


def _resolve_ffprobe() -> str:
    """Xác định đường dẫn thực thi của FFprobe."""
    try:
        from app.runtime_paths import bin_path
        p = bin_path("ffmpeg", "ffprobe.exe")
        if os.path.isfile(p):
            return p
    except Exception:
        pass

    w = shutil.which("ffprobe")
    if w:
        return w

    local_fallback = os.path.join(r"d:\capcap\CapCap", "bin", "ffmpeg", "ffprobe.exe")
    if os.path.isfile(local_fallback):
        return local_fallback

    return "ffprobe"


def measure_media_duration(file_path: str, ffprobe_bin: str | None = None) -> float:
    """Đo thời lượng thực tế của tệp đa phương tiện (video hoặc audio) bằng FFprobe/wave."""
    if not os.path.isfile(file_path):
        return 0.0

    # Nếu là file WAV, thử đo bằng wave module trước (cực nhanh)
    if file_path.lower().endswith(".wav"):
        try:
            import wave
            with wave.open(file_path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return round(frames / float(rate), 3)
        except Exception:
            pass

    # Đo qua FFprobe
    probe = ffprobe_bin or _resolve_ffprobe()
    if os.path.isfile(probe) or shutil.which(probe):
        cmd = [
            probe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        kwargs: dict[str, Any] = {"capture_output": True, "timeout": 15}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            res = subprocess.run(cmd, text=True, encoding="utf-8", errors="ignore", **kwargs)
            if res.returncode == 0 and res.stdout.strip():
                return max(0.0, round(float(res.stdout.strip()), 3))
        except Exception:
            pass

    return 0.0


def probe_video_dimensions(file_path: str, ffprobe_bin: str | None = None) -> tuple[int, int]:
    """Lấy độ phân giải (width, height) của video từ file nguồn."""
    if not os.path.isfile(file_path):
        return 1280, 720

    probe = ffprobe_bin or _resolve_ffprobe()
    if os.path.isfile(probe) or shutil.which(probe):
        cmd = [
            probe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            file_path,
        ]
        kwargs: dict[str, Any] = {"capture_output": True, "timeout": 15}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            res = subprocess.run(cmd, text=True, encoding="utf-8", errors="ignore", **kwargs)
            if res.returncode == 0 and "x" in res.stdout:
                parts = res.stdout.strip().split("x")
                w, h = int(parts[0]), int(parts[1])
                if w > 0 and h > 0:
                    return w, h
        except Exception:
            pass

    # Fallback OpenCV nếu có
    try:
        import cv2
        cap = cv2.VideoCapture(file_path)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass

    return 1280, 720


def auto_detect_video_bands(
    video_path: str,
    sample_times: list[float] | None = None,
    vid_w: int = 1280,
    vid_h: int = 720,
) -> tuple[tuple[float, float, float, float] | None, tuple[float, float, float, float, float] | None]:
    """Tự động phân tích video để phát hiện 2 dải mặt nạ độc lập:
    1. bottom_dialogue_rect: (rx, ry, rw, rh) Dải phụ đề thoại ở nửa dưới video.
    2. top_header_info: (rx, ry, rw, rh, duration) Tiêu đề ở đầu video (chỉ tồn tại ở những giây đầu, sau đó tự tắt).
    """
    if not video_path or not os.path.isfile(video_path):
        return None, None

    bottom_dialogue_rect = None
    top_header_info = None

    try:
        import sys
        # Đảm bảo runtime_paths và app luôn có trong sys.path để nạp OCR engine
        _cur_dir = os.path.dirname(os.path.abspath(__file__))
        _app_dir = os.path.dirname(_cur_dir)
        _repo_root = os.path.dirname(_app_dir)
        for _p in [_repo_root, _app_dir, _cur_dir]:
            if _p and _p not in sys.path:
                sys.path.insert(0, _p)

        import cv2
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or vid_h
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or vid_w
        if h <= 0 or w <= 0:
            cap.release()
            return None, None

        from app.ocr_processor import _load_ocr_engine
        engine = _load_ocr_engine()

        # -------------------------------------------------------------
        # 1. Phát hiện Dải phụ đề thoại (Dialogue Subtitle) ở nửa dưới
        # -------------------------------------------------------------
        is_vertical = h > w
        bot_min_y = int(h * (0.55 if is_vertical else 0.62))
        bot_max_y = int(h * 0.95)

        times = sample_times if (sample_times and len(sample_times) > 0) else [1.5, 4.0, 7.0, 15.0]
        bot_boxes = []

        for st in times:
            frame_idx = max(0, int(st * fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            crop_bot = frame[bot_min_y:bot_max_y, :]
            res = engine(crop_bot, use_cls=False, text_score=0.30)
            raw_boxes = getattr(res, "boxes", None)
            if raw_boxes is not None and len(raw_boxes) > 0:
                for b in raw_boxes:
                    try:
                        xs = [pt[0] for pt in b]
                        ys = [pt[1] for pt in b]
                        bw = max(xs) - min(xs)
                        bh = max(ys) - min(ys)
                        if bw > w * 0.10 and 20 <= bh <= int(h * 0.08):
                            real_y1 = bot_min_y + min(ys)
                            real_y2 = bot_min_y + max(ys)
                            bot_boxes.append((real_y1, real_y2))
                    except Exception:
                        continue
            if len(bot_boxes) >= 4:
                break

        if bot_boxes:
            centers = [(b[0] + b[1]) / 2.0 for b in bot_boxes]
            centers.sort()
            med_c = centers[len(centers) // 2]
            heights = [b[1] - b[0] for b in bot_boxes]
            med_h = sorted(heights)[len(heights) // 2]
            box_h = max(int(h * 0.06), med_h + int(h * 0.025))
            y1 = max(0, int(med_c - box_h / 2.0))
            y2 = min(h, int(med_c + box_h / 2.0))
            ry = round(y1 / h, 4)
            rh = round((y2 - y1) / h, 4)
            bottom_dialogue_rect = (0.0, ry, 1.0, rh)
            print(f"[AutoBlurDetector] Bottom dialogue band: y={ry*100:.1f}%, h={rh*100:.1f}%, center={med_c:.1f}px")

        # -------------------------------------------------------------
        # 2. Phát hiện Tiêu đề đầu video ở trên (Top Header / Hook title)
        # -------------------------------------------------------------
        top_max_y = int(h * 0.35)
        top_duration = 0.0
        top_boxes = []

        check_times = [0.5, 2.0, 5.0, 9.0, 14.0, 18.0, 22.0]
        for t in check_times:
            frame_idx = max(0, int(t * fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            crop_top = frame[:top_max_y, :]
            res = engine(crop_top, use_cls=False, text_score=0.30)
            raw_boxes = getattr(res, "boxes", None)
            has_top_text = False
            if raw_boxes is not None and len(raw_boxes) > 0:
                for b in raw_boxes:
                    try:
                        xs = [pt[0] for pt in b]
                        ys = [pt[1] for pt in b]
                        if max(xs) - min(xs) > w * 0.15:
                            top_boxes.append((min(ys), max(ys)))
                            has_top_text = True
                    except Exception:
                        continue

            if has_top_text:
                top_duration = t + 1.2
            elif top_duration > 0:
                # Tiêu đề đã biến mất, dừng kiểm tra
                break

        if top_boxes and top_duration > 0:
            ty1 = max(0, min(b[0] for b in top_boxes) - int(h * 0.015))
            ty2 = min(h, max(b[1] for b in top_boxes) + int(h * 0.015))
            try_y = round(ty1 / h, 4)
            trh = max(0.08, round((ty2 - ty1) / h, 4))
            top_header_info = (0.0, try_y, 1.0, trh, round(top_duration, 2))
            print(f"[AutoBlurDetector] Top header band: y={try_y*100:.1f}%, h={trh*100:.1f}%, duration={top_duration:.1f}s")

        cap.release()
    except Exception as exc:
        print(f"[AutoBlurDetector] Notice: {exc}")

    return bottom_dialogue_rect, top_header_info


def auto_detect_subtitle_band_from_video(
    video_path: str, sample_times: list[float] | float = 2.0
) -> tuple[float, float, float, float] | None:
    """Tương thích ngược: Lấy dải phụ đề thoại chính."""
    times = [sample_times] if isinstance(sample_times, (int, float)) else sample_times
    bot, _ = auto_detect_video_bands(video_path, sample_times=times)
    return bot



def format_srt_timecode(seconds: float) -> str:
    """Chuyển đổi giây sang định dạng thời gian chuẩn SRT (HH:MM:SS,mmm)."""
    total_ms = max(0, int(round(float(seconds or 0.0) * 1000)))
    total_sec, ms = divmod(total_ms, 1000)
    minutes, sec = divmod(total_sec, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d},{ms:03d}"


def make_rounded_rect_ass(w: int, h: int, r: int, cx: int, cy: int) -> str:
    """Tạo đường vẽ Bezier bo góc (Rounded Rectangle) chuẩn ASS vector."""
    x1 = cx - w // 2
    y1 = cy - h // 2
    x2 = x1 + w
    y2 = y1 + h
    r = max(4, min(r, h // 2, w // 2))
    k = int(round(r * 0.5523))
    return (
        f"m {x1+r} {y1} "
        f"l {x2-r} {y1} "
        f"b {x2-r+k} {y1} {x2} {y1+r-k} {x2} {y1+r} "
        f"l {x2} {y2-r} "
        f"b {x2} {y2-r+k} {x2-r+k} {y2} {x2-r} {y2} "
        f"l {x1+r} {y2} "
        f"b {x1+r-k} {y2} {x1} {y2-r+k} {x1} {y2-r} "
        f"l {x1} {y1+r} "
        f"b {x1} {y1+r-k} {x1+r-k} {y1} {x1+r} {y1}"
    )


def format_ass_time(seconds: float) -> str:
    """Chuyển đổi giây sang định dạng thời gian chuẩn ASS (H:MM:SS.cs)."""
    total_cs = max(0, int(round(float(seconds or 0.0) * 100)))
    total_sec, cs = divmod(total_cs, 100)
    minutes, sec = divmod(total_sec, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}.{cs:02d}"


def hex_to_ass_color(hex_str: str, alpha: float = 1.0) -> str:
    """Chuyển đổi mã màu Hex (#RRGGBB hoặc #RGB) sang định dạng chuẩn ASS &HAABBGGRR&."""
    s = str(hex_str or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) < 6:
        s = "FFFFFF"
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        r, g, b = 255, 255, 255
    # Trong ASS: Alpha 00 = hoàn toàn đặc (opaque), FF = trong suốt (transparent)
    a = int(round((1.0 - max(0.0, min(1.0, float(alpha)))) * 255))
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}&"


def ass_color_to_hex(ass_str: str) -> str:
    """Chuyển đổi mã màu ASS (&HAABBGGRR& hoặc &HBBGGRR&) sang Hex chuẩn #RRGGBB."""
    clean = str(ass_str or "").replace("&H", "").replace("&", "").strip().upper()
    if len(clean) == 8:
        # AABBGGRR
        b = clean[2:4]
        g = clean[4:6]
        r = clean[6:8]
        return f"#{r}{g}{b}"
    elif len(clean) == 6:
        # BBGGRR
        b = clean[0:2]
        g = clean[2:4]
        r = clean[4:6]
        return f"#{r}{g}{b}"
    return "#FFFFFF"


def generate_ass_script(
    segments: list[SubtitleSegment],
    vid_w: int,
    vid_h: int,
    cfg: "SubtitleRenderConfig",
    target_cy: int | None = None,
    enable_mask: bool = True,
    duration: float = 0.0,
    user_rect: tuple[float, float, float, float] | None = None,
    mask_mode: str | None = None,
) -> tuple[str, int]:
    """Sinh kịch bản ASS với kiểu dáng tùy biến: hộp nền ôm sát chữ (che video gốc) hoặc dải làm mờ ngang (Ảnh 1) và chữ rõ nét."""
    is_vertical = vid_h > vid_w
    scale_ref = 1080.0
    res_scale = (vid_w / scale_ref) if is_vertical else (vid_h / scale_ref)
    user_size = int(getattr(cfg, "font_size", 34) or 34)
    user_scale = float(getattr(cfg, "font_scale", 1.0) or 1.0)
    font_size = max(18, int(round(user_size * user_scale * res_scale)))

    eff_mask_mode = str(mask_mode if mask_mode is not None else getattr(cfg, "mask_mode", "box") or "box").strip().lower()

    if target_cy is None:
        if user_rect and len(user_rect) == 4 and user_rect[2] > 0 and user_rect[3] > 0:
            target_cy = int(round((user_rect[1] + user_rect[3] / 2.0) * vid_h))
        else:
            target_cy = int(round(vid_h * (0.74 if is_vertical else 0.82)))

    bg_color = getattr(cfg, "badge_bg_color", "&H00000000&") or "&H00000000&"
    text_color = getattr(cfg, "badge_text_color", "&H00FFFFFF&") or "&H00FFFFFF&"
    font_name = getattr(cfg, "font_name", "Arial") or "Arial"
    bold = getattr(cfg, "bold", True)

    # Chế độ mặt nạ / che chữ
    if eff_mask_mode == "blur":
        # Mặt nạ làm mờ ngang (Ảnh 1): Đã có dải video mờ che chữ gốc, không dùng hộp đen BgBadge
        has_box = False
        text_color = "&H00FFFFFF&"
        outline_col = "&H00000000&"
        outline_w = max(4, int(round(font_size * 0.13)))
        bold = True
        font_size = max(font_size, int(round(font_size * 1.05)))
    elif eff_mask_mode == "none":
        has_box = False
        outline_w = getattr(cfg, "outline_width", 3)
        outline_col = getattr(cfg, "outline_color", "&H00000000") or "&H00000000"
    else:  # "box"
        has_box = getattr(cfg, "background_box", True) and enable_mask
        outline_w = getattr(cfg, "outline_width", 3) if not has_box else 0
        outline_col = getattr(cfg, "outline_color", "&H00000000") or "&H00000000"

    animation = str(getattr(cfg, "animation", "Pop In") or "Pop In").strip().lower()

    # Thẻ hiệu ứng chữ phụ đề
    anim_tag = ""
    if "pop" in animation:
        anim_tag = r"\fad(80,60)\fscx108\fscy108\t(0,180,\fscx100\fscy100)"
    elif "fade" in animation or "mờ" in animation:
        anim_tag = r"\fad(180,120)"
    elif "slide" in animation or "trượt" in animation:
        anim_tag = r"\fad(120,80)"

    watermark_text = str(getattr(cfg, "watermark_text", "") or "").strip()
    enable_watermark = bool(getattr(cfg, "enable_watermark", False)) and bool(watermark_text)

    watermark_style_def = ""
    if enable_watermark:
        wm_pos = str(getattr(cfg, "watermark_position", "center") or "center").strip().lower()
        align_map = {
            "center": 5,
            "center_bottom": 2,
            "top_left": 7,
            "top_right": 9,
            "bottom_left": 1,
            "bottom_right": 3,
            "top_center": 8,
        }
        wm_align = align_map.get(wm_pos, 5)
        wm_base_size = int(getattr(cfg, "watermark_font_size", 36) or 36)
        wm_font_size = max(16, int(round(wm_base_size * res_scale)))
        wm_opacity = max(0.05, min(1.0, float(getattr(cfg, "watermark_opacity", 0.35) or 0.35)))
        wm_color_hex = str(getattr(cfg, "watermark_color", "#FFFFFF") or "#FFFFFF")
        wm_ass_color = hex_to_ass_color(wm_color_hex, alpha=wm_opacity)
        wm_outline_ass = hex_to_ass_color("#000000", alpha=wm_opacity * 0.7)
        margin_lr = int(round(vid_w * 0.04))
        margin_v = int(round(vid_h * 0.04))
        if wm_pos == "center_bottom":
            margin_v = int(round(vid_h * (0.28 if is_vertical else 0.20)))
        watermark_style_def = f"Style: Watermark,{font_name},{wm_font_size},{wm_ass_color},&H000000FF,{wm_outline_ass},&H00000000,1,0,0,0,100,100,1,0,1,1,0,{wm_align},{margin_lr},{margin_lr},{margin_v},1\n"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {vid_w}
PlayResY: {vid_h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BgBadge,{font_name},20,{bg_color},&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: SubText,{font_name},{font_size},{text_color},&H000000FF,{outline_col},&H00000000,{1 if bold else 0},0,0,0,100,100,0,0,1,{outline_w},0,5,0,0,0,1
{watermark_style_def}
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines: list[str] = []
    char_w = int(round(font_size * 0.48))
    max_line_w = int(round(vid_w * 0.86))
    max_chars_per_line = max(16, max_line_w // max(1, char_w))
    rendered_cnt = 0

    user_has_rect = (user_rect is not None and len(user_rect) == 4 and user_rect[2] > 0 and user_rect[3] > 0)

    for s in segments:
        text = str(getattr(s, "translated_text", "") or "").strip()
        if not text or getattr(s, "is_noise", False) or s.end <= s.start:
            continue

        rendered_cnt += 1
        words = text.split()
        lines: list[str] = []
        cur: list[str] = []
        cur_len = 0
        for w in words:
            if cur_len + len(w) + 1 > max_chars_per_line and cur:
                lines.append(" ".join(cur))
                cur = [w]
                cur_len = len(w)
            else:
                cur.append(w)
                cur_len += len(w) + (1 if cur_len > 0 else 0)
        if cur:
            lines.append(" ".join(cur))

        # Tọa độ Y riêng của từng segment
        seg_cy = target_cy
        # NẾU ĐÃ CÓ user_rect (người dùng quét OCR): TUYỆT ĐỐI KHÔNG để bbox ngẫu nhiên làm lệch tâm phụ đề!
        if not user_has_rect:
            bbox = getattr(s, "bbox", None)
            if bbox and len(bbox) == 4:
                try:
                    by1, by2 = float(bbox[1]), float(bbox[3])
                    if 0.10 <= by1 < by2 <= 0.98 and (by2 - by1) <= 0.18:
                        cand_cy = int(round(((by1 + by2) / 2.0) * vid_h))
                        if target_cy is None or abs(cand_cy - target_cy) <= int(round(vid_h * 0.08)):
                            seg_cy = cand_cy
                except Exception:
                    pass

        num_lines = len(lines)
        longest_line_chars = max(len(l) for l in lines)
        # Khoảng đệm ôm sát chữ (vừa vặn, che kín video gốc, không bị to cồng kềnh)
        pad_x = int(round(font_size * 0.55))
        box_w = min(max_line_w, longest_line_chars * char_w + pad_x * 2)
        line_h = int(round(font_size * 1.25))
        pad_y = int(round(font_size * 0.28))
        box_h = num_lines * line_h + pad_y * 2
        # Đảm bảo chiều cao tối thiểu che kín dòng chữ gốc trên video
        min_box_h = max(int(round(font_size * 1.45)), 48 if is_vertical else 38)
        if user_has_rect:
            user_h_px = int(round(user_rect[3] * vid_h))
            min_user_box_h = int(round(user_h_px * 1.25))
            min_box_h = max(min_box_h, min_user_box_h)
        box_h = max(min_box_h, box_h)
        radius = min(14, int(box_h * 0.22))

        start_t = format_ass_time(s.start)
        end_t = format_ass_time(s.end)
        ass_text = r"\N".join(lines)

        if has_box:
            shape = make_rounded_rect_ass(box_w, box_h, radius, vid_w // 2, seg_cy)
            dialogue_lines.append(
                f"Dialogue: 0,{start_t},{end_t},BgBadge,,0,0,0,,{{\\pos(0,0)\\p1\\1c{bg_color}\\bord0\\shad0}}{shape}{{\\p0}}"
            )

        dialogue_lines.append(
            f"Dialogue: 1,{start_t},{end_t},SubText,,0,0,0,,{{\\pos({vid_w // 2},{seg_cy})\\an5\\c{text_color}\\bord{outline_w}\\3c{outline_col}\\shad0\\b{1 if bold else 0}\\fs{font_size}{anim_tag}}}{ass_text}"
        )

    # Thêm dòng Watermark chữ chạy xuyên suốt toàn bộ video
    if enable_watermark:
        end_time_sec = max(float(duration or 0.0), 36000.0)
        end_time_ass = format_ass_time(end_time_sec)
        dialogue_lines.insert(
            0,
            f"Dialogue: 10,0:00:00.00,{end_time_ass},Watermark,,0,0,0,,{watermark_text}"
        )
        rendered_cnt += 1

    return header + "\n".join(dialogue_lines) + "\n", rendered_cnt


@dataclass
class SubtitleRenderConfig:
    """Cấu hình hiển thị phụ đề Hardsub tiếng Việt Unicode và Mặt nạ che chữ gốc."""
    font_name: str = "Arial"
    font_size: int = 34                   # Kích cỡ chuẩn vừa vặn, thanh thoát
    font_scale: float = 1.0               # Tỷ lệ co giãn (0.75x -> 1.5x)
    primary_color: str = "&H00FFFFFF&"    # Chữ trắng
    outline_color: str = "&H00000000&"    # Viền đen
    border_style: int = 1                 # 1 = Chữ + Outline
    outline_width: int = 3                # Độ dày viền outline
    margin_v: int = 25                    # Cách đáy video
    bold: bool = True                     # In đậm
    enable_blur_mask: bool = True         # Mặt nạ hộp nền bo góc phong cách hiện đại
    blur_rect: tuple[float, float, float, float] | None = None  # (x, y, w, h) normalized 0.0-1.0
    blur_strength: int = 18               # Bán kính làm mờ
    background_box: bool = True           # Bật/tắt hộp nền
    badge_bg_color: str = "&H00000000&"    # Hộp nền đen ôm sát chữ che video gốc phong cách Ảnh 3
    badge_text_color: str = "&H00FFFFFF&"  # Màu chữ trắng sắc nét nổi bật
    box_alpha: float = 1.0                # Độ mờ của hộp nền (1.0 = đặc hoàn toàn)
    box_radius: int = 12                  # Bo tròn góc (px)
    animation: str = "Pop In"             # Hiệu ứng xuất hiện
    preset_name: str = "black_box"        # Tên mẫu định sẵn
    mask_mode: str = "box"                # Kiểu mặt nạ: "blur" (Ảnh 1), "box" (Ảnh 2), "none"
    # Watermark chữ cấu hình
    enable_watermark: bool = False
    watermark_text: str = ""
    watermark_position: str = "center"
    watermark_font_size: int = 36
    watermark_opacity: float = 0.35
    watermark_color: str = "#FFFFFF"
    # Logo thương hiệu cấu hình
    enable_brand_logo: bool = False
    brand_logo_path: str = ""
    brand_logo_position: str = "top_left"
    brand_logo_size_percent: int = 15
    brand_logo_opacity: float = 1.0
    # Xóa / Tẩy Logo & Watermark video gốc (Bilibili, Douyin, Bản quyền mờ)
    delogo_bilibili: bool = False
    delogo_watermark: bool = False
    delogo_watermark_rect: tuple[float, float, float, float] | None = None
    delogo_watermark_mode: str = "delogo"  # "delogo" (Xóa sạch tàng hình, 0s), "telea", "boxblur"
    delogo_custom_rect: tuple[float, float, float, float] | None = None
    delogo_custom_mode: Literal["delogo", "boxblur", "inpaint"] = "inpaint"


@dataclass
class VideoExportRequest:
    """Đầu vào yêu cầu xuất bản video hoàn chỉnh."""
    original_video_path: str
    final_audio_path: str
    segments: list[SubtitleSegment]
    output_video_path: str
    overflow_policy: OverflowPolicy = "shortest"
    subtitle_config: SubtitleRenderConfig = field(default_factory=SubtitleRenderConfig)
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
    delogo_watermark_mode: str = "delogo"  # "delogo" (Xóa sạch tàng hình, 0s), "telea", "boxblur"
    delogo_custom_rect: tuple[float, float, float, float] | None = None
    delogo_custom_mode: Literal["delogo", "boxblur", "inpaint"] = "inpaint"


def build_delogo_filters(
    vid_w: int,
    vid_h: int,
    delogo_bilibili: bool,
    delogo_watermark: bool,
    delogo_custom_rect: tuple[float, float, float, float] | None = None,
    delogo_custom_mode: str = "delogo",
    current_v: str = "0:v",
    delogo_watermark_rect: tuple[float, float, float, float] | None = None,
    delogo_watermark_mode: str = "delogo",
    has_top_right_logo: bool = False,
) -> tuple[list[str], str]:
    """Tạo chuỗi filter FFmpeg để xóa logo Bilibili/Douyin, xóa watermark mờ và xóa vùng tùy chọn.
    
    Áp dụng thuật toán nội suy điểm ảnh Delogo (xóa logo góc và tẩy sạch chữ mà KHÔNG tạo mặt nạ mờ che khuất video).
    """
    is_vertical = vid_h > vid_w
    filters: list[str] = []
    idx = 1

    def _sanitize_box(x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        px_x = int(round(x * vid_w))
        px_y = int(round(y * vid_h))
        px_w = int(round(w * vid_w))
        px_h = int(round(h * vid_h))
        # Đảm bảo số chẵn cho chuẩn yuv420p
        px_x = px_x + (px_x % 2)
        px_y = px_y + (px_y % 2)
        px_w = max(16, px_w - (px_w % 2))
        px_h = max(16, px_h - (px_h % 2))
        # Giới hạn an toàn trong khung hình video (cách mép ít nhất 2px để delogo nội suy biên)
        px_x = max(2, min(px_x, vid_w - px_w - 2))
        px_y = max(2, min(px_y, vid_h - px_h - 2))
        px_w = max(16, min(px_w, vid_w - px_x - 2))
        px_h = max(16, min(px_h, vid_h - px_y - 2))
        return px_x, px_y, px_w, px_h

    # 1. Logo Bilibili / Douyin góc trên bên phải (ôm sát logo, xóa sạch viền không nhòe góc)
    # Tự động xóa sạch nếu bật delogo_bilibili HOẶC khi có Logo thương hiệu góc trên phải để nền phía dưới sạch bóng 100%
    if delogo_bilibili or has_top_right_logo:
        if is_vertical:
            rx, ry, rw, rh = 0.78, 0.012, 0.20, 0.055
        else:
            # Video ngang 16:9: Mở rộng vùng quét bao trọn cả tên kênh 星白漫 lẫn logo bilibili
            rx, ry, rw, rh = 0.78, 0.008, 0.21, 0.075
        bx, by, bw, bh = _sanitize_box(rx, ry, rw, rh)
        out_v = f"v_delogo_{idx}"
        filters.append(f"[{current_v}]delogo=x={bx}:y={by}:w={bw}:h={bh}:show=0[{out_v}]")
        current_v = out_v
        idx += 1

    # 2. Xóa Watermark chữ bản quyền: XÓA SẠCH TÀNG HÌNH BẰNG DELOGO NỘI SUY (TUYỆT ĐỐI KHÔNG DÙNG MẶT NẠ MỜ CHE Ở GIỮA)
    if delogo_watermark:
        if delogo_watermark_rect and len(delogo_watermark_rect) == 4 and delogo_watermark_rect[2] > 0.01:
            rx, ry, rw, rh = delogo_watermark_rect
            # Giới hạn an toàn: Nếu vùng chọn quá cao (> 5.5% chiều cao video), delogo nội suy sẽ tạo vệt sọc đứng biến dạng
            # Tự động thu hẹp chiều cao về vùng trung tâm thực tế của chữ mờ (cao ~4.8% video) để xóa sạch mịn màng
            if rh > 0.055:
                ry_center = ry + rh / 2.0
                rh = 0.048
                ry = max(0.01, ry_center - rh / 2.0)
        elif is_vertical:
            rx, ry, rw, rh = 0.25, 0.65, 0.50, 0.045
        else:
            rx, ry, rw, rh = 0.35, 0.49, 0.30, 0.045
        bx, by, bw, bh = _sanitize_box(rx, ry, rw, rh)
        out_v = f"v_wm_{idx}"
        # Thuật toán Delogo nội suy điểm ảnh: Tẩy sạch dòng chữ mà giữ nguyên 100% bối cảnh gốc, không để lại vết mờ
        filters.append(f"[{current_v}]delogo=x={bx}:y={by}:w={bw}:h={bh}:show=0[{out_v}]")
        current_v = out_v
        idx += 1

    # 3. Vùng xóa tùy chỉnh do người dùng chỉ định
    if delogo_custom_rect and len(delogo_custom_rect) == 4:
        crx, cry, crw, crh = delogo_custom_rect
        if crw > 0.01 and crh > 0.01:
            # Nếu người dùng đã dán Brand Logo ở góc trên phải và vùng xóa này cũng nằm ở góc trên phải:
            # Chính Brand Logo sẽ che kín 100% góc này, bỏ qua để tránh tạo vết mờ bao quanh / đè logo!
            is_top_right = (crx >= 0.60 and cry <= 0.25)
            if not (has_top_right_logo and is_top_right):
                bx, by, bw, bh = _sanitize_box(crx, cry, crw, crh)
                out_v = f"v_custom_{idx}"
                if str(delogo_custom_mode).lower() == "boxblur":
                    min_dim = min(bw, bh)
                    luma_r = max(2, min(10, int(min_dim // 3)))
                    chroma_r = max(1, min(5, int(min_dim // 6)))
                    filters.append(
                        f"[{current_v}]split[v_main_{idx}][v_crop_{idx}];"
                        f"[v_crop_{idx}]crop={bw}:{bh}:{bx}:{by},boxblur={luma_r}:2:{chroma_r}:2[v_blur_{idx}];"
                        f"[v_main_{idx}][v_blur_{idx}]overlay={bx}:{by}[{out_v}]"
                    )
                else:
                    # Mặc định: Xóa tàng hình sạch sẽ bằng delogo
                    filters.append(f"[{current_v}]delogo=x={bx}:y={by}:w={bw}:h={bh}:show=0[{out_v}]")
                current_v = out_v
                idx += 1

    return filters, current_v


@dataclass
class VideoExportResult:
    """Đầu ra báo cáo kết quả xuất xưởng video."""
    output_video_path: str = ""
    video_duration: float = 0.0
    audio_duration: float = 0.0
    final_video_duration: float = 0.0
    rendered_subtitles_count: int = 0
    skipped_subtitles_count: int = 0
    applied_overflow_policy: str = "shortest"
    status: Literal["success", "failed"] = "success"
    warning: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VideoExportService:
    """Service phụ trách xuất bản video hoàn thiện với hardsub tiếng Việt và âm thanh hòa âm."""

    def __init__(
        self,
        *,
        ffmpeg_bin: str | None = None,
        ffprobe_bin: str | None = None,
        temp_dir: str = "temp",
    ):
        self.ffmpeg_bin = ffmpeg_bin or _resolve_ffmpeg()
        self.ffprobe_bin = ffprobe_bin or _resolve_ffprobe()
        self.temp_dir = temp_dir

    def generate_srt_content(
        self,
        segments: list[SubtitleSegment],
    ) -> tuple[str, int, int]:
        """Sinh chuỗi nội dung SRT chuẩn từ danh sách SubtitleSegment.
        
        Tuân thủ nghiêm ngặt Contract 7.1:
        1. Timing validation: start >= 0 và end > start (nếu sai ném ValueError).
        2. Bỏ qua nếu is_noise == True.
        3. Bỏ qua nếu translated_text.strip() == "".
        4. Render cho cả nam, nữ, unknown, none nếu có nội dung dịch.
        
        Returns:
            (srt_text, rendered_count, skipped_count)
        """
        blocks: list[str] = []
        rendered_count = 0
        skipped_count = 0

        for seg in segments:
            # Timing validation
            if seg.start < 0 or seg.end <= seg.start:
                raise ValueError(
                    f"Invalid segment timing: id={seg.id}, start={seg.start}, end={seg.end}"
                )

            # Skip noise
            if getattr(seg, "is_noise", False):
                skipped_count += 1
                continue

            # Text selection
            trans_text = str(getattr(seg, "translated_text", "") or "").strip()
            if not trans_text:
                # Nếu không có bản dịch -> bỏ qua, không sinh phụ đề trống
                skipped_count += 1
                continue

            rendered_count += 1
            start_tc = format_srt_timecode(seg.start)
            end_tc = format_srt_timecode(seg.end)
            block = f"{rendered_count}\n{start_tc} --> {end_tc}\n{trans_text}\n"
            blocks.append(block)

        return "\n".join(blocks), rendered_count, skipped_count

    def export_video(self, request: VideoExportRequest) -> VideoExportResult:
        """Thực hiện xuất bản video theo toàn bộ Contract 7.1 & 7.2."""
        temp_srt_path: str = ""
        temp_ass_path: str = ""

        # =====================================================================
        # 1. VALIDATION INPUTS & IMMUTABILITY (FAIL-FAST)
        # =====================================================================
        # 1.1. Validate overflow_policy
        if request.overflow_policy not in {"shortest", "freeze_end"}:
            return VideoExportResult(
                status="failed",
                error=f"Invalid overflow_policy: '{request.overflow_policy}'. Supported policies: ['shortest', 'freeze_end']",
            )

        # 1.2. Validate output extension .mp4
        if not str(request.output_video_path or "").lower().endswith(".mp4"):
            return VideoExportResult(
                status="failed",
                error=f"output_video_path must use .mp4 extension (got '{request.output_video_path}')",
            )

        if not request.original_video_path or not os.path.isfile(request.original_video_path):
            return VideoExportResult(
                status="failed",
                error=f"Original video file not found: '{request.original_video_path}'",
            )

        if not request.final_audio_path or not os.path.isfile(request.final_audio_path):
            return VideoExportResult(
                status="failed",
                error=f"Final audio file not found: '{request.final_audio_path}'",
            )

        orig_vid_abs = os.path.abspath(request.original_video_path)
        final_aud_abs = os.path.abspath(request.final_audio_path)
        out_vid_abs = os.path.abspath(request.output_video_path)

        if out_vid_abs == orig_vid_abs:
            return VideoExportResult(
                status="failed",
                error="output_video_path cannot overwrite original_video_path",
            )

        if out_vid_abs == final_aud_abs:
            return VideoExportResult(
                status="failed",
                error="output_video_path cannot overwrite final_audio_path",
            )

        # Đo thời lượng 2 luồng đầu vào
        t_video = measure_media_duration(request.original_video_path, self.ffprobe_bin)
        t_audio = measure_media_duration(request.final_audio_path, self.ffprobe_bin)


        if t_video <= 0.0:
            return VideoExportResult(
                status="failed",
                error=f"Invalid or unreadable original video: '{request.original_video_path}'",
            )

        if t_audio <= 0.0:
            return VideoExportResult(
                status="failed",
                error=f"Invalid or unreadable final audio: '{request.final_audio_path}'",
            )

        # =====================================================================
        # 2. GENERATE EPHEMERAL SRT (UTF-8 WITH BOM)
        # =====================================================================
        try:
            srt_content, rendered_cnt, skipped_cnt = self.generate_srt_content(request.segments)
        except ValueError as val_err:
            return VideoExportResult(
                video_duration=t_video,
                audio_duration=t_audio,
                status="failed",
                error=str(val_err),
            )

        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(os.path.dirname(out_vid_abs) or ".", exist_ok=True)

        # Tạo file SRT tạm thời trong temp/
        temp_srt_path = os.path.join(
            self.temp_dir,
            f"export_sub_{int(time.time() * 1000)}_{os.getpid()}.srt",
        )
        filter_script_path: str = ""
        try:
            with open(temp_srt_path, "w", encoding="utf-8-sig") as sf:
                sf.write(srt_content)

            # =====================================================================
            # 3. CONFIGURE FILTER GRAPH: FREEZE_END -> BLUR MASK -> HARD SUBTITLES
            # =====================================================================
            warning_msg = ""
            vid_w, vid_h = probe_video_dimensions(request.original_video_path, self.ffprobe_bin)
            filter_chains: list[str] = []
            current_v = "0:v"

            # 3.1. Áp dụng freeze_end nếu T_audio > T_video và được yêu cầu
            if t_audio > t_video:
                if request.overflow_policy == "freeze_end":
                    freeze_dur = round(t_audio - t_video, 3)
                    filter_chains.append(f"[{current_v}]tpad=stop_mode=clone:stop_duration={freeze_dur}[v_padded]")
                    current_v = "v_padded"
                    warning_msg = (
                        f"Audio duration ({t_audio:.2f}s) exceeds video duration ({t_video:.2f}s). "
                        f"Video extended with freeze frame to {t_audio:.2f}s."
                    )
                else:
                    warning_msg = (
                        f"Audio duration ({t_audio:.2f}s) exceeds video duration ({t_video:.2f}s). "
                        f"Applied '-shortest' policy."
                    )

            cfg = request.subtitle_config

            # 3.1b. Áp dụng Xóa Logo Bilibili & Watermark Video Gốc (Delogo AI & BoxBlur)
            delogo_bili = getattr(request, "delogo_bilibili", False) or getattr(cfg, "delogo_bilibili", False)
            delogo_wm = getattr(request, "delogo_watermark", False) or getattr(cfg, "delogo_watermark", False)
            delogo_c_rect = getattr(request, "delogo_custom_rect", None) or getattr(cfg, "delogo_custom_rect", None)
            delogo_c_mode = getattr(request, "delogo_custom_mode", "delogo") or getattr(cfg, "delogo_custom_mode", "delogo")

            # Nếu người dùng chọn chế độ AI Inpainting hoặc OpenCV Telea siêu tốc
            if str(delogo_c_mode).lower() in ("inpaint", "lama", "telea") and delogo_c_rect and len(delogo_c_rect) == 4:
                try:
                    from app.services.video_inpainting_service import VideoInpaintingService
                    inpaint_svc = VideoInpaintingService()
                    dir_name = os.path.dirname(request.original_video_path)
                    base_n, ext = os.path.splitext(os.path.basename(request.original_video_path))
                    actual_mode = "telea" if str(delogo_c_mode).lower() == "telea" else "lama"
                    inpaint_clean_path = os.path.join(dir_name, f"{base_n}_inpainted_{actual_mode}{ext}")

                    if not os.path.isfile(inpaint_clean_path):
                        print(f"[ExportVideo] Running Inpainting ({actual_mode}) on {request.original_video_path} with rect {delogo_c_rect}...")
                        ok = inpaint_svc.inpaint_video(
                            input_video_path=request.original_video_path,
                            output_video_path=inpaint_clean_path,
                            bbox=delogo_c_rect,
                            mode=actual_mode,
                        )
                        if ok and os.path.isfile(inpaint_clean_path):
                            request.original_video_path = inpaint_clean_path
                    else:
                        request.original_video_path = inpaint_clean_path
                    # Đã inpaint sạch bóng bằng AI / Telea, bỏ qua bộ lọc delogo FFmpeg cho vùng này
                    delogo_c_rect = None
                except Exception as inpaint_exc:
                    print(f"[ExportVideo] Inpainting notice: {inpaint_exc}")

            # 3.1. Nhận diện cấu hình Brand Logo trước để phối hợp tránh tạo vết mờ che logo góc trên phải
            enable_logo = getattr(request, "enable_brand_logo", False) or getattr(cfg, "enable_brand_logo", False)
            logo_path = str(getattr(request, "brand_logo_path", "") or getattr(cfg, "brand_logo_path", "")).strip()
            has_logo = enable_logo and bool(logo_path) and os.path.isfile(logo_path)
            logo_pos = str(getattr(request, "brand_logo_position", None) or getattr(cfg, "brand_logo_position", "top_left") or "top_left").strip().lower()
            has_top_right_logo = (has_logo and logo_pos == "top_right")

            delogo_wm_rect = getattr(request, "delogo_watermark_rect", None) or getattr(cfg, "delogo_watermark_rect", None)
            delogo_wm_mode = getattr(request, "delogo_watermark_mode", "delogo") or getattr(cfg, "delogo_watermark_mode", "delogo")
            if delogo_bili or delogo_wm or (delogo_c_rect and len(delogo_c_rect) == 4):
                delogo_filters, current_v = build_delogo_filters(
                    vid_w=vid_w,
                    vid_h=vid_h,
                    delogo_bilibili=delogo_bili,
                    delogo_watermark=delogo_wm,
                    delogo_custom_rect=delogo_c_rect,
                    delogo_custom_mode=delogo_c_mode,
                    current_v=current_v,
                    delogo_watermark_rect=delogo_wm_rect,
                    delogo_watermark_mode=delogo_wm_mode,
                    has_top_right_logo=has_top_right_logo,
                )
                filter_chains.extend(delogo_filters)
                print(f"[ExportVideo] Applied delogo filters ({len(delogo_filters)}): bili={delogo_bili}, wm={delogo_wm}, custom={bool(delogo_c_rect)}")

            # 3.2. Cấu hình Mặt Nạ Che Chữ và Xác Định Vị Trí Phụ Đề
            enable_blur = getattr(request, "enable_blur_mask", True) and getattr(cfg, "enable_blur_mask", True)
            mask_mode = str(getattr(request, "mask_mode", None) or getattr(cfg, "mask_mode", "box") or "box").strip().lower()

            # Lấy thông tin user_rect (khung OCR hoặc khung che chữ do người dùng chỉ định)
            user_rect = request.blur_rect or getattr(cfg, "blur_rect", None)
            if not user_rect:
                rect_str = os.getenv("OCR_SUBTITLE_RECT", "").strip()
                if rect_str:
                    try:
                        parts = [float(p) for p in rect_str.split(",")]
                        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
                            user_rect = (parts[0], parts[1], parts[2], parts[3])
                    except Exception:
                        user_rect = None

            # Xác định tọa độ Y trung tâm của phụ đề để đè mặt nạ và chữ tiếng Việt lên đúng chữ tiếng Trung gốc
            target_cy = None

            # 1. ƯU TIÊN SỐ 1: Tôn trọng tuyệt đối khung OCR / Vùng che do người dùng thiết lập
            if user_rect and len(user_rect) == 4 and user_rect[2] > 0 and user_rect[3] > 0:
                target_cy = int(round((user_rect[1] + user_rect[3] / 2.0) * vid_h))
                print(f"[ExportVideo] Subtitle target center from user blur_rect: cy={target_cy}px (y={user_rect[1]:.2f}, h={user_rect[3]:.2f})")

            # 2. ƯU TIÊN SỐ 2: Kiểm tra bbox trong các segments (nếu OCR đã ghi nhận tọa độ chữ tiếng Trung)
            if target_cy is None:
                valid_segs_with_bbox = []
                for s in request.segments:
                    if str(getattr(s, "translated_text", "") or "").strip() and not getattr(s, "is_noise", False):
                        bb = getattr(s, "bbox", None)
                        if bb and len(bb) == 4:
                            try:
                                by1, by2 = float(bb[1]), float(bb[3])
                                if 0.10 <= by1 < by2 <= 0.98 and (by2 - by1) <= 0.18:
                                    valid_segs_with_bbox.append((by1 + by2) / 2.0)
                            except Exception:
                                pass
                if valid_segs_with_bbox:
                    valid_segs_with_bbox.sort()
                    mid_idx = len(valid_segs_with_bbox) // 2
                    target_cy = int(round(valid_segs_with_bbox[mid_idx] * vid_h))
                    print(f"[ExportVideo] Subtitle target center from segment bbox: cy={target_cy}px")

            # 3. ƯU TIÊN SỐ 3: Nếu không có user_rect và segments chưa có bbox, tự động dò vị trí chữ tiếng Trung thoại thực tế trên video
            if target_cy is None:
                valid_segs = [s for s in request.segments if str(getattr(s, "translated_text", "") or "").strip() and not getattr(s, "is_noise", False)]
                sample_times = [(s.start + s.end) / 2.0 for s in valid_segs if s.end > s.start][:6]
                bot_detected, _ = auto_detect_video_bands(
                    request.original_video_path,
                    sample_times=sample_times,
                    vid_w=vid_w,
                    vid_h=vid_h,
                )
                if bot_detected:
                    target_cy = int(round((bot_detected[1] + bot_detected[3] / 2.0) * vid_h))
                    print(f"[ExportVideo] Subtitle target center from auto detector: cy={target_cy}px")

            # 4. Fallback cuối cùng theo tỷ lệ chuẩn video dọc 9:16 (74.3%) hoặc video ngang 16:9 (83%)
            if target_cy is None:
                target_cy = int(round(vid_h * (0.743 if vid_h > vid_w else 0.83)))

            # 3.3. Áp dụng Mặt Nạ Làm Mờ (Blur Mask): Che sạch chữ Trung gốc gọn gàng thanh thoát
            if enable_blur and mask_mode == "blur":
                if user_rect and len(user_rect) == 4 and user_rect[2] > 0 and user_rect[3] > 0:
                    ocr_y = int(round(user_rect[1] * vid_h))
                    ocr_h = int(round(user_rect[3] * vid_h))
                    ocr_x = int(round(user_rect[0] * vid_w))
                    ocr_w = int(round(user_rect[2] * vid_w))

                    # Thu hẹp chiều cao thanh thoát vừa vặn ôm khít chữ Trung, tuyệt đối không phình to
                    pad_v = max(2, int(round(vid_h * 0.003)))
                    strip_y = max(0, ocr_y - pad_v)
                    strip_h = ocr_h + pad_v * 2

                    # Về chiều rộng: Chỉ làm mờ trong phạm vi dòng chữ Trung (mở rộng nhẹ 2 bên để êm biên)
                    # KHÔNG KÉO DÀI HẾT TOÀN BỘ CHIỀU NGANG VIDEO làm đen cả đáy màn hình
                    pad_h = max(20, int(round(vid_w * 0.04)))
                    strip_x = max(0, ocr_x - pad_h)
                    strip_w = min(vid_w - strip_x, ocr_w + pad_h * 2)
                else:
                    # Fallback thanh thoát gọn gàng ở chân trang
                    strip_h = int(round(vid_h * (0.048 if vid_h > vid_w else 0.040)))
                    strip_y = max(0, target_cy - strip_h // 2)
                    strip_w = int(round(vid_w * 0.75))
                    strip_x = (vid_w - strip_w) // 2

                # Đảm bảo số chẵn cho chuẩn yuv420p
                strip_x = strip_x - (strip_x % 2)
                strip_y = strip_y - (strip_y % 2)
                strip_w = strip_w + (strip_w % 2)
                strip_h = strip_h + (strip_h % 2)
                if strip_x + strip_w > vid_w:
                    strip_w = vid_w - strip_x
                if strip_y + strip_h > vid_h:
                    strip_h = vid_h - strip_y

                # Căn giữa phụ đề tiếng Việt chuẩn xác tại tâm dải làm mờ
                target_cy = strip_y + strip_h // 2

                # boxblur=12:2: Làm mờ mịn nhẹ nhàng, chỉ nằm gọn ở vùng có chữ, 2 bên màn hình giữ nguyên độ nét
                filter_chains.append(
                    f"[{current_v}]split[v_base_strip][v_crop_strip];"
                    f"[v_crop_strip]crop={strip_w}:{strip_h}:{strip_x}:{strip_y},boxblur=12:2[v_blur_strip];"
                    f"[v_base_strip][v_blur_strip]overlay={strip_x}:{strip_y}[v_masked]"
                )
                current_v = "v_masked"
                print(f"[ExportVideo] Applied Blur Mask Strip (Thanh thoát): x={strip_x}px, y={strip_y}px, w={strip_w}px, h={strip_h}px")

            # Đồng bộ cấu hình Watermark từ request sang cfg nếu có
            if getattr(request, "enable_watermark", False):
                cfg.enable_watermark = True
                cfg.watermark_text = request.watermark_text
                cfg.watermark_position = request.watermark_position
                cfg.watermark_font_size = request.watermark_font_size
                cfg.watermark_opacity = request.watermark_opacity
                cfg.watermark_color = request.watermark_color

            # 3.4. Sinh kịch bản ASS (phụ đề tiếng Việt in đậm, viền đen sắc nét đè trực tiếp lên dải làm mờ)
            temp_ass_path = os.path.join(
                self.temp_dir,
                f"export_sub_{int(time.time() * 1000)}_{os.getpid()}.ass",
            )
            ass_content, ass_rendered_cnt = generate_ass_script(
                request.segments,
                vid_w=vid_w,
                vid_h=vid_h,
                cfg=cfg,
                target_cy=target_cy,
                enable_mask=enable_blur,
                duration=max(t_video, t_audio),
                user_rect=user_rect,
                mask_mode=mask_mode,
            )

            if ass_rendered_cnt > 0:
                with open(temp_ass_path, "w", encoding="utf-8") as af:
                    af.write(ass_content)

                escaped_ass = os.path.abspath(temp_ass_path).replace("\\", "/").replace(":", r"\:")
                filter_chains.append(f"[{current_v}]subtitles='{escaped_ass}'[outv]")
                current_v = "outv"

            # 3.5. DÁN LOGO THƯƠNG HIỆU LÊN LỚP TRÊN CÙNG (TOPMOST)
            # Đảm bảo Logo luôn nằm trên cùng, sắc nét 100%, không bao giờ bị dải mờ hay phụ đề đè lên
            if has_logo:
                logo_pct = max(5, min(50, int(getattr(request, "brand_logo_size_percent", None) or getattr(cfg, "brand_logo_size_percent", 15) or 15)))
                # Sử dụng kích thước cạnh ngắn hơn min(vid_w, vid_h) để logo trên video ngang (16:9) không bị phình to gấp đôi và tụt xuống dưới
                ref_dim = min(vid_w, vid_h)
                target_logo_w = max(40, int(round(ref_dim * (logo_pct / 100.0))))
                logo_alpha = max(0.1, min(1.0, float(getattr(request, "brand_logo_opacity", None) or getattr(cfg, "brand_logo_opacity", 1.0) or 1.0)))

                filter_chains.append(
                    f"[2:v]format=rgba,colorchannelmixer=aa={logo_alpha:.2f},scale={target_logo_w}:-1[brand_logo]"
                )

                margin_x = max(8, int(round(vid_w * 0.010)))
                margin_y = max(8, int(round(vid_h * 0.010)))
                if logo_pos == "top_left":
                    pos_xy = f"{margin_x}:{margin_y}"
                elif logo_pos == "top_right":
                    pos_xy = f"main_w-overlay_w-{margin_x}:{margin_y}"
                elif logo_pos == "bottom_left":
                    pos_xy = f"{margin_x}:main_h-overlay_h-{margin_y}"
                elif logo_pos == "bottom_right":
                    pos_xy = f"main_w-overlay_w-{margin_x}:main_h-overlay_h-{margin_y}"
                elif logo_pos == "center":
                    pos_xy = "(main_w-overlay_w)/2:(main_h-overlay_h)/2"
                elif logo_pos == "top_center":
                    pos_xy = f"(main_w-overlay_w)/2:{margin_y}"
                else:
                    pos_xy = f"{margin_x}:{margin_y}"

                filter_chains.append(
                    f"[{current_v}][brand_logo]overlay={pos_xy}:repeatlast=1[v_logo_final]"
                )
                current_v = "v_logo_final"

            # =====================================================================
            # 4. EXECUTE FFMPEG EXPORT COMMAND
            # =====================================================================
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-i", request.original_video_path,
                "-i", request.final_audio_path,
            ]
            if has_logo:
                cmd.extend(["-i", logo_path])

            if filter_chains:
                filter_script_path = os.path.join(
                    self.temp_dir,
                    f"export_filter_{int(time.time() * 1000)}_{os.getpid()}.txt",
                )
                with open(filter_script_path, "w", encoding="utf-8") as ff:
                    ff.write(";\n".join(filter_chains))
                cmd.extend(["-filter_complex_script", filter_script_path, "-map", f"[{current_v}]"])
            else:
                cmd.extend(["-map", "0:v:0"])

            cmd.extend([
                "-map", "1:a:0",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-threads", "0",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-ac", "2",
            ])

            if t_audio > t_video and request.overflow_policy == "shortest":
                cmd.append("-shortest")

            cmd.append(request.output_video_path)

            kwargs: dict[str, Any] = {"capture_output": True}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            proc = subprocess.run(cmd, **kwargs)
            if proc.returncode != 0 or not os.path.isfile(request.output_video_path):
                err_text = proc.stderr.decode("utf-8", errors="ignore") if proc.stderr else "Unknown FFmpeg error"
                return VideoExportResult(
                    video_duration=t_video,
                    audio_duration=t_audio,
                    status="failed",
                    error=f"FFmpeg video export failed:\n{err_text}",
                )

            # =====================================================================
            # 5. MEASURE ACTUAL OUTPUT FILE DURATION
            # =====================================================================
            actual_final_duration = measure_media_duration(request.output_video_path, self.ffprobe_bin)

            return VideoExportResult(
                output_video_path=request.output_video_path,
                video_duration=t_video,
                audio_duration=t_audio,
                final_video_duration=actual_final_duration,
                rendered_subtitles_count=rendered_cnt,
                skipped_subtitles_count=skipped_cnt,
                applied_overflow_policy=request.overflow_policy,
                status="success",
                warning=warning_msg,
                error="",
            )

        except Exception as exc:
            return VideoExportResult(
                video_duration=t_video,
                audio_duration=t_audio,
                status="failed",
                error=f"Unexpected error during video export: {exc}",
            )

        finally:
            # =====================================================================
            # 6. ALWAYS CLEANUP EPHEMERAL ARTIFACTS
            # =====================================================================
            if temp_srt_path and os.path.isfile(temp_srt_path):
                try:
                    os.remove(temp_srt_path)
                except Exception:
                    pass
            if temp_ass_path and os.path.isfile(temp_ass_path):
                try:
                    os.remove(temp_ass_path)
                except Exception:
                    pass
            if filter_script_path and os.path.isfile(filter_script_path):
                try:
                    os.remove(filter_script_path)
                except Exception:
                    pass

