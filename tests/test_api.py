import time

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def wait_for_status(investigation_id: str, timeout_seconds: float = 5.0):
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        res = client.get(f"/api/investigations/{investigation_id}")
        assert res.status_code == 200
        body = res.json()
        last = body
        if body["status"] in {"completed", "failed"}:
            return body
        time.sleep(0.1)
    return last


def test_create_and_complete_investigation_crashloop():
    payload = {
        "incident_name": "Payment Service Failure",
        "namespace": "default",
        "target": "payment-service",
        "scenario": "crashloop-missing-env",
    }
    res = client.post("/api/investigations", json=payload)
    assert res.status_code == 200

    created = res.json()
    assert created["status"] == "pending"
    assert created["id"]

    final_state = wait_for_status(created["id"])
    assert final_state is not None
    assert final_state["status"] == "completed"
    assert final_state["report"] is not None
    assert "DATABASE_URL" in final_state["report"]["root_cause"]
    assert final_state["report"]["confidence"] >= 90


def test_list_investigations_includes_recent_runs():
    res = client.get("/api/investigations")
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, list)


def test_get_unknown_investigation_returns_404():
    res = client.get("/api/investigations/not-found-id")
    assert res.status_code == 404


def test_websocket_stream_reaches_terminal_event():
    payload = {
        "incident_name": "Image pull issue",
        "namespace": "default",
        "target": "payment-service",
        "scenario": "image-pull-backoff",
    }
    created = client.post("/api/investigations", json=payload).json()
    investigation_id = created["id"]

    terminal = None
    with client.websocket_connect(f"/api/investigations/{investigation_id}/stream") as ws:
        for _ in range(20):
            event = ws.receive_json()
            if event.get("status") in {"completed", "failed"}:
                terminal = event
                break

    assert terminal is not None
    assert terminal["status"] == "completed"
    assert terminal["report"] is not None
    assert "ImagePullBackOff" in terminal["report"]["root_cause"]
