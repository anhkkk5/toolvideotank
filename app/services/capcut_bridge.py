from __future__ import annotations

import glob
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from runtime_paths import bin_path, subprocess_text_kwargs


def _ffmpeg_path() -> str:
    return bin_path("ffmpeg", "ffmpeg.exe")


def find_default_capcut_drafts_dir(custom_path: str = "") -> str:
    """Tự động tìm kiếm thư mục CapCut Drafts trên máy tính."""
    if custom_path and os.path.isdir(custom_path):
        return os.path.abspath(custom_path)

    candidates = [
        r"D:\CAPCUT\CapCut Drafts",
        r"C:\CAPCUT\CapCut Drafts",
        r"E:\CAPCUT\CapCut Drafts",
    ]
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidates.append(
            os.path.join(local_app_data, "CapCut", "User Data", "Projects", "com.lveditor.draft")
        )

    for path in candidates:
        if os.path.isdir(path):
            return os.path.abspath(path)

    for drive in ["D", "C", "E"]:
        drive_path = f"{drive}:\\CAPCUT\\CapCut Drafts"
        if os.path.isdir(drive_path):
            return drive_path

    return candidates[0]


def list_capcut_drafts(drafts_dir: str = "") -> list[dict[str, Any]]:
    """Liệt kê tất cả các dự án CapCut Drafts, sắp xếp mới nhất lên đầu."""
    base_dir = find_default_capcut_drafts_dir(drafts_dir)
    if not os.path.isdir(base_dir):
        return []

    drafts = []
    try:
        entries = os.scandir(base_dir)
    except OSError:
        return []

    for entry in entries:
        if not entry.is_dir():
            continue

        draft_folder = entry.path
        draft_content_path = os.path.join(draft_folder, "draft_content.json")
        text_reading_dir = os.path.join(draft_folder, "textReading")

        audio_files = []
        if os.path.isdir(text_reading_dir):
            for ext in ("*.wav", "*.mp3", "*.m4a", "*.aac"):
                audio_files.extend(glob.glob(os.path.join(text_reading_dir, ext)))

        has_content = os.path.isfile(draft_content_path)
        if not has_content and not audio_files:
            continue

        mtime = entry.stat().st_mtime
        drafts.append({
            "name": entry.name,
            "path": os.path.abspath(draft_folder),
            "mtime": mtime,
            "audio_count": len(audio_files),
            "audio_files": [os.path.abspath(f) for f in audio_files],
            "has_draft_content": has_content,
        })

    drafts.sort(key=lambda item: item["mtime"], reverse=True)
    return drafts


