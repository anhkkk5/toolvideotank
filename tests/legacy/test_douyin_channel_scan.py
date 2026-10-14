"""Douyin Channel Scanner FINAL - Dùng Playwright visible browser.

Giải pháp:
1. Mở browser THẤY ĐƯỢC (Playwright Chromium)
2. User quét QR hoặc đăng nhập 1 lần
3. Lưu cookies vào file (tái sử dụng cho lần sau)
4. Quét kênh bằng API interception + scroll

Workflow production:
- Lần đầu: Mở browser visible -> user login -> save cookies
- Lần sau: Load saved cookies -> headless quét
"""
import os, sys, time, re, json, urllib.request
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

URL = "https://www.douyin.com/user/MS4wLjABAAAACCkgrN9l_P-Gww2kwbKh9Fe4Nx_oxX3i8gqeidD8dLGag5rKjosE9Q5dS8JnNzq8"
COOKIE_FILE = os.path.join(os.path.dirname(__file__), "douyin_login_cookies.json")


def login_and_save_cookies():
    """Mở browser visible để user đăng nhập Douyin, lưu cookies."""
    from playwright.sync_api import sync_playwright
    
    print("\n" + "="*60)
    print("ĐĂNG NHẬP DOUYIN")
    print("="*60)
    print("Browser sẽ mở trang Douyin.")
    print("Hãy đăng nhập bằng QR code hoặc số điện thoại.")
    print("Sau khi đăng nhập xong, nhấn Enter ở đây...")
    print("="*60 + "\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # VISIBLE browser
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--lang=zh-CN"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=30000)
        
        # Wait for user to login
        input("\n>>> Nhấn Enter sau khi đã đăng nhập Douyin... ")
        
        # Save all cookies
        cookies = context.cookies()
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        
        print(f"\nĐã lưu {len(cookies)} cookies vào {COOKIE_FILE}")
        
        # Check login
        douyin_cookies = [c for c in cookies if "douyin" in c.get("domain", "")]
        important = ["sessionid", "sessionid_ss", "sid_tt", "uid_tt", "LOGIN_STATUS", "passport_csrf_token"]
        for c in douyin_cookies:
            if c["name"] in important:
                print(f"  {c['name']}: {c['value'][:30]}...")
        
        browser.close()
        return cookies


def load_cookies():
    """Load saved cookies."""
    if not os.path.exists(COOKIE_FILE):
        return None
    
    # Check age (cookies valid for ~24h)
    age = time.time() - os.path.getmtime(COOKIE_FILE)
    if age > 86400:  # 24 hours
        print(f"Cookies expired ({age/3600:.1f}h old). Need re-login.")
        return None
    
    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    
    print(f"Loaded {len(cookies)} saved cookies ({age/60:.0f}min old)")
    return cookies


def scan_channel_with_cookies(url, cookies, headless=True):
    """Quét kênh Douyin dùng cookies đã lưu."""
    from playwright.sync_api import sync_playwright
    
    sec_match = re.search(r'/user/([^/?#]+)', url)
    sec_user_id = sec_match.group(1) if sec_match else ""
    print(f"\nsec_user_id: {sec_user_id}")
    
    all_videos = {}
    channel_name = ""
    has_more_flag = True
    
    def handle_response(response):
        nonlocal channel_name, has_more_flag
        url = response.url
        
        if "aweme/v1/web/aweme/post" in url or "aweme/post" in url:
            try:
                data = response.json()
                aweme_list = data.get("aweme_list", [])
                has_more_flag = data.get("has_more", False)
                for item in aweme_list:
                    aid = item.get("aweme_id", "")
                    if aid:
                        all_videos[aid] = {
                            "aweme_id": aid,
                            "desc": item.get("desc", ""),
                            "url": f"https://www.douyin.com/video/{aid}",
                            "create_time": item.get("create_time", 0),
                            "statistics": {
                                "digg_count": item.get("statistics", {}).get("digg_count", 0),
                                "comment_count": item.get("statistics", {}).get("comment_count", 0),
                                "share_count": item.get("statistics", {}).get("share_count", 0),
                                "play_count": item.get("statistics", {}).get("play_count", 0),
                            }
                        }
                print(f"  [API] +{len(aweme_list)} videos (total: {len(all_videos)}, has_more: {has_more_flag})")
            except Exception as e:
                try:
                    text = response.text()
                    print(f"  [API] Error: {e}, body: {text[:100]}")
                except:
                    print(f"  [API] Error: {e}")
        
        if "user/profile" in url or "user/other" in url:
            try:
                data = response.json()
                user = data.get("user", {})
                if user.get("nickname"):
                    channel_name = user["nickname"]
                    print(f"  [User] Channel: {channel_name} (followers: {user.get('follower_count', '?')})")
            except:
                pass
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--lang=zh-CN"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        
        # Inject saved cookies
        context.add_cookies(cookies)
        print(f"Injected {len(cookies)} cookies")
        
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page.on("response", handle_response)
        
        # Navigate to profile
        print(f"\nLoading profile...")
        try:
            page.goto(url.split("?")[0], wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print(f"  Navigation: {e}")
        page.wait_for_timeout(5000)
        
        title = page.title()
        body = page.evaluate("document.body?.innerText?.substring(0, 300) || ''")
        print(f"Title: {title}")
        
        # Check login status
        if "登录" in body[:80] and "用户不存在" in body:
            print("\n*** COOKIES EXPIRED - Need re-login! ***")
            browser.close()
            return None
        
        page.screenshot(path="debug_scan_final.png")
        
        # Extract from RENDER_DATA
        render = page.evaluate("""() => {
            const s = document.querySelector('script#RENDER_DATA');
            if (!s) return null;
            try {
                const d = decodeURIComponent(s.textContent);
                const data = JSON.parse(d);
                const videos = [];
                let channel = '';
                const scan = (o, depth) => {
                    if (depth > 10 || !o || typeof o !== 'object') return;
                    if (Array.isArray(o)) { o.forEach(x => scan(x, depth+1)); return; }
                    if (o.aweme_id && typeof o.aweme_id === 'string' && o.aweme_id.length > 5)
                        videos.push({aweme_id: o.aweme_id, desc: (o.desc||'').substring(0,100), create_time: o.create_time||0});
                    if (o.nickname && o.sec_uid) channel = o.nickname;
                    Object.values(o).forEach(v => scan(v, depth+1));
                };
                scan(data, 0);
                return {videos, channel};
            } catch(e) { return {error: e.message}; }
        }""")
        
        if render and render.get("videos"):
            if not channel_name:
                channel_name = render.get("channel", "")
            for v in render["videos"]:
                aid = v["aweme_id"]
                if aid not in all_videos:
                    all_videos[aid] = {"aweme_id": aid, "desc": v.get("desc", ""),
                                       "url": f"https://www.douyin.com/video/{aid}",
                                       "create_time": v.get("create_time", 0)}
            print(f"\nRENDER_DATA: {len(render['videos'])} videos")
        
        print(f"After initial load: {len(all_videos)} videos")
        
        # Dismiss login popup if any
        page.evaluate("""() => {
            document.querySelectorAll('[class*="login-guide"], [class*="LoginGuide"], [class*="modal"], [class*="mask"]').forEach(el => {
                try { el.remove(); } catch(e) {}
            });
        }""")
        
        # Scroll to load all videos
        print(f"\nScrolling to load more...")
        no_new = 0
        for i in range(100):
            prev = len(all_videos)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            
            # Also check DOM
            dom_links = page.evaluate("Array.from(document.querySelectorAll('a[href*=\"/video/\"]')).map(a=>a.href)")
            for href in dom_links:
                m = re.search(r'/video/(\d+)', href)
                if m:
                    vid = m.group(1)
                    if vid not in all_videos:
                        all_videos[vid] = {"aweme_id": vid, "desc": "", "url": href}
            
            nf = len(all_videos) - prev
            if nf > 0:
                no_new = 0
                print(f"  Scroll {i+1}: {len(all_videos)} videos (+{nf})")
            else:
                no_new += 1
                if no_new >= 6:
                    print(f"  No new for 6 scrolls. Done.")
                    break
        
        if not channel_name:
            # Try from DOM
            channel_name = page.evaluate("""() => {
                const h1 = document.querySelector('h1');
                return h1 ? h1.innerText : '';
            }""") or ""
        
        result = sorted(all_videos.values(), key=lambda x: x.get("create_time", 0), reverse=True)
        
        print(f"\n{'='*60}")
        print(f"RESULT: {len(result)} videos for '{channel_name}'")
        print(f"{'='*60}")
        for i, v in enumerate(result, 1):
            stats = v.get("statistics", {})
            desc = v.get("desc", "")[:50]
            plays = stats.get("play_count", "")
            print(f"  {i:3d}. [{v['aweme_id']}] {desc}" + (f" (plays: {plays})" if plays else ""))
        
        browser.close()
        return result


if __name__ == "__main__":
    print("="*60)
    print("DOUYIN CHANNEL SCANNER (Final)")
    print("="*60)
    
    # Try load saved cookies
    cookies = load_cookies()
    
    if cookies:
        # Try scan with saved cookies
        result = scan_channel_with_cookies(URL, cookies)
        
        if result is None:
            # Cookies expired, re-login
            cookies = login_and_save_cookies()
            result = scan_channel_with_cookies(URL, cookies)
    else:
        # First time: need login
        cookies = login_and_save_cookies()
        result = scan_channel_with_cookies(URL, cookies)
    
    if result:
        print(f"\n*** TOTAL: {len(result)} videos ***")
    else:
        print("\n*** FAILED ***")
