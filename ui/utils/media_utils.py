import os
import time

from PySide6.QtCore import QTimer, QUrl

from .media_backend import create_media_backend, get_mpv_startup_diagnostic


def setup_media_player(gui):
    gui.media_player = create_media_backend(gui.video_view)
    if hasattr(gui, "log"):
        gui.log(f"[Preview] media backend: {gui.media_player.backend_name}")
    if getattr(gui.media_player, "backend_name", "") == "qt":
        diagnostic = get_mpv_startup_diagnostic()
        if diagnostic:
            stage = str(diagnostic.get("stage") or "MPV startup")
            summary = str(diagnostic.get("summary") or "Advanced Video Preview is unavailable.")
            technical = str(diagnostic.get("details") or diagnostic.get("error") or "")
            if hasattr(gui, "log"):
                gui.log(f"[Preview] Sử dụng chế độ xem trước tương thích Qt ({stage}): {technical or summary}")

    gui.play_btn.clicked.connect(gui.toggle_play)
    gui.stop_btn.clicked.connect(gui.stop_video)

    gui.media_player.positionChanged.connect(gui.position_changed)
    gui.media_player.durationChanged.connect(gui.duration_changed)

    # Re-apply the managed visual effects on play/pause/stop. Effects remain
    # visible on the paused frame; only their editing handles are stateful.
    if hasattr(gui.media_player, "stateChanged"):
        gui.media_player.stateChanged.connect(gui._on_preview_state_changed)


def refresh_video_dimensions(gui, path: str, get_video_dimensions):
    try:
        if path and os.path.exists(path):
            width, height = get_video_dimensions(path)
            gui.video_view.set_video_dimensions(width, height)
    except Exception:
        pass


