"""HTTP/SSE acceptance with an isolated database and deterministic AI provider."""
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.chat import Conversation, Message
from app.models.consultation import ConsultationPass, ConsultationRequest
from app.routers import consultations
from app.db import get_db
from app.deps import get_current_user


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for model in (Conversation, Message, ConsultationPass, ConsultationRequest): model.__table__.create(engine)
    sessions = sessionmaker(engine)
    with sessions() as db:
        db.add(Conversation(id=1, user_id=1, title="换工作"))
        db.add(ConsultationPass(id=1, user_id=1, order_id=1, conversation_id=1, status="ACTIVE", duration_hours=24, reply_limit=2, expires_at=datetime.utcnow() + timedelta(hours=24)))
        db.commit()
    def dependency():
        with sessions() as db: yield db
    monkeypatch.setattr(consultations.settings, "consultation_enabled", True)
    monkeypatch.setattr(consultations, "SessionLocal", sessions)
    monkeypatch.setattr(consultations, "build_messages", lambda *_: [{"role": "user", "content": "换工作"}])
    monkeypatch.setattr("app.chat.store.delete_conv", lambda *_: True)
    monkeypatch.setattr("app.chat.deepseek_client.call_deepseek_stream", lambda *_, **__: iter(["### 核心观察\n\n", "先核实 offer 条件。\n"]))
    app = FastAPI(); app.include_router(consultations.router)
    app.dependency_overrides[get_db] = dependency
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as http: yield http, sessions, app
    engine.dispose()


def test_sse_commits_once_and_replays(client):
    http, sessions, _ = client
    payload = {"pass_id": 1, "request_key": "request-1", "message": "怎样核实？"}
    response = http.post("/consultations/1/messages", json=payload)
    assert response.status_code == 200
    assert "[DONE]" in response.text
    assert "先核实" in response.text
    assert "[DONE]" in http.post("/consultations/1/messages", json=payload).text
    with sessions() as db:
        assert db.get(ConsultationPass, 1).replies_used == 1
        assert db.scalar(select(func.count()).select_from(Message)) == 2


def test_provider_failure_is_error_event_and_free(client, monkeypatch):
    http, sessions, _ = client
    def broken(*_, **__):
        yield "partial"
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr("app.chat.deepseek_client.call_deepseek_stream", broken)
    response = http.post("/consultations/1/messages", json={"pass_id": 1, "request_key": "request-1", "message": "问题"})
    assert '"error"' in response.text and "[DONE]" not in response.text
    with sessions() as db:
        assert db.get(ConsultationPass, 1).replies_used == 0
        assert db.scalar(select(func.count()).select_from(Message)) == 0
        assert db.scalar(select(ConsultationRequest)).status == "FAILED"


def test_feature_disabled_and_foreign_user_rejected(client, monkeypatch):
    http, _, app = client
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2)
    assert http.get("/consultations/1").status_code == 404
    monkeypatch.setattr(consultations.settings, "consultation_enabled", False)
    assert http.get("/consultations/1").status_code == 404
    assert http.get("/consultations/features").json() == {"enabled": False}
