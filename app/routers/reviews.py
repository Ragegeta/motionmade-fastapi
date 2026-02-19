"""
ReviewMate: Google Review Auto-Responder. All routes under /api/reviews/.
Uses owner JWT for auth (same as dashboard). Callback is unauthenticated.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..db import get_conn
from ..review_models import (
    ConnectionStatus,
    DraftEditBody,
    DraftItem,
    GoogleLocation,
    PullResult,
    ReviewItem,
    ReviewSettingsResponse,
    ReviewSettingsUpdate,
)
from ..services.google_auth import (
    get_authorization_url,
    generate_state,
    exchange_code_for_tokens,
    fetch_locations,
    _review_config_ok,
)
from ..services.token_manager import get_valid_access_token
from ..services.google_reviews import fetch_all_reviews
from ..services.review_responder import generate_draft_response
from ..services.google_reviews import post_reply
from ..settings import settings

# Owner JWT dependency (duplicated here to avoid circular import with main)
try:
    from jose import jwt, JWTError
except ImportError:
    jwt = None
    JWTError = Exception

OWNER_TOKEN_ALG = "HS256"

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class SelectLocationBody(BaseModel):
    account_id: str
    location_id: str
    name: str = ""


def _decode_owner_token(token: str) -> Optional[dict]:
    if not jwt or not getattr(settings, "JWT_SECRET", None):
        return None
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[OWNER_TOKEN_ALG])
    except JWTError:
        return None


def get_current_owner(authorization: str = Header(default="")):
    """Dependency: require valid owner JWT. Returns dict with owner_id, tenant_id."""
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization")
    token = authorization.strip().split(None, 1)[-1]
    payload = _decode_owner_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"owner_id": int(payload["sub"]), "tenant_id": payload["tenant_id"]}


# ----- Auth (OAuth) -----

@router.get("/auth/google")
def reviews_auth_google(
    owner: dict = Depends(get_current_owner),
):
    """Start Google OAuth. Redirects to Google consent; callback will store tokens. Frontend must send Authorization: Bearer <owner_token> (e.g. via fetch then window.location = response.url)."""
    if not _review_config_ok():
        raise HTTPException(
            status_code=503,
            detail="ReviewMate Google OAuth not configured (REVIEW_GOOGLE_* env vars)",
        )
    tenant_id = owner["tenant_id"]
    state = generate_state()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO review_oauth_states (state, tenant_id) VALUES (%s, %s)",
            (state, tenant_id),
        )
        conn.commit()
    url = get_authorization_url(state)
    return RedirectResponse(url=url, status_code=302)


@router.get("/auth/google/url")
def reviews_auth_google_url(
    owner: dict = Depends(get_current_owner),
):
    """Return the Google OAuth URL so the frontend can redirect with auth. Use this from /reviews when user clicks Connect."""
    if not _review_config_ok():
        raise HTTPException(
            status_code=503,
            detail="ReviewMate Google OAuth not configured (REVIEW_GOOGLE_* env vars)",
        )
    tenant_id = owner["tenant_id"]
    state = generate_state()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO review_oauth_states (state, tenant_id) VALUES (%s, %s)",
            (state, tenant_id),
        )
        conn.commit()
    url = get_authorization_url(state)
    return {"url": url}


@router.get("/auth/google/callback")
def reviews_auth_google_callback(
    state: str,
    code: Optional[str] = None,
    error: Optional[str] = None,
):
    """OAuth callback from Google. Exchanges code for tokens, fetches locations, stores connection or pending pick."""
    if error:
        # User denied or error - redirect to reviews page with error
        return RedirectResponse(url=f"/reviews?error={error}", status_code=302)
    if not code or not state:
        return RedirectResponse(url="/reviews?error=missing_code_or_state", status_code=302)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT tenant_id FROM review_oauth_states WHERE state = %s",
            (state,),
        ).fetchone()
    if not row:
        return RedirectResponse(url="/reviews?error=invalid_state", status_code=302)
    tenant_id = row[0]
    # Delete state so it can't be reused
    with get_conn() as conn:
        conn.execute("DELETE FROM review_oauth_states WHERE state = %s", (state,))
        conn.commit()
    try:
        access_token, refresh_token, token_expires_at = exchange_code_for_tokens(code)
    except Exception as e:
        return RedirectResponse(url=f"/reviews?error=token_exchange_failed", status_code=302)
    locations = fetch_locations(access_token)
    if not locations:
        return RedirectResponse(url="/reviews?error=no_locations", status_code=302)
    if len(locations) == 1:
        # Single location: save connection and redirect to dashboard
        loc = locations[0]
        with get_conn() as conn:
            conn.execute(
                "UPDATE review_connections SET is_active = FALSE WHERE tenant_id = %s",
                (tenant_id,),
            )
            conn.execute(
                """INSERT INTO review_connections
                   (tenant_id, google_account_id, google_location_id, google_location_name,
                    access_token, refresh_token, token_expires_at, is_active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)""",
                (
                    tenant_id,
                    loc["account_id"],
                    loc["location_id"],
                    loc.get("name") or loc["location_id"],
                    access_token,
                    refresh_token,
                    token_expires_at,
                ),
            )
            conn.commit()
            cur = conn.execute(
                "SELECT id FROM review_connections WHERE tenant_id = %s AND is_active = TRUE",
                (tenant_id,),
            )
            row = cur.fetchone()
            if row:
                conn.execute(
                    """INSERT INTO review_settings (connection_id, tone)
                       VALUES (%s, 'professional')
                       ON CONFLICT (connection_id) DO NOTHING""",
                    (str(row[0]),),
                )
                conn.commit()
        return RedirectResponse(url="/reviews?connected=1", status_code=302)
    # Multiple locations: store pending and redirect to picker
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO review_oauth_pending
               (state, tenant_id, access_token, refresh_token, token_expires_at, locations_json)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (state) DO UPDATE SET
                 access_token = EXCLUDED.access_token,
                 refresh_token = EXCLUDED.refresh_token,
                 token_expires_at = EXCLUDED.token_expires_at,
                 locations_json = EXCLUDED.locations_json""",
            (
                state,
                tenant_id,
                access_token,
                refresh_token,
                token_expires_at,
                json.dumps(locations),
            ),
        )
        conn.commit()
    return RedirectResponse(url=f"/reviews?state={state}&pick_location=1", status_code=302)


