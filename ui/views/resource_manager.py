import os

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from runtime_paths import workspace_root as default_workspace_root
from services import ResourceDownloadService


_STATUS_STYLES = {
    "installed": ("Sẵn sàng", "#3ddc97", "#1b3b2c"),
    "partial":   ("Một phần", "#f0b347", "#3b2f12"),
    "missing":   ("Chưa tải", "#ff6b6b", "#3b1a1a"),
}


def _status_pill_widget(status_key: str, parent: QWidget, label_override: str = "") -> QLabel:
    status = str(status_key or "").strip().lower()
    default_label, fg, bg = _STATUS_STYLES.get(status, _STATUS_STYLES["missing"])
    label = str(label_override or default_label).strip() or default_label
    pill = QLabel(label, parent)
    pill.setAlignment(Qt.AlignCenter)
    pill.setStyleSheet(
        f"color: {fg}; background-color: {bg}; border: 1px solid {fg}55;"
        f" border-radius: 10px; padding: 3px 12px; font-weight: 700; font-size: 12px;"
    )
    pill.setFixedHeight(24)
    return pill


def _open_url(url: str) -> bool:
    target = str(url or "").strip()
    if not target:
        return False
    return QDesktopServices.openUrl(QUrl(target))


def _open_folder_dialog(gui_parent, path: str) -> None:
    target = str(path or "").strip()
    if not target:
        return
    from PySide6.QtWidgets import QMessageBox
    try:
        os.makedirs(target, exist_ok=True)
        os.startfile(os.path.abspath(target))
    except Exception as exc:
        QMessageBox.critical(gui_parent, "Lỗi", f"Không thể mở thư mục:\n{exc}")


