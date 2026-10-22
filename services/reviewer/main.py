import time

import httpx
import jwt
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from formatting import build_inline_comments, build_summary
from models import Settings, PullRequest, ReviewRequest

settings = Settings()
engine = create_async_engine(settings.database_url)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

app = FastAPI()
Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/post-review")
async def post_review(request: ReviewRequest):
    token = await get_installation_token(request.installation_id)

    inline_comments = build_inline_comments(request.findings)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/repos/{request.repo_full_name}/pulls/{request.pr_number}/reviews"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={"event": "COMMENT", "body": build_summary(request.findings), "comments": inline_comments},
            headers=headers,
            timeout=30,
        )
        if response.status_code == 422 and inline_comments:
            # GitHub rejected a comment position (e.g. the PR was force-pushed meanwhile);
            # fall back to a single review that lists everything in the body.
            response = await client.post(
                url,
                json={"event": "COMMENT", "body": build_summary(request.findings, include_all=True)},
                headers=headers,
                timeout=30,
            )
        response.raise_for_status()

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(PullRequest).where(PullRequest.id == request.pr_id).values(status="reviewed")
        )
        await session.commit()

    return {"status": "ok", "inline_comments": len(inline_comments)}


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
