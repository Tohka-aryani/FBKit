import base64
import json
import os
import re
import time
from html import unescape

import requests
from dotenv import load_dotenv

from comment_scraper import PROXIES, clean_comment_item, fetch_comments, fetch_replies

load_dotenv()

POST_URL_FILE = "post_url.txt"


def load_post_urls(filepath=POST_URL_FILE):
    """Load Facebook post URLs from a text file (one URL per line)."""
    if not os.path.isfile(filepath):
        return []

    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def extract_post_id_from_url(url, cookies=None):
    """Extract Facebook Post ID from a post URL."""
    url_patterns = [
        r"/groups/[^/]+/posts/(\d+)",
        r"/posts/(\d+)",
    ]

    for pattern in url_patterns:
        match = re.search(pattern, url)
        if match:
            post_id = match.group(1)
            print(f"  Found Post ID in URL: {post_id}")
            return post_id

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        print(f"  No direct ID in URL, fetching post: {url}")
        response = requests.get(
            url, headers=headers, cookies=cookies, proxies=PROXIES, timeout=20
        )
        html = response.text
        post_id = None

        if cookies:
            story_id_match = re.search(r'"storyID":"([^"]+)"', html)
            if story_id_match:
                try:
                    story_id_decoded = base64.b64decode(
                        story_id_match.group(1)
                    ).decode("utf-8")
                    parts = story_id_decoded.split(":")
                    if len(parts) >= 2:
                        post_id = parts[-1]
                        print(f"  Found Post ID from storyID: {post_id}")
                        return post_id
                except Exception as e:
                    print(f"  Could not decode storyID: {e}")

        og_url_match = re.search(
            r'<meta property="og:url" content="([^"]+)"', html
        )
        if og_url_match:
            og_url = unescape(og_url_match.group(1))
            m = re.search(r"/posts/(?:[^/]+/)?(\d+)", og_url)
            if not m:
                m = re.search(r"story_fbid=(\d+)", og_url)
            if m:
                post_id = m.group(1)

        if post_id:
            print(f"  Found Post ID from og:url: {post_id}")
            return post_id

        print("  Post ID not found in URL")
        return None

    except Exception as e:
        print(f"  Error fetching URL: {e}")
        return None


def convert_post_id_to_feedback_id(post_id):
    """Convert post_id to feedback_id using base64 encoding."""
    return base64.b64encode(f"feedback:{post_id}".encode()).decode()


def fetch_comments_for_post(post_id, cookies=None, fb_dtsg=None):
    """Fetch all comments and replies for a given post_id."""
    import comment_scraper

    comment_scraper.FB_DTSG = fb_dtsg or ""

    feedback_id = convert_post_id_to_feedback_id(post_id)
    print(f"  Fetching comments for post {post_id}...")
    print(f"  Using feedback_id: {feedback_id}")

    all_data = []
    comments, post_info = fetch_comments(feedback_id, cookies=cookies)

    for c in comments:
        author = c.get("author") or "Unknown"
        print(f"    {author}: {c.get('text', '')[:50]}...")
        c["replies"] = fetch_replies(c, cookies=cookies)

        for r in c["replies"]:
            reply_author = r.get("author") or "Unknown"
            print(f"       -> {reply_author}: {r.get('text', '')[:50]}...")

        all_data.append(clean_comment_item(c))

    print(f"  Found {len(all_data)} comments")
    return all_data, post_info


def save_post_data(post_id, post_data, comments_data):
    """Save post and comments data under simple_post/<post_id>/."""
    folder_path = os.path.join("simple_post", post_id)
    os.makedirs(folder_path, exist_ok=True)

    combined_data = {**post_data, "comments": comments_data}
    output_file = os.path.join(folder_path, f"{post_id}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(combined_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved to {output_file}")


def scrape_single_post_url(url, cookies=None, fb_dtsg=None):
    """Scrape comments and replies for one Facebook post URL."""
    print(f"\nProcessing: {url}")
    post_id = extract_post_id_from_url(url, cookies=cookies)
    if not post_id:
        print("  Could not extract post ID from URL")
        return False

    print(f"  Post ID: {post_id}")
    comments, post_info = fetch_comments_for_post(
        post_id, cookies=cookies, fb_dtsg=fb_dtsg
    )

    post_data = {
        "post_id": post_id,
        "source_url": url,
        "type": "simple_post",
        "post_info": post_info,
    }
    save_post_data(post_id, post_data, comments)
    print(f"  Done: simple_post/{post_id}/{post_id}.json")
    return True


def scrape_posts_from_file(filepath=POST_URL_FILE, cookies=None, fb_dtsg=None):
    """Scrape all post URLs listed in a text file."""
    urls = load_post_urls(filepath)
    if not urls:
        print(f"No URLs found in {filepath}")
        print("   Add one Facebook post URL per line.")
        return

    print(f"Loaded {len(urls)} URL(s) from {filepath}")
    succeeded = 0
    failed = 0

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}]", end="")
        try:
            if scrape_single_post_url(url, cookies=cookies, fb_dtsg=fb_dtsg):
                succeeded += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  Error: {e}")
            failed += 1

        if i < len(urls):
            time.sleep(1)

    print(f"\n{'=' * 60}")
    print(f"Batch complete: {succeeded} succeeded, {failed} failed")
    print("Output directory: simple_post/")


if __name__ == "__main__":
    scrape_posts_from_file()
