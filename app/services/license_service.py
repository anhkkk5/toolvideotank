"""TankVideo SaaS License and Authentication Service.

Handles machine-id fingerprinting, license key generation & validation,
offline digital signature verification, and client-server synchronization.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import subprocess
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

# Khóa bí mật nội bộ của TankVideo để chống giả mạo key (Secret Salt)
_TANK_SECRET_SALT = "TANKVIDEO_SAAS_AUTH_KEY_2026_SECRET_983742"


def get_hardware_machine_id() -> str:
    """Tạo mã định danh phần cứng (Hardware ID / Machine ID) duy nhất cho mỗi máy tính.
    
    Kết hợp UUID của Mainboard, CPU và Tên máy để đảm bảo:
    - 1 Key chỉ kích hoạt được trên đúng 1 máy tính.
    - Không thể copy file license sang máy khác để dùng lậu.
    """
    raw_parts = []
    
    # 1. Lấy UUID của Mainboard trên Windows
    if platform.system() == "Windows":
        try:
            cmd = "wmic csproduct get uuid"
            out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            lines = [line.strip() for line in out.splitlines() if line.strip()]
            if len(lines) > 1 and lines[1]:
                raw_parts.append(lines[1])
        except Exception:
            pass

        # Dự phòng bằng Windows ProductId / MachineGuid từ Registry
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            if guid:
                raw_parts.append(str(guid).strip())
        except Exception:
            pass

    # 2. Lấy thông tin Node / Processor
    raw_parts.append(platform.node())
    raw_parts.append(platform.processor())
    raw_parts.append(platform.machine())

    combined = "##".join(raw_parts)
    digest = hashlib.sha256(combined.encode("utf-8")).hexdigest().upper()
    
    # Định dạng thành chuỗi đẹp: TANK-XXXX-XXXX-XXXX
    return f"TANK-{digest[:4]}-{digest[4:8]}-{digest[8:12]}"


# Cấu hình mặc định Supabase Cloud
DEFAULT_SUPABASE_URL = "https://mgtrrinjjkpnjxkjrtyh.supabase.co"
DEFAULT_SUPABASE_KEY = "sb_publishable_VMs5RD9UEoi8PUhHpX6VyQ_hbua75qa"


class LicenseService:
    """Service trung tâm quản lý bản quyền TankVideo."""

    def __init__(self, workspace_root: str | None = None):
        self.workspace_root = workspace_root or os.getcwd()
        self.license_file = os.path.join(self.workspace_root, "license.tank")

        # Thư mục lưu bản quyền vĩnh viễn trên AppData của Windows
        app_data = os.environ.get("APPDATA")
        if app_data:
            self.global_dir = os.path.join(app_data, "TankVideo")
        else:
            self.global_dir = os.path.join(os.path.expanduser("~"), ".tankvideo")
        try:
            os.makedirs(self.global_dir, exist_ok=True)
        except Exception:
            pass
        self.global_license_file = os.path.join(self.global_dir, "license.tank")

        # Đồng bộ license nếu bản dựng mới bị xóa mất file cục bộ
        if not os.path.isfile(self.license_file) and os.path.isfile(self.global_license_file):
            try:
                import shutil
                shutil.copyfile(self.global_license_file, self.license_file)
            except Exception:
                pass
        elif os.path.isfile(self.license_file) and not os.path.isfile(self.global_license_file):
            try:
                import shutil
                shutil.copyfile(self.license_file, self.global_license_file)
            except Exception:
                pass

        self.machine_id = get_hardware_machine_id()
        self.supabase_url = os.getenv("SUPABASE_URL", DEFAULT_SUPABASE_URL).rstrip("/")
        self.supabase_key = os.getenv("SUPABASE_KEY", DEFAULT_SUPABASE_KEY).strip()

    def _call_supabase(
        self, endpoint: str, method: str = "GET", payload: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        """Gọi REST API Supabase an toàn qua urllib chuẩn của Python."""
        import urllib.request
        import urllib.error
        import ssl

        url = f"{self.supabase_url}/rest/v1/{endpoint.lstrip('/')}"
        headers = {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation" if method == "PATCH" else "return=minimal",
        }

        data_bytes = None
        if payload is not None:
            data_bytes = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        ctx = ssl.create_default_context()

        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                status_code = resp.status
                body = resp.read().decode("utf-8")
                try:
                    res_json = json.loads(body) if body else {}
                except Exception:
                    res_json = {}
                return status_code, res_json
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            return he.code, {"error": err_body or str(he)}
        except Exception as exc:
            return 0, {"error": f"Lỗi kết nối máy chủ Supabase: {exc}"}

    def login_supabase(self, email: str, password: str) -> tuple[bool, str]:
        """Xác thực đăng nhập tài khoản trực tiếp qua Supabase Cloud."""
        clean_email = str(email or "").strip().lower()
        clean_pwd = str(password or "").strip()

        if not clean_email or "@" not in clean_email:
            return False, "Vui lòng nhập địa chỉ Email hợp lệ."
        if not clean_pwd:
            return False, "Vui lòng nhập mật khẩu tài khoản."

        # 1. Truy vấn tài khoản từ bảng tank_licenses
        status_code, records = self._call_supabase(f"tank_licenses?email=eq.{urllib.parse.quote(clean_email)}&select=*")
        if status_code != 200 or not isinstance(records, list):
            err_msg = records.get("error", "Lỗi mạng hoặc không thể kết nối tới Supabase.") if isinstance(records, dict) else "Lỗi kết nối."
            return False, f"Không thể kết nối máy chủ xác thực: {err_msg}"

        if not records:
            return False, "Tài khoản không tồn tại trên hệ thống. Vui lòng liên hệ Admin để đăng ký thuê tool!"

        user = records[0]

        # 2. Kiểm tra mật khẩu (Hỗ trợ cả mã hash SHA256 lẫn mật khẩu chữ thường do Admin gõ)
        pwd_hash = hashlib.sha256(clean_pwd.encode("utf-8")).hexdigest()
        db_pwd = str(user.get("password_hash", "") or "").strip()
        if db_pwd != pwd_hash and db_pwd != clean_pwd:
            return False, "Mật khẩu không chính xác. Vui lòng thử lại!"

        # 3. Kiểm tra trạng thái tài khoản
        if user.get("status") == "blocked":
            return False, "Tài khoản đã bị khóa. Lý do: Phát hiện vi phạm hoặc bị Admin tạm ngưng. Liên hệ Admin để được hỗ trợ."

        # 4. Kiểm tra ngày hết hạn
        exp_raw = str(user.get("expires_at", "") or "")
        now_ts = int(time.time())
        exp_ts = 0

        try:
            # Parse ISO timestamp từ Supabase (hỗ trợ cả có múi giờ Z hoặc +00:00)
            clean_iso = exp_raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_iso)
            exp_ts = int(dt.timestamp())
        except Exception:
            exp_ts = now_ts + 86400 * 30

        if now_ts > exp_ts:
            exp_date_str = datetime.fromtimestamp(exp_ts).strftime("%d/%m/%Y")
            return False, f"Gói thuê của tài khoản đã hết hạn vào ngày {exp_date_str}. Vui lòng liên hệ Admin để gia hạn!"

        days_left = max(0, int((exp_ts - now_ts) / 86400))
        exp_date_str = datetime.fromtimestamp(exp_ts).strftime("%d/%m/%Y %H:%M")

        # 5. Kiểm tra ràng buộc thiết bị (Machine ID)
        bound_mid = str(user.get("machine_id", "") or "").strip().upper()
        current_mid = self.machine_id.strip().upper()

        if not bound_mid:
            # Lần đầu đăng nhập: Tự động khóa chặt vào Machine ID của máy này
            patch_code, _ = self._call_supabase(
                f"tank_licenses?id=eq.{user.get('id')}",
                method="PATCH",
                payload={"machine_id": current_mid},
            )
            if patch_code not in (200, 204):
                print(f"[License] Warning: Không thể cập nhật machine_id lên Supabase (status {patch_code})")
        elif bound_mid != current_mid:
            return False, (
                f"Tài khoản đã bị khóa. Lý do: Phát hiện đăng nhập từ thiết bị khác [{bound_mid}].\n"
                f"Thiết bị hiện tại: [{current_mid}].\n"
                f"Vui lòng liên hệ Admin để xác minh đổi máy mới!"
            )

        # 6. Lưu trạng thái bản quyền cục bộ vào file license.tank
        plan = str(user.get("plan", "VIP") or "VIP")
        local_record = {
            "email": clean_email,
            "plan": plan,
            "machine_id": current_mid,
            "expires_at": exp_ts,
            "expires_str": exp_date_str,
            "days_left": days_left,
            "server_synced": True,
            "activated_at": now_ts,
            "hash": hashlib.sha256(f"{clean_email}:{plan}:{current_mid}:{exp_ts}:{_TANK_SECRET_SALT}".encode()).hexdigest(),
        }

        for target_path in (self.license_file, self.global_license_file):
            try:
                os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(local_record, f, indent=2)
            except Exception as exc:
                print(f"[License] Lưu license lỗi {target_path}: {exc}")

        return True, f"Đăng nhập thành công! Gói {plan}, thời hạn còn {days_left} ngày (đến {exp_date_str})."

    @classmethod
    def generate_license_key(
        cls,
        email: str,
        days: int = 30,
        machine_id: str = "",
        plan: str = "VIP",
    ) -> str:
        """Dành cho Admin: Sinh mã bản quyền an toàn có chữ ký mật mã."""
        clean_email = str(email or "").strip().lower()
        now_ts = int(time.time())
        exp_ts = now_ts + (days * 86400)
        
        payload = {
            "email": clean_email,
            "mid": machine_id.strip().upper(),
            "days": days,
            "created": now_ts,
            "expires": exp_ts,
            "plan": plan.upper(),
        }
        raw_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        # Tạo chữ ký HMAC bằng Secret Salt
        signature = hashlib.sha256(f"{raw_json}::{_TANK_SECRET_SALT}".encode("utf-8")).hexdigest()[:8].upper()
        
        # Mã hóa base64URL để khách hàng dễ copy
        b64 = base64.b32encode(raw_json.encode("utf-8")).decode("ascii").rstrip("=")
        return f"TANK-{signature}-{b64}"

    def verify_key(self, key_str: str) -> dict[str, Any]:
        """Xác thực mã bản quyền xem có hợp lệ, đúng mã máy và còn hạn không."""
        clean_key = str(key_str or "").strip()
        if not clean_key.startswith("TANK-"):
            return {"valid": False, "error": "Mã kích hoạt không đúng định dạng TankVideo (cần bắt đầu bằng TANK-)."}

        parts = clean_key.split("-", 2)
        if len(parts) < 3:
            return {"valid": False, "error": "Mã kích hoạt không hợp lệ hoặc bị thiếu ký tự."}

        expected_sig = parts[1].upper()
        b64_payload = parts[2]
        
        # Bù padding base32
        pad_len = (8 - (len(b64_payload) % 8)) % 8
        b64_padded = b64_payload + ("=" * pad_len)

        try:
            raw_bytes = base64.b32decode(b64_padded)
            payload = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return {"valid": False, "error": "Mã bản quyền bị sai cú pháp hoặc đã bị chỉnh sửa."}

        # 1. Kiểm tra tính toàn vẹn (Signature)
        raw_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        actual_sig = hashlib.sha256(f"{raw_json}::{_TANK_SECRET_SALT}".encode("utf-8")).hexdigest()[:8].upper()
        if actual_sig != expected_sig:
            return {"valid": False, "error": "Chữ ký bản quyền không hợp lệ (Key giả mạo)."}

        # 2. Kiểm tra ràng buộc mã máy (nếu có khóa theo máy)
        bound_mid = payload.get("mid", "").strip().upper()
        if bound_mid and bound_mid != self.machine_id.upper():
            return {
                "valid": False,
                "error": f"Mã bản quyền này chỉ dùng được cho máy [{bound_mid}], không khớp với máy hiện tại [{self.machine_id}].",
            }

        # 3. Kiểm tra hạn sử dụng
        expires_ts = payload.get("expires", 0)
        now_ts = int(time.time())
        if expires_ts > 0 and now_ts > expires_ts:
            exp_date_str = datetime.fromtimestamp(expires_ts).strftime("%d/%m/%Y")
            return {"valid": False, "error": f"Bản quyền này đã hết hạn vào ngày {exp_date_str}."}

        days_left = max(0, int((expires_ts - now_ts) / 86400))
        exp_date_str = datetime.fromtimestamp(expires_ts).strftime("%d/%m/%Y %H:%M")

        return {
            "valid": True,
            "email": payload.get("email", ""),
            "plan": payload.get("plan", "VIP"),
            "days_left": days_left,
            "expires_at": exp_date_str,
            "expires_ts": expires_ts,
            "bound_mid": bound_mid,
            "payload": payload,
        }

    def activate(self, email: str, password: str, key_str: str) -> tuple[bool, str]:
        """Kích hoạt bản quyền cho người dùng và lưu trạng thái vào file bản quyền cục bộ."""
        clean_email = str(email or "").strip().lower()
        clean_key = str(key_str or "").strip()

        if not clean_email or "@" not in clean_email:
            return False, "Vui lòng nhập địa chỉ Email hợp lệ."
        if not password or len(password) < 4:
            return False, "Vui lòng nhập mật khẩu tài khoản (tối thiểu 4 ký tự)."
        if not clean_key:
            return False, "Vui lòng nhập mã kích hoạt bản quyền."

        # Xác thực tính hợp lệ của Key
        verify_res = self.verify_key(clean_key)
        if not verify_res["valid"]:
            return False, verify_res["error"]

        # Nếu key có gắn email, kiểm tra xem có khớp không
        key_email = verify_res.get("email", "").strip().lower()
        if key_email and key_email != clean_email:
            return False, f"Key này được cấp riêng cho email [{key_email}], không khớp với email đăng nhập."

        # Lưu bản quyền vào file mã hóa cục bộ
        record = {
            "email": clean_email,
            "key": clean_key,
            "machine_id": self.machine_id,
            "activated_at": int(time.time()),
            "expires_at": verify_res["expires_ts"],
            "plan": verify_res["plan"],
            "hash": hashlib.sha256(f"{clean_email}:{clean_key}:{self.machine_id}:{_TANK_SECRET_SALT}".encode()).hexdigest(),
        }

        for target_path in (self.license_file, self.global_license_file):
            try:
                os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(record, f, indent=2)
            except Exception as exc:
                pass
        return True, f"Kích hoạt thành công gói {verify_res['plan']}! Hạn dùng đến: {verify_res['expires_at']}."

    def get_license_status(self) -> dict[str, Any]:
        """Kiểm tra bản quyền hiện tại trên máy xem có hợp lệ không."""
        data = None
        for candidate in (self.license_file, self.global_license_file):
            if candidate and os.path.isfile(candidate):
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        candidate_data = json.load(f)
                        if isinstance(candidate_data, dict) and ("hash" in candidate_data or "key" in candidate_data):
                            data = candidate_data
                            break
                except Exception:
                    pass

        if not data:
            return {
                "licensed": False,
                "status": "unlicensed",
                "message": "Chưa kích hoạt bản quyền",
                "machine_id": self.machine_id,
                "days_left": 0,
            }

        email = data.get("email", "")
        plan = data.get("plan", "VIP")
        saved_hash = data.get("hash", "")
        now_ts = int(time.time())

        # 1. Trường hợp kích hoạt trực tiếp từ Supabase Cloud
        if data.get("server_synced"):
            exp_ts = int(data.get("expires_at", 0))
            expected_hash = hashlib.sha256(f"{email}:{plan}:{self.machine_id}:{exp_ts}:{_TANK_SECRET_SALT}".encode()).hexdigest()
            if saved_hash != expected_hash:
                return {
                    "licensed": False,
                    "status": "invalid_machine",
                    "message": "Bản quyền không khớp với máy này hoặc đã bị chỉnh sửa.",
                    "machine_id": self.machine_id,
                    "days_left": 0,
                }
            if now_ts > exp_ts:
                exp_date_str = datetime.fromtimestamp(exp_ts).strftime("%d/%m/%Y")
                return {
                    "licensed": False,
                    "status": "expired",
                    "message": f"Bản quyền đã hết hạn vào ngày {exp_date_str}.",
                    "machine_id": self.machine_id,
                    "days_left": 0,
                    "email": email,
                }
            days_left = max(0, int((exp_ts - now_ts) / 86400))
            return {
                "licensed": True,
                "status": "active",
                "message": "Bản quyền hợp lệ (Cloud Supabase)",
                "machine_id": self.machine_id,
                "email": email,
                "plan": plan,
                "days_left": days_left,
                "expires_at": data.get("expires_str", datetime.fromtimestamp(exp_ts).strftime("%d/%m/%Y %H:%M")),
            }

        # 2. Trường hợp kích hoạt bằng Offline Key
        key = data.get("key", "")
        expected_hash = hashlib.sha256(f"{email}:{key}:{self.machine_id}:{_TANK_SECRET_SALT}".encode()).hexdigest()

        if saved_hash != expected_hash:
            return {
                "licensed": False,
                "status": "invalid_machine",
                "message": "Bản quyền không khớp với máy này (hoặc đã bị sửa đổi)",
                "machine_id": self.machine_id,
                "days_left": 0,
            }

        verify_res = self.verify_key(key)
        if not verify_res["valid"]:
            return {
                "licensed": False,
                "status": "expired",
                "message": verify_res["error"],
                "machine_id": self.machine_id,
                "days_left": 0,
                "email": email,
            }

        return {
            "licensed": True,
            "status": "active",
            "message": "Bản quyền hợp lệ",
            "machine_id": self.machine_id,
            "email": email,
            "plan": verify_res["plan"],
            "days_left": verify_res["days_left"],
            "expires_at": verify_res["expires_at"],
        }

    def is_license_valid(self) -> tuple[bool, str]:
        st = self.get_license_status()
        return st.get("licensed", False), st.get("message", "")

    def logout(self) -> None:
        """Đăng xuất / Xóa bản quyền trên máy này."""
        for target_path in (self.license_file, self.global_license_file):
            if os.path.isfile(target_path):
                try:
                    os.remove(target_path)
                except Exception:
                    pass

