import requests
import json
import time
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

GRAPHQL = "https://www.facebook.com/api/graphql/"

# Base headers for all requests.
# Keep the UA bare: a full Chrome UA makes Facebook expect browser-only headers
# and reject GraphQL with AJAX error 1357054.
BASE_HEADERS = {
    "user-agent": "Mozilla/5.0",
    "content-type": "application/x-www-form-urlencoded"
}

# Get proxy configuration
PROXY = os.getenv('PROXY')
PROXIES = {'http': PROXY, 'https': PROXY} if PROXY else None

# FB_DTSG token (set by UI when provided)
FB_DTSG = ""

# GraphQL persisted-query IDs (Facebook rotates these; refresh if queries fail).
COMMENTS_DOC_ID = os.getenv("FB_COMMENTS_DOC_ID", "27806180149070312")
REPLIES_DOC_ID = os.getenv("FB_REPLIES_DOC_ID", "27888228590762910")
FEED_LOCATION = "POST_PERMALINK_DIALOG"
COMMENTS_INTENT_TOKEN = "REVERSE_CHRONOLOGICAL_UNFILTERED_INTENT_V1"

# Required Relay provider vars for the current UFI comment/reply queries.
# Omitting these yields missing_required_variable_value.
UFI_COMMENT_PROVIDER_VARS = {
    "__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider": "ORIGINAL",
    "__relay_internal__pv__CometUFICommentAvatarStickerAnimatedImagerelayprovider": False,
    "__relay_internal__pv__CometUFICommentActionLinksRewriteEnabledrelayprovider": False,
    "__relay_internal__pv__IsWorkUserrelayprovider": False,
}

STALE_QUERY_MARKERS = (
    "missing_required_variable_value",
    "VariableNotFoundError",
)

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

def _actor_id(cookies=None):
    if cookies and "c_user" in cookies:
        return cookies["c_user"]
    return "0"


def comments_payload(feedback_id, cursor=None, cookies=None):
    user_id = _actor_id(cookies)

    return {
        "av": user_id,
        "__user": user_id,
        "__a": "1",
        "fb_dtsg": FB_DTSG if FB_DTSG else "",
        "doc_id": COMMENTS_DOC_ID,
        "variables": json.dumps({
            "commentsAfterCount": -1,
            "commentsAfterCursor": cursor,
            "commentsBeforeCount": None,
            "commentsBeforeCursor": None,
            "commentsIntentToken": COMMENTS_INTENT_TOKEN,
            "feedLocation": FEED_LOCATION,
            "focusCommentID": None,
            "scale": 2,
            "useDefaultActor": False,
            "id": feedback_id,
            **UFI_COMMENT_PROVIDER_VARS,
        }, separators=(",", ":")),
    }


