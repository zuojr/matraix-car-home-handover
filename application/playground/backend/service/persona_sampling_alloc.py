"""Shared stratified allocation helpers (Hamilton / largest-remainder)."""

from __future__ import annotations

import random
from typing import Any


def hamilton_allocate(counts: dict[str, int], sample_size: int) -> dict[str, int]:
    """Largest-remainder allocation: quotas sum to ``sample_size``."""
    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    positive = {key: count for key, count in counts.items() if count > 0}
    if not positive:
        raise ValueError("No non-empty strata for proportional allocation")
    total = sum(positive.values())
    if sample_size > total:
        raise ValueError(
            "sample_size={} exceeds matched pool size={}".format(sample_size, total)
        )
    raw = {key: sample_size * (count / total) for key, count in positive.items()}
    floors = {key: int(value) for key, value in raw.items()}
    assigned = sum(floors.values())
    remainders = sorted(
        ((raw[key] - floors[key], key) for key in floors),
        key=lambda item: (-item[0], item[1]),
    )
    quotas = dict(floors)
    for index in range(sample_size - assigned):
        quotas[remainders[index][1]] += 1
    surplus = 0
    for key, quota in list(quotas.items()):
        avail = positive[key]
        if quota > avail:
            surplus += quota - avail
            quotas[key] = avail
    if surplus:
        for _ in range(surplus):
            donors = sorted(
                (
                    (positive[k] - quotas[k], k)
                    for k in quotas
                    if positive[k] > quotas[k]
                ),
                key=lambda item: (-item[0], item[1]),
            )
            if not donors:
                break
            quotas[donors[0][1]] += 1
    return quotas


def sample_proportional_from_buckets(
    buckets: dict[Any, list[dict[str, Any]]],
    *,
    sample_size: int,
    seed: int,
) -> list[dict[str, Any]]:
    counts = {str(key): len(rows) for key, rows in buckets.items()}
    key_map = {str(key): key for key in buckets}
    quotas = hamilton_allocate(counts, sample_size)
    rng = random.Random(seed)
    chosen: list[dict[str, Any]] = []
    for key_str in sorted(quotas):
        take = quotas[key_str]
        if take <= 0:
            continue
        pool = list(buckets[key_map[key_str]])
        rng.shuffle(pool)
        chosen.extend(pool[:take])
    rng.shuffle(chosen)
    return chosen


def portions_allocate(
    counts: dict[str, int],
    weights: dict[str, float],
    sample_size: int,
) -> dict[str, int]:
    """Largest-remainder allocation to *declared target shares* (``weights``).

    Unlike :func:`hamilton_allocate` (which allocates by the pool's natural
    population), this hits an operator-declared target mix — e.g. "70% / 30%"
    — regardless of how the pool is actually distributed. Quotas sum to
    ``sample_size`` and follow the (normalized) weights.

    Only ``counts`` availability constrains it: a bucket whose target quota
    exceeds its available population raises ``ValueError`` (the target is
    infeasible at this ``sample_size``). Ratio mismatch with the pool is *not*
    an error — reweighting away from the pool's natural share is the point.
    """
    if sample_size < 1:
        raise ValueError("sample_size must be >= 1")
    positive = {key: float(weight) for key, weight in weights.items() if float(weight) > 0}
    if not positive:
        raise ValueError("No positive target portions for allocation")
    total_weight = sum(positive.values())
    raw = {key: sample_size * (weight / total_weight) for key, weight in positive.items()}
    floors = {key: int(value) for key, value in raw.items()}
    assigned = sum(floors.values())
    remainders = sorted(
        ((raw[key] - floors[key], key) for key in floors),
        key=lambda item: (-item[0], item[1]),
    )
    quotas = dict(floors)
    for index in range(sample_size - assigned):
        quotas[remainders[index][1]] += 1

    shortfalls = [
        (key, quota, int(counts.get(key, 0)))
        for key, quota in quotas.items()
        if quota > int(counts.get(key, 0))
    ]
    if shortfalls:
        detail = "; ".join(
            f"{key!r} needs {quota} for its target share but pool has {have}"
            for key, quota, have in sorted(shortfalls)
        )
        raise ValueError(
            f"portions target is infeasible at sampleSize={sample_size}: {detail}. "
            "Lower sampleSize, adjust portions, or enlarge the eligible pool."
        )
    return quotas


def sample_by_portions_from_buckets(
    buckets: dict[Any, list[dict[str, Any]]],
    *,
    weights: dict[str, float],
    sample_size: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Draw a cohort matching declared target shares (``weights``) per bucket."""
    counts = {str(key): len(rows) for key, rows in buckets.items()}
    key_map = {str(key): key for key in buckets}
    # Surface target values that are absent from the pool as zero-count buckets
    # so the feasibility check reports them instead of silently dropping.
    for target_key in weights:
        counts.setdefault(str(target_key), 0)
    quotas = portions_allocate(
        counts,
        {str(key): float(weight) for key, weight in weights.items()},
        sample_size,
    )
    rng = random.Random(seed)
    chosen: list[dict[str, Any]] = []
    for key_str in sorted(quotas):
        take = quotas[key_str]
        if take <= 0:
            continue
        pool = list(buckets.get(key_map.get(key_str, key_str), []))
        rng.shuffle(pool)
        chosen.extend(pool[:take])
    rng.shuffle(chosen)
    return chosen
