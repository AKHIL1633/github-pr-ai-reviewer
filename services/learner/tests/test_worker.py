from fastapi.testclient import TestClient

import main
import worker


def test_learner_worker_registers_trigger_learning_on_learning_queue():
    # Regression: the task used to live only in the webhook worker, which never consumes "learning".
    assert "trigger_learning" in worker.app.tasks
    assert worker.app.conf.task_routes["trigger_learning"] == {"queue": "learning"}


def test_health():
    assert TestClient(main.app).get("/health").json() == {"status": "ok"}
