"""Native persona provenance and independent, paired single-episode plans."""

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import random

import yaml


VERSION = "journey-sidecar-v10"
CONCURRENCY_VALUES = (1, 2, 4, 8)
DOMAINS = ("car", "home")
CONDITIONS = ("C1", "C2", "C3", "C4")


def domain_module(domain, module):
    if domain not in DOMAINS or module not in {
        "cases",
        "native",
        "common",
        "scoring",
        "charging_verification",
    }:
        raise ValueError("Unknown native component")
    return importlib.import_module(f"matraix.journeys.{domain}.{module}")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def native_context(case):
    p = case["native_persona"]
    return {
        "source_persona_id": p["persona_id"],
        "attributes": deepcopy(p["dimensions"]),
        "condition": deepcopy(case["persona"]),
        "precedence": "fixed task facts/consent > assigned current condition > background attributes",
    }


def make_case(domain, task, block=1, condition="C1", boundary=False, seed=20261029):
    from .programmatic import adapt_case

    if (
        domain not in DOMAINS
        or condition not in CONDITIONS
        or task not in {("J" if domain == "car" else "H") + str(i) for i in range(1, 7)}
    ):
        raise ValueError("Unknown task or condition")
    if type(boundary) is not bool or type(block) is not int or block < 1:
        raise ValueError("Explicit boundary and positive block required")
    c = domain_module(domain, "cases").make_case(block, condition, task, boundary, seed)
    c.update(domain=domain, id=f"{domain}--{c['id']}")
    return adapt_case(c)


def code_contract():
    root = Path(__file__).resolve().parent
    paths = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and not any(x in p.parts for x in (".cache", "__pycache__"))
        and p.suffix in {".py", ".json", ".zip"}
    ]
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(
            p.read_bytes().replace(b"\r\n", b"\n")
            if p.suffix != ".zip"
            else p.read_bytes()
        ).hexdigest()
        for p in sorted(paths)
    }


