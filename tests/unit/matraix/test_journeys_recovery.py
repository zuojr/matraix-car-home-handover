"""Never-attempted continuation and immutable prior accounting; no paid calls."""

from concurrent.futures import CancelledError
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from matraix.journeys import ledger

REPO = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "journey_recovery", REPO / "scripts/journey_recovery.py"
)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


def baseline(path, count=3):
    for i in range(count):
        rid = ledger.reserve(path, "sut", f"old-{i}", 100)
        ledger.finish(
            path,
            rid,
            {
                "status": "failed" if i == 0 else "accepted",
                "role": "sut",
                "usage_unknown": i == 0,
                "usage": None if i == 0 else {"total_tokens": 1},
            },
        )
        if i < count - 1:
            with ledger.database(path) as c:
                c.execute("UPDATE control SET stopped=0,reason=NULL WHERE id=1")
    ledger.stop(path, "previous response read interruption")
    return recovery.ledger_fingerprint(path)


def test_partition_excludes_all_330_attempts_not_only_322_terminal_records():
    plan = {"cases": [{"id": f"case-{i}"} for i in range(4800)]}
    attempted = [f"case-{i}" for i in range(330)]
    remaining = recovery.partition_cases(plan, attempted)
    assert len(remaining) == 4470
    assert remaining[0]["id"] == "case-330"
    assert not {f"case-{i}" for i in range(322, 330)} & {c["id"] for c in remaining}


def test_partition_preserves_original_order_for_nonprefix_attempts():
    plan = {"cases": [{"id": str(i)} for i in range(8)]}
    assert [c["id"] for c in recovery.partition_cases(plan, ["6", "1", "3"])] == [
        "0",
        "2",
        "4",
        "5",
        "7",
    ]


@pytest.mark.parametrize("attempts", [["1", "1"], ["not-planned"]])
def test_partition_rejects_duplicate_or_unknown_prior_attempts(attempts):
    with pytest.raises(ValueError):
        recovery.partition_cases({"cases": [{"id": "1"}]}, attempts)


def test_copy_carries_failures_usage_and_global_cap_without_touching_old_ledger(
    tmp_path,
):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    expected = baseline(old)
    recovery.copy_ledger(old, new, expected, authorize_continuation=True)
    assert recovery.ledger_fingerprint(old) == expected
    assert recovery.ledger_fingerprint(new)["control"] == [0, None]
    assert recovery.ledger_fingerprint(new)["failed"] == 1
    for i in range(2):
        rid = ledger.reserve(new, "put", f"new-{i}", 5)
        assert rid > expected["max_id"]
        ledger.finish(
            new,
            rid,
            {
                "status": "accepted",
                "role": "put",
                "usage_unknown": False,
                "usage": {"total_tokens": 2},
            },
        )
    with pytest.raises(RuntimeError, match="ceiling"):
        ledger.reserve(new, "put", "must-not-dispatch", 5)
    assert ledger.summary(new)["requests"] == 5
    assert ledger.summary(new)["usage_unknown_requests"] == 1
    assert (
        recovery.ledger_fingerprint(new, expected["max_id"])["rows_sha256"]
        == expected["rows_sha256"]
    )
    assert recovery.ledger_fingerprint(old) == expected


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE requests SET status='accepted' WHERE id=1",
        "DELETE FROM requests WHERE id=2",
    ],
)
def test_derived_ledger_prevents_mutation_of_preserved_requests(tmp_path, sql):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    expected = baseline(old)
    recovery.copy_ledger(old, new, expected, authorize_continuation=True)
    with ledger.database(new) as c:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute(sql)
    assert (
        recovery.ledger_fingerprint(new, expected["max_id"])["rows_sha256"]
        == expected["rows_sha256"]
    )


def test_copy_rejects_changed_baseline_and_existing_destination(tmp_path):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    expected = baseline(old)
    changed = {**expected, "rows_sha256": "wrong"}
    with pytest.raises(ValueError, match="changed"):
        recovery.copy_ledger(old, new, changed)
    assert not new.exists()
    recovery.copy_ledger(old, new, expected)
    with pytest.raises(ValueError, match="new ledger"):
        recovery.copy_ledger(old, new, expected)


def test_copy_rejects_inflight_even_if_snapshot_matches(tmp_path):
    old = tmp_path / "old.db"
    ledger.reserve(old, "sut", "inflight", 100)
    expected = recovery.ledger_fingerprint(old)
    with pytest.raises(ValueError, match="in-flight"):
        recovery.copy_ledger(
            old, tmp_path / "new.db", expected, authorize_continuation=True
        )


def fake_config():
    return SimpleNamespace(public=lambda: {"model": "scripted-test-only"})


