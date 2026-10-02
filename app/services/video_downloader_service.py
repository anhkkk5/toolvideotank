"""Video Downloader Service – tải video từ các nền tảng mạng xã hội.

Hỗ trợ: YouTube, TikTok, Douyin, Bilibili, Xiaohongshu (小红书/RED)
Đặc điểm:
  - Không logo / watermark
  - Không cần đăng nhập
  - Hỗ trợ HD, Full HD
  - Tải nhanh chóng
"""

import os
import re
import json
import time
import threading
from typing import Optional, Callable

# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

_PLATFORM_PATTERNS = {
    "youtube": [
        r"(?:youtube\.com|youtu\.be)",
    ],
    "tiktok": [
        r"(?:tiktok\.com|vm\.tiktok\.com)",
    ],
    "douyin": [
        r"(?:douyin\.com|iesdouyin\.com)",
    ],
    "bilibili": [
        r"(?:bilibili\.com|b23\.tv)",
    ],
    "xiaohongshu": [
        r"(?:xiaohongshu\.com|xhslink\.com|小红书)",
    ],
}


def extract_url_from_text(text: str) -> str:
    """Extract a valid URL from share text.

    Social apps (Douyin, TikTok, Xiaohongshu) copy share text that contains
    the actual URL surrounded by description text.  For example:

        "0.20 HvS:/ ... https://v.douyin.com/IPxMB92X9vY/ 复制此链接..."

    This function finds and returns the first valid HTTP(S) URL.
    If the input already is a clean URL, it is returned as-is.
    """
    text = text.strip()

    # If the whole text is already a URL, return it directly
    if re.match(r'^https?://', text) and ' ' not in text:
        return _normalize_platform_url(text)

    # Find all URLs in the text
    url_pattern = r'https?://[^\s<>"\'\u3000\uff0c\u3001\uff01\uff1f\u300a\u300b\u201c\u201d\u2018\u2019]+'
    urls = re.findall(url_pattern, text)

    if not urls:
        # Some share texts use short codes without http – try to find
        # domain patterns like v.douyin.com/xxx
        domain_pattern = r'(?:v\.douyin\.com|vm\.tiktok\.com|xhslink\.com|b23\.tv)/[A-Za-z0-9_\-/]+'
        matches = re.findall(domain_pattern, text)
        if matches:
            return _normalize_platform_url('https://' + matches[0])
        return text  # fallback: return original

    # Prefer known platform URLs
    priority_domains = [
        'douyin.com', 'tiktok.com', 'youtube.com', 'youtu.be',
        'bilibili.com', 'b23.tv', 'xiaohongshu.com', 'xhslink.com',
    ]
    for url in urls:
        for domain in priority_domains:
            if domain in url.lower():
                # Clean trailing punctuation
                url = re.sub(r'[)\]}>，。！？]+$', '', url)
                return _normalize_platform_url(url)

    # Return first URL found, cleaned
    first = re.sub(r'[)\]}>，。！？]+$', '', urls[0])
    return _normalize_platform_url(first)


def _normalize_platform_url(url: str) -> str:
    """Normalize platform-specific URLs to formats yt-dlp supports.

    - Douyin short links (v.douyin.com) → follow redirect → douyin.com/video/ID
    - iesdouyin.com/share/video/ID → douyin.com/video/ID
    - douyin.com/jingxuan?modal_id=ID → douyin.com/video/ID
    - b23.tv short links → follow redirect → bilibili.com/video/BVxxx
    """
    url_lower = url.lower()

    # --- iesdouyin.com/share/video/ID → douyin.com/video/ID ---
    m = re.search(r'iesdouyin\.com/share/video/(\d+)', url_lower)
    if m:
        video_id = m.group(1)
        return f"https://www.douyin.com/video/{video_id}"

    # --- douyin.com/jingxuan?modal_id=ID → douyin.com/video/ID ---
    m = re.search(r'douyin\.com/.*[?&]modal_id=(\d+)', url)
    if m:
        video_id = m.group(1)
        return f"https://www.douyin.com/video/{video_id}"

    # --- v.douyin.com short link → resolve redirect ---
    if 'v.douyin.com' in url_lower:
        resolved = _resolve_douyin_short_url(url)
        if resolved:
            return resolved

    return url


def _resolve_douyin_short_url(short_url: str) -> str:
    """Follow v.douyin.com redirect to get the real video URL.

    Returns a clean douyin.com/video/ID URL or empty string on failure.
    """
    import urllib.request
    import urllib.error

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    try:
        req = urllib.request.Request(short_url, headers=headers, method="GET")
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        resp = opener.open(req, timeout=10)
        final_url = resp.url or ""
        resp.close()
    except urllib.error.HTTPError as e:
        final_url = e.headers.get("Location", "") if hasattr(e, "headers") else ""
    except Exception:
        try:
            req = urllib.request.Request(short_url, headers=headers, method="HEAD")
            resp = urllib.request.urlopen(req, timeout=10)
            final_url = resp.url or ""
            resp.close()
        except Exception:
            return ""

    if not final_url:
        return ""

    # Extract video ID from the final URL
    # Patterns: douyin.com/video/123, iesdouyin.com/share/video/123, modal_id=123
    for pattern in [
        r'(?:douyin\.com/video|iesdouyin\.com/share/video)/(\d+)',
        r'modal_id=(\d+)',
    ]:
        m = re.search(pattern, final_url)
        if m:
            return f"https://www.douyin.com/video/{m.group(1)}"

    # If final URL is already a usable douyin.com URL, return it
    if 'douyin.com' in final_url and 'iesdouyin' not in final_url:
        return final_url.split('?')[0]

    return ""


