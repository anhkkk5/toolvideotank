import sys
sys.stdout.reconfigure(encoding='utf-8')
from app.services.cookie_storage_service import get_saved_douyin_cookies
from playwright.sync_api import sync_playwright

cookies, _, ua = get_saved_douyin_cookies()
url = 'https://www.douyin.com/user/MS4wLjABAAAAB_L0ZA2HhM0KMI1RqFA7jEC5K3qCxf8AJbkxL6KngxFnAeT_1EGIL4pw6TmLcm8c'

with sync_playwright() as p:
    b = p.chromium.launch(channel='chrome', headless=True, args=['--disable-blink-features=AutomationControlled'])
    ctx = b.new_context(user_agent=ua)
    pw_cookies = [{'name': c['name'], 'value': c['value'], 'domain': '.douyin.com', 'path': '/'} for c in cookies]
    ctx.add_cookies(pw_cookies)
    page = ctx.new_page()
    page.goto(url, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(3500)
    page.screenshot(path='test_douyin_render.png')
    print('Screenshot saved!')
    text = page.evaluate("() => document.body ? document.body.innerText : ''")
    print('Body text preview:\n', text[:800])
    b.close()