def toggle_play(gui):
    try:
        if hasattr(gui, "ensure_media_backend_ready"):
            gui.ensure_media_backend_ready()
        if hasattr(gui, "audio_preview_player"):
            gui.audio_preview_player.stop()

        video_path = ""
        if hasattr(gui, "video_path_edit"):
            video_path = gui.video_path_edit.text().strip()

        # If the backend lost its loaded source after UI/state changes, restore it lazily.
        if video_path and os.path.exists(video_path):
            source_path = str(getattr(gui.media_player, "_source_path", "") or "")
            if not source_path:
                gui.media_player.setSource(QUrl.fromLocalFile(video_path))

        has_active_video_filters = bool(hasattr(gui, "has_active_video_filters") and gui.has_active_video_filters())
        filter_workflow_active = bool(hasattr(gui, "is_filter_workflow_active") and gui.is_filter_workflow_active())
        realtime_color_filters = bool(
            hasattr(gui, "_is_realtime_color_filter_state")
            and gui._is_realtime_color_filter_state()
        )

        if gui.media_player.is_playing():
            gui.media_player.pause()
            if hasattr(gui, "refresh_play_button_icon"):
                gui.refresh_play_button_icon()
            gui.timeline.set_playing(False)
            # Keep Blur and Mask applied to the paused frame. The backend's
            # stateChanged handler reapplies the current graph; clearing here
            # caused a visible gap until another layer was selected.
            # A selected Blur/Mask remains in lightweight edit mode while
            # paused. Refresh through the shared timed-layer path so that
            # only that selected effect stays suppressed; other effects keep
            # rendering normally.
            if hasattr(gui, "refresh_timed_layer_preview"):
                gui.refresh_timed_layer_preview()
            if (
                has_active_video_filters
                and filter_workflow_active
                and not realtime_color_filters
                and hasattr(gui, "schedule_live_video_filter_preview")
            ):
                gui.schedule_live_video_filter_preview()
            else:
                gui.schedule_seek_frame_preview()
        else:
            current_source = str(getattr(gui.media_player, "_source_path", "") or "")
            preview_source = str(getattr(gui, "last_preview_video_path", "") or "")
            if has_active_video_filters and filter_workflow_active and not realtime_color_filters:
                if filter_workflow_active and bool(getattr(gui, "_video_filter_preview_dirty", False)):
                    gui._play_video_filter_preview_when_ready = False
                    if hasattr(gui, "video_filter_render_status_label") and gui.video_filter_render_status_label is not None:
                        gui.video_filter_render_status_label.setText("Filter changes are pending. Click Apply Filter before playing.")
                        gui.video_filter_render_status_label.setVisible(True)
                    if hasattr(gui, "video_filter_render_progress") and gui.video_filter_render_progress is not None:
                        gui.video_filter_render_progress.setVisible(False)
                    if hasattr(gui, "refresh_ui_state"):
                        gui.refresh_ui_state()
                    return
                if not (current_source and preview_source and os.path.exists(preview_source) and os.path.abspath(current_source) == os.path.abspath(preview_source)):
                    gui.seek_frame_preview_timer.stop()
                    gui._play_video_filter_preview_when_ready = True
                    if hasattr(gui, "hide_filter_thumbnail_preview"):
                        gui.hide_filter_thumbnail_preview()
                    gui.preview_video()
                    return
            gui.seek_frame_preview_timer.stop()
            if hasattr(gui, "hide_filter_thumbnail_preview"):
                gui.hide_filter_thumbnail_preview()
            if realtime_color_filters and hasattr(gui, "_apply_realtime_color_filter_preview"):
                gui._apply_realtime_color_filter_preview()
            # Pressing Play is the commit boundary for paused Blur/Mask
            # edits. Restore their latest geometry before MPV resumes.
            if hasattr(gui, "prepare_preview_for_review_mode"):
                gui.prepare_preview_for_review_mode()
            elif hasattr(gui, "commit_deferred_effect_editing"):
                gui.commit_deferred_effect_editing(refresh=False)
            if hasattr(gui, "apply_preview_blur_region"):
                gui.apply_preview_blur_region(force=True)
            if (
                hasattr(gui, "video_view")
                and hasattr(gui.video_view, "set_blur_edit_enabled")
                and hasattr(gui, "_blur_effect_enabled")
                and gui._blur_effect_enabled()
            ):
                gui.video_view.set_blur_edit_enabled(False)
            # The track inspector is always expanded - no auto-collapse.
            gui.media_player.play()
            gui.timeline.set_playing(True)
            if hasattr(gui, "refresh_play_button_icon"):
                gui.refresh_play_button_icon()
            # Apply the M1 mask filter on play so the colour shows
            # while the video is playing. Use force=True to bypass
            # the is_playing() check (the play() call above already
            # set the state to PlayingState).
            if hasattr(gui, "_apply_mask_to_preview"):
                try:
                    gui._apply_mask_to_preview(force=True)
                except Exception:
                    pass
    except Exception as exc:
        if hasattr(gui, "log"):
            gui.log(f"[Preview] toggle play failed: {exc}")
        if hasattr(gui, "show_error"):
            gui.show_error("Preview Playback Failed", "Could not start or pause video preview.", str(exc))


def stop_video(gui):
    if hasattr(gui, "ensure_media_backend_ready"):
        gui.ensure_media_backend_ready()
    if hasattr(gui, "audio_preview_player"):
        gui.audio_preview_player.stop()
    gui.media_player.stop()
    if hasattr(gui, "refresh_play_button_icon"):
        gui.refresh_play_button_icon()
    if hasattr(gui, "media_player"):
        gui.media_player.clear_blur_region()
    if hasattr(gui, "_sync_blur_controls"):
        gui._sync_blur_controls()
    gui.timeline.set_playing(False)
    gui.schedule_seek_frame_preview()


