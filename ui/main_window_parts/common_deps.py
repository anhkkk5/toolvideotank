"""Common dependencies, imports, and utility functions shared by all MainWindow mixins."""

import sys
import os
import re
import json
import copy
import glob
import hashlib
import shutil
import threading
from typing import Any, Dict, List, Optional, Tuple, Union, Callable
from uuid import uuid4

# PySide6 Widgets
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QToolButton, QLabel, QLineEdit,
    QFileDialog, QTextEdit, QComboBox, QCheckBox, QSpinBox,
    QDoubleSpinBox, QSlider, QProgressBar, QMessageBox,
    QScrollArea, QColorDialog, QTabWidget, QDialog, QSizePolicy,
    QInputDialog, QLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMenu, QGroupBox, QSplitter,
    QFrame, QAbstractSpinBox, QPlainTextEdit
)
from PySide6.QtCore import (
    Qt, QUrl, QTimer, QSettings, QEvent, Signal, QPoint, QRect, QRectF, QSize
)
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontInfo, QIcon, QKeySequence,
    QPixmap, QTextCursor, QAction, QPainter, QPen, QBrush
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

# Backend paths
ROOT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT_PATH not in sys.path:
    sys.path.insert(0, ROOT_PATH)

APP_PATH = os.path.join(ROOT_PATH, 'app')
if APP_PATH not in sys.path:
    sys.path.insert(0, APP_PATH)

UI_PATH = os.path.join(ROOT_PATH, 'ui')
if UI_PATH not in sys.path:
    sys.path.insert(0, UI_PATH)

# Helper functions and services
def _default_asr_engine() -> str:
    return "ocr"

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
from video_processor import srt_to_ass, get_video_dimensions
from audio_mixer import ffprobe_wav_duration, mix_voice_with_background
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
from utils.settings_utils import (
    load_user_settings as load_user_settings_impl,
    save_user_settings as save_user_settings_impl
)

# Custom Widgets
try:
    from widgets.progress_dialog import BackgroundableProgressDialog
except ImportError:
    from ui.widgets.progress_dialog import BackgroundableProgressDialog

try:
    from widgets.spin_boxes import ReliableDoubleSpinBox
except ImportError:
    from ui.widgets.spin_boxes import ReliableDoubleSpinBox

try:
    from widgets.subtitle_editor_dialog import SubtitleEditorDialog
except ImportError:
    from ui.widgets.subtitle_editor_dialog import SubtitleEditorDialog

from runtime_paths import app_path, asset_path, bundle_root, models_path, workspace_root
from runtime_profile import is_remote_profile

# Worker Adapters
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

# Layers
from app.layers.base import BaseLayer, LayerType, BlendMode
from app.layers.video import VideoLayer
from app.layers.audio import AudioLayer
from app.layers.subtitle import SubtitleLayer
from app.layers.dub_subtitle import DubSubtitleLayer
from app.layers.text import TextLayer, TEXT_LAYER_EXPORT_SCALE
from app.layers.image import ImageLayer
from app.layers.sticker import StickerLayer
from app.layers.blur import BlurLayer
from app.layers.mask import MaskLayer, MaskMode
from app.layers.keyframe import Keyframe, KeyframeTrack
from app.layers.transform import Transform
from app.layers.timeline import Timeline, Track, Clip
from app.layers.sync_bridge import (
    find_or_create_track,
    DUB_SUBTITLE_TRACK_NAME,
    sync_segments_to_dub_subtitle_layers,
    sync_blur_regions_to_layers,
    sync_tts_to_dub_subtitle_layers,
    ensure_v1_a1_tracks,
)

__all__ = [k for k in list(globals().keys()) if not (k.startswith("__") and k.endswith("__"))]
