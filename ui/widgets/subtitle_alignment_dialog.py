from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Qt, QSettings
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
    QMessageBox,
    QFrame,
)

from services.capcut_bridge import export_subtitles_to_capcut_draft


def _format_time(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds or 0.0) * 1000)))
    minutes, remainder = divmod(total_ms, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


class SubtitleAlignmentDialog(QDialog):
    """Cửa sổ đối chiếu trực quan phụ đề gốc và phụ đề đã dịch song song."""

    def __init__(self, parent=None, project_state=None, project_service=None):
        super().__init__(parent)
        self.project_state = project_state
        self.project_service = project_service
        self.settings = QSettings("TankVideo", "Settings")

        self.setWindowTitle("Đối chiếu Phụ đề Song ngữ (Gốc & Đã Dịch)")
        self.setMinimumSize(960, 620)
        self.resize(1080, 700)

        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel("📋 Bảng đối chiếu Phụ đề Song ngữ (Gốc & Đã Dịch)")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #4ecdc4;")
        layout.addWidget(header)

        # Thống kê nhanh
        self.summary_box = QFrame()
        self.summary_box.setStyleSheet(
            "background-color: #1e222d; border-radius: 6px; padding: 10px; border: 1px solid #263238;"
        )
        summary_layout = QHBoxLayout(self.summary_box)
        summary_layout.setContentsMargins(10, 8, 10, 8)

        self.orig_count_lbl = QLabel("Phụ đề Gốc: -- câu")
        self.orig_count_lbl.setStyleSheet("font-weight: bold; color: #90a4ae;")
        summary_layout.addWidget(self.orig_count_lbl)

        summary_layout.addWidget(QLabel("|"))

        self.trans_count_lbl = QLabel("Phụ đề Dịch: -- câu")
        self.trans_count_lbl.setStyleSheet("font-weight: bold; color: #4ecdc4;")
        summary_layout.addWidget(self.trans_count_lbl)

        summary_layout.addWidget(QLabel("|"))

        self.sync_status_lbl = QLabel("Tình trạng: Đang kiểm tra...")
        self.sync_status_lbl.setStyleSheet("font-weight: bold; color: #81c784;")
        summary_layout.addWidget(self.sync_status_lbl)

        summary_layout.addStretch(1)
        layout.addWidget(self.summary_box)

        # Ô tìm kiếm
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Tìm kiếm từ khóa:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Gõ để lọc câu thoại tiếng gốc hoặc tiếng Việt...")
        self.search_edit.setStyleSheet(
            "background-color: #131722; color: #eceff1; border: 1px solid #37474f; border-radius: 4px; padding: 6px;"
        )
        self.search_edit.textChanged.connect(self._filter_table)
        filter_row.addWidget(self.search_edit, 1)
        layout.addLayout(filter_row)

        # Bảng hiển thị song song
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "STT",
            "Thời gian (Start → End)",
            "Phụ đề Gốc (ASR)",
            "Phụ đề Đã dịch (Tiếng Việt)",
            "Độ lệch thời gian",
        ])
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.Stretch)
        header_view.setSectionResizeMode(3, QHeaderView.Stretch)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setStyleSheet(
            "QTableWidget { background-color: #131722; color: #eceff1; gridline-color: #263238; border: 1px solid #37474f; border-radius: 4px; font-size: 12px; }"
            "QTableWidget::item:selected { background-color: #00897b; color: #ffffff; }"
            "QHeaderView::section { background-color: #1e222d; color: #cfd8dc; padding: 8px; border: 1px solid #263238; font-weight: bold; }"
        )
        layout.addWidget(self.table, 1)

        # Thanh thao tác cuối bảng
        btn_row = QHBoxLayout()

        self.export_capcut_btn = QPushButton("📤 Xuất toàn bộ phụ đề sang CapCut Draft")
        self.export_capcut_btn.setStyleSheet(
            "background-color: #00897b; color: #ffffff; font-weight: bold; padding: 8px 18px; border-radius: 4px;"
        )
        self.export_capcut_btn.setToolTip("Tạo sẵn dự án CapCut chứa video và đầy đủ các câu phụ đề đã căn đúng mốc thời gian.")
        self.export_capcut_btn.clicked.connect(self._on_export_capcut)
        btn_row.addWidget(self.export_capcut_btn)

        btn_row.addStretch(1)

        self.close_btn = QPushButton("Đóng")
        self.close_btn.setStyleSheet(
            "background-color: #263238; color: #eceff1; padding: 8px 18px; border-radius: 4px;"
        )
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

    def _load_data(self):
        if not self.project_state or not self.project_service:
            return

        orig_segments = []
        if self.project_state.artifacts.get("transcript_segments"):
            orig_models = self.project_service.load_segment_artifact(self.project_state, "transcript_segments")
            orig_segments = [m.to_dict() if hasattr(m, "to_dict") else dict(m) for m in orig_models]

        trans_segments = []
        if self.project_state.artifacts.get("translation_final"):
            trans_models = self.project_service.load_segment_artifact(self.project_state, "translation_final")
            trans_segments = [
                m.to_subtitle_dict() if hasattr(m, "to_subtitle_dict") else dict(m) for m in trans_models
            ]
        elif self.project_state.artifacts.get("translation_raw"):
            trans_models = self.project_service.load_segment_artifact(self.project_state, "translation_raw")
            trans_segments = [
                m.to_subtitle_dict() if hasattr(m, "to_subtitle_dict") else dict(m) for m in trans_models
            ]

        self.orig_segments = orig_segments
        self.trans_segments = trans_segments

        count_orig = len(orig_segments)
        count_trans = len(trans_segments)

        self.orig_count_lbl.setText(f"Phụ đề Gốc: {count_orig} câu")
        self.trans_count_lbl.setText(f"Phụ đề Dịch: {count_trans} câu")

        max_count = max(count_orig, count_trans)
        self.table.setRowCount(max_count)

        perfect_matches = 0
        for i in range(max_count):
            orig_seg = orig_segments[i] if i < count_orig else {}
            trans_seg = trans_segments[i] if i < count_trans else {}

            orig_start = float(orig_seg.get("start", 0.0) or 0.0)
            orig_end = float(orig_seg.get("end", 0.0) or 0.0)
            trans_start = float(trans_seg.get("start", 0.0) or 0.0)
            trans_end = float(trans_seg.get("end", 0.0) or 0.0)

            orig_text = str(orig_seg.get("original_text") or orig_seg.get("text") or "")
            trans_text = str(trans_seg.get("text") or trans_seg.get("final_text") or "")

            stt_item = QTableWidgetItem(f"{i + 1:02d}")
            stt_item.setTextAlignment(Qt.AlignCenter)

            if orig_seg and trans_seg:
                time_str = f"{_format_time(orig_start)} → {_format_time(orig_end)}"
            elif orig_seg:
                time_str = f"{_format_time(orig_start)} → {_format_time(orig_end)}"
            else:
                time_str = f"{_format_time(trans_start)} → {_format_time(trans_end)}"
            time_item = QTableWidgetItem(time_str)
            time_item.setTextAlignment(Qt.AlignCenter)

            orig_item = QTableWidgetItem(orig_text)
            trans_item = QTableWidgetItem(trans_text)

            diff = abs(orig_start - trans_start) if (orig_seg and trans_seg) else 999.0
            if diff < 0.05:
                perfect_matches += 1
                diff_str = "✓ Khớp 0.000s"
                diff_item = QTableWidgetItem(diff_str)
                diff_item.setForeground(Qt.green)
            else:
                diff_str = f"⚠ Lệch {diff:.3f}s"
                diff_item = QTableWidgetItem(diff_str)
                diff_item.setForeground(Qt.yellow)
            diff_item.setTextAlignment(Qt.AlignCenter)

            self.table.setItem(i, 0, stt_item)
            self.table.setItem(i, 1, time_item)
            self.table.setItem(i, 2, orig_item)
            self.table.setItem(i, 3, trans_item)
            self.table.setItem(i, 4, diff_item)

        if max_count > 0 and perfect_matches == max_count:
            self.sync_status_lbl.setText("✓ Khớp số lượng và mốc thời gian (chưa kiểm chứng nội dung)")
            self.sync_status_lbl.setStyleSheet("font-weight: bold; color: #81c784;")
        elif max_count > 0:
            self.sync_status_lbl.setText(f"⚠ Khớp {perfect_matches}/{max_count} câu")
            self.sync_status_lbl.setStyleSheet("font-weight: bold; color: #ffa726;")
        else:
            self.sync_status_lbl.setText("Chưa có dữ liệu phụ đề")
            self.sync_status_lbl.setStyleSheet("color: #90a4ae;")

    def _filter_table(self, query: str):
        query = query.strip().lower()
        for row in range(self.table.rowCount()):
            orig = self.table.item(row, 2).text().lower() if self.table.item(row, 2) else ""
            trans = self.table.item(row, 3).text().lower() if self.table.item(row, 3) else ""
            match = (not query) or (query in orig) or (query in trans)
            self.table.setRowHidden(row, not match)

    def _on_export_capcut(self):
        if not self.project_state or not self.trans_segments:
            QMessageBox.warning(self, "Chưa có phụ đề", "Dự án hiện tại chưa có phụ đề dịch để xuất sang CapCut.")
            return

        try:
            draft_folder = export_subtitles_to_capcut_draft(
                project_state=self.project_state,
                project_service=self.project_service,
                segments=self.trans_segments,
            )
            draft_name = os.path.basename(draft_folder)
            QMessageBox.information(
                self,
                "Xuất thành công & Đã mở CapCut",
                f"Đã tạo dự án CapCut mới:\n📂 {draft_name}\n\n"
                f"CapCut PC đã được tự động mở lên!\nDự án nằm ngay ở vị trí ĐẦU TIÊN trên CapCut.\n\n"
                f"Phụ đề đã được tự động phân tách theo giới tính nhân vật:\n"
                f"• Track 1: Phụ đề Nữ -> Chọn giọng 'Cô Gái Hoạt Ngôn'\n"
                f"• Track 2: Phụ đề Nam -> Chọn giọng 'Anh Dũng'\n\n"
                f"Các bước thực hiện trên CapCut:\n"
                f"1. Mở dự án '{draft_name}' ở đầu danh sách.\n"
                f"2. Bấm chọn track phụ đề -> Bấm 'Đọc văn bản' (Tạo lời nói) -> Chọn giọng tương ứng.\n"
                f"3. Quay lại TankVideo bấm nút 'Đồng bộ giọng từ CapCut PC' để khớp 100%!",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi xuất CapCut", f"Không thể xuất sang CapCut Draft:\n{exc}")
