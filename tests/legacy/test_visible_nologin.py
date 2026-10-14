"""Quick test: Playwright visible (non-headless) WITHOUT login.
Check if Douyin shows profile content for visible browser."""
import os, sys, time, re, json, urllib.request
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

URL = "https://www.douyin.com/user/MS4wLjABAAAACCkgrN9l_P-Gww2kwbKh9Fe4Nx_oxX3i8gqeidD8dLGag5rKjosE9Q5dS8JnNzq8"


def get_ttwid():
    payload = json.dumps({"region": "cn", "aid": 1128, "needFid": False,
        "service": "www.douyin.com", "migrate_info": {"ticket": "", "source": "node"},
        "cbUrlProtocol": "https", "union": True}).encode()
    req = urllib.request.Request("https://ttwid.bytedance.com/ttwid/union/register/",
        data=payload, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        m = re.search(r'ttwid=([^;]+)', resp.headers.get("Set-Cookie", ""))
        return m.group(1) if m else None
    except:
        return None


def test_visible():
    from playwright.sync_api import sync_playwright
    
    ttwid = get_ttwid()
    
    api_videos = []
    
    def on_response(response):
        if "aweme/v1/web/aweme/post" in response.url or "aweme/post" in response.url:
            try:
                data = response.json()
                for item in data.get("aweme_list", []):
                    api_videos.append(item.get("aweme_id", ""))
                print(f"  [API] +{len(data.get('aweme_list',[]))} videos, total API: {len(api_videos)}")
            except:
                pass
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # VISIBLE!
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--lang=zh-CN"]
        )
        context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="zh-CN")
        if ttwid:
            context.add_cookies([{"name": "ttwid", "value": ttwid, "domain": ".douyin.com", "path": "/", "secure": True}])
        
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page.on("response", on_response)
        
        # Homepage first
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)
        
        # Profile
        page.goto(URL.split("?")[0], wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(8000)
        
        title = page.title()
        body = page.evaluate("document.body?.innerText?.substring(0, 400) || ''")
        print(f"\nTitle: {title}")
        print(f"Body: {body[:200]}")
        
        # DOM video links
        links = page.evaluate("Array.from(document.querySelectorAll('a[href*=\"/video/\"]')).map(a=>a.href)")
        print(f"\nDOM video links: {len(links)}")
        for l in links[:5]:
            print(f"  {l}")
        
        # API videos
        print(f"\nAPI captured videos: {len(api_videos)}")
        
        page.screenshot(path="debug_visible_nologin.png")
        
        # Wait a bit for user to see
        time.sleep(3)
        
        browser.close()


if __name__ == "__main__":
    test_visible()
