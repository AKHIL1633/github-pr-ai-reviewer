import os

import httpx
from celery import Celery

redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
orchestrator_url = os.environ.get("ORCHESTRATOR_SERVICE_URL", "http://orchestrator:8002")

app = Celery("webhook", broker=redis_url, backend=redis_url)
app.conf.task_routes = {
    "analyze_pr": {"queue": "webhook"},
    "trigger_learning": {"queue": "learning"},
}
# Only ack a job once it has finished, so a worker crash mid-review re-queues it.
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1


@app.task(name="analyze_pr", autoretry_for=(httpx.HTTPError,), retry_backoff=True, max_retries=3)
def analyze_pr(pr_id: str, pr_number: int, repo_full_name: str, head_sha: str, installation_id: int):
    with httpx.Client() as client:
        response = client.post(
            f"{orchestrator_url}/analyze",
            json={
                "pr_id": pr_id,
                "pr_number": pr_number,
                "repo_full_name": repo_full_name,
                "head_sha": head_sha,
                "installation_id": installation_id,
            },
            timeout=300,
        )
        response.raise_for_status()


def trigger_learning(repo_full_name: str, pr_id: str):
    # Executed by the learner worker (services/learner/worker.py); here we only enqueue it.
    app.send_task("trigger_learning", args=[repo_full_name, pr_id], queue="learning")
