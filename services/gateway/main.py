import hashlib
import hmac
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from prometheus_fastapi_instrumentator import Instrumentator

from models import Settings

settings = Settings()
WEBHOOK_URL = os.environ.get("WEBHOOK_SERVICE_URL", "http://webhook:8001")
FORWARDED_HEADERS = ("X-GitHub-Event", "X-GitHub-Delivery")

app = FastAPI()
Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook/github")
async def github_webhook(request: Request):
    body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256", "")

    expected = (
        "sha256="
        + hmac.new(
            settings.github_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{WEBHOOK_URL}/events",
            content=body,
            headers={
                "Content-Type": "application/json",
                **{h: request.headers[h] for h in FORWARDED_HEADERS if h in request.headers},
            },
        )
        response.raise_for_status()

    return {"status": "ok"}
