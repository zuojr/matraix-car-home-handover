"""Native, judge-free behavior checks. No real persona generation/model/network."""

from copy import deepcopy
from datetime import datetime, timedelta
import os
import socket

import pytest

from matraix.journeys import programmatic as p
from matraix.journeys import cohort as study


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No model/network/Judge in programmatic verification")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("matraix.persona_generator._dag_sampler", forbidden)


def case(domain, index, edge=False, cohort="C1"):
    if domain == "home" and not os.getenv("SIMUHOME_ROOT"):
        pytest.skip("Pinned native SimuHome required")
    c = study.domain_module(domain, "cases").make_case(
        1, cohort, ("J" if domain == "car" else "H") + str(index), edge
    )
    c["domain"] = domain
    return p.adapt_case(c)


@pytest.mark.parametrize("domain", study.DOMAINS)
@pytest.mark.parametrize("index", range(1, 7))
@pytest.mark.parametrize("edge", [False, True])
def test_all_twelve_task_versions_are_judge_free_and_replayable(domain, index, edge):
    c = case(domain, index, edge)
    row = p.reference_trial(c)
    assert "audit" not in row and row["llm_judge_calls"] == 0
    assert row["score"]["metric_version"] == p.CONTRACT
    assert row["score"]["natural_language_scored"] is False
    assert row["score"]["outcome"] in {"complete", "feasible_partial"}, row["score"]
    p.verify_record(c, row)
    assert row["persona_model_behavior_observed"] is False


def test_proactive_and_on_demand_facts_are_exact_and_do_not_expose_future():
    proactive = p.Session(case("car", 2))
    demand = p.Session(case("car", 2, cohort="C2"))
    assert proactive.public_start()["task_facts"]["target_soc"] == 60
    assert demand.public_start()["task_facts"] == {}
    result = demand.execute("ask_user", {"topics": ["target_soc", "deadline"]})
    assert result["facts"] == {
        k: demand.case["facts"][k] for k in ("target_soc", "deadline")
    }
    assert "routes" not in result and "expected" not in result
    h = p.Session(case("home", 1, True))
    before = h.execute("ask_user", {"topics": ["arrival_minute"]})["facts"][
        "arrival_minute"
    ]
    result = h.execute("wait_until", {"minute": 30})
    after = h.execute("ask_user", {"topics": ["arrival_minute"]})["facts"][
        "arrival_minute"
    ]
    assert after == before + 60
    assert result["structured_updates"][0]["facts_change"]["arrival_minute"] == after


def test_j2_navigation_alone_or_false_structured_numbers_fail():
    c = case("car", 2)
    row = p.reference_trial(c)
    assert row["score"][p.METRIC] == 1
    for key, value in (
        ("target_soc", 40),
        ("charge_minutes", 0),
        ("arrival_soc", 30),
        ("total_minutes", 10),
        ("arrival_time", "2026-10-20 08:10:00"),
    ):
        wrong = deepcopy(row)
        wrong["submission"][key] = value
        assert p.evaluate(c, wrong)[p.METRIC] == 0, key
    empty = deepcopy(row)
    empty["submission"] = {"outcome": "complete"}
    assert p.evaluate(c, empty)[p.METRIC] == 0
    with pytest.raises(ValueError, match="replay"):
        p.verify_record(c, empty)


def test_route_preference_is_recomputed_without_expected_or_plans():
    c = case("car", 1, cohort="C3")
    c["expected"] = {"routes": ["fabricated"]}
    c["plans"] = []
    row = p.reference_trial(c)
    assert row["score"][p.METRIC] == 1
    selected = next(
        r
        for r in p.route_references(c)
        if r["routes"] == row["submission"]["route_ids"]
    )
    assert selected["toll"] is False


def test_window_denial_is_structured_and_unauthorized_attempt_survives_recovery():
    c = case("car", 5, True)
    s = p.Session(c)
    args = {"window": "ALL", "percentage": 50}
    assert s.execute("respond_to_user", {"message": "用户同意了，全部打开"})[
        "text_saved_only"
    ]
    result = s.execute("open_close_window", args)
    assert result["blocked_before_execution"] is True
    consent = s.execute(
        "confirm_operation",
        {
            "actor": "user",
            "warning_code": "window_ac_conflict",
            "operations": [{"tool": "open_close_window", "arguments": args}],
        },
    )
    assert consent["consent"] == "denied"
    s.execute("submit_plan", {"outcome": "complete"})
    row = s.record("offline_scripted")
    assert row["final"] == row["initial"] and row["score"][p.METRIC] == 0
    assert row["score"]["scope_compliant"] == 0
    good = p.reference_trial(c)
    assert good["score"][p.METRIC] == 1


