import hashlib
import hmac
import json

import httpx
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
BODY = json.dumps({"action": "opened"}).encode()


def sign(body: bytes, secret: str = "test-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_rejects_missing_signature():
    assert client.post("/webhook/github", content=BODY).status_code == 401


def test_rejects_wrong_secret():
    response = client.post("/webhook/github", content=BODY, headers={"X-Hub-Signature-256": sign(BODY, "wrong")})
    assert response.status_code == 401


def test_rejects_tampered_body():
    response = client.post(
        "/webhook/github",
        content=BODY + b" ",
        headers={"X-Hub-Signature-256": sign(BODY)},
    )
    assert response.status_code == 401


def test_forwards_valid_event_with_github_headers(monkeypatch):
    forwarded = {}

    async def fake_post(self, url, content=None, headers=None, **kwargs):
        forwarded.update(url=url, content=content, headers=headers)
        return httpx.Response(202, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = client.post(
        "/webhook/github",
        content=BODY,
        headers={"X-Hub-Signature-256": sign(BODY), "X-GitHub-Event": "pull_request"},
    )
    assert response.status_code == 200
    assert forwarded["url"].endswith("/events")
    assert forwarded["content"] == BODY
    assert forwarded["headers"]["X-GitHub-Event"] == "pull_request"
