"""Cookie Storage & Parser Service for TankVideo / CapCap.

Supports:
- ATP Cookie format: cookie_string|user_agent
- Standard Cookie header: k1=v1; k2=v2; ...
- JSON format (e.g. from Cookie-Editor extension)
- Netscape format (.txt)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PySide6.QtCore import QSettings
    _HAS_QT = True
except ImportError:
    QSettings = None
    _HAS_QT = False

SETTINGS_GROUP = "VideoDownloader"
COOKIE_KEY = "douyin_cookie_raw"
COOKIE_TIME_KEY = "douyin_cookie_updated_at"


def _get_setting(key: str, default: str = "") -> str:
    val = ""
    if _HAS_QT and QSettings is not None:
        try:
            val = str(QSettings("TankVideo", SETTINGS_GROUP).value(key, "") or "").strip()
        except Exception:
            val = ""
    if val:
        return val
    # JSON fallback
    p = os.path.join(get_cookie_cache_dir(), "settings.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return str(json.load(f).get(key, default) or "").strip()
        except Exception:
            pass
    return default


def _set_setting(key: str, val: str):
    if _HAS_QT and QSettings is not None:
        try:
            QSettings("TankVideo", SETTINGS_GROUP).setValue(key, val)
        except Exception:
            pass
    p = os.path.join(get_cookie_cache_dir(), "settings.json")
    data = {}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data[key] = val
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _remove_setting(key: str):
    if _HAS_QT and QSettings is not None:
        try:
            QSettings("TankVideo", SETTINGS_GROUP).remove(key)
        except Exception:
            pass
    p = os.path.join(get_cookie_cache_dir(), "settings.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.pop(key, None)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def get_cookie_cache_dir() -> str:
    """Return persistent cookie directory in user's home or app data."""
    home = os.path.expanduser("~")
    cookie_dir = os.path.join(home, ".capcap", "cookies")
    os.makedirs(cookie_dir, exist_ok=True)
    return cookie_dir


def parse_cookie_input(raw_input: str) -> Tuple[Dict[str, str], str]:
    """Parse raw cookie string from user input into (cookie_dict, user_agent).

    Supports:
    1. ATP Cookie: 'cookie_str|user_agent'
    2. JSON list of cookie dicts: [{'name': '...', 'value': '...'}, ...]
    3. JSON dict: {'cookie_name': 'cookie_value', ...}
    4. Key-Value semicolon separated: 'k1=v1; k2=v2;'
    """
    raw = (raw_input or "").strip()
    if not raw:
        return {}, ""

    user_agent = ""

    # Check ATP Cookie format (split by '|' at the end)
    if "|" in raw:
        parts = raw.split("|", 1)
        cookie_part = parts[0].strip()
        ua_part = parts[1].strip()
        if ua_part.startswith("Mozilla/"):
            user_agent = ua_part
            raw = cookie_part

    # Try JSON parsing
    if (raw.startswith("[") and raw.endswith("]")) or (raw.startswith("{") and raw.endswith("}")):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                cookie_dict = {}
                for item in data:
                    if isinstance(item, dict) and "name" in item and "value" in item:
                        cookie_dict[item["name"]] = str(item["value"])
                if cookie_dict:
                    return cookie_dict, user_agent
            elif isinstance(data, dict):
                cookie_dict = {str(k): str(v) for k, v in data.items() if not str(k).startswith("@")}
                if cookie_dict:
                    return cookie_dict, user_agent
        except Exception:
            pass

    # Semicolon separated parsing
    cookie_dict = {}
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        k = k.strip()
        v = v.strip()
        # Clean leading '=' if any (ATP format sometimes has '=douyin.com;...')
        if not k:
            continue
        cookie_dict[k] = v

    return cookie_dict, user_agent


PLATFORM_DOMAINS = {
    "douyin": ".douyin.com",
    "bilibili": ".bilibili.com",
    "tiktok": ".tiktok.com",
    "facebook": ".facebook.com",
    "reels": ".facebook.com",
    "instagram": ".instagram.com",
    "youtube": ".youtube.com",
    "kuaishou": ".kuaishou.com",
    "xiaohongshu": ".xiaohongshu.com",
}