def parse_capcut_draft_audios(draft_folder: str) -> list[dict[str, Any]]:
    """Phân tích các đoạn âm thanh giọng đọc trong draft của CapCut."""
    draft_content_path = os.path.join(draft_folder, "draft_content.json")
    text_reading_dir = os.path.join(draft_folder, "textReading")

    audios: list[dict[str, Any]] = []

    # 1. Đọc từ draft_content.json nếu có
    if os.path.isfile(draft_content_path):
        try:
            with open(draft_content_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)

            materials = data.get("materials", {})
            mat_audios = {a.get("id"): a for a in materials.get("audios", []) if isinstance(a, dict)}
            mat_texts = {t.get("id"): t for t in materials.get("texts", []) if isinstance(t, dict)}

            # Tìm các track âm thanh
            for track in data.get("tracks", []):
                if track.get("type") != "audio":
                    continue
                for seg in track.get("segments", []):
                    mat_id = seg.get("material_id")
                    audio_mat = mat_audios.get(mat_id)
                    if not audio_mat or audio_mat.get("type") != "text_to_audio":
                        continue

                    # Lấy thông tin giọng đọc và text trước
                    speaker_name = str(audio_mat.get("tone_effect_name") or audio_mat.get("tone_type", "") or "").strip()
                    speaker_code = str(audio_mat.get("tone_speaker", "") or "").strip()

                    text_id = audio_mat.get("text_id")
                    text_mat = mat_texts.get(text_id, {})
                    text_content = text_mat.get("content", "") or text_mat.get("base_content", "")
                    clean_text = re.sub(r"<[^>]+>", "", text_content).strip()

                    target_timerange = seg.get("target_timerange", {})
                    start_us = target_timerange.get("start", 0)
                    duration_us = target_timerange.get("duration", audio_mat.get("duration", 0))

                    # Lấy file audio thực tế
                    raw_path = str(audio_mat.get("path", "")).strip()
                    file_name = os.path.basename(raw_path)
                    candidate_path = os.path.join(text_reading_dir, file_name)

                    if not os.path.isfile(candidate_path):
                        # Nếu không khớp tên chính xác, thử tìm file tương tự
                        text_reading_files = [
                            f for f in glob.glob(os.path.join(text_reading_dir, "*.*"))
                            if f.lower().endswith((".wav", ".mp3", ".m4a", ".aac"))
                        ]
                        # Thử tìm theo từ khóa speaker_name
                        matched_file = ""
                        speaker_lower = speaker_name.lower().replace(" ", "")
                        for f in text_reading_files:
                            fname = os.path.basename(f).lower()
                            if "anhdung" in fname and ("anh" in speaker_lower or "dung" in speaker_lower):
                                matched_file = f
                                break
                            if ("cogai" in fname or "hoatngon" in fname or "dethuong" in fname) and ("nữ" in speaker_lower or "gái" in speaker_lower or "hoạt" in speaker_lower):
                                matched_file = f
                                break
                        if matched_file:
                            candidate_path = matched_file
                        elif len(text_reading_files) > len(audios):
                            candidate_path = text_reading_files[len(audios)]

                    if os.path.isfile(candidate_path):
                        audios.append({
                            "file_path": candidate_path,
                            "text": clean_text,
                            "speaker_name": speaker_name,
                            "speaker_code": speaker_code,
                            "start_s": float(start_us) / 1_000_000.0,
                            "duration_s": float(duration_us) / 1_000_000.0,
                            "end_s": float(start_us + duration_us) / 1_000_000.0,
                        })
        except Exception as exc:
            print(f"[CapCut Bridge] Warning parsing draft_content.json: {exc}")

    # 2. Quét trực tiếp thư mục textReading nếu danh sách trên rỗng
    if not audios and os.path.isdir(text_reading_dir):
        raw_files = []
        for ext in ("*.wav", "*.mp3", "*.m4a", "*.aac"):
            raw_files.extend(glob.glob(os.path.join(text_reading_dir, ext)))
        raw_files.sort(key=lambda f: os.path.getmtime(f))

        for idx, file_path in enumerate(raw_files):
            fname = os.path.basename(file_path).lower()
            name = "CapCut Voice"
            if "anhdung" in fname:
                name = "Anh Dũng"
            elif "cogai" in fname or "hoatngon" in fname:
                name = "Cô Gái Hoạt Ngôn"

            audios.append({
                "file_path": file_path,
                "text": f"Đoạn {idx + 1}",
                "speaker_name": name,
                "speaker_code": "capcut",
                "start_s": 0.0,
                "duration_s": 0.0,
                "end_s": 0.0,
            })

    valid_audios = [a for a in audios if os.path.isfile(a["file_path"])]
    valid_audios.sort(key=lambda item: item["start_s"])
    return valid_audios


def convert_to_wav_16k_mono(input_audio_path: str, output_wav_path: str) -> str:
    """Chuyển đổi file âm thanh bất kỳ sang WAV 16kHz Mono bằng FFmpeg."""
    ffmpeg = _ffmpeg_path()
    if not os.path.isfile(ffmpeg):
        raise FileNotFoundError(f"FFmpeg not found at {ffmpeg}")

    os.makedirs(os.path.dirname(output_wav_path), exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        input_audio_path,
        "-ar",
        "16000",
        "-ac",
        "1",
        output_wav_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, **subprocess_text_kwargs())
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg conversion failed:\n{proc.stderr or proc.stdout}")
    return output_wav_path


