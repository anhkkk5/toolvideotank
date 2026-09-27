from __future__ import annotations

import datetime
import os
from typing import Any

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QFrame,
)

from services.capcut_bridge import (
    find_default_capcut_drafts_dir,
    list_capcut_drafts,
    parse_capcut_draft_audios,
    sync_capcut_voice_to_project,
)


class CapCutSyncWorker(QThread):
    progress = Signal(str)
    finished_success = Signal(dict)
    finished_error = Signal(str)

    def __init__(
        self,
        project_state: Any,
        project_service: Any,
        draft_folder: str,
        original_volume: int = 100,
        dub_volume: int = 100,
    ):
        super().__init__()
        self.project_state = project_state
        self.project_service = project_service
        self.draft_folder = draft_folder
        self.original_volume = original_volume
        self.dub_volume = dub_volume

    def run(self):
        try:
            result = sync_capcut_voice_to_project(
                project_state=self.project_state,
                project_service=self.project_service,
                draft_folder=self.draft_folder,
                original_volume_percent=self.original_volume,
                dub_volume_percent=self.dub_volume,
                on_progress=self.progress.emit,
            )
            self.finished_success.emit(result)
        except Exception as exc:
            self.finished_error.emit(str(exc))


class CapCutSyncDialog(QDialog):
    sync_completed = Signal(dict)

    def __init__(self, parent=None, project_state=None, project_service=None):
        super().__init__(parent)
        self.project_state = project_state
        self.project_service = project_service
        self.settings = QSettings("TankVideo", "Settings")

        self.setWindowTitle("Đồng bộ giọng đọc từ CapCut PC")
        self.setMinimumSize(680, 520)
        self.resize(720, 560)

        self._init_ui()
        self._load_drafts()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        # Header
        header = QLabel("🎙️ Đồng bộ giọng đọc từ CapCut PC sang TankVideo")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #ff7b1a;")
        layout.addWidget(header)

        desc = QLabel(
            "Tự động quét các file âm thanh được tạo từ tính năng 'Chuyển văn bản thành lời nói' (Text Reading) "
            "trong CapCut PC và nạp vào timeline lồng tiếng của TankVideo."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #b0bec5; font-size: 12px;")
        layout.addWidget(desc)

        # Cấu hình thư mục CapCut Drafts
        dir_frame = QFrame()
        dir_frame.setStyleSheet("background-color: #1e222d; border-radius: 6px; padding: 6px;")
        dir_layout = QVBoxLayout(dir_frame)
        dir_layout.setContentsMargins(8, 8, 8, 8)
        dir_layout.setSpacing(6)

        dir_label = QLabel("Thư mục CapCut Drafts:")
        dir_label.setStyleSheet("font-weight: bold; color: #cfd8dc;")
        dir_layout.addWidget(dir_label)

        path_row = QHBoxLayout()
        saved_dir = str(self.settings.value("capcut_drafts_dir", "") or "").strip()
        default_dir = find_default_capcut_drafts_dir(saved_dir)

        self.dir_edit = QLineEdit(default_dir)
        self.dir_edit.setStyleSheet(
            "background-color: #131722; color: #eceff1; border: 1px solid #37474f; border-radius: 4px; padding: 6px;"
        )
        path_row.addWidget(self.dir_edit, 1)

        self.browse_btn = QPushButton("Duyệt...")
        self.browse_btn.setStyleSheet(
            "background-color: #263238; color: #eceff1; padding: 6px 14px; border-radius: 4px;"
        )
        self.browse_btn.clicked.connect(self._on_browse_dir)
        path_row.addWidget(self.browse_btn)

        self.refresh_btn = QPushButton("Làm mới")
        self.refresh_btn.setStyleSheet(
            "background-color: #263238; color: #4ecdc4; padding: 6px 14px; border-radius: 4px;"
        )
        self.refresh_btn.clicked.connect(self._load_drafts)
        path_row.addWidget(self.refresh_btn)

        dir_layout.addLayout(path_row)
        layout.addWidget(dir_frame)

        # Bảng danh sách drafts
        table_label = QLabel("Chọn dự án CapCut cần lấy giọng:")
        table_label.setStyleSheet("font-weight: bold; color: #cfd8dc;")
        layout.addWidget(table_label)

        self.drafts_table = QTableWidget()
        self.drafts_table.setColumnCount(3)
        self.drafts_table.setHorizontalHeaderLabels(["Tên dự án CapCut", "Thời gian cập nhật", "File giọng đọc"])
        self.drafts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.drafts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.drafts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.drafts_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.drafts_table.setSelectionMode(QTableWidget.SingleSelection)
        self.drafts_table.setStyleSheet(
            "QTableWidget { background-color: #131722; color: #eceff1; gridline-color: #263238; border: 1px solid #37474f; border-radius: 4px; }"
            "QTableWidget::item:selected { background-color: #00897b; color: #ffffff; }"
            "QHeaderView::section { background-color: #1e222d; color: #90a4ae; padding: 6px; border: 1px solid #263238; font-weight: bold; }"
        )
        self.drafts_table.itemSelectionChanged.connect(self._on_draft_selected)
        layout.addWidget(self.drafts_table, 1)

        # Chi tiết giọng đọc trong draft được chọn
        self.preview_label = QLabel("Chọn một dự án để xem các giọng đọc có sẵn...")
        self.preview_label.setStyleSheet("color: #80cbc4; font-size: 11px; padding: 2px;")
        layout.addWidget(self.preview_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #1e222d; border-radius: 4px; text-align: center; color: #eceff1; height: 16px; }"
            "QProgressBar::chunk { background-color: #4ecdc4; border-radius: 4px; }"
        )
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #ffb74d; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.cancel_btn = QPushButton("Đóng")
        self.cancel_btn.setStyleSheet(
            "background-color: #263238; color: #eceff1; padding: 8px 18px; border-radius: 4px;"
        )
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.sync_btn = QPushButton("Đồng bộ vào TankVideo")
        self.sync_btn.setStyleSheet(
            "background-color: #ff6a00; color: #ffffff; font-weight: bold; padding: 8px 22px; border-radius: 4px;"
        )
        self.sync_btn.setEnabled(False)
        self.sync_btn.clicked.connect(self._start_sync)
        btn_row.addWidget(self.sync_btn)

        layout.addLayout(btn_row)

    def _on_browse_dir(self):
        current_dir = self.dir_edit.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục CapCut Drafts", current_dir)
        if folder:
            self.dir_edit.setText(folder)
            self.settings.setValue("capcut_drafts_dir", folder)
            self._load_drafts()

    def _load_drafts(self):
        drafts_dir = self.dir_edit.text().strip()
        self.settings.setValue("capcut_drafts_dir", drafts_dir)

        self.drafts = list_capcut_drafts(drafts_dir)
        self.drafts_table.setRowCount(0)

        for row_idx, draft in enumerate(self.drafts):
            self.drafts_table.insertRow(row_idx)

            name_item = QTableWidgetItem(draft["name"])
            name_item.setData(Qt.UserRole, draft["path"])

            time_str = datetime.datetime.fromtimestamp(draft["mtime"]).strftime("%d/%m/%Y %H:%M")
            time_item = QTableWidgetItem(time_str)

            count = draft["audio_count"]
            count_str = f"{count} file âm thanh" if count > 0 else "0 file"
            count_item = QTableWidgetItem(count_str)
            if count > 0:
                count_item.setForeground(Qt.green)
            else:
                count_item.setForeground(Qt.gray)

            self.drafts_table.setItem(row_idx, 0, name_item)
            self.drafts_table.setItem(row_idx, 1, time_item)
            self.drafts_table.setItem(row_idx, 2, count_item)

        if self.drafts:
            self.drafts_table.selectRow(0)
        else:
            self.preview_label.setText("Không tìm thấy dự án CapCut nào trong thư mục này.")
            self.sync_btn.setEnabled(False)

    def _on_draft_selected(self):
        selected_rows = self.drafts_table.selectionModel().selectedRows()
        if not selected_rows:
            self.sync_btn.setEnabled(False)
            return

        row = selected_rows[0].row()
        if 0 <= row < len(self.drafts):
            draft = self.drafts[row]
            audios = parse_capcut_draft_audios(draft["path"])
            if audios:
                speakers = list({a.get("speaker_name", "CapCut Voice") for a in audios})
                speaker_text = ", ".join(speakers)
                self.preview_label.setText(
                    f"✓ Tìm thấy {len(audios)} đoạn giọng đọc ({speaker_text}). Sẵn sàng đồng bộ!"
                )
                self.preview_label.setStyleSheet("color: #4ecdc4; font-weight: bold; font-size: 11px;")
                self.sync_btn.setEnabled(True)
            else:
                self.preview_label.setText(
                    "⚠️ Dự án này chưa có file giọng đọc trong textReading. Hãy bấm 'Tạo lời nói' trong CapCut trước."
                )
                self.preview_label.setStyleSheet("color: #ffa726; font-size: 11px;")
                self.sync_btn.setEnabled(False)

    def _start_sync(self):
        selected_rows = self.drafts_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        draft = self.drafts[row]

        if not self.project_state:
            QMessageBox.warning(self, "Chưa mở dự án", "Vui lòng mở một dự án trong TankVideo trước khi đồng bộ giọng đọc.")
            return

        self.sync_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText("Đang bắt đầu đồng bộ giọng đọc...")

        self.worker = CapCutSyncWorker(
            project_state=self.project_state,
            project_service=self.project_service,
            draft_folder=draft["path"],
        )
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished_success.connect(self._on_worker_success)
        self.worker.finished_error.connect(self._on_worker_error)
        self.worker.start()

    def _on_worker_progress(self, msg: str):
        self.status_label.setText(msg)

    def _on_worker_success(self, result: dict):
        self.progress_bar.hide()
        self.status_label.setText("Đồng bộ hoàn tất!")
        self.sync_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)

        speakers_str = ", ".join(result.get("speakers", [])) or "CapCut Voice"
        QMessageBox.information(
            self,
            "Thành công",
            f"Đã đồng bộ thành công {result.get('count', 0)} đoạn giọng đọc ({speakers_str}) vào TankVideo!\n\n"
            f"Track lồng tiếng đã được tạo tại:\n{result.get('voice_track', '')}",
        )
        self.sync_completed.emit(result)
        self.accept()

    def _on_worker_error(self, err: str):
        self.progress_bar.hide()
        self.status_label.setText("Đồng bộ thất bại.")
        self.sync_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        QMessageBox.critical(self, "Lỗi đồng bộ", f"Không thể đồng bộ giọng đọc từ CapCut:\n{err}")
