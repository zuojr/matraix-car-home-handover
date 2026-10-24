"""New coordinator, final design and real loopback HTTP; no external API calls."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import pytest

from matraix.journeys.api import ModelConfig
from matraix.journeys.cohort import CONDITIONS
from matraix.journeys.design import (
    METHOD,
    PRIMARY,
    infer,
    validate_matrix,
    validate_spec,
)
from matraix.journeys.launch import (
    child_environment,
    execute,
    free_port,
    validation_plan,
)
from matraix.journeys.ledger import finish, reserve, summary

REPO = Path(__file__).resolve().parents[3]


def test_deepseek_parameters_reject_incompatible_thinking_before_network():
    with pytest.raises(ValueError, match="thinking.type=disabled"):
        ModelConfig(
            "sut", "https://api.deepseek.com", "deepseek-flash", "NO_KEY"
        ).validate()
    ModelConfig(
        "sut",
        "https://api.deepseek.com",
        "deepseek-flash",
        "NO_KEY",
        options_json='{"thinking":{"type":"disabled"}}',
    ).validate()


def test_native_child_cannot_inherit_model_credentials(monkeypatch):
    monkeypatch.setenv("JOURNEY_SUT_API_KEY", "must-not-copy")
    monkeypatch.setenv("JOURNEY_PUT_API_KEY", "must-not-copy")
    monkeypatch.setenv("SOME_OTHER_API_KEY", "must-not-copy")
    env = child_environment()
    assert not any("API_KEY" in k for k in env)


def test_global_ledger_bounds_failed_and_unknown_calls(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    first = reserve(path, "sut", "hash-one", 2)
    reserve(path, "put", "hash-two", 2)
    finish(path, first, {"status": "failed", "usage": None, "usage_unknown": True})
    with pytest.raises(RuntimeError, match="stopped"):
        reserve(path, "sut", "not-sent", 2)
    s = summary(path)
    assert s["requests"] == 2 and s["failed"] == 1 and s["inflight_or_unknown"] == 1
    assert s["usage_unknown_requests"] == 2 and s["usage_reported_tokens"] == 0


def synthetic_formal():
    cases = []
    for domain in ("car", "home"):
        for n in range(20):
            for c in CONDITIONS:
                for i in range(1, 7):
                    for edge in (False, True):
                        cases.append(
                            {
                                "domain": domain,
                                "id": f"{domain}-{n}-{c}-{i}-{edge}",
                                "source_persona_id": str(n),
                                "block": n + 1,
                                "cohort": c,
                                "task": ("J" if domain == "car" else "H") + str(i),
                                "boundary": edge,
                            }
                        )
    spec = {
        "method": METHOD,
        "independent_unit": "source_persona",
        "primary_comparisons": list(PRIMARY),
        "alpha": 0.05,
        "looks": ["final"],
        "missing": "planned-denominator-[0,1]",
        "bootstrap_replicates": 20000,
        "seed": 71,
        "source_personas": {"car": 20, "home": 20},
        "approved": True,
        "approval_note": "Synthetic statistics unit test only",
    }
    from matraix.journeys.cohort import digest

    plan = {
        "purpose": "formal",
        "cases": cases,
        "planned_episodes": len(cases),
        "formal_spec_frozen": True,
        "freeze": {
            "spec": spec,
            "spec_sha256": digest(spec),
            "sut_config": {"model": "offline"},
            "put_config": {"model": "offline"},
        },
    }
    return plan


def test_source_matrix_disallows_dropping_cells():
    p = synthetic_formal()
    validate_matrix(p)
    p["cases"].pop()
    p["planned_episodes"] -= 1
    with pytest.raises(ValueError, match="48-case"):
        validate_matrix(p)


@pytest.mark.parametrize("change", ["approval", "look", "n", "alpha"])
def test_formal_freeze_requires_approved_matching_prospective_spec(change):
    p = synthetic_formal()
    s = deepcopy(p["freeze"]["spec"])
    if change == "approval":
        s["approved"] = False
    if change == "look":
        s["looks"] = ["interim", "final"]
    if change == "n":
        s["source_personas"]["car"] = 21
    if change == "alpha":
        s["alpha"] = 0.1
    with pytest.raises(ValueError):
        validate_spec(s, p)


@pytest.mark.parametrize(
    "lo,hi,significant", [(0.4, 0.4, True), (0, 0, False), (-1, 1, False)]
)
def test_final_cluster_interval_keeps_missingness_and_never_calls_null_equivalence(
    lo, hi, significant
):
    p = synthetic_formal()
    result = {
        "overall_comparisons": [
            {
                "domain": d,
                "comparison": label,
                "units": [{"lower": lo, "upper": hi} for _ in range(20)],
            }
            for d in ("car", "home")
            for label in ("disclosure", "priority")
        ]
    }
    analysis = infer(result, p)
    assert analysis["family_alpha"] == 0.05
    for r in analysis["intervals"]:
        assert abs(r["lower"] - lo) < 1e-9 and abs(r["upper"] - hi) < 1e-9
        assert r["significant"] is significant and r["equivalence_tested"] is False


def test_no_execution_without_explicit_flag(tmp_path):
    with pytest.raises(ValueError, match="--execute"):
        execute(tmp_path / "absent", tmp_path / "absent.json", tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("mismatch", ["sut", "interaction_limit", "missing_ledger"])
def test_formal_host_actor_checks_freeze_before_any_paid_call(
    tmp_path, monkeypatch, mismatch
):
    from matraix.journeys import run
    from matraix.journeys.cohort import code_contract, digest

    configs = {
        role: ModelConfig(role, "https://offline.invalid", role, "NO_KEY")
        for role in ("sut", "put")
    }
    plan = {
        "purpose": "formal",
        "fixture_only": False,
        "formal_spec_frozen": True,
        "freeze": {
            "sut_config": configs["sut"].public(),
            "put_config": configs["put"].public(),
            "limits": {
                "max_sut_calls_per_case": 160,
                "max_persona_turns": 64,
                "chat_timeout": 1200,
                "max_total_api_requests": 100,
            },
        },
    }
    identity = {
        "mode": "model",
        "plan_sha256": digest(plan),
        "source_contract_sha256": digest(code_contract()),
        "sut_config": configs["sut"].public(),
        "max_sut_calls_per_case": 160,
    }
    if mismatch == "sut":
        identity["sut_config"] = {"model": "changed"}
    if mismatch == "interaction_limit":
        identity["max_sut_calls_per_case"] = 159
    monkeypatch.setattr(run, "load_plan", lambda path: plan)
    monkeypatch.setattr(run.ModelConfig, "from_env", lambda role: configs[role])
    monkeypatch.delenv("JOURNEY_REQUEST_LEDGER", raising=False)

    def handle(request):
        assert request.method == "GET" and request.url.path == "/ready"
        return httpx.Response(200, json=identity)

    with pytest.raises(ValueError, match="formal freeze|fresh shared request ledger"):
        run.run_api(
            tmp_path / "unused",
            "http://localhost",
            tmp_path / "out",
            execute=True,
            transport=httpx.MockTransport(handle),
        )
    assert not (tmp_path / "out").exists()


def test_formal_harbor_recipes_reject_unshared_budget_path(tmp_path, monkeypatch):
    from matraix.journeys import cli

    monkeypatch.setattr(
        cli,
        "load_plan",
        lambda path: {
            "purpose": "formal",
            "fixture_only": False,
            "formal_spec_frozen": True,
        },
    )
    with pytest.raises(ValueError, match="shared request ledger"):
        cli.resolve(
            REPO,
            tmp_path / "unused",
            REPO / "journey-runs/formal-should-never-start",
            "unused",
        )


@pytest.mark.parametrize(
    "concurrency,fault", [(1, 0), (2, 0), (4, 0), (8, 0), (2, 8), (4, 8), (8, 8)]
)
def test_full_sixteen_episode_coordinator_uses_only_local_scripted_api(
    tmp_path, monkeypatch, concurrency, fault
):
    if not os.getenv("SIMUHOME_ROOT"):
        pytest.skip("Pinned native Home checkout required")
    plan = tmp_path / "plan"
    collaborator_cli = concurrency == 2 and fault == 0
    cli_env = child_environment()
    if collaborator_cli:
        # Exercise the documented fresh-checkout commands, with fake keys and a
        # loopback-only API. Other variants retain the lower-level runner tests.
        generated = subprocess.run(
            [
                sys.executable,
                "-m",
                "matraix.journeys",
                "validation-plan",
                "--repo",
                str(REPO),
                "--out",
                str(plan),
            ],
            cwd=REPO,
            env=cli_env,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        assert json.loads(generated.stdout)["planned_episodes"] == 16
    else:
        validation_plan(REPO, plan)
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    settings = {
        role: {
            "base_url": url,
            "model": "offline-" + role,
            "timeout": 15,
            "max_tokens": 1024,
        }
        for role in ("sut", "put")
    }
    settings["limits"] = {"max_total_api_requests": 400}
    settings["concurrency"] = concurrency
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    for role in ("sut", "put"):
        monkeypatch.setenv(
            "JOURNEY_" + role.upper() + "_API_KEY", "offline-test-not-a-secret"
        )
    log = (tmp_path / "stub.log").open("wb")
    server = subprocess.Popen(
        [
            sys.executable,
            str(REPO / "tests/helpers/journey_api_stub.py"),
            "--plan",
            str(plan),
            "--port",
            str(port),
            "--fail-at",
            str(fault),
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        env=child_environment(),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise AssertionError(
                    (tmp_path / "stub.log").read_text(encoding="utf-8")
                )
            try:
                if (
                    httpx.get(url + "/health", timeout=1, trust_env=False).status_code
                    == 200
                ):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        if collaborator_cli:
            secret = "offline-cli-not-a-real-secret"
            for role in ("SUT", "PUT"):
                credential = tmp_path / (role + ".key")
                credential.write_text(secret, encoding="utf-8")
                cli_env["JOURNEY_" + role + "_API_KEY_FILE"] = str(credential)
            checked = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "scripts/check_journey_setup.py"),
                    "--config",
                    str(path),
                    "--plan",
                    str(plan),
                    "--check-credentials",
                ],
                cwd=REPO,
                env=cli_env,
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            assert json.loads(checked.stdout)["model_requests"] == 0
            assert httpx.get(url + "/health", trust_env=False).json()["calls"] == 0
            executed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "matraix.journeys",
                    "execute",
                    "--plan",
                    str(plan),
                    "--config",
                    str(path),
                    "--out",
                    str(tmp_path / "run"),
                    "--execute",
                ],
                cwd=REPO,
                env=cli_env,
                capture_output=True,
                text=True,
                timeout=180,
                check=True,
            )
            assert (
                secret
                not in checked.stdout
                + checked.stderr
                + executed.stdout
                + executed.stderr
            )
            result = json.loads(executed.stdout)
            replay = json.loads((tmp_path / "run/verifier/replay.json").read_text())
            assert replay["replayed"] == 16 and replay["missing"] == []
            lifecycle = json.loads(
                (tmp_path / "run/service_lifecycle.json").read_text()
            )
            assert lifecycle["live_children"] == 0
            assert all(service["exit_code"] == 0 for service in lifecycle["services"])
        else:
            result = execute(plan, path, tmp_path / "run", execute_authorized=True)
        if fault:
            assert result["status"] == "stopped"
            assert result["unattempted"] > 0
            assert result["ledger"]["inflight_or_unknown"] == 0
            assert result["ledger"]["failed"] > 0
            lifecycle = json.loads(
                (tmp_path / "run/service_lifecycle.json").read_text(encoding="utf-8")
            )
            assert lifecycle["live_children"] == 0
            assert all(s["exit_code"] == 0 for s in lifecycle["services"])
            return
        assert result["status"] == "complete", result
        assert (
            result["planned"] == result["terminal_records"] == 16
            and result["missing_or_unresolved"] == 0
        )
        assert (
            result["ledger"]["requests"] > 16
            and result["ledger"]["inflight_or_unknown"] == 0
        )
        assert result["ledger"]["usage_reported_tokens"] == 0
        scheduler = json.loads(
            (tmp_path / "run/actor/scheduler.json").read_text(encoding="utf-8")
        )
        assert scheduler["peak_submitted_unfinished"] == concurrency
        assert len(set(scheduler["dispatched_case_ids"])) == 16
        assert (
            json.loads(
                (tmp_path / "run/service_lifecycle.json").read_text(encoding="utf-8")
            )["live_children"]
            == 0
        )
        assert not (tmp_path / "run/analysis/descriptive.json").exists()
        assert (tmp_path / "run/REPORT_CN.md").exists()
        from matraix.journeys.cli import analyze

        with pytest.raises(ValueError, match="Reference evidence"):
            analyze(
                tmp_path / "run/plan",
                tmp_path / "run/records",
                tmp_path / "forbidden-analysis",
            )
    finally:
        server.terminate()
        server.wait(timeout=10)
        log.close()
        for key in ("JOURNEY_REQUEST_LEDGER", "JOURNEY_REQUEST_LIMIT"):
            monkeypatch.delenv(key, raising=False)
