from openai import OpenAI
from .settings import settings

client = OpenAI(api_key=settings.OPENAI_API_KEY)

def embed_text(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        return [0.0] * 1536
    r = client.embeddings.create(model=settings.EMBED_MODEL, input=text)
    return r.data[0].embedding

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