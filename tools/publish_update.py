"""Công cụ tự động phát hành bản cập nhật TankVideo Studio lên GitHub Gist.

Chỉ cần chạy file này (hoặc bấm publish_update.bat), hệ thống sẽ:
1. Tự động đóng gói file chạy TankVideo.exe mới thành dist/patch.zip siêu nhẹ (~32 MB).
2. Tự động tăng số phiên bản (ví dụ 1.0.0 -> 1.0.1).
3. Đẩy thông tin phiên bản mới và đường link bản vá lên GitHub Gist qua Git.
4. Toàn bộ người dùng khi mở app bấm "Cập nhật" sẽ được cập nhật tự động 1-Click trong 5 giây!
"""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parents[1]
GIST_REPO_DIR = ROOT_DIR / "scratch" / "gist_repo"
GIST_URL = "https://gist.github.com/b298a331f107ac7f0cd2911cddc438f7.git"
VERSION_PY = ROOT_DIR / "app" / "version.py"


def get_current_app_version() -> str:
    if not VERSION_PY.exists():
        return "1.0.0"
    content = VERSION_PY.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.startswith("APP_VERSION"):
            parts = line.split("=")
            if len(parts) >= 2:
                return parts[1].strip().strip('"').strip("'")
    return "1.0.0"


def set_current_app_version(new_ver: str):
    if not VERSION_PY.exists():
        return
    content = VERSION_PY.read_text(encoding="utf-8")
    lines = []
    for line in content.splitlines():
        if line.startswith("APP_VERSION"):
            lines.append(f'APP_VERSION = "{new_ver}"')
        else:
            lines.append(line)
    VERSION_PY.write_text("\n".join(lines) + "\n", encoding="utf-8")


def auto_bump(v: str) -> str:
    parts = v.strip().split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    except Exception:
        return v + ".1"


