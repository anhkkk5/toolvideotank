import html as html_lib
import json
import logging
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("FacebookScanner")


def normalize_facebook_url(url: str, mode: str = "reels") -> str:
    """Chuẩn hóa URL Facebook về đúng tab reels hoặc videos."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url

    # Remove query params except essential ones like id and sk
    if "/reel/" in url or "/watch" in url or "fb.watch" in url:
        return url

    # Handle profile.php?id=...
    if "profile.php" in url and "id=" in url:
        if "sk=" not in url:
            sep = "&" if "?" in url else "?"
            sk_val = "reels_tab" if mode == "reels" else "videos"
            url = f"{url}{sep}sk={sk_val}"
        return url

    # Handle facebook.com/username
    if mode == "reels" and "/reels" not in url and "/videos" not in url:
        url = url.rstrip("/") + "/reels/"
    elif mode == "videos" and "/videos" not in url and "/reels" not in url:
        url = url.rstrip("/") + "/videos/"

    return url


def parse_fb_count(txt: str) -> int:
    """Chuyển đổi chuỗi lượt xem/lượt thích Facebook (ví dụ: 8,9K, 1.2M, 540) thành số nguyên."""
    if not txt:
        return 0
    txt = str(txt).strip().upper().replace(",", ".")
    m = re.search(r'([\d\.]+)\s*([KM]?)', txt)
    if not m:
        return 0
    try:
        val = float(m.group(1))
        unit = m.group(2)
        if unit == "K":
            return int(val * 1000)
        elif unit == "M":
            return int(val * 1_000_000)
        return int(val)
    except Exception:
        return 0


def parse_fb_duration(txt: str) -> int:
    """Parse duration string like '2:29:21' or '12:35' to seconds."""
    if not txt:
        return 0
    m = re.search(r'\b(\d{1,2}):(\d{2}):(\d{2})\b', txt)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    m = re.search(r'\b(\d{1,2}):(\d{2})\b', txt)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return 0


def fetch_facebook_reel_metadata(reel_id_or_url: str) -> Dict[str, Any]:
    """Lấy tiêu đề, tác giả, lượt xem qua OpenGraph của Facebook bằng header mạng xã hội."""
    m = re.search(r'(\d+)', reel_id_or_url)
    reel_id = m.group(1) if m else reel_id_or_url
    url = f"https://www.facebook.com/reel/{reel_id}"

    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    result = {
        "id": reel_id,
        "title": f"Facebook Reel {reel_id}",
        "author": "",
        "views": 0,
        "likes": 0,
        "cover": "",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

            m_title = re.search(r'<meta property="og:title"\s+content="(.*?)"', html)
            m_desc = re.search(r'<meta property="og:description"\s+content="(.*?)"', html)
            m_img = re.search(r'<meta property="og:image"\s+content="(.*?)"', html)

            raw_title = html_lib.unescape(m_title.group(1)) if m_title else ""
            raw_desc = html_lib.unescape(m_desc.group(1)) if m_desc else ""
            cover_img = html_lib.unescape(m_img.group(1)) if m_img else ""

            if cover_img:
                result["cover"] = cover_img

            if raw_title:
                parts = [p.strip() for p in raw_title.split("|")]
                if len(parts) >= 3:
                    # parts[0]: '8,9K lượt xem · 98 cảm xúc'
                    # parts[1]: Caption
                    # parts[2]: Author
                    stat_part = parts[0]
                    v_match = re.search(r'([\d,\.]+[KM]?)\s*lượt xem', stat_part, re.IGNORECASE)
                    if v_match:
                        result["views"] = parse_fb_count(v_match.group(1))
                    l_match = re.search(r'([\d,\.]+[KM]?)\s*cảm xúc', stat_part, re.IGNORECASE)
                    if l_match:
                        result["likes"] = parse_fb_count(l_match.group(1))

                    result["title"] = parts[1]
                    result["author"] = parts[2]
                elif len(parts) == 2:
                    result["title"] = parts[0]
                    result["author"] = parts[1]
                else:
                    result["title"] = raw_title

            if raw_desc and (not result["title"] or result["title"].startswith("Facebook Reel")):
                result["title"] = raw_desc
    except Exception as e:
        logger.debug(f"Không thể lấy metadata reel {reel_id}: {e}")

    return result


def scan_facebook_channel(
    url: str,
    max_videos: int = 0,  # 0: Không giới hạn (quét sạch toàn bộ kênh)
    browser_id: str = "chrome",
    profile_id: Optional[str] = None,
    browser_exe_path: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    video_found_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_cancelled_cb: Optional[Callable[[], bool]] = None,
    mode: str = "reels",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[str]]:
    """Quét toàn bộ video hoặc reels từ Facebook Page/Profile bằng Playwright và cookie đã lưu."""
    from playwright.sync_api import sync_playwright
    from app.services.cookie_storage_service import get_saved_platform_cookies

    def _cancelled() -> bool:
        return bool(is_cancelled_cb and is_cancelled_cb())

    def _progress(msg: str, count: int = 0):
        if progress_cb:
            progress_cb(msg, count)

    target_url = normalize_facebook_url(url, mode=mode)
    _progress(f"Đang chuẩn bị phiên quét Facebook: {target_url}...", 0)

    # If it's a single video or reel URL
    if "/reel/" in target_url or "/watch" in target_url or "fb.watch" in target_url:
        meta = fetch_facebook_reel_metadata(target_url)
        v_entry = {
            "id": meta["id"],
            "title": meta["title"],
            "url": f"https://www.facebook.com/reel/{meta['id']}" if "/reel/" in target_url else target_url,
            "direct_url": "",
            "cover": meta["cover"],
            "likes": meta["likes"],
            "views": meta["views"],
            "author": meta["author"] or "Facebook Creator",
            "duration": 0,
            "status": "Chờ tải",
        }
        if video_found_cb:
            video_found_cb(v_entry)
        return [v_entry], {"name": v_entry["author"], "total": 1}, None

    videos: List[Dict[str, Any]] = []
    channel_info: Dict[str, Any] = {"name": "Facebook Creator", "total": 0}
    cookies, _, saved_ua = get_saved_platform_cookies("facebook")

    browser = None
    context = None

    try:
        with sync_playwright() as p:
            launch_kwargs: Dict[str, Any] = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-sandbox",
                    "--disable-notifications",
                ],
            }
            if browser_exe_path and os.path.exists(browser_exe_path):
                launch_kwargs["executable_path"] = browser_exe_path
                try:
                    browser = p.chromium.launch(**launch_kwargs)
                except Exception:
                    pass

            if not browser:
                channel_map = {"chrome": "chrome", "edge": "msedge", "coccoc": None}
                ch_name = channel_map.get(browser_id, "chrome")
                for cand in [ch_name, "chrome", "msedge", None]:
                    try:
                        kw = dict(launch_kwargs)
                        kw.pop("executable_path", None)
                        if cand:
                            kw["channel"] = cand
                        browser = p.chromium.launch(**kw)
                        break
                    except Exception:
                        continue

            if not browser:
                return [], channel_info, "Không thể khởi động trình duyệt Chrome/Edge để quét Facebook."

            ua_str = saved_ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            context = browser.new_context(
                viewport={"width": 1280, "height": 850},
                user_agent=ua_str,
                locale="vi-VN",
            )

            # Inject saved Facebook cookies if available
            if cookies:
                pw_cookies = []
                for c in cookies:
                    d = c.get("domain", ".facebook.com")
                    if not d.startswith("."):
                        d = "." + d
                    pw_cookies.append({
                        "name": c["name"],
                        "value": c["value"],
                        "domain": d,
                        "path": c.get("path", "/"),
                    })
                try:
                    context.add_cookies(pw_cookies)
                except Exception as e:
                    logger.debug(f"Không thể nạp cookie Facebook: {e}")

            page = context.new_page()
            _progress("Đang mở trang Facebook và phân tích danh sách video...", 0)
            page.goto(target_url, timeout=35000, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            # Get Page / Channel Name from page title
            doc_title = page.title() or ""
            if "|" in doc_title:
                channel_info["name"] = doc_title.split("|")[0].strip()
            elif doc_title and doc_title != "Facebook":
                channel_info["name"] = doc_title.strip()

            seen_ids = set()
            scroll_attempts = 0
            max_scrolls = 60
            last_count = 0
            stuck_count = 0

            js_extract = """
            () => {
                const results = [];
                // Look for reel links and video links
                const links = Array.from(document.querySelectorAll('a[href*="/reel/"], a[href*="/videos/"]'));
                for (const a of links) {
                    let m = a.href.match(/\\/reel\\/(\\d+)/);
                    let isReel = true;
                    if (!m) {
                        m = a.href.match(/\\/videos\\/(\\d+)/);
                        isReel = false;
                    }
                    if (!m) continue;
                    const id = m[1];

                    // Find container card
                    let container = a;
                    for (let i = 0; i < 6; i++) {
                        if (container && container.querySelector('img')) break;
                        if (container && container.parentElement) container = container.parentElement;
                    }

                    const img = container ? container.querySelector('img') : null;
                    const imgSrc = img ? img.src : '';
                    const text = (container ? container.innerText : a.innerText) || '';

                    // Check duration text (e.g. 2:29:21 or 12:35)
                    let durStr = '';
                    const durMatch = text.match(/\\b(\\d{1,2}:\\d{2}(?::\\d{2})?)\\b/);
                    if (durMatch) {
                        durStr = durMatch[1];
                    }

                    results.push({
                        id: id,
                        url: isReel ? ('https://www.facebook.com/reel/' + id) : ('https://www.facebook.com/watch/?v=' + id),
                        cover: imgSrc,
                        views_str: text.trim().replace(/\\n+/g, ' '),
                        duration_str: durStr,
                    });
                }
                return results;
            }
            """

            js_dismiss_overlay = """
            () => {
                // Dismiss login modals
                const dialogs = document.querySelectorAll('div[role="dialog"]');
                for (const d of dialogs) {
                    const closeBtn = d.querySelector('[aria-label="Đóng"], [aria-label="Close"]');
                    if (closeBtn) {
                        closeBtn.click();
                    } else {
                        d.remove();
                    }
                }
                const overlays = document.querySelectorAll('div[data-pagelet="root"] + div, div[style*="position: fixed"]');
                for (const o of overlays) {
                    if (o.innerText.includes('Đăng nhập') || o.innerText.includes('Log In')) {
                        o.remove();
                    }
                }
                document.body.style.overflow = 'auto';
                document.documentElement.style.overflow = 'auto';
                window.scrollTo(0, document.body.scrollHeight);
            }
            """

            # Queue of raw items to enrich
            raw_items_dict: Dict[str, Dict[str, Any]] = {}
            is_unlimited = (max_videos <= 0 or max_videos >= 99999)
            max_scrolls = 2000 if is_unlimited else max(80, max_videos // 3)

            while scroll_attempts < max_scrolls:
                if _cancelled():
                    break

                # Extract currently loaded items
                try:
                    current_items = page.evaluate(js_extract)
                except Exception:
                    current_items = []

                new_batch = []
                for it in current_items:
                    r_id = it.get("id")
                    if r_id and r_id not in seen_ids:
                        seen_ids.add(r_id)
                        raw_items_dict[r_id] = it
                        new_batch.append(it)

                if new_batch:
                    # Multi-threaded OpenGraph enrichment for fast title / view details
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        future_to_item = {
                            executor.submit(fetch_facebook_reel_metadata, item["url"]): item
                            for item in new_batch
                        }
                        for future in as_completed(future_to_item):
                            orig_item = future_to_item[future]
                            meta = {}
                            try:
                                meta = future.result()
                            except Exception:
                                pass

                            v_title = meta.get("title") or orig_item.get("views_str") or f"Video {orig_item['id']}"
                            v_cover = meta.get("cover") or orig_item.get("cover") or ""
                            v_likes = meta.get("likes") or 0
                            v_views = meta.get("views") or parse_fb_count(orig_item.get("views_str", ""))
                            v_author = meta.get("author") or channel_info["name"]
                            v_duration = parse_fb_duration(orig_item.get("duration_str", ""))

                            entry = {
                                "id": orig_item["id"],
                                "title": v_title,
                                "url": orig_item["url"],
                                "direct_url": "",
                                "cover": v_cover,
                                "likes": v_likes,
                                "views": v_views,
                                "author": v_author,
                                "duration": v_duration,
                                "status": "Chờ tải",
                            }
                            videos.append(entry)
                            if video_found_cb:
                                video_found_cb(entry)

                    _progress(f"Đã quét được {len(videos)} video Facebook...", len(videos))

                if not is_unlimited and len(videos) >= max_videos:
                    break

                if len(seen_ids) == last_count:
                    stuck_count += 1
                    if stuck_count >= 8:
                        break
                else:
                    stuck_count = 0
                last_count = len(seen_ids)

                # Scroll down using wheel and keyboard pagination
                try:
                    page.evaluate(js_dismiss_overlay)
                except Exception:
                    pass

                try:
                    page.mouse.wheel(0, 3500)
                    page.wait_for_timeout(300)
                    page.keyboard.press("PageDown")
                    page.wait_for_timeout(300)
                    page.keyboard.press("End")
                except Exception:
                    pass

                page.wait_for_timeout(1000)
                scroll_attempts += 1

            channel_info["total"] = len(videos)
            browser.close()

            if not videos:
                return [], channel_info, "Không tìm thấy video/reel nào trên trang Facebook này. Hãy đảm bảo kênh ở chế độ công khai hoặc nạp Cookie Facebook."

            return videos, channel_info, None

    except Exception as exc:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        return videos, channel_info, f"Lỗi quét Facebook: {str(exc)}"
