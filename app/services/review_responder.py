"""
ReviewMate: Generate draft review responses using GPT-4o (or CHAT_MODEL).
Keeps responses under 150 words, Australian English, tone from settings.
"""
from ..openai_client import chat_once


def _system_prompt(connection_name: str, settings: dict) -> str:
    business_type = (settings.get("business_type") or "local business").strip()
    owner_name = (settings.get("owner_name") or "").strip()
    tone = (settings.get("tone") or "professional").strip()
    custom = (settings.get("custom_instructions") or "").strip()
    return f"""You are a review response writer for a local Australian service business.

Business type: {business_type}
Business name: {connection_name}
Owner name: {owner_name or 'Not specified'}
Tone: {tone}
Custom instructions: {custom or 'None'}

Rules:
- Keep responses under 150 words
- Be genuine, not corporate
- For 4-5 star reviews: thank them specifically for what they mentioned
- For 3 star reviews: thank them, acknowledge the feedback, mention commitment to improvement
- For 1-2 star reviews: apologise sincerely, don't be defensive, offer to make it right, invite them to contact directly
- Never use emojis unless the reviewer used them
- Never make up details about the service that weren't in the review
- Use Australian English spelling (e.g., "organised" not "organized")
- Sign off with the owner's first name if provided
- Sound like a real person, not a chatbot
"""


def _user_prompt(reviewer_name: str, star_rating: int, review_text: str) -> str:
    name = (reviewer_name or "A customer").strip()
    text = (review_text or "").strip() or "(No text)"
    return f"""Review from {name}:
Rating: {star_rating}/5 stars
Review text: "{text}"

Write a response."""


def generate_draft_response(
    connection_name: str,
    settings: dict,
    reviewer_name: str,
    star_rating: int,
    review_text: str,
    model: str = None,
    max_tokens: int = 200,
) -> str:
    """
    Generate a single draft response for a review.
    Returns the response text (plain, under 150 words).
    """
    system = _system_prompt(connection_name, settings)
    user = _user_prompt(reviewer_name, star_rating, review_text)
    return chat_once(
        system=system,
        user=user,
        temperature=0.6,
        model=model,
        max_tokens=max_tokens,
        timeout=30.0,
    )
