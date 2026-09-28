import sys
import os
import re
import json
import copy
import glob
import hashlib
import shutil
import threading
from uuid import uuid4
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QToolButton, QLabel, QLineEdit,
                             QFileDialog, QTextEdit, QComboBox,
                             QFrame, QProgressBar, QMessageBox,
                             QScrollArea,
                             QColorDialog, QTabWidget, QDialog, QSizePolicy, QInputDialog, QLayout,
                             QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from PySide6.QtCore import Qt, QUrl, QTimer, QSettings, QEvent, Signal, QPoint, QRect
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontInfo, QIcon, QKeySequence, QPixmap, QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

APP_PATH = os.path.join(os.path.dirname(__file__), '..', 'app')
if APP_PATH not in sys.path:
    sys.path.append(APP_PATH)

from dotenv import load_dotenv
_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
if os.path.isfile(_ENV_PATH):
    load_dotenv(_ENV_PATH, override=True)

from services import GUIProjectBridge, ProjectService, ResourceDownloadService, VoiceCatalogService
from controllers import PipelineController, PreviewController, SubtitleController
from helpers import (
    build_guidance_state,
    build_preview_context_text,
    build_workflow_hint,
    extract_subtitle_text_entries,
    format_segments_to_srt,
    format_timestamp,
    get_export_button_label,
    get_output_mode_key,
    parse_srt_to_segments,
    validate_srt_text,
)
from new_highlight_selector import auto_select_matches
from video_processor import srt_to_ass
from audio_mixer import ffprobe_wav_duration
from utils.display_utils import (
    cleanup_temp_preview_files as cleanup_temp_preview_files_impl,
    clear_log as clear_log_impl,
    log_message as log_message_impl,
    show_error as show_error_impl,
    show_frame_preview_dialog as show_frame_preview_dialog_impl,
    show_processed_files as show_processed_files_impl,
)
from utils.file_dialog_utils import (
    browse_audio_folder as browse_audio_folder_impl,
    browse_audio_source as browse_audio_source_impl,
    browse_background_audio as browse_background_audio_impl,
    browse_existing_mixed_audio as browse_existing_mixed_audio_impl,
    browse_srt_output_folder as browse_srt_output_folder_impl,
    browse_voice_output_folder as browse_voice_output_folder_impl,
    cleanup_file_if_exists as cleanup_file_if_exists_impl,
    open_folder as open_folder_impl,
)
from utils.icon_utils import load_icon
from utils.media_utils import (
    browse_video as browse_video_impl,
    duration_changed as duration_changed_impl,
    position_changed as position_changed_impl,
    refresh_video_dimensions as refresh_video_dimensions_impl,
    set_position as set_position_impl,
    setup_media_player as setup_media_player_impl,
    stop_video as stop_video_impl,
    toggle_play as toggle_play_impl,
    update_duration_label as update_duration_label_impl,
    update_frame_preview_thumbnail as update_frame_preview_thumbnail_impl,
)
from utils.settings_utils import load_user_settings as load_user_settings_impl, save_user_settings as save_user_settings_impl
from views import build_main_window_ui
from widgets.progress_dialog import BackgroundableProgressDialog
from widgets.spin_boxes import ReliableDoubleSpinBox
from widgets.subtitle_editor_dialog import SubtitleEditorDialog
from runtime_paths import app_path, asset_path, bundle_root, models_path, workspace_root
from runtime_profile import is_remote_profile
from worker_adapters import (
    ExtractionWorker,
    ResourceDownloadWorker,
    OcrTranslatorCaptureWorker,
    OcrTranslatorTranslationWorker,
    SegmentAudioPreviewWorker,
    VoiceSamplePreviewWorker,
    VocalSeparationWorker,
    VoiceOverWorker,
    VoiceGenderCheckWorker,
    TimelineThumbnailWorker,
    TimelineWaveformWorker,
    AlternateRangeTranscriptionWorker,
)

# Import our backend modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'app'))
from video_processor import get_video_dimensions
from workflows.voice_workflow import predict_speed_ratios
from audio_mixer import mix_voice_with_background


def _default_asr_engine() -> str:
    return "ocr"


class _BootstrapMediaBackend:
    backend_name = "bootstrap"
    _source_path = ""

    def setSource(self, source):
        self._source_path = ""

    def play(self):
        return None

    def pause(self):
        return None

    def stop(self):
        return None

    def setPosition(self, position):
        return None

    def position(self):
        return 0

    def duration(self):
        return 0

    def playbackState(self):
        return QMediaPlayer.StoppedState

    def is_playing(self):
        return False

    def set_subtitle_file(self, subtitle_path, subtitle_style=None):
        return None

    def clear_subtitle(self):
        return None

    def set_audio_file(self, audio_path):
        return None

    def clear_audio(self):
        return None

    def set_original_audio_file(self, audio_path):
        return None

    def _clear_original_audio(self):
        return None

    def set_blur_region(self, blur_region=None):
        return None

    def clear_blur_region(self):
        return None

    def set_volume(self, percent):
        return None

    def volume(self):
        return 100

    def set_muted(self, muted):
        return None

    def is_muted(self):
        return False

    def set_mute_original(self, muted):
        return None

    def set_mute_dubbed(self, muted):
        return None

    def is_original_muted(self):
        return False

    def is_dubbed_muted(self):
        return False

    def set_original_volume(self, percent):
        return None

    def set_dubbed_volume(self, percent):
        return None

    def original_volume(self):
        return 100

    def dubbed_volume(self):
        return 100

    def set_playback_rate(self, rate):
        return None

    def playback_rate(self):
        return 1.0


_WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, _WORKSPACE_ROOT)

try:
    from main_window_parts.voice_gender_mixin import VoiceGenderMixin
except ImportError:
    from ui.main_window_parts.voice_gender_mixin import VoiceGenderMixin


try:
    from main_window_parts.project_settings_mixin import ProjectSettingsMixin
except ImportError:
    from ui.main_window_parts.project_settings_mixin import ProjectSettingsMixin


try:
    from main_window_parts.video_filter_export_mixin import VideoFilterExportMixin
except ImportError:
    from ui.main_window_parts.video_filter_export_mixin import VideoFilterExportMixin
try:
    from main_window_parts.tts_voiceover_mixin import TtsVoiceoverMixin
except ImportError:
    from ui.main_window_parts.tts_voiceover_mixin import TtsVoiceoverMixin
try:
    from main_window_parts.ocr_subtitle_mixin import OcrSubtitleMixin
except ImportError:
    from ui.main_window_parts.ocr_subtitle_mixin import OcrSubtitleMixin
try:
    from main_window_parts.media_playback_mixin import MediaPlaybackMixin
except ImportError:
    from ui.main_window_parts.media_playback_mixin import MediaPlaybackMixin
try:
    from main_window_parts.layer_inspector_mixin import LayerInspectorMixin
except ImportError:
    from ui.main_window_parts.layer_inspector_mixin import LayerInspectorMixin
try:
    from main_window_parts.voice_dubbing_mixin import VoiceDubbingMixin
except ImportError:
    from ui.main_window_parts.voice_dubbing_mixin import VoiceDubbingMixin







