from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")

    assert response.status_code == 200

    body = response.json()
    assert body["app"] == "RootPatch"
    assert body["status"] == "healthy"
