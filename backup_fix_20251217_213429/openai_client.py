from openai import OpenAI
from .settings import settings

client = OpenAI(api_key=settings.OPENAI_API_KEY)

def embed_text(text: str, model: str) -> list[float]:
    r = client.embeddings.create(model=model, input=text)
    return r.data[0].embedding

def chat_once(system: str, user: str, model: str, temperature: float = 0.6) -> str:
    r = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    )
    return (r.choices[0].message.content or '').strip()