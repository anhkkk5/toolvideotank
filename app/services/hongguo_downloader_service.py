"""Hongguo Downloader Service – Dịch vụ bóc tách và tải phim ngắn Hồng Quả (红果短剧 - hongguoduanju.com).

Hỗ trợ:
- Phân tích link / ID phim ngắn Hongguo (detail, player, m/detail...)
- Lấy thông tin phim: Tên phim, tổng số tập, ảnh bìa, diễn viên, thể loại
- Quét danh sách toàn bộ các tập
- Giải mã link stream MP4 trực tiếp không logo (HD / Full HD)
- Tải video đa luồng tốc độ cao (Multi-threaded downloading)
- Báo cáo tiến độ và hỗ trợ dừng tải an toàn
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://hongguoduanju.com/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,vi;q=0.7",
}


def parse_hongguo_id(input_str: str) -> Optional[str]:
    """Trích xuất series_id từ URL hoặc chuỗi nhập vào."""
    if not input_str:
        return None
    s = str(input_str).strip()

    # 1. Trích xuất từ query param series_id=...
    m = re.search(r"series_id=(\d+)", s)
    if m:
        return m.group(1)

    # 2. Trích xuất từ path /player/{series_id}
    m = re.search(r"hongguoduanju\.com/player/(\d+)", s)
    if m:
        return m.group(1)

    # 3. Chuỗi số thuần túy (ID 15-22 chữ số)
    m = re.search(r"^\d{15,22}$", s)
    if m:
        return s

    # 4. Tìm số ID dài bất kỳ trong chuỗi
    m = re.search(r"\b(\d{18,20})\b", s)
    if m:
        return m.group(1)

    return None


def fetch_hongguo_drama_info(series_id_or_url: str, cookies: Optional[str] = None) -> Dict[str, Any]:
    """Lấy thông tin chi tiết phim ngắn Hồng Quả và danh sách tất cả các tập."""
    series_id = parse_hongguo_id(series_id_or_url)
    if not series_id:
        raise ValueError(f"Không nhận diện được ID phim ngắn từ: {series_id_or_url}")

    url = f"https://hongguoduanju.com/player/{series_id}"
    headers = dict(DEFAULT_HEADERS)
    if cookies:
        headers["Cookie"] = cookies.strip()

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        # Thử fallback sang detail URL
        detail_url = f"https://hongguoduanju.com/detail?series_id={series_id}"
        req_fallback = urllib.request.Request(detail_url, headers=headers)
        with urllib.request.urlopen(req_fallback, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

    idx = html.find("_ROUTER_DATA =")
    if idx == -1:
        raise RuntimeError("Không tìm thấy dữ liệu _ROUTER_DATA từ trang Hồng Quả.")

    sub = html[idx + len("_ROUTER_DATA ="):].strip()
    try:
        data, _ = json.JSONDecoder().raw_decode(sub)
    except Exception as exc:
        raise RuntimeError(f"Lỗi giải mã cấu trúc JSON phim: {exc}")

    loader_data = data.get("loaderData", {})
    # Tìm page data trong loaderData
    page_data = {}
    for k, v in loader_data.items():
        if isinstance(v, dict) and ("seriesDetail" in v or "series_id" in v):
            page_data = v
            break

    if not page_data:
        # Fallback duyệt sâu
        for k, v in loader_data.items():
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    if isinstance(sub_v, dict) and "seriesDetail" in sub_v:
                        page_data = sub_v
                        break

    series_detail = page_data.get("seriesDetail", {})
    if not series_detail:
        raise RuntimeError("Không tìm thấy thông tin seriesDetail của bộ phim.")

    title = series_detail.get("series_name") or f"Hongguo_{series_id}"
    cover_url = series_detail.get("series_cover") or ""
    intro = series_detail.get("series_intro") or ""
    total_episodes = int(series_detail.get("episode_cnt") or 0)
    accessible_episodes = int(series_detail.get("accessible_episode_cnt") or 0)
    tags = series_detail.get("tags") or []
    celebrities = series_detail.get("celebrities") or []
    actors = [c.get("nickname") for c in celebrities if c.get("nickname")]

    # Danh sách các vid
    vid_list = series_detail.get("vid_list") or []
    if not vid_list:
        # Nếu chưa có trong seriesDetail, thử tìm tất cả các ID tập có dạng tương tự
        raw_vids = re.findall(r"/player/" + re.escape(series_id) + r"/(\d+)", html)
        vid_list = list(dict.fromkeys(raw_vids))

    if not total_episodes and vid_list:
        total_episodes = len(vid_list)

    # Khởi tạo danh sách các tập
    episodes = []
    current_player_info = page_data.get("video_player_info") or {}
    current_vid = str(page_data.get("vid") or "")

    for idx, vid in enumerate(vid_list):
        ep_num = idx + 1
        ep_info = {
            "index": ep_num,
            "title": f"Tập {ep_num:02d}",
            "vid": str(vid),
            "series_id": series_id,
            "status": "ready",  # ready, downloading, completed, error
            "progress": 0,
            "video_url": "",
            "duration": 0,
        }
        # Nếu trùng tập đang phát sẵn trong HTML
        if str(vid) == current_vid and current_player_info.get("main_url"):
            ep_info["video_url"] = current_player_info.get("main_url")
            ep_info["duration"] = current_player_info.get("duration") or 0

        episodes.append(ep_info)

    # Nếu vid_list ít hơn total_episodes, tự sinh các tập còn lại để người dùng thấy đầy đủ
    if len(episodes) < total_episodes:
        start_idx = len(episodes) + 1
        for ep_num in range(start_idx, total_episodes + 1):
            episodes.append({
                "index": ep_num,
                "title": f"Tập {ep_num:02d}",
                "vid": "",
                "series_id": series_id,
                "status": "ready",
                "progress": 0,
                "video_url": "",
                "duration": 0,
            })

    return {
        "series_id": series_id,
        "title": title,
        "cover_url": cover_url,
        "intro": intro,
        "total_episodes": total_episodes or len(episodes),
        "accessible_episodes": accessible_episodes,
        "tags": tags,
        "actors": actors,
        "episodes": episodes,
        "raw_page_data": page_data,
    }


def resolve_episode_video_url(series_id: str, vid: str, cookies: Optional[str] = None) -> Optional[str]:
    """Lấy link tải video MP4 trực tiếp của một tập phim cụ thể."""
    if not vid:
        return None

    url = f"https://hongguoduanju.com/player/{series_id}/{vid}"
    headers = dict(DEFAULT_HEADERS)
    if cookies:
        headers["Cookie"] = cookies.strip()

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return None

    idx = html.find("_ROUTER_DATA =")
    if idx == -1:
        return None

    sub = html[idx + len("_ROUTER_DATA ="):].strip()
    try:
        data, _ = json.JSONDecoder().raw_decode(sub)
    except Exception:
        return None

    loader_data = data.get("loaderData", {})
    for k, v in loader_data.items():
        if isinstance(v, dict):
            vp = v.get("video_player_info")
            if vp and isinstance(vp, dict) and vp.get("main_url"):
                return vp.get("main_url")

    # Thử tìm trực tiếp chuỗi URL video trong HTML
    m = re.search(r'["\'](https://[^"\']*qznovelvod\.com/[^"\']+)["\']', html)
    if m:
        return m.group(1)

    return None


def download_file_with_progress(
    url: str,
    output_path: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    is_cancelled_func: Optional[Callable[[], bool]] = None,
) -> bool:
    """Tải một file với báo cáo tiến độ và khả năng hủy ngang lập tức."""
    headers = dict(DEFAULT_HEADERS)
    req = urllib.request.Request(url, headers=headers)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    temp_path = output_path + ".part"

    try:
        with urllib.request.urlopen(req, timeout=15) as resp, open(temp_path, "wb") as f:
            total_bytes = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            chunk_size = 128 * 1024  # 128KB

            while True:
                if is_cancelled_func and is_cancelled_func():
                    f.close()
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    return False

                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total_bytes)

        if os.path.exists(temp_path):
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(temp_path, output_path)
        return True
    except Exception as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise exc


# ============================================================================
#  Qt Worker Threads for Background Scanning & Concurrent Downloading
# ============================================================================
try:
    from PySide6.QtCore import QThread, Signal
except ImportError:
    QThread = object
    Signal = lambda *args: None


class HongguoScanWorker(QThread):
    sig_progress = Signal(str)
    sig_done = Signal(dict)
    sig_error = Signal(str)

    def __init__(self, url_or_id: str, cookies: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.url_or_id = url_or_id
        self.cookies = cookies
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self.sig_progress.emit(f"Đang phân tích link phim Hồng Quả: {self.url_or_id}...")
            info = fetch_hongguo_drama_info(self.url_or_id, cookies=self.cookies)
            if self._is_cancelled:
                return
            self.sig_progress.emit(f"Đã quét thành công: {info.get('title')} ({info.get('total_episodes')} tập)")
            self.sig_done.emit(info)
        except Exception as exc:
            if not self._is_cancelled:
                self.sig_error.emit(str(exc))


class HongguoDownloadWorker(QThread):
    sig_ep_status = Signal(int, str)  # ep_index, status_text
    sig_ep_completed = Signal(int, str)  # ep_index, file_path
    sig_ep_error = Signal(int, str)  # ep_index, error_msg
    sig_overall_progress = Signal(int, int, int)  # completed, total, percent
    sig_log = Signal(str)  # log message
    sig_all_done = Signal(int, int)  # success_count, fail_count

    def __init__(
        self,
        drama_info: dict,
        selected_episodes: List[dict],
        output_dir: str,
        threads: int = 16,
        cookies: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.drama_info = drama_info
        self.selected_episodes = selected_episodes
        self.output_dir = output_dir
        self.threads = max(1, min(32, int(threads or 16)))
        self.cookies = cookies
        self._is_cancelled = False
        self._executor = None

    def cancel(self):
        self._is_cancelled = True
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _sanitize_name(self, name: str) -> str:
        return re.sub(r'[\\/*?:"<>|]', "_", str(name or "")).strip()

    def _download_single_ep(self, ep: dict, sub_dir: str) -> bool:
        if self._is_cancelled:
            return False

        ep_idx = ep.get("index", 1)
        series_id = self.drama_info.get("series_id", "")
        vid = ep.get("vid", "")
        drama_title = self._sanitize_name(self.drama_info.get("title", f"Hongguo_{series_id}"))
        file_name = f"{drama_title}_Tap_{ep_idx:02d}.mp4"
        file_path = os.path.join(sub_dir, file_name)

        # Kiểm tra nếu file đã tải xong trước đó (dung lượng > 100KB)
        if os.path.exists(file_path) and os.path.getsize(file_path) > 100 * 1024:
            self.sig_ep_status.emit(ep_idx, "Đã có sẵn ✓")
            self.sig_log.emit(f"[{time.strftime('%H:%M:%S')}] [Tập {ep_idx:02d}] Đã tồn tại, bỏ qua: {file_name}")
            self.sig_ep_completed.emit(ep_idx, file_path)
            return True

        self.sig_ep_status.emit(ep_idx, "Bóc tách...")
        video_url = ep.get("video_url", "")
        if not video_url and vid:
            # Format cookies if passed as tuple/list
            ck_str = self.cookies
            if isinstance(ck_str, tuple):
                ck_list = ck_str[0]
                if isinstance(ck_list, list):
                    ck_str = "; ".join([f"{c['name']}={c['value']}" for c in ck_list if isinstance(c, dict) and "name" in c])
            video_url = resolve_episode_video_url(series_id, vid, cookies=ck_str)

        if not video_url:
            self.sig_ep_status.emit(ep_idx, "Khóa Web")
            self.sig_log.emit(
                f"[{time.strftime('%H:%M:%S')}] [Tập {ep_idx:02d}] ⚠️ Tập này bị khóa trên Web Hongguo "
                f"(ByteDance chỉ mở xem thử các tập đầu trên Web, các tập sau cần mở App Hồng Quả)."
            )
            self.sig_ep_error.emit(ep_idx, "Bị khóa trên Web (Cần App)")
            return False

        if self._is_cancelled:
            return False

        self.sig_ep_status.emit(ep_idx, "Bắt đầu tải...")
        self.sig_log.emit(f"[{time.strftime('%H:%M:%S')}] [Tập {ep_idx:02d}] Đang tải: {file_name}...")

        def _prog(dl_bytes, total_bytes):
            if total_bytes > 0:
                pct = int(dl_bytes * 100 / total_bytes)
                self.sig_ep_status.emit(ep_idx, f"Tải {pct}%")

        try:
            ok = download_file_with_progress(
                video_url,
                file_path,
                progress_callback=_prog,
                is_cancelled_func=lambda: self._is_cancelled,
            )
            if ok:
                self.sig_ep_status.emit(ep_idx, "Hoàn tất ✓")
                self.sig_log.emit(f"[{time.strftime('%H:%M:%S')}] [Tập {ep_idx:02d}] ✅ Tải thành công -> {file_name}")
                self.sig_ep_completed.emit(ep_idx, file_path)
                return True
            else:
                self.sig_ep_status.emit(ep_idx, "Đã dừng")
                return False
        except Exception as exc:
            self.sig_ep_status.emit(ep_idx, "Lỗi tải")
            self.sig_log.emit(f"[{time.strftime('%H:%M:%S')}] [Tập {ep_idx:02d}] ❌ Lỗi tải: {exc}")
            self.sig_ep_error.emit(ep_idx, str(exc))
            return False

    def run(self):
        total = len(self.selected_episodes)
        if total == 0:
            self.sig_all_done.emit(0, 0)
            return

        drama_title = self._sanitize_name(self.drama_info.get("title", "Hongguo"))
        sub_dir = os.path.join(self.output_dir, f"Hongguo_{drama_title}")
        os.makedirs(sub_dir, exist_ok=True)

        self.sig_log.emit(
            f"[{time.strftime('%H:%M:%S')}] 🚀 Bắt đầu tải {total} tập phim: '{drama_title}'\n"
            f"   📁 Thư mục lưu: {sub_dir}\n"
            f"   ⚡ Số luồng song song: {self.threads} luồng"
        )

        completed = 0
        success = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            self._executor = executor
            future_to_ep = {
                executor.submit(self._download_single_ep, ep, sub_dir): ep
                for ep in self.selected_episodes
            }

            for future in as_completed(future_to_ep):
                if self._is_cancelled:
                    break
                try:
                    res = future.result()
                    if res:
                        success += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

                completed += 1
                pct = int(completed * 100 / total)
                self.sig_overall_progress.emit(completed, total, pct)

        if self._is_cancelled:
            self.sig_log.emit(f"[{time.strftime('%H:%M:%S')}] 🛑 Quá trình tải đã dừng theo yêu cầu ({success}/{total} hoàn tất).")
        else:
            self.sig_log.emit(f"[{time.strftime('%H:%M:%S')}] 🎉 Hoàn thành toàn bộ! Thành công: {success}/{total} tập.")

        self.sig_all_done.emit(success, failed)
