"""Unit tests for Hamilton / proportional stratum allocation."""

from __future__ import annotations

import pytest

from backend.service.persona_sampling_alloc import (
    hamilton_allocate,
    portions_allocate,
    sample_by_portions_from_buckets,
)


def test_hamilton_allocate_sums_to_sample_size() -> None:
    quotas = hamilton_allocate({"a": 50, "b": 30, "c": 20}, 10)
    assert sum(quotas.values()) == 10
    assert quotas["a"] >= quotas["b"] >= quotas["c"]


def test_hamilton_allocate_respects_availability() -> None:
    quotas = hamilton_allocate({"tiny": 1, "big": 99}, 5)
    assert sum(quotas.values()) == 5
    assert quotas["tiny"] <= 1
    assert quotas["big"] <= 99


def test_portions_allocate_follows_declared_shares() -> None:
    # 70/30 target on a sample of 20 → 14 / 6, regardless of pool ratio.
    quotas = portions_allocate(
        {"cost": 200, "premium": 200},
        {"cost": 0.7, "premium": 0.3},
        20,
    )
    assert quotas == {"cost": 14, "premium": 6}


def test_portions_allocate_normalizes_arbitrary_weights() -> None:
    # Weights need not sum to 1 — they are relative shares.
    quotas = portions_allocate({"a": 100, "b": 100}, {"a": 7, "b": 3}, 10)
    assert quotas == {"a": 7, "b": 3}


def test_portions_allocate_ratio_mismatch_is_not_an_error() -> None:
    # Pool is 50/50 but target is 70/30 — allowed as long as pool can supply it.
    quotas = portions_allocate({"cost": 50, "premium": 50}, {"cost": 0.7, "premium": 0.3}, 20)
    assert quotas == {"cost": 14, "premium": 6}


def test_portions_allocate_raises_on_shortfall() -> None:
    with pytest.raises(ValueError) as exc:
        portions_allocate({"cost": 9, "premium": 200}, {"cost": 0.7, "premium": 0.3}, 20)
    message = str(exc.value)
    assert "infeasible" in message
    assert "'cost'" in message and "9" in message


def test_sample_by_portions_from_buckets_hits_quota() -> None:
    buckets = {
        "cost": [{"personaId": f"c{i}"} for i in range(50)],
        "premium": [{"personaId": f"p{i}"} for i in range(50)],
    }
    chosen = sample_by_portions_from_buckets(
        buckets, weights={"cost": 0.7, "premium": 0.3}, sample_size=20, seed=1
    )
    ids = {row["personaId"] for row in chosen}
    assert len(chosen) == 20
    assert sum(1 for pid in ids if pid.startswith("c")) == 14
    assert sum(1 for pid in ids if pid.startswith("p")) == 6


def test_sample_by_portions_flags_target_value_absent_from_pool() -> None:
    # 'premium' has a target share but no members in the pool → shortfall.
    buckets = {"cost": [{"personaId": f"c{i}"} for i in range(50)]}
    with pytest.raises(ValueError):
        sample_by_portions_from_buckets(
            buckets, weights={"cost": 0.7, "premium": 0.3}, sample_size=20, seed=1
        )
