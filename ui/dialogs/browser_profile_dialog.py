"""Browser & Profile Selector Dialog & Cookie Expired Alert Dialog.

Cung cấp giao diện hiện đại phong cách Cyberpunk:
1. BrowserProfileDialog: Cho phép người dùng chọn trình duyệt đã cài trên máy (Cốc Cốc, Chrome, Edge...)
   - Nếu trình duyệt có profile: Hiển thị danh sách profile để chọn.
   - Nếu không có hoặc chỉ có 1 profile: Chạy thẳng vào quét.
   - Tùy chọn ghi nhớ lựa chọn để không phải hỏi lại các lần sau.
2. CookieExpiredDialog: Thông báo khi Cookie Douyin hết hạn (hoặc lỗi '服务异常，重新刷新拉取数据'),
   hướng dẫn chi tiết cách lấy lại cookie qua tiện ích ATP Cookie và hỗ trợ dán nhanh từ clipboard.
"""

import os
import sys
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtGui import QColor, QFont, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.browser_profile_service import get_installed_browsers_with_profiles
from app.services.cookie_storage_service import save_douyin_cookies


# ====================================================================== #
#  Browser & Profile Selection Dialog                                    #
# ====================================================================== #
class BrowserProfileDialog(QDialog):
    """Hộp thoại chọn trình duyệt và profile trước khi quét."""

    _BG = "#070b13"
    _CARD = "#0f172a"
    _CARD_HOVER = "#1e293b"
    _CARD_BORDER = "#1e293b"
    _CYAN = "#00f0ff"
    _CYAN_HOVER = "#38bdf8"
    _TEXT = "#f8fafc"
    _TEXT_MUTED = "#94a3b8"
    _GREEN = "#10b981"
    _ROSE = "#f43f5e"

    def __init__(self, parent=None, default_browser_id: str = "chrome"):
        super().__init__(parent)
        self.setWindowTitle("🌐 CHỌN TRÌNH DUYỆT & HỒ SƠ QUÉT (PROFILE)")
        self.setMinimumSize(560, 480)
        self.resize(580, 520)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {self._BG};
                color: {self._TEXT};
            }}
            QWidget {{
                color: {self._TEXT};
                font-family: "Segoe UI", "Microsoft YaHei", "Arial", sans-serif;
            }}
            QScrollBar:vertical {{
                background: #0d1321; width: 6px; margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #1e293b; min-height: 20px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self._CYAN};
            }}
        """)

        self.installed_browsers = get_installed_browsers_with_profiles()
        self.selected_browser: Optional[Dict[str, Any]] = None
        self.selected_profile_id: str = "Default"
        self.selected_profile_name: str = "Mặc định"
        self.selected_browser_exe: str = ""
        self.selected_browser_id: str = default_browser_id
        self.selected_browser_name: str = ""

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        # ---- TOP HEADER ----
        header_card = QFrame(self)
        header_card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 10px;
                padding: 4px;
            }}
        """)
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(12, 10, 12, 10)
        h_layout.setSpacing(12)

        icon_lbl = QLabel("🌐")
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {self._CYAN}, stop:1 #3b82f6);
            border-radius: 8px; font-size: 20px; color: white;
        """)
        h_layout.addWidget(icon_lbl)

        t_col = QVBoxLayout()
        t_col.setSpacing(2)
        self.dlg_title = QLabel("CHỌN TRÌNH DUYỆT TRÊN MÁY TÍNH")
        self.dlg_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #ffffff;")
        t_col.addWidget(self.dlg_title)

        self.dlg_sub = QLabel("Chọn trình duyệt bạn dùng để đăng nhập Douyin để đồng bộ dữ liệu tốt nhất:")
        self.dlg_sub.setStyleSheet(f"font-size: 11px; color: {self._TEXT_MUTED};")
        t_col.addWidget(self.dlg_sub)
        h_layout.addLayout(t_col, 1)

        root.addWidget(header_card)

        # ---- STACKED WIDGET (Page 0: Browsers | Page 1: Profiles) ----
        self.stack = QStackedWidget(self)

        # Page 0: Browsers list
        self.page_browsers = QWidget()
        b_layout = QVBoxLayout(self.page_browsers)
        b_layout.setContentsMargins(0, 8, 0, 8)
        b_layout.setSpacing(10)

        if not self.installed_browsers:
            lbl_empty = QLabel("⚠️ Không tìm thấy trình duyệt nhân Chromium (Chrome/Cốc Cốc/Edge) nào trên máy.")
            lbl_empty.setStyleSheet(f"color: {self._ROSE}; font-size: 12px; padding: 20px;")
            lbl_empty.setAlignment(Qt.AlignCenter)
            b_layout.addWidget(lbl_empty)
        else:
            for b in self.installed_browsers:
                btn_card = self._create_browser_card(b)
                b_layout.addWidget(btn_card)

        b_layout.addStretch()
        self.stack.addWidget(self.page_browsers)

        # Page 1: Profiles list
        self.page_profiles = QWidget()
        p_root_layout = QVBoxLayout(self.page_profiles)
        p_root_layout.setContentsMargins(0, 4, 0, 4)
        p_root_layout.setSpacing(10)

        # Top row in Page 1: Back button + title
        p_nav_row = QHBoxLayout()
        btn_back = QPushButton("⬅️ Chọn Trình Duyệt Khác")
        btn_back.setStyleSheet(f"""
            QPushButton {{
                background: #1e293b; border: 1px solid #334155;
                border-radius: 6px; color: #cbd5e1; font-size: 11px; font-weight: 700;
                padding: 6px 12px;
            }}
            QPushButton:hover {{ background: #334155; color: white; }}
        """)
        btn_back.clicked.connect(lambda: self._switch_to_browsers_page())
        p_nav_row.addWidget(btn_back)

        self.lbl_profile_heading = QLabel("Hồ Sơ (Profiles)")
        self.lbl_profile_heading.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {self._CYAN};")
        p_nav_row.addWidget(self.lbl_profile_heading, 1)
        p_root_layout.addLayout(p_nav_row)

        # Profiles Scroll area
        p_scroll = QScrollArea(self)
        p_scroll.setWidgetResizable(True)
        p_scroll.setFrameShape(QFrame.NoFrame)
        p_scroll.setStyleSheet("background: transparent;")

        self.p_scroll_content = QWidget()
        self.p_scroll_layout = QVBoxLayout(self.p_scroll_content)
        self.p_scroll_layout.setContentsMargins(0, 0, 6, 0)
        self.p_scroll_layout.setSpacing(8)
        p_scroll.setWidget(self.p_scroll_content)
        p_root_layout.addWidget(p_scroll, 1)

        self.stack.addWidget(self.page_profiles)

        root.addWidget(self.stack, 1)

        # ---- BOTTOM BAR ----
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 4, 0, 0)

        self.chk_remember = QCheckBox("Ghi nhớ lựa chọn này (Lần sau quét sẽ chạy thẳng)")
        self.chk_remember.setChecked(False)
        self.chk_remember.setStyleSheet(f"""
            QCheckBox {{
                color: {self._TEXT_MUTED}; font-size: 11px;
            }}
            QCheckBox::indicator {{
                width: 16px; height: 16px; border-radius: 4px;
                border: 1px solid #334155; background: #0b1120;
            }}
            QCheckBox::indicator:checked {{
                background: {self._CYAN}; border-color: {self._CYAN};
            }}
        """)
        bottom_row.addWidget(self.chk_remember, 1)

        btn_cancel = QPushButton("Hủy Bỏ")
        btn_cancel.setFixedSize(90, 34)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background: #1e293b; border: 1px solid #334155;
                border-radius: 6px; color: #cbd5e1; font-size: 11px; font-weight: 700;
            }
            QPushButton:hover { background: #334155; color: white; }
        """)
        btn_cancel.clicked.connect(self.reject)
        bottom_row.addWidget(btn_cancel)

        root.addLayout(bottom_row)

    def _create_browser_card(self, b: Dict[str, Any]) -> QFrame:
        card = QFrame(self)
        card.setCursor(QCursor(Qt.PointingHandCursor))
        card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 8px;
            }}
            QFrame:hover {{
                background: {self._CARD_HOVER};
                border: 1px solid {self._CYAN};
            }}
        """)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        # Icon
        icon_str = "🌐"
        if b["id"] == "coccoc":
            icon_str = "🟢"
        elif b["id"] == "edge":
            icon_str = "🔷"
        elif b["id"] == "brave":
            icon_str = "🦁"

        icon_box = QLabel(icon_str)
        icon_box.setFixedSize(36, 36)
        icon_box.setAlignment(Qt.AlignCenter)
        icon_box.setStyleSheet("background: #090e17; border-radius: 6px; font-size: 18px;")
        lay.addWidget(icon_box)

        col = QVBoxLayout()
        col.setSpacing(2)
        name_lbl = QLabel(b["name"])
        name_lbl.setStyleSheet("font-size: 13px; font-weight: 800; color: #ffffff;")
        col.addWidget(name_lbl)

        p_cnt = len(b.get("profiles", []))
        if p_cnt > 1:
            names_preview = ", ".join([p["name"] for p in b["profiles"][:3]])
            if p_cnt > 3:
                names_preview += f" (+{p_cnt - 3} hồ sơ nữa)"
            info_text = f"📂 Có {p_cnt} hồ sơ ({names_preview})"
            action_btn_text = f"Chọn Hồ Sơ ({p_cnt}) ➔"
            action_btn_color = self._CYAN
        elif p_cnt == 1:
            p_first = b["profiles"][0]
            info_text = f"📂 1 Hồ sơ: {p_first['name']}" + (f" ({p_first['email']})" if p_first.get('email') else "")
            action_btn_text = "⚡ Quét Ngay ➔"
            action_btn_color = self._GREEN
        else:
            info_text = "⚡ Hồ sơ độc lập"
            action_btn_text = "⚡ Quét Ngay ➔"
            action_btn_color = self._GREEN

        sub_lbl = QLabel(info_text)
        sub_lbl.setStyleSheet(f"font-size: 11px; color: {self._TEXT_MUTED};")
        col.addWidget(sub_lbl)
        lay.addLayout(col, 1)

        # Action tag
        tag_btn = QPushButton(action_btn_text)
        tag_btn.setCursor(QCursor(Qt.PointingHandCursor))
        tag_btn.setStyleSheet(f"""
            QPushButton {{
                background: #090e17; border: 1px solid {action_btn_color};
                border-radius: 6px; color: {action_btn_color}; font-size: 11px; font-weight: 700;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background: {action_btn_color}; color: #000000;
            }}
        """)
        tag_btn.clicked.connect(lambda: self._on_browser_clicked(b))
        lay.addWidget(tag_btn)

        # Make entire card clickable
        card.mousePressEvent = lambda e: self._on_browser_clicked(b)

        return card

    def _on_browser_clicked(self, b: Dict[str, Any]):
        self.selected_browser = b
        self.selected_browser_id = b["id"]
        self.selected_browser_name = b["name"]
        self.selected_browser_exe = b["exe_path"]

        profiles = b.get("profiles", [])

        # "nếu trình duyệt nào có profile thì cho người đó chọn profile , còn k thì chạy thẳng vào"
        if len(profiles) > 1:
            # Switch to Profile selection page
            self._populate_profiles_page(b)
            self.stack.setCurrentIndex(1)
            self.dlg_title.setText(f"CHỌN HỒ SƠ ({b['name'].upper()})")
            self.dlg_sub.setText("Bấm vào hồ sơ bạn đã đăng nhập tài khoản Douyin để bắt đầu quét:")
        else:
            # Only 1 profile or 0 profiles: "chạy thẳng vào"
            if profiles:
                self.selected_profile_id = profiles[0]["id"]
                self.selected_profile_name = profiles[0]["name"]
            else:
                self.selected_profile_id = "Default"
                self.selected_profile_name = "Mặc định"
            self.accept()

    def _populate_profiles_page(self, b: Dict[str, Any]):
        # Clear existing items
        while self.p_scroll_layout.count():
            item = self.p_scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.lbl_profile_heading.setText(f"Trình duyệt {b['name']} có {len(b['profiles'])} hồ sơ:")

        for p in b.get("profiles", []):
            card = self._create_profile_card(b, p)
            self.p_scroll_layout.addWidget(card)

        # Add an option for clean session
        clean_card = self._create_clean_session_card(b)
        self.p_scroll_layout.addWidget(clean_card)
        self.p_scroll_layout.addStretch()

    def _create_profile_card(self, b: Dict[str, Any], p: Dict[str, Any]) -> QFrame:
        card = QFrame(self)
        card.setCursor(QCursor(Qt.PointingHandCursor))
        card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid {self._CARD_BORDER};
                border-radius: 8px;
            }}
            QFrame:hover {{
                background: {self._CARD_HOVER};
                border: 1px solid {self._CYAN};
            }}
        """)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        icon_box = QLabel("👤")
        icon_box.setFixedSize(36, 36)
        icon_box.setAlignment(Qt.AlignCenter)
        icon_box.setStyleSheet("background: #090e17; border-radius: 18px; font-size: 16px;")
        lay.addWidget(icon_box)

        col = QVBoxLayout()
        col.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_lbl = QLabel(p["name"])
        name_lbl.setStyleSheet("font-size: 13px; font-weight: 800; color: #ffffff;")
        name_row.addWidget(name_lbl)

        if p["id"] == "Default":
            badge_def = QLabel("Default")
            badge_def.setStyleSheet(f"background: #1e3a5f; color: {self._CYAN}; font-size: 9px; padding: 1px 5px; border-radius: 3px;")
            name_row.addWidget(badge_def)
        name_row.addStretch()
        col.addLayout(name_row)

        email = p.get("email") or p["id"]
        sub_lbl = QLabel(email)
        sub_lbl.setStyleSheet(f"font-size: 11px; color: {self._TEXT_MUTED};")
        col.addWidget(sub_lbl)
        lay.addLayout(col, 1)

        btn_select = QPushButton("⚡ Chọn & Quét")
        btn_select.setCursor(QCursor(Qt.PointingHandCursor))
        btn_select.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._CYAN}, stop:1 #0284c7);
                border: none; border-radius: 6px; color: white;
                font-size: 11px; font-weight: 800; padding: 6px 14px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._CYAN_HOVER}, stop:1 #0369a1);
            }}
        """)
        btn_select.clicked.connect(lambda: self._on_profile_selected(p))
        lay.addWidget(btn_select)

        card.mousePressEvent = lambda e: self._on_profile_selected(p)
        return card

    def _create_clean_session_card(self, b: Dict[str, Any]) -> QFrame:
        card = QFrame(self)
        card.setCursor(QCursor(Qt.PointingHandCursor))
        card.setStyleSheet(f"""
            QFrame {{
                background: #090e17;
                border: 1px dashed #334155;
                border-radius: 8px;
            }}
            QFrame:hover {{
                background: {self._CARD};
                border-color: {self._CYAN};
            }}
        """)

        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        icon_box = QLabel("✨")
        icon_box.setFixedSize(36, 36)
        icon_box.setAlignment(Qt.AlignCenter)
        icon_box.setStyleSheet("background: #090e17; border-radius: 6px; font-size: 16px;")
        lay.addWidget(icon_box)

        col = QVBoxLayout()
        col.setSpacing(2)
        name_lbl = QLabel("Phiên Mới Độc Lập (Không dùng profile nào)")
        name_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #cbd5e1;")
        col.addWidget(name_lbl)
        sub_lbl = QLabel("Khởi động phiên sạch, chỉ sử dụng chuỗi ATP Cookie đã dán")
        sub_lbl.setStyleSheet(f"font-size: 10px; color: {self._TEXT_MUTED};")
        col.addWidget(sub_lbl)
        lay.addLayout(col, 1)

        btn_select = QPushButton("Chọn")
        btn_select.setCursor(QCursor(Qt.PointingHandCursor))
        btn_select.setStyleSheet(f"""
            QPushButton {{
                background: #1e293b; border: 1px solid #334155;
                border-radius: 6px; color: #cbd5e1; font-size: 11px; font-weight: 700;
                padding: 6px 14px;
            }}
            QPushButton:hover {{ background: #334155; color: white; }}
        """)
        btn_select.clicked.connect(lambda: self._on_profile_selected({"id": "new_session", "name": "Phiên Độc Lập"}))
        lay.addWidget(btn_select)

        card.mousePressEvent = lambda e: self._on_profile_selected({"id": "new_session", "name": "Phiên Độc Lập"})
        return card

    def _on_profile_selected(self, p: Dict[str, Any]):
        self.selected_profile_id = p["id"]
        self.selected_profile_name = p["name"]
        self.accept()

    def _switch_to_browsers_page(self):
        self.stack.setCurrentIndex(0)
        self.dlg_title.setText("CHỌN TRÌNH DUYỆT TRÊN MÁY TÍNH")
        self.dlg_sub.setText("Chọn trình duyệt bạn dùng để đăng nhập Douyin để đồng bộ dữ liệu tốt nhất:")

    def get_selected(self) -> Dict[str, Any]:
        return {
            "browser_id": self.selected_browser_id,
            "browser_name": self.selected_browser_name,
            "browser_exe": self.selected_browser_exe,
            "profile_id": self.selected_profile_id,
            "profile_name": self.selected_profile_name,
            "remember": self.chk_remember.isChecked(),
        }


# ====================================================================== #
#  Cookie Expired Warning Dialog                                         #
# ====================================================================== #
class CookieExpiredDialog(QDialog):
    """Hộp thoại cảnh báo Cookie Douyin hết hạn và hướng dẫn lấy lại cookie."""

    _BG = "#070b13"
    _CARD = "#0f172a"
    _CARD_BORDER = "#ef4444"
    _CYAN = "#00f0ff"
    _CYAN_HOVER = "#38bdf8"
    _ROSE = "#f43f5e"
    _ROSE_HOVER = "#e11d48"
    _TEXT = "#f8fafc"
    _TEXT_MUTED = "#94a3b8"

    def __init__(self, parent=None, browser_name: str = "Google Chrome", profile_name: str = ""):
        super().__init__(parent)
        self.browser_name = browser_name
        self.profile_name = profile_name
        self.action_result = "dismiss"  # 'paste_retry' | 'goto_cookie' | 'dismiss'

        self.setWindowTitle("⚠️ COOKIE DOUYIN ĐÃ HẾT HẠN")
        self.setMinimumSize(540, 400)
        self.resize(560, 420)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {self._BG};
                color: {self._TEXT};
            }}
            QWidget {{
                color: {self._TEXT};
                font-family: "Segoe UI", "Microsoft YaHei", "Arial", sans-serif;
            }}
        """)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        # Header with warning badge
        header_card = QFrame(self)
        header_card.setStyleSheet(f"""
            QFrame {{
                background: #1c0a0e;
                border: 1px solid #7f1d1d;
                border-radius: 10px;
                padding: 4px;
            }}
        """)
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(14, 12, 14, 12)
        h_layout.setSpacing(12)

        icon_lbl = QLabel("⚠️")
        icon_lbl.setFixedSize(44, 44)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("""
            background: #991b1b;
            border-radius: 10px; font-size: 24px; color: white;
        """)
        h_layout.addWidget(icon_lbl)

        t_col = QVBoxLayout()
        t_col.setSpacing(3)
        t_title = QLabel("COOKIE DOUYIN ĐÃ HẾT HẠN HOẶC PHIÊN BỊ LỖI")
        t_title.setStyleSheet("font-size: 15px; font-weight: 900; color: #fecaca;")
        t_col.addWidget(t_title)

        t_sub = QLabel("Douyin phản hồi: '服务异常，重新刷新拉取数据' (Dịch vụ bất thường)")
        t_sub.setStyleSheet("font-size: 11px; color: #f87171;")
        t_col.addWidget(t_sub)
        h_layout.addLayout(t_col, 1)

        root.addWidget(header_card)

        # Content card with steps
        body_card = QFrame(self)
        body_card.setStyleSheet(f"""
            QFrame {{
                background: {self._CARD};
                border: 1px solid #1e293b;
                border-radius: 8px;
            }}
        """)
        b_lay = QVBoxLayout(body_card)
        b_lay.setContentsMargins(16, 14, 16, 14)
        b_lay.setSpacing(10)

        lbl_desc = QLabel(
            f"Phiên đăng nhập trên <b>{self.browser_name}</b>"
            + (f" (Hồ sơ: <b>{self.profile_name}</b>)" if self.profile_name else "")
            + " đã hết hạn hoặc chuỗi cookie đã cũ. Douyin yêu cầu làm mới phiên để xem danh sách video."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 12px; color: #e2e8f0; line-height: 1.4;")
        b_lay.addWidget(lbl_desc)

        lbl_guide_title = QLabel("📌 CÁCH LẤY LẠI COOKIE MỚI TRONG 30 GIÂY:")
        lbl_guide_title.setStyleSheet(f"font-size: 12px; font-weight: 800; color: {self._CYAN};")
        b_lay.addWidget(lbl_guide_title)

        steps = [
            f"1. Mở trình duyệt <b>{self.browser_name}</b> và truy cập <b>https://www.douyin.com</b>.",
            "2. Đảm bảo tài khoản Douyin của bạn đang ở trạng thái đã đăng nhập.",
            "3. Bấm vào icon tiện ích <b>ATP Cookie</b> trên thanh công cụ và nhấn <b>Copy Cookie</b>.",
            "4. Quay lại đây và bấm nút <b>'📋 Dán Cookie & Quét Lại'</b> bên dưới.",
        ]
        for s in steps:
            s_lbl = QLabel(s)
            s_lbl.setWordWrap(True)
            s_lbl.setStyleSheet("font-size: 11px; color: #cbd5e1; margin-left: 6px;")
            b_lay.addWidget(s_lbl)

        root.addWidget(body_card, 1)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_paste_retry = QPushButton("📋 Dán Cookie & Quét Lại")
        btn_paste_retry.setFixedHeight(40)
        btn_paste_retry.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._CYAN}, stop:1 #0284c7);
                border: none; border-radius: 6px; color: white;
                font-size: 12px; font-weight: 800; padding: 0 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {self._CYAN_HOVER}, stop:1 #0369a1);
            }}
        """)
        btn_paste_retry.clicked.connect(self._on_paste_retry)
        btn_row.addWidget(btn_retry := btn_paste_retry, 2)

        btn_goto_input = QPushButton("✏️ Nhập Bằng Tay")
        btn_goto_input.setFixedHeight(40)
        btn_goto_input.setStyleSheet("""
            QPushButton {{
                background: #1e293b; border: 1px solid #334155;
                border-radius: 6px; color: #cbd5e1; font-size: 11px; font-weight: 700;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: #334155; color: white; }}
        """)
        btn_goto_input.clicked.connect(self._on_goto_input)
        btn_row.addWidget(btn_goto_input, 1)

        btn_close = QPushButton("Đóng")
        btn_close.setFixedHeight(40)
        btn_close.setStyleSheet("""
            QPushButton {{
                background: #1e293b; border: 1px solid #334155;
                border-radius: 6px; color: #cbd5e1; font-size: 11px; font-weight: 700;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: #334155; color: white; }}
        """)
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close, 1)

        root.addLayout(btn_row)

    def _on_paste_retry(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if not text:
            QMessageBox.warning(self, "Bộ Nhớ Tạm Rỗng", "Clipboard hiện không có nội dung!\nVui lòng copy cookie từ tiện ích ATP Cookie trước.")
            return

        res = save_douyin_cookies(text)
        if not res.get("success"):
            QMessageBox.warning(
                self,
                "Không Phải Cookie Hợp Lệ",
                f"Chuỗi trong clipboard không phải định dạng cookie ATP hợp lệ:\n{res.get('error')}\n\nVui lòng copy lại từ ATP Cookie."
            )
            return

        self.action_result = "paste_retry"
        self.accept()

    def _on_goto_input(self):
        self.action_result = "goto_cookie"
        self.accept()