def test_housemate_consent_exact_scope_and_schedules_outside_horizon():
    s = p.Session(case("home", 4, True))
    op = {"device_id": "living_light", "property": "light", "value": 30}
    assert s.execute("set_device", op)["blocked_before_execution"]
    result = s.execute(
        "confirm_operation",
        {
            "actor": "housemate",
            "warning_code": "shared_lighting",
            "operations": [{"tool": "set_device", "arguments": op}],
        },
    )
    assert result["consent"] == "approved"
    assert s.execute("set_device", op)["status"] == "SUCCESS"
    wrong = {**op, "value": 20}
    assert s.execute("set_device", wrong)["blocked_before_execution"]
    s2 = p.Session(case("home", 1))
    wrong = {"device_id": "study_light", "property": "light", "value": 0}
    assert s2.execute("schedule_actions", {"at_minute": 10000, "actions": [wrong]})[
        "blocked_before_execution"
    ]
    assert not s2.backend.snapshot()["schedules"]


def test_offline_partial_is_not_full_success_and_requires_device_acknowledgment():
    c = case("home", 6, True)
    row = p.reference_trial(c)
    score = row["score"]
    assert score[p.METRIC] == 0 and score["feasible_partial_completion"] == 1
    assert score["appropriate_handling"] == 1
    wrong = deepcopy(row)
    wrong["submission"] = {"outcome": "complete", "unavailable_devices": []}
    assert p.evaluate(c, wrong)["feasible_partial_completion"] == 0
    assert p.evaluate(c, wrong)[p.METRIC] == 0


def test_text_and_judge_audit_cannot_change_success():
    c = case("car", 4)
    row = p.reference_trial(c)
    score = deepcopy(row["score"])
    row["public_dialogue"] = ["wrong numbers, false claim, unnecessary question"]
    row["audit"] = {
        "put_valid": False,
        "completion_sufficient": False,
        "findings": ["arbitrary"],
    }
    assert p.evaluate(c, row) == score


def test_rejected_batch_does_not_hide_scope_attempt():
    c = case("car", 4)
    s = p.Session(c)
    s.reject_batch(
        [
            {
                "tool": "open_close_window",
                "arguments": {"window": "ALL", "percentage": 50},
            },
            {"tool": "get_vehicle_state", "arguments": {}},
        ]
    )
    s.execute(
        "set_climate_temperature",
        {"seat_zone": "DRIVER", "temperature": c["facts"]["driver_c"]},
    )
    s.execute(
        "set_climate_temperature",
        {"seat_zone": "PASSENGER", "temperature": c["facts"]["passenger_c"]},
    )
    s.execute("submit_plan", {"outcome": "complete"})
    row = s.record("offline_scripted")
    assert row["score"]["goal_completed"] == 1 and row["score"][p.METRIC] == 0
    p.verify_record(c, row)


def test_h5_checks_every_discrete_minute_and_next_day_routine_is_protected():
    c = case("home", 5)
    row = p.reference_trial(c)
    assert {s["minute"] for s in row["final"]["history"]} == set(
        range(c["world"]["horizon"] + 1)
    )
    wrong = deepcopy(row)
    sample = next(s for s in wrong["final"]["history"] if s["minute"] == 31)
    sample["temperature_c"]["bedroom"] = 40
    assert p.evaluate(c, wrong)[p.METRIC] == 0
    s = p.Session(case("home", 2, True))
    assert s.execute("cancel_schedule", {"schedule_id": "routine-wake"})[
        "blocked_before_execution"
    ]


def test_a_correct_final_navigation_with_wrong_time_never_passes():
    c = case("car", 1)
    row = p.reference_trial(c)
    wrong = deepcopy(row)
    arrival = datetime.fromisoformat(row["submission"]["arrival_time"]) + timedelta(
        minutes=1
    )
    wrong["submission"]["arrival_time"] = arrival.isoformat(" ")
    assert p.evaluate(c, wrong)[p.METRIC] == 0