def get_available_browsers() -> list:
    """Detect installed Chromium/Edge browsers on Windows for scraping/cookies."""
    browsers = []

    # 1. Cốc Cốc (Vietnamese browser based on Chromium)
    coccoc_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\CocCoc\Browser\Application\browser.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\CocCoc\Browser\Application\browser.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\CocCoc\Browser\Application\browser.exe"),
    ]
    for p in coccoc_paths:
        if os.path.exists(p):
            browsers.append({
                "id": "coccoc",
                "name": "Cốc Cốc",
                "path": p,
                "driver_type": "chrome",
            })
            break

    # 2. Google Chrome
    chrome_paths = [
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            browsers.append({
                "id": "chrome",
                "name": "Google Chrome",
                "path": p,
                "driver_type": "chrome",
            })
            break

    # 3. Microsoft Edge (Pre-installed on Windows 10/11)
    edge_paths = [
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in edge_paths:
        if os.path.exists(p):
            browsers.append({
                "id": "edge",
                "name": "Microsoft Edge",
                "path": p,
                "driver_type": "edge",
            })
            break

    # 4. Brave
    brave_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for p in brave_paths:
        if os.path.exists(p):
            browsers.append({
                "id": "brave",
                "name": "Brave",
                "path": p,
                "driver_type": "chrome",
            })
            break

    return browsers


def create_headless_driver(
    preferred_browser_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    enable_images: bool = False,
):
    """Create a high-performance headless Selenium WebDriver using an installed browser.

    Supports Cốc Cốc, Google Chrome, Microsoft Edge, and Brave.
    Uses 'eager' page load strategy. Disables images by default for faster scraping.
    Returns (driver, browser_name) or raises RuntimeError.
    """
    from selenium import webdriver

    available = get_available_browsers()
    if not available:
        # Fallback to default selenium path resolution
        available = [
            {"id": "chrome", "name": "Chrome", "path": None, "driver_type": "chrome"},
            {"id": "edge", "name": "Edge", "path": None, "driver_type": "edge"},
        ]

    # Reorder candidates based on user preference
    if preferred_browser_id and preferred_browser_id != "auto":
        match = [b for b in available if b["id"] == preferred_browser_id]
        rest = [b for b in available if b["id"] != preferred_browser_id]
        candidate_list = match + rest
    else:
        candidate_list = available

    last_err = None
    for b in candidate_list:
        b_name = b["name"]
        b_type = b["driver_type"]
        b_path = b.get("path")

        try:
            if b_type == "edge":
                from selenium.webdriver.edge.options import Options as EdgeOptions
                options = EdgeOptions()
                if b_path and os.path.exists(b_path):
                    options.binary_location = b_path
                options.page_load_strategy = "eager"
                options.add_argument("--headless=new")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-gpu")
                options.add_argument("--window-size=1280,720")
                options.add_argument("--lang=zh-CN")
                if user_agent:
                    options.add_argument(f"--user-agent={user_agent}")
                if not enable_images:
                    options.add_argument("--blink-settings=imagesEnabled=false")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option("useAutomationExtension", False)
                driver = webdriver.Edge(options=options)
            else:
                from selenium.webdriver.chrome.options import Options as ChromeOptions
                options = ChromeOptions()
                if b_path and os.path.exists(b_path):
                    options.binary_location = b_path
                options.page_load_strategy = "eager"
                options.add_argument("--headless=new")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-gpu")
                options.add_argument("--window-size=1280,720")
                options.add_argument("--lang=zh-CN")
                if user_agent:
                    options.add_argument(f"--user-agent={user_agent}")
                if not enable_images:
                    options.add_argument("--blink-settings=imagesEnabled=false")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option("useAutomationExtension", False)
                driver = webdriver.Chrome(options=options)

            driver.set_page_load_timeout(15)
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            })
            return driver, b_name
        except Exception as exc:
            last_err = exc
            print(f"[VideoDownloader] Browser {b_name} startup failed: {exc}")
            continue

    raise RuntimeError(f"Không thể khởi động trình duyệt (Cốc Cốc, Chrome, Edge): {last_err}")


def _get_douyin_cookie_file(cache_dir: str, preferred_browser: Optional[str] = None) -> str:
    """Generate fresh Douyin session cookies (no login required).

    yt-dlp's Douyin extractor requires JS-rendered session cookies.
    Strategy (in order):
      1. Selenium headless (Cốc Cốc, Chrome, Edge)
      2. urllib-based ttwid fetch (fallback)
    """
    # 0. Check custom saved cookies (from ATP Cookie / user paste)
    try:
        from app.services.cookie_storage_service import get_saved_douyin_cookies
        _, custom_cookie_path, _ = get_saved_douyin_cookies()
        if custom_cookie_path and os.path.exists(custom_cookie_path):
            return custom_cookie_path
    except Exception:
        pass

    cookie_path = os.path.join(cache_dir, "douyin_cookies.txt")

    # Reuse existing cookies if fresh (< 2 hours)
    if os.path.exists(cookie_path):
        age = time.time() - os.path.getmtime(cookie_path)
        if age < 7200:
            return cookie_path

    os.makedirs(cache_dir, exist_ok=True)

    # ---- Primary: Selenium headless browser ----
    try:
        result = _get_douyin_cookies_selenium(cookie_path, preferred_browser=preferred_browser)
        if result:
            return result
    except Exception as exc:
        print(f"[VideoDownloader] Selenium cookie error: {exc}")

    # ---- Fallback: urllib ----
    return _get_douyin_cookies_urllib(cookie_path)