class VideoTranslatorGUI(QMainWindow, VoiceGenderMixin, ProjectSettingsMixin, VideoFilterExportMixin, TtsVoiceoverMixin, OcrSubtitleMixin, MediaPlaybackMixin, LayerInspectorMixin, VoiceDubbingMixin):
    VOICE_ENTRY_ID_ROLE = Qt.UserRole + 1
    runtime_log_received = Signal(str)
    subtitle_ass_ready = Signal(int, str, str, object)

    def __init__(self):
        super().__init__()
        self._current_video_path = ""
        title = "TankVideo - AI Video Dubbing & Translation Studio"
        if is_remote_profile():
            title += " (Remote)"
        self.setWindowTitle(title)
        self.settings = QSettings("TankVideo", "VideoTranslatorGUI")
        self.setAcceptDrops(True)
        tank_logo = asset_path("tankvideo.png")
        self.logo_path = tank_logo if os.path.exists(tank_logo) else asset_path("tankvideo.ico")
        if os.path.exists(self.logo_path):
            self.setWindowIcon(QIcon(self.logo_path))
        self.setWindowFlag(Qt.FramelessWindowHint)
        
        # Start maximized, but keep the window genuinely resizable.
        self.setWindowState(Qt.WindowMaximized)
        self.setMinimumSize(1024, 640)
        self._responsive_layout_pending = False
        self._responsive_layout_mode = "desktop"
        self._initial_layout_finalized = False
        
        # Stylesheet – CapCut-inspired compact dark theme (Orange accent #ff7b1a)
        self.setStyleSheet("""
            /* ───── Base ───── */
            QMainWindow { background-color: #0d0e10; }
            QWidget { color: #d4d4d8; font-family: 'Segoe UI', 'Inter', 'Noto Sans', Arial, sans-serif; font-size: 12px; }
            #centralWidget { background-color: #0d0e10; }

            /* ───── Panels ───── */
            #leftPanelArea { background-color: #141519; border-right: 1px solid #232529; }
            #leftPanelContainer { background-color: #141519; }
            #rightPanel { background-color: #0d0e10; }

            /* ───── Cards ───── */
            QGroupBox { border: none; border-radius: 0; margin-top: 0; font-weight: 600; color: #e4e4e7; background: transparent; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #ff7b1a; font-size: 11px; }
            QFrame#heroCard, QFrame#statusCard, QFrame#sideInfoCard {
                background-color: #18191d; border: 1px solid #27282d; border-radius: 6px;
            }
            QFrame#audioSourcePanel { background-color: #1a1b20; border: 1px solid #2a2b30; border-radius: 6px; }
            QLabel#audioSourceTitle { color: #e4e4e7; font-weight: 700; font-size: 12px; }

            /* ───── Inspector Handle ───── */
            QFrame#subtitleInspectorHandle { background-color: #18191d; border: 1px solid #27282d; border-left: none; border-top-right-radius: 6px; border-bottom-right-radius: 6px; }
            QPushButton#subtitleInspectorHandleBtn { background-color: #1e1f24; color: #ff7b1a; border: 1px solid #333; border-right: none; border-radius: 0; font-size: 18px; font-weight: 900; padding: 0; }
            QPushButton#subtitleInspectorHandleBtn:hover { background-color: #28292f; border-color: #ff7b1a; }

            /* ───── Typography ───── */
            QLabel#heroTitle { font-size: 16px; font-weight: 800; color: #fafafa; }
            QLabel#heroBody, QLabel#statusBody, QLabel#helperLabel, QLabel#previewContextLabel { color: #8b8b92; font-size: 11px; }
            QLabel#helperLabel[filterModified="true"] { color: #ff7b1a; font-weight: 700; }
            QLabel#sectionTitle { font-size: 11px; font-weight: 700; color: #ff7b1a; }
            QLabel#timingChip { background-color: #1e1f24; color: #ff944d; border: 1px solid #333; border-radius: 10px; padding: 2px 8px; font-size: 10px; font-weight: 700; }
            QLabel#statusHeadline { font-size: 13px; font-weight: 700; color: #fafafa; }
            QLabel#statusPill { background-color: #241c12; color: #ff9d42; border: 1px solid #4a3018; border-radius: 10px; padding: 2px 8px; font-size: 10px; font-weight: 700; }
            QLabel#statusChip { background-color: #1a1b20; color: #a1a1aa; border: 1px solid #2a2b30; border-radius: 10px; padding: 2px 8px; font-size: 10px; font-weight: 600; }
            QLabel#statusChip[state="ok"] { background-color: #0f1f14; color: #4ade80; border-color: #166534; }
            QLabel#statusChip[state="running"] { background-color: #241c12; color: #f59e0b; border-color: #854d0e; }
            QLabel#statusChip[state="na"] { background-color: #141519; color: #52525b; border-color: #27282d; }
            QLabel#statusChip[state="pending"] { background-color: #1a1b20; color: #a1a1aa; border-color: #2a2b30; }
            QLabel { background: transparent; color: #a1a1aa; font-size: 11px; }

            /* ───── Buttons ───── */
            QPushButton {
                background-color: #1e1f24; color: #d4d4d8; border: 1px solid #333;
                border-radius: 4px; padding: 5px 10px; font-weight: 600; font-size: 11px;
            }
            QPushButton:hover { background-color: #28292f; border-color: #ff7b1a; color: #fff; }
            QPushButton:pressed { background-color: #151618; }
            QPushButton:disabled { background-color: #141519; color: #52525b; border-color: #222; }

            QPushButton#mainActionBtn, QToolButton#mainActionBtn {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff6a00,stop:1 #e04800);
                color: #fff; border: none; border-radius: 4px; font-size: 12px; font-weight: 700; padding: 6px 14px;
            }
            QPushButton#mainActionBtn:hover, QToolButton#mainActionBtn:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff7d1a,stop:1 #f05400);
            }
            QToolButton#mainActionBtn::menu-indicator { image: none; width: 0; }

            QPushButton#secondaryActionBtn {
                background-color: #1e1f24; color: #d4d4d8; border: 1px solid #333;
                border-radius: 4px; font-size: 11px; font-weight: 600; padding: 5px 10px;
            }
            QPushButton#secondaryActionBtn:hover { background-color: #28292f; border-color: #ff7b1a; color: #fff; }
            QPushButton#secondaryActionBtn::menu-indicator { width: 0; image: none; }

            QPushButton#pipelineBActionBtn {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff6a00,stop:1 #e04800);
                color: #fff; border: none; border-radius: 4px; font-size: 12px; font-weight: 700; padding: 6px 14px;
            }
            QPushButton#pipelineBActionBtn:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff7d1a,stop:1 #f05400);
            }

            /* ───── Workflow Tabs ───── */
            QPushButton#workflowTabBtn { background-color: #18191d; color: #71717a; border: 1px solid #27282d; border-radius: 4px; padding: 4px 8px; font-size: 10px; font-weight: 700; }
            QPushButton#workflowTabBtn:hover { background-color: #1e1f24; border-color: #3f3f46; color: #a1a1aa; }
            QPushButton#workflowTabBtn:checked { background-color: #2a1a0e; color: #ff9d42; border-color: #ff7b1a; }
            QStackedWidget#leftPanelStack { background: transparent; }

            /* ───── Inputs ───── */
            QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #141519; border: 1px solid #27282d; border-radius: 4px; color: #e4e4e7; padding: 5px 8px; font-size: 11px;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #ff7b1a; }
            QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { background-color: #111114; color: #52525b; border-color: #1e1f24; }
            QLineEdit::placeholder, QTextEdit { selection-background-color: #ff6a00; }
            QComboBox QAbstractItemView { background-color: #18191d; color: #e4e4e7; selection-background-color: #ff6a00; border: 1px solid #333; outline: none; }
            QComboBox::drop-down { border: none; width: 20px; }

            /* ───── Segment Inspector ───── */
            QScrollArea#segmentEditorScroll { background-color: transparent; border: none; }
            QWidget#segmentEditorContainer { background-color: transparent; }
            QFrame#segmentInspectorCard { background-color: #18191d; border: 1px solid #27282d; border-radius: 0; }
            QTextEdit#segmentInspectorEditor { background-color: #141519; border: 1px solid #27282d; border-radius: 4px; padding: 6px 8px; }
            QTextEdit#segmentInspectorEditor:focus { border-color: #ff7b1a; background-color: #17181d; }

            /* ───── Progress ───── */
            QProgressBar { border: 1px solid #27282d; border-radius: 3px; text-align: center; background-color: #141519; color: #fff; font-size: 10px; max-height: 6px; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff7b1a,stop:1 #e04800); border-radius: 3px; }

            /* ───── Checkboxes / Radios ───── */
            QCheckBox { background: transparent; color: #a1a1aa; spacing: 6px; }
            QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #3f3f46; border-radius: 3px; background: #141519; }
            QCheckBox::indicator:checked { background: #ff7b1a; border-color: #ff7b1a; }
            QRadioButton { background: transparent; color: #a1a1aa; }

            /* ───── ScrollArea / ScrollBar ───── */
            QScrollArea { border: none; background-color: #141519; }
            QScrollBar:vertical { border: none; background: #111114; width: 8px; margin: 0; }
            QScrollBar::handle:vertical { background: #333; min-height: 30px; border-radius: 4px; }
            QScrollBar::handle:vertical:hover { background: #ff7b1a; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { border: none; background: #111114; height: 8px; margin: 0; }
            QScrollBar::handle:horizontal { background: #333; min-width: 30px; border-radius: 4px; }
            QScrollBar::handle:horizontal:hover { background: #ff7b1a; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

            /* ───── Menus ───── */
            QMenu#headerMoreMenu, QMenu#generateMenu, QMenu#generateStepMenu {
                background-color: #18191d; color: #d4d4d8; border: 1px solid #333; padding: 4px; border-radius: 6px;
            }
            QMenu#headerMoreMenu::item, QMenu#generateMenu::item, QMenu#generateStepMenu::item {
                background: transparent; color: #d4d4d8; padding: 6px 12px; border-radius: 4px;
            }
            QMenu#generateStepMenu::item:enabled { background-color: #1e1f24; color: #e4e4e7; border: 1px solid #333; font-weight: 700; }
            QMenu#generateStepMenu::item:disabled { background-color: #141519; color: rgba(113,113,122,0.6); border: 1px solid #1e1f24; }
            QMenu#headerMoreMenu::item:selected, QMenu#generateMenu::item:selected, QMenu#generateStepMenu::item:selected { background-color: #ff6a00; color: #fff; }
            QMenu#generateStepMenu::item:disabled:selected { background-color: #141519; color: rgba(113,113,122,0.6); }
            QMenu#headerMoreMenu::separator, QMenu#generateMenu::separator, QMenu#generateStepMenu::separator { height: 1px; background: #27282d; margin: 4px 6px; }

            /* ───── Message Box ───── */
            QMessageBox { background-color: #18191d; }
            QMessageBox QLabel { color: #e4e4e7; background: transparent; }
            QMessageBox QPushButton { min-width: 80px; }

            /* ───── Tabs ───── */
            QTabWidget::pane { border: 1px solid #27282d; border-radius: 4px; background: #141519; top: -1px; }
            QTabBar::tab { background: #18191d; color: #71717a; padding: 6px 12px; border: 1px solid #27282d; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; min-width: 80px; font-size: 11px; }
            QTabBar::tab:selected { background: #141519; color: #ff7b1a; border-top: 2px solid #ff7b1a; }
            QTabBar::tab:hover:!selected { color: #d4d4d8; background: #1e1f24; }

            /* ───── Splitters ───── */
            QSplitter::handle { background: #1e1f24; }
            QSplitter::handle:hover { background: #ff7b1a; }
            QSplitter#workspaceSplitter::handle { background: #1e1f24; margin: 0 1px; }
            QSplitter#workspaceSplitter::handle:hover { background: #ff7b1a; }
            QSplitter#previewTimelineSplitter::handle { background: #1e1f24; margin: 1px 0; }
            QSplitter#previewTimelineSplitter::handle:hover { background: #ff7b1a; }

            /* ───── Slider ───── */
            QSlider::groove:horizontal { border: none; height: 4px; background: #27282d; border-radius: 2px; }
            QSlider::handle:horizontal { background: #ff7b1a; border: none; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
            QSlider::handle:horizontal:hover { background: #ff944d; }
            QSlider::sub-page:horizontal { background: #ff7b1a; border-radius: 2px; }

            /* ───── Table/Header ───── */
            QHeaderView::section { background: #18191d; color: #a1a1aa; border: none; border-bottom: 1px solid #27282d; padding: 4px 8px; font-weight: 600; font-size: 11px; }
            QTableWidget { background: #141519; alternate-background-color: #18191d; gridline-color: #27282d; border: 1px solid #27282d; }
            QTableWidget::item { padding: 4px; }
            QTableWidget::item:selected { background: #2a1a0e; color: #ff9d42; }
        """)


        # -----------------------------
        # State (must exist before setup_ui)
        # -----------------------------
        # Track generated/selected artifacts for quick inspection.
        # Keys are stable IDs, values are absolute file paths.
        self.processed_artifacts = {}
        self._runtime_logs = []
        self._pending_runtime_log_entries = []
        self._runtime_log_view_entry_count = 0
        self._runtime_log_flush_timer = QTimer(self)
        self._runtime_log_flush_timer.setSingleShot(True)
        self._runtime_log_flush_timer.setInterval(100)
        self._runtime_log_flush_timer.timeout.connect(self._flush_runtime_log_entries)
        self._editor_highlight_chunks = {}
        self._editor_highlight_state = {}
        self.runtime_log_received.connect(self._append_runtime_log_entry)
        self.workspace_root = workspace_root()
        self._cleanup_temp_root()
        self.project_service = ProjectService(self.workspace_root)
        self.project_bridge = GUIProjectBridge(self.project_service)
        self.voice_catalog_service = VoiceCatalogService(self.workspace_root)
        self.subtitle_controller = SubtitleController(self)
        self.pipeline_controller = PipelineController(self)
        self.preview_controller = PreviewController(self)
        self.current_project_state = None
        # Do not inherit a legacy global Subtitle Source from .env.  Opening
        # a project below will replace this with that project's own setting.
        os.environ["TRANSCRIPTION_ENGINE"] = _default_asr_engine()
        self.current_segment_models = []
        self.current_translated_segment_models = []
        self.selected_whisper_model_name = "auto"
        self._last_audio_preview_path = ""
        self._segment_preview_threads = {}
        self._voice_sample_preview_thread = None
        self._voiceover_force_refresh = False
        self.voice_catalog_entries_all = []
        self.voice_catalog_entries = []

        self.voice_catalog_map = {}
        self._voice_signals_bound = False
        self._media_backend_ready = False
        self._blur_region_signal_bound = False
        self._blur_edit_finished_signal_bound = False
        self._preview_audio_signals_bound = False
        self.media_player = _BootstrapMediaBackend()
        self.voice_preview_dialog = None
        self._voice_preview_row_buttons = {}
        self._tracked_progress_dialogs = []
        self._timeline_timing_undo_stack = []
        self._timeline_timing_redo_stack = []
        self._suspend_timeline_undo = False
        self._timeline_waveform_cache_key = None
        self._timeline_waveform_samples = []
        self._timeline_waveform_duration_s = 0.0
        self._timeline_waveform_worker = None
        self._desired_timeline_waveform_request = None
        self._timeline_video_thumb_cache_key = None
        self._timeline_video_thumbnails = []
        self._timeline_thumbnail_worker = None
        self._desired_timeline_thumbnail_request = None
        self._pending_timeline_waveform_refresh = False
        self._pending_timeline_thumbnail_refresh = False
        self._allow_post_pipeline_preview_assets = False
        self._subtitle_custom_style_state = None
        self._subtitle_preset_apply_in_progress = False
        # Exact full-block subtitle backgrounds are measured by libass.  Keep
        # that expensive work out of the GUI thread; the active ASS track is
        # intentionally retained until the newest debounced result is ready.
        self._subtitle_ass_request_token = 0
        self._subtitle_ass_worker_running = False
        self._subtitle_ass_worker_threads = []
        self._subtitle_ass_pending_snapshot = None
        self.subtitle_ass_ready.connect(self._on_async_subtitle_ass_ready)
        self._video_filter_ui_sync = False
        self._video_filter_preset_key = "original"
        self._video_filter_intensity = 75
        self._video_filter_adjust_overrides = {
            "brightness": 0,
            "contrast": 0,
            "saturation": 0,
            "temperature": 0,
            "highlights": 0,
            "shadows": 0,
        }
        self._video_filter_user_modified = {
            "brightness": False,
            "contrast": False,
            "saturation": False,
            "temperature": False,
            "highlights": False,
            "shadows": False,
        }
        self._pending_video_filter_preview = False
        self._filter_thumbnail_visible = False
        self._filter_preview_blur_was_checked = False
        self._filter_preview_ocr_was_editable = False
        self._suspend_ocr_overlay = False
        self._ocr_overlay_visible = True
        self._ocr_translator_active = False
        self._ocr_translator_rect = (0.2, 0.2, 0.6, 0.25)
        self._ocr_translator_capture_worker = None
        self._ocr_translator_translation_worker = None
        self._play_video_filter_preview_when_ready = False
        self._filter_thumbnail_target_height = 320
        self._video_filter_preview_dirty = False
        self._video_filter_apply_requested = False
        self._blur_edit_finish_syncing = False
        self._blur_region_preview_dirty = False
        # Blur/Mask are MPV filter effects. During a paused geometry edit we
        # suppress only the active layer from the filter graph so an old,
        # stale effect is never left behind the lightweight edit overlay.
        self._deferred_effect_edit_type = ""
        self._deferred_effect_edit_layer_id = ""
        # A selected layer becomes editable only after an explicit paused
        # selection.  Playback and its pause transition never implicitly
        # restore edit chrome for the previously selected layer.
        self._preview_edit_layer_id = ""
        self._review_mode_active = False
        # Overlay drags can emit dozens of events per second.  Persisting the
        # full project/timeline for each one causes synchronous JSON and
        # project-file writes on the UI thread, so collect rapid edits and
        # save their final state shortly after interaction settles.
        self._pending_timeline_persist = False
        self._pending_mask_state_persist = False
        self._pending_blur_state_persist = False
        self._timeline_persist_timer = QTimer(self)
        self._timeline_persist_timer.setSingleShot(True)
        self._timeline_persist_timer.setInterval(180)
        self._timeline_persist_timer.timeout.connect(self._flush_pending_timeline_persist)
        # Simple pipeline runner (Run All)
        self._pipeline_active = False
        self._pipeline_step = ""

        # Pre-rendered video state
        self.last_preview_video_path = ""
        self.last_styled_preview_path = ""
        self.last_styled_preview_signature = ""
        self.last_exact_preview_5s_path = ""

        self._deferred_startup_stage1_done = False
        self._deferred_startup_stage2_done = False

        self.setup_ui()
        self._configure_local_voice_mode_ui()
        self._timeline_visual_refresh_timer = QTimer(self)
        self._timeline_visual_refresh_timer.setSingleShot(True)
        self._timeline_visual_refresh_timer.timeout.connect(self._run_pending_timeline_visual_refresh)
        QTimer.singleShot(0, self._run_deferred_startup_stage1)
        QTimer.singleShot(600, self._run_deferred_startup_stage2)








    def setup_ui(self):
        build_main_window_ui(self)
        self._setup_editor_shortcuts()
        self.sync_license_header_status()
        self.check_update_quietly()

    def open_update_dialog(self):
        from ui.dialogs.update_dialog import UpdateDialog
        root = getattr(self, "workspace_root", None) or os.getcwd()
        info = getattr(self, "_cached_update_info", None)
        is_mand = bool(info and info.get("has_update"))
        dlg = UpdateDialog(self, workspace_root=root, mandatory=is_mand, preloaded_info=info)
        dlg.exec()

    def check_update_quietly(self):
        import threading
        def _bg():
            try:
                from app.services.update_service import UpdateService
                root = getattr(self, "workspace_root", None) or os.getcwd()
                res = UpdateService(root).check_for_updates(timeout=8.0)
                if res.get("has_update"):
                    latest = str(res.get("latest_version", "") or "")
                    self._cached_update_info = res
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, lambda: self._notify_update_available(latest))
                    QTimer.singleShot(1000, lambda: self._prompt_mandatory_update(res))
            except Exception:
                pass
        threading.Thread(target=_bg, daemon=True).start()

    def _prompt_mandatory_update(self, info: dict):
        from ui.dialogs.update_dialog import UpdateDialog
        root = getattr(self, "workspace_root", None) or os.getcwd()
        dlg = UpdateDialog(self, workspace_root=root, mandatory=True, preloaded_info=info)
        dlg.exec()

    def _notify_update_available(self, latest_ver: str):
        if hasattr(self, "update_btn"):
            self.update_btn.setText(f"🔥 Có bản {latest_ver}")
            self.update_btn.setStyleSheet(
                "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7b1a, stop:1 #e04800); "
                "color: #ffffff; border: 1px solid #ff9d42; border-radius: 8px; font-weight: 800; padding: 6px 14px; font-size: 11px; } "
                "QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff8c33, stop:1 #f05400); }"
            )

    def open_license_dialog(self):
        from ui.dialogs.login_license_dialog import LoginLicenseDialog
        root = getattr(self, "workspace_root", None) or os.getcwd()
        dlg = LoginLicenseDialog(self, workspace_root=root)
        dlg.exec()
        self.sync_license_header_status()

    def sync_license_header_status(self):
        from app.services.license_service import LicenseService
        root = getattr(self, "workspace_root", None) or os.getcwd()
        svc = LicenseService(root)
        st = svc.get_license_status()
        if hasattr(self, "license_btn"):
            if st["licensed"]:
                days = st.get("days_left", 0)
                self.license_btn.setText(f"👑 VIP ({days} ngày)")
                self.license_btn.setStyleSheet(
                    "QPushButton { background: #132a1e; color: #3ddc97; border: 1px solid #238636; border-radius: 8px; font-weight: bold; padding: 6px 12px; } "
                    "QPushButton:hover { background: #1e3f2e; color: #fff; border-color: #3fb950; }"
                )
            else:
                self.license_btn.setText("⚠️ Chưa kích hoạt")
                self.license_btn.setStyleSheet(
                    "QPushButton { background: #2d1818; color: #ff7b72; border: 1px solid #da3633; border-radius: 8px; font-weight: bold; padding: 6px 12px; } "
                    "QPushButton:hover { background: #422020; color: #fff; border-color: #f85149; }"
                )

    def _setup_editor_shortcuts(self):
        from PySide6.QtGui import QShortcut, QKeySequence
        from PySide6.QtCore import Qt

        # Ctrl+B: Tách đoạn tại playhead
        self.split_shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self.split_shortcut.activated.connect(self.split_selected_timeline_segment)

        # Delete & Backspace: Xóa đối tượng đang chọn
        self.delete_shortcut = QShortcut(QKeySequence.Delete, self)
        self.delete_shortcut.activated.connect(self._on_delete_shortcut)
        self.backspace_shortcut = QShortcut(QKeySequence(Qt.Key_Backspace), self)
        self.backspace_shortcut.activated.connect(self._on_delete_shortcut)

        # Shift+Delete: Ripple Delete
        self.ripple_delete_shortcut = QShortcut(QKeySequence("Shift+Delete"), self)
        self.ripple_delete_shortcut.activated.connect(self.ripple_delete_selected_timeline_segment)

        # Ctrl+Z: Hoàn tác
        self.undo_shortcut = QShortcut(QKeySequence.Undo, self)
        self.undo_shortcut.activated.connect(self.undo_last_timeline_timing_edit)

        # Redo: Ctrl+Shift+Z và Ctrl+Y
        self.redo_shortcut = QShortcut(QKeySequence.Redo, self)
        self.redo_shortcut.activated.connect(self.redo_last_timeline_timing_edit)
        self.redo_y_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_y_shortcut.activated.connect(self.redo_last_timeline_timing_edit)
        self.redo_sz_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self.redo_sz_shortcut.activated.connect(self.redo_last_timeline_timing_edit)

        # Space: Phát / Tạm dừng xem trước
        self.space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.space_shortcut.activated.connect(self._on_space_shortcut)

        # Phím mũi tên Left/Right: Di chuyển Playhead
        self.left_shortcut = QShortcut(QKeySequence(Qt.Key_Left), self)
        self.left_shortcut.activated.connect(lambda: self._nudge_playhead(-0.1))
        self.right_shortcut = QShortcut(QKeySequence(Qt.Key_Right), self)
        self.right_shortcut.activated.connect(lambda: self._nudge_playhead(0.1))
        self.shift_left_shortcut = QShortcut(QKeySequence("Shift+Left"), self)
        self.shift_left_shortcut.activated.connect(lambda: self._nudge_playhead(-1.0))
        self.shift_right_shortcut = QShortcut(QKeySequence("Shift+Right"), self)
        self.shift_right_shortcut.activated.connect(lambda: self._nudge_playhead(1.0))

    def _on_space_shortcut(self):
        focus = QApplication.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return
        if hasattr(self, "toggle_play"):
            self.toggle_play()

    def _on_delete_shortcut(self):
        focus = QApplication.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return
        self.delete_selected_timeline_segment()




    def prepare_responsive_layout(self):
        """Apply only the target-screen responsive profile while hidden."""
        screen = self.screen() or QApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen is not None else None
        if geometry is None:
            self.apply_responsive_layout()
            return
        self.apply_responsive_layout(geometry.width(), geometry.height())

    def prepare_initial_editor_layout(self):
        """Resolve the complete first editor layout while the window is hidden.

        Unlike the old post-show timers, this gives the central widget and
        splitter their final screen-sized geometry first, activates Qt's
        layouts, and then applies the initial 45/55 workspace allocation.
        The first visible paint is therefore already the settled layout.
        """
        if getattr(self, "_initial_layout_finalized", False):
            return
        screen = self.screen() or QApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen is not None else None
        if geometry is not None:
            self.setGeometry(geometry)
        self.ensurePolished()
        central = self.centralWidget()
        if central is not None:
            central.setGeometry(self.contentsRect())
            layout = central.layout()
            if layout is not None:
                layout.activate()
        self.prepare_responsive_layout()
        if central is not None and central.layout() is not None:
            central.layout().activate()
        set_default_splitter = getattr(self, "_set_default_preview_timeline_sizes", None)
        if callable(set_default_splitter):
            set_default_splitter()
        self._initial_layout_finalized = True

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_initial_layout_finalized", False):
            return
        # Fallback for non-launcher entry points. The normal Launcher flow
        # calls prepare_initial_editor_layout() before show().
        self.prepare_initial_editor_layout()

    def resizeEvent(self, event):
        """Apply responsive layout changes after Qt settles a resize/DPI move."""
        super().resizeEvent(event)
        if not getattr(self, "_initial_layout_finalized", False):
            return
        if not getattr(self, "_responsive_layout_pending", False):
            self._responsive_layout_pending = True
            QTimer.singleShot(0, self.apply_responsive_layout)

    def apply_responsive_layout(self, available_width=None, available_height=None):
        """Keep the editor usable from 1280x720 upward without altering
        the normal desktop composition.

        Width controls the two side panels; available height controls the
        Preview/Timeline minimums.  Content remains reachable through the
        existing inspector and timeline scroll areas instead of being clipped.
        """
        self._responsive_layout_pending = False
        central = self.centralWidget()
        width = int(available_width or (central.width() if central is not None else self.width()) or self.width())
        height = int(available_height or (central.height() if central is not None else self.height()) or self.height())
        compact_width = width < 1500
        compact_height = height < 850
        tight_height = height < 760
        mode = "compact" if (compact_width or compact_height) else "desktop"
        self._responsive_layout_mode = mode

        root_layout = getattr(self, "root_layout", None)
        content_layout = getattr(self, "content_layout", None)
        header_layout = getattr(self, "header_layout", None)
        if root_layout is not None:
            margin = 4 if compact_height else 4
            root_layout.setContentsMargins(margin, margin, margin, margin)
            root_layout.setSpacing(4 if compact_height else 4)
        if content_layout is not None:
            content_layout.setSpacing(4 if compact_width else 4)
        if header_layout is not None:
            header_layout.setContentsMargins(8 if compact_width else 10, 4 if compact_height else 4,
                                             8 if compact_width else 10, 4 if compact_height else 4)
            header_layout.setSpacing(4 if compact_width else 6)

        # Narrower side panels leave a meaningful preview width on 1366/1280
        # laptops while the cards themselves remain scrollable.
        left_panel = getattr(self, "left_panel_scroll_area", None)
        if left_panel is not None:
            left_panel.setMinimumWidth(280 if compact_width else 320)
            left_panel.setMaximumWidth(420 if compact_width else 520)
        inspector_width = 320 if compact_width else 400
        inspector_max = 440 if compact_width else 560
        self._responsive_inspector_width = inspector_width
        for attr in (
            "subtitle_inspector_card", "audio_inspector_card", "blur_inspector_card",
            "logo_inspector_card", "mask_inspector_card", "text_inspector_card",
            "default_inspector_card", "video_inspector_card",
        ):
            card = getattr(self, attr, None)
            if card is not None:
                card.setMinimumWidth(inspector_width)
                card.setMaximumWidth(inspector_max)
        self._sync_subtitle_inspector_shell_width()
        stack = getattr(self, "inspector_stack", None)
        if stack is not None:
            for index in range(stack.count()):
                scroll = stack.widget(index)
                if isinstance(scroll, QScrollArea):
                    scroll.setHorizontalScrollBarPolicy(
                        Qt.ScrollBarAsNeeded if compact_width else Qt.ScrollBarAlwaysOff
                    )

        # Minimum heights linh hoạt cho phép người dùng kéo thu hẹp / mở rộng tự do
        workspace_min = 150
        timeline_min = 140
        video_min = 150
        if compact_height:
            workspace_min, timeline_min, video_min = 130, 120, 130
        if tight_height:
            workspace_min, timeline_min, video_min = 120, 110, 120
        self._responsive_workspace_minimum_height = workspace_min
        self._responsive_timeline_minimum_height = timeline_min
        workspace = getattr(self, "preview_workspace_widget", None)
        timeline_card = getattr(self, "timeline_card", None)
        video_view = getattr(self, "video_view", None)
        if workspace is not None:
            workspace.setMinimumHeight(workspace_min)
        if timeline_card is not None:
            timeline_card.setMinimumHeight(timeline_min)
        if video_view is not None:
            video_view.setMinimumHeight(video_min)

        # Reduce header chrome in compact mode without removing actions.
        for button in (getattr(self, "voice_gender_check_btn", None), getattr(self, "voice_gender_history_btn", None),
                       getattr(self, "run_all_btn", None), getattr(self, "export_btn", None),
                       getattr(self, "more_actions_btn", None)):
            if button is not None:
                button.setMinimumHeight(28 if compact_height else 30)
        preview_button = getattr(self, "preview_5s_btn", None)
        if preview_button is not None:
            preview_button.setVisible(not compact_width)
        more_button = getattr(self, "more_actions_btn", None)
        if more_button is not None:
            more_button.setMinimumWidth(40 if compact_width else 50)
        logo = getattr(self, "header_logo_label", None)
        if logo is not None:
            logo.setVisible(not compact_width)
        brand = getattr(self, "header_brand_label", None)
        if brand is not None:
            brand.setVisible(not compact_width)

        # Ensure altered minimums are immediately reflected in splitter bounds
        # and native preview overlay geometry.
        splitter = getattr(self, "preview_timeline_splitter", None)
        if splitter is not None:
            sizes = splitter.sizes()
            if len(sizes) == 2 and sum(sizes) > timeline_min and sizes[1] < timeline_min:
                splitter.setSizes([max(1, sum(sizes) - timeline_min), timeline_min])
        self.sync_left_panel_container_width()
        QTimer.singleShot(0, self._resync_preview_region_overlays)

    def _run_deferred_startup_stage1(self):
        if getattr(self, "_deferred_startup_stage1_done", False):
            return
        self._deferred_startup_stage1_done = True
        self.setup_audio_preview_player()
        self.load_user_settings()
        self.refresh_saved_subtitle_style_presets()

    def _run_deferred_startup_stage2(self):
        if getattr(self, "_deferred_startup_stage2_done", False):
            return
        self._deferred_startup_stage2_done = True
        self.load_voice_preview_catalog()

    def ensure_media_backend_ready(self):
        if getattr(self, "_media_backend_ready", False):
            return
        self.setup_media_player()
        if hasattr(self, "video_view") and hasattr(self.video_view, "blurRegionChanged"):
            if getattr(self, "_blur_region_signal_bound", False):
                try:
                    self.video_view.blurRegionChanged.disconnect(self.on_preview_blur_region_changed)
                except Exception:
                    pass
            self.video_view.blurRegionChanged.connect(self.on_preview_blur_region_changed)
            self._blur_region_signal_bound = True
        if hasattr(self, "video_view") and hasattr(self.video_view, "blurEditFinished"):
            if getattr(self, "_blur_edit_finished_signal_bound", False):
                try:
                    self.video_view.blurEditFinished.disconnect(self.on_blur_edit_finished)
                except Exception:
                    pass
            self.video_view.blurEditFinished.connect(self.on_blur_edit_finished)
            self._blur_edit_finished_signal_bound = True
        if hasattr(self, "video_view") and hasattr(self.video_view, "subtitlePositionChanged"):
            if not getattr(self, "_subtitle_position_drag_signal_bound", False):
                self.video_view.subtitlePositionChanged.connect(self.on_subtitle_position_dragged)
                self._subtitle_position_drag_signal_bound = True
        if hasattr(self, "video_view") and hasattr(self.video_view, "textLayerSelected"):
            if not getattr(self, "_text_layer_signal_bound", False):
                self.video_view.textLayerSelected.connect(self._on_text_layer_selected_from_preview)
                self.video_view.textLayerMoved.connect(self._on_text_layer_moved)
                self._text_layer_signal_bound = True









    def _entry_has_preview_media(self, entry: dict | None) -> bool:
        if not entry:
            return False
        return bool(
            entry.get("preview_video_path")
            or entry.get("preview_video_url")
            or entry.get("preview_audio_path")
            or entry.get("preview_audio_url")
        )





    def get_transcription_engine(self) -> str:
        """Return the recognition source for the open project, never a stale global preference."""
        state = getattr(self, "current_project_state", None)
        settings = getattr(state, "settings", {}) if state is not None else {}
        value = str(settings.get("transcription_engine", "") or "").strip().lower()
        return value if value in {"whisper", "sensevoice", "ocr"} else _default_asr_engine()

    def set_project_transcription_engine(self, engine: str) -> None:
        """Apply a project-local source choice and clear incompatible range state."""
        engine = str(engine or "").strip().lower()
        if engine not in {"whisper", "sensevoice", "ocr"}:
            engine = _default_asr_engine()
        previous = self.get_transcription_engine()
        os.environ["TRANSCRIPTION_ENGINE"] = engine
        state = getattr(self, "current_project_state", None)
        if state is not None:
            state.set_setting("transcription_engine", engine)
            self.project_service.save_project(state)
        if engine != previous:
            # A new OCR project needs the crop editor immediately. Existing
            # projects with completed OCR remain unobstructed until the user
            # explicitly reopens the region tool.
            if engine == "ocr" and not self.current_segments and not self.transcript_text.toPlainText().strip():
                self._ocr_overlay_visible = True
            timeline = getattr(self, "timeline", None)
            if timeline is not None:
                timeline.clear_selection_range()
            self._alternate_ocr_range_pending = None
            overlay = getattr(self, "ocr_region_overlay", None)
            if overlay is not None:
                overlay.set_editable(False)
                overlay.hide()
            button = getattr(self, "timeline_alt_transcribe_btn", None)
            if button is not None:
                self._update_alt_transcribe_button_label()
            self.log(f"[Subtitle Source] Changed to {engine}; cleared Selection Range.")
        self.update_speaker_diarization_availability()
        self._update_ocr_overlay()

    def _alternate_transcription_engine(self) -> str:
        return "whisper" if self.get_transcription_engine() == "ocr" else "ocr"

    def _update_alt_transcribe_button_label(self) -> None:
        button = getattr(self, "timeline_alt_transcribe_btn", None)
        if button is None or getattr(self, "_alternate_range_transcription_worker", None) is not None:
            return
        if bool(getattr(self, "_alternate_ocr_range_pending", None)):
            button.setText("Run OCR")
            return
        button.setText("Alt Transcribe")
        button.setToolTip("Transcribe the Selection Range with custom Whisper or OCR settings")














    def on_target_language_changed(self, _index: int = -1):
        """Show and select only local voices that match the output language."""
        self._voiceover_force_refresh = True
        if getattr(self, "voice_catalog_entries_all", None):
            self.refresh_voice_catalog_combos()





    @staticmethod

    @staticmethod






    @staticmethod














    def _percent_to_db(self, percent: int) -> float:
        """Convert volume percentage (0-200) to dB gain."""
        if percent <= 0:
            return -60.0
        import math
        return 20.0 * math.log10(percent / 100.0)

    # -----------------------------
    # Logging + error helpers
    # -----------------------------
    def log(self, message: str):
        log_message_impl(self, message)

    def _append_runtime_log_entry(self, message: str):
        from datetime import datetime

        text = str(message or "").strip()
        if not text:
            return
        entry = f"{datetime.now().strftime('%H:%M:%S')}  {text}"
        self._pending_runtime_log_entries.append(entry)
        if not self._runtime_log_flush_timer.isActive():
            self._runtime_log_flush_timer.start()

    def _flush_runtime_log_entries(self):
        entries = self._pending_runtime_log_entries
        self._pending_runtime_log_entries = []
        if not entries:
            return
        self._runtime_logs.extend(entries)
        if len(self._runtime_logs) > 10000:
            del self._runtime_logs[:-10000]
        view = getattr(self, "runtime_log_view", None)
        # The Logs view belongs to the Advanced workflow page. Keep the
        # in-memory log complete, but defer text layout/repaint work until
        # the user actually opens that page.
        if view is not None and view.isVisible():
            already_rendered = int(getattr(self, "_runtime_log_view_entry_count", 0))
            if already_rendered != len(self._runtime_logs) - len(entries):
                view.setPlainText("\n".join(self._runtime_logs))
            else:
                view.appendPlainText("\n".join(entries))
            self._runtime_log_view_entry_count = len(self._runtime_logs)

    def sync_runtime_log_view(self, *_args):
        """Populate deferred runtime logs when the Advanced page is shown."""
        view = getattr(self, "runtime_log_view", None)
        if view is None or not view.isVisible():
            return
        logs = getattr(self, "_runtime_logs", [])
        if int(getattr(self, "_runtime_log_view_entry_count", 0)) == len(logs):
            return
        view.setPlainText("\n".join(logs))
        self._runtime_log_view_entry_count = len(logs)

    def clear_log(self):
        clear_log_impl(self)


    def _register_progress_dialog(self, dialog):
        if dialog is None:
            return
        self._tracked_progress_dialogs = [d for d in self._tracked_progress_dialogs if d is not None]
        if dialog not in self._tracked_progress_dialogs:
            self._tracked_progress_dialogs.append(dialog)
            try:
                dialog.destroyed.connect(lambda *_args, dlg=dialog: self._unregister_progress_dialog(dlg))
            except Exception:
                pass
        self._update_progress_reopen_button()

    def _unregister_progress_dialog(self, dialog):
        self._tracked_progress_dialogs = [d for d in self._tracked_progress_dialogs if d is not dialog]
        self._update_progress_reopen_button()

    def _active_progress_dialogs(self):
        active = []
        for dialog in list(getattr(self, "_tracked_progress_dialogs", []) or []):
            if dialog is None:
                continue
            try:
                if dialog.isVisible():
                    active.append(dialog)
                    continue
                if getattr(dialog, "isHidden", None) and not dialog.isHidden():
                    active.append(dialog)
            except Exception:
                continue
        return active

    def _update_progress_reopen_button(self):
        button = getattr(self, "show_progress_btn", None)
        if button is None:
            return
        tracked = [d for d in getattr(self, "_tracked_progress_dialogs", []) if d is not None]
        try:
            button.setVisible(bool(tracked))
            button.setEnabled(bool(tracked))
        except RuntimeError:
            # Qt can destroy the toolbar button before a tracked progress
            # dialog emits its destroyed signal during application shutdown.
            pass

    def show_active_progress_dialog(self):
        dialogs = [d for d in getattr(self, "_tracked_progress_dialogs", []) if d is not None]
        if not dialogs:
            self._update_progress_reopen_button()
            return
        dialog = dialogs[-1]
        try:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception:
            pass
        self._update_progress_reopen_button()

    def _resource_service(self) -> ResourceDownloadService:
        return ResourceDownloadService(self.workspace_root)

    def _create_vietdict_template(self, resource_id: str):
        # Kept as a compatibility no-op for old callers.  Dictionaries are
        # now stored in project state and are edited in Subtitle Inspector.
        return
        """

        acronyms_path = os.path.join("", "acronyms.csv")
        if not os.path.exists(acronyms_path):
            with open(acronyms_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["acronym", "transliteration"])
                w.writerow(["vtv", "vô tuyến truyền hình"])
                w.writerow(["CLB", "câu lạc bộ"])
            print(f"[VietDict] Created template: {acronyms_path}")

        nonvn_path = os.path.join(dir_path, "non-vietnamese-words.csv")
        if not os.path.exists(nonvn_path):
            with open(nonvn_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["original", "transliteration"])
                w.writerow(["iPhone", "ai phôn"])
            print(f"[VietDict] Created template: {nonvn_path}")

        os.startfile(dir_path)

        """

    def _vietdict_add_row(self, table):
        from PySide6.QtWidgets import QTableWidgetItem
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r, 0, QTableWidgetItem(""))
        table.setItem(r, 1, QTableWidgetItem(""))
        table.scrollToBottom()

    def _vietdict_remove_row(self, table):
        rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
        for r in rows:
            table.removeRow(r)


    def _missing_resource_entries(self, *, include_whisper: bool = False, include_voice: bool = False, include_ocr: bool = False, validate_pipeline_runtime: bool = False) -> list[tuple[str, str]]:
        service = self._resource_service()
        missing: list[tuple[str, str]] = []

        if include_whisper and not is_remote_profile():
            engine = self.get_transcription_engine()
            if engine == "sensevoice":
                missing.extend(service.validate_sensevoice_runtime())
            else:
                model_name = self.get_whisper_model_name()
                resource_id = f"whisper:{model_name}"
                if not service.is_resource_installed(resource_id):
                    missing.append((resource_id, f"Whisper {model_name.title()} model"))

        if include_voice and not is_remote_profile():
            voice_name = self.get_active_voice_name()
            is_capcut = (
                str(voice_name).startswith("capcut_")
                or getattr(self, "voice_catalog_map", {}).get(voice_name, {}).get("provider") == "capcut"
            )
            if (
                voice_name
                and not str(voice_name).startswith("edge:")
                and not str(voice_name).startswith("f5:")
                and not is_capcut
            ):
                resource_id = f"voice:{voice_name}"
                if not service.is_resource_installed(resource_id):
                    voice_label = voice_name
                    voice_entry = self.voice_catalog_map.get(voice_name) if hasattr(self, "voice_catalog_map") else None
                    if isinstance(voice_entry, dict):
                        voice_label = str(voice_entry.get("name", voice_name)).strip() or voice_name
                    missing.append((resource_id, f"Local voice: {voice_label}"))

        if include_ocr:
            missing.extend(service.validate_ocr_runtime())

        if include_voice and not is_remote_profile():
            missing.extend(service.validate_piper_voice_runtime(self.get_active_voice_name()))

        if validate_pipeline_runtime and not is_remote_profile():
            missing.extend(service.validate_pipeline_runtime())

        deduped: list[tuple[str, str]] = []
        seen = set()
        for item in missing:
            if item[0] in seen:
                continue
            seen.add(item[0])
            deduped.append(item)
        return deduped

    def ensure_required_resources(self, action_label: str, *, include_whisper: bool = False, include_voice: bool = False, include_ocr: bool = False, validate_pipeline_runtime: bool = False) -> bool:
        missing = self._missing_resource_entries(
            include_whisper=include_whisper,
            include_voice=include_voice,
            include_ocr=include_ocr,
            validate_pipeline_runtime=validate_pipeline_runtime,
        )
        if not missing:
            return True

        missing_lines = "\n".join(f"- {label}" for _resource_id, label in missing)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("TankVideo Cannot Start This Step")
        box.setText(f"{action_label} cannot start because a required local component is unavailable.")
        box.setInformativeText(
            "The exact cause is listed below. Use Manage Resources for downloadable "
            "models, or fix the shown folder/permission problem before trying again:\n\n"
            f"{missing_lines}"
        )
        open_btn = box.addButton("Manage Resources", QMessageBox.AcceptRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self.open_resource_manager_dialog()
        return False

    def open_resource_manager_dialog(self):
        from views.resource_manager import open_resource_manager
        open_resource_manager(
            self.workspace_root,
            parent=self,
            on_finished=lambda: self._on_resource_download_complete(),
        )

    def _on_resource_download_complete(self):
        try:
            self.load_voice_preview_catalog()
        except Exception:
            pass
        self.refresh_ui_state()

    def show_error(self, title: str, short_msg: str, details: str = ""):
        show_error_impl(self, title, short_msg, details)

    def stabilize_button(self, button: QPushButton, min_width: int = 220, min_height: int = 42):
        button.setMinimumWidth(min_width)
        button.setMinimumHeight(min_height)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def make_helper_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("helperLabel")
        return label

    def using_existing_audio_source(self) -> bool:
        # The Audio Source selector was replaced by timeline audio tracks.
        # Legacy radio controls may still exist in older project/settings
        # data, but they are not part of the active UI and must not bypass
        # A1/TS1/Music track composition.
        if not hasattr(self, "existing_audio_source_panel"):
            return False
        mixed_path = self._normalize_local_file_path(
            self.mixed_audio_edit.text().strip() if hasattr(self, "mixed_audio_edit") else ""
        )
        use_existing = bool(hasattr(self, "use_existing_audio_radio") and self.use_existing_audio_radio.isChecked())
        return bool(use_existing and mixed_path and os.path.exists(mixed_path))

    def _normalize_local_file_path(self, path: str) -> str:
        value = str(path or "").replace("\r", "").replace("\n", "").replace("\t", " ").strip().strip('"').strip("'")
        if not value:
            return ""

        value = os.path.expandvars(os.path.expanduser(value))
        candidates = []
        if os.path.isabs(value):
            candidates.append(value)
        else:
            candidates.append(os.path.join(self.workspace_root, value))
            current_project = getattr(self, "current_project_state", None)
            if current_project and getattr(current_project, "project_root", ""):
                candidates.append(os.path.join(current_project.project_root, value))
            candidates.append(os.path.join(self.workspace_root, value))

        for candidate in candidates:
            normalized = os.path.normpath(os.path.abspath(candidate))
            if os.path.exists(normalized):
                return normalized

        fallback = candidates[0] if candidates else value
        return os.path.normpath(os.path.abspath(fallback))

    def resolve_selected_audio_path(self) -> str:
        if self.using_existing_audio_source():
            return self._normalize_local_file_path(self.mixed_audio_edit.text().strip())
        music_tracks = self._music_audio_tracks()
        try:
            voice_path = self._resolve_preview_voice_only_audio_path()
        except Exception:
            voice_path = ""
        tts_state = self._tts_audio_track_state()
        if voice_path and not bool(tts_state.get("muted", False)) and float(tts_state.get("volume", 100.0)) > 0.0:
            return voice_path
        # A Music Layer is also a valid audio source for composed export when
        # TTS has not been generated (or has been muted). Respect its actual
        # volume/mute state so a zeroed track cannot re-enter export through a
        # stale raw-path fallback.
        for item in music_tracks:
            if bool(item.get("muted", False)) or float(item.get("volume", 0.0)) <= 0.0:
                continue
            candidate = self._normalize_local_file_path(item.get("path", ""))
            if candidate and os.path.exists(candidate):
                return candidate
        # Legacy projects without a usable timeline voice/music state may
        # still have a cached mixed_vi artifact. Only use it when no active
        # independent tracks are present, preventing old audio from bypassing
        # the new per-track volume controls.
        if not music_tracks and not voice_path:
            for candidate in (
                self.processed_artifacts.get("mixed_vi"),
                self.last_mixed_vi_path,
            ):
                normalized = self._normalize_local_file_path(candidate)
                if normalized and os.path.exists(normalized):
                    return normalized
        return ""



    def _audio_track_is_soloed(self, track_name: str) -> bool:
        timeline = getattr(self, "timeline", None)
        model = getattr(timeline, "_timeline", None) if timeline is not None else None
        if model is None:
            return False
        for track in getattr(model, "tracks", []) or []:
            name = str(getattr(track, "name", "") or "")
            metadata = getattr(track, "metadata", {}) or {}
            if name == track_name:
                return bool(getattr(track, "solo", False) or metadata.get("_solo", False))
        return False

    def _audio_total_duration_ms(self) -> int:
        try:
            duration = int(getattr(self.media_player, "duration", lambda: 0)() or 0)
        except Exception:
            duration = 0
        if duration <= 0:
            try:
                duration = int(getattr(self.timeline, "duration", 0) or 0)
            except Exception:
                duration = 0
        return max(0, duration)



    def _schedule_preview_audio_refresh(self, *, force: bool = False):
        if getattr(self, "_preview_audio_track_switching", False):
            return
        timer = getattr(self, "_music_preview_refresh_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(120)
            timer.timeout.connect(lambda: self.sync_preview_audio_track_to_output(apply_to_player=True, force=True))
            self._music_preview_refresh_timer = timer
        timer.start(0 if force else 120)


    def _resolve_preview_background_audio_path(self) -> str:
        # A Music Layer is the only source that should be mixed with TTS.
        # Never silently substitute the source video's extracted audio here:
        # A1 remains an independent track and can be muted separately.
        music_tracks = self._music_audio_tracks()
        if music_tracks:
            return str(music_tracks[0].get("path", "") or "")
        # Keep a narrow legacy fallback for projects created before Music
        # Layer existed.  Explicitly selected background audio is stored in
        # bg_music_edit/last_music_path; the ordinary extracted A1 audio is
        # deliberately not considered a background bed anymore.
        candidates = [
            self.bg_music_edit.text().strip() if hasattr(self, "bg_music_edit") else "",
            self.last_music_path,
        ]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return normalized
        return ""

    def _resolve_preview_mixed_audio_path(self) -> str:
        if self.using_existing_audio_source():
            audio_path = self._normalize_local_file_path(self.mixed_audio_edit.text().strip())
            return audio_path if audio_path and os.path.exists(audio_path) else ""
        voice_only = self._resolve_preview_voice_only_audio_path()
        music_tracks = self._music_audio_tracks()
        # The dubbed sidecar may contain TTS, music, or both.  Do not require
        # a voice file here: a project with a muted/skipped TTS track and an
        # active Music Layer must still be previewable and exportable.
        if not voice_only and not music_tracks:
            return ""

        tts_state = self._tts_audio_track_state()
        voice_stat = None
        if voice_only:
            try:
                voice_stat = os.stat(voice_only)
            except OSError:
                voice_only = ""
        signature_payload = {
            "kind": "tts-plus-music-v1",
            "voice": os.path.abspath(voice_only) if voice_only else "",
            "voice_size": int(voice_stat.st_size) if voice_stat is not None else 0,
            "voice_mtime_ns": int(getattr(voice_stat, "st_mtime_ns", int(voice_stat.st_mtime * 1_000_000_000))) if voice_stat is not None else 0,
            "tts_volume": round(float(tts_state.get("volume", 100.0)), 3),
            "tts_muted": bool(tts_state.get("muted", False)),
            "music": [
                {
                    "path": os.path.abspath(str(item.get("path", ""))),
                    "size": int(os.path.getsize(str(item.get("path", "")))),
                    "mtime_ns": int(os.stat(str(item.get("path", ""))).st_mtime_ns),
                    "start": round(float(item.get("start", 0.0)), 3),
                    "end": round(float(item.get("end", 0.0)), 3),
                    "source_start": round(float(item.get("source_start", 0.0)), 3),
                    "volume": round(float(item.get("volume", 30.0)), 3),
                    "muted": bool(item.get("muted", False)),
                }
                for item in music_tracks
            ],
        }
        mix_hash = hashlib.sha1(json.dumps(signature_payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        output_path = os.path.join(self.get_workspace_temp_root(create=True), f"timeline_preview_mix_{mix_hash}.wav")
        if os.path.exists(output_path):
            return output_path

        try:
            from audio_mixer import mix_audio_tracks
            tracks = []
            if voice_only:
                tracks.append({
                    "path": voice_only,
                    "start": 0.0,
                    "end": self._audio_total_duration_ms() / 1000.0,
                    "volume": float(tts_state.get("volume", 100.0)),
                    "muted": bool(tts_state.get("muted", False)),
                })
            tracks.extend(music_tracks)
            mix_audio_tracks(
                tracks=tracks,
                output_wav_path=output_path,
                total_duration_ms=self._audio_total_duration_ms(),
            )
        except Exception as exc:
            # A project may legitimately have no active dubbed/music track
            # yet (for example before TTS generation, or when both tracks
            # are muted).  Treat that as a silent sidecar rather than an
            # error emitted on every preview refresh; unexpected mixer
            # failures remain visible in the runtime log.
            if not (isinstance(exc, ValueError) and "No active audio tracks" in str(exc)):
                self.log(f"[Preview] timeline audio mix unavailable: {exc}")
            return ""
        return output_path


    def _resolve_preview_original_video_path(self) -> str:
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        normalized = self._normalize_local_file_path(video_path)
        return normalized if normalized and os.path.exists(normalized) else ""





    def _preview_audio_track_choices(self) -> list[tuple[str, str]]:
        choices = [("Original Audio", "original")]
        if self._has_preview_dubbed_audio_source():
            choices.append(("Dub Voice", "dubbed"))
        return choices

    def _preferred_preview_audio_track_mode(self) -> str:
        track_mutes = self._timeline_audio_track_mutes()
        if track_mutes:
            _a1_muted, a2_muted = track_mutes
            # A2 mute applies only to TTS.  Music is composed into the
            # dubbed sidecar independently, so keep that sidecar selected
            # when a Music Layer exists.
            if a2_muted and not self._music_audio_tracks():
                return "original"
        mode = str(self.get_output_mode_key() or "subtitle").strip().lower()
        if mode in ("voice", "both"):
            if self._has_preview_dubbed_audio_source():
                return "dubbed"
        return "original"

    def sync_preview_audio_track_to_output(self, *, apply_to_player: bool = True, force: bool = False):
        target_mode = self._preferred_preview_audio_track_mode()
        self._preview_audio_track_mode = target_mode

        if not apply_to_player or not getattr(self, "media_player", None):
            return

        source_video = self._resolve_preview_original_video_path()
        current_source = self._normalize_local_file_path(str(getattr(self.media_player, "_source_path", "") or ""))
        should_apply = bool(force) or not current_source
        if source_video and current_source:
            should_apply = bool(force) or os.path.abspath(current_source) == os.path.abspath(source_video)

        if should_apply:
            self._apply_preview_audio_track_selection()
            return

    def _apply_preview_audio_track_selection(self):
        if (
            getattr(self, "_preview_audio_track_switching", False)
            or not hasattr(self, "media_player")
            or not getattr(self, "media_player", None)
        ):
            return
        source_video = self._resolve_preview_original_video_path()
        if not source_video:
            return

        # Always load the original audio sidecar. Resolve/build the composed
        # dubbed sidecar only when the current output mode actually selects
        # it; otherwise a subtitle-only/original preview would needlessly
        # attempt a TTS+Music mix and report "No active audio tracks".
        preferred_mode = self._preferred_preview_audio_track_mode()
        selected_mode = str(getattr(self, "_preview_audio_track_mode", "") or preferred_mode).strip().lower()
        if selected_mode == "dubbed":
            dubbed_audio_kind, dubbed_audio = self._resolve_preview_dubbed_playback_source()
        else:
            dubbed_audio_kind, dubbed_audio = "original", ""
        if not dubbed_audio or dubbed_audio_kind == "original":
            dubbed_audio = ""
        original_audio = self._resolve_preview_original_audio_path()

        try:
            current_position = int(self.media_player.position())
        except Exception:
            current_position = 0
        try:
            was_playing = bool(self.media_player.is_playing())
        except Exception:
            was_playing = False

        current_source = str(getattr(self.media_player, "_source_path", "") or "")
        should_reset_source = not current_source or os.path.abspath(current_source) != os.path.abspath(source_video)

        self._preview_audio_track_switching = True
        try:
            if should_reset_source:
                try:
                    self.media_player.pause()
                except Exception:
                    pass
                self.media_player.setSource(QUrl.fromLocalFile(source_video))
                self.refresh_video_dimensions(source_video)
                self._preview_video_has_burned_subtitles = False
                self.sync_live_subtitle_preview()
            # Always load the original audio sidecar when available
            if hasattr(self.media_player, "set_original_audio_file"):
                if original_audio:
                    self.media_player.set_original_audio_file(original_audio)
                else:
                    try:
                        self.media_player._clear_original_audio()
                    except Exception:
                        pass
            # Re-apply persisted A1 level/mute after replacing the sidecar.
            # QMediaPlayer resets the output volume when a new audio source
            # is opened, which otherwise makes a restored 0%/custom level
            # appear to be ignored until the slider is touched.
            try:
                original_volume = self._compute_audio_track_volume("A1 Audio", base=100.0)
                original_gain = self._get_audio_track_gain_db("A1 Audio")
                original_volume *= 10 ** (original_gain / 20.0)
                if hasattr(self.media_player, "set_original_volume"):
                    self.media_player.set_original_volume(max(0.0, min(200.0, original_volume)))
                if hasattr(self.media_player, "set_mute_original"):
                    self.media_player.set_mute_original(self._is_audio_track_muted("A1 Audio"))
            except Exception:
                pass
            if dubbed_audio:
                self.media_player.set_audio_file(dubbed_audio)
                try:
                    if dubbed_audio_kind == "mixed":
                        # TTS and Music volumes are already baked into the
                        # composed WAV; never apply TS1's level to the whole
                        # sidecar a second time.
                        if hasattr(self.media_player, "set_dubbed_volume"):
                            self.media_player.set_dubbed_volume(100.0)
                        if hasattr(self.media_player, "set_mute_dubbed"):
                            self.media_player.set_mute_dubbed(False)
                    else:
                        dubbed_volume = self._compute_audio_track_volume("TS1", base=100.0)
                        dubbed_gain = self._get_audio_track_gain_db("TS1")
                        dubbed_volume *= 10 ** (dubbed_gain / 20.0)
                        if hasattr(self.media_player, "set_dubbed_volume"):
                            self.media_player.set_dubbed_volume(max(0.0, min(200.0, dubbed_volume)))
                        if hasattr(self.media_player, "set_mute_dubbed"):
                            self.media_player.set_mute_dubbed(self._is_audio_track_muted("TS1"))
                except Exception:
                    pass
            else:
                self.media_player.clear_audio()
            if current_position > 0:
                try:
                    self.media_player.setPosition(current_position)
                except Exception:
                    pass
            if was_playing:
                try:
                    self.media_player.play()
                    if hasattr(self, "timeline"):
                        self.timeline.set_playing(True)
                except Exception:
                    pass
            else:
                if hasattr(self, "timeline"):
                    self.timeline.set_playing(False)
            # Only log the preview audio state when at least one audio sidecar
            # was actually applied. Logging "silent" on a freshly opened
            # video (no generate/voice done yet) is misleading noise —
            # Bug 3.
            if original_audio or dubbed_audio:
                active_label = "both" if (original_audio and dubbed_audio) else (
                    "dubbed" if dubbed_audio else "original"
                )
                self.log(f"[Preview] audio: {active_label}")
        finally:
            self._preview_audio_track_switching = False
        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=True)

    def _resolve_preview_original_audio_path(self) -> str:
        """Resolve the original audio file path (separate from source video).

        A1 always represents the source video's original audio.  Audio
        Processing/Clean mode no longer changes this track; separated stems
        are only used when the user explicitly adds a Music Layer.
        """
        candidates: list[str] = []
        candidates.extend([
            self.processed_artifacts.get("extracted_audio"),
            self.last_extracted_audio,
            self.audio_source_edit.text().strip() if hasattr(self, "audio_source_edit") else "",
        ])
        for candidate in candidates:
            if not candidate:
                continue
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                return normalized
        # Final fallback: the source video file itself. mpv runs with
        # `ao=null` (video-only) and audio is routed through the A1
        # QMediaPlayer sidecar, so on a freshly opened video (no Generate
        # run yet, no extracted audio artifact) the sidecar would be empty
        # and the user hears nothing. QMediaPlayer decodes the audio
        # track straight out of a video container, so loading the source
        # video into the A1 sidecar restores the original audio. Once the
        # pipeline extracts a dedicated audio file, that takes priority
        # via the candidates above.
        source_video = self._resolve_preview_original_video_path()
        if source_video:
            return source_video
        return ""

    def on_preview_audio_track_changed(self, index: int):
        if getattr(self, "_preview_audio_track_switching", False) or not hasattr(self, "preview_audio_track_combo"):
            return
        mode = str(self.preview_audio_track_combo.itemData(index) or "original").strip().lower()
        self._preview_audio_track_mode = mode if mode in ("original", "dubbed") else "original"
        self._apply_preview_audio_track_selection()











    def _hide_legacy_audio_source_controls(self):
        """Keep pre-timeline Audio Source widgets out of the active UI.

        Older projects still load a handful of compatibility widgets because
        runtime code and settings migration reference their values.  They are
        deliberately not part of the current Audio tab, which is based on
        independent A1/TS1/Music tracks.  Centralising the hide operation also
        prevents a legacy refresh path from making the old radio buttons
        visible again after output-mode or project-state updates.
        """
        legacy_widget_names = (
            "use_generated_audio_radio",
            "use_existing_audio_radio",
            "audio_source_hint_label",
            "bg_music_label",
            "bg_music_edit",
            "browse_bg_music_btn",
            "mixed_audio_label",
            "mixed_audio_edit",
            "browse_mixed_audio_btn",
            "generated_audio_section_label",
            "generated_audio_section_hint",
            "existing_audio_section_label",
            "existing_audio_section_hint",
        )
        for name in legacy_widget_names:
            widget = getattr(self, name, None)
            if widget is None:
                continue
            try:
                widget.hide()
                widget.setVisible(False)
            except RuntimeError:
                # A Qt object may have been deleted during a UI rebuild.
                continue
        for name in ("generated_audio_source_panel", "existing_audio_source_panel"):
            panel = getattr(self, name, None)
            if panel is None:
                continue
            try:
                panel.hide()
                panel.setVisible(False)
            except RuntimeError:
                continue

    def on_audio_source_mode_changed(self):
        # The old source selector is compatibility-only.  Always force it
        # hidden before handling any legacy state refresh.
        self._hide_legacy_audio_source_controls()
        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
        self.refresh_ui_state()

    def on_advanced_toggled(self, checked: bool):
        if hasattr(self, "tabs"):
            self.tabs.setVisible(True)
        if hasattr(self, "workflow_advanced_layout"):
            checked = True
        if hasattr(self, "toggle_advanced_btn"):
            self.toggle_advanced_btn.setText(("▼ " if checked else "▶ ") + "Advanced Settings")
        if hasattr(self, "advanced_section_content"):
            self.advanced_section_content.setVisible(bool(checked))

    def on_auto_preview_toggled(self, checked: bool):
        if checked:
            self.schedule_auto_frame_preview()
        else:
            self.auto_frame_preview_timer.stop()
            self.seek_frame_preview_timer.stop()
















    @staticmethod

    @staticmethod
    def _test_remote_api_connection(base_url: str, token: str) -> dict:
        previous_url = os.environ.get("CAPCAP_REMOTE_API_URL", "")
        previous_token = os.environ.get("CAPCAP_REMOTE_API_TOKEN", "")
        try:
            os.environ["CAPCAP_REMOTE_API_URL"] = (base_url or "").strip()
            if token:
                os.environ["CAPCAP_REMOTE_API_TOKEN"] = token.strip()
            else:
                os.environ.pop("CAPCAP_REMOTE_API_TOKEN", None)
            from remote_api import remote_api_get

            return remote_api_get("/health", timeout=10)
        finally:
            if previous_url:
                os.environ["CAPCAP_REMOTE_API_URL"] = previous_url
            else:
                os.environ.pop("CAPCAP_REMOTE_API_URL", None)
            if previous_token:
                os.environ["CAPCAP_REMOTE_API_TOKEN"] = previous_token
            else:
                os.environ.pop("CAPCAP_REMOTE_API_TOKEN", None)

    def _highlight_color_hex(self) -> str:
        mapping = {
            "Yellow": "#FFD400",
            "Cyan": "#00E5FF",
            "Green": "#5CFF95",
            "Pink": "#FF6BD6",
        }
        return mapping.get(self.subtitle_highlight_color_combo.currentText().strip(), "#FFD400")



















    def _dict_segments_to_models(self, segments, *, translated=False):
        return self.project_bridge.dict_segments_to_models(segments, translated=translated)

    def _sync_segment_models_from_current_segments(self):
        self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
        self.current_translated_segment_models = self._dict_segments_to_models(
            self.current_translated_segments,
            translated=True,
        )



    def build_current_translation_signature(self, source_segments=None):
        base_segments = list(source_segments or self.current_segments or [])
        if not base_segments:
            transcript_text = self.transcript_text.toPlainText().strip() if hasattr(self, "transcript_text") else ""
            if transcript_text:
                base_segments = self.parse_srt_to_segments(transcript_text)
        if not base_segments:
            return ""
        return self.project_service.build_translation_signature(
            base_segments,
            src_lang=self.get_source_language_code(),
            target_lang=self.get_target_language_code(),
            enable_polish=self.is_ai_polish_enabled(),
            optimize_subtitles=False,
            style_instruction=self.get_ai_style_instruction(),
        )








    def _enable_post_pipeline_preview_assets(self, *, refresh: bool = True):
        self._allow_post_pipeline_preview_assets = True
        if refresh:
            self.refresh_timeline_waveform()
            self.refresh_timeline_video_thumbnails()

    def resolve_background_audio_path(self) -> str:
        # Voice generation receives only an explicitly added Music Layer (or
        # the legacy manually selected background path).  The source video's
        # extracted A1 audio is never implicitly treated as music.
        music_tracks = self._music_audio_tracks()
        if music_tracks:
            return str(music_tracks[0].get("path", "") or "")
        manual_candidate = self.bg_music_edit.text().strip() if hasattr(self, "bg_music_edit") else ""
        candidates = [manual_candidate, getattr(self, "last_music_path", "")]
        for candidate in candidates:
            normalized = self._normalize_local_file_path(candidate)
            if normalized and os.path.exists(normalized):
                self.last_music_path = normalized
                self.processed_artifacts["music"] = normalized
                return normalized
        return ""















    def cleanup_file_if_exists(self, path: str):
        cleanup_file_if_exists_impl(path)

    def get_workspace_temp_root(self, create: bool = False) -> str:
        root = os.path.normpath(os.path.join(self.workspace_root, "temp"))
        if create:
            os.makedirs(root, exist_ok=True)
        return root

    def _cleanup_temp_root(self) -> None:
        root = self.get_workspace_temp_root()
        if not os.path.isdir(root):
            return
        for entry in os.listdir(root):
            fpath = os.path.join(root, entry)
            if not os.path.isfile(fpath):
                continue
            try:
                os.remove(fpath)
            except OSError:
                pass




    def get_output_mode_key(self):
        return "both"

    def get_output_quality_key(self):
        if not hasattr(self, "output_quality_combo"):
            return "source"
        value = self.output_quality_combo.currentData()
        if value:
            return str(value).strip().lower()
        return str(self.output_quality_combo.currentText() or "source").strip().lower() or "source"

    def get_output_fps_key(self):
        if not hasattr(self, "output_fps_combo"):
            return "source"
        value = self.output_fps_combo.currentData()
        if value:
            return str(value).strip().lower()
        return str(self.output_fps_combo.currentText() or "source").strip().lower() or "source"

    def get_output_ratio_key(self):
        if not hasattr(self, "output_ratio_combo"):
            return "source"
        value = self.output_ratio_combo.currentData()
        if value:
            return str(value).strip().lower()
        return str(self.output_ratio_combo.currentText() or "source").strip().lower() or "source"

    def get_output_scale_mode_key(self):
        if not hasattr(self, "output_scale_mode_combo"):
            return "fit"
        value = self.output_scale_mode_combo.currentData()
        if value:
            return str(value).strip().lower()
        return str(self.output_scale_mode_combo.currentText() or "fit").strip().lower() or "fit"

    def get_output_fill_focus(self):
        if hasattr(self, "video_view") and hasattr(self.video_view, "get_preview_fill_focus"):
            return self.video_view.get_preview_fill_focus()
        return (0.5, 0.5)





















    def on_output_ratio_changed(self, *_args):
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_preview_aspect_ratio"):
            self.video_view.set_preview_aspect_ratio(self.get_output_ratio_key())
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_preview_scale_mode"):
            self.video_view.set_preview_scale_mode(self.get_output_scale_mode_key())
        self._sync_preview_framing_to_player()
        self._sync_preview_output_canvas_dimensions()
        self.update_subtitle_preview_style()
        # update_subtitle_preview_style establishes the new output canvas
        # render dimensions. Refresh Text afterwards so it cannot reuse the
        # previous Ratio's height/scale payload.
        self._refresh_text_layer_preview(getattr(getattr(self, "timeline", None), "_selected_layer_id", ""))
        self.apply_preview_blur_region()
        self.refresh_ui_state()

    def on_output_scale_mode_changed(self, *_args):
        if hasattr(self, "video_view") and hasattr(self.video_view, "set_preview_scale_mode"):
            self.video_view.set_preview_scale_mode(self.get_output_scale_mode_key())
        self._sync_preview_framing_to_player()
        self._sync_preview_output_canvas_dimensions()
        self.update_subtitle_preview_style()
        self._refresh_text_layer_preview(getattr(getattr(self, "timeline", None), "_selected_layer_id", ""))
        self.apply_preview_blur_region()
        self.refresh_ui_state()

    def on_preview_framing_changed(self, *_args):
        self._sync_preview_framing_to_player()
        self._refresh_text_layer_preview(getattr(getattr(self, "timeline", None), "_selected_layer_id", ""))
        self.apply_preview_blur_region()
        self.refresh_ui_state()

    def reset_preview_framing(self):
        if hasattr(self, "video_view") and hasattr(self.video_view, "reset_preview_fill_focus"):
            self.video_view.reset_preview_fill_focus()
        self._sync_preview_framing_to_player()
        self.apply_preview_blur_region()
        self.refresh_ui_state()

    def get_audio_handling_mode(self):
        if not hasattr(self, "audio_handling_combo"):
            return "fast"
        value = self.audio_handling_combo.currentData()
        if value:
            return str(value).strip().lower()
        return "fast"




    def get_source_language_code(self):
        if not hasattr(self, "lang_whisper_combo"):
            return "auto"
        value = self.lang_whisper_combo.currentData()
        if value:
            return str(value)
        return self.lang_whisper_combo.currentText().strip() or "auto"

    def get_target_language_code(self):
        if not hasattr(self, "lang_target_combo"):
            return "vi"
        value = self.lang_target_combo.currentData()
        if value:
            return str(value)
        label = self.lang_target_combo.currentText().strip().lower()
        if "english" in label:
            return "en"
        return "vi"

    def is_ai_polish_enabled(self):
        # The old "Use AI translation" checkbox was removed when provider
        # selection moved into Settings.  A configured cloud/API provider is
        # now the explicit request to use AI; only selecting Google Translate
        # bypasses the AI branch.  Keeping the legacy checkbox fallback makes
        # older embedded UI layouts harmless.
        provider = str(os.getenv("OPENAI_PROVIDER") or "google").strip().lower()
        if provider in {"gemini", "google_ai_studio", "deepseek", "openai", "ollama"}:
            return True
        legacy_checkbox = getattr(self, "translator_ai_cb", None)
        return bool(legacy_checkbox and legacy_checkbox.isChecked())

    def is_skip_translation(self):
        # Translation is always part of the fixed Subtitle + Voice workflow.
        return False



    def get_ai_style_instruction(self):
        style_parts = []
        if hasattr(self, "translator_style_edit"):
            custom_style = self.translator_style_edit.text().strip()
            if custom_style:
                style_parts.append(custom_style)
        if hasattr(self, "subtitle_single_line_cb") and self.subtitle_single_line_cb.isChecked():
            style_parts.append("[subtitle_layout=single_line]")
        return " | ".join(part for part in style_parts if part).strip()

    def on_output_mode_changed(self, value: str):
        mode = "both"
        if getattr(self, "_filter_thumbnail_visible", False):
            self.hide_filter_thumbnail_preview()
        self.workflow_hint_label.setText(build_workflow_hint(mode, self.is_ai_polish_enabled()))

        show_voice = mode in ("voice", "both")
        if hasattr(self, "voice_section_card"):
            self.voice_section_card.setVisible(show_voice)
        if hasattr(self, "quick_preview_btn"):
            self.quick_preview_btn.setVisible(show_voice)
        if hasattr(self, "styled_preview_btn"):
            self.styled_preview_btn.setVisible(show_voice)
        self.mixed_audio_edit.setEnabled(show_voice)
        # Do not resurrect the pre-timeline Audio Source controls when the
        # output mode changes.  Music is added through the visible Music Layer
        # card and mixed via independent track volumes.
        self._hide_legacy_audio_source_controls()
        self.export_btn.setText(get_export_button_label(mode))
        self.refresh_ui_state()

    def on_left_panel_workflow_changed(self, index: int):
        # Filter thumbnail preview should only stay active while the Filter page is open.
        if int(index) != 4 and getattr(self, "_filter_thumbnail_visible", False):
            self.hide_filter_thumbnail_preview()

    def _workflow_dependency_state(self) -> dict:
        video_path = self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        has_video = bool(video_path and os.path.exists(video_path))
        return {
            "media": {"enabled": True, "reason": ""},
            "language": {"enabled": has_video, "reason": "Select a video first to transcribe and translate."},
            "voice": {"enabled": has_video, "reason": "Select a video first to configure voice and audio."},
            "style": {"enabled": has_video, "reason": "Select a video first to style subtitle output."},
            "filter": {"enabled": has_video, "reason": "Select a video first to preview and apply filters."},
            "advanced": {"enabled": True, "reason": ""},
        }

    def update_workflow_availability(self):
        states = self._workflow_dependency_state()
        current_index = int(self.left_panel_stack.currentIndex()) if hasattr(self, "left_panel_stack") else 0
        page_order = ["media", "language", "voice", "style", "filter", "advanced"]

        for page_key, state in states.items():
            container = getattr(self, "workflow_page_containers", {}).get(page_key) if hasattr(self, "workflow_page_containers") else None
            hint = getattr(self, "workflow_page_hints", {}).get(page_key) if hasattr(self, "workflow_page_hints") else None
            tab_btn = getattr(self, "workflow_tab_buttons", {}).get(page_key) if hasattr(self, "workflow_tab_buttons") else None
            enabled = bool(state.get("enabled"))
            reason = str(state.get("reason", "") or "").strip()
            if container is not None:
                container.setEnabled(enabled)
            if hint is not None:
                hint.setText("" if enabled else reason)
                hint.setVisible(not enabled and bool(reason))
            if tab_btn is not None:
                tab_btn.setEnabled(enabled)
                tab_btn.style().unpolish(tab_btn)
                tab_btn.style().polish(tab_btn)

        active_key = page_order[current_index] if 0 <= current_index < len(page_order) else "media"
        active_state = states.get(active_key, {"enabled": True})
        if not active_state.get("enabled", True):
            for fallback_key in ("media", "advanced"):
                fallback_index = page_order.index(fallback_key)
                fallback_state = states.get(fallback_key, {"enabled": True})
                if fallback_state.get("enabled", True):
                    btn = getattr(self, "workflow_tab_buttons", {}).get(fallback_key) if hasattr(self, "workflow_tab_buttons") else None
                    if btn is not None:
                        btn.setChecked(True)
                    elif hasattr(self, "left_panel_stack"):
                        self.left_panel_stack.setCurrentIndex(fallback_index)
                    break

    def update_guidance_panel(self):
        guidance = build_guidance_state(
            video_path=self.video_path_edit.text(),
            transcript_text=self.transcript_text.toPlainText(),
            translated_text=self.translated_text.toPlainText(),
            translated_srt_path=self.last_translated_srt_path,
            selected_audio_path=self.resolve_selected_audio_path(),
            mode=self.get_output_mode_key(),
            pipeline_active=getattr(self, "_pipeline_active", False),
            mode_label=self.output_mode_combo.currentText(),
        )
        self.update_preview_context_label(guidance["has_subtitles"], guidance["has_voice_audio"])


    def sync_left_panel_container_width(self):
        scroll_area = getattr(self, "left_panel_scroll_area", None)
        container = getattr(self, "left_panel_container", None)
        if not scroll_area or not container:
            return
        viewport_width = max(0, scroll_area.viewport().width())
        if viewport_width <= 0:
            return
        gutter = 10
        target_width = max(320, viewport_width - gutter)
        container.setMaximumWidth(target_width)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            scroll_area = getattr(self, "left_panel_scroll_area", None)
            if scroll_area and watched in (scroll_area, scroll_area.viewport(), scroll_area.verticalScrollBar()):
                QTimer.singleShot(0, self.sync_left_panel_container_width)
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Undo):
            focused = self.focusWidget()
            if isinstance(focused, (QTextEdit, QLineEdit)):
                super().keyPressEvent(event)
                return
            if self.undo_last_timeline_timing_edit():
                event.accept()
                return
        if event.matches(QKeySequence.Redo):
            focused = self.focusWidget()
            if isinstance(focused, (QTextEdit, QLineEdit)):
                super().keyPressEvent(event)
                return
            if self.redo_last_timeline_timing_edit():
                event.accept()
                return
        super().keyPressEvent(event)

    def toggle_controls_panel(self):
        # Hide-controls is disabled - the workflow panel is always visible.
        self.set_controls_panel_visible(True)

    def set_controls_panel_visible(self, visible: bool):
        # The workflow panel is always visible. Hide-controls is disabled.
        if hasattr(self, "left_panel_scroll_area"):
            self.left_panel_scroll_area.setVisible(True)
        QTimer.singleShot(0, self._resync_preview_region_overlays)

    def _resync_preview_region_overlays(self):
        try:
            self._sync_blur_controls()
        except Exception:
            pass
        try:
            self._update_ocr_overlay()
        except Exception:
            pass

    def update_progress_checklist(self):
        self.update_workflow_stage_badges()

    def _completed_translation_provider_label(self) -> str:
        """Return the provider recorded in completed translation segments.

        This intentionally reads the result metadata rather than Settings:
        an unavailable AI provider can finish a run through Google Translate.
        """
        models = list(getattr(self, "current_translated_segment_models", []) or [])
        provider_counts = {}
        for model in models:
            provider = str(getattr(model, "metadata", {}).get("translation_provider", "") or "").strip().lower()
            if provider:
                provider_counts[provider] = provider_counts.get(provider, 0) + 1
        if not provider_counts:
            return ""
        provider = max(provider_counts, key=provider_counts.get)
        names = {
            "google-web": "Google Translate",
            "google": "Google Translate",
            "gemini": "Google AI Studio",
            "google_ai_studio": "Google AI Studio",
            "deepseek": "DeepSeek",
            "openai": "OpenAI",
            "ollama": "Ollama",
        }
        return names.get(provider, provider.replace("-", " ").title())

    def update_workflow_stage_badges(self):
        """Reflect persisted workflow artifacts in the left-side milestones."""
        badges = getattr(self, "workflow_stage_badges", {}) or {}
        labels = getattr(self, "workflow_stage_labels", {}) or {}
        if not badges:
            return
        video_path = str(self.video_path_edit.text() if hasattr(self, "video_path_edit") else "").strip()
        state = getattr(self, "current_project_state", None)
        artifacts = getattr(state, "artifacts", {}) or {}
        steps = getattr(state, "steps", {}) or {}
        has_video = bool(video_path and os.path.exists(video_path))
        transcript = bool(self.current_segments) or bool(artifacts.get("transcript_segments"))
        # PrepareWorkflow writes a compatibility SRT even when translation is
        # intentionally skipped. Only a completed translation artifact/step
        # unlocks the next Step-by-Step action.
        translation_status = str(steps.get("translate_raw", "")).lower()
        # A retained translation artifact is useful for legacy projects, but
        # it must not make the phase look completed while a new translation
        # is running or after the user stopped it.
        translated = (
            False if translation_status in {"running", "failed"}
            else translation_status == "done" or bool(artifacts.get("translation_final"))
        )
        tts_skipped = bool(state and state.settings.get("tts_skipped", False))
        voice = not tts_skipped and bool(
            artifacts.get("voice_vi") or artifacts.get("mixed_vi") or self.last_voice_vi_path or self.last_mixed_vi_path
        )
        exported = bool(artifacts.get("final_video"))
        running = str(getattr(self, "_pipeline_step", "") or "") if getattr(self, "_pipeline_active", False) else ""
        values = {
            "prepare": (has_video, "prepare"),
            "transcript": (transcript, "prepare"),
            "translate": (translated, "translation"),
            "tts": (voice, "voiceover"),
            "export": (exported, "export"),
        }
        for key, (complete, running_step) in values.items():
            label = labels.get(key)
            if label is not None and key == "translate":
                provider = self._completed_translation_provider_label() if complete else ""
                label.setText(f"3. Dịch thuật — {provider}" if provider else "3. Dịch thuật")
            badge = badges.get(key)
            if badge is None:
                continue
            is_running = running == running_step or (key == "transcript" and running == "prepare")
            if is_running:
                text, color = "Đang xử lý…", "#f6c453"
            elif complete:
                text, color = "✓ Hoàn thành", "#6ee7d6"
            elif key == "tts" and translated:
                text, color = "Tùy chọn", "#8394aa"
            else:
                text, color = "Chưa bắt đầu", "#8394aa"
            badge.setText(text)
            badge.setStyleSheet(f"color: {color}; font-weight: 700;")

        # Step-by-Step is deliberately linear until translation is complete.
        # Translation remains repeatable, like TTS: users often adjust the
        # provider, prompt, or source subtitles and need to run it again
        # without transcribing the video a second time.
        if hasattr(self, "_generate_transcript_action"):
            self._generate_transcript_action.setEnabled(has_video and not transcript and not self._pipeline_active)
        if hasattr(self, "_generate_translate_action"):
            self._generate_translate_action.setEnabled(transcript and not self._pipeline_active)
            self._generate_translate_action.setText("Re-translate" if translated else "Auto Translate")
        if hasattr(self, "_generate_import_translated_srt_action"):
            self._generate_import_translated_srt_action.setEnabled(transcript and not self._pipeline_active)
        if hasattr(self, "_generate_tts_action"):
            self._generate_tts_action.setEnabled(
                # TTS is intentionally repeatable: subtitle/voice edits may
                # require regenerating audio after this stage was completed.
                translated and not self._pipeline_active
                and self.get_output_mode_key() in ("voice", "both")
            )
        if hasattr(self, "_generate_tts_skip_action"):
            self._generate_tts_skip_action.setEnabled(translated and not self._pipeline_active)

    def update_preview_context_label(self, has_subtitles: bool, has_voice_audio: bool):
        subtitle_source = "Vietnamese review track" if self.current_translated_segments else ("original subtitle track" if self.current_segments else "no subtitle track yet")
        # Audio is composed from independent timeline tracks now; do not
        # surface the removed "Use generated..." / "Use existing..." source
        # selector terminology in the preview context text.
        audio_parts = []
        if has_voice_audio:
            audio_parts.append("generated voice")
        if self._music_audio_tracks():
            audio_parts.append("music")
        audio_source = " + ".join(audio_parts) if audio_parts else "original audio"
        self.preview_context_label.setText(
            build_preview_context_text(
                video_ready=bool(self.video_path_edit.text().strip()),
                has_subtitles=has_subtitles,
                has_voice_audio=has_voice_audio,
                subtitle_source=subtitle_source,
                audio_source=audio_source,
            )
        )







    def _sync_preview_output_canvas_dimensions(self):
        """Set the current output canvas before any preview-layer refresh.

        Text can exist without TS1 subtitles, so it must not depend on the
        subtitle-style path to learn that Ratio/Quality changed.
        """
        view = getattr(self, "video_view", None)
        if view is None or not hasattr(view, "set_subtitle_render_dimensions"):
            return
        width, height = self._subtitle_render_dimensions()
        view.set_subtitle_render_dimensions(width, height)




    def on_single_line_toggled(self, checked: bool):
        self.update_subtitle_preview_style()
        if not self.current_translated_segments:
            return
        if checked:
            self._split_segments_for_single_line()
        else:
            self._single_line_split_cache = None
        self.apply_segments_to_timeline()
        self.schedule_live_subtitle_preview_refresh()



    def _build_render_highlight_lists(self, style_segments):
        mode = self.subtitle_highlight_mode_combo.currentText().strip() if hasattr(self, "subtitle_highlight_mode_combo") else "Auto"
        include_auto = mode in ("Auto", "Auto + Manual")
        include_manual = mode in ("Manual", "Auto + Manual")
        rows = []
        for seg in style_segments or []:
            merged = []
            seen = set()
            if include_auto:
                for phrase in seg.get("auto_highlights", []) or []:
                    normalized = self._normalize_manual_highlight(phrase)
                    key = normalized.lower()
                    if normalized and key not in seen:
                        seen.add(key)
                        merged.append(normalized)
            if include_manual:
                for phrase in seg.get("manual_highlights", []) or []:
                    normalized = self._normalize_manual_highlight(phrase)
                    key = normalized.lower()
                    if normalized and key not in seen:
                        seen.add(key)
                        merged.append(normalized)
            rows.append(merged)
        return rows


    def _update_animation_time_visibility(self):
        current_animation = self.subtitle_animation_combo.currentText().strip().lower()
        show_animation_time = current_animation != "static"
        show_karaoke_timing = current_animation in ("word highlight karaoke", "typewriter")
        if hasattr(self, "subtitle_animation_time_label"):
            self.subtitle_animation_time_label.setVisible(show_animation_time)
        if hasattr(self, "subtitle_animation_time_spin"):
            self.subtitle_animation_time_spin.setVisible(show_animation_time)
        if hasattr(self, "subtitle_karaoke_timing_label"):
            self.subtitle_karaoke_timing_label.setVisible(show_karaoke_timing)
        if hasattr(self, "subtitle_karaoke_timing_combo"):
            self.subtitle_karaoke_timing_combo.setVisible(show_karaoke_timing)


    def refresh_video_dimensions(self, path: str):
        refresh_video_dimensions_impl(self, path, get_video_dimensions)
        self._sync_preview_framing_to_player()

    def _hex_to_ass_color(self, hex_color: str) -> str:
        color = QColor(hex_color)
        return f"&H00{color.blue():02X}{color.green():02X}{color.red():02X}"


    def preview_five_seconds(self):
        self.preview_controller.preview_five_seconds()






    def _update_segment_spoken_status(self, index: int):
        row = self._find_segment_editor_row(index)
        if not row:
            return
        segment = {}
        if 0 <= index < len(self.current_translated_segments or []):
            segment = self.current_translated_segments[index] or {}
        subtitle_text = " ".join(str(segment.get("text", "") or "").split()).strip()
        spoken_text = " ".join(str(segment.get("tts_text") or segment.get("dubbing_vi") or segment.get("text", "")).split()).strip()
        # The per-segment status label was moved to the A2 Dub
        # Track Inspector. Update it there so the inspector reflects
        # whether the spoken text matches the subtitle.
        status_label = getattr(self, "audio_inspector_spoken_status_label", None)
        if status_label is not None:
            if spoken_text and subtitle_text and spoken_text != subtitle_text:
                status_label.setText("Spoken text differs from subtitle.")
            elif spoken_text:
                status_label.setText("Spoken text matches subtitle.")
            else:
                status_label.setText("")


    def on_segment_spoken_text_edited(self, index: int, editor: QTextEdit):
        if getattr(self, "_syncing_segment_editor", False):
            return
        if not (0 <= index < len(self.current_translated_segments or [])):
            return
        value = " ".join(editor.toPlainText().split()).strip()
        segment = self.current_translated_segments[index]
        segment["tts_text"] = value
        segment["dubbing_vi"] = value
        segment["voice_edited"] = True
        self._voiceover_force_refresh = True
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self.persist_current_timeline_project_data()
        self._update_segment_spoken_status(index)
        self.refresh_ui_state()


    def _normalize_manual_highlight(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").replace("\u2029", " ").replace("\n", " ")).strip()

    def refresh_auto_keyword_highlights(self, force: bool = False):
        if not getattr(self, "current_translated_segments", None):
            return
        if not getattr(self, "subtitle_keyword_highlight_cb", None) or not self.subtitle_keyword_highlight_cb.isChecked():
            return
        if not hasattr(self, "subtitle_highlight_mode_combo") or self.subtitle_highlight_mode_combo.currentText().strip() not in ("Auto", "Auto + Manual"):
            return

        pending_indexes = []
        pending_texts = []
        for idx, segment in enumerate(self.current_translated_segments or []):
            text = ' '.join(str(segment.get("text") or "").replace("\n", " ").split()).strip()
            if not text:
                segment["auto_highlights"] = []
                continue
            cached_key = segment.get("_auto_highlights_source_text", "")
            if not force and cached_key == text and isinstance(segment.get("auto_highlights"), list):
                continue
            pending_indexes.append(idx)
            pending_texts.append(text)

        if not pending_texts:
            return

        self.log(f"[Auto Highlight] Generating highlight phrases for {len(pending_texts)} subtitle lines...")
        resolved_batches = [
            [candidate.text for candidate in auto_select_matches(text, max_keywords=2)]
            for text in pending_texts
        ]

        for idx, phrases in zip(pending_indexes, resolved_batches):
            segment = self.current_translated_segments[idx]
            text = ' '.join(str(segment.get("text") or "").replace("\n", " ").split()).strip()
            cleaned = []
            seen = set()
            lowered = text.lower()
            for phrase in phrases or []:
                normalized = self._normalize_manual_highlight(phrase)
                key = normalized.lower()
                if not normalized or key in seen or key not in lowered:
                    continue
                seen.add(key)
                cleaned.append(normalized)
            segment["auto_highlights"] = cleaned
            segment["_auto_highlights_source_text"] = text

        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)

    def _reconcile_manual_highlights(self, segment: dict):
        text = str(segment.get("text", ""))
        cleaned = []
        seen = set()
        for phrase in segment.get("manual_highlights", []):
            normalized = self._normalize_manual_highlight(phrase)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen or key not in text.lower():
                continue
            seen.add(key)
            cleaned.append(normalized)
        segment["manual_highlights"] = cleaned


    def add_segment_manual_highlight(self, index: int, editor: QTextEdit):
        if index < 0 or index >= len(self.current_translated_segments):
            QMessageBox.warning(self, "Highlight", "Please prepare translated subtitles first.")
            return

        selected_text = self._normalize_manual_highlight(editor.textCursor().selectedText())
        if not selected_text:
            QMessageBox.warning(self, "Highlight", "Select the translated text you want to highlight first.")
            return

        segment = self.current_translated_segments[index]
        segment.setdefault("manual_highlights", [])
        existing = {self._normalize_manual_highlight(item).lower() for item in segment.get("manual_highlights", [])}
        if selected_text.lower() not in existing:
            segment["manual_highlights"].append(selected_text)
        self._reconcile_manual_highlights(segment)
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_segment_highlight_chip_row(index)
        self._sync_hidden_translated_text_from_segments()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def remove_segment_manual_highlight(self, index: int, phrase: str):
        if index < 0 or index >= len(self.current_translated_segments):
            return
        target = self._normalize_manual_highlight(phrase).lower()
        segment = self.current_translated_segments[index]
        segment["manual_highlights"] = [
            item for item in segment.get("manual_highlights", [])
            if self._normalize_manual_highlight(item).lower() != target
        ]
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_segment_highlight_chip_row(index)
        self._sync_hidden_translated_text_from_segments()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()

    def _update_segment_highlight_button_state(self, index: int, editor: QTextEdit):
        row = self._find_segment_editor_row(index)
        if not row:
            return
        button = row.get("highlight_button")
        if button is None:
            return
        has_selection = bool(self._normalize_manual_highlight(editor.textCursor().selectedText()))
        button.setEnabled(has_selection)





    def _get_effective_selected_segment_index(self, rows=None) -> int:
        rows = rows if rows is not None else self._segment_editor_display_rows()
        if not rows:
            return -1
        selected = int(getattr(self, "_selected_segment_index", -1))
        valid_indexes = [int(row.get("segment_index", idx)) for idx, row in enumerate(rows)]
        if selected in valid_indexes:
            return selected
        active_index = self._find_active_segment_index(self.media_player.position(), self.live_preview_segments or self.get_active_segments())
        if active_index in valid_indexes:
            return active_index
        return valid_indexes[0]

    def set_selected_segment_index(self, index: int, *, sync_ui: bool = True):
        rows = self._segment_editor_display_rows()
        valid_indexes = [int(row.get("segment_index", idx)) for idx, row in enumerate(rows)]
        if not valid_indexes:
            self._selected_segment_index = -1
        elif index in valid_indexes:
            self._selected_segment_index = int(index)
        else:
            self._selected_segment_index = valid_indexes[0]
        if sync_ui:
            self.sync_segment_editor_rows()
        if hasattr(self, "subtitle_list_view") and self.subtitle_list_view:
            try:
                self.subtitle_list_view.select_card(self._selected_segment_index, seek=False)
            except Exception:
                pass
        if hasattr(self, "_refresh_audio_inspector_dub_voice_buttons"):
            try:
                self._refresh_audio_inspector_dub_voice_buttons()
            except Exception:
                pass







    def _set_deferred_effect_edit_target(self, track=None, layer=None) -> bool:
        """Suppress exactly one selected Blur/Mask effect while paused.

        Overlay geometry continues to update normally; only the MPV filter
        contribution of the selected clip is deferred until it is committed.
        """
        next_type = ""
        next_id = ""
        if layer is not None and not self._preview_is_playing():
            layer_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower()
            track_name = str(getattr(track, "name", "") or "")
            if layer_type == "blur" and track_name == "B1":
                next_type, next_id = "blur", str(getattr(layer, "id", "") or "")
            elif layer_type == "mask" and track_name == "M1":
                next_type, next_id = "mask", str(getattr(layer, "id", "") or "")
        changed = (
            next_type != str(getattr(self, "_deferred_effect_edit_type", "") or "")
            or next_id != str(getattr(self, "_deferred_effect_edit_layer_id", "") or "")
        )
        if changed:
            previous_id = str(getattr(self, "_deferred_effect_edit_layer_id", "") or "")
            # Restore the previously edited layer before changing the shared
            # target. This prevents a stale suppression from surviving a
            # Blur A -> Blur B or Mask A -> Mask B selection switch.
            if previous_id and not self._preview_is_playing():
                self._deferred_effect_edit_type = ""
                self._deferred_effect_edit_layer_id = ""
                self._timed_layer_preview_signature = None
                self.refresh_timed_layer_preview()
            self._deferred_effect_edit_type = next_type
            self._deferred_effect_edit_layer_id = next_id
            self._timed_layer_preview_signature = None
        return changed

    def commit_deferred_effect_editing(self, *, refresh: bool = True) -> bool:
        """Restore a deferred Blur/Mask effect using its final geometry."""
        if not getattr(self, "_deferred_effect_edit_layer_id", ""):
            return False
        self._deferred_effect_edit_type = ""
        self._deferred_effect_edit_layer_id = ""
        self._timed_layer_preview_signature = None
        if refresh:
            self.refresh_timed_layer_preview()
        return True

    def prepare_preview_for_review_mode(self) -> None:
        """Commit paused edits and remove every preview editing affordance.

        Called immediately before playback starts so the frame entering
        Review Mode already contains the final Blur/Mask graph, rather than
        waiting for the asynchronous media-player state notification.
        """
        self._preview_edit_layer_id = ""
        self.commit_deferred_effect_editing(refresh=False)
        if hasattr(self, "video_view"):
            if hasattr(self.video_view, "subtitle_item"):
                self.video_view.subtitle_item.set_editable(False)
            if hasattr(self.video_view, "set_blur_edit_enabled"):
                self.video_view.set_blur_edit_enabled(False)
            mask_overlay = getattr(self.video_view, "mask_overlay", None)
            if mask_overlay is not None:
                mask_overlay.set_editable(False)
            logo_overlay = getattr(self.video_view, "logo_overlay", None)
            if logo_overlay is not None:
                logo_overlay.set_editable(False)
        self._timed_layer_preview_signature = None
        self._refresh_text_layer_preview("")
        self.refresh_timed_layer_preview()













    def _clear_effect_selection_after_delete(self):
        """Leave deleted Blur/Mask layers in a neutral, non-editing state."""
        self._deferred_effect_edit_type = ""
        self._deferred_effect_edit_layer_id = ""
        self._preview_edit_layer_id = ""
        self._timed_layer_preview_signature = None
        timeline = getattr(self, "timeline", None)
        model = getattr(timeline, "_timeline", None) if timeline is not None else None
        video_layer_id = ""
        video_track = None
        video_layer = None
        for track in getattr(model, "tracks", []) or []:
            track_type = str(getattr(getattr(track, "type", ""), "value", getattr(track, "type", ""))).lower()
            if track_type != "video" and str(getattr(track, "name", "")) != "V1 Video":
                continue
            if track.layers:
                video_track, video_layer = track, track.layers[0]
                video_layer_id = str(getattr(video_layer, "id", "") or "")
                break
        # If the M1 track was removed with its final layer, clear the
        # independent top-level overlay as well as the MPV effect. The
        # overlay is not owned by the timeline scene and can otherwise keep
        # painting its last region after the model is empty.
        has_mask_layers = any(
            str(getattr(track, "name", "")) == "M1" and bool(getattr(track, "layers", []))
            for track in getattr(model, "tracks", []) or []
        )
        if not has_mask_layers and hasattr(self, "video_view"):
            try:
                if hasattr(self.video_view, "clear_mask_region"):
                    self.video_view.clear_mask_region()
                elif getattr(self.video_view, "mask_overlay", None) is not None:
                    self.video_view.mask_overlay.clear_region()
            except Exception:
                pass
        if video_layer_id:
            timeline._selected_layer_id = video_layer_id
            self.on_timeline_layer_selected(video_layer_id)
        else:
            timeline._selected_layer_id = ""
            self.refresh_timed_layer_preview()






































    AUDIO_MIX_PRESETS = {
        "original_only": (100, 0),
        "prefer_original": (80, 20),
        "balanced": (100, 100),
        "prefer_dub": (20, 80),
        "dub_only": (0, 100),
    }

    def on_audio_mix_preset_changed(self):
        if not hasattr(self, "audio_mix_preset_combo"):
            return
        preset_key = str(self.audio_mix_preset_combo.currentData() or "").strip().lower()
        if preset_key in self.AUDIO_MIX_PRESETS:
            a1_val, a2_val = self.AUDIO_MIX_PRESETS[preset_key]
            if hasattr(self, "audio_a1_volume_slider"):
                self.audio_a1_volume_slider.blockSignals(True)
                self.audio_a1_volume_slider.setValue(a1_val)
                self.audio_a1_volume_slider.blockSignals(False)
            if hasattr(self, "audio_a1_volume_label"):
                self.audio_a1_volume_label.setText(f"{int(a1_val)}%")
            if hasattr(self, "audio_a2_volume_slider"):
                self.audio_a2_volume_slider.blockSignals(True)
                self.audio_a2_volume_slider.setValue(a2_val)
                self.audio_a2_volume_slider.blockSignals(False)
            if hasattr(self, "audio_a2_volume_label"):
                self.audio_a2_volume_label.setText(f"{int(a2_val)}%")
            self._apply_audio_mix_to_tracks(a1_val, a2_val)

    def on_audio_a1_volume_changed(self, value: int):
        if hasattr(self, "audio_a1_volume_label"):
            self.audio_a1_volume_label.setText(f"{int(value)}%")
        self._sync_audio_track_volume("A1 Audio", int(value))
        self._set_audio_mix_preset_custom()

    def on_audio_a2_volume_changed(self, value: int):
        if hasattr(self, "audio_a2_volume_label"):
            self.audio_a2_volume_label.setText(f"{int(value)}%")
        self._sync_audio_track_volume("TS1", int(value))
        # Music is composed into the dubbed sidecar.  Changing the TTS level
        # must rebuild that sidecar even when the TTS level becomes 0%, so the
        # music-only result is loaded instead of leaving the previous render.
        if self._music_audio_tracks():
            self._schedule_preview_audio_refresh(force=True)
        self._set_audio_mix_preset_custom()

    def on_audio_music_volume_changed(self, value: int):
        if hasattr(self, "audio_music_volume_label"):
            self.audio_music_volume_label.setText(f"{int(value)}%")
        self._sync_audio_track_volume("A2 Music", int(value))
        # The music level is baked into the composed dubbed sidecar. Refresh
        # immediately so a prior original-only sidecar cannot remain audible
        # after the user enables/raises Music.
        self._schedule_preview_audio_refresh(force=True)

    def _apply_audio_mix_to_tracks(self, a1_val: int, a2_val: int):
        self._sync_audio_track_volume("A1 Audio", a1_val)
        self._sync_audio_track_volume("TS1", a2_val)

    def _sync_audio_track_volume(self, track_name: str, volume: int):
        if not hasattr(self, "timeline") or self.timeline is None:
            return
        # TS1 is the current dubbed/subtitle track name; A2 Dub is retained
        # for projects created by older releases.  Treat both as the same
        # logical TTS volume control so a restored legacy timeline cannot
        # silently ignore a slider update.
        names = {str(track_name)}
        if str(track_name) in {"TS1", "A2 Dub"}:
            names.update({"TS1", "A2 Dub"})
        for t in self.timeline._timeline.tracks:
            if str(getattr(t, "name", "")) in names:
                if not isinstance(t.metadata, dict):
                    t.metadata = {}
                t.metadata["_volume"] = float(volume)
                self._apply_audio_track_settings(str(getattr(t, "name", track_name)))
                self.schedule_timeline_project_persist()


    def _set_audio_mix_preset_custom(self):
        if not hasattr(self, "audio_mix_preset_combo"):
            return
        idx = self.audio_mix_preset_combo.findData("custom")
        if idx >= 0 and self.audio_mix_preset_combo.currentIndex() != idx:
            self.audio_mix_preset_combo.setCurrentIndex(idx)


    def _get_audio_track_meta(self, track_name: str) -> dict:
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return {}
        for t in self.timeline._timeline.tracks:
            if t.name == track_name:
                if not isinstance(t.metadata, dict):
                    t.metadata = {}
                return t.metadata
        return {}

    def _get_audio_track_volume(self, track_name: str) -> float:
        meta = self._get_audio_track_meta(track_name)
        default_vol = 50.0 if track_name.startswith("A1") else 100.0
        try:
            return float(meta.get("_volume", default_vol))
        except (TypeError, ValueError):
            return default_vol

    def _get_audio_track_gain_db(self, track_name: str) -> float:
        meta = self._get_audio_track_meta(track_name)
        try:
            return float(meta.get("_gain_db", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def _is_audio_track_muted(self, track_name: str) -> bool:
        meta = self._get_audio_track_meta(track_name)
        track_obj = None
        if hasattr(self, "timeline") and self.timeline._timeline:
            track_obj = next(
                (
                    t for t in self.timeline._timeline.tracks
                    if t.name == track_name
                    or (track_name.startswith("A1") and t.name.startswith("A1"))
                    or (track_name.startswith("TS1") and (t.name.startswith("TS1") or t.name.startswith("A2 Dub")))
                    or (track_name.startswith("A2 Music") and (t.name.startswith("A2 Music") or t.name.startswith("A2 Nhạc")))
                ),
                None,
            )
        if bool(meta.get("_muted", False)) or bool(getattr(track_obj, "muted", False)):
            return True
        # A soloed track is never muted by another track's solo. If
        # multiple tracks are soloed, all of them play; the rest are muted.
        if bool(meta.get("_solo", False)) or bool(getattr(track_obj, "solo", False)):
            return False
        # If any OTHER audio track is soloed, this one is muted.
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return False
        for t in self.timeline._timeline.tracks:
            if t.name == track_name:
                continue
            other_name = str(getattr(t, "name", "") or "")
            is_audio = other_name.startswith(("A1", "A2")) or other_name in ("TS1", "A2 Dub")
            if is_audio:
                if bool(getattr(t, "solo", False)) or (
                    isinstance(t.metadata, dict) and bool(t.metadata.get("_solo", False))
                ):
                    return True
        return False

    def _compute_audio_track_volume(self, track_name: str, base: float = 100.0) -> float:
        meta = self._get_audio_track_meta(track_name)
        default_base = 50.0 if track_name.startswith("A1") else base
        try:
            v = float(meta.get("_volume", default_base))
        except (TypeError, ValueError):
            v = default_base
        return max(0.0, min(200.0, v))

    def on_track_mute_toggled(self, track_name: str, is_muted: bool):
        """Handle timeline audio track mute toggling.
        Maps timeline mute to per-track mute on the dual-track player.
        """
        if not hasattr(self, "timeline") or not self.timeline._timeline:
            return
        is_a1 = track_name.startswith("A1") or track_name in ("A1 Audio", "A1 Âm thanh")
        is_dub = track_name.startswith("TS1") or track_name.startswith("A2 Dub") or track_name in ("A2 Dub", "TS1", "TS1 Phụ đề")
        is_music = track_name.startswith("A2 Music") or track_name in ("A2 Music", "A2 Nhạc nền")

        for t in self.timeline._timeline.tracks:
            t_is_match = (
                t.name == track_name
                or (is_a1 and (t.name.startswith("A1") or t.name in ("A1 Audio", "A1 Âm thanh")))
                or (is_dub and (t.name.startswith("TS1") or t.name.startswith("A2 Dub") or t.name in ("A2 Dub", "TS1", "TS1 Phụ đề")))
                or (is_music and (t.name.startswith("A2 Music") or t.name in ("A2 Music", "A2 Nhạc nền")))
            )
            if t_is_match:
                t.muted = is_muted
                if not isinstance(t.metadata, dict):
                    t.metadata = {}
                t.metadata["_muted"] = bool(is_muted)

        muted = bool(is_muted)
        if is_a1:
            self._mute_original = muted
            if hasattr(self, "media_player") and self.media_player is not None:
                try:
                    if not muted:
                        orig_audio = self._resolve_preview_original_audio_path()
                        if orig_audio and hasattr(self.media_player, "set_original_audio_file"):
                            cur_loaded = getattr(self.media_player, "_original_loaded_path", "")
                            if not cur_loaded or cur_loaded != orig_audio:
                                self.media_player.set_original_audio_file(orig_audio)
                    self.media_player.set_mute_original(muted)
                except Exception:
                    pass
        elif is_dub:
            self._mute_dubbed = muted
            if hasattr(self, "media_player") and self.media_player is not None:
                try:
                    # A composed dubbed sidecar may still contain Music;
                    # rebuild it with TS1 muted instead of muting the whole
                    # sidecar (which would incorrectly silence Music too).
                    if bool(self._music_audio_tracks()):
                        self.media_player.set_mute_dubbed(False)
                        self._schedule_preview_audio_refresh(force=True)
                    else:
                        if not muted:
                            _, dubbed_audio = self._resolve_preview_dubbed_playback_source()
                            if dubbed_audio and hasattr(self.media_player, "set_audio_file"):
                                cur_dubbed = getattr(self.media_player, "_dubbed_loaded_path", "")
                                if not cur_dubbed or cur_dubbed != dubbed_audio:
                                    self.media_player.set_audio_file(dubbed_audio)
                        self.media_player.set_mute_dubbed(muted)
                except Exception:
                    pass

        if is_music:
            # Music shares the generated-audio sidecar, so its mute state is
            # reflected by rebuilding the TTS+music preview mix.  The track
            # itself remains independent in the timeline/export model.
            self._schedule_preview_audio_refresh(force=True)

        if hasattr(self, "track_label_bar"):
            self.track_label_bar.set_muted(track_name, muted)

        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
        self.schedule_timeline_project_persist()




    def on_track_text_toggled(self, track_name: str, is_shown: bool):
        """Show or hide every Text layer in the T1 track without changing export data."""
        timeline = getattr(self, "timeline", None)
        if timeline is not None and timeline._timeline:
            for track in timeline._timeline.tracks:
                if track.name == track_name:
                    self._text_track_preview_visible = bool(is_shown)
                    timeline._redraw()
                    self._refresh_text_layer_preview(getattr(timeline, "_selected_layer_id", ""))
                    if hasattr(self, "track_label_bar"):
                        self.track_label_bar.set_text_shown(track_name, bool(is_shown))
                    self.log(f"[Timeline] {'Shown' if is_shown else 'Hidden'} text track: {track_name}")
                    self.schedule_timeline_project_persist()
                    return


    def on_track_label_selected(self, track_name: str):
        """Select the first layer in a track; label clicks never toggle state."""
        timeline = getattr(self, "timeline", None)
        if timeline is None or not timeline._timeline:
            return
        for track in timeline._timeline.tracks:
            if track.name == track_name and track.layers:
                timeline.select_layer(track.layers[0].id)
                return




    def _sync_hidden_transcript_text_from_segments(self):
        if getattr(self, "_syncing_segment_editor", False):
            return
        self._syncing_hidden_editor_text = True
        try:
            self.transcript_text.setText(self.format_to_srt(self.current_segments))
        finally:
            self._syncing_hidden_editor_text = False

    def _apply_segment_timing(self, segment: dict, start: float, end: float):
        segment["start"] = float(start)
        segment["end"] = float(end)
        if "tts_group_start" in segment or "tts_group_end" in segment:
            segment["tts_group_start"] = float(start)
            segment["tts_group_end"] = float(end)










    def transcribe_selected_range_alternate(self):
        timeline = getattr(self, "timeline", None)
        selection = timeline.selection_range() if timeline else None
        if not selection:
            QMessageBox.information(self, "Transcribe Selected Range", "Please create a Selection Range first.")
            return
        if getattr(self, "_alternate_range_transcription_worker", None) is not None:
            return
        video_path = self.video_path_edit.text().strip()
        if not video_path or not os.path.isfile(video_path):
            QMessageBox.warning(self, "Transcribe Selected Range", "Please load a video first.")
            return
        pending = getattr(self, "_alternate_ocr_range_pending", None)
        pending_overlay = getattr(self, "ocr_region_overlay", None)
        # A hidden range-OCR editor is not actionable. It can happen after a
        # window switch or an older pending state, and must not bypass the
        # configuration dialog on the next Alt Transcribe click.
        if pending and (pending_overlay is None or not pending_overlay.isVisible()):
            self.log("[Range OCR] Cleared a stale pending OCR region request.")
            self._alternate_ocr_range_pending = None
            pending = None
            self._update_alt_transcribe_button_label()
        if pending:
            config = dict(pending)
            self._alternate_ocr_range_pending = None
            overlay = getattr(self, "ocr_region_overlay", None)
            if overlay is not None:
                overlay.set_editable(False)
                overlay.hide()
            self._update_alt_transcribe_button_label()
        else:
            config = self._show_range_transcription_dialog(selection)
            if config is None:
                return

        start, end = float(config["start"]), float(config["end"])
        engine_name = str(config["engine"])
        mode = str(config["mode"])
        if engine_name == "whisper" and not self.ensure_required_resources("Range Transcription", include_whisper=True):
            return
        if engine_name == "ocr" and not self.ensure_required_resources("Range Transcription", include_ocr=True):
            return
        if engine_name == "ocr" and not pending:
            overlay = getattr(self, "ocr_region_overlay", None)
            if overlay is None:
                QMessageBox.warning(self, "Range OCR", "The OCR region editor is unavailable.")
                return
            self._alternate_ocr_range_pending = dict(config)
            overlay._requested_visible = True
            overlay.set_editable(True)

            def _show_range_ocr_editor():
                view = getattr(overlay, "_target_view", None)
                if view is None:
                    return
                overlay.setGeometry(QRect(view.mapToGlobal(QPoint(0, 0)), view.size()))
                overlay.show()
                overlay.raise_()
                overlay.update()

            _show_range_ocr_editor()
            QTimer.singleShot(0, _show_range_ocr_editor)
            self._update_alt_transcribe_button_label()
            self.log(
                f"[Range OCR] Region editor opened for {start:.3f}s–{end:.3f}s; "
                f"fps={config['ocr_fps'] or 'Settings default'}. Adjust it, then click Run OCR."
            )
            return

        model = str(config.get("whisper_model", "")) if engine_name == "whisper" else ""
        language = str(config.get("language", "auto"))
        ocr_fps = config.get("ocr_fps") if engine_name == "ocr" else None
        ocr_region = str(config.get("ocr_region", "bottom"))
        settings_summary = (
            f"model={model}, language={language}" if engine_name == "whisper"
            else f"region={ocr_region}, fps={ocr_fps or 'Settings default'}"
        )
        self.log(
            f"[Range Transcription] Running {engine_name} for {start:.3f}s–{end:.3f}s "
            f"({mode}; {settings_summary})."
        )
        worker = AlternateRangeTranscriptionWorker(
            video_path, start, end, engine_name, model, language,
            ocr_region=ocr_region, ocr_fps=ocr_fps,
        )
        # Keep the QThread parented and referenced until its native finished
        # signal fires.  Clearing the only reference from the worker's custom
        # result signal could destroy the QThread while run() was unwinding.
        worker.setParent(self)
        self._alternate_range_transcription_worker = worker
        action_button = getattr(self, "timeline_alt_transcribe_btn", None)
        if action_button is not None:
            action_button.setEnabled(False)
            action_button.setText("Running…")
        def finished(segments, error):
            if action_button is not None:
                action_button.setEnabled(True)
                self._update_alt_transcribe_button_label()
            if error:
                QMessageBox.warning(self, "Transcribe Selected Range", f"{engine_name.title()} failed.\n\n{error}")
                return
            if not segments:
                QMessageBox.information(
                    self, "Transcribe Selected Range",
                    "No subtitle text was detected in this range. Existing subtitle segments were not changed.",
                )
                return
            self._apply_alternate_range_transcript(segments, start, end, mode)
        def cleanup_worker():
            if getattr(self, "_alternate_range_transcription_worker", None) is worker:
                self._alternate_range_transcription_worker = None
            # finished() runs while the worker reference is still retained,
            # so its label refresh intentionally does nothing. Refresh once
            # the native QThread has actually finished and been released.
            self._update_alt_transcribe_button_label()
            worker.deleteLater()
        worker.completed.connect(finished)
        worker.finished.connect(cleanup_worker)
        worker.start()

    def _show_range_transcription_dialog(self, selection):
        """Collect recognition options without changing the project's main source."""
        start, end = (float(selection[0]), float(selection[1]))
        overlaps = any(
            float(seg.get("end", 0.0)) > start and float(seg.get("start", 0.0)) < end
            for seg in list(self.current_segments or [])
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("Chép lời đoạn đã chọn")
        dialog.setMinimumWidth(420)
        dialog.setStyleSheet(
            "QDialog { background: #101b2d; color: #e6eef9; } "
            "QLabel { color: #d7e4f5; } QComboBox { min-height: 28px; }"
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(QLabel(f"Khoảng thời gian: {start:.3f}s – {end:.3f}s", dialog))

        engine_label = QLabel("Công cụ", dialog)
        engine_combo = QComboBox(dialog)
        engine_combo.addItem("Whisper", "whisper")
        engine_combo.addItem("OCR", "ocr")
        default_engine = self._alternate_transcription_engine()
        engine_index = engine_combo.findData(default_engine)
        engine_combo.setCurrentIndex(engine_index if engine_index >= 0 else 0)
        layout.addWidget(engine_label)
        layout.addWidget(engine_combo)

        mode_label = QLabel("Xử lý phụ đề hiện có", dialog)
        mode_combo = QComboBox(dialog)
        mode_combo.addItem("Thay thế các đoạn trùng lặp (khuyên dùng)", "replace")
        mode_combo.addItem("Nối thêm các đoạn mới", "append")
        mode_combo.setCurrentIndex(0 if overlaps else 1)
        layout.addWidget(mode_label)
        layout.addWidget(mode_combo)

        whisper_box = QWidget(dialog)
        whisper_layout = QVBoxLayout(whisper_box)
        whisper_layout.setContentsMargins(0, 0, 0, 0)
        whisper_layout.setSpacing(6)
        whisper_layout.addWidget(QLabel("Mô hình Whisper", whisper_box))
        whisper_model_combo = QComboBox(whisper_box)
        whisper_model_combo.addItem("Base (Nhẹ)", "base")
        whisper_model_combo.addItem("Small (Nhanh)", "small")
        if os.environ.get("CAPCAP_DEVICE", "cuda").strip().lower() == "cuda":
            whisper_model_combo.addItem("Medium (Chất lượng)", "medium")
        current_model = str(self.get_whisper_model_name() or "small").strip().lower()
        model_index = whisper_model_combo.findData(current_model)
        whisper_model_combo.setCurrentIndex(model_index if model_index >= 0 else 0)
        whisper_layout.addWidget(whisper_model_combo)
        whisper_layout.addWidget(QLabel("Ngôn ngữ", whisper_box))
        language_combo = QComboBox(whisper_box)
        source_language = str(self.get_source_language_code() or "auto")
        language_combo.addItem(f"Ngôn ngữ dự án ({source_language})", source_language)
        if source_language != "auto":
            language_combo.addItem("Tự động nhận diện", "auto")
        for label, code in (("Tiếng Trung", "zh"), ("Tiếng Anh", "en"), ("Tiếng Việt", "vi"), ("Tiếng Nhật", "ja"), ("Tiếng Hàn", "ko")):
            if code != source_language:
                language_combo.addItem(label, code)
        whisper_layout.addWidget(language_combo)
        layout.addWidget(whisper_box)

        ocr_box = QWidget(dialog)
        ocr_layout = QVBoxLayout(ocr_box)
        ocr_layout.setContentsMargins(0, 0, 0, 0)
        ocr_layout.setSpacing(6)
        ocr_layout.addWidget(QLabel("Tốc độ lấy mẫu OCR", ocr_box))
        ocr_fps_combo = QComboBox(ocr_box)
        ocr_fps_combo.addItem("Dùng mặc định trong Cài đặt", "settings")
        ocr_fps_combo.addItem("1 FPS (nhẹ máy)", "1")
        ocr_fps_combo.addItem("1.5 FPS", "1.5")
        ocr_fps_combo.addItem("2 FPS", "2")
        ocr_fps_combo.addItem("3 FPS", "3")
        ocr_fps_combo.addItem("4 FPS (chữ xuất hiện nhanh)", "4")
        current_fps = str(os.getenv("OCR_SAMPLING_FPS") or "auto").strip().lower()
        fps_index = ocr_fps_combo.findData(current_fps)
        ocr_fps_combo.setCurrentIndex(fps_index if fps_index >= 0 else 0)
        ocr_layout.addWidget(ocr_fps_combo)
        ocr_hint = QLabel("Sau khi tiếp tục, hãy điều chỉnh vùng OCR trên bản xem trước, sau đó nhấn Chạy OCR.", ocr_box)
        ocr_hint.setWordWrap(True)
        ocr_hint.setObjectName("helperLabel")
        ocr_layout.addWidget(ocr_hint)
        layout.addWidget(ocr_box)

        def update_engine_options():
            is_whisper = engine_combo.currentData() == "whisper"
            whisper_box.setVisible(is_whisper)
            ocr_box.setVisible(not is_whisper)
            dialog.adjustSize()

        engine_combo.currentIndexChanged.connect(update_engine_options)
        update_engine_options()

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_button = QPushButton("Hủy", dialog)
        run_button = QPushButton("Tiếp tục", dialog)
        buttons.addWidget(cancel_button)
        buttons.addWidget(run_button)
        layout.addLayout(buttons)
        cancel_button.clicked.connect(dialog.reject)
        run_button.clicked.connect(dialog.accept)
        if dialog.exec() != QDialog.Accepted:
            return None

        engine_name = str(engine_combo.currentData() or "whisper")
        fps_value = str(ocr_fps_combo.currentData() or "settings")
        return {
            "start": start,
            "end": end,
            "engine": engine_name,
            "mode": str(mode_combo.currentData() or "replace"),
            "whisper_model": str(whisper_model_combo.currentData() or "small"),
            "language": str(language_combo.currentData() or "auto"),
            "ocr_region": str(os.getenv("OCR_SUBTITLE_REGION") or "bottom").strip().lower(),
            "ocr_fps": None if fps_value == "settings" else float(fps_value),
        }

    def _apply_alternate_range_transcript(self, segments, start, end, mode):
        fresh = [
            {"start": max(float(start), float(seg.get("start", start))), "end": min(float(end), float(seg.get("end", end))), "text": str(seg.get("text", "")).strip()}
            for seg in list(segments or []) if str(seg.get("text", "")).strip()
        ]
        if mode == "replace":
            self.current_segments = self._replace_subtitle_segments_in_range(
                self.current_segments, fresh, start, end,
            )
            if self.current_translated_segments:
                self.current_translated_segments = self._replace_subtitle_segments_in_range(
                    self.current_translated_segments, [dict(seg) for seg in fresh], start, end,
                )
        else:
            self.current_segments = sorted(self.current_segments + fresh, key=lambda seg: float(seg.get("start", 0.0)))
            if self.current_translated_segments:
                self.current_translated_segments = sorted(
                    self.current_translated_segments + [dict(seg) for seg in fresh],
                    key=lambda seg: float(seg.get("start", 0.0)),
                )
        self.current_segment_models = self._dict_segments_to_models(self.current_segments, translated=False)
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_hidden_transcript_text_from_segments()
        self._sync_hidden_translated_text_from_segments()
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()
        self.log(f"[Range Transcription] Added {len(fresh)} alternate-engine segment(s).")

    @staticmethod













    def step_selected_segment(self, direction: int):
        rows = self._segment_editor_display_rows()
        valid_indexes = [int(row.get("segment_index", idx)) for idx, row in enumerate(rows)]
        if not valid_indexes:
            self.set_selected_segment_index(-1)
            return
        current = self._get_effective_selected_segment_index(rows)
        try:
            current_pos = valid_indexes.index(current)
        except ValueError:
            current_pos = 0
        target_pos = max(0, min(len(valid_indexes) - 1, current_pos + int(direction)))
        self.set_selected_segment_index(valid_indexes[target_pos], sync_ui=True)







    def _translation_phase_complete(self) -> bool:
        """Return whether translated subtitle data is a completed artifact."""
        state = getattr(self, "current_project_state", None)
        steps = getattr(state, "steps", {}) or {}
        status = str(steps.get("translate_raw", "") or "").strip().lower()
        if status in {"running", "failed", "cancelled", "pending"}:
            return False
        segments_ready = bool(getattr(self, "current_translated_segments", None))
        artifacts = getattr(state, "artifacts", {}) or {}
        artifact_path = str(artifacts.get("translation_final", "") or "").strip()
        artifact_ready = bool(artifact_path and os.path.exists(artifact_path))
        if not (segments_ready or artifact_ready):
            return False
        # Legacy projects may have the artifact but no explicit done status.
        return status == "done" or artifact_ready

        # Do NOT change the inspector collapsed state from here; the
        # toggle button drives the collapse. Other callers (e.g. media_utils
        # on Play) just hide the details without collapsing the shell.







    def sync_segment_editor_from_hidden_text(self):
        if getattr(self, "_syncing_hidden_editor_text", False):
            return

        transcript_text = self.transcript_text.toPlainText().strip()
        if transcript_text and not transcript_text.lower().startswith("transcribing..."):
            # Preserve non-SRT metadata (notably diarization speaker IDs)
            # when the hidden SRT editor is populated during project load.
            parsed_transcript = self._segments_from_editor_text(
                transcript_text, self.current_segments
            )
            if parsed_transcript:
                self.current_segments = parsed_transcript

        translated_text = self.translated_text.toPlainText().strip()
        if translated_text and not translated_text.lower().startswith("translating with "):
            base_segments = self.current_translated_segments or self.current_segments
            parsed_translated = self._segments_from_editor_text(translated_text, base_segments)
            if parsed_translated:
                self.current_translated_segments = parsed_translated

        self.sync_segment_editor_rows()


    def on_segment_translation_edited(self, index: int, editor: QTextEdit):
        if getattr(self, "_syncing_segment_editor", False):
            return

        base_segments = self.current_segments or self.current_translated_segments
        if not base_segments or index >= len(base_segments):
            return

        if len(self.current_translated_segments) != len(base_segments):
            self.current_translated_segments = [
                {
                    "start": float(base.get("start", 0.0)),
                    "end": float(base.get("end", 0.0)),
                    "text": str(self.current_translated_segments[idx].get("text", "")) if idx < len(self.current_translated_segments) else "",
                    "tts_text": str(self.current_translated_segments[idx].get("tts_text", base.get("tts_text", "")) or "") if idx < len(self.current_translated_segments) else str(base.get("tts_text", "") or ""),
                    "tts_group_id": self.current_translated_segments[idx].get("tts_group_id", base.get("tts_group_id", "")) if idx < len(self.current_translated_segments) else base.get("tts_group_id", ""),
                    "tts_group_start": float(self.current_translated_segments[idx].get("tts_group_start", base.get("tts_group_start", base.get("start", 0.0))) or base.get("start", 0.0)) if idx < len(self.current_translated_segments) else float(base.get("tts_group_start", base.get("start", 0.0)) or base.get("start", 0.0)),
                    "tts_group_end": float(self.current_translated_segments[idx].get("tts_group_end", base.get("tts_group_end", base.get("end", 0.0))) or base.get("end", 0.0)) if idx < len(self.current_translated_segments) else float(base.get("tts_group_end", base.get("end", 0.0)) or base.get("end", 0.0)),
                    "words": list(base.get("words", [])),
                    "manual_highlights": list(base.get("manual_highlights", [])),
                    "speaker": str(base.get("speaker", "") or ""),
                }
                for idx, base in enumerate(base_segments)
            ]

        self.current_translated_segments[index]["text"] = editor.toPlainText().strip()
        self.current_translated_segments[index].setdefault("manual_highlights", [])
        self._reconcile_manual_highlights(self.current_translated_segments[index])
        self.current_translated_segment_models = self._dict_segments_to_models(self.current_translated_segments, translated=True)
        self._sync_segment_highlight_chip_row(index)
        self._sync_hidden_translated_text_from_segments()
        self.schedule_live_subtitle_preview_refresh()
        self.refresh_ui_state()


    def _set_segment_editor_highlight(self, active_index: int):
        rows = getattr(self, "_segment_editor_rows", [])
        target_frame = None
        for row in rows:
            row_index = int(row.get("segment_index", -1))
            if row_index == active_index:
                row["frame"].setStyleSheet("QFrame#statusCard { background-color: #153149; border: 1px solid #5fb9ff; border-radius: 14px; }")
                target_frame = row["frame"]
            else:
                row["frame"].setStyleSheet("")
        # Scroll the outer inspector card so the highlighted segment
        # is visible. The inner segment_editor_scroll was flattened;
        # the QScrollArea wrapping the subtitle card is at stack index 0.
        if target_frame is not None and hasattr(self, "inspector_stack"):
            try:
                scroll = self.inspector_stack.widget(0)
                if scroll is not None and hasattr(scroll, "ensureWidgetVisible"):
                    scroll.ensureWidgetVisible(target_frame, 0, 36)
            except Exception:
                pass


    def preview_current_audio_track(self):
        audio_path = self.resolve_selected_audio_path()
        if not audio_path or not os.path.exists(audio_path):
            QMessageBox.warning(self, "Missing Voice", "Please generate voice first before using Preview audio.")
            return
        try:
            self.play_audio_preview_file(audio_path)
            self.log(f"[Audio Preview] playing {audio_path}")
        except Exception as exc:
            self.show_error("Audio Preview Failed", "Could not preview the current audio track.", str(exc))



















    # ---- Mask layer (M1) ----


    def _on_preview_state_changed(self, _state: int):
        """Re-apply the M1 mask filter when the player state changes.

        The mask is only applied to the video while the player is
        playing. Hooked from `media_player.stateChanged` in
        `setup_media_player` so the mpv filter chain is updated on
        play / pause / stop. The mask overlay is also locked
        (`set_editable(False)`) while the video is playing so the
        user cannot accidentally drag or resize the region during
        playback. Also sync the timeline play state so the timeline
        stops running when the video ends (Bug 2).
        """
        try:
            is_playing = bool(self.media_player.is_playing())
        except Exception:
            is_playing = False
        was_review_mode = bool(getattr(self, "_review_mode_active", False))
        self._review_mode_active = is_playing
        if is_playing:
            # Entering review mode is an explicit commit boundary. This
            # restores a deferred Blur/Mask at its final geometry before the
            # next frame is shown, then removes every preview edit target.
            self._preview_edit_layer_id = ""
        if is_playing or was_review_mode:
            # Borders are selection chrome, not rendered layer content.
            # Clear their active state on both Review entry and its pause
            # transition; a subsequent explicit paused selection re-enables
            # only the requested layer.
            if hasattr(self, "video_view") and hasattr(self.video_view, "subtitle_item"):
                self.video_view.subtitle_item.set_editable(False)
            self._refresh_text_layer_preview("")
        if hasattr(self, "track_label_bar"):
            self.track_label_bar.set_controls_enabled(not is_playing)
        splitter = getattr(self, "preview_timeline_splitter", None)
        if splitter is not None:
            try:
                # Review Mode keeps the preview geometry stable so native
                # overlays and MPV effects cannot be disturbed mid-playback.
                # Disable only the handle; never disable the child widgets.
                splitter.handle(1).setEnabled(not is_playing)
            except Exception:
                pass
        # Sync the timeline's "playing" flag to the real player state.
        # Without this the timeline keeps animating past the end of the
        # video because the player auto-pauses (keep_open="always") but
        # nothing tells the timeline to stop.
        try:
            if hasattr(self, "timeline") and self.timeline is not None:
                self.timeline.set_playing(is_playing)
        except Exception:
            pass
        # Lock / unlock editing based on both play state and timeline
        # selection. Pausing must not make every region editable.
        try:
            selected_id = str(getattr(getattr(self, "timeline", None), "_selected_layer_id", "") or "")
            selected_type = ""
            selected_track_name = ""
            selected_track = None
            selected_layer = None
            for track in getattr(getattr(self.timeline, "_timeline", None), "tracks", []) if hasattr(self, "timeline") else []:
                for layer in getattr(track, "layers", []):
                    if str(getattr(layer, "id", "")) == selected_id:
                        selected_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower()
                        selected_track_name = str(getattr(track, "name", ""))
                        selected_track, selected_layer = track, layer
                        break
                if selected_type:
                    break
            if is_playing:
                effect_edit_changed = self.commit_deferred_effect_editing(refresh=False)
            else:
                # Pausing enters Edit Mode, but does not automatically start
                # editing the layer selected before playback. Effects remain
                # rendered and handles remain hidden until the user selects
                # a layer again.
                effect_edit_changed = False
            if effect_edit_changed:
                self.refresh_timed_layer_preview()
            mask_overlay = getattr(self.video_view, "mask_overlay", None)
            if mask_overlay is not None and mask_overlay._regions:
                mask_overlay.set_editable(bool(
                    not is_playing
                    and selected_type == "mask"
                    and selected_track_name == "M1"
                    and selected_id == str(getattr(self, "_preview_edit_layer_id", "") or "")
                    and self._deferred_effect_layer_id_for("mask") == selected_id
                ))
            if hasattr(self, "video_view") and hasattr(self.video_view, "set_blur_edit_enabled"):
                self.video_view.set_blur_edit_enabled(
                    bool(
                        not is_playing
                        and selected_type == "blur"
                        and selected_id == str(getattr(self, "_preview_edit_layer_id", "") or "")
                        and self._deferred_effect_layer_id_for("blur") == selected_id
                        and self._blur_effect_enabled()
                    )
                )
            logo_overlay = getattr(self.video_view, "logo_overlay", None)
            if logo_overlay is not None and getattr(logo_overlay, "_regions", None):
                logo_overlay.set_editable(bool(
                    not is_playing
                    and selected_type == "image"
                    and selected_track_name == "L1 Logo"
                    and selected_id == str(getattr(self, "_preview_edit_layer_id", "") or "")
                ))
            if hasattr(self, "video_view") and getattr(self.video_view, "text_overlay", None) is not None:
                # Keep text content visible but make its top-level overlay
                # click-through in review mode and immediately after pause.
                self.video_view.text_overlay.set_editable(False if (is_playing or was_review_mode) else bool(
                    selected_type == "text" and selected_id == str(getattr(self, "_preview_edit_layer_id", "") or "")
                ))
        except Exception:
            pass
        # When playback just ended, pause both audio sidecars so they
        # don't drift ahead of the held last frame.
        if not is_playing and hasattr(self, "media_player"):
            try:
                if hasattr(self.media_player, "_original_loaded_path") and getattr(self.media_player, "_original_loaded_path", ""):
                    self.media_player._original_player.pause()
            except Exception:
                pass
            try:
                if hasattr(self.media_player, "_dubbed_loaded_path") and getattr(self.media_player, "_dubbed_loaded_path", ""):
                    self.media_player._dubbed_player.pause()
            except Exception:
                pass
        try:
            self._apply_mask_to_preview()
        except Exception:
            pass
        QTimer.singleShot(0, self.refresh_ui_state)












    def preview_segment_audio(self, index: int):
        if index < 0 or index >= len(self.current_translated_segments or self.current_segments):
            QMessageBox.warning(self, "Missing Subtitle", "This subtitle line is not ready yet.")
            return

        if not self.ensure_required_resources("Subtitle audio preview", include_voice=True):
            return

        source_segments = self.current_translated_segments or self.current_segments
        text = str(source_segments[index].get("tts_text") or source_segments[index].get("text", "")).strip()
        if not text:
            QMessageBox.warning(self, "Missing Subtitle", "This subtitle line is empty.")
            return

        voice_name = self.get_active_voice_name()
        if not voice_name:
            QMessageBox.warning(self, "Missing Voice", "Choose a voice first before generating subtitle audio preview.")
            return
        voice_speed = self._parse_voice_speed_value()
        project_state = getattr(self, "current_project_state", None) or self.ensure_current_project()
        project_settings = getattr(project_state, "settings", {}) or {}
        normalizer_dictionary = dict(project_settings.get("normalizer_dictionary", {}) or {})
        row = self._find_segment_editor_row(index)
        # The per-segment "Regenerate voice" button was moved to the
        # A2 Dub Track Inspector. Disable that one instead.
        if getattr(self, "audio_inspector_regenerate_voice_btn", None) is not None:
            self.audio_inspector_regenerate_voice_btn.setEnabled(False)
            self.audio_inspector_regenerate_voice_btn.setText("...")

        existing = self._segment_preview_threads.get(index)
        if existing and existing.isRunning():
            existing.quit()
            existing.wait(2000)
        worker = SegmentAudioPreviewWorker(
            self.workspace_root,
            index,
            text,
            voice_name,
            voice_speed,
            temp_dir=self.get_project_temp_dir("segment_audio_preview"),
            cache_temp_dir=self.get_project_temp_dir("tts"),
            normalizer_dictionary=normalizer_dictionary,
        )
        worker.finished.connect(self.on_segment_audio_preview_ready)
        self._segment_preview_threads[index] = worker
        worker.start()






    def download_original_script(self):
        script_text = self.transcript_text.toPlainText().strip()
        if not script_text:
            QMessageBox.warning(self, "Missing Script", "No original script is ready yet.")
            return
        base_name = os.path.splitext(os.path.basename(self.video_path_edit.text().strip() or "original"))[0] + "_original"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Source Subtitle",
            base_name + ".srt",
            "Subtitle Files (*.srt)",
        )
        if not file_path:
            return
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(script_text)
        QMessageBox.information(self, "Saved", f"Source subtitle exported to:\n\n{file_path}")


    def on_quick_preview_ready(self, output_path, error):
        self.preview_controller.on_quick_preview_ready(output_path, error)



    # -----------------------------
    # Subtitle source handling
    # -----------------------------
    def get_active_segments(self):
        base = self.current_translated_segments or self.current_segments or []
        if base and bool(getattr(self, "subtitle_single_line_cb", None) and self.subtitle_single_line_cb.isChecked()):
            split = getattr(self, "_single_line_split_cache", None)
            if split is not None:
                return split
        return base


    def _segments_from_editor_text(self, srt_text: str, base_segments):
        srt_text = (srt_text or "").strip()
        if not srt_text:
            return []

        if self.keep_timeline_cb.isChecked() and base_segments:
            edited_texts = self.extract_subtitle_text_entries(srt_text)
            if edited_texts and len(edited_texts) == len(base_segments):
                out = []
                for idx, base in enumerate(base_segments):
                    d = {
                        "start": float(base["start"]),
                        "end": float(base["end"]),
                        "text": edited_texts[idx],
                        "tts_text": str(base.get("tts_text", "") or ""),
                        "tts_group_id": base.get("tts_group_id", ""),
                        "tts_group_start": float(base.get("tts_group_start", base.get("start", 0.0)) or 0.0),
                        "tts_group_end": float(base.get("tts_group_end", base.get("end", 0.0)) or 0.0),
                        "words": list(base.get("words", [])),
                        "manual_highlights": list(base.get("manual_highlights", [])),
                    }
                    if base.get("speaker"):
                        d["speaker"] = str(base.get("speaker", "") or "")
                    raw = base.get("_audio_end")
                    if raw is not None:
                        try:
                            d["_audio_end"] = float(raw)
                        except (TypeError, ValueError):
                            pass
                    out.append(d)
                return out

        parsed_segments = self.parse_srt_to_segments(srt_text)
        if base_segments and len(parsed_segments) == len(base_segments):
            for idx, segment in enumerate(parsed_segments):
                base = base_segments[idx]
                segment["words"] = list(base.get("words", []))
                segment["manual_highlights"] = list(base.get("manual_highlights", []))
                if base.get("speaker"):
                    segment["speaker"] = str(base.get("speaker", "") or "")
                if base.get("tts_text"):
                    segment["tts_text"] = str(base.get("tts_text", "") or "")
                    segment["tts_group_id"] = base.get("tts_group_id", "")
                    segment["tts_group_start"] = float(base.get("tts_group_start", base.get("start", 0.0)) or 0.0)
                    segment["tts_group_end"] = float(base.get("tts_group_end", base.get("end", 0.0)) or 0.0)
        return parsed_segments



    @staticmethod




    def _write_live_preview_assets(self, segments):
        if not segments:
            self.live_preview_subtitle_path = ""
            self.live_preview_ass_path = ""
            self._live_preview_signature = None
            self._loaded_live_ass_path = ""
            self._loaded_live_ass_signature = None
            return "", ""

        # Full-block geometry is measured from libass itself.  Scheduling it
        # here keeps all callers (style controls, playback callbacks, project
        # load) non-blocking.  The previous exact track stays visible while a
        # newer style is being measured after the debounce interval.
        if self._uses_exact_full_block_subtitle_background():
            self._schedule_deferred_subtitle_ass_build(segments)
            return self.live_preview_subtitle_path, self.live_preview_ass_path

        # A pending Full Block worker must never re-apply an older ASS file
        # after the user switches the background off (or back to Fit Text).
        self._subtitle_ass_request_token = int(getattr(self, "_subtitle_ass_request_token", 0)) + 1

        preview_dir = self.get_project_temp_dir("preview")
        preview_srt_path = os.path.join(preview_dir, "live_preview_subtitle.srt")

        from subtitle_builder import generate_srt

        video_path = self.video_path_edit.text().strip()
        if (
            video_path
            and os.path.exists(video_path)
            and (
                not getattr(self.video_view, "video_source_width", 0)
                or not getattr(self.video_view, "video_source_height", 0)
            )
        ):
            self.refresh_video_dimensions(video_path)
        source_width = max(1, int(getattr(self.video_view, "video_source_width", 0) or 1920))
        source_height = max(1, int(getattr(self.video_view, "video_source_height", 0) or 1080))
        canvas_width, canvas_height = self._subtitle_render_dimensions()
        subtitle_style = self.get_subtitle_export_style(segments=segments)
        # MPV/libass renders subtitles on the source frame before MPV applies
        # its Fit/Fill presentation transform. Convert custom canvas-relative
        # anchors back into source coordinates so the visible result follows
        # the same point after framing.
        if subtitle_style.get("custom_position_enabled") and (canvas_width != source_width or canvas_height != source_height):
            try:
                scale_mode = self.get_output_scale_mode_key()
                focus_x, focus_y = self.get_output_fill_focus()
                scale = max(canvas_width / source_width, canvas_height / source_height) if scale_mode == "fill" else min(canvas_width / source_width, canvas_height / source_height)
                displayed_w, displayed_h = source_width * scale, source_height * scale
                offset_x = (canvas_width - displayed_w) * (focus_x if scale_mode == "fill" else 0.5)
                offset_y = (canvas_height - displayed_h) * (focus_y if scale_mode == "fill" else 0.5)
                x_canvas = float(subtitle_style.get("custom_position_x", 50.0)) * canvas_width / 100.0
                y_canvas = float(subtitle_style.get("custom_position_y", 86.0)) * canvas_height / 100.0
                subtitle_style["custom_position_x"] = max(0.0, min(100.0, (x_canvas - offset_x) * 100.0 / displayed_w))
                subtitle_style["custom_position_y"] = max(0.0, min(100.0, (y_canvas - offset_y) * 100.0 / displayed_h))
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        video_width, video_height = source_width, source_height
        preview_signature = (
            video_path,
            video_width,
            video_height,
            repr(segments),
            repr(subtitle_style),
        )
        if (
            preview_signature == getattr(self, "_live_preview_signature", None)
            and self.live_preview_subtitle_path
            and os.path.exists(self.live_preview_subtitle_path)
            and self.live_preview_ass_path
            and os.path.exists(self.live_preview_ass_path)
        ):
            return self.live_preview_subtitle_path, self.live_preview_ass_path

        # Subtitle or content changed. We no longer revert the media source!
        # Because we'll disable burned-in subs in muxed previews, the rendered
        # background is already blank-subbed and can host our live overlay/mpv track comfortably.
        # This solves the user's complaint that 'it reverts to original'.

        generate_srt(segments, preview_srt_path)
        self.live_preview_subtitle_path = preview_srt_path
        self.live_preview_ass_path = srt_to_ass(
            preview_srt_path,
            video_width=video_width,
            video_height=video_height,
            alignment=subtitle_style.get("alignment", 2),
            margin_v=subtitle_style.get("margin_v", 30),
            font_name=subtitle_style.get("font_name", "Arial"),
            font_size=subtitle_style.get("font_size", 18),
            font_color=subtitle_style.get("font_color", "&H00FFFFFF"),
            background_box=subtitle_style.get("background_box", False),
            animation_style=subtitle_style.get("animation", "Static"),
            highlight_color=subtitle_style.get("highlight_color", "&H00FFFFFF"),
            outline_color=subtitle_style.get("outline_color", "&H00000000"),
            outline_width=subtitle_style.get("outline_width", 2.0),
            shadow_color=subtitle_style.get("shadow_color", "&H80000000"),
            shadow_depth=subtitle_style.get("shadow_depth", 1.0),
            background_color=subtitle_style.get("background_color", "&H80000000"),
            background_alpha=subtitle_style.get("background_alpha", 0.5),
            background_width=subtitle_style.get("background_width", "fit_text"),
            background_shape=subtitle_style.get("background_shape", "rectangle"),
            background_padding=subtitle_style.get("background_padding", 6),
            background_radius=subtitle_style.get("background_radius", 0),
            bold=subtitle_style.get("bold", False),
            preset_key=subtitle_style.get("preset_key", ""),
            auto_keyword_highlight=subtitle_style.get("auto_keyword_highlight", False),
            animation_duration=subtitle_style.get("animation_duration", 0.22),
            manual_highlights=subtitle_style.get("manual_highlights", []),
            word_timings=subtitle_style.get("word_timings", []),
            speaker_colors=subtitle_style.get("speaker_colors", []),
            custom_position_enabled=subtitle_style.get("custom_position_enabled", False),
            custom_position_x=subtitle_style.get("custom_position_x", 50),
            custom_position_y=subtitle_style.get("custom_position_y", 86),
            custom_position_bottom_y=subtitle_style.get("custom_position_bottom_y"),
            single_line=subtitle_style.get("single_line", False),
            font_scale=subtitle_style.get("font_scale", 1.0),
            log_generation=False,
        )
        self._live_preview_signature = preview_signature
        self.processed_artifacts["subtitle_preview_srt"] = self.live_preview_subtitle_path
        self.processed_artifacts["subtitle_preview_ass"] = self.live_preview_ass_path
        return self.live_preview_subtitle_path, self.live_preview_ass_path

    def _resolve_live_preview_segments(self):
        single_line = bool(getattr(self, "subtitle_single_line_cb", None) and self.subtitle_single_line_cb.isChecked())
        if single_line and self.current_translated_segments:
            return self.get_active_segments(), "translated"

        translated_text = self.translated_text.toPlainText().strip()
        if translated_text and not translated_text.lower().startswith("translating with "):
            base_segments = self.current_translated_segments or self.current_segments
            translated_segments = self._segments_from_editor_text(translated_text, base_segments)
            if translated_segments:
                return translated_segments, "translated"

        transcript_text = self.transcript_text.toPlainText().strip()
        if transcript_text and not transcript_text.lower().startswith("transcribing..."):
            transcript_segments = self._segments_from_editor_text(transcript_text, self.current_segments)
            if transcript_segments:
                return transcript_segments, "transcript"

        return [], ""


    def _find_active_segment_index(self, position_ms: int, segments):
        active = self._find_active_segment_indices(position_ms, segments)
        return active[0] if active else -1

    def _find_active_segment_indices(self, position_ms: int, segments) -> list[int]:
        """Return the indices of every segment whose [start, end] contains
        position_ms. Multiple entries are returned when segments overlap in
        time, so the live overlay can stack them on separate lines.
        """
        position_seconds = max(0.0, float(position_ms) / 1000.0)
        # ``segments`` is already the editor's indexed list. Avoid copying a
        # long TS1 list on each 200 ms playback tick; the cache below only
        # needs its identity and length to detect a replacement.
        source = segments or []
        cache = getattr(self, "_playback_subtitle_activity_cache", None)
        source_key = (id(segments), len(source))
        if cache and cache.get("source_key") == source_key:
            # The end is exclusive so a tick landing exactly on the next cue
            # boundary recalculates the active set immediately.
            if cache["stable_start"] <= position_seconds < cache["stable_end"]:
                return list(cache["active_indices"])

        # This full scan happens only when playback crosses a subtitle/gap
        # boundary. The cached stable interval handles the several position
        # updates that occur while a cue remains unchanged.
        result: list[int] = []
        previous_boundary = 0.0
        next_boundary = None
        for idx, seg in enumerate(source):
            if not isinstance(seg, dict):
                continue
            try:
                start_s = float(seg.get("start", 0.0))
                end_s = float(seg.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            for boundary in (start_s, end_s):
                if boundary <= position_seconds:
                    previous_boundary = max(previous_boundary, boundary)
                else:
                    next_boundary = boundary if next_boundary is None else min(next_boundary, boundary)
            if start_s <= position_seconds <= end_s:
                result.append(idx)
        stable_start = previous_boundary
        stable_end = next_boundary if next_boundary is not None else float("inf")
        self._playback_subtitle_activity_cache = {
            "source_key": source_key,
            "stable_start": stable_start,
            "stable_end": stable_end,
            "active_indices": list(result),
        }
        return result

    def _set_editor_highlight(self, editor, active_index: int):
        if not editor:
            return

        document = editor.document()
        revision = int(document.revision())
        editor_key = id(editor)
        state = (revision, active_index)
        if self._editor_highlight_state.get(editor_key) == state:
            return
        self._editor_highlight_state[editor_key] = state

        selections = []
        cached = self._editor_highlight_chunks.get(editor_key)
        if cached and cached[0] == revision:
            chunks = cached[1]
        else:
            text = editor.toPlainText()
            block_pattern = re.compile(
                r"(^|\n\n)(\d+\n\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}\n.*?)(?=\n\n\d+\n|\Z)",
                re.DOTALL,
            )
            chunks = [(match.start(2), match.end(2)) for match in block_pattern.finditer(text)]
            self._editor_highlight_chunks[editor_key] = (revision, chunks)

        if 0 <= active_index < len(chunks):
            start, end = chunks[active_index]
            selection = QTextEdit.ExtraSelection()
            selection.cursor = editor.textCursor()
            selection.cursor.setPosition(start)
            selection.cursor.setPosition(end, QTextCursor.KeepAnchor)
            selection.format.setBackground(QColor("#183248"))
            selection.format.setForeground(QColor("#EAF6FF"))
            selections.append(selection)
            temp_cursor = editor.textCursor()
            temp_cursor.setPosition(start)
            editor.setTextCursor(temp_cursor)
            editor.ensureCursorVisible()

        editor.setExtraSelections(selections)




    def refresh_ui_state(self):
        """Basic enable/disable rules to guide user flow."""
        # Legacy Audio Source controls are kept only for compatibility with
        # older project/settings data.  Re-assert their hidden state on every
        # UI refresh so playback, project loading, or mode changes cannot
        # accidentally make the obsolete radio buttons appear.
        self._hide_legacy_audio_source_controls()
        review_mode = self._preview_is_playing()
        v_ok = bool(self.video_path_edit.text().strip()) and os.path.exists(self.video_path_edit.text().strip())
        if hasattr(self, "voice_gender_check_btn"):
            worker = getattr(self, "_voice_gender_check_worker", None)
            self.voice_gender_check_btn.setEnabled(v_ok and not (worker and worker.isRunning()))
        if hasattr(self, "voice_gender_history_btn"):
            self.voice_gender_history_btn.setEnabled(v_ok)
        if hasattr(self, "pipeline_b_create_btn"):
            self.pipeline_b_create_btn.setEnabled(True)
        a_ok = bool(self.audio_source_edit.text().strip()) and os.path.exists(self.audio_source_edit.text().strip())
        has_translated_text = bool(self.translated_text.toPlainText().strip())
        translation_ready = self._translation_phase_complete()
        selected_audio_path = self.resolve_selected_audio_path()
        has_voice_audio = bool(selected_audio_path and os.path.exists(selected_audio_path))
        has_subtitle_track = bool(self.last_translated_srt_path and os.path.exists(self.last_translated_srt_path))
        mode = self.get_output_mode_key()
        steps = getattr(getattr(self, "current_project_state", None), "steps", {}) or {}
        voice_running = steps.get("generate_tts") == "running" or steps.get("mix_audio") == "running"
        # Translation is sufficient for a final subtitle-only export.  TTS
        # remains optional: if it has not been generated, Export and Fast
        # Preview retain the source audio and burn the translated subtitles.
        # Voice-only projects without subtitles keep their historical rule.
        can_export = v_ok and (
            has_subtitle_track
            or (mode == "voice" and has_voice_audio)
        )

        self.extract_btn.setEnabled(v_ok)
        self.vocal_sep_btn.setEnabled(a_ok)
        if hasattr(self, "voice_timing_sync_combo") and hasattr(self, "voice_speed_spin"):
            mode = self.voice_timing_sync_combo.currentText().strip().lower()
            self.voice_speed_spin.setEnabled(mode != "off")
        self.transcribe_btn.setEnabled(a_ok)
        self.translate_btn.setEnabled(bool(self.transcript_text.toPlainText().strip()))
        self.apply_translated_btn.setEnabled(translation_ready and has_translated_text)
        if hasattr(self, "rewrite_translation_btn"):
            self.rewrite_translation_btn.setVisible(translation_ready)
            self.rewrite_translation_btn.setEnabled(
                translation_ready and bool(self.transcript_text.toPlainText().strip()) and has_translated_text
            )
        if hasattr(self, "subtitle_editor_btn"):
            self.subtitle_editor_btn.setVisible(translation_ready)
            self.subtitle_editor_btn.setEnabled(translation_ready and not review_mode)
        if hasattr(self, "normalizer_dict_btn"):
            self.normalizer_dict_btn.setVisible(translation_ready)
            self.normalizer_dict_btn.setEnabled(translation_ready and not review_mode)
        if hasattr(self, "rewrite_selected_segment_btn"):
            has_selected_segment = 0 <= int(getattr(self, "_selected_segment_index", -1)) < len(self.current_translated_segments or [])
            self.rewrite_selected_segment_btn.setEnabled(
                translation_ready and bool(self.transcript_text.toPlainText().strip()) and has_translated_text and has_selected_segment
            )
        if hasattr(self, "_refresh_audio_inspector_dub_voice_buttons"):
            self._refresh_audio_inspector_dub_voice_buttons()
        generated_mode = not self.using_existing_audio_source()
        if hasattr(self, "voiceover_btn"):
            self.voiceover_btn.setEnabled(translation_ready and has_translated_text and generated_mode and mode in ("voice", "both"))
        preview_enabled = v_ok and not voice_running
        if hasattr(self, "quick_preview_btn"):
            self.quick_preview_btn.setEnabled(preview_enabled)
        if hasattr(self, "styled_preview_btn"):
            self.styled_preview_btn.setEnabled(preview_enabled)
        if hasattr(self, "preview_btn"):
            self.preview_btn.setVisible(True)
            self.preview_btn.setEnabled(preview_enabled and not getattr(self, "_styled_preview_running", False))
        if hasattr(self, "video_filter_apply_btn"):
            has_active_filters = self.has_active_video_filters() if hasattr(self, "has_active_video_filters") else False
            self.video_filter_apply_btn.setVisible(True)
            self.video_filter_apply_btn.setEnabled(
                self.is_filter_workflow_active()
                and v_ok
                and has_active_filters
                and not getattr(self, "_styled_preview_running", False)
            )
            self.video_filter_apply_btn.setText("Applying..." if getattr(self, "_video_filter_apply_requested", False) and getattr(self, "_styled_preview_running", False) else "Apply Filter")
        is_rendering_filter_preview = bool(getattr(self, "_video_filter_apply_requested", False) and getattr(self, "_styled_preview_running", False))
        if hasattr(self, "video_filter_render_status_label"):
            status_text = ""
            if not self.is_filter_workflow_active():
                status_text = ""
            elif getattr(self, "_video_filter_apply_requested", False) and getattr(self, "_styled_preview_running", False):
                status_text = "Rendering filtered preview video..."
            elif getattr(self, "_video_filter_preview_dirty", False):
                status_text = "Filter changes pending. Click Apply Filter to render motion preview."
            elif self._is_realtime_color_filter_state():
                status_text = "Realtime MPV preview active."
            elif self.has_active_video_filters() if hasattr(self, "has_active_video_filters") else False:
                status_text = "Filtered preview video is ready."
            self.video_filter_render_status_label.setText(status_text)
            self.video_filter_render_status_label.setVisible(bool(status_text))
        if hasattr(self, "video_filter_render_progress"):
            self.video_filter_render_progress.setVisible(self.is_filter_workflow_active() and is_rendering_filter_preview)
        if hasattr(self, "reset_framing_btn"):
            scale_mode = self.get_output_scale_mode_key() if hasattr(self, "get_output_scale_mode_key") else "fit"
            focus_x, focus_y = self.get_output_fill_focus() if hasattr(self, "get_output_fill_focus") else (0.5, 0.5)
            framing_dirty = abs(float(focus_x) - 0.5) > 0.001 or abs(float(focus_y) - 0.5) > 0.001
            self.reset_framing_btn.setVisible(True)
            self.reset_framing_btn.setEnabled(v_ok and scale_mode == "fill" and framing_dirty)
        if hasattr(self, "play_btn"):
            self.play_btn.setEnabled(v_ok and not voice_running and not getattr(self, "_styled_preview_running", False))
        if hasattr(self, "stop_btn"):
            self.stop_btn.setEnabled(v_ok and not voice_running)
        if hasattr(self, "blur_area_btn"):
            self.blur_area_btn.setEnabled(can_export and not review_mode)
        if hasattr(self, "add_music_layer_btn"):
            # Music is an audio track, not a visual overlay; it can be added
            # as soon as a source video is selected, but never while Review
            # Mode is active or a voice/render worker is running.
            source_video = self._resolve_preview_original_video_path()
            self.add_music_layer_btn.setEnabled(bool(source_video) and not review_mode and not voice_running)
        # Overlay tracks are only meaningful once the generated output is
        # ready. Keep their controls disabled before that point so users
        # cannot create layers against an incomplete video workflow.
        self._optional_layer_controls_ready = bool(can_export and not voice_running and not review_mode)
        for button_name in ("blur_add_btn", "add_logo_btn", "add_mask_btn", "add_text_btn"):
            button = getattr(self, button_name, None)
            if button is not None:
                button.setEnabled(self._optional_layer_controls_ready)
        # Subtitle segments are valid as soon as a transcript/translation is
        # available. Keep the shared + Layer menu usable for manual fixes
        # without unlocking the unrelated overlay-layer actions early.
        if hasattr(self, "add_layer_btn"):
            has_subtitle_segments = bool(self.current_segments or self.current_translated_segments)
            self.add_layer_btn.setEnabled((self._optional_layer_controls_ready or has_subtitle_segments) and not review_mode)
        if hasattr(self, "blur_add_btn"):
            self.blur_add_btn.setEnabled(
                self._optional_layer_controls_ready
                and not bool(getattr(self, "_filter_thumbnail_visible", False))
            )
        if hasattr(self, "ocr_region_btn"):
            self.ocr_region_btn.setEnabled(v_ok)
        if hasattr(self, "ocr_translator_btn"):
            self.ocr_translator_btn.setEnabled(v_ok)
        self._sync_blur_controls()
        if hasattr(self, "free_voice_combo"):
            self.free_voice_combo.setEnabled(
                generated_mode
                and mode in ("voice", "both")
            )
        if hasattr(self, "voice_engine_combo"):
            self.voice_engine_combo.setEnabled(generated_mode and mode in ("voice", "both"))
        if hasattr(self, "premium_voice_combo"):
            self.premium_voice_combo.setEnabled(False)
        if hasattr(self, "bg_music_edit"):
            self.bg_music_edit.setEnabled(generated_mode and mode in ("voice", "both"))
        if hasattr(self, "mixed_audio_edit"):
            self.mixed_audio_edit.setEnabled(mode in ("voice", "both") and bool(hasattr(self, "use_existing_audio_radio") and self.use_existing_audio_radio.isChecked()))
        if hasattr(self, "preview_voice_btn"):
            self.preview_voice_btn.setVisible(True)
            self.preview_voice_btn.setEnabled(bool(self.voice_catalog_entries_all))
        has_timeline_segments = bool(self.get_active_segments())
        selected_overlay_is_splittable = False
        selected_layer_locked = False
        has_selected_timeline_layer = False
        selected_layer_id = str(getattr(getattr(self, "timeline", None), "_selected_layer_id", "") or "")
        if selected_layer_id and getattr(getattr(self, "timeline", None), "_timeline", None):
            for track in self.timeline._timeline.tracks:
                for layer in track.layers:
                    if layer.id != selected_layer_id:
                        continue
                    has_selected_timeline_layer = True
                    selected_layer_locked = bool(getattr(track, "locked", False)) or bool(getattr(layer, "locked", False))
                    layer_type = str(getattr(getattr(layer, "type", ""), "value", getattr(layer, "type", ""))).lower()
                    selected_overlay_is_splittable = layer_type in {"blur", "mask", "text"} or (
                        layer_type == "image" and str(getattr(track, "name", "")) == "L1 Logo"
                    )
                    break
                if selected_overlay_is_splittable:
                    break
        if hasattr(self, "timeline_split_btn"):
            self.timeline_split_btn.setEnabled(
                (has_timeline_segments or selected_overlay_is_splittable)
                and (not has_selected_timeline_layer or not selected_layer_locked)
                and not review_mode
            )
        if hasattr(self, "timeline_split_sentences_btn"):
            self.timeline_split_sentences_btn.setEnabled(
                has_timeline_segments
                and (not has_selected_timeline_layer or not selected_layer_locked)
                and not review_mode
            )
        if hasattr(self, "timeline_delete_btn"):
            self.timeline_delete_btn.setEnabled(
                has_timeline_segments and (not has_selected_timeline_layer or not selected_layer_locked)
                and not review_mode
            )

        # Keep the timeline readable and fully seekable during playback, but
        # make every state-changing control unavailable in Review Mode.
        if review_mode:
            for button_name in (
                "timeline_undo_btn", "timeline_redo_btn", "timeline_selection_mode_btn",
                "timeline_clear_selection_btn", "timeline_alt_transcribe_btn",
                "timeline_split_sentences_btn",
            ):
                button = getattr(self, button_name, None)
                if button is not None:
                    button.setEnabled(False)
        else:
            self._refresh_timeline_history_buttons()
            selection_exists = bool(getattr(self.timeline, "selection_range", lambda: None)()) if hasattr(self, "timeline") else False
            if hasattr(self, "timeline_selection_mode_btn"):
                self.timeline_selection_mode_btn.setEnabled(bool(v_ok))
            if hasattr(self, "timeline_clear_selection_btn"):
                self.timeline_clear_selection_btn.setEnabled(selection_exists)
            if hasattr(self, "timeline_alt_transcribe_btn"):
                self.timeline_alt_transcribe_btn.setVisible(selection_exists)
                self.timeline_alt_transcribe_btn.setEnabled(selection_exists and not bool(getattr(self, "_alternate_range_transcription_worker", None)))
        if hasattr(self, "inspector_stack"):
            self.inspector_stack.setEnabled(not review_mode)
        # Lock only the layout handle while playing.  The splitter's child
        # widgets remain enabled so playback/seek controls still work.
        splitter = getattr(self, "preview_timeline_splitter", None)
        if splitter is not None:
            try:
                splitter.handle(1).setEnabled(not review_mode)
            except Exception:
                pass

        self._update_generate_button_menu(has_data=has_translated_text or has_timeline_segments)
        self.update_workflow_stage_badges()

        if hasattr(self, "clean_project_action"):
            self.clean_project_action.setEnabled(self._has_cleanable_project_data())
        self.run_all_btn.setEnabled(v_ok and not self._pipeline_active)
        self.preview_frame_btn.setEnabled(v_ok and bool(self.get_active_segments()))
        self.preview_5s_btn.setEnabled(v_ok)
        if hasattr(self, "preview_5s_action"):
            self.preview_5s_action.setEnabled(v_ok)
        self.export_btn.setEnabled(can_export)
        if hasattr(self, "download_subtitle_action"):
            self.download_subtitle_action.setEnabled(bool(self.translated_text.toPlainText().strip()))
        if hasattr(self, "download_original_action"):
            self.download_original_action.setEnabled(bool(self.transcript_text.toPlainText().strip()))
        if hasattr(self, "tabs"):
            self.tabs.setTabEnabled(1, v_ok)
            self.tabs.setTabEnabled(2, v_ok and mode in ("voice", "both"))
        # Audio Source and related controls are needed before Transcript, so
        # the workflow Audio tab must be available as soon as a video is
        # selected—not only after the optional TTS stage completes.
        if hasattr(self, "audio_tab_btn"):
            self.audio_tab_btn.setEnabled(v_ok)
        self.update_workflow_availability()
        self.update_guidance_panel()
        self._update_ocr_overlay()

    def _update_generate_button_menu(self, has_data: bool):
        if not hasattr(self, "run_all_btn"):
            return
        btn = self.run_all_btn
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        if btn.menu() is None:
            menu = QMenu(btn)
            menu.setObjectName("generateMenu")
            # The parent menu renders the Step-by-Step / Full Pipeline
            # submenu titles, so it needs its own width—not just the child
            # popup menus.
            menu.setMinimumWidth(220)
            step_menu = menu.addMenu("Từng bước")
            step_menu.setObjectName("generateStepMenu")
            step_menu.setMinimumWidth(220)
            transcript_action = QAction("Chạy đến Chép lời", step_menu)
            transcript_action.triggered.connect(lambda: self.run_pipeline_to_stage("transcript"))
            translate_menu = step_menu.addMenu("Chạy đến Dịch thuật")
            translate_menu.setObjectName("generateStepMenu")
            translate_menu.setMinimumWidth(220)
            translate_action = QAction("Tự động dịch", translate_menu)
            translate_action.triggered.connect(lambda: self.run_pipeline_to_stage("translate"))
            import_translation_action = QAction("Nhập file dịch phụ đề…", translate_menu)
            import_translation_action.triggered.connect(self.import_translated_srt)
            align_translation_action = QAction("Đối chiếu phụ đề Song ngữ…", translate_menu)
            align_translation_action.triggered.connect(self.open_subtitle_alignment_dialog)
            translate_menu.addActions([translate_action, import_translation_action, align_translation_action])
            tts_menu = step_menu.addMenu("Tạo giọng đọc / TTS")
            tts_menu.setObjectName("generateStepMenu")
            tts_menu.setMinimumWidth(220)
            tts_action = QAction("Tạo TTS", tts_menu)
            tts_action.triggered.connect(lambda: self.run_pipeline_to_stage("tts"))
            tts_capcut_action = QAction("Đồng bộ từ CapCut PC…", tts_menu)
            tts_capcut_action.triggered.connect(self.open_capcut_sync_dialog)
            tts_skip_action = QAction("Bỏ qua", tts_menu)
            tts_skip_action.triggered.connect(self.skip_tts_stage)
            tts_menu.addActions([tts_action, tts_capcut_action, tts_skip_action])
            step_menu.insertAction(translate_menu.menuAction(), transcript_action)
            step_menu.addAction(tts_menu.menuAction())
            full_menu = menu.addMenu("Toàn bộ quy trình")
            full_menu.setObjectName("generateStepMenu")
            full_menu.setMinimumWidth(220)
            full_action = QAction("Chạy toàn bộ quy trình (1 giọng)", full_menu)
            full_action.triggered.connect(self.run_all_pipeline)
            fresh_action = QAction("Làm mới & Tạo lại từ đầu", full_menu)
            fresh_action.triggered.connect(self.run_fresh_pipeline)
            full_menu.addAction(full_action)
            full_menu.addAction(fresh_action)
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.MenuButtonPopup)
            btn.clicked.connect(self.run_all_pipeline)
            btn.setText("▶ Tạo video (1 giọng)")

            self._generate_transcript_action = transcript_action
            self._generate_translate_action = translate_action
            self._generate_import_translated_srt_action = import_translation_action
            self._generate_tts_action = tts_action
            self._generate_tts_skip_action = tts_skip_action
        self.update_workflow_stage_badges()

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if mime_data.hasUrls():
            for url in mime_data.urls():
                local_path = url.toLocalFile()
                if local_path and os.path.splitext(local_path)[1].lower() in {".mp4", ".mkv", ".avi", ".mov"}:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            event.ignore()
            return
        for url in mime_data.urls():
            local_path = url.toLocalFile()
            if local_path and os.path.splitext(local_path)[1].lower() in {".mp4", ".mkv", ".avi", ".mov"}:
                self.ensure_media_backend_ready()
                self.video_path_edit.setText(local_path)
                self.media_player.setSource(QUrl.fromLocalFile(local_path))
                self.refresh_video_dimensions(local_path)
                self.play_btn.setText("Play")
                self.timeline.set_segments([])
                self.timeline.set_playing(False)
                self.current_segments = []
                self.current_translated_segments = []
                self.current_segment_models = []
                self.current_translated_segment_models = []
                self.current_project_state = self.ensure_current_project()
                self._allow_post_pipeline_preview_assets = False
                self.load_project_context(self.current_project_state)
                self.media_player.pause()
                self.media_player.setPosition(0)
                self.refresh_ui_state()
                self.sync_live_subtitle_preview()
                event.acceptProposedAction()
                return
        event.ignore()

    def run_extraction(self):
        v_path = self.video_path_edit.text()
        if not v_path: return
        
        target_dir = self.audio_folder_edit.text()
        file_basename = os.path.splitext(os.path.basename(v_path))[0]
        a_path = os.path.join(target_dir, file_basename + ".wav")
        
        print(f"[Extraction] start: video={v_path} audio={a_path}")
        self.progress_bar.setValue(10)
        self.update_project_step("extract_audio", "running")
        self.extraction_thread = ExtractionWorker(v_path, a_path)
        self.extraction_thread.finished.connect(self.on_extraction_finished)
        self.extraction_thread.start()

    def on_extraction_finished(self, success, path):
        print(f"[Extraction] finished: success={success} path={path}")
        self.progress_bar.setValue(30)
        self.extract_btn.setEnabled(True)
        if success:
            self.last_extracted_audio = path
            self.audio_source_edit.setText(path)
            self.processed_artifacts["audio_extracted"] = path
            self.update_project_artifact("extracted_audio", path)
            self.update_project_step("extract_audio", "done")
            self.log(f"[Audio] Original audio extracted: {path}")
            self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
        else:
            self.update_project_step("extract_audio", "failed")
            self.show_error("Error", "Extraction failed.", str(path))
            self._pipeline_fail("Extraction failed.")
            return

        self.refresh_ui_state()
        self._pipeline_advance("extraction")



    def run_transcription(self):
        is_ocr = self.get_transcription_engine() == "ocr"
        if not self.ensure_required_resources(
            "Transcription",
            include_whisper=not is_ocr,
            include_ocr=is_ocr,
            validate_pipeline_runtime=True,
        ):
            return
        self.subtitle_controller.run_transcription()

    def on_transcription_finished(self, segments, error=""):
        self.subtitle_controller.on_transcription_finished(segments, error)

    def run_translation(self):
        self.subtitle_controller.run_translation()

    def on_translation_finished(self, translated_srt, error, fallback_notice=""):
        self.subtitle_controller.on_translation_finished(translated_srt, error, fallback_notice)

    def run_rewrite_translation(self):
        self.subtitle_controller.run_rewrite_translation()

    def run_rewrite_selected_segment(self):
        self.subtitle_controller.run_rewrite_selected_segment()

    def on_rewrite_translation_finished(self, translated_srt, error):
        self.subtitle_controller.on_rewrite_translation_finished(translated_srt, error)

    def on_rewrite_selected_segment_finished(self, translated_srt, error):
        self.subtitle_controller.on_rewrite_selected_segment_finished(translated_srt, error)




    def get_whisper_model_name(self) -> str:
        selected = str(getattr(self, "selected_whisper_model_name", "auto") or "auto").strip().lower()
        is_gpu_mode = os.environ.get("CAPCAP_DEVICE", "cuda").strip().lower() == "cuda"
        if not is_gpu_mode and selected == "medium":
            selected = "auto"
        if selected and selected != "auto":
            return selected
        model_root = os.path.join(self.workspace_root, "models", "faster_whisper")
        preferred_models = ("medium", "small", "base", "tiny") if is_gpu_mode else ("small", "base", "tiny")
        for candidate in preferred_models:
            model_dir = os.path.join(model_root, candidate)
            if os.path.isdir(model_dir) and any(
                name.endswith(".bin") for name in os.listdir(model_dir)
            ):
                return candidate
            snapshots_dir = os.path.join(
                model_root,
                f"models--Systran--faster-whisper-{candidate}",
                "snapshots",
            )
            if os.path.isdir(snapshots_dir):
                for snapshot_name in os.listdir(snapshots_dir):
                    if os.path.isfile(os.path.join(snapshots_dir, snapshot_name, "model.bin")):
                        return candidate
        return "medium"

    def get_whisper_model_path(self) -> str:
        return os.path.join(self.workspace_root, "models", "ggml-medium.bin")


    def apply_edited_translation(self, show_message=True, force_apply=True):
        result = self.subtitle_controller.apply_edited_translation(show_message=show_message, force_apply=force_apply)
        if result:
            self.refresh_auto_keyword_highlights()
            self.sync_segment_editor_rows()
            return result




















    def open_capcut_sync_dialog(self):
        from widgets.capcut_sync_dialog import CapCutSyncDialog
        dialog = CapCutSyncDialog(
            parent=self,
            project_state=self.current_project_state,
            project_service=self.project_service,
        )
        dialog.sync_completed.connect(self.on_capcut_sync_completed)
        dialog.exec()


    def on_capcut_sync_completed(self, result: dict):
        voice_track = result.get("voice_track", "")
        mixed_track = result.get("mixed_track", "")
        if voice_track and os.path.isfile(voice_track):
            self.last_voice_vi_path = voice_track
            self.processed_artifacts["voice_vi"] = voice_track
            self.update_project_artifact("voice_vi", voice_track)
            self.update_project_step("generate_tts", "done")
            if hasattr(self, "audio_tab_btn"):
                self.audio_tab_btn.setEnabled(True)
            if hasattr(self, "timeline"):
                self.timeline.sync_tts_track(
                    voice_track,
                    segments=self.current_translated_segments or self.current_segments,
                )
        if mixed_track and os.path.isfile(mixed_track):
            self.last_mixed_vi_path = mixed_track
            self.processed_artifacts["mixed_vi"] = mixed_track
            self.update_project_artifact("mixed_vi", mixed_track)
            self.update_project_step("mix_audio", "done")

        self.schedule_timeline_visual_refresh(waveform=True, thumbnails=False)
        self.refresh_ui_state()
        self.sync_preview_audio_track_to_output()
        self.log(f"[CapCut Sync] Đã nạp thành công giọng đọc từ CapCut: {voice_track}")

    def preview_video(self):
        self.preview_controller.preview_video()

    def on_preview_ready(self, preview_path, error, styled_signature=""):
        self.preview_controller.on_preview_ready(preview_path, error, styled_signature)

    def smart_generate(self):
        if getattr(self, "_pipeline_active", False):
            return
        has_subtitles = bool(self.current_segments)
        has_translated = bool(self.current_translated_segments and self.translated_text.toPlainText().strip())
        mode = self.get_output_mode_key()
        need_voice = mode in ("voice", "both")

        if not has_subtitles or (not has_translated and mode != "voice"):
            self.run_all_pipeline()
        elif need_voice:
            self.run_voiceover_with_progress()
        else:
            self.preview_video()


    def run_pipeline_to_stage(self, target_stage: str):
        target_stage = str(target_stage or "full").strip().lower()
        if target_stage not in {"transcript", "translate", "tts"}:
            self.run_all_pipeline()
            return
        has_transcript = bool(self.current_segments or self.transcript_text.toPlainText().strip())
        has_translation = bool(self.current_translated_segments or self.translated_text.toPlainText().strip())
        if target_stage == "translate" and not has_transcript:
            QMessageBox.information(self, "Step-by-Step", "Complete Transcript before running Translate.")
            return
        if target_stage == "translate" and has_translation:
            # A deliberate re-translate must bypass the finished-translation
            # cache.  Keep the transcript cache intact, so this does not
            # repeat audio extraction or transcription.
            state = self.ensure_current_project()
            if state is not None:
                state.set_setting("translation_signature", "")
                state.set_step_status("translate_raw", "pending")
                state.set_step_status("refine_translation", "pending")
                self.project_service.save_project(state)
            self.log("[Translation] Re-translate requested; reusing the existing transcript.")
        if target_stage == "translate":
            # Translate is independent once TS1 exists.  Do not send this
            # request through PrepareWorkflow: that workflow begins at audio
            # extraction/transcription and can rerun OCR/ASR when a cache
            # signature changes.
            if not self.transcript_text.toPlainText().strip() and self.current_segments:
                self.transcript_text.setText(self.format_to_srt(self.current_segments))
            self.log("[Pipeline] Translate requested; using the completed transcript only.")
            self.run_translation()
            return
        if target_stage == "tts" and not has_translation:
            QMessageBox.information(self, "Step-by-Step", "Complete Translate before running Generate Voice / TTS.")
            return
        if target_stage == "tts" and has_translation:
            self.run_voiceover_with_progress(target_stage="tts")
            return
        mode = self.get_output_mode_key()
        include_voice = target_stage == "tts" and mode in ("voice", "both")
        is_ocr = self.get_transcription_engine() == "ocr"
        if not self.ensure_required_resources(
            "Generate",
            include_whisper=not is_ocr,
            include_voice=include_voice,
            include_ocr=is_ocr,
            validate_pipeline_runtime=True,
        ):
            return
        self.pipeline_controller.run_all_pipeline(target_stage=target_stage)


    def run_all_pipeline(self):
        """Kích hoạt quy trình 1 giọng tự động: Setup âm thanh ➔ Quét OCR ➔ DeepSeek AI ➔ Che chữ Trung + Đè phụ đề ➔ Ra video."""
        video_path = self._normalize_local_file_path(
            self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        )
        if not video_path or not os.path.isfile(video_path):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Chạy toàn bộ quy trình", "Vui lòng chọn hoặc kéo thả một tệp video trước.")
            return

        # 1. Tự động lấy khung che chữ Trung từ vùng OCR / Blur Region người dùng đã vẽ
        blur_rect = None
        if hasattr(self, "video_view") and hasattr(self.video_view, "get_blur_region_normalized"):
            try:
                norm_blur = self.video_view.get_blur_region_normalized()
                if isinstance(norm_blur, dict):
                    blur_rect = (
                        float(norm_blur.get("x", 0.0)),
                        float(norm_blur.get("y", 0.0)),
                        float(norm_blur.get("width", 0.0)),
                        float(norm_blur.get("height", 0.0)),
                    )
                elif isinstance(norm_blur, list) and norm_blur and isinstance(norm_blur[0], dict):
                    first = norm_blur[0]
                    blur_rect = (
                        float(first.get("x", 0.0)),
                        float(first.get("y", 0.0)),
                        float(first.get("width", 0.0)),
                        float(first.get("height", 0.0)),
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

        # 2. Mở bảng Setup âm thanh & chọn 1 giọng lồng tiếng
        from ui.dialogs.single_voice_setup_dialog import SingleVoiceSetupDialog
        init_orig = int(self.audio_a1_volume_slider.value()) if hasattr(self, "audio_a1_volume_slider") else 50
        init_tts = int(self.audio_a2_volume_slider.value()) if hasattr(self, "audio_a2_volume_slider") else 100
        dialog = SingleVoiceSetupDialog(
            self,
            video_path=video_path,
            initial_orig_volume=init_orig,
            initial_tts_volume=init_tts,
            blur_rect=blur_rect,
            workspace_root=str(getattr(self, "workspace_root", os.getcwd())),
        )
        if dialog.exec() != QDialog.Accepted:
            return

        selected_voice = dialog.get_selected_voice()
        audio_mix = dialog.get_audio_mix_settings()
        enable_blur = dialog.is_blur_mask_enabled()
        burn_subs = dialog.is_burn_subtitles_enabled()
        sub_cfg = dialog.get_subtitle_config()
        brand_logo_settings = dialog.get_brand_logo_settings()
        watermark_settings = dialog.get_watermark_settings()

        # 3. Kiểm tra bản quyền VIP nếu chọn giọng VieNeu
        v_id = selected_voice.get("id", "")
        if "vieneu" in selected_voice.get("provider", "") or "vieneu" in v_id:
            from app.services.license_service import LicenseService
            lic = LicenseService(str(getattr(self, "workspace_root", os.getcwd())))
            is_valid, msg = lic.is_license_valid()
            if not is_valid:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Yêu cầu kích hoạt bản quyền VIP",
                    f"Giọng {selected_voice.get('name')} yêu cầu kích hoạt bản quyền VIP TankVideo!\n\n"
                    f"Trạng thái: {msg}\n\n"
                    "Vui lòng nhấn vào nút 'Bản quyền' trên thanh tiêu đề để đăng nhập và kích hoạt.",
                )
                getattr(self, "open_license_dialog", lambda: None)()
                return

        # 4. Đồng bộ lại thanh trượt âm lượng trên thanh công cụ
        orig_vol = audio_mix.get("original_volume", 0.50)
        tts_vol = audio_mix.get("tts_volume", 1.00)
        if hasattr(self, "audio_a1_volume_slider"):
            self.audio_a1_volume_slider.blockSignals(True)
            self.audio_a1_volume_slider.setValue(int(round(orig_vol * 100)))
            self.audio_a1_volume_slider.blockSignals(False)
            if hasattr(self, "audio_a1_volume_label"):
                self.audio_a1_volume_label.setText(f"{int(round(orig_vol * 100))}%")
        if hasattr(self, "audio_a2_volume_slider"):
            self.audio_a2_volume_slider.blockSignals(True)
            self.audio_a2_volume_slider.setValue(int(round(tts_vol * 100)))
            self.audio_a2_volume_slider.blockSignals(False)
            if hasattr(self, "audio_a2_volume_label"):
                self.audio_a2_volume_label.setText(f"{int(round(tts_vol * 100))}%")

        # 5. Đường dẫn file video xuất ra
        output_folder = (
            self.final_output_folder_edit.text().strip()
            if hasattr(self, "final_output_folder_edit") and self.final_output_folder_edit.text().strip()
            else os.path.join(str(self.workspace_root), "output")
        )
        os.makedirs(output_folder, exist_ok=True)
        video_name = os.path.splitext(os.path.basename(video_path))[0] if video_path else "video"
        output_video_path = os.path.join(output_folder, f"{video_name}_final_vi.mp4")

        # 6. Kiểm tra các câu đã quét trước đó nếu có
        existing_cues = []
        raw_segs = getattr(self, "current_segments", None) or getattr(self, "current_translated_segments", None)
        if raw_segs and isinstance(raw_segs, list):
            for s in raw_segs:
                if isinstance(s, dict) and s.get("text"):
                    existing_cues.append(dict(s))
                elif hasattr(s, "to_dict"):
                    d = s.to_dict()
                    if d.get("text"):
                        existing_cues.append(d)

        # 7. Mở dialog tiến trình trực quan thực hiện toàn bộ quy trình
        from ui.dialogs.single_voice_progress_dialog import SingleVoiceProgressDialog
        progress_dlg = SingleVoiceProgressDialog(
            self,
            workspace_root=str(self.workspace_root),
            video_path=video_path,
            selected_voice=selected_voice,
            audio_mix_settings=audio_mix,
            enable_blur_mask=enable_blur,
            blur_rect=blur_rect,
            burn_subtitles=burn_subs,
            existing_cues=existing_cues if existing_cues else None,
            output_video_path=output_video_path,
            subtitle_config=sub_cfg,
            brand_logo_settings=brand_logo_settings,
            watermark_settings=watermark_settings,
        )
        progress_dlg.exec()

        # 8. Cập nhật kết quả sau khi hoàn thành
        res = getattr(progress_dlg, "_last_result", None)
        if res and getattr(res, "output_video_path", "") and os.path.isfile(res.output_video_path):
            final_mp4 = os.path.abspath(res.output_video_path)
            self.log(f"[Pipeline 1 Giọng] Đã xuất video hoàn chỉnh thành công: {final_mp4}")
            try:
                from PySide6.QtCore import QUrl
                self.media_player.setSource(QUrl.fromLocalFile(final_mp4))
                self.video_path_edit.setText(final_mp4)
                self.play_btn.setText("Play")
            except Exception:
                pass

            trans_cues = getattr(progress_dlg, "_translated_cues", [])
            if trans_cues:
                try:
                    self.current_translated_segments = trans_cues
                    self.timeline.set_segments(trans_cues)
                except Exception:
                    pass


    def run_fresh_pipeline(self):
        """Force a fresh pipeline run by clearing cached transcription and subtitle artifacts."""
        if getattr(self, "_pipeline_active", False):
            return
        state = getattr(self, "current_project_state", None)
        if state is not None:
            state.settings["transcription_signature"] = ""
            state.settings["ocr_transcription_signature"] = ""
            state.settings["speaker_diarization_signature"] = ""
            state.settings["openai_speaker_analysis_signature"] = ""
            state.settings["translation_signature"] = ""
            state.settings["voice_signature"] = ""
            state.settings.pop("speaker_analysis_summary", None)
            state.settings.pop("character_analysis_summary", None)
            state.artifacts["transcript_segments"] = ""
            state.artifacts["transcript_raw"] = ""
            state.artifacts["openai_speaker_analysis"] = ""
            state.artifacts["speaker_diarization"] = ""
            state.artifacts["character_registry"] = ""
            state.artifacts["character_review_queue"] = ""
            state.artifacts["character_voice_prototypes"] = ""
            state.artifacts["translated_subtitles"] = ""
            state.artifacts["translation_final"] = ""
            state.artifacts["translation_raw"] = ""
            state.artifacts["voice_vi"] = ""
            state.artifacts["voice_segments"] = ""
            self.project_service.save_project(state)

        # The fresh action promises a real rebuild, including TTS.  Without
        # this flag run_voiceover could still accept voice_vi.wav from the
        # previous run and layer stale voices over the new assignments.
        self._voiceover_force_refresh = True

        self.current_segments = []
        self.current_translated_segments = []
        self.current_segment_models = []
        self.current_translated_segment_models = []
        if hasattr(self, "transcript_text"):
            self.transcript_text.clear()
        if hasattr(self, "translated_text"):
            self.translated_text.clear()
        self.apply_segments_to_timeline()
        self.persist_current_timeline_project_data()
        self.refresh_ui_state()
        self.run_all_pipeline()

    def on_prepare_workflow_finished(self, project_state_path, error):
        self.pipeline_controller.on_prepare_workflow_finished(project_state_path, error)

    def _pipeline_advance(self, completed_step: str):
        self.pipeline_controller.pipeline_advance(completed_step)

    def _pipeline_fail(self, reason: str):
        self.pipeline_controller.pipeline_fail(reason)

    def _pipeline_done(self):
        self.pipeline_controller.pipeline_done()

    def open_folder(self, path):
        open_folder_impl(self, path)

    def show_processed_files(self):
        show_processed_files_impl(self)

    def cleanup_temp_preview_files(self):
        cleanup_temp_preview_files_impl(self)

    def _path_within_root(self, path: str, root: str) -> bool:
        try:
            normalized_path = os.path.normcase(os.path.abspath(path))
            normalized_root = os.path.normcase(os.path.abspath(root))
            return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
        except Exception:
            return False

    def _remove_path_if_safe(self, path: str, *, allowed_roots: list[str], removed: list[str]) -> None:
        normalized = self._normalize_local_file_path(path)
        if not normalized or not os.path.exists(normalized):
            return
        if not any(self._path_within_root(normalized, root) for root in allowed_roots if root):
            return

        def _on_remove_error(func, target, exc_info):
            try:
                os.chmod(target, 0o777)
                func(target)
            except OSError:
                return

        try:
            if os.path.isdir(normalized):
                shutil.rmtree(normalized, onerror=_on_remove_error)
            else:
                os.remove(normalized)
        except OSError:
            return
        if not os.path.exists(normalized):
            removed.append(normalized)





    def _return_to_launcher(self, project_removed_from_recent=True, *, persist_project_data=True):
        # Keep the complete saved timeline when returning to the launcher.
        # Optional tracks (Text, Logo, Blur, Mask) are part of the project
        # state and must be available when that project is reopened.
        if persist_project_data:
            try:
                self.persist_current_timeline_project_data()
            except Exception:
                pass
        video_path = getattr(self, "_current_video_path", "")
        if not video_path:
            video_path = os.path.normpath(self.video_path_edit.text().strip())
        self.log(f"[Clean] _return_to_launcher: video_path={video_path}")
        if video_path and project_removed_from_recent:
            try:
                from views.launcher import _load_recent_projects, _save_recent_projects
                projects = _load_recent_projects()
                projects = [p for p in projects if os.path.normpath(p.get("video_path", "")) != os.path.normpath(video_path)]
                _save_recent_projects(None, projects)
                self.log(f"[Clean] Removed from recent: {video_path} -> {len(projects)} remaining")
            except Exception as e:
                self.log(f"[Clean] Failed: {e}")
        self._current_video_path = ""
        self._terminate_workers()
        self.hide()
        QApplication.setQuitOnLastWindowClosed(False)
        QTimer.singleShot(100, _relaunch_launcher)

    def _terminate_workers(self):
        attrs = [
            "extraction_thread",
            "vocal_thread",
            "voice_thread",
            "_voice_sample_preview_thread",
            "transcription_thread",
            "_alternate_range_transcription_worker",
            "translation_thread",
            "rewrite_translation_thread",
            "prepare_workflow_thread",
            "export_thread",
            "quick_preview_thread",
            "frame_preview_thread",
            "preview_thread",
        ]
        for name in attrs:
            worker = getattr(self, name, None)
            if worker is not None and getattr(worker, "isRunning", lambda: False)():
                print(f"[Cleanup] Terminating worker: {name}")
                try:
                    worker.quit()
                    worker.wait(3000)
                    if worker.isRunning():
                        worker.terminate()
                        worker.wait(2000)
                        print(f"[Cleanup] Force-terminated {name}")
                    else:
                        print(f"[Cleanup] Graceful quit {name}")
                except Exception as e:
                    print(f"[Cleanup] Failed to terminate {name}: {e}")
        threads_dict = getattr(self, "_segment_preview_threads", None)
        if threads_dict:
            for idx, worker in list(threads_dict.items()):
                try:
                    if getattr(worker, "isRunning", lambda: False)():
                        print(f"[Cleanup] Terminating segment preview thread idx={idx}")
                        worker.quit()
                        worker.wait(3000)
                        if worker.isRunning():
                            worker.terminate()
                            worker.wait(2000)
                except Exception as e:
                    print(f"[Cleanup] Failed to terminate segment thread {idx}: {e}")
            threads_dict.clear()
        print("[Cleanup] Worker termination complete.")

    def closeEvent(self, event):
        try:
            # 1. Close and hide all floating overlays (OCR, blur, text, mask) immediately
            for attr in ("ocr_region_overlay", "ocr_translator_overlay"):
                overlay = getattr(self, attr, None)
                if overlay is not None:
                    try:
                        overlay.hide()
                        overlay.close()
                    except Exception:
                        pass
            if hasattr(self, "video_view") and self.video_view is not None:
                for sub_attr in ("blur_overlay", "mask_overlay", "logo_overlay", "text_overlay"):
                    sub_overlay = getattr(self.video_view, sub_attr, None)
                    if sub_overlay is not None:
                        try:
                            sub_overlay.hide()
                            sub_overlay.close()
                        except Exception:
                            pass

            # A drag may have ended less than one debounce interval ago.
            # Flush it before teardown so the final overlay position is not
            # lost when the window is closed immediately.
            self._flush_pending_timeline_persist()
            # Persist the current blur state BEFORE clearing the overlay.
            # Block the blurRegionChanged signal during the clear so the
            # signal handler does not overwrite the saved state with an
            # empty regions list.
            if hasattr(self, "video_view"):
                try:
                    self.video_view.blurRegionChanged.disconnect(self.on_preview_blur_region_changed)
                except Exception:
                    pass
            if hasattr(self, "persist_project_blur_state"):
                try:
                    self.persist_project_blur_state()
                except Exception:
                    pass
            if hasattr(self, "persist_project_mask_state"):
                try:
                    self.persist_project_mask_state()
                except Exception:
                    pass
            # Preserve the complete project timeline on a normal application
            # close, including Text and Logo tracks. Optional layers are
            # removed only by the explicit clean/return workflow.
            if hasattr(self, "video_view"):
                self.video_view.clear_blur_region()
            if hasattr(self, "media_player") and hasattr(self.media_player, "clear_mask_region"):
                try:
                    self.media_player.clear_mask_region()
                except Exception:
                    pass
            self.save_user_settings()
            self.cleanup_temp_preview_files()
            self._terminate_workers()

            # Ensure any remaining auxiliary top-level tool/overlay widgets are closed
            from PySide6.QtWidgets import QApplication
            for widget in list(QApplication.topLevelWidgets()):
                if widget is not self:
                    try:
                        widget.hide()
                        widget.close()
                    except Exception:
                        pass
        finally:
            super().closeEvent(event)


    def stop_video(self):
        stop_video_impl(self)


    def duration_changed(self, duration):
        duration_changed_impl(self, duration)
        self.schedule_timeline_visual_refresh(waveform=False, thumbnails=True)


    def update_duration_label(self, current, total):
        update_duration_label_impl(self, current, total)


    def on_preview_speed_changed(self, index: int):
        if not hasattr(self, "preview_speed_combo"):
            return
        rate = self.preview_speed_combo.itemData(index)
        try:
            new_rate = float(rate or 1.0)
        except Exception:
            new_rate = 1.0
        self._preview_speed = new_rate
        if hasattr(self, "media_player"):
            try:
                self.media_player.set_playback_rate(new_rate)
            except Exception:
                pass


def _relaunch_launcher():
    from views.launcher import show_launcher, LauncherWindow
    video_path = show_launcher(None)
    QApplication.setQuitOnLastWindowClosed(True)
    if not video_path:
        QApplication.quit()
        return
    LauncherWindow.add_recent(None, video_path)
    new_window = VideoTranslatorGUI()
    new_window.prepare_initial_editor_layout()
    new_window.show()
    def _init():
        new_window._current_video_path = os.path.abspath(video_path)
        new_window.ensure_media_backend_ready()
        new_window.video_path_edit.setText(video_path)
        new_window.media_player.setSource(QUrl.fromLocalFile(video_path))
        if hasattr(new_window, "refresh_video_dimensions"):
            new_window.refresh_video_dimensions(video_path)
        new_window.current_project_state = new_window.ensure_current_project()
        new_window.load_project_context(new_window.current_project_state)
        if hasattr(new_window, "timeline") and hasattr(new_window.timeline, "set_video_source"):
            try:
                dur = new_window.media_player.duration() / 1000.0
            except Exception:
                dur = 60.0
            new_window.timeline.set_video_source(new_window._current_video_path, dur)
        new_window.schedule_timeline_visual_refresh(waveform=True, thumbnails=True)
    QTimer.singleShot(100, _init)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoTranslatorGUI()
    window.show()
    sys.exit(app.exec())
