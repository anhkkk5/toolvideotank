"""
Batch Panel — Giao diện quản lý xử lý hàng loạt video.

Tích hợp vào left_master_stack (index 8) với icon 📦 trên sidebar.
Cho phép:
- Import nhiều video cùng lúc (drag & drop hoặc browse)
- Hiển thị card từng video (thumb, progress, status)
- Chọn max_concurrent (số pipeline chạy đồng thời)
- Nút: Xử lý tất cả / Dừng / Retry lỗi
- Cấu hình riêng từng video (override engine, voice, etc.)
- Log trực tiếp
"""

import os
import time

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QSpinBox,
    QComboBox, QProgressBar, QMenu, QFileDialog, QSizePolicy,
)


def build_batch_panel(gui):
    """Tạo trang Batch Panel để tích hợp vào left_master_stack."""

    # ═══════════════════════════════════════════════════════════════════
    # Root widget
    # ═══════════════════════════════════════════════════════════════════
    panel = QWidget()
    panel.setAcceptDrops(True)
    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(8, 8, 8, 8)
    panel_layout.setSpacing(10)

    # ─── Header ───────────────────────────────────────────────────────
    header = QFrame()
    header.setStyleSheet(
        "QFrame { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        "stop:0 #1A1F2E, stop:1 #0F1318); border: 1px solid #2E384C; "
        "border-radius: 10px; }"
    )
    header_layout = QVBoxLayout(header)
    header_layout.setContentsMargins(14, 12, 14, 12)
    header_layout.setSpacing(6)

    title_row = QHBoxLayout()
    title_icon = QLabel("📦")
    title_icon.setStyleSheet("font-size: 18px; background: transparent; border: none;")
    title_label = QLabel("Xử Lý Hàng Loạt")
    title_label.setStyleSheet(
        "font-size: 16px; font-weight: 800; color: #F8FAFC; "
        "background: transparent; border: none;"
    )
    title_row.addWidget(title_icon)
    title_row.addWidget(title_label)
    title_row.addStretch(1)

    # Badge đếm video
    gui._batch_count_badge = QLabel("0 video")
    gui._batch_count_badge.setStyleSheet(
        "background: #FF8A00; color: #fff; font-size: 10px; font-weight: 700; "
        "border-radius: 8px; padding: 2px 8px; border: none;"
    )
    title_row.addWidget(gui._batch_count_badge)
    header_layout.addLayout(title_row)

    # Subtitle
    sub_label = QLabel("Import nhiều video, cấu hình, bấm 1 nút — xử lý tất cả")
    sub_label.setStyleSheet(
        "color: #94A3B8; font-size: 11px; background: transparent; border: none;"
    )
    sub_label.setWordWrap(True)
    header_layout.addWidget(sub_label)

    panel_layout.addWidget(header)

    # ─── Controls Row ─────────────────────────────────────────────────
    controls_row = QHBoxLayout()
    controls_row.setSpacing(8)

    # Concurrent spinner
    conc_label = QLabel("Đồng thời:")
    conc_label.setStyleSheet("color: #CBD5E1; font-size: 11px; font-weight: 600;")
    controls_row.addWidget(conc_label)

    gui._batch_concurrent_spin = QSpinBox()
    gui._batch_concurrent_spin.setRange(1, 8)
    gui._batch_concurrent_spin.setValue(1)
    gui._batch_concurrent_spin.setFixedWidth(50)
    gui._batch_concurrent_spin.setStyleSheet(
        "QSpinBox { background: #1A2030; color: #F1F5F9; border: 1px solid #2E384C; "
        "border-radius: 4px; padding: 2px 4px; font-size: 11px; }"
        "QSpinBox::up-button, QSpinBox::down-button { width: 14px; }"
    )
    gui._batch_concurrent_spin.setToolTip("Số video xử lý đồng thời (1 = tuần tự, an toàn nhất)")
    controls_row.addWidget(gui._batch_concurrent_spin)

    controls_row.addStretch(1)

    # Import button
    btn_import = QPushButton("＋ Thêm video")
    btn_import.setCursor(Qt.PointingHandCursor)
    btn_import.setFixedHeight(28)
    btn_import.setStyleSheet(
        "QPushButton { background: #1E293B; color: #F1F5F9; font-size: 11px; "
        "font-weight: 700; border: 1px solid #334155; border-radius: 6px; padding: 0 12px; } "
        "QPushButton:hover { background: #334155; border-color: #FF8A00; }"
    )
    btn_import.clicked.connect(lambda: _on_import_videos(gui))
    controls_row.addWidget(btn_import)

    panel_layout.addLayout(controls_row)

    # ─── Video Cards Grid (Scrollable) ────────────────────────────────
    cards_scroll = QScrollArea()
    cards_scroll.setWidgetResizable(True)
    cards_scroll.setFrameShape(QFrame.NoFrame)
    cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    cards_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

    cards_container = QWidget()
    cards_container.setStyleSheet("background: transparent;")
    gui._batch_cards_layout = QVBoxLayout(cards_container)
    gui._batch_cards_layout.setContentsMargins(0, 0, 0, 0)
    gui._batch_cards_layout.setSpacing(6)
    gui._batch_cards_layout.addStretch(1)
    cards_scroll.setWidget(cards_container)

    panel_layout.addWidget(cards_scroll, 1)

    # ─── Drop Zone (khi chưa có video nào) ────────────────────────────
    gui._batch_drop_zone = QFrame()
    gui._batch_drop_zone.setStyleSheet(
        "QFrame { background: #0E121A; border: 2px dashed #2E384C; "
        "border-radius: 12px; min-height: 100px; }"
        "QFrame:hover { border-color: #FF8A00; background: #111620; }"
    )
    drop_layout = QVBoxLayout(gui._batch_drop_zone)
    drop_layout.setAlignment(Qt.AlignCenter)
    drop_layout.setSpacing(6)
    drop_icon = QLabel("🎬")
    drop_icon.setAlignment(Qt.AlignCenter)
    drop_icon.setStyleSheet("font-size: 28px; background: transparent; border: none;")
    drop_layout.addWidget(drop_icon)
    drop_text = QLabel("Kéo thả video vào đây\nhoặc bấm '＋ Thêm video'")
    drop_text.setAlignment(Qt.AlignCenter)
    drop_text.setWordWrap(True)
    drop_text.setStyleSheet(
        "color: #64748B; font-size: 11px; font-weight: 600; "
        "background: transparent; border: none;"
    )
    drop_layout.addWidget(drop_text)
    panel_layout.addWidget(gui._batch_drop_zone)

    # ─── Action Buttons ──────────────────────────────────────────────
    action_row = QHBoxLayout()
    action_row.setSpacing(8)

    gui._batch_start_btn = QPushButton("▶  Xử lý tất cả")
    gui._batch_start_btn.setCursor(Qt.PointingHandCursor)
    gui._batch_start_btn.setFixedHeight(36)
    gui._batch_start_btn.setStyleSheet(
        "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        "stop:0 #FF6B00, stop:1 #FF9500); color: #fff; font-size: 13px; "
        "font-weight: 800; border-radius: 8px; border: none; padding: 0 16px; } "
        "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        "stop:0 #FF8A00, stop:1 #FFB347); } "
        "QPushButton:disabled { background: #334155; color: #64748B; }"
    )
    gui._batch_start_btn.clicked.connect(lambda: _on_start_batch(gui))
    action_row.addWidget(gui._batch_start_btn, 2)

    gui._batch_stop_btn = QPushButton("⏹ Dừng")
    gui._batch_stop_btn.setCursor(Qt.PointingHandCursor)
    gui._batch_stop_btn.setFixedHeight(36)
    gui._batch_stop_btn.setEnabled(False)
    gui._batch_stop_btn.setStyleSheet(
        "QPushButton { background: #1E293B; color: #F87171; font-size: 12px; "
        "font-weight: 700; border: 1px solid #7F1D1D; border-radius: 8px; padding: 0 12px; } "
        "QPushButton:hover { background: #7F1D1D; color: #fff; } "
        "QPushButton:disabled { background: #1E293B; color: #475569; border-color: #334155; }"
    )
    gui._batch_stop_btn.clicked.connect(lambda: _on_stop_batch(gui))
    action_row.addWidget(gui._batch_stop_btn, 1)

    gui._batch_retry_btn = QPushButton("⟳ Retry lỗi")
    gui._batch_retry_btn.setCursor(Qt.PointingHandCursor)
    gui._batch_retry_btn.setFixedHeight(36)
    gui._batch_retry_btn.setEnabled(False)
    gui._batch_retry_btn.setStyleSheet(
        "QPushButton { background: #1E293B; color: #FBBF24; font-size: 12px; "
        "font-weight: 700; border: 1px solid #92400E; border-radius: 8px; padding: 0 12px; } "
        "QPushButton:hover { background: #92400E; color: #fff; } "
        "QPushButton:disabled { background: #1E293B; color: #475569; border-color: #334155; }"
    )
    gui._batch_retry_btn.clicked.connect(lambda: _on_retry_batch(gui))
    action_row.addWidget(gui._batch_retry_btn, 1)

    panel_layout.addLayout(action_row)

    # ─── Summary Bar ─────────────────────────────────────────────────
    gui._batch_summary_label = QLabel("")
    gui._batch_summary_label.setStyleSheet(
        "color: #64748B; font-size: 10px; font-weight: 600; padding: 2px 0;"
    )
    gui._batch_summary_label.setAlignment(Qt.AlignCenter)
    panel_layout.addWidget(gui._batch_summary_label)

    # ─── Log Area ─────────────────────────────────────────────────────
    log_frame = QFrame()
    log_frame.setStyleSheet(
        "QFrame { background: #0B0F14; border: 1px solid #1E232E; border-radius: 6px; }"
    )
    log_layout = QVBoxLayout(log_frame)
    log_layout.setContentsMargins(8, 6, 8, 6)
    log_layout.setSpacing(2)

    log_title = QLabel("📋 Nhật ký batch")
    log_title.setStyleSheet(
        "color: #64748B; font-size: 10px; font-weight: 700; "
        "background: transparent; border: none;"
    )
    log_layout.addWidget(log_title)

    gui._batch_log_label = QLabel("")
    gui._batch_log_label.setStyleSheet(
        "color: #94A3B8; font-size: 10px; background: transparent; border: none;"
    )
    gui._batch_log_label.setWordWrap(True)
    gui._batch_log_label.setMaximumHeight(80)
    gui._batch_log_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    log_layout.addWidget(gui._batch_log_label)

    panel_layout.addWidget(log_frame)

    # ═══════════════════════════════════════════════════════════════════
    # Drag & Drop cho toàn bộ panel
    # ═══════════════════════════════════════════════════════════════════
    def _drag_enter(event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(event: QDropEvent):
        urls = event.mimeData().urls()
        video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"}
        paths = []
        for url in urls:
            p = url.toLocalFile()
            if p and os.path.isfile(p) and os.path.splitext(p)[1].lower() in video_exts:
                paths.append(p)
        if paths:
            _add_videos_to_batch(gui, paths)
        event.acceptProposedAction()

    panel.dragEnterEvent = _drag_enter
    panel.dropEvent = _drop

    # ═══════════════════════════════════════════════════════════════════
    # Khởi tạo BatchPipelineController
    # ═══════════════════════════════════════════════════════════════════
    _init_batch_controller(gui)

    # Store references
    gui._batch_panel = panel
    gui._batch_log_lines = []

    return panel


# ═══════════════════════════════════════════════════════════════════════
# Batch Controller Integration
# ═══════════════════════════════════════════════════════════════════════

def _init_batch_controller(gui):
    """Tạo BatchPipelineController và kết nối signals."""
    from controllers.batch_pipeline_controller import BatchPipelineController

    workspace_root = getattr(gui, "workspace_root", os.getcwd())
    log_fn = getattr(gui, "log", lambda msg: print(msg))

    ctrl = BatchPipelineController(
        workspace_root=str(workspace_root),
        max_concurrent=1,
        log_fn=log_fn,
    )
    gui._batch_controller = ctrl

    # Kết nối signals
    ctrl.workspace_added.connect(lambda ws_id: _refresh_batch_ui(gui))
    ctrl.workspace_removed.connect(lambda ws_id: _refresh_batch_ui(gui))
    ctrl.workspace_status_changed.connect(lambda ws_id, s: _on_ws_status_changed(gui, ws_id, s))
    ctrl.workspace_progress_changed.connect(lambda ws_id, p: _on_ws_progress_changed(gui, ws_id, p))
    ctrl.workspace_step_changed.connect(lambda ws_id, step: _on_ws_step_changed(gui, ws_id, step))
    ctrl.batch_started.connect(lambda: _on_batch_started(gui))
    ctrl.batch_completed.connect(lambda ok, fail: _on_batch_completed(gui, ok, fail))
    ctrl.log_message.connect(lambda msg: _append_batch_log(gui, msg))


# ═══════════════════════════════════════════════════════════════════════
# Actions
# ═══════════════════════════════════════════════════════════════════════

def _on_import_videos(gui):
    """Mở dialog chọn nhiều video."""
    file_paths, _ = QFileDialog.getOpenFileNames(
        gui, "Chọn video cho batch",
        "",
        "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.flv);;All Files (*.*)"
    )
    if file_paths:
        _add_videos_to_batch(gui, file_paths)


def _add_videos_to_batch(gui, paths: list):
    """Thêm danh sách video vào batch controller."""
    ctrl = getattr(gui, "_batch_controller", None)
    if not ctrl:
        return

    from runtime_paths import workspace_root
    thumb_dir = os.path.join(workspace_root(), "temp", "batch_thumbs")
    os.makedirs(thumb_dir, exist_ok=True)

    for p in paths:
        # Kiểm tra trùng
        already = any(ws.video_path == os.path.abspath(p) for ws in ctrl.workspaces)
        if not already:
            ctrl.add_workspace(p, thumb_dir)

    _refresh_batch_ui(gui)


def _on_start_batch(gui):
    """Bắt đầu xử lý batch."""
    ctrl = getattr(gui, "_batch_controller", None)
    if not ctrl:
        return

    # Cập nhật max_concurrent từ spinner
    spin = getattr(gui, "_batch_concurrent_spin", None)
    if spin:
        ctrl.set_max_concurrent(spin.value())

    # Snapshot cấu hình chung từ GUI
    ctrl.set_defaults_from_gui(gui)

    ctrl.start_all()


def _on_stop_batch(gui):
    """Dừng toàn bộ batch."""
    ctrl = getattr(gui, "_batch_controller", None)
    if ctrl:
        ctrl.stop_all()
        _refresh_batch_ui(gui)


def _on_retry_batch(gui):
    """Retry tất cả video lỗi."""
    ctrl = getattr(gui, "_batch_controller", None)
    if ctrl:
        ctrl.retry_failed()
        _refresh_batch_ui(gui)


# ═══════════════════════════════════════════════════════════════════════
# Signal Handlers
# ═══════════════════════════════════════════════════════════════════════

def _on_batch_started(gui):
    gui._batch_start_btn.setEnabled(False)
    gui._batch_start_btn.setText("⏳ Đang xử lý...")
    gui._batch_stop_btn.setEnabled(True)
    gui._batch_retry_btn.setEnabled(False)


def _on_batch_completed(gui, success_count, fail_count):
    gui._batch_start_btn.setEnabled(True)
    gui._batch_start_btn.setText("▶  Xử lý tất cả")
    gui._batch_stop_btn.setEnabled(False)
    gui._batch_retry_btn.setEnabled(fail_count > 0)
    _refresh_batch_ui(gui)
    _append_batch_log(gui, f"✅ Hoàn tất! Thành công: {success_count}, Lỗi: {fail_count}")


def _on_ws_status_changed(gui, ws_id, status):
    _refresh_card_status(gui, ws_id, status)
    _update_summary(gui)


def _on_ws_progress_changed(gui, ws_id, progress):
    widget = gui._batch_card_widgets.get(ws_id)
    if widget:
        pbar = widget.findChild(QProgressBar, f"pbar_{ws_id}")
        if pbar:
            pbar.setValue(int(progress * 100))


def _on_ws_step_changed(gui, ws_id, step):
    widget = gui._batch_card_widgets.get(ws_id)
    if widget:
        step_label = widget.findChild(QLabel, f"step_{ws_id}")
        if step_label:
            step_names = {
                "prepare": "Chuẩn bị",
                "extract_audio": "Trích xuất",
                "extraction": "Trích xuất",
                "separation": "Tách giọng",
                "diarization": "Nhận diện",
                "transcription": "Chép lời",
                "translation": "Dịch thuật",
                "voiceover": "Lồng tiếng",
                "preview": "Xem trước",
                "done": "Hoàn tất",
            }
            step_label.setText(step_names.get(step, step))


# ═══════════════════════════════════════════════════════════════════════
# UI Rendering
# ═══════════════════════════════════════════════════════════════════════

def _refresh_batch_ui(gui):
    """Render lại toàn bộ danh sách video cards."""
    ctrl = getattr(gui, "_batch_controller", None)
    if not ctrl:
        return

    layout = gui._batch_cards_layout

    # Xóa cards cũ (giữ stretch ở cuối)
    if not hasattr(gui, "_batch_card_widgets"):
        gui._batch_card_widgets = {}

    for ws_id, widget in list(gui._batch_card_widgets.items()):
        layout.removeWidget(widget)
        widget.deleteLater()
    gui._batch_card_widgets.clear()

    # Tạo cards mới
    for ws in ctrl.workspaces:
        card = _build_video_card(gui, ws)
        gui._batch_card_widgets[ws.id] = card
        layout.insertWidget(layout.count() - 1, card)  # trước stretch

    # Cập nhật badge, summary, drop zone visibility
    gui._batch_count_badge.setText(f"{len(ctrl.workspaces)} video")
    gui._batch_drop_zone.setVisible(len(ctrl.workspaces) == 0)
    _update_summary(gui)


def _build_video_card(gui, ws):
    """Tạo card widget cho 1 VideoWorkspace."""
    card = QFrame()
    card.setObjectName(f"batch_card_{ws.id}")
    card.setFixedHeight(68)
    card.setCursor(Qt.PointingHandCursor)

    # Border color theo status
    border_colors = {
        "pending": "#2E384C",
        "queued": "#3B82F6",
        "running": "#FF8A00",
        "done": "#22C55E",
        "error": "#EF4444",
        "cancelled": "#6B7280",
    }
    border = border_colors.get(ws.status, "#2E384C")
    card.setStyleSheet(
        f"QFrame#batch_card_{ws.id} {{ "
        f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #141820, stop:1 #0F1318); "
        f"border: 1.5px solid {border}; border-radius: 8px; }}"
    )

    h_layout = QHBoxLayout(card)
    h_layout.setContentsMargins(8, 6, 8, 6)
    h_layout.setSpacing(8)

    # Thumbnail
    thumb_label = QLabel()
    thumb_label.setFixedSize(44, 44)
    thumb_label.setAlignment(Qt.AlignCenter)
    thumb_label.setStyleSheet("background: #0E121A; border-radius: 4px; border: none;")
    if ws.thumb_path and os.path.exists(ws.thumb_path):
        pm = QPixmap(ws.thumb_path)
        if not pm.isNull():
            thumb_label.setPixmap(pm.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            thumb_label.setText("🎬")
            thumb_label.setStyleSheet("font-size: 18px; color: #FFA033; background: #0E121A; border-radius: 4px; border: none;")
    else:
        thumb_label.setText("🎬")
        thumb_label.setStyleSheet("font-size: 18px; color: #FFA033; background: #0E121A; border-radius: 4px; border: none;")
    h_layout.addWidget(thumb_label)

    # Info column
    info_layout = QVBoxLayout()
    info_layout.setContentsMargins(0, 0, 0, 0)
    info_layout.setSpacing(2)

    # Name + duration
    name_row = QHBoxLayout()
    name_row.setSpacing(4)
    display_name = ws.video_name if len(ws.video_name) <= 20 else ws.video_name[:18] + "…"
    name_lbl = QLabel(display_name)
    name_lbl.setStyleSheet("color: #E2E8F0; font-size: 11px; font-weight: 700; border: none;")
    name_row.addWidget(name_lbl)

    if ws.duration_s > 0:
        m, s = divmod(int(ws.duration_s), 60)
        dur_lbl = QLabel(f"{m:02d}:{s:02d}")
        dur_lbl.setStyleSheet(
            "color: #94A3B8; font-size: 9px; background: rgba(0,0,0,0.4); "
            "border-radius: 3px; padding: 1px 4px; border: none;"
        )
        name_row.addWidget(dur_lbl)
    name_row.addStretch(1)
    info_layout.addLayout(name_row)

    # Progress bar
    pbar = QProgressBar()
    pbar.setObjectName(f"pbar_{ws.id}")
    pbar.setRange(0, 100)
    pbar.setValue(int(ws.progress * 100))
    pbar.setFixedHeight(6)
    pbar.setTextVisible(False)
    pbar.setStyleSheet(
        "QProgressBar { background: #1E293B; border-radius: 3px; border: none; }"
        "QProgressBar::chunk { "
        "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF6B00, stop:1 #FF9500); "
        "border-radius: 3px; }"
    )
    info_layout.addWidget(pbar)

    # Status + step
    status_row = QHBoxLayout()
    status_row.setSpacing(4)

    status_icons = {
        "pending": "⏸️",
        "queued": "🔵",
        "running": "🔄",
        "done": "✅",
        "error": "❌",
        "cancelled": "⛔",
    }
    status_texts = {
        "pending": "Chờ",
        "queued": "Hàng đợi",
        "running": "Đang xử lý",
        "done": "Hoàn tất",
        "error": "Lỗi",
        "cancelled": "Đã hủy",
    }
    s_icon = status_icons.get(ws.status, "⏸️")
    s_text = status_texts.get(ws.status, ws.status)
    status_lbl = QLabel(f"{s_icon} {s_text}")
    status_lbl.setObjectName(f"status_{ws.id}")
    status_colors = {
        "pending": "#64748B",
        "queued": "#60A5FA",
        "running": "#FF8A00",
        "done": "#4ADE80",
        "error": "#F87171",
        "cancelled": "#9CA3AF",
    }
    status_lbl.setStyleSheet(
        f"color: {status_colors.get(ws.status, '#64748B')}; "
        f"font-size: 10px; font-weight: 600; border: none;"
    )
    status_row.addWidget(status_lbl)

    step_lbl = QLabel(ws.current_step or "")
    step_lbl.setObjectName(f"step_{ws.id}")
    step_lbl.setStyleSheet("color: #475569; font-size: 9px; border: none;")
    status_row.addWidget(step_lbl)

    if ws.status == "error" and ws.error_message:
        err_short = ws.error_message[:30] + "…" if len(ws.error_message) > 30 else ws.error_message
        err_lbl = QLabel(err_short)
        err_lbl.setStyleSheet("color: #F87171; font-size: 9px; border: none;")
        err_lbl.setToolTip(ws.error_message)
        status_row.addWidget(err_lbl)

    status_row.addStretch(1)

    # Engine badge
    engine = ws.transcription_engine or "default"
    engine_display = {"ocr": "OCR", "whisper": "Whisper", "sensevoice": "SenseVoice"}.get(engine, "")
    if engine_display:
        engine_badge = QLabel(engine_display)
        engine_badge.setStyleSheet(
            "background: #1E293B; color: #94A3B8; font-size: 8px; font-weight: 700; "
            "border-radius: 3px; padding: 1px 5px; border: 1px solid #334155;"
        )
        status_row.addWidget(engine_badge)

    info_layout.addLayout(status_row)
    h_layout.addLayout(info_layout, 1)

    # Delete button (x)
    btn_del = QPushButton("✕")
    btn_del.setFixedSize(22, 22)
    btn_del.setCursor(Qt.PointingHandCursor)
    btn_del.setStyleSheet(
        "QPushButton { background: transparent; color: #475569; font-size: 12px; "
        "font-weight: 700; border: none; border-radius: 11px; } "
        "QPushButton:hover { background: #7F1D1D; color: #F87171; }"
    )
    btn_del.setToolTip("Xóa khỏi batch")
    btn_del.clicked.connect(lambda _c=False, wid=ws.id: _remove_from_batch(gui, wid))
    h_layout.addWidget(btn_del, 0, Qt.AlignTop)

    # Context menu
    card.setContextMenuPolicy(Qt.CustomContextMenu)
    card.customContextMenuRequested.connect(
        lambda pos, wid=ws.id, c=card: _show_card_context_menu(gui, wid, c, pos)
    )

    return card


def _refresh_card_status(gui, ws_id, status):
    """Cập nhật visual của 1 card khi status thay đổi."""
    # Rebuild card cho đơn giản (tránh quản lý từng widget)
    _refresh_batch_ui(gui)


def _remove_from_batch(gui, ws_id):
    """Xóa video khỏi batch."""
    ctrl = getattr(gui, "_batch_controller", None)
    if ctrl:
        ctrl.remove_workspace(ws_id)
        _refresh_batch_ui(gui)


def _show_card_context_menu(gui, ws_id, card, pos):
    """Menu chuột phải cho từng video card."""
    ctrl = getattr(gui, "_batch_controller", None)
    if not ctrl:
        return
    ws = ctrl.get_workspace(ws_id)
    if not ws:
        return

    menu = QMenu(card)
    menu.setStyleSheet(
        "QMenu { background: #161B24; color: #E5E7EB; border: 1px solid #2E384D; "
        "padding: 4px; font-size: 11px; } "
        "QMenu::item:selected { background: #FF8A00; color: #fff; }"
    )

    act_config = menu.addAction("⚙️ Cấu hình riêng")
    if ws.status == "error":
        act_retry = menu.addAction("⟳ Retry video này")
    else:
        act_retry = None
    act_remove = menu.addAction("🗑️ Xóa khỏi batch")

    action = menu.exec(card.mapToGlobal(pos))
    if action == act_config:
        _show_workspace_config(gui, ws_id)
    elif action == act_retry and act_retry:
        ctrl.retry_single(ws_id)
        _refresh_batch_ui(gui)
    elif action == act_remove:
        _remove_from_batch(gui, ws_id)


def _show_workspace_config(gui, ws_id):
    """Dialog cấu hình riêng cho 1 video (engine, voice, etc.)."""
    ctrl = getattr(gui, "_batch_controller", None)
    if not ctrl:
        return
    ws = ctrl.get_workspace(ws_id)
    if not ws:
        return

    # Đơn giản: dùng QMenu dropdown chọn engine
    from PySide6.QtWidgets import QInputDialog
    engines = ["(Dùng mặc định)", "ocr", "whisper", "sensevoice"]
    current_idx = 0
    if ws.transcription_engine in engines:
        current_idx = engines.index(ws.transcription_engine)

    choice, ok = QInputDialog.getItem(
        gui, f"Cấu hình — {ws.video_name}",
        "Chọn engine nhận diện:",
        engines, current_idx, False
    )
    if ok:
        if choice == "(Dùng mặc định)":
            ws.transcription_engine = ""
        else:
            ws.transcription_engine = choice
        _refresh_batch_ui(gui)


def _update_summary(gui):
    """Cập nhật thanh tóm tắt."""
    ctrl = getattr(gui, "_batch_controller", None)
    if not ctrl:
        return

    summary = ctrl.get_summary()
    parts = []
    if summary["done"] > 0:
        parts.append(f"✅ {summary['done']}")
    if summary["running"] > 0:
        parts.append(f"🔄 {summary['running']}")
    if summary["pending"] > 0:
        parts.append(f"⏸ {summary['pending']}")
    if summary["error"] > 0:
        parts.append(f"❌ {summary['error']}")

    text = " │ ".join(parts) if parts else ""
    if summary["is_running"]:
        text = f"Đang chạy (đồng thời: {summary['max_concurrent']})  •  {text}"

    gui._batch_summary_label.setText(text)


def _append_batch_log(gui, msg):
    """Thêm 1 dòng log vào batch log panel."""
    if not hasattr(gui, "_batch_log_lines"):
        gui._batch_log_lines = []

    timestamp = time.strftime("%H:%M")
    line = f"[{timestamp}] {msg}"
    gui._batch_log_lines.append(line)

    # Giữ tối đa 20 dòng
    if len(gui._batch_log_lines) > 20:
        gui._batch_log_lines = gui._batch_log_lines[-20:]

    gui._batch_log_label.setText("\n".join(gui._batch_log_lines[-5:]))
