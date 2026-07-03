import json
import re
from html import unescape

import requests

from comment_scraper import BASE_HEADERS, FB_DTSG, GRAPHQL, PROXIES, fb_json, retry_request

STORY_CONTENT_DOC_ID = "27602768712688932"


def is_truncated_preview(text):
    """Return True when text looks like a Facebook preview snippet."""
    if not text:
        return True
    stripped = text.rstrip()
    return stripped.endswith("...") or stripped.endswith("…")


def pick_best_post_title(candidates):
    """Prefer the longest non-truncated post body, otherwise the longest text."""
    cleaned = []
    for text in candidates:
        if not text or not isinstance(text, str):
            continue
        text = text.strip()
        if text and text not in cleaned:
            cleaned.append(text)

    if not cleaned:
        return None

    full_texts = [text for text in cleaned if not is_truncated_preview(text)]
    pool = full_texts or cleaned
    return max(pool, key=len)


def _parse_meta_content(html, property_name):
    match = re.search(
        rf'<meta property="{re.escape(property_name)}" content="([^"]*)"',
        html,
    )
    return unescape(match.group(1)).strip() if match else None


def extract_story_id_from_html(html):
    match = re.search(r'"storyID":"([^"]+)"', html)
    return match.group(1) if match else None


def extract_message_texts_from_json(data):
    """Collect message.text values from a parsed hydration JSON tree."""
    texts = []

    def walk(obj):
        if isinstance(obj, dict):
            message = obj.get("message")
            if isinstance(message, dict):
                text = message.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    return texts


def extract_messages_from_hydration(html):
    scripts = re.findall(
        r'<script type="application/json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    texts = []
    for script in scripts:
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue
        texts.extend(extract_message_texts_from_json(data))
    return texts


def fetch_post_page_html(url, cookies=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = requests.get(
        url, headers=headers, cookies=cookies, proxies=PROXIES, timeout=20
    )
    return response.text


def fetch_story_message(story_id, cookies=None, fb_dtsg=None, quiet=False):
    """Fetch the full post body via CometSinglePostDialogContentQuery."""
    if not story_id:
        return None

    user_id = "0"
    if cookies and "c_user" in cookies:
        user_id = cookies["c_user"]

    variables = {
        "storyID": story_id,
        "scale": 2,
        "useDefaultActor": False,
        "renderLocation": "permalink",
        "feedLocation": "POST_PERMALINK_DIALOG",
        "feedbackSource": 2,
        "focusCommentID": None,
        "privacySelectorRenderLocation": "COMET_STREAM",
        "referringStoryRenderLocation": None,
        "shouldChangeNodeFieldName": False,
    }

    headers = {
        **BASE_HEADERS,
        "x-fb-friendly-name": "CometSinglePostDialogContentQuery",
    }
    data = {
        "av": user_id,
        "__user": user_id,
        "__a": "1",
        "fb_dtsg": fb_dtsg or FB_DTSG or "",
        "doc_id": STORY_CONTENT_DOC_ID,
        "variables": json.dumps(variables),
    }

    try:
        response = retry_request(
            GRAPHQL, headers, data, PROXIES, cookies=cookies
        )
        payload = fb_json(response.text)
        return pick_best_post_title(extract_message_texts_from_json(payload))
    except Exception as e:
        if not quiet:
            print(f"  Could not fetch full post text: {e}")
        return None


def resolve_post_title(
    url,
    post_type,
    post_info=None,
    cookies=None,
    fb_dtsg=None,
    quiet=False,
):
    """Resolve the best available post body from GraphQL, HTML, and hydration data."""
    candidates = []
    post_info = post_info or {}

    if post_info.get("post_title"):
        candidates.append(post_info["post_title"])

    story_id = post_info.get("post_story_id")
    html = None

    try:
        if not quiet:
            print(f"  Fetching post page for full text: {url}")
        html = fetch_post_page_html(url, cookies=cookies)

        if not story_id:
            story_id = extract_story_id_from_html(html)

        candidates.extend(extract_messages_from_hydration(html))

        og_description = _parse_meta_content(html, "og:description")
        if og_description:
            candidates.append(og_description)

        og_title = _parse_meta_content(html, "og:title")
        if og_title:
            if post_type == "group_post" and " | " in og_title:
                candidates.append(og_title.split(" | ", 1)[1].strip())
            else:
                candidates.append(og_title)
    except Exception as e:
        if not quiet:
            print(f"  Error fetching post page metadata: {e}")

    story_message = fetch_story_message(
        story_id, cookies=cookies, fb_dtsg=fb_dtsg, quiet=quiet
    )
    if story_message:
        candidates.append(story_message)

    return pick_best_post_title(candidates)