def open_resource_manager(workspace_root: str = None, parent=None,
                          on_finished=None):
    if workspace_root is None:
        workspace_root = default_workspace_root()

    service = ResourceDownloadService(workspace_root)

    dialog = QDialog(parent)
    dialog.setWindowTitle("Quản lý tài nguyên")
    dialog.setModal(True)
    dialog.resize(820, 580)
    dialog.setStyleSheet("""
        QDialog { background-color: #0f1724; }
        QLabel { color: #d7e3f4; background-color: transparent; }
        QLabel#resourceTitle { color: #f8fbff; font-size: 16px; font-weight: 700; }
        QLabel#resourceHint { color: #9fb3ca; font-size: 12px; }
        QWidget#resourceContent { background-color: transparent; }
        QScrollArea { border: none; background-color: #0f1724; }
        QFrame#resourceCard { background-color: #132033; border: 1px solid #2f4868; border-radius: 12px; }
        QPushButton {
            background-color: #22344d; color: #f8fbff; border: 1px solid #34506f;
            border-radius: 8px; padding: 6px 14px; font-weight: 600; min-width: 90px;
        }
        QPushButton:hover { background-color: #29405d; }
        QPushButton:disabled { color: #8ea3bb; background-color: #182636; border-color: #29405d; }
        QPushButton#primaryBtn {
            background-color: #1a3a5c; color: #8ad7ff; border: 1px solid #4ecdc4;
            font-weight: 700;
        }
        QPushButton#primaryBtn:hover { background-color: #224a6e; }
    """)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    title = QLabel("Quản lý tài nguyên AI & Runtime", dialog)
    title.setObjectName("resourceTitle")
    layout.addWidget(title)

    hint = QLabel(
        "Mỗi tài nguyên hiển thị thư mục đích và nút tải tương ứng. "
        "Bấm nút 'Tải ...' để tải tự động hoặc tải thủ công rồi sao chép vào thư mục đích. "
        "Bấm 'Làm mới' sau khi sao chép để cập nhật trạng thái.",
        dialog,
    )
    hint.setObjectName("resourceHint")
    hint.setWordWrap(True)
    layout.addWidget(hint)

    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    layout.addWidget(scroll, 1)

    content = QWidget(dialog)
    content.setObjectName("resourceContent")
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(10)
    scroll.setWidget(content)

    dialog._resource_rows = {}
    download_worker = [None]
    active_resource_id = [""]
    download_state = {"running": False}

    def _show_status_pill(row, status_key: str, status_label: str = ""):
        new_pill = _status_pill_widget(status_key, dialog, status_label)
        row["header_row"].replaceWidget(row["status_pill"], new_pill)
        row["status_pill"].deleteLater()
        row["status_pill"] = new_pill
        row["status_pill"].show()

    def _set_download_button(row, *, active: bool = False, message: str = ""):
        button = row.get("download_btn") if row else None
        if button is None:
            return
        if active:
            button.setEnabled(False)
            button.setText(str(message or "Đang tải..."))
        else:
            button.setEnabled(bool(row.get("download_supported", False)))
            button.setText(str(row.get("download_label", "Tải xuống")))

    def _on_download_progress(percent: int, message: str):
        resource_id = active_resource_id[0]
        row = dialog._resource_rows.get(resource_id)
        if row is None:
            return
        try:
            value = int(percent)
        except (TypeError, ValueError):
            value = -1
        if value >= 0:
            _set_download_button(row, active=True, message=f"Đang tải... {max(0, min(100, value))}%")
        else:
            _set_download_button(row, active=True, message="Đang tải...")

    def _on_download_finished(resource_id: str, error: str):
        download_worker[0] = None
        download_state["running"] = False
        active_resource_id[0] = ""
        row = dialog._resource_rows.get(resource_id)
        if row is not None:
            _set_download_button(row, active=False)
        if error:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                dialog,
                "Tải tài nguyên thất bại",
                f"Không thể tải {resource_id}.\n\n{error}",
            )
            return
        _refresh()
        if on_finished:
            try:
                on_finished()
            except Exception:
                pass

    def _start_download(resource_id: str):
        rid = str(resource_id or "").strip()
        if not rid:
            return
        if download_state["running"]:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                dialog,
                "Đang có tiến trình tải",
                "Một tài nguyên khác đang được tải về. Vui lòng đợi hoàn tất.",
            )
            return
        row = dialog._resource_rows.get(rid)
        if row is None or not row.get("download_supported", False):
            return

        if rid == "voice:pack":
            count = service._usable_piper_voice_count("vi")
            if count >= 25:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    dialog,
                    "Giọng đọc Piper đã sẵn sàng",
                    f"Gói {count} giọng đọc Piper Tiếng Việt offline đã có đầy đủ trên máy của bạn và SẴN SÀNG sử dụng!\n\n"
                    "Bạn không cần phải tải lại nữa.",
                    QMessageBox.Ok,
                )
                return

        if rid == "voice:vieneu":
            if service.is_resource_installed("voice:vieneu"):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    dialog,
                    "VieNeu TTS đã sẵn sàng",
                    "Gói giọng đọc VieNeu AI Neural (Cô gái hoạt ngôn & Thanh niên tự tin) đã được cài đặt và SẴN SÀNG sử dụng trên máy tính của bạn!\n\n"
                    "Bạn có thể sử dụng ngay 2 giọng đọc này khi tạo dự án và vào màn hình Lồng tiếng mà không cần tải lại.",
                    QMessageBox.Ok,
                )
                return

            try:
                from app.services.license_service import LicenseService
                lic = LicenseService(workspace_root)
                is_valid, _ = lic.is_license_valid()
                if not is_valid:
                    from PySide6.QtWidgets import QMessageBox
                    ans = QMessageBox.question(
                        dialog,
                        "Tài nguyên VIP (VieNeu AI Neural)",
                        "Gói VieNeu TTS (~4.5 GB) dành cho tài khoản VIP.\n\n"
                        "Bạn có muốn mở hộp thoại kích hoạt bản quyền VIP trước khi tải không?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    if ans == QMessageBox.Yes:
                        from ui.dialogs.login_license_dialog import LoginLicenseDialog
                        dlg = LoginLicenseDialog(dialog, workspace_root=workspace_root)
                        dlg.exec()
            except Exception:
                pass

            from PySide6.QtWidgets import QMessageBox
            ans = QMessageBox.question(
                dialog,
                "Tải gói VieNeu AI (~4.5 GB)",
                "Gói VieNeu Neural TTS có dung lượng lớn (~4.5 GB) trên Google Drive.\n\n"
                "Để tải với tốc độ cao nhất và an toàn nhất, phần mềm sẽ mở link Google Drive trên trình duyệt của bạn.\n\n"
                "Sau khi tải xong file 'vieneu_runtime_full.zip', hãy giải nén vào thư mục lưu trữ rồi bấm nút 'Làm mới'.\n\n"
                "Bạn có muốn mở trang tải về ngay bây giờ không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if ans == QMessageBox.Yes:
                _open_url("https://drive.google.com/file/d/1hMVIr-E0xSeKg8kEeU4EvbZYwlODkHoB/view?usp=sharing")
            return

        try:
            from worker_adapters.processing_workers import ResourceDownloadWorker

        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(dialog, "Tải tài nguyên", f"Tiến trình tải không khả dụng:\n\n{exc}")
            return

        download_state["running"] = True
        active_resource_id[0] = rid
        _set_download_button(row, active=True)
        worker = ResourceDownloadWorker(workspace_root, rid)
        worker.progress.connect(_on_download_progress)
        worker.finished.connect(_on_download_finished)
        download_worker[0] = worker
        worker.start()

    def _add_card(item, target_layout):
        card = QFrame(dialog)
        card.setObjectName("resourceCard")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        name_label = QLabel(str(item.get("name", item.get("id", "Tài nguyên"))), dialog)
        name_label.setStyleSheet("color: #f8fbff; font-weight: 700; font-size: 14px; background-color: transparent;")
        header_row.addWidget(name_label, 1)

        required_for = str(item.get("required_for", "") or "").strip()
        if required_for:
            req_text = "Chế độ GPU" if "GPU" in required_for else required_for
            required_label = QLabel(f"Bắt buộc cho {req_text}", dialog)
            required_label.setStyleSheet(
                "color: #ffd28a; font-size: 10px; font-weight: 700; "
                "background-color: #4a3520; border: 1px solid #8b6734; "
                "border-radius: 6px; padding: 2px 6px;"
            )
            header_row.addWidget(required_label, 0, Qt.AlignVCenter)

        status_pill = _status_pill_widget(
            item.get("status", "missing"),
            dialog,
            item.get("status_label", ""),
        )
        header_row.addWidget(status_pill, 0, Qt.AlignVCenter | Qt.AlignRight)

        outer.addLayout(header_row)

        description = str(item.get("description", "")).strip()
        if description:
            desc_label = QLabel(description, dialog)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: #c0d0e3; font-size: 12px; background-color: transparent;")
            outer.addWidget(desc_label)

        target_dir = str(item.get("target_dir", "")).strip()
        if target_dir:
            display_dir = target_dir
            lower_dir = target_dir.lower()
            if "models" in lower_dir:
                idx = lower_dir.find("models")
                display_dir = os.path.join("TankVideo", target_dir[idx:])
            else:
                try:
                    from app.runtime_paths import workspace_root
                    ws = workspace_root()
                    if lower_dir.startswith(ws.lower()):
                        rel = os.path.relpath(target_dir, ws)
                        display_dir = os.path.join("TankVideo", rel)
                except Exception:
                    pass
            display_dir = display_dir.replace("CapCap", "TankVideo").replace("capcap", "TankVideo")

            path_row = QHBoxLayout()
            path_row.setSpacing(6)
            path_label = QLabel("Thư mục lưu:", dialog)
            path_label.setStyleSheet("color: #8ea3bb; font-size: 11px; background-color: transparent;")
            path_value = QLabel(display_dir, dialog)
            path_value.setStyleSheet("color: #d7e3f4; font-size: 11px; font-family: monospace; background-color: transparent;")
            path_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            path_value.setWordWrap(True)
            path_row.addWidget(path_label, 0)
            path_row.addWidget(path_value, 1)
            outer.addLayout(path_row)

        expected = str(item.get("expected_filename", "")).strip()
        if expected:
            file_row = QHBoxLayout()
            file_row.setSpacing(6)
            file_caption = QLabel("Tệp yêu cầu:", dialog)
            file_caption.setStyleSheet("color: #8ea3bb; font-size: 11px; background-color: transparent;")
            file_value = QLabel(expected, dialog)
            file_value.setStyleSheet("color: #d7e3f4; font-size: 11px; font-family: monospace; background-color: transparent;")
            file_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            file_value.setWordWrap(True)
            file_row.addWidget(file_caption, 0)
            file_row.addWidget(file_value, 1)
            outer.addLayout(file_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)

        download_url = str(item.get("download_url", "")).strip()
        resource_id = str(item.get("id", "") or "").strip()
        download_btn = QPushButton("Mở trang tải về", dialog)
        download_btn.setObjectName("primaryBtn")
        if resource_id == "voice:vieneu" and not download_url:
            download_btn.setEnabled(True)
            download_btn.setToolTip("Liên hệ Admin để nhận quyền truy cập Google Drive tải gói VieNeu")
            def _open_vieneu_drive():
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    dialog,
                    "Tải gói VieNeu Neural TTS",
                    "Gói VieNeu AI (Cô gái hoạt ngôn & Thanh niên tự tin) được lưu trữ trên Google Drive bảo mật.\n\n"
                    "👉 Sau khi đăng ký tài khoản VIP, bạn sẽ được Admin cấp quyền tải trực tiếp vào địa chỉ Gmail của bạn.\n\n"
                    "Sau khi tải về, hãy giải nén file vào thư mục lưu trữ (bấm nút 'Mở thư mục lưu') rồi bấm 'Làm mới'.",
                )
            download_btn.clicked.connect(_open_vieneu_drive)
        else:
            download_btn.setEnabled(bool(download_url))
            if download_url:
                download_btn.setToolTip(download_url)
            download_btn.clicked.connect(
                lambda _checked=False, url=download_url: _open_url(url)
            )
        button_row.addWidget(download_btn)

        resource_id = str(item.get("id", "") or "").strip()
        download_supported = bool(
            item.get("auto_download_supported", False)
            and service.supports_auto_download(resource_id)
        )
        resource_download_btn = None
        download_label = {
            "whisper:base": "Tải Whisper Base",
            "whisper:small": "Tải Whisper Small",
            "whisper:medium": "Tải Whisper Medium",
            "cuda:whisper": "Tải gói tăng tốc GPU",
            "sensevoice:model": "Tải SenseVoice",
            "ocr:engine": "Tải Rapid OCR",
            "diarization:segmentation": "Tải mô hình người nói",
            "diarization:embedding": "Tải mô hình người nói",
            "voice:pack": "Tải giọng đọc Tiếng Việt",
            "voice:pack-en": "Tải giọng đọc Tiếng Anh",
            "voice:vieneu": "Tải gói VieNeu TTS",
        }.get(resource_id, "Tải xuống")

        if download_supported:
            resource_download_btn = QPushButton(download_label, dialog)
            resource_download_btn.setToolTip("Tải tài nguyên này tự động vào thư mục lưu")
            resource_download_btn.clicked.connect(
                lambda _checked=False, rid=item["id"]: _start_download(rid)
            )
            button_row.addWidget(resource_download_btn)

        open_folder_btn = QPushButton("Mở thư mục lưu", dialog)
        open_folder_btn.setEnabled(bool(target_dir))
        open_folder_btn.clicked.connect(
            lambda _checked=False, p=target_dir: _open_folder_dialog(dialog, p)
        )
        button_row.addWidget(open_folder_btn)

        outer.addLayout(button_row)

        target_layout.addWidget(card)
        dialog._resource_rows[item["id"]] = {
            "item": item,
            "name_label": name_label,
            "status_pill": status_pill,
            "header_row": header_row,
            "download_btn": resource_download_btn,
            "download_supported": download_supported,
            "download_label": download_label,
        }

    def _make_section(title_text, expanded):
        wrapper = QFrame()
        wrapper.setObjectName("statusCard")
        wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(8, 2, 8, 2)
        wrapper_layout.setSpacing(0)

        btn = QToolButton()
        btn.setText(("▼ " if expanded else "▶ ") + title_text)
        btn.setCheckable(True)
        btn.setChecked(expanded)
        btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn.setStyleSheet("QToolButton { text-align: left; font-weight: 700; color: #8ad7ff; border: none; padding: 2px 4px; margin: 0; }")

        inner = QWidget()
        inner.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 4)
        inner_layout.setSpacing(2)
        inner.setVisible(expanded)
        if not expanded:
            inner.setMaximumHeight(0)

        btn.toggled.connect(lambda c: (
            btn.setText(("▼ " if c else "▶ ") + title_text),
            inner.setVisible(c),
            inner.setMaximumHeight(16777215 if c else 0),
        ))
        wrapper_layout.addWidget(btn)
        wrapper_layout.addWidget(inner)
        return wrapper, inner_layout

    def _refresh():
        resources = {item["id"]: item for item in service.list_resources()}
        for resource_id, row in dialog._resource_rows.items():
            item = resources.get(resource_id, row.get("item", {}))
            row["item"] = item
            status = str(item.get("status", "missing")).strip().lower()
            _show_status_pill(row, status, str(item.get("status_label", "") or ""))
            row["download_supported"] = bool(
                service.supports_auto_download(resource_id)
                and item.get("auto_download_supported", False)
            )
            is_active = bool(download_state["running"] and resource_id == active_resource_id[0])
            _set_download_button(row, active=is_active)

    def _populate():
        for i in reversed(range(content_layout.count())):
            it = content_layout.takeAt(i)
            widget = it.widget() if it is not None else None
            if widget is not None:
                widget.deleteLater()
        dialog._resource_rows = {}

        resources = service.list_resources()
        cpu_items = [r for r in resources if r.get("kind") in {"sensevoice", "whisper_cpu", "ocr"}]
        gpu_kinds = {"ai", "whisper", "cuda"}
        gpu_items = [r for r in resources if r.get("kind") in gpu_kinds]
        speaker_items = [r for r in resources if r.get("kind") == "diarization"]
        voice_items = [r for r in resources if r.get("kind") == "voice"]

        if cpu_items:
            cpu_card, cpu_layout = _make_section("Tài nguyên CPU", expanded=True)
            for item in cpu_items:
                _add_card(item, cpu_layout)
            content_layout.addWidget(cpu_card)

        if gpu_items:
            gpu_card, gpu_layout = _make_section("Tài nguyên GPU", expanded=True)
            for item in gpu_items:
                _add_card(item, gpu_layout)
            content_layout.addWidget(gpu_card)

        if speaker_items:
            speaker_card, speaker_layout = _make_section("Mô hình nhận diện người nói", expanded=False)
            for item in speaker_items:
                _add_card(item, speaker_layout)
            content_layout.addWidget(speaker_card)

        for item in voice_items:
            _add_card(item, content_layout)

        content_layout.addStretch()

    _populate()

    footer_row = QHBoxLayout()
    footer_row.setSpacing(8)
    footer_hint = QLabel(
        "Mẹo: Các thư mục lưu trữ sẽ tự động được tạo khi bạn bấm mở.",
        dialog,
    )
    footer_hint.setObjectName("resourceHint")
    footer_hint.setWordWrap(True)
    footer_row.addWidget(footer_hint, 1)

    refresh_btn = QPushButton("Làm mới", dialog)
    refresh_btn.clicked.connect(_refresh)
    footer_row.addWidget(refresh_btn)

    close_btn = QPushButton("Đóng", dialog)
    close_btn.clicked.connect(dialog.accept)
    footer_row.addWidget(close_btn)

    layout.addLayout(footer_row)

    def _on_dialog_closed():
        worker = download_worker[0]
        if worker is not None and worker.isRunning():
            # ResourceDownloadWorker performs blocking network/file work, so
            # let it finish briefly before the dialog is destroyed.  This
            # prevents QThread warnings when a user closes Manage Resources
            # during a download.
            worker.quit()
            worker.wait(3000)
            if worker.isRunning():
                worker.terminate()
                worker.wait(1000)
            download_worker[0] = None
            download_state["running"] = False
        if on_finished:
            try:
                on_finished()
            except Exception:
                pass

    dialog.accepted.connect(_on_dialog_closed)
    dialog.rejected.connect(_on_dialog_closed)
    dialog.exec()
