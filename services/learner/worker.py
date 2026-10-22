import os

import httpx
from celery import Celery

redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
learner_url = os.environ.get("LEARNER_SERVICE_URL", "http://learner:8004")

app = Celery("learner", broker=redis_url, backend=redis_url)
app.conf.task_routes = {
    "trigger_learning": {"queue": "learning"},
}


# The webhook service enqueues this by name on PR merge; the learner worker consumes the "learning" queue.
@app.task(name="trigger_learning", autoretry_for=(httpx.HTTPError,), retry_backoff=True, max_retries=3)
def trigger_learning(repo_full_name: str, pr_id: str):
    with httpx.Client() as client:
        response = client.post(
            f"{learner_url}/learn",
            json={"repo_full_name": repo_full_name, "pr_id": pr_id},
            timeout=120,
        )
        response.raise_for_status()