def test_dispatch_only_remaining_and_original_indices_once(tmp_path):
    plan = {
        "protocol": "offline-dispatch-test",
        "cases": [{"id": str(i)} for i in range(6)],
    }
    candidates = recovery.partition_cases(plan, ["0", "2"])
    calls = []

    def scripted(case, index, *args):
        calls.append((case["id"], index))
        return case["id"]

    limits = {"concurrency": 2, "max_persona_turns": 64, "chat_timeout": 1200}
    result = recovery.dispatch(
        candidates,
        plan,
        tmp_path,
        "http://never.invalid",
        tmp_path / "actor",
        fake_config(),
        limits,
        tmp_path / "ledger",
        case_fn=scripted,
    )
    assert set(result) == {"1", "3", "4", "5"}
    assert set(calls) == {("1", 1), ("3", 3), ("4", 4), ("5", 5)}
    assert len(calls) == 4
    with pytest.raises(ValueError, match="restart"):
        recovery.dispatch(
            candidates,
            plan,
            tmp_path,
            "http://never.invalid",
            tmp_path / "actor",
            fake_config(),
            limits,
            tmp_path / "ledger",
            case_fn=scripted,
        )


def test_new_failure_stops_without_retry_or_releasing_old_cap(tmp_path):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    expected = baseline(old)
    recovery.copy_ledger(old, new, expected, authorize_continuation=True)
    plan = {
        "protocol": "offline-failure-test",
        "cases": [{"id": str(i)} for i in range(5)],
    }
    calls = []

    def scripted(
        case,
        index,
        plan,
        plan_path,
        chat_url,
        out,
        config,
        turns,
        timeout,
        transport,
        factory,
        cancelled,
        fail,
    ):
        if cancelled.is_set():
            raise CancelledError()
        calls.append(case["id"])
        exc = RuntimeError("scripted transport read error")
        fail(case["id"], "no-real-session", exc)
        raise exc

    limits = {"concurrency": 1, "max_persona_turns": 64, "chat_timeout": 1200}
    with pytest.raises(RuntimeError, match="stopped"):
        recovery.dispatch(
            recovery.partition_cases(plan, ["0"]),
            plan,
            tmp_path,
            "http://never.invalid",
            tmp_path / "actor",
            fake_config(),
            limits,
            new,
            case_fn=scripted,
        )
    assert calls == ["1"]
    assert ledger.is_stopped(new)
    assert recovery.ledger_fingerprint(old) == expected
    schedule = json.loads((tmp_path / "actor/scheduler.json").read_text())
    assert schedule["dispatched_case_ids"] == ["1"]
    assert schedule["automatic_retry"] is False


def test_ready_checks_model_plan_ledger_binding_and_exact_carried_rows(
    tmp_path, monkeypatch
):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    expected = baseline(old)
    recovery.copy_ledger(old, new, expected, authorize_continuation=True)
    plan = {"cases": []}
    configs = {"sut": fake_config()}
    limits = {"max_sut_calls_per_case": 160, "max_total_api_requests": 60000}
    identity = {
        "mode": "model",
        "plan_sha256": recovery.digest(plan),
        "source_contract_sha256": recovery.digest(recovery.code_contract()),
        "sut_config": configs["sut"].public(),
        "max_sut_calls_per_case": 160,
        "request_accounting": ledger.binding(new, 60000),
    }
    recovery.check_ready(identity, plan, configs, limits, new, expected)
    bad = deepcopy(identity)
    bad["sut_config"] = {"model": "wrong"}
    with pytest.raises(ValueError, match="contract"):
        recovery.check_ready(bad, plan, configs, limits, new, expected)
    ledger.reserve(new, "put", "unexpected-paid-call-before-ready", 60000)
    with pytest.raises(ValueError, match="baseline"):
        recovery.check_ready(identity, plan, configs, limits, new, expected)


def test_unchanged_inference_gate_keeps_eight_missing_and_unknown_usage_ineligible():
    plan = {"cases": [{"id": str(i)} for i in range(4800)]}
    rows = {str(i): {} for i in range(4792)}
    stats = {"inflight_or_unknown": 0, "usage_unknown_requests": 4, "failed": 4}
    assert not recovery.original_inference_eligible(
        plan,
        rows,
        stats,
        True,
        {"attempted_without_terminal_ids": [str(i) for i in range(8)]},
    )
    # Even a terminal-count coincidence cannot erase the old unknown requests.
    assert not recovery.original_inference_eligible(
        plan,
        {str(i): {} for i in range(4800)},
        stats,
        True,
        {"attempted_without_terminal_ids": []},
    )


