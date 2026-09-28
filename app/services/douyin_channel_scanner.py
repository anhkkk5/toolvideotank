"""Douyin Channel & Video Scanner Engine - Bóc tách danh sách video Douyin kèm metadata.

Tính năng:
- Bắt trực tiếp API aweme/v1/web/aweme/post qua Playwright
- Tự động nhận diện has_more để dừng cuộn ngay khi hết video
- Hỗ trợ chọn Trình duyệt (Cốc Cốc, Chrome, Edge) và Profile cụ thể
- Chống hiện màn hình Profile Picker ("Ai sẽ sử dụng Chrome?")
- Tự động phát hiện Cookie hết hạn / "服务异常" và báo cho người dùng lấy lại cookie
- Loại bỏ 100% video rác từ DOM đề xuất / sidebar
- Chặn stream media nặng trong browser để chống giật lag tối đa
"""

import os
import sys
import time
import json
import re
from typing import Callable, Optional, Dict, List, Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def scan_douyin_channel(
    channel_url: str,
    max_videos: int = 200,
    browser_id: str = "chrome",
    profile_id: Optional[str] = None,
    browser_exe_path: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    video_found_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_cancelled_cb: Optional[Callable[[], bool]] = None,
) -> tuple:
    """Quét toàn bộ video của kênh Douyin với trình duyệt và profile được chọn.

    Returns:
        (videos_list, channel_info_dict)
    """
    from app.services.cookie_storage_service import get_saved_douyin_cookies
    from playwright.sync_api import sync_playwright

    cookies, _, ua = get_saved_douyin_cookies()
    clean_url = channel_url.split("?")[0]

    all_videos: Dict[str, Dict[str, Any]] = {}
    channel_info = {
        "name": "",
        "url": clean_url,
        "total": 0,
        "avatar": "",
        "error_type": "",
    }
    has_more_videos = True
    cookie_expired_detected = False

    def _log(msg: str):
        print(f"[DouyinScanner] {msg}")
        if progress_cb:
            progress_cb(msg, len(all_videos))

    _log(f"Đang khởi tạo trình duyệt ({browser_id.upper()})...")

    with sync_playwright() as p:
        browser = None
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--lang=zh-CN",
            "--window-size=1200,800",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=ProfilePicker,PrivacySandboxSettings4",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
        ]
        if profile_id and profile_id != "new_session":
            launch_args.append(f"--profile-directory={profile_id}")

        # Determine launch mode
        launch_kwargs = {
            "headless": False,
            "args": launch_args,
        }

        # 1. Try specified executable path first if provided (e.g. Cốc Cốc)
        if browser_exe_path and os.path.exists(browser_exe_path):
            launch_kwargs["executable_path"] = browser_exe_path
            try:
                browser = p.chromium.launch(**launch_kwargs)
            except Exception as e:
                _log(f"Không thể mở browser bằng exe_path ({e}), thử channel...")

        # 2. Try by channel name
        if not browser:
            channel_map = {"chrome": "chrome", "edge": "msedge", "coccoc": None}
            ch_name = channel_map.get(browser_id, "chrome")
            for candidate in [ch_name, "chrome", "msedge", None]:
                try:
                    kw = dict(launch_kwargs)
                    kw.pop("executable_path", None)
                    if candidate:
                        kw["channel"] = candidate
                    browser = p.chromium.launch(**kw)
                    break
                except Exception:
                    continue

        if not browser:
            raise RuntimeError("Không thể khởi động trình duyệt! Vui lòng kiểm tra lại Google Chrome hoặc Cốc Cốc trên máy.")

        context = browser.new_context(
            viewport={"width": 1200, "height": 800},
            locale="zh-CN",
            user_agent=ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        # Inject ATP cookies
        pw_cookies = []
        for c in cookies:
            domain = c.get("domain", ".douyin.com")
            if not domain.startswith("."):
                domain = "." + domain
            pw_cookies.append({
                "name": c["name"],
                "value": c["value"],
                "domain": domain,
                "path": c.get("path", "/"),
            })
        try:
            context.add_cookies(pw_cookies)
            _log(f"Đã nạp {len(pw_cookies)} cookies vào phiên quét")
        except Exception as e:
            _log(f"Cảnh báo nạp cookie: {e}")

        def handle_response(response):
            nonlocal has_more_videos, cookie_expired_detected
            u = response.url or ""
            if "aweme/v1/web/aweme/post" in u or "aweme/post" in u:
                try:
                    data = response.json()

                    # Check for login / session rejection
                    status_code = data.get("status_code", 0)
                    status_msg = str(data.get("status_msg", "")).lower()
                    if status_code != 0 or "login" in status_msg:
                        _log(f"Douyin API báo mã lỗi {status_code}: {data.get('status_msg')}")
                        if status_code in [403, 10001] or "login" in status_msg or "cookie" in status_msg:
                            cookie_expired_detected = True

                    aweme_list = data.get("aweme_list", [])

                    # Check pagination flag from Douyin API
                    api_has_more = data.get("has_more")
                    if api_has_more is False or api_has_more == 0:
                        has_more_videos = False
                        _log("Douyin API báo cáo: Đã lấy trọn vẹn danh sách video của kênh.")

                    new_in_page = 0
                    for item in aweme_list:
                        aid = item.get("aweme_id")
                        if aid and aid not in all_videos:
                            cover = ""
                            video_obj = item.get("video", {})
                            if video_obj.get("cover") and video_obj["cover"].get("url_list"):
                                cover = video_obj["cover"]["url_list"][0]

                            author = item.get("author", {}).get("nickname", "")
                            if author and not channel_info["name"]:
                                channel_info["name"] = author
                            if item.get("author", {}).get("avatar_thumb", {}).get("url_list"):
                                channel_info["avatar"] = item["author"]["avatar_thumb"]["url_list"][0]

                            stats = item.get("statistics", {})

                            # Direct video CDN stream url (No Watermark)
                            direct_play_url = ""
                            play_addr = video_obj.get("play_addr", {})
                            if play_addr.get("url_list"):
                                direct_play_url = play_addr["url_list"][0]
                            elif video_obj.get("download_addr", {}).get("url_list"):
                                direct_play_url = video_obj["download_addr"]["url_list"][0]

                            desc = item.get("desc", "").strip()

                            v_entry = {
                                "id": aid,
                                "title": desc or f"Video {len(all_videos) + 1}",
                                "url": f"https://www.douyin.com/video/{aid}",
                                "direct_url": direct_play_url,
                                "cover": cover,
                                "likes": stats.get("digg_count", 0),
                                "views": stats.get("play_count", 0),
                                "comments": stats.get("comment_count", 0),
                                "shares": stats.get("share_count", 0),
                                "author": author,
                                "duration": video_obj.get("duration", 0),
                                "create_time": item.get("create_time", 0),
                                "status": "Chờ tải",
                            }
                            all_videos[aid] = v_entry
                            new_in_page += 1
                            if video_found_cb:
                                video_found_cb(v_entry)

                    if new_in_page > 0:
                        _log(f"Bắt được {new_in_page} video (Tổng: {len(all_videos)})")
                except Exception:
                    pass

            if "user/profile" in u or "user/other" in u:
                try:
                    data = response.json()
                    user = data.get("user", {})
                    if user.get("nickname") and not channel_info["name"]:
                        channel_info["name"] = user["nickname"]
                except Exception:
                    pass

        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page.on("response", handle_response)

        # Block media streaming to prevent browser lag and save network bandwidth
        def block_media_stream(route):
            if route.request.resource_type in ["media"]:
                route.abort()
            else:
                route.continue_()
        page.route("**/*", block_media_stream)

        _log("Đang khởi tạo phiên làm việc Douyin...")
        try:
            page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
        except Exception as e:
            _log(f"Khởi tạo phiên trang chủ: {e}")

        _log(f"Đang kết nối tới kênh: {clean_url}")
        try:
            page.goto(clean_url, wait_until="domcontentloaded", timeout=25000)
        except Exception as e:
            _log(f"Thông báo tải trang: {e}")

        page.wait_for_timeout(3500)

        # Auto-retry: If Douyin shows "服务异常" or "重新刷新", click "刷新" automatically!
        for retry_idx in range(2):
            has_err = page.evaluate("() => document.body && (document.body.innerText.includes('服务异常') || document.body.innerText.includes('重新刷新'))")
            if has_err:
                _log(f"Douyin thông báo cần làm mới, đang tự động bấm '刷新' (lần {retry_idx + 1})...")
                page.evaluate("""() => {
                    const btn = Array.from(document.querySelectorAll('span, a, button')).find(e => e.innerText && e.innerText.trim() === '刷新');
                    if (btn) btn.click();
                }""")
                page.wait_for_timeout(3000)
            else:
                break

        # Check for Douyin service error or expired session ("服务异常" / Captcha)
        body_text = page.evaluate("() => document.body ? document.body.innerText.substring(0, 10000) : ''")
        if "服务异常" in body_text or "重新刷新拉取数据" in body_text:
            _log("⚠️ Phát hiện Douyin báo '服务异常' (Dịch vụ bất thường) -> Cookie đã hết hạn hoặc phiên đăng nhập không hợp lệ!")
            cookie_expired_detected = True

        # Captcha detection & resolution helper
        title = page.title()
        if "验证码" in title or "verify" in page.url.lower():
            _log("⚠️ Douyin yêu cầu xác thực: Vui lòng kéo mảnh ghép trượt trên trình duyệt...")
            for _ in range(60):
                if is_cancelled_cb and is_cancelled_cb():
                    browser.close()
                    return list(all_videos.values()), channel_info
                page.wait_for_timeout(1000)
                cur_title = page.title()
                if "验证码" not in cur_title and "verify" not in page.url.lower():
                    _log("✅ Xác thực thành công! Đang bóc tách video...")
                    page.wait_for_timeout(1500)
                    break

        # Check RENDER_DATA for pre-rendered videos (ONLY if valid items exist)
        render_videos = page.evaluate("""() => {
            const s = document.querySelector('script#RENDER_DATA');
            if (!s) return null;
            try {
                const data = JSON.parse(decodeURIComponent(s.textContent));
                const list = [];
                let chName = '';
                const scan = (o, depth) => {
                    if (depth > 8 || !o || typeof o !== 'object') return;
                    if (Array.isArray(o)) { o.forEach(x => scan(x, depth + 1)); return; }
                    if (o.aweme_id && typeof o.aweme_id === 'string' && o.aweme_id.length > 5) {
                        let cover = '';
                        let direct = '';
                        if (o.video) {
                            if (o.video.cover && o.video.cover.url_list) cover = o.video.cover.url_list[0];
                            if (o.video.play_addr && o.video.play_addr.url_list) direct = o.video.play_addr.url_list[0];
                        }
                        const title = (o.desc || '').trim();
                        if (title || cover || direct) {
                            list.push({
                                id: o.aweme_id,
                                title: title,
                                url: 'https://www.douyin.com/video/' + o.aweme_id,
                                direct_url: direct,
                                cover: cover,
                                likes: (o.statistics && o.statistics.digg_count) || 0,
                                views: (o.statistics && o.statistics.play_count) || 0,
                                author: (o.author && o.author.nickname) || '',
                                status: 'Chờ tải',
                            });
                        }
                    }
                    if (o.nickname && !chName) chName = o.nickname;
                    Object.values(o).forEach(v => scan(v, depth + 1));
                };
                scan(data, 0);
                return {list, chName};
            } catch(e) { return null; }
        }""")

        if render_videos and render_videos.get("list"):
            if not channel_info["name"]:
                channel_info["name"] = render_videos.get("chName", "")
            for v in render_videos["list"]:
                if v["id"] not in all_videos:
                    all_videos[v["id"]] = v
                    if video_found_cb:
                        video_found_cb(v)

        # Detect channel name
        if not channel_info["name"]:
            h1 = page.evaluate("() => document.querySelector('h1')?.innerText?.trim() || ''")
            if h1:
                channel_info["name"] = h1
            else:
                t = page.title()
                if "的主页" in t:
                    channel_info["name"] = t.split("的主页")[0].strip()
                elif " - 抖音" in t:
                    channel_info["name"] = t.split(" - 抖音")[0].strip()

        _log(f"Kênh: '{channel_info['name']}'. Bắt đầu quét...")

        # Dismiss any overlays or login modals
        page.evaluate("""() => {
            document.querySelectorAll('[class*="login-guide"], [class*="LoginGuide"], [class*="modal"], [class*="mask"]').forEach(el => {
                try { el.remove(); } catch(e) {}
            });
        }""")

        # Fast intelligent scrolling
        stable_rounds = 0
        max_scroll_rounds = max(5, min(60, max_videos // 10 + 3))

        for scroll_idx in range(max_scroll_rounds):
            if is_cancelled_cb and is_cancelled_cb():
                _log("Người dùng đã hủy quét.")
                break

            if not has_more_videos:
                _log("Đã lấy trọn vẹn danh sách video của kênh (has_more=0). Dừng cuộn.")
                break

            prev_count = len(all_videos)
            page.mouse.wheel(0, 3600)
            page.wait_for_timeout(1300)

            cur_count = len(all_videos)
            if cur_count > prev_count:
                stable_rounds = 0
                _log(f"Đang quét... Đã tìm thấy {cur_count} video")
            else:
                stable_rounds += 1
                if cur_count == 0 and stable_rounds <= 2:
                    # Click tab '作品' to ensure active tab
                    page.evaluate("""() => {
                        const tab = Array.from(document.querySelectorAll('div, span')).find(e => e.innerText && e.innerText.trim().startsWith('作品') && e.children.length === 0);
                        if (tab) tab.click();
                    }""")
                    page.wait_for_timeout(1000)

                if cur_count == 0 and stable_rounds >= 3:
                    # Check if page is showing error / service exception
                    body_check = page.evaluate("() => document.body ? document.body.innerText.substring(0, 10000) : ''")
                    if "服务异常" in body_check or "重新刷新拉取数据" in body_check:
                        _log("⚠️ Douyin hiển thị '服务异常' -> Dừng quét do cookie/phiên hết hạn.")
                        cookie_expired_detected = True
                        break

                if stable_rounds >= 4:
                    _log("Không có video mới sau 4 lần cuộn. Hoàn tất quét.")
                    break

            if cur_count >= max_videos:
                _log(f"Đã đạt giới hạn tối đa {max_videos} video.")
                break

        # Fallback extraction from DOM video cards (strictly validated)
        if len(all_videos) == 0:
            dom_items = page.evaluate("""() => {
                const list = [];
                document.querySelectorAll('a[href*="/video/"]').forEach(a => {
                    const m = a.href.match(/\\/video\\/(\\d+)/);
                    if (!m) return;
                    const vid = m[1];
                    const img = a.querySelector('img');
                    const cover = img ? (img.src || img.getAttribute('data-src') || '') : '';
                    const titleEl = a.querySelector('p, span, [class*="title"], [class*="desc"]');
                    const title = titleEl ? titleEl.innerText.trim() : (a.title || '');
                    if (title || cover) {
                        list.push({
                            id: vid,
                            title: title || ('Video ' + vid),
                            url: 'https://www.douyin.com/video/' + vid,
                            direct_url: '',
                            cover: cover,
                            likes: 0,
                            views: 0,
                            author: '',
                            status: 'Chờ tải'
                        });
                    }
                });
                return list;
            }""")
            if dom_items:
                for v in dom_items:
                    if v["id"] not in all_videos:
                        all_videos[v["id"]] = v
                        if video_found_cb:
                            video_found_cb(v)
                _log(f"Đã trích xuất {len(dom_items)} video từ giao diện trang.")

        # Save any refreshed cookies
        try:
            from app.services.cookie_storage_service import save_douyin_cookies
            new_cookies = context.cookies()
            if new_cookies:
                save_douyin_cookies(new_cookies)
        except Exception:
            pass

        browser.close()

    # Filter out any malformed empty items
    cleaned_videos = [
        v for v in all_videos.values()
        if (v.get("title") or v.get("cover") or v.get("direct_url") or (v.get("likes", 0) > 0))
    ]

    channel_info["total"] = len(cleaned_videos)

    # Check if failed due to expired cookie
    if len(cleaned_videos) == 0:
        if cookie_expired_detected:
            channel_info["error_type"] = "COOKIE_EXPIRED"
            _log("⚠️ Quét thất bại do Cookie Douyin đã hết hạn hoặc phiên đăng nhập không hợp lệ.")
        else:
            channel_info["error_type"] = "NO_VIDEOS_OR_COOKIE_EXPIRED"
            _log("⚠️ Không tìm thấy video nào (kiểm tra lại link kênh hoặc cập nhật cookie mới).")
    else:
        _log(f"Quét hoàn tất: Tìm thấy đúng {len(cleaned_videos)} video của kênh '{channel_info['name']}'")

    return cleaned_videos, channel_info