def position_changed(gui, position):
    gui.timeline.set_position(position)
    update_duration_label(gui, position, gui.media_player.duration())
    try:
        gui.refresh_timed_layer_preview(position)
    except Exception as exc:
        if hasattr(gui, "log"):
            gui.log(f"[Preview] timed layer refresh error: {exc}")
    try:
        gui.update_playback_subtitle_highlight(position)
    except Exception as exc:
        if hasattr(gui, "log"):
            gui.log(f"[Preview] position highlight error: {exc}")
    # Apply audio fade-in/fade-out during playback
    try:
        _apply_audio_fade(gui, position)
    except Exception:
        pass
    # Disable the play button when the playhead reaches the end of
    # the video (within 250 ms of the duration) so the user can tell
    # at a glance that playback has finished. The button is re-enabled
    # on seek (`set_position`) or when a new source is loaded.
    try:
        if hasattr(gui, "play_btn") and not getattr(
            gui, "_disable_play_at_end", False
        ):
            duration_ms = 0
            try:
                duration_ms = int(gui.media_player.duration() or 0)
            except Exception:
                duration_ms = 0
            at_end = duration_ms > 0 and position >= duration_ms - 250
            try:
                is_playing = bool(gui.media_player.is_playing())
            except Exception:
                is_playing = False
            gui.play_btn.setEnabled(not at_end)
            # When playback ends naturally, update the icon/tooltip to
            # "Play" so the next click re-starts from the end.
            if at_end and not is_playing and hasattr(gui, "refresh_play_button_icon"):
                gui.refresh_play_button_icon()
    except Exception:
        pass


def _apply_audio_fade(gui, position_ms: int):
    """Apply fade-in/fade-out to audio track volumes during playback.

    The fade values are stored in each track's metadata. During the
    fade-in window the volume ramps from 0 to the set volume; during
    the fade-out window it ramps from the set volume down to 0.
    """
    if not getattr(gui, "media_player", None):
        return
    try:
        duration_ms = int(gui.media_player.duration())
    except Exception:
        duration_ms = 0
    if duration_ms <= 0:
        return
    pos_s = position_ms / 1000.0
    # When a Music Layer exists, the dubbed sidecar is a composed render of
    # TTS + music.  Its per-track levels have already been baked into the WAV
    # by the shared mixer.  Applying the TS1 slider/fade to the whole sidecar
    # would therefore mute the music when TS1 is set to 0% (and attenuate it
    # at every other TS1 value).
    has_composed_dubbed_sidecar = False
    try:
        has_composed_dubbed_sidecar = bool(gui._music_audio_tracks())
    except Exception:
        has_composed_dubbed_sidecar = False

    for track_name in ("A1 Audio", "TS1"):
        track, _ = _find_audio_track(gui, track_name)
        if track is None:
            continue
        meta = getattr(track, "metadata", None) or {}
        try:
            fade_in = float(meta.get("_fade_in", 0.0))
            fade_out = float(meta.get("_fade_out", 0.0))
        except (TypeError, ValueError):
            fade_in = fade_out = 0.0
        base_vol = _compute_base_volume(gui, track, meta)
        # Compute fade multiplier
        mult = 1.0
        if fade_in > 0 and pos_s < fade_in:
            mult = min(mult, pos_s / fade_in if fade_in > 0 else 1.0)
        if fade_out > 0:
            remaining = (duration_ms - position_ms) / 1000.0
            if remaining < fade_out:
                mult = min(mult, max(0.0, remaining / fade_out) if fade_out > 0 else 1.0)
        effective = base_vol * mult
        if track_name == "A1 Audio":
            if hasattr(gui.media_player, "set_original_volume"):
                gui.media_player.set_original_volume(effective)
        elif track_name == "TS1":
            if hasattr(gui.media_player, "set_dubbed_volume"):
                if has_composed_dubbed_sidecar:
                    gui.media_player.set_dubbed_volume(100.0)
                else:
                    gui.media_player.set_dubbed_volume(effective)