def _get_douyin_cookies_selenium(cookie_path: str, preferred_browser: Optional[str] = None) -> str:
    """Use Selenium headless browser (Cốc Cốc, Chrome, Edge) to get real Douyin cookies.

    No browser login (Google or Douyin) is required.
    """
    try:
        driver, browser_name = create_headless_driver(preferred_browser)
        print(f"[VideoDownloader] Trying {browser_name} headless for Douyin cookies...")
    except Exception as exc:
        print(f"[VideoDownloader] Cannot create browser driver: {exc}")
        return ""

    try:
        try:
            driver.get("https://www.douyin.com/discover")
        except Exception as exc:
            print(f"[VideoDownloader] Discover navigation notice: {exc}")

        time.sleep(3)  # ttwid and anti-bot cookies are set by JS
        cookies = driver.get_cookies()
        if not cookies:
            print(f"[VideoDownloader] {browser_name}: no cookies received")
            return ""

        _save_cookies_netscape(cookies, cookie_path)
        print(f"[VideoDownloader] {browser_name} cookies saved: {cookie_path} ({len(cookies)} cookies)")
        return cookie_path
    except Exception as exc:
        print(f"[VideoDownloader] {browser_name} cookie extraction failed: {exc}")
        return ""
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _save_cookies_netscape(cookies: list, cookie_path: str):
    """Save a list of cookie dicts to Netscape cookie file format."""
    with open(cookie_path, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# http://curl.haxx.se/rfc/cookie_spec.html\n")
        f.write("# This is a generated file!  Do not edit.\n\n")
        for c in cookies:
            domain = c.get("domain", ".douyin.com")
            flag = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure", False) else "FALSE"
            expiry = int(c.get("expiry", 0) or 0)
            if expiry <= 0:
                expiry = int(time.time()) + 86400
            name = c["name"]
            value = c["value"]
            f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n")


def _get_douyin_cookies_urllib(cookie_path: str) -> str:
    """Fallback: generate Douyin cookies via urllib (limited effectiveness)."""
    import http.cookiejar
    import urllib.request
    import random
    import string

    jar = http.cookiejar.MozillaCookieJar(cookie_path)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # Get ttwid from ttwid API
    ttwid_payload = json.dumps({
        "region": "cn", "aid": 1128, "needFid": False,
        "service": "www.douyin.com",
        "migrate_info": {"ticket": "", "source": "node"},
        "cbUrlProtocol": "https", "union": True,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://ttwid.bytedance.com/ttwid/union/register/",
            data=ttwid_payload,
            headers={"User-Agent": ua, "Content-Type": "application/json"},
            method="POST",
        )
        resp = opener.open(req, timeout=15)
        resp.read()
        resp.close()
    except Exception:
        pass

    # Visit homepage
    try:
        req = urllib.request.Request("https://www.douyin.com/", headers={"User-Agent": ua})
        resp = opener.open(req, timeout=15)
        resp.read()
        resp.close()
    except Exception:
        pass

    # Add synthetic msToken
    ms_chars = string.ascii_letters + string.digits + "_-"
    ms_token = "".join(random.choices(ms_chars, k=107)) + "=="
    from http.cookiejar import Cookie
    jar.set_cookie(Cookie(
        version=0, name="msToken", value=ms_token,
        port=None, port_specified=False,
        domain=".douyin.com", domain_specified=True, domain_initial_dot=True,
        path="/", path_specified=True,
        secure=True, expires=int(time.time()) + 86400,
        discard=False, comment=None, comment_url=None, rest={}, rfc2109=False,
    ))

    try:
        jar.save(ignore_discard=True, ignore_expires=True)
        print(f"[VideoDownloader] urllib cookies saved: {cookie_path} ({len(jar)} cookies)")
    except Exception as exc:
        print(f"[VideoDownloader] Cookie save warning: {exc}")

    return cookie_path if os.path.exists(cookie_path) else ""


def _scrape_douyin_user_videos(
    user_url: str,
    progress_callback: Optional[Callable] = None,
    preferred_browser: Optional[str] = None,
    cookie_cache_path: Optional[str] = None,
    max_videos: int = 0,
) -> tuple:
    """Scrape video links and channel name from a Douyin user profile page.

    Uses high-speed headless browser (Cốc Cốc, Chrome, Edge) with eager page
    loading and smart scroll termination. Typically completes in 5-8 seconds.
    Returns (sorted_video_links_list, channel_name).
    """
    clean_url = user_url.split("?")[0]

    if progress_callback:
        p = DownloadProgress()
        p.status = "downloading"
        p.title = "Đang khởi động trình duyệt để đọc thông tin kênh..."
        progress_callback(p)

    custom_cookies = []
    user_agent = None
    try:
        from app.services.cookie_storage_service import get_saved_douyin_cookies
        custom_cookies, _, user_agent = get_saved_douyin_cookies()
    except Exception:
        pass

    driver, browser_name = create_headless_driver(
        preferred_browser,
        user_agent=None,
        enable_images=True,
    )
    print(f"[VideoDownloader] Scraping Douyin profile with {browser_name}...")

    try:
        # Pre-inject cookies before loading profile
        if custom_cookies:
            try:
                driver.get("https://www.douyin.com/robots.txt")
                cdp_cookies = [
                    {"name": c["name"], "value": c["value"], "domain": ".douyin.com", "path": "/"}
                    for c in custom_cookies
                ]
                driver.execute_cdp_cmd("Network.setCookies", {"cookies": cdp_cookies})
                print(f"[VideoDownloader] Injected {len(cdp_cookies)} cookies for channel scraping")
            except Exception as e:
                print(f"[VideoDownloader] Channel cookie inject notice: {e}")

        if progress_callback:
            p = DownloadProgress()
            p.status = "downloading"
            p.title = f"Đang kết nối tới kênh Douyin qua {browser_name}..."
            progress_callback(p)

        try:
            driver.get(clean_url)
        except Exception as exc:
            print(f"[VideoDownloader] Profile load notice: {exc}")

        # Save cookies simultaneously so no second browser launch is needed
        if cookie_cache_path:
            try:
                cookies = driver.get_cookies()
                if cookies:
                    _save_cookies_netscape(cookies, cookie_cache_path)
            except Exception:
                pass

        # Collect video links with fast scrolling
        video_links = set()

        # Initial check (wait up to ~3s for initial elements to appear)
        for _ in range(6):
            time.sleep(0.5)
            links = driver.find_elements("css selector", 'a[href*="/video/"]')
            for l in links:
                h = l.get_attribute("href")
                if h and "/video/" in h:
                    h = h.split("?")[0]
                    if not h.startswith("http"):
                        h = "https://www.douyin.com" + h
                    video_links.add(h)
            if video_links:
                break

        if progress_callback:
            p = DownloadProgress()
            p.status = "downloading"
            p.title = f"Đã tìm thấy {len(video_links)} video ban đầu, đang quét tiếp..."
            progress_callback(p)

        no_new_count = 0
        is_unlimited = (max_videos <= 0 or max_videos >= 99999) if "max_videos" in locals() else True
        max_scrolls = 1000 if is_unlimited else max(20, max_videos // 8 + 5)
        for scroll_idx in range(max_scrolls):
            prev_len = len(video_links)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.6)

            links = driver.find_elements("css selector", 'a[href*="/video/"]')
            for l in links:
                h = l.get_attribute("href")
                if h and "/video/" in h:
                    h = h.split("?")[0]
                    if not h.startswith("http"):
                        h = "https://www.douyin.com" + h
                    video_links.add(h)

            new_found = len(video_links) - prev_len
            if new_found > 0:
                no_new_count = 0
                if progress_callback:
                    p = DownloadProgress()
                    p.status = "downloading"
                    p.title = f"Đang quét kênh... Đã tìm thấy {len(video_links)} video (+{new_found})"
                    progress_callback(p)
            else:
                if len(video_links) > 0:
                    no_new_count += 1
                    # Nhấp nhả cuộn để kích hoạt lazy-load nếu bị kẹt
                    try:
                        driver.execute_script("window.scrollBy(0, -500);")
                        time.sleep(0.4)
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        time.sleep(1.0)
                    except Exception:
                        pass
                    if no_new_count >= 6:
                        # 6 consecutive scrolls with 0 new videos (~12-15s) -> all videos loaded
                        break
                else:
                    if scroll_idx >= 8:
                        # 8 scrolls without any videos -> empty channel or blocked
                        break

            if not is_unlimited and len(video_links) >= max_videos:
                break

        # Extract channel name after page has hydrated
        channel_name = ""
        try:
            h1_elems = driver.find_elements("css selector", "h1")
            for h in h1_elems:
                txt = h.text.strip()
                if txt:
                    channel_name = txt
                    break
            if not channel_name:
                raw_title = driver.title or ""
                if "的主页" in raw_title:
                    channel_name = raw_title.split("的主页")[0].strip()
                elif "的抖音" in raw_title:
                    channel_name = raw_title.split("的抖音")[0].strip()
                elif " - 抖音" in raw_title:
                    channel_name = raw_title.split(" - 抖音")[0].strip()
        except Exception:
            pass

        print(f"[VideoDownloader] Scraped {len(video_links)} videos for channel '{channel_name}'")
        return sorted(video_links), channel_name

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def detect_platform(url: str) -> str:
    """Return platform name from URL, or 'unknown'."""
    cleaned = extract_url_from_text(url)
    url_lower = cleaned.lower()
    for platform, patterns in _PLATFORM_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, url_lower):
                return platform
    return "unknown"


def _sanitize_filename(name: str) -> str:
    """Remove characters not safe for file/folder names."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.strip('. ')
    return name[:200] if name else "video"



# ---------------------------------------------------------------------------
# Core downloader
# ---------------------------------------------------------------------------

# JavaScript hook that captures Douyin API responses (aweme/detail, aweme/related)
# This hook is injected before any page navigation so it intercepts all fetch/XHR
# calls made by Douyin's JS SDK (which includes proper Argus signatures).
_DOUYIN_XHR_HOOK_SCRIPT = """
window.__captured_responses = [];

// Hook fetch
const originalFetch = window.fetch;
window.fetch = async function(...args) {
    const response = await originalFetch.apply(this, args);
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
    if (url.includes('aweme/detail') || url.includes('aweme/post') ||
        url.includes('play_addr') || url.includes('aweme/v1')) {
        try {
            const clone = response.clone();
            const text = await clone.text();
            window.__captured_responses.push({
                url: url, status: response.status, body: text, timestamp: Date.now()
            });
        } catch(e) {}
    }
    return response;
};

// Hook XMLHttpRequest
const originalXHROpen = XMLHttpRequest.prototype.open;
const originalXHRSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this._interceptUrl = url;
    return originalXHROpen.apply(this, [method, url, ...rest]);
};
XMLHttpRequest.prototype.send = function(...args) {
    if (this._interceptUrl && (
        this._interceptUrl.includes('aweme/detail') ||
        this._interceptUrl.includes('aweme/post') ||
        this._interceptUrl.includes('aweme/v1'))) {
        this.addEventListener('load', function() {
            try {
                window.__captured_responses.push({
                    url: this._interceptUrl, status: this.status,
                    body: this.responseText, timestamp: Date.now()
                });
            } catch(e) {}
        });
    }
    return originalXHRSend.apply(this, args);
};
"""


def _extract_video_info_from_douyin_response(response_body: str) -> Optional[dict]:
    """Parse a Douyin aweme API response body and return video download info.

    Returns dict with keys: aweme_id, desc, play_urls, download_urls, duration
    or None if no usable data is found.
    """
    try:
        data = json.loads(response_body)
    except (json.JSONDecodeError, TypeError):
        return None

    # Try to find aweme_detail or aweme_list in the response
    aweme = data.get("aweme_detail") or (data.get("aweme_list", [{}])[0] if data.get("aweme_list") else None) if isinstance(data, dict) else None
    if not aweme:
        # Check nested structures
        for key in (data if isinstance(data, dict) else {}):
            val = data[key]
            if isinstance(val, dict):
                if "aweme_detail" in val:
                    aweme = val["aweme_detail"]
                    break
                elif "aweme_list" in val and val["aweme_list"]:
                    aweme = val["aweme_list"][0]
                    break

    if not aweme:
        return None

    video = aweme.get("video", {})
    desc = aweme.get("desc", "")
    aweme_id = aweme.get("aweme_id", "")

    play_addr = video.get("play_addr", {})
    play_urls = play_addr.get("url_list", [])
    download_addr = video.get("download_addr", {})
    download_urls = download_addr.get("url_list", [])

    if not play_urls and not download_urls:
        return None

    return {
        "aweme_id": aweme_id,
        "desc": desc,
        "play_urls": play_urls,
        "download_urls": download_urls,
        "duration": video.get("duration", 0),
    }


def _download_douyin_via_browser(
    video_urls: list,
    output_dir: str,
    progress_callback: Optional[Callable] = None,
    preferred_browser: Optional[str] = None,
    cancel_flag: Optional[threading.Event] = None,
) -> dict:
    """Download Douyin videos by intercepting browser API responses.

    This approach works by:
    1. Injecting XHR/fetch hooks via CDP Page.addScriptToEvaluateOnNewDocument
    2. Navigating to each video page (triggering Douyin's JS to call the API
       with proper Argus signatures)
    3. Capturing the API response containing video CDN URLs
    4. Downloading the video file directly from the CDN

    Args:
        video_urls: List of Douyin video URLs (https://www.douyin.com/video/ID)
        output_dir: Directory to save downloaded videos
        progress_callback: Optional callback for progress updates
        preferred_browser: Browser preference (coccoc, chrome, edge, auto)
        cancel_flag: Optional threading.Event to signal cancellation

    Returns:
        dict with keys: success, files, downloaded, total, error
    """
    import urllib.request

    os.makedirs(output_dir, exist_ok=True)
    result = {
        "success": False,
        "files": [],
        "downloaded": 0,
        "total": len(video_urls),
        "error": "",
    }

    if not video_urls:
        result["error"] = "Không có video URL nào để tải."
        return result

    # Load custom cookies if available
    custom_cookies = []
    user_agent = None
    try:
        from app.services.cookie_storage_service import get_saved_douyin_cookies
        custom_cookies, _, user_agent = get_saved_douyin_cookies()
    except Exception:
        pass

    # Create browser with XHR hooks
    driver, browser_name = create_headless_driver(
        preferred_browser,
        user_agent=None,
        enable_images=True,
    )
    print(f"[VideoDownloader] Douyin browser download using {browser_name}")

    try:
        # Install XHR/fetch hooks BEFORE any page loads
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": _DOUYIN_XHR_HOOK_SCRIPT
        })

        # Warm up & inject cookies
        try:
            driver.get("https://www.douyin.com/robots.txt")
            if custom_cookies:
                cdp_cookies = [
                    {"name": c["name"], "value": c["value"], "domain": ".douyin.com", "path": "/"}
                    for c in custom_cookies
                ]
                driver.execute_cdp_cmd("Network.setCookies", {"cookies": cdp_cookies})
                print(f"[VideoDownloader] Injected {len(cdp_cookies)} cookies for video download")
            time.sleep(1)
        except Exception:
            pass

        for idx, video_url in enumerate(video_urls, 1):
            if cancel_flag and cancel_flag.is_set():
                result["error"] = "Đã hủy tải"
                break

            # Extract video ID from URL for filename
            vid_match = re.search(r'/video/(\d+)', video_url)
            vid_id = vid_match.group(1) if vid_match else f"video_{idx}"

            if progress_callback:
                p = DownloadProgress()
                p.status = "downloading"
                p.title = f"Đang tải video {idx}/{len(video_urls)}: {vid_id}"
                p.video_index = idx
                p.video_total = len(video_urls)
                p.percent = 0
                progress_callback(p)

            print(f"[VideoDownloader] [{idx}/{len(video_urls)}] Loading {video_url}")

            try:
                driver.get(video_url)
                time.sleep(6)
            except Exception as e:
                print(f"[VideoDownloader] Page load notice: {e}")

            # Retrieve captured API responses
            try:
                captured = driver.execute_script(
                    "return window.__captured_responses || [];"
                )
            except Exception:
                captured = []

            # Find the video info from captured responses
            video_info = None
            for resp in captured:
                if resp.get("status") != 200:
                    continue
                resp_url = resp.get("url", "")
                body = resp.get("body", "")
                # Prefer aweme/detail over aweme/related
                if "aweme/detail" in resp_url and len(body) > 100:
                    info = _extract_video_info_from_douyin_response(body)
                    if info and info.get("play_urls"):
                        video_info = info
                        break

            # Fallback: try aweme/related responses
            if not video_info:
                for resp in captured:
                    if resp.get("status") != 200:
                        continue
                    body = resp.get("body", "")
                    if len(body) > 100:
                        info = _extract_video_info_from_douyin_response(body)
                        if info and info.get("play_urls"):
                            video_info = info
                            break

            if not video_info:
                print(f"[VideoDownloader] Could not extract video info for {vid_id}")
                continue

            # Determine filename
            desc = _sanitize_filename(video_info.get("desc", ""))
            if desc and len(desc) > 5:
                filename = f"{desc}.mp4"
            else:
                filename = f"{vid_id}.mp4"
            output_path = os.path.join(output_dir, filename)

            # Choose best download URL (play_urls first, then download_urls)
            download_url = (
                video_info["play_urls"][0] if video_info.get("play_urls")
                else video_info["download_urls"][0] if video_info.get("download_urls")
                else None
            )

            if not download_url:
                print(f"[VideoDownloader] No download URL for {vid_id}")
                continue

            if progress_callback:
                p = DownloadProgress()
                p.status = "downloading"
                p.title = desc or vid_id
                p.video_index = idx
                p.video_total = len(video_urls)
                p.percent = 50
                progress_callback(p)

            # Download the video file
            try:
                req = urllib.request.Request(download_url)
                req.add_header("User-Agent",
                               "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36")
                req.add_header("Referer", "https://www.douyin.com/")

                with urllib.request.urlopen(req, timeout=120) as resp:
                    total_size = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk_size = 1024 * 256  # 256 KB chunks
                    start_time = time.time()

                    with open(output_path, "wb") as f:
                        while True:
                            if cancel_flag and cancel_flag.is_set():
                                raise Exception("Đã hủy tải")
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)

                            if progress_callback and total_size > 0:
                                p = DownloadProgress()
                                p.status = "downloading"
                                p.title = desc or vid_id
                                p.video_index = idx
                                p.video_total = len(video_urls)
                                p.downloaded_bytes = downloaded
                                p.total_bytes = total_size
                                p.percent = (downloaded / total_size) * 100
                                elapsed = time.time() - start_time
                                p.speed = downloaded / elapsed if elapsed > 0 else 0
                                if p.speed > 0:
                                    p.eta = int((total_size - downloaded) / p.speed)
                                progress_callback(p)

                file_size = os.path.getsize(output_path)
                if file_size > 1024:  # At least 1KB (not an error page)
                    result["files"].append(output_path)
                    result["downloaded"] += 1
                    print(f"[VideoDownloader] ✓ Downloaded {filename} "
                          f"({file_size / 1024 / 1024:.1f} MB)")
                else:
                    os.remove(output_path)
                    print(f"[VideoDownloader] ✗ File too small, removed: {filename}")

            except Exception as dl_exc:
                err = str(dl_exc)
                if "Đã hủy tải" in err:
                    result["error"] = "Đã hủy tải"
                    break
                print(f"[VideoDownloader] ✗ Download failed for {vid_id}: {dl_exc}")
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    result["success"] = result["downloaded"] > 0
    return result


class DownloadProgress:
    """Container for download progress info."""
    __slots__ = ("status", "filename", "downloaded_bytes", "total_bytes",
                 "speed", "eta", "percent", "video_index", "video_total",
                 "error", "title", "channel_name")

    def __init__(self):
        self.status = "waiting"       # waiting | downloading | finished | error
        self.filename = ""
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.speed = 0.0
        self.eta = 0
        self.percent = 0.0
        self.video_index = 0
        self.video_total = 0
        self.error = ""
        self.title = ""
        self.channel_name = ""


class VideoDownloaderService:
    """Download videos from social media platforms using yt-dlp."""

    def __init__(self, output_root: str, preferred_browser: str = "auto"):
        self.output_root = output_root
        self.preferred_browser = preferred_browser
        self._cancel_flag = threading.Event()

    def cancel(self):
        """Signal the current download to stop."""
        self._cancel_flag.set()

    def is_cancelled(self) -> bool:
        return self._cancel_flag.is_set()

    def reset(self):
        self._cancel_flag.clear()

    # ------------------------------------------------------------------
    # Quality presets
    # ------------------------------------------------------------------
    @staticmethod
    def quality_format(quality: str) -> str:
        """Return yt-dlp format string for the given quality label."""
        presets = {
            "best":    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "1080p":   "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
            "720p":    "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
            "480p":    "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best",
        }
        return presets.get(quality, presets["best"])

    # ------------------------------------------------------------------
    # Single video download
    def _apply_delogo_if_needed(self, video_path: str, delogo_bili: bool = True, delogo_wm: bool = True) -> bool:
        """Tự động khử logo và watermark trên video tải về."""
        try:
            if not video_path or not os.path.isfile(video_path):
                return False
            from app.services.video_export_service import _resolve_ffmpeg, probe_video_dimensions, build_delogo_filters
            ffmpeg = _resolve_ffmpeg()
            vid_w, vid_h = probe_video_dimensions(video_path)
            filters, out_v = build_delogo_filters(vid_w, vid_h, delogo_bilibili=delogo_bili, delogo_watermark=delogo_wm)
            if not filters:
                return False
            dir_name = os.path.dirname(video_path)
            base_name, ext = os.path.splitext(os.path.basename(video_path))
            temp_clean = os.path.join(dir_name, f"{base_name}_delogo_temp{ext}")
            cmd = [
                ffmpeg, "-y",
                "-i", video_path,
                "-filter_complex", ";\n".join(filters),
                "-map", f"[{out_v}]",
                "-map", "0:a:0?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                temp_clean,
            ]
            import subprocess
            kwargs = {"capture_output": True}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            p = subprocess.run(cmd, **kwargs)
            if p.returncode == 0 and os.path.isfile(temp_clean) and os.path.getsize(temp_clean) > 10240:
                try:
                    os.replace(temp_clean, video_path)
                except Exception:
                    os.remove(video_path)
                    os.rename(temp_clean, video_path)
                return True
            elif os.path.isfile(temp_clean):
                os.remove(temp_clean)
        except Exception as exc:
            print(f"[VideoDownloaderService] Delogo notice: {exc}")
        return False

    # ------------------------------------------------------------------
    def download_single(
        self,
        url: str,
        output_dir: str,
        quality: str = "best",
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
        auto_delogo_bilibili: bool = False,
        auto_delogo_watermark: bool = False,
    ) -> dict:
        """Download a single video. Returns dict with result info."""
        import yt_dlp

        url = extract_url_from_text(url)
        self.reset()
        os.makedirs(output_dir, exist_ok=True)
        progress = DownloadProgress()
        progress.status = "downloading"
        progress.video_index = 1
        progress.video_total = 1

        def _hook(d):
            if self._cancel_flag.is_set():
                raise Exception("Đã hủy tải")
            progress.status = d.get("status", "downloading")
            progress.filename = d.get("filename", "")
            progress.downloaded_bytes = d.get("downloaded_bytes", 0) or 0
            progress.total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            progress.speed = d.get("speed") or 0
            progress.eta = d.get("eta") or 0
            if progress.total_bytes > 0:
                progress.percent = (progress.downloaded_bytes / progress.total_bytes) * 100
            if progress_callback:
                progress_callback(progress)

        ydl_opts = {
            "format": self.quality_format(quality),
            "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "progress_hooks": [_hook],
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 15,
            "fragment_retries": 15,
            "http_chunk_size": 10485760,  # 10 MB chunks avoids Akamai/Bilibili CDN stream cutoff
            # No watermark tricks
            "extractor_args": {"tiktok": ["app_version=0"]},
        }

        platform = detect_platform(url)
        if platform == "douyin":
            # Douyin defaults to HEVC (H.265) which many players can't play.
            # Prefer H.264 (AVC) for maximum compatibility, fallback to any.
            ydl_opts["format"] = "best[vcodec^=avc]/best[vcodec!=?hevc]/best"
            ydl_opts["format_sort"] = ["vcodec:h264"]
            ydl_opts["http_headers"] = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            # Auto-generate fresh session cookies for Douyin
            cookie_dir = os.path.join(self.output_root, ".cache")
            cookie_file = _get_douyin_cookie_file(cookie_dir, preferred_browser=self.preferred_browser)
            if cookie_file:
                ydl_opts["cookiefile"] = cookie_file
        elif platform in ("tiktok", "bilibili", "youtube", "facebook", "instagram", "kuaishou"):
            from app.services.cookie_storage_service import get_saved_platform_cookies
            _, netscape_path, ua = get_saved_platform_cookies(platform)
            if netscape_path and os.path.exists(netscape_path):
                ydl_opts["cookiefile"] = netscape_path
            headers = {
                "User-Agent": ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            if platform == "bilibili" or "bilibili.com" in url or "b23.tv" in url:
                headers["Referer"] = "https://www.bilibili.com/"
            ydl_opts["http_headers"] = headers

        result = {"success": False, "files": [], "error": "", "platform": platform}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info:
                    progress.title = info.get("title", "")
                    progress.channel_name = info.get("uploader", "") or info.get("channel", "")
                    filename = ydl.prepare_filename(info)
                    # yt-dlp may merge into mp4
                    mp4_name = os.path.splitext(filename)[0] + ".mp4"
                    if os.path.exists(mp4_name):
                        result["files"].append(mp4_name)
                    elif os.path.exists(filename):
                        result["files"].append(filename)
                    result["success"] = True
                    result["title"] = info.get("title", "")
                    result["channel"] = progress.channel_name

                    # Tự động tẩy Logo Bilibili & Watermark nếu tải video từ Bilibili
                    if (platform == "bilibili" or "bilibili.com" in url or "b23.tv" in url) and (auto_delogo_bilibili or auto_delogo_watermark):
                        for f_path in list(result["files"]):
                            self._apply_delogo_if_needed(f_path, auto_delogo_bilibili, auto_delogo_watermark)

            progress.status = "finished"
            progress.percent = 100
            if progress_callback:
                progress_callback(progress)

        except Exception as exc:
            err_msg = str(exc)
            # -----------------------------------------------------------
            # Douyin fallback: yt-dlp often fails due to Argus signature.
            # Retry with browser-based XHR intercept approach.
            # -----------------------------------------------------------
            if platform == "douyin":
                print(f"[VideoDownloader] yt-dlp failed for Douyin: {err_msg}")
                print(f"[VideoDownloader] Falling back to browser intercept...")
                if progress_callback:
                    p = DownloadProgress()
                    p.status = "downloading"
                    p.title = "yt-dlp thất bại – Đang thử tải qua trình duyệt..."
                    p.video_index = 1
                    p.video_total = 1
                    progress_callback(p)

                browser_result = _download_douyin_via_browser(
                    [url],
                    output_dir,
                    progress_callback=progress_callback,
                    preferred_browser=self.preferred_browser,
                    cancel_flag=self._cancel_flag,
                )
                if browser_result["success"]:
                    result["success"] = True
                    result["files"] = browser_result["files"]
                    result["error"] = ""
                    return result
                else:
                    # Both methods failed
                    result["error"] = (
                        f"yt-dlp: {err_msg}\n"
                        f"Browser: {browser_result.get('error', 'Không tải được')}"
                    )
            else:
                result["error"] = err_msg

            progress.status = "error"
            progress.error = result["error"]
            if progress_callback:
                progress_callback(progress)

        return result

    # ------------------------------------------------------------------
    # Channel / playlist download  (all videos)
    # ------------------------------------------------------------------
    def download_channel(
        self,
        url: str,
        output_base_dir: str,
        quality: str = "best",
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
        max_videos: int = 0,
    ) -> dict:
        """Download all videos from a channel/user page.

        The videos are stored under ``output_base_dir/<channel_name>/``.
        """
        import yt_dlp

        url = extract_url_from_text(url)

        self.reset()
        progress = DownloadProgress()

        result = {
            "success": False,
            "channel_name": "",
            "output_dir": "",
            "files": [],
            "error": "",
            "total": 0,
            "downloaded": 0,
            "platform": detect_platform(url),
        }

        cookie_dir = os.path.join(output_base_dir, ".cache")
        os.makedirs(cookie_dir, exist_ok=True)
        cookie_file = os.path.join(cookie_dir, "douyin_cookies.txt")
        platform = result["platform"]

        # --- Step 1: Extract playlist/channel metadata ---
        # Special optimization for Douyin /user/ profile pages:
        # yt-dlp DOES NOT support Douyin user profiles and will always throw "Unsupported URL".
        # Bypass yt-dlp directly and scrape with high-speed headless browser!
        if platform == "douyin" and "/user/" in url:
            print(f"[VideoDownloader] Direct scraping Douyin user profile...")
            try:
                video_links, channel_name = _scrape_douyin_user_videos(
                    url,
                    progress_callback=progress_callback,
                    preferred_browser=self.preferred_browser,
                    cookie_cache_path=cookie_file,
                    max_videos=max_videos,
                )
                if not video_links:
                    result["error"] = "Không tìm thấy video nào trên trang kênh."
                    progress.status = "error"
                    progress.error = result["error"]
                    if progress_callback:
                        progress_callback(progress)
                    return result

                info = {
                    "title": channel_name or "Douyin User",
                    "uploader": channel_name or "Douyin User",
                    "entries": [{"url": vl, "title": f"Video {i+1}"} for i, vl in enumerate(video_links)],
                    "_type": "playlist",
                }
            except Exception as scrape_exc:
                result["error"] = f"Không thể lấy thông tin kênh: {scrape_exc}"
                progress.status = "error"
                progress.error = result["error"]
                if progress_callback:
                    progress_callback(progress)
                return result
        else:
            # YouTube, TikTok, Bilibili, Xiaohongshu, etc.
            progress.status = "downloading"
            progress.title = "Đang lấy thông tin kênh..."
            if progress_callback:
                progress_callback(progress)

            flat_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "skip_download": True,
            }
            if max_videos > 0 and max_videos < 99999:
                flat_opts["playlistend"] = max_videos

            if platform == "douyin":
                flat_opts["http_headers"] = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
                c_file = _get_douyin_cookie_file(cookie_dir, preferred_browser=self.preferred_browser)
                if c_file:
                    flat_opts["cookiefile"] = c_file

            try:
                with yt_dlp.YoutubeDL(flat_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as exc:
                result["error"] = f"Không thể lấy thông tin kênh: {exc}"
                progress.status = "error"
                progress.error = result["error"]
                if progress_callback:
                    progress_callback(progress)
                return result

        if not info:
            result["error"] = "Không tìm thấy thông tin kênh."
            return result

        # Determine channel name
        channel_name = (
            info.get("uploader")
            or info.get("channel")
            or info.get("title")
            or info.get("id")
            or "unknown_channel"
        )
        channel_name = _sanitize_filename(channel_name)
        result["channel_name"] = channel_name

        channel_dir = os.path.join(output_base_dir, channel_name)
        os.makedirs(channel_dir, exist_ok=True)
        result["output_dir"] = channel_dir

        # Gather all video entries
        entries = list(info.get("entries", []) or [])
        if not entries:
            # Single video URL provided – download it directly
            single = self.download_single(url, channel_dir, quality, progress_callback)
            result["files"] = single.get("files", [])
            result["success"] = single.get("success", False)
            result["error"] = single.get("error", "")
            result["total"] = 1
            result["downloaded"] = 1 if single["success"] else 0
            return result

        total = len(entries)
        result["total"] = total
        progress.video_total = total

        # --- Step 2: Download each video ---
        # For Douyin: use browser-based XHR intercept (yt-dlp always fails
        # due to Argus signature requirements)
        if platform == "douyin":
            video_urls = [
                entry.get("url") or entry.get("webpage_url") or ""
                for entry in entries
            ]
            video_urls = [v for v in video_urls if v]  # filter empties

            if progress_callback:
                p = DownloadProgress()
                p.status = "downloading"
                p.title = f"Đang tải {len(video_urls)} video Douyin qua trình duyệt..."
                p.video_total = len(video_urls)
                progress_callback(p)

            browser_result = _download_douyin_via_browser(
                video_urls,
                channel_dir,
                progress_callback=progress_callback,
                preferred_browser=self.preferred_browser,
                cancel_flag=self._cancel_flag,
            )

            result["files"] = browser_result.get("files", [])
            result["downloaded"] = browser_result.get("downloaded", 0)
            result["success"] = browser_result.get("success", False)
            result["error"] = browser_result.get("error", "")

            progress.status = "finished" if result["success"] else "error"
            progress.percent = 100
            if progress_callback:
                progress_callback(progress)

            return result

        # Non-Douyin platforms: use yt-dlp as usual
        def _hook(d):
            if self._cancel_flag.is_set():
                raise Exception("Đã hủy tải")
            progress.status = d.get("status", "downloading")
            progress.filename = d.get("filename", "")
            progress.downloaded_bytes = d.get("downloaded_bytes", 0) or 0
            progress.total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            progress.speed = d.get("speed") or 0
            progress.eta = d.get("eta") or 0
            if progress.total_bytes > 0:
                progress.percent = (progress.downloaded_bytes / progress.total_bytes) * 100
            if progress_callback:
                progress_callback(progress)

        dl_opts = {
            "format": self.quality_format(quality),
            "outtmpl": os.path.join(channel_dir, "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "progress_hooks": [_hook],
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 15,
            "fragment_retries": 15,
            "http_chunk_size": 10485760,  # 10 MB chunks avoids Akamai/Bilibili CDN stream cutoff
            "extractor_args": {"tiktok": ["app_version=0"]},
        }

        if platform in ("tiktok", "bilibili", "youtube", "facebook", "instagram", "kuaishou"):
            from app.services.cookie_storage_service import get_saved_platform_cookies
            _, netscape_path, ua = get_saved_platform_cookies(platform)
            if netscape_path and os.path.exists(netscape_path):
                dl_opts["cookiefile"] = netscape_path
            headers = {
                "User-Agent": ua or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            if platform == "bilibili" or "bilibili.com" in url or "b23.tv" in url:
                headers["Referer"] = "https://www.bilibili.com/"
            dl_opts["http_headers"] = headers

        downloaded_count = 0
        for idx, entry in enumerate(entries, 1):
            if self._cancel_flag.is_set():
                result["error"] = "Đã hủy tải"
                break

            video_url = entry.get("url") or entry.get("webpage_url") or ""
            if not video_url:
                continue

            progress.video_index = idx
            progress.title = entry.get("title", f"Video {idx}")
            progress.percent = 0
            if progress_callback:
                progress_callback(progress)

            try:
                with yt_dlp.YoutubeDL(dl_opts) as ydl:
                    vinfo = ydl.extract_info(video_url, download=True)
                    if vinfo:
                        filename = ydl.prepare_filename(vinfo)
                        mp4_name = os.path.splitext(filename)[0] + ".mp4"
                        if os.path.exists(mp4_name):
                            result["files"].append(mp4_name)
                        elif os.path.exists(filename):
                            result["files"].append(filename)
                        downloaded_count += 1
            except Exception as exc:
                err = str(exc)
                if "Đã hủy tải" in err:
                    result["error"] = "Đã hủy tải"
                    break
                print(f"[VideoDownloader] Bỏ qua video {idx}/{total}: {exc}")
                continue

        result["downloaded"] = downloaded_count
        result["success"] = downloaded_count > 0

        progress.status = "finished" if result["success"] else "error"
        progress.percent = 100
        if progress_callback:
            progress_callback(progress)

        return result

    # ------------------------------------------------------------------
    # Convenience: auto-detect single vs channel
    # ------------------------------------------------------------------
    def download_auto(
        self,
        url: str,
        output_base_dir: str,
        quality: str = "best",
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    ) -> dict:
        """Auto-detect whether URL is a single video or channel, then download."""
        import yt_dlp

        url = extract_url_from_text(url)
        platform = detect_platform(url)

        # Douyin /user/ URLs are always channel downloads (yt-dlp doesn't support them)
        if platform == "douyin" and "/user/" in url:
            return self.download_channel(url, output_base_dir, quality, progress_callback)

        # Quick probe
        try:
            probe_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "skip_download": True,
            }
            if platform == "douyin":
                cookie_dir = os.path.join(output_base_dir, ".cache")
                cookie_file = _get_douyin_cookie_file(cookie_dir, preferred_browser=self.preferred_browser)
                if cookie_file:
                    probe_opts["cookiefile"] = cookie_file
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info and info.get("_type") == "playlist":
                return self.download_channel(url, output_base_dir, quality, progress_callback)
        except Exception:
            pass

        # Fallback: single video
        channel_name = _sanitize_filename(platform)
        output_dir = os.path.join(output_base_dir, channel_name)
        return self.download_single(url, output_dir, quality, progress_callback)
