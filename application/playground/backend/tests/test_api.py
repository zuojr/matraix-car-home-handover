"""End-to-end tests for the FastAPI app (:mod:`backend.api.app`).

Covers health, preflight, and config options. No RecAI / OpenAI / numpy /
network is touched.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic")

from backend.service.config import PERSONA_MODEL_OPTIONS


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_preflight_shape(client):
    resp = client.get("/api/preflight")
    assert resp.status_code == 200
    body = resp.json()
    assert "ready" in body and isinstance(body["ready"], bool)
    assert isinstance(body["checks"], list) and body["checks"]
    names = {c["name"] for c in body["checks"]}
    assert "Model credentials" in names
    assert {
        "OpenAI credentials",
        "Anthropic credentials",
        "DashScope (Qwen / DeepSeek)",
        "OpenRouter",
        "Gemini credentials",
        "xAI credentials",
        "DeepSeek credentials",
        "Z.ai credentials",
        "OpenBB (finance)",
        "Meal planning",
        "Acme support API",
        "Acme MCP support",
        "Survey forms",
        "Web tasks",
        "Docker",
        "use.computer API",
        "Smart attribute match (local embed)",
        "MatrAIx Persona 1M",
    } <= names
    # Not part of the shipped application task set — keep out of readiness.
    assert "Recommendation engine" not in names
    assert "RecAI resources" not in names
    assert "RecAI chat API" not in names
    assert "Medical assistant" not in names
    for check in body["checks"]:
        assert set(check.keys()) >= {"name", "ok", "detail", "group"}


def test_preflight_required_vs_optional_contract(client):
    body = client.get("/api/preflight").json()
    by_name = {c["name"]: c for c in body["checks"]}
    required = {name for name, check in by_name.items() if not check.get("optional")}
    optional = {name for name, check in by_name.items() if check.get("optional")}
    assert required == {"Model credentials", "Survey forms", "Web tasks"}
    assert {
        "OpenAI credentials",
        "Anthropic credentials",
        "DashScope (Qwen / DeepSeek)",
        "OpenRouter",
        "Gemini credentials",
        "xAI credentials",
        "DeepSeek credentials",
        "Z.ai credentials",
        "OpenBB (finance)",
        "Meal planning",
        "Acme support API",
        "Acme MCP support",
        "Docker",
        "use.computer API",
        "Smart attribute match (local embed)",
        "MatrAIx Persona 1M",
    } <= optional
    assert body["ready"] == all(c["ok"] for c in body["checks"] if not c.get("optional"))


def test_preflight_does_not_leak_env_var_names(client):
    body = client.get("/api/preflight").json()
    leaked = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CLAUDE_API_KEY",
        "DASHSCOPE_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "XAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "ZAI_API_KEY",
        "USE_COMPUTER_API_KEY",
        "MATRIX_PERSONA_1M_DIR",
        "INTERECAGENT_ROOT",
        "INTERECAGENT_CATALOG_PATH",
    )
    for check in body["checks"]:
        for token in leaked:
            assert token not in check["name"]
            assert token not in check["detail"]


def test_preflight_model_credentials_any_provider(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    body = client.get("/api/preflight").json()
    model = next(c for c in body["checks"] if c["name"] == "Model credentials")
    assert model["ok"] is False
    assert model.get("optional") is not True
    assert body["ready"] is False

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    body = client.get("/api/preflight").json()
    model = next(c for c in body["checks"] if c["name"] == "Model credentials")
    assert model["ok"] is True
    assert "DashScope" in model["detail"]
    assert body["ready"] is True


def test_preflight_dashscope_check_optional(client, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    body = client.get("/api/preflight").json()
    dashscope = next(c for c in body["checks"] if c["name"] == "DashScope (Qwen / DeepSeek)")
    assert dashscope["ok"] is False
    assert dashscope.get("optional") is True

    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    body = client.get("/api/preflight").json()
    dashscope = next(c for c in body["checks"] if c["name"] == "DashScope (Qwen / DeepSeek)")
    assert dashscope["ok"] is True


def test_preflight_openrouter_check_optional(client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    body = client.get("/api/preflight").json()
    openrouter = next(c for c in body["checks"] if c["name"] == "OpenRouter")
    assert openrouter["ok"] is False
    assert openrouter.get("optional") is True

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    body = client.get("/api/preflight").json()
    openrouter = next(c for c in body["checks"] if c["name"] == "OpenRouter")
    assert openrouter["ok"] is True


def test_preflight_gemini_check_optional(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    body = client.get("/api/preflight").json()
    gemini = next(c for c in body["checks"] if c["name"] == "Gemini credentials")
    assert gemini["ok"] is False
    assert gemini.get("optional") is True

    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")
    body = client.get("/api/preflight").json()
    gemini = next(c for c in body["checks"] if c["name"] == "Gemini credentials")
    assert gemini["ok"] is True


def test_preflight_xai_check_optional(client, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    body = client.get("/api/preflight").json()
    xai = next(c for c in body["checks"] if c["name"] == "xAI credentials")
    assert xai["ok"] is False
    assert xai.get("optional") is True

    monkeypatch.setenv("XAI_API_KEY", "sk-test")
    body = client.get("/api/preflight").json()
    xai = next(c for c in body["checks"] if c["name"] == "xAI credentials")
    assert xai["ok"] is True


def test_preflight_deepseek_check_optional(client, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    body = client.get("/api/preflight").json()
    deepseek = next(c for c in body["checks"] if c["name"] == "DeepSeek credentials")
    assert deepseek["ok"] is False
    assert deepseek.get("optional") is True

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    body = client.get("/api/preflight").json()
    deepseek = next(c for c in body["checks"] if c["name"] == "DeepSeek credentials")
    assert deepseek["ok"] is True


def test_preflight_zai_check_optional(client, monkeypatch):
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    body = client.get("/api/preflight").json()
    zai = next(c for c in body["checks"] if c["name"] == "Z.ai credentials")
    assert zai["ok"] is False
    assert zai.get("optional") is True

    monkeypatch.setenv("ZAI_API_KEY", "sk-test")
    body = client.get("/api/preflight").json()
    zai = next(c for c in body["checks"] if c["name"] == "Z.ai credentials")
    assert zai["ok"] is True


def test_preflight_anthropic_check_optional(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    body = client.get("/api/preflight").json()
    anthropic = next(c for c in body["checks"] if c["name"] == "Anthropic credentials")
    assert anthropic["ok"] is False
    assert anthropic.get("optional") is True
    assert body["ready"] is True

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    body = client.get("/api/preflight").json()
    anthropic = next(c for c in body["checks"] if c["name"] == "Anthropic credentials")
    assert anthropic["ok"] is True


class _FakeOkResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getcode(self):
        return 200


def test_sidecar_reachable_true_on_2xx(monkeypatch):
    from backend.api import app as appmod

    seen: dict[str, str] = {}

    def _open(req, timeout=0):
        seen["url"] = getattr(req, "full_url", None) or str(req)
        return _FakeOkResponse()

    monkeypatch.setattr(appmod.urllib.request, "urlopen", _open)
    assert appmod._sidecar_reachable("http://sidecar.test:8902") is True
    assert seen["url"] == "http://sidecar.test:8902/ready"


def test_sidecar_reachable_false_when_unreachable(monkeypatch):
    from backend.api import app as appmod

    def _boom(req, timeout=0):
        raise OSError("connection refused")

    monkeypatch.setattr(appmod.urllib.request, "urlopen", _boom)
    assert appmod._sidecar_reachable("http://sidecar.test:8902") is False


def test_preflight_marks_down_sidecars_optional(client, monkeypatch):
    from backend.service import chatbot_sidecar_service as sidecar_mod

    monkeypatch.setattr(
        sidecar_mod,
        "sidecar_status",
        lambda application_id, repo_root=None: {
            "applicationId": application_id,
            "ok": False,
            "healthUrl": "http://127.0.0.1:9",
            "canStart": True,
            "detail": "down",
        },
    )
    body = client.get("/api/preflight").json()
    by_name = {c["name"]: c for c in body["checks"]}
    for name in ("OpenBB (finance)", "Meal planning", "Acme support API", "Acme MCP support"):
        assert by_name[name]["ok"] is False
        assert by_name[name]["optional"] is True
        assert "not ready" in by_name[name]["detail"]
    assert "Medical assistant" not in by_name
    assert body["ready"] == all(c["ok"] for c in body["checks"] if not c.get("optional"))


def test_preflight_reachable_sidecar_shows_ok(client, monkeypatch):
    from backend.service import chatbot_sidecar_service as sidecar_mod

    monkeypatch.setattr(
        sidecar_mod,
        "sidecar_status",
        lambda application_id, repo_root=None: {
            "applicationId": application_id,
            "ok": True,
            "healthUrl": "http://127.0.0.1:8905",
            "canStart": True,
            "detail": "ready",
        },
    )
    body = client.get("/api/preflight").json()
    meal = next(c for c in body["checks"] if c["name"] == "Meal planning")
    assert meal["ok"] is True
    assert "ready" in meal["detail"]


def test_preflight_os_app_checks_optional(client, monkeypatch):
    monkeypatch.delenv("USE_COMPUTER_API_KEY", raising=False)
    body = client.get("/api/preflight").json()
    by_name = {c["name"]: c for c in body["checks"]}
    for name in ("Docker", "use.computer API"):
        assert by_name[name]["optional"] is True
    assert by_name["use.computer API"]["group"] == "OS app"
    assert "survey" in by_name["Docker"]["detail"].lower() or "Linux" in by_name["Docker"]["detail"]


def test_preflight_smart_attribute_embed_optional(client, monkeypatch):
    """Missing local embed must not flip overall ready."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "backend.api.app._sentence_transformers_importable",
        lambda: False,
    )
    body = client.get("/api/preflight").json()
    embed = next(
        c for c in body["checks"] if c["name"] == "Smart attribute match (local embed)"
    )
    assert embed["optional"] is True
    assert embed["group"] == "Persona"
    assert embed["ok"] is False
    assert "sentence-transformers" in embed["detail"].lower()
    assert body["ready"] is True

    monkeypatch.setattr(
        "backend.api.app._sentence_transformers_importable",
        lambda: True,
    )
    monkeypatch.setattr(
        "backend.api.app._embed_model_weights_cached",
        lambda _model: False,
    )
    body = client.get("/api/preflight").json()
    embed = next(
        c for c in body["checks"] if c["name"] == "Smart attribute match (local embed)"
    )
    assert embed["ok"] is False
    assert "download" in embed["detail"].lower()
    assert body["ready"] is True

    monkeypatch.setattr(
        "backend.api.app._embed_model_weights_cached",
        lambda _model: True,
    )
    body = client.get("/api/preflight").json()
    embed = next(
        c for c in body["checks"] if c["name"] == "Smart attribute match (local embed)"
    )
    assert embed["ok"] is True
    assert body["ready"] is True


