from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_ignores_non_pull_request_events():
    response = client.post("/events", json={"zen": "hi"}, headers={"X-GitHub-Event": "ping"})
    assert response.status_code == 202
    assert response.json() == {"status": "skipped"}


def test_ignores_irrelevant_pr_actions():
    response = client.post(
        "/events",
        json={"action": "labeled", "pull_request": {"number": 1}},
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert response.json() == {"status": "skipped"}


def test_merge_enqueues_learning_by_task_name(monkeypatch):
    import worker

    sent = []
    monkeypatch.setattr(worker.app, "send_task", lambda name, args, queue: sent.append((name, args, queue)))
    worker.trigger_learning("octo/repo", "1234")
    assert sent == [("trigger_learning", ["octo/repo", "1234"], "learning")]