def create_patch_zip() -> tuple[Path | None, float]:
    exe_path = ROOT_DIR / "dist" / "TankVideo" / "TankVideo.exe"
    if not exe_path.exists():
        print("⚠️ Chưa tìm thấy dist/TankVideo/TankVideo.exe để đóng gói bản vá.")
        return None, 0.0

    # Delegate to mk_patch.py which bundles exe + Playwright driver + dependencies
    mk_patch = ROOT_DIR / "scratch" / "mk_patch.py"
    if mk_patch.exists():
        res = subprocess.run(
            [sys.executable, str(mk_patch)],
            cwd=str(ROOT_DIR),
            capture_output=False,
        )
        if res.returncode != 0:
            print("⚠️ mk_patch.py thất bại, dùng fallback đóng gói chỉ exe.")
    else:
        # Fallback: chỉ nén TankVideo.exe
        patch_zip = ROOT_DIR / "dist" / "patch.zip"
        patch_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(patch_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(exe_path, "TankVideo.exe")

    patch_zip = ROOT_DIR / "dist" / "patch.zip"
    if not patch_zip.exists():
        return None, 0.0

    size_mb = patch_zip.stat().st_size / (1024 * 1024)
    print(f"\n📦 ĐÃ ĐÓNG GÓI XONG BẢN VÁ: dist/patch.zip ({size_mb:.1f} MB)")
    return patch_zip, size_mb


def ensure_gist_repo() -> bool:
    if not (GIST_REPO_DIR / ".git").exists():
        GIST_REPO_DIR.parent.mkdir(parents=True, exist_ok=True)
        print("Đang đồng bộ kho Gist từ GitHub...")
        res = subprocess.run(["git", "clone", GIST_URL, str(GIST_REPO_DIR)], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Lỗi clone Gist: {res.stderr}")
            return False
    return True


def publish(new_version: str, release_notes: str = "", download_url: str = "", patch_url: str = "", size_mb: float = 0.0):
    if not ensure_gist_repo():
        print("Không thể kết nối kho Gist.")
        return False

    v_json_path = GIST_REPO_DIR / "version.json"
    data = {}
    if v_json_path.exists():
        try:
            data = json.loads(v_json_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    data["version"] = new_version
    if release_notes:
        data["name"] = release_notes
    elif "name" not in data:
        data["name"] = f"Bản cập nhật v{new_version}"

    if download_url:
        data["download_url"] = download_url
    elif "download_url" not in data:
        data["download_url"] = "https://drive.google.com/file/d/132Y6CEbseVO_SqiiKd_77OVNhajxv9Ih/view?usp=drive_link"

    if patch_url:
        data["patch_url"] = patch_url
    if size_mb > 0:
        data["size_mb"] = round(size_mb, 1)

    v_json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Git commit & push
    try:
        subprocess.run(["git", "pull", "--rebase"], cwd=str(GIST_REPO_DIR), capture_output=True)
        subprocess.run(["git", "add", "version.json"], cwd=str(GIST_REPO_DIR), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Release v{new_version}"], cwd=str(GIST_REPO_DIR), check=True, capture_output=True)
        push_res = subprocess.run(["git", "push", "origin", "main"], cwd=str(GIST_REPO_DIR), capture_output=True, text=True)
        if push_res.returncode != 0:
            push_res = subprocess.run(["git", "push", "origin", "HEAD"], cwd=str(GIST_REPO_DIR), capture_output=True, text=True)
        if push_res.returncode != 0:
            print(f"Lỗi khi đẩy lên GitHub Gist: {push_res.stderr}")
            return False
    except Exception as e:
        print(f"Lỗi Git: {e}")
        return False

    print(f"\n=======================================================")
    print(f"🎉 PHÁT HÀNH THÀNH CÔNG PHIÊN BẢN v{new_version} LÊN MẠNG!")
    print(f"=======================================================")
    print(f"- Gist URL: {GIST_URL}")
    print(f"- Link bộ cài Full (Drive): {data.get('download_url', '')}")
    if data.get("patch_url"):
        print(f"- Link bản vá Patch 1-Click: {data.get('patch_url')}")
    print(f"- Người dùng khi mở app bấm 'Cập nhật' sẽ cập nhật tự động ngay!")
    return True


if __name__ == "__main__":
    cur_ver = get_current_app_version()
    bumped = auto_bump(cur_ver)

    print(f"=======================================================")
    print(f"   CÔNG CỤ TỰ ĐỘNG PHÁT HÀNH BẢN CẬP NHẬT TANKVIDEO   ")
    print(f"=======================================================")
    print(f"Phiên bản hiện tại trong mã nguồn: v{cur_ver}")

    if len(sys.argv) > 1:
        target_ver = sys.argv[1].strip()
    else:
        target_ver = input(f"\n1. Nhập phiên bản cần phát hành (Mặc định: {cur_ver}): ").strip()
        if not target_ver:
            target_ver = cur_ver

    notes = ""
    if len(sys.argv) > 2:
        notes = sys.argv[2].strip()
    else:
        notes = input("2. Mô tả nội dung cập nhật (Enter để dùng mặc định): ").strip()

    # CẬP NHẬT version.py TRƯỚC KHI BUILD để exe mới chứa đúng version
    if target_ver != cur_ver:
        set_current_app_version(target_ver)
        print(f"\n✅ Đã cập nhật version.py: {cur_ver} → {target_ver}")
        print(f"⚠️  BẠN CẦN BUILD LẠI EXE TRƯỚC KHI TIẾP TỤC!")
        print(f"   Chạy: .\\.venv\\Scripts\\pyinstaller CapCap.spec --noconfirm")
        input(f"\n   Nhấn ENTER sau khi build xong... ")

    # Đóng gói bản vá patch.zip (lúc này exe đã chứa version mới)
    patch_path, size_mb = create_patch_zip()

    patch_url_input = ""
    if len(sys.argv) > 3:
        patch_url_input = sys.argv[3].strip()
    else:
        prompt_txt = "3. Link tải file patch.zip (Nếu bạn đã up file dist/patch.zip lên Drive/Web, dán link vào đây): "
        patch_url_input = input(prompt_txt).strip()

    publish(target_ver, release_notes=notes, patch_url=patch_url_input, size_mb=size_mb)

