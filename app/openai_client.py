from typing import List

from openai import OpenAI
from .settings import settings

client = OpenAI(api_key=settings.OPENAI_API_KEY)

_EMBED_DIMS = 1536


def embed_text(text: str) -> List[float]:
    text = (text or "").strip()
    if not text:
        return [0.0] * _EMBED_DIMS
    r = client.embeddings.create(model=settings.EMBED_MODEL, input=text)
    return r.data[0].embedding


def embed_texts(texts: List[str]) -> List[List[float]]:
    # Batch embeddings for speed (used by admin FAQ upload)
    clean = [(t or "").strip() for t in (texts or [])]
    if not clean:
        return []
    r = client.embeddings.create(model=settings.EMBED_MODEL, input=clean)
    return [d.embedding for d in r.data]


def chat_once(system: str, user: str, temperature: float = 0.6) -> str:
    r = client.chat.completions.create(
        model=settings.CHAT_MODEL,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system or ""},
            {"role": "user", "content": user or ""},
        ],
    )
    return (r.choices[0].message.content or "").strip()
