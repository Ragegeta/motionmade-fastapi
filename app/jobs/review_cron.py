"""
ReviewMate: Daily job to pull new reviews and generate draft responses for all active connections.
Runs at 7:00 AM AEST (Australia/Brisbane). Errors for one business do not block others.
"""
import logging
from datetime import datetime, timezone

from ..db import get_conn
from ..services.token_manager import get_valid_access_token
from ..services.google_reviews import fetch_all_reviews
from ..services.review_responder import generate_draft_response

logger = logging.getLogger(__name__)


def _parse_ts(s):
    if not s:
        return None
    try:
        from datetime import datetime as _dt
        s = str(s).replace("Z", "+00:00")
        return _dt.fromisoformat(s)
    except Exception:
        return None


def run_daily_review_job():
    """
    For each active review_connection: refresh token if needed, pull reviews from Google,
    upsert into reviews table, then generate draft responses for any new unresponded reviews.
    Logs results and errors; one connection's failure does not stop others.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, google_account_id, google_location_id, google_location_name
               FROM review_connections WHERE is_active = TRUE"""
        ).fetchall()
    if not rows:
        logger.info("Review cron: no active connections")
        return
    for row in rows:
        connection_id = str(row[0])
        account_id, location_id, location_name = row[1], row[2], (row[3] or "")
        try:
            access_token = get_valid_access_token(connection_id)
        except Exception as e:
            logger.warning("Review cron: token refresh failed for %s: %s", connection_id, e)
            continue
        try:
            reviews = fetch_all_reviews(access_token, account_id, location_id)
        except Exception as e:
            logger.warning("Review cron: fetch reviews failed for %s: %s", connection_id, e)
            continue
        new_count = 0
        with get_conn() as conn:
            existing = set(
                r[0] for r in conn.execute(
                    "SELECT google_review_id FROM reviews WHERE connection_id = %s",
                    (connection_id,),
                ).fetchall()
            )
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
        logger.info("Review cron: %s pulled %d reviews (%d new)", connection_id, len(reviews), new_count)
        # Generate drafts for unresponded reviews that don't have a non-rejected draft
        with get_conn() as conn:
            settings_row = conn.execute(
                """SELECT business_type, tone, owner_name, custom_instructions
                   FROM review_settings WHERE connection_id = %s""",
                (connection_id,),
            ).fetchone()
        settings = {
            "business_type": (settings_row[0] if settings_row else None) or "",
            "tone": (settings_row[1] if settings_row else None) or "professional",
            "owner_name": (settings_row[2] if settings_row else None) or "",
            "custom_instructions": (settings_row[3] if settings_row else None) or "",
        }
        with get_conn() as conn:
            to_draft = conn.execute(
                """SELECT r.id, r.google_review_id, r.reviewer_name, r.star_rating, r.review_text
                   FROM reviews r
                   WHERE r.connection_id = %s AND r.has_existing_reply = FALSE
                   AND NOT EXISTS (
                     SELECT 1 FROM review_drafts d
                     WHERE d.review_id = r.id AND d.status != 'rejected'
                   )""",
                (connection_id,),
            ).fetchall()
        drafts_created = 0
        for rev_row in to_draft:
            review_id = str(rev_row[0])
            reviewer_name = rev_row[2] or ""
            star_rating = int(rev_row[3]) if rev_row[3] else 1
            review_text = rev_row[4] or ""
            try:
                draft_text = generate_draft_response(
                    connection_name=location_name,
                    settings=settings,
                    reviewer_name=reviewer_name,
                    star_rating=star_rating,
                    review_text=review_text,
                )
            except Exception as e:
                logger.warning("Review cron: draft gen failed for review %s: %s", review_id, e)
                continue
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO review_drafts (review_id, connection_id, draft_text, status)
                       VALUES (%s, %s, %s, 'pending')""",
                    (review_id, connection_id, (draft_text or "").strip() or "Thank you for your feedback."),
                )
                conn.commit()
            drafts_created += 1
        logger.info("Review cron: %s created %d draft(s)", connection_id, drafts_created)


def get_scheduler():
    """Create and return an APScheduler AsyncIOScheduler with the daily review job at 7:00 AM AEST."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        return None
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_daily_review_job,
        "cron",
        hour=7,
        minute=0,
        timezone="Australia/Brisbane",
        id="review_daily",
    )
    return scheduler
