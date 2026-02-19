"""
ReviewMate: Fetch reviews from Google Business Profile and post replies.
Uses v4 API: list reviews (paginated), updateReply for posting.
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import requests

REVIEWS_LIST_TEMPLATE = "https://mybusiness.googleapis.com/v4/accounts/{account_id}/locations/{location_id}/reviews"
REPLY_URL_TEMPLATE = "https://mybusiness.googleapis.com/v4/accounts/{account_id}/locations/{location_id}/reviews/{review_id}/reply"

# Map API star rating enum to integer 1-5
STAR_MAP = {
    "ONE": 1,
    "TWO": 2,
    "THREE": 3,
    "FOUR": 4,
    "FIVE": 5,
}


def _star_to_int(star_rating: str) -> int:
    if not star_rating:
        return 0
    return STAR_MAP.get(star_rating.upper().replace("STAR_RATING_", ""), 0) or int(star_rating) if str(star_rating).isdigit() else 0


def fetch_all_reviews(
    access_token: str,
    account_id: str,
    location_id: str,
    page_size: int = 50,
) -> List[dict]:
    """
    Fetch all reviews for a location (handles pagination).
    Returns list of dicts with: google_review_id, reviewer_name, star_rating (1-5), review_text,
    review_created_at, review_updated_at, has_existing_reply, existing_reply_text.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    url = REVIEWS_LIST_TEMPLATE.format(account_id=account_id, location_id=location_id)
    all_reviews = []
    page_token = None
    while True:
        params = {"pageSize": page_size}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        for rev in data.get("reviews") or []:
            name = rev.get("name") or ""
            if "/" in name:
                review_id = name.split("/")[-1]
            else:
                review_id = rev.get("reviewId") or name or ""
            reviewer = rev.get("reviewer") or {}
            reviewer_name = reviewer.get("displayName") or ""
            if reviewer.get("isAnonymous"):
                reviewer_name = reviewer_name or "Anonymous"
            star_rating = _star_to_int(rev.get("starRating") or "")
            if star_rating < 1 or star_rating > 5:
                star_rating = 1
            comment = (rev.get("comment") or "").strip()
            create_time = rev.get("createTime")
            update_time = rev.get("updateTime")
            reply = rev.get("reviewReply") or {}
            has_reply = bool(reply.get("comment"))
            reply_text = (reply.get("comment") or "").strip() if has_reply else None
            all_reviews.append({
                "google_review_id": review_id,
                "reviewer_name": reviewer_name[:500] if reviewer_name else None,
                "star_rating": star_rating,
                "review_text": comment or None,
                "review_created_at": create_time,
                "review_updated_at": update_time,
                "has_existing_reply": has_reply,
                "existing_reply_text": reply_text,
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return all_reviews


def post_reply(
    access_token: str,
    account_id: str,
    location_id: str,
    review_id: str,
    comment: str,
) -> None:
    """
    Post or update the reply to a review. comment is the reply text (max 4096 bytes).
    Raises requests.HTTPError on API failure.
    """
    url = REPLY_URL_TEMPLATE.format(
        account_id=account_id,
        location_id=location_id,
        review_id=review_id,
    )
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    body = {"comment": (comment or "")[:4096]}
    r = requests.put(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
