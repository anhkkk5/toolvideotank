"""Browser & Profile Detection Service for Windows.

Tự động phát hiện các trình duyệt nhân Chromium đã cài đặt (Cốc Cốc, Google Chrome, Microsoft Edge, Brave)
và đọc danh sách Profile của từng trình duyệt từ file 'Local State'.
"""

import os
import sys
import json
from typing import Dict, List, Any, Optional


def get_installed_browsers_with_profiles() -> List[Dict[str, Any]]:
    """Quét các trình duyệt và hồ sơ (profiles) trên Windows.

    Returns:
        List[dict]: Mỗi phần tử gồm:
            id: 'coccoc' | 'chrome' | 'edge' | 'brave'
            name: Tên hiển thị ('Cốc Cốc', 'Google Chrome'...)
            exe_path: Đường dẫn file thực thi .exe
            user_data_dir: Thư mục User Data
            profiles: List[dict] chứa {'id': 'Default', 'name': 'Tên hồ sơ', 'email': '...'}
    """
    candidates = [
        {
            "id": "coccoc",
            "name": "Cốc Cốc",
            "exe_candidates": [
                r"C:\Program Files\CocCoc\Browser\Application\browser.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\CocCoc\Browser\Application\browser.exe"),
                r"C:\Program Files (x86)\CocCoc\Browser\Application\browser.exe",
            ],
            "user_data_candidates": [
                os.path.expandvars(r"%LOCALAPPDATA%\CocCoc\Browser\User Data"),
            ],
            "channel": None,  # Launch by binary path
        },
        {
            "id": "chrome",
            "name": "Google Chrome",
            "exe_candidates": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ],
            "user_data_candidates": [
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data"),
            ],
            "channel": "chrome",
        },
        {
            "id": "edge",
            "name": "Microsoft Edge",
            "exe_candidates": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            ],
            "user_data_candidates": [
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data"),
            ],
            "channel": "msedge",
        },
        {
            "id": "brave",
            "name": "Brave",
            "exe_candidates": [
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            ],
            "user_data_candidates": [
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data"),
            ],
            "channel": None,
        }
    ]

    result = []
    for c in candidates:
        # Check if browser binary exists
        exe_path = ""
        for p in c["exe_candidates"]:
            if os.path.exists(p):
                exe_path = p
                break
        if not exe_path:
            continue

        # Check user data dir
        user_data_dir = ""
        for u in c["user_data_candidates"]:
            if os.path.exists(u):
                user_data_dir = u
                break

        profiles = []
        if user_data_dir:
            local_state_file = os.path.join(user_data_dir, "Local State")
            if os.path.exists(local_state_file):
                try:
                    with open(local_state_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    info_cache = data.get("profile", {}).get("info_cache", {})
                    for pdir, pinfo in info_cache.items():
                        p_name = pinfo.get("name") or pdir
                        user_name = pinfo.get("user_name") or pinfo.get("gaia_name") or ""
                        profiles.append({
                            "id": pdir,
                            "name": p_name,
                            "email": user_name,
                            "display": f"{p_name} ({user_name})" if user_name else p_name,
                        })
                except Exception:
                    pass

        # If no profile parsed, add a default option
        if not profiles:
            profiles.append({
                "id": "Default",
                "name": "Mặc định (Default)",
                "email": "",
                "display": "Mặc định (Default)",
            })

        result.append({
            "id": c["id"],
            "name": c["name"],
            "exe_path": exe_path,
            "user_data_dir": user_data_dir,
            "channel": c["channel"],
            "profiles": profiles,
        })

    return result
