"""
ReviewMate: Ensure we have a valid access token for a review_connection.
Refreshes the token if expired (with a small buffer).
"""
from datetime import datetime, timezone, timedelta

from ..db import get_conn
from ..services.google_auth import refresh_access_token

# Refresh if token expires in less than 5 minutes
BUFFER_SECONDS = 300


def get_valid_access_token(connection_id: str) -> str:
    """
    Return a valid access_token for the given connection_id.
    If the stored token is expired (or within BUFFER_SECONDS of expiry), refresh it and update the DB.
    Raises ValueError if connection not found or refresh fails.
    """
    with get_conn() as conn:
        row = conn.execute(
            """SELECT access_token, refresh_token, token_expires_at
               FROM review_connections WHERE id = %s AND is_active = TRUE""",
            (connection_id,),
        ).fetchone()
    if not row:
        raise ValueError("Connection not found or inactive")
    access_token, refresh_token, expires_at = row[0], row[1], row[2]
    now = datetime.now(timezone.utc)
    if expires_at and (expires_at.tzinfo is None or expires_at.tzinfo.utcoffset(expires_at) is None):
        # Naive datetime — treat as UTC
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and (expires_at - now).total_seconds() > BUFFER_SECONDS:
        return access_token
    # Refresh
    new_access, new_expires = refresh_access_token(refresh_token)
    with get_conn() as conn:
        conn.execute(
            """UPDATE review_connections
               SET access_token = %s, token_expires_at = %s, updated_at = NOW()
               WHERE id = %s""",
            (new_access, new_expires, connection_id),
        )
        conn.commit()
    return new_access
