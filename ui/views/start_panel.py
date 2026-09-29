import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from widgets.spin_boxes import ReliableDoubleSpinBox, ReliableSpinBox


def _section_title(text):
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _section_card():
    card = QFrame()
    card.setObjectName("statusCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)
    return card, layout


def _build_collapsible_section(title: str, start_expanded: bool = True):
    wrapper = QFrame()
    wrapper.setObjectName("statusCard")
    wrapper_layout = QVBoxLayout(wrapper)
    wrapper_layout.setContentsMargins(12, 11, 12, 11)
    wrapper_layout.setSpacing(8)

    toggle_btn = QToolButton()
    toggle_btn.setText(("▼ " if start_expanded else "▶ ") + title)
    toggle_btn.setCheckable(True)
    toggle_btn.setChecked(start_expanded)
    toggle_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
    toggle_btn.setStyleSheet("QToolButton { text-align: left; font-weight: 700; color: #8ad7ff; border: none; padding: 0; }")

    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(10)
    content.setVisible(start_expanded)

    def _toggle_section(checked: bool):
        toggle_btn.setText(("▼ " if checked else "▶ ") + title)
        content.setVisible(checked)
        content.setMaximumHeight(16777215 if checked else 0)

    toggle_btn.toggled.connect(_toggle_section)
    wrapper_layout.addWidget(toggle_btn)
    wrapper_layout.addWidget(content)
    return wrapper, content_layout


def _build_hidden_status_widgets(gui):
    gui.workflow_hint_label = QLabel()
    gui.workflow_hint_label.setObjectName("helperLabel")
    gui.workflow_hint_label.setWordWrap(True)
    gui.workflow_hint_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    gui.workflow_hint_label.setTextInteractionFlags(Qt.NoTextInteraction)


def _build_style_preset_card(title: str, line_one: str, line_two: str, radio: QRadioButton):
    card = QFrame()
    card.setObjectName("statusCard")
    card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    card.setStyleSheet(
        "QFrame#statusCard { background-color: #132132; border: 1px solid #35506f; border-radius: 14px; }"
        "QFrame#statusCard:hover { border-color: #5aa6d9; }"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(4)
    layout.addWidget(radio, 0, Qt.AlignTop)

    title_label = QLabel(title)
    title_label.setObjectName("sectionTitle")
    title_label.setAlignment(Qt.AlignCenter)

    style_key = title.strip().lower()
    preview_frame = QFrame()
    preview_frame.setFixedHeight(88)
    preview_frame.setStyleSheet(
        "QFrame {"
        "background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #1d2940, stop:1 #0d1522);"
        "border:1px solid #2d425d; border-radius: 12px; }"
    )
    preview_layout = QVBoxLayout(preview_frame)
    preview_layout.setContentsMargins(10, 10, 10, 10)
    preview_layout.setSpacing(2)

    preview_top = QLabel(line_one)
    preview_bottom = QLabel(line_two)
    preview_top.setAlignment(Qt.AlignCenter)
    preview_bottom.setAlignment(Qt.AlignCenter)

    if style_key == "tiktok":
        preview_top.setStyleSheet("font-size: 18px; font-weight: 900; color: #ffffff;")
        preview_bottom.setStyleSheet("font-size: 16px; font-weight: 900; color: #ffd400;")
    elif style_key == "youtube":
        preview_top.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #ffffff; "
            "background-color: rgba(0, 0, 0, 255); padding: 4px 8px; border-radius: 7px;"
        )
        preview_bottom.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #ffffff; "
            "background-color: rgba(0, 0, 0, 255); padding: 4px 8px; border-radius: 7px;"
        )
    elif style_key == "short":
        preview_top.setStyleSheet("font-size: 15px; font-weight: 800; color: #ffffff; letter-spacing: 1px;")
        preview_bottom.setStyleSheet("font-size: 13px; color: #dbe5f3;")
    else:
        preview_top.setStyleSheet("font-size: 15px; font-weight: 800; color: #ffffff;")
        preview_bottom.setStyleSheet(
            "font-size: 13px; color: #ffffff; background-color: rgba(0, 0, 0, 120); "
            "padding: 3px 8px; border-radius: 7px;"
        )

    preview_layout.addStretch(1)
    preview_layout.addWidget(preview_top)
    preview_layout.addWidget(preview_bottom)
    preview_layout.addStretch(1)

    layout.addWidget(title_label, 0, Qt.AlignCenter)
    layout.addWidget(preview_frame)
    return card


def _build_filter_preset_button(label: str):
    btn = QPushButton(label)
    btn.setCheckable(True)
    btn.setObjectName("workflowTabBtn")
    btn.setMinimumHeight(32)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return btn


def _build_filter_slider_row(title: str, slider: QSlider, value_label: QLabel):
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(8)
    title_label = QLabel(title)
    title_label.setObjectName("helperLabel")
    value_label.setObjectName("helperLabel")
    value_label.setMinimumWidth(42)
    value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    header.addWidget(title_label)
    header.addStretch(1)
    header.addWidget(value_label)
    layout.addLayout(header)
    layout.addWidget(slider)
    return wrapper


def _update_device_label(gui):
    import os
    cpu_mode = os.getenv("CAPCAP_DEVICE", "cuda").strip().lower() == "cpu"
    if cpu_mode:
        gui.device_mode_label.setText("Chế độ CPU")
        gui.device_mode_label.setStyleSheet("font-size: 11px; color: #ffa500;")
    else:
        gpu_name = os.getenv("CAPCAP_GPU_NAME", "").strip()
        if gpu_name:
            gui.device_mode_label.setText(gpu_name)
        else:
            gui.device_mode_label.setText("Chế độ GPU")
        gui.device_mode_label.setStyleSheet("font-size: 11px; color: #4ecdc4;")