def replies_payload(comment_feedback_id, expansion_token, cursor=None, cookies=None):
    user_id = _actor_id(cookies)

    variables = {
        "clientKey": None,
        "expansionToken": expansion_token,
        "feedLocation": FEED_LOCATION,
        "focusCommentID": None,
        "repliesAfterCount": None,
        "repliesAfterCursor": cursor,
        "repliesBeforeCount": None,
        "repliesBeforeCursor": None,
        "scale": 2,
        "useDefaultActor": False,
        "id": comment_feedback_id,
        **UFI_COMMENT_PROVIDER_VARS,
    }

    return {
        "av": user_id,
        "__user": user_id,
        "__a": "1",
        "fb_dtsg": FB_DTSG if FB_DTSG else "",
        "doc_id": REPLIES_DOC_ID,
        "variables": json.dumps(variables, separators=(",", ":")),
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


def _extract_message_text(story):
    """Extract post message/body text from a parent_post_story node."""
    message = story.get("message") or {}
    text = message.get("text")
    if text:
        return text

    nested_story = story.get("story") or {}
    nested_message = nested_story.get("message") or {}
    text = nested_message.get("text")
    if text:
        return text

    for attachment in story.get("attachments") or []:
        title = attachment.get("title")
        if title:
            return title
        description = attachment.get("description")
        if description:
            return description

    return None


def extract_post_info(parent_post_story):
    """Build post_info dict from a parent_post_story GraphQL node."""
    post_info = {
        "post_story_id": parent_post_story.get("id"),
        "media_id": None,
        "post_title": _extract_message_text(parent_post_story),
    }

    for attachment in parent_post_story.get("attachments") or []:
        media = attachment.get("media") or {}
        if media.get("id"):
            post_info["media_id"] = media.get("id")
            break

    return post_info


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


def _raise_if_stale_query(payload, where):
    """Raise when Facebook rejects the persisted query schema/doc_id."""
    errors = payload.get("errors") or []
    for err in errors:
        message = str(err.get("message") or "")
        if any(marker in message for marker in STALE_QUERY_MARKERS):
            raise RuntimeError(
                f"Facebook rejected the {where} query as stale "
                f"(doc_id/variables out of date): {message}"
            )

    # AJAX-style envelope used when browser headers don't match the UA.
    ajax_error = payload.get("error")
    if ajax_error and payload.get("payload") is None and "data" not in payload:
        summary = payload.get("errorSummary") or ajax_error
        raise RuntimeError(f"Facebook rejected the {where} request: {summary}")


def _fetch_comments_once(feedback_id, cookies=None, progress=None):
    results = []
    seen_comment_ids = set()
    seen_cursors = set()
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
        _raise_if_stale_query(j, "comments")

        response_count += 1

        node = (j.get("data") or {}).get("node")
        if node is None:
            if response_count == 1 and progress is None:
                print("  No comment node returned for this feedback ID")
            break

        comments_block = (
            node.get("comment_rendering_instance_for_feed_location", {})
                .get("comments", {})
        )

        edges = comments_block.get("edges", [])
        if not edges:
            break

        new_on_page = 0
        for e in edges:
            n = e["node"]
            fb = n["feedback"]

            # Extract parent_post_story info from first response
            if response_count == 1 and post_info is None:
                parent_post_story = n.get("parent_post_story", {})
                if parent_post_story:
                    post_info = extract_post_info(parent_post_story)
                    if progress is None:
                        print(f"📎 Extracted post info: {post_info}")

            reactors = fb.get("reactors", {})
            total_reactions = reactors.get("count_reduced", "0")

            item = parse_comment_node(n)
            comment_id = item.get("comment_id")
            if comment_id and comment_id in seen_comment_ids:
                continue
            if comment_id:
                seen_comment_ids.add(comment_id)

            item["reaction_count"] = total_reactions
            results.append(item)
            new_on_page += 1

        if progress is not None:
            progress.update_comments_page(response_count, len(results))

        page_info = comments_block.get("page_info", {})
        if not page_info.get("has_next_page"):
            break
        next_cursor = page_info.get("end_cursor")
        if not next_cursor or next_cursor in seen_cursors or new_on_page == 0:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        time.sleep(0.3)

    return results, post_info


def fetch_comments(feedback_id, cookies=None, progress=None):
    """Fetch all comments, retrying when the API returns a truncated result."""
    if progress is not None:
        progress.start_comments()

    best_results, best_post_info = _fetch_comments_once(
        feedback_id, cookies=cookies, progress=progress
    )
    for attempt in range(2, 4):
        if progress is not None:
            progress.comments_attempt(attempt, 3, len(best_results))
        time.sleep(attempt * 2)
        results, post_info = _fetch_comments_once(
            feedback_id, cookies=cookies, progress=progress
        )
        if len(results) > len(best_results):
            best_results, best_post_info = results, post_info

    if progress is not None:
        progress.finish_comments(len(best_results))

    return best_results, best_post_info

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
        _raise_if_stale_query(j, "replies")
        node = (j.get("data") or {}).get("node") or {}
        replies_block = node.get("replies_connection", {})
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

