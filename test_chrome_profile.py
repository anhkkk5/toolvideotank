import os, sys
if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

from playwright.sync_api import sync_playwright

user_data = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
profile_dir = "Default"

print(f"Testing launch_persistent_context with Chrome profile {profile_dir}...")
with sync_playwright() as p:
    try:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data,
            channel="chrome",
            headless=False,
            args=[
                f"--profile-directory={profile_dir}",
                "--disable-blink-features=AutomationControlled",
                "--lang=zh-CN",
            ]
        )
        print("Success! Context opened.")
        page = context.new_page()
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=15000)
        print("Page title:", page.title())
        context.close()
    except Exception as e:
        print("Error launching persistent context:", e)
