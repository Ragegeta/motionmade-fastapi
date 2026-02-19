"""
Pydantic request/response schemas for ReviewMate (/api/reviews/) endpoints.
"""
from typing import Optional, List
from pydantic import BaseModel, Field


# ----- Auth / connection -----

class LocationSelectBody(BaseModel):
    """Body for POST /api/reviews/locations/{id}/select"""
    pass  # location id is in path


class GoogleLocation(BaseModel):
    """A Google Business Profile location (account + location id and name)."""
    account_id: str
    location_id: str
    name: str


class ConnectionStatus(BaseModel):
    """Current connection status for the tenant."""
    connected: bool
    location_name: Optional[str] = None
    connection_id: Optional[str] = None


# ----- Settings -----

class ReviewSettingsUpdate(BaseModel):
    """Update review response settings."""
    business_type: Optional[str] = None
    tone: Optional[str] = Field(None, pattern="^(professional|friendly|casual|formal)$")
    owner_name: Optional[str] = None
    custom_instructions: Optional[str] = None


class ReviewSettingsResponse(BaseModel):
    """Current review settings."""
    business_type: Optional[str] = None
    tone: str = "professional"
    owner_name: Optional[str] = None
    custom_instructions: Optional[str] = None


# ----- Reviews / drafts (for Phase 2–4) -----

class ReviewItem(BaseModel):
    """A single review from Google (cached)."""
    id: str
    google_review_id: str
    reviewer_name: Optional[str] = None
    star_rating: int
    review_text: Optional[str] = None
    review_created_at: Optional[str] = None
    has_existing_reply: bool = False
    existing_reply_text: Optional[str] = None
    synced_at: Optional[str] = None


class DraftItem(BaseModel):
    """A draft response awaiting approval."""
    id: str
    review_id: str
    draft_text: str
    edited_text: Optional[str] = None
    status: str  # pending | approved | posted | rejected | failed
    review: Optional[ReviewItem] = None
    created_at: Optional[str] = None
    error_message: Optional[str] = None


class DraftEditBody(BaseModel):
    """Body for PUT /api/reviews/drafts/{id}/edit"""
    edited_text: str = Field(..., min_length=1)


class PullResult(BaseModel):
    """Result of POST /api/reviews/pull"""
    total_reviews: int
    unresponded_count: int
    new_since_last_sync: int
