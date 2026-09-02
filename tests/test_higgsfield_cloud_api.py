from fastapi.testclient import TestClient

import higgsfield_cloud_api as module


class _Controller:
    request_id = "request-123"


class Completed:
    pass


class _FakeClient:
    submitted_application = None
    submitted_arguments = None

    @classmethod
    async def submit_async(cls, application, arguments):
        cls.submitted_application = application
        cls.submitted_arguments = arguments
        return _Controller()

    @staticmethod
    async def status_async(request_id):
        assert request_id == "request-123"
        return Completed()

    @staticmethod
    async def result_async(request_id):
        assert request_id == "request-123"
        return {"video": {"url": "https://media.example/video.mp4"}}

    @staticmethod
    async def cancel_async(request_id):
        assert request_id == "request-123"


def _client(monkeypatch):
    module.app.dependency_overrides[module.verify_owner] = lambda: True
    monkeypatch.setenv("HF_API_KEY", "test-key")
    monkeypatch.setenv("HF_API_SECRET", "test-secret")
    monkeypatch.setattr(module, "_client_module", lambda: _FakeClient)
    return TestClient(module.app)


def test_health_is_owner_only_and_does_not_expose_credentials(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/higgsfield-cloud/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["credentials_configured"] is True
    assert body["credentials_exposed"] is False
    assert "test-key" not in response.text
    assert "test-secret" not in response.text
    module.app.dependency_overrides.clear()


def test_generation_requires_explicit_confirmation(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/higgsfield-cloud/cinematic/generations",
        json={"scene": "entrance", "confirm": "NO"},
    )
    assert response.status_code == 422
    module.app.dependency_overrides.clear()


def test_generation_submits_controlled_seedance_scene(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/higgsfield-cloud/cinematic/generations",
        json={"scene": "execution", "confirm": "GENERATE", "duration": 5, "resolution": "720p"},
    )
    assert response.status_code == 200
    assert response.json()["request_id"] == "request-123"
    assert _FakeClient.submitted_application == "seedance_2_5"
    assert _FakeClient.submitted_arguments["aspect_ratio"] == "16:9"
    assert _FakeClient.submitted_arguments["generate_audio"] is False
    module.app.dependency_overrides.clear()


def test_completed_generation_returns_result(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/higgsfield-cloud/cinematic/generations/request-123")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result"]["video"]["url"].endswith(".mp4")
    module.app.dependency_overrides.clear()