def load_profiles(repo, pool, ids, domain, fixture=False):
    from matraix.persona_consistency import validate_dimensions
    from matraix.persona_generator import load_catalog_values
    from matraix.persona_job import load_manifest

    repo, pool = Path(repo).resolve(), Path(pool).resolve()
    if not pool.is_relative_to(repo) or not ids or len(ids) != len(set(ids)):
        raise ValueError("Select unique IDs in a repository native pool")
    raw_manifest = json.loads((pool / "manifest.json").read_text(encoding="utf-8"))
    if raw_manifest.get("overlay_dimensions") or raw_manifest.get("contrast"):
        raise ValueError("Use original base personas, not contrast copies")
    kind = raw_manifest.get("kind", "")
    if not fixture and not (
        kind == "saved-persona-dataset" or kind.startswith("generated-persona-dev")
    ):
        raise ValueError("A native generated or saved pool is required")
    entries = load_manifest(pool, repo_root=repo)
    catalog = load_catalog_values(repo / "persona/schema/dimensions.json")
    profiles, origins = {}, set()
    for e in entries:
        if e.get("persona_id") not in ids:
            continue
        p = (repo / e["path"]).resolve()
        if not p.is_relative_to(pool):
            raise ValueError("Persona escaped pool")
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        pid, dims = raw.get("persona_id"), raw.get("dimensions")
        if pid in profiles or not pid or not isinstance(dims, dict):
            raise ValueError("Duplicate ID or missing dimensions")
        indexed_dimensions = e.get("dimensions") or {}
        if (
            any(raw.get(k) != e.get(k) for k in ("persona_id", "source"))
            or not isinstance(indexed_dimensions, dict)
            or any(dims.get(k) != v for k, v in indexed_dimensions.items())
        ):
            raise ValueError("Manifest/YAML disagreement")
        if (
            raw.get("contrast_from")
            or not raw.get("source")
            or raw.get("fixture_only")
            and not fixture
        ):
            raise ValueError("Not a supported real source persona")
        if (
            not dims
            or any(k not in catalog or v not in catalog[k] for k, v in dims.items())
            or validate_dimensions(dims)
        ):
            raise ValueError("Invalid native persona dimensions")
        origin = raw.get("provenance", {}).get("origin_persona_id", pid)
        if origin in origins:
            raise ValueError("Duplicate original persona")
        origins.add(origin)
        profiles[pid] = {
            **deepcopy(raw),
            "source_yaml": p.relative_to(repo).as_posix(),
            "source_yaml_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
    selected = []
    for pid in ids:
        if pid not in profiles:
            raise ValueError("Unknown source ID")
        p = profiles[pid]
        d = p["dimensions"]
        if not fixture:
            if (
                d.get("age_bracket")
                not in {
                    "18-24",
                    "25-34",
                    "35-44",
                    "45-54",
                    "55-64",
                    "65-74",
                    "75-84",
                    "85+",
                }
                or d.get("primary_language") != "Mandarin"
            ):
                raise ValueError(
                    "Documented adult Mandarin-speaking eligibility required"
                )
            if domain == "car" and d.get("demo_driver_status") not in {
                "Daily driver",
                "Occasional driver",
                "Licensed, rarely drives",
            }:
                raise ValueError("Documented driving status required")
        selected.append(p)
    return selected


def prepare(
    repo,
    pools,
    selections,
    out,
    purpose="pilot",
    fixture=False,
    seed=20261029,
    validation_cases=None,
):
    out = Path(out)
    if out.exists() or set(pools) != set(DOMAINS) or set(selections) != set(DOMAINS):
        raise ValueError("New output and both domain selections required")
    if (
        purpose not in {"pilot", "formal", "offline", "validation"}
        or fixture
        and purpose not in {"offline", "validation"}
    ):
        raise ValueError("Fixtures are offline only")
    cases, sources = [], {}
    for domain in DOMAINS:
        profiles = load_profiles(
            repo, pools[domain], selections[domain], domain, fixture
        )
        sources[domain] = {
            "pool": "inputs/" + domain,
            "manifest_sha256": hashlib.sha256(
                (Path(pools[domain]) / "manifest.json").read_bytes()
            ).hexdigest(),
        }
        for block, profile in enumerate(profiles, 1):
            for condition in CONDITIONS:
                for i in range(1, 7):
                    for edge in (False, True):
                        c = make_case(
                            domain,
                            ("J" if domain == "car" else "H") + str(i),
                            block,
                            condition,
                            edge,
                            seed,
                        )
                        c["native_persona"] = deepcopy(profile)
                        c["source_persona_id"] = profile["persona_id"]
                        c["persona_binding"] = digest(
                            {
                                "domain": domain,
                                "profile": profile,
                                "condition": condition,
                            }
                        )
                        cases.append(c)
    if validation_cases is not None:
        if purpose != "validation" or not fixture:
            raise ValueError(
                "Subsetting is only permitted for explicit integration validation"
            )
        cases = [
            c
            for c in cases
            if (c["domain"], c["task"], c["cohort"], c["boundary"]) in validation_cases
        ]
        if len(cases) != len(validation_cases):
            raise ValueError("Validation scenario selection mismatch")
    random.Random(seed).shuffle(cases)
    from .identity import runtime_contract

    catalog = Path(repo) / "persona/schema/dimensions.json"
    plan = {
        "protocol": VERSION,
        "purpose": purpose,
        "fixture_only": fixture,
        "seed": seed,
        "cases": cases,
        "sources": sources,
        "code_contract": code_contract(),
        "planned_episodes": len(cases),
        "sut": "fixed baseline only",
        "formal_spec_frozen": False,
        "execution_authorized": False,
        "identity_contract": runtime_contract(catalog),
    }
    (out / "identity").mkdir(parents=True, exist_ok=False)
    (out / "identity/dimensions.json").write_bytes(catalog.read_bytes())
    for domain in DOMAINS:
        dest = out / "inputs" / domain
        dest.mkdir(parents=True, exist_ok=False)
        (dest / "manifest.json").write_bytes(
            (Path(pools[domain]) / "manifest.json").read_bytes()
        )
        for profile in {
            c["source_persona_id"]: c["native_persona"]
            for c in cases
            if c["domain"] == domain
        }.values():
            source = (Path(repo) / profile["source_yaml"]).resolve()
            (dest / source.name).write_bytes(source.read_bytes())
    write_new(out / "plan.json", plan)
    write_new(out / "manifest.json", {"plan_sha256": digest(plan), "protocol": VERSION})
    return plan


def load_plan(path):
    path = Path(path)
    p = json.loads((path / "plan.json").read_text(encoding="utf-8"))
    m = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if (
        p.get("protocol") != VERSION
        or digest(p) != m.get("plan_sha256")
        or p["code_contract"] != code_contract()
    ):
        raise ValueError("Plan/source contract changed")
    for ref in p["sources"].values():
        source_root = (path / ref["pool"]).resolve()
        if not source_root.is_relative_to(path.resolve()):
            raise ValueError("Source pool escaped plan")
        if (
            hashlib.sha256((source_root / "manifest.json").read_bytes()).hexdigest()
            != ref["manifest_sha256"]
        ):
            raise ValueError("Source pool changed")
    originals = {}
    for c in p["cases"]:
        profile = c["native_persona"]
        source = (
            path / p["sources"][c["domain"]]["pool"] / Path(profile["source_yaml"]).name
        )
        source_bytes = source.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        if source_hash != profile["source_yaml_sha256"]:
            raise ValueError("Source YAML changed")
        if source_hash not in originals:
            originals[source_hash] = yaml.safe_load(source_bytes.decode("utf-8"))
        original = originals[source_hash]
        if any(profile.get(k) != v for k, v in original.items()):
            raise ValueError("Plan profile differs from the hashed original YAML")
    if p.get("identity_contract"):
        catalog = path / "identity/dimensions.json"
        if (
            hashlib.sha256(catalog.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            != p["identity_contract"]["files"]["dimensions.json"]
        ):
            raise ValueError("Bound identity schema changed")
    from .design import validate_matrix

    validate_matrix(p)
    if p["purpose"] == "formal" and p["formal_spec_frozen"]:
        from .design import validate_frozen

        validate_frozen(p)
    return p
