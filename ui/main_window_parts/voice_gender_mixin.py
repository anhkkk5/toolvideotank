"""VoiceGenderMixin: Voice gender check, history, DeepSeek translation and Pipeline B."""
from __future__ import annotations


try:
    from main_window_parts.common_deps import *
except ImportError:
    from ui.main_window_parts.common_deps import *



import copy
import hashlib
import json
import os
import sys
import subprocess
from uuid import uuid4

from runtime_paths import bin_path, subprocess_hidden_kwargs
from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QPushButton, QSlider, QProgressBar, QLabel, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QHBoxLayout, QVBoxLayout, QGridLayout, QGroupBox, QTabWidget, QSplitter, QScrollArea, QFrame, QDialog,
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class VoiceGenderMixin:
    """Mixin class providing all voice gender check, history management,

    DeepSeek script translation and Pipeline B automated video workflow.
    """
    def run_voice_gender_check(self):
        """Run an isolated OCR + acoustic gender report on the source video."""
        from app.services.license_service import LicenseService
        svc = LicenseService(str(getattr(self, "workspace_root", os.getcwd())))
        lic_st = svc.get_license_status()
        if not lic_st["licensed"]:
            QMessageBox.warning(
                self,
                "Yêu cầu kích hoạt bản quyền",
                f"Tính năng Phân vai AI yêu cầu kích hoạt bản quyền TankVideo!\n\n"
                f"Trạng thái: {lic_st.get('message', 'Chưa kích hoạt')}\n\n"
                f"Vui lòng nhấn vào nút 'Bản quyền' trên thanh tiêu đề để đăng nhập và kích hoạt.",
            )
            getattr(self, "open_license_dialog", lambda: None)()
            return

        video_path = self._normalize_local_file_path(
            self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        )
        if not video_path or not os.path.isfile(video_path):
            QMessageBox.warning(self, "Kiểm tra giọng nói", "Hãy import một video hợp lệ trước.")
            return
        running = getattr(self, "_voice_gender_check_worker", None)
        if running is not None and running.isRunning():
            return

        button = getattr(self, "voice_gender_check_btn", None)
        if button is not None:
            button.setEnabled(False)
            button.setText("Đang kiểm tra…")

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

        # Lấy khung OCR người dùng đã đặt cho video này
        ocr_rect = None
        preview_panel = getattr(self, "preview_panel", None)
        if preview_panel and hasattr(preview_panel, "_norm"):
            norm_r = preview_panel._norm
            if norm_r and norm_r.width() > 0 and norm_r.height() > 0:
                ocr_rect = (float(norm_r.x()), float(norm_r.y()), float(norm_r.width()), float(norm_r.height()))

        if not ocr_rect and hasattr(self, "_video_ocr_rects"):
            norm_p = os.path.normpath(video_path)
            ocr_rect = self._video_ocr_rects.get(norm_p)

        if not ocr_rect:
            ps = getattr(self, "current_project_state", None)
            if ps and hasattr(ps, "settings"):
                r_str = ps.settings.get("ocr_subtitle_rect", "")
                if r_str:
                    try:
                        parts = [float(p) for p in r_str.split(",")]
                        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
                            ocr_rect = tuple(parts)
                    except Exception:
                        pass

        if not ocr_rect:
            rect_env = os.getenv("OCR_SUBTITLE_RECT", "").strip()
            if rect_env:
                try:
                    parts = [float(p) for p in rect_env.split(",")]
                    if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
                        ocr_rect = tuple(parts)
                except Exception:
                    pass

        if ocr_rect:
            os.environ["OCR_SUBTITLE_RECT"] = f"{ocr_rect[0]:.4f},{ocr_rect[1]:.4f},{ocr_rect[2]:.4f},{ocr_rect[3]:.4f}"

        worker = VoiceGenderCheckWorker(video_path, existing_cues=existing_cues if existing_cues else None, ocr_rect=ocr_rect)
        self._voice_gender_check_video_path = video_path
        self._voice_gender_check_worker = worker
        worker.progress.connect(self._on_voice_gender_check_progress)
        worker.completed.connect(self._on_voice_gender_check_completed)
        worker.finished.connect(lambda: self._finish_voice_gender_check_worker(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _finish_voice_gender_check_worker(self, worker):
        if getattr(self, "_voice_gender_check_worker", None) is worker:
            self._voice_gender_check_worker = None
        self.refresh_ui_state()

    def _on_voice_gender_check_progress(self, message):
        button = getattr(self, "voice_gender_check_btn", None)
        if button is not None:
            short = str(message or "Đang kiểm tra…").replace("…", "")
            button.setText(short[:28] + ("…" if len(short) > 28 else ""))

    def _save_env_key_value(self, key: str, value: str):
        """Save a key-value pair to .env safely and update os.environ."""
        k = str(key).strip()
        v = str(value).strip()
        if not k:
            return
        os.environ[k] = v

        env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
        lines = []
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception:
                lines = []

        new_lines = []
        found = False
        for line in lines:
            if re.match(rf"^{re.escape(k)}\s*=.*", line):
                new_lines.append(f"{k}={v}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{k}={v}\n")

        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as exc:
            print(f"[Config] Cannot write .env: {exc}")

    def _voice_gender_history_file(self, video_path=""):
        state = getattr(self, "current_project_state", None)
        project_root = str(getattr(state, "project_root", "") or "")
        if project_root:
            history_dir = os.path.join(project_root, "analysis")
        else:
            source = self._normalize_local_file_path(
                video_path or (self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else "")
            )
            key = hashlib.sha256(os.path.abspath(source).lower().encode("utf-8")).hexdigest()[:20]
            history_dir = os.path.join(str(self.workspace_root), "projects", "_voice_gender_history", key)
        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, "voice_gender_checks.json")

    def _load_voice_gender_history(self, video_path=""):
        path = self._voice_gender_history_file(video_path)
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return list(payload.get("entries") or [])
        except (OSError, ValueError, TypeError):
            return []

    def _save_voice_gender_history(self, result):
        from datetime import datetime

        video_path = str((result or {}).get("video_path") or getattr(self, "_voice_gender_check_video_path", ""))
        entries = self._load_voice_gender_history(video_path)
        entry_id = uuid4().hex
        entry = {
            "id": entry_id,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "video_path": video_path,
            "result": dict(result or {}),
        }
        entries.insert(0, entry)
        path = self._voice_gender_history_file(video_path)
        temp_file = path + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "entries": entries[:30]}, handle, ensure_ascii=False, indent=2)
        os.replace(temp_file, path)
        return entry_id

    def _delete_voice_gender_history(self, entry_id="", *, delete_all=False):
        path = self._voice_gender_history_file()
        entries = self._load_voice_gender_history()
        remaining = [] if delete_all else [entry for entry in entries if str(entry.get("id")) != str(entry_id)]
        if remaining:
            temp_file = path + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "entries": remaining}, handle, ensure_ascii=False, indent=2)
            os.replace(temp_file, path)
        elif os.path.isfile(path):
            os.remove(path)

    def _update_voice_gender_history(self, entry_id, result):
        from datetime import datetime

        video_path = str((result or {}).get("video_path") or getattr(self, "_voice_gender_check_video_path", ""))
        entries = self._load_voice_gender_history(video_path)
        for entry in entries:
            if str(entry.get("id", "")) == str(entry_id):
                entry["result"] = copy.deepcopy(dict(result or {}))
                entry["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                break
        else:
            return False
        path = self._voice_gender_history_file(video_path)
        temp_file = path + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "entries": entries}, handle, ensure_ascii=False, indent=2)
        os.replace(temp_file, path)
        return True

    def open_voice_gender_history(self):
        entries = self._load_voice_gender_history()
        if not entries:
            QMessageBox.information(self, "Lịch sử kiểm tra", "Dự án này chưa có kết quả kiểm tra giọng nói đã lưu.")
            return
        old_dialog = getattr(self, "_voice_gender_history_dialog", None)
        if old_dialog is not None:
            old_dialog.close()
        dialog = QDialog(self)
        dialog.setWindowFlags(
            Qt.Window
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        dialog.setWindowTitle("Lịch sử kiểm tra giọng nói")
        dialog.setObjectName("voiceGenderHistoryDialog")
        dialog.setModal(False)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.resize(820, 520)
        dialog.setStyleSheet("""
            QDialog#voiceGenderHistoryDialog {
                background-color: #101826;
            }
            QDialog#voiceGenderHistoryDialog QLabel {
                color: #e8f1fb;
                font-size: 13px;
                background: transparent;
            }
            QDialog#voiceGenderHistoryDialog QTableWidget {
                color: #e8f1fb;
                background-color: #0d1624;
                alternate-background-color: #121f30;
                gridline-color: #2b4058;
                border: 1px solid #2b4058;
                border-radius: 6px;
                selection-background-color: #126cc1;
                selection-color: #ffffff;
                font-size: 13px;
            }
            QDialog#voiceGenderHistoryDialog QTableWidget::item {
                color: #e8f1fb;
                padding: 8px 12px;
                border: none;
            }
            QDialog#voiceGenderHistoryDialog QTableWidget::item:selected {
                background-color: #126cc1;
                color: #ffffff;
            }
            QDialog#voiceGenderHistoryDialog QHeaderView::section {
                color: #ffffff;
                background-color: #1b2d42;
                border: none;
                border-right: 1px solid #304860;
                border-bottom: 1px solid #304860;
                padding: 10px;
                font-weight: 700;
                font-size: 13px;
            }
            QDialog#voiceGenderHistoryDialog QTableCornerButton::section {
                background-color: #1b2d42;
                border: none;
            }
            QDialog#voiceGenderHistoryDialog QScrollBar:vertical {
                background: #101826;
                width: 14px;
                margin: 0;
            }
            QDialog#voiceGenderHistoryDialog QScrollBar::handle:vertical {
                background: #3b5b7d;
                min-height: 30px;
                border-radius: 6px;
            }
            QDialog#voiceGenderHistoryDialog QPushButton {
                color: #ffffff;
                background-color: #20364d;
                border: 1px solid #3d5d7c;
                border-radius: 7px;
                padding: 8px 18px;
                font-weight: 700;
                font-size: 13px;
            }
            QDialog#voiceGenderHistoryDialog QPushButton:hover {
                background-color: #2c4b69;
            }
        """)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(entries), 5)
        table.setHorizontalHeaderLabels(["Thời gian", "Số câu", "Nam", "Nữ", "Không chắc chắn"])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(42)
        for row_index, entry in enumerate(entries):
            result = dict(entry.get("result") or {})
            counts = dict(result.get("counts") or {})
            values = [
                str(entry.get("created_at", "")).replace("T", " ")[:19],
                str(len(result.get("rows") or [])),
                str(counts.get("male", 0)),
                str(counts.get("female", 0)),
                str(counts.get("unknown", 0)),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, str(entry.get("id", "")))
                table.setItem(row_index, column, item)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 5):
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        table.selectRow(0)
        layout.addWidget(table, 1)

        def selected_entry():
            row = table.currentRow()
            return entries[row] if 0 <= row < len(entries) else None

        def open_selected():
            entry = selected_entry()
            if entry:
                dialog.close()
                self._on_voice_gender_check_completed(
                    dict(entry.get("result") or {}), "", save_history=False,
                    history_entry_id=str(entry.get("id", "")),
                )

        def delete_selected():
            entry = selected_entry()
            if not entry:
                return
            self._delete_voice_gender_history(str(entry.get("id", "")))
            dialog.close()
            self.open_voice_gender_history()

        table.cellDoubleClicked.connect(lambda _row, _column: open_selected())
        actions = QHBoxLayout()
        open_btn = QPushButton("Mở kết quả")
        open_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669); "
            "color: #ffffff; font-weight: 800; border: none; border-radius: 7px; padding: 8px 22px; font-size: 13px; } "
            "QPushButton:hover { background: #047857; }"
        )
        delete_btn = QPushButton("Xóa mục đã chọn")
        delete_all_btn = QPushButton("Xóa toàn bộ")
        close_btn = QPushButton("Đóng")
        open_btn.clicked.connect(open_selected)
        delete_btn.clicked.connect(delete_selected)
        delete_all_btn.clicked.connect(lambda: (self._delete_voice_gender_history(delete_all=True), dialog.close()))
        close_btn.clicked.connect(dialog.close)
        actions.addWidget(open_btn)
        actions.addWidget(delete_btn)
        actions.addWidget(delete_all_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)
        self._voice_gender_history_dialog = dialog
        dialog.destroyed.connect(lambda: setattr(self, "_voice_gender_history_dialog", None))
        dialog.show()

    def _on_voice_gender_check_completed(self, result, error, save_history=True, history_entry_id=""):
        button = getattr(self, "voice_gender_check_btn", None)
        if button is not None:
            button.setText("Kiểm tra giọng nói")
            button.setEnabled(True)
        if error:
            QMessageBox.critical(self, "Kiểm tra giọng nói thất bại", str(error))
            return

        result = copy.deepcopy(dict(result or {}))

        if save_history:
            try:
                history_entry_id = self._save_voice_gender_history(result)
            except Exception as exc:
                print(f"[Voice Gender Check] Cannot save history: {exc}")

        rows = list(result.get("rows") or [])
        result["rows"] = rows
        counts = dict(result.get("counts") or {})
        result["counts"] = counts
        labels = {"male": "Nam", "female": "Nữ", "unknown": "Không xác định", "none": "Không xác định"}
        report_lines = []
        for row in rows:
            gender = labels.get(str(row.get("gender", "unknown")), "Không chắc chắn")
            raw_c = float(row.get("confidence", 0.0) or 0.0)
            c_val = raw_c if raw_c > 1.0 else (raw_c * 100.0)
            suffix = f" — {c_val:.1f}%" if c_val > 0 else ""
            report_lines.append(
                f"Câu {int(row.get('index', 0))}: {row.get('text', '')} ({gender}{suffix})"
            )
        report_text = "\n".join(report_lines)
        # Tự động tắt khung OCR sau khi quét xong để không che khuất màn hình video preview
        if hasattr(self, "toggle_ocr_overlay_visibility"):
            self.toggle_ocr_overlay_visibility(False)

        old_dialog = getattr(self, "_voice_gender_result_dialog", None)
        if old_dialog is not None:
            old_dialog.close()
        dialog = QDialog(self)
        orig_v_path = result.get("video_path") or getattr(self, "_voice_gender_check_video_path", "")
        dialog.original_video_path = orig_v_path
        dialog.setWindowFlags(
            Qt.Window
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        dialog.setWindowTitle("Kết quả kiểm tra giọng nói từ video gốc")
        dialog.setObjectName("voiceGenderResultDialog")
        dialog.setModal(False)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.resize(1380, 760)
        dialog.setStyleSheet("""
            QDialog#voiceGenderResultDialog {
                background-color: #101826;
            }
            QDialog#voiceGenderResultDialog QLabel {
                color: #e8f1fb;
                font-size: 13px;
                background: transparent;
            }
            QDialog#voiceGenderResultDialog QTableWidget {
                color: #e8f1fb;
                background-color: #0d1624;
                alternate-background-color: #121f30;
                gridline-color: #2b4058;
                border: 1px solid #2b4058;
                border-radius: 6px;
                selection-background-color: #126cc1;
                selection-color: #ffffff;
                font-size: 13px;
            }
            QDialog#voiceGenderResultDialog QTableWidget::item {
                color: #e8f1fb;
                padding: 7px;
                border: none;
            }
            QDialog#voiceGenderResultDialog QHeaderView::section {
                color: #ffffff;
                background-color: #1b2d42;
                border: none;
                border-right: 1px solid #304860;
                border-bottom: 1px solid #304860;
                padding: 8px;
                font-weight: 700;
            }
            QDialog#voiceGenderResultDialog QTableCornerButton::section {
                background-color: #1b2d42;
                border: none;
            }
            QDialog#voiceGenderResultDialog QScrollBar:vertical {
                background: #101826;
                width: 14px;
                margin: 0;
            }
            QDialog#voiceGenderResultDialog QScrollBar::handle:vertical {
                background: #3b5b7d;
                min-height: 30px;
                border-radius: 6px;
            }
            QDialog#voiceGenderResultDialog QPushButton {
                color: #ffffff;
                background-color: #20364d;
                border: 1px solid #3d5d7c;
                border-radius: 7px;
                padding: 8px 20px;
                font-weight: 700;
            }
            QDialog#voiceGenderResultDialog QPushButton:hover {
                background-color: #2c4b69;
            }
        """)
        layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"Đã đọc {len(rows)} câu phụ đề gốc  •  Nam: {counts.get('male', 0)}  •  "
            f"Nữ: {counts.get('female', 0)}  •  Không xác định: "
            f"{counts.get('unknown', 0) + counts.get('none', 0)}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        note = QLabel(
            "Bấm một câu để đưa video tới đúng thời điểm; bấm đúp hoặc bấm nút ▶ Nghe để nghe đoạn âm thanh của câu đó. "
            "Bấm ⬇ Tải MP3 để xuất riêng đoạn audio kiểm tra. Có thể chỉnh sửa bản dịch tại cột Dịch tiếng Việt, "
            "đổi Nam/Nữ tại cột Giọng, hoặc bấm nút Dịch phụ đề (DeepSeek) để AI dịch tự động theo ngữ cảnh phim."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        table = QTableWidget(len(rows), 7)
        table.setHorizontalHeaderLabels(["Câu", "Thời gian (Bắt đầu → Kết thúc)", "Phụ đề gốc", "Dịch tiếng Việt", "Giọng", "Đồng thuận", "Nghe / Tải Audio"])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(46)
        confidence_items = {}
        trans_edits = {}

        def export_row_audio_mp3(row_data):
            idx = int(row_data.get("index", 1))
            st = float(row_data.get("start", 0.0))
            en = float(row_data.get("end", st + 0.1))
            # Đảm bảo padding an toàn tối thiểu 1.2s và +200ms âm đuôi để nghe trọn vẹn
            dur = max(1.2, (en - st) + 0.2)
            v_path = result.get("video_path") or getattr(self, "_voice_gender_check_video_path", "")
            if not v_path or not os.path.isfile(v_path):
                QMessageBox.warning(dialog, "Lỗi", "Không tìm thấy đường dẫn video gốc để trích xuất âm thanh.")
                return

            default_name = f"cau_{idx}_{st:.2f}s_den_{en:.2f}s.mp3"
            save_path, _ = QFileDialog.getSaveFileName(
                dialog,
                f"Lưu đoạn âm thanh câu {idx}",
                default_name,
                "Audio MP3 (*.mp3);;Audio WAV (*.wav)"
            )
            if not save_path:
                return

            ffmpeg = bin_path("ffmpeg", "ffmpeg.exe")
            try:
                cmd = [
                    ffmpeg, "-y", "-ss", f"{st:.3f}", "-t", f"{dur:.3f}",
                    "-i", v_path, "-vn"
                ]
                if save_path.lower().endswith(".wav"):
                    cmd += ["-ac", "1", "-ar", "16000", save_path]
                else:
                    cmd += ["-c:a", "libmp3lame", "-q:a", "2", save_path]

                subprocess.run(cmd, check=True, **subprocess_hidden_kwargs())
                QMessageBox.information(
                    dialog,
                    "Tải thành công",
                    f"Đã lưu đoạn âm thanh câu {idx} ({st:.2f}s → {en:.2f}s) tại:\n{save_path}"
                )
            except Exception as exc:
                QMessageBox.critical(dialog, "Lỗi trích xuất audio", f"Không thể lưu audio: {exc}")

        def refresh_manual_summary():
            updated_counts = {"male": 0, "female": 0, "none": 0, "unknown": 0}
            for current_row in rows:
                value = str(current_row.get("gender", "unknown") or "unknown").lower()
                if value not in updated_counts:
                    value = "unknown"
                updated_counts[value] += 1
            counts.clear()
            counts.update(updated_counts)
            summary.setText(
                f"Đã đọc {len(rows)} câu phụ đề gốc  •  Nam: {counts['male']}  •  "
                f"Nữ: {counts['female']}  •  Không xác định: {counts['unknown'] + counts['none']}"
            )

        def manual_gender_changed(row_index, combo):
            if not (0 <= row_index < len(rows)):
                return
            new_g = str(combo.currentData() or "unknown")
            rows[row_index]["gender"] = new_g
            rows[row_index]["final_gender"] = new_g
            rows[row_index]["confidence"] = 1.0
            rows[row_index]["final_decision_confidence"] = 100.0
            rows[row_index]["decision_mode"] = "manual"
            rows[row_index]["source"] = "manual"
            rows[row_index]["status"] = "manual_override"
            rows[row_index]["manual_override"] = True
            confidence_item = confidence_items.get(row_index)
            if confidence_item is not None:
                confidence_item.setText("Thủ công")
            refresh_manual_summary()
            save_button = getattr(dialog, "voice_gender_save_button", None)
            if save_button is not None:
                save_button.setEnabled(True)

        def manual_translation_changed(row_index, text):
            if not (0 <= row_index < len(rows)):
                return
            clean_text = text.strip()
            rows[row_index]["translated_text"] = clean_text
            rows[row_index]["translation_source"] = "manual"
            rows[row_index]["translation_edited"] = True
            rows[row_index]["translation_status"] = "manual"
            save_button = getattr(dialog, "voice_gender_save_button", None)
            if save_button is not None:
                save_button.setEnabled(True)

        for table_row, row in enumerate(rows):
            gender = labels.get(str(row.get("gender", "unknown")), "Không xác định")
            raw_conf = float(row.get("confidence", 0.0) or 0.0)
            if raw_conf > 0.0:
                conf_val = raw_conf if raw_conf > 1.0 else (raw_conf * 100.0)
                conf_str = f"{conf_val:.1f}%" if conf_val < 100.0 else f"{int(round(conf_val))}%"
            else:
                conf_str = "—"
            start = float(row.get("start", 0.0) or 0.0)
            end = max(start + 0.1, float(row.get("end", start) or start))

            # Column 0: Index
            idx_cell = QTableWidgetItem(str(int(row.get("index", 0))))
            idx_cell.setData(Qt.UserRole, start)
            idx_cell.setData(int(Qt.UserRole) + 1, end)
            table.setItem(table_row, 0, idx_cell)

            # Column 1: Time (Bắt đầu → Kết thúc)
            st_str = f"{int(start // 60):02d}:{start % 60:05.2f}"
            en_str = f"{int(end // 60):02d}:{end % 60:05.2f}"
            time_cell = QTableWidgetItem(f"{st_str} → {en_str}")
            time_cell.setTextAlignment(Qt.AlignCenter)
            time_cell.setData(Qt.UserRole, start)
            time_cell.setData(int(Qt.UserRole) + 1, end)
            table.setItem(table_row, 1, time_cell)

            # Column 2: Original Subtitle
            orig_cell = QTableWidgetItem(str(row.get("text", "") or ""))
            orig_cell.setData(Qt.UserRole, start)
            orig_cell.setData(int(Qt.UserRole) + 1, end)
            table.setItem(table_row, 2, orig_cell)

            # Column 3: Vietnamese Translation (Editable QLineEdit)
            initial_trans = str(row.get("translated_text", "") or "")
            trans_edit = QLineEdit(initial_trans)
            trans_edit.setPlaceholderText("Bản dịch tiếng Việt…")
            trans_edit.setStyleSheet(
                "QLineEdit { color: #e8f1fb; background-color: #16263a; border: 1px solid #3d5d7c; "
                "border-radius: 5px; padding: 6px 10px; font-size: 13px; }"
                "QLineEdit:focus { border: 1px solid #38bdf8; background-color: #1a304c; }"
            )
            trans_edit.textChanged.connect(
                lambda text, r_idx=table_row: manual_translation_changed(r_idx, text)
            )
            table.setCellWidget(table_row, 3, trans_edit)
            trans_edits[table_row] = trans_edit

            # Column 4: Voice / Gender ComboBox
            gender_combo = QComboBox()
            gender_combo.setMinimumWidth(200)
            gender_combo.setMinimumHeight(34)
            gender_combo.addItem("Nam", "male")
            gender_combo.addItem("Nữ", "female")
            gender_combo.addItem("Không xác định", "unknown")
            current_gender = str(row.get("gender", "unknown") or "unknown").lower()
            if current_gender == "none":
                current_gender = "unknown"
            selected_index = gender_combo.findData(current_gender)
            gender_combo.setCurrentIndex(max(0, selected_index))
            gender_combo.setStyleSheet(
                "QComboBox { color: #ffffff; background-color: #16263a; border: 1px solid #3d5d7c; "
                "border-radius: 5px; padding: 6px 12px; font-size: 14px; }"
                "QComboBox QAbstractItemView { color: #ffffff; background-color: #16263a; "
                "selection-background-color: #126cc1; min-width: 210px; font-size: 14px; }"
            )
            gender_combo.currentIndexChanged.connect(
                lambda _index, row_index=table_row, combo=gender_combo: manual_gender_changed(row_index, combo)
            )
            table.setCellWidget(table_row, 4, gender_combo)

            # Column 5: Confidence / Agreement
            is_smoothed = str(row.get("decision_mode", "")) == "contextual_smoothing"
            display_conf = "Thủ công" if row.get("manual_override") else (f"{conf_str} 🔧" if is_smoothed else conf_str)
            conf_cell = QTableWidgetItem(display_conf)
            conf_cell.setTextAlignment(Qt.AlignCenter)
            conf_cell.setData(Qt.UserRole, start)
            conf_cell.setData(int(Qt.UserRole) + 1, end)

            if is_smoothed:
                raw_g_lbl = "Nam" if row.get("raw_gender") == "male" else ("Nữ" if row.get("raw_gender") == "female" else "Không xác định")
                raw_c_pct = float(row.get("raw_gender_confidence", 0.0) or 0.0)
                reasons_str = ", ".join(row.get("gender_reason") or [])
                conf_cell.setToolTip(
                    f"🔧 Đã hiệu chỉnh theo chuỗi thoại liên tục (Anchor-based smoothing)\n"
                    f"• Model âm thanh gốc: {raw_g_lbl} ({raw_c_pct:.1f}%)\n"
                    f"• Lý do: {reasons_str}"
                )
            else:
                conf_cell.setToolTip(f"Độ tin cậy nhận diện âm thanh gốc: {conf_str}")

            table.setItem(table_row, 5, conf_cell)
            confidence_items[table_row] = conf_cell

            # Column 6: Listen / Download Snippet
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(6)

            play_btn = QPushButton("▶ Nghe")
            play_btn.setToolTip("Nghe đúng đoạn âm thanh câu này")
            play_btn.setStyleSheet(
                "QPushButton { background-color: #0f2b38; color: #38bdf8; border: 1px solid #1a5270; "
                "border-radius: 4px; padding: 4px 8px; font-weight: bold; font-size: 11px; } "
                "QPushButton:hover { background-color: #0284c7; color: #ffffff; border-color: #38bdf8; }"
            )
            play_btn.clicked.connect(lambda _, r_idx=table_row: self._seek_voice_gender_result(table, r_idx, play=True))

            export_btn = QPushButton("⬇ Tải MP3")
            export_btn.setToolTip("Tải đoạn âm thanh cắt từ video gốc dạng MP3 để kiểm tra hoặc gửi đi")
            export_btn.setStyleSheet(
                "QPushButton { background-color: #2b1f0d; color: #fbbf24; border: 1px solid #6b4d1b; "
                "border-radius: 4px; padding: 4px 8px; font-weight: bold; font-size: 11px; } "
                "QPushButton:hover { background-color: #d97706; color: #ffffff; border-color: #fbbf24; }"
            )
            export_btn.clicked.connect(lambda _, r_data=row: export_row_audio_mp3(r_data))

            action_layout.addWidget(play_btn)
            action_layout.addWidget(export_btn)
            table.setCellWidget(table_row, 6, action_widget)

        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        table.setColumnWidth(4, 215)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
        table.setColumnWidth(6, 175)
        table.cellClicked.connect(lambda row, _column: self._seek_voice_gender_result(table, row, False))
        table.cellDoubleClicked.connect(lambda row, _column: self._seek_voice_gender_result(table, row, True))
        layout.addWidget(table, 1)

        actions = QHBoxLayout()
        save_changes_btn = QPushButton("Lưu thay đổi")
        save_changes_btn.setEnabled(False)
        dialog.voice_gender_save_button = save_changes_btn

        def save_manual_changes():
            nonlocal history_entry_id
            result["rows"] = rows
            result["counts"] = counts
            try:
                if history_entry_id:
                    self._update_voice_gender_history(history_entry_id, result)
                else:
                    history_entry_id = self._save_voice_gender_history(result)
                save_changes_btn.setEnabled(False)
                save_changes_btn.setText("Đã lưu")
                def _restore_btn():
                    try:
                        import shiboken6
                        if shiboken6.isValid(save_changes_btn):
                            save_changes_btn.setEnabled(True)
                            save_changes_btn.setText("Lưu thay đổi")
                    except Exception:
                        pass
                QTimer.singleShot(1200, _restore_btn)
            except Exception as exc:
                QMessageBox.critical(dialog, "Không thể lưu", str(exc))

        save_changes_btn.clicked.connect(save_manual_changes)
        actions.addWidget(save_changes_btn)

        # Button: Dịch phụ đề bằng DeepSeek (Tự động đổi nhãn tùy theo bảng đã có bản dịch hay chưa)
        def get_deepseek_btn_text():
            has_trans = any(bool(str(r.get("translated_text", "") or "").strip()) for r in rows)
            return "Dịch lại bằng DeepSeek (Nâng cao)" if has_trans else "Dịch phụ đề (DeepSeek)"

        translate_deepseek_btn = QPushButton(get_deepseek_btn_text())
        translate_deepseek_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #0369a1); "
            "color: #ffffff; font-weight: 700; border: none; border-radius: 7px; padding: 8px 18px; } "
            "QPushButton:hover { background: #0284c7; } "
            "QPushButton:disabled { background-color: #334155; color: #94a3b8; }"
        )

        def run_deepseek_translation():
            if not rows:
                QMessageBox.warning(dialog, "Thông báo", "Không có câu phụ đề nào để dịch.")
                return

            # 1. Check if any rows were edited manually
            edited_count = sum(1 for r in rows if r.get("translation_edited") and str(r.get("translated_text", "")).strip())
            overwrite_manual = False
            if edited_count > 0:
                msg_box = QMessageBox(dialog)
                msg_box.setWindowTitle("Xác nhận dịch lại phụ đề")
                msg_box.setText(
                    f"Phát hiện {edited_count} câu đã được chỉnh sửa thủ công.\n\n"
                    "Bạn có muốn giữ lại các câu đã sửa (chỉ dịch những câu chưa sửa) hay ghi đè toàn bộ?"
                )
                keep_btn = msg_box.addButton("Giữ câu sửa tay", QMessageBox.YesRole)
                overwrite_btn = msg_box.addButton("Ghi đè tất cả", QMessageBox.NoRole)
                cancel_btn = msg_box.addButton("Hủy bỏ", QMessageBox.RejectRole)
                msg_box.setDefaultButton(keep_btn)
                msg_box.exec()

                if msg_box.clickedButton() == cancel_btn:
                    return
                overwrite_manual = (msg_box.clickedButton() == overwrite_btn)

            # 2. Check DeepSeek API Key
            api_key = str(os.getenv("DEEPSEEK_API_KEY", "")).strip()
            if not api_key:
                entered_key, ok = QInputDialog.getText(
                    dialog,
                    "Cấu hình DeepSeek API",
                    "Vui lòng nhập DeepSeek API Key để tiến hành dịch phụ đề:\n(Khóa sẽ được lưu an toàn trong file .env)",
                    QLineEdit.Password,
                    "",
                )
                if not ok or not entered_key.strip():
                    return
                api_key = entered_key.strip()
                os.environ["DEEPSEEK_API_KEY"] = api_key
                self._save_env_key_value("DEEPSEEK_API_KEY", api_key)

            model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

            translate_deepseek_btn.setEnabled(False)
            translate_deepseek_btn.setText("Đang kết nối DeepSeek…")

            from worker_adapters import DeepSeekTranslationWorker
            worker = DeepSeekTranslationWorker(
                rows=rows,
                overwrite_manual=overwrite_manual,
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
                parent=dialog,
            )
            dialog._translation_worker = worker

            def on_worker_progress(msg, cur, tot):
                if tot > 0:
                    translate_deepseek_btn.setText(f"Đang dịch {cur}/{tot}…")
                else:
                    translate_deepseek_btn.setText(msg[:25] + ("…" if len(msg) > 25 else ""))

            def on_worker_row_updated(row_dict):
                r_id = row_dict.get("id")
                for idx, r_item in enumerate(rows):
                    if r_item.get("id") == r_id:
                        r_item.update(row_dict)
                        w_edit = trans_edits.get(idx)
                        if w_edit is not None:
                            w_edit.blockSignals(True)
                            w_edit.setText(row_dict.get("translated_text", ""))
                            w_edit.blockSignals(False)
                        break

            def on_worker_finished(final_rows, memory):
                translate_deepseek_btn.setText("Dịch lại bằng DeepSeek (Nâng cao)")
                translate_deepseek_btn.setEnabled(True)
                for idx, f_row in enumerate(final_rows):
                    if idx < len(rows):
                        rows[idx].update(f_row)
                        w_edit = trans_edits.get(idx)
                        if w_edit is not None:
                            w_edit.blockSignals(True)
                            w_edit.setText(f_row.get("translated_text", ""))
                            w_edit.blockSignals(False)

                save_changes_btn.setEnabled(True)
                save_manual_changes()
                QMessageBox.information(
                    dialog,
                    "Dịch hoàn tất",
                    f"Đã dịch thành công {len(final_rows)} câu phụ đề bằng DeepSeek!\n"
                    "Các bản dịch đã được cập nhật trực tiếp vào bảng."
                )

            def on_worker_error(err_msg):
                translate_deepseek_btn.setText(get_deepseek_btn_text())
                translate_deepseek_btn.setEnabled(True)
                QMessageBox.critical(dialog, "Dịch DeepSeek thất bại", err_msg)

            worker.progress.connect(on_worker_progress)
            worker.row_updated.connect(on_worker_row_updated)
            worker.finished.connect(on_worker_finished)
            worker.error.connect(on_worker_error)
            worker.start()

        translate_deepseek_btn.clicked.connect(run_deepseek_translation)
        actions.addWidget(translate_deepseek_btn)

        apply_to_project_btn = QPushButton("Áp dụng vào Dự án")
        apply_to_project_btn.setStyleSheet(
            "QPushButton { background-color: #1f4068; color: #ffffff; border: 1px solid #3282b8; "
            "border-radius: 7px; padding: 8px 18px; font-weight: 700; } "
            "QPushButton:hover { background-color: #2b588f; }"
        )

        apply_and_create_btn = QPushButton("Áp dụng & Tạo ngay")
        apply_and_create_btn.setStyleSheet(
            "QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669); "
            "color: #ffffff; font-weight: 800; border: none; border-radius: 7px; padding: 8px 20px; } "
            "QPushButton:hover { background: #047857; }"
        )

        def on_apply_to_project(auto_gen=False):
            if save_changes_btn.isEnabled():
                save_manual_changes()
            dialog.accept()

            # Tự động tắt khung OCR sau khi áp dụng kết quả để video preview hiển thị rõ ràng
            if hasattr(self, "toggle_ocr_overlay_visibility"):
                self.toggle_ocr_overlay_visibility(False)

            # Lưu approved_cues vào cấu hình của video
            v_path = result.get("video_path") or getattr(self, "_voice_gender_check_video_path", "")
            norm_vid = os.path.normpath(v_path) if v_path else ""
            if norm_vid:
                if not hasattr(self, "_video_voice_configs"):
                    self._video_voice_configs = {}
                if norm_vid not in self._video_voice_configs:
                    self._video_voice_configs[norm_vid] = {}
                self._video_voice_configs[norm_vid]["approved_cues"] = copy.deepcopy(rows)
                self._video_voice_configs[norm_vid]["voice_mode"] = "dual"

            queue_ctrl = getattr(self, "queue_controller", None)
            is_queue_active = queue_ctrl and getattr(queue_ctrl, "is_running", False)
            if auto_gen and is_queue_active and hasattr(queue_ctrl, "enqueue_approved_video") and norm_vid:
                queue_ctrl.enqueue_approved_video(norm_vid)
            else:
                self.apply_voice_gender_result_to_project(rows=rows, auto_generate=False)
                if auto_gen:
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(250, lambda: getattr(self, "start_pipeline_b_flow", lambda: None)())

        apply_to_project_btn.clicked.connect(lambda: on_apply_to_project(False))
        apply_and_create_btn.clicked.connect(lambda: on_apply_to_project(True))

        actions.addWidget(apply_to_project_btn)
        actions.addWidget(apply_and_create_btn)

        rerun_btn = QPushButton("Kiểm tra lại")
        rerun_btn.clicked.connect(lambda: (dialog.close(), self.run_voice_gender_check()))
        actions.addWidget(rerun_btn)
        if history_entry_id:
            delete_history_btn = QPushButton("Xóa khỏi lịch sử")
            delete_history_btn.clicked.connect(
                lambda: (self._delete_voice_gender_history(history_entry_id), dialog.close())
            )
            actions.addWidget(delete_history_btn)
        close_btn = QPushButton("Đóng")
        close_btn.clicked.connect(dialog.accept)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)
        self._voice_gender_result_dialog = dialog
        dialog.destroyed.connect(self._close_voice_gender_result_preview)
        dialog.show()

    def _seek_voice_gender_result(self, table, row, play=False):
        item = table.item(int(row), 0)
        if item is None:
            return
        position_ms = max(0, int(float(item.data(Qt.UserRole) or 0.0) * 1000.0))
        raw_end_ms = int(float(item.data(int(Qt.UserRole) + 1) or 0.0) * 1000.0)
        # Thêm padding an toàn +250ms ở đuôi và thời lượng nghe tối thiểu 1.4s để không bao giờ bị cắt cụt âm thanh
        end_ms = max(position_ms + 1400, raw_end_ms + 250)
        try:
            self._stop_voice_gender_result_preview()

            # Đảm bảo Media Player nạp đúng video gốc tiếng Trung để nghe chuẩn xác giọng nhân vật gốc
            dialog = getattr(self, "_voice_gender_result_dialog", None)
            v_path = getattr(dialog, "original_video_path", "") if dialog else ""
            if not v_path:
                v_path = getattr(self, "_voice_gender_check_video_path", "")
            if v_path and os.path.isfile(v_path) and hasattr(self, "media_player") and self.media_player is not None:
                current_src = ""
                try:
                    src_url = self.media_player.source()
                    current_src = src_url.toLocalFile() if hasattr(src_url, "toLocalFile") else str(src_url)
                except Exception:
                    pass
                if not current_src or os.path.normpath(current_src) != os.path.normpath(v_path):
                    from PySide6.QtCore import QUrl
                    self.media_player.setSource(QUrl.fromLocalFile(v_path))
                    self._current_video_path = v_path

            self.media_player.setPosition(position_ms)
            if play:
                self._voice_gender_preview_end_ms = end_ms
                timer = getattr(self, "_voice_gender_preview_timer", None)
                if timer is None:
                    timer = QTimer(self)
                    timer.setInterval(40)
                    timer.timeout.connect(self._watch_voice_gender_result_preview)
                    self._voice_gender_preview_timer = timer
                timer.start()
                self.media_player.play()
        except Exception as exc:
            print(f"[Voice Gender Check] Cannot seek preview: {exc}")

    def _watch_voice_gender_result_preview(self):
        end_ms = int(getattr(self, "_voice_gender_preview_end_ms", 0) or 0)
        if end_ms <= 0:
            self._stop_voice_gender_result_preview()
            return
        try:
            if int(self.media_player.position()) >= end_ms:
                self.media_player.pause()
                self.media_player.setPosition(end_ms)
                self._stop_voice_gender_result_preview(pause=False)
        except Exception as exc:
            print(f"[Voice Gender Check] Cannot stop segment preview: {exc}")
            self._stop_voice_gender_result_preview()

    def _stop_voice_gender_result_preview(self, pause=True):
        timer = getattr(self, "_voice_gender_preview_timer", None)
        if timer is not None:
            timer.stop()
        self._voice_gender_preview_end_ms = 0
        if pause:
            try:
                self.media_player.pause()
            except Exception:
                pass

    def _close_voice_gender_result_preview(self, *_args):
        self._stop_voice_gender_result_preview()
        self._voice_gender_result_dialog = None

    def apply_voice_gender_result_to_project(self, rows=None, auto_generate=True) -> bool:
        """Nạp kết quả kiểm tra giọng nói (phụ đề gốc, bản dịch, phân vai Nam/Nữ/Không xác định)
        trực tiếp vào dự án và timeline, đồng thời tạo giọng nói theo phân vai:
        - Nữ: gán Cô gái hoạt ngôn / Cô gái hoạt bát (vieneu_cogaihoatbat)
        - Nam: gán Thanh niên tự tin (vieneu_thanhnientutin)
        - Không xác định: không tạo âm thanh (skip_tts=True), chỉ hiển thị chữ dịch trên video
        """
        if rows is None:
            entries = self._load_voice_gender_history()
            if entries and isinstance(entries, list):
                rows = list(entries[0].get("result", {}).get("rows") or [])
        if not rows:
            QMessageBox.warning(self, "Chưa có dữ liệu", "Chưa tìm thấy kết quả kiểm tra giọng nói nào cho dự án này.")
            return False

        orig_segments = []
        trans_segments = []
        for idx, row in enumerate(rows):
            start = float(row.get("start", 0.0) or 0.0)
            end = max(start + 0.1, float(row.get("end", start + 0.5) or (start + 0.5)))
            orig_text = str(row.get("text", "") or row.get("original_text", "") or "").strip()
            raw_trans = str(row.get("translated_text", "") or "").strip()
            is_noise = bool(row.get("is_noise", False))
            trans_text = raw_trans if (raw_trans or is_noise) else orig_text

            gender = str(row.get("gender", "unknown") or "unknown").lower().strip()
            if is_noise or not trans_text:
                speaker = "Không xác định"
                voice_id = ""
                group_id = ""
                skip_tts = True
            elif gender in ("female", "nu", "nữ"):
                speaker = "Nữ"
                voice_id = "vieneu_cogaihoatbat"
                group_id = "circle"
                skip_tts = False
            elif gender in ("male", "nam"):
                speaker = "Nam"
                voice_id = "vieneu_thanhnientutin"
                group_id = "square"
                skip_tts = False
            else:
                speaker = "Không xác định"
                voice_id = ""
                group_id = ""
                skip_tts = True

            cue_id = int(row.get("id", idx + 1) or (idx + 1))
            base_item = {
                "id": cue_id,
                "start": start,
                "end": end,
                "speaker": speaker,
                "voice_group": group_id,
                "voice": voice_id,
                "voice_custom": voice_id,
                "voice_name": voice_id,
                "skip_tts": skip_tts,
                "manual_override": bool(row.get("manual_override")),
                "translation_source": str(row.get("translation_source", "none")),
                "translation_edited": bool(row.get("translation_edited", False)),
                "is_noise": is_noise,
            }
            orig_seg = dict(base_item)
            orig_seg["text"] = orig_text
            orig_seg["original_text"] = orig_text
            orig_seg["source_text"] = orig_text
            orig_segments.append(orig_seg)

            trans_seg = dict(base_item)
            trans_seg["text"] = trans_text
            trans_seg["translated"] = trans_text
            trans_seg["original"] = orig_text
            trans_seg["original_text"] = orig_text
            trans_seg["source_text"] = orig_text
            trans_segments.append(trans_seg)

        self.current_segments = orig_segments
        self.current_translated_segments = trans_segments
        self.current_segment_models = self._dict_segments_to_models(orig_segments, translated=False)
        self.current_translated_segment_models = self._dict_segments_to_models(trans_segments, translated=True)

        orig_srt = self.format_to_srt(orig_segments)
        trans_srt = self.format_to_srt(trans_segments)
        if hasattr(self, "transcript_text"):
            self.transcript_text.setPlainText(orig_srt)
        if hasattr(self, "translated_text"):
            self.translated_text.setPlainText(trans_srt)

        # Lưu speaker assignment vào bộ nhớ dự án
        self._save_speaker_voice_assignment("Nữ", voice="vieneu_cogaihoatbat", voice_gender_filter="female")
        self._save_speaker_voice_assignment("Nam", voice="vieneu_thanhnientutin", voice_gender_filter="male")
        self._save_speaker_voice_assignment("Không xác định", voice="", voice_gender_filter="unknown")

        # Cập nhật project artifacts & pipeline steps
        state = self.ensure_current_project()
        if state:
            self.project_service.save_text_artifact(
                state, "srt_original", os.path.join("transcription", "original.srt"), orig_srt
            )
            trans_path = self.project_service.save_text_artifact(
                state, "translated_subtitles", os.path.join("translation", "subtitles_vi.srt"), trans_srt
            )
            state.artifacts["subtitle_translated_srt"] = trans_path
            state.artifacts["translation_final"] = trans_path
            self.project_service.save_json_artifact(
                state, "transcript_segments", os.path.join("transcription", "transcript_segments.json"), orig_segments
            )
            state.set_step_status("extract_audio", "done")
            state.set_step_status("transcribe", "done")
            state.set_step_status("translate_raw", "done")
            state.set_step_status("refine_translation", "done")
            state.settings["speaker_diarization_enabled"] = False
            self.project_service.save_project(state)

        # Đồng bộ giao diện
        self.apply_segments_to_timeline()
        if hasattr(self, "subtitle_list_view") and self.subtitle_list_view:
            self.subtitle_list_view.refresh_segments()
        if hasattr(self, "sync_segment_editor_rows"):
            self.sync_segment_editor_rows()
        self.update_workflow_stage_badges()
        self.refresh_ui_state()
        self.log(
            f"[Voice Gender Check] Đã áp dụng thành công {len(trans_segments)} câu vào dự án "
            "(Nữ: Cô gái hoạt ngôn, Nam: Thanh niên tự tin, Không xác định: chỉ hiện phụ đề)."
        )

        if auto_generate:
            self._voiceover_force_refresh = True
            self.log("[Pipeline] Đang tiến hành tạo lồng tiếng giọng nói (TTS) theo phân vai...")
            self.run_voiceover_with_progress(target_stage="full")

    def start_pipeline_b_flow(self, preselected_master_id: str = ""):
        """Kích hoạt luồng Pipeline B: Tạo video tự động từ Master Data đã kiểm duyệt.

        Quy trình 3 bước chuẩn hóa theo 5 nguyên tắc:
        1. Nạp bản Master Data đã kiểm duyệt (Single Source of Truth)
        2. Lồng tiếng AI theo phân vai nhân vật (không TTS unknown/none)
        3. Khớp thời lượng (<= 1.20x) -> Ducking âm thanh gốc -> Xuất MP4 & SRT
        """
        from app.services.license_service import LicenseService
        svc = LicenseService(str(getattr(self, "workspace_root", os.getcwd())))
        lic_st = svc.get_license_status()
        if not lic_st["licensed"]:
            QMessageBox.warning(
                self,
                "Yêu cầu kích hoạt bản quyền",
                f"Tính năng TẠO VIDEO AI yêu cầu kích hoạt bản quyền TankVideo!\n\n"
                f"Trạng thái: {lic_st.get('message', 'Chưa kích hoạt')}\n\n"
                f"Vui lòng nhấn vào nút 'Bản quyền' trên thanh tiêu đề để đăng nhập và kích hoạt.",
            )
            getattr(self, "open_license_dialog", lambda: None)()
            return

        from ui.dialogs.select_master_dialog import SelectMasterDialog
        from ui.dialogs.pipeline_b_progress_dialog import PipelineBProgressDialog
        from app.models.render_job import RenderJob
        from app.services.master_dataset_service import MasterDatasetService

        video_path = self._normalize_local_file_path(
            self.video_path_edit.text().strip() if hasattr(self, "video_path_edit") else ""
        )
        state = getattr(self, "current_project_state", None)
        project_root = str(getattr(state, "project_root", "") or "")

        target_dataset = None

        if preselected_master_id:
            target_dataset = MasterDatasetService.load_dataset_by_id(
                str(self.workspace_root),
                entry_id=preselected_master_id,
                video_path=video_path,
                project_root=project_root,
            )

        audio_mix_settings = None
        voice_config = None
        subtitle_config = None
        brand_logo_settings = None
        watermark_settings = None
        if target_dataset is None:
            init_orig = int(self.audio_a1_volume_slider.value()) if hasattr(self, "audio_a1_volume_slider") else 50
            init_tts = int(self.audio_a2_volume_slider.value()) if hasattr(self, "audio_a2_volume_slider") else 100
            dialog = SelectMasterDialog(
                self,
                workspace_root=str(self.workspace_root),
                video_path=video_path,
                project_root=project_root,
                initial_orig_volume=init_orig,
                initial_tts_volume=init_tts,
            )
            if dialog.exec() != QDialog.Accepted:
                return
            target_dataset = dialog.get_selected_dataset()
            audio_mix_settings = dialog.get_audio_mix_settings()
            voice_config = dialog.get_voice_mapping_config()
            subtitle_config = dialog.get_subtitle_config()
            brand_logo_settings = dialog.get_brand_logo_settings()
            watermark_settings = dialog.get_watermark_settings()

        if not target_dataset:
            QMessageBox.warning(self, "Pipeline B", "Chưa chọn bản Master Data nào.")
            return

        # Xác định video đầu vào
        if target_dataset and getattr(target_dataset, "video_path", ""):
            video_path = target_dataset.video_path or video_path

        # Chuẩn hóa thư mục xuất video theo convention hiện tại của CapCap
        output_folder = (
            self.final_output_folder_edit.text().strip()
            if hasattr(self, "final_output_folder_edit") and self.final_output_folder_edit.text().strip()
            else os.path.join(str(self.workspace_root), "output")
        )
        os.makedirs(output_folder, exist_ok=True)
        video_name = os.path.splitext(os.path.basename(video_path))[0] if video_path else "video"
        output_video_path = os.path.join(output_folder, f"{video_name}_final_vi.mp4")

        from app.services.video_creator_service import VideoCreatorConfig
        creator_config = VideoCreatorConfig()
        creator_config.enable_blur_mask = True
        if subtitle_config:
            creator_config.subtitle_config = subtitle_config
            creator_config.mask_mode = getattr(subtitle_config, "mask_mode", "blur")
            creator_config.blur_rect = getattr(subtitle_config, "blur_rect", None)
            creator_config.enable_blur_mask = getattr(subtitle_config, "enable_blur_mask", True)
        if voice_config:
            creator_config.voice_config = voice_config

        # Nạp dự phòng từ QSettings nếu chưa có từ dialog
        if brand_logo_settings is None or watermark_settings is None:
            branding_st = QSettings("TankVideo", "TankVideoStudio")
            if brand_logo_settings is None:
                enable_l = branding_st.value("branding/enable_logo", False, type=bool)
                l_path = branding_st.value("branding/logo_path", "", type=str)
                brand_logo_settings = {
                    "enable": enable_l and bool(l_path),
                    "path": l_path,
                    "position": branding_st.value("branding/logo_pos", "top_left", type=str),
                    "size_percent": branding_st.value("branding/logo_size", 15, type=int),
                    "opacity": float(branding_st.value("branding/logo_opacity", 100, type=int)) / 100.0,
                }
            if watermark_settings is None:
                enable_w = branding_st.value("branding/enable_watermark", False, type=bool)
                w_text = branding_st.value("branding/watermark_text", "", type=str)
                watermark_settings = {
                    "enable": enable_w and bool(w_text),
                    "text": w_text,
                    "position": branding_st.value("branding/watermark_pos", "center", type=str),
                    "font_size": branding_st.value("branding/watermark_size", 36, type=int),
                    "opacity": float(branding_st.value("branding/watermark_opacity", 35, type=int)) / 100.0,
                    "color": "#FFFFFF",
                }

        # Áp dụng cấu hình Logo thương hiệu & Watermark bản quyền
        if brand_logo_settings:
            creator_config.enable_brand_logo = bool(brand_logo_settings.get("enable", False))
            creator_config.brand_logo_path = str(brand_logo_settings.get("path", ""))
            creator_config.brand_logo_position = str(brand_logo_settings.get("position", "top_left"))
            creator_config.brand_logo_size_percent = int(brand_logo_settings.get("size_percent", 15))
            creator_config.brand_logo_opacity = float(brand_logo_settings.get("opacity", 1.0))

        if watermark_settings:
            creator_config.enable_watermark = bool(watermark_settings.get("enable", False))
            creator_config.watermark_text = str(watermark_settings.get("text", ""))
            creator_config.watermark_position = str(watermark_settings.get("position", "center"))
            creator_config.watermark_font_size = int(watermark_settings.get("font_size", 36))
            creator_config.watermark_opacity = float(watermark_settings.get("opacity", 0.35))
            creator_config.watermark_color = str(watermark_settings.get("color", "#FFFFFF"))

        # Nạp cấu hình Xóa Logo & Watermark video gốc (Delogo AI) từ QSettings (mặc định False)
        delogo_st = QSettings("TankVideo", "TankVideoStudio")
        creator_config.delogo_bilibili = delogo_st.value("delogo/enable_bilibili", False, type=bool)
        creator_config.delogo_watermark = delogo_st.value("delogo/enable_watermark", False, type=bool)
        creator_config.delogo_watermark_mode = delogo_st.value("delogo/watermark_mode", "delogo", type=str)
        if creator_config.delogo_watermark:
            wm_str = delogo_st.value("delogo/watermark_rect", "", type=str)
            if wm_str:
                try:
                    parts = [float(p) for p in wm_str.split(",")]
                    if len(parts) == 4:
                        creator_config.delogo_watermark_rect = (parts[0], parts[1], parts[2], parts[3])
                except Exception:
                    pass
        if delogo_st.value("delogo/enable_custom", False, type=bool):
            cr_str = delogo_st.value("delogo/custom_rect", "", type=str)
            if cr_str:
                try:
                    parts = [float(p) for p in cr_str.split(",")]
                    if len(parts) == 4:
                        creator_config.delogo_custom_rect = (parts[0], parts[1], parts[2], parts[3])
                except Exception:
                    pass
            creator_config.delogo_custom_mode = delogo_st.value("delogo/custom_mode", "delogo", type=str)
            # Nếu người dùng đang bật Logo thương hiệu ở Top-Left mà vùng delogo custom cũng ở Top-Left,
            # hủy bỏ delogo custom này để tránh tạo vệt mờ nhòe đè lên Logo thương hiệu
            if creator_config.enable_brand_logo and "left" in str(creator_config.brand_logo_position).lower() and "top" in str(creator_config.brand_logo_position).lower():
                if creator_config.delogo_custom_rect:
                    cx, cy, cw, ch = creator_config.delogo_custom_rect
                    if cx < 0.35 and cy < 0.25:
                        creator_config.delogo_custom_rect = None

        # Áp dụng cấu hình Hòa trộn âm thanh (Audio Mix) từ dialog
        if audio_mix_settings:
            orig_vol = float(audio_mix_settings.get("original_volume", 0.50))
            tts_vol = float(audio_mix_settings.get("tts_volume", 1.00))
            creator_config.original_volume = orig_vol
            creator_config.tts_volume = tts_vol
            if orig_vol <= 0.001:
                creator_config.duck_volume = 0.0
            else:
                creator_config.duck_volume = min(orig_vol, max(0.05, orig_vol * 0.40))

            # Đồng bộ ngược lại thanh trượt trên Sidebar nếu có
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

        # Tự động nạp vùng mặt nạ từ khung vẽ OCR / Blur Region người dùng đã chọn trên giao diện
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

        if blur_rect:
            creator_config.blur_rect = blur_rect

        # Khởi tạo RenderJob (Nguyên tắc 5)
        job = RenderJob.create(target_dataset, workspace_root=str(self.workspace_root))
        job.output_video_file = output_video_path

        # Mở dialog tiến trình 3 bước trực quan
        progress_dlg = PipelineBProgressDialog(
            self,
            job=job,
            target_dataset=target_dataset,
            original_video_path=video_path,
            segments=target_dataset.segments,
            output_video_path=output_video_path,
            config=creator_config,
        )
        progress_dlg.exec()

        # Kiểm tra kết quả sau khi hoàn thành: Nạp video hoàn thành và hiển thị audio lồng tiếng lên Player/Timeline
        result = getattr(progress_dlg, "_last_result", None)
        if result and getattr(result, "status", "") == "success" and result.output_video_path and os.path.isfile(result.output_video_path):
            output_video = os.path.abspath(result.output_video_path)
            output_audio = getattr(result, "output_audio_path", "")
            if output_audio and os.path.isfile(output_audio):
                output_audio = os.path.abspath(output_audio)
                if hasattr(self, "processed_artifacts"):
                    self.processed_artifacts["voice_vi"] = output_audio
                    self.processed_artifacts["mixed_vi"] = output_audio
                    self.processed_artifacts["final_video"] = output_video
                self.last_voice_vi_path = output_audio
                self.last_mixed_vi_path = output_audio

            # 1. Cập nhật đường dẫn video hoàn thành thay thế video gốc trên giao diện
            self._current_video_path = output_video
            if hasattr(self, "video_path_edit"):
                self.video_path_edit.setText(output_video)

            # 2. Nạp video hoàn thành vào Preview Media Player
            if hasattr(self, "media_player") and self.media_player is not None:
                try:
                    self.media_player.pause()
                except Exception:
                    pass
                from PySide6.QtCore import QUrl, QTimer
                self.media_player.setSource(QUrl.fromLocalFile(output_video))
                if hasattr(self, "refresh_video_dimensions"):
                    self.refresh_video_dimensions(output_video)
                self._preview_video_has_burned_subtitles = True
                if hasattr(self, "sync_live_subtitle_preview"):
                    self.sync_live_subtitle_preview()

            # 3. Hiển thị trên Timeline (Track V1 Video và Track A1 Âm thanh đã lồng tiếng)
            if hasattr(self, "timeline") and self.timeline is not None:
                dur = float(getattr(result, "final_video_duration", 0.0) or getattr(result, "audio_duration", 0.0) or 0.0)
                if dur <= 0.0 and hasattr(self, "media_player"):
                    try:
                        dur = max(0.0, float(self.media_player.duration() or 0.0) / 1000.0)
                    except Exception:
                        dur = 0.0
                if hasattr(self.timeline, "set_video_source"):
                    self.timeline.set_video_source(output_video, dur)
                    ensure_tracks = getattr(self.timeline, "_ensure_tracks_populated", None)
                    if callable(ensure_tracks):
                        ensure_tracks()
                    redraw = getattr(self.timeline, "_redraw", None)
                    if callable(redraw):
                        redraw()

                # Xóa visual cache để làm mới dải sóng âm (waveform) và thumbnail của video hoàn thành
                self._timeline_waveform_cache_key = None
                self._timeline_video_thumb_cache_key = None
                self._desired_timeline_waveform_request = None
                self._desired_timeline_thumbnail_request = None
                if hasattr(self, "schedule_timeline_visual_refresh"):
                    self.schedule_timeline_visual_refresh(waveform=True, thumbnails=True)

                if hasattr(self.timeline, "set_playhead"):
                    self.timeline.set_playhead(0.0)

            # 4. Tua về đầu video 00:00
            try:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(150, lambda: self.media_player.setPosition(0) if hasattr(self, "media_player") else None)
            except Exception:
                pass