def test_hash_preservation_rejects_changed_old_raw_artifact(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    p = raw / "response.json"
    p.write_text("original unmodified failed evidence")
    manifest = tmp_path / "seal.json"
    manifest.write_text(json.dumps({"files": {"response.json": recovery.file_hash(p)}}))
    recovery.verify_hash_manifest(raw, manifest)
    p.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        recovery.verify_hash_manifest(raw, manifest)


def test_execute_without_explicit_paid_authorization_never_creates_directory(tmp_path):
    with pytest.raises(ValueError, match="--execute"):
        recovery.execute(tmp_path / "not-created", tmp_path / "settings.json")
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize(
    "candidates", [[], [{"id": "unknown"}], [{"id": "1", "altered": True}]]
)
def test_dispatch_rejects_noncanonical_candidates_before_creating_actor(
    tmp_path, candidates
):
    with pytest.raises(ValueError, match="frozen plan"):
        recovery.dispatch(
            candidates,
            {"cases": [{"id": "1"}]},
            tmp_path,
            "http://never.invalid",
            tmp_path / "actor",
            fake_config(),
            {},
            tmp_path / "db",
        )
    assert not (tmp_path / "actor").exists()


def test_finalization_combines_segments_once_and_retains_original_missing_gate(
    tmp_path, monkeypatch
):
    from matraix.journeys import design, programmatic, verify

    old, segment = tmp_path / "old", tmp_path / "segment"
    old.mkdir()
    segment.mkdir()
    cases = [
        {
            "id": f"{domain}-{i}-{cohort}",
            "domain": domain,
            "task": ("J" if domain == "car" else "H") + str(i),
            "source_persona_id": domain + "-persona",
            "cohort": cohort,
        }
        for domain in ("car", "home")
        for i in range(1, 7)
        for cohort in ("C1", "C2", "C3", "C4")
    ]
    plan = {
        "cases": cases,
        "protocol": "offline-test",
        "freeze": {"limits": {"concurrency": 8}},
    }
    previous = baseline(old / "requests.sqlite3")
    recovery.copy_ledger(
        old / "requests.sqlite3",
        segment / "requests.sqlite3",
        previous,
        authorize_continuation=True,
    )
    for i, case in enumerate(cases):
        folder = (old if i < 2 else segment) / "records" / case["id"]
        recovery.write_new(folder / "binding.json", {"case": case, "mode": "model"})
        if i != 1:
            recovery.write_new(
                folder / "record.json",
                {
                    "score": {
                        "metric_version": programmatic.CONTRACT,
                        programmatic.METRIC: 1,
                        "feasible_partial_completion": 0,
                        "issues": [],
                    }
                },
            )
        if i >= 2:
            recovery.write_new(
                segment / "actor" / case["id"] / "attempt.json", {"case_id": case["id"]}
            )
    seal = tmp_path / "preserved.json"
    recovery.write_new(
        seal,
        {
            "files": {
                p.relative_to(old).as_posix(): recovery.file_hash(p)
                for p in old.rglob("*.json")
            }
        },
    )

    def replay(folder):
        return recovery.read(folder / "binding.json"), recovery.read(
            folder / "record.json"
        ) if (folder / "record.json").exists() else None

    monkeypatch.setattr(verify, "verify_trial", replay)

    def forbidden(*args):
        raise AssertionError("Incomplete continuation must not run formal inference")

    monkeypatch.setattr(design, "infer", forbidden)
    manifest = {
        "prior_run": str(old),
        "prior_preservation_manifest": str(seal),
        "prior_index": {
            "attempted_case_ids": [c["id"] for c in cases[:2]],
            "attempted_without_terminal_ids": [cases[1]["id"]],
            "ledger": previous,
        },
        "never_attempted_case_ids": [c["id"] for c in cases[2:]],
        "continuation_count": 46,
        "plan_sha256": recovery.digest(plan),
        "spec_sha256": "unchanged",
    }
    result = recovery.finalize(tmp_path / "recovery", segment, manifest, plan, None)
    assert result["status"] == "remaining_collection_complete_with_retained_missing"
    assert result["planned"] == 48 and result["attempted"] == 48
    assert result["terminal_records"] == 47 and result["missing_or_unresolved"] == 1
    assert result["unattempted"] == 0 and result["formal_inference_eligible"] is False
    analysis = recovery.read(
        tmp_path / "recovery/combined-final/analysis/descriptive.json"
    )
    assert analysis["inference_enabled"] is False
    assert sum(g["planned"] for g in analysis["groups"]) == 48
    assert sum(g["confirmed_success"] for g in analysis["groups"]) == 47
    assert recovery.ledger_fingerprint(old / "requests.sqlite3") == previous
