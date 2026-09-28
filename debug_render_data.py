"""Debug: Dump và phân tích RENDER_DATA từ Douyin profile."""
import os, sys, time, re, json, urllib.request
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

URL = "https://www.douyin.com/user/MS4wLjABAAAACCkgrN9l_P-Gww2kwbKh9Fe4Nx_oxX3i8gqeidD8dLGag5rKjosE9Q5dS8JnNzq8"


def get_ttwid():
    payload = json.dumps({
        "region": "cn", "aid": 1128, "needFid": False,
        "service": "www.douyin.com",
        "migrate_info": {"ticket": "", "source": "node"},
        "cbUrlProtocol": "https", "union": True,
    }).encode()
    req = urllib.request.Request(
        "https://ttwid.bytedance.com/ttwid/union/register/",
        data=payload,
        headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        m = re.search(r'ttwid=([^;]+)', resp.headers.get("Set-Cookie", ""))
        return m.group(1) if m else None
    except:
        return None


def debug_render_data():
    from playwright.sync_api import sync_playwright
    
    ttwid = get_ttwid()
    print(f"ttwid: {'OK' if ttwid else 'FAILED'}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--lang=zh-CN"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        if ttwid:
            context.add_cookies([{"name": "ttwid", "value": ttwid, "domain": ".douyin.com", "path": "/", "secure": True}])
        
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        
        # Visit homepage first
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)
        
        # Navigate to profile
        page.goto(URL.split("?")[0], wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(5000)
        
        # Screenshot
        page.screenshot(path="debug_render_data.png")
        
        # Extract RENDER_DATA raw
        raw = page.evaluate("""() => {
            const s = document.querySelector('script#RENDER_DATA');
            if (!s) return null;
            return s.textContent;
        }""")
        
        if not raw:
            print("NO RENDER_DATA!")
            browser.close()
            return
        
        decoded = urllib.request.unquote(raw)
        print(f"\nRENDER_DATA: {len(decoded)} chars")
        
        # Save to file for analysis
        with open("debug_render_data.json", "w", encoding="utf-8") as f:
            f.write(decoded)
        print("Saved to debug_render_data.json")
        
        # Parse and analyze structure
        data = json.loads(decoded)
        
        # Show top-level keys
        print(f"\nTop-level keys: {list(data.keys())}")
        
        for key in data:
            val = data[key]
            if isinstance(val, dict):
                print(f"\n  [{key}] (dict, {len(val)} keys): {list(val.keys())[:10]}")
                for k2 in list(val.keys())[:5]:
                    v2 = val[k2]
                    if isinstance(v2, dict):
                        print(f"    [{k2}] (dict, {len(v2)} keys): {list(v2.keys())[:10]}")
                    elif isinstance(v2, list):
                        print(f"    [{k2}] (list, {len(v2)} items)")
                    elif isinstance(v2, str):
                        print(f"    [{k2}] = '{v2[:60]}'")
                    else:
                        print(f"    [{k2}] = {v2}")
            elif isinstance(val, str):
                print(f"\n  [{key}] = '{val[:80]}'")
            else:
                print(f"\n  [{key}] = {val}")
        
        # Search for aweme_id anywhere in the JSON string
        json_str = json.dumps(data)
        aweme_ids = re.findall(r'"aweme_id"\s*:\s*"(\d+)"', json_str)
        print(f"\n\naweme_id occurrences: {len(aweme_ids)}")
        for aid in aweme_ids[:20]:
            print(f"  - {aid}")
        
        # Search for nickname
        nicknames = re.findall(r'"nickname"\s*:\s*"([^"]+)"', json_str)
        print(f"\nnicknames: {nicknames[:5]}")
        
        # Search for sec_uid
        sec_uids = re.findall(r'"sec_uid"\s*:\s*"([^"]+)"', json_str)
        print(f"\nsec_uids: {sec_uids[:5]}")
        
        # Search for video-related patterns
        for pattern in ["aweme_list", "video_list", "post_list", "videoList", "postList"]:
            count = json_str.count(pattern)
            if count:
                print(f"\nPattern '{pattern}': {count} occurrences")
        
        # Check for user profile data
        for pattern in ["user_info", "userInfo", "user_profile", "userProfile"]:
            if pattern in json_str:
                print(f"Found '{pattern}' in data")
        
        # Check for error messages
        for pattern in ["error", "status_code", "status_msg"]:
            matches = re.findall(f'"{pattern}"\\s*:\\s*([^,}}]+)', json_str)
            if matches:
                print(f"\n'{pattern}' values: {matches[:5]}")
        
        browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("DEBUG: RENDER_DATA Analysis")
    print("=" * 60)
    debug_render_data()
