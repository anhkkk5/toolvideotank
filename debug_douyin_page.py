"""Debug: Xem Douyin profile page render gì trong headless browser."""
import os, sys, time, json
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.services.video_downloader_service import create_headless_driver

URL = "https://www.douyin.com/user/MS4wLjABAAAACCkgrN9l_P-Gww2kwbKh9Fe4Nx_oxX3i8gqeidD8dLGag5rKjosE9Q5dS8JnNzq8"

driver, name = create_headless_driver()
print(f"Browser: {name}")

# Install hook before navigating
HOOK = """
window.__api_calls = [];
const _f = window.fetch;
window.fetch = async function(...a) {
    const url = typeof a[0] === 'string' ? a[0] : a[0]?.url || '';
    window.__api_calls.push({url: url.substring(0, 200), ts: Date.now()});
    return _f.apply(this, a);
};
const _xo = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function(m, u, ...r) {
    window.__api_calls.push({url: (u||'').substring(0, 200), ts: Date.now(), type: 'xhr'});
    return _xo.apply(this, [m, u, ...r]);
};
"""
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": HOOK})

try:
    driver.set_page_load_timeout(15)
    driver.get(URL)
except Exception as e:
    print(f"Load: {e}")

time.sleep(5)

# 1. Title
print(f"\nTitle: {driver.title}")

# 2. Page URL
print(f"URL: {driver.current_url}")

# 3. Body text preview
body = driver.execute_script("return document.body ? document.body.innerText.substring(0, 500) : 'NO BODY';")
print(f"\nBody text:\n{body}")

# 4. All links with /video/
links = driver.execute_script("""
    const links = document.querySelectorAll('a[href*="/video/"]');
    return Array.from(links).map(l => l.href).slice(0, 20);
""")
print(f"\nVideo links: {len(links)}")
for l in links:
    print(f"  {l}")

# 5. API calls captured
api_calls = driver.execute_script("return window.__api_calls || [];")
print(f"\nAPI calls: {len(api_calls)}")
for c in api_calls[:30]:
    print(f"  [{c.get('type','fetch')}] {c['url']}")

# 6. Check for RENDER_DATA
has_render = driver.execute_script("""
    const s = document.querySelector('script#RENDER_DATA');
    if (s) return s.textContent.substring(0, 300);
    return 'NO RENDER_DATA';
""")
print(f"\nRENDER_DATA: {has_render[:200]}")

# 7. Check for login wall / captcha
login_wall = driver.execute_script("""
    const el = document.querySelector('[class*="login"], [class*="captcha"], [class*="verify"]');
    return el ? el.className : 'none';
""")
print(f"\nLogin/Captcha wall: {login_wall}")

# 8. Screenshot
driver.save_screenshot("debug_douyin_profile.png")
print("\nScreenshot saved: debug_douyin_profile.png")

driver.quit()
