import base64
import json
import os
import re
import time
from datetime import datetime
from html import unescape

import requests
from dotenv import load_dotenv

from comment_scraper import PROXIES, clean_comment_item, fetch_comments, fetch_replies

load_dotenv()

POST_URL_FILE = "post_url.txt"
OUTPUT_DIR = "output"


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


def make_run_timestamp(when=None):
    """Return display and filesystem-safe timestamp strings for a batch run."""
    when = when or datetime.now()
    display = when.strftime("%Y-%m-%d %H:%M:%S")
    filename = when.strftime("%Y-%m-%d %H-%M-%S")
    return display, filename


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


def save_batch_output(posts, failures, scraped_at_display, filename_stamp):
    """Save all scraped posts from one batch run to a timestamped JSON file."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    output = {
        "scraped_at": scraped_at_display,
        "post_count": len(posts),
        "succeeded": len(posts),
        "failed": len(failures),
        "posts": posts,
    }
    if failures:
        output["failures"] = failures

    output_file = os.path.join(OUTPUT_DIR, f"{filename_stamp}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved batch output to {output_file}")
    return output_file


def scrape_single_post_url(url, cookies=None, fb_dtsg=None):
    """Scrape comments and replies for one Facebook post URL."""
    print(f"\nProcessing: {url}")
    post_id = extract_post_id_from_url(url, cookies=cookies)
    if not post_id:
        print("  Could not extract post ID from URL")
        return None

    print(f"  Post ID: {post_id}")
    comments, post_info = fetch_comments_for_post(
        post_id, cookies=cookies, fb_dtsg=fb_dtsg
    )

    return {
        "post_id": post_id,
        "source_url": url,
        "post_info": post_info,
        "comments": comments,
    }


def scrape_posts_from_file(filepath=POST_URL_FILE, cookies=None, fb_dtsg=None):
    """Scrape all post URLs listed in a text file."""
    urls = load_post_urls(filepath)
    if not urls:
        print(f"No URLs found in {filepath}")
        print("   Add one Facebook post URL per line.")
        return

    scraped_at_display, filename_stamp = make_run_timestamp()
    print(f"Loaded {len(urls)} URL(s) from {filepath}")
    print(f"Batch timestamp: {scraped_at_display}")

    posts = []
    failures = []

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}]", end="")
        try:
            result = scrape_single_post_url(url, cookies=cookies, fb_dtsg=fb_dtsg)
            if result:
                posts.append(result)
            else:
                failures.append({"url": url, "error": "Could not extract post ID"})
        except Exception as e:
            print(f"  Error: {e}")
            failures.append({"url": url, "error": str(e)})

        if i < len(urls):
            time.sleep(1)

    save_batch_output(posts, failures, scraped_at_display, filename_stamp)

    print(f"\n{'=' * 60}")
    print(f"Batch complete: {len(posts)} succeeded, {len(failures)} failed")
    print(f"Output directory: {OUTPUT_DIR}/")


if __name__ == "__main__":
    scrape_posts_from_file()
