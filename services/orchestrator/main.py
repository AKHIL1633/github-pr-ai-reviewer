import logging
import os
import time

import httpx
import jwt
from fastapi import FastAPI
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from models import Settings, Finding, Pattern, PullRequest, AnalyzeRequest
from graph import build_graph
from llm import embed

logger = logging.getLogger(__name__)

settings = Settings()
engine = create_async_engine(settings.database_url)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

REVIEWER_URL = os.environ.get("REVIEWER_SERVICE_URL", "http://reviewer:8003")
PATTERN_CANDIDATES = 20
PATTERNS_IN_PROMPT = 10

REVIEW_DURATION = Histogram("pr_review_duration_seconds", "End-to-end time to analyze one PR", buckets=(5, 10, 20, 30, 60, 120, 300))
FINDINGS_TOTAL = Counter("pr_review_findings_total", "Findings produced", ["agent", "severity"])



graph = build_graph()

app = FastAPI()
Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/analyze", status_code=202)
async def analyze(request: AnalyzeRequest):
    started = time.perf_counter()
    try:
        token = await get_installation_token(request.installation_id)
        diff = await fetch_diff(request.repo_full_name, request.pr_number, token)

        async with AsyncSessionLocal() as session:
            patterns = await load_patterns(session, request.repo_full_name, diff)

        state = await graph.ainvoke({"diff": diff, "patterns": patterns, "findings": []})
        findings_data = state.get("review", [])

        async with AsyncSessionLocal() as session:
            for f in findings_data:
                session.add(Finding(
                    pr_id=request.pr_id,
                    file=f.get("file"),
                    line=f.get("line"),
                    severity=f.get("severity"),
                    message=f.get("message"),
                    agent=f.get("agent"),
                ))
                FINDINGS_TOTAL.labels(f.get("agent", "unknown"), f.get("severity", "info")).inc()
            await session.commit()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{REVIEWER_URL}/post-review",
                json={
                    "pr_id": str(request.pr_id),
                    "repo_full_name": request.repo_full_name,
                    "pr_number": request.pr_number,
                    "installation_id": request.installation_id,
                    "findings": findings_data,
                },
                timeout=60,
            )
            response.raise_for_status()
    except Exception:
        await set_status(request.pr_id, "failed")
        raise
    finally:
        REVIEW_DURATION.observe(time.perf_counter() - started)

    return {"status": "accepted", "findings": len(findings_data)}


async def load_patterns(session: AsyncSession, repo_full_name: str, diff: str) -> list[str]:
    """Past issues for this repo, ranked by semantic similarity to the current diff.

    Takes the nearest candidates by embedding distance, then keeps the most frequent ones,
    so the prompt gets issues that are both relevant to this change and recurring.
    Falls back to pure frequency ranking if embeddings are unavailable.
    """
    base = select(Pattern).where(Pattern.repo_full_name == repo_full_name)
    try:
        [diff_embedding] = await embed([diff[:8000]])
        result = await session.execute(
            base.where(Pattern.embedding.is_not(None))
            .order_by(Pattern.embedding.cosine_distance(diff_embedding))
            .limit(PATTERN_CANDIDATES)
        )
        candidates = result.scalars().all()
    except Exception:
        logger.warning("Semantic pattern lookup failed; using frequency ranking", exc_info=True)
        await session.rollback()
        candidates = []

    if not candidates:
        result = await session.execute(base.order_by(Pattern.frequency.desc()).limit(PATTERNS_IN_PROMPT))
        candidates = result.scalars().all()

    candidates = sorted(candidates, key=lambda p: p.frequency or 0, reverse=True)
    return [p.pattern_text for p in candidates[:PATTERNS_IN_PROMPT]]


async def set_status(pr_id, status: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(update(PullRequest).where(PullRequest.id == pr_id).values(status=status))
            await session.commit()
    except Exception:
        logger.exception("Could not update PR status")


async def get_installation_token(installation_id: int) -> str:
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": settings.github_app_id}
    private_key = settings.github_app_private_key.replace("\\n", "\n")
    encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {encoded_jwt}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        response.raise_for_status()
        return response.json()["token"]


async def fetch_diff(repo_full_name: str, pr_number: int, token: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3.diff",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.text