def test_preflight_persona_1m_optional(client, monkeypatch):
    """Missing 1M coreset must remind, not flip overall ready."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "backend.service.persona_1m_pool.production_1m_available",
        lambda repo_root=None: False,
    )
    body = client.get("/api/preflight").json()
    check = next(c for c in body["checks"] if c["name"] == "MatrAIx Persona 1M")
    assert check["optional"] is True
    assert check["group"] == "Persona"
    assert check["ok"] is False
    assert "hugging face" in check["detail"].lower()
    assert "MATRIX_PERSONA_1M_DIR" not in check["detail"]
    assert body["ready"] is True

    monkeypatch.setattr(
        "backend.service.persona_1m_pool.production_1m_available",
        lambda repo_root=None: True,
    )
    body = client.get("/api/preflight").json()
    check = next(c for c in body["checks"] if c["name"] == "MatrAIx Persona 1M")
    assert check["ok"] is True
    assert body["ready"] is True


def test_sample_missing_1m_returns_404(client, monkeypatch):
    """Draw from 1M without a local copy must surface the missing-files error."""

    def _missing(repo_root=None):
        raise FileNotFoundError(
            "MatrAIx Persona 1M release not found locally. "
            "Download MatrAIx2026/MatrAIx_Persona_1M_Public_Release."
        )

    monkeypatch.setattr(
        "backend.service.persona_1m_pool.resolve_1m_paths",
        _missing,
    )
    resp = client.post(
        "/api/persona-pool/sample",
        json={
            "pool": "persona/datasets/matraix-persona-1m",
            "sampleSize": 6,
            "seed": 42,
            "dimensionFilters": {"economic_motivation": ["Cost-sensitive"]},
            "fields": ["economic_motivation"],
            "perCell": 6,
        },
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert isinstance(detail, str)
    assert "1M" in detail
    assert "Internal Server Error" not in detail


def test_sample_loads_portions_from_task_path(client, monkeypatch):
    captured: dict = {}

    def _fake_sample(**kwargs):
        captured.update(kwargs)
        return {
            "pool": "persona/datasets/matraix-persona-dev-sample",
            "matchedCount": 4,
            "sampleSize": 4,
            "seed": 42,
            "personaIds": ["p1", "p2", "p3", "p4"],
            "personas": [],
            "selectedCount": 4,
        }

    monkeypatch.setattr(client.app.state.services.persona_pool, "sample_pool", _fake_sample)
    monkeypatch.setattr(
        "backend.service.task_persona_strategy_service.get_task_persona_strategy",
        lambda task_path, repo_root=None: {
            "sampling": {
                "portions": {
                    "economic_motivation": {
                        "Cost-sensitive": 0.7,
                        "Premium-seeking": 0.3,
                    }
                }
            }
        },
    )
    resp = client.post(
        "/api/persona-pool/sample",
        json={
            "sampleSize": 4,
            "allocation": "proportional",
            "fields": ["economic_motivation"],
            "taskPath": "application/tasks/example-web-demo",
        },
    )
    assert resp.status_code == 200
    assert captured["portions"] == {
        "economic_motivation": {"Cost-sensitive": 0.7, "Premium-seeking": 0.3}
    }


def test_config_options(client):
    resp = client.get("/api/config/options")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {"knobs", "defaults", "environment"}

    knobs = {k["key"]: k for k in body["knobs"]}
    assert set(knobs.keys()) == {
        "applicationId",
        "engine",
        "personaModel",
        "domain",
        "botType",
    }
    engine = knobs["engine"]
    assert engine["label"]
    assert engine["rebuildsAgent"] is True
    engine_values = {o["value"] for o in engine["options"]}
    assert engine_values == {"gpt-4o-mini", "gpt-4o"}
    persona_model = knobs["personaModel"]
    persona_model_values = {o["value"] for o in persona_model["options"]}
    assert persona_model_values == set(PERSONA_MODEL_OPTIONS)
    assert "dashscope/qwen3.6-plus-2026-04-02" in persona_model_values
    assert "dashscope/deepseek-v4-pro" in persona_model_values
    assert "openrouter/z-ai/glm-4.7" in persona_model_values
    assert "openrouter/anthropic/claude-haiku-4.5" in persona_model_values
    assert "gemini/gemini-2.5-flash" in persona_model_values
    assert "gemini/gemini-2.5-pro" in persona_model_values
    assert "gemini/gemini-2.5-computer-use-preview-10-2025" in persona_model_values
    assert "xai/grok-4.5" in persona_model_values
    assert "xai/grok-3-mini" in persona_model_values
    assert "deepseek/deepseek-v4-pro" in persona_model_values
    assert "deepseek/deepseek-chat" in persona_model_values
    assert "zai/glm-5" in persona_model_values
    assert "zai/glm-4.7" in persona_model_values

    assert body["defaults"]["engine"] == "gpt-4o-mini"
    assert body["defaults"]["rankerMode"] == "native"
    assert body["environment"]["resources"] == "adapter-specific resources"
    assert body["environment"]["agent"] == "chatbot application adapter"
    assert body["environment"]["personaModel"] == "anthropic/claude-haiku-4-5"
    assert body["environment"]["scorer"] == "Playground self-report scorer"
    assert "application-specific" in body["environment"]["ranker"]
    assert body["environment"]["promptOwnership"] == {
        "personaSystemPrompt": "Persona prompt from Playground",
        "taskPrompt": "Application-provided chatbot simulation prompt",
    }
