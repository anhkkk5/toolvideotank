import os

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .advanced_tabs import build_advanced_group
from .preview_panel import build_preview_panel
from .start_panel import build_start_group


class _TitleBar(QFrame):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._drag_pos = None

    def mousePressEvent(self, event):
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)


def build_main_window_ui(gui):
    central_widget = QWidget()
    central_widget.setObjectName("centralWidget")
    gui.setCentralWidget(central_widget)
    root_layout = QVBoxLayout(central_widget)
    root_layout.setContentsMargins(4, 4, 4, 4)
    root_layout.setSpacing(4)
    gui.root_layout = root_layout

    scroll_area = _build_left_panel(gui)
    root_layout.addWidget(_build_header_bar(gui))

    content_layout = QHBoxLayout()
    content_layout.setSpacing(4)
    gui.content_layout = content_layout
    right_panel = build_preview_panel(gui)

    content_layout.addWidget(scroll_area)
    content_layout.addWidget(right_panel, 1)
    gui.right_panel = right_panel
    root_layout.addLayout(content_layout, 1)

    _connect_ui_signals(gui)
    if hasattr(gui, "left_panel_stack"):
        gui.left_panel_stack.currentChanged.connect(gui.sync_runtime_log_view)
    _initialize_ui_state(gui)
    QTimer.singleShot(0, gui.sync_left_panel_container_width)
    QTimer.singleShot(0, gui.sync_runtime_log_view)
    # Configure the static responsive profile before the editor is shown.
    # The first show event only finalizes geometry that Qt cannot know until
    # the window has a real viewport.
    gui.prepare_responsive_layout()


