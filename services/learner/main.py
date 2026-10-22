import logging
import os

from fastapi import FastAPI
from openai import AsyncOpenAI
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from models import Settings, Finding, Pattern, LearnRequest

logger = logging.getLogger(__name__)

settings = Settings()
engine = create_async_engine(settings.database_url)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
# Cosine distance under which two findings count as the same recurring issue,
# e.g. "SQL query built with f-string" vs "Possible SQL injection via string formatting".
SIMILARITY_THRESHOLD = float(os.environ.get("PATTERN_SIMILARITY_THRESHOLD", "0.2"))



app = FastAPI()
Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health():
    return {"status": "ok"}


async def embed(texts: list[str]) -> list[list[float]] | None:
    try:
        response = await AsyncOpenAI().embeddings.create(model=EMBEDDING_MODEL, input=texts)
        return [item.embedding for item in response.data]
    except Exception:
        logger.warning("Embedding failed; falling back to exact-match patterns", exc_info=True)
        return None


@app.post("/learn")
async def learn(request: LearnRequest):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Finding)
            .where(
                Finding.pr_id == request.pr_id,
                Finding.severity.in_(["warning", "error"]),
            )
        )
        messages = [f.message for f in result.scalars().all() if f.message]
        if not messages:
            return {"status": "ok", "learned": 0, "merged": 0}

        embeddings = await embed(messages)
        merged = 0
        for i, message in enumerate(messages):
            embedding = embeddings[i] if embeddings else None
            if embedding is not None and await _bump_similar(session, request.repo_full_name, embedding):
                merged += 1
                continue

            stmt = (
                insert(Pattern)
                .values(
                    repo_full_name=request.repo_full_name,
                    pattern_text=message,
                    frequency=1,
                    embedding=embedding,
                )
                .on_conflict_do_update(
                    index_elements=["repo_full_name", "pattern_text"],
                    set_={"frequency": Pattern.frequency + 1, "updated_at": func.now()},
                )
            )
            await session.execute(stmt)
            # Flush so later findings from this same PR can match against it.
            await session.flush()

        await session.commit()

    return {"status": "ok", "learned": len(messages) - merged, "merged": merged}


async def _bump_similar(session: AsyncSession, repo_full_name: str, embedding: list[float]) -> bool:
    """Increment the closest existing pattern if it is semantically the same issue."""
    distance = Pattern.embedding.cosine_distance(embedding)
    result = await session.execute(
        select(Pattern.id, distance.label("distance"))
        .where(Pattern.repo_full_name == repo_full_name, Pattern.embedding.is_not(None))
        .order_by(distance)
        .limit(1)
    )
    nearest = result.first()
    if nearest is None or nearest.distance > SIMILARITY_THRESHOLD:
        return False
    await session.execute(
        update(Pattern)
        .where(Pattern.id == nearest.id)
        .values(frequency=Pattern.frequency + 1, updated_at=func.now())
    )
    return True