@router.get("/locations")
def reviews_list_locations(
    state: Optional[str] = None,
    owner: dict = Depends(get_current_owner),
):
    """List locations for the current tenant. If state is provided (after OAuth with multiple locations), return pending locations."""
    tenant_id = owner["tenant_id"]
    if state:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT locations_json FROM review_oauth_pending WHERE state = %s AND tenant_id = %s",
                (state, tenant_id),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Pending OAuth not found or expired")
        locations = json.loads(row[0])
        return {"locations": [GoogleLocation(**loc) for loc in locations], "pending_state": state}
    # Already connected: return the single connected location
    with get_conn() as conn:
        row = conn.execute(
            """SELECT google_account_id, google_location_id, google_location_name
               FROM review_connections WHERE tenant_id = %s AND is_active = TRUE""",
            (tenant_id,),
        ).fetchone()
    if not row:
        return {"locations": [], "pending_state": None}
    return {
        "locations": [
            GoogleLocation(account_id=row[0], location_id=row[1], name=row[2] or row[1])
        ],
        "pending_state": None,
    }


@router.post("/locations/select")
def reviews_select_location(
    body: SelectLocationBody,
    state: Optional[str] = Query(None),
    owner: dict = Depends(get_current_owner),
):
    """After OAuth with multiple locations, user selects one. Pass state from the picker URL."""
    tenant_id = owner["tenant_id"]
    if not state:
        raise HTTPException(status_code=400, detail="state query param required when selecting from multiple locations")
    with get_conn() as conn:
        row = conn.execute(
            """SELECT access_token, refresh_token, token_expires_at
               FROM review_oauth_pending WHERE state = %s AND tenant_id = %s""",
            (state, tenant_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Pending OAuth not found or expired")
    access_token, refresh_token, token_expires_at = row[0], row[1], row[2]
    with get_conn() as conn:
        conn.execute(
            "UPDATE review_connections SET is_active = FALSE WHERE tenant_id = %s",
            (tenant_id,),
        )
        conn.execute(
            """INSERT INTO review_connections
               (tenant_id, google_account_id, google_location_id, google_location_name,
                access_token, refresh_token, token_expires_at, is_active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)""",
            (
                tenant_id,
                body.account_id,
                body.location_id,
                body.name or body.location_id,
                access_token,
                refresh_token,
                token_expires_at,
            ),
        )
        conn.commit()
        cur = conn.execute(
            "SELECT id FROM review_connections WHERE tenant_id = %s AND is_active = TRUE",
            (tenant_id,),
        )
        conn_id_row = cur.fetchone()
    if conn_id_row:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO review_settings (connection_id, tone)
                   VALUES (%s, 'professional')
                   ON CONFLICT (connection_id) DO NOTHING""",
                (str(conn_id_row[0]),),
            )
            conn.commit()
    with get_conn() as conn:
        conn.execute("DELETE FROM review_oauth_pending WHERE state = %s", (state,))
        conn.commit()
    return {"ok": True, "message": "Location selected", "redirect": "/reviews"}


@router.post("/pull")
def reviews_pull(owner: dict = Depends(get_current_owner)):
    """Pull reviews from Google for the connected location. Refreshes token if needed. Returns summary."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            """SELECT id, google_account_id, google_location_id
               FROM review_connections WHERE tenant_id = %s AND is_active = TRUE""",
            (tenant_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active connection")
    connection_id, account_id, location_id = str(row[0]), row[1], row[2]
    try:
        access_token = get_valid_access_token(connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        reviews = fetch_all_reviews(access_token, account_id, location_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google API error: {e}")
    with get_conn() as conn:
        existing = set(
            r[0] for r in conn.execute(
                "SELECT google_review_id FROM reviews WHERE connection_id = %s",
                (connection_id,),
            ).fetchall()
        )
    def _parse_ts(s):
        if not s:
            return None
        try:
            from datetime import datetime
            s = str(s).replace("Z", "+00:00")
            return datetime.fromisoformat(s)
        except Exception:
            return None

    new_count = 0
    for rev in reviews:
        is_new = rev["google_review_id"] not in existing
        if is_new:
            new_count += 1
        create_ts = _parse_ts(rev.get("review_created_at"))
        update_ts = _parse_ts(rev.get("review_updated_at"))
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO reviews
                   (connection_id, google_review_id, reviewer_name, star_rating, review_text,
                    review_created_at, review_updated_at, has_existing_reply, existing_reply_text, synced_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                   ON CONFLICT (connection_id, google_review_id) DO UPDATE SET
                     reviewer_name = EXCLUDED.reviewer_name,
                     star_rating = EXCLUDED.star_rating,
                     review_text = EXCLUDED.review_text,
                     review_created_at = EXCLUDED.review_created_at,
                     review_updated_at = EXCLUDED.review_updated_at,
                     has_existing_reply = EXCLUDED.has_existing_reply,
                     existing_reply_text = EXCLUDED.existing_reply_text,
                     synced_at = NOW()""",
                (
                    connection_id,
                    rev["google_review_id"],
                    rev.get("reviewer_name"),
                    rev["star_rating"],
                    rev.get("review_text"),
                    create_ts,
                    update_ts,
                    rev.get("has_existing_reply") or False,
                    rev.get("existing_reply_text"),
                ),
            )
            conn.commit()
    with get_conn() as conn:
        unresponded = conn.execute(
            """SELECT COUNT(*) FROM reviews
               WHERE connection_id = %s AND has_existing_reply = FALSE""",
            (connection_id,),
        ).fetchone()[0] or 0
    return PullResult(
        total_reviews=len(reviews),
        unresponded_count=unresponded,
        new_since_last_sync=new_count,
    )


@router.post("/generate")
def reviews_generate_drafts(owner: dict = Depends(get_current_owner)):
    """Generate draft responses for all unresponded reviews that don't already have a pending/approved/posted draft."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            """SELECT rc.id, rc.google_location_name, rs.business_type, rs.tone, rs.owner_name, rs.custom_instructions
               FROM review_connections rc
               LEFT JOIN review_settings rs ON rs.connection_id = rc.id
               WHERE rc.tenant_id = %s AND rc.is_active = TRUE""",
            (tenant_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active connection")
    connection_id, location_name = str(row[0]), (row[1] or "")
    settings = {
        "business_type": row[2],
        "tone": row[3] or "professional",
        "owner_name": row[4],
        "custom_instructions": row[5],
    }
    with get_conn() as conn:
        reviews_to_draft = conn.execute(
            """SELECT r.id, r.google_review_id, r.reviewer_name, r.star_rating, r.review_text
               FROM reviews r
               WHERE r.connection_id = %s AND r.has_existing_reply = FALSE
               AND NOT EXISTS (
                 SELECT 1 FROM review_drafts d
                 WHERE d.review_id = r.id AND d.status != 'rejected'
               )""",
            (connection_id,),
        ).fetchall()
    created = 0
    for rev_row in reviews_to_draft:
        review_id, _, reviewer_name, star_rating, review_text = str(rev_row[0]), rev_row[1], rev_row[2], rev_row[3], rev_row[4]
        try:
            draft_text = generate_draft_response(
                connection_name=location_name,
                settings=settings,
                reviewer_name=reviewer_name or "",
                star_rating=int(star_rating) if star_rating else 1,
                review_text=review_text or "",
            )
        except Exception as e:
            continue
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO review_drafts (review_id, connection_id, draft_text, status)
                   VALUES (%s, %s, %s, 'pending')""",
                (review_id, connection_id, (draft_text or "").strip() or "Thank you for your feedback."),
            )
            conn.commit()
        created += 1
    return {"ok": True, "drafts_created": created}