def _build_resource_media_card(gui):
    """Xây dựng thẻ Tài nguyên & Batch — Quản lý Media Pool và Xử lý hàng loạt tích hợp."""
    import os
    import time
    from PySide6.QtCore import Qt, QTimer, QUrl
    from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
        QScrollArea, QProgressBar, QSpinBox, QMenu, QInputDialog, QMessageBox,
    )
    from app.layers.base import LayerType
    from utils.media_utils import (
        import_multi_media_files, import_media_paths,
        append_video_to_timeline, browse_video, probe_video_duration_and_thumb,
    )
    from runtime_paths import workspace_root

    card = QFrame()
    card.setObjectName("resourceMediaCard")
    card.setAcceptDrops(True)
    card.setStyleSheet(
        "QFrame#resourceMediaCard { background-color: #141820; border: 1px solid #2E323A; border-radius: 8px; }"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)

    # ═══════════════════════════════════════════════════════════════════
    # Drag & Drop trực tiếp vào Resource Media Card
    # ═══════════════════════════════════════════════════════════════════
    def _drag_enter(event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(event: QDropEvent):
        urls = event.mimeData().urls()
        video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".mp3", ".wav", ".m4a"}
        paths = []
        for url in urls:
            p = url.toLocalFile()
            if p and os.path.isfile(p) and os.path.splitext(p)[1].lower() in video_exts:
                paths.append(p)
        if paths:
            import_media_paths(gui, paths)
        event.acceptProposedAction()

    card.dragEnterEvent = _drag_enter
    card.dropEvent = _drop

    # ═══════════════════════════════════════════════════════════════════
    # 1. Header: Tài nguyên | Thư viện & Badge đếm video
    # ═══════════════════════════════════════════════════════════════════
    top_tab_row = QHBoxLayout()
    top_tab_row.setContentsMargins(2, 0, 2, 0)
    top_tab_row.setSpacing(10)

    tab_res_btn = QPushButton("Tài nguyên")
    tab_res_btn.setCursor(Qt.PointingHandCursor)
    tab_res_btn.setStyleSheet(
        "QPushButton { background: transparent; color: #FFFFFF; font-weight: 700; font-size: 12px; "
        "border: none; border-bottom: 2px solid #FF8A00; padding: 2px 4px 4px 4px; }"
    )
    tab_lib_btn = QPushButton("Thư viện")
    tab_lib_btn.setCursor(Qt.PointingHandCursor)
    tab_lib_btn.setStyleSheet(
        "QPushButton { background: transparent; color: #8C93A0; font-weight: 500; font-size: 12px; "
        "border: none; border-bottom: 2px solid transparent; padding: 2px 4px 4px 4px; } "
        "QPushButton:hover { color: #E5E7EB; }"
    )
    top_tab_row.addWidget(tab_res_btn)
    top_tab_row.addWidget(tab_lib_btn)
    top_tab_row.addStretch(1)

    gui._batch_count_badge = QLabel("0 tệp")
    gui._batch_count_badge.setStyleSheet(
        "background: #FF8A00; color: #ffffff; font-size: 10px; font-weight: 700; "
        "border-radius: 8px; padding: 2px 8px; border: none;"
    )
    top_tab_row.addWidget(gui._batch_count_badge)
    layout.addLayout(top_tab_row)

    def _switch_res_tab(is_lib: bool):
        if is_lib:
            tab_lib_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #FFFFFF; font-weight: 700; font-size: 12px; "
                "border: none; border-bottom: 2px solid #FF8A00; padding: 2px 4px 4px 4px; }"
            )
            tab_res_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #8C93A0; font-weight: 500; font-size: 12px; "
                "border: none; border-bottom: 2px solid transparent; padding: 2px 4px 4px 4px; } "
                "QPushButton:hover { color: #E5E7EB; }"
            )
        else:
            tab_res_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #FFFFFF; font-weight: 700; font-size: 12px; "
                "border: none; border-bottom: 2px solid #FF8A00; padding: 2px 4px 4px 4px; }"
            )
            tab_lib_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #8C93A0; font-weight: 500; font-size: 12px; "
                "border: none; border-bottom: 2px solid transparent; padding: 2px 4px 4px 4px; } "
                "QPushButton:hover { color: #E5E7EB; }"
            )
    tab_res_btn.clicked.connect(lambda: _switch_res_tab(False))
    tab_lib_btn.clicked.connect(lambda: _switch_res_tab(True))

    # ═══════════════════════════════════════════════════════════════════
    # 2. Nút to màu cam: + Nhập tệp (Chọn nhiều video)
    # ═══════════════════════════════════════════════════════════════════
    import_btn = QPushButton("＋ Nhập tệp (Chọn nhiều video)")
    import_btn.setMinimumHeight(34)
    import_btn.setCursor(Qt.PointingHandCursor)
    import_btn.setStyleSheet(
        "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF8A00, stop:1 #FF6A00); "
        "color: #ffffff; font-weight: 700; font-size: 12px; border-radius: 6px; border: none; padding: 6px; } "
        "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFA033, stop:1 #FF7D1A); } "
        "QPushButton:pressed { background: #E67600; }"
    )
    import_btn.clicked.connect(lambda: import_multi_media_files(gui))
    layout.addWidget(import_btn)

    # ═══════════════════════════════════════════════════════════════════
    # 2b. Khởi tạo SequentialQueueController & State hàng đợi
    # ═══════════════════════════════════════════════════════════════════
    if not hasattr(gui, "queue_controller"):
        from controllers.queue_controller import SequentialQueueController
        gui.queue_controller = SequentialQueueController(gui)

    if not hasattr(gui, "_selected_media_paths"):
        gui._selected_media_paths = set()
    if not hasattr(gui, "_seen_media_paths"):
        gui._seen_media_paths = set()
    if not hasattr(gui, "_video_voice_configs"):
        gui._video_voice_configs = {}
    if not hasattr(gui, "_video_ocr_rects"):
        gui._video_ocr_rects = {}
    if not hasattr(gui, "_video_queue_status"):
        gui._video_queue_status = {}

    # ═══════════════════════════════════════════════════════════════════
    # 2c. Khung Hàng Đợi (1 Luồng tuần tự) & Cài đặt chung / riêng
    # ═══════════════════════════════════════════════════════════════════
    queue_card = QFrame()
    queue_card.setStyleSheet(
        "QFrame { background: #11151F; border: 1px solid #232B3B; border-radius: 6px; }"
    )
    qc_layout = QVBoxLayout(queue_card)
    qc_layout.setContentsMargins(6, 6, 6, 6)
    qc_layout.setSpacing(6)

    # Hàng 1: Checkbox Tất cả + Nút Đặt OCR chung
    setup_row = QHBoxLayout()
    setup_row.setSpacing(6)

    gui._queue_select_all_cb = QCheckBox("Tất cả (0/0)")
    gui._queue_select_all_cb.setCursor(Qt.PointingHandCursor)
    gui._queue_select_all_cb.setStyleSheet(
        "QCheckBox { color: #CBD5E1; font-size: 10px; font-weight: 700; } "
        "QCheckBox::indicator { width: 13px; height: 13px; border-radius: 3px; border: 1px solid #475569; background: #0B0E14; } "
        "QCheckBox::indicator:checked { background: #FF8A00; border-color: #FF8A00; }"
    )
    setup_row.addWidget(gui._queue_select_all_cb)
    setup_row.addStretch(1)

    btn_group_ocr = QPushButton("🎯 Đặt OCR chung")
    btn_group_ocr.setFixedHeight(22)
    btn_group_ocr.setCursor(Qt.PointingHandCursor)
    btn_group_ocr.setToolTip("Cài đặt chung: Áp dụng vị trí khung OCR cho các video đang chọn")
    btn_group_ocr.setStyleSheet(
        "QPushButton { background: #132420; color: #34D399; border: 1px solid #059669; border-radius: 3px; font-size: 10px; font-weight: 700; padding: 1px 8px; } "
        "QPushButton:hover { background: #059669; color: #FFFFFF; }"
    )
    setup_row.addWidget(btn_group_ocr)

    btn_open_folder = QPushButton("📁 Thư mục video")
    btn_open_folder.setFixedHeight(22)
    btn_open_folder.setCursor(Qt.PointingHandCursor)
    btn_open_folder.setToolTip("Mở thư mục lưu các video kết quả đã xuất")
    btn_open_folder.setStyleSheet(
        "QPushButton { background: #162032; color: #38BDF8; border: 1px solid #0284C7; border-radius: 3px; font-size: 10px; font-weight: 700; padding: 1px 8px; } "
        "QPushButton:hover { background: #0284C7; color: #FFFFFF; }"
    )
    def _on_open_output_folder():
        out_f = (
            gui.final_output_folder_edit.text().strip()
            if hasattr(gui, "final_output_folder_edit") and gui.final_output_folder_edit.text().strip()
            else os.path.join(str(getattr(gui, "workspace_root", os.getcwd())), "output")
        )
        os.makedirs(out_f, exist_ok=True)
        if hasattr(gui, "open_folder") and callable(gui.open_folder):
            gui.open_folder(out_f)
        else:
            try:
                os.startfile(out_f)
            except Exception:
                import subprocess
                subprocess.Popen(["explorer", out_f])
    btn_open_folder.clicked.connect(_on_open_output_folder)
    setup_row.addWidget(btn_open_folder)
    qc_layout.addLayout(setup_row)

    # Hàng 2: Nút chạy hàng đợi (1 luồng tuần tự)
    gui._queue_run_btn = QPushButton("▶ CHẠY HÀNG ĐỢI (0 video)")
    gui._queue_run_btn.setFixedHeight(32)
    gui._queue_run_btn.setCursor(Qt.PointingHandCursor)
    gui._queue_run_btn.setStyleSheet(
        "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF8A00, stop:1 #FF5500); "
        "color: #FFFFFF; font-weight: 800; font-size: 11px; border-radius: 5px; border: none; } "
        "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFA033, stop:1 #FF6E1A); } "
        "QPushButton:disabled { background: #262E3D; color: #64748B; }"
    )
    qc_layout.addWidget(gui._queue_run_btn)
    layout.addWidget(queue_card)

    def _set_voice_for_paths(paths, voice_name="", label=""):
        if not hasattr(gui, "_video_voice_configs"):
            gui._video_voice_configs = {}
        for p in paths:
            norm_p = os.path.normpath(p) if p else ""
            if norm_p:
                gui._video_voice_configs[norm_p] = {
                    "voice_mode": "single",
                    "voice_name": voice_name,
                    "label": label or "1 Giọng",
                }
        _render_media_pool()

    def _set_ocr_for_paths(paths, rect_tuple):
        if not hasattr(gui, "_video_ocr_rects"):
            gui._video_ocr_rects = {}
        for p in paths:
            norm_p = os.path.normpath(p) if p else ""
            if norm_p:
                gui._video_ocr_rects[norm_p] = rect_tuple
        cur_p = getattr(gui, "_current_video_path", "")
        if cur_p and os.path.normpath(cur_p) in [os.path.normpath(x) for x in paths if x]:
            overlay = getattr(gui, "ocr_region_overlay", None)
            if overlay and hasattr(overlay, "set_norm_rect"):
                overlay.set_norm_rect(*rect_tuple)
            if hasattr(gui, "_sync_ocr_overlay"):
                gui._sync_ocr_overlay()
            ps = getattr(gui, "current_project_state", None)
            if ps and hasattr(ps, "settings"):
                ps.settings["ocr_subtitle_rect"] = f"{rect_tuple[0]:.4f},{rect_tuple[1]:.4f},{rect_tuple[2]:.4f},{rect_tuple[3]:.4f}"
        _render_media_pool()

    def _on_group_ocr_click():
        sel = list(getattr(gui, "_selected_media_paths", set()))
        if not sel:
            QMessageBox.information(gui, "Cài đặt chung", "Vui lòng tích chọn ít nhất 1 video để cài đặt.")
            return
        m = QMenu(btn_group_ocr)
        m.setStyleSheet(
            "QMenu { background: #161B24; color: #E5E7EB; border: 1px solid #2E384D; padding: 4px; font-size: 11px; } "
            "QMenu::item:selected { background: #FF8A00; color: #fff; }"
        )
        act_cur = m.addAction("💾 Áp dụng khung OCR hiện tại trên màn hình")
        m.addSeparator()
        act_b = m.addAction("👇 OCR Dưới đáy (65%)")
        act_m = m.addAction("👉 OCR Ở giữa màn hình (40%)")
        act_t = m.addAction("👆 OCR Trên đỉnh màn hình (10%)")
        pos = btn_group_ocr.mapToGlobal(QPoint(0, btn_group_ocr.height()))
        chosen = m.exec(pos)
        if chosen == act_cur:
            overlay = getattr(gui, "ocr_region_overlay", None)
            if overlay and hasattr(overlay, "get_norm_rect"):
                _set_ocr_for_paths(sel, overlay.get_norm_rect())
        elif chosen == act_b:
            _set_ocr_for_paths(sel, (0.05, 0.65, 0.90, 0.16))
        elif chosen == act_m:
            _set_ocr_for_paths(sel, (0.05, 0.40, 0.90, 0.16))
        elif chosen == act_t:
            _set_ocr_for_paths(sel, (0.05, 0.10, 0.90, 0.16))

    btn_group_ocr.clicked.connect(_on_group_ocr_click)

    def _on_select_all_toggled(checked):
        if not hasattr(gui, "_selected_media_paths"):
            gui._selected_media_paths = set()
        pool = getattr(gui, "project_media_pool", [])
        if checked:
            for it in pool:
                p = it.get("path")
                if p:
                    gui._selected_media_paths.add(os.path.normpath(p))
        else:
            gui._selected_media_paths.clear()
        _update_queue_ui_state()
        _render_media_pool()

    gui._queue_select_all_cb.toggled.connect(_on_select_all_toggled)

    def _on_queue_run_click():
        if getattr(gui.queue_controller, "is_running", False):
            gui.queue_controller.stop_queue()
        else:
            pool = getattr(gui, "project_media_pool", [])
            selected = [it for it in pool if os.path.normpath(it.get("path", "")) in gui._selected_media_paths]
            if not selected:
                QMessageBox.warning(gui, "Hàng đợi", "Vui lòng tích chọn ít nhất 1 video để chạy hàng đợi.")
                return

            # 1. Xác định khung che chữ Trung từ vùng OCR / Blur Region đã vẽ
            blur_rect = None
            cur_p = getattr(gui, "_current_video_path", "")
            if cur_p:
                blur_rect = getattr(gui, "_video_ocr_rects", {}).get(os.path.normpath(cur_p))
            if not blur_rect and hasattr(gui, "video_view") and hasattr(gui.video_view, "get_blur_region_normalized"):
                try:
                    norm_blur = gui.video_view.get_blur_region_normalized()
                    if isinstance(norm_blur, dict):
                        blur_rect = (
                            float(norm_blur.get("x", 0.0)),
                            float(norm_blur.get("y", 0.0)),
                            float(norm_blur.get("width", 0.0)),
                            float(norm_blur.get("height", 0.0)),
                        )
                except Exception:
                    blur_rect = None

            if not blur_rect:
                rect_env = os.getenv("OCR_SUBTITLE_RECT", "").strip()
                if rect_env:
                    try:
                        parts = [float(p) for p in rect_env.split(",")]
                        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
                            blur_rect = (parts[0], parts[1], parts[2], parts[3])
                    except Exception:
                        blur_rect = None

            # 2. Mở bảng Cài đặt lồng tiếng (1 giọng) & Tạo video tự động (đầy đủ các giọng)
            from ui.dialogs.single_voice_setup_dialog import SingleVoiceSetupDialog
            from PySide6.QtWidgets import QDialog
            selected_paths = [it.get("path") for it in selected if it.get("path")]
            init_orig = int(gui.audio_a1_volume_slider.value()) if hasattr(gui, "audio_a1_volume_slider") else 50
            init_tts = int(gui.audio_a2_volume_slider.value()) if hasattr(gui, "audio_a2_volume_slider") else 100
            last_voice_id = getattr(gui, "_last_single_voice_id", "adam1")

            dialog = SingleVoiceSetupDialog(
                gui,
                video_path=selected_paths[0] if selected_paths else "",
                video_paths=selected_paths,
                initial_orig_volume=init_orig,
                initial_tts_volume=init_tts,
                blur_rect=blur_rect,
                workspace_root=str(getattr(gui, "workspace_root", os.getcwd())),
                initial_voice_id=last_voice_id,
            )
            if dialog.exec() != QDialog.Accepted:
                return

            selected_voice = dialog.get_selected_voice()
            audio_mix = dialog.get_audio_mix_settings()
            enable_blur = dialog.is_blur_mask_enabled()
            burn_subs = dialog.is_burn_subtitles_enabled()
            sub_cfg = dialog.get_subtitle_config()
            brand_logo = dialog.get_brand_logo_settings()
            watermark = dialog.get_watermark_settings()
            is_individual = (selected_voice.get("id") == "keep_individual")
            if not is_individual:
                gui._last_single_voice_id = selected_voice.get("id", "adam1")

            # 3. Kiểm tra bản quyền VIP nếu chọn giọng VieNeu
            v_id = selected_voice.get("id", "")
            if not is_individual and ("vieneu" in selected_voice.get("provider", "") or "vieneu" in v_id):
                from app.services.license_service import LicenseService
                lic = LicenseService(str(getattr(gui, "workspace_root", os.getcwd())))
                is_valid, msg = lic.is_license_valid()
                if not is_valid:
                    QMessageBox.warning(
                        gui,
                        "Yêu cầu kích hoạt bản quyền VIP",
                        f"Giọng {selected_voice.get('name')} yêu cầu kích hoạt bản quyền VIP TankVideo!\n\n"
                        f"Trạng thái: {msg}\n\n"
                        "Vui lòng nhấn vào nút 'Bản quyền' trên thanh tiêu đề để đăng nhập và kích hoạt.",
                    )
                    getattr(gui, "open_license_dialog", lambda: None)()
                    return

            # 4. Cập nhật nhãn giọng đọc trên thẻ video: CHỈ CẬP NHẬT KHI KHÔNG CHỌN GIỮ GIỌNG RIÊNG
            if not is_individual:
                v_label = selected_voice.get("name", "1 Giọng").split("(")[0].replace("👩 ", "").replace("👨 ", "").replace("👑 ", "").strip()
                for it in selected:
                    p = it.get("path")
                    if p:
                        norm_p = os.path.normpath(p)
                        gui._video_voice_configs[norm_p] = {
                            "voice_mode": "single",
                            "voice_name": selected_voice.get("id", ""),
                            "label": v_label,
                        }
                _render_media_pool()

            # 5. Khởi động hàng đợi 1 giọng nhanh
            setup_config = {
                "selected_voice": selected_voice,
                "audio_mix": audio_mix,
                "enable_blur": enable_blur,
                "default_blur_rect": blur_rect,
                "burn_subs": burn_subs,
                "sub_cfg": sub_cfg,
                "brand_logo": brand_logo,
                "watermark": watermark,
                "use_individual_voices": is_individual,
            }
            gui.queue_controller.start_single_voice_queue(selected, setup_config)

        _update_queue_ui_state()

    gui._queue_run_btn.clicked.connect(_on_queue_run_click)

    def _update_queue_ui_state():
        pool = getattr(gui, "project_media_pool", [])
        total_count = len(pool)
        selected_count = len(getattr(gui, "_selected_media_paths", set()))
        if hasattr(gui, "_queue_select_all_cb"):
            gui._queue_select_all_cb.blockSignals(True)
            gui._queue_select_all_cb.setText(f"Tất cả ({selected_count}/{total_count})")
            gui._queue_select_all_cb.setChecked(selected_count == total_count and total_count > 0)
            gui._queue_select_all_cb.blockSignals(False)

        if hasattr(gui, "_queue_run_btn"):
            if getattr(gui.queue_controller, "is_running", False):
                curr = getattr(gui.queue_controller, "current_index", 0) + 1
                q_len = len(getattr(gui.queue_controller, "queue", []))
                # Lấy phần trăm tiến độ của video hiện tại
                pct = 0
                if hasattr(gui.queue_controller, "queue") and 0 <= gui.queue_controller.current_index < len(gui.queue_controller.queue):
                    cur_item = gui.queue_controller.queue[gui.queue_controller.current_index]
                    cur_p = os.path.normpath(cur_item.get("path", ""))
                    pct = getattr(gui, "_video_queue_percent", {}).get(cur_p, 0)
                pct_str = f" - {pct}%" if pct > 0 else ""
                gui._queue_run_btn.setText(f"⏹ DỪNG HÀNG ĐỢI ({curr}/{q_len}{pct_str})")
                gui._queue_run_btn.setStyleSheet(
                    "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #EF4444, stop:1 #B91C1C); "
                    "color: #FFFFFF; font-weight: 800; font-size: 11px; border-radius: 5px; border: none; } "
                    "QPushButton:hover { background: #DC2626; }"
                )
                gui._queue_run_btn.setEnabled(True)
            else:
                gui._queue_run_btn.setText(f"▶ CHẠY HÀNG ĐỢI ({selected_count} video)")
                gui._queue_run_btn.setStyleSheet(
                    "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FF8A00, stop:1 #FF5500); "
                    "color: #FFFFFF; font-weight: 800; font-size: 11px; border-radius: 5px; border: none; } "
                    "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #FFA033, stop:1 #FF6E1A); } "
                    "QPushButton:disabled { background: #262E3D; color: #64748B; }"
                )
                gui._queue_run_btn.setEnabled(selected_count > 0)

    try:
        gui.queue_controller.status_changed.connect(lambda _p, _s: _render_media_pool())
        gui.queue_controller.queue_progress.connect(lambda _c, _t: _update_queue_ui_state())
        gui.queue_controller.queue_finished.connect(lambda _ok, _m: _update_queue_ui_state())
    except Exception:
        pass

    # ═══════════════════════════════════════════════════════════════════
    # 3. Filter Row: Tất cả | Video | Ảnh | Âm thanh
    # ═══════════════════════════════════════════════════════════════════
    filter_row = QHBoxLayout()
    filter_row.setSpacing(4)
    current_filter = ["all"]
    filter_btns = {}
    f_active_style = "QPushButton { background: #2A1E14; color: #FF8A00; border: 1px solid #FF8A00; border-radius: 4px; font-size: 10px; font-weight: 700; padding: 2px 6px; }"
    f_inactive_style = "QPushButton { background: #161A22; color: #8C93A0; border: 1px solid #2E323A; border-radius: 4px; font-size: 10px; font-weight: 500; padding: 2px 6px; } QPushButton:hover { color: #E5E7EB; border-color: #3F444E; }"

    def _set_active_filter(active_key):
        current_filter[0] = active_key
        for k, b in filter_btns.items():
            b.setStyleSheet(f_active_style if k == active_key else f_inactive_style)
        _render_media_pool()

    for f_key, f_text in [("all", "Tất cả"), ("video", "Video"), ("image", "Ảnh"), ("audio", "Âm thanh")]:
        f_btn = QPushButton(f_text)
        f_btn.setFixedHeight(22)
        f_btn.setCursor(Qt.PointingHandCursor)
        f_btn.setStyleSheet(f_active_style if f_key == "all" else f_inactive_style)
        f_btn.clicked.connect(lambda _c=False, fk=f_key: _set_active_filter(fk))
        filter_btns[f_key] = f_btn
        filter_row.addWidget(f_btn)
    filter_row.addStretch(1)
    layout.addLayout(filter_row)

    # ═══════════════════════════════════════════════════════════════════
    # 4. Danh sách video dạng List dọc (QScrollArea co giãn 100%, không bị cắt)
    # ═══════════════════════════════════════════════════════════════════
    scroll_pool = QScrollArea()
    scroll_pool.setWidgetResizable(True)
    scroll_pool.setFrameShape(QFrame.NoFrame)
    scroll_pool.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll_pool.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll_pool.setStyleSheet("QScrollArea { background: transparent; border: none; }")

    pool_content = QWidget()
    pool_content.setStyleSheet("background: transparent;")
    pool_layout = QVBoxLayout(pool_content)
    pool_layout.setContentsMargins(0, 2, 0, 2)
    pool_layout.setSpacing(6)
    pool_layout.addStretch(1)
    scroll_pool.setWidget(pool_content)
    layout.addWidget(scroll_pool, 1)

    # Thẻ Drop Zone khi chưa có video nào
    drop_zone = QFrame()
    drop_zone.setStyleSheet(
        "QFrame { background: #0E121A; border: 2px dashed #2E384C; border-radius: 8px; min-height: 80px; }"
        "QFrame:hover { border-color: #FF8A00; background: #111620; }"
    )
    dz_layout = QVBoxLayout(drop_zone)
    dz_layout.setAlignment(Qt.AlignCenter)
    dz_layout.setSpacing(4)
    dz_icon = QLabel("🎬")
    dz_icon.setAlignment(Qt.AlignCenter)
    dz_icon.setStyleSheet("font-size: 24px; background: transparent; border: none;")
    dz_layout.addWidget(dz_icon)
    dz_txt = QLabel("Kéo thả video vào đây\nhoặc bấm '+ Nhập tệp'")
    dz_txt.setAlignment(Qt.AlignCenter)
    dz_txt.setStyleSheet("color: #64748B; font-size: 10px; font-weight: 600; background: transparent; border: none;")
    dz_layout.addWidget(dz_txt)
    pool_layout.insertWidget(0, drop_zone)

    # ═══════════════════════════════════════════════════════════════════
    # 5. Render Media Pool Items
    # ═══════════════════════════════════════════════════════════════════
    gui._media_card_widgets = {}

    def _remove_media_item(item_path):
        if hasattr(gui, "project_media_pool"):
            gui.project_media_pool = [it for it in gui.project_media_pool if os.path.normpath(it.get("path", "")) != os.path.normpath(item_path)]
        if hasattr(gui, "_selected_media_paths"):
            gui._selected_media_paths.discard(os.path.normpath(item_path))
        _render_media_pool()

    def _open_file_folder(file_path, select_file=True):
        import subprocess as sp
        abs_p = os.path.abspath(file_path) if file_path else ""
        if abs_p and os.path.isfile(abs_p) and select_file:
            if os.name == "nt":
                sp.Popen(f'explorer /select,"{os.path.normpath(abs_p)}"')
                return
        folder = abs_p if os.path.isdir(abs_p) else os.path.dirname(abs_p)
        if folder and os.path.isdir(folder):
            if os.name == "nt":
                os.startfile(folder)
            else:
                sp.Popen(["xdg-open", folder])

    def _sync_subtitles_for_video(norm_item, item_path):
        """Đồng bộ phụ đề tiếng Việt đã dịch của video này vào Cột Phụ đề và Timeline."""
        cues = getattr(gui, "_video_translated_cues", {}).get(norm_item)
        if not cues:
            out_folder = (
                gui.final_output_folder_edit.text().strip()
                if hasattr(gui, "final_output_folder_edit") and gui.final_output_folder_edit.text().strip()
                else os.path.join(str(getattr(gui, "workspace_root", os.getcwd())), "output")
            )
            base_name = os.path.splitext(os.path.basename(item_path))[0]
            candidate_srt = os.path.join(out_folder, f"{base_name}_final_vi.srt")
            if not os.path.isfile(candidate_srt):
                candidate_srt = os.path.join(out_folder, f"{base_name}.srt")
            if os.path.isfile(candidate_srt):
                try:
                    from app.translation.srt_utils import parse_srt
                    with open(candidate_srt, "r", encoding="utf-8") as sf:
                        cues = parse_srt(sf.read())
                    if cues:
                        if not hasattr(gui, "_video_translated_cues"):
                            gui._video_translated_cues = {}
                        gui._video_translated_cues[norm_item] = cues
                except Exception:
                    cues = None

        if cues and isinstance(cues, list):
            trans_segs = []
            base_segs = []
            for c in cues:
                if not isinstance(c, dict):
                    continue
                s_s = float(c.get("start", 0.0))
                e_s = float(c.get("end", 0.0))
                raw_txt = str(c.get("text", "")).strip()
                t_txt = str(c.get("translated_text", "") or c.get("translated", "")).strip()
                o_txt = str(c.get("source_text", "") or c.get("original", "")).strip()

                has_cjk_raw = bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", raw_txt)) if raw_txt else False
                if not t_txt and raw_txt and not has_cjk_raw:
                    t_txt = raw_txt
                if not o_txt and raw_txt and has_cjk_raw:
                    o_txt = raw_txt

                trans_segs.append({
                    "start": s_s,
                    "end": e_s,
                    "text": t_txt or raw_txt,
                    "translated": t_txt,
                    "translated_text": t_txt,
                    "original": o_txt,
                    "source_text": o_txt,
                })
                base_segs.append({
                    "start": s_s,
                    "end": e_s,
                    "text": o_txt,
                    "original": o_txt,
                    "source_text": o_txt,
                })
            gui.current_translated_segments = trans_segs
            if base_segs:
                gui.current_segments = base_segs
            if hasattr(gui, "timeline") and hasattr(gui.timeline, "set_segments"):
                gui.timeline.set_segments(trans_segs)
            if hasattr(gui, "subtitle_list_view") and hasattr(gui.subtitle_list_view, "refresh_segments"):
                gui.subtitle_list_view.refresh_segments()

    def _build_media_item_card(item_data, timeline_video_paths):
        item_path = item_data.get("path", "")
        norm_item = os.path.normpath(item_path) if item_path else ""
        item_name = item_data.get("name", "") or os.path.basename(item_path)
        cur_active = getattr(gui, "_current_video_path", "")
        is_active = bool(cur_active and item_path and os.path.normpath(cur_active) == norm_item)
        is_on_timeline = norm_item in timeline_video_paths if norm_item else False

        card_w = QFrame()
        card_w.setFixedHeight(66)
        card_w.setCursor(Qt.PointingHandCursor)

        if is_active:
            border = "#FF8A00"
            bg = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1F2838, stop:1 #141A24)"
        else:
            border = "#283446"
            bg = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #141820, stop:1 #0F1318)"

        card_w.setStyleSheet(
            f"QFrame {{ background: {bg}; border: {'2px solid #FF8A00' if is_active else f'1px solid {border}'}; border-radius: 7px; }} "
            f"QFrame:hover {{ border-color: #FFA033; }}"
        )
        card_w.setToolTip(f"Tệp: {item_name}\nĐường dẫn: {item_path}\nNhấp chuột để mở chỉnh sửa; nhấp đúp để nối vào timeline.")

        h_layout = QHBoxLayout(card_w)
        h_layout.setContentsMargins(6, 6, 6, 6)
        h_layout.setSpacing(6)

        # Checkbox tích chọn video vào hàng đợi
        cb_select = QCheckBox()
        cb_select.setCursor(Qt.PointingHandCursor)
        is_selected = norm_item in getattr(gui, "_selected_media_paths", set())
        cb_select.setChecked(is_selected)
        cb_select.setStyleSheet(
            "QCheckBox::indicator { width: 14px; height: 14px; border-radius: 3px; border: 1px solid #475569; background: #0B0E14; } "
            "QCheckBox::indicator:checked { background: #FF8A00; border-color: #FF8A00; }"
        )
        def _on_item_check_toggled(checked):
            if not hasattr(gui, "_selected_media_paths"):
                gui._selected_media_paths = set()
            if checked:
                gui._selected_media_paths.add(norm_item)
            else:
                gui._selected_media_paths.discard(norm_item)
            _update_queue_ui_state()

        cb_select.toggled.connect(_on_item_check_toggled)
        h_layout.addWidget(cb_select, 0, Qt.AlignVCenter)

        # Thumbnail với huy hiệu thời lượng
        thumb_container = QFrame()
        thumb_container.setFixedSize(48, 48)
        thumb_container.setStyleSheet("background: #0B0E14; border-radius: 4px; border: none;")
        t_layout = QGridLayout(thumb_container)
        t_layout.setContentsMargins(0, 0, 0, 0)

        img_label = QLabel()
        img_label.setAlignment(Qt.AlignCenter)
        img_label.setScaledContents(True)
        img_label.setStyleSheet("background: transparent; border-radius: 4px;")
        thumb_p = item_data.get("thumb_path", "")
        if thumb_p and os.path.exists(thumb_p):
            pm = QPixmap(thumb_p)
            if not pm.isNull():
                img_label.setPixmap(pm)
            else:
                img_label.setText("🎬")
                img_label.setStyleSheet("font-size: 18px; color: #FFA033; background: transparent;")
        else:
            img_label.setText("🎬")
            img_label.setStyleSheet("font-size: 18px; color: #FFA033; background: transparent;")
        t_layout.addWidget(img_label, 0, 0)

        dur_str = item_data.get("duration_str", "")
        if dur_str:
            dur_badge = QLabel(dur_str)
            dur_badge.setStyleSheet(
                "background: rgba(0, 0, 0, 0.7); color: #E2E8F0; font-size: 8px; font-weight: 700; "
                "border-radius: 2px; padding: 1px 3px; border: none;"
            )
            t_layout.addWidget(dur_badge, 0, 0, Qt.AlignRight | Qt.AlignBottom)

        h_layout.addWidget(thumb_container)

        # Cột thông tin ở giữa
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(3)

        # Hàng 1: Tên video + nhãn trạng thái hàng đợi / đang sửa / timeline
        name_row = QHBoxLayout()
        name_row.setSpacing(4)
        disp_name = item_name if len(item_name) <= 18 else item_name[:16] + "…"
        name_lbl = QLabel(disp_name)
        name_lbl.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 700; border: none;")
        name_row.addWidget(name_lbl)

        q_stat = getattr(gui, "_video_queue_status", {}).get(norm_item, "idle")
        if q_stat == "running":
            pct = getattr(gui, "_video_queue_percent", {}).get(norm_item, 0)
            pct_str = f" ({pct}%)" if pct > 0 else ""
            q_badge = QLabel(f"⏳ Đang tạo{pct_str}...")
            q_badge.setStyleSheet(
                "background: #FF8A00; color: #FFFFFF; font-size: 8px; font-weight: 800; "
                "border-radius: 2px; padding: 0 4px; border: none;"
            )
            name_row.addWidget(q_badge)
        elif q_stat == "waiting":
            q_badge = QLabel("⏱ Hàng đợi")
            q_badge.setStyleSheet(
                "background: #0284C7; color: #FFFFFF; font-size: 8px; font-weight: 700; "
                "border-radius: 2px; padding: 0 4px; border: none;"
            )
            name_row.addWidget(q_badge)
        elif q_stat == "done":
            dur = getattr(gui, "_video_durations", {}).get(norm_item)
            dur_text = ""
            dur_tip = "Đã xuất video hoàn tất"
            if dur and dur > 0:
                s_int = int(round(dur))
                if s_int < 60:
                    dur_text = f" ({s_int}s)"
                    dur_tip = f"Hoàn thành trong {s_int} giây ({dur:.1f}s)"
                else:
                    m = s_int // 60
                    rem = s_int % 60
                    dur_text = f" ({m}m{rem:02d}s)"
                    dur_tip = f"Hoàn thành trong {m} phút {rem} giây ({dur:.1f}s)"

            q_badge = QLabel(f"✓ Hoàn thành{dur_text}")
            q_badge.setStyleSheet(
                "background: #059669; color: #FFFFFF; font-size: 8px; font-weight: 700; "
                "border-radius: 2px; padding: 0 4px; border: none;"
            )
            q_badge.setToolTip(dur_tip)
            name_row.addWidget(q_badge)
        elif q_stat == "error":
            q_badge = QLabel("✕ Lỗi")
            q_badge.setStyleSheet(
                "background: #DC2626; color: #FFFFFF; font-size: 8px; font-weight: 700; "
                "border-radius: 2px; padding: 0 4px; border: none;"
            )
            name_row.addWidget(q_badge)
        elif is_active:
            active_badge = QLabel("Đang sửa")
            active_badge.setStyleSheet(
                "background: #FF8A00; color: #fff; font-size: 8px; font-weight: 800; "
                "border-radius: 2px; padding: 0 4px; border: none;"
            )
            name_row.addWidget(active_badge)
        elif is_on_timeline:
            tl_badge = QLabel("Trên timeline")
            tl_badge.setStyleSheet(
                "background: #2563EB; color: #fff; font-size: 8px; font-weight: 700; "
                "border-radius: 2px; padding: 0 4px; border: none;"
            )
            name_row.addWidget(tl_badge)

        name_row.addStretch(1)
        info_layout.addLayout(name_row)

        # Hàng 2: Huy hiệu Cài đặt riêng (Giọng đọc & Khung OCR)
        status_row = QHBoxLayout()
        status_row.setSpacing(4)

        # 1. Huy hiệu Giọng đọc (Luôn là 1 Giọng)
        v_cfg = getattr(gui, "_video_voice_configs", {}).get(norm_item, {})
        v_label = v_cfg.get("label", "") or getattr(gui, "_queue_selected_voice_label", "Ngọc Huyền")
        v_text = f"👤 {v_label}"
        v_col = "#38BDF8"
        v_tip = f"Giọng đọc: {v_label}\nNhấp để đổi giọng riêng cho video này"

        voice_badge = QLabel(v_text)
        voice_badge.setCursor(Qt.PointingHandCursor)
        voice_badge.setStyleSheet(
            f"background: #141A24; color: {v_col}; font-size: 8px; font-weight: 700; "
            f"border: 1px solid {v_col}66; border-radius: 2px; padding: 0 4px;"
        )
        voice_badge.setToolTip(v_tip)

        def _on_voice_badge_click(ev):
            from ui.dialogs.single_voice_setup_dialog import SingleVoiceSetupDialog
            from PySide6.QtWidgets import QDialog
            v_curr = getattr(gui, "_video_voice_configs", {}).get(norm_item, {}).get("voice_name", "")
            init_orig = int(gui.audio_a1_volume_slider.value()) if hasattr(gui, "audio_a1_volume_slider") else 50
            init_tts = int(gui.audio_a2_volume_slider.value()) if hasattr(gui, "audio_a2_volume_slider") else 100
            dlg = SingleVoiceSetupDialog(
                gui,
                video_path=item_path,
                blur_rect=getattr(gui, "_video_ocr_rects", {}).get(norm_item),
                initial_orig_volume=init_orig,
                initial_tts_volume=init_tts,
                workspace_root=str(getattr(gui, "workspace_root", os.getcwd())),
                initial_voice_id=v_curr or getattr(gui, "_last_single_voice_id", "adam1"),
            )
            if dlg.exec() == QDialog.Accepted:
                v_sel = dlg.get_selected_voice()
                v_short = v_sel.get("name", "").split("(")[0].replace("👩 ", "").replace("👨 ", "").replace("👑 ", "").strip()
                _set_voice_for_paths([item_path], v_sel.get("id", ""), v_short)
                gui._last_single_voice_id = v_sel.get("id", "adam1")

        voice_badge.mousePressEvent = _on_voice_badge_click
        status_row.addWidget(voice_badge)

        # 2. Huy hiệu OCR phụ đề (Setup riêng cho video này)
        cur_ocr = getattr(gui, "_video_ocr_rects", {}).get(norm_item)
        if not cur_ocr and is_active:
            overlay = getattr(gui, "ocr_region_overlay", None)
            if overlay and hasattr(overlay, "get_norm_rect"):
                cur_ocr = overlay.get_norm_rect()

        def _format_ocr_badge_info(r):
            if not r or len(r) != 4:
                return ("OCR: Đáy (65%)", "#64748B", "Vùng nhận diện OCR: Mặc định dưới đáy\nNhấp để đổi vị trí nhanh")
            ry = r[1]
            y_pct = int(ry * 100)
            h_pct = int(r[3] * 100)
            if ry < 0.28:
                return (f"OCR: Trên ({y_pct}%)", "#06B6D4", f"Khung OCR: Trên đỉnh (y={y_pct}%, h={h_pct}%)\nNhấp để đổi nhanh")
            elif ry <= 0.55:
                return (f"OCR: Giữa ({y_pct}%)", "#A855F7", f"Khung OCR: Ở giữa (y={y_pct}%, h={h_pct}%)\nNhấp để đổi nhanh")
            else:
                return (f"OCR: Đáy ({y_pct}%)", "#38BDF8", f"Khung OCR: Dưới đáy (y={y_pct}%, h={h_pct}%)\nNhấp để đổi nhanh")

        b_txt, b_col, b_tip = _format_ocr_badge_info(cur_ocr)
        ocr_badge = QLabel(b_txt)
        ocr_badge.setCursor(Qt.PointingHandCursor)
        ocr_badge.setStyleSheet(
            f"background: #141A24; color: {b_col}; font-size: 8px; font-weight: 700; "
            f"border: 1px solid {b_col}66; border-radius: 2px; padding: 0 4px;"
        )
        ocr_badge.setToolTip(b_tip)

        def _on_ocr_badge_click(ev):
            b_menu = QMenu(ocr_badge)
            b_menu.setStyleSheet(
                "QMenu { background: #161B24; color: #E5E7EB; border: 1px solid #2E384D; padding: 4px; font-size: 11px; } "
                "QMenu::item:selected { background: #FF8A00; color: #fff; }"
            )
            act_save_curr = b_menu.addAction("💾 Ghi nhớ khung hiện tại cho video này")
            b_menu.addSeparator()
            act_b = b_menu.addAction("👇 OCR Dưới đáy (65%)")
            act_m = b_menu.addAction("👉 OCR Ở giữa màn hình (40%)")
            act_t = b_menu.addAction("👆 OCR Trên đỉnh màn hình (10%)")
            pos = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
            chosen = b_menu.exec(pos)
            if chosen == act_save_curr:
                overlay = getattr(gui, "ocr_region_overlay", None)
                if overlay and hasattr(overlay, "get_norm_rect"):
                    _set_ocr_for_paths([item_path], overlay.get_norm_rect())
            elif chosen == act_b:
                _set_ocr_for_paths([item_path], (0.05, 0.65, 0.90, 0.16))
            elif chosen == act_m:
                _set_ocr_for_paths([item_path], (0.05, 0.40, 0.90, 0.16))
            elif chosen == act_t:
                _set_ocr_for_paths([item_path], (0.05, 0.10, 0.90, 0.16))

        ocr_badge.mousePressEvent = _on_ocr_badge_click
        status_row.addWidget(ocr_badge)
        status_row.addStretch(1)

        info_layout.addLayout(status_row)
        h_layout.addLayout(info_layout, 1)

        # Cột nút thao tác bên phải: Nút xóa (✕) & Nút mở file video khi xong
        right_actions_layout = QVBoxLayout()
        right_actions_layout.setContentsMargins(0, 0, 0, 0)
        right_actions_layout.setSpacing(4)
        right_actions_layout.setAlignment(Qt.AlignTop | Qt.AlignRight)

        btn_del = QPushButton("✕")
        btn_del.setFixedSize(18, 18)
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.setStyleSheet(
            "QPushButton { background: transparent; color: #64748B; font-size: 10px; font-weight: 700; border: none; border-radius: 9px; } "
            "QPushButton:hover { background: #7F1D1D; color: #F87171; }"
        )
        btn_del.setToolTip("Xóa video này khỏi danh sách")
        btn_del.clicked.connect(lambda _c=False, p=item_path: _remove_media_item(p))
        right_actions_layout.addWidget(btn_del, 0, Qt.AlignRight)

        # Kiểm tra đường dẫn video hoàn thành
        out_target = getattr(gui, "_video_output_paths", {}).get(norm_item, "")
        if not out_target or not os.path.isfile(out_target):
            out_folder_test = (
                gui.final_output_folder_edit.text().strip()
                if hasattr(gui, "final_output_folder_edit") and gui.final_output_folder_edit.text().strip()
                else os.path.join(str(getattr(gui, "workspace_root", os.getcwd())), "output")
            )
            cand_p = os.path.join(out_folder_test, f"{os.path.splitext(os.path.basename(item_path))[0]}_final_vi.mp4")
            if os.path.isfile(cand_p):
                out_target = cand_p

        if q_stat == "done" or (out_target and os.path.isfile(out_target)):
            btn_open_done = QPushButton("📁 Mở")
            btn_open_done.setFixedHeight(22)
            btn_open_done.setCursor(Qt.PointingHandCursor)
            btn_open_done.setStyleSheet(
                "QPushButton { background: #064E3B; color: #34D399; font-size: 10px; font-weight: 700; "
                "border: 1px solid #059669; border-radius: 4px; padding: 1px 6px; } "
                "QPushButton:hover { background: #059669; color: #FFFFFF; border-color: #10B981; }"
            )
            btn_open_done.setToolTip("Mở thư mục và chọn video đã hoàn thành trong Windows Explorer")
            btn_open_done.clicked.connect(lambda _c=False, p=(out_target or item_path): _open_file_folder(p, select_file=True))
            right_actions_layout.addWidget(btn_open_done, 0, Qt.AlignRight)

        h_layout.addLayout(right_actions_layout)

        # Sự kiện Click & Double-click
        def _on_card_click(event):
            if event.button() == Qt.LeftButton:
                browse_video(gui, file_path=item_path)
                _sync_subtitles_for_video(norm_item, item_path)
                _render_media_pool()
            super(QFrame, card_w).mousePressEvent(event)

        def _on_card_dbl_click(event):
            if event.button() == Qt.LeftButton:
                append_video_to_timeline(gui, item_path)
                _sync_subtitles_for_video(norm_item, item_path)
                _render_media_pool()
            super(QFrame, card_w).mouseDoubleClickEvent(event)

        card_w.mousePressEvent = _on_card_click
        card_w.mouseDoubleClickEvent = _on_card_dbl_click

        # Menu chuột phải
        card_w.setContextMenuPolicy(Qt.CustomContextMenu)
        def _show_card_menu(pos):
            menu = QMenu(card_w)
            menu.setStyleSheet(
                "QMenu { background: #161B24; color: #E5E7EB; border: 1px solid #2E384D; padding: 4px; font-size: 11px; } "
                "QMenu::item:selected { background: #FF8A00; color: #fff; }"
            )
            act_edit = menu.addAction("✏️ Mở chỉnh sửa video này")
            act_add = menu.addAction("➕ Nối vào cuối timeline")
            menu.addSeparator()

            act_set_voice = menu.addAction("🎙️ Cài đặt lồng tiếng (1 giọng)...")

            ocr_menu = menu.addMenu("🎯 Đặt khung OCR phụ đề")
            act_save_curr = ocr_menu.addAction("💾 Ghi nhớ khung hiện tại cho video này")
            ocr_menu.addSeparator()
            act_ocr_bottom = ocr_menu.addAction("👇 Dưới đáy (65%)")
            act_ocr_mid = ocr_menu.addAction("👉 Ở giữa màn hình (40%)")
            act_ocr_top = ocr_menu.addAction("👆 Trên đỉnh màn hình (10%)")

            menu.addSeparator()
            act_open_out = None
            if out_target and os.path.isfile(out_target):
                act_open_out = menu.addAction("📁 Mở video đã xuất (Explorer)")
            act_open_dir = menu.addAction("📂 Mở thư mục video gốc")
            act_del = menu.addAction("🗑️ Xóa khỏi danh sách")

            action = menu.exec(card_w.mapToGlobal(pos))
            if action == act_edit:
                browse_video(gui, file_path=item_path)
                _render_media_pool()
            elif action == act_add:
                append_video_to_timeline(gui, item_path)
                _render_media_pool()
            elif action == act_set_voice:
                from ui.dialogs.single_voice_setup_dialog import SingleVoiceSetupDialog
                from PySide6.QtWidgets import QDialog
                v_curr = getattr(gui, "_video_voice_configs", {}).get(norm_item, {}).get("voice_name", "")
                init_orig = int(gui.audio_a1_volume_slider.value()) if hasattr(gui, "audio_a1_volume_slider") else 50
                init_tts = int(gui.audio_a2_volume_slider.value()) if hasattr(gui, "audio_a2_volume_slider") else 100
                dlg = SingleVoiceSetupDialog(
                    gui,
                    video_path=item_path,
                    blur_rect=getattr(gui, "_video_ocr_rects", {}).get(norm_item),
                    initial_orig_volume=init_orig,
                    initial_tts_volume=init_tts,
                    workspace_root=str(getattr(gui, "workspace_root", os.getcwd())),
                    initial_voice_id=v_curr or getattr(gui, "_last_single_voice_id", "adam1"),
                )
                if dlg.exec() == QDialog.Accepted:
                    v_sel = dlg.get_selected_voice()
                    v_short = v_sel.get("name", "").split("(")[0].replace("👩 ", "").replace("👨 ", "").replace("👑 ", "").strip()
                    _set_voice_for_paths([item_path], v_sel.get("id", ""), v_short)
                    gui._last_single_voice_id = v_sel.get("id", "adam1")
            elif action == act_save_curr:
                overlay = getattr(gui, "ocr_region_overlay", None)
                if overlay and hasattr(overlay, "get_norm_rect"):
                    _set_ocr_for_paths([item_path], overlay.get_norm_rect())
            elif action == act_ocr_bottom:
                _set_ocr_for_paths([item_path], (0.05, 0.65, 0.90, 0.16))
            elif action == act_ocr_mid:
                _set_ocr_for_paths([item_path], (0.05, 0.40, 0.90, 0.16))
            elif action == act_ocr_top:
                _set_ocr_for_paths([item_path], (0.05, 0.10, 0.90, 0.16))
            elif act_open_out and action == act_open_out:
                _open_file_folder(out_target, select_file=True)
            elif action == act_open_dir:
                _open_file_folder(item_path, select_file=True)
            elif action == act_del:
                _remove_media_item(item_path)

        card_w.customContextMenuRequested.connect(_show_card_menu)
        return card_w

    def _build_ai_generate_card():
        ai_box = QFrame()
        ai_box.setCursor(Qt.PointingHandCursor)
        ai_box.setFixedHeight(44)
        ai_box.setStyleSheet(
            "QFrame { background: #121722; border: 1px dashed #2E384C; border-radius: 6px; } "
            "QFrame:hover { background: #1C2433; border-color: #FF8A00; }"
        )
        ai_box.setToolTip("Nhấp để chuyển sang Quy trình TankVideo tự động")
        ai_layout = QHBoxLayout(ai_box)
        ai_layout.setContentsMargins(8, 4, 8, 4)
        ai_layout.setSpacing(6)
        ai_layout.setAlignment(Qt.AlignCenter)

        sparkle = QLabel("✨")
        sparkle.setStyleSheet("font-size: 16px; color: #FFB347; border: none; background: transparent;")
        ai_layout.addWidget(sparkle)

        ai_txt = QLabel("Tạo video bằng AI tự động")
        ai_txt.setStyleSheet("color: #94A3B8; font-size: 10px; font-weight: 700; border: none; background: transparent;")
        ai_layout.addWidget(ai_txt)

        def _on_ai_click(event):
            if hasattr(gui, "left_master_stack"):
                gui.left_master_stack.setCurrentIndex(1)
            elif hasattr(gui, "workflow_shell"):
                gui.workflow_shell.show()
            if hasattr(gui, "_select_sidebar_key"):
                gui._select_sidebar_key("workflow")
        ai_box.mousePressEvent = _on_ai_click
        return ai_box

    def _render_media_pool():
        thumb_dir = os.path.join(workspace_root(), "temp", "launcher_thumbs")
        os.makedirs(thumb_dir, exist_ok=True)

        if not hasattr(gui, "project_media_pool"):
            gui.project_media_pool = []

        cur_v = getattr(gui, "_current_video_path", "")
        if cur_v and os.path.exists(cur_v):
            if not any(os.path.normpath(it.get("path", "")) == os.path.normpath(cur_v) for it in gui.project_media_pool):
                try:
                    dur_s, th = probe_video_duration_and_thumb(cur_v, thumb_dir)
                except Exception:
                    dur_s, th = 0.0, ""
                total_s = int(dur_s)
                gui.project_media_pool.append({
                    "id": str(int(time.time() * 1000)),
                    "path": cur_v,
                    "name": os.path.basename(cur_v),
                    "duration": dur_s,
                    "duration_str": f"{total_s // 60:02d}:{total_s % 60:02d}",
                    "thumb_path": th,
                })

        if not hasattr(gui, "_seen_media_paths"):
            gui._seen_media_paths = set()
        if not hasattr(gui, "_selected_media_paths"):
            gui._selected_media_paths = set()
        for it in gui.project_media_pool:
            p = os.path.normpath(it.get("path", ""))
            if p and p not in gui._seen_media_paths:
                gui._seen_media_paths.add(p)
                gui._selected_media_paths.add(p)

        timeline_video_paths = set()
        try:
            tl = getattr(gui, "timeline", None)
            if tl and hasattr(tl, "_timeline") and tl._timeline:
                for track in tl._timeline.tracks:
                    if str(getattr(track, "name", "")).startswith("V1") or getattr(track, "type", None) == LayerType.VIDEO:
                        for layer in getattr(track, "layers", []):
                            src = getattr(layer, "source", "")
                            if src:
                                timeline_video_paths.add(os.path.normpath(src))
        except Exception:
            pass

        for wid, widget in list(gui._media_card_widgets.items()):
            pool_layout.removeWidget(widget)
            widget.deleteLater()
        gui._media_card_widgets.clear()

        for i in range(pool_layout.count() - 1, -1, -1):
            item = pool_layout.itemAt(i)
            w = item.widget() if item else None
            if w and w != drop_zone and w not in gui._media_card_widgets.values():
                pool_layout.removeWidget(w)
                w.deleteLater()

        fk = current_filter[0]
        pool = gui.project_media_pool
        visible_count = 0
        for itm in pool:
            if fk not in ("all", itm.get("type", "video")):
                continue
            card_w = _build_media_item_card(itm, timeline_video_paths)
            card_key = itm.get("path", "") or itm.get("id", "")
            gui._media_card_widgets[card_key] = card_w
            pool_layout.insertWidget(pool_layout.count() - 1, card_w)
            visible_count += 1

        ai_card = _build_ai_generate_card()
        pool_layout.insertWidget(pool_layout.count() - 1, ai_card)

        total_items = len(pool)
        gui._batch_count_badge.setText(f"{total_items} tệp")
        drop_zone.setVisible(total_items == 0)
        _update_queue_ui_state()

    gui._refresh_media_pool_ui = _render_media_pool
    gui.video_path_edit.textChanged.connect(lambda _t: _render_media_pool())
    _render_media_pool()

    return card



