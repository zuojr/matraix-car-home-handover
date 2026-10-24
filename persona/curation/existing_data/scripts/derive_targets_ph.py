#!/usr/bin/env python3
"""Derive calibration targets from a converted PUF, so they cannot drift.

A hand-written target and a crosswalk can disagree, and `rake_weights` will not
warn you: it divides by the sum of the codes you supply while counting *every*
observed row in the denominator (calibration.py:37-46). Name three of four
urbanicity values and the margin is silently skewed. Deriving the target from
the same crosswalk that produces the data makes that class of bug impossible.

Only valid when the source is representative of the population you are
calibrating to. CPH is a census, so its own distribution *is* the target. LFS /
FIES / NDHS are samples — pass `--weight-col` or the result is a target for the
sample design, not for the Philippines.

    python persona/curation/existing_data/scripts/derive_targets_ph.py \
      --source persona/curation/existing_data/raw/psa_ph/psa_ph.jsonl \
      --dataset persona/curation/existing_data/scripts/crosswalks/psa_ph.py \
      --dims urbanicity,highest_education \
      --targets persona/curation/existing_data/philippines/targets_ph.json --write

Without --write it prints what it would change and touches nothing.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SCHEMA = SCRIPTS_DIR.parent.parent.parent / "schema" / "dimensions.json"


def _load_dataset(path):
    spec = importlib.util.spec_from_file_location("ph_dataset", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec.loader.exec_module(module)
    return module


def _open(path):
    path = Path(path)
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(
        path, encoding="utf-8"
    )


def _weight(row, col):
    if not col:
        return 1.0
    v = row.get(col)
    try:
        w = float(v)
    except (TypeError, ValueError):
        return 0.0
    # NaN and negatives are not usable weights; drop the row rather than let it
    # poison the totals.
    return w if w == w and w > 0 else 0.0


def derive(source, dataset, dims, weight_col=None, limit=None):
    sys.path.insert(0, str(SCRIPTS_DIR))
    from crosswalk_engine import apply_crosswalk, load_allowed

    allowed = load_allowed(str(SCHEMA))
    crosswalk = dataset.CROSSWALK
    unknown = [d for d in dims if d not in crosswalk]
    if unknown:
        raise SystemExit(f"not produced by this crosswalk: {', '.join(unknown)}")

    counts = {d: defaultdict(float) for d in dims}
    observed = dict.fromkeys(dims, 0.0)
    rows = 0
    total_weight = 0.0
    with _open(source) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            w = _weight(raw, weight_col)
            if w <= 0:
                continue
            rows += 1
            total_weight += w
            obs, _prov, _unmapped = apply_crosswalk(
                dataset.flatten(raw), crosswalk, allowed
            )
            for d in dims:
                val = obs.get(d)
                if val is not None:
                    counts[d][val] += w
                    observed[d] += w
            if limit and rows >= limit:
                break

    out = {}
    for d in dims:
        if observed[d] <= 0:
            out[d] = {"shares": {}, "coverage": 0.0, "rows": rows}
            continue
        out[d] = {
            "shares": {k: round(v / observed[d], 5) for k, v in sorted(counts[d].items())},
            # share of the weighted population this margin actually saw; a low
            # number means the target is conditional on being observed
            "coverage": round(observed[d] / total_weight, 5),
            "rows": rows,
        }
    return out, rows, total_weight


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True, help="converted JSONL (.jsonl or .jsonl.gz)")
    ap.add_argument("--dataset", required=True, help="crosswalk .py")
    ap.add_argument("--dims", required=True, help="comma-separated dimensions")
    ap.add_argument("--targets", help="targets json to update")
    ap.add_argument("--weight-col", help="survey weight column (required for sample sources)")
    ap.add_argument("--reference", default="", help="provenance string for the updated entries")
    ap.add_argument("--limit", type=int, help="stop after N rows (smoke test)")
    ap.add_argument("--write", action="store_true", help="apply; otherwise dry-run")
    args = ap.parse_args(argv)

    dims = [d.strip() for d in args.dims.split(",") if d.strip()]
    dataset = _load_dataset(args.dataset)
    derived, rows, total_weight = derive(
        args.source, dataset, dims, args.weight_col, args.limit
    )

    if not args.weight_col:
        print(
            "NOTE: no --weight-col. Correct for a census PUF; wrong for LFS/FIES/NDHS.",
            file=sys.stderr,
        )
    print(f"rows read: {rows:,}   weighted total: {total_weight:,.0f}\n")
    for d, res in derived.items():
        print(f"{d}  (observed on {res['coverage']:.1%} of weight)")
        if not res["shares"]:
            print("   nothing observed — crosswalk never emitted this dimension")
        for k, v in res["shares"].items():
            print(f"   {k:<28} {v:.5f}")
        print()

    if not args.targets:
        return 0
    path = Path(args.targets)
    doc = json.loads(path.read_text())
    changed = []
    for d, res in derived.items():
        if not res["shares"]:
            continue
        entry = doc["dimensions"].setdefault(d, {"weight": 0.5})
        before = entry.get("shares", {})
        entry["shares"] = res["shares"]
        entry["quality"] = "derived"
        entry["reference"] = args.reference or f"derived from {Path(args.source).name}"
        entry["coverage"] = (
            f"Derived from the source itself via {Path(args.dataset).name}, so the "
            f"categories match what the crosswalk emits. Observed on "
            f"{res['coverage']:.1%} of weighted rows; shares are conditional on "
            f"being observed."
        )
        changed.append((d, before, res["shares"]))

    if not changed:
        print("nothing to write")
        return 0
    for d, before, after in changed:
        print(f"{d}: {sorted(before)} -> {sorted(after)}")
    if not args.write:
        print("\ndry run — re-run with --write to apply")
        return 0
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"\n✓ updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
