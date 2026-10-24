"""The collaborator's preflight must be local, secret-safe and actionable."""

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "journey_preflight", REPO / "scripts/check_journey_setup.py"
)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Preflight may not contact a provider")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    if not os.getenv("SIMUHOME_ROOT"):
        pytest.skip("Pinned SimuHome checkout required")
    for role in ("SUT", "PUT"):
        monkeypatch.delenv(f"JOURNEY_{role}_API_KEY", raising=False)
        monkeypatch.delenv(f"JOURNEY_{role}_API_KEY_FILE", raising=False)


def config(tmp_path):
    data = json.loads(
        (REPO / "configs/journeys/chat-compatible.example.json").read_text()
    )
    for role in ("sut", "put"):
        data[role].update(base_url="http://127.0.0.1:1/v1", model="my-" + role)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    return path


def test_preflight_without_key_checks_sends_nothing_and_restores_environment(tmp_path):
    previous = dict(os.environ)
    result = preflight.check_setup(config(tmp_path))
    assert (
        result["local_setup_valid"]
        and result["model_requests"] == result["http_requests"] == 0
    )
    assert result["roles"]["sut"]["credential_present"] is None
    assert result["remote_key_model_and_protocol_verified"] is False
    assert dict(os.environ) == previous


def test_separate_role_key_files_never_enter_output_or_persist(tmp_path, monkeypatch):
    secret = "private-value-not-for-output"
    for role in ("SUT", "PUT"):
        p = tmp_path / (role + ".key")
        p.write_text(secret + role)
        monkeypatch.setenv(f"JOURNEY_{role}_API_KEY_FILE", str(p))
    previous = dict(os.environ)
    result = preflight.check_setup(config(tmp_path), check_credentials=True)
    assert all(r["credential_present"] for r in result["roles"].values())
    assert secret not in json.dumps(result)
    assert dict(os.environ) == previous


@pytest.mark.parametrize(
    "problem", ["placeholders", "missing_key", "invalid_options", "native_missing"]
)
def test_fail_closed_for_incomplete_setup(tmp_path, problem):
    path = config(tmp_path)
    kwargs = {}
    if problem == "placeholders":
        path = REPO / "configs/journeys/chat-compatible.example.json"
    elif problem == "missing_key":
        kwargs["check_credentials"] = True
    elif problem == "invalid_options":
        data = json.loads(path.read_text())
        data["sut"]["options"] = {"unreviewed_sdk_option": 1}
        path.write_text(json.dumps(data))
    elif problem == "native_missing":
        kwargs["native_root"] = tmp_path / "missing"
    with pytest.raises(ValueError):
        preflight.check_setup(path, **kwargs)


def test_shared_cli_key_file_is_checked_without_printing(tmp_path):
    secret = "private-shared-not-a-real-key"
    p = tmp_path / "secret.key"
    p.write_text(secret)
    command = [
        sys.executable,
        str(REPO / "scripts/check_journey_setup.py"),
        "--config",
        str(config(tmp_path)),
        "--key-file",
        str(p),
        "--check-credentials",
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=30, check=True
    )
    assert secret not in result.stdout + result.stderr
    parsed = json.loads(result.stdout)
    assert parsed["local_setup_valid"] and parsed["model_requests"] == 0


def test_real_prepared_validation_plan_is_accepted(tmp_path):
    from matraix.journeys.launch import validation_plan

    plan = tmp_path / "plan"
    validation_plan(REPO, plan)
    result = preflight.check_setup(config(tmp_path), plan=plan)
    assert result["plan"]["purpose"] == "validation"
    assert result["plan"]["planned_episodes"] == 16


@pytest.mark.parametrize("bad_value", [None, {"unexpected": "private-option-value"}])
def test_malformed_configuration_cli_is_secret_safe_and_nonzero(tmp_path, bad_value):
    path = config(tmp_path)
    data = json.loads(path.read_text())
    data["sut"]["base_url"] = bad_value
    path.write_text(json.dumps(data))
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/check_journey_setup.py"),
            "--config",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1 and not result.stderr
    assert "private-option-value" not in result.stdout
    assert json.loads(result.stdout)["local_setup_valid"] is False


def test_failed_key_check_also_restores_environment(tmp_path, monkeypatch):
    key = tmp_path / "sut.key"
    key.write_text("offline-role-key")
    monkeypatch.setenv("JOURNEY_SUT_API_KEY_FILE", str(key))
    previous = dict(os.environ)
    with pytest.raises(ValueError, match="Missing credential"):
        preflight.check_setup(config(tmp_path), check_credentials=True)
    assert dict(os.environ) == previous


def test_old_editable_persona_renderer_is_rejected_before_requests(
    tmp_path, monkeypatch
):
    from matraix.agents.persona import templating

    monkeypatch.setattr(
        templating, "render_persona_template", lambda template, persona: ""
    )
    with pytest.raises(ValueError, match="older persona renderer"):
        preflight.check_setup(config(tmp_path))


def test_no_author_runtime_needed_for_collaborator_smoke():
    guide = (REPO / "docs/journeys/COLLABORATOR_QUICKSTART_CN.md").read_text(
        encoding="utf-8"
    )
    assert "python scripts/validate_journey_harbor.py" in guide
    assert "python -m matraix.cli experiment create" in guide
    assert "--persona-pool COHORT_DIR --persona-ids" in guide
    assert "experiment analyze EXPERIMENT_ID --format json,csv,pdf" in guide
