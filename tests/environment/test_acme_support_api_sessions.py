"""Session isolation for the Acme support HTTP sidecar (#37)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = (
    REPO_ROOT
    / "environment"
    / "task-environments"
    / "application"
    / "chatbot-api-sidecar_acme-support-api"
    / "support-api"
    / "server.py"
)


def _load_server():
    spec = importlib.util.spec_from_file_location("acme_support_api_server", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_acme_support_api_scopes_conversation_by_session() -> None:
    server = _load_server()
    # Fresh module state between pytest invocations of this file.
    server._sessions.clear()
    client = server.app.test_client()

    first = client.post("/v1/messages", json={"message": "Where is order 4521?"})
    assert first.status_code == 200
    first_body = first.get_json()
    session_a = first_body["sessionId"]
    assert session_a
    assert "4521" in first_body["reply"]

    second = client.post(
        "/v1/messages",
        json={"sessionId": session_a, "message": "Thanks"},
    )
    assert second.status_code == 200
    assert second.get_json()["sessionId"] == session_a

    other = client.post("/v1/messages", json={"message": "I want a refund"})
    assert other.status_code == 200
    session_b = other.get_json()["sessionId"]
    assert session_b != session_a

    convo_a = client.get(f"/v1/conversation?sessionId={session_a}")
    assert convo_a.status_code == 200
    messages_a = convo_a.get_json()["messages"]
    assert any("4521" in m.get("content", "") for m in messages_a)
    assert not any("refund" in m.get("content", "").lower() for m in messages_a)

    convo_b = client.get(f"/v1/conversation?sessionId={session_b}")
    assert convo_b.status_code == 200
    messages_b = convo_b.get_json()["messages"]
    assert any("refund" in m.get("content", "").lower() for m in messages_b)
    assert not any("4521" in m.get("content", "") for m in messages_b)

    bare = client.get("/v1/conversation")
    assert bare.status_code == 400
