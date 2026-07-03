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
from post_content import resolve_post_title
from progress_tracker import ProgressTracker
from url_resolver import extract_video_id_from_url, resolve_feedback_id_from_video

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


def classify_post_url(url):
    """Classify a Facebook URL as group_post, profile_post, or reel."""
    if extract_video_id_from_url(url):
        return {"post_type": "reel", "group_slug": None}

    group_match = re.search(r"/groups/([^/]+)/posts/", url)
    if group_match:
        return {"post_type": "group_post", "group_slug": group_match.group(1)}

    return {"post_type": "profile_post", "group_slug": None}


def extract_post_id_from_url(url, cookies=None, quiet=False):
    """Extract Facebook Post ID from a post URL."""
    url_patterns = [
        r"/groups/[^/]+/posts/(\d+)",
        r"/posts/(\d+)",
    ]

    for pattern in url_patterns:
        match = re.search(pattern, url)
        if match:
            post_id = match.group(1)
            if not quiet:
                print(f"  Found Post ID in URL: {post_id}")
            return post_id

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        if not quiet:
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
                        if not quiet:
                            print(f"  Found Post ID from storyID: {post_id}")
                        return post_id
                except Exception as e:
                    if not quiet:
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
            if not quiet:
                print(f"  Found Post ID from og:url: {post_id}")
            return post_id

        if not quiet:
            print("  Post ID not found in URL")
        return None

    except Exception as e:
        if not quiet:
            print(f"  Error fetching URL: {e}")
        return None


def convert_post_id_to_feedback_id(post_id):
    """Convert post_id to feedback_id using base64 encoding."""
    return base64.b64encode(f"feedback:{post_id}".encode()).decode()


def resolve_url(url, cookies=None, quiet=False):
    """Resolve a Facebook post or reel URL to scrape targets."""
    classification = classify_post_url(url)

    video_id = extract_video_id_from_url(url)
    if video_id:
        if not quiet:
            print(f"  Found Video ID in URL: {video_id}")
        feedback_id = resolve_feedback_id_from_video(
            video_id, cookies=cookies, quiet=quiet
        )
        return {
            "content_id": video_id,
            "content_type": "reel",
            "post_type": classification["post_type"],
            "group_slug": classification["group_slug"],
            "feedback_id": feedback_id,
        }

    post_id = extract_post_id_from_url(url, cookies=cookies, quiet=quiet)
    if post_id:
        return {
            "content_id": post_id,
            "content_type": "post",
            "post_type": classification["post_type"],
            "group_slug": classification["group_slug"],
            "feedback_id": convert_post_id_to_feedback_id(post_id),
        }

    return None


def fetch_comments_for_post(
    post_id, cookies=None, fb_dtsg=None, progress=None, feedback_id=None
):
    """Fetch all comments and replies for a post or reel."""
    import comment_scraper

    comment_scraper.FB_DTSG = fb_dtsg or ""

    if feedback_id is None:
        feedback_id = convert_post_id_to_feedback_id(post_id)

    all_data = []
    comments, post_info = fetch_comments(
        feedback_id, cookies=cookies, progress=progress
    )

    total_replies = 0
    if progress is not None:
        progress.start_replies(len(comments))

    for idx, c in enumerate(comments, 1):
        if progress is not None:
            progress.update_replies(idx, len(comments))
        c["replies"] = fetch_replies(c, cookies=cookies)
        total_replies += len(c["replies"])
        all_data.append(clean_comment_item(c))

    if progress is not None:
        progress.finish_post(len(all_data), total_replies)

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

    return output_file


def scrape_single_post_url(url, cookies=None, fb_dtsg=None, progress=None):
    """Scrape comments and replies for one Facebook post URL."""
    quiet = progress is not None

    if progress is not None:
        progress.set_phase("resolving URL")

    resolved = resolve_url(url, cookies=cookies, quiet=quiet)
    if not resolved:
        return None

    if progress is not None:
        progress.set_post_id(resolved["content_id"])

    comments, post_info = fetch_comments_for_post(
        resolved["content_id"],
        cookies=cookies,
        fb_dtsg=fb_dtsg,
        progress=progress,
        feedback_id=resolved["feedback_id"],
    )

    if post_info is None:
        post_info = {}

    post_title = resolve_post_title(
        url,
        resolved["post_type"],
        post_info=post_info,
        cookies=cookies,
        fb_dtsg=fb_dtsg,
        quiet=quiet,
    )
    if post_title:
        post_info["post_title"] = post_title

    result = {
        "post_id": resolved["content_id"],
        "content_type": resolved["content_type"],
        "post_type": resolved["post_type"],
        "post_title": post_title,
        "source_url": url,
        "post_info": post_info,
        "comments": comments,
    }
    if resolved.get("group_slug"):
        result["group_slug"] = resolved["group_slug"]

    return result


def scrape_posts_from_file(filepath=POST_URL_FILE, cookies=None, fb_dtsg=None):
    """Scrape all post URLs listed in a text file."""
    urls = load_post_urls(filepath)
    if not urls:
        print(f"No URLs found in {filepath}")
        print("   Add one Facebook post URL per line.")
        return

    scraped_at_display, filename_stamp = make_run_timestamp()

    posts = []
    failures = []

    with ProgressTracker() as progress:
        progress.start_batch(len(urls))

        for i, url in enumerate(urls, 1):
            progress.start_post(i, url)
            try:
                result = scrape_single_post_url(
                    url, cookies=cookies, fb_dtsg=fb_dtsg, progress=progress
                )
                if result:
                    posts.append(result)
                else:
                    failures.append({"url": url, "error": "Could not resolve URL"})
            except Exception as e:
                progress.console.print(f"[bold red]Error:[/bold red] {e}")
                failures.append({"url": url, "error": str(e)})

            if i < len(urls):
                progress.set_phase("waiting before next post")
                time.sleep(3)

        progress.set_phase("saving batch")
        output_file = save_batch_output(
            posts, failures, scraped_at_display, filename_stamp
        )
        progress.finish_batch(len(posts), len(failures), output_file)


if __name__ == "__main__":
    scrape_posts_from_file()