def _find_audio_track(gui, name: str):
    if not getattr(gui, "timeline", None) or not gui.timeline._timeline:
        return None, None
    for t in gui.timeline._timeline.tracks:
        if t.name == name:
            return t, name
    return None, None


def _compute_base_volume(gui, track, meta) -> float:
    track_name = getattr(track, "name", "") or ""
    default_vol = 50.0 if track_name.startswith("A1") else 100.0
    try:
        vol = float(meta.get("_volume", default_vol))
    except (TypeError, ValueError):
        vol = default_vol
    try:
        gain_db = float(meta.get("_gain_db", 0.0))
    except (TypeError, ValueError):
        gain_db = 0.0
    effective = vol * (10 ** (gain_db / 20.0))
    return max(0.0, min(200.0, effective))


def duration_changed(gui, duration):
    gui.timeline.set_duration(duration)
    update_duration_label(gui, gui.media_player.position(), duration)


def set_position(gui, position):
    if hasattr(gui, "ensure_media_backend_ready"):
        gui.ensure_media_backend_ready()
    gui.media_player.setPosition(position)
    gui.timeline.set_position(position)
    try:
        gui.update_playback_subtitle_highlight(position)
    except Exception as exc:
        if hasattr(gui, "log"):
            gui.log(f"[Preview] seek highlight error: {exc}")
    # Seeking away from the end re-enables the play button.
    try:
        if hasattr(gui, "play_btn"):
            duration_ms = 0
            try:
                duration_ms = int(gui.media_player.duration() or 0)
            except Exception:
                duration_ms = 0
            gui.play_btn.setEnabled(duration_ms <= 0 or position < duration_ms - 250)
    except Exception:
        pass
    if (
        hasattr(gui, "has_active_video_filters")
        and gui.has_active_video_filters()
        and not (hasattr(gui, "_is_realtime_color_filter_state") and gui._is_realtime_color_filter_state())
        and hasattr(gui, "is_filter_workflow_active")
        and gui.is_filter_workflow_active()
        and not gui.media_player.is_playing()
    ):
        if hasattr(gui, "schedule_live_video_filter_preview"):
            gui.schedule_live_video_filter_preview()
    else:
        gui.schedule_seek_frame_preview()


