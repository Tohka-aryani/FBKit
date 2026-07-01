import requests
import json
import time
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

GRAPHQL = "https://www.facebook.com/api/graphql/"

# Base headers for all requests
BASE_HEADERS = {
    "user-agent": "Mozilla/5.0",
    "content-type": "application/x-www-form-urlencoded"
}

# Get proxy configuration
PROXY = os.getenv('PROXY')
PROXIES = {'http': PROXY, 'https': PROXY} if PROXY else None

# FB_DTSG token (set by UI when provided)
FB_DTSG = ""

if PROXY:
    print(f"Using proxy: {PROXY}")

# ========= RETRY HELPER =========
def retry_request(url, headers, data, proxies, cookies=None, max_retries=5):
    """Make a POST request with retry logic"""
    global PROXIES
    from proxy_utils import rotate_static_proxy, is_proxy_infra_error, is_ip_blocked

    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(url, headers=headers, data=data, proxies=proxies, cookies=cookies, timeout=30)
            if r.status_code == 200:
                return r
            if is_proxy_infra_error(status_code=r.status_code):
                print(f"  🚫 Attempt {attempt}/{max_retries}: Proxy auth failed (HTTP {r.status_code}) — rotating static proxy...")
                new_p = rotate_static_proxy()
                if new_p:
                    proxies = new_p
                    PROXIES = new_p
            elif is_ip_blocked(status_code=r.status_code, response_text=r.text):
                print(f"  🛑 Attempt {attempt}/{max_retries}: Facebook blocked this IP (HTTP {r.status_code}) — rotating static proxy...")
                new_p = rotate_static_proxy()
                if new_p:
                    proxies = new_p
                    PROXIES = new_p
            else:
                print(f"  ⚠️ Attempt {attempt}/{max_retries}: Status {r.status_code}")
        except requests.exceptions.ProxyError as e:
            print(f"  🚫 Attempt {attempt}/{max_retries}: Proxy unreachable — rotating static proxy...")
            new_p = rotate_static_proxy()
            if new_p:
                proxies = new_p
                PROXIES = new_p
        except Exception as e:
            if is_proxy_infra_error(exc=e):
                print(f"  🚫 Attempt {attempt}/{max_retries}: Proxy connection error — rotating static proxy...")
                new_p = rotate_static_proxy()
                if new_p:
                    proxies = new_p
                    PROXIES = new_p
            else:
                print(f"  ⚠️ Attempt {attempt}/{max_retries}: {str(e)}")

        if attempt < max_retries:
            wait_time = attempt * 2
            print(f"  ⏳ Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

    raise Exception(f"Failed after {max_retries} attempts")

# ===== PAYLOADS =====

def comments_payload(feedback_id, cursor=None, cookies=None):
    # Extract user ID from cookies if available
    user_id = "0"
    if cookies and "c_user" in cookies:
        user_id = cookies["c_user"]
    
    return {
        "av": user_id,
        "__user": user_id,
        "__a": "1",
        "fb_dtsg": FB_DTSG if FB_DTSG else "",
        "doc_id": "25550760954572974",
        "variables": json.dumps({
            "commentsAfterCount": -1,
            "commentsAfterCursor": cursor,
            "commentsIntentToken": "REVERSE_CHRONOLOGICAL_UNFILTERED_INTENT_V1",
            "feedLocation": "DEDICATED_COMMENTING_SURFACE",
            "focusCommentID": None,
            "scale": 2,
            "useDefaultActor": False,
            "id": feedback_id
        })
    }


def replies_payload(comment_feedback_id, expansion_token, cursor=None, cookies=None):
    # Extract user ID from cookies if available
    user_id = "0"
    if cookies and "c_user" in cookies:
        user_id = cookies["c_user"]

    variables = {
        "clientKey": None,
        "expansionToken": expansion_token,
        "feedLocation": "POST_PERMALINK_DIALOG",
        "focusCommentID": None,
        "scale": 2,
        "useDefaultActor": False,
        "id": comment_feedback_id,
    }
    if cursor:
        variables["after"] = cursor

    return {
        "av": user_id,
        "__user": user_id,
        "__a": "1",
        "fb_dtsg": FB_DTSG if FB_DTSG else "",
        "doc_id": "26570577339199586",
        "variables": json.dumps(variables),
    }

# ===== FETCH COMMENTS =====

def extract_author(node):
    """Extract author name and ID from a comment/reply node."""
    author = node.get("author") or {}
    return {
        "author": author.get("name"),
        "author_id": author.get("id"),
    }


def parse_comment_node(node):
    """Parse a GraphQL comment or reply node into a dict."""
    fb = node.get("feedback") or {}
    reactors = fb.get("reactors", {})
    expansion = fb.get("expansion_info") or {}

    item = {
        "comment_id": node.get("legacy_fbid"),
        **extract_author(node),
        "text": (node.get("body") or {}).get("text", ""),
        "reaction_count": reactors.get("count_reduced", "0"),
    }

    if fb.get("id") and expansion.get("expansion_token"):
        item["_feedback_id"] = fb["id"]
        item["_expansion_token"] = expansion["expansion_token"]
        item["_has_subreplies"] = bool(expansion.get("should_show_reply_count"))

    return item


def clean_comment_item(item):
    """Remove internal fields used only for API pagination."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def fb_json(response_text):
    """
    Facebook GraphQL sometimes returns:
    for (;;);
    {json}
    {json}

    This extracts the first valid JSON object safely.
    """
    text = response_text.strip()

    # Remove for (;;);
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):]

    # Keep only first JSON object
    first = text.split("\n")[0].strip()

    return json.loads(first)


def fetch_comments(feedback_id, cookies=None):
    results = []
    cursor = None
    response_count = 0
    post_info = None  # Store parent post info from first response

    while True:
        headers = {**BASE_HEADERS, "x-fb-friendly-name": "CommentsListComponentsPaginationQuery"}
        r = retry_request(
            GRAPHQL,
            headers,
            comments_payload(feedback_id, cursor, cookies),
            PROXIES,
            cookies=cookies
        )
        j = fb_json(r.text)
        
        # Save each JSON response for inspection
        response_count += 1
        # with open(f"response_{response_count}.json", "w", encoding="utf-8") as f:
        #     json.dump(j, f, ensure_ascii=False, indent=2)
        # print(f"💾 Saved response_{response_count}.json")
        
        comments_block = (
            j.get("data", {})
             .get("node", {})
             .get("comment_rendering_instance_for_feed_location", {})
             .get("comments", {})
        )

        edges = comments_block.get("edges", [])
        if not edges:
            break

        for e in edges:
            n = e["node"]
            fb = n["feedback"]

            # Extract parent_post_story info from first response
            if response_count == 1 and post_info is None:
                parent_post_story = n.get("parent_post_story", {})
                
                if parent_post_story:
                    post_info = {
                        "post_story_id": parent_post_story.get("id"),
                        "media_id": None
                    }
                    
                    # Extract first media ID
                    attachments = parent_post_story.get("attachments", [])
                    for attachment in attachments:
                        media = attachment.get("media", {})
                        if media and media.get("id"):
                            post_info["media_id"] = media.get("id")
                            break  # Only get first one
                    
                    print(f"📎 Extracted post info: {post_info}")

            reactors = fb.get("reactors", {})
            total_reactions = reactors.get("count_reduced", "0")

            item = parse_comment_node(n)
            item["reaction_count"] = total_reactions
            results.append(item)

        cursor = comments_block.get("page_info", {}).get("end_cursor")
        #break
        if not cursor:
            break

        #time.sleep(0.4)

    return results, post_info

# ===== FETCH REPLIES =====

def fetch_replies(comment, cookies=None):
    """Fetch direct replies for a comment."""
    if not comment.get("_feedback_id") or not comment.get("_expansion_token"):
        return []

    headers = {**BASE_HEADERS, "x-fb-friendly-name": "Depth1CommentsListPaginationQuery"}
    replies = []
    seen_reply_ids = set()
    seen_cursors = set()
    cursor = None

    while True:
        r = retry_request(
            GRAPHQL,
            headers,
            replies_payload(
                comment["_feedback_id"],
                comment["_expansion_token"],
                cursor=cursor,
                cookies=cookies,
            ),
            PROXIES,
            cookies=cookies,
        )

        j = fb_json(r.text)
        replies_block = (
            j.get("data", {})
            .get("node", {})
            .get("replies_connection", {})
        )
        edges = replies_block.get("edges", [])
        if not edges:
            break

        new_on_page = 0
        for e in edges:
            n = e["node"]
            reply = parse_comment_node(n)
            reply_id = reply.get("comment_id")
            if reply_id and reply_id in seen_reply_ids:
                continue
            if reply_id:
                seen_reply_ids.add(reply_id)

            clean_reply = clean_comment_item(reply)
            clean_reply["reply_id"] = clean_reply.pop("comment_id", None)
            replies.append(clean_reply)
            new_on_page += 1

        page_info = replies_block.get("page_info", {})
        if not page_info.get("has_next_page"):
            break
        next_cursor = page_info.get("end_cursor")
        if not next_cursor or next_cursor in seen_cursors or new_on_page == 0:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return replies