@router.get("/drafts")
def reviews_list_drafts(
    status: Optional[str] = None,
    owner: dict = Depends(get_current_owner),
):
    """List draft responses. Optional status filter: pending, approved, posted, rejected, failed."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                """SELECT d.id, d.review_id, d.draft_text, d.edited_text, d.status, d.created_at, d.error_message,
                          r.id, r.google_review_id, r.reviewer_name, r.star_rating, r.review_text, r.review_created_at, r.has_existing_reply, r.existing_reply_text, r.synced_at
                   FROM review_drafts d
                   JOIN reviews r ON r.id = d.review_id
                   JOIN review_connections rc ON rc.id = d.connection_id
                   WHERE rc.tenant_id = %s AND d.status = %s
                   ORDER BY d.created_at DESC""",
                (tenant_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT d.id, d.review_id, d.draft_text, d.edited_text, d.status, d.created_at, d.error_message,
                          r.id, r.google_review_id, r.reviewer_name, r.star_rating, r.review_text, r.review_created_at, r.has_existing_reply, r.existing_reply_text, r.synced_at
                   FROM review_drafts d
                   JOIN reviews r ON r.id = d.review_id
                   JOIN review_connections rc ON rc.id = d.connection_id
                   WHERE rc.tenant_id = %s
                   ORDER BY d.created_at DESC""",
                (tenant_id,),
            ).fetchall()
    out = []
    for row in rows:
        (d_id, d_review_id, d_text, d_edited, d_status, d_created, d_err,
         r_id, r_google_id, r_name, r_stars, r_text, r_created, r_has_reply, r_reply_text, r_synced) = row
        review_item = ReviewItem(
            id=str(r_id),
            google_review_id=r_google_id or "",
            reviewer_name=r_name,
            star_rating=int(r_stars) if r_stars else 0,
            review_text=r_text,
            review_created_at=r_created.isoformat() if hasattr(r_created, "isoformat") else str(r_created) if r_created else None,
            has_existing_reply=bool(r_has_reply),
            existing_reply_text=r_reply_text,
            synced_at=r_synced.isoformat() if hasattr(r_synced, "isoformat") else str(r_synced) if r_synced else None,
        )
        out.append(DraftItem(
            id=str(d_id),
            review_id=str(d_review_id),
            draft_text=d_text or "",
            edited_text=d_edited,
            status=d_status or "pending",
            review=review_item,
            created_at=d_created.isoformat() if hasattr(d_created, "isoformat") else str(d_created) if d_created else None,
            error_message=d_err,
        ))
    return {"drafts": out, "count": len(out)}