def build_start_group(gui, left_layout):
    _build_hidden_status_widgets(gui)

    gui.video_path_edit = QLineEdit()
    gui.video_path_edit.setPlaceholderText("Chọn video cần xử lý...")
    gui.video_path_edit.hide()

    gui.final_output_folder_edit = QLineEdit(os.path.join(gui.workspace_root, "output"))
    gui.final_output_folder_edit.setPlaceholderText("Thư mục lưu video kết quả...")
    gui.final_output_folder_edit.hide()

    gui.run_all_btn = QToolButton()
    gui.run_all_btn.setObjectName("mainActionBtn")
    gui.run_all_btn.setPopupMode(QToolButton.MenuButtonPopup)
    gui._generate_full_action = QAction("Tạo toàn bộ quy trình", gui.run_all_btn)
    gui._generate_full_action.triggered.connect(gui.run_all_pipeline)
    gui.run_all_btn.setDefaultAction(gui._generate_full_action)
    gui._generate_menu = None

    gui.export_btn = QPushButton("Xuất video")
    gui.export_btn.setObjectName("mainActionBtn")
    gui.export_btn.clicked.connect(gui.export_final_video)

    gui.preview_5s_btn = QPushButton("Xem nhanh (5s)")
    gui.preview_5s_btn.clicked.connect(gui.preview_five_seconds)
    gui.preview_frame_btn = QPushButton("Xem trước khung hình lớn")
    gui.preview_frame_btn.clicked.connect(gui.preview_exact_frame)
    gui.open_output_btn = QPushButton("Mở thư mục kết quả")
    gui.open_output_btn.clicked.connect(lambda: gui.open_folder(gui.final_output_folder_edit.text()))

    gui.stabilize_button(gui.run_all_btn, min_width=240)
    gui.stabilize_button(gui.export_btn, min_width=180)

    workflow_shell, workflow_shell_layout = _section_card()
    workflow_shell.setStyleSheet(
        "QFrame#statusCard { background-color: #141820; border: 1px solid #2E323A; border-radius: 8px; }"
    )
    workflow_shell_layout.setSpacing(10)
    gui.workflow_shell = workflow_shell

    workflow_header_layout = QHBoxLayout()
    workflow_icon = QLabel("⚡")
    workflow_icon.setStyleSheet("font-size: 13px; color: #ff9d42;")
    workflow_header_layout.addWidget(workflow_icon)

    workflow_title = QLabel("QUY TRÌNH TANKVIDEO")
    workflow_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #ff9d42; letter-spacing: 0.5px;")
    workflow_header_layout.addWidget(workflow_title)
    workflow_header_layout.addStretch()
    workflow_shell_layout.addLayout(workflow_header_layout)

    # Generation milestones remain visible while users work through the
    # configuration pages below.
    gui.workflow_stage_badges = {}
    # Keep the label widgets too: the Translate label is updated with the
    # provider that actually completed the most recent translation.
    gui.workflow_stage_labels = {}
    stage_box = QFrame()
    stage_box.setObjectName("statusCard")
    stage_box.setStyleSheet(
        "QFrame#statusCard { background-color: #12151d; border: 1px solid #232938; border-radius: 8px; }"
    )
    stage_layout = QVBoxLayout(stage_box)
    stage_layout.setContentsMargins(8, 6, 8, 6)
    stage_layout.setSpacing(3)

    stage_tab_map = {
        "prepare": 0,    # media
        "transcript": 0, # media
        "translate": 2,  # language
        "tts": 3,        # voice
        "export": 5,     # advanced
    }

    for key, title in (("prepare", "1. Chuẩn bị"), ("transcript", "2. Chép lời"),
                       ("translate", "3. Dịch thuật"), ("tts", "4. Lồng tiếng AI"),
                       ("export", "5. Xuất video")):
        row_frame = QFrame()
        row_frame.setCursor(Qt.PointingHandCursor)
        row_frame.setToolTip("Nhấp để chuyển đến phần cấu hình này")
        row_frame.setStyleSheet(
            "QFrame { background: transparent; border-radius: 4px; padding: 1px 3px; } "
            "QFrame:hover { background: #1a202c; }"
        )
        row = QHBoxLayout(row_frame)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(6)
        label = QLabel(title)
        label.setStyleSheet("font-size: 11px; font-weight: 600; color: #cbd5e1;")
        status = QLabel("Chưa bắt đầu")
        status.setObjectName("helperLabel")
        status.setStyleSheet(
            "background: #181d28; color: #8394aa; border: 1px solid #262f42; border-radius: 8px; padding: 1px 7px; font-size: 10px; font-weight: 600;"
        )
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(status)
        stage_layout.addWidget(row_frame)
        gui.workflow_stage_badges[key] = status
        gui.workflow_stage_labels[key] = label

        # Click to jump to tab
        def _bind_stage_jump(frame, target_idx):
            stage_to_master = {
                0: 0, # prepare -> media
                1: 0, # transcript -> media
                2: 4, # translate -> translate
                3: 5, # tts -> voice
                5: 6, # export -> framing
            }
            stage_to_key = {
                0: "media",
                1: "media",
                2: "translate",
                3: "voice",
                5: "framing",
            }
            def handler(event):
                m_idx = stage_to_master.get(target_idx, 0)
                if hasattr(gui, "left_master_stack"):
                    gui.left_master_stack.setCurrentIndex(m_idx)
                if hasattr(gui, "_select_sidebar_key"):
                    gui._select_sidebar_key(stage_to_key.get(target_idx, "media"))
            frame.mousePressEvent = handler
        _bind_stage_jump(row_frame, stage_tab_map.get(key, 0))

    workflow_shell_layout.addWidget(stage_box)

    gui.device_mode_label = QLabel()
    gui.device_mode_label.setObjectName("helperLabel")
    _update_device_label(gui)
    workflow_shell_layout.addWidget(gui.device_mode_label)

    tab_bar = QWidget()
    tab_bar_layout = QGridLayout(tab_bar)
    tab_bar_layout.setContentsMargins(0, 0, 0, 0)
    tab_bar_layout.setHorizontalSpacing(8)
    tab_bar_layout.setVerticalSpacing(8)
    tab_bar_layout.setColumnStretch(0, 1)
    tab_bar_layout.setColumnStretch(1, 1)
    tab_group = QButtonGroup(gui)
    tab_group.setExclusive(True)
    gui.left_panel_stack = QStackedWidget()
    gui.left_panel_stack.setObjectName("leftPanelStack")

    gui.workflow_page_containers = {}
    gui.workflow_page_hints = {}
    gui.workflow_tab_buttons = {}

    def _make_page(page_key: str):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        lock_hint = QLabel("")
        lock_hint.setObjectName("helperLabel")
        lock_hint.setWordWrap(True)
        lock_hint.setVisible(False)
        layout.addWidget(lock_hint)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        layout.addWidget(content)

        gui.workflow_page_containers[page_key] = content
        gui.workflow_page_hints[page_key] = lock_hint
        return page, content_layout

    pages = []
    media_page, media_layout = _make_page("media")
    audio_page, audio_layout = _make_page("audio")
    gui.workflow_audio_layout = audio_layout
    language_page, language_layout = _make_page("language")
    voice_page, voice_layout = _make_page("voice")
    style_page, style_layout = _make_page("style")
    advanced_page, advanced_layout = _make_page("advanced")
    gui.workflow_advanced_layout = advanced_layout
    pages.extend([media_page, audio_page, language_page, voice_page, style_page, advanced_page])

    def _add_tab(label: str, page_index: int, page_key: str, checked: bool = False):
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setMinimumHeight(34)
        btn.setMinimumWidth(0)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setObjectName("workflowTabBtn")
        tab_group.addButton(btn)
        row = page_index // 2
        col = page_index % 2
        tab_bar_layout.addWidget(btn, row, col)
        btn.toggled.connect(lambda active, idx=page_index: active and gui.left_panel_stack.setCurrentIndex(idx))
        gui.workflow_tab_buttons[page_key] = btn
        return btn

    _add_tab("🎬 Video & Khung", 0, "media", checked=False)
    gui.audio_tab_btn = _add_tab("🎵 Âm thanh", 1, "audio")
    gui.audio_tab_btn.setEnabled(False)
    _add_tab("🌐 Dịch thuật", 2, "language")
    _add_tab("🎙️ Giọng đọc AI", 3, "voice", checked=True)
    _add_tab("🎨 Kiểu dáng Sub", 4, "style")
    _add_tab("⚙️ Nâng cao", 5, "advanced")
    gui.show_progress_btn = QPushButton("Xem tiến trình")
    gui.show_progress_btn.clicked.connect(gui.show_active_progress_dialog)
    gui.show_progress_btn.setVisible(False)
    gui.show_progress_btn.setEnabled(False)
    gui.show_progress_btn.setObjectName("workflowTabBtn")
    gui.show_progress_btn.setMinimumHeight(34)
    gui.show_progress_btn.setMinimumWidth(0)
    gui.show_progress_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    tab_bar_layout.addWidget(gui.show_progress_btn, 3, 0, 1, 2)
    workflow_shell_layout.addWidget(tab_bar)

    upload_card, upload_layout = _build_collapsible_section("Video")
    upload_card.hide()

    output_card, output_layout = _build_collapsible_section("Đầu ra")
    # Output is always subtitles + voice. Keep the hidden compatibility
    # control because older settings/project helpers still read it.
    gui.output_mode_combo = QComboBox(gui)
    gui.output_mode_combo.addItem("Phụ đề + Giọng đọc Tiếng Việt")
    gui.output_mode_combo.setCurrentText("Phụ đề + Giọng đọc Tiếng Việt")
    gui.output_mode_combo.hide()

    # ---- Quick Presets 1-Click for Creator ----
    preset_card, preset_layout = _section_card()
    preset_title = QLabel("⚡ Thiết lập nhanh theo Nền tảng")
    preset_title.setObjectName("sectionTitle")
    preset_title.setStyleSheet("color: #ff9d42; font-weight: 700; font-size: 11px;")
    preset_layout.addWidget(preset_title)

    preset_btn_row = QHBoxLayout()
    preset_btn_row.setSpacing(6)

    def _apply_quick_preset(ratio_val, quality_val, fps_val, scale_val):
        idx_r = gui.output_ratio_combo.findData(ratio_val)
        if idx_r >= 0:
            gui.output_ratio_combo.setCurrentIndex(idx_r)
        idx_q = gui.output_quality_combo.findData(quality_val)
        if idx_q >= 0:
            gui.output_quality_combo.setCurrentIndex(idx_q)
        idx_f = gui.output_fps_combo.findData(fps_val)
        if idx_f >= 0:
            gui.output_fps_combo.setCurrentIndex(idx_f)
        idx_s = gui.output_scale_mode_combo.findData(scale_val)
        if idx_s >= 0:
            gui.output_scale_mode_combo.setCurrentIndex(idx_s)

    btn_tiktok = QPushButton("📱 TikTok (9:16)")
    btn_tiktok.setToolTip("Chuẩn dọc 9:16 - 1080p - 30 FPS - Vừa vặn")
    btn_tiktok.setStyleSheet(
        "QPushButton { background: #161b26; color: #f1f5f9; border: 1px solid #2a3449; border-radius: 6px; padding: 6px 4px; font-size: 10px; font-weight: 700; } "
        "QPushButton:hover { background: #222b3d; border-color: #ff7b1a; color: #ff9d42; }"
    )
    btn_tiktok.clicked.connect(lambda: _apply_quick_preset("9:16", "1080p", "30", "fit"))

    btn_yt = QPushButton("🖥️ YouTube (16:9)")
    btn_yt.setToolTip("Chuẩn ngang 16:9 - 1080p - Gốc/30 FPS - Vừa vặn")
    btn_yt.setStyleSheet(
        "QPushButton { background: #161b26; color: #f1f5f9; border: 1px solid #2a3449; border-radius: 6px; padding: 6px 4px; font-size: 10px; font-weight: 700; } "
        "QPushButton:hover { background: #222b3d; border-color: #ff7b1a; color: #ff9d42; }"
    )
    btn_yt.clicked.connect(lambda: _apply_quick_preset("16:9", "1080p", "30", "fit"))

    btn_fb = QPushButton("🟦 FB (1:1)")
    btn_fb.setToolTip("Chuẩn vuông 1:1 - 1080p - 30 FPS - Vừa vặn")
    btn_fb.setStyleSheet(
        "QPushButton { background: #161b26; color: #f1f5f9; border: 1px solid #2a3449; border-radius: 6px; padding: 6px 4px; font-size: 10px; font-weight: 700; } "
        "QPushButton:hover { background: #222b3d; border-color: #ff7b1a; color: #ff9d42; }"
    )
    btn_fb.clicked.connect(lambda: _apply_quick_preset("1:1", "1080p", "30", "fit"))

    preset_btn_row.addWidget(btn_tiktok)
    preset_btn_row.addWidget(btn_yt)
    preset_btn_row.addWidget(btn_fb)
    preset_layout.addLayout(preset_btn_row)
    output_layout.addWidget(preset_card)

    output_quality_card, output_quality_layout = _section_card()
    output_quality_title = QLabel("Chất lượng video")
    output_quality_title.setObjectName("sectionTitle")
    output_quality_layout.addWidget(output_quality_title)
    gui.output_quality_combo = QComboBox()
    gui.output_quality_combo.addItem("Tối đa (Gốc)", "source")
    gui.output_quality_combo.addItem("720p", "720p")
    gui.output_quality_combo.addItem("1080p (Full HD)", "1080p")
    gui.output_quality_combo.addItem("1440p (2K)", "1440p")
    gui.output_quality_combo.addItem("2160p (4K)", "2160p")
    output_quality_layout.addWidget(gui.output_quality_combo)
    output_fps_row = QVBoxLayout()
    output_fps_row.addWidget(QLabel("Tốc độ khung hình (FPS)"))
    gui.output_fps_combo = QComboBox()
    gui.output_fps_combo.addItem("Gốc (Khuyên dùng)", "source")
    gui.output_fps_combo.addItem("24 FPS", "24")
    gui.output_fps_combo.addItem("30 FPS", "30")
    gui.output_fps_combo.addItem("60 FPS", "60")
    output_fps_row.addWidget(gui.output_fps_combo)
    output_quality_layout.addLayout(output_fps_row)
    output_ratio_row = QVBoxLayout()
    output_ratio_row.addWidget(QLabel("Tỷ lệ khung hình"))
    gui.output_ratio_combo = QComboBox()
    gui.output_ratio_combo.addItem("Gốc (Khuyên dùng)", "source")
    gui.output_ratio_combo.addItem("16:9", "16:9")
    gui.output_ratio_combo.addItem("9:16", "9:16")
    gui.output_ratio_combo.addItem("1:1", "1:1")
    gui.output_ratio_combo.addItem("4:3", "4:3")
    gui.output_ratio_combo.currentIndexChanged.connect(gui.on_output_ratio_changed)
    output_ratio_row.addWidget(gui.output_ratio_combo)
    output_quality_layout.addLayout(output_ratio_row)
    output_scale_row = QVBoxLayout()
    output_scale_row.addWidget(QLabel("Khung hình hiển thị"))
    gui.output_scale_mode_combo = QComboBox()
    gui.output_scale_mode_combo.addItem("Vừa vặn (Fit)", "fit")
    gui.output_scale_mode_combo.addItem("Lấp đầy (Fill)", "fill")
    gui.output_scale_mode_combo.currentIndexChanged.connect(gui.on_output_scale_mode_changed)
    output_scale_row.addWidget(gui.output_scale_mode_combo)
    gui.reset_framing_btn = QPushButton("Đặt lại căn khung")
    gui.reset_framing_btn.setToolTip("Đặt lại trọng tâm lấp đầy về chính giữa")
    gui.reset_framing_btn.hide()
    output_scale_row.addWidget(gui.reset_framing_btn)
    output_quality_layout.addLayout(output_scale_row)
    output_layout.addWidget(output_quality_card)

    audio_cleanup_card, audio_cleanup_layout = _section_card()
    audio_cleanup_title = QLabel("Xử lý âm thanh")
    audio_cleanup_title.setObjectName("sectionTitle")
    audio_cleanup_layout.addWidget(audio_cleanup_title)
    gui.audio_handling_combo = QComboBox()
    gui.audio_handling_combo.addItem("Nhanh (Khuyên dùng)", "fast")
    gui.audio_handling_combo.addItem("Lọc giọng sạch (Tách bỏ giọng gốc)", "clean")
    gui.audio_handling_combo.setCurrentIndex(0)
    audio_cleanup_layout.addWidget(gui.audio_handling_combo)
    gui.audio_handling_hint_label = QLabel("Nhanh: chép lời từ toàn bộ âm thanh gốc. Lọc sạch: tách riêng giọng nói để chép lời chuẩn hơn.", gui)
    gui.audio_handling_hint_label.setObjectName("helperLabel")
    gui.audio_handling_hint_label.setWordWrap(True)
    audio_cleanup_layout.addWidget(gui.audio_handling_hint_label)

    diarization_card, diarization_layout = _section_card()
    gui.speaker_diarization_card = diarization_card
    diarization_title = QLabel("Phân biệt người nói")
    diarization_title.setObjectName("sectionTitle")
    diarization_layout.addWidget(diarization_title)
    gui.speaker_diarization_cb = QCheckBox("Bật nhận diện từng người nói")
    gui.speaker_diarization_cb.setChecked(True)
    gui.speaker_diarization_cb.setToolTip(
        "Nhận diện người nói offline bằng Sherpa-ONNX để tự động phân vai giọng đọc thông minh."
    )
    diarization_layout.addWidget(gui.speaker_diarization_cb)
    expected_speakers_row = QVBoxLayout()
    expected_speakers_row.addWidget(QLabel("Số người nói dự kiến"))
    gui.speaker_diarization_speakers_combo = QComboBox()
    gui.speaker_diarization_speakers_combo.addItem("Tự động nhận diện", -1)
    for count in range(2, 9):
        gui.speaker_diarization_speakers_combo.addItem(f"{count} người nói", count)
    gui.speaker_diarization_speakers_combo.setToolTip(
        "Chọn số lượng khi bạn biết chính xác số người nói trong video. Tự động nhận diện sẽ gom cụm theo độ tương đồng."
    )
    expected_speakers_row.addWidget(gui.speaker_diarization_speakers_combo)
    diarization_layout.addLayout(expected_speakers_row)
    gui.speaker_diarization_hint_label = QLabel(
        "Tùy chọn: phát hiện các lượt nói và phân màu từng đoạn trên timeline TS1. Yêu cầu mô hình Sherpa-ONNX."
    )
    gui.speaker_diarization_hint_label.setObjectName("helperLabel")
    gui.speaker_diarization_hint_label.setWordWrap(True)
    diarization_layout.addWidget(gui.speaker_diarization_hint_label)
    output_layout.addWidget(audio_cleanup_card)
    output_layout.addWidget(diarization_card)

    media_layout.addWidget(output_card)

    # -------------------------------------------------------------
    # Thẻ Logo Thương hiệu & Watermark Bản quyền (Màn hình chính)
    # -------------------------------------------------------------
    branding_main_card, branding_main_layout = _section_card()
    branding_main_title = QLabel("🏷️ Logo Thương hiệu & Watermark")
    branding_main_title.setObjectName("sectionTitle")
    branding_main_title.setStyleSheet("font-size: 12px; font-weight: 800; color: #ff9d42;")
    branding_main_layout.addWidget(branding_main_title)

    # Logo row
    gui.brand_logo_main_cb = QCheckBox("Hiển thị Logo thương hiệu trên video")
    gui.brand_logo_main_cb.setStyleSheet("font-size: 11px; font-weight: 600; color: #f8fbff;")
    branding_main_layout.addWidget(gui.brand_logo_main_cb)

    logo_picker_row = QHBoxLayout()
    logo_picker_row.setSpacing(6)
    gui.brand_logo_path_edit = QLineEdit()
    gui.brand_logo_path_edit.setPlaceholderText("Chọn file ảnh logo (.png, .jpg)...")
    gui.brand_logo_path_edit.setStyleSheet("background-color: #1a2738; color: #f8fbff; border: 1px solid #344862; border-radius: 6px; padding: 4px 6px; font-size: 11px;")
    gui.brand_logo_browse_btn = QPushButton("Chọn ảnh...")
    gui.brand_logo_browse_btn.setStyleSheet("background-color: #1e293b; color: #38bdf8; border: 1px solid #334155; border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: 600;")
    gui.brand_logo_preview_lbl = QLabel("Logo")
    gui.brand_logo_preview_lbl.setFixedSize(32, 32)
    gui.brand_logo_preview_lbl.setAlignment(Qt.AlignCenter)
    gui.brand_logo_preview_lbl.setStyleSheet("border: 1px dashed #344862; border-radius: 4px; background-color: #16202e; color: #64748b; font-size: 9px;")
    logo_picker_row.addWidget(gui.brand_logo_path_edit, 1)
    logo_picker_row.addWidget(gui.brand_logo_browse_btn)
    logo_picker_row.addWidget(gui.brand_logo_preview_lbl)
    branding_main_layout.addLayout(logo_picker_row)

    # Watermark row
    gui.brand_wm_main_cb = QCheckBox("Hiển thị Watermark chữ (Chống reup)")
    gui.brand_wm_main_cb.setStyleSheet("font-size: 11px; font-weight: 600; color: #f8fbff;")
    branding_main_layout.addWidget(gui.brand_wm_main_cb)

    gui.brand_wm_text_edit = QLineEdit()
    gui.brand_wm_text_edit.setPlaceholderText("Nhập chữ watermark (Ví dụ: Nhím Review)...")
    gui.brand_wm_text_edit.setStyleSheet("background-color: #1a2738; color: #f8fbff; border: 1px solid #344862; border-radius: 6px; padding: 4px 6px; font-size: 11px;")
    branding_main_layout.addWidget(gui.brand_wm_text_edit)

    from PySide6.QtCore import QSettings
    settings = QSettings("TankVideo", "TankVideoStudio")
    gui.brand_logo_main_cb.setChecked(settings.value("branding/enable_logo", False, type=bool))
    init_logo_path = settings.value("branding/logo_path", "", type=str)
    if init_logo_path:
        gui.brand_logo_path_edit.setText(init_logo_path)
    gui.brand_wm_main_cb.setChecked(settings.value("branding/enable_watermark", False, type=bool))
    init_wm_text = settings.value("branding/watermark_text", "", type=str)
    if init_wm_text:
        gui.brand_wm_text_edit.setText(init_wm_text)

    def _on_browse_logo():
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            gui,
            "Chọn file ảnh Logo Thương hiệu",
            os.path.dirname(gui.brand_logo_path_edit.text().strip()) if gui.brand_logo_path_edit.text().strip() else "",
            "File hình ảnh (*.png *.jpg *.jpeg *.webp *.bmp);;Tất cả file (*.*)",
        )
        if path:
            gui.brand_logo_path_edit.setText(os.path.normpath(path))
            gui.brand_logo_main_cb.setChecked(True)

    def _sync_logo_state():
        settings.setValue("branding/enable_logo", gui.brand_logo_main_cb.isChecked())
        settings.setValue("branding/logo_path", gui.brand_logo_path_edit.text().strip())
        lp = gui.brand_logo_path_edit.text().strip()
        if lp and os.path.isfile(lp):
            from PySide6.QtGui import QPixmap
            pm = QPixmap(lp)
            if not pm.isNull():
                gui.brand_logo_preview_lbl.setPixmap(pm.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                gui.brand_logo_preview_lbl.setText("")
                return
        gui.brand_logo_preview_lbl.clear()
        gui.brand_logo_preview_lbl.setText("Logo")

    def _sync_wm_state():
        settings.setValue("branding/enable_watermark", gui.brand_wm_main_cb.isChecked())
        settings.setValue("branding/watermark_text", gui.brand_wm_text_edit.text().strip())

    gui.brand_logo_browse_btn.clicked.connect(_on_browse_logo)
    gui.brand_logo_main_cb.toggled.connect(lambda: _sync_logo_state())
    gui.brand_logo_path_edit.textChanged.connect(lambda: _sync_logo_state())
    gui.brand_wm_main_cb.toggled.connect(lambda: _sync_wm_state())
    gui.brand_wm_text_edit.textChanged.connect(lambda: _sync_wm_state())
    _sync_logo_state()

    media_layout.addWidget(branding_main_card)

    if hasattr(gui, "update_speaker_diarization_availability"):
        gui.update_speaker_diarization_availability()

    language_card, language_layout = _build_collapsible_section("Ngôn ngữ")
    gui.lang_whisper_combo = QComboBox()
    gui.lang_whisper_combo.addItem("Tự động phát hiện", "auto")
    gui.lang_whisper_combo.addItem("Tiếng Trung", "zh")
    gui.lang_whisper_combo.addItem("Tiếng Nhật", "ja")
    gui.lang_whisper_combo.addItem("Tiếng Hàn", "ko")
    gui.lang_whisper_combo.addItem("Tiếng Anh", "en")
    gui.lang_whisper_combo.addItem("Tiếng Việt", "vi")
    gui.lang_target_combo = QComboBox()
    gui.lang_target_combo.addItem("Tiếng Việt", "vi")
    gui.lang_target_combo.addItem("Tiếng Anh", "en")
    gui.lang_target_combo.setCurrentIndex(0)
    language_pair_card, language_pair_layout = _section_card()
    language_pair_title = QLabel("Cặp ngôn ngữ dịch")
    language_pair_title.setObjectName("sectionTitle")
    language_pair_layout.addWidget(language_pair_title)
    source_row = QVBoxLayout()
    source_row.addWidget(QLabel("Ngôn ngữ gốc của video"))
    source_row.addWidget(gui.lang_whisper_combo)
    target_row = QVBoxLayout()
    target_row.addWidget(QLabel("Dịch sang ngôn ngữ"))
    target_row.addWidget(gui.lang_target_combo)
    language_pair_layout.addLayout(source_row)
    language_pair_layout.addLayout(target_row)

    gui.view_subtitle_alignment_btn = QPushButton("📋 Đối chiếu Phụ đề Song ngữ (Gốc & Dịch)")
    gui.view_subtitle_alignment_btn.setStyleSheet(
        "background-color: #1e3a5f; color: #4ecdc4; font-weight: bold; padding: 8px 14px; border: 1px solid #2d5a88; border-radius: 4px; margin-top: 6px;"
    )
    gui.view_subtitle_alignment_btn.clicked.connect(gui.open_subtitle_alignment_dialog)
    language_layout.addWidget(gui.view_subtitle_alignment_btn)

    language_layout.addWidget(language_pair_card)
    gui.lang_target_combo.currentIndexChanged.connect(gui.on_target_language_changed)

    language_page.layout().addWidget(language_card)

    voice_card, voice_layout = _build_collapsible_section("Giọng đọc")
    gui.voice_section_card = voice_card
    gui.voice_engine_combo = QComboBox()
    gui.voice_engine_combo.addItem("Giọng đọc nhanh", "fast")
    gui.free_voice_combo = QComboBox()
    gui.voice_gender_combo = QComboBox()
    gui.voice_gender_combo.addItem("Tất cả", "any")
    gui.voice_gender_combo.addItem("Nam", "male")
    gui.voice_gender_combo.addItem("Nữ", "female")
    gui.voice_gender_combo.setCurrentIndex(0)
    gui.voice_gender_combo.currentIndexChanged.connect(gui.on_voice_gender_changed)
    gui.voice_speed_spin = QComboBox(gui)
    gui.voice_speed_spin.setEditable(True)
    gui.voice_speed_spin.addItems(["0.8x", "0.9x", "1.0x", "1.1x", "1.2x", "1.3x", "1.4x", "1.5x", "1.6x", "1.8x", "2.0x"])
    gui.voice_speed_spin.setCurrentText("1.0x")
    gui.voice_speed_spin.hide()
    gui.voice_timing_sync_combo = QComboBox()
    gui.voice_timing_sync_combo.addItems(["Tắt", "Thông minh", "Ưu tiên Timeline", "Ép khớp thời gian"])
    gui.voice_timing_sync_combo.setCurrentText("Thông minh")

    def _sync_voice_speed_enabled(_value: str = ""):
        mode = gui.voice_timing_sync_combo.currentText().strip().lower()
        gui.voice_speed_spin.setEnabled(mode != "tắt" and mode != "off")
    gui.voice_timing_sync_combo.currentTextChanged.connect(_sync_voice_speed_enabled)
    _sync_voice_speed_enabled()

    def _on_voice_timing_sync_changed(_value: str = ""):
        if hasattr(gui, "timeline") and gui.timeline is not None:
            gui.timeline.set_voice_sync_mode(gui.voice_timing_sync_combo.currentText())
    _on_voice_timing_sync_changed()

    media_workflow_card, media_workflow_layout = _build_collapsible_section("Quy trình âm thanh")
    timing_card, timing_layout = _section_card()
    timing_title = QLabel("Đồng bộ thời lượng giọng đọc")
    timing_title.setObjectName("sectionTitle")
    timing_hint = QLabel("Điều khiển cách thời lượng giọng đọc bám sát theo trục thời gian phụ đề.")
    timing_hint.setObjectName("helperLabel")
    timing_hint.setWordWrap(True)
    timing_layout.addWidget(timing_title)
    timing_layout.addWidget(timing_hint)
    timing_layout.addWidget(gui.voice_timing_sync_combo)
    media_workflow_layout.addWidget(timing_card)
    media_layout.addWidget(media_workflow_card)
    gui.free_voice_combo.currentIndexChanged.connect(gui.on_selected_voice_changed)
    gui.voice_engine_combo.currentIndexChanged.connect(gui.on_voice_engine_changed)
    gui.preview_voice_btn = QPushButton("Nghe thử giọng đọc")
    gui.preview_voice_btn.clicked.connect(gui.preview_selected_voice_sample)
    gui.voice_preview_meta_label = QLabel("Nghe đoạn đọc mẫu ngắn trước khi tạo toàn bộ audio.", gui)
    gui.voice_preview_meta_label.setObjectName("helperLabel")
    gui.voice_preview_meta_label.setWordWrap(True)
    gui.voice_preview_meta_label.hide()
    voice_setup_card, voice_setup_layout = _section_card()
    voice_setup_title = QLabel("Tạo giọng đọc")
    voice_setup_title.setObjectName("sectionTitle")
    voice_setup_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #ffffff;")
    voice_setup_layout.addWidget(voice_setup_title)

    # Segmented mode toggle: [Một giọng] | [Phân vai]
    mode_bar = QFrame()
    mode_bar.setStyleSheet(
        "QFrame { background: #0c1524; border-radius: 8px; padding: 2px; border: 1px solid #203550; }"
    )
    mode_layout = QHBoxLayout(mode_bar)
    mode_layout.setContentsMargins(2, 2, 2, 2)
    mode_layout.setSpacing(4)
    gui.voice_single_mode_btn = QPushButton("Một giọng")
    gui.voice_single_mode_btn.setCheckable(True)
    gui.voice_single_mode_btn.setStyleSheet(
        "QPushButton { background: transparent; color: #a0b4cc; font-weight: bold; border-radius: 6px; padding: 6px 12px; border: none; }"
        "QPushButton:checked { background: #1f3b5c; color: #ffffff; }"
    )
    gui.voice_role_mode_btn = QPushButton("Phân vai")
    gui.voice_role_mode_btn.setCheckable(True)
    gui.voice_role_mode_btn.setChecked(True)
    gui.voice_role_mode_btn.setStyleSheet(
        "QPushButton { background: transparent; color: #a0b4cc; font-weight: bold; border-radius: 6px; padding: 6px 12px; border: none; }"
        "QPushButton:checked { background: #1f3b5c; color: #ffffff; }"
    )
    gui.voice_mode_button_group = QButtonGroup(gui)
    gui.voice_mode_button_group.addButton(gui.voice_single_mode_btn)
    gui.voice_mode_button_group.addButton(gui.voice_role_mode_btn)
    mode_layout.addWidget(gui.voice_single_mode_btn)
    mode_layout.addWidget(gui.voice_role_mode_btn)
    voice_setup_layout.addWidget(mode_bar)

    gui.fast_voice_panel = QWidget()
    fast_voice_layout = QVBoxLayout(gui.fast_voice_panel)
    fast_voice_layout.setContentsMargins(0, 4, 0, 0)
    fast_voice_layout.setSpacing(8)
    fast_voice_layout.addWidget(QLabel("Bộ đọc giọng"))
    fast_voice_layout.addWidget(gui.voice_engine_combo)
    fast_voice_layout.addWidget(QLabel("Loại giọng / Giới tính"))
    fast_voice_layout.addWidget(gui.voice_gender_combo)
    fast_voice_layout.addWidget(QLabel("Giọng đọc"))
    fast_voice_layout.addWidget(gui.free_voice_combo)
    fast_voice_layout.addWidget(gui.preview_voice_btn)
    fast_voice_layout.addWidget(gui.voice_preview_meta_label)
    gui.sync_capcut_voice_btn = QPushButton("🎙️ Đồng bộ giọng từ CapCut PC…")
    gui.sync_capcut_voice_btn.setStyleSheet(
        "background-color: #00897b; color: #ffffff; font-weight: bold; padding: 7px 14px; border-radius: 4px; margin-top: 4px;"
    )
    gui.sync_capcut_voice_btn.clicked.connect(gui.open_capcut_sync_dialog)
    fast_voice_layout.addWidget(gui.sync_capcut_voice_btn)
    voice_setup_layout.addWidget(gui.fast_voice_panel)

    # Detected speakers card for role casting mode
    gui.detected_speakers_card, detected_speakers_layout = _section_card()
    gui.auto_assign_gender_voices_btn = QPushButton("⚡ Tự động phân vai thông minh")
    gui.auto_assign_gender_voices_btn.setStyleSheet(
        "background-color: #4f46e5; color: #ffffff; font-weight: bold; padding: 9px 14px; border-radius: 6px;"
    )
    gui.auto_assign_gender_voices_btn.setToolTip(
        "Tự động nhận diện giới tính và phân vai nhân vật theo âm thanh gốc"
    )
    detected_speakers_layout.addWidget(gui.auto_assign_gender_voices_btn)
    gui.detected_speakers_hint_label = QLabel(
        "Nhân vật được nhận diện và gán giọng tương ứng bên dưới:"
    )
    gui.detected_speakers_hint_label.setObjectName("helperLabel")
    gui.detected_speakers_hint_label.setWordWrap(True)
    detected_speakers_layout.addWidget(gui.detected_speakers_hint_label)

    gui.detected_speakers_list = QWidget()
    gui.detected_speakers_list_layout = QVBoxLayout(gui.detected_speakers_list)
    gui.detected_speakers_list_layout.setContentsMargins(0, 0, 0, 0)
    gui.detected_speakers_list_layout.setSpacing(8)
    detected_speakers_layout.addWidget(gui.detected_speakers_list)
    voice_setup_layout.addWidget(gui.detected_speakers_card)

    def _on_voice_studio_mode_changed():
        single = gui.voice_single_mode_btn.isChecked()
        gui.fast_voice_panel.setVisible(single)
        gui.detected_speakers_card.setVisible(not single)

    gui.voice_single_mode_btn.toggled.connect(_on_voice_studio_mode_changed)
    gui.voice_role_mode_btn.toggled.connect(_on_voice_studio_mode_changed)
    _on_voice_studio_mode_changed()

    # Speed and Tone Sliders
    sliders_card = QFrame()
    sliders_card.setStyleSheet("background: transparent;")
    sliders_layout = QVBoxLayout(sliders_card)
    sliders_layout.setContentsMargins(0, 6, 0, 0)
    sliders_layout.setSpacing(6)

    # Speed slider row
    speed_row = QHBoxLayout()
    speed_row.addWidget(QLabel("Tốc độ đọc:"))
    gui.voice_speed_slider = QSlider(Qt.Horizontal)
    gui.voice_speed_slider.setRange(5, 20)
    gui.voice_speed_slider.setValue(10)
    gui.voice_speed_slider_label = QLabel("1.0x")
    gui.voice_speed_slider_label.setFixedWidth(36)
    def _on_speed_slider_changed(v):
        factor = v / 10.0
        gui.voice_speed_slider_label.setText(f"{factor:.1f}x")
        gui.voice_speed_spin.setCurrentText(f"{factor:.1f}x")
    gui.voice_speed_slider.valueChanged.connect(_on_speed_slider_changed)
    speed_row.addWidget(gui.voice_speed_slider, 1)
    speed_row.addWidget(gui.voice_speed_slider_label)
    sliders_layout.addLayout(speed_row)

    # Tone / Pitch slider row
    pitch_row = QHBoxLayout()
    pitch_row.addWidget(QLabel("Cao độ giọng:"))
    gui.voice_pitch_slider = QSlider(Qt.Horizontal)
    gui.voice_pitch_slider.setRange(-5, 5)
    gui.voice_pitch_slider.setValue(0)
    gui.voice_pitch_slider_label = QLabel("0")
    gui.voice_pitch_slider_label.setFixedWidth(36)
    def _on_pitch_slider_changed(v):
        gui.voice_pitch_slider_label.setText(f"{v:+d}" if v != 0 else "0")
    gui.voice_pitch_slider.valueChanged.connect(_on_pitch_slider_changed)
    pitch_row.addWidget(gui.voice_pitch_slider, 1)
    pitch_row.addWidget(gui.voice_pitch_slider_label)
    sliders_layout.addLayout(pitch_row)
    voice_setup_layout.addWidget(sliders_card)

    # Big action button: Tạo giọng cho tất cả
    gui.generate_all_voices_btn = QPushButton("✨ Tạo giọng cho tất cả")
    gui.generate_all_voices_btn.setMinimumHeight(44)
    gui.generate_all_voices_btn.setStyleSheet(
        "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00d2ff, stop:1 #0078d4); "
        "color: #ffffff; font-weight: 800; font-size: 13px; border: none; border-radius: 8px; padding: 10px; } "
        "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #33dcff, stop:1 #198cff); }"
    )
    gui.generate_all_voices_btn.setToolTip("Tạo toàn bộ âm thanh lồng tiếng theo thiết lập phân vai hiện tại")
    # An explicit user request to regenerate all voices must bypass the voice
    # cache even when a stale signature was accidentally persisted.
    gui.generate_all_voices_btn.clicked.connect(
        lambda _checked=False: gui.run_voiceover(force_refresh=True)
    )
    voice_setup_layout.addWidget(gui.generate_all_voices_btn)

    gui.ai_dubbing_rewrite_cb = QCheckBox("Dùng AI viết lại lời khi lồng tiếng để khớp thời gian", gui)
    gui.ai_dubbing_rewrite_cb.setChecked(False)
    gui.ai_dubbing_rewrite_cb.hide()
    gui.ai_dubbing_rewrite_hint_label = QLabel(
        "Giữ nguyên văn bản phụ đề, nhưng cho phép AI tóm gọn câu khi đọc nếu đoạn âm thanh quá ngắn.",
        gui,
    )
    gui.ai_dubbing_rewrite_hint_label.setObjectName("helperLabel")
    gui.ai_dubbing_rewrite_hint_label.setWordWrap(True)
    gui.ai_dubbing_rewrite_hint_label.hide()
    voice_layout.addWidget(voice_setup_card)

    voice_page.layout().addWidget(voice_card)

    subtitle_card, subtitle_layout = _build_collapsible_section("Kiểu phụ đề", start_expanded=True)
    base_style_label = QLabel("Mẫu định sẵn (Presets)")
    base_style_label.setObjectName("sectionTitle")
    subtitle_layout.addWidget(base_style_label)
    gui.subtitle_preset_tiktok_radio = QRadioButton("TikTok")
    gui.subtitle_preset_youtube_radio = QRadioButton("YouTube")
    gui.subtitle_preset_minimal_radio = QRadioButton("Ngắn gọn")
    gui.subtitle_preset_custom_radio = QRadioButton("Tùy chỉnh")
    gui.subtitle_preset_youtube_radio.setChecked(True)
    gui.subtitle_preset_group = QButtonGroup(gui)
    gui.subtitle_preset_group.addButton(gui.subtitle_preset_tiktok_radio)
    gui.subtitle_preset_group.addButton(gui.subtitle_preset_youtube_radio)
    gui.subtitle_preset_group.addButton(gui.subtitle_preset_minimal_radio)
    gui.subtitle_preset_group.addButton(gui.subtitle_preset_custom_radio)

    preset_grid = QGridLayout()
    preset_grid.setContentsMargins(0, 0, 0, 0)
    preset_grid.setHorizontalSpacing(8)
    preset_grid.setVerticalSpacing(8)
    preset_grid.setColumnStretch(0, 1)
    preset_grid.setColumnStretch(1, 1)
    preset_grid.addWidget(_build_style_preset_card("TikTok", "XU HƯỚNG", "CHỮ NỔI BẬT", gui.subtitle_preset_tiktok_radio), 0, 0)
    preset_grid.addWidget(_build_style_preset_card("YouTube", "Phụ đề chuẩn", "hộp nền đen", gui.subtitle_preset_youtube_radio), 0, 1)
    preset_grid.addWidget(_build_style_preset_card("Ngắn gọn", "XIN CHÀO", "các bạn", gui.subtitle_preset_minimal_radio), 1, 0)
    preset_grid.addWidget(_build_style_preset_card("Tùy chỉnh", "Kiểu", "của bạn", gui.subtitle_preset_custom_radio), 1, 1)
    subtitle_layout.addLayout(preset_grid)

    style_library_card, style_library_layout = _section_card()
    style_library_title = QLabel("Kiểu đã lưu")
    style_library_title.setObjectName("sectionTitle")
    style_library_layout.addWidget(style_library_title)
    gui.save_subtitle_style_btn = QPushButton("+ Lưu kiểu này")
    gui.save_subtitle_style_btn.clicked.connect(gui.save_current_subtitle_style_preset)
    gui.saved_subtitle_style_combo = QComboBox()
    gui.saved_subtitle_style_combo.addItem("Kiểu của tôi")
    gui.saved_subtitle_style_combo.currentIndexChanged.connect(gui.load_selected_subtitle_style_preset)
    style_library_layout.addWidget(gui.save_subtitle_style_btn)
    style_library_layout.addWidget(gui.saved_subtitle_style_combo)
    subtitle_layout.addWidget(style_library_card)
    gui.style_library_card = style_library_card

    highlight_card, highlight_card_layout = _build_collapsible_section("Tô sáng từ khóa", start_expanded=False)
    gui.subtitle_keyword_highlight_cb = QCheckBox("Tô màu làm nổi bật từ khóa")
    gui.subtitle_keyword_highlight_cb.setChecked(False)
    gui.subtitle_highlight_color_combo = QComboBox()
    gui.subtitle_highlight_color_combo.addItems(["Vàng", "Xanh lơ", "Xanh lá", "Hồng"])
    gui.subtitle_highlight_mode_combo = QComboBox()
    gui.subtitle_highlight_mode_combo.addItems(["Tự động", "Thủ công", "Tự động + Thủ công"])
    highlight_card_layout.addWidget(gui.subtitle_keyword_highlight_cb)

    highlight_color_row = QHBoxLayout()
    highlight_color_row.addWidget(QLabel("Màu sắc:"))
    highlight_color_row.addWidget(gui.subtitle_highlight_color_combo, 1)
    highlight_card_layout.addLayout(highlight_color_row)

    highlight_mode_row = QHBoxLayout()
    highlight_mode_row.addWidget(QLabel("Source:"))
    highlight_mode_row.addWidget(gui.subtitle_highlight_mode_combo, 1)
    highlight_card_layout.addLayout(highlight_mode_row)
    subtitle_layout.addWidget(highlight_card)
    gui.highlight_card = highlight_card

    position_card, position_layout = _build_collapsible_section("Vị trí chữ", start_expanded=False)
    position_wrapper = QFrame()
    position_wrapper.setObjectName("statusCard")
    position_wrapper_layout = QVBoxLayout(position_wrapper)
    position_wrapper_layout.setContentsMargins(12, 12, 12, 12)
    position_wrapper_layout.setSpacing(10)

    position_grid = QGridLayout()
    position_grid.setContentsMargins(0, 0, 0, 0)
    position_grid.setHorizontalSpacing(10)
    position_grid.setVerticalSpacing(8)

    gui.subtitle_position_mode_combo = QComboBox()
    gui.subtitle_position_mode_combo.addItem("Căn vị trí nhanh", "anchor")
    gui.subtitle_position_mode_combo.addItem("Tọa độ X/Y tùy chỉnh", "custom")
    gui.subtitle_align_label = QLabel("Vị trí:")
    gui.subtitle_align_combo = QComboBox()
    gui.subtitle_align_combo.addItems(["Dưới cùng", "Dưới trái", "Dưới phải", "Chính giữa", "Trên cùng"])
    gui.subtitle_align_combo.setCurrentText("Dưới cùng")
    gui.subtitle_custom_x_label = QLabel("X tùy chỉnh:")
    gui.subtitle_custom_x_spin = ReliableSpinBox()
    gui.subtitle_custom_x_spin.setRange(0, 100)
    gui.subtitle_custom_x_spin.setValue(50)
    gui.subtitle_custom_x_spin.setSuffix(" %")
    gui.subtitle_custom_y_label = QLabel("Y tùy chỉnh:")
    gui.subtitle_custom_y_spin = ReliableSpinBox()
    gui.subtitle_custom_y_spin.setRange(0, 100)
    gui.subtitle_custom_y_spin.setValue(86)
    gui.subtitle_custom_y_spin.setSuffix(" %")
    gui.subtitle_bottom_offset_label = QLabel("Khoảng cách đáy:")
    gui.subtitle_bottom_offset_spin = ReliableSpinBox()
    gui.subtitle_bottom_offset_spin.setRange(0, 300)
    gui.subtitle_bottom_offset_spin.setValue(30)
    gui.subtitle_bottom_offset_spin.setSuffix(" px")

    position_grid.addWidget(QLabel("Chế độ căn vị trí:"), 0, 0)
    position_grid.addWidget(gui.subtitle_position_mode_combo, 0, 1)
    position_grid.addWidget(gui.subtitle_align_label, 1, 0)
    position_grid.addWidget(gui.subtitle_align_combo, 1, 1)
    position_grid.addWidget(gui.subtitle_custom_x_label, 2, 0)
    position_grid.addWidget(gui.subtitle_custom_x_spin, 2, 1)
    position_grid.addWidget(gui.subtitle_custom_y_label, 3, 0)
    position_grid.addWidget(gui.subtitle_custom_y_spin, 3, 1)
    position_grid.addWidget(gui.subtitle_bottom_offset_label, 4, 0)
    position_grid.addWidget(gui.subtitle_bottom_offset_spin, 4, 1)

    position_wrapper_layout.addLayout(position_grid)
    position_layout.addWidget(position_wrapper)
    subtitle_layout.addWidget(position_card)
    gui.subtitle_position_card = position_card

    timing_card, timing_layout = _build_collapsible_section("Hiệu ứng xuất hiện", start_expanded=False)
    timing_wrapper = QFrame()
    timing_wrapper.setObjectName("statusCard")
    timing_wrapper_layout = QVBoxLayout(timing_wrapper)
    timing_wrapper_layout.setContentsMargins(12, 12, 12, 12)
    timing_wrapper_layout.setSpacing(10)

    timing_grid = QGridLayout()
    timing_grid.setContentsMargins(0, 0, 0, 0)
    timing_grid.setHorizontalSpacing(10)
    timing_grid.setVerticalSpacing(8)

    custom_title_card, custom_title_layout = _build_collapsible_section("Định dạng chữ", start_expanded=False)
    custom_wrapper = QFrame()
    custom_wrapper.setObjectName("statusCard")
    custom_wrapper_layout = QVBoxLayout(custom_wrapper)
    custom_wrapper_layout.setContentsMargins(12, 12, 12, 12)
    custom_wrapper_layout.setSpacing(10)
    gui.custom_settings_toggle_btn = QToolButton()
    gui.custom_settings_toggle_btn.setText("▼ Chi tiết kiểu dáng")
    gui.custom_settings_toggle_btn.setCheckable(True)
    gui.custom_settings_toggle_btn.setChecked(True)
    gui.custom_settings_toggle_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
    gui.custom_settings_toggle_btn.setStyleSheet("QToolButton { text-align: left; font-weight: 700; color: #dbe5f3; border: none; padding: 0; }")
    custom_wrapper_layout.addWidget(gui.custom_settings_toggle_btn)

    gui.custom_settings_content = QWidget()
    custom_controls_layout = QGridLayout(gui.custom_settings_content)
    custom_controls_layout.setContentsMargins(0, 0, 0, 0)
    custom_controls_layout.setHorizontalSpacing(10)
    custom_controls_layout.setVerticalSpacing(8)

    gui.subtitle_font_combo = QComboBox()
    gui.subtitle_font_combo.setEditable(True)
    gui.subtitle_font_combo.addItems(["Montserrat", "Roboto", "Inter", "Poppins", "Arial", "Segoe UI", "Tahoma", "Verdana", "Times New Roman"])
    gui.subtitle_font_combo.setCurrentText("Segoe UI")
    gui.subtitle_font_size_spin = ReliableSpinBox()
    gui.subtitle_font_size_spin.setRange(30, 90)
    gui.subtitle_font_size_spin.setValue(60)
    gui.subtitle_font_scale_combo = QComboBox()
    for percent in (50, 75, 100, 125, 150):
        gui.subtitle_font_scale_combo.addItem(f"{percent}%", percent)
    gui.subtitle_font_scale_combo.setCurrentIndex(2)
    gui.subtitle_color_btn = QPushButton("Trắng")
    gui.subtitle_color_hex = "#FFFFFF"
    gui.subtitle_color_btn.clicked.connect(gui.choose_subtitle_color)
    gui.subtitle_background_color_btn = QPushButton("#000000")
    gui.subtitle_background_color_hex = "#000000"
    gui.subtitle_background_color_btn.clicked.connect(gui.choose_subtitle_background_color)
    gui.subtitle_background_cb = QCheckBox("Bật hộp nền")
    gui.subtitle_background_cb.setChecked(False)
    gui.subtitle_outline_cb = QCheckBox("Viền chữ")
    gui.subtitle_outline_cb.setChecked(True)
    gui.subtitle_bold_cb = QCheckBox("In đậm")
    gui.subtitle_bold_cb.setChecked(True)
    gui.subtitle_speaker_colors_cb = QCheckBox("Dùng màu riêng cho từng người nói")
    gui.subtitle_speaker_colors_cb.setToolTip(
        "Sử dụng màu nhận diện trên TS1 của từng người nói để tô màu chữ phụ đề."
    )
    gui.subtitle_single_line_cb = QCheckBox("Phụ đề 1 dòng (Netflix)")
    gui.subtitle_single_line_cb.setChecked(False)
    gui.subtitle_animation_combo = QComboBox()
    gui.subtitle_animation_combo.addItems(
        ["Tĩnh", "Bật lên (Pop In)", "Trượt lên", "Mờ dần vào", "Mờ dần ra", "Nhịp đập", "Hiện nền", "Máy đánh chữ", "Karaoke nổi bật từng từ"]
    )
    gui.subtitle_animation_combo.setCurrentText("Bật lên (Pop In)")
    gui.subtitle_animation_combo.currentTextChanged.connect(lambda _value: gui.on_subtitle_animation_changed())
    gui.subtitle_animation_time_spin = ReliableDoubleSpinBox()
    gui.subtitle_animation_time_spin.setRange(0.1, 2.5)
    gui.subtitle_animation_time_spin.setSingleStep(0.05)
    gui.subtitle_animation_time_spin.setDecimals(2)
    gui.subtitle_animation_time_spin.setValue(0.22)
    gui.subtitle_animation_time_spin.setSuffix(" s")
    gui.subtitle_animation_time_label = QLabel("Thời lượng")
    gui.subtitle_bg_alpha_spin = ReliableDoubleSpinBox()
    gui.subtitle_bg_alpha_spin.setRange(0.0, 1.0)
    gui.subtitle_bg_alpha_spin.setSingleStep(0.05)
    gui.subtitle_bg_alpha_spin.setDecimals(2)
    gui.subtitle_bg_alpha_spin.setValue(0.6)
    gui.subtitle_bg_alpha_spin.setSuffix(" độ mờ")
    gui.subtitle_karaoke_timing_label = QLabel("Nhịp xuất hiện")
    gui.subtitle_karaoke_timing_combo = QComboBox()
    gui.subtitle_karaoke_timing_combo.addItem("Theo nhịp Tiếng Việt", "vietnamese")
    gui.subtitle_karaoke_timing_combo.addItem("Theo nhịp lời nói gốc", "source")
    gui.subtitle_karaoke_timing_combo.setCurrentIndex(0)
    gui.subtitle_karaoke_timing_combo.currentTextChanged.connect(lambda _value: gui.update_subtitle_preview_style())

    custom_controls_layout.addWidget(QLabel("Phông chữ:"), 0, 0)
    custom_controls_layout.addWidget(gui.subtitle_font_combo, 0, 1)
    custom_controls_layout.addWidget(QLabel("Kích cỡ:"), 1, 0)
    custom_controls_layout.addWidget(gui.subtitle_font_scale_combo, 1, 1)
    custom_controls_layout.addWidget(QLabel("Màu chữ:"), 2, 0)
    custom_controls_layout.addWidget(gui.subtitle_color_btn, 2, 1)
    custom_controls_layout.addWidget(gui.subtitle_outline_cb, 3, 0)
    custom_controls_layout.addWidget(gui.subtitle_bold_cb, 3, 1)
    custom_controls_layout.addWidget(gui.subtitle_speaker_colors_cb, 4, 0, 1, 2)
    custom_wrapper_layout.addWidget(gui.custom_settings_content)
    custom_title_layout.addWidget(custom_wrapper)
    subtitle_layout.addWidget(custom_title_card)
    gui.custom_title_card = custom_title_card

    single_line_card, single_line_layout = _build_collapsible_section("Phụ đề 1 dòng (Netflix)", start_expanded=False)
    single_line_wrapper = QFrame()
    single_line_wrapper.setObjectName("statusCard")
    single_line_grid = QGridLayout(single_line_wrapper)
    single_line_grid.setContentsMargins(12, 12, 12, 12)
    gui.subtitle_single_line_cb.setText("Bật phụ đề 1 dòng kiểu Netflix")
    gui.subtitle_words_per_segment_spin = ReliableSpinBox()
    gui.subtitle_words_per_segment_spin.setRange(1, 20)
    gui.subtitle_words_per_segment_spin.setValue(4)
    gui.subtitle_words_per_segment_spin.setSuffix(" từ")
    single_line_grid.addWidget(gui.subtitle_single_line_cb, 0, 0, 1, 2)
    single_line_grid.addWidget(QLabel("Số từ mỗi đoạn:"), 1, 0)
    single_line_grid.addWidget(gui.subtitle_words_per_segment_spin, 1, 1)
    single_line_layout.addWidget(single_line_wrapper)
    subtitle_layout.addWidget(single_line_card)

    background_card, background_layout = _build_collapsible_section("Hộp nền phụ đề", start_expanded=False)
    background_wrapper = QFrame()
    background_wrapper.setObjectName("statusCard")
    background_wrapper_layout = QGridLayout(background_wrapper)
    background_wrapper_layout.setContentsMargins(12, 12, 12, 12)
    background_wrapper_layout.setHorizontalSpacing(10)
    background_wrapper_layout.setVerticalSpacing(8)
    background_wrapper_layout.addWidget(gui.subtitle_background_cb, 0, 0, 1, 2)
    gui.subtitle_background_width_combo = QComboBox()
    gui.subtitle_background_width_combo.addItem("Ôm sát từng dòng chữ", "fit_text")
    gui.subtitle_background_width_combo.addItem("Bao trọn khối phụ đề (Chuẩn xác)", "full_area")
    gui.subtitle_background_width_combo.setToolTip(
        "Ôm sát từng dòng: tốc độ xử lý nhanh, bọc từng dòng chữ.\n"
        "Bao trọn khối: khung chữ cố định vuông vắn."
    )
    background_wrapper_layout.addWidget(QLabel("Độ rộng:"), 1, 0)
    background_wrapper_layout.addWidget(gui.subtitle_background_width_combo, 1, 1)
    gui.subtitle_background_exact_hint = QLabel(
        "Bố cục chuẩn xác cập nhật sau khi hoàn tất chỉnh sửa. Khuyên dùng Ôm sát từng dòng để xem nhanh nhất."
    )
    gui.subtitle_background_exact_hint.setObjectName("subtleHint")
    gui.subtitle_background_exact_hint.setWordWrap(True)
    gui.subtitle_background_exact_hint.setVisible(False)
    background_wrapper_layout.addWidget(gui.subtitle_background_exact_hint, 2, 0, 1, 2)
    gui.subtitle_background_shape_label = QLabel("Hình dạng:")
    gui.subtitle_background_shape_combo = QComboBox()
    gui.subtitle_background_shape_combo.addItem("Hình chữ nhật", "rectangle")
    gui.subtitle_background_shape_combo.setToolTip("Hình dạng nền phụ đề.")
    gui.subtitle_background_shape_label.setVisible(False)
    gui.subtitle_background_shape_combo.setVisible(False)
    background_wrapper_layout.addWidget(gui.subtitle_background_shape_label, 3, 0)
    background_wrapper_layout.addWidget(gui.subtitle_background_shape_combo, 3, 1)
    gui.subtitle_background_padding_spin = ReliableSpinBox()
    gui.subtitle_background_padding_spin.setRange(0, 30)
    gui.subtitle_background_padding_spin.setValue(6)
    gui.subtitle_background_padding_spin.setSuffix(" px")
    background_wrapper_layout.addWidget(QLabel("Khoảng đệm (Padding):"), 4, 0)
    background_wrapper_layout.addWidget(gui.subtitle_background_padding_spin, 4, 1)
    gui.subtitle_background_radius_spin = ReliableSpinBox()
    gui.subtitle_background_radius_spin.setRange(0, 80)
    gui.subtitle_background_radius_spin.setValue(0)
    gui.subtitle_background_radius_spin.setSuffix(" px")
    gui.subtitle_background_radius_spin.setToolTip("Bo tròn các góc của hộp nền phụ đề.")
    background_wrapper_layout.addWidget(QLabel("Bo tròn góc:"), 5, 0)
    background_wrapper_layout.addWidget(gui.subtitle_background_radius_spin, 5, 1)
    background_wrapper_layout.addWidget(QLabel("Màu nền:"), 6, 0)
    background_wrapper_layout.addWidget(gui.subtitle_background_color_btn, 6, 1)
    background_wrapper_layout.addWidget(QLabel("Độ mờ:"), 7, 0)
    background_wrapper_layout.addWidget(gui.subtitle_bg_alpha_spin, 7, 1)
    background_layout.addWidget(background_wrapper)
    subtitle_layout.addWidget(background_card)
    gui.subtitle_background_card = background_card

    timing_grid.addWidget(QLabel("Hiệu ứng:"), 0, 0)
    timing_grid.addWidget(gui.subtitle_animation_combo, 0, 1)
    timing_grid.addWidget(gui.subtitle_animation_time_label, 1, 0)
    timing_grid.addWidget(gui.subtitle_animation_time_spin, 1, 1)
    timing_grid.addWidget(gui.subtitle_karaoke_timing_label, 2, 0)
    timing_grid.addWidget(gui.subtitle_karaoke_timing_combo, 2, 1)

    timing_wrapper_layout.addLayout(timing_grid)
    timing_layout.addWidget(timing_wrapper)
    subtitle_layout.addWidget(timing_card)
    gui.subtitle_timing_card = timing_card

    gui.subtitle_preset_summary_label = QLabel()
    gui.subtitle_preset_summary_label.setObjectName("helperLabel")
    gui.subtitle_preset_summary_label.setWordWrap(True)
    gui.subtitle_preset_summary_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    gui.subtitle_preset_summary_label.setTextInteractionFlags(Qt.NoTextInteraction)
    subtitle_layout.addWidget(gui.subtitle_preset_summary_label)

    gui.subtitle_x_offset_spin = ReliableSpinBox()
    gui.subtitle_x_offset_spin.setRange(-400, 400)
    gui.subtitle_x_offset_spin.setValue(0)
    gui.subtitle_x_offset_spin.hide()

    def _toggle_custom_section(checked: bool):
        gui.custom_settings_toggle_btn.setText(("▼ " if checked else "▶ ") + "Chi tiết kiểu dáng")
        gui.custom_settings_content.setVisible(checked)

    gui.custom_settings_toggle_btn.toggled.connect(_toggle_custom_section)
    style_page.layout().addWidget(subtitle_card)

    audio_mix_card, audio_mix_layout = _build_collapsible_section("Hòa trộn âm thanh (Audio Mix)", start_expanded=True)
    audio_mix_inner_card, audio_mix_inner_layout = _section_card()
    audio_mix_title = QLabel("Mẫu trộn nhanh")
    audio_mix_title.setObjectName("sectionTitle")
    audio_mix_inner_layout.addWidget(audio_mix_title)
    gui.audio_mix_preset_combo = QComboBox()
    gui.audio_mix_preset_combo.addItem("Chỉ nghe âm thanh gốc", "original_only")
    gui.audio_mix_preset_combo.addItem("Ưu tiên âm thanh gốc", "prefer_original")
    gui.audio_mix_preset_combo.addItem("Cân bằng (50/50)", "balanced")
    gui.audio_mix_preset_combo.addItem("Ưu tiên giọng lồng tiếng", "prefer_dub")
    gui.audio_mix_preset_combo.addItem("Chỉ nghe giọng lồng tiếng", "dub_only")
    gui.audio_mix_preset_combo.addItem("Tùy chỉnh", "custom")
    gui.audio_mix_preset_combo.setCurrentIndex(2)
    audio_mix_inner_layout.addWidget(gui.audio_mix_preset_combo)
    gui.audio_mix_preset_hint_label = QLabel("Phím tắt nhanh cho tỷ lệ Âm thanh gốc / Lồng tiếng TTS. Thanh trượt âm lượng bên dưới điều khiển chi tiết.", gui)
    gui.audio_mix_preset_hint_label.setObjectName("helperLabel")
    gui.audio_mix_preset_hint_label.setWordWrap(True)
    audio_mix_inner_layout.addWidget(gui.audio_mix_preset_hint_label)
    audio_mix_layout.addWidget(audio_mix_inner_card)

    audio_tracks_card, audio_tracks_layout = _section_card()
    tracks_title = QLabel("Âm lượng từng kênh")
    tracks_title.setObjectName("sectionTitle")
    audio_tracks_layout.addWidget(tracks_title)

    a1_row = QHBoxLayout()
    a1_label = QLabel("A1 Video gốc")
    a1_label.setMinimumWidth(100)
    a1_row.addWidget(a1_label)
    gui.audio_a1_volume_slider = QSlider(Qt.Horizontal)
    gui.audio_a1_volume_slider.setMinimum(0)
    gui.audio_a1_volume_slider.setMaximum(200)
    gui.audio_a1_volume_slider.setValue(50)
    gui.audio_a1_volume_slider.setTickInterval(50)
    gui.audio_a1_volume_slider.setTickPosition(QSlider.TicksBelow)
    a1_row.addWidget(gui.audio_a1_volume_slider, 1)
    gui.audio_a1_volume_label = QLabel("50%")
    gui.audio_a1_volume_label.setObjectName("helperLabel")
    gui.audio_a1_volume_label.setMinimumWidth(40)
    gui.audio_a1_volume_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    a1_row.addWidget(gui.audio_a1_volume_label)
    audio_tracks_layout.addLayout(a1_row)

    a2_row = QHBoxLayout()
    a2_label = QLabel("TS1 Giọng đọc AI")
    a2_label.setMinimumWidth(100)
    a2_row.addWidget(a2_label)
    gui.audio_a2_volume_slider = QSlider(Qt.Horizontal)
    gui.audio_a2_volume_slider.setMinimum(0)
    gui.audio_a2_volume_slider.setMaximum(200)
    gui.audio_a2_volume_slider.setValue(100)
    gui.audio_a2_volume_slider.setTickInterval(50)
    gui.audio_a2_volume_slider.setTickPosition(QSlider.TicksBelow)
    a2_row.addWidget(gui.audio_a2_volume_slider, 1)
    gui.audio_a2_volume_label = QLabel("100%")
    gui.audio_a2_volume_label.setObjectName("helperLabel")
    gui.audio_a2_volume_label.setMinimumWidth(40)
    gui.audio_a2_volume_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    a2_row.addWidget(gui.audio_a2_volume_label)
    audio_tracks_layout.addLayout(a2_row)

    gui.audio_music_volume_row = QWidget(gui)
    music_row = QHBoxLayout(gui.audio_music_volume_row)
    music_row.setContentsMargins(0, 0, 0, 0)
    music_row.setSpacing(6)
    music_label = QLabel("A2 Nhạc nền")
    music_label.setMinimumWidth(100)
    music_row.addWidget(music_label)
    gui.audio_music_volume_slider = QSlider(Qt.Horizontal)
    gui.audio_music_volume_slider.setMinimum(0)
    gui.audio_music_volume_slider.setMaximum(200)
    gui.audio_music_volume_slider.setValue(30)
    gui.audio_music_volume_slider.setTickInterval(50)
    gui.audio_music_volume_slider.setTickPosition(QSlider.TicksBelow)
    music_row.addWidget(gui.audio_music_volume_slider, 1)
    gui.audio_music_volume_label = QLabel("30%")
    gui.audio_music_volume_label.setObjectName("helperLabel")
    gui.audio_music_volume_label.setMinimumWidth(40)
    gui.audio_music_volume_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    music_row.addWidget(gui.audio_music_volume_label)
    gui.audio_music_volume_row.setVisible(False)
    audio_tracks_layout.addWidget(gui.audio_music_volume_row)

    audio_mix_layout.addWidget(audio_tracks_card)
    audio_page.layout().addWidget(audio_mix_card)

    for page in pages:
        page.layout().addStretch()
        gui.left_panel_stack.addWidget(page)

    # Ẩn tab_bar con 6 nút bên trong vì thanh điều hướng Sidebar Nav 8 icon bên ngoài đã đảm nhiệm
    tab_bar.hide()

    # Tạo Master Stack 8 trang chuyên nghiệp cho Cột bên trái
    gui.left_master_stack = QStackedWidget()
    gui.left_master_stack.setObjectName("leftMasterStack")

    # Trang 0: Media & Batch (Quản lý tệp, Media Pool, Điều khiển hàng loạt tích hợp)
    page_media = QWidget()
    page_media_layout = QVBoxLayout(page_media)
    page_media_layout.setContentsMargins(0, 0, 0, 0)
    page_media_layout.setSpacing(0)
    gui.resource_media_card = _build_resource_media_card(gui)
    page_media_layout.addWidget(gui.resource_media_card, 1)

    # Trang 1: Quy trình TankVideo 5 bước & Thao tác quy trình
    page_workflow = QWidget()
    page_workflow_layout = QVBoxLayout(page_workflow)
    page_workflow_layout.setContentsMargins(0, 0, 0, 0)
    page_workflow_layout.setSpacing(8)
    page_workflow_layout.addWidget(workflow_shell)

    workflow_actions_card = QFrame()
    workflow_actions_card.setObjectName("statusCard")
    workflow_actions_card.setStyleSheet("QFrame#statusCard { background-color: #141820; border: 1px solid #2E323A; border-radius: 8px; }")
    wfa_layout = QVBoxLayout(workflow_actions_card)
    wfa_layout.setContentsMargins(10, 10, 10, 10)
    wfa_layout.setSpacing(8)
    wfa_title = QLabel("Thao tác quy trình")
    wfa_title.setObjectName("sectionTitle")
    wfa_layout.addWidget(wfa_title)
    wfa_layout.addWidget(gui.preview_5s_btn)
    wfa_layout.addWidget(gui.preview_frame_btn)
    wfa_layout.addWidget(gui.open_output_btn)
    page_workflow_layout.addWidget(workflow_actions_card)
    page_workflow_layout.addStretch(1)

    # Nạp 8 trang tương ứng 8 icon ở Sidebar Nav
    gui.left_master_stack.addWidget(page_media)      # 0: media
    gui.left_master_stack.addWidget(page_workflow)   # 1: workflow
    gui.left_master_stack.addWidget(audio_page)      # 2: audio
    gui.left_master_stack.addWidget(style_page)      # 3: subtitle
    gui.left_master_stack.addWidget(language_page)   # 4: translate
    gui.left_master_stack.addWidget(voice_page)      # 5: voice
    gui.left_master_stack.addWidget(media_page)      # 6: framing (Khung hình & Tỷ lệ nền tảng)
    gui.left_master_stack.addWidget(advanced_page)   # 7: advanced

    # Thêm duy nhất gui.left_master_stack vào left_layout, giao diện không còn bị nhồi nhét
    left_layout.addWidget(gui.left_master_stack)

    # Đồng bộ tương thích nếu có code cũ gọi gui.left_panel_stack.setCurrentIndex(...)
    def _on_old_stack_changed(old_idx):
        old_to_master = {0: 6, 1: 2, 2: 4, 3: 5, 4: 3, 5: 7}
        m_idx = old_to_master.get(old_idx)
        if m_idx is not None and gui.left_master_stack.currentIndex() != m_idx:
            gui.left_master_stack.setCurrentIndex(m_idx)
    gui.left_panel_stack.currentChanged.connect(_on_old_stack_changed)


def build_workflow_group(left_layout):
    return None