PLATFORM_DISPLAY_NAMES = {
    "douyin": "Douyin",
    "bilibili": "Bilibili",
    "tiktok": "TikTok",
    "facebook": "Facebook",
    "reels": "Facebook Reels",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "kuaishou": "Kuaishou",
    "xiaohongshu": "Xiaohongshu (RED)",
}


def detect_cookie_platform(raw_input: str, default_platform: str = "douyin") -> str:
    """Tự động phân tích chuỗi cookie để nhận diện thuộc nền tảng nào."""
    raw = (raw_input or "").lower()
    if not raw:
        return default_platform

    # 1. Nhận diện theo domain trong ATP / link / chuỗi cookie
    if "bilibili.com" in raw or "b23.tv" in raw:
        return "bilibili"
    if "douyin.com" in raw or "iesdouyin.com" in raw:
        return "douyin"
    if "tiktok.com" in raw:
        return "tiktok"
    if "facebook.com" in raw or "fb.com" in raw:
        return "facebook"
    if "instagram.com" in raw:
        return "instagram"
    if "youtube.com" in raw or "google.com" in raw:
        return "youtube"
    if "kuaishou.com" in raw or "gifshow.com" in raw:
        return "kuaishou"
    if "xiaohongshu.com" in raw or "xhslink.com" in raw:
        return "xiaohongshu"

    # 2. Nhận diện theo khóa cookie đặc trưng của từng nền tảng
    if any(k in raw for k in ("sessdata", "bili_jct", "dedeuserid", "bili_ticket", "buvid3")):
        return "bilibili"
    if any(k in raw for k in ("c_user=", "xs=", "datr=")):
        return "facebook"
    if any(k in raw for k in ("ds_user_id=", "csrftoken", "ig_did")):
        return "instagram"
    if any(k in raw for k in ("sapisid=", "login_info=", "__secure-3p")):
        return "youtube"
    if any(k in raw for k in ("kuaishou.server", "kpn=")):
        return "kuaishou"
    if any(k in raw for k in ("web_session=", "a1=", "xsecappid")):
        return "xiaohongshu"
    if any(k in raw for k in ("odin_tt", "sid_guard", "sid_tt", "passport_csrf_token")):
        return "douyin"

    return default_platform or "douyin"


