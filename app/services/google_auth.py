"""
Google OAuth 2.0 and Business Profile account/location helpers for ReviewMate.
Uses REVIEW_GOOGLE_* env vars. Requires: REVIEW_GOOGLE_CLIENT_ID, REVIEW_GOOGLE_CLIENT_SECRET, REVIEW_GOOGLE_REDIRECT_URI.
"""
import json
import secrets
import urllib.parse
from typing import List, Tuple
from datetime import datetime, timedelta, timezone

import requests

from ..settings import settings

# Scope for Business Profile API (manage listings, reply to reviews)
SCOPE = "https://www.googleapis.com/auth/business.manage"

# OAuth URLs
AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
# Account/location APIs (v4)
ACCOUNTS_LIST_URL = "https://mybusiness.googleapis.com/v4/accounts"
LOCATIONS_LIST_TEMPLATE = "https://mybusiness.googleapis.com/v4/{parent}/locations"


def _review_config_ok() -> bool:
    """Return True if Review OAuth is configured."""
    return bool(
        getattr(settings, "REVIEW_GOOGLE_CLIENT_ID", None)
        and getattr(settings, "REVIEW_GOOGLE_CLIENT_SECRET", None)
        and getattr(settings, "REVIEW_GOOGLE_REDIRECT_URI", None)
    )


def get_authorization_url(state: str) -> str:
    """Build Google OAuth authorization URL. Redirect user here to start OAuth."""
    if not _review_config_ok():
        raise ValueError("Review OAuth not configured (REVIEW_GOOGLE_* env vars)")
    params = {
        "client_id": settings.REVIEW_GOOGLE_CLIENT_ID,
        "redirect_uri": settings.REVIEW_GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",  # Force consent to get refresh_token
    }
    return f"{AUTH_BASE}?{urllib.parse.urlencode(params)}"


def generate_state() -> str:
    """Generate a cryptographically secure state string for OAuth."""
    return secrets.token_urlsafe(32)


def exchange_code_for_tokens(code: str) -> Tuple[str, str, datetime]:
    """
    Exchange authorization code for access_token and refresh_token.
    Returns (access_token, refresh_token, token_expires_at).
    """
    if not _review_config_ok():
        raise ValueError("Review OAuth not configured")
    r = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.REVIEW_GOOGLE_CLIENT_ID,
            "client_secret": settings.REVIEW_GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.REVIEW_GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    access = data.get("access_token") or data.get("accessToken")
    refresh = data.get("refresh_token") or data.get("refreshToken")
    if not access:
        raise ValueError("No access_token in token response")
    if not refresh:
        raise ValueError("No refresh_token in token response (use prompt=consent)")
    expires_in = int(data.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return access, refresh, expires_at


def refresh_access_token(refresh_token: str) -> Tuple[str, datetime]:
    """
    Get a new access_token using refresh_token.
    Returns (access_token, token_expires_at).
    """
    if not _review_config_ok():
        raise ValueError("Review OAuth not configured")
    r = requests.post(
        TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": settings.REVIEW_GOOGLE_CLIENT_ID,
            "client_secret": settings.REVIEW_GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    access = data.get("access_token")
    if not access:
        raise ValueError("No access_token in refresh response")
    expires_in = int(data.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return access, expires_at


def fetch_locations(access_token: str) -> List[dict]:
    """
    Fetch all accounts and their locations using the Business Profile API.
    Returns a list of dicts: [{"account_id": str, "location_id": str, "name": str}, ...]
    """
    locations_out = []
    next_page = None
    accounts_seen = []
    headers = {"Authorization": f"Bearer {access_token}"}
    while True:
        url = ACCOUNTS_LIST_URL
        if next_page:
            url += "?pageToken=" + urllib.parse.quote(next_page)
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        for acc in data.get("accounts") or []:
            name = acc.get("name") or acc.get("accountName")
            if not name or name in accounts_seen:
                continue
            accounts_seen.append(name)
            if "/" in name:
                account_id = name.split("/", 1)[-1]
            else:
                account_id = name
            parent = f"accounts/{account_id}"
            loc_url = LOCATIONS_LIST_TEMPLATE.format(parent=parent)
            loc_next = None
            while True:
                loc_req_url = loc_url
                if loc_next:
                    sep = "&" if "?" in loc_req_url else "?"
                    loc_req_url += f"{sep}pageToken={urllib.parse.quote(loc_next)}"
                try:
                    lr = requests.get(loc_req_url, headers=headers, timeout=30)
                    if lr.status_code in (403, 404):
                        break
                    lr.raise_for_status()
                    loc_data = lr.json()
                except requests.RequestException:
                    break
                for loc in loc_data.get("locations") or []:
                    loc_name = loc.get("name") or loc.get("locationName") or ""
                    if "/" in loc_name:
                        loc_id = loc_name.split("/")[-1]
                    else:
                        loc_id = loc_name or ""
                    meta = loc.get("metadata") or {}
                    display = meta.get("title") or loc.get("title") or ""
                    if not display and isinstance(loc.get("storefrontAddress"), dict):
                        lines = (loc.get("storefrontAddress") or {}).get("addressLines") or []
                        display = lines[0] if lines else ""
                    if not display:
                        display = loc.get("locationName") or loc_name or loc_id or "Unnamed location"
                    locations_out.append({
                        "account_id": account_id,
                        "location_id": loc_id,
                        "name": str(display)[:500],
                    })
                loc_next = loc_data.get("nextPageToken")
                if not loc_next:
                    break
        next_page = data.get("nextPageToken")
        if not next_page:
            break
    return locations_out
