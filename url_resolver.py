import base64
import json
import re

from comment_scraper import (
    BASE_HEADERS,
    GRAPHQL,
    PROXIES,
    fb_json,
    retry_request,
)

VIDEO_URL_PATTERNS = [
    r"/reel/(\d+)",
    r"[?&]v=(\d+)",
    r"/videos/(?:[^/]+/)?(\d+)",
]

TAHOE_DOC_ID = "5279476072161634"


def extract_video_id_from_url(url):
    """Extract a Facebook video/reel numeric ID from supported URL shapes."""
    for pattern in VIDEO_URL_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _story_feedback_token_from_tahoe_response(response_text):
    """Return the story-level feedback token from a CometTahoeSidePaneQuery response."""
    for token in re.findall(r"ZmVlZGJhY2s6[A-Za-z0-9+/=]+", response_text):
        decoded = base64.b64decode(token).decode(errors="ignore")
        if re.fullmatch(r"feedback:\d+", decoded):
            return token
    return None


def resolve_feedback_id_from_video(video_id, cookies=None, quiet=False):
    """Resolve a reel/watch/video ID to its GraphQL story feedback token."""
    payload = {
        "av": "0",
        "__user": "0",
        "__a": "1",
        "fb_dtsg": "",
        "doc_id": TAHOE_DOC_ID,
        "variables": json.dumps(
            {
                "UFI2CommentsProvider_commentsKey": "CometTahoeSidePaneQuery",
                "caller": "CHANNEL_VIEW_FROM_PAGE_TIMELINE",
                "displayCommentsContextEnableComment": None,
                "displayCommentsContextIsAdPreview": None,
                "displayCommentsContextIsAggregatedShare": None,
                "displayCommentsContextIsStorySet": None,
                "displayCommentsFeedbackContext": None,
                "feedbackSource": 41,
                "feedLocation": "TAHOE",
                "focusCommentID": None,
                "privacySelectorRenderLocation": "COMET_STREAM",
                "renderLocation": "video_channel",
                "scale": 1,
                "streamChainingSection": False,
                "useDefaultActor": False,
                "videoChainingContext": None,
                "videoID": video_id,
            }
        ),
    }
    headers = {**BASE_HEADERS, "x-fb-friendly-name": "CometTahoeSidePaneQuery"}
    response = retry_request(GRAPHQL, headers, payload, PROXIES, cookies=cookies)
    data = fb_json(response.text)

    if data.get("errors"):
        message = data["errors"][0].get("message", "CometTahoeSidePaneQuery failed")
        raise ValueError(message)

    feedback_id = _story_feedback_token_from_tahoe_response(response.text)
    if not feedback_id:
        raise ValueError(f"No story feedback found for video {video_id}")

    if not quiet:
        decoded = base64.b64decode(feedback_id).decode(errors="ignore")
        numeric_id = decoded.split(":", 1)[1]
        print(f"  Resolved video feedback ID: {numeric_id}")

    return feedback_id