def save_platform_cookies(raw_input: str, platform: Optional[str] = None) -> dict:
    """Phân tích và lưu cookie theo từng nền tảng cụ thể (Douyin, Bilibili, TikTok, Facebook...)."""
    cookie_dict, user_agent = parse_cookie_input(raw_input)
    if not cookie_dict:
        return {"success": False, "error": "Không thể nhận diện cookie từ nội dung đã dán.", "count": 0}

    # Tự động nhận diện platform nếu chưa có hoặc có chữ ký rõ ràng trong cookie
    detected = detect_cookie_platform(raw_input, default_platform=platform or "douyin")
    target_platform = detected if platform in (None, "auto") else (detected if detected != "douyin" else platform)
    target_platform = target_platform.lower()

    platform_name = PLATFORM_DISPLAY_NAMES.get(target_platform, target_platform.capitalize())
    domain = PLATFORM_DOMAINS.get(target_platform, f".{target_platform}.com")

    cache_dir = get_cookie_cache_dir()
    json_path = os.path.join(cache_dir, f"{target_platform}_cookies.json")
    netscape_path = os.path.join(cache_dir, f"{target_platform}_cookies.txt")

    # 1. Lưu file JSON
    cookie_list = [
        {"name": k, "value": v, "domain": domain, "path": "/"}
        for k, v in cookie_dict.items()
    ]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(cookie_list, f, indent=2, ensure_ascii=False)

    # 2. Lưu định dạng Netscape cho yt-dlp
    expiry = int(time.time()) + 86400 * 30  # 30 ngày
    with open(netscape_path, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write(f"# Generated by TankVideo Cookie Storage for {platform_name}\n\n")
        for k, v in cookie_dict.items():
            f.write(f"{domain}\tTRUE\t/\tTRUE\t{expiry}\t{k}\t{v}\n")

    # 3. Đồng bộ công cụ douyin-downloader ngoài nếu là Douyin
    if target_platform == "douyin":
        ext_path = r"d:\tooldownload\douyin-downloader\.cookies.json"
        if os.path.exists(os.path.dirname(ext_path)):
            try:
                with open(ext_path, "w", encoding="utf-8") as f:
                    json.dump(cookie_dict, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    # 4. Lưu vào Settings theo key nền tảng
    cookie_key = f"{target_platform}_cookie_raw" if target_platform != "douyin" else COOKIE_KEY
    time_key = f"{target_platform}_cookie_updated_at" if target_platform != "douyin" else COOKIE_TIME_KEY
    ua_key = f"{target_platform}_user_agent" if target_platform != "douyin" else "douyin_user_agent"

    _set_setting(cookie_key, raw_input)
    if user_agent:
        _set_setting(ua_key, user_agent)
    _set_setting(time_key, time.strftime("%Y-%m-%d %H:%M:%S"))

    return {
        "success": True,
        "platform": target_platform,
        "platform_name": platform_name,
        "count": len(cookie_dict),
        "user_agent": user_agent,
        "json_path": json_path,
        "netscape_path": netscape_path,
    }


def get_saved_platform_cookies(platform: str = "douyin") -> Tuple[List[dict], str, str]:
    """Lấy danh sách cookie đã lưu cho một nền tảng cụ thể.

    Returns:
        (cookie_list_for_cdp, netscape_txt_path, user_agent)
    """
    platform = (platform or "douyin").lower()
    cache_dir = get_cookie_cache_dir()
    netscape_path = os.path.join(cache_dir, f"{platform}_cookies.txt")
    json_path = os.path.join(cache_dir, f"{platform}_cookies.json")

    ua_key = f"{platform}_user_agent" if platform != "douyin" else "douyin_user_agent"
    user_agent = _get_setting(ua_key, "")

    cookie_list = []
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                cookie_list = json.load(f)
        except Exception:
            cookie_list = []

    return cookie_list, netscape_path if os.path.exists(netscape_path) else "", user_agent


def get_platform_cookie_summary(platform: str = "douyin") -> Tuple[str, bool, int, str]:
    """Lấy thông tin tóm tắt trạng thái cookie của một nền tảng.

    Returns:
        (summary_text, is_valid, count, platform_name)
    """
    platform = (platform or "douyin").lower()
    platform_name = PLATFORM_DISPLAY_NAMES.get(platform, platform.capitalize())

    cookie_key = f"{platform}_cookie_raw" if platform != "douyin" else COOKIE_KEY
    time_key = f"{platform}_cookie_updated_at" if platform != "douyin" else COOKIE_TIME_KEY

    raw = _get_setting(cookie_key, "")
    updated_at = _get_setting(time_key, "")

    if not raw:
        return f"⚪ Chưa có cookie {platform_name}. Dán cookie ATP để quét mượt mà.", False, 0, platform_name

    cookie_dict, _ = parse_cookie_input(raw)
    count = len(cookie_dict)
    if count == 0:
        return f"⚪ Chưa có cookie {platform_name}.", False, 0, platform_name

    status = f"🟢 Đã lưu {count} cookies {platform_name} (Hợp lệ)"
    return status, True, count, platform_name


def clear_saved_platform_cookies(platform: str = "douyin"):
    """Xóa cookie đã lưu của một nền tảng cụ thể."""
    platform = (platform or "douyin").lower()
    cookie_key = f"{platform}_cookie_raw" if platform != "douyin" else COOKIE_KEY
    time_key = f"{platform}_cookie_updated_at" if platform != "douyin" else COOKIE_TIME_KEY
    ua_key = f"{platform}_user_agent" if platform != "douyin" else "douyin_user_agent"

    _remove_setting(cookie_key)
    _remove_setting(time_key)
    _remove_setting(ua_key)

    cache_dir = get_cookie_cache_dir()
    for fname in [f"{platform}_cookies.json", f"{platform}_cookies.txt"]:
        p = os.path.join(cache_dir, fname)
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


# --- Tương thích ngược với các module đang gọi save_douyin_cookies ---
def save_douyin_cookies(raw_input: str) -> dict:
    return save_platform_cookies(raw_input, platform="douyin")


def get_saved_douyin_cookies() -> Tuple[List[dict], str, str]:
    return get_saved_platform_cookies("douyin")


def get_douyin_cookie_summary() -> Tuple[str, bool]:
    text, is_valid, _, _ = get_platform_cookie_summary("douyin")
    return text, is_valid


def clear_saved_douyin_cookies():
    clear_saved_platform_cookies("douyin")