def sync_capcut_voice_to_project(
    *,
    project_state: Any,
    project_service: Any,
    draft_folder: str,
    original_volume_percent: int = 100,
    dub_volume_percent: int = 100,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Đồng bộ các file giọng đọc từ dự án CapCut vào dự án CapCap hiện tại."""
    if not project_state:
        raise ValueError("Chưa mở dự án nào trong CapCap.")

    if not os.path.isdir(draft_folder):
        raise FileNotFoundError(f"Thư mục CapCut draft không tồn tại: {draft_folder}")

    if on_progress:
        on_progress(f"Đang phân tích dự án CapCut: {os.path.basename(draft_folder)}...")

    capcut_audios = parse_capcut_draft_audios(draft_folder)
    if not capcut_audios:
        raise RuntimeError(
            f"Không tìm thấy file âm thanh giọng đọc nào trong dự án CapCut: {os.path.basename(draft_folder)}.\n"
            "Vui lòng đảm bảo bạn đã bấm 'Tạo lời nói' trong CapCut trước khi đồng bộ."
        )

    if on_progress:
        on_progress(f"Tìm thấy {len(capcut_audios)} file âm thanh giọng đọc. Đang chuyển đổi định dạng...")

    tts_segments_dir = os.path.join(project_state.project_root, "audio", "tts_segments")
    os.makedirs(tts_segments_dir, exist_ok=True)

    converted_wavs = []
    for idx, item in enumerate(capcut_audios):
        src_path = item["file_path"]
        base_name = f"capcut_cue_{idx:04d}.wav"
        dest_wav = os.path.join(tts_segments_dir, base_name)

        if on_progress:
            on_progress(f"Chuyển đổi đoạn {idx + 1}/{len(capcut_audios)} ({item.get('speaker_name', 'CapCut')})...")

        convert_to_wav_16k_mono(src_path, dest_wav)
        converted_wavs.append(dest_wav)

    def _to_seg_dict(m):
        if hasattr(m, "to_subtitle_dict"):
            return m.to_subtitle_dict()
        elif hasattr(m, "to_original_subtitle_dict"):
            return m.to_original_subtitle_dict()
        elif isinstance(m, dict):
            return dict(m)
        return {
            "start": getattr(m, "start", 0.0),
            "end": getattr(m, "end", 0.0),
            "text": getattr(m, "subtitle_text", getattr(m, "text", "")),
        }

    target_segments = []
    if project_state.artifacts.get("translation_final"):
        models = project_service.load_segment_artifact(project_state, "translation_final")
        target_segments = [_to_seg_dict(m) for m in models]
    elif project_state.artifacts.get("transcript_segments"):
        models = project_service.load_segment_artifact(project_state, "transcript_segments")
        target_segments = [_to_seg_dict(m) for m in models]

    if not target_segments or len(target_segments) != len(capcut_audios):
        segments_for_build = []
        for idx, item in enumerate(capcut_audios):
            start_s = item.get("start_s", 0.0)
            dur_s = item.get("duration_s", 2.0)
            end_s = item.get("end_s", start_s + dur_s)

            if idx < len(target_segments):
                seg_copy = dict(target_segments[idx])
                segments_for_build.append(seg_copy)
            else:
                segments_for_build.append({
                    "start": start_s,
                    "end": end_s,
                    "text": item.get("text", f"Segment {idx + 1}"),
                })
    else:
        segments_for_build = [dict(s) for s in target_segments]

    if on_progress:
        on_progress("Đang ghép các đoạn âm thanh thành track lồng tiếng hoàn chỉnh...")

    from audio_mixer import build_voice_track_from_srt_segments, mix_voice_with_background

    voice_track_wav = os.path.join(project_state.project_root, "audio", "voice_vi.wav")
    build_voice_track_from_srt_segments(
        segments=segments_for_build,
        tts_wav_paths=converted_wavs,
        output_wav_path=voice_track_wav,
        gain_db=0.0,
    )

    mixed_track_wav = ""
    background_path = (
        project_state.artifacts.get("music")
        or project_state.artifacts.get("audio_music")
        or os.path.join(project_state.project_root, "audio", "separated", "music.wav")
        or os.path.join(project_state.project_root, "audio", "separated", "music.mp3")
    )
    if os.path.isfile(str(background_path)):
        if on_progress:
            on_progress("Đang hòa âm (mix) giọng đọc CapCut với nhạc nền...")
        mixed_track_wav = os.path.join(project_state.project_root, "audio", "mixed_vi.wav")

        import math
        bg_gain = 20.0 * math.log10(original_volume_percent / 100.0) if original_volume_percent > 0 else -60.0
        dub_gain = 20.0 * math.log10(dub_volume_percent / 100.0) if dub_volume_percent > 0 else -60.0

        mix_voice_with_background(
            background_wav_path=background_path,
            voice_wav_path=voice_track_wav,
            output_wav_path=mixed_track_wav,
            background_gain_db=bg_gain,
            voice_gain_db=dub_gain,
            ducking_mode="timeline",
            ducking_segments=segments_for_build,
            ducking_amount_db=-10.0,
        )

    project_service.update_artifact(project_state, "voice_vi", voice_track_wav, save=False)
    project_service.update_step(project_state, "generate_tts", "done", save=False)

    if mixed_track_wav and os.path.isfile(mixed_track_wav):
        project_service.update_artifact(project_state, "mixed_vi", mixed_track_wav, save=False)
        project_service.update_step(project_state, "mix_audio", "done", save=False)
    elif background_path and os.path.isfile(str(background_path)):
        project_service.update_step(project_state, "mix_audio", "skipped", save=False)

    project_service.save_project(project_state)

    if on_progress:
        on_progress("Đồng bộ giọng CapCut thành công!")

    return {
        "success": True,
        "voice_track": voice_track_wav,
        "mixed_track": mixed_track_wav,
        "count": len(converted_wavs),
        "speakers": list({item.get("speaker_name", "CapCut") for item in capcut_audios}),
    }


def detect_speaker_gender_from_audio(audio_path: str, segments: list[dict[str, Any]]) -> str:
    """Tự động phân biệt giọng Nam / Nữ từ file âm thanh bằng phân tích phổ (Spectral Centroid)."""
    if not audio_path or not os.path.isfile(audio_path) or not segments:
        return "female"
    try:
        import wave
        import numpy as np

        with wave.open(audio_path, "rb") as wf:
            sr = wf.getframerate()
            n_ch = wf.getnchannels()
            total_frames = wf.getnframes()
            centroids = []
            for s in segments[:12]:
                start_s = float(s.get("start", 0.0) or 0.0)
                end_s = float(s.get("end", start_s + 2.0) or (start_s + 2.0))
                dur_s = min(end_s - start_s, 2.5)
                if dur_s <= 0.3:
                    continue
                start_f = int(start_s * sr)
                dur_f = int(dur_s * sr)
                if start_f + dur_f > total_frames or start_f < 0:
                    continue
                wf.setpos(start_f)
                raw = wf.readframes(dur_f)
                if not raw:
                    continue
                data = np.frombuffer(raw, dtype=np.int16)
                if n_ch == 2:
                    data = data[::2]
                fft = np.abs(np.fft.rfft(data))
                freqs = np.fft.rfftfreq(len(data), 1.0 / sr)
                mask = (freqs >= 80) & (freqs <= 3000)
                sum_mag = np.sum(fft[mask])
                if sum_mag > 0:
                    sc = np.sum(freqs[mask] * fft[mask]) / sum_mag
                    centroids.append(sc)

            if centroids:
                avg_sc = float(np.mean(centroids))
                return "female" if avg_sc > 920.0 else "male"
    except Exception as exc:
        print(f"[CapCut Bridge] Gender detection fallback: {exc}")
    return "female"


def _get_host_capcut_platform(drafts_base: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    """Lấy thông tin platform thực tế từ máy để CapCut nhận diện chính chủ."""
    candidates_dirs = [
        drafts_base,
        r"D:\CAPCUT\CapCut Drafts",
        r"C:\CAPCUT\CapCut Drafts",
        r"E:\CAPCUT\CapCut Drafts",
    ]
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        candidates_dirs.append(
            os.path.join(local_app_data, "CapCut", "User Data", "Projects", "com.lveditor.draft")
        )

    for base in candidates_dirs:
        if not base or not os.path.isdir(base):
            continue
        for f in glob.glob(os.path.join(base, "*", "draft_content.json")):
            try:
                with open(f, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                plat = data.get("platform")
                if plat and isinstance(plat, dict) and plat.get("app_id"):
                    last_plat = data.get("last_modified_platform") or plat
                    return plat, last_plat
            except Exception:
                continue

    fallback = {
        "app_id": 359289,
        "app_source": "cc",
        "app_version": "6.7.0",
        "device_id": "356ab86796c37b7d918fe76f5292f0d5",
        "hard_disk_id": "",
        "mac_address": "4bf895eb5b89678109c2b0349f81533b",
        "os": "windows",
        "os_version": "10.0.26200",
    }
    return fallback, fallback


def export_subtitles_to_capcut_draft(
    *,
    project_state: Any,
    project_service: Any,
    segments: list[dict[str, Any]],
    draft_name: str = "",
) -> str:
    """Tạo một dự án CapCut Draft mới chứa toàn bộ phụ đề đã dịch, tự động phân luồng Nam / Nữ."""
    import time
    import uuid
    import re

    if not segments:
        raise ValueError("Danh sách phụ đề trống, không thể xuất sang CapCut.")

    drafts_base = find_default_capcut_drafts_dir()
    if not os.path.isdir(drafts_base):
        os.makedirs(drafts_base, exist_ok=True)

    if not draft_name:
        video_name = os.path.splitext(os.path.basename(project_state.input_video or "video"))[0]
        timestamp = time.strftime("%m%d_%H%M")
        draft_name = f"CapCap_{video_name[:15]}_{timestamp}"

    draft_folder = os.path.join(drafts_base, draft_name)
    os.makedirs(draft_folder, exist_ok=True)
    os.makedirs(os.path.join(draft_folder, "textReading"), exist_ok=True)
    os.makedirs(os.path.join(draft_folder, "Resources"), exist_ok=True)

    # Lấy thông tin audio gốc và voice assignments để phân biệt Nam / Nữ
    audio_path = (
        project_state.artifacts.get("extracted_audio")
        or project_state.artifacts.get("audio_extracted")
        or ""
    )
    assignments = (
        project_state.settings.get("speaker_voice_assignments", {})
        if project_state and hasattr(project_state, "settings")
        else {}
    )

    # Dự đoán giới tính từng speaker
    speaker_gender_cache: dict[str, str] = {}
    unique_speakers = {str(seg.get("speaker", "") or "").strip() for seg in segments}
    for spk in unique_speakers:
        if not spk:
            continue
        entry = assignments.get(spk, {})
        cfg_gender = str(entry.get("voice_gender_filter", "") or "").lower()
        cfg_voice = str(entry.get("voice", "") or "").lower()
        if cfg_gender in ("female", "male"):
            speaker_gender_cache[spk] = cfg_gender
        elif "cogai" in cfg_voice:
            speaker_gender_cache[spk] = "female"
        elif "anhdung" in cfg_voice:
            speaker_gender_cache[spk] = "male"
        elif audio_path and os.path.isfile(audio_path):
            spk_segs = [s for s in segments if str(s.get("speaker", "") or "").strip() == spk]
            speaker_gender_cache[spk] = detect_speaker_gender_from_audio(audio_path, spk_segs)
        else:
            speaker_gender_cache[spk] = "female"

    materials_texts = []
    female_segments = []
    male_segments = []

    for idx, seg in enumerate(segments):
        start_s = float(seg.get("start", 0.0) or 0.0)
        end_s = float(seg.get("end", start_s + 2.0) or (start_s + 2.0))
        dur_s = max(0.2, end_s - start_s)
        text_content = str(seg.get("text") or seg.get("final_text") or "").strip()
        if not text_content:
            continue

        text_id = str(uuid.uuid4()).upper()
        seg_id = str(uuid.uuid4()).upper()

        text_json_content = json.dumps({
            "text": text_content,
            "styles": [{
                "fill": {"content": {"render_type": "solid", "solid": {"color": [1, 1, 1]}}},
                "font": {"path": "", "id": ""},
                "size": 15,
                "range": [0, len(text_content)],
            }],
        }, ensure_ascii=False)

        materials_texts.append({
            "id": text_id,
            "type": "subtitle",
            "content": text_json_content,
            "text_color": "#FFFFFF",
            "text_size": 30,
            "alignment": 1,
            "add_type": 2,
            "check_flag": 15,
            "font_path": "",
            "font_title": "none",
            "initial_scale": 1.0,
            "layer_weight": 1,
            "sub_type": 0,
            "words": {"start_time": [], "end_time": [], "text": []},
        })

        track_seg_item = {
            "id": seg_id,
            "material_id": text_id,
            "render_index": 14000 + idx,
            "source": "segmentsourcenormal",
            "source_timerange": None,
            "speed": 1.0,
            "state": 0,
            "target_timerange": {
                "start": int(start_s * 1_000_000),
                "duration": int(dur_s * 1_000_000),
            },
            "template_id": "",
            "template_scene": "default",
            "track_attribute": 0,
            "track_render_index": 1,
            "visible": True,
            "volume": 1.0,
        }

        spk = str(seg.get("speaker", "") or "").strip()
        gender = speaker_gender_cache.get(spk, "female")
        if gender == "male":
            male_segments.append(track_seg_item)
        else:
            female_segments.append(track_seg_item)

    tracks = []
    if female_segments and male_segments:
        tracks.append({
            "attribute": 0,
            "flag": 1,
            "id": str(uuid.uuid4()).upper(),
            "is_default_name": False,
            "name": "Phụ đề Nữ (Cô Gái Hoạt Ngôn)",
            "segments": female_segments,
            "type": "text",
        })
        tracks.append({
            "attribute": 0,
            "flag": 1,
            "id": str(uuid.uuid4()).upper(),
            "is_default_name": False,
            "name": "Phụ đề Nam (Anh Dũng)",
            "segments": male_segments,
            "type": "text",
        })
    elif male_segments:
        tracks.append({
            "attribute": 0,
            "flag": 1,
            "id": str(uuid.uuid4()).upper(),
            "is_default_name": False,
            "name": "Phụ đề Nam (Anh Dũng)",
            "segments": male_segments,
            "type": "text",
        })
    else:
        tracks.append({
            "attribute": 0,
            "flag": 1,
            "id": str(uuid.uuid4()).upper(),
            "is_default_name": False,
            "name": "Phụ đề Nữ (Cô Gái Hoạt Ngôn)",
            "segments": female_segments,
            "type": "text",
        })

    plat, last_plat = _get_host_capcut_platform(drafts_base)

    draft_content = {
        "canvas_config": {"height": 1080, "ratio": "original", "width": 1920},
        "color_space": 0,
        "config": {
            "adjust_max_index": 1,
            "attachment_info": [],
            "combination_max_index": 1,
            "export_range": None,
            "extract_audio_last_index": 1,
            "lyrics_recognition_id": "",
            "lyrics_sync": True,
            "lyrics_taskinfo": [],
            "maintrack_adsorb": True,
            "material_save_mode": 0,
            "original_sound_last_index": 1,
            "record_audio_last_index": 1,
            "sample_aspect_ratio": "1:1",
            "sticker_max_index": 1,
            "subtitle_keywords_config": None,
            "subtitle_recognition_id": "",
            "subtitle_sync": True,
            "subtitle_taskinfo": [],
            "system_font_list": [],
            "video_mute": False,
            "zoom_info_params": None,
        },
        "cover": None,
        "create_time": int(time.time()),
        "duration": int(float(segments[-1].get("end", 60.0) or 60.0) * 1_000_000),
        "extra_info": None,
        "fps": 30.0,
        "free_render_index_mode_on": False,
        "group_container": None,
        "id": str(uuid.uuid4()).upper(),
        "is_drop_frame_timecode": False,
        "keyframe_graph_list": [],
        "keyframes": {"adjusts": [], "audios": [], "effects": [], "filters": [], "handwrites": [], "stickers": [], "texts": [], "videos": []},
        "last_modified_platform": last_plat,
        "lyrics_effects": [],
        "materials": {
            "audios": [],
            "canvases": [],
            "drafts": [],
            "speeds": [],
            "texts": materials_texts,
            "videos": [],
        },
        "mutable_config": None,
        "name": draft_name,
        "new_version": "140.0.0",
        "path": "",
        "platform": plat,
        "relationships": [],
        "render_index_track_mode_on": True,
        "retouch_cover": None,
        "source": "default",
        "static_cover_image_path": "",
        "time_marks": None,
        "tracks": tracks,
        "uneven_animation_template_info": {"composition": "", "content": "", "order": "", "sub_template_info_list": []},
        "update_time": int(time.time()),
        "version": 360000,
    }

    draft_content_path = os.path.join(draft_folder, "draft_content.json")
    with open(draft_content_path, "w", encoding="utf-8") as handle:
        json.dump(draft_content, handle, ensure_ascii=False, indent=2)

    agency_path = os.path.join(draft_folder, "draft_agency_config.json")
    with open(agency_path, "w", encoding="utf-8") as handle:
        json.dump({
            "is_auto_agency_enabled": False,
            "is_auto_agency_popup": False,
            "is_single_agency_mode": False,
            "marterials": None,
            "use_converter": False,
            "video_resolution": 720,
        }, handle, ensure_ascii=False, indent=2)

    biz_path = os.path.join(draft_folder, "draft_biz_config.json")
    if not os.path.exists(biz_path):
        with open(biz_path, "w", encoding="utf-8") as handle:
            handle.write("")

    settings_path = os.path.join(draft_folder, "draft_settings")
    if not os.path.exists(settings_path):
        now_sec = int(time.time())
        with open(settings_path, "w", encoding="utf-8") as handle:
            handle.write(f"[General]\r\ndraft_create_time={now_sec}\r\ndraft_last_edit_time={now_sec}\r\nreal_edit_seconds=0\r\nreal_edit_keys=1\r\n")

    # Tạo draft_meta_info.json trong thư mục draft
    now_us = int(time.time() * 1_000_000)
    dur_us = int(float(segments[-1].get("end", 60.0) or 60.0) * 1_000_000)
    draft_id = str(uuid.uuid4()).upper()

    draft_meta = {
        "cloud_draft_cover": True,
        "cloud_draft_sync": True,
        "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False,
        "draft_cloud_package_type": "",
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "",
        "draft_deeplink_url": "",
        "draft_enterprise_info": {"draft_enterprise_extra": "", "draft_enterprise_id": "", "draft_enterprise_name": "", "enterprise_material": []},
        "draft_fold_path": draft_folder.replace("\\", "/"),
        "draft_id": draft_id,
        "draft_is_ae_produce": False,
        "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False,
        "draft_is_cloud_temp_draft": False,
        "draft_is_from_deeplink": "false",
        "draft_is_invisible": False,
        "draft_materials": [{"type": 0, "value": []}, {"type": 1, "value": []}, {"type": 2, "value": []}, {"type": 3, "value": []}, {"type": 6, "value": []}],
        "draft_materials_copied_info": [],
        "draft_name": draft_name,
        "draft_need_rename_folder": False,
        "draft_new_version": "",
        "draft_removable_storage_device": os.path.splitdrive(drafts_base)[0] or "D:",
        "draft_root_path": drafts_base,
        "draft_segment_extra_info": [],
        "draft_timeline_materials_size_": 3070,
        "draft_type": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_draft_removed": 0,
        "tm_duration": dur_us,
    }
    meta_path = os.path.join(draft_folder, "draft_meta_info.json")
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(draft_meta, handle, ensure_ascii=False, indent=2)

    # Đăng ký vào root_meta_info.json của CapCut PC để dự án hiện ngay ở vị trí đầu tiên
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        root_meta_path = os.path.join(
            local_app_data, "CapCut", "User Data", "Projects", "com.lveditor.draft", "root_meta_info.json"
        )
        if os.path.isfile(root_meta_path):
            try:
                with open(root_meta_path, "r", encoding="utf-8") as handle:
                    root_meta = json.load(handle)
                all_drafts = root_meta.get("all_draft_store", [])
                norm_folder = draft_folder.replace("\\", "/").lower()
                all_drafts = [d for d in all_drafts if d.get("draft_fold_path", "").replace("\\", "/").lower() != norm_folder]
                store_entry = {
                    "cloud_draft_cover": True,
                    "cloud_draft_sync": True,
                    "draft_cloud_last_action_download": False,
                    "draft_cloud_purchase_info": "",
                    "draft_cloud_template_id": "",
                    "draft_cloud_tutorial_info": "",
                    "draft_cloud_videocut_purchase_info": "",
                    "draft_cover": "",
                    "draft_fold_path": draft_folder.replace("\\", "/"),
                    "draft_id": draft_id,
                    "draft_is_ai_shorts": False,
                    "draft_is_cloud_temp_draft": False,
                    "draft_is_invisible": False,
                    "draft_json_file": draft_content_path.replace("\\", "/"),
                    "draft_name": draft_name,
                    "draft_new_version": "",
                    "draft_root_path": drafts_base.replace("\\", "/"),
                    "draft_timeline_materials_size": 3070,
                    "draft_type": "",
                    "streaming_edit_draft_ready": True,
                    "tm_draft_cloud_completed": "",
                    "tm_draft_cloud_entry_id": -1,
                    "tm_draft_cloud_modified": 0,
                    "tm_draft_cloud_parent_entry_id": -1,
                    "tm_draft_cloud_space_id": -1,
                    "tm_draft_cloud_user_id": -1,
                    "tm_draft_create": now_us,
                    "tm_draft_modified": now_us,
                    "tm_draft_removed": 0,
                    "tm_duration": dur_us,
                }
                all_drafts.insert(0, store_entry)
                root_meta["all_draft_store"] = all_drafts
                root_meta["draft_ids"] = len(all_drafts)
                with open(root_meta_path, "w", encoding="utf-8") as handle:
                    json.dump(root_meta, handle, ensure_ascii=False)
            except Exception as exc:
                print(f"[CapCut Bridge] Không thể cập nhật root_meta_info.json: {exc}")

    # Tự động kích hoạt CapCut PC
    launch_capcut_app(draft_folder)

    return draft_folder


def find_capcut_executable() -> str:
    """Tìm file thực thi CapCut.exe hoặc shortcut CapCut trên máy tính."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        # 1. Ưu tiên executable theo phiên bản (VD: Apps/6.7.0.2661/CapCut.exe)
        # Đây là file thực thi chính bung cửa sổ giao diện trực tiếp trên màn hình
        pattern = os.path.join(local_app_data, "CapCut", "Apps", "*", "CapCut.exe")
        matches = glob.glob(pattern)
        if matches:
            matches.sort(reverse=True)
            return matches[0]

        launcher = os.path.join(local_app_data, "CapCut", "Apps", "CapCut.exe")
        if os.path.isfile(launcher):
            return launcher

    app_data = os.environ.get("APPDATA", "")
    if app_data:
        shortcut = os.path.join(
            app_data, "Microsoft", "Windows", "Start Menu", "Programs", "CapCut", "CapCut.lnk"
        )
        if os.path.isfile(shortcut):
            return shortcut

    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        for desk in ("Desktop", "OneDrive/Desktop"):
            desk_lnk = os.path.join(user_profile, desk, "CapCut.lnk")
            if os.path.isfile(desk_lnk):
                return desk_lnk

    program_files = os.environ.get("PROGRAMFILES", "")
    if program_files:
        p = os.path.join(program_files, "CapCut", "CapCut.exe")
        if os.path.isfile(p):
            return p

    return ""


def launch_capcut_app(draft_folder: str = "") -> bool:
    """Tự động khởi chạy ứng dụng CapCut PC hiển thị giao diện ngay lập tức."""
    target = find_capcut_executable()
    if not target:
        try:
            print("[CapCut Bridge] Khong tim thay CapCut tren he thong.")
        except Exception:
            pass
        return False

    app_dir = os.path.dirname(target)
    try:
        if target.lower().endswith(".exe"):
            subprocess.Popen([target], cwd=app_dir)
            try:
                print(f"[CapCut Bridge] Opened CapCut directly: {target}")
            except Exception:
                pass
            return True
        else:
            os.startfile(target)
            try:
                print(f"[CapCut Bridge] Opened CapCut via startfile: {target}")
            except Exception:
                pass
            return True
    except Exception as exc:
        try:
            os.startfile(target)
            return True
        except Exception as e2:
            try:
                print(f"[CapCut Bridge] Failed to launch CapCut: {e2}")
            except Exception:
                pass
            return False