def _build_header_bar(gui):
    header = _TitleBar()
    header.setObjectName("statusCard")
    layout = QHBoxLayout(header)
    layout.setContentsMargins(10, 4, 10, 4)
    layout.setSpacing(6)
    gui.header_bar = header
    gui.header_layout = layout

    logo_label = QLabel()
    logo_label.setFixedSize(24, 24)
    logo_label.setAlignment(Qt.AlignCenter)
    
    # Ưu tiên logo TankVideo mới
    tank_logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "tankvideo.png")
    actual_logo = tank_logo_path if os.path.exists(tank_logo_path) else getattr(gui, "logo_path", "")
    
    if os.path.exists(actual_logo):
        logo_pixmap = QPixmap(actual_logo)
        if not logo_pixmap.isNull():
            logo_label.setPixmap(logo_pixmap.scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    layout.addWidget(logo_label)
    gui.header_logo_label = logo_label

    brand_label = QLabel()
    brand_label.setObjectName("heroTitle")
    brand_label.setText("<span style='color:#fafafa; font-size:14px; font-weight:900; letter-spacing:0.5px;'>TANK</span><span style='color:#ff7b1a; font-size:14px; font-weight:900; letter-spacing:0.5px;'>VIDEO</span>")
    brand_label.setTextFormat(Qt.RichText)
    layout.addWidget(brand_label)
    gui.header_brand_label = brand_label

    gui.project_title_label = QLabel("📁 Chưa chọn video")
    gui.project_title_label.setObjectName("statusHeadline")
    gui.project_title_label.setStyleSheet(
        "background-color: #141519; border: 1px solid #27282d; border-radius: 4px; "
        "padding: 4px 10px; color: #a1a1aa; font-size: 11px; font-weight: 600;"
    )
    layout.addWidget(gui.project_title_label, 1)

    gui.voice_gender_check_btn = QPushButton("🎙️ Phân vai AI")
    gui.voice_gender_check_btn.setObjectName("secondaryActionBtn")
    gui.voice_gender_check_btn.setMinimumHeight(30)
    gui.voice_gender_check_btn.setMinimumWidth(100)
    gui.voice_gender_check_btn.setToolTip("Đọc phụ đề gốc và phân vai Nam / Nữ bằng AI")
    gui.voice_gender_check_btn.clicked.connect(gui.run_voice_gender_check)
    layout.addWidget(gui.voice_gender_check_btn)

    gui.voice_gender_history_btn = QPushButton("📜 Lịch sử")
    gui.voice_gender_history_btn.setObjectName("secondaryActionBtn")
    gui.voice_gender_history_btn.setMinimumHeight(30)
    gui.voice_gender_history_btn.setMinimumWidth(80)
    gui.voice_gender_history_btn.setToolTip("Mở danh sách các bản Master Data đã lưu")
    gui.voice_gender_history_btn.clicked.connect(gui.open_voice_gender_history)
    layout.addWidget(gui.voice_gender_history_btn)

    gui.pipeline_b_create_btn = QPushButton("⚡ TẠO VIDEO")
    gui.pipeline_b_create_btn.setObjectName("pipelineBActionBtn")
    gui.pipeline_b_create_btn.setMinimumHeight(30)
    gui.pipeline_b_create_btn.setMinimumWidth(120)
    gui.pipeline_b_create_btn.setToolTip("Tạo video tự động từ Master Data đã duyệt (Lồng tiếng AI -> Ducking -> Xuất MP4)")
    gui.pipeline_b_create_btn.setStyleSheet(
        "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6a00, stop:1 #e04800); "
        "color: #fff; font-weight: 700; font-size: 12px; border: none; border-radius: 4px; padding: 5px 12px; } "
        "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7d1a, stop:1 #f05400); }"
    )
    gui.pipeline_b_create_btn.clicked.connect(lambda: getattr(gui, "start_pipeline_b_flow", lambda: None)())
    layout.addWidget(gui.pipeline_b_create_btn)

    gui.run_all_btn.setText("▶ Tạo video")
    gui.run_all_btn.setMinimumHeight(30)
    gui.run_all_btn.setMinimumWidth(110)
    gui.run_all_btn.setToolTip("Chạy toàn bộ quy trình 1 giọng")
    gui.run_all_btn.setStyleSheet(
        "QToolButton { background: #141519; color: #8ad7ff; border: 1px solid #27282d; border-radius: 4px; padding: 5px 10px; font-weight: 600; font-size: 11px; } "
        "QToolButton:hover { background: #1e1f24; color: #fff; border-color: #4ecdc4; }"
    )
    layout.addWidget(gui.run_all_btn)


    gui.export_btn.setText("Export")
    gui.export_btn.setObjectName("secondaryActionBtn")
    gui.export_btn.setMinimumHeight(30)
    layout.addWidget(gui.export_btn)

    gui.preview_5s_btn.setText("Xem nhanh")
    gui.preview_5s_btn.setObjectName("secondaryActionBtn")
    gui.preview_5s_btn.setMinimumHeight(30)
    gui.preview_5s_btn.setMinimumWidth(90)
    gui.preview_5s_btn.setToolTip("Render 5 giây mẫu với đầy đủ phụ đề và mặt nạ")
    layout.addWidget(gui.preview_5s_btn)

    gui.toggle_panel_btn = QPushButton("Control")
    gui.toggle_panel_btn.setObjectName("secondaryActionBtn")
    gui.toggle_panel_btn.setMinimumHeight(30)
    gui.toggle_panel_btn.setVisible(False)
    layout.addWidget(gui.toggle_panel_btn)

    gui.license_btn = QPushButton("👑 VIP")
    gui.license_btn.setObjectName("secondaryActionBtn")
    gui.license_btn.setMinimumHeight(30)
    gui.license_btn.setStyleSheet(
        "QPushButton { background: #1a1510; color: #fbbf24; border: 1px solid #78530a; border-radius: 4px; font-weight: 700; font-size: 11px; padding: 5px 10px; } "
        "QPushButton:hover { background: #241e14; border-color: #fbbf24; color: #fff; }"
    )
    gui.license_btn.setToolTip("Xem thông tin bản quyền")
    gui.license_btn.clicked.connect(lambda: getattr(gui, "open_license_dialog", lambda: None)())
    layout.addWidget(gui.license_btn)

    gui.update_btn = QPushButton("Cập nhật")
    gui.update_btn.setObjectName("secondaryActionBtn")
    gui.update_btn.setMinimumHeight(30)
    gui.update_btn.setToolTip("Kiểm tra và cập nhật phiên bản mới nhất")
    gui.update_btn.clicked.connect(lambda: getattr(gui, "open_update_dialog", lambda: None)())
    layout.addWidget(gui.update_btn)

    gui.more_actions_btn = QPushButton("⚙ ▾")
    gui.more_actions_btn.setObjectName("secondaryActionBtn")
    gui.more_actions_btn.setMinimumHeight(30)
    gui.more_actions_btn.setMinimumWidth(50)
    more_menu = QMenu(gui.more_actions_btn)
    more_menu.setObjectName("headerMoreMenu")

    gui.download_subtitle_action = more_menu.addAction("Export Translated SRT…")
    gui.download_subtitle_action.triggered.connect(gui.download_subtitle)
    gui.download_original_action = more_menu.addAction("Export Source SRT…")
    gui.download_original_action.triggered.connect(gui.download_original_script)
    gui.preview_5s_action = more_menu.addAction("Fast Preview (5 seconds)")
    gui.preview_5s_action.triggered.connect(gui.preview_5s_btn.click)
    more_menu.addSeparator()
    gui.update_action = more_menu.addAction("🚀 Kiểm tra cập nhật...")
    gui.update_action.triggered.connect(lambda: getattr(gui, "open_update_dialog", lambda: None)())
    more_menu.addSeparator()
    gui.clean_project_action = more_menu.addAction("Clean Project")
    gui.clean_project_action.triggered.connect(gui.clean_current_project)
    gui.exit_project_action = more_menu.addAction("Exit to Launcher")
    gui.exit_project_action.triggered.connect(gui.exit_to_launcher)
    gui.settings_action = more_menu.addAction("Settings")
    gui.settings_action.triggered.connect(gui.open_model_settings_dialog)
    gui.more_actions_btn.setMenu(more_menu)
    layout.addWidget(gui.more_actions_btn)
    layout.addSpacing(10)

    gui.titlebar_min_btn = QPushButton("—")
    gui.titlebar_min_btn.setFixedSize(28, 28)
    gui.titlebar_min_btn.setToolTip("Minimize")
    gui.titlebar_min_btn.setStyleSheet("QPushButton { background: transparent; color: #71717a; font-size: 14px; font-weight: bold; border-radius: 4px; border: none; } QPushButton:hover { background: #1e1f24; color: #fff; }")
    gui.titlebar_min_btn.clicked.connect(gui.showMinimized)
    layout.addWidget(gui.titlebar_min_btn)

    gui.titlebar_close_btn = QPushButton("✕")
    gui.titlebar_close_btn.setFixedSize(28, 28)
    gui.titlebar_close_btn.setToolTip("Close")
    gui.titlebar_close_btn.setStyleSheet("QPushButton { background: transparent; color: #71717a; font-size: 13px; font-weight: bold; border-radius: 4px; border: none; } QPushButton:hover { background: #e11d48; color: #fff; }")
    gui.titlebar_close_btn.clicked.connect(gui.close)
    layout.addWidget(gui.titlebar_close_btn)
    return header


def _tint_pixmap(pixmap: QPixmap, color: QColor) -> QPixmap:
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    tinted = QImage(image.size(), QImage.Format_ARGB32)
    tinted.fill(Qt.transparent)

    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            alpha = pixel.alpha()
            if alpha <= 0:
                continue
            pixel.setRed(color.red())
            pixel.setGreen(color.green())
            pixel.setBlue(color.blue())
            pixel.setAlpha(alpha)
            tinted.setPixelColor(x, y, pixel)
    return QPixmap.fromImage(tinted)


class _SidebarNavItem(QFrame):
    def __init__(self, key: str, icon: str, title: str, tooltip: str, on_click=None, parent=None):
        super().__init__(parent)
        self.key = key
        self.on_click = on_click
        self._is_active = False
        self.setFixedSize(54, 48)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 5, 2, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        self.icon_label = QLabel(icon)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("font-size: 15px; background: transparent;")

        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 9px; font-weight: 600; background: transparent;")

        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)
        self._update_style()

    def set_active(self, active: bool):
        self._is_active = active
        self._update_style()

    def _update_style(self, hovering: bool = False):
        if self._is_active:
            self.setStyleSheet(
                "QFrame { background-color: rgba(255, 138, 0, 0.12); "
                "border-left: 3px solid #FF8A00; border-top: none; border-right: none; border-bottom: none; }"
            )
            self.icon_label.setStyleSheet("font-size: 15px; color: #FF8A00; background: transparent;")
            self.title_label.setStyleSheet("font-size: 9px; font-weight: 700; color: #FF8A00; background: transparent;")
        elif hovering:
            self.setStyleSheet(
                "QFrame { background-color: #141822; "
                "border-left: 3px solid transparent; border-top: none; border-right: none; border-bottom: none; }"
            )
            self.icon_label.setStyleSheet("font-size: 15px; color: #E5E7EB; background: transparent;")
            self.title_label.setStyleSheet("font-size: 9px; font-weight: 600; color: #E5E7EB; background: transparent;")
        else:
            self.setStyleSheet(
                "QFrame { background-color: transparent; "
                "border-left: 3px solid transparent; border-top: none; border-right: none; border-bottom: none; }"
            )
            self.icon_label.setStyleSheet("font-size: 15px; color: #8C93A0; background: transparent;")
            self.title_label.setStyleSheet("font-size: 9px; font-weight: 500; color: #8C93A0; background: transparent;")

    def enterEvent(self, event):
        if not self._is_active:
            self._update_style(hovering=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._is_active:
            self._update_style(hovering=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if callable(self.on_click):
                self.on_click(self.key)
        super().mousePressEvent(event)


def _build_nav_sidebar(gui):
    sidebar = QFrame()
    sidebar.setObjectName("navSidebar")
    sidebar.setFixedWidth(56)
    sidebar.setStyleSheet(
        "QFrame#navSidebar { background-color: #0B0F14; border-right: 1px solid #1E232E; }"
    )
    sidebar_layout = QVBoxLayout(sidebar)
    sidebar_layout.setContentsMargins(0, 8, 0, 8)
    sidebar_layout.setSpacing(2)
    sidebar_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

    gui.sidebar_nav_items = {}

    def _select_sidebar_key(key):
        for k, item in gui.sidebar_nav_items.items():
            item.set_active(k == key)

    nav_to_index = {
        "media": 0,
        "workflow": 1,
        "audio": 2,
        "subtitle": 3,
        "translate": 4,
        "voice": 5,
        "framing": 6,
        "advanced": 7,
    }

    def _on_nav_clicked(key):
        _select_sidebar_key(key)
        target_idx = nav_to_index.get(key, 0)
        if hasattr(gui, "left_master_stack"):
            gui.left_master_stack.setCurrentIndex(target_idx)
        scroll_area = getattr(gui, "left_panel_scroll_area", None)
        if scroll_area:
            scroll_area.verticalScrollBar().setValue(0)
        if key == "media" and hasattr(gui, "_refresh_media_pool_ui"):
            gui._refresh_media_pool_ui()

    gui._select_sidebar_key = _select_sidebar_key

    nav_configs = [
        ("media", "📁", "Media", "Quản lý tệp video, ảnh, âm thanh"),
        ("workflow", "⚡", "Quy trình", "Quy trình TankVideo 5 bước"),
        ("audio", "🎵", "Âm thanh", "Hòa trộn âm thanh, kênh A1, TS1, A2"),
        ("subtitle", "💬", "Phụ đề", "Kiểu dáng chữ, font, màu, hiệu ứng"),
        ("translate", "🌐", "Dịch thuật", "Dịch ngôn ngữ phụ đề"),
        ("voice", "🎙️", "Công cụ AI", "Giọng đọc AI & Voice clone"),
        ("framing", "📐", "Khung hình", "Tỷ lệ khung hình & định dạng video"),
        ("advanced", "⚙️", "Nâng cao", "Cài đặt hệ thống, CPU/GPU, tiến trình"),
    ]

    for key, icon, title, tooltip in nav_configs:
        item = _SidebarNavItem(key, icon, title, tooltip, on_click=_on_nav_clicked, parent=sidebar)
        sidebar_layout.addWidget(item)
        gui.sidebar_nav_items[key] = item

    sidebar_layout.addStretch(1)

    # Mặc định kích hoạt tab Media
    _select_sidebar_key("media")
    return sidebar


def _build_left_panel(gui):
    # Khung bao bọc tích hợp thanh icon điều hướng dọc + vùng cuộn nội dung
    left_panel_wrapper = QWidget()
    left_panel_wrapper.setObjectName("leftPanelWrapper")
    left_panel_wrapper.setStyleSheet("QWidget#leftPanelWrapper { background-color: #0B0F14; }")
    wrapper_layout = QHBoxLayout(left_panel_wrapper)
    wrapper_layout.setContentsMargins(0, 0, 0, 0)
    wrapper_layout.setSpacing(0)

    # 1. Sidebar điều hướng dọc (56px) chuẩn giao diện CapCut / Studio chuyên nghiệp
    sidebar = _build_nav_sidebar(gui)
    wrapper_layout.addWidget(sidebar)

    # 2. Vùng cuộn nội dung bên phải sidebar
    scroll_area = QScrollArea()
    gui.left_panel_scroll_area = scroll_area
    scroll_area.setObjectName("leftPanelArea")
    scroll_area.setWidgetResizable(True)
    scroll_area.setMinimumWidth(300)
    scroll_area.setMaximumWidth(520)
    scroll_area.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll_area.setFrameShape(QFrame.NoFrame)

    left_panel_container = QWidget()
    left_panel_container.setObjectName("leftPanelContainer")
    gui.left_panel_container = left_panel_container
    left_layout = QVBoxLayout(left_panel_container)
    left_layout.setContentsMargins(6, 4, 6, 4)
    left_layout.setSpacing(8)
    scroll_area.setWidget(left_panel_container)
    scroll_area.installEventFilter(gui)
    scroll_area.viewport().installEventFilter(gui)
    scroll_area.verticalScrollBar().installEventFilter(gui)

    build_start_group(gui, left_layout)
    build_advanced_group(gui, left_layout)

    # Đồng bộ highlight trên thanh sidebar khi chuyển tab trong master stack
    def _sync_sidebar_from_master_idx(idx):
        idx_to_key = {
            0: "media",
            1: "workflow",
            2: "audio",
            3: "subtitle",
            4: "translate",
            5: "voice",
            6: "framing",
            7: "advanced",
        }
        target_k = idx_to_key.get(idx)
        if target_k and hasattr(gui, "_select_sidebar_key"):
            gui._select_sidebar_key(target_k)

    if hasattr(gui, "left_master_stack"):
        gui.left_master_stack.currentChanged.connect(_sync_sidebar_from_master_idx)
    elif hasattr(gui, "left_panel_stack"):
        gui.left_panel_stack.currentChanged.connect(_sync_sidebar_from_tab_idx)

    wrapper_layout.addWidget(scroll_area, 1)
    gui.left_panel_wrapper = left_panel_wrapper
    return left_panel_wrapper


def _connect_ui_signals(gui):
    gui.extract_btn.clicked.connect(gui.run_extraction)
    gui.vocal_sep_btn.clicked.connect(gui.run_vocal_separation)
    gui.transcribe_btn.clicked.connect(gui.run_transcription)
    gui.import_original_srt_btn.clicked.connect(gui.import_original_srt)
    gui.translate_btn.clicked.connect(gui.run_translation)
    gui.rewrite_translation_btn.clicked.connect(gui.run_rewrite_translation)
    gui.import_translation_btn.clicked.connect(gui.import_translated_srt)
    if hasattr(gui, "normalizer_dict_btn"):
        gui.normalizer_dict_btn.clicked.connect(gui.open_normalizer_dict_dialog)
    gui.preview_btn.clicked.connect(gui.preview_video)
    if hasattr(gui, "reset_framing_btn"):
        gui.reset_framing_btn.clicked.connect(gui.reset_preview_framing)
    if hasattr(gui, "left_panel_stack"):
        gui.left_panel_stack.currentChanged.connect(gui.on_left_panel_workflow_changed)
    gui.output_mode_combo.currentTextChanged.connect(gui.on_output_mode_changed)
    if hasattr(gui, "output_quality_combo"):
        gui.output_quality_combo.currentIndexChanged.connect(gui.refresh_ui_state)
    gui.audio_handling_combo.currentTextChanged.connect(gui.refresh_ui_state)
    if hasattr(gui, "audio_mix_preset_combo"):
        gui.audio_mix_preset_combo.currentIndexChanged.connect(
            gui.on_audio_mix_preset_changed
        )
    if hasattr(gui, "audio_a1_volume_slider"):
        gui.audio_a1_volume_slider.valueChanged.connect(
            gui.on_audio_a1_volume_changed
        )
    if hasattr(gui, "audio_a2_volume_slider"):
        gui.audio_a2_volume_slider.valueChanged.connect(
            gui.on_audio_a2_volume_changed
        )
    if hasattr(gui, "audio_music_volume_slider"):
        gui.audio_music_volume_slider.valueChanged.connect(
            gui.on_audio_music_volume_changed
        )
    if hasattr(gui, "audio_inspector_gain_spin"):
        gui.audio_inspector_gain_spin.valueChanged.connect(
            gui.on_audio_inspector_gain_changed
        )
    if hasattr(gui, "audio_inspector_speed_spin"):
        gui.audio_inspector_speed_spin.valueChanged.connect(
            gui.on_audio_inspector_speed_changed
        )
    if hasattr(gui, "audio_inspector_fade_in_spin"):
        gui.audio_inspector_fade_in_spin.valueChanged.connect(
            gui.on_audio_inspector_fade_in_changed
        )
    if hasattr(gui, "audio_inspector_fade_out_spin"):
        gui.audio_inspector_fade_out_spin.valueChanged.connect(
            gui.on_audio_inspector_fade_out_changed
        )
    if hasattr(gui, "audio_inspector_mute_btn"):
        gui.audio_inspector_mute_btn.toggled.connect(
            gui.on_audio_inspector_mute_toggled
        )
    if hasattr(gui, "audio_inspector_solo_btn"):
        gui.audio_inspector_solo_btn.toggled.connect(
            gui.on_audio_inspector_solo_toggled
        )
    if hasattr(gui, "audio_inspector_regenerate_voice_btn"):
        gui.audio_inspector_regenerate_voice_btn.clicked.connect(
            gui.on_audio_inspector_regenerate_voice_clicked
        )
    if hasattr(gui, "blur_inspector_show_cb"):
        gui.blur_inspector_show_cb.toggled.connect(
            gui.on_blur_inspector_show_toggled
        )
    if hasattr(gui, "preview_speed_combo"):
        gui.preview_speed_combo.currentIndexChanged.connect(gui.on_preview_speed_changed)
    gui.final_output_folder_edit.textChanged.connect(gui.voice_output_folder_edit.setText)
    gui.final_output_folder_edit.textChanged.connect(gui.srt_output_folder_edit.setText)
    gui.video_path_edit.textChanged.connect(gui.refresh_ui_state)
    gui.video_path_edit.textChanged.connect(gui.update_project_header)
    gui.audio_source_edit.textChanged.connect(gui.refresh_ui_state)
    gui.bg_music_edit.textChanged.connect(gui.refresh_ui_state)
    gui.mixed_audio_edit.textChanged.connect(gui.refresh_ui_state)
    gui.use_generated_audio_radio.toggled.connect(gui.on_audio_source_mode_changed)
    if hasattr(gui, "subtitle_single_line_cb"):
        gui.subtitle_single_line_cb.toggled.connect(gui.on_single_line_toggled)
    if hasattr(gui, "subtitle_words_per_segment_spin"):
        gui.subtitle_words_per_segment_spin.valueChanged.connect(lambda _value: gui.on_single_line_toggled(gui.subtitle_single_line_cb.isChecked()))
    gui.use_existing_audio_radio.toggled.connect(gui.on_audio_source_mode_changed)
    gui.blur_area_btn.toggled.connect(gui.toggle_blur_effect_enabled)
    # The visible Blur button creates a timeline-backed B1 layer.  Keeping
    # creation in one path ensures multiple Blur layers receive independent
    # timing, selection, persistence, and preview state.
    gui.blur_add_btn.clicked.connect(lambda: gui.on_add_timeline_layer("blur"))
    gui.ocr_region_btn.clicked.connect(gui.toggle_ocr_overlay_visibility)
    if hasattr(gui, "delogo_region_btn"):
        gui.delogo_region_btn.clicked.connect(gui.toggle_delogo_overlay_visibility)
    if hasattr(gui, "watermark_region_btn"):
        gui.watermark_region_btn.clicked.connect(gui.toggle_watermark_overlay_visibility)
    if hasattr(gui, "ocr_translator_btn"):
        gui.ocr_translator_btn.toggled.connect(gui.toggle_ocr_translator)
    if hasattr(gui, "ocr_translator_overlay"):
        gui.ocr_translator_overlay.captureRequested.connect(gui.capture_ocr_translator_region)
        gui.ocr_translator_overlay.rectChanged.connect(gui._on_ocr_translator_rect_changed)
    if hasattr(gui, "video_view") and hasattr(gui.video_view, "framingChanged"):
        gui.video_view.framingChanged.connect(gui.on_preview_framing_changed)
    gui.transcript_text.textChanged.connect(gui.refresh_ui_state)
    gui.transcript_text.textChanged.connect(gui.schedule_live_subtitle_preview_refresh)
    gui.transcript_text.textChanged.connect(gui.sync_segment_editor_from_hidden_text)
    gui.translated_text.textChanged.connect(gui.refresh_ui_state)
    gui.translated_text.textChanged.connect(gui.schedule_live_subtitle_preview_refresh)
    gui.translated_text.textChanged.connect(gui.sync_segment_editor_from_hidden_text)
    if hasattr(gui, "anchor_inspector_cb"):
        gui.anchor_inspector_cb.toggled.connect(gui.on_anchor_inspector_toggled)
    gui.subtitle_font_combo.currentTextChanged.connect(gui.update_subtitle_preview_style)
    gui.subtitle_font_size_spin.valueChanged.connect(gui.update_subtitle_preview_style)
    if hasattr(gui, "subtitle_font_scale_combo"):
        gui.subtitle_font_scale_combo.currentIndexChanged.connect(gui.on_subtitle_font_scale_changed)
        gui.subtitle_font_size_spin.valueChanged.connect(gui.sync_subtitle_font_scale_control)
    gui.subtitle_animation_combo.currentTextChanged.connect(gui.on_subtitle_animation_changed)
    gui.subtitle_bold_cb.toggled.connect(gui.update_subtitle_preview_style)
    if hasattr(gui, "subtitle_speaker_colors_cb"):
        gui.subtitle_speaker_colors_cb.toggled.connect(gui.update_subtitle_preview_style)
    gui.subtitle_preset_tiktok_radio.toggled.connect(gui.on_subtitle_preset_changed)
    gui.subtitle_preset_youtube_radio.toggled.connect(gui.on_subtitle_preset_changed)
    gui.subtitle_preset_minimal_radio.toggled.connect(gui.on_subtitle_preset_changed)
    gui.subtitle_preset_custom_radio.toggled.connect(gui.on_subtitle_preset_changed)
    gui.subtitle_keyword_highlight_cb.toggled.connect(gui.update_subtitle_preview_style)
    gui.subtitle_highlight_color_combo.currentTextChanged.connect(gui.update_subtitle_preview_style)
    gui.subtitle_highlight_mode_combo.currentTextChanged.connect(gui.update_subtitle_preview_style)
    gui.subtitle_animation_time_spin.valueChanged.connect(gui.update_subtitle_preview_style)
    gui.subtitle_position_mode_combo.currentTextChanged.connect(gui.on_subtitle_position_mode_changed)
    gui.subtitle_align_combo.currentTextChanged.connect(gui.update_subtitle_preview_style)
    gui.subtitle_custom_x_spin.valueChanged.connect(gui.update_subtitle_preview_style)
    gui.subtitle_custom_y_spin.valueChanged.connect(gui.update_subtitle_preview_style)
    gui.subtitle_x_offset_spin.valueChanged.connect(gui.update_subtitle_preview_style)
    gui.subtitle_bottom_offset_spin.valueChanged.connect(gui.update_subtitle_preview_style)
    gui.subtitle_background_cb.toggled.connect(gui.update_subtitle_preview_style)
    if hasattr(gui, "subtitle_outline_cb"):
        gui.subtitle_outline_cb.toggled.connect(gui.update_subtitle_preview_style)
    if hasattr(gui, "subtitle_bg_alpha_spin"):
        gui.subtitle_bg_alpha_spin.valueChanged.connect(gui.update_subtitle_preview_style)
    if hasattr(gui, "subtitle_background_padding_spin"):
        gui.subtitle_background_padding_spin.valueChanged.connect(gui.update_subtitle_preview_style)
    if hasattr(gui, "subtitle_background_radius_spin"):
        gui.subtitle_background_radius_spin.valueChanged.connect(gui.update_subtitle_preview_style)
    if hasattr(gui, "subtitle_background_width_combo"):
        gui.subtitle_background_width_combo.currentIndexChanged.connect(gui.on_subtitle_background_width_changed)
        gui.subtitle_background_shape_combo.currentIndexChanged.connect(gui.update_subtitle_preview_style)

    gui.subtitle_font_combo.currentTextChanged.connect(gui.on_subtitle_style_control_edited)
    gui.subtitle_font_size_spin.valueChanged.connect(gui.on_subtitle_style_control_edited)
    gui.subtitle_animation_combo.currentTextChanged.connect(gui.on_subtitle_style_control_edited)
    gui.subtitle_bold_cb.toggled.connect(gui.on_subtitle_style_control_edited)
    gui.subtitle_keyword_highlight_cb.toggled.connect(gui.on_subtitle_style_control_edited)
    gui.subtitle_highlight_color_combo.currentTextChanged.connect(gui.on_subtitle_style_control_edited)
    gui.subtitle_highlight_mode_combo.currentTextChanged.connect(gui.on_subtitle_style_control_edited)
    gui.subtitle_animation_time_spin.valueChanged.connect(gui.on_subtitle_style_control_edited)
    gui.subtitle_background_cb.toggled.connect(gui.on_subtitle_style_control_edited)
    gui.subtitle_karaoke_timing_combo.currentTextChanged.connect(gui.on_subtitle_style_control_edited)
    if hasattr(gui, "subtitle_outline_cb"):
        gui.subtitle_outline_cb.toggled.connect(gui.on_subtitle_style_control_edited)
    if hasattr(gui, "subtitle_bg_alpha_spin"):
        gui.subtitle_bg_alpha_spin.valueChanged.connect(gui.on_subtitle_style_control_edited)
    if hasattr(gui, "subtitle_background_padding_spin"):
        gui.subtitle_background_padding_spin.valueChanged.connect(gui.on_subtitle_style_control_edited)
    if hasattr(gui, "subtitle_background_radius_spin"):
        gui.subtitle_background_radius_spin.valueChanged.connect(gui.on_subtitle_style_control_edited)
    if hasattr(gui, "subtitle_background_width_combo"):
        gui.subtitle_background_width_combo.currentIndexChanged.connect(gui.on_subtitle_style_control_edited)
        gui.subtitle_background_shape_combo.currentIndexChanged.connect(gui.on_subtitle_style_control_edited)
    if hasattr(gui, "subtitle_single_line_cb"):
        gui.subtitle_single_line_cb.toggled.connect(gui.on_subtitle_style_control_edited)

    # add_layer_btn uses QMenu (connected via actions in preview_panel.py)

    gui.on_advanced_toggled(bool(getattr(gui, "toggle_advanced_btn", None) and gui.toggle_advanced_btn.isChecked()))


def _initialize_ui_state(gui):
    QTimer.singleShot(100, gui.video_view.reposition_subtitle)

    gui.current_segments = []
    gui.current_translated_segments = []
    gui._frame_preview_running = False
    gui._pending_auto_frame_preview = False
    gui._show_dialog_on_frame_preview = False
    gui.auto_frame_preview_timer = QTimer(gui)
    gui.auto_frame_preview_timer.setSingleShot(True)
    gui.auto_frame_preview_timer.setInterval(700)
    gui.auto_frame_preview_timer.timeout.connect(gui.trigger_auto_frame_preview)
    gui.seek_frame_preview_timer = QTimer(gui)
    gui.seek_frame_preview_timer.setSingleShot(True)
    gui.seek_frame_preview_timer.setInterval(300)
    gui.seek_frame_preview_timer.timeout.connect(gui.trigger_seek_frame_preview)
    gui.live_subtitle_preview_timer = QTimer(gui)
    gui.live_subtitle_preview_timer.setSingleShot(True)
    gui.live_subtitle_preview_timer.setInterval(250)
    gui.live_subtitle_preview_timer.timeout.connect(gui.refresh_live_subtitle_preview)
    gui.subtitle_ass_debounce_timer = QTimer(gui)
    gui.subtitle_ass_debounce_timer.setSingleShot(True)
    # Font and size controls can emit many intermediate values while being
    # dragged.  Only the settled value needs an exact libass layout pass.
    gui.subtitle_ass_debounce_timer.setInterval(360)
    gui.subtitle_ass_debounce_timer.timeout.connect(gui._start_deferred_subtitle_ass_build)
    gui.video_filter_preview_timer = QTimer(gui)
    gui.video_filter_preview_timer.setSingleShot(True)
    gui.video_filter_preview_timer.setInterval(350)
    gui.video_filter_preview_timer.timeout.connect(gui.run_live_video_filter_preview)
    # Inspector shell starts collapsed (handle only). The shell expands
    # when the user clicks a track layer or toggles the inspector open.
    gui._inspector_collapsed = True
    gui.last_extracted_audio = ""
    gui.last_vocals_path = ""
    gui.last_music_path = ""
    gui.last_original_srt_path = ""
    gui.last_translated_srt_path = ""
    gui.last_voice_vi_path = ""
    gui.last_mixed_vi_path = ""
    gui.last_preview_video_path = ""
    gui.last_styled_preview_path = ""
    gui.last_styled_preview_signature = ""
    gui.last_exported_video_path = ""
    gui.last_exact_preview_5s_path = ""
    gui.last_exact_preview_frame_path = ""
    gui._preview_video_has_burned_subtitles = False
    # Regular preview uses MPV/libass just like Fast Preview and export. The
    # Qt subtitle widget remains as an invisible drag target only.
    gui._use_libass_live_preview = True
    gui._preview_audio_track_mode = "both"
    gui._mute_original = False
    gui._mute_dubbed = False
    gui._preview_audio_track_switching = False
    gui.live_preview_subtitle_path = ""
    gui.live_preview_ass_path = ""
    gui.live_preview_segments = []
    gui.live_preview_editor_name = ""
    gui._live_preview_signature = None
    gui._styled_preview_running = False
    gui._suspend_live_subtitle_sync = False
    gui._syncing_segment_editor = False
    gui._syncing_hidden_editor_text = False
    gui._segment_editor_rows = []
    gui._selected_segment_index = -1
    # Export-only calibration. Keep it at 1.0 for the authored size; raise
    # it when the burned ASS text needs to match a larger Qt preview.
    gui.subtitle_export_font_scale = 1
    gui.use_exact_subtitle_preview = True

    gui.update_subtitle_preview_style()
    gui.refresh_ui_state()
    gui.on_subtitle_preset_changed()
    gui.on_output_mode_changed(gui.output_mode_combo.currentText())
    gui.update_project_header()
    gui.refresh_ui_state()
    # Restore anchor preference from settings. If user previously had
    # the inspector anchored, keep it open; otherwise start collapsed.
    if gui.is_subtitle_inspector_anchored():
        gui._inspector_collapsed = False
    else:
        gui._inspector_collapsed = True
    gui.set_inspector_collapsed(gui._inspector_collapsed)
    # If collapsed on startup, switch the stack to default (no card) so
    # only the handle is visible.
    if gui._inspector_collapsed and hasattr(gui, "inspector_stack"):
        gui.inspector_stack.setCurrentIndex(2)
    # Sync shell width to current collapsed state
    if hasattr(gui, "_sync_subtitle_inspector_shell_width"):
        try:
            gui._sync_subtitle_inspector_shell_width(visible=not gui._inspector_collapsed)
        except Exception:
            pass
    gui.sync_segment_editor_rows()
    gui.set_controls_panel_visible(False)

