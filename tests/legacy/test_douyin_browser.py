"""
FINAL WORKING APPROACH: Hook XMLHttpRequest/fetch to capture Douyin API responses.
When the page loads a video, the Douyin JS app calls the API with proper signatures.
We intercept those responses to get video URLs.
"""
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, r"d:\capcap\CapCap")
from app.services.video_downloader_service import create_headless_driver

OUTPUT_DIR = r"d:\tooldownload\douyin-downloader\Downloaded"


# JavaScript to inject that hooks fetch/XHR and captures API responses
HOOK_SCRIPT = """
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
                url: url,
                status: response.status,
                body: text,
                timestamp: Date.now()
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
                    url: this._interceptUrl,
                    status: this.status,
                    body: this.responseText,
                    timestamp: Date.now()
                });
            } catch(e) {}
        });
    }
    return originalXHRSend.apply(this, args);
};

console.log('[HOOK] XHR/Fetch hooks installed');
"""


def extract_video_info_from_response(response_body):
    """Parse Douyin API response to extract video download URL."""
    try:
        data = json.loads(response_body)
    except json.JSONDecodeError:
        return None

    aweme = data.get("aweme_detail") or data.get("aweme_list", [{}])[0] if isinstance(data, dict) else None
    if not aweme:
        # Try nested structure
        for key in data:
            if isinstance(data[key], dict) and "aweme_detail" in data[key]:
                aweme = data[key]["aweme_detail"]
                break

    if not aweme:
        return None

    video = aweme.get("video", {})
    desc = aweme.get("desc", "")
    aweme_id = aweme.get("aweme_id", "")

    # Get play URL
    play_addr = video.get("play_addr", {})
    play_urls = play_addr.get("url_list", [])

    # Get download URL
    download_addr = video.get("download_addr", {})
    download_urls = download_addr.get("url_list", [])

    # Get no-watermark URL if available
    play_addr_h265 = video.get("play_addr_h265", {})
    play_urls_h265 = play_addr_h265.get("url_list", [])

    return {
        "aweme_id": aweme_id,
        "desc": desc,
        "play_urls": play_urls,
        "download_urls": download_urls,
        "play_urls_h265": play_urls_h265,
        "duration": video.get("duration", 0),
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("=" * 60, flush=True)
    print("Douyin Video Downloader via XHR/Fetch Interception", flush=True)
    print("=" * 60, flush=True)

    driver, name = create_headless_driver("coccoc")
    print(f"Browser: {name}", flush=True)

    try:
        # Install hooks BEFORE loading any page
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": HOOK_SCRIPT})
        print("XHR/Fetch hooks installed", flush=True)

        # Load douyin
        driver.get("https://www.douyin.com/")
        time.sleep(3)
        print(f"Douyin: {driver.title}", flush=True)

        # Load channel  
        channel_url = "https://www.douyin.com/user/MS4wLjABAAAA6O7EZyfDRYXxJrUTpf91K3tmB4rBROkAw-nYMfld8ss"
        driver.get(channel_url)
        time.sleep(5)
        print(f"Channel: {driver.title}", flush=True)

        # Scroll to find videos
        video_ids = set()
        for i in range(5):
            source = driver.page_source
            new_ids = set(re.findall(r'/video/(\d{15,})', source))
            video_ids.update(new_ids)
            driver.execute_script("window.scrollBy(0, 2000)")
            time.sleep(1.5)

        video_ids = list(video_ids)
        print(f"\nFound {len(video_ids)} video IDs", flush=True)

        # Check if channel page captured any API responses already
        captured = driver.execute_script("return window.__captured_responses || [];")
        print(f"Captured {len(captured)} API responses from channel page", flush=True)
        for c in captured:
            print(f"  [{c.get('status')}] {c.get('url', '')[:100]}", flush=True)
            info = extract_video_info_from_response(c.get("body", ""))
            if info:
                print(f"    -> Video: {info['desc'][:50]}", flush=True)
                print(f"    -> Play URLs: {len(info['play_urls'])}", flush=True)

        # Now load each video page to trigger API calls
        for i, vid in enumerate(video_ids[:3]):  # Test first 3
            print(f"\n--- Video {i+1}/{len(video_ids)}: {vid} ---", flush=True)
            driver.get(f"https://www.douyin.com/video/{vid}")
            time.sleep(6)
            
            title = driver.title
            print(f"  Title: {title}", flush=True)

            # Get captured responses
            captured = driver.execute_script("return window.__captured_responses || [];")
            print(f"  Captured {len(captured)} responses", flush=True)

            for c in captured:
                print(f"  [{c.get('status')}] {c.get('url', '')[:80]}", flush=True)
                body = c.get("body", "")
                if len(body) > 100:
                    info = extract_video_info_from_response(body)
                    if info:
                        print(f"    Video: {info['desc'][:60]}", flush=True)
                        print(f"    Duration: {info['duration']}ms", flush=True)
                        if info['play_urls']:
                            play_url = info['play_urls'][0]
                            print(f"    Play URL: {play_url[:120]}...", flush=True)
                            
                            # Try to download
                            output_path = os.path.join(OUTPUT_DIR, f"{vid}.mp4")
                            try:
                                import urllib.request
                                req = urllib.request.Request(play_url)
                                req.add_header("User-Agent", "Mozilla/5.0")
                                req.add_header("Referer", "https://www.douyin.com/")
                                with urllib.request.urlopen(req, timeout=30) as resp:
                                    data = resp.read()
                                    with open(output_path, "wb") as f:
                                        f.write(data)
                                    print(f"    ✓ Downloaded! {len(data)/1024/1024:.1f} MB", flush=True)
                            except Exception as e:
                                print(f"    ✗ Download failed: {e}", flush=True)
                        
                        if info['download_urls']:
                            print(f"    Download URL: {info['download_urls'][0][:120]}...", flush=True)
                    else:
                        # Show first 200 chars of body for debugging
                        print(f"    Body preview: {body[:200]}", flush=True)

    finally:
        driver.quit()

    # List results
    print(f"\n{'='*60}", flush=True)
    if os.path.exists(OUTPUT_DIR):
        files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.mp4')]
        print(f"Downloaded {len(files)} videos:", flush=True)
        for f in files:
            size = os.path.getsize(os.path.join(OUTPUT_DIR, f))
            print(f"  {f} ({size/1024/1024:.1f} MB)", flush=True)
    
    print("[DONE]", flush=True)


if __name__ == "__main__":
    main()