@router.get("/stats")
def reviews_stats(owner: dict = Depends(get_current_owner)):
    """Return draft counts by status for the tenant's connection."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM review_connections WHERE tenant_id = %s AND is_active = TRUE",
            (tenant_id,),
        ).fetchone()
    if not row:
        return {"pending": 0, "approved": 0, "posted": 0, "rejected": 0, "failed": 0}
    connection_id = str(row[0])
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM review_drafts WHERE connection_id = %s GROUP BY status",
            (connection_id,),
        ).fetchall()
    counts = {"pending": 0, "approved": 0, "posted": 0, "rejected": 0, "failed": 0}
    for status, cnt in rows:
        if status in counts:
            counts[status] = cnt
    return counts


@router.post("/drafts/{draft_id}/approve")
def reviews_draft_approve(
    draft_id: str,
    owner: dict = Depends(get_current_owner),
):
    """Approve draft and post it to Google. On success status=posted; on failure status=failed with error_message."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            """SELECT d.id, d.review_id, d.draft_text, d.edited_text, d.connection_id,
                      r.google_review_id, rc.google_account_id, rc.google_location_id
               FROM review_drafts d
               JOIN reviews r ON r.id = d.review_id
               JOIN review_connections rc ON rc.id = d.connection_id
               WHERE d.id = %s AND rc.tenant_id = %s AND d.status = 'pending'""",
            (draft_id, tenant_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found or not pending")
    _, _, draft_text, edited_text, connection_id, google_review_id, account_id, location_id = row
    connection_id = str(connection_id)
    text_to_post = (edited_text or draft_text or "").strip() or "Thank you for your feedback."
    try:
        access_token = get_valid_access_token(connection_id)
        post_reply(access_token, account_id, location_id, google_review_id, text_to_post)
    except Exception as e:
        err_msg = str(e)[:500]
        with get_conn() as conn:
            conn.execute(
                "UPDATE review_drafts SET status = 'failed', error_message = %s, updated_at = NOW() WHERE id = %s",
                (err_msg, draft_id),
            )
            conn.commit()
        raise HTTPException(status_code=502, detail=f"Failed to post reply: {err_msg}")
    with get_conn() as conn:
        conn.execute(
            "UPDATE review_drafts SET status = 'posted', posted_at = NOW(), error_message = NULL, updated_at = NOW() WHERE id = %s",
            (draft_id,),
        )
        conn.execute(
            "UPDATE reviews SET has_existing_reply = TRUE, existing_reply_text = %s WHERE id = (SELECT review_id FROM review_drafts WHERE id = %s)",
            (text_to_post, draft_id),
        )
        conn.commit()
    return {"ok": True, "status": "posted"}


@router.put("/drafts/{draft_id}/edit")
def reviews_draft_edit(
  draft_id: str,
  body: DraftEditBody,
  owner: dict = Depends(get_current_owner),
):
    """Update the draft's edited_text (keeps status pending)."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            "SELECT d.id FROM review_drafts d JOIN review_connections rc ON rc.id = d.connection_id WHERE d.id = %s AND rc.tenant_id = %s AND d.status = 'pending'",
            (draft_id, tenant_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found or not pending")
    with get_conn() as conn:
        conn.execute(
            "UPDATE review_drafts SET edited_text = %s, updated_at = NOW() WHERE id = %s",
            (body.edited_text.strip(), draft_id),
        )
        conn.commit()
    return {"ok": True}


@router.post("/drafts/{draft_id}/reject")
def reviews_draft_reject(
  draft_id: str,
  owner: dict = Depends(get_current_owner),
):
    """Mark draft as rejected."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            "SELECT d.id FROM review_drafts d JOIN review_connections rc ON rc.id = d.connection_id WHERE d.id = %s AND rc.tenant_id = %s",
            (draft_id, tenant_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    with get_conn() as conn:
        conn.execute(
            "UPDATE review_drafts SET status = 'rejected', updated_at = NOW() WHERE id = %s",
            (draft_id,),
        )
        conn.commit()
    return {"ok": True, "status": "rejected"}


@router.get("/connection")
def reviews_connection_status(owner: dict = Depends(get_current_owner)):
    """Return whether the tenant has an active Google Business Profile connection."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            """SELECT id, google_location_name FROM review_connections
               WHERE tenant_id = %s AND is_active = TRUE""",
            (tenant_id,),
        ).fetchone()
    if not row:
        return ConnectionStatus(connected=False, location_name=None, connection_id=None)
    return ConnectionStatus(
        connected=True,
        location_name=row[1] or "",
        connection_id=str(row[0]),
    )


@router.post("/disconnect")
def reviews_disconnect(owner: dict = Depends(get_current_owner)):
    """Deactivate the Google Business Profile connection (does not delete data)."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        conn.execute(
            "UPDATE review_connections SET is_active = FALSE, updated_at = NOW() WHERE tenant_id = %s",
            (tenant_id,),
        )
        conn.commit()
    return {"ok": True, "message": "Disconnected"}


