from fastapi.testclient import TestClient

from backend.api.main import app


def test_status_endpoint():
    client = TestClient(app)

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_generate_validates_empty_query():
    client = TestClient(app)

    response = client.post("/generate", json={"query": ""})

    assert response.status_code == 422
