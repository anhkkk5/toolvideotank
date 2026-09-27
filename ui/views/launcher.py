import hashlib
import math
import os
import json
import time
import shutil
import hashlib
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from runtime_paths import asset_path, subprocess_hidden_kwargs, workspace_root



def _get_appdata_dir() -> str:
    app_data = os.environ.get("APPDATA")
    if app_data:
        target = os.path.join(app_data, "TankVideo")
    else:
        target = os.path.join(os.path.expanduser("~"), ".tankvideo")
    try:
        os.makedirs(target, exist_ok=True)
    except Exception:
        pass
    return target


def _recent_projects_paths() -> list[str]:
    return [
        os.path.join(_get_appdata_dir(), "recent_projects.json"),
        os.path.join(workspace_root(), "recent_projects.json"),
    ]


def _load_recent_projects(settings=None):
    for path in _recent_projects_paths():
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        return data
        except Exception:
            pass
    return []


def _save_recent_projects(settings, projects):
    for path in _recent_projects_paths():
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(projects, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def _project_pipeline_status(video_path: str) -> tuple[str, str]:
    """Read the persisted project stage without creating or modifying it."""
    name = os.path.splitext(os.path.basename(video_path))[0] or "project"
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower() or "project"
    digest = hashlib.sha1(os.path.abspath(video_path).encode("utf-8")).hexdigest()[:8]
    state_path = os.path.join(workspace_root(), "projects", f"{slug}_{digest}", "project.json")
    try:
        with open(os.path.normpath(state_path), "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError, TypeError):
        return "Ready", "#8394aa"
    artifacts = dict(state.get("artifacts") or {})
    steps = dict(state.get("steps") or {})
    if artifacts.get("final_video"):
        return "Xuất hoàn tất", "#6ee7d6"
    if artifacts.get("voice_vi") or artifacts.get("mixed_vi"):
        return "TTS hoàn tất", "#6ee7d6"
    if str(steps.get("translate_raw", "")).lower() == "done" or artifacts.get("translation_final"):
        return "Dịch hoàn tất", "#78b8ff"
    if artifacts.get("transcript_segments"):
        return "Chép lời xong", "#f6c453"
    return "Sẵn sàng", "#8394aa"


def _extract_thumbnail(video_path: str, output_path: str) -> str:
    if not os.path.exists(video_path):
        return ""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    import subprocess
    try:
        subprocess.run(
            [_ffmpeg_path(), "-y", "-i", video_path, "-vframes", "1", "-q:v", "3",
             "-vf", "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
             output_path],
            capture_output=True, timeout=30, **subprocess_hidden_kwargs(),
        )
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
    except Exception:
        pass
    return ""


def _ffmpeg_path():
    from runtime_paths import bin_path
    return os.path.join(bin_path(), "ffmpeg", "ffmpeg.exe")


def _get_video_duration(video_path: str) -> float:
    try:
        import subprocess
        ffprobe = _ffmpeg_path().replace("ffmpeg.exe", "ffprobe.exe")
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=30, **subprocess_hidden_kwargs(),
        )
        if result.returncode == 0:
            return float(result.stdout.strip() or 0)
    except Exception:
        pass
    return 0.0


MSG_STYLE = """
    QMessageBox { background-color: #0f1724; }
    QLabel { color: #ffffff; }
    QPushButton { background-color: #22344d; color: #f8fbff; border: 1px solid #34506f;
        border-radius: 8px; padding: 6px 16px; font-weight: 600; }
    QPushButton:hover { background-color: #29405d; }
"""


class ProjectCard(QFrame):
    def __init__(self, video_path: str, thumbnail_cache_dir: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self._orig_pixmap = None
        self.setObjectName("projectCard")
        self.setMinimumSize(210, 205)
        self.setMaximumWidth(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Khung chứa hình thu nhỏ
        self.thumb_container = QWidget(self)
        self.thumb_container.setMinimumHeight(115)
        self.thumb_container.setStyleSheet("background-color: #060911; border-radius: 8px;")
        thumb_box = QVBoxLayout(self.thumb_container)
        thumb_box.setContentsMargins(0, 0, 0, 0)

        self.thumb_label = QLabel(self.thumb_container)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("border-radius: 8px; background: transparent;")
        thumb_box.addWidget(self.thumb_label)
        layout.addWidget(self.thumb_container)

        # Tính thời lượng video
        duration_s = _get_video_duration(video_path)
        dur_str = ""
        if duration_s > 0:
            m = int(duration_s // 60)
            s = int(duration_s % 60)
            dur_str = f"{m:02d}:{s:02d}"

        # Tiêu đề video và nút xóa
        title_row = QHBoxLayout()
        title_row.setSpacing(4)

        self.name_label = QLabel(os.path.basename(video_path))
        self.name_label.setWordWrap(True)
        self.name_label.setFixedHeight(40)
        self.name_label.setToolTip(video_path)
        self.name_label.setStyleSheet("color: #f8fafc; font-size: 12px; font-weight: 700; background: transparent;")
        title_row.addWidget(self.name_label, 1)

        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedSize(22, 22)
        self.btn_remove.setToolTip("Xóa khỏi danh sách dự án gần đây")
        self.btn_remove.setStyleSheet("""
            QPushButton {
                background: transparent; color: #64748b; font-size: 11px; font-weight: bold; border: none; border-radius: 4px;
            }
            QPushButton:hover { background: #334155; color: #f87171; }
        """)
        self.btn_remove.clicked.connect(self._on_remove_clicked)
        title_row.addWidget(self.btn_remove, 0)
        layout.addLayout(title_row)

        # Trạng thái tiến trình & Thời lượng
        meta_row = QHBoxLayout()
        stage_text, stage_color = _project_pipeline_status(video_path)
        self.stage_badge = QLabel(f"● {stage_text}")
        self.stage_badge.setStyleSheet(
            f"color: {stage_color}; font-size: 11px; font-weight: 700; background: transparent;"
        )
        meta_row.addWidget(self.stage_badge)
        meta_row.addStretch()

        if dur_str:
            dur_badge = QLabel(f"⏱️ {dur_str}")
            dur_badge.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; background: transparent;")
            meta_row.addWidget(dur_badge)

        layout.addLayout(meta_row)

        self._load_thumb(thumbnail_cache_dir)

    def _on_remove_clicked(self):
        projects = _load_recent_projects()
        norm_current = os.path.normpath(self.video_path)
        filtered = [p for p in projects if os.path.normpath(p.get("video_path", "")) != norm_current]
        _save_recent_projects(None, filtered)
        if self.window() and hasattr(self.window(), "_load_recent"):
            self.window()._load_recent()

    def _load_thumb(self, cache_dir):
        thumb_path = os.path.join(cache_dir, _thumbnail_name(self.video_path))
        if not os.path.exists(thumb_path):
            thumb_path = _extract_thumbnail(self.video_path, thumb_path)
        if os.path.exists(thumb_path):
            self._orig_pixmap = QPixmap(thumb_path)
            self._update_thumb()
        else:
            self.thumb_label.setText("🎬 Chưa có xem trước")
            self.thumb_label.setStyleSheet("color: #64748b; font-size: 11px;")

    def _update_thumb(self):
        if self._orig_pixmap is None or self._orig_pixmap.isNull():
            return
        w = max(160, self.thumb_container.width())
        self.thumb_label.setPixmap(self._orig_pixmap.scaled(w, 115, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_thumb()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self.isEnabled():
                event.ignore()
                return
            if getattr(LauncherWindow, "_cached_update_info", None) and LauncherWindow._cached_update_info.get("has_update"):
                from ui.dialogs.update_dialog import UpdateDialog
                dlg = UpdateDialog(self.window(), workspace_root=workspace_root(), mandatory=True, preloaded_info=LauncherWindow._cached_update_info)
                dlg.exec()
                return
            self.window().selected_video = self.video_path
            self.window().accept()


class HeroDropCard(QFrame):
    clicked = Signal()
    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("heroDropCard")
        self.setMinimumHeight(118)

        self.setStyleSheet("""
            QFrame#heroDropCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a1628, stop:0.5 #1e1b32, stop:1 #131c2d);
                border: 2px dashed #f59e0b;
                border-radius: 14px;
            }
            QFrame#heroDropCard:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #271f3d, stop:0.5 #2a2245, stop:1 #192740);
                border: 2px solid #ff7b1a;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(20)

        # Big icon
        icon_box = QLabel("🚀")
        icon_box.setFixedSize(54, 54)
        icon_box.setAlignment(Qt.AlignCenter)
        icon_box.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff7b1a, stop:1 #ea580c);
            border-radius: 27px;
            font-size: 26px;
        """)
        layout.addWidget(icon_box)

        # Text section
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        title_lbl = QLabel("BẤM VÀO ĐÂY HOẶC KÉO THẢ TỆP VIDEO ĐỂ TẠO DỰ ÁN MỚI")
        title_lbl.setStyleSheet("color: #f8fafc; font-size: 15px; font-weight: 800; letter-spacing: 0.5px;")
        text_layout.addWidget(title_lbl)

        desc_lbl = QLabel("Tự động quét phụ đề Trung ➔ Dịch chuẩn ngữ cảnh DeepSeek AI ➔ Lồng tiếng & Che chữ Trung")
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        text_layout.addWidget(desc_lbl)

        badges_row = QHBoxLayout()
        badges_row.setSpacing(8)
        tag1 = QLabel("🎬 MP4, MKV, MOV, TS, AVI")
        tag1.setStyleSheet("color: #38bdf8; background: #0f2744; border: 1px solid #1e40af; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 700;")
        tag2 = QLabel("👑 Hỗ trợ VieNeu AI Neural VIP")
        tag2.setStyleSheet("color: #34d399; background: #064e3b; border: 1px solid #059669; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 700;")
        tag3 = QLabel("⚡ Tự động hóa 100%")
        tag3.setStyleSheet("color: #fbbf24; background: #451a03; border: 1px solid #b45309; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 700;")
        badges_row.addWidget(tag1)
        badges_row.addWidget(tag2)
        badges_row.addWidget(tag3)
        badges_row.addStretch()
        text_layout.addLayout(badges_row)

        layout.addLayout(text_layout, 1)

        # Right CTA Button
        self.btn_select = QPushButton("+ Chọn Video")
        self.btn_select.setMinimumHeight(42)
        self.btn_select.setMinimumWidth(135)
        self.btn_select.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7b1a, stop:1 #e04800);
                color: #ffffff; font-weight: 800; font-size: 13px; border: 1px solid #ff9d42; border-radius: 8px; padding: 6px 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff8c33, stop:1 #f05400); border-color: #ffb366;
            }
        """)
        self.btn_select.clicked.connect(self.clicked.emit)
        layout.addWidget(self.btn_select)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                ext = os.path.splitext(url.toLocalFile())[1].lower()
                if ext in {".mp4", ".mkv", ".mov", ".avi", ".ts", ".webm", ".flv"}:
                    event.acceptProposedAction()
                    self.setStyleSheet("""
                        QFrame#heroDropCard {
                            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #331f08, stop:1 #241433);
                            border: 2px solid #ff7b1a; border-radius: 14px;
                        }
                    """)
                    return

    def dragLeaveEvent(self, event):
        self.setStyleSheet("""
            QFrame#heroDropCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1a1628, stop:0.5 #1e1b32, stop:1 #131c2d);
                border: 2px dashed #f59e0b; border-radius: 14px;
            }
            QFrame#heroDropCard:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #271f3d, stop:0.5 #2a2245, stop:1 #192740);
                border: 2px solid #ff7b1a;
            }
        """)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if os.path.isfile(path):
                    self.file_dropped.emit(path)
                    event.acceptProposedAction()
                    return


def _extract_waveform_audio(video_path: str, temp_root: str) -> str:
    video_hash = hashlib.md5(video_path.encode("utf-8")).hexdigest()[:12]
    audio_path = os.path.join(temp_root, f"waveform_{video_hash}.wav")
    if os.path.exists(audio_path):
        return audio_path
    if not os.path.exists(video_path):
        return ""
    os.makedirs(os.path.dirname(audio_path) or ".", exist_ok=True)
    import subprocess
    try:
        subprocess.run(
            [_ffmpeg_path(), "-y", "-loglevel", "error", "-i", video_path,
             "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path],
            check=True, timeout=60, **subprocess_hidden_kwargs(),
        )
        print(f"[Launcher] Waveform audio extracted: {audio_path}")
    except Exception as exc:
        print(f"[Launcher] Waveform extract failed: {exc}")
        return ""
    return audio_path if os.path.exists(audio_path) else ""


def _prepare_timeline_visual_cache(video_path: str, temp_root: str) -> None:
    """Build the editor's static V1/A1 cache before opening the editor."""
    try:
        import numpy as np
        import subprocess
        import wave

        source = os.path.abspath(video_path)
        stat = os.stat(source)
        digest = hashlib.md5(source.encode("utf-8")).hexdigest()[:12]
        cache_dir = os.path.join(temp_root, "timeline_visuals")
        thumb_dir = os.path.join(temp_root, "timeline_thumbnails")
        manifest_path = os.path.join(cache_dir, f"{digest}.json")
        os.makedirs(cache_dir, exist_ok=True)

        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            if (
                int(existing.get("visual_version", 0)) == 4
                and
                existing.get("source") == source
                and existing.get("size") == int(stat.st_size)
                and existing.get("mtime_ns") == int(stat.st_mtime_ns)
                and existing.get("waveform")
                and all(os.path.exists(path) for _time, path in existing.get("thumbnails", []))
            ):
                print("[Launcher] Timeline visuals loaded from cache")
                return
        except (OSError, ValueError, TypeError):
            pass

        duration_s = _get_video_duration(source)
        if duration_s <= 60.0:
            interval_s = max(2.0, duration_s / 12.0)
        elif duration_s <= 300.0:
            interval_s = max(5.0, duration_s / 30.0)
        else:
            interval_s = max(20.0, duration_s / 90.0)
        thumb_count = max(1, min(120, int(math.ceil(duration_s / interval_s))))
        timestamps = [0.0] if duration_s <= 1.0 else [
            min(duration_s - 0.05, index * interval_s) for index in range(thumb_count)
        ]
        os.makedirs(thumb_dir, exist_ok=True)

        def build_waveform():
            waveform = []
            audio_path = _extract_waveform_audio(source, temp_root)
            waveform_duration = duration_s
            if audio_path and os.path.exists(audio_path):
                with wave.open(audio_path, "rb") as audio_file:
                    frame_count = audio_file.getnframes()
                    sample_rate = max(1, audio_file.getframerate())
                    raw_samples = audio_file.readframes(frame_count)
                samples = np.frombuffer(raw_samples, dtype=np.int16).astype(np.float32)
                waveform_duration = max(waveform_duration, frame_count / sample_rate)
                peak = float(np.max(np.abs(samples))) if samples.size else 0.0
                if peak > 0:
                    samples /= peak
                    bucket_count = int(min(1200, max(240, round(waveform_duration * 12.0))))
                    chunk_size = max(256, int(np.ceil(samples.size / max(1, bucket_count))))
                    for start in range(0, samples.size, chunk_size):
                        chunk = samples[start:start + chunk_size]
                        peak_value = float(np.max(np.abs(chunk))) if chunk.size else 0.0
                        rms_value = float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0
                        waveform.append(min(1.0, max(0.03, max(peak_value, rms_value * 1.15) ** 0.85)))
            return waveform, waveform_duration

        def build_thumbnail(index_and_time):
            index, timestamp_s = index_and_time
            output_path = os.path.join(thumb_dir, f"launcher_{digest}_v4_{index:03d}.jpg")
            if not os.path.exists(output_path):
                subprocess.run(
                    [_ffmpeg_path(), "-y", "-loglevel", "error", "-ss", f"{timestamp_s:.3f}",
                     "-i", source, "-frames:v", "1", "-q:v", "4",
                     "-vf", "scale=180:-1:force_original_aspect_ratio=decrease", output_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=20,
                    **subprocess_hidden_kwargs(),
                )
            return [float(timestamp_s), output_path] if os.path.exists(output_path) and os.path.getsize(output_path) > 0 else None

        # Two independent FFmpeg workers seek the original video directly,
        # while waveform extraction runs alongside them. This stays bounded
        # (two thumbnail processes plus one audio process) and avoids splits.
        from concurrent.futures import ThreadPoolExecutor
        import threading
        print(f"[Launcher] Preparing {thumb_count} timeline thumbnails with 2 workers + waveform worker")
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="capcap-thumbs") as thumbnail_pool:
            # Keep waveform CPU/audio work independent from the two thumbnail
            # slots so all three tasks can progress concurrently.
            waveform_result = []
            waveform_error = []
            def run_waveform():
                try:
                    waveform_result.extend(build_waveform())
                except Exception as exc:
                    waveform_error.append(exc)
            waveform_thread = threading.Thread(target=run_waveform, name="capcap-waveform", daemon=True)
            waveform_thread.start()
            thumbnails = [item for item in thumbnail_pool.map(build_thumbnail, enumerate(timestamps)) if item]
            waveform_thread.join()
        if waveform_error:
            raise waveform_error[0]
        waveform, duration_s = waveform_result if waveform_result else ([], duration_s)

        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump({
                "visual_version": 4, "source": source, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
                "duration_s": float(duration_s), "waveform": waveform, "thumbnails": thumbnails,
            }, handle)
        print(f"[Launcher] Timeline visuals prepared: waveform={len(waveform)}, thumbnails={len(thumbnails)}")
    except Exception as exc:
        print(f"[Launcher] Timeline visual preparation skipped: {exc}")


class LauncherWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.selected_video = ""
        self.selected_device = "cuda"
        self._thumbnail_dir = os.path.join(workspace_root(), "temp", "launcher_thumbs")

        from runtime_paths import asset_path
        from PySide6.QtGui import QIcon
        tank_logo = asset_path("tankvideo.png")
        logo = tank_logo if os.path.exists(tank_logo) else asset_path("tankvideo.ico")
        if os.path.exists(logo):
            self.setWindowIcon(QIcon(logo))

        self.setWindowTitle("TankVideo Studio - Xưởng dịch thuật & Lồng tiếng video AI")
        self.setMinimumSize(940, 620)
        self.resize(980, 650)
        self.setStyleSheet("""
            QDialog {
                background-color: #080c14;
                color: #e2e8f0;
            }
            QWidget {
                color: #e2e8f0;
            }
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollArea > QWidget {
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
            QScrollBar:vertical {
                background: #090e1a;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #1e293b;
                min-height: 24px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #334155;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QFrame#projectCard {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 12px;
            }
            QFrame#projectCard:hover {
                background-color: #162238;
                border: 1px solid #ff7b1a;
            }
            QFrame#recentContainer {
                background-color: #0a0f1d;
                border: 1px solid #1e293b;
                border-radius: 14px;
            }
        """)

        self._build_ui()
        QTimer.singleShot(0, self._load_recent)
        QTimer.singleShot(0, self._validate_resources_for_device)
        QTimer.singleShot(2500, self._check_update_quietly)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        # --- 1. HEADER SECTION ---
        header = QHBoxLayout()
        header.setSpacing(16)

        # Brand & Subtitle
        header_brand = QVBoxLayout()
        header_brand.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel()
        title.setText(
            "<span style='color:#f8fafc; font-size:25px; font-weight:900; letter-spacing:1px;'>TANK</span>"
            "<span style='color:#ff7b1a; font-size:25px; font-weight:900; letter-spacing:1px;'>VIDEO</span>"
        )
        title.setTextFormat(Qt.RichText)
        title_row.addWidget(title)

        pro_badge = QLabel("PRO STUDIO 2026")
        pro_badge.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #451a03, stop:1 #78350f);
            color: #fbbf24; font-size: 10px; font-weight: 800; border: 1px solid #b45309;
            border-radius: 6px; padding: 3px 8px;
        """)
        title_row.addWidget(pro_badge)

        self.btn_update = QPushButton("🔄 Kiểm tra cập nhật")
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.setToolTip("Kiểm tra phiên bản mới từ GitHub")
        self.btn_update.setStyleSheet("""
            QPushButton {
                background: #111a2e; color: #38bdf8; font-size: 11px; font-weight: 700;
                border: 1px solid #1e3a8a; border-radius: 6px; padding: 3px 10px;
            }
            QPushButton:hover { background: #1e293b; color: #7dd3fc; border-color: #38bdf8; }
        """)
        self.btn_update.clicked.connect(self._on_check_update)
        title_row.addWidget(self.btn_update)
        title_row.addStretch()
        header_brand.addLayout(title_row)

        subtitle = QLabel("Xưởng dịch thuật & Lồng tiếng video AI tự động chuyên nghiệp")
        subtitle.setStyleSheet("font-size: 12px; color: #ff9d42; font-weight: 600;")
        header_brand.addWidget(subtitle)

        # Hardware & CPU/GPU Mode Row
        has_gpu, gpu_name, cuda_ready = self._detect_gpu_with_cuda()
        gpu_usable = has_gpu and cuda_ready
        self.selected_device = "cuda" if gpu_usable else "cpu"
        LauncherWindow._gpu_name = gpu_name if has_gpu else ""

        device_row = QHBoxLayout()
        device_row.setSpacing(8)

        self.cpu_btn = QPushButton("CPU")
        self.cpu_btn.setCheckable(True)
        self.cpu_btn.setChecked(not gpu_usable)
        self.gpu_btn = QPushButton("GPU NVIDIA" if gpu_usable else "GPU (Không khả dụng)")
        self.gpu_btn.setCheckable(True)
        self.gpu_btn.setChecked(gpu_usable)
        self.gpu_btn.setEnabled(gpu_usable)

        btn_style = """
            QPushButton {
                color: #8ea3bb; border: 1px solid #2f4868; padding: 4px 12px;
                font-size: 11px; font-weight: 700; border-radius: 6px;
                background-color: #111a2e;
            }
            QPushButton:checked {
                background-color: #1e3a8a; color: #60a5fa; border-color: #3b82f6;
            }
            QPushButton:disabled {
                color: #475569; border-color: #1e293b; background-color: #0b0f19;
            }
        """
        self.cpu_btn.setStyleSheet(btn_style)
        self.gpu_btn.setStyleSheet(btn_style)

        def _select_cpu(checked):
            if checked:
                self.gpu_btn.setChecked(False)
                self._set_selected_device("cpu")
                self._validate_resources_for_device()
            elif not self.gpu_btn.isChecked():
                self.cpu_btn.setChecked(True)

        def _select_gpu(checked):
            if checked:
                self.cpu_btn.setChecked(False)
                self._set_selected_device("cuda")
                self._validate_resources_for_device()
            elif not self.cpu_btn.isChecked():
                self.gpu_btn.setChecked(True)

        self.cpu_btn.clicked.connect(_select_cpu)
        self.gpu_btn.clicked.connect(_select_gpu)

        device_row.addWidget(self.cpu_btn)
        device_row.addWidget(self.gpu_btn)

        self._gpu_label = QLabel()
        self._update_gpu_label(has_gpu, gpu_name, cuda_ready)
        device_row.addWidget(self._gpu_label)
        device_row.addStretch()

        header_brand.addLayout(device_row)
        header.addLayout(header_brand, 1)

        # Right Toolbar Actions (Sleek Pills)
        toolbar_grid = QGridLayout()
        toolbar_grid.setSpacing(8)

        self.ai_settings_btn = QPushButton("⚙️ Cài đặt AI && API Key")
        self.ai_settings_btn.setMinimumHeight(38)
        self.ai_settings_btn.setStyleSheet("""
            QPushButton {
                background: #2e1c4a; color: #c084fc; font-weight: 700; font-size: 12px;
                border-radius: 8px; border: 1px solid #7c3aed; padding: 6px 14px;
            }
            QPushButton:hover { background: #3b2260; color: #f3e8ff; border-color: #a855f7; }
        """)
        self.ai_settings_btn.setToolTip("Cấu hình DeepSeek API Key, Google Gemini hoặc Google Dịch miễn phí")
        self.ai_settings_btn.clicked.connect(self._on_manage_ai_settings)
        toolbar_grid.addWidget(self.ai_settings_btn, 0, 0)

        self.license_btn = QPushButton("🔑 Bản quyền && VIP")
        self.license_btn.setMinimumHeight(38)
        self.license_btn.setStyleSheet("""
            QPushButton {
                background: #064e3b; color: #6ee7b7; font-weight: 700; font-size: 12px;
                border-radius: 8px; border: 1px solid #059669; padding: 6px 14px;
            }
            QPushButton:hover { background: #065f46; color: #ffffff; border-color: #10b981; }
        """)
        self.license_btn.setToolTip("Xem thông tin gói VIP, số ngày còn lại, gia hạn hoặc đăng xuất")
        self.license_btn.clicked.connect(self._on_manage_license)
        toolbar_grid.addWidget(self.license_btn, 0, 1)

        self.resource_btn = QPushButton("📦 Quản lý tài nguyên")
        self.resource_btn.setMinimumHeight(38)
        self.resource_btn.setStyleSheet("""
            QPushButton {
                background: #1e293b; color: #94a3b8; font-weight: 700; font-size: 12px;
                border-radius: 8px; border: 1px solid #334155; padding: 6px 14px;
            }
            QPushButton:hover { background: #334155; color: #f8fafc; }
        """)
        self.resource_btn.setToolTip("Tải mô hình Whisper, SenseVoice, OCR và giọng đọc Piper / VieNeu")
        self.resource_btn.clicked.connect(self._on_manage_resources)
        toolbar_grid.addWidget(self.resource_btn, 1, 0)

        self.split_btn = QPushButton("✂️ Cắt chia video")
        self.split_btn.setMinimumHeight(38)
        self.split_btn.setStyleSheet("""
            QPushButton {
                background: #1e293b; color: #94a3b8; font-weight: 700; font-size: 12px;
                border-radius: 8px; border: 1px solid #334155; padding: 6px 14px;
            }
            QPushButton:hover { background: #334155; color: #f8fafc; }
        """)
        self.split_btn.setToolTip("Cắt video dài thành từng đoạn nhỏ dưới 2 giờ")
        self.split_btn.clicked.connect(self._on_split_video)
        toolbar_grid.addWidget(self.split_btn, 1, 1)

        self.btn_update = QPushButton("🚀 Cập nhật")
        self.btn_update.setMinimumHeight(38)
        self.btn_update.setStyleSheet("""
            QPushButton {
                background: #1e293b; color: #94a3b8; font-weight: 700; font-size: 12px;
                border-radius: 8px; border: 1px solid #334155; padding: 6px 14px;
            }
            QPushButton:hover { background: #334155; color: #f8fafc; }
        """)
        self.btn_update.setToolTip("Kiểm tra và nâng cấp phiên bản mới nhất của TankVideo")
        self.btn_update.clicked.connect(self._on_check_update)
        toolbar_grid.addWidget(self.btn_update, 0, 2)

        self.project_folder_btn = QPushButton("📁 Thư mục")
        self.project_folder_btn.setMinimumHeight(38)
        self.project_folder_btn.setStyleSheet("""
            QPushButton {
                background: #1e293b; color: #94a3b8; font-weight: 700; font-size: 12px;
                border-radius: 8px; border: 1px solid #334155; padding: 6px 14px;
            }
            QPushButton:hover { background: #334155; color: #f8fafc; }
        """)
        self.project_folder_btn.setToolTip("Mở thư mục chứa các dự án video")
        self.project_folder_btn.clicked.connect(self._on_open_project_folder)
        toolbar_grid.addWidget(self.project_folder_btn, 1, 2)

        self.download_video_btn = QPushButton("📥 Tải video MXH")
        self.download_video_btn.setMinimumHeight(38)
        self.download_video_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0e4a6e, stop:1 #1e3a8a);
                color: #38bdf8; font-weight: 700; font-size: 12px;
                border-radius: 8px; border: 1px solid #0ea5e9; padding: 6px 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #155e8a, stop:1 #2855a8);
                color: #7dd3fc; border-color: #38bdf8;
            }
        """)
        self.download_video_btn.setToolTip("Tải video từ YouTube, TikTok, Douyin, Bilibili, Xiaohongshu – Không logo, không watermark, HD/Full HD")
        self.download_video_btn.clicked.connect(self._on_open_downloader)
        toolbar_grid.addWidget(self.download_video_btn, 2, 0, 1, 3)

        header.addLayout(toolbar_grid)
        root.addLayout(header)

        # Missing resource alert banner (hidden by default)
        self._missing_label = QLabel("", self)
        self._missing_label.setWordWrap(True)
        self._missing_label.setStyleSheet(
            "font-size: 12px; color: #fca5a5; padding: 8px 12px;"
            " background-color: #3b1414; border: 1px solid #b91c1c; border-radius: 8px; font-weight: 600;"
        )
        self._missing_label.hide()
        root.addWidget(self._missing_label)

        # --- 2. HERO ACTION BANNER (DRAG & DROP / CLICK) ---
        self.hero_card = HeroDropCard(self)
        self.hero_card.clicked.connect(self._on_new_project)
        self.hero_card.file_dropped.connect(self._on_file_dropped)
        self.new_btn = self.hero_card.btn_select
        root.addWidget(self.hero_card)

        # --- 3. RECENT PROJECTS SECTION ---
        recent_header = QHBoxLayout()
        recent_header.setSpacing(8)

        self.section_label = QLabel("🎬 DỰ ÁN GẦN ĐÂY")
        self.section_label.setStyleSheet("font-size: 14px; font-weight: 800; color: #38bdf8; letter-spacing: 0.5px;")
        recent_header.addWidget(self.section_label)

        self.count_badge = QLabel("(0 dự án)")
        self.count_badge.setStyleSheet("font-size: 12px; color: #64748b; font-weight: 600;")
        recent_header.addWidget(self.count_badge)

        recent_header.addStretch()

        self.open_project_btn = QPushButton("📂 Mở thư mục dự án")
        self.open_project_btn.setStyleSheet("""
            QPushButton {
                background: #111a2e; color: #38bdf8; font-weight: 600; font-size: 12px;
                border-radius: 6px; border: 1px solid #1e3a8a; padding: 5px 12px;
            }
            QPushButton:hover { background: #1e293b; color: #7dd3fc; }
        """)
        self.open_project_btn.clicked.connect(self._on_open_project_folder)
        recent_header.addWidget(self.open_project_btn)

        self.clean_video_btn = QPushButton("🧹 Dọn dẹp cache")
        self.clean_video_btn.setStyleSheet("""
            QPushButton {
                background: #251419; color: #f87171; font-weight: 600; font-size: 12px;
                border-radius: 6px; border: 1px solid #7f1d1d; padding: 5px 12px;
            }
            QPushButton:hover { background: #3b141e; color: #fca5a5; }
        """)
        self.clean_video_btn.setToolTip("Xóa cache xem trước và dữ liệu tạm")
        self.clean_video_btn.clicked.connect(self._on_clean_video_data)
        recent_header.addWidget(self.clean_video_btn)

        root.addLayout(recent_header)

        # Container Frame for Projects (NO MORE WHITE BOX!)
        self.recent_container = QFrame(self)
        self.recent_container.setObjectName("recentContainer")
        container_layout = QVBoxLayout(self.recent_container)
        container_layout.setContentsMargins(10, 10, 10, 10)

        # Scroll Area for Project Cards
        self.scroll = QScrollArea(self.recent_container)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        if self.scroll.viewport():
            self.scroll.viewport().setStyleSheet("background: transparent; border: none;")
            self.scroll.viewport().setAutoFillBackground(False)

        self.grid_widget = QWidget()
        self.grid_widget.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll.setWidget(self.grid_widget)
        container_layout.addWidget(self.scroll)

        # Modern Empty State Widget
        self.empty_widget = QWidget(self.recent_container)
        self.empty_widget.setStyleSheet("background: transparent;")
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(8)

        empty_icon = QLabel("🎬")
        empty_icon.setStyleSheet("font-size: 38px; background: transparent;")
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_icon)

        empty_title = QLabel("Chưa có dự án nào gần đây")
        empty_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #e2e8f0; background: transparent;")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_title)

        empty_desc = QLabel("Bấm vào khung 'TẠO DỰ ÁN MỚI' ở trên hoặc kéo thả video vào để bắt đầu dịch thuật & lồng tiếng ngay!")
        empty_desc.setStyleSheet("font-size: 12px; color: #64748b; background: transparent;")
        empty_desc.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_desc)

        container_layout.addWidget(self.empty_widget)
        self.empty_widget.hide()

        root.addWidget(self.recent_container, 1)

        self.loading_label = QLabel("Đang chuẩn bị video...")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("color: #ff7b1a; font-size: 15px; font-weight: 700; padding: 12px;")
        self.loading_label.hide()
        root.addWidget(self.loading_label)

        # Kiểm tra bản cập nhật ngầm sau khi hiển thị Launcher
        QTimer.singleShot(1500, self._check_update_quietly)

    def _on_file_dropped(self, video_path: str):
        if video_path and os.path.exists(video_path):
            self.selected_video = video_path
            self.accept()

    def accept(self):
        # Chặn bắt buộc cập nhật nếu có phiên bản mới
        if getattr(LauncherWindow, "_cached_update_info", None) and LauncherWindow._cached_update_info.get("has_update"):
            from ui.dialogs.update_dialog import UpdateDialog
            dlg = UpdateDialog(self, workspace_root=workspace_root(), mandatory=True, preloaded_info=LauncherWindow._cached_update_info)
            dlg.exec()
            return

        if not self.selected_video or not os.path.exists(self.selected_video):
            super().accept()
            return

        try:
            service = self._resource_service()
            is_ok, missing, _advisory = self._launch_resource_state(service)
            if not is_ok:
                from PySide6.QtWidgets import QMessageBox
                labels = [label for _rid, label in missing]
                if self.selected_device == "cpu":
                    prefix = "Chế độ CPU cần:"
                else:
                    prefix = "Chế độ GPU cần:"
                mb = QMessageBox(self)
                mb.setIcon(QMessageBox.Warning)
                mb.setWindowTitle("Thiếu tài nguyên")
                mb.setText(f"{prefix}\n\n" + "\n".join(f"- {label}" for label in labels))
                mb.setInformativeText("Mở Quản lý tài nguyên để tải về.")
                mb.addButton("Quản lý tài nguyên", QMessageBox.AcceptRole)
                mb.addButton("Đóng", QMessageBox.RejectRole)
                mb.setStyleSheet(MSG_STYLE)
                mb.exec()
                self._validate_resources_for_device()
                return
        except Exception as exc:
            print(f"[Launcher] Resource validation failed: {exc}")

        duration = _get_video_duration(self.selected_video)
        MAX_DURATION = 7200
        if duration > MAX_DURATION:
            h = int(duration // 3600)
            m = int((duration % 3600) // 60)
            from PySide6.QtWidgets import QMessageBox
            reply = QMessageBox.warning(
                self, "Video quá dài",
                f"Video này dài {h} giờ {m} phút.\nTankVideo hoạt động tối ưu nhất với video dưới 2 giờ.\n\n"
                "Hãy dùng tính năng 'Cắt chia video' để chia nhỏ thành từng đoạn trước.",
                QMessageBox.Ok,
            )
            reply.setStyleSheet(MSG_STYLE)
            return

        self._set_selected_device(self.selected_device)
        self.loading_label.show()
        self.loading_label.setText("Đang chuẩn bị hình thu nhỏ và dạng sóng âm thanh...\nVideo dung lượng lớn có thể tiếp tục xử lý ngầm trong trình biên tập.")
        self.new_btn.setEnabled(False)
        self._extraction_done = False
        self._preprocess_started_at = time.monotonic()
        self._preprocess_continued_in_background = False
        import threading
        def _preprocess():
            from runtime_paths import workspace_root
            temp_root = os.path.join(workspace_root(), "temp")
            _prepare_timeline_visual_cache(self.selected_video, temp_root)
            self._extraction_done = True
        threading.Thread(target=_preprocess, daemon=True).start()
        self._loader_timer = QTimer()
        self._loader_timer.timeout.connect(self._on_loader_tick)
        self._loader_timer.start(200)

    def _on_loader_tick(self):
        if not getattr(self, "_extraction_done", False):
            # Do not hold the launcher hostage while a long video is being
            # sampled.  The cache worker is filesystem-only and can safely
            # finish after the editor opens; the editor has its own cache
            # consumers/fallback workers for any assets not ready yet.
            started = float(getattr(self, "_preprocess_started_at", 0.0) or 0.0)
            if started and time.monotonic() - started >= 12.0:
                self._preprocess_continued_in_background = True
                print("[Launcher] Timeline visual cache is still preparing; continuing in background.")
                self._loader_timer.stop()
                self._finish_accept()
            return
        self._loader_timer.stop()
        self._finish_accept()

    def _finish_accept(self):
        self.loading_label.hide()
        self.new_btn.setEnabled(True)
        self._save_device_env()
        super().accept()

    @staticmethod
    def _save_device_env():
        device = getattr(LauncherWindow, "_selected_device", "cuda")
        gpu_name = getattr(LauncherWindow, "_gpu_name", "")
        print(f"[Launcher] Saving CAPCAP_DEVICE={device}, GPU={gpu_name}")
        os.environ["CAPCAP_DEVICE"] = device
        os.environ["CAPCAP_GPU_NAME"] = gpu_name
        # ``__file__`` points inside _internal in a PyInstaller build. The
        # writable package root is the only place both later GUI launches and
        # the spawned worker can consistently read.
        env_path = os.path.join(workspace_root(), ".env")
        try:
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            found = False
            for i, line in enumerate(lines):
                if line.startswith("CAPCAP_DEVICE="):
                    lines[i] = f"CAPCAP_DEVICE={device}\n"
                    found = True
                    break
            if not found:
                lines.append(f"CAPCAP_DEVICE={device}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception as e:
            print(f"[Launcher] Failed to write .env: {e}")

    def _set_selected_device(self, device: str) -> None:
        """Apply the launcher choice immediately and make it authoritative."""
        normalized = "cuda" if str(device or "").strip().lower() == "cuda" else "cpu"
        self.selected_device = normalized
        LauncherWindow._selected_device = normalized
        # The Main UI and its local worker inherit this exact value. Do not
        # wait for thumbnail preprocessing to finish before publishing it.
        os.environ["CAPCAP_DEVICE"] = normalized

    def _resource_service(self):
        from runtime_paths import workspace_root
        from services import ResourceDownloadService
        return ResourceDownloadService(workspace_root())

    def _launch_resource_state(self, service):
        """Return launch-blocking and advisory resource requirements.

        SenseVoice has a recovery download for installations where the
        bundled model cannot be detected, but its absence must not prevent a
        user from opening the Main UI.  The Generate/prepare workflow still
        performs the exact runtime validation before transcription starts.
        GPU requirements such as the CUDA pack remain launch-blocking.
        """
        _validated, missing = service.validate_device(self.selected_device)
        blocking = []
        advisory = []
        for resource_id, label in missing:
            if str(resource_id or "").strip().lower().startswith("sensevoice:"):
                advisory.append((resource_id, label))
            else:
                blocking.append((resource_id, label))
        return (not blocking), blocking, advisory

    def _validate_resources_for_device(self):
        try:
            service = self._resource_service()
        except Exception as exc:
            print(f"[Launcher] Failed to load resource service: {exc}")
            self.new_btn.setEnabled(True)
            return
        device = self.selected_device
        is_ok, missing, advisory = self._launch_resource_state(service)
        self.new_btn.setEnabled(is_ok)
        if device == "cuda":
            has_gpu = True
            gpu_name = ""
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=10,
                    **subprocess_hidden_kwargs(),
                )
                if result.returncode == 0 and result.stdout.strip():
                    gpu_name = result.stdout.strip().split("\n")[0].strip()
            except Exception:
                pass
            cuda_ready = is_ok
            self._update_gpu_label(has_gpu, gpu_name, cuda_ready)
            if not cuda_ready:
                self.gpu_btn.setEnabled(False)
                self.gpu_btn.setText("GPU (Không khả dụng)")
        elif device == "cpu":
            has_gpu, _gpu_name, cuda_ready = self._detect_gpu_with_cuda()
            gpu_usable = has_gpu and cuda_ready
            if gpu_usable:
                self.gpu_btn.setEnabled(True)
                self.gpu_btn.setText("GPU (Khuyên dùng)")
                self._update_gpu_label(has_gpu, _gpu_name, cuda_ready)
        if is_ok and not advisory:
            self._missing_label.hide()
            self._missing_label.setText("")
            if hasattr(self, "new_btn") and self.new_btn.toolTip():
                self.new_btn.setToolTip("")
        elif is_ok:
            labels = [label for _rid, label in advisory]
            text = (
                "Chưa phát hiện mô hình SenseVoice. Bạn vẫn có thể tiếp tục vào giao diện chính; "
                "hãy tải SenseVoice trong Quản lý tài nguyên trước khi chép lời."
            )
            self._missing_label.setText(text)
            self._missing_label.show()
            self.new_btn.setToolTip(text)
        else:
            labels = [label for _rid, label in missing]
            if advisory:
                labels.extend(label for _rid, label in advisory)
            if device == "cpu":
                prefix = "Chế độ CPU cần:"
            else:
                prefix = "Chế độ GPU cần:"
            text = f"{prefix} {', '.join(labels)}. Hãy mở Quản lý tài nguyên để tải."
            self._missing_label.setText(text)
            self._missing_label.show()
            self.new_btn.setToolTip(text)
        try:
            for i in range(self.grid.count()):
                item = self.grid.itemAt(i)
                if item is None:
                    continue
                widget = item.widget()
                if isinstance(widget, ProjectCard):
                    widget.setEnabled(is_ok)
        except Exception:
            pass

    def _load_recent(self):
        projects = _load_recent_projects()
        os.makedirs(self._thumbnail_dir, exist_ok=True)

        for i in reversed(range(self.grid.count())):
            widget = self.grid.itemAt(i).widget()
            if widget:
                widget.deleteLater()

        existing = [p for p in projects if os.path.exists(p.get("video_path", ""))]
        if existing != projects:
            _save_recent_projects(None, existing)

        count = len(existing)
        if hasattr(self, "count_badge"):
            self.count_badge.setText(f"({count} dự án)")

        if not existing:
            if hasattr(self, "scroll"):
                self.scroll.hide()
            if hasattr(self, "empty_widget"):
                self.empty_widget.show()
            return

        if hasattr(self, "empty_widget"):
            self.empty_widget.hide()
        if hasattr(self, "scroll"):
            self.scroll.show()

        container_w = self.recent_container.width() if hasattr(self, "recent_container") else self.grid_widget.width()
        columns = min(4, max(2, (container_w - 40) // 250))
        for i, proj in enumerate(existing):
            card = ProjectCard(proj["video_path"], self._thumbnail_dir, self)
            row, col = divmod(i, max(1, columns))
            self.grid.addWidget(card, row, col)
            self.grid.setColumnStretch(col, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._load_recent)

    def _on_new_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video", "",
            "Tệp video (*.mp4 *.mkv *.avi *.mov *.webm);;Tất cả tệp (*)"
        )
        if path:
            self.selected_video = path
            self.accept()

    def _on_manage_resources(self):
        from views.resource_manager import open_resource_manager
        open_resource_manager(parent=self)
        self._validate_resources_for_device()

    def _on_manage_license(self):
        from ui.dialogs.login_license_dialog import LoginLicenseDialog
        dlg = LoginLicenseDialog(self, workspace_root=workspace_root())
        dlg.exec()

    def _on_manage_ai_settings(self):
        from ui.dialogs.ai_settings_dialog import AiSettingsDialog
        dlg = AiSettingsDialog(self, workspace_root=workspace_root())
        dlg.exec()

    def _on_check_update(self):
        from ui.dialogs.update_dialog import UpdateDialog
        info = getattr(LauncherWindow, "_cached_update_info", None)
        is_mand = bool(info and info.get("has_update"))
        dlg = UpdateDialog(self, workspace_root=workspace_root(), mandatory=is_mand, preloaded_info=info)
        dlg.exec()

    def _check_update_quietly(self):
        import threading
        def _bg():
            try:
                from app.services.update_service import UpdateService
                res = UpdateService(workspace_root()).check_for_updates(timeout=8.0)
                if res.get("has_update"):
                    latest = str(res.get("latest_version", "") or "")
                    LauncherWindow._cached_update_info = res
                    QTimer.singleShot(0, lambda: self._on_mandatory_update_detected(res))
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True).start()

    def _on_mandatory_update_detected(self, info: dict):
        latest = str(info.get("latest_version", "") or "")
        self._notify_update_available(latest)
        from ui.dialogs.update_dialog import UpdateDialog
        dlg = UpdateDialog(self, workspace_root=workspace_root(), mandatory=True, preloaded_info=info)
        dlg.exec()

    def _notify_update_available(self, latest_ver: str):
        if hasattr(self, "btn_update"):
            self.btn_update.setText(f"🔥 Có bản mới {latest_ver}")
            self.btn_update.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7b1a, stop:1 #e04800);
                    color: #ffffff; font-size: 11px; font-weight: 800;
                    border: 1px solid #ff9d42; border-radius: 6px; padding: 3px 10px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff8c33, stop:1 #f05400);
                }
            """)

    def _on_open_downloader(self):
        from ui.dialogs.video_downloader_dialog import VideoDownloaderDialog
        dlg = VideoDownloaderDialog(self, workspace_root=workspace_root())
        dlg.exec()

    def _on_open_project_folder(self):
        from PySide6.QtWidgets import QMessageBox
        projects_dir = os.path.join(workspace_root(), "projects")
        try:
            os.makedirs(projects_dir, exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(projects_dir)
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(projects_dir))
        except Exception as exc:
            message = QMessageBox(QMessageBox.Warning, "Mở thư mục dự án",
                f"Không thể mở thư mục dự án:\n\n{exc}", QMessageBox.Ok, self)
            message.setStyleSheet(MSG_STYLE)
            message.exec()

    def _on_clean_video_data(self):
        from PySide6.QtWidgets import QMessageBox

        confirm = QMessageBox(QMessageBox.Warning, "Dọn dẹp dữ liệu video",
            "Bạn có chắc muốn xóa toàn bộ dữ liệu dự án và bộ nhớ đệm xem trước video?\n\n"
            "Video gốc, các mô hình đã tải, giọng Piper, tệp CUDA và tài nguyên ứng dụng sẽ được giữ nguyên.",
            QMessageBox.Yes | QMessageBox.No, self)
        confirm.setStyleSheet(MSG_STYLE)
        if confirm.exec() != QMessageBox.Yes:
            return

        # Keep generated project/cache data in the explicit writable runtime
        # root rather than deriving it from a module location.
        root = workspace_root()
        targets = [
            os.path.join(root, "projects"),
            os.path.join(root, "temp"),
        ]

        # Project cards can still own loaded thumbnail pixmaps from temp.
        # Detach them and process their deferred deletion before removing the
        # cache tree; this avoids a common first-click Windows file lock.
        try:
            from PySide6.QtWidgets import QApplication
            for index in reversed(range(self.grid.count())):
                item = self.grid.takeAt(index)
                widget = item.widget() if item is not None else None
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
            QApplication.processEvents()
        except Exception:
            pass

        removed = 0
        errors = []
        for target in targets:
            if not os.path.exists(target):
                continue
            last_error = None
            # FFmpeg/thumbnail work can release a file just after the user
            # confirms cleanup. Retry briefly instead of making the user
            # click Clean Video Data a second time.
            for attempt in range(5):
                try:
                    shutil.rmtree(target)
                    removed += 1
                    last_error = None
                    break
                except FileNotFoundError:
                    last_error = None
                    break
                except OSError as exc:
                    last_error = exc
                    if attempt < 4:
                        try:
                            QApplication.processEvents()
                        except Exception:
                            pass
                        time.sleep(0.25 * (attempt + 1))
            if last_error is not None:
                errors.append(f"{os.path.basename(target)}: {last_error}")
        for target in targets:
            try:
                os.makedirs(target, exist_ok=True)
            except OSError:
                pass
        # Cleaning all generated project data also resets the launcher history;
        # no deleted project should remain listed in recent_projects.json.
        try:
            _save_recent_projects(None, [])
            self._load_recent()
        except Exception as exc:
            errors.append(f"recent projects: {exc}")

        if errors:
            detail = "\n".join(errors)
            message = QMessageBox(QMessageBox.Warning, "Dọn dẹp dữ liệu video",
                f"Một số dữ liệu không thể xóa:\n\n{detail}", QMessageBox.Ok, self)
            message.setStyleSheet(MSG_STYLE)
            message.exec()
        else:
            message = QMessageBox(QMessageBox.Information, "Dọn dẹp dữ liệu video",
                "Đã dọn dẹp xong toàn bộ dữ liệu dự án và bộ nhớ đệm video.", QMessageBox.Ok, self)
            message.setStyleSheet(MSG_STYLE)
            message.exec()

    def _on_split_video(self):
        from PySide6.QtWidgets import QMessageBox, QProgressDialog, QInputDialog
        from PySide6.QtCore import QThread, Signal
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video dài cần cắt chia", "",
            "Tệp video (*.mp4 *.mkv *.avi *.mov *.webm);;Tất cả tệp (*)"
        )
        if not path:
            return

        duration = _get_video_duration(path)
        if duration <= 7200:
            mb = QMessageBox(QMessageBox.Information, "Không cần cắt chia",
                "Video này dưới 2 giờ. Bạn có thể mở trực tiếp bằng nút '+ Tạo dự án mới'.",
                QMessageBox.Ok, self)
            mb.setStyleSheet(MSG_STYLE)
            mb.exec()
            return

        h = int(duration // 3600)
        m = int((duration % 3600) // 60)

        seg_minutes, ok = QInputDialog.getInt(
            self, "Thời lượng mỗi đoạn",
            f"Video dài {h} giờ {m} phút.\nBạn muốn chia thành các đoạn bao nhiêu phút?",
            120, 10, 1440, 10,
        )
        if not ok:
            return

        seg_seconds = seg_minutes * 60
        base, ext = os.path.splitext(path)
        out_pattern = f"{base}_part%03d{ext}"

        reply = QMessageBox(QMessageBox.Question, "Xác nhận cắt chia video",
            f"Chia thành các đoạn {seg_minutes} phút bằng phương pháp sao chép luồng (không mã hóa lại, cực nhanh).\n\n"
            f"Đầu ra: {out_pattern}\n\nTiếp tục?",
            QMessageBox.Yes | QMessageBox.No, self)
        reply.setStyleSheet(MSG_STYLE)
        if reply.exec() != QMessageBox.Yes:
            return

        progress = QProgressDialog("Đang cắt chia video...", None, 0, 0, self)
        progress.setWindowTitle("Cắt chia video")
        progress.setModal(True)
        progress.setCancelButton(None)
        progress.show()

        import subprocess
        import threading

        def _do_split():
            try:
                subprocess.run(
                    [_ffmpeg_path(), "-y", "-i", path, "-c", "copy",
                     "-f", "segment", "-segment_time", str(seg_seconds),
                     "-reset_timestamps", "1", out_pattern],
                    capture_output=True, timeout=3600, **subprocess_hidden_kwargs(),
                )
                progress.accept()
            except Exception as e:
                progress.accept()
                print(f"[Split] Error: {e}")

        threading.Thread(target=_do_split, daemon=True).start()
        progress.exec()

        mb = QMessageBox(QMessageBox.Information, "Hoàn tất",
            f"Đã cắt video thành các đoạn {seg_minutes} phút.\nTệp được lưu cùng thư mục với video gốc.",
            QMessageBox.Ok, self)
        mb.setStyleSheet(MSG_STYLE)
        mb.exec()

    def _detect_gpu_with_cuda(self):
        has_gpu = False
        gpu_name = ""
        cuda_ready = False
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
                **subprocess_hidden_kwargs(),
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu_name = result.stdout.strip().split("\n")[0].strip()
                has_gpu = True
        except Exception:
            pass
        if not has_gpu:
            try:
                import torch
                if torch.cuda.is_available():
                    name = torch.cuda.get_device_name(0)
                    vram = torch.cuda.get_device_properties(0).total_mem // (1024 ** 3)
                    gpu_name = f"{name} ({vram}GB)"
                    has_gpu = True
            except Exception:
                pass
        if has_gpu:
            try:
                service = self._resource_service()
                cuda_ready = service.is_requirement_met("cuda:whisper")
            except Exception:
                pass
        return has_gpu, gpu_name, cuda_ready

    def _update_gpu_label(self, has_gpu: bool, gpu_name: str, cuda_ready: bool):
        if has_gpu:
            if cuda_ready:
                self._gpu_label.setText(f"GPU: {gpu_name}  \u2713 Đã có CUDA")
                self._gpu_label.setStyleSheet("font-size: 11px; color: #4ecdc4;")
            else:
                self._gpu_label.setText(f"GPU: {gpu_name}  \u2717 Cần gói tăng tốc GPU")
                self._gpu_label.setStyleSheet("font-size: 11px; color: #ffa500;")
        else:
            self._gpu_label.setText("Chỉ dùng CPU")
            self._gpu_label.setStyleSheet("font-size: 11px; color: #5a7a9a;")

    @staticmethod
    def add_recent(settings_or_none, video_path: str):
        video_path = os.path.normpath(video_path)
        projects = _load_recent_projects()
        projects = [p for p in projects if os.path.exists(p.get("video_path", ""))]
        existing = [p for p in projects if os.path.normpath(p.get("video_path", "")) == video_path]
        if existing:
            projects.remove(existing[0])
        projects.insert(0, {
            "video_path": video_path,
            "opened_at": int(time.time()),
        })
        projects = projects[:12]
        _save_recent_projects(None, projects)


def _thumbnail_name(video_path: str) -> str:
    import hashlib
    h = hashlib.md5(video_path.encode()).hexdigest()
    return f"{h}.jpg"


def show_launcher(settings_or_none) -> str:
    """Show launcher, return selected video path or empty string."""
    w = LauncherWindow()
    if w.exec() == QDialog.Accepted:
        return w.selected_video
    return ""