@router.get("/settings")
def reviews_get_settings(owner: dict = Depends(get_current_owner)):
    """Get review response settings for the connected account."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            """SELECT rs.business_type, rs.tone, rs.owner_name, rs.custom_instructions
               FROM review_settings rs
               JOIN review_connections rc ON rc.id = rs.connection_id
               WHERE rc.tenant_id = %s AND rc.is_active = TRUE""",
            (tenant_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No connection or settings")
    return ReviewSettingsResponse(
        business_type=row[0],
        tone=row[1] or "professional",
        owner_name=row[2],
        custom_instructions=row[3],
    )


@router.put("/settings")
def reviews_update_settings(
    body: ReviewSettingsUpdate,
    owner: dict = Depends(get_current_owner),
):
    """Update review response settings."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            "SELECT rs.id FROM review_settings rs JOIN review_connections rc ON rc.id = rs.connection_id WHERE rc.tenant_id = %s AND rc.is_active = TRUE",
            (tenant_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No connection or settings")
        updates = ["updated_at = NOW()"]
        params = []
        if body.business_type is not None:
            updates.append("business_type = %s")
            params.append(body.business_type)
        if body.tone is not None:
            updates.append("tone = %s")
            params.append(body.tone)
        if body.owner_name is not None:
            updates.append("owner_name = %s")
            params.append(body.owner_name)
        if body.custom_instructions is not None:
            updates.append("custom_instructions = %s")
            params.append(body.custom_instructions)
        params.append(row[0])
        conn.execute(
            f"UPDATE review_settings SET {', '.join(updates)} WHERE id = %s",
            tuple(params),
        )
        conn.commit()
    return {"ok": True}
