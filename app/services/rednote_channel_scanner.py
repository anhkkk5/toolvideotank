"""RedNote / Xiaohongshu (小红书) Channel & Video Scanner Engine.

Bóc tách danh sách video RedNote / Xiaohongshu kèm metadata và Direct MP4 CDN stream.
Tính năng:
- Bóc tách Link Video đơn / Danh sách nhiều link (hỗ trợ rednote.com, xiaohongshu.com, xhslink.com)
- Bóc tách Kênh / User Profile RedNote
- Trích xuất Direct Stream MP4 không watermark với chất lượng cao nhất (Master H.264 / H.265)
- Hỗ trợ chọn Trình duyệt (Cốc Cốc, Chrome, Edge) và Profile có sẵn
- Tự động nạp ATP Cookie / Web Session nếu có
- Chống giật lag, tự động hủy an toàn khi người dùng nhấn Dừng quét
"""

import os
import sys
import time
import re
import json
import urllib.request
from typing import Callable, Optional, Dict, List, Any, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _clean_str(text: Any) -> str:
    if text is None:
        return ""
    return " ".join(str(text).split())


def _parse_count(val: Any) -> int:
    """Chuyển chuỗi count '100K+', '1.2万', '9,278' thành số nguyên."""
    if not val:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip().replace(",", "")
    try:
        if s.endswith("+"):
            s = s[:-1]
        if s.endswith("K") or s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("M") or s.endswith("m"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("万") or s.endswith("w"):
            return int(float(s[:-1]) * 10000)
        return int(float(s))
    except Exception:
        return 0


def extract_rednote_urls(text: str) -> List[str]:
    """Trích xuất tất cả liên kết RedNote/Xiaohongshu từ văn bản người dùng nhập."""
    pattern = r"https?://[^\s,;\"'<>]+"
    raw_urls = re.findall(pattern, text or "")
    valid = []
    for u in raw_urls:
        u_clean = u.strip()
        if any(d in u_clean.lower() for d in ["rednote.com", "xiaohongshu.com", "xhslink.com"]):
            valid.append(u_clean)
    return valid


def scan_rednote(
    url: str,
    max_videos: int = 200,
    browser_id: str = "chrome",
    profile_id: Optional[str] = None,
    browser_exe_path: Optional[str] = None,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    video_found_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
    is_cancelled_cb: Optional[Callable[[], bool]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Quét video hoặc kênh RedNote (Xiaohongshu).

    Returns:
        (videos_list, channel_info_dict)
    """
    from app.services.cookie_storage_service import get_saved_platform_cookies
    from playwright.sync_api import sync_playwright

    all_videos: Dict[str, Dict[str, Any]] = {}
    channel_info = {
        "name": "",
        "url": url.strip(),
        "total": 0,
        "avatar": "",
        "error_type": "",
    }

    def _log(msg: str):
        print(f"[RedNoteScanner] {msg}")
        if progress_cb:
            progress_cb(msg, len(all_videos))

    def _is_cancelled() -> bool:
        return is_cancelled_cb() if is_cancelled_cb else False

    # 1. Phát hiện danh sách URL nhập vào
    extracted_urls = extract_rednote_urls(url)
    if not extracted_urls and ("rednote.com" in url or "xiaohongshu.com" in url or "xhslink.com" in url):
        extracted_urls = [url.strip()]

    if not extracted_urls:
        _log("Không tìm thấy liên kết RedNote/Xiaohongshu hợp lệ trong chuỗi nhập.")
        return [], channel_info

    # Phân loại: Danh sách các note đơn lẻ hay là 1 trang User Profile
    is_profile_scan = False
    if len(extracted_urls) == 1 and "/user/profile/" in extracted_urls[0]:
        is_profile_scan = True

    _log(f"Đang khởi động trình duyệt ({browser_id.upper()})...")

    with sync_playwright() as p:
        browser = None
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--lang=zh-CN",
            "--window-size=1280,850",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=ProfilePicker,PrivacySandboxSettings4",
            "--disable-gpu",
            "--disable-dev-shm-usage",
        ]
        if profile_id and profile_id != "new_session":
            launch_args.append(f"--profile-directory={profile_id}")

        launch_kwargs = {
            "headless": False,
            "args": launch_args,
        }

        # 1. Ưu tiên đường dẫn exe nếu có (Cốc Cốc, Chrome tùy chỉnh)
        if browser_exe_path and os.path.exists(browser_exe_path):
            launch_kwargs["executable_path"] = browser_exe_path
            try:
                browser = p.chromium.launch(**launch_kwargs)
            except Exception as e:
                _log(f"Không thể mở browser bằng exe_path ({e}), thử channel...")

        # 2. Thử theo channel name
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

        # Nạp Cookies đã lưu
        cookies, _, ua = get_saved_platform_cookies("xiaohongshu")
        context = browser.new_context(
            viewport={"width": 1280, "height": 850},
            locale="zh-CN",
            user_agent=ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        pw_cookies = []
        for c in cookies:
            d = c.get("domain", ".rednote.com")
            # Nạp cookie cho cả rednote.com lẫn xiaohongshu.com
            for target_domain in [".rednote.com", ".xiaohongshu.com"]:
                pw_cookies.append({
                    "name": c["name"],
                    "value": c["value"],
                    "domain": target_domain,
                    "path": c.get("path", "/"),
                })
        if pw_cookies:
            try:
                context.add_cookies(pw_cookies)
                _log(f"Đã nạp {len(pw_cookies)} cookies RedNote vào phiên quét")
            except Exception as e:
                _log(f"Cảnh báo nạp cookie: {e}")

        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

        # ============================================================== #
        #  TRƯỜNG HỢP 1: QUÉT DANH SÁCH NOTE / VIDEO ĐƠN LẺ            #
        # ============================================================== #
        if not is_profile_scan:
            total_items = len(extracted_urls)
            _log(f"Bắt đầu bóc tách {total_items} liên kết RedNote...")

            for idx, target_url in enumerate(extracted_urls):
                if _is_cancelled() or len(all_videos) >= max_videos:
                    break

                _log(f"Đang bóc tách [{idx+1}/{total_items}]: {target_url[:60]}...")
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                    page.wait_for_timeout(2500)

                    # Tự động gỡ mask/popup nếu có
                    page.evaluate("""() => {
                        document.querySelectorAll('.reds-mask, [class*="mask"], .login-container').forEach(el => el.remove());
                    }""")

                    # Bóc tách dữ liệu từ window.__INITIAL_STATE__
                    note_info = page.evaluate("""() => {
                        const state = window.__INITIAL_STATE__ || {};
                        const noteState = state.note || {};
                        const map = noteState.noteDetailMap || {};
                        const unref = (val) => (val && typeof val === 'object' && ('_value' in val || 'value' in val)) ? (val._value !== undefined ? val._value : val.value) : val;

                        for (let k in map) {
                            let item = unref(map[k]);
                            if (!item) continue;
                            let n = unref(item.note) || item;
                            if (n && (n.video || n.title || n.desc)) {
                                return {
                                    noteId: k,
                                    title: n.title || n.desc || '',
                                    desc: n.desc || '',
                                    type: n.type || '',
                                    author: (n.user && n.user.nickname) ? n.user.nickname : '',
                                    avatar: (n.user && n.user.avatar) ? n.user.avatar : '',
                                    likes: (n.interactInfo && n.interactInfo.likedCount) ? n.interactInfo.likedCount : '0',
                                    comments: (n.interactInfo && n.interactInfo.commentCount) ? n.interactInfo.commentCount : '0',
                                    shares: (n.interactInfo && n.interactInfo.shareCount) ? n.interactInfo.shareCount : '0',
                                    cover: (n.image && n.image.thumbnailFileid) ? n.image.thumbnailFileid : (n.imageList && n.imageList[0] ? n.imageList[0].urlDefault : ''),
                                    video: n.video || null
                                };
                            }
                        }
                        return null;
                    }""")

                    current_url = page.url
                    # Trích xuất noteId từ URL nếu có
                    m_id = re.search(r"/(?:item|explore)/([a-zA-Z0-9]+)", current_url)
                    note_id = m_id.group(1) if m_id else f"note_{idx+1}"

                    direct_url = ""
                    title = ""
                    cover = ""
                    author = ""
                    likes = 0
                    comments = 0
                    shares = 0
                    duration = 0

                    if note_info:
                        if note_info.get("noteId") and note_info["noteId"] != "undefined":
                            note_id = note_info["noteId"]
                        title = _clean_str(note_info.get("title") or note_info.get("desc"))
                        author = _clean_str(note_info.get("author"))
                        cover = note_info.get("cover") or ""
                        likes = _parse_count(note_info.get("likes"))
                        comments = _parse_count(note_info.get("comments"))
                        shares = _parse_count(note_info.get("shares"))

                        # Trích xuất Master Video Stream URL (Không watermark)
                        v_obj = note_info.get("video") or {}
                        media = v_obj.get("media") or {}
                        stream = media.get("stream") or {}
                        h264_list = stream.get("h264") or []
                        h265_list = stream.get("h265") or []

                        if h264_list and isinstance(h264_list, list) and h264_list[0].get("masterUrl"):
                            direct_url = h264_list[0]["masterUrl"]
                        elif h265_list and isinstance(h265_list, list) and h265_list[0].get("masterUrl"):
                            direct_url = h265_list[0]["masterUrl"]
                        elif h264_list and h264_list[0].get("backupUrls"):
                            direct_url = h264_list[0]["backupUrls"][0]

                        duration = v_obj.get("duration") or (v_obj.get("capa") or {}).get("duration", 0)

                    # Fallback bóc tách từ DOM nếu State chưa nạp đủ
                    if not direct_url:
                        video_el = page.query_selector("video")
                        if video_el:
                            direct_url = video_el.get_attribute("src") or ""
                            if not cover:
                                cover = video_el.get_attribute("poster") or ""

                    if not title:
                        title_el = page.query_selector("#detail-title, .title, .desc, .note-content")
                        if title_el:
                            title = _clean_str(title_el.inner_text())

                    if not author:
                        author_el = page.query_selector(".username, .name, .author")
                        if author_el:
                            author = _clean_str(author_el.inner_text())

                    if not title:
                        title = f"RedNote Video {len(all_videos) + 1}"

                    # Nếu không tìm thấy video direct_url (có thể là bài viết chỉ có ảnh)
                    if not direct_url:
                        _log(f"Liên kết [{idx+1}] không chứa video stream trực tiếp (có thể là bài viết ảnh).")
                        continue

                    v_entry = {
                        "id": note_id,
                        "title": title,
                        "url": current_url,
                        "direct_url": direct_url,
                        "cover": cover,
                        "likes": likes,
                        "views": 0,
                        "comments": comments,
                        "shares": shares,
                        "author": author,
                        "duration": duration,
                        "status": "Chờ tải",
                    }
                    all_videos[note_id] = v_entry
                    if video_found_cb:
                        video_found_cb(v_entry)
                    _log(f"Bắt thành công video: {title[:40]}... (Thích: {likes})")

                except Exception as e:
                    _log(f"Lỗi khi đọc liên kết {target_url[:50]}: {e}")

            channel_info["total"] = len(all_videos)

        # ============================================================== #
        #  TRƯỜNG HỢP 2: QUÉT TOÀN BỘ KÊNH / USER PROFILE REDNOTE       #
        # ============================================================== #
        else:
            profile_url = extracted_urls[0]
            _log(f"Đang kết nối tới kênh RedNote: {profile_url}...")

            try:
                page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3500)

                # Bỏ qua popup mask
                page.evaluate("""() => {
                    document.querySelectorAll('.reds-mask, [class*="mask"], .login-container').forEach(el => el.remove());
                }""")

                # 1. Trích xuất thông tin Kênh / Tác giả
                u_info = page.evaluate("""() => {
                    const state = window.__INITIAL_STATE__ || {};
                    const user = state.user || {};
                    const unref = (val) => (val && typeof val === 'object' && ('_value' in val || 'value' in val)) ? (val._value !== undefined ? val._value : val.value) : val;
                    const pageData = unref(user.userPageData) || {};
                    const basic = unref(pageData.basicInfo) || {};
                    return {
                        name: basic.nickname || '',
                        avatar: basic.images || basic.imageb || '',
                        desc: basic.desc || ''
                    };
                }""")
                if u_info:
                    channel_info["name"] = _clean_str(u_info.get("name"))
                    channel_info["avatar"] = u_info.get("avatar", "")
                if not channel_info["name"]:
                    author_el = page.query_selector(".user-name, .user-nickname, .name")
                    if author_el:
                        channel_info["name"] = _clean_str(author_el.inner_text())

                _log(f"Đã nhận diện kênh: {channel_info['name']}")

                # 2. Cuộn trang để tải thêm video (cuộn thông minh, dừng khi hết nội dung mới)
                _log("Đang cuộn tải danh sách bài đăng của kênh...")
                prev_height = 0
                no_change_count = 0
                for scroll_step in range(30):
                    if _is_cancelled():
                        break
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    page.wait_for_timeout(1000)
                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == prev_height:
                        no_change_count += 1
                        if no_change_count >= 3:
                            _log("Đã cuộn hết nội dung kênh.")
                            break
                    else:
                        no_change_count = 0
                    prev_height = new_height
                    _log(f"Cuộn [{scroll_step+1}]... đang tải thêm bài đăng")

                # 3. Thu thập danh sách thẻ video từ Vue State
                notes_data = page.evaluate("""() => {
                    const state = window.__INITIAL_STATE__ || {};
                    const user = state.user || {};
                    const unref = (val) => (val && typeof val === 'object' && ('_value' in val || 'value' in val)) ? (val._value !== undefined ? val._value : val.value) : val;

                    const rawNotes = unref(user.notes);
                    if (!Array.isArray(rawNotes)) return [];

                    let items = [];
                    rawNotes.forEach(col => {
                        let arr = unref(col);
                        if (!Array.isArray(arr)) return;
                        arr.forEach(it => {
                            let n = unref(it);
                            let card = unref(n.noteCard) || n;
                            let title = card.displayTitle || card.title || '';
                            let type = card.type || '';
                            let cover = '';
                            if (card.cover) {
                                cover = card.cover.urlDefault || card.cover.urlPre || '';
                                if (!cover && card.cover.infoList && card.cover.infoList[0]) {
                                    cover = card.cover.infoList[0].url;
                                }
                            }
                            let likes = (card.interactInfo && card.interactInfo.likedCount) ? card.interactInfo.likedCount : '0';
                            let nid = card.noteId || n.id || '';
                            let xsec = card.xsecToken || n.xsecToken || '';

                            items.push({
                                noteId: nid,
                                title: title,
                                type: type,
                                cover: cover,
                                likes: likes,
                                xsecToken: xsec
                            });
                        });
                    });
                    return items;
                }""")

                _log(f"Tìm thấy {len(notes_data)} bài đăng trong trạng thái kênh. Đang lọc bài dạng Video...")

                # Lọc bài video
                video_notes = [n for n in notes_data if n.get("type") == "video"]
                if not video_notes:
                    # Nếu type không ghi rõ 'video', kiểm tra tất cả bài đăng
                    video_notes = notes_data

                # Thu thập metadata nhanh từ profile state — KHÔNG goto từng video
                _log(f"Đang thu thập {len(video_notes)} video từ kênh (chế độ nhanh)...")
                for idx, vn in enumerate(video_notes):
                    if _is_cancelled() or len(all_videos) >= max_videos:
                        break

                    vid = vn.get("noteId") or f"rednote_{idx+1}"
                    v_title = _clean_str(vn.get("title")) or f"Video {idx+1}"
                    v_cover = vn.get("cover") or ""
                    v_likes = _parse_count(vn.get("likes"))

                    # Xây URL video (direct_url sẽ được resolve khi tải)
                    v_url = f"https://www.rednote.com/discovery/item/{vid}" if vn.get("noteId") else profile_url
                    if vn.get("noteId") and vn.get("xsecToken"):
                        v_url += f"?xsec_token={vn['xsecToken']}&xsec_source=pc_user"

                    v_entry = {
                        "id": vid,
                        "title": v_title,
                        "url": v_url,
                        "direct_url": "",
                        "cover": v_cover,
                        "likes": v_likes,
                        "views": 0,
                        "comments": 0,
                        "shares": 0,
                        "author": channel_info["name"],
                        "duration": 0,
                        "status": "Chờ tải",
                    }
                    all_videos[vid] = v_entry
                    if video_found_cb:
                        video_found_cb(v_entry)
                    _log(f"Bắt được [{len(all_videos)}/{len(video_notes)}]: {v_title[:35]}...")

                channel_info["total"] = len(all_videos)

            except Exception as e:
                _log(f"Lỗi quét kênh RedNote: {e}")

        browser.close()

    _log(f"Hoàn thành quét RedNote. Tìm thấy {len(all_videos)} video.")
    return list(all_videos.values()), channel_info