def update_duration_label(gui, current, total):
    def fmt(ms):
        seconds = max(0, ms // 1000)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    gui.time_label.setText(f"{fmt(current)} / {fmt(total)}")


def probe_video_duration_and_thumb(file_path: str, thumb_dir: str) -> tuple[float, str]:
    dur = 0.0
    thumb_path = ""
    try:
        import hashlib
        h = hashlib.md5(os.path.normpath(file_path).encode()).hexdigest()
        os.makedirs(thumb_dir, exist_ok=True)
        thumb_path = os.path.join(thumb_dir, f"{h}.jpg")

        import cv2
        cap = cv2.VideoCapture(file_path)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            dur = float(count / fps) if fps > 0 and count > 0 else 0.0
            if not os.path.exists(thumb_path):
                ret, frame = cap.read()
                if ret and frame is not None:
                    h_orig, w_orig = frame.shape[:2]
                    target_w = int(w_orig * (120 / max(1, h_orig)))
                    resized = cv2.resize(frame, (target_w, 120))
                    cv2.imwrite(thumb_path, resized)
            cap.release()
    except Exception:
        pass
    return dur, thumb_path


def append_video_to_timeline(gui, video_path: str):
    """Ghép nối clip video vào Track V1 trên timeline (chuẩn CapCut ghép nối)."""
    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        return
    filename = os.path.basename(video_path)

    from runtime_paths import workspace_root
    thumb_dir = os.path.join(workspace_root(), "temp", "launcher_thumbs")
    dur_s, _ = probe_video_duration_and_thumb(video_path, thumb_dir)
    if dur_s <= 0:
        dur_s = 10.0

    timeline = getattr(gui, "timeline", None)
    if not timeline or not getattr(timeline, "_timeline", None):
        return

    from app.layers.video import VideoLayer
    from app.layers.audio import AudioLayer
    from app.layers.transform import Transform
    from app.layers.base import LayerType
    from app.layers.timeline import Track

    v1 = a1 = None
    for track in timeline._timeline.tracks:
        if str(getattr(track, "name", "")).startswith("V1") or getattr(track, "type", None) == LayerType.VIDEO:
            v1 = track
        elif str(getattr(track, "name", "")).startswith("A1") or getattr(track, "type", None) == LayerType.AUDIO:
            a1 = track

    if v1 is None:
        v1 = Track(name="V1 Video", type=LayerType.VIDEO, height=36)
        timeline._timeline.tracks.insert(0, v1)
    if a1 is None:
        a1 = Track(name="A1 Audio", type=LayerType.AUDIO, height=30)
        v1_idx = timeline._timeline.tracks.index(v1)
        timeline._timeline.tracks.insert(v1_idx + 1, a1)

    # Nếu Track V1 đang có placeholder rỗng (source == "") thì xóa bỏ
    if v1.layers and len(v1.layers) == 1 and not getattr(v1.layers[0], "source", ""):
        v1.layers.clear()
    if a1.layers and len(a1.layers) == 1 and not getattr(a1.layers[0], "source", ""):
        a1.layers.clear()

    # Vị trí bắt đầu của clip mới: ngay sau điểm kết thúc của clip cuối cùng trên V1
    last_end = max((float(l.end) for l in v1.layers), default=0.0)

    new_v = VideoLayer(
        name=filename,
        source=video_path,
        start=last_end,
        end=last_end + dur_s,
        source_start=0.0,
        transform=Transform(x=0, y=0, scale_x=1.0, scale_y=1.0),
    )
    new_a = AudioLayer(
        name=f"A1 {filename}",
        source=video_path,
        start=last_end,
        end=last_end + dur_s,
        volume=1.0,
    )
    v1.layers.append(new_v)
    a1.layers.append(new_a)

    total_dur = max(float(l.end) for l in v1.layers)
    timeline.set_duration_ms(int(total_dur * 1000))
    timeline._duration = total_dur

    # Cập nhật trạng thái 'is_on_timeline' trong kho Media
    for item in getattr(gui, "project_media_pool", []):
        if os.path.normpath(item.get("path", "")) == os.path.normpath(video_path):
            item["is_on_timeline"] = True

    if hasattr(gui, "_refresh_media_pool_ui"):
        gui._refresh_media_pool_ui()

    timeline.viewport().update()


def import_media_paths(gui, file_paths):
    """Xử lý danh sách đường dẫn media được nhập (từ dialog hoặc kéo thả)."""
    if not file_paths:
        return

    if not hasattr(gui, "project_media_pool"):
        gui.project_media_pool = []

    from runtime_paths import workspace_root
    thumb_dir = os.path.join(workspace_root(), "temp", "launcher_thumbs")
    os.makedirs(thumb_dir, exist_ok=True)

    ctrl = getattr(gui, "_batch_controller", None)
    has_active_video = bool(getattr(gui, "_current_video_path", "") and os.path.exists(getattr(gui, "_current_video_path", "")))

    newly_added = []
    for path in file_paths:
        path = os.path.abspath(path)
        existing = next((item for item in gui.project_media_pool if os.path.normpath(item.get("path", "")) == os.path.normpath(path)), None)
        if not existing:
            try:
                dur_s, thumb_p = probe_video_duration_and_thumb(path, thumb_dir)
            except Exception:
                dur_s, thumb_p = 0.0, ""
            total_s = int(dur_s)
            m = total_s // 60
            s = total_s % 60
            item = {
                "id": str(int(time.time() * 1000)),
                "path": path,
                "name": os.path.basename(path),
                "duration": dur_s,
                "duration_str": f"{m:02d}:{s:02d}",
                "thumb_path": thumb_p,
                "is_on_timeline": False,
                "type": "video",
            }
            gui.project_media_pool.append(item)
            newly_added.append(item)

            # Đồng bộ trực tiếp vào Batch Controller nếu đã khởi tạo
            if ctrl and not any(os.path.normpath(ws.video_path) == os.path.normpath(path) for ws in ctrl.workspaces):
                ctrl.add_workspace(path, thumb_dir)

    # Nếu chưa có video nào mở: nạp video đầu tiên vào player & timeline
    if not has_active_video and newly_added:
        first_video = newly_added[0]["path"]
        browse_video(gui, file_path=first_video)

    # Lưu trữ bền vững Media Pool vào disk
    save_media_pool_state(gui)

    # Refresh UI Media Pool
    if hasattr(gui, "_refresh_media_pool_ui") and callable(gui._refresh_media_pool_ui):
        gui._refresh_media_pool_ui()


def save_media_pool_state(gui):
    """Lưu trữ bền vững danh sách video trong Media Pool và cấu hình riêng vào disk."""
    import json
    pool = getattr(gui, "project_media_pool", [])
    if not pool:
        return
    voice_configs = getattr(gui, "_video_voice_configs", {})
    ocr_rects = getattr(gui, "_video_ocr_rects", {})

    from runtime_paths import workspace_root
    save_data = {
        "media_pool": pool,
        "video_voice_configs": voice_configs,
        "video_ocr_rects": ocr_rects,
        "updated_at": time.time(),
    }

    # 1. Lưu vào session cache toàn cục của workspace
    cache_path = os.path.join(workspace_root(), "temp", "session_media_pool.json")
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 2. Lưu liên kết cho từng video trong pool (để khi mở bất kỳ video nào trong Launcher cũng tìm lại được cả nhóm)
    sessions_file = os.path.join(workspace_root(), "projects", "media_pool_sessions.json")
    try:
        os.makedirs(os.path.dirname(sessions_file), exist_ok=True)
        all_sessions = {}
        if os.path.exists(sessions_file):
            try:
                with open(sessions_file, "r", encoding="utf-8") as f:
                    all_sessions = json.load(f)
            except Exception:
                all_sessions = {}
        pool_paths = [os.path.normpath(it.get("path", "")) for it in pool if it.get("path")]
        for p in pool_paths:
            all_sessions[p] = save_data
        with open(sessions_file, "w", encoding="utf-8") as f:
            json.dump(all_sessions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 3. Lưu vào project state hiện tại nếu có
    ps = getattr(gui, "current_project_state", None)
    if ps and hasattr(ps, "settings"):
        ps.settings["project_media_pool"] = pool
        ps.settings["video_voice_configs"] = voice_configs
        ps.settings["video_ocr_rects"] = ocr_rects
        project_service = getattr(gui, "project_service", None)
        if project_service and hasattr(project_service, "save_project"):
            try:
                project_service.save_project(ps)
            except Exception:
                pass


def restore_media_pool_state(gui, target_video_path="") -> bool:
    """Khôi phục danh sách media pool từ session cache hoặc project state."""
    import json
    norm_target = os.path.normpath(target_video_path) if target_video_path else ""

    save_data = None
    from runtime_paths import workspace_root

    # 1. Thử tìm trong media_pool_sessions.json theo video được mở
    if norm_target:
        sessions_file = os.path.join(workspace_root(), "projects", "media_pool_sessions.json")
        if os.path.exists(sessions_file):
            try:
                with open(sessions_file, "r", encoding="utf-8") as f:
                    all_sessions = json.load(f)
                    save_data = all_sessions.get(norm_target)
            except Exception:
                pass

    # 2. Thử tìm trong project state hiện tại
    if not save_data:
        ps = getattr(gui, "current_project_state", None)
        if ps and hasattr(ps, "settings") and ps.settings.get("project_media_pool"):
            save_data = {
                "media_pool": ps.settings.get("project_media_pool", []),
                "video_voice_configs": ps.settings.get("video_voice_configs", {}),
                "video_ocr_rects": ps.settings.get("video_ocr_rects", {}),
            }

    # 3. Thử tìm trong session_media_pool.json
    if not save_data:
        cache_path = os.path.join(workspace_root(), "temp", "session_media_pool.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    save_data = json.load(f)
            except Exception:
                pass

    if not save_data or not isinstance(save_data, dict):
        return False

    saved_pool = save_data.get("media_pool") or []
    valid_pool = []
    for it in saved_pool:
        p = it.get("path", "")
        if p and os.path.isfile(p) and not str(p).lower().endswith("_final_vi.mp4"):
            valid_pool.append(dict(it))

    if not valid_pool:
        return False

    # Nếu có target_video_path, kiểm tra xem nó có nằm trong pool không
    if norm_target and not any(os.path.normpath(it.get("path", "")) == norm_target for it in valid_pool):
        return False

    gui.project_media_pool = valid_pool
    if not hasattr(gui, "_video_voice_configs"):
        gui._video_voice_configs = {}
    gui._video_voice_configs.update(save_data.get("video_voice_configs") or {})

    if not hasattr(gui, "_video_ocr_rects"):
        gui._video_ocr_rects = {}
    gui._video_ocr_rects.update(save_data.get("video_ocr_rects") or {})

    return True


def import_multi_media_files(gui):
    """Mở hộp thoại chọn một hoặc nhiều file video/media, đưa vào Media Pool và Batch."""
    from PySide6.QtWidgets import QFileDialog
    file_paths, _ = QFileDialog.getOpenFileNames(
        gui,
        "Chọn các video hoặc tệp media cần nhập",
        "",
        "Media Files (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.mp3 *.wav *.m4a);;All Files (*.*)"
    )
    if file_paths:
        import_media_paths(gui, file_paths)


def browse_video(gui, file_path=None):
    if not file_path:
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(gui, "Open Video", "", "Video Files (*.mp4 *.mkv *.avi *.mov)")
    if not file_path:
        return

    # 1. Lưu lại khung OCR và Media Pool của video cũ trước khi switch
    old_video = getattr(gui, "_current_video_path", "")
    overlay = getattr(gui, "ocr_region_overlay", None)
    if old_video and overlay and hasattr(overlay, "get_norm_rect"):
        try:
            old_rect = overlay.get_norm_rect()
            if not hasattr(gui, "_video_ocr_rects"):
                gui._video_ocr_rects = {}
            norm_old = os.path.normpath(old_video)
            gui._video_ocr_rects[norm_old] = old_rect
            ctrl = getattr(gui, "_batch_controller", None)
            if ctrl:
                for ws in ctrl.workspaces:
                    if os.path.normpath(ws.video_path) == norm_old:
                        ws.ocr_rect = old_rect
                        ws.blur_rect = old_rect
                        break
            ps = getattr(gui, "current_project_state", None)
            if ps and hasattr(ps, "settings"):
                ps.settings["ocr_subtitle_rect"] = f"{old_rect[0]:.4f},{old_rect[1]:.4f},{old_rect[2]:.4f},{old_rect[3]:.4f}"
                project_service = getattr(gui, "project_service", None)
                if project_service and hasattr(project_service, "save_project"):
                    try:
                        project_service.save_project(ps)
                    except Exception:
                        pass
        except Exception:
            pass

    # Lưu lại trạng thái media pool hiện tại
    save_media_pool_state(gui)

    if hasattr(gui, "ensure_media_backend_ready"):
        gui.ensure_media_backend_ready()

    # Tìm sẵn thời lượng đã biết trong Media Pool để tránh ffprobe trên UI thread
    dur_s = 0.0
    if hasattr(gui, "project_media_pool"):
        norm_f = os.path.normpath(file_path)
        for item in gui.project_media_pool:
            if os.path.normpath(item.get("path", "")) == norm_f:
                dur_s = float(item.get("duration", 0.0) or 0.0)
                break

    if hasattr(gui, "video_path_edit"):
        gui.video_path_edit.blockSignals(True)
        gui.video_path_edit.setText(file_path)
        gui.video_path_edit.blockSignals(False)
    gui._current_video_path = os.path.abspath(file_path)
    if hasattr(gui, "settings"):
        from views.launcher import LauncherWindow
        LauncherWindow.add_recent(gui.settings, file_path)
    gui.media_player.setSource(QUrl.fromLocalFile(file_path))
    gui._allow_post_pipeline_preview_assets = False
    gui.refresh_video_dimensions(file_path)

    if hasattr(gui, "timeline") and hasattr(gui.timeline, "clear"):
        gui.timeline.clear()
    gui.timeline.set_segments([])
    gui.timeline.set_playing(False)
    gui.current_segments = []
    gui.current_translated_segments = []
    gui.current_segment_models = []
    gui.current_translated_segment_models = []
    if hasattr(gui, "timeline") and hasattr(gui.timeline, "set_video_source"):
        gui.timeline.set_video_source(file_path, dur_s)

    gui.current_project_state = gui.ensure_current_project()
    gui.load_project_context(gui.current_project_state)

    # Chỉ khôi phục danh sách Media Pool nếu đang thiếu
    if len(getattr(gui, "project_media_pool", [])) <= 1:
        restore_media_pool_state(gui, file_path)

    # 2. Khôi phục khung OCR riêng của video mới vừa chọn
    if overlay and hasattr(overlay, "restore_for_video"):
        overlay.restore_for_video(file_path)
    if hasattr(gui, "_sync_ocr_overlay"):
        gui._sync_ocr_overlay()
    if hasattr(gui, "_refresh_media_pool_ui") and callable(gui._refresh_media_pool_ui):
        gui._refresh_media_pool_ui()

    try:
        gui.media_player.pause()
    except Exception:
        pass
    if hasattr(gui, "auto_frame_preview_timer"):
        gui.auto_frame_preview_timer.stop()
    if hasattr(gui, "seek_frame_preview_timer"):
        gui.seek_frame_preview_timer.stop()
    QTimer.singleShot(120, lambda: gui.media_player.setPosition(0))
    QTimer.singleShot(160, lambda: gui._sync_ocr_overlay() if hasattr(gui, "_sync_ocr_overlay") else None)
    QTimer.singleShot(220, gui.video_view.reposition_subtitle)
    gui.refresh_ui_state()
    gui.sync_live_subtitle_preview()


def update_frame_preview_thumbnail(gui, image_path: str, qpixmap_cls, qt):
    pixmap = qpixmap_cls(image_path)
    if pixmap.isNull():
        gui.frame_preview_image_label.setText("Could not load frame preview")
        gui.frame_preview_image_label.setPixmap(qpixmap_cls())
        return
    target_width = 0
    target_height = 0
    if hasattr(gui, "video_view") and gui.video_view is not None:
        target_width = int(gui.video_view.width() or 0)
        target_height = int(gui.video_view.height() or 0)
    if target_width <= 0 or target_height <= 0:
        target_width = int(gui.frame_preview_image_label.width() or 0)
        target_height = int(gui.frame_preview_image_label.height() or 0)
    if target_width <= 0:
        target_width = 960
    if target_height <= 0:
        target_height = 540
    scaled = pixmap.scaled(target_width, target_height, qt.KeepAspectRatio, qt.SmoothTransformation)
    gui.frame_preview_image_label.setPixmap(scaled)
    gui.frame_preview_image_label.setText("")
    gui.frame_preview_status_label.setText(f"Exact frame preview synced at {time.strftime('%H:%M:%S')}.")
