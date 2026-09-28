"""Bilibili Channel & Video Scanner Engine - Bóc tách danh sách video Bilibili kèm metadata đầy đủ.

Tính năng:
- Bóc tách toàn bộ video từ Bilibili Space (Kênh cá nhân / UP 主) hoặc video đơn lẻ
- Tự động lấy: ID (BVID), Tiêu đề (Title), Ảnh bìa (Cover HD), Lượt xem (Views), Lượt thích (Likes), Tác giả (UP主), Thời lượng
- Kết hợp đa phương thức:
  1. Flat Extraction + Concurrent HTML Initial State Parsing (cực nhanh, không cần đăng nhập)
  2. Playwright with Profile session (dùng hồ sơ trình duyệt người dùng chọn khi Bilibili chặn IP)
- Chống chặn 412/352 từ Bilibili
"""

import os
import sys
import re
import json
import gzip
import time
import urllib.request
from typing import Callable, Optional, Dict, List, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.services.cookie_storage_service import get_saved_platform_cookies

_BILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,vi;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.bilibili.com/",
}


def fetch_bilibili_video_details(bvid_or_url: str) -> Optional[Dict[str, Any]]:
    """Lấy chi tiết 1 video Bilibili qua HTML window.__INITIAL_STATE__ (không bị 412)."""
    m = re.search(r'(BV[a-zA-Z0-9]+)', bvid_or_url)
    bvid = m.group(1) if m else bvid_or_url
    if not bvid.startswith("BV"):
        return None

    video_url = f"https://www.bilibili.com/video/{bvid}"
    headers = dict(_BILI_HEADERS)
    try:
        saved_cookies, _, ua = get_saved_platform_cookies("bilibili")
        if ua:
            headers["User-Agent"] = ua
        if saved_cookies:
            headers["Cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in saved_cookies)
    except Exception:
        pass

    req = urllib.request.Request(video_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            html = raw.decode("utf-8", errors="ignore")

            # 1. Parse window.__INITIAL_STATE__
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html)
            if match:
                data = json.loads(match.group(1))
                vd = data.get("videoData") or {}
                stat = vd.get("stat") or {}
                owner = vd.get("owner") or {}
                cover = vd.get("pic") or ""
                if cover.startswith("//"):
                    cover = "https:" + cover
                elif cover.startswith("http://"):
                    cover = "https://" + cover[7:]

                return {
                    "id": bvid,
                    "title": vd.get("title") or "",
                    "url": video_url,
                    "direct_url": "",
                    "cover": cover,
                    "likes": stat.get("like") or 0,
                    "views": stat.get("view") or 0,
                    "author": owner.get("name") or "",
                    "duration": vd.get("duration") or 0,
                    "status": "Chờ tải",
                }

            # 2. Fallback parse meta tags
            title_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
            pic_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
            author_m = re.search(r'<meta\s+name="author"\s+content="([^"]+)"', html)

            cover = pic_m.group(1) if pic_m else ""
            if cover.startswith("//"):
                cover = "https:" + cover
            elif cover.startswith("http://"):
                cover = "https://" + cover[7:]

            return {
                "id": bvid,
                "title": title_m.group(1) if title_m else bvid,
                "url": video_url,
                "direct_url": "",
                "cover": cover,
                "likes": 0,
                "views": 0,
                "author": author_m.group(1) if author_m else "",
                "duration": 0,
                "status": "Chờ tải",
            }
    except Exception:
        pass
    return None


def _extract_via_playwright(
    url: str,
    browser_id: str = "chrome",
    profile_id: Optional[str] = None,
    browser_exe_path: Optional[str] = None,
    max_videos: int = 200,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    is_cancelled_cb: Optional[Callable[[], bool]] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """Bóc tách danh sách video trực tiếp từ DOM Bilibili qua Playwright với Profile đã chọn."""
    from playwright.sync_api import sync_playwright

    if progress_cb:
        progress_cb(f"Đang khởi động trình duyệt ({browser_id.upper()})...", 0)

    clean_url = url.split("?")[0]
    videos = []
    ch_name = ""

    with sync_playwright() as p:
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=ProfilePicker,PrivacySandboxSettings4",
        ]
        if profile_id and profile_id != "new_session":
            launch_args.append(f"--profile-directory={profile_id}")

        launch_kwargs = {
            "headless": False,
            "args": launch_args,
        }
        if browser_exe_path and os.path.exists(browser_exe_path):
            launch_kwargs["executable_path"] = browser_exe_path
        else:
            channel_map = {"chrome": "chrome", "edge": "msedge"}
            if browser_id in channel_map:
                launch_kwargs["channel"] = channel_map[browser_id]

        browser = None
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception:
            # Fallback to standard chromium launch
            launch_kwargs.pop("channel", None)
            launch_kwargs.pop("executable_path", None)
            try:
                browser = p.chromium.launch(**launch_kwargs)
            except Exception as e:
                if progress_cb:
                    progress_cb(f"Không thể mở browser: {e}", 0)
                return [], ""

        page = browser.new_page()
        try:
            if progress_cb:
                progress_cb("Đang tải trang Bilibili...", 0)
            page.goto(clean_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)

            # Extract channel name
            ch_name = page.evaluate('''() => {
                const el = document.querySelector('#h-name, .nickname, .up-name, [class*="name_"]');
                return el ? el.innerText.trim() : '';
            }''')

            # Scroll down to load videos
            scroll_count = min(10, max(3, max_videos // 15))
            for s in range(scroll_count):
                if is_cancelled_cb and is_cancelled_cb():
                    break
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(800)

            # Extract video cards from DOM
            dom_items = page.evaluate('''() => {
                const results = [];
                const seen = new Set();
                const cards = document.querySelectorAll('.bili-video-card, a[href*="/video/BV"]');
                cards.forEach(c => {
                    const a = c.tagName === 'A' ? c : c.querySelector('a[href*="/video/BV"]');
                    if (!a) return;
                    const m = a.href.match(/(BV[a-zA-Z0-9]+)/);
                    if (!m) return;
                    const bvid = m[1];
                    if (seen.has(bvid)) return;
                    seen.add(bvid);

                    const root = c.tagName === 'A' ? (c.closest('.bili-video-card') || c.parentElement) : c;
                    const img = root ? root.querySelector('img') : null;
                    const titleEl = root ? root.querySelector('.bili-video-card__info--tit, [title], h3, a.title') : null;

                    let title = '';
                    if (img && img.alt) title = img.alt;
                    else if (titleEl) title = titleEl.getAttribute('title') || titleEl.innerText;
                    else if (a) title = a.getAttribute('title') || a.innerText;

                    let cover = '';
                    if (img) {
                        cover = img.src || img.getAttribute('data-src') || '';
                        if (cover.startsWith('//')) cover = 'https:' + cover;
                    }

                    // Views & likes
                    const stats = root ? root.querySelectorAll('.bili-cover-card__stat span, .bili-video-card__stats--item') : [];
                    let views = '';
                    let likes = '';
                    if (stats.length >= 1) views = stats[0].innerText.trim();
                    if (stats.length >= 2) likes = stats[1].innerText.trim();

                    results.push({
                        id: bvid,
                        title: (title || '').trim(),
                        cover: cover,
                        viewsText: views,
                        likesText: likes
                    });
                });
                return results;
            }''')

            # Parse view string (e.g. "203万" -> 2030000)
            def parse_stat(txt: str) -> int:
                if not txt:
                    return 0
                txt = txt.strip().lower()
                try:
                    if "万" in txt or "w" in txt:
                        num = float(re.findall(r"[\d\.]+", txt)[0])
                        return int(num * 10000)
                    elif "亿" in txt:
                        num = float(re.findall(r"[\d\.]+", txt)[0])
                        return int(num * 100000000)
                    else:
                        digits = re.findall(r"\d+", txt)
                        return int("".join(digits)) if digits else 0
                except Exception:
                    return 0

            for it in dom_items:
                vid = it["id"]
                cover = it["cover"]
                if cover.startswith("http://"):
                    cover = "https://" + cover[7:]

                videos.append({
                    "id": vid,
                    "title": it["title"] or vid,
                    "url": f"https://www.bilibili.com/video/{vid}",
                    "direct_url": "",
                    "cover": cover,
                    "likes": parse_stat(it.get("likesText", "")),
                    "views": parse_stat(it.get("viewsText", "")),
                    "author": ch_name or "UP主",
                    "duration": 0,
                    "status": "Chờ tải",
                })
        except Exception as e:
            print(f"[BiliScanner] Error in Playwright extraction: {e}")
            if progress_cb:
                progress_cb(f"Lỗi đọc DOM Bilibili: {e}", 0)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    return videos, ch_name


def scan_bilibili(
    url: str,
    max_videos: int = 200,
    browser_id: str = "chrome",
    profile_id: Optional[str] = None,
    browser_exe_path: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    video_found_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_cancelled_cb: Optional[Callable[[], bool]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    """Quét toàn bộ video Bilibili (Kênh hoặc Video đơn) kèm đầy đủ metadata.

    Returns:
        (videos_list, channel_info_dict, error_string)
    """
    clean_url = url.strip()
    channel_info = {"name": "", "total": 0}
    videos = []
    err = ""

    # 1. Single video case
    if "/video/BV" in clean_url or "/video/av" in clean_url:
        if progress_cb:
            progress_cb("Đang lấy thông tin video Bilibili...", 0)
        v = fetch_bilibili_video_details(clean_url)
        if v:
            videos.append(v)
            if video_found_cb:
                video_found_cb(v)
            channel_info["name"] = v.get("author", "Bilibili")
            channel_info["total"] = 1
            return videos, channel_info, ""
        else:
            return [], channel_info, "Không thể lấy thông tin video Bilibili đã nhập."

    # 2. Channel / Space scanning
    if progress_cb:
        progress_cb("Đang phân tích danh sách video từ Kênh Bilibili...", 0)

    # Strategy A: Fast yt-dlp flat extraction to get list of BVids
    raw_bvids = []
    ch_name = ""
    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            if info:
                ch_name = info.get("uploader") or info.get("channel") or info.get("title") or ""
                entries = info.get("entries") or [info]
                for e in entries:
                    vid = e.get("id") or ""
                    v_url = e.get("url") or ""
                    if not vid.startswith("BV"):
                        m = re.search(r'(BV[a-zA-Z0-9]+)', v_url)
                        if m:
                            vid = m.group(1)
                    if vid and vid.startswith("BV") and vid not in raw_bvids:
                        raw_bvids.append(vid)
    except Exception as e:
        # If yt-dlp hit 412 on space, we will fallback to Playwright
        pass

    # Strategy B: If yt-dlp was blocked by 412 or returned nothing, use Playwright
    if not raw_bvids:
        if progress_cb:
            progress_cb("Đang quét kênh Bilibili qua trình duyệt...", 0)
        pw_videos, pw_ch_name = _extract_via_playwright(
            url=clean_url,
            browser_id=browser_id,
            profile_id=profile_id,
            browser_exe_path=browser_exe_path,
            max_videos=max_videos,
            progress_cb=progress_cb,
            is_cancelled_cb=is_cancelled_cb,
        )
        if pw_videos:
            channel_info["name"] = pw_ch_name or "Bilibili UP主"
            channel_info["total"] = len(pw_videos)
            for v in pw_videos:
                if is_cancelled_cb and is_cancelled_cb():
                    break
                videos.append(v)
                if video_found_cb:
                    video_found_cb(v)
            return videos, channel_info, ""

    if not raw_bvids:
        return [], channel_info, "Không tìm thấy video nào từ kênh Bilibili này."

    # Strategy A enrichment: Fetch real titles, thumbnails, views, likes concurrently
    if progress_cb:
        progress_cb(f"Đã tìm thấy {len(raw_bvids)} video, đang tải thông tin chi tiết...", len(raw_bvids))

    target_bvids = raw_bvids[:max_videos]

    def _fetch_one(bvid: str):
        if is_cancelled_cb and is_cancelled_cb():
            return None
        details = fetch_bilibili_video_details(bvid)
        if details:
            return details
        # Fallback minimal entry if network glitched
        return {
            "id": bvid,
            "title": f"Video {bvid}",
            "url": f"https://www.bilibili.com/video/{bvid}",
            "direct_url": "",
            "cover": "",
            "likes": 0,
            "views": 0,
            "author": ch_name or "Unknown",
            "duration": 0,
            "status": "Chờ tải",
        }

    # Parallel enrichment with 8 worker threads
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(_fetch_one, bvid): bvid for bvid in target_bvids}
        for future in as_completed(future_map):
            if is_cancelled_cb and is_cancelled_cb():
                break
            try:
                item = future.result()
                if item:
                    videos.append(item)
                    if not channel_info["name"] and item.get("author") and item["author"] != "Unknown":
                        channel_info["name"] = item["author"]
                    if video_found_cb:
                        video_found_cb(item)
                    if progress_cb:
                        progress_cb(f"Đang bóc tách video ({len(videos)}/{len(target_bvids)})...", len(videos))
            except Exception:
                pass

    if not channel_info["name"]:
        channel_info["name"] = ch_name or "Bilibili"
    channel_info["total"] = len(videos)

    return videos, channel_info, err
