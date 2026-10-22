import os
from functools import lru_cache

try:
    # LangFuse's drop-in wrapper traces every call (prompt, tokens, latency, cost).
    from langfuse.openai import AsyncOpenAI
except ImportError:  # tracing is optional, e.g. when running the local CLI
    from openai import AsyncOpenAI

CHAT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = 1536


@lru_cache(maxsize=1)
def get_client() -> AsyncOpenAI:
    # Created lazily so importing this module never requires an API key (tests, tooling).
    return AsyncOpenAI()


async def embed(texts: list[str]) -> list[list[float]]:
    response = await get_client().embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]
