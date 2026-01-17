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


def chat_once(system: str, user: str, temperature: float = 0.6, model: str = None, max_tokens: int = None, timeout: float = None) -> str:
    """
    Single chat completion with optional timeout and model override.
    
    Args:
        system: System message
        user: User message
        temperature: Sampling temperature
        model: Model override (defaults to settings.CHAT_MODEL)
        max_tokens: Maximum tokens to generate
        timeout: Request timeout in seconds
    
    Returns:
        Response text
    """
    model = model or settings.CHAT_MODEL
    
    # Create request params
    params = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system or ""},
            {"role": "user", "content": user or ""},
        ],
    }
    if max_tokens:
        params["max_tokens"] = max_tokens
    
    # Handle timeout if specified
    if timeout is not None:
        # Enforce timeouts even if the SDK doesn't abort promptly
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

        def _call():
            return client.with_options(timeout=timeout).chat.completions.create(**params)

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call)
                r = future.result(timeout=timeout)
        except FutureTimeoutError:
            raise TimeoutError(f"LLM request timed out after {timeout}s")
        except Exception as e:
            if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                raise TimeoutError(f"LLM request timed out after {timeout}s")
            raise
    else:
        r = client.chat.completions.create(**params)
    
    return (r.choices[0].message.content or "").strip()
